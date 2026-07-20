"""Numeric safety caps, staged plans, and operational corrections."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from ._common import _mapping, _number
from .numeric_common import (
    _MAX_EXPLICIT_STAGED_CHECKPOINTS,
    NORMAL_OPTIMIZATION,
    OPERATIONAL_CORRECTION,
    STAGED_OPTIMIZATION,
    _change_limit_percent,
    _change_percent,
    _limit_candidate,
    _quantize,
    _review_gate,
    _stage_review_values,
)
from .policy_loader import LoadedPolicy


def _build_staged_plan(
    *,
    current: float,
    first_stage: float,
    final_candidate: float,
    variable: str,
    direction: str,
    policy: LoadedPolicy,
    review_gate: Mapping[str, Any],
) -> dict[str, Any]:
    review_after_days, minimum_mature_events = _stage_review_values(policy, review_gate)
    limit_percent = _change_limit_percent(
        policy, variable=variable, direction=direction
    )
    stages: list[dict[str, Any]] = []
    value = current
    next_value = first_stage
    fully_enumerated = False
    for stage_number in range(1, _MAX_EXPLICIT_STAGED_CHECKPOINTS + 1):
        immediate = stage_number == 1
        stage: dict[str, Any] = {
            "stage": stage_number,
            "target": next_value,
            "immediate": immediate,
            "approval_state": "PROPOSED" if immediate else "REQUIRES_FRESH_REVIEW",
            "review_after_days": review_after_days,
            "minimum_mature_events": minimum_mature_events,
            "automatic_execution": False,
        }
        if not immediate:
            stage["condition"] = {
                "fresh_mature_data_required": True,
                "conversion_delay_mature": True,
                "mature_efficiency_within_business_limit": True,
                "delivery_improved_or_control_objective_met": True,
                "no_unreviewed_concurrent_change": True,
            }
        stages.append(stage)
        if math.isclose(next_value, final_candidate, rel_tol=1e-9, abs_tol=1e-9):
            fully_enumerated = True
            break
        value = next_value
        if direction == "increase":
            raw_next = min(final_candidate, value * (1 + limit_percent / 100))
        else:
            raw_next = max(final_candidate, value * (1 - limit_percent / 100))
        raw_next = round(raw_next, 12)
        next_value = _quantize(raw_next, value)
        if direction == "increase":
            next_value = min(next_value, raw_next, final_candidate)
        else:
            next_value = max(next_value, raw_next, final_candidate)
        if math.isclose(next_value, value, rel_tol=1e-9, abs_tol=1e-9):
            # A valid sub-1% policy can be smaller than the display quantizer.
            # Preserve the exact safe cap boundary instead of crashing or
            # silently widening the configured percentage.
            next_value = round(raw_next, 12)
        if math.isclose(next_value, value, rel_tol=1e-12, abs_tol=1e-12):
            break
    return {
        "final_candidate": final_candidate,
        "immediate_stage": 1,
        "stages": stages,
        "stages_fully_enumerated": fully_enumerated,
        "remaining_stages_require_fresh_recalculation": not fully_enumerated,
        "future_stages_require_fresh_review": True,
        "automatic_execution": False,
    }


def _empty_numeric_safety(policy: LoadedPolicy) -> dict[str, Any]:
    return {
        "policy_version": policy.policy_version,
        "raw_candidate": None,
        "business_bounded_candidate": None,
        "change_limited_candidate": None,
        "final_recommendation": None,
        "current_change_percent": None,
        "staged_adjustment_required": False,
        "operation_classification": NORMAL_OPTIMIZATION,
        "limit_reasons": [],
        "applied_change_limit_percent": None,
        "capped_by_policy": False,
        "staged_plan": None,
        "correction_evidence": None,
    }


def _correction_request(
    case: Mapping[str, Any], *, variable: str, target_type: str | None = None
) -> tuple[bool, float | None, str | None]:
    operational = _mapping(_mapping(case.get("quick_ops")).get("operational"))
    if operational.get("operation_classification") != OPERATIONAL_CORRECTION:
        return False, None, None
    affected = str(operational.get("affected_variable", ""))
    if variable == "target":
        specific_target = "target_roas" if target_type == "tROAS" else "target_cpa"
        accepted_variables = {"target", "bid", specific_target}
    else:
        accepted_variables = {"daily_budget", "budget"}
    if affected not in accepted_variables:
        if variable == "target" and affected in {"target_cpa", "target_roas"}:
            return True, None, "operational_correction_target_type_mismatch"
        return False, None, None
    historical = _number(operational.get("historical_approved_value"))
    rollback_target = _number(operational.get("rollback_target"))
    evidence = operational.get("configuration_error_evidence")
    if (
        historical is None
        or rollback_target is None
        or historical <= 0
        or rollback_target <= 0
        or not math.isclose(historical, rollback_target, rel_tol=1e-9, abs_tol=1e-9)
        or not isinstance(evidence, str)
        or not evidence.strip()
        or operational.get("configuration_error_confirmed") is not True
        or operational.get("human_confirmation") is not True
    ):
        return True, None, "operational_correction_evidence_incomplete"
    return True, historical, None


def _correction_within_business_boundary(
    value: float, *, variable: str, target_type: str | None, context: Mapping[str, Any]
) -> bool:
    if value <= 0:
        return False
    if variable == "daily_budget":
        cap = _number(context.get("daily_budget_cap"))
        return cap is not None and value <= cap
    if target_type == "tROAS":
        floor = _number(context.get("minimum_acceptable_roas"))
        return floor is not None and value >= floor
    ceiling = _number(context.get("maximum_acceptable_cpa"))
    return ceiling is not None and value <= ceiling


def _correction_recommendation(
    *,
    current: float,
    historical: float,
    target_type: str | None,
    context: Mapping[str, Any],
    case: Mapping[str, Any],
    budget: bool,
) -> dict[str, Any]:
    if math.isclose(current, historical, rel_tol=1e-9, abs_tol=1e-9):
        action = "NO_CHANGE"
    else:
        action = "INCREASE" if historical > current else "DECREASE"
    current_key = "current_daily_budget" if budget else "current_value"
    result: dict[str, Any] = {
        current_key: current,
        "conservative_value": historical,
        "recommended_value": historical,
        "aggressive_value": historical,
        "recommended_action": action,
        "change_percent": _change_percent(current, historical),
        "evidence_quality": "high",
        "calculation_basis": [
            "confirmed_configuration_error",
            "historical_approved_value",
            "explicit_human_confirmation",
        ],
        "calculation_evidence": [
            {
                "type": "ACCOUNT_EVIDENCE",
                "fact": "historical_approved_value",
                "value": historical,
            },
            {
                "type": "BUSINESS_CONSTRAINT",
                "fact": "confirmed_configuration_error",
            },
        ],
        "do_not_change_before": _review_gate(case, context),
        "rollback_value": historical,
        "rollback_condition": {"configuration_error_reappears": True},
        "reason": "restore_confirmed_historical_value_after_configuration_error",
        "numeric_safety": {
            "policy_version": None,
            "raw_candidate": historical,
            "business_bounded_candidate": historical,
            "change_limited_candidate": historical,
            "final_recommendation": historical,
            "current_change_percent": _change_percent(current, historical),
            "staged_adjustment_required": False,
            "operation_classification": OPERATIONAL_CORRECTION,
            "limit_reasons": [
                "confirmed_operational_correction_bypasses_normal_change_cap"
            ],
            "applied_change_limit_percent": None,
            "capped_by_policy": False,
            "staged_plan": None,
            "correction_evidence": {
                "historical_approved_value": historical,
                "rollback_target": historical,
                "configuration_error_confirmed": True,
                "human_confirmation_recorded": True,
            },
        },
    }
    if not budget:
        result["target_type"] = target_type
    return result


def _candidate_values(
    current: float,
    boundary: float,
    *,
    direction: str,
    priority: str,
) -> tuple[float, float, float]:
    gap = abs(boundary - current)
    if direction == "increase":
        conservative_fraction = 0.25
        recommended_fraction = {
            "scale": 0.5,
            "balanced": 0.4,
            "efficiency": 0.25,
        }[priority]
        aggressive_fraction = {
            "scale": 1.0,
            "balanced": 0.75,
            "efficiency": 0.5,
        }[priority]
        raw = (
            current + gap * conservative_fraction,
            current + gap * recommended_fraction,
            current + gap * aggressive_fraction,
        )
    else:
        conservative_fraction = 0.25
        recommended_fraction = {
            "scale": 0.5,
            "balanced": 0.6,
            "efficiency": 1.0,
        }[priority]
        aggressive_fraction = 1.0
        raw = (
            current - gap * conservative_fraction,
            current - gap * recommended_fraction,
            current - gap * aggressive_fraction,
        )
    quantized = [_quantize(value, current) for value in raw]
    if direction == "increase":
        quantized = [min(value, boundary) for value in quantized]
    else:
        quantized = [max(value, boundary) for value in quantized]
    return tuple(quantized)  # type: ignore[return-value]


def _candidate_within_business_boundary(
    value: float,
    *,
    variable: str,
    target_type: str | None,
    context: Mapping[str, Any],
) -> bool:
    return _correction_within_business_boundary(
        value,
        variable=variable,
        target_type=target_type,
        context=context,
    )


def _apply_numeric_safety(
    recommendation: dict[str, Any],
    *,
    variable: str,
    current_field: str,
    target_type: str | None,
    context: Mapping[str, Any],
    case: Mapping[str, Any],
    policy: LoadedPolicy,
) -> None:
    current = _number(recommendation.get(current_field))
    candidate = _number(recommendation.get("recommended_value"))
    action = str(recommendation.get("recommended_action", "NO_CHANGE"))
    existing_safety = recommendation.get("numeric_safety")
    if (
        isinstance(existing_safety, dict)
        and existing_safety.get("operation_classification") == OPERATIONAL_CORRECTION
    ):
        existing_safety["policy_version"] = policy.policy_version
        return
    safety = _empty_numeric_safety(policy)
    recommendation["numeric_safety"] = safety
    if current is None or candidate is None or action not in {"INCREASE", "DECREASE"}:
        return

    direction = "increase" if action == "INCREASE" else "decrease"
    limited, limit_percent, capped = _limit_candidate(
        current,
        candidate,
        variable=variable,
        direction=direction,
        policy=policy,
    )
    limit_reason = (
        "max_single_budget_change_percent"
        if variable == "daily_budget"
        else "max_single_target_change_percent"
    )
    safety.update(
        {
            "raw_candidate": candidate,
            "business_bounded_candidate": candidate,
            "change_limited_candidate": limited,
            "current_change_percent": _change_percent(current, limited),
            "applied_change_limit_percent": limit_percent,
            "capped_by_policy": capped,
        }
    )

    if limit_percent == 0:
        zero_cap_reason = (
            "numeric_policy_degraded_to_zero_change_cap"
            if policy.degraded
            else "numeric_policy_zero_change_cap"
        )
        recommendation.update(
            {
                "conservative_value": current,
                "recommended_value": current,
                "aggressive_value": current,
                "recommended_action": "NO_CHANGE",
                "change_percent": 0.0,
                "rollback_value": None,
                "rollback_condition": None,
                "reason": zero_cap_reason,
            }
        )
        safety.update(
            {
                "change_limited_candidate": current,
                "final_recommendation": current,
                "current_change_percent": 0.0,
                "limit_reasons": [
                    (
                        "degraded_policy_zero_change_cap"
                        if policy.degraded
                        else "configured_policy_zero_change_cap"
                    )
                ],
            }
        )
        return

    if math.isclose(limited, current, rel_tol=1e-9, abs_tol=1e-9):
        recommendation.update(
            {
                "conservative_value": current,
                "recommended_value": current,
                "aggressive_value": current,
                "recommended_action": "NO_CHANGE",
                "change_percent": 0.0,
                "rollback_value": None,
                "rollback_condition": None,
                "reason": "numeric_change_cap_below_minimum_safe_increment",
            }
        )
        safety.update(
            {
                "change_limited_candidate": current,
                "final_recommendation": current,
                "current_change_percent": 0.0,
                "limit_reasons": [
                    limit_reason,
                    "minimum_safe_increment_not_reached",
                ],
            }
        )
        return

    if not _candidate_within_business_boundary(
        limited,
        variable=variable,
        target_type=target_type,
        context=context,
    ):
        recommendation.update(
            {
                "conservative_value": None,
                "recommended_value": None,
                "aggressive_value": None,
                "recommended_action": "NO_CHANGE",
                "change_percent": None,
                "evidence_quality": "insufficient",
                "rollback_value": None,
                "rollback_condition": None,
                "reason": "business_boundary_and_change_limit_have_no_safe_intersection",
            }
        )
        safety.update(
            {
                "final_recommendation": None,
                "current_change_percent": None,
                "limit_reasons": [
                    limit_reason,
                    "business_boundary_and_change_limit_have_no_safe_intersection",
                ],
            }
        )
        return

    for field in ("conservative_value", "recommended_value", "aggressive_value"):
        value = _number(recommendation.get(field))
        if value is None or math.isclose(value, current, rel_tol=1e-9, abs_tol=1e-9):
            continue
        value_direction = "increase" if value > current else "decrease"
        value_limited, _, _ = _limit_candidate(
            current,
            value,
            variable=variable,
            direction=value_direction,
            policy=policy,
        )
        recommendation[field] = value_limited
    recommendation["recommended_value"] = limited
    recommendation["change_percent"] = _change_percent(current, limited)
    safety["final_recommendation"] = limited
    if capped:
        review_gate = _review_gate(case, context)
        safety.update(
            {
                "staged_adjustment_required": True,
                "operation_classification": STAGED_OPTIMIZATION,
                "limit_reasons": [limit_reason],
                "staged_plan": _build_staged_plan(
                    current=current,
                    first_stage=limited,
                    final_candidate=candidate,
                    variable=variable,
                    direction=direction,
                    policy=policy,
                    review_gate=review_gate,
                ),
            }
        )
        recommendation["reason"] = (
            "account_evidence_supports_first_stage_of_bounded_numeric_change"
        )
        recommendation["calculation_basis"] = list(
            dict.fromkeys([*recommendation.get("calculation_basis", []), limit_reason])
        )
        recommendation["calculation_evidence"] = [
            *recommendation.get("calculation_evidence", []),
            {
                "type": "HEURISTIC",
                "fact": limit_reason,
                "value": limit_percent,
                "policy_version": policy.policy_version,
            },
        ]
