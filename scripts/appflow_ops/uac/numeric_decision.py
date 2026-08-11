"""Deterministic bid, budget, and split recommendations for UAC Quick Ops.

The implementation is split into numeric_common (shared helpers and policy
gates), numeric_safety (change caps, staged plans, operational corrections),
numeric_targets (target recommendations), and numeric_budgets (budget
recommendations); this module keeps the public entry point and orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import _mapping, _number
from .numeric_budgets import _budget_recommendation
from .numeric_common import (
    EMERGENCY_INTERVENTION,
    NORMAL_OPTIMIZATION,
    NUMERIC_DECISION_SCHEMA_VERSION,
    OPERATIONAL_CORRECTION,
    STAGED_OPTIMIZATION,
    _OPERATION_CLASSIFICATIONS,
)
from .numeric_safety import _apply_numeric_safety
from .numeric_targets import _target_recommendation
from .policy_loader import LoadedPolicy, load_policy
from .signals import _numeric_context, derive_signals
from .types import ContractError


def _primary_constraint(signals: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    maturity = _mapping(signals.get("maturity")).get("state")
    target = _mapping(signals.get("target_constraint")).get("state")
    budget = _mapping(signals.get("budget_delivery")).get("state")
    events = _mapping(signals.get("event_volume")).get("state")
    current_budget = _number(context.get("current_daily_budget"))
    daily_budget_cap = _number(context.get("daily_budget_cap"))
    if (
        current_budget is not None
        and daily_budget_cap is not None
        and current_budget > daily_budget_cap
    ):
        return "BUSINESS_BUDGET_CAP"
    target_cpa = _number(context.get("target_cpa"))
    maximum_cpa = _number(context.get("maximum_acceptable_cpa"))
    target_roas = _number(context.get("target_roas"))
    minimum_roas = _number(context.get("minimum_acceptable_roas"))
    if target_roas is not None:
        target_boundary_violated = (
            minimum_roas is not None and target_roas < minimum_roas
        )
    else:
        target_boundary_violated = (
            target_cpa is not None
            and maximum_cpa is not None
            and target_cpa > maximum_cpa
        )
    if target_boundary_violated:
        return "BUSINESS_TARGET_BOUNDARY"
    if maturity != "MATURE":
        return "DATA_MATURITY"
    if target in {"TARGET_LIKELY_TOO_TIGHT", "TARGET_LIKELY_TOO_LOOSE"}:
        return str(target)
    if budget == "BUDGET_CONSTRAINED":
        return "BUDGET_CONSTRAINED"
    if events == "INSUFFICIENT":
        return "INSUFFICIENT_EVENT_VOLUME"
    return "NO_NUMERIC_CHANGE_EVIDENCED"


def _permission_class(case: Mapping[str, Any], variable: str) -> str:
    permissions = _mapping(case.get("permissions"))
    if variable in permissions.get("optimizer_can", []):
        return "OPTIMIZER_CAN_EXECUTE"
    if variable in permissions.get("client_approval_required", []):
        return "CLIENT_APPROVAL_REQUIRED"
    if variable in permissions.get("client_data_required", []):
        return "CLIENT_DATA_REQUIRED"
    if variable in permissions.get("platform_limitations", []):
        return "PLATFORM_LIMITATION"
    if variable in permissions.get("unavailable", []):
        return "NOT_ACTIONABLE"
    return "NOT_ACTIONABLE"


def _apply_permission(
    recommendation: dict[str, Any], case: Mapping[str, Any], variable: str
) -> None:
    permission = _permission_class(case, variable)
    changes = recommendation.get("recommended_value") is not None and (
        recommendation.get("recommended_action") not in {"NO_CHANGE", "WAIT"}
    )
    executable = bool(changes and permission == "OPTIMIZER_CAN_EXECUTE")
    if not changes or executable:
        request = None
    elif permission == "CLIENT_APPROVAL_REQUIRED":
        request = f"request client approval for {variable} recommendation"
    elif permission == "CLIENT_DATA_REQUIRED":
        request = f"request client data before {variable} recommendation"
    elif permission == "PLATFORM_LIMITATION":
        request = (
            f"keep {variable} as a future recommendation; platform access is blocked"
        )
    else:
        request = f"ask an authorized operator to apply the {variable} recommendation"
    recommendation["executable_now"] = executable
    recommendation["permission"] = permission
    recommendation["client_request"] = request
    safety = recommendation.get("numeric_safety")
    if isinstance(safety, dict):
        if changes and not executable:
            current_key = (
                "current_daily_budget" if variable == "budget" else "current_value"
            )
            safety["final_recommendation"] = recommendation.get(current_key)
            safety["limit_reasons"] = list(
                dict.fromkeys([*safety.get("limit_reasons", []), "permission_boundary"])
            )
        elif changes:
            safety["final_recommendation"] = recommendation.get("recommended_value")


def _campaign_level_guidance(
    case: Mapping[str, Any], primary_constraint: str, split: Mapping[str, Any]
) -> dict[str, Any]:
    facts = _mapping(case.get("facts"))
    plan = _mapping(facts.get("split_plan"))
    quick = _mapping(case.get("quick_ops"))
    current_campaign = _mapping(quick.get("current_campaign"))
    current = facts.get("campaign_level") or current_campaign.get("level")
    candidate = plan.get("candidate_level")
    permission = _permission_class(case, "campaign_create")
    if primary_constraint in {
        "TARGET_LIKELY_TOO_TIGHT",
        "TARGET_LIKELY_TOO_LOOSE",
        "BUSINESS_BUDGET_CAP",
        "BUSINESS_TARGET_BOUNDARY",
        "DATA_MATURITY",
        "INSUFFICIENT_EVENT_VOLUME",
    }:
        immediate = "KEEP_CURRENT"
        recommended = current
    elif split.get("state") == "SPLIT_FEASIBLE" and permission == (
        "OPTIMIZER_CAN_EXECUTE"
    ):
        immediate = "TEST_IN_PARALLEL"
        recommended = candidate or current
    else:
        immediate = "KEEP_CURRENT"
        recommended = current
    return {
        "current_level": current,
        "recommended_level": recommended,
        "immediate_action": immediate,
        "future_candidate": candidate,
        "executable_now": bool(
            immediate == "TEST_IN_PARALLEL" and permission == "OPTIMIZER_CAN_EXECUTE"
        ),
        "permission": permission,
    }


def _operation_classification(
    case: Mapping[str, Any],
    target: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> str:
    operational = _mapping(_mapping(case.get("quick_ops")).get("operational"))
    simultaneous = operational.get("simultaneous_changes", [])
    emergency_changes = (
        {str(item) for item in simultaneous}
        if isinstance(simultaneous, list)
        else set()
    )
    if operational.get("urgent_confirmed") is True and len(emergency_changes) > 1:
        return EMERGENCY_INTERVENTION
    recommendation_classes = {
        _mapping(section.get("numeric_safety")).get("operation_classification")
        for section in (target, budget)
    }
    if OPERATIONAL_CORRECTION in recommendation_classes:
        return OPERATIONAL_CORRECTION
    if STAGED_OPTIMIZATION in recommendation_classes:
        return STAGED_OPTIMIZATION
    return NORMAL_OPTIMIZATION


def _validate_operation_input(case: Mapping[str, Any]) -> None:
    operational = _mapping(_mapping(case.get("quick_ops")).get("operational"))
    requested = operational.get("operation_classification")
    if requested is not None and requested not in _OPERATION_CLASSIFICATIONS:
        allowed = ", ".join(sorted(_OPERATION_CLASSIFICATIONS))
        raise ContractError(
            f"quick_ops.operational.operation_classification must be one of {allowed}"
        )
    if requested == OPERATIONAL_CORRECTION and str(
        operational.get("affected_variable", "")
    ) not in {"target", "bid", "target_cpa", "target_roas", "daily_budget", "budget"}:
        raise ContractError(
            "OPERATIONAL_CORRECTION requires affected_variable target or daily_budget"
        )


def recommend_numeric(
    case: Mapping[str, Any],
    signals: Mapping[str, Any] | None = None,
    *,
    numeric_policy: LoadedPolicy | None = None,
    signal_policy: LoadedPolicy | None = None,
) -> dict[str, Any]:
    """Return bounded target, budget, and split recommendations from facts."""

    if not isinstance(case, Mapping):
        raise ContractError("UAC input must be an object")
    _validate_operation_input(case)
    loaded_numeric_policy = numeric_policy or load_policy("numeric")
    loaded_signal_policy = signal_policy or load_policy("signal")
    derived = (
        dict(signals)
        if signals is not None
        else derive_signals(case, policy=loaded_signal_policy)
    )
    context = _numeric_context(case, loaded_signal_policy)
    target = _target_recommendation(case, derived, context, loaded_signal_policy)
    budget = _budget_recommendation(
        case, derived, context, target, loaded_signal_policy
    )
    _apply_numeric_safety(
        target,
        variable=(
            "target_roas" if target.get("target_type") == "tROAS" else "target_cpa"
        ),
        current_field="current_value",
        target_type=str(target.get("target_type")),
        context=context,
        case=case,
        policy=loaded_numeric_policy,
    )
    _apply_numeric_safety(
        budget,
        variable="daily_budget",
        current_field="current_daily_budget",
        target_type=None,
        context=context,
        case=case,
        policy=loaded_numeric_policy,
    )
    _apply_permission(target, case, "bid")
    _apply_permission(budget, case, "budget")
    supplied = _mapping(_mapping(case.get("quick_ops")).get("bid_budget"))
    ignored_hints = []
    for name in ("recommended_target", "recommended_daily_budget"):
        if supplied.get(name) is not None:
            ignored_hints.append(name)
    evidence = list(derived.get("calculation_evidence", []))
    evidence.extend(target.get("calculation_evidence", []))
    evidence.extend(budget.get("calculation_evidence", []))
    heuristics = list(derived.get("heuristics_used", []))
    heuristics.extend(
        [
            "candidate_values_are_bounded_by_account_specific_business_limits",
            "only_one_ordinary_numeric_variable_may_change_at_a_time",
        ]
    )
    if ignored_hints:
        heuristics.append(
            "legacy_recommended_values_are_untrusted_hints_and_do_not_bypass_gates"
        )
    primary_constraint = _primary_constraint(derived, context)
    missing_markers = (
        "missing",
        "insufficient",
        "unreliable",
        "not_supplied",
        "not_reliable",
        "incomplete",
        "no_safe_intersection",
        "violates_business_boundary",
        "degraded",
        "mismatch",
    )
    data_gaps = [
        str(reason)
        for reason in (target.get("reason"), budget.get("reason"))
        if isinstance(reason, str)
        and any(marker in reason for marker in missing_markers)
    ]
    split = dict(_mapping(derived.get("split_feasibility")))
    operation_classification = _operation_classification(case, target, budget)
    emergency = operation_classification == EMERGENCY_INTERVENTION
    return {
        "schema_version": NUMERIC_DECISION_SCHEMA_VERSION,
        "constraint_analysis": {
            "has_numeric_evidence": derived.get("has_numeric_evidence") is True,
            "primary_constraint": primary_constraint,
            "budget_state": _mapping(derived.get("budget_delivery")).get("state"),
            "maturity_state": _mapping(derived.get("maturity")).get("state"),
            "target_state": _mapping(derived.get("target_constraint")).get("state"),
            "event_volume_state": _mapping(derived.get("event_volume")).get("state"),
            "value_signal_state": _mapping(derived.get("value_signal")).get("state"),
        },
        "target_recommendation": target,
        "budget_recommendation": budget,
        "split_feasibility": split,
        "campaign_level_guidance": _campaign_level_guidance(
            case, primary_constraint, split
        ),
        "calculation_evidence": evidence,
        "heuristics_used": list(dict.fromkeys(heuristics)),
        "policy": {
            "numeric": loaded_numeric_policy.as_record(),
            "signal": loaded_signal_policy.as_record(),
        },
        "legacy_hints_ignored": ignored_hints,
        "data_gaps": list(dict.fromkeys(data_gaps)),
        "classification": {
            "type": "OPERATIONAL_DECISION",
            "operation_classification": operation_classification,
            "experiment_validity": (
                "NOT_A_VALID_EXPERIMENT" if emergency else "NOT_AN_EXPERIMENT"
            ),
            "attribution": (
                "ATTRIBUTION_WILL_BE_CONFOUNDED" if emergency else "NOT_APPLICABLE"
            ),
        },
        "account_write": False,
        "ledger_write": False,
    }


__all__ = ["NUMERIC_DECISION_SCHEMA_VERSION", "recommend_numeric"]
