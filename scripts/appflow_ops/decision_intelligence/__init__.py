"""Ads Decision Intelligence facade (v3.6.0).

Public entry points — callers should never import internal modules:

    detect_operational_domain(request)        → primary domain
    build_hypothesis_set(platform_scope, domain, cross_platform)
    evaluate_hypotheses(specs, signals, measurement_state, maturity_state)
    rank_hypotheses(evaluations)
    converge(ranked, measurement_state, maturity_state, safety_context,
             action_context)
    resolve_evaluation_safety(evaluation, safety_context)
    scale_eligibility(facts) / thresholds_for(family) / sample_sufficient
"""

from __future__ import annotations

from .calibration import (
    METRIC_CALIBRATION,
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
    RankedHypothesis,
    SafetyContext,
    converge,
    rank_hypotheses,
    resolve_evaluation_safety,
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
    "ALL_HYPOTHESES",
    "CONVERGENCE_STATUSES",
    "CROSS_PLATFORM_HYPOTHESES",
    "HYPOTHESIS_STATUSES",
    "META_HYPOTHESES",
    "METRIC_CALIBRATION",
    "OPERATIONAL_DOMAINS",
    "SIGNAL_IDS",
    "SIGNAL_LABELS",
    "TIKTOK_HYPOTHESES",
    "Convergence",
    "DecisionIntelligenceResult",
    "EvidenceResult",
    "HypothesisEvaluation",
    "HypothesisSpec",
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
    "evaluate_hypotheses",
    "evaluate_hypothesis",
    "hypothesis_by_id",
    "is_cross_platform_request",
    "observations_comparable",
    "operational_domain",
    "primary_domain",
    "rank_hypotheses",
    "resolve_evaluation_safety",
    "sample_sufficient",
    "scale_eligibility",
    "signals_from_metrics",
    "signals_from_platforms",
    "summarize_decision_intelligence",
    "thresholds_for",
]
