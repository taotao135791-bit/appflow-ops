"""Campaign-level and structure decisions for Quick Ops."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import _mapping
from .quick_ops_base import (
    _LEVEL_SUFFIX,
    _level,
    _permission_block,
    _permission_for,
    _permission_request,
    _unique,
)
from .quick_ops_gates import _candidate_event_gate, _split_gate, _value_gate


def _same_level_structure(
    case: dict[str, Any], quick: Mapping[str, Any]
) -> dict[str, Any]:
    structure = _mapping(quick.get("structure"))
    split_state, split_blocked, split_unknown = _split_gate(quick)
    duplicate_reason = str(structure.get("duplicate_reason", ""))
    restart_only = duplicate_reason in {
        "restart_learning",
        "recent_performance_drop",
        "try_again",
    }
    isolation_reasons = [
        field
        for field in (
            "independent_geo_required",
            "independent_os_required",
            "independent_budget_required",
            "different_user_hypothesis",
            "different_audience_required",
            "client_attribution_isolation_required",
        )
        if structure.get(field) is True
    ]
    same_semantics = structure.get("same_semantics") is True or all(
        structure.get(field) is True
        for field in (
            "same_optimization_event",
            "same_geo",
            "same_os",
            "same_bid_strategy",
            "same_business_goal",
        )
    )
    create_permission = _permission_for(case, "campaign_create")
    client_requests: list[str] = []
    reasons: list[str] = []
    data_gaps: list[str] = []

    if restart_only:
        action = "DO_NOT_DUPLICATE"
        reasons.append("duplicate_only_to_restart_learning")
    elif isolation_reasons and split_state == "ready":
        if create_permission != "OPTIMIZER_CAN_EXECUTE":
            action = (
                "REQUEST_CLIENT_APPROVAL"
                if create_permission == "CLIENT_APPROVAL_REQUIRED"
                else "WAIT"
            )
            reasons.append("campaign_create_not_immediately_executable")
            client_requests.append(
                _permission_request("campaign_create", create_permission)
            )
        elif (
            structure.get("controlled_test_required") is True
            and structure.get("experiment_admission_ready") is True
            and structure.get("traffic_isolation_ready") is True
        ):
            action = "DUPLICATE_FOR_CONTROLLED_TEST"
            reasons.append("controlled_test_isolation_ready")
        else:
            action = "CREATE_NEW_SAME_LEVEL"
            reasons.append("independent_structure_is_required")
    elif same_semantics and structure.get("new_assets_only") is True:
        action = "ADD_TO_EXISTING"
        reasons.append("new_assets_share_existing_campaign_semantics")
    elif split_state == "blocked":
        action = "DO_NOT_DUPLICATE"
        reasons.extend(split_blocked)
    elif isolation_reasons and split_state == "unknown":
        action = "WAIT"
        reasons.append("split_capacity_not_proven")
        data_gaps.extend(split_unknown)
    else:
        action = "DO_NOT_DUPLICATE"
        reasons.append("no_independent_campaign_reason")

    if structure.get("controlled_test_required") is True and action not in {
        "DUPLICATE_FOR_CONTROLLED_TEST"
    }:
        reasons.append("not_a_valid_experiment")
    return {
        "action": action,
        "create_new_campaign": action
        in {"CREATE_NEW_SAME_LEVEL", "DUPLICATE_FOR_CONTROLLED_TEST"},
        "run_in_parallel": action
        in {"CREATE_NEW_SAME_LEVEL", "DUPLICATE_FOR_CONTROLLED_TEST"},
        "permission": create_permission,
        "reason_codes": _unique(reasons),
        "data_gaps": _unique(data_gaps),
        "client_requests": _unique(client_requests),
    }


def _keep_verdict(level: str | None, *, adjust: bool = False) -> str:
    if level is None:
        return "INSUFFICIENT_EVIDENCE"
    action = "ADJUST" if adjust else "CONTINUE"
    return f"{action}_CURRENT_{_LEVEL_SUFFIX[level]}"


def _level_decision(
    case: dict[str, Any],
    quick: Mapping[str, Any],
    analysis: Mapping[str, Any],
    current: str | None,
    candidate: str | None,
    terminology: Mapping[str, Any],
    question_type: str,
    numeric: Mapping[str, Any],
) -> dict[str, Any]:
    gaps: list[str] = []
    client_requests: list[str] = []
    structure = {
        "action": "ADJUST_EXISTING",
        "create_new_campaign": False,
        "run_in_parallel": False,
        "permission": "INSUFFICIENT_EVIDENCE",
        "reason_codes": [],
        "data_gaps": [],
        "client_requests": [],
    }
    if current is None:
        return {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "recommended": None,
            "action": "wait",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["current_campaign_level_unknown"],
            "data_gaps": ["current campaign level and actual account settings"],
            "client_requests": [],
        }

    signals = _mapping(quick.get("signals"))
    rollback = _mapping(quick.get("rollback"))
    if signals.get("rollback_triggered") is True:
        baseline = _level(rollback.get("baseline_level"))
        rollback_verdict = None
        if current == "AC2.5" and baseline == "AC2.0":
            rollback_verdict = "ROLL_BACK_TO_AC20"
        elif current == "AC3.0" and baseline == "AC2.5":
            rollback_verdict = "ROLL_BACK_TO_AC25"
        if rollback_verdict is not None:
            permission_block = _permission_block(
                case, ("optimization_event", "bid_strategy")
            )
            if permission_block is not None:
                permission_action, permission, requests = permission_block
                return {
                    "verdict": _keep_verdict(current),
                    "recommended": current,
                    "action": "keep",
                    "structure": {
                        **structure,
                        "action": permission_action,
                        "permission": permission,
                        "reason_codes": ["level_migration_requires_permission"],
                        "client_requests": requests,
                    },
                    "reason_codes": ["level_change_not_immediately_executable"],
                    "data_gaps": [],
                    "client_requests": requests,
                }
            return {
                "verdict": rollback_verdict,
                "recommended": baseline,
                "action": "rollback",
                "structure": structure,
                "reason_codes": ["predeclared_rollback_triggered"],
                "data_gaps": [],
                "client_requests": [],
            }
        gaps.append("known stable rollback baseline")

    permission_profile = quick.get("permission_profile")
    if (
        permission_profile == "android_editable_ios_locked"
        and _mapping(case.get("facts")).get("segmentation_complete") is not True
    ):
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["os_level_segmentation_incomplete"],
            "data_gaps": ["OS-segmented campaign and conversion evidence"],
            "client_requests": ["request OS-segmented campaign evidence"],
        }
    if permission_profile == "aggregate_data_only":
        return {
            "verdict": "INSUFFICIENT_EVIDENCE",
            "recommended": current,
            "action": "keep",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["aggregate_data_cannot_support_campaign_action"],
            "data_gaps": ["campaign, OS, event, and asset-level evidence"],
            "client_requests": [],
        }
    if (
        permission_profile == "mmp_access_without_backend_access"
        and candidate == "AC3.0"
    ):
        return {
            "verdict": "WAIT_FOR_VALUE_SIGNAL",
            "recommended": current,
            "action": "wait",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["backend_value_reconciliation_missing"],
            "data_gaps": ["backend value reconciliation"],
            "client_requests": ["request backend value reconciliation"],
        }

    active_experiment = any(
        isinstance(item, Mapping) and item.get("active", True)
        for item in analysis.get("experiment_reviews", [])
        if isinstance(item, Mapping)
    )
    urgent = _mapping(quick.get("operational")).get("urgent_confirmed") is True
    if active_experiment and not urgent:
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["unfinished_experiment_blocks_stacked_change"],
            "data_gaps": ["close or mature the current experiment first"],
            "client_requests": [],
        }

    constraint = _mapping(numeric.get("constraint_analysis"))
    numeric_evidence = constraint.get("has_numeric_evidence") is True
    if (
        candidate is not None
        and candidate != current
        and numeric_evidence
        and constraint.get("maturity_state") != "MATURE"
    ):
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "wait",
            "structure": {
                **structure,
                "action": "WAIT",
                "reason_codes": ["numeric_data_not_mature_precedes_level_change"],
            },
            "reason_codes": ["numeric_data_not_mature_precedes_level_change"],
            "data_gaps": ["mature numeric evidence after the latest change"],
            "client_requests": [],
        }
    if (
        candidate is not None
        and candidate != current
        and constraint.get("target_state") == "TARGET_LIKELY_TOO_TIGHT"
    ):
        return {
            "verdict": _keep_verdict(current, adjust=True),
            "recommended": current,
            "action": "keep",
            "structure": {
                **structure,
                "action": "ADJUST_EXISTING",
                "reason_codes": ["target_constraint_precedes_level_change"],
            },
            "reason_codes": ["target_constraint_precedes_level_change"],
            "data_gaps": [],
            "client_requests": [],
        }

    if question_type == "same_level_campaign" or candidate == current:
        structure = _same_level_structure(case, quick)
        action = structure["action"]
        if action in {"CREATE_NEW_SAME_LEVEL", "DUPLICATE_FOR_CONTROLLED_TEST"}:
            verdict = f"CREATE_NEW_{_LEVEL_SUFFIX[current]}"
        elif action == "ADJUST_EXISTING":
            verdict = _keep_verdict(current, adjust=True)
        else:
            verdict = _keep_verdict(current)
        return {
            "verdict": verdict,
            "recommended": current,
            "action": "keep" if not structure["create_new_campaign"] else "create",
            "structure": structure,
            "reason_codes": structure["reason_codes"],
            "data_gaps": structure["data_gaps"],
            "client_requests": structure["client_requests"],
        }

    if candidate is None:
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": structure,
            "reason_codes": ["no_level_change_requested"],
            "data_gaps": [],
            "client_requests": [],
        }

    if terminology.get("confirmation_required") is True:
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["campaign_level_mapping_confirmation_required"],
            "data_gaps": ["confirmed project meaning for the requested AC level"],
            "client_requests": [],
        }

    external = _mapping(quick.get("external_checks"))
    material_external = [
        str(name)
        for name, value in external.items()
        if value is True or value == "material_issue"
    ]
    if material_external:
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": {**structure, "action": "WAIT"},
            "reason_codes": ["material_external_issue_blocks_level_change"],
            "data_gaps": [
                f"resolve external issue: {name}" for name in material_external
            ],
            "client_requests": [],
        }

    if current == "AC2.0" and candidate == "AC2.5":
        gate, blocked, unknown = _candidate_event_gate(quick, analysis)
        if gate == "blocked":
            verdict = (
                "WAIT_FOR_MORE_DEEP_EVENTS"
                if any(
                    "volume_assessment" in reason or "delay_mature" in reason
                    for reason in blocked
                )
                else "DO_NOT_START_AC25"
            )
            return {
                "verdict": verdict,
                "recommended": current,
                "action": "wait" if verdict.startswith("WAIT") else "keep",
                "structure": {**structure, "action": "WAIT"},
                "reason_codes": blocked,
                "data_gaps": unknown,
                "client_requests": [],
            }
        if gate == "unknown":
            return {
                "verdict": "WAIT_FOR_MORE_DEEP_EVENTS",
                "recommended": current,
                "action": "wait",
                "structure": {**structure, "action": "WAIT"},
                "reason_codes": ["candidate_deep_event_not_ready"],
                "data_gaps": unknown,
                "client_requests": [],
            }
        return _admit_level_change(
            case,
            quick,
            current=current,
            candidate=candidate,
            parallel_verdict="KEEP_AC20_AND_TEST_AC25",
            move_verdict="MOVE_AC20_TO_AC25",
            do_not_verdict="DO_NOT_START_AC25",
        )

    if current == "AC2.5" and candidate == "AC3.0":
        gate, blocked, unknown = _value_gate(
            quick, analysis, _mapping(quick.get("candidate_campaign"))
        )
        if gate == "blocked":
            soft_wait_reasons = {
                "value_signal_delay_mature_failed",
                "value_signal_volume_assessment_failed",
                "value_signal_stability_assessment_failed",
            }
            waits_for_signal = bool(blocked) and set(blocked).issubset(
                soft_wait_reasons
            )
            return {
                "verdict": (
                    "WAIT_FOR_VALUE_SIGNAL" if waits_for_signal else "DO_NOT_START_AC30"
                ),
                "recommended": current,
                "action": "wait" if waits_for_signal else "keep",
                "structure": {**structure, "action": "WAIT"},
                "reason_codes": blocked,
                "data_gaps": unknown,
                "client_requests": [],
            }
        if gate == "unknown":
            return {
                "verdict": "WAIT_FOR_VALUE_SIGNAL",
                "recommended": current,
                "action": "wait",
                "structure": {**structure, "action": "WAIT"},
                "reason_codes": ["value_signal_not_ready"],
                "data_gaps": unknown,
                "client_requests": [],
            }
        return _admit_level_change(
            case,
            quick,
            current=current,
            candidate=candidate,
            parallel_verdict="KEEP_AC25_AND_TEST_AC30",
            move_verdict="MOVE_AC25_TO_AC30",
            do_not_verdict="DO_NOT_START_AC30",
        )

    if current == "AC3.0":
        gate, blocked, unknown = _value_gate(
            quick, analysis, _mapping(quick.get("current_campaign"))
        )
        if gate == "blocked" and _level(rollback.get("baseline_level")) == "AC2.5":
            verdict = "ROLL_BACK_TO_AC25"
            recommended = "AC2.5"
        elif gate == "blocked":
            verdict = "ADJUST_CURRENT_AC30"
            recommended = current
            gaps.append("known stable AC2.5 rollback baseline")
        elif gate == "unknown":
            verdict = "WAIT_FOR_VALUE_SIGNAL"
            recommended = current
        else:
            verdict = "CONTINUE_CURRENT_AC30"
            recommended = current
        if verdict == "ROLL_BACK_TO_AC25":
            permission_block = _permission_block(
                case, ("optimization_event", "bid_strategy")
            )
            if permission_block is not None:
                structure_action, permission, requests = permission_block
                verdict = _keep_verdict(current)
                recommended = current
                structure = {
                    **structure,
                    "action": structure_action,
                    "permission": permission,
                    "reason_codes": ["level_migration_requires_permission"],
                    "client_requests": requests,
                }
                client_requests.extend(requests)
                blocked.append("level_change_not_immediately_executable")
        return {
            "verdict": verdict,
            "recommended": recommended,
            "action": "rollback" if verdict.startswith("ROLL_BACK") else "keep",
            "structure": structure,
            "reason_codes": blocked or ["current_ac30_value_gate_ready"],
            "data_gaps": _unique([*unknown, *gaps]),
            "client_requests": client_requests,
        }

    return {
        "verdict": _keep_verdict(current),
        "recommended": current,
        "action": "keep",
        "structure": {**structure, "action": "WAIT"},
        "reason_codes": ["unsupported_or_unconfirmed_level_transition"],
        "data_gaps": ["account-specific transition evidence"],
        "client_requests": [],
    }


def _admit_level_change(
    case: dict[str, Any],
    quick: Mapping[str, Any],
    *,
    current: str,
    candidate: str,
    parallel_verdict: str,
    move_verdict: str,
    do_not_verdict: str,
) -> dict[str, Any]:
    current_campaign = _mapping(quick.get("current_campaign"))
    transition = _mapping(quick.get("transition"))
    split_state, split_blocked, split_unknown = _split_gate(quick)
    create_permission = _permission_for(case, "campaign_create")
    event_permission = _permission_for(case, "optimization_event")
    strategy_permission = _permission_for(case, "bid_strategy")
    current_healthy = current_campaign.get("healthy")
    direct_ready = all(
        transition.get(field) is True
        for field in (
            "direct_migration_safe",
            "single_campaign_learning_ready",
            "rollback_baseline_available",
        )
    )
    current_misaligned = (
        current_campaign.get("healthy") is False
        or current_campaign.get("goal_misaligned") is True
    )

    if split_state == "ready" and current_healthy is not False:
        if create_permission == "OPTIMIZER_CAN_EXECUTE":
            return {
                "verdict": parallel_verdict,
                "recommended": candidate,
                "action": "parallel_test",
                "structure": {
                    "action": "CREATE_NEW_CANDIDATE_LEVEL",
                    "create_new_campaign": True,
                    "run_in_parallel": True,
                    "permission": create_permission,
                    "reason_codes": ["split_budget_and_event_volume_are_sufficient"],
                    "data_gaps": [],
                    "client_requests": [],
                },
                "reason_codes": ["keep_healthy_baseline_while_testing_deeper_level"],
                "data_gaps": [],
                "client_requests": [],
            }
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": {
                "action": (
                    "REQUEST_CLIENT_APPROVAL"
                    if create_permission == "CLIENT_APPROVAL_REQUIRED"
                    else "WAIT"
                ),
                "create_new_campaign": False,
                "run_in_parallel": False,
                "permission": create_permission,
                "reason_codes": ["candidate_campaign_requires_permission"],
                "data_gaps": [],
                "client_requests": [
                    _permission_request("campaign_create", create_permission)
                ],
            },
            "reason_codes": ["level_change_not_immediately_executable"],
            "data_gaps": [],
            "client_requests": [
                _permission_request("campaign_create", create_permission)
            ],
        }

    if current_misaligned and direct_ready:
        required = {
            "optimization_event": event_permission,
            "bid_strategy": strategy_permission,
        }
        blocked_permissions = {
            name: value
            for name, value in required.items()
            if value != "OPTIMIZER_CAN_EXECUTE"
        }
        if not blocked_permissions:
            return {
                "verdict": move_verdict,
                "recommended": candidate,
                "action": "move",
                "structure": {
                    "action": "ADJUST_EXISTING",
                    "create_new_campaign": False,
                    "run_in_parallel": False,
                    "permission": "OPTIMIZER_CAN_EXECUTE",
                    "reason_codes": ["direct_migration_gate_ready"],
                    "data_gaps": [],
                    "client_requests": [],
                },
                "reason_codes": ["current_level_misaligned_and_migration_safe"],
                "data_gaps": [],
                "client_requests": [],
            }
        requests = [
            _permission_request(name, value)
            for name, value in blocked_permissions.items()
        ]
        return {
            "verdict": _keep_verdict(current),
            "recommended": current,
            "action": "keep",
            "structure": {
                "action": (
                    "REQUEST_CLIENT_APPROVAL"
                    if any(
                        value == "CLIENT_APPROVAL_REQUIRED"
                        for value in blocked_permissions.values()
                    )
                    else "WAIT"
                ),
                "create_new_campaign": False,
                "run_in_parallel": False,
                "permission": next(iter(blocked_permissions.values())),
                "reason_codes": ["level_migration_requires_permission"],
                "data_gaps": [],
                "client_requests": requests,
            },
            "reason_codes": ["level_change_not_immediately_executable"],
            "data_gaps": [],
            "client_requests": requests,
        }

    reasons = split_blocked or ["healthy_current_campaign_should_not_be_closed"]
    gaps = split_unknown
    return {
        "verdict": do_not_verdict
        if split_state == "blocked"
        else _keep_verdict(current),
        "recommended": current,
        "action": "keep",
        "structure": {
            "action": "DO_NOT_DUPLICATE" if split_state == "blocked" else "WAIT",
            "create_new_campaign": False,
            "run_in_parallel": False,
            "permission": create_permission,
            "reason_codes": reasons,
            "data_gaps": gaps,
            "client_requests": [],
        },
        "reason_codes": reasons,
        "data_gaps": gaps,
        "client_requests": [],
    }
