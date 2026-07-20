"""Aggregate metric helpers for replay reports."""

from __future__ import annotations

import math
from typing import Any

from .models import RateMetric
from .types import ContractError


def _rate(numerator: int, denominator: int) -> RateMetric:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
    }


def _magnitude_error(values: list[float]) -> dict[str, float | int | None]:
    total = 0.0
    for value in values:
        total += value
        if not math.isfinite(total):
            raise ContractError("aggregate numeric magnitude error must remain finite")
    return {
        "total_absolute_percentage_error": round(total, 4),
        "denominator": len(values),
        "mean_absolute_percentage_error": (
            round(total / len(values), 4) if values else None
        ),
    }


def _median_magnitude_error(
    values: list[float],
) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        median_value = None
    else:
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            median_value = ordered[midpoint]
        else:
            median_value = ordered[midpoint - 1] / 2 + ordered[midpoint] / 2
        if not math.isfinite(median_value):
            raise ContractError(
                "aggregate median numeric magnitude error must remain finite"
            )
    return {
        "denominator": len(ordered),
        "median_magnitude_error_percent": (
            round(median_value, 4) if median_value is not None else None
        ),
    }


def _numeric_calibration_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    records = [
        (case, case["numeric_evaluation"])
        for case in cases
        if isinstance(case.get("numeric_evaluation"), dict)
    ]
    numeric_actions = [
        (case, record)
        for case, record in records
        if record["final_recommendation"] is not None
    ]
    evaluable_numeric_actions = [
        (case, record)
        for case, record in numeric_actions
        if case["evaluation"]["numeric_calibration_evaluable"] is True
    ]
    direction_evaluations = [
        record
        for _, record in evaluable_numeric_actions
        if isinstance(record["direction_correct"], bool)
    ]
    magnitude_evaluations = [
        record
        for _, record in evaluable_numeric_actions
        if record["magnitude_error_percent"] is not None
    ]
    capped_recommendations = [
        record for _, record in records if record["capped_by_policy"] is True
    ]
    executed_numeric_actions = [
        record
        for case, record in numeric_actions
        if case["actual_action"]["executed"] is True
        and record["human_executed_value"] is not None
    ]
    no_action_evaluations = [
        record
        for case, record in records
        if record["final_recommendation"] is None
        and case["evaluation"]["numeric_calibration_evaluable"] is True
        and isinstance(record["direction_correct"], bool)
    ]
    return {
        "direction_accuracy": _rate(
            sum(
                record["direction_correct"] is True for record in direction_evaluations
            ),
            len(direction_evaluations),
        ),
        "median_magnitude_error": _median_magnitude_error(
            [
                float(record["magnitude_error_percent"])
                for record in magnitude_evaluations
            ]
        ),
        "policy_cap_trigger_rate": _rate(
            sum(record["capped_by_policy"] is True for _, record in records),
            len(records),
        ),
        "too_aggressive_rate": _rate(
            sum(
                record["recommendation_was_too_aggressive"] is True
                for _, record in evaluable_numeric_actions
            ),
            len(evaluable_numeric_actions),
        ),
        "too_conservative_rate": _rate(
            sum(
                record["recommendation_was_too_conservative"] is True
                for _, record in evaluable_numeric_actions
            ),
            len(evaluable_numeric_actions),
        ),
        "rollback_rate": _rate(
            sum(
                record["rollback_triggered"] is True
                for record in executed_numeric_actions
            ),
            len(executed_numeric_actions),
        ),
        "staged_plan_completion_rate": _rate(
            sum(
                record["staged_plan_used"] is True for record in capped_recommendations
            ),
            len(capped_recommendations),
        ),
        "no_action_correct_rate": _rate(
            sum(
                record["direction_correct"] is True for record in no_action_evaluations
            ),
            len(no_action_evaluations),
        ),
    }
