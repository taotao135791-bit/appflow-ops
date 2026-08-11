"""Numeric ground-truth labels and numeric replay evaluation."""

from __future__ import annotations

import math
from typing import Any

from .replay_fields import (
    _optional_bool,
    _optional_non_negative_finite,
    _positive_finite,
    _require_bool,
)
from .types import ContractError

_NUMERIC_DIRECTIONS = {"INCREASE", "DECREASE", "NO_CHANGE"}
_NUMERIC_ACTIONS = _NUMERIC_DIRECTIONS | {"WAIT", "ROLLBACK"}
_NUMERIC_COMPONENTS = {
    "target": (
        "target_recommendation",
        "current_value",
        "recommended_value",
        "recommended_action",
        "bid_decision",
    ),
    "budget": (
        "budget_recommendation",
        "current_daily_budget",
        "recommended_value",
        "recommended_action",
        "budget_decision",
    ),
}

_NUMERIC_EVALUATION_FIELDS = {
    "policy_version",
    "raw_candidate",
    "final_recommendation",
    "human_executed_value",
    "direction_correct",
    "magnitude_error_percent",
    "capped_by_policy",
    "staged_plan_used",
    "rollback_triggered",
    "recommendation_was_too_aggressive",
    "recommendation_was_too_conservative",
    "mature_result_available",
}


def _numeric_evaluation_label(
    evaluation: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate an optional human-reviewed numeric calibration record."""

    if "numeric_evaluation" not in evaluation:
        return None
    value = evaluation["numeric_evaluation"]
    field = "evaluation.yaml numeric_evaluation"
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be an object")
    unknown = sorted(set(value) - _NUMERIC_EVALUATION_FIELDS)
    missing = sorted(_NUMERIC_EVALUATION_FIELDS - set(value))
    if unknown:
        raise ContractError(
            f"{field} contains unsupported fields: " + ", ".join(unknown)
        )
    if missing:
        raise ContractError(f"{field} is missing fields: " + ", ".join(missing))

    policy_version = value.get("policy_version")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ContractError(f"{field}.policy_version must be a non-empty string")
    normalized = {
        "policy_version": policy_version.strip(),
        "raw_candidate": _optional_non_negative_finite(
            value.get("raw_candidate"), f"{field}.raw_candidate"
        ),
        "final_recommendation": _optional_non_negative_finite(
            value.get("final_recommendation"), f"{field}.final_recommendation"
        ),
        "human_executed_value": _optional_non_negative_finite(
            value.get("human_executed_value"), f"{field}.human_executed_value"
        ),
        "direction_correct": _optional_bool(
            value.get("direction_correct"), f"{field}.direction_correct"
        ),
        "magnitude_error_percent": _optional_non_negative_finite(
            value.get("magnitude_error_percent"),
            f"{field}.magnitude_error_percent",
        ),
    }
    for boolean_field in (
        "capped_by_policy",
        "staged_plan_used",
        "rollback_triggered",
        "recommendation_was_too_aggressive",
        "recommendation_was_too_conservative",
        "mature_result_available",
    ):
        normalized[boolean_field] = _require_bool(value, boolean_field)

    if (
        normalized["recommendation_was_too_aggressive"]
        and normalized["recommendation_was_too_conservative"]
    ):
        raise ContractError(
            f"{field} cannot be both too aggressive and too conservative"
        )
    if normalized["capped_by_policy"] and (
        normalized["raw_candidate"] is None
        or normalized["final_recommendation"] is None
    ):
        raise ContractError(
            f"{field} capped_by_policy=true requires raw_candidate and final_recommendation"
        )
    if normalized["staged_plan_used"] and not normalized["capped_by_policy"]:
        raise ContractError(
            f"{field} staged_plan_used=true requires capped_by_policy=true"
        )
    return normalized


def _finalize_numeric_evaluation(
    label: dict[str, Any] | None,
    *,
    accepted_recommendation: bool | None,
    executed: bool,
    confounded: bool,
    deviated: bool,
    unsafe_action: bool,
    maturity_met: bool,
    insufficient_evidence: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """Mask post-result labels unless the recorded recommendation was followed."""

    if label is None:
        return None, False

    normalized = dict(label)
    final_recommendation = normalized["final_recommendation"]
    human_executed_value = normalized["human_executed_value"]
    no_action_recommendation = final_recommendation is None
    recommendation_followed = bool(
        accepted_recommendation is True
        and (
            (no_action_recommendation and not executed and human_executed_value is None)
            or (
                not no_action_recommendation
                and executed
                and human_executed_value is not None
            )
        )
    )
    mature_result_available = bool(
        normalized["mature_result_available"] and maturity_met
    )
    outcome_evaluable = bool(
        recommendation_followed
        and mature_result_available
        and not confounded
        and not deviated
        and not unsafe_action
        and not insufficient_evidence
    )

    normalized["mature_result_available"] = mature_result_available
    if not executed:
        normalized["human_executed_value"] = None
        normalized["staged_plan_used"] = False
        normalized["rollback_triggered"] = False
    if not outcome_evaluable:
        normalized["direction_correct"] = None
        normalized["magnitude_error_percent"] = None
        normalized["recommendation_was_too_aggressive"] = False
        normalized["recommendation_was_too_conservative"] = False
    elif no_action_recommendation:
        normalized["magnitude_error_percent"] = None
        normalized["recommendation_was_too_aggressive"] = False
        normalized["recommendation_was_too_conservative"] = False
    return normalized, outcome_evaluable


def _numeric_ground_truth(before: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the optional numeric replay label without changing legacy cases."""

    if "numeric_ground_truth" not in before:
        return None
    value = before["numeric_ground_truth"]
    if not isinstance(value, dict):
        raise ContractError(
            "snapshot-before.yaml numeric_ground_truth must be an object"
        )
    if not all(isinstance(key, str) and key for key in value):
        raise ContractError("numeric_ground_truth keys must be non-empty strings")
    allowed_root = {"target", "budget", "no_action_expected"}
    unknown_root = sorted(set(value) - allowed_root)
    if unknown_root:
        raise ContractError(
            "numeric_ground_truth contains unsupported fields: "
            + ", ".join(unknown_root)
        )
    declared_components = [
        component for component in _NUMERIC_COMPONENTS if component in value
    ]
    if not declared_components:
        raise ContractError("numeric_ground_truth must define target or budget")
    no_action_expected = value.get("no_action_expected")
    if not isinstance(no_action_expected, bool):
        raise ContractError("numeric_ground_truth.no_action_expected must be boolean")

    normalized: dict[str, Any] = {"no_action_expected": no_action_expected}
    allowed_component = {
        "expected_direction",
        "expected_value",
        "safe_to_recommend",
        "minimum_safe_value",
        "maximum_safe_value",
    }
    for component in declared_components:
        raw = value.get(component)
        field = f"numeric_ground_truth.{component}"
        if not isinstance(raw, dict):
            raise ContractError(f"{field} must be an object")
        if not all(isinstance(key, str) and key for key in raw):
            raise ContractError(f"{field} keys must be non-empty strings")
        unknown = sorted(set(raw) - allowed_component)
        if unknown:
            raise ContractError(
                f"{field} contains unsupported fields: " + ", ".join(unknown)
            )
        direction = raw.get("expected_direction")
        if direction not in _NUMERIC_DIRECTIONS:
            raise ContractError(
                f"{field}.expected_direction must be INCREASE, DECREASE, or NO_CHANGE"
            )
        safe = raw.get("safe_to_recommend")
        if not isinstance(safe, bool):
            raise ContractError(f"{field}.safe_to_recommend must be boolean")
        expected = _positive_finite(
            raw.get("expected_value"), f"{field}.expected_value"
        )
        minimum = _optional_non_negative_finite(
            raw.get("minimum_safe_value"), f"{field}.minimum_safe_value"
        )
        maximum = _optional_non_negative_finite(
            raw.get("maximum_safe_value"), f"{field}.maximum_safe_value"
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ContractError(
                f"{field}.minimum_safe_value must not exceed maximum_safe_value"
            )
        if safe and minimum is not None and expected < minimum:
            raise ContractError(f"{field}.expected_value is below minimum_safe_value")
        if safe and maximum is not None and expected > maximum:
            raise ContractError(f"{field}.expected_value is above maximum_safe_value")
        if not safe and direction != "NO_CHANGE":
            raise ContractError(
                f"{field} must expect NO_CHANGE when safe_to_recommend=false"
            )
        if no_action_expected and (safe or direction != "NO_CHANGE"):
            raise ContractError(
                "numeric_ground_truth.no_action_expected=true requires every "
                "declared component to be unsafe to change and expect NO_CHANGE"
            )
        normalized[component] = {
            "expected_direction": direction,
            "expected_value": expected,
            "safe_to_recommend": safe,
            "minimum_safe_value": minimum,
            "maximum_safe_value": maximum,
        }
    return normalized


def _quick_numeric_recommendation(
    quick_decision: dict[str, Any], component: str
) -> dict[str, Any]:
    (
        section_name,
        current_field,
        recommended_field,
        action_field,
        execution_section_name,
    ) = _NUMERIC_COMPONENTS[component]
    section = quick_decision.get(section_name)
    if not isinstance(section, dict):
        raise ContractError(f"Quick Decision {section_name} must be an object")
    raw_action = section.get(action_field)
    if not isinstance(raw_action, str):
        raise ContractError(
            f"Quick Decision {section_name}.{action_field} must be text"
        )
    action = raw_action.upper()
    if action not in _NUMERIC_ACTIONS:
        raise ContractError(
            f"Quick Decision {section_name}.action must be INCREASE, DECREASE, "
            "NO_CHANGE, WAIT, or ROLLBACK"
        )
    current = _optional_non_negative_finite(
        section.get(current_field), f"Quick Decision {section_name}.{current_field}"
    )
    recommended = _optional_non_negative_finite(
        section.get(recommended_field),
        f"Quick Decision {section_name}.{recommended_field}",
    )
    if action == "ROLLBACK":
        if current is None or recommended is None:
            raise ContractError(
                f"Quick Decision {section_name} ROLLBACK requires current and recommended values"
            )
        if recommended > current:
            direction = "INCREASE"
        elif recommended < current:
            direction = "DECREASE"
        else:
            direction = "NO_CHANGE"
    else:
        direction = "NO_CHANGE" if action == "WAIT" else action
    if direction in {"INCREASE", "DECREASE"}:
        if current is None or recommended is None:
            raise ContractError(
                f"Quick Decision {section_name} numeric change requires current and recommended values"
            )
        if direction == "INCREASE" and recommended <= current:
            raise ContractError(
                f"Quick Decision {section_name} INCREASE conflicts with its values"
            )
        if direction == "DECREASE" and recommended >= current:
            raise ContractError(
                f"Quick Decision {section_name} DECREASE conflicts with its values"
            )
    elif (
        current is not None
        and recommended is not None
        and not math.isclose(current, recommended, rel_tol=1e-9, abs_tol=1e-9)
    ):
        raise ContractError(
            f"Quick Decision {section_name} NO_CHANGE conflicts with its values"
        )
    execution_section = quick_decision.get(execution_section_name)
    if not isinstance(execution_section, dict):
        raise ContractError(
            f"Quick Decision {execution_section_name} must be an object"
        )
    execution_action = execution_section.get("action")
    if not isinstance(execution_action, str):
        raise ContractError(
            f"Quick Decision {execution_section_name}.action must be text"
        )
    normalized_execution_action = execution_action.upper()
    if normalized_execution_action not in _NUMERIC_ACTIONS:
        raise ContractError(
            f"Quick Decision {execution_section_name}.action must be INCREASE, "
            "DECREASE, NO_CHANGE, WAIT, or ROLLBACK"
        )
    return {
        "direction": direction,
        "action": action,
        "execution_action": normalized_execution_action,
        "current_value": current,
        "recommended_value": recommended,
        "effective_value": recommended if recommended is not None else current,
    }


def _evaluate_numeric_replay(
    ground_truth: dict[str, Any],
    quick_decision: dict[str, Any],
    *,
    accepted_recommendation: bool | None,
    executed: bool,
    confounded: bool,
    deviated: bool,
    mature_result_available: bool,
    business_result_evaluable: bool,
) -> dict[str, Any]:
    policy_set = quick_decision.get("policy")
    if not isinstance(policy_set, dict):
        raise ContractError("Quick Decision policy must be an object")
    numeric_policy = policy_set.get("numeric")
    signal_policy = policy_set.get("signal")
    if not isinstance(numeric_policy, dict) or not isinstance(signal_policy, dict):
        raise ContractError("Quick Decision must record numeric and signal policies")
    numeric_policy_version = numeric_policy.get("policy_version")
    signal_policy_version = signal_policy.get("policy_version")
    if not isinstance(numeric_policy_version, str) or not numeric_policy_version:
        raise ContractError("Quick Decision numeric policy_version is required")
    if not isinstance(signal_policy_version, str) or not signal_policy_version:
        raise ContractError("Quick Decision signal policy_version is required")
    system = {
        component: _quick_numeric_recommendation(quick_decision, component)
        for component in _NUMERIC_COMPONENTS
    }
    component_evaluations: dict[str, dict[str, Any]] = {}
    raw_direction_matches: list[bool] = []
    raw_magnitude_errors: list[float] = []
    unsafe_components: list[str] = []

    for component in (item for item in _NUMERIC_COMPONENTS if item in ground_truth):
        recommendation = system[component]
        label = ground_truth[component]
        current = recommendation["current_value"]
        effective = recommendation["effective_value"]
        expected = label["expected_value"]
        if current is None or effective is None:
            raise ContractError(
                f"numeric_ground_truth.{component} requires a current numeric account value"
            )
        expected_direction = label["expected_direction"]
        if expected_direction == "INCREASE" and expected <= current:
            raise ContractError(
                f"numeric_ground_truth.{component} INCREASE conflicts with expected_value"
            )
        if expected_direction == "DECREASE" and expected >= current:
            raise ContractError(
                f"numeric_ground_truth.{component} DECREASE conflicts with expected_value"
            )
        if expected_direction == "NO_CHANGE" and not math.isclose(
            expected, current, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise ContractError(
                f"numeric_ground_truth.{component} NO_CHANGE conflicts with expected_value"
            )

        changes_value = recommendation["direction"] != "NO_CHANGE"
        below_minimum = bool(
            changes_value
            and label["minimum_safe_value"] is not None
            and effective < label["minimum_safe_value"]
        )
        above_maximum = bool(
            changes_value
            and label["maximum_safe_value"] is not None
            and effective > label["maximum_safe_value"]
        )
        unsafe = bool(
            changes_value
            and (not label["safe_to_recommend"] or below_minimum or above_maximum)
        )
        if unsafe:
            unsafe_components.append(component)
        direction_matches = recommendation["direction"] == expected_direction
        magnitude_error = abs(effective - expected) / expected * 100
        raw_direction_matches.append(direction_matches)
        raw_magnitude_errors.append(magnitude_error)
        component_evaluations[component] = {
            "expected_direction": expected_direction,
            "expected_value": expected,
            "safe_to_recommend": label["safe_to_recommend"],
            "direction_correct": (
                direction_matches if business_result_evaluable else None
            ),
            "absolute_percentage_error": (
                round(magnitude_error, 4) if business_result_evaluable else None
            ),
            "unsafe": unsafe,
        }

    any_numeric_change = any(
        item["direction"] != "NO_CHANGE" for item in system.values()
    )
    no_action_expected = ground_truth["no_action_expected"]
    no_action_correct = not any_numeric_change if no_action_expected else None
    unsafe_numeric = bool(
        unsafe_components or (no_action_expected and any_numeric_change)
    )
    direction_correct = (
        all(raw_direction_matches) if business_result_evaluable else None
    )
    magnitude_error = (
        sum(raw_magnitude_errors) / len(raw_magnitude_errors)
        if business_result_evaluable
        else None
    )
    return {
        "ground_truth_present": True,
        "policy": {
            "numeric_policy_version": numeric_policy_version,
            "signal_policy_version": signal_policy_version,
        },
        "system_recommendation": system,
        "human_decision": {
            "accepted_system_recommendation": accepted_recommendation,
        },
        "after": {
            "executed": executed,
            "confounded": confounded,
            "deviated": deviated,
            "mature_result_available": mature_result_available,
        },
        "evaluation": {
            "business_result_evaluable": business_result_evaluable,
            "direction_correct": direction_correct,
            "magnitude_error": (
                round(magnitude_error, 4) if magnitude_error is not None else None
            ),
            "unsafe_numeric_recommendation": unsafe_numeric,
            "unsafe_components": unsafe_components,
            "no_action_expected": no_action_expected,
            "no_action_correct": no_action_correct,
            "components": component_evaluations,
        },
        "ground_truth": ground_truth,
    }
