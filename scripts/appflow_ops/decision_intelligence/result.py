"""Runtime-native Decision Intelligence result (v3.5.1).

The result is the operational OUTPUT of the DI pipeline — a light,
structured answer, NOT a full scoring dump. Callers (and the runtime
summary builder) consume this; internal scores stay inside
``evaluations``/``ranked_hypotheses`` and are never the default product
output.
"""

from __future__ import annotations

from dataclasses import dataclass

from .evaluator import HypothesisEvaluation
from .evidence import EvidenceResult
from .ranking import Convergence, RankedHypothesis

CONVERGENCE_STATUSES = ("converged", "investigate", "wait", "insufficient_evidence")


@dataclass(frozen=True)
class DecisionIntelligenceResult:
    """Lightweight DI outcome for one operational run."""

    platform_scope: tuple[str, ...]
    operational_domain: str
    evaluations: tuple[HypothesisEvaluation, ...]
    ranked_hypotheses: tuple[RankedHypothesis, ...]
    top_hypothesis: str | None
    top_status: str | None
    material_alternatives: tuple[str, ...]
    convergence_status: str  # converged | investigate | wait | insufficient_evidence
    recommended_action: str | None
    reason_summary: str
    review_condition: str | None
    missing_evidence: tuple[str, ...]
    next_discriminating_evidence: tuple[str, ...]
    safety_context: dict[str, str]  # measurement/maturity/policy/permission
    # v3.5.3: platform attribution of the top evaluation (None = generic).
    top_platform: str | None = None
    # v3.5.2: evidence provenance (per-platform signals, shared signals,
    # historical comparisons) — audit support, not default output.
    evidence: EvidenceResult | None = None


def convergence_status(convergence: Convergence) -> str:
    """Map the internal Convergence to the four public statuses."""
    if convergence.converged:
        return "converged"
    if convergence.decision in ("investigate", "investigate_measurement"):
        return "investigate"
    if convergence.decision == "wait":
        return "wait"
    return "insufficient_evidence"


def from_convergence(
    *,
    convergence: Convergence,
    platform_scope: tuple[str, ...],
    operational_domain: str,
    evaluations: tuple[HypothesisEvaluation, ...],
    ranked: tuple[RankedHypothesis, ...],
    safety_context: dict[str, str],
    evidence: EvidenceResult | None = None,
) -> DecisionIntelligenceResult:
    """Build the public result from pipeline internals (single assembly
    point so the runtime entry and tests share identical semantics)."""
    top = ranked[0].evaluation if ranked else None
    return DecisionIntelligenceResult(
        top_platform=top.platform if top is not None else None,
        platform_scope=platform_scope,
        operational_domain=operational_domain,
        evaluations=evaluations,
        ranked_hypotheses=ranked,
        top_hypothesis=convergence.top_hypothesis,
        top_status=top.status if top is not None else None,
        material_alternatives=convergence.material_alternatives,
        convergence_status=convergence_status(convergence),
        recommended_action=convergence.decision,
        reason_summary=convergence.rationale[0] if convergence.rationale else "",
        review_condition=convergence.review_condition,
        missing_evidence=convergence.missing_evidence,
        next_discriminating_evidence=convergence.next_discriminating_evidence,
        safety_context=dict(safety_context),
        evidence=evidence,
    )
