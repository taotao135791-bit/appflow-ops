"""Read-only Campaign Level Quick Ops decision layer for Google App campaigns.

The implementation is split into quick_ops_base (constants, validation,
permissions), quick_ops_gates (readiness gates), quick_ops_level (level and
structure decisions), and quick_ops_actions (creative, bid/budget, review, and
rollback decisions); this module keeps the public entry points and the output
contract validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from typing import Any, cast

from ._common import _finite_number, _mapping
from .engine import analyze_case
from .numeric_decision import recommend_numeric
from .policy_loader import LoadedPolicy, load_policy_set
from .quick_ops_actions import (
    _bid_budget_decisions,
    _creative_decision,
    _operational_classification,
    _review_condition,
    _rollback_condition,
    _summary,
)
from .quick_ops_base import (
    CAMPAIGN_VERDICTS,
    CREATIVE_ACTIONS,
    QUICK_DECISION_SCHEMA_VERSION,
    STRUCTURE_ACTIONS,
    _level,
    _non_negative_or_none,
    _unique,
    _validate_quick_input,
)
from .quick_ops_level import _level_decision
from .routing import route_question
from .signals import apply_derived_signals, derive_signals
from .terminology import (
    CAMPAIGN_LEVELS,
    extract_campaign_levels,
    normalize_glossary,
    resolve_campaign_level,
)
from .types import (
    BUDGET_DELIVERY_STATES,
    CALCULATION_EVIDENCE_TYPES,
    EVENT_VOLUME_STATES,
    MATURITY_STATES,
    SPLIT_FEASIBILITY_STATES,
    TARGET_CONSTRAINT_STATES,
    VALUE_SIGNAL_STATES,
    ContractError,
)


def validate_quick_decision(result: Mapping[str, Any]) -> None:
    errors: list[str] = []
    if result.get("schema_version") != QUICK_DECISION_SCHEMA_VERSION:
        errors.append("schema_version must be 1.0")
    if result.get("mode") != "quick_decision":
        errors.append("mode must be quick_decision")
    decision = _mapping(result.get("decision"))
    if decision.get("verdict") not in CAMPAIGN_VERDICTS:
        errors.append("decision.verdict is invalid")
    if decision.get("confidence") not in {"low", "medium", "high"}:
        errors.append("decision.confidence is invalid")
    if not isinstance(decision.get("summary"), str) or not decision.get("summary"):
        errors.append("decision.summary is required")
    if decision.get("primary_action_count") != 1:
        errors.append("decision.primary_action_count must be 1")
    level = _mapping(result.get("campaign_level_decision"))
    for field in ("current", "recommended", "next_candidate"):
        value = level.get(field)
        if value is not None and value not in CAMPAIGN_LEVELS:
            errors.append(f"campaign_level_decision.{field} is invalid")
    structure = _mapping(result.get("campaign_structure_decision"))
    if structure.get("action") not in STRUCTURE_ACTIONS:
        errors.append("campaign_structure_decision.action is invalid")
    for field in ("create_new_campaign", "run_in_parallel"):
        if not isinstance(structure.get(field), bool):
            errors.append(f"campaign_structure_decision.{field} must be boolean")
    if structure.get("campaign_id") is not None and not isinstance(
        structure.get("campaign_id"), str
    ):
        errors.append("campaign_structure_decision.campaign_id must be text or null")
    creative = _mapping(result.get("creative_decision"))
    if creative.get("action") not in CREATIVE_ACTIONS:
        errors.append("creative_decision.action is invalid")
    for section_name in ("bid_decision", "budget_decision"):
        section = _mapping(result.get(section_name))
        for name, value in section.items():
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(f"{section_name}.{name} must be finite")
    constraint = _mapping(result.get("constraint_analysis"))
    constraint_enums = {
        "budget_state": BUDGET_DELIVERY_STATES,
        "maturity_state": MATURITY_STATES,
        "target_state": TARGET_CONSTRAINT_STATES,
        "event_volume_state": EVENT_VOLUME_STATES,
        "value_signal_state": VALUE_SIGNAL_STATES,
    }
    for field, allowed in constraint_enums.items():
        if constraint.get(field) not in allowed:
            errors.append(f"constraint_analysis.{field} is invalid")
    if not isinstance(constraint.get("has_numeric_evidence"), bool):
        errors.append("constraint_analysis.has_numeric_evidence must be boolean")
    numeric_actions = {"INCREASE", "DECREASE", "NO_CHANGE", "WAIT", "ROLLBACK"}
    recommendation_specs = {
        "target_recommendation": (
            "current_value",
            "conservative_value",
            "recommended_value",
            "aggressive_value",
            "rollback_value",
        ),
        "budget_recommendation": (
            "current_daily_budget",
            "conservative_value",
            "recommended_value",
            "aggressive_value",
            "rollback_value",
        ),
    }
    executable_count = 0
    for section_name, numeric_fields in recommendation_specs.items():
        recommendation = _mapping(result.get(section_name))
        if recommendation.get("recommended_action") not in numeric_actions:
            errors.append(f"{section_name}.recommended_action is invalid")
        for field in numeric_fields:
            if not _non_negative_or_none(recommendation.get(field)):
                errors.append(f"{section_name}.{field} must be finite and non-negative")
        current_field = (
            "current_value"
            if section_name == "target_recommendation"
            else "current_daily_budget"
        )
        ordered_values = [
            recommendation.get(current_field),
            recommendation.get("conservative_value"),
            recommendation.get("recommended_value"),
            recommendation.get("aggressive_value"),
        ]
        if all(_finite_number(value) for value in ordered_values):
            numeric_values = [
                float(cast(int | float, value)) for value in ordered_values
            ]
            if recommendation.get("recommended_action") == "INCREASE" and any(
                left > right for left, right in zip(numeric_values, numeric_values[1:])
            ):
                errors.append(f"{section_name} increase candidates must be ordered")
            if recommendation.get("recommended_action") == "DECREASE" and any(
                left < right for left, right in zip(numeric_values, numeric_values[1:])
            ):
                errors.append(f"{section_name} decrease candidates must be ordered")
        if (
            recommendation.get("recommended_action")
            in {
                "INCREASE",
                "DECREASE",
                "ROLLBACK",
            }
            and recommendation.get("recommended_value") is None
        ):
            errors.append(f"{section_name}.recommended_value is required for a change")
        if recommendation.get("change_percent") is not None and not _finite_number(
            recommendation.get("change_percent")
        ):
            errors.append(f"{section_name}.change_percent must be finite or null")
        execution = _mapping(recommendation.get("execution"))
        if execution.get("executable_now") is True:
            executable_count += 1
        safety = recommendation.get("numeric_safety")
        if safety is not None:
            safety_map = _mapping(safety)
            operation_classification = safety_map.get("operation_classification")
            if operation_classification not in {
                "NORMAL_OPTIMIZATION",
                "STAGED_OPTIMIZATION",
                "OPERATIONAL_CORRECTION",
                "EMERGENCY_INTERVENTION",
            }:
                errors.append(
                    f"{section_name}.numeric_safety.operation_classification is invalid"
                )
            if not isinstance(safety_map.get("policy_version"), str) or not str(
                safety_map.get("policy_version")
            ):
                errors.append(
                    f"{section_name}.numeric_safety.policy_version is required"
                )
            applied_limit = safety_map.get("applied_change_limit_percent")
            change_percent = recommendation.get("change_percent")
            if (
                operation_classification
                in {"NORMAL_OPTIMIZATION", "STAGED_OPTIMIZATION"}
                and recommendation.get("recommended_action") in {"INCREASE", "DECREASE"}
                and _finite_number(applied_limit)
                and _finite_number(change_percent)
                and abs(float(cast(int | float, change_percent)))
                > float(cast(int | float, applied_limit)) + 0.01
            ):
                errors.append(
                    f"{section_name} exceeds its normal single-change policy cap"
                )
            staged_required = safety_map.get("staged_adjustment_required") is True
            staged_plan = safety_map.get("staged_plan")
            if staged_required:
                plan = _mapping(staged_plan)
                stages = plan.get("stages")
                if not isinstance(stages, list) or len(stages) < 2:
                    errors.append(
                        f"{section_name}.numeric_safety staged plan needs multiple stages"
                    )
                elif (
                    not isinstance(stages[0], Mapping)
                    or stages[0].get("immediate") is not True
                    or stages[0].get("target")
                    != recommendation.get("recommended_value")
                    or any(
                        not isinstance(stage, Mapping)
                        or stage.get("automatic_execution") is not False
                        or (index > 0 and stage.get("immediate") is not False)
                        for index, stage in enumerate(stages)
                    )
                ):
                    errors.append(
                        f"{section_name}.numeric_safety only stage 1 may be immediate"
                    )
            elif staged_plan is not None:
                errors.append(
                    f"{section_name}.numeric_safety staged_plan must be null when not staged"
                )
    if executable_count > 1:
        errors.append("only one numeric recommendation may be executable now")
    classification = _mapping(result.get("classification"))
    operation_classification = classification.get("operation_classification")
    if operation_classification is not None and operation_classification not in {
        "NORMAL_OPTIMIZATION",
        "STAGED_OPTIMIZATION",
        "OPERATIONAL_CORRECTION",
        "EMERGENCY_INTERVENTION",
    }:
        errors.append("classification.operation_classification is invalid")
    if operation_classification == "EMERGENCY_INTERVENTION" and (
        classification.get("experiment_validity") != "NOT_A_VALID_EXPERIMENT"
        or classification.get("attribution") != "ATTRIBUTION_WILL_BE_CONFOUNDED"
    ):
        errors.append("emergency intervention must be non-experimental and confounded")
    split = _mapping(result.get("split_feasibility"))
    if split.get("state") not in SPLIT_FEASIBILITY_STATES:
        errors.append("split_feasibility.state is invalid")
    evidence = result.get("calculation_evidence")
    if not isinstance(evidence, list):
        errors.append("calculation_evidence must be a list")
    else:
        for index, item in enumerate(evidence):
            if (
                not isinstance(item, Mapping)
                or item.get("type") not in CALCULATION_EVIDENCE_TYPES
            ):
                errors.append(f"calculation_evidence[{index}].type is invalid")
    heuristics = result.get("heuristics_used")
    if not isinstance(heuristics, list) or not all(
        isinstance(item, str) and item for item in heuristics
    ):
        errors.append("heuristics_used must be a list of non-empty strings")
    legacy_hints = result.get("legacy_hints_ignored")
    if not isinstance(legacy_hints, list) or not all(
        item in {"recommended_target", "recommended_daily_budget"}
        for item in legacy_hints
    ):
        errors.append("legacy_hints_ignored is invalid")
    if result.get("account_write") is not False:
        errors.append("account_write must be false")
    if result.get("ledger_write") is not False:
        errors.append("ledger_write must be false")
    if result.get("experiments") != []:
        errors.append("Quick Decision must not create experiments")
    if result.get("human_confirmation_required_for_live_write") is not True:
        errors.append("human_confirmation_required_for_live_write must be true")
    if not isinstance(result.get("reason_codes"), list) or not result.get(
        "reason_codes"
    ):
        errors.append("reason_codes must be non-empty")
    if not isinstance(result.get("review_condition"), Mapping):
        errors.append("review_condition is required")
    if not isinstance(result.get("rollback"), Mapping):
        errors.append("rollback is required")
    upgrade = _mapping(result.get("upgrade_condition"))
    if (
        upgrade.get("target_level") is not None
        and upgrade.get("target_level") not in CAMPAIGN_LEVELS
    ):
        errors.append("upgrade_condition.target_level is invalid")
    if not isinstance(upgrade.get("requirements"), list):
        errors.append("upgrade_condition.requirements must be a list")
    permission = _mapping(result.get("permission_check"))
    for field in (
        "allowed",
        "requires_client_approval",
        "requires_exact_live_edit_confirmation",
    ):
        if not isinstance(permission.get(field), bool):
            errors.append(f"permission_check.{field} must be boolean")
    if not isinstance(permission.get("client_requests"), list):
        errors.append("permission_check.client_requests must be a list")
    if errors:
        raise ContractError("invalid Quick Decision: " + "; ".join(errors))


def decide_case(
    case: dict[str, Any],
    ledger: dict[str, Any] | None = None,
    *,
    question: str | None = None,
    project_glossary: Mapping[str, Any] | None = None,
    policies: Mapping[str, LoadedPolicy] | None = None,
) -> dict[str, Any]:
    """Return one deterministic, read-only operation card from supplied facts."""

    _validate_quick_input(case)
    loaded_policies = dict(policies) if policies is not None else load_policy_set()
    numeric_policy = loaded_policies.get("uac_numeric")
    signal_policy = loaded_policies.get("uac_signal")
    if not isinstance(numeric_policy, LoadedPolicy) or not isinstance(
        signal_policy, LoadedPolicy
    ):
        raise ContractError("Quick Decision requires numeric and signal policies")
    analysis = analyze_case(case, ledger)
    derived_signals = derive_signals(case, policy=signal_policy)
    numeric = recommend_numeric(
        case,
        derived_signals,
        numeric_policy=numeric_policy,
        signal_policy=signal_policy,
    )
    decision_case = apply_derived_signals(case, derived_signals)
    quick = _mapping(decision_case.get("quick_ops"))
    prompt = question if question is not None else str(quick.get("question", ""))
    route = route_question(prompt)
    current_campaign = _mapping(quick.get("current_campaign"))
    candidate_campaign = _mapping(quick.get("candidate_campaign"))
    current = _level(current_campaign.get("level"))
    mentioned = extract_campaign_levels(prompt)
    candidate = _level(candidate_campaign.get("level")) or _level(
        quick.get("candidate_level")
    )
    if candidate is None:
        candidate = next((item for item in mentioned if item != current), None)
    if candidate is None and len(mentioned) == 1 and mentioned[0] != current:
        candidate = mentioned[0]
    switching = candidate is not None and current is not None and candidate != current

    merged_glossary = normalize_glossary(
        _mapping(decision_case.get("campaign_level_glossary"))
    )
    merged_glossary.update(normalize_glossary(project_glossary))
    target_term: Any = quick.get("user_term") or candidate or current
    terminology = resolve_campaign_level(
        target_term,
        glossary=merged_glossary,
        account=candidate_campaign if candidate is not None else current_campaign,
        mapping_confirmed=quick.get("terminology_mapping_confirmed") is True,
        switching=switching,
    )
    current_resolution = resolve_campaign_level(
        current,
        glossary=merged_glossary,
        account=current_campaign,
        mapping_confirmed=quick.get("terminology_mapping_confirmed") is True,
        switching=False,
    )
    terminology = {**terminology, "current_resolution": current_resolution}

    requested_question_type = str(quick.get("question_type") or route["question_type"])
    level_decision: dict[str, Any]
    if route["mode"] != "quick_decision":
        level_decision = {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "recommended": current,
            "action": "keep",
            "structure": {
                "action": "WAIT",
                "create_new_campaign": False,
                "run_in_parallel": False,
                "permission": "NOT_ACTIONABLE",
                "reason_codes": ["request_routes_to_different_mode"],
                "data_gaps": [],
                "client_requests": [],
            },
            "reason_codes": ["request_routes_to_different_mode"],
            "data_gaps": [f"use {route['mode']} mode for this request"],
            "client_requests": [],
        }
    else:
        level_decision = _level_decision(
            decision_case,
            quick,
            analysis,
            current,
            candidate,
            terminology,
            requested_question_type,
            numeric,
        )

    structure = _mapping(level_decision["structure"])
    creative = _creative_decision(
        decision_case,
        quick,
        str(structure.get("action", "WAIT")),
        requested_question_type,
    )
    (
        bid,
        budget,
        bid_budget_reasons,
        bid_budget_requests,
        target_recommendation,
        budget_recommendation,
    ) = _bid_budget_decisions(
        decision_case,
        numeric,
        str(level_decision["action"]),
        execution_block_reason=(
            "numeric_change_blocked_by_unfinished_experiment"
            if "unfinished_experiment_blocks_stacked_change"
            in level_decision["reason_codes"]
            else None
        ),
    )
    classification = _operational_classification(quick, analysis, numeric)
    review, review_gaps = _review_condition(quick)
    rollback, rollback_gaps = _rollback_condition(
        quick, str(level_decision["action"]), structure
    )
    if classification.get("operation_classification") == "OPERATIONAL_CORRECTION":
        operational = _mapping(quick.get("operational"))
        rollback_target = operational.get("rollback_target")
        rollback = {
            "applicable": True,
            "condition": "live configuration deviates again from the confirmed approved value",
            "action": "restore the affected variable to the confirmed rollback target",
            "baseline_level": _level(
                _mapping(quick.get("current_campaign")).get("level")
            ),
            "affected_variable": operational.get("affected_variable"),
            "rollback_target": rollback_target,
            "source": "confirmed_operational_correction",
        }
        rollback_gaps = []

    reason_codes = _unique(
        [
            *level_decision["reason_codes"],
            *structure.get("reason_codes", []),
            *creative["reason_codes"],
            *bid_budget_reasons,
        ]
    )
    if derived_signals.get("has_numeric_evidence") is True:
        target_reason = str(target_recommendation.get("reason", ""))
        budget_reason = str(budget_recommendation.get("reason", ""))
        reason_codes.extend(
            item
            for item in (
                f"numeric_target_{target_reason}" if target_reason else "",
                f"numeric_budget_{budget_reason}" if budget_reason else "",
            )
            if item
        )
    data_gaps = _unique(
        [
            *level_decision["data_gaps"],
            *structure.get("data_gaps", []),
            *creative["data_gaps"],
            *review_gaps,
            *rollback_gaps,
        ]
    )
    if derived_signals.get("has_numeric_evidence") is True:
        gap_reasons = {
            "business_cpa_ceiling_missing",
            "business_roas_floor_missing",
            "business_daily_budget_cap_missing",
            "current_target_missing",
            "current_daily_budget_missing",
            "mature_actual_cpa_missing",
            "mature_actual_roas_missing",
            "insufficient_mature_conversion_data",
            "value_signal_not_reliable_enough_for_troas",
            "measurement_reconciliation_unreliable",
            "duplicate_conversion_events",
            "value_or_currency_not_verified",
            "payment_trial_or_refund_definition_unreliable",
            "subscription_renewal_value_not_included",
            "numeric_value_measurement_unreliable",
            "operational_correction_evidence_incomplete",
            "historical_correction_value_violates_business_boundary",
            "business_boundary_and_change_limit_have_no_safe_intersection",
            "numeric_policy_degraded_to_zero_change_cap",
            "numeric_policy_zero_change_cap",
            "numeric_change_cap_below_minimum_safe_increment",
            "operational_correction_target_type_mismatch",
        }
        data_gaps.extend(
            reason
            for reason in (
                target_recommendation.get("reason"),
                budget_recommendation.get("reason"),
            )
            if reason in gap_reasons
        )
    client_requests = _unique(
        [
            *level_decision["client_requests"],
            *structure.get("client_requests", []),
            *creative["client_requests"],
            *bid_budget_requests,
        ]
    )
    if quick.get("permission_profile") == "mmp_access_without_backend_access":
        data_gaps.append("backend value reconciliation")
        reason_codes.append("mmp_without_backend_evidence")
    if quick.get("permission_profile") == "aggregate_data_only":
        data_gaps.append("campaign and asset-level segmented evidence")
        reason_codes.append("aggregate_data_cannot_support_action")
    reason_codes = _unique(reason_codes)
    data_gaps = _unique(data_gaps)

    if terminology.get("confidence") == "low" or data_gaps:
        confidence = "low"
    elif terminology.get("confidence") == "medium":
        confidence = "medium"
    else:
        confidence = str(quick.get("confidence", "medium"))
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"

    verdict = str(level_decision["verdict"])
    recommended_value = level_decision["recommended"]
    recommended = recommended_value if isinstance(recommended_value, str) else None
    next_candidate = candidate if candidate != recommended else None
    campaign_id = current_campaign.get("id") or current_campaign.get("campaign_id")
    structure_decision = deepcopy(dict(structure))
    structure_decision["campaign_id"] = campaign_id
    upgrade_requirements = _unique(
        [
            *level_decision["data_gaps"],
            *(
                [
                    "stable_payment_value_volume",
                    "reliable_value_and_currency",
                    "value_specific_reconciliation",
                ]
                if candidate == "AC3.0"
                and level_decision["action"] not in {"move", "parallel_test"}
                else []
            ),
        ]
    )
    result = {
        "schema_version": QUICK_DECISION_SCHEMA_VERSION,
        "mode": "quick_decision",
        "requested_mode": route["mode"],
        "question_type": requested_question_type,
        "terminology": terminology,
        "decision": {
            "verdict": verdict,
            "confidence": confidence,
            "summary": _summary(verdict, current, recommended),
            "primary_action_count": 1,
        },
        "campaign_level_decision": {
            "current": current,
            "recommended": recommended,
            "next_candidate": next_candidate,
            "action": level_decision["action"],
            "upgrade_allowed": level_decision["action"] in {"move", "parallel_test"},
        },
        "campaign_structure_decision": structure_decision,
        "creative_decision": creative,
        "bid_decision": bid,
        "budget_decision": budget,
        "constraint_analysis": numeric["constraint_analysis"],
        "target_recommendation": target_recommendation,
        "budget_recommendation": budget_recommendation,
        "split_feasibility": numeric["split_feasibility"],
        "derived_signals": derived_signals,
        "calculation_evidence": numeric["calculation_evidence"],
        "heuristics_used": numeric["heuristics_used"],
        "policy": numeric["policy"],
        "legacy_hints_ignored": numeric["legacy_hints_ignored"],
        "permission_check": {
            "allowed": not client_requests,
            "requires_client_approval": any(
                "approval" in request for request in client_requests
            ),
            "requires_exact_live_edit_confirmation": True,
            "client_requests": client_requests,
        },
        "classification": classification,
        "reason_codes": reason_codes or ["safe_hold_by_default"],
        "data_gaps": data_gaps,
        "do_not_do": _unique(
            [
                "do_not_treat_ac_labels_as_bid_values",
                "do_not_duplicate_only_to_restart_learning",
                "do_not_change_level_bid_budget_and_creative_together",
                "do_not_edit_google_ads_without_exact_human_confirmation",
            ]
        ),
        "review_condition": review,
        "upgrade_condition": {
            "target_level": candidate,
            "requirements": upgrade_requirements,
        },
        "upgrade_requirements": upgrade_requirements,
        "rollback": rollback,
        "experiments": [],
        "account_write": False,
        "ledger_write": False,
        "human_confirmation_required_for_live_write": True,
    }
    validate_quick_decision(result)
    return result
