"""Ads Decision Intelligence facade (v3.6.2).

Public entry points — callers should never import internal modules:

    detect_operational_domain(request)        → primary domain
    build_hypothesis_set(platform_scope, domain, cross_platform)
    evaluate_hypotheses(specs, signals, measurement_state, maturity_state)
    rank_hypotheses(evaluations)
    converge(ranked, measurement_state, maturity_state, safety_context,
             action_context)
    resolve_evaluation_safety(evaluation, safety_context)
    scale_eligibility(facts) / thresholds_for(family) / sample_sufficient
    resolve_primary_kpi_context(facts) / resolve_kpi_outcome_volume(kpi)
    is_material_rival(top, candidate)
"""

from __future__ import annotations

from .calibration import (
    ACTION_MAGNITUDES,
    ACTION_READINESS_STATES,
    KPI_SCALE_MINIMUMS,
    METRIC_CALIBRATION,
    PRIMARY_KPIS,
    TIMING_CALIBRATION,
    evaluate_action_readiness,
    evaluate_descale_candidate,
    normalize_goal_to_kpi,
    resolve_action_lever,
    resolve_action_magnitude,
    resolve_creative_action,
    resolve_kpi_outcome_volume,
    resolve_primary_kpi,
    resolve_primary_kpi_context,
    sample_sufficient,
    scale_eligibility,
    thresholds_for,
)
from .domains import (
    OPERATIONAL_DOMAINS,
    detect_operational_domain,
    is_cross_platform_request,
    primary_domain,
)
from .evaluator import (
    HYPOTHESIS_STATUSES,
    HypothesisEvaluation,
    evaluate_hypotheses,
    evaluate_hypothesis,
)
from .evidence import (
    EvidenceResult,
    add_context_signals,
    build_evidence,
    comparable_identity,
    derive_change_pcts,
    observations_comparable,
    signals_from_metrics,
    signals_from_platforms,
)
from .hypotheses import (
    ALL_HYPOTHESES,
    CROSS_PLATFORM_HYPOTHESES,
    META_HYPOTHESES,
    SIGNAL_IDS,
    TIKTOK_HYPOTHESES,
    HypothesisSpec,
    build_hypothesis_set,
    hypothesis_by_id,
)
from .ranking import (
    Convergence,
    MaterialContext,
    ParallelIssue,
    RankedHypothesis,
    SafetyContext,
    converge,
    is_material_rival,
    rank_hypotheses,
    resolve_evaluation_safety,
    shared_candidate_blocks_action,
)
from .result import (
    CONVERGENCE_STATUSES,
    DecisionIntelligenceResult,
    convergence_status,
    decision_attribution,
)
from .summary import (
    SIGNAL_LABELS,
    summarize_decision_intelligence,
)

__all__ = [
    "ACTION_MAGNITUDES",
    "ACTION_READINESS_STATES",
    "ALL_HYPOTHESES",
    "CONVERGENCE_STATUSES",
    "CROSS_PLATFORM_HYPOTHESES",
    "HYPOTHESIS_STATUSES",
    "KPI_SCALE_MINIMUMS",
    "META_HYPOTHESES",
    "METRIC_CALIBRATION",
    "OPERATIONAL_DOMAINS",
    "PRIMARY_KPIS",
    "SIGNAL_IDS",
    "SIGNAL_LABELS",
    "TIKTOK_HYPOTHESES",
    "TIMING_CALIBRATION",
    "Convergence",
    "DecisionIntelligenceResult",
    "EvidenceResult",
    "HypothesisEvaluation",
    "HypothesisSpec",
    "MaterialContext",
    "ParallelIssue",
    "RankedHypothesis",
    "SafetyContext",
    "add_context_signals",
    "build_evidence",
    "build_hypothesis_set",
    "comparable_identity",
    "converge",
    "convergence_status",
    "decision_attribution",
    "derive_change_pcts",
    "detect_operational_domain",
    "evaluate_action_readiness",
    "evaluate_descale_candidate",
    "evaluate_hypotheses",
    "evaluate_hypothesis",
    "hypothesis_by_id",
    "is_cross_platform_request",
    "is_material_rival",
    "normalize_goal_to_kpi",
    "observations_comparable",
    "operational_domain",
    "primary_domain",
    "rank_hypotheses",
    "resolve_action_lever",
    "resolve_action_magnitude",
    "resolve_creative_action",
    "resolve_evaluation_safety",
    "resolve_kpi_outcome_volume",
    "resolve_primary_kpi",
    "resolve_primary_kpi_context",
    "sample_sufficient",
    "scale_eligibility",
    "shared_candidate_blocks_action",
    "signals_from_metrics",
    "signals_from_platforms",
    "summarize_decision_intelligence",
    "thresholds_for",
]
