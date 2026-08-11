"""Shared constants, scalar helpers, and policy gates for numeric decisions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ._common import _mapping, _number
from .policy_loader import LoadedPolicy
from .types import ContractError

NUMERIC_DECISION_SCHEMA_VERSION = "1.0"

NORMAL_OPTIMIZATION = "NORMAL_OPTIMIZATION"
STAGED_OPTIMIZATION = "STAGED_OPTIMIZATION"
OPERATIONAL_CORRECTION = "OPERATIONAL_CORRECTION"
EMERGENCY_INTERVENTION = "EMERGENCY_INTERVENTION"

_OPERATION_CLASSIFICATIONS = {
    NORMAL_OPTIMIZATION,
    STAGED_OPTIMIZATION,
    OPERATIONAL_CORRECTION,
    EMERGENCY_INTERVENTION,
}

_MAX_EXPLICIT_STAGED_CHECKPOINTS = 25


def _quantize(value: float, reference: float) -> float:
    step = max(0.01, round(abs(reference) * 0.01, 2))
    quantized = round(value / step) * step
    digits = 2 if step < 1 else 1 if step < 10 else 0
    return round(max(0.0, quantized), digits)


def _change_percent(current: float | None, recommended: float | None) -> float | None:
    if current in {None, 0} or recommended is None:
        return None
    assert current is not None
    return round((recommended - current) / current * 100, 2)


def _policy_values(policy: LoadedPolicy) -> Mapping[str, Any]:
    values = policy.values
    if not isinstance(values, Mapping):
        raise ContractError("loaded numeric policy must be an object")
    return values


def _change_limit_percent(
    policy: LoadedPolicy, *, variable: str, direction: str
) -> float:
    limits = _mapping(_policy_values(policy).get("numeric_change_limits"))
    variable_limits = _mapping(limits.get(variable))
    key = f"normal_max_{direction}_percent"
    value = _number(variable_limits.get(key))
    if value is None or value < 0 or value > 100:
        raise ContractError(
            f"numeric policy numeric_change_limits.{variable}.{key} "
            "must be between 0 and 100"
        )
    return value


def _limit_candidate(
    current: float,
    candidate: float,
    *,
    variable: str,
    direction: str,
    policy: LoadedPolicy,
) -> tuple[float, float, bool]:
    limit_percent = _change_limit_percent(
        policy, variable=variable, direction=direction
    )
    if direction == "increase":
        limit_boundary = current * (1 + limit_percent / 100)
        raw_limited = min(candidate, limit_boundary)
    else:
        limit_boundary = current * (1 - limit_percent / 100)
        raw_limited = max(candidate, limit_boundary)
    capped = not math.isclose(raw_limited, candidate, rel_tol=1e-9, abs_tol=1e-9)
    if not capped:
        return candidate, limit_percent, False
    limited = _quantize(raw_limited, current)
    if direction == "increase":
        limited = min(limited, candidate, limit_boundary)
    else:
        limited = max(limited, candidate, limit_boundary)
    return limited, limit_percent, True


def _stage_review_values(
    policy: LoadedPolicy, review_gate: Mapping[str, Any]
) -> tuple[float | None, float | None]:
    staged = _mapping(_policy_values(policy).get("staged_adjustment"))
    days = _number(review_gate.get("minimum_days"))
    events = _number(review_gate.get("minimum_mature_events"))
    if days is None:
        days = _number(staged.get("review_after_days"))
    if events is None:
        events = _number(staged.get("minimum_mature_events"))
    return days, events


def _review_gate(case: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    review = _mapping(_mapping(case.get("quick_ops")).get("review"))
    return {
        "minimum_days": review.get("after_days") or context.get("minimum_days"),
        "minimum_mature_events": review.get("minimum_additional_mature_events")
        or context.get("minimum_conversions"),
        "conversion_delay_must_be_mature": review.get(
            "conversion_delay_must_be_mature", True
        ),
    }
