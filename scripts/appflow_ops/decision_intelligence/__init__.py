"""Ads Decision Intelligence facade (v3.5.0).

Public entry points — callers should never import internal modules:

    detect_operational_domain(request)        → primary domain
    build_hypothesis_set(platform_scope, domain, cross_platform)
    evaluate_hypotheses(specs, signals, measurement_state, maturity_state)
    rank_hypotheses(evaluations)
    converge(ranked, measurement_state, maturity_state)
"""

from __future__ import annotations

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
    add_context_signals,
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
    converge,
    rank_hypotheses,
)
from .result import (
    CONVERGENCE_STATUSES,
    DecisionIntelligenceResult,
    convergence_status,
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
    "OPERATIONAL_DOMAINS",
    "SIGNAL_IDS",
    "SIGNAL_LABELS",
    "TIKTOK_HYPOTHESES",
    "Convergence",
    "DecisionIntelligenceResult",
    "HypothesisEvaluation",
    "HypothesisSpec",
    "RankedHypothesis",
    "add_context_signals",
    "build_hypothesis_set",
    "converge",
    "convergence_status",
    "detect_operational_domain",
    "evaluate_hypotheses",
    "evaluate_hypothesis",
    "hypothesis_by_id",
    "is_cross_platform_request",
    "primary_domain",
    "rank_hypotheses",
    "signals_from_metrics",
    "signals_from_platforms",
    "summarize_decision_intelligence",
]
