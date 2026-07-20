"""Field-level validators shared by the replay evaluation modules."""

from __future__ import annotations

import math
from typing import Any

from .types import ContractError


def _require_bool(document: dict[str, Any], field: str) -> bool:
    value = document.get(field)
    if not isinstance(value, bool):
        raise ContractError(f"{field} must be boolean")
    return value


def _require_text(document: dict[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value


def _non_negative_finite(value: Any, field: str) -> float:
    try:
        finite = math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        finite = False
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not finite
        or value < 0
    ):
        raise ContractError(f"{field} must be a finite non-negative number")
    return float(value)


def _positive_finite(value: Any, field: str) -> float:
    number = _non_negative_finite(value, field)
    if number <= 0:
        raise ContractError(f"{field} must be greater than zero")
    return number


def _optional_non_negative_finite(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _non_negative_finite(value, field)


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ContractError(f"{field} must be boolean or null")
    return value


def _string_list(document: dict[str, Any], field: str) -> list[str]:
    if field not in document:
        raise ContractError(f"{field} is required")
    value = document[field]
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ContractError(f"{field} must be an array of non-empty strings")
    return value


def _contains_finite_numeric_metric(value: Any, field: str) -> bool:
    """Validate nested metric values and report whether numeric evidence exists."""

    if isinstance(value, bool) or value is None or isinstance(value, str):
        return False
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if not finite:
            raise ContractError(f"{field} must contain only finite numeric values")
        return True
    if isinstance(value, dict):
        contains_numeric = False
        for name, child in value.items():
            if not isinstance(name, str) or not name.strip():
                raise ContractError(f"{field} keys must be non-empty strings")
            contains_numeric = (
                _contains_finite_numeric_metric(child, f"{field}.{name}")
                or contains_numeric
            )
        return contains_numeric
    if isinstance(value, list):
        contains_numeric = False
        for index, child in enumerate(value):
            contains_numeric = (
                _contains_finite_numeric_metric(child, f"{field}[{index}]")
                or contains_numeric
            )
        return contains_numeric
    raise ContractError(f"{field} contains an unsupported metric value")


def _positive_policy_minimum_days(uac_input: dict[str, Any]) -> float | None:
    policy = uac_input.get("experiment_policy")
    if not isinstance(policy, dict):
        return None
    value = policy.get("minimum_days")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        return None
    return float(value) if finite and value > 0 else None
