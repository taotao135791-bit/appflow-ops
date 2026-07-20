"""Creative, bid/budget, operational, review, and rollback decisions."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ._common import _finite_number, _mapping
from .quick_ops_base import (
    _level,
    _permission_for,
    _permission_request,
    _unique,
)


def _creative_decision(
    case: dict[str, Any],
    quick: Mapping[str, Any],
    structure_action: str,
    question_type: str,
) -> dict[str, Any]:
    creative = _mapping(quick.get("creative"))
    permission = _permission_for(case, "creative")
    add_permission = _permission_for(case, "creative_add")
    reasons: list[str] = []
    requests: list[str] = []
    gaps: list[str] = []

    if creative.get("asset_grain_available") is False:
        action = "INSUFFICIENT_DATA"
        reasons.append("asset_level_mature_cohort_missing")
    elif creative.get("new_asset") is True and creative.get("mature") is not True:
        action = "WAIT_FOR_MATURITY"
        reasons.append("creative_conversion_delay_or_volume_not_mature")
    elif creative.get("guardrail_breached") is True:
        if creative.get("replacement_available") is True:
            action = "REPLACE"
        else:
            action = "REDUCE_EXPOSURE"
        reasons.append("mature_creative_guardrail_breached")
    elif creative.get("fatigued") is True:
        action = (
            "REPLACE"
            if creative.get("replacement_available") is True
            else "REDUCE_EXPOSURE"
        )
        reasons.append("creative_fatigue_detected")
    elif creative.get("lowest_cpi_worst_payment_rate") is True:
        action = (
            "REPLACE"
            if creative.get("replacement_available") is True
            else "RUN_WITH_LIMIT"
        )
        reasons.append("low_cpi_does_not_equal_high_value")
    elif creative.get("high_cpi_best_payment_efficiency") is True:
        action = "KEEP_RUNNING"
        reasons.append("mature_payment_efficiency_outweighs_cpi")
    elif creative.get("value_goal_mismatch") is True:
        action = (
            "REPLACE"
            if creative.get("replacement_available") is True
            else "RUN_WITH_LIMIT"
        )
        reasons.append("creative_promise_mismatches_value_goal")
    elif creative.get("mature") is True:
        action = "KEEP_RUNNING"
        reasons.append("no_mature_creative_stop_condition")
    else:
        action = "INSUFFICIENT_DATA"
        reasons.append("creative_evidence_not_supplied")

    if permission != "OPTIMIZER_CAN_EXECUTE" and action in {
        "REPLACE",
        "PAUSE",
        "REDUCE_EXPOSURE",
        "RETEST",
    }:
        requests.append(_permission_request("creative", permission))
        action = "KEEP_RUNNING"
        reasons.append("creative_change_not_immediately_executable")
    if creative.get("new_assets_available") is False:
        requests.append("request approved replacement assets")
        if action == "REPLACE":
            action = "REDUCE_EXPOSURE"
        reasons.append("no_approved_replacement_assets")
    if creative.get("stop_condition") is None and (
        creative.get("new_asset") is True or question_type == "creative_action"
    ):
        gaps.append("creative stop condition")

    add_new_assets = (
        creative.get("new_asset") is True
        and creative.get("new_assets_available") is not False
    )
    if add_new_assets and add_permission != "OPTIMIZER_CAN_EXECUTE":
        requests.append(_permission_request("creative_add", add_permission))
        reasons.append("creative_add_not_immediately_executable")
        add_new_assets = False

    if add_new_assets and structure_action in {
        "CREATE_NEW_SAME_LEVEL",
        "CREATE_NEW_CANDIDATE_LEVEL",
        "DUPLICATE_FOR_CONTROLLED_TEST",
    }:
        placement = "TEST_IN_NEW_CAMPAIGN"
    elif add_new_assets:
        placement = "ADD_TO_EXISTING_CAMPAIGN"
    else:
        placement = None

    review = _mapping(quick.get("review"))
    return {
        "action": action,
        "placement": placement,
        "keep_existing_assets": action not in {"PAUSE", "REPLACE"},
        "add_new_assets": add_new_assets,
        "minimum_additional_days": review.get("after_days"),
        "minimum_additional_mature_events": review.get(
            "minimum_additional_mature_events"
        ),
        "maximum_additional_spend": review.get("maximum_additional_spend"),
        "stop_condition": creative.get("stop_condition"),
        "permission": permission,
        "add_permission": add_permission,
        "reason_codes": _unique(reasons),
        "data_gaps": _unique(gaps),
        "client_requests": _unique(requests),
    }


def _bid_budget_decisions(
    case: dict[str, Any],
    numeric: Mapping[str, Any],
    level_action: str,
    *,
    execution_block_reason: str | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[str],
    list[str],
    dict[str, Any],
    dict[str, Any],
]:
    target = deepcopy(dict(_mapping(numeric.get("target_recommendation"))))
    budget_recommendation = deepcopy(
        dict(_mapping(numeric.get("budget_recommendation")))
    )
    current_target = target.get("current_value")
    recommended_target = target.get("recommended_value")
    current_budget = budget_recommendation.get("current_daily_budget")
    recommended_budget = budget_recommendation.get("recommended_value")
    target_action = str(target.get("recommended_action", "NO_CHANGE"))
    budget_action = str(budget_recommendation.get("recommended_action", "NO_CHANGE"))
    target_magnitude = (
        abs(float(target["change_percent"])) / 100
        if _finite_number(target.get("change_percent"))
        else None
    )
    budget_magnitude = (
        abs(float(budget_recommendation["change_percent"])) / 100
        if _finite_number(budget_recommendation.get("change_percent"))
        else None
    )
    reasons: list[str] = []
    requests: list[str] = []
    level_is_changing = level_action in {"move", "parallel_test", "rollback"}
    if level_is_changing:
        target_action = "NO_CHANGE"
        budget_action = "NO_CHANGE"
        recommended_target = current_target
        recommended_budget = current_budget
        target_magnitude = 0.0 if current_target is not None else None
        budget_magnitude = 0.0 if current_budget is not None else None
        reasons.append("keep_bid_and_budget_stable_during_level_change")
        target_execution_reason = "campaign_level_change_selected"
        budget_execution_reason = "campaign_level_change_selected"
    elif execution_block_reason is not None:
        target_action = "NO_CHANGE"
        budget_action = "NO_CHANGE"
        recommended_target = current_target
        recommended_budget = current_budget
        target_magnitude = 0.0 if current_target is not None else None
        budget_magnitude = 0.0 if current_budget is not None else None
        reasons.append(execution_block_reason)
        target_execution_reason = execution_block_reason
        budget_execution_reason = execution_block_reason
    else:
        target_execution_reason = None
        budget_execution_reason = None

    bid_permission = _permission_for(case, "bid")
    budget_permission = _permission_for(case, "budget")
    if (
        target.get("recommended_value") is not None
        and target.get("recommended_action") not in {"NO_CHANGE", "WAIT"}
        and bid_permission != "OPTIMIZER_CAN_EXECUTE"
    ):
        requests.append(_permission_request("bid", bid_permission))
        target_action = "NO_CHANGE"
        recommended_target = current_target
        target_magnitude = 0.0 if current_target is not None else None
        target_execution_reason = "permission_or_approval_required"
    if (
        budget_recommendation.get("recommended_value") is not None
        and budget_recommendation.get("recommended_action") not in {"NO_CHANGE", "WAIT"}
        and budget_permission != "OPTIMIZER_CAN_EXECUTE"
    ):
        requests.append(_permission_request("budget", budget_permission))
        budget_action = "NO_CHANGE"
        recommended_budget = current_budget
        budget_magnitude = 0.0 if current_budget is not None else None
        budget_execution_reason = "permission_or_approval_required"

    target["execution"] = {
        "executable_now": bool(
            target.get("recommended_value") is not None
            and target_action not in {"NO_CHANGE", "WAIT"}
            and bid_permission == "OPTIMIZER_CAN_EXECUTE"
        ),
        "permission": bid_permission,
        "immediate_action": target_action,
        "reason": target_execution_reason,
    }
    budget_recommendation["execution"] = {
        "executable_now": bool(
            budget_recommendation.get("recommended_value") is not None
            and budget_action not in {"NO_CHANGE", "WAIT"}
            and budget_permission == "OPTIMIZER_CAN_EXECUTE"
        ),
        "permission": budget_permission,
        "immediate_action": budget_action,
        "reason": budget_execution_reason,
    }

    bid = {
        "action": target_action,
        "current_target": current_target,
        "recommended_target": recommended_target,
        "recommended_change_ratio": target_magnitude,
        "source": "deterministic_numeric_decision",
        "permission": bid_permission,
    }
    budget = {
        "action": budget_action,
        "current_daily_budget": current_budget,
        "recommended_daily_budget": recommended_budget,
        "recommended_change_ratio": budget_magnitude,
        "source": "deterministic_numeric_decision",
        "permission": budget_permission,
    }
    return (
        bid,
        budget,
        _unique(reasons),
        _unique(requests),
        target,
        budget_recommendation,
    )


def _operational_classification(
    quick: Mapping[str, Any],
    analysis: Mapping[str, Any],
    numeric: Mapping[str, Any],
) -> dict[str, Any]:
    operational = _mapping(quick.get("operational"))
    changes = operational.get("simultaneous_changes", [])
    changes = [str(item) for item in changes] if isinstance(changes, list) else []
    active_reviews = analysis.get("experiment_reviews", [])
    active_experiment = any(
        isinstance(item, Mapping) and item.get("active", True)
        for item in active_reviews
        if isinstance(item, Mapping)
    )
    urgent = operational.get("urgent_confirmed") is True
    numeric_operation = _mapping(numeric.get("classification")).get(
        "operation_classification", "NORMAL_OPTIMIZATION"
    )
    if urgent and len(set(changes)) > 1:
        review = _mapping(quick.get("review"))
        return {
            "classification": "OPERATIONAL_INTERVENTION",
            "operation_classification": "EMERGENCY_INTERVENTION",
            "experiment_validity": "NOT_A_VALID_EXPERIMENT",
            "attribution": "ATTRIBUTION_WILL_BE_CONFOUNDED",
            "causal_attribution_allowed": False,
            "active_experiment_conflict": active_experiment,
            "changed_variables": sorted(set(changes)),
            "intervention_reason": operational.get("reason"),
            "stable_baseline_review": {
                "minimum_days": review.get("after_days"),
                "minimum_mature_events": review.get("minimum_additional_mature_events"),
                "conversion_delay_must_be_mature": review.get(
                    "conversion_delay_must_be_mature"
                ),
            },
        }
    return {
        "classification": "OPERATIONAL_DECISION",
        "operation_classification": numeric_operation,
        "experiment_validity": "NOT_AN_EXPERIMENT",
        "attribution": "NOT_APPLICABLE",
        "causal_attribution_allowed": False,
        "active_experiment_conflict": active_experiment,
    }


def _review_condition(quick: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    review = _mapping(quick.get("review"))
    result = {
        "after_days": review.get("after_days"),
        "minimum_additional_mature_events": review.get(
            "minimum_additional_mature_events"
        ),
        "maximum_additional_spend": review.get("maximum_additional_spend"),
        "conversion_delay_must_be_mature": review.get(
            "conversion_delay_must_be_mature"
        ),
        "safety_review_rule": "ANY supplied time, event, or spend limit",
        "performance_conclusion_rule": "ALL declared time, volume, and delay gates",
    }
    numeric = (
        result["after_days"],
        result["minimum_additional_mature_events"],
        result["maximum_additional_spend"],
    )
    gaps = (
        []
        if any(value is not None for value in numeric)
        else ["account-specific review time, mature-event, or spend limit"]
    )
    return result, gaps


def _rollback_condition(
    quick: Mapping[str, Any], level_action: str, structure: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    supplied = _mapping(quick.get("rollback"))
    applies = level_action in {"move", "parallel_test", "rollback"} or bool(
        structure.get("create_new_campaign")
    )
    if not applies:
        return {
            "applicable": False,
            "condition": None,
            "action": None,
            "baseline_level": _level(supplied.get("baseline_level")),
        }, []
    condition = supplied.get("condition")
    action = supplied.get("action")
    gaps: list[str] = []
    if condition is None:
        gaps.append("predeclared rollback condition")
    if action is None:
        gaps.append("predeclared rollback action")
    return {
        "applicable": True,
        "condition": condition,
        "action": action,
        "baseline_level": _level(supplied.get("baseline_level")),
    }, gaps


def _summary(verdict: str, current: str | None, recommended: str | None) -> str:
    messages = {
        "KEEP_AC20_AND_TEST_AC25": "保留现有 AC2.0，同时在独立条件下测试 AC2.5。",
        "KEEP_AC25_AND_TEST_AC30": "保留现有 AC2.5，同时小规模测试 AC3.0。",
        "MOVE_AC20_TO_AC25": "把当前主力从 AC2.0 调整到已确认口径的 AC2.5。",
        "MOVE_AC25_TO_AC30": "把当前主力从 AC2.5 调整到已确认口径的 AC3.0。",
        "DO_NOT_START_AC25": "继续现有 AC2.0，暂时不要进入 AC2.5。",
        "DO_NOT_START_AC30": "继续现有 AC2.5，暂时不要进入 AC3.0。",
        "WAIT_FOR_MORE_DEEP_EVENTS": "保持现有层级，等待更多成熟深层事件。",
        "WAIT_FOR_VALUE_SIGNAL": "保持现有层级，等待可靠且成熟的价值信号。",
        "ROLL_BACK_TO_AC20": "停止扩大当前深层层级，按预案回退到 AC2.0。",
        "ROLL_BACK_TO_AC25": "停止扩大 AC3.0，按预案回退到 AC2.5。",
        "INSUFFICIENT_EVIDENCE": "当前不改层级；先补齐会改变决策的证据。",
    }
    if verdict in messages:
        return messages[verdict]
    if verdict.startswith("CREATE_NEW_"):
        return f"保留现有 {current}，并按已验证的隔离条件新建同层级 campaign。"
    if verdict.startswith("ADJUST_CURRENT_"):
        return f"调整现有 {current}，不通过复制 campaign 重启学习。"
    if verdict.startswith("CONTINUE_CURRENT_"):
        return f"继续现有 {current}，当前不新建、不并行、不切换层级。"
    return f"保持 {recommended or current or '当前设置'}，等待下一次安全复查。"
