"""Replay document loading and single-case evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .engine import analyze_case
from .io import _load
from .models import FeasibilityState
from .policy_loader import LoadedPolicy
from .quick_ops import decide_case
from .replay_fields import (
    _contains_finite_numeric_metric,
    _non_negative_finite,
    _positive_policy_minimum_days,
    _require_bool,
    _require_text,
    _string_list,
)
from .replay_numeric import (
    _evaluate_numeric_replay,
    _finalize_numeric_evaluation,
    _numeric_evaluation_label,
    _numeric_ground_truth,
)
from .types import FEASIBILITY_STATES, ContractError


REPLAY_FILES = (
    "snapshot-before.yaml",
    "system-recommendation.yaml",
    "human-decision.yaml",
    "actual-action.yaml",
    "snapshot-after.yaml",
    "evaluation.yaml",
)

LEGACY_REPLAY_FILES = (
    "snapshot-before.yaml",
    "decision-at-the-time.yaml",
    "actual-action.yaml",
    "snapshot-after.yaml",
    "evaluation.yaml",
)

_BLOCKING_FEASIBILITY = {
    FeasibilityState.DATA_BLOCKED.value,
    FeasibilityState.PERMISSION_BLOCKED.value,
    FeasibilityState.TRACKING_BLOCKED.value,
    FeasibilityState.PRODUCT_FUNNEL_BLOCKED.value,
    FeasibilityState.LEARNING_BLOCKED.value,
    FeasibilityState.NO_ACTION_RECOMMENDED.value,
}

REPLAY_DISCLAIMERS = [
    "Replay metrics are retrospective workflow diagnostics, not causal proof.",
    "Small samples cannot support platform-wide or account-independent conclusions.",
    "Account-specific outcomes may improve this project but do not become global rules automatically.",
    "A recommendation that a human did not execute is neither a system success nor a system failure.",
    "Confounded experiments never enter positive or negative effect rates.",
    "Numeric direction and magnitude exclude rejected, unexecuted, immature, deviated, or confounded cases.",
    "Contaminated cases never enter numeric magnitude calibration.",
    "Numeric calibration should be reviewed separately for different products and markets.",
    "Replay calibration never changes a policy automatically; every policy change requires human approval and a new policy version.",
    "A replay never authorizes an advertising-account change.",
]


def _load_replay(case_dir: Path) -> dict[str, dict[str, Any]]:
    if case_dir.is_symlink():
        raise ContractError("replay case directories must not be symbolic links")
    if not case_dir.is_dir():
        raise ContractError("replay path must be a directory")
    selected_files: tuple[str, ...]
    if all((case_dir / filename).is_file() for filename in REPLAY_FILES):
        selected_files = REPLAY_FILES
        contract = "six-stage"
    elif all((case_dir / filename).is_file() for filename in LEGACY_REPLAY_FILES):
        selected_files = LEGACY_REPLAY_FILES
        contract = "legacy-five-file"
    else:
        raise ContractError(
            "replay must contain either the six-stage contract or all legacy five files"
        )

    documents: dict[str, dict[str, Any]] = {}
    for filename in selected_files:
        path = case_dir / filename
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"replay is missing a regular {filename}")
        document = _load(path)
        if document.get("schema_version") != "1.0":
            raise ContractError(f"{filename} schema_version must be 1.0")
        documents[filename] = document
    case_ids = {_require_text(document, "case_id") for document in documents.values()}
    if len(case_ids) != 1:
        raise ContractError("all replay documents must share one non-empty case_id")
    if contract == "six-stage":
        system_recommendation = documents["system-recommendation.yaml"]
        human_decision = documents["human-decision.yaml"]
        _require_text(system_recommendation, "recorded_at")
        _require_text(human_decision, "decided_at")
        _require_bool(human_decision, "accepted_system_recommendation")
        documents["decision-at-the-time.yaml"] = {
            **human_decision,
            "kimi_ads": system_recommendation.get("kimi_ads"),
        }
    return documents


def evaluate_replay(
    case_dir: Path,
    *,
    policies: Mapping[str, LoadedPolicy] | None = None,
) -> dict[str, Any]:
    """Re-run the deterministic decision and compare it with recorded action."""

    documents = _load_replay(case_dir)
    before = documents["snapshot-before.yaml"]
    recorded_decision = documents["decision-at-the-time.yaml"]
    action = documents["actual-action.yaml"]
    after = documents["snapshot-after.yaml"]
    evaluation = documents["evaluation.yaml"]

    _require_text(before, "captured_at")
    uac_input = before.get("uac_input")
    if not isinstance(uac_input, dict):
        raise ContractError("snapshot-before.yaml uac_input must be an object")
    numeric_ground_truth = _numeric_ground_truth(before)
    quick_decision: dict[str, Any] | None = None
    if numeric_ground_truth is not None:
        if not isinstance(uac_input.get("quick_ops"), dict):
            raise ContractError(
                "numeric_ground_truth requires snapshot-before.yaml uac_input.quick_ops"
            )
        quick_decision = decide_case(uac_input, policies=policies)
    analysis = analyze_case(uac_input)
    feasibility = analysis["optimization_feasibility"]["status"]
    generated_experiment = bool(analysis["experiments"])
    current_experiment_variables = sorted(
        {
            str(experiment.get("variable", {}).get("type"))
            for experiment in analysis["experiments"]
            if isinstance(experiment.get("variable"), dict)
            and isinstance(experiment["variable"].get("type"), str)
            and experiment["variable"]["type"].strip()
        }
    )
    current_recommended = sorted(
        {
            item["variable"]
            for item in analysis["recommendations"]
            if item.get("permission") == "OPTIMIZER_CAN_EXECUTE"
        }
    )

    decision_data = recorded_decision.get("kimi_ads")
    if not isinstance(decision_data, dict):
        raise ContractError("recorded system recommendation must be an object")
    human_judgment = _require_text(recorded_decision, "human_judgment")
    accepted_recommendation = recorded_decision.get("accepted_system_recommendation")
    if accepted_recommendation is not None and not isinstance(
        accepted_recommendation, bool
    ):
        raise ContractError("accepted_system_recommendation must be boolean")
    recorded_version = _require_text(decision_data, "version")
    recorded_feasibility = decision_data.get("feasibility")
    if recorded_feasibility not in FEASIBILITY_STATES:
        raise ContractError("kimi_ads.feasibility is invalid")
    recorded_confidence = decision_data.get("confidence")
    if recorded_confidence not in {"low", "medium", "high"}:
        raise ContractError("kimi_ads.confidence is invalid")
    recorded_data_gaps = _string_list(decision_data, "data_gaps")
    recorded_recommended = _string_list(decision_data, "recommended_variables")
    protected = _string_list(decision_data, "protected_variables")
    recorded_created = _require_bool(decision_data, "created_experiment")

    executed = _require_bool(action, "executed")
    approved_by_role = _require_text(action, "approved_by_role")
    executed_at = action.get("executed_at")
    if executed:
        if not isinstance(executed_at, str) or not executed_at.strip():
            raise ContractError("executed_at must be recorded for an executed action")
    elif executed_at is not None and executed_at != "":
        raise ContractError("executed_at must be null when no action was executed")
    actual_variables = _string_list(action, "variables_changed")
    concurrent_changes = _string_list(action, "concurrent_changes")
    reported_deviation = _require_bool(action, "deviated_from_recommendation")
    action_rollback = _require_bool(action, "rollback_performed")

    correct_block_label = _require_bool(evaluation, "correct_block")
    executable_label = _require_bool(evaluation, "recommendation_executable")
    single_variable_label = _require_bool(evaluation, "single_variable_compliant")
    experiment_completed = _require_bool(evaluation, "experiment_completed")
    observation_conditions_met = _require_bool(evaluation, "observation_conditions_met")
    conclusive_label = _require_bool(evaluation, "conclusive")
    evaluation_rollback = _require_bool(evaluation, "rollback_performed")
    insufficient_label = _require_bool(evaluation, "insufficient_evidence")
    _require_text(evaluation, "human_rating")
    if evaluation.get("causal_claim") is not False:
        raise ContractError("evaluation.yaml causal_claim must be false")
    numeric_evaluation_label = _numeric_evaluation_label(evaluation)

    _require_text(after, "captured_at")
    observation_days = _non_negative_finite(
        after.get("observation_days"), "observation_days"
    )
    after_metrics = after.get("metrics")
    if not isinstance(after_metrics, dict):
        raise ContractError("snapshot-after.yaml metrics must be an object")
    has_numeric_after_metric = _contains_finite_numeric_metric(
        after_metrics, "snapshot-after.yaml metrics"
    )
    _require_bool(after, "backend_data_available")
    confounders = _string_list(after, "confounders")
    delay_mature = _require_bool(after, "conversion_delay_mature")
    volume_mature = _require_bool(after, "minimum_conversions_met")
    outcome = evaluation.get("outcome")
    if outcome not in {"positive", "negative", "inconclusive", "not_executed"}:
        raise ContractError(
            "evaluation.yaml outcome must be positive, negative, inconclusive, or not_executed"
        )
    time_saved = _non_negative_finite(
        evaluation.get("time_saved_minutes"), "evaluation.yaml time_saved_minutes"
    )

    if not executed and (actual_variables or concurrent_changes or action_rollback):
        raise ContractError(
            "an unexecuted action cannot record changed variables, concurrent changes, or rollback"
        )
    if not executed and experiment_completed:
        raise ContractError("an unexecuted action cannot be a completed experiment")
    if executed and outcome == "not_executed":
        raise ContractError("an executed action cannot have outcome=not_executed")
    if not executed and outcome != "not_executed":
        raise ContractError("an unexecuted action requires outcome=not_executed")
    if conclusive_label and not experiment_completed:
        raise ContractError("a conclusive evaluation must be a completed experiment")
    if outcome in {"positive", "negative"} and not conclusive_label:
        raise ContractError(
            "positive or negative outcome requires a conclusive evaluation"
        )
    if conclusive_label and outcome not in {"positive", "negative"}:
        raise ContractError(
            "a conclusive evaluation requires a positive or negative outcome"
        )
    if conclusive_label and not observation_conditions_met:
        raise ContractError(
            "a conclusive evaluation requires observation_conditions_met=true"
        )
    if observation_conditions_met and not (delay_mature and volume_mature):
        raise ContractError(
            "observation_conditions_met=true requires mature delay and conversion volume"
        )
    requires_outcome_evidence = conclusive_label or outcome in {"positive", "negative"}
    if requires_outcome_evidence and not has_numeric_after_metric:
        raise ContractError(
            "a conclusive or positive/negative outcome requires at least one finite numeric after-metric"
        )
    minimum_observation_days = _positive_policy_minimum_days(uac_input)
    if (
        observation_conditions_met
        and minimum_observation_days is not None
        and observation_days < minimum_observation_days
    ):
        raise ContractError(
            "observation_conditions_met=true conflicts with experiment_policy.minimum_days"
        )
    if action_rollback != evaluation_rollback:
        raise ContractError(
            "rollback_performed must agree across action and evaluation"
        )

    system_should_block = feasibility in _BLOCKING_FEASIBILITY
    protected_changes = sorted(set(actual_variables) & set(protected))
    actual_variable = actual_variables[0] if len(actual_variables) == 1 else None
    matches_recorded_experiment = bool(
        recorded_created
        and len(recorded_recommended) == 1
        and actual_variable == recorded_recommended[0]
    )
    matches_current_experiment = bool(
        generated_experiment
        and len(current_experiment_variables) == 1
        and actual_variable == current_experiment_variables[0]
    )
    variable_matches_experiment = bool(executed and matches_recorded_experiment)
    derived_variable_deviation = bool(
        executed and recorded_created and not variable_matches_experiment
    )
    deviated = bool(reported_deviation or derived_variable_deviation)
    single_variable = bool(
        executed
        and recorded_created
        and len(actual_variables) == 1
        and variable_matches_experiment
        and not concurrent_changes
        and not deviated
        and single_variable_label
    )
    confounded = bool(confounders or concurrent_changes)
    unsafe_action = bool(
        executed
        and (system_should_block or protected_changes or len(actual_variables) != 1)
    )
    correct_block = bool(system_should_block and not executed and correct_block_label)
    recommendation_available = bool(current_recommended or analysis["recommendations"])
    executable_recommendation = bool(
        recommendation_available and executable_label and current_recommended
    )
    experiment_opportunity = bool(generated_experiment or recorded_created)
    executed_experiment = bool(executed and recorded_created)
    completed = bool(executed_experiment and experiment_completed)
    maturity_met = bool(observation_conditions_met and delay_mature and volume_mature)
    insufficient_evidence = bool(
        insufficient_label or feasibility == FeasibilityState.DATA_BLOCKED.value
    )
    conclusive = bool(
        completed
        and maturity_met
        and conclusive_label
        and not confounded
        and not unsafe_action
        and not insufficient_evidence
    )
    valid_experiment = bool(
        executed_experiment
        and completed
        and maturity_met
        and single_variable
        and not confounded
        and not unsafe_action
        and not insufficient_evidence
    )
    recommendation_accepted = accepted_recommendation is not False
    attributable = bool(
        valid_experiment and conclusive and not deviated and recommendation_accepted
    )
    positive = bool(attributable and outcome == "positive")
    negative = bool(attributable and outcome == "negative")
    rollback = bool(action_rollback or evaluation_rollback)
    numeric_business_result_evaluable = bool(
        accepted_recommendation is True
        and executed
        and not confounded
        and not deviated
        and observation_conditions_met
        and delay_mature
        and volume_mature
        and not insufficient_evidence
    )
    numeric_evaluation, numeric_calibration_evaluable = _finalize_numeric_evaluation(
        numeric_evaluation_label,
        accepted_recommendation=accepted_recommendation,
        executed=executed,
        confounded=confounded,
        deviated=deviated,
        unsafe_action=unsafe_action,
        maturity_met=maturity_met,
        insufficient_evidence=insufficient_evidence,
    )
    numeric_replay = (
        _evaluate_numeric_replay(
            numeric_ground_truth,
            quick_decision,
            accepted_recommendation=accepted_recommendation,
            executed=executed,
            confounded=confounded,
            deviated=deviated,
            mature_result_available=maturity_met,
            business_result_evaluable=numeric_business_result_evaluable,
        )
        if numeric_ground_truth is not None and quick_decision is not None
        else None
    )
    if unsafe_action:
        classification = "unsafe_action"
    elif correct_block:
        classification = "correct_block"
    elif insufficient_evidence:
        classification = "insufficient_evidence"
    elif confounded:
        classification = "confounded"
    elif executed and experiment_opportunity and not attributable:
        classification = "unattributable"
    elif positive:
        classification = "positive_experiment"
    elif negative:
        classification = "negative_experiment"
    else:
        classification = "incomplete_or_monitoring"

    case_id = next(iter({doc["case_id"] for doc in documents.values()}))
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "system_at_the_time": {
            "rule_basis": "current_rules_on_historical_snapshot",
            "feasibility": feasibility,
            "diagnosis": analysis["diagnoses"][0]["code"],
            "generated_experiment": generated_experiment,
            "recommended_variables": current_recommended,
            "experiment_variables": current_experiment_variables,
            "system_should_block": system_should_block,
        },
        "recorded_decision": {
            "human_judgment": human_judgment,
            "accepted_system_recommendation": accepted_recommendation,
            "version": recorded_version,
            "feasibility": recorded_feasibility,
            "confidence": recorded_confidence,
            "data_gaps": recorded_data_gaps,
            "recommended_variables": recorded_recommended,
            "created_experiment": recorded_created,
        },
        "actual_action": {
            "executed": executed,
            "approved_by_role": approved_by_role,
            "executed_at": executed_at,
            "variables_changed": actual_variables,
            "protected_changes": protected_changes,
            "deviated": deviated,
            "reported_deviation": reported_deviation,
            "derived_variable_deviation": derived_variable_deviation,
            "variable_matches_experiment": variable_matches_experiment,
            "variable_matches_current_rules": matches_current_experiment,
        },
        "evaluation": {
            "classification": classification,
            "correct_block": correct_block,
            "unsafe_action": unsafe_action,
            "recommendation_available": recommendation_available,
            "executable_recommendation": executable_recommendation,
            "experiment_opportunity": experiment_opportunity,
            "executed_experiment": executed_experiment,
            "single_variable_compliant": single_variable,
            "confounded": confounded,
            "experiment_completed": completed,
            "conclusive": conclusive,
            "valid_experiment": valid_experiment,
            "attributable": attributable,
            "recommendation_accepted": recommendation_accepted,
            "positive": positive,
            "negative": negative,
            "rollback": rollback,
            "insufficient_evidence": insufficient_evidence,
            "time_saved_minutes": time_saved,
            "observation_days": observation_days,
            "minimum_observation_days": minimum_observation_days,
            "has_numeric_after_metric": has_numeric_after_metric,
            "numeric_calibration_evaluable": numeric_calibration_evaluable,
        },
        "numeric_replay": numeric_replay,
        "numeric_evaluation": numeric_evaluation,
        "disclaimers": REPLAY_DISCLAIMERS,
    }
