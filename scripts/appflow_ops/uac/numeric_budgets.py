"""Daily-budget recommendations and hard business-cap corrections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import _mapping, _number
from .numeric_common import (
    OPERATIONAL_CORRECTION,
    _change_percent,
    _review_gate,
)
from .numeric_safety import (
    _candidate_values,
    _correction_recommendation,
    _correction_request,
    _correction_within_business_boundary,
)
from .numeric_targets import _measurement_block
from .policy_loader import LoadedPolicy


def _empty_budget(
    *,
    current: float | None,
    reason: str,
    context: Mapping[str, Any],
    case: Mapping[str, Any],
    action: str = "NO_CHANGE",
) -> dict[str, Any]:
    hold_current = reason in {
        "target_change_selected_as_the_single_numeric_variable",
        "budget_is_not_the_primary_constraint",
        "operational_target_correction_selected_as_single_variable",
    }
    hold_value = current if hold_current else None
    return {
        "current_daily_budget": current,
        "conservative_value": hold_value,
        "recommended_value": hold_value,
        "aggressive_value": hold_value,
        "recommended_action": action,
        "change_percent": None,
        "evidence_quality": "insufficient",
        "calculation_basis": [],
        "calculation_evidence": [{"type": "INSUFFICIENT_EVIDENCE", "fact": reason}],
        "do_not_change_before": _review_gate(case, context),
        "rollback_value": None,
        "rollback_condition": None,
        "reason": reason,
    }


def _hard_budget_cap_correction(
    *,
    current: float,
    cap: float,
    context: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "current_daily_budget": current,
        "conservative_value": cap,
        "recommended_value": cap,
        "aggressive_value": cap,
        "recommended_action": "DECREASE",
        "change_percent": _change_percent(current, cap),
        "evidence_quality": "high",
        "calculation_basis": ["current_daily_budget", "business_daily_budget_cap"],
        "calculation_evidence": [
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": "current_daily_budget",
                "value": current,
            },
            {
                "type": "BUSINESS_CONSTRAINT",
                "fact": "daily_budget_cap",
                "value": cap,
            },
        ],
        "do_not_change_before": _review_gate(case, context),
        "rollback_value": None,
        "rollback_condition": None,
        "reason": "current_budget_exceeds_business_cap",
    }


def _budget_recommendation(
    case: Mapping[str, Any],
    signals: Mapping[str, Any],
    context: Mapping[str, Any],
    target: Mapping[str, Any],
    signal_policy: LoadedPolicy,
) -> dict[str, Any]:
    current = _number(context.get("current_daily_budget"))
    if not context.get("has_numeric_evidence"):
        return _empty_budget(
            current=current,
            reason="numeric_account_evidence_not_supplied",
            context=context,
            case=case,
        )
    if current is None:
        return _empty_budget(
            current=None,
            reason="current_daily_budget_missing",
            context=context,
            case=case,
        )
    operational = _mapping(_mapping(case.get("quick_ops")).get("operational"))
    if operational.get("operation_classification") == OPERATIONAL_CORRECTION and str(
        operational.get("affected_variable", "")
    ) in {"target", "bid", "target_cpa", "target_roas"}:
        return _empty_budget(
            current=current,
            reason="operational_target_correction_selected_as_single_variable",
            context=context,
            case=case,
        )
    cap = context.get("daily_budget_cap")
    if cap is None:
        return _empty_budget(
            current=current,
            reason="business_daily_budget_cap_missing",
            context=context,
            case=case,
        )
    cap = float(cap)
    correction_requested, historical, correction_error = _correction_request(
        case, variable="daily_budget"
    )
    if correction_requested:
        if correction_error is not None or historical is None:
            return _empty_budget(
                current=current,
                reason=correction_error or "operational_correction_evidence_incomplete",
                context=context,
                case=case,
            )
        if not _correction_within_business_boundary(
            historical,
            variable="daily_budget",
            target_type=None,
            context=context,
        ):
            return _empty_budget(
                current=current,
                reason="historical_correction_value_violates_business_boundary",
                context=context,
                case=case,
            )
        return _correction_recommendation(
            current=current,
            historical=historical,
            target_type=None,
            context=context,
            case=case,
            budget=True,
        )
    if _mapping(signals.get("maturity")).get("state") != "MATURE":
        return _empty_budget(
            current=current,
            reason="insufficient_mature_conversion_data",
            context=context,
            case=case,
            action="WAIT",
        )
    if current > cap:
        return _hard_budget_cap_correction(
            current=current,
            cap=cap,
            context=context,
            case=case,
        )
    if target.get("recommended_action") not in {"NO_CHANGE", "WAIT", None}:
        return _empty_budget(
            current=current,
            reason="target_change_selected_as_the_single_numeric_variable",
            context=context,
            case=case,
        )
    priority = str(context.get("optimization_priority", "balanced"))
    budget_state = _mapping(signals.get("budget_delivery")).get("state")
    event_state = _mapping(signals.get("event_volume")).get("state")
    strategy = str(_mapping(case.get("goal")).get("bidding_strategy", "")).lower()
    if "roas" in strategy:
        actual = context.get("mature_actual_roas")
        boundary = context.get("minimum_acceptable_roas")
        efficient = actual is not None and boundary is not None and actual >= boundary
    else:
        actual = context.get("mature_actual_cpa")
        boundary = context.get("maximum_acceptable_cpa")
        efficient = actual is not None and boundary is not None and actual <= boundary
    if budget_state == "BUDGET_CONSTRAINED" and cap > current:
        measurement_reason = _measurement_block(
            case,
            value_target="roas" in strategy,
            signal_policy=signal_policy,
        )
        if measurement_reason is not None:
            return _empty_budget(
                current=current,
                reason=measurement_reason,
                context=context,
                case=case,
            )
        if event_state not in {
            "SUFFICIENT_AND_STABLE",
            "SUFFICIENT_BUT_VOLATILE",
        }:
            return _empty_budget(
                current=current,
                reason="event_volume_cannot_support_budget_increase",
                context=context,
                case=case,
            )
        if not efficient:
            return _empty_budget(
                current=current,
                reason="mature_efficiency_outside_business_constraint",
                context=context,
                case=case,
            )
        conservative, recommended, aggressive = _candidate_values(
            current, cap, direction="increase", priority=priority
        )
        action = "INCREASE"
        reason = "budget_constraint_with_mature_efficiency_inside_business_limit"
        rollback_value = current
        rollback_condition = (
            {"mature_cpa_above": boundary}
            if "roas" not in strategy
            else {"mature_roas_below": boundary}
        )
    else:
        return _empty_budget(
            current=current,
            reason="budget_is_not_the_primary_constraint",
            context=context,
            case=case,
        )
    return {
        "current_daily_budget": current,
        "conservative_value": conservative,
        "recommended_value": recommended,
        "aggressive_value": aggressive,
        "recommended_action": action,
        "change_percent": _change_percent(current, recommended),
        "evidence_quality": (
            "high" if event_state == "SUFFICIENT_AND_STABLE" else "medium"
        ),
        "calculation_basis": [
            "multi_day_spend_delivery",
            "mature_efficiency",
            "business_daily_budget_cap",
        ],
        "calculation_evidence": [
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": "multi_day_spend_delivery",
                "value": _mapping(signals.get("budget_delivery")).get("delivery_rate"),
            },
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": "mature_efficiency",
                "value": actual,
            },
            {
                "type": "BUSINESS_CONSTRAINT",
                "fact": "daily_budget_cap",
                "value": cap,
            },
            {
                "type": "HEURISTIC",
                "fact": "candidate_values_use_account_specific_budget_headroom",
            },
        ],
        "do_not_change_before": _review_gate(case, context),
        "rollback_value": rollback_value,
        "rollback_condition": rollback_condition,
        "reason": reason,
    }
