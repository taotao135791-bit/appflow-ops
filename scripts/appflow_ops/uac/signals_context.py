"""Numeric context extraction for UAC signal derivation.

The functions in this module only transform supplied account facts. They do
not read an advertising account, write files, or treat platform guidance as a
substitute for account evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
import math
from statistics import fmean
from typing import Any

from ._common import _mapping
from .policy_loader import LoadedPolicy, load_policy
from .types import ContractError


SIGNAL_DERIVATION_SCHEMA_VERSION = "1.0"

_NEW_NUMERIC_FIELDS = {
    "mature_actual_cpa",
    "mature_actual_roas",
    "mature_conversions",
    "mature_revenue",
    "google_value",
    "mmp_value",
    "backend_value",
}
_VALUE_RATE_FIELDS = (
    "value_missing_rate",
    "currency_consistency_rate",
    "google_mmp_value_difference_rate",
    "mmp_backend_value_difference_rate",
    "refund_rate",
)


def _signal_policy_values(policy: LoadedPolicy) -> Mapping[str, Any]:
    values = policy.values
    if not isinstance(values, Mapping):
        raise ContractError("loaded signal policy must be an object")
    return values


def _policy_number(values: Mapping[str, Any], section: str, field: str) -> float | None:
    return _number(_mapping(values.get(section)).get(field))


def _policy_ratio(values: Mapping[str, Any], section: str, field: str) -> float:
    number = _policy_number(values, section, field)
    if number is None or number < 0 or number > 100:
        raise ContractError(
            f"signal policy {section}.{field} must be between 0 and 100"
        )
    return number / 100


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _number(value: Any) -> float | None:
    return float(value) if _finite_number(value) else None


def _non_negative(value: Any, path: str) -> float | None:
    if value is None:
        return None
    number = _number(value)
    if number is None or number < 0:
        raise ContractError(f"{path} must be a finite non-negative number")
    return number


def _rate(value: Any, path: str) -> float | None:
    number = _non_negative(value, path)
    if number is not None and number > 1:
        raise ContractError(f"{path} must be between 0 and 1")
    return number


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    result = numerator / denominator
    return result if math.isfinite(result) else None


def _round_metric(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _date_window_days(scope: Mapping[str, Any]) -> int | None:
    start = scope.get("start_date")
    end = scope.get("end_date")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except ValueError:
        return None


def _days_since_last_change(
    maturity: Mapping[str, Any], scope: Mapping[str, Any]
) -> float | None:
    supplied = _non_negative(
        maturity.get("days_since_last_change"),
        "maturity.days_since_last_change",
    )
    if supplied is not None:
        return supplied
    changed_at = maturity.get("last_change_at")
    end = scope.get("end_date")
    if not isinstance(changed_at, str) or not isinstance(end, str):
        return None
    try:
        return float((date.fromisoformat(end) - date.fromisoformat(changed_at)).days)
    except ValueError:
        return None


def _numeric_series(
    rows: Any,
    field: str,
    *,
    path: str,
) -> list[float]:
    if rows is None:
        return []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ContractError(f"{path} must be an array")
    values: list[float] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ContractError(f"{path}[{index}] must be an object")
        if field not in row or row[field] is None:
            continue
        value = _non_negative(row[field], f"{path}[{index}].{field}")
        assert value is not None
        values.append(value)
    return values


def _difference_rate(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    denominator = max(abs(left), abs(right))
    if denominator == 0:
        return 0.0
    return abs(left - right) / denominator


def _has_new_numeric_evidence(case: Mapping[str, Any]) -> bool:
    facts = _mapping(case.get("facts"))
    metrics = _mapping(facts.get("metrics"))
    goal = _mapping(case.get("goal"))
    maturity = _mapping(case.get("maturity"))
    measurement = _mapping(case.get("measurement"))
    return bool(
        _NEW_NUMERIC_FIELDS.intersection(metrics)
        or any(
            key in facts
            for key in (
                "daily_series",
                "event_candidates",
                "creative_cohorts",
                "split_plan",
                "minimum_daily_mature_events",
                "budget_limited",
            )
        )
        or any(
            key in goal
            for key in (
                "maximum_acceptable_cpa",
                "minimum_acceptable_roas",
                "daily_budget_cap",
                "target_roas",
                "optimization_priority",
            )
        )
        or any(
            key in maturity
            for key in (
                "last_change_at",
                "days_since_last_change",
                "last_change_variables",
                "mature_events_since_change",
                "previous_target",
                "previous_daily_budget",
            )
        )
        or any(key in measurement for key in _VALUE_RATE_FIELDS)
    )


def _numeric_context(
    case: Mapping[str, Any], policy: LoadedPolicy | None = None
) -> dict[str, Any]:
    loaded_policy = policy or load_policy("signal")
    policy_values = _signal_policy_values(loaded_policy)
    maturity_defaults = _mapping(policy_values.get("maturity_defaults"))
    facts = _mapping(case.get("facts"))
    metrics = _mapping(facts.get("metrics"))
    goal = _mapping(case.get("goal"))
    maturity = _mapping(case.get("maturity"))
    scope = _mapping(case.get("scope"))
    quick = _mapping(case.get("quick_ops"))
    legacy = _mapping(quick.get("bid_budget"))
    daily_rows = facts.get("daily_series")
    spend_series = _numeric_series(daily_rows, "spend", path="facts.daily_series")
    event_series = _numeric_series(
        daily_rows, "mature_events", path="facts.daily_series"
    )
    value_series = _numeric_series(daily_rows, "value", path="facts.daily_series")
    observation_days = len(daily_rows) if isinstance(daily_rows, list) else None
    if isinstance(daily_rows, list) and daily_rows:
        supplied_dates = [
            row.get("date")
            for row in daily_rows
            if isinstance(row, Mapping) and isinstance(row.get("date"), str)
        ]
        if len(supplied_dates) == len(daily_rows):
            observation_days = len(set(supplied_dates))
    if not observation_days:
        observation_days = int(
            _non_negative(maturity.get("days_elapsed"), "maturity.days_elapsed")
            or _date_window_days(scope)
            or 0
        )
    total_spend = _non_negative(metrics.get("spend"), "facts.metrics.spend")
    if spend_series:
        total_spend = sum(spend_series)
    current_budget = _non_negative(
        facts.get("daily_budget", legacy.get("current_daily_budget")),
        "facts.daily_budget",
    )
    average_spend = (
        fmean(spend_series)
        if spend_series
        else _safe_ratio(total_spend, float(observation_days))
    )
    target_cpa = _non_negative(
        goal.get("target_cpa", legacy.get("current_target")),
        "goal.target_cpa",
    )
    target_roas = _non_negative(goal.get("target_roas"), "goal.target_roas")
    mature_conversions = _non_negative(
        metrics.get("mature_conversions", maturity.get("conversions_observed")),
        "facts.metrics.mature_conversions",
    )
    mature_revenue = _non_negative(
        metrics.get("mature_revenue", metrics.get("revenue")),
        "facts.metrics.mature_revenue",
    )
    actual_cpa = _non_negative(
        metrics.get("mature_actual_cpa"), "facts.metrics.mature_actual_cpa"
    )
    if actual_cpa is None:
        actual_cpa = _safe_ratio(total_spend, mature_conversions)
    actual_roas = _non_negative(
        metrics.get("mature_actual_roas"), "facts.metrics.mature_actual_roas"
    )
    if actual_roas is None:
        actual_roas = _safe_ratio(mature_revenue, total_spend)
    return {
        "has_numeric_evidence": _has_new_numeric_evidence(case),
        "observation_days": observation_days or None,
        "spend_series": spend_series,
        "event_series": event_series,
        "value_series": value_series,
        "total_spend": total_spend,
        "average_daily_spend": average_spend,
        "current_daily_budget": current_budget,
        "delivery_rate": _safe_ratio(average_spend, current_budget),
        "target_cpa": target_cpa,
        "target_roas": target_roas,
        "mature_actual_cpa": actual_cpa,
        "mature_actual_roas": actual_roas,
        "mature_conversions": mature_conversions,
        "mature_revenue": mature_revenue,
        "maximum_acceptable_cpa": _non_negative(
            goal.get("maximum_acceptable_cpa"),
            "goal.maximum_acceptable_cpa",
        ),
        "minimum_acceptable_roas": _non_negative(
            goal.get("minimum_acceptable_roas"),
            "goal.minimum_acceptable_roas",
        ),
        "daily_budget_cap": _non_negative(
            goal.get("daily_budget_cap"), "goal.daily_budget_cap"
        ),
        "optimization_priority": goal.get("optimization_priority", "balanced"),
        "days_since_last_change": _days_since_last_change(maturity, scope),
        "mature_events_since_change": _non_negative(
            maturity.get("mature_events_since_change"),
            "maturity.mature_events_since_change",
        ),
        "last_change_variables": maturity.get("last_change_variables", []),
        "minimum_days": _non_negative(
            maturity.get("minimum_days", maturity_defaults.get("minimum_days")),
            "maturity.minimum_days",
        ),
        "minimum_conversions": _non_negative(
            maturity.get(
                "minimum_conversions",
                maturity_defaults.get("minimum_mature_events"),
            ),
            "maturity.minimum_conversions",
        ),
        "delay_elapsed": _non_negative(
            maturity.get("conversion_delay_elapsed_days"),
            "maturity.conversion_delay_elapsed_days",
        ),
        "delay_days": _non_negative(
            maturity.get("conversion_delay_days"),
            "maturity.conversion_delay_days",
        ),
    }
