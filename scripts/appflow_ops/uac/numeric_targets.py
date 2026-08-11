"""Measurement gates and target (tCPA/tROAS) recommendations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import _mapping, _number
from .numeric_common import (
    OPERATIONAL_CORRECTION,
    _change_percent,
    _policy_values,
    _review_gate,
)
from .numeric_safety import (
    _candidate_values,
    _correction_recommendation,
    _correction_request,
    _correction_within_business_boundary,
)
from .policy_loader import LoadedPolicy
from .types import ContractError


def _measurement_block(
    case: Mapping[str, Any],
    *,
    value_target: bool,
    signal_policy: LoadedPolicy,
) -> str | None:
    measurement = _mapping(case.get("measurement"))
    goal = _mapping(case.get("goal"))
    comparisons = (
        "google_ads_vs_firebase",
        "google_ads_vs_mmp",
        "mmp_vs_backend",
    )
    if any(measurement.get(field) == "material_mismatch" for field in comparisons):
        return "measurement_reconciliation_unreliable"
    if measurement.get("duplicate_events") is True:
        return "duplicate_conversion_events"
    if value_target and measurement.get("value_currency_valid") is False:
        return "value_or_currency_not_verified"
    business_goal = str(goal.get("business_goal", "")).lower()
    if (
        business_goal in {"payment", "value", "retention", "revenue", "subscription"}
        and measurement.get("payment_trial_refund_distinguished") is False
    ):
        return "payment_trial_or_refund_definition_unreliable"
    if (
        business_goal in {"subscription", "retention"}
        and measurement.get("subscription_renewal_included") is False
    ):
        return "subscription_renewal_value_not_included"
    missing_rate = _number(measurement.get("value_missing_rate"))
    currency_rate = _number(measurement.get("currency_consistency_rate"))
    google_mmp_rate = _number(measurement.get("google_mmp_value_difference_rate"))
    mmp_backend_rate = _number(measurement.get("mmp_backend_value_difference_rate"))
    refund_rate = _number(measurement.get("refund_rate"))
    maximum_refund_rate = _number(goal.get("maximum_acceptable_refund_rate"))
    value_quality = _mapping(_policy_values(signal_policy).get("value_quality"))
    missing_block_value = _number(value_quality.get("missing_value_blocking_percent"))
    currency_block_value = _number(
        value_quality.get("currency_consistency_blocking_min_percent")
    )
    difference_block_value = _number(value_quality.get("difference_blocking_percent"))
    if (
        missing_block_value is None
        or currency_block_value is None
        or difference_block_value is None
    ):
        raise ContractError("signal policy value blocking thresholds are incomplete")
    missing_block = missing_block_value / 100
    currency_block = currency_block_value / 100
    difference_block = difference_block_value / 100
    if business_goal in {"payment", "value", "retention", "revenue"} and (
        (missing_rate is not None and missing_rate > missing_block)
        or (currency_rate is not None and currency_rate < currency_block)
        or (google_mmp_rate is not None and google_mmp_rate > difference_block)
        or (mmp_backend_rate is not None and mmp_backend_rate > difference_block)
        or (
            refund_rate is not None
            and maximum_refund_rate is not None
            and refund_rate > maximum_refund_rate
        )
    ):
        return "numeric_value_measurement_unreliable"
    return None


def _empty_target(
    *,
    target_type: str,
    current: float | None,
    reason: str,
    action: str = "NO_CHANGE",
    context: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    hold_current = reason in {
        "target_is_not_primary_constraint",
        "budget_is_the_primary_constraint",
        "business_budget_cap_correction_precedes_target_change",
        "operational_budget_correction_selected_as_single_variable",
    }
    hold_value = current if hold_current else None
    return {
        "target_type": target_type,
        "current_value": current,
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


def _hard_target_boundary_correction(
    *,
    target_type: str,
    current: float,
    boundary: float,
    context: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any] | None:
    if target_type == "tROAS":
        if current >= boundary:
            return None
        action = "INCREASE"
        boundary_fact = "business_roas_floor"
    else:
        if current <= boundary:
            return None
        action = "DECREASE"
        boundary_fact = "business_cpa_ceiling"
    return {
        "target_type": target_type,
        "current_value": current,
        "conservative_value": boundary,
        "recommended_value": boundary,
        "aggressive_value": boundary,
        "recommended_action": action,
        "change_percent": _change_percent(current, boundary),
        "evidence_quality": "high",
        "calculation_basis": ["current_account_target", boundary_fact],
        "calculation_evidence": [
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": "current_account_target",
                "value": current,
            },
            {
                "type": "BUSINESS_CONSTRAINT",
                "fact": boundary_fact,
                "value": boundary,
            },
        ],
        "do_not_change_before": _review_gate(case, context),
        "rollback_value": None,
        "rollback_condition": None,
        "reason": "current_target_violates_business_boundary",
    }


def _target_recommendation(
    case: Mapping[str, Any],
    signals: Mapping[str, Any],
    context: Mapping[str, Any],
    signal_policy: LoadedPolicy,
) -> dict[str, Any]:
    goal = _mapping(case.get("goal"))
    strategy = str(goal.get("bidding_strategy", "")).lower()
    value_target = "roas" in strategy or context.get("target_roas") is not None
    target_type = "tROAS" if value_target else "tCPA"
    current = _number(context.get("target_roas" if value_target else "target_cpa"))
    maturity = _mapping(signals.get("maturity"))
    target_state = _mapping(signals.get("target_constraint")).get("state")
    if not context.get("has_numeric_evidence"):
        return _empty_target(
            target_type=target_type,
            current=current,
            reason="numeric_account_evidence_not_supplied",
            context=context,
            case=case,
        )
    current_budget = _number(context.get("current_daily_budget"))
    daily_budget_cap = _number(context.get("daily_budget_cap"))
    if (
        current_budget is not None
        and daily_budget_cap is not None
        and current_budget > daily_budget_cap
    ):
        return _empty_target(
            target_type=target_type,
            current=current,
            reason="business_budget_cap_correction_precedes_target_change",
            context=context,
            case=case,
        )
    if current is None:
        return _empty_target(
            target_type=target_type,
            current=None,
            reason="current_target_missing",
            context=context,
            case=case,
        )
    operational = _mapping(_mapping(case.get("quick_ops")).get("operational"))
    if operational.get("operation_classification") == OPERATIONAL_CORRECTION and str(
        operational.get("affected_variable", "")
    ) in {"daily_budget", "budget"}:
        return _empty_target(
            target_type=target_type,
            current=current,
            reason="operational_budget_correction_selected_as_single_variable",
            context=context,
            case=case,
        )
    boundary = _number(
        context.get(
            "minimum_acceptable_roas" if value_target else "maximum_acceptable_cpa"
        )
    )
    if boundary is None:
        return _empty_target(
            target_type=target_type,
            current=current,
            reason=(
                "business_roas_floor_missing"
                if value_target
                else "business_cpa_ceiling_missing"
            ),
            context=context,
            case=case,
        )
    measurement_reason = _measurement_block(
        case, value_target=value_target, signal_policy=signal_policy
    )
    if measurement_reason is not None:
        return _empty_target(
            target_type=target_type,
            current=current,
            reason=measurement_reason,
            context=context,
            case=case,
        )
    if value_target and _mapping(signals.get("value_signal")).get("state") != (
        "VALUE_SIGNAL_READY"
    ):
        return _empty_target(
            target_type=target_type,
            current=current,
            reason="value_signal_not_reliable_enough_for_troas",
            context=context,
            case=case,
        )
    correction_requested, historical, correction_error = _correction_request(
        case, variable="target", target_type=target_type
    )
    if correction_requested:
        if correction_error is not None or historical is None:
            return _empty_target(
                target_type=target_type,
                current=current,
                reason=correction_error or "operational_correction_evidence_incomplete",
                context=context,
                case=case,
            )
        if not _correction_within_business_boundary(
            historical,
            variable="target",
            target_type=target_type,
            context=context,
        ):
            return _empty_target(
                target_type=target_type,
                current=current,
                reason="historical_correction_value_violates_business_boundary",
                context=context,
                case=case,
            )
        return _correction_recommendation(
            current=current,
            historical=historical,
            target_type=target_type,
            context=context,
            case=case,
            budget=False,
        )
    if maturity.get("state") != "MATURE":
        return _empty_target(
            target_type=target_type,
            current=current,
            reason="insufficient_mature_conversion_data",
            action="WAIT",
            context=context,
            case=case,
        )
    hard_correction = _hard_target_boundary_correction(
        target_type=target_type,
        current=current,
        boundary=boundary,
        context=context,
        case=case,
    )
    if hard_correction is not None:
        return hard_correction
    if value_target and _mapping(signals.get("event_volume")).get("state") not in {
        "SUFFICIENT_AND_STABLE",
        "SUFFICIENT_BUT_VOLATILE",
    }:
        return _empty_target(
            target_type=target_type,
            current=current,
            reason="mature_value_event_volume_is_insufficient",
            context=context,
            case=case,
        )
    priority = str(context.get("optimization_priority", "balanced"))
    if value_target:
        actual = context.get("mature_actual_roas")
        if actual is None:
            reason = "mature_actual_roas_missing"
        else:
            reason = "target_is_not_primary_constraint"
        if actual is None:
            return _empty_target(
                target_type=target_type,
                current=current,
                reason=reason,
                context=context,
                case=case,
            )
        if target_state == "TARGET_LIKELY_TOO_TIGHT" and current > boundary:
            conservative, recommended, aggressive = _candidate_values(
                current,
                float(boundary),
                direction="decrease",
                priority=priority,
            )
            action = "DECREASE"
            basis = [
                "mature_actual_roas",
                "spend_delivery_rate",
                "business_roas_floor",
            ]
            rollback_condition = {"mature_roas_below": float(boundary)}
        elif target_state == "TARGET_LIKELY_TOO_LOOSE" and current < boundary:
            conservative = recommended = aggressive = float(boundary)
            action = "INCREASE"
            basis = ["mature_actual_roas", "business_roas_floor"]
            rollback_condition = None
        else:
            return _empty_target(
                target_type=target_type,
                current=current,
                reason="target_is_not_primary_constraint",
                context=context,
                case=case,
            )
    else:
        actual = context.get("mature_actual_cpa")
        if actual is None:
            reason = "mature_actual_cpa_missing"
        else:
            reason = "target_is_not_primary_constraint"
        if actual is None:
            return _empty_target(
                target_type=target_type,
                current=current,
                reason=reason,
                context=context,
                case=case,
            )
        if actual > boundary and current <= boundary:
            return _empty_target(
                target_type=target_type,
                current=current,
                reason="mature_cpa_above_business_ceiling_do_not_relax",
                context=context,
                case=case,
            )
        if target_state == "TARGET_LIKELY_TOO_TIGHT" and current < boundary:
            conservative, recommended, aggressive = _candidate_values(
                current,
                float(boundary),
                direction="increase",
                priority=priority,
            )
            action = "INCREASE"
            basis = [
                "mature_actual_cpa",
                "spend_delivery_rate",
                "business_cpa_ceiling",
            ]
            rollback_condition = {"mature_cpa_above": float(boundary)}
        elif target_state == "TARGET_LIKELY_TOO_LOOSE" and current > boundary:
            conservative = recommended = aggressive = float(boundary)
            action = "DECREASE"
            basis = ["mature_actual_cpa", "business_cpa_ceiling"]
            rollback_condition = None
        else:
            return _empty_target(
                target_type=target_type,
                current=current,
                reason="target_is_not_primary_constraint",
                context=context,
                case=case,
            )
    evidence_quality = (
        "high"
        if _mapping(signals.get("event_volume")).get("state") == "SUFFICIENT_AND_STABLE"
        else "medium"
    )
    return {
        "target_type": target_type,
        "current_value": current,
        "conservative_value": conservative,
        "recommended_value": recommended,
        "aggressive_value": aggressive,
        "recommended_action": action,
        "change_percent": _change_percent(current, recommended),
        "evidence_quality": evidence_quality,
        "calculation_basis": basis,
        "calculation_evidence": [
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": basis[0],
                "value": actual,
            },
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": "spend_delivery_rate",
                "value": _mapping(signals.get("budget_delivery")).get("delivery_rate"),
            },
            {
                "type": "BUSINESS_CONSTRAINT",
                "fact": basis[-1],
                "value": boundary,
            },
            {
                "type": "PLATFORM_GUIDANCE",
                "fact": "avoid_large_frequent_target_changes",
            },
            {
                "type": "HEURISTIC",
                "fact": "candidate_values_use_account_specific_headroom",
            },
        ],
        "do_not_change_before": _review_gate(case, context),
        "rollback_value": current if rollback_condition is not None else None,
        "rollback_condition": rollback_condition,
        "reason": "account_evidence_supports_one_bounded_target_change",
    }
