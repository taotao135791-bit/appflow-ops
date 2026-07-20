"""Local, anonymization-aware replay evaluation for historical UAC cases.

The implementation is split into replay_fields (field validators),
replay_numeric (numeric ground truth and evaluation), replay_evaluate
(document loading and single-case evaluation), and replay_metrics (aggregate
metric helpers); this module keeps the public entry points and report
rendering. ``decide_case`` is re-exported so existing monkeypatch-based tests
keep resolving it on this module.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .policy_loader import LoadedPolicy
from .quick_ops import decide_case as decide_case  # re-exported for tests
from .replay_evaluate import (
    LEGACY_REPLAY_FILES,
    REPLAY_DISCLAIMERS,
    REPLAY_FILES,
    evaluate_replay,
)
from .replay_metrics import (
    _magnitude_error,
    _median_magnitude_error,
    _numeric_calibration_metrics,
    _rate,
)
from .types import ContractError


def _case_directories(path: Path) -> list[Path]:
    if path.is_symlink() or not path.is_dir():
        raise ContractError("replay path must be a regular directory")
    if all((path / filename).is_file() for filename in REPLAY_FILES) or all(
        (path / filename).is_file() for filename in LEGACY_REPLAY_FILES
    ):
        return [path]
    cases = sorted(
        {
            candidate.parent
            for candidate in path.rglob("snapshot-before.yaml")
            if candidate.is_file() and not candidate.is_symlink()
        }
    )
    if not cases:
        raise ContractError("no replay cases were found")
    return cases


def replay_path(
    path: Path,
    *,
    policies: Mapping[str, LoadedPolicy] | None = None,
) -> dict[str, Any]:
    """Evaluate one case or aggregate all cases below a directory."""

    cases = [
        evaluate_replay(case_dir, policies=policies)
        for case_dir in _case_directories(path)
    ]
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("replay case_id values must be unique")
    evaluations = [case["evaluation"] for case in cases]

    block_opportunities = sum(
        bool(case["system_at_the_time"]["system_should_block"]) for case in cases
    )
    recommendation_opportunities = sum(
        bool(item["recommendation_available"]) for item in evaluations
    )
    created_experiments = sum(
        bool(case["recorded_decision"]["created_experiment"]) for case in cases
    )
    executed_experiments = sum(
        bool(item["executed_experiment"]) for item in evaluations
    )
    completed_experiments = sum(
        bool(item["experiment_completed"]) for item in evaluations
    )
    conclusive_experiments = sum(bool(item["conclusive"]) for item in evaluations)
    attributable_experiments = sum(bool(item["attributable"]) for item in evaluations)
    numeric_replays = [
        case["numeric_replay"]
        for case in cases
        if isinstance(case.get("numeric_replay"), dict)
    ]
    numeric_evaluations = [item["evaluation"] for item in numeric_replays]
    direction_evaluations = [
        item
        for item in numeric_evaluations
        if item["business_result_evaluable"] is True
    ]
    magnitude_errors = [
        float(item["magnitude_error"])
        for item in direction_evaluations
        if item["magnitude_error"] is not None
    ]
    no_action_evaluations = [
        item for item in numeric_evaluations if item["no_action_expected"] is True
    ]
    human_decisions = [
        item["human_decision"]["accepted_system_recommendation"]
        for item in numeric_replays
        if isinstance(item["human_decision"]["accepted_system_recommendation"], bool)
    ]
    numeric_calibration = _numeric_calibration_metrics(cases)
    has_numeric_calibration = any(
        isinstance(case.get("numeric_evaluation"), dict) for case in cases
    )

    time_saved_total = 0.0
    for item in evaluations:
        time_saved_total += float(item["time_saved_minutes"])
        if not math.isfinite(time_saved_total):
            raise ContractError("aggregate time_saved_minutes must remain finite")

    experiment_rollback_rate = _rate(
        sum(
            bool(item["rollback"]) and bool(item["executed_experiment"])
            for item in evaluations
        ),
        executed_experiments,
    )
    metrics = {
        "correct_block_rate": _rate(
            sum(bool(item["correct_block"]) for item in evaluations),
            block_opportunities,
        ),
        "unsafe_action_rate": _rate(
            sum(bool(item["unsafe_action"]) for item in evaluations), len(cases)
        ),
        "executable_recommendation_rate": _rate(
            sum(bool(item["executable_recommendation"]) for item in evaluations),
            recommendation_opportunities,
        ),
        "single_variable_compliance_rate": _rate(
            sum(
                bool(item["single_variable_compliant"])
                and bool(item["executed_experiment"])
                for item in evaluations
            ),
            executed_experiments,
        ),
        "experiment_completion_rate": _rate(completed_experiments, created_experiments),
        "conclusive_experiment_rate": _rate(
            conclusive_experiments, completed_experiments
        ),
        "confounded_rate": _rate(
            sum(
                bool(item["confounded"]) and bool(item["executed_experiment"])
                for item in evaluations
            ),
            executed_experiments,
        ),
        "positive_experiment_rate": _rate(
            sum(bool(item["positive"]) for item in evaluations),
            attributable_experiments,
        ),
        "rollback_rate": (
            numeric_calibration["rollback_rate"]
            if has_numeric_calibration
            else experiment_rollback_rate
        ),
        "time_saved_minutes": round(time_saved_total, 2),
        "insufficient_evidence_rate": _rate(
            sum(bool(item["insufficient_evidence"]) for item in evaluations),
            len(cases),
        ),
        "direction_accuracy": (
            numeric_calibration["direction_accuracy"]
            if has_numeric_calibration
            else _rate(
                sum(bool(item["direction_correct"]) for item in direction_evaluations),
                len(direction_evaluations),
            )
        ),
        "magnitude_error": _magnitude_error(magnitude_errors),
        "median_magnitude_error": (
            numeric_calibration["median_magnitude_error"]
            if has_numeric_calibration
            else _median_magnitude_error(magnitude_errors)
        ),
        "policy_cap_trigger_rate": numeric_calibration["policy_cap_trigger_rate"],
        "too_aggressive_rate": numeric_calibration["too_aggressive_rate"],
        "too_conservative_rate": numeric_calibration["too_conservative_rate"],
        "staged_plan_completion_rate": numeric_calibration[
            "staged_plan_completion_rate"
        ],
        "unsafe_numeric_recommendation_rate": _rate(
            sum(
                bool(item["unsafe_numeric_recommendation"])
                for item in numeric_evaluations
            ),
            len(numeric_evaluations),
        ),
        "no_action_correct_rate": (
            numeric_calibration["no_action_correct_rate"]
            if has_numeric_calibration
            else _rate(
                sum(bool(item["no_action_correct"]) for item in no_action_evaluations),
                len(no_action_evaluations),
            )
        ),
        "human_acceptance_rate": _rate(
            sum(value is True for value in human_decisions), len(human_decisions)
        ),
    }
    return {
        "schema_version": "1.0",
        "sample_size": len(cases),
        "cases": cases,
        "metrics": metrics,
        "disclaimers": REPLAY_DISCLAIMERS,
    }


def render_replay(report: dict[str, Any]) -> str:
    lines = [f"UAC Replay: {report['sample_size']} case(s)"]
    for case in report["cases"]:
        evaluation = case["evaluation"]
        lines.append(
            f"- {case['case_id']}: {evaluation['classification']} "
            f"(attributable={str(evaluation['attributable']).lower()})"
        )
    lines.append("")
    lines.append("Metrics:")
    for name, metric in report["metrics"].items():
        if isinstance(metric, dict):
            if "rate" in metric:
                rate = "n/a" if metric["rate"] is None else metric["rate"]
                lines.append(
                    f"- {name}: {rate} ({metric['numerator']}/{metric['denominator']})"
                )
            elif "mean_absolute_percentage_error" in metric:
                mean = metric["mean_absolute_percentage_error"]
                rendered = "n/a" if mean is None else mean
                lines.append(
                    f"- {name}: {rendered} ({metric['denominator']} evaluated case(s))"
                )
            else:
                median_value = metric["median_magnitude_error_percent"]
                rendered = "n/a" if median_value is None else median_value
                lines.append(
                    f"- {name}: {rendered} ({metric['denominator']} evaluated case(s))"
                )
        else:
            lines.append(f"- {name}: {metric}")
    lines.append("")
    lines.extend(f"Warning: {item}" for item in report["disclaimers"])
    return "\n".join(lines)
