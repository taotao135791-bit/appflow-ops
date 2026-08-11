"""Constants, input validation, and permission gates for Quick Ops decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import _finite_number, _mapping
from .engine import _permission_class
from .terminology import canonical_campaign_level
from .types import ContractError

QUICK_DECISION_SCHEMA_VERSION = "1.0"

CAMPAIGN_VERDICTS = {
    "CONTINUE_CURRENT_AC20",
    "ADJUST_CURRENT_AC20",
    "CREATE_NEW_AC20",
    "CONTINUE_CURRENT_AC25",
    "ADJUST_CURRENT_AC25",
    "CREATE_NEW_AC25",
    "CONTINUE_CURRENT_AC30",
    "ADJUST_CURRENT_AC30",
    "CREATE_NEW_AC30",
    "MOVE_AC20_TO_AC25",
    "MOVE_AC25_TO_AC30",
    "KEEP_AC20_AND_TEST_AC25",
    "KEEP_AC25_AND_TEST_AC30",
    "DO_NOT_START_AC25",
    "DO_NOT_START_AC30",
    "ROLL_BACK_TO_AC20",
    "ROLL_BACK_TO_AC25",
    "WAIT_FOR_MORE_DEEP_EVENTS",
    "WAIT_FOR_VALUE_SIGNAL",
    "INSUFFICIENT_EVIDENCE",
}

STRUCTURE_ACTIONS = {
    "ADD_TO_EXISTING",
    "ADJUST_EXISTING",
    "CREATE_NEW_SAME_LEVEL",
    "CREATE_NEW_CANDIDATE_LEVEL",
    "DUPLICATE_FOR_CONTROLLED_TEST",
    "DO_NOT_DUPLICATE",
    "REQUEST_CLIENT_APPROVAL",
    "WAIT",
}

CREATIVE_ACTIONS = {
    "KEEP_RUNNING",
    "RUN_WITH_LIMIT",
    "WAIT_FOR_MATURITY",
    "REDUCE_EXPOSURE",
    "PAUSE",
    "REPLACE",
    "RETEST",
    "INSUFFICIENT_DATA",
}

_LEVEL_SUFFIX = {"AC2.0": "AC20", "AC2.5": "AC25", "AC3.0": "AC30"}
_PROFILE_PERMISSION: dict[str, dict[str, str]] = {
    "read_only": {"*": "NOT_ACTIONABLE"},
    "creative_only": {
        "creative": "OPTIMIZER_CAN_EXECUTE",
        "creative_add": "OPTIMIZER_CAN_EXECUTE",
        "creative_remove": "OPTIMIZER_CAN_EXECUTE",
        "*": "NOT_ACTIONABLE",
    },
    "creative_permission_but_no_new_assets": {
        "creative": "OPTIMIZER_CAN_EXECUTE",
        "creative_add": "NOT_ACTIONABLE",
        "creative_remove": "OPTIMIZER_CAN_EXECUTE",
        "*": "NOT_ACTIONABLE",
    },
    "budget_only": {"budget": "OPTIMIZER_CAN_EXECUTE", "*": "NOT_ACTIONABLE"},
    "bid_only": {
        "bid": "OPTIMIZER_CAN_EXECUTE",
        "bid_strategy": "OPTIMIZER_CAN_EXECUTE",
        "*": "NOT_ACTIONABLE",
    },
    "campaign_create_only_with_approval": {
        "campaign_create": "CLIENT_APPROVAL_REQUIRED"
    },
    "event_change_requires_client": {"optimization_event": "CLIENT_APPROVAL_REQUIRED"},
    "all_changes_require_client_approval": {"*": "CLIENT_APPROVAL_REQUIRED"},
    "aggregate_data_only": {"*": "NOT_ACTIONABLE"},
    "campaign_locked_asset_editable": {
        "creative": "OPTIMIZER_CAN_EXECUTE",
        "creative_add": "OPTIMIZER_CAN_EXECUTE",
        "creative_remove": "OPTIMIZER_CAN_EXECUTE",
        "campaign_create": "PLATFORM_LIMITATION",
        "optimization_event": "PLATFORM_LIMITATION",
        "budget": "PLATFORM_LIMITATION",
        "bid": "PLATFORM_LIMITATION",
    },
    "cannot_change_optimization_event": {"optimization_event": "PLATFORM_LIMITATION"},
    "cannot_create_new_campaign": {"campaign_create": "PLATFORM_LIMITATION"},
}


def _non_negative_or_none(value: Any) -> bool:
    return value is None or (_finite_number(value) and value >= 0)


def _level(value: Any) -> str | None:
    return canonical_campaign_level(value)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _validate_quick_input(case: Mapping[str, Any]) -> None:
    quick = case.get("quick_ops", {})
    if not isinstance(quick, Mapping):
        raise ContractError("quick_ops must be an object")
    glossary = case.get("campaign_level_glossary", {})
    if not isinstance(glossary, Mapping):
        raise ContractError("campaign_level_glossary must be an object")
    for key, definition in glossary.items():
        if _level(str(key)) is None:
            raise ContractError(
                f"campaign_level_glossary.{key} is not a supported AC label"
            )
        if not isinstance(definition, Mapping):
            raise ContractError(f"campaign_level_glossary.{key} must be an object")
    for field in (
        "current_campaign",
        "candidate_campaign",
        "candidate_event",
        "value_signal",
        "split_capacity",
        "structure",
        "creative",
        "bid_budget",
        "operational",
        "review",
        "rollback",
        "external_checks",
    ):
        if field in quick and not isinstance(quick[field], Mapping):
            raise ContractError(f"quick_ops.{field} must be an object")
    for container_name in ("current_campaign", "candidate_campaign"):
        container = _mapping(quick.get(container_name))
        if "level" in container and _level(container.get("level")) is None:
            raise ContractError(
                f"quick_ops.{container_name}.level must be AC2.0, AC2.5, or AC3.0"
            )
    if "candidate_level" in quick and _level(quick.get("candidate_level")) is None:
        raise ContractError("quick_ops.candidate_level must be a campaign-level label")
    for container_name in ("review", "bid_budget", "creative"):
        container = _mapping(quick.get(container_name))
        for name, value in container.items():
            if (
                any(
                    marker in str(name)
                    for marker in (
                        "days",
                        "events",
                        "spend",
                        "budget",
                        "target",
                        "value",
                    )
                )
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                if not _non_negative_or_none(value):
                    raise ContractError(
                        f"quick_ops.{container_name}.{name} must be a finite non-negative number"
                    )
    if "question" in quick and not isinstance(quick["question"], str):
        raise ContractError("quick_ops.question must be text")
    profile = quick.get("permission_profile")
    if profile is not None and not isinstance(profile, str):
        raise ContractError("quick_ops.permission_profile must be text")


def _permission_request(variable: str, classification: str) -> str:
    if classification == "CLIENT_APPROVAL_REQUIRED":
        return f"request client approval for {variable}"
    if classification == "CLIENT_DATA_REQUIRED":
        return f"request client data for {variable}"
    if classification == "PLATFORM_LIMITATION":
        return f"confirm platform capability for {variable}"
    if classification == "NOT_ACTIONABLE":
        return f"keep {variable} unchanged because it is not actionable"
    return f"confirm permission for {variable}"


def _permission_for(case: dict[str, Any], variable: str) -> str:
    quick = _mapping(case.get("quick_ops"))
    profile = quick.get("permission_profile")
    profile_map = _PROFILE_PERMISSION.get(str(profile), {})
    if variable in profile_map:
        return profile_map[variable]
    if "*" in profile_map:
        return profile_map["*"]
    if profile == "android_editable_ios_locked":
        if _mapping(case.get("facts")).get("segmentation_complete") is not True:
            return "NOT_ACTIONABLE"
        os_name = str(
            _mapping(quick.get("current_campaign")).get("os")
            or _mapping(case.get("scope")).get("os", "")
        ).lower()
        if os_name == "android":
            return "OPTIMIZER_CAN_EXECUTE"
        return "PLATFORM_LIMITATION"
    classification = _permission_class(case, variable)
    if (
        variable in {"creative_add", "creative_remove"}
        and classification == "INSUFFICIENT_EVIDENCE"
    ):
        return _permission_class(case, "creative")
    return classification


def _permission_block(
    case: dict[str, Any], variables: tuple[str, ...]
) -> tuple[str, str, list[str]] | None:
    blocked: dict[str, str] = {}
    for variable in variables:
        classification = _permission_for(case, variable)
        if classification != "OPTIMIZER_CAN_EXECUTE":
            blocked[variable] = classification
    if not blocked:
        return None
    action = (
        "REQUEST_CLIENT_APPROVAL"
        if any(value == "CLIENT_APPROVAL_REQUIRED" for value in blocked.values())
        else "WAIT"
    )
    requests = [
        _permission_request(variable, classification)
        for variable, classification in blocked.items()
    ]
    return action, next(iter(blocked.values())), requests


def _tri_state_gate(
    source: Mapping[str, Any],
    *,
    true_fields: tuple[str, ...],
    enum_fields: Mapping[str, str],
    prefix: str,
) -> tuple[str, list[str], list[str]]:
    blocked: list[str] = []
    unknown: list[str] = []
    for field in true_fields:
        value = source.get(field)
        if value is False:
            blocked.append(f"{prefix}_{field}_failed")
        elif value is not True and value != "not_applicable":
            unknown.append(f"{prefix}_{field}_unknown")
    for field, expected in enum_fields.items():
        value = source.get(field)
        if value is None or value == "unknown":
            unknown.append(f"{prefix}_{field}_unknown")
        elif value != expected:
            blocked.append(f"{prefix}_{field}_failed")
    if blocked:
        return "blocked", blocked, unknown
    if unknown:
        return "unknown", blocked, unknown
    return "ready", blocked, unknown
