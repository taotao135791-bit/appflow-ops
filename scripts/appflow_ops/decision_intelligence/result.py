"""Runtime-native Decision Intelligence result (v3.5.5).

The result is the operational OUTPUT of the DI pipeline — a light,
structured answer, NOT a full scoring dump. Callers (and the runtime
summary builder) consume this; internal scores stay inside
``evaluations``/``ranked_hypotheses`` and are never the default product
output.

Attribution integrity (v3.5.5): ``top_hypothesis``, ``top_platform``
and ``top_evaluation_scope`` always derive from ONE ``selected_evaluation``
— convergence can block the outcome, but it never silently swaps the
diagnosis identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .evaluator import HypothesisEvaluation
from .evidence import EvidenceResult
from .ranking import (
    Convergence,
    MaterialContext,
    ParallelIssue,
    RankedHypothesis,
)
from .windows import DecisionWindow

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
    # v3.5.5: the single ranked evaluation all top fields derive from —
    # top_hypothesis / top_platform / top_evaluation_scope are its
    # hypothesis id, platform and evaluation_scope (never mixed sources).
    selected_evaluation: HypothesisEvaluation | None = None
    # v3.5.5: evaluation scope of the selected evaluation
    # (platform | shared | run).
    top_evaluation_scope: str | None = None
    # v3.5.5: the safety gate that blocked confident convergence
    # (measurement_invalid | maturity_insufficient | None). A block
    # changes convergence/action, never the ranked diagnosis.
    safety_block: str | None = None
    # v3.6.0: action eligibility for the recommended action
    # (eligible | not_eligible | needs_more_evidence | None) — diagnosis
    # and action eligibility are evaluated separately (a budget
    # constraint does not imply permission to scale).
    action_eligibility: str | None = None
    # v3.6.1: short reason for a blocked/deferred scale action.
    eligibility_reason: str | None = None
    # v3.6.2: supported independent issues on OTHER platforms — parallel
    # issues for explanation, never rivals that block the selected
    # platform's action (Google may scale while Meta fatigue is recorded
    # here). v3.6.3: every entry keeps its platform/scope attribution.
    parallel_issues: tuple[ParallelIssue, ...] = ()
    # v3.6.3: supported shared/run facts that do NOT block the selected
    # action but matter as material context (market-wide event, ...).
    material_context: tuple[MaterialContext, ...] = ()
    # v3.6.4: action readiness (ready | wait | needs_more_evidence |
    # not_eligible | None) — eligibility is NOT readiness.
    action_readiness: str | None = None
    # v3.6.4: why a material action was deferred (recent_change_unsettled...).
    wait_reason: str | None = None
    # v3.6.4: what evidence should trigger the next review (more_pay_outcomes...).
    next_review_trigger: str | None = None
    # v3.6.4: small | normal | none — reversible magnitude.
    action_magnitude: str | None = None
    # v3.6.4: the ONE material lever moved (budget | bid | creative |
    # measurement | None) — sequencing means never moving two levers.
    action_lever: str | None = None
    # v3.6.4: the primary KPI governing this action (audit + user-facing
    # KPI name) — resolved from the action context, never guessed.
    primary_kpi: str | None = None
    # v3.5.5: safety warnings per NON-selected platform (e.g.
    # {"meta": ("measurement_invalid",)}) — a warning on one platform is
    # never a veto on an independent diagnosis for another.
    platform_warnings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # v3.5.2: evidence provenance (per-platform signals, shared signals,
    # historical comparisons) — audit support, not default output.
    evidence: EvidenceResult | None = None
    # v3.6.5: the STATE-DERIVED decision window behind action readiness —
    # latest relevant confirmed Change, comparable pre-change baseline,
    # KPI-aligned outcome delta (or the reason it could not be derived).
    decision_window: DecisionWindow | None = None


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
    platform_warnings: dict[str, tuple[str, ...]] | None = None,
    primary_kpi: str | None = None,
    decision_window: DecisionWindow | None = None,
) -> DecisionIntelligenceResult:
    """Build the public result from pipeline internals (single assembly
    point so the runtime entry and tests share identical semantics).

    v3.5.5: the selected evaluation is ``ranked[0]`` — convergence never
    replaces the diagnosis identity, so the top fields derive from ONE
    evaluation (hard invariant, enforced by tests).
    """
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
        selected_evaluation=top,
        top_evaluation_scope=(
            top.hypothesis.evaluation_scope if top is not None else None
        ),
        safety_block=convergence.safety_block,
        action_eligibility=convergence.action_eligibility,
        eligibility_reason=convergence.eligibility_reason,
        parallel_issues=convergence.parallel_issues,
        material_context=convergence.material_context,
        action_readiness=convergence.action_readiness,
        wait_reason=convergence.wait_reason,
        next_review_trigger=convergence.next_review_trigger,
        action_magnitude=convergence.action_magnitude,
        action_lever=convergence.action_lever,
        primary_kpi=primary_kpi,
        platform_warnings=dict(platform_warnings or {}),
        evidence=evidence,
        decision_window=decision_window,
    )


def decision_attribution(
    selected_evaluation: HypothesisEvaluation | None,
    run_platform_scope: tuple[str, ...],
) -> tuple[str | None, tuple[str, ...]]:
    """Platform attribution for a persisted Decision, derived from the
    SELECTED evaluation (v3.5.5): a platform-bound diagnosis persists
    with that platform; a shared/run diagnosis stays cross-platform
    with the run scope. A safety action never rewrites this attribution
    — investigate_measurement on a shared diagnosis is still a
    cross-platform Decision.
    """
    if (
        selected_evaluation is not None
        and selected_evaluation.platform
        and selected_evaluation.platform != "cross_platform"
    ):
        return selected_evaluation.platform, ()
    if run_platform_scope:
        return "cross_platform", run_platform_scope
    return None, ()
