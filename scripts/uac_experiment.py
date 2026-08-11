#!/usr/bin/env python3
"""Compatibility entry point for the deterministic UAC experiment helper.

The implementation lives under appflow_ops.uac. Existing imports and CLI
invocations continue to use this module.
"""

from __future__ import annotations

from appflow_ops.uac import (
    ANALYSIS_SCHEMA_VERSION,
    CURRENT_LEDGER_SCHEMA_VERSION,
    EVIDENCE_QUALITY_STATES,
    EXPERIMENT_RESULTS,
    EXPERIMENT_STATUSES,
    FEASIBILITY_STATES,
    LEARNING_SCOPES,
    LEARNING_STATES,
    MEASUREMENT_STATES,
    PERMISSION_CLASSES,
    SUPPORTED_LEDGER_SCHEMA_VERSIONS,
    TERMINAL_EXPERIMENT_RESULTS,
    ContractError,
    EvidenceQuality,
    ExperimentOutcome,
    ExperimentStatus,
    FeasibilityState,
    LearningScope,
    LearningState,
    MeasurementState,
    PermissionClass,
    Workspace,
    analyze_case,
    decide_case,
    derive_signals,
    initialize_workspace,
    migrate_ledger,
    normalize_uac_input,
    recommend_numeric,
    render_markdown,
    render_quick_card,
    replay_path,
    review_experiment,
    route_question,
    run_doctor,
    validate_analysis,
    validate_experiment,
    validate_ledger,
    validate_workspace_name,
)
from appflow_ops.uac.cli import _cli, main

__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "CURRENT_LEDGER_SCHEMA_VERSION",
    "EVIDENCE_QUALITY_STATES",
    "EXPERIMENT_RESULTS",
    "EXPERIMENT_STATUSES",
    "FEASIBILITY_STATES",
    "LEARNING_SCOPES",
    "LEARNING_STATES",
    "MEASUREMENT_STATES",
    "PERMISSION_CLASSES",
    "SUPPORTED_LEDGER_SCHEMA_VERSIONS",
    "TERMINAL_EXPERIMENT_RESULTS",
    "ContractError",
    "EvidenceQuality",
    "ExperimentOutcome",
    "ExperimentStatus",
    "FeasibilityState",
    "LearningScope",
    "LearningState",
    "MeasurementState",
    "PermissionClass",
    "Workspace",
    "_cli",
    "analyze_case",
    "decide_case",
    "derive_signals",
    "initialize_workspace",
    "main",
    "migrate_ledger",
    "normalize_uac_input",
    "recommend_numeric",
    "render_markdown",
    "render_quick_card",
    "replay_path",
    "review_experiment",
    "route_question",
    "run_doctor",
    "validate_analysis",
    "validate_experiment",
    "validate_ledger",
    "validate_workspace_name",
]


if __name__ == "__main__":
    raise SystemExit(main())
