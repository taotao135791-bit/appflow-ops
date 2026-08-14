"""Ranking and convergence for Ads Decision Intelligence (v3.5.5).

Ranking is deterministic and repeatable — never pseudo-probabilities.
Status priority: supported > unverified > insufficient_evidence >
weakened > excluded; ties break by score desc, then hypothesis id.

Convergence produces the smallest useful action: the top supported
hypothesis's first (smallest) action, with material exclusions, missing
evidence, and a review condition; when nothing is supported, the answer
is wait/investigate with the most decisive missing evidence named —
never a forced recommendation.

A materially supported runner-up (status=supported with a material
score) is a MAJOR ALTERNATIVE: score gap alone never eliminates it —
the runtime converges to investigate plus the next discriminating
evidence instead of a confident action (v3.5.1).

Safety follows the SELECTED evaluation's provenance (v3.5.5): a
platform-bound top consumes that platform's own measurement/maturity
(missing platform safety resolves to "unknown", never an aggregate
fallback), shared and run-level tops consume the aggregate states. A
safety block changes the convergence/action, never the ranked diagnosis
identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .calibration import SCALE_ACTIONS, scale_eligibility
from .evaluator import SUPPORTED_THRESHOLD, HypothesisEvaluation

_STATUS_ORDER: dict[str, int] = {
    "supported": 0,
    "unverified": 1,
    "insufficient_evidence": 2,
    "weakened": 3,
    "excluded": 4,
}

# Convergence: how much evidence the top hypothesis needs.
CONVERGE_SCORE_THRESHOLD = 4
# A supported hypothesis with at least this score carries MATERIAL
# supporting evidence (v3.5.1) — it cannot be dismissed by score gap.
MAJOR_ALTERNATIVE_THRESHOLD = SUPPORTED_THRESHOLD


@dataclass(frozen=True)
class SafetyContext:
    """Safety states resolved per evaluation scope (v3.5.5).

    platform-bound evaluations consume the platform's own
    measurement/maturity; shared and run-level evaluations consume the
    aggregate states. A platform-bound evaluation whose platform has no
    safety evidence resolves to "unknown" — never a silent aggregate
    fallback (a safety problem on one platform is not a veto on an
    independent diagnosis for another platform, and a missing platform's
    safety is not pretended to be stable).
    """

    measurement_by_platform: Mapping[str, str] = field(default_factory=dict)
    maturity_by_platform: Mapping[str, str] = field(default_factory=dict)
    aggregate_measurement: str = "stable"
    aggregate_maturity: str = "sufficient"


def resolve_evaluation_safety(
    evaluation: HypothesisEvaluation | None,
    safety_context: SafetyContext,
) -> tuple[str, str]:
    """Safety (measurement, maturity) for the SELECTED evaluation,
    following its scope (v3.5.5):

    - evaluation_scope="platform" + a media platform → that platform's
      own measurement/maturity (missing → "unknown");
    - evaluation_scope="shared" → aggregate/shared Safety;
    - evaluation_scope="run" → aggregate/run Safety.

    Never infers scope from hypothesis names or string matching — the
    ranked evaluation already carries ``platform`` and
    ``evaluation_scope``; use them directly.
    """
    if evaluation is None:
        return safety_context.aggregate_measurement, safety_context.aggregate_maturity
    if (
        evaluation.hypothesis.evaluation_scope == "platform"
        and evaluation.platform
        and evaluation.platform != "cross_platform"
    ):
        return (
            safety_context.measurement_by_platform.get(evaluation.platform, "unknown"),
            safety_context.maturity_by_platform.get(evaluation.platform, "unknown"),
        )
    return safety_context.aggregate_measurement, safety_context.aggregate_maturity


@dataclass(frozen=True)
class RankedHypothesis:
    evaluation: HypothesisEvaluation
    rank: int


@dataclass(frozen=True)
class Convergence:
    """The smallest useful operational answer."""

    decision: str  # action class: wait | investigate | observe | replace | retest | pause | scale | increase | decrease | hold | investigate_measurement
    top_hypothesis: str | None
    rank: int = 0
    confidence: str = "low"  # high | medium | low
    rationale: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    review_condition: str | None = None
    converged: bool = False
    # Competing hypotheses that prevented confident convergence (v3.5.1).
    material_alternatives: tuple[str, ...] = ()
    # Evidence that would separate the top hypothesis from its rival.
    next_discriminating_evidence: tuple[str, ...] = ()
    # v3.5.5: the safety gate that blocked confident convergence
    # (measurement_invalid | maturity_insufficient | None). The ranked
    # diagnosis identity is preserved — a block changes the action, not
    # the hypothesis.
    safety_block: str | None = None
    # v3.6.0: action eligibility for the final action
    # (eligible | not_eligible | needs_more_evidence | None when no
    # eligibility gate applies) — diagnosis and action eligibility are
    # evaluated separately.
    action_eligibility: str | None = None
    # v3.6.1: short reason for a blocked/deferred scale action
    # (thin_kpi_headroom | low_conversion_volume | weak_sample |
    # recent_change | measurement_unreliable | maturity_insufficient |
    # None).
    eligibility_reason: str | None = None


def rank_hypotheses(
    evaluations: tuple[HypothesisEvaluation, ...],
) -> tuple[RankedHypothesis, ...]:
    """Deterministic ranking: status priority, then score desc, then id."""
    ordered = sorted(
        evaluations,
        key=lambda ev: (
            _STATUS_ORDER.get(ev.status, 5),
            -ev.score,
            ev.hypothesis.id,
            ev.platform or "",
        ),
    )
    return tuple(
        RankedHypothesis(evaluation=ev, rank=index)
        for index, ev in enumerate(ordered, start=1)
    )


def _first_action(hypothesis_id: str | None, actions: tuple[str, ...]) -> str | None:
    """Smallest-first action ordering; returns the first present action."""
    if not actions:
        return None
    return actions[0]


def _discriminating_evidence(
    top: HypothesisEvaluation, runner: HypothesisEvaluation
) -> tuple[str, ...]:
    """Evidence that would separate two supported candidates: signal ids
    that support the runner but not the top (observing them shifts the
    balance); fallback to required evidence the runner needs that the top
    does not. Never chain-of-thought — only what evidence is missing."""
    top_support = set(top.hypothesis.supporting_signals)
    runner_support = set(runner.hypothesis.supporting_signals)
    discriminating = runner_support - top_support
    if discriminating:
        return tuple(sorted(discriminating))[:3]
    top_required = set(top.hypothesis.required_evidence)
    runner_required = set(runner.hypothesis.required_evidence)
    return tuple(sorted(runner_required - top_required))[:3]


def converge(
    ranked: tuple[RankedHypothesis, ...],
    *,
    measurement_state: str = "stable",
    maturity_state: str = "sufficient",
    safety_context: SafetyContext | None = None,
    action_context: Mapping[str, object] | None = None,
) -> Convergence:
    """Converge to the smallest useful action (or an honest wait).

    Provenance-aware (v3.5.5): when ``safety_context`` is provided the
    Safety used for convergence is resolved from the SELECTED
    evaluation's scope (``resolve_evaluation_safety``) — a
    platform-bound top uses that platform's measurement/maturity
    (missing → unknown, never an aggregate fallback), shared/run tops
    use the aggregate states. ``measurement_state``/``maturity_state``
    remain for library callers without a SafetyContext (aggregate
    semantics; the runtime-native path always passes a SafetyContext).

    Eligibility-aware (v3.6.0): when ``action_context`` is provided and
    the smallest action is a scaling action (increase/scale), the action
    is gated by ``scale_eligibility`` — a budget/bid constraint is a
    DIAGNOSIS, not permission to scale; bad efficiency or an unsettled
    recent change downgrades the action to hold/wait.
    """
    top = ranked[0].evaluation if ranked else None
    if top is None:
        return Convergence(
            decision="investigate", top_hypothesis=None, rationale=("没有可用假设",)
        )

    if safety_context is not None:
        measurement_state, maturity_state = resolve_evaluation_safety(
            top, safety_context
        )

    exclusions = tuple(
        ev.evaluation.hypothesis.id
        for ev in ranked
        if ev.evaluation.status == "excluded"
    )
    missing = tuple(sorted({item for ev in ranked for item in ev.evaluation.missing}))

    # Measurement first: invalid measurement blocks confident convergence
    # (Scenario 7) — investigate measurement before anything else. The
    # ranked diagnosis identity is preserved: a block changes the
    # action, not the hypothesis (v3.5.5).
    if measurement_state == "invalid":
        return Convergence(
            decision="investigate_measurement",
            top_hypothesis=top.hypothesis.id,
            confidence="medium",
            rationale=(
                (
                    f"{top.hypothesis.label} 仍是当前最强诊断，但 measurement 不可信，"
                    "先排查数据/归因问题"
                ),
            ),
            exclusions=exclusions,
            missing_evidence=missing,
            review_condition="measurement 恢复可信后再重新诊断",
            safety_block="measurement_invalid",
            converged=False,
        )

    # Insufficient maturity: honest wait (Scenario 8). The diagnosis
    # identity is preserved; the block gates convergence, not the rank.
    if maturity_state == "insufficient":
        return Convergence(
            decision="wait",
            top_hypothesis=top.hypothesis.id,
            confidence="low",
            rationale=(
                (
                    f"{top.hypothesis.label} 仍是最强候选，但样本/数据成熟度不足，"
                    "不能确认任何原因；先观察一个完整窗口"
                ),
            ),
            exclusions=exclusions,
            missing_evidence=missing,
            review_condition="积累足够样本后复查",
            safety_block="maturity_insufficient",
            converged=False,
        )

    if top.status == "supported" and (
        top.score >= 6 or (top.score >= CONVERGE_SCORE_THRESHOLD and not top.missing)
    ):
        # A materially supported runner-up is a MAJOR ALTERNATIVE: score
        # gap alone never eliminates it (v3.5.1). Confident convergence is
        # only allowed when the runner-up is weakened/excluded or lacks
        # material support.
        runner = ranked[1].evaluation if len(ranked) > 1 else None
        major_alternative = (
            runner is not None
            and runner.status == "supported"
            and runner.score >= MAJOR_ALTERNATIVE_THRESHOLD
        )
        if major_alternative and runner is not None:
            return Convergence(
                decision="investigate",
                top_hypothesis=top.hypothesis.id,
                confidence="medium",
                rationale=(
                    (
                        f"候选原因并存：{top.hypothesis.id} 与 "
                        f"{runner.hypothesis.id} 都有实质支持，不能仅凭分差收敛；"
                        f"先补充区分性证据"
                    ),
                ),
                exclusions=exclusions,
                missing_evidence=missing,
                material_alternatives=(top.hypothesis.id, runner.hypothesis.id),
                next_discriminating_evidence=_discriminating_evidence(top, runner),
                review_condition="补齐区分性证据后再收敛",
                converged=False,
            )
        action = _first_action(top.hypothesis.id, top.hypothesis.possible_actions)
        if action is None:
            action = "observe"
        # v3.6.0: Diagnosis != Action. A scaling action (increase/scale) is
        # only emitted when scale is actually eligible — a budget
        # constraint proves the cap, not that adding budget is wise.
        # v3.6.1: eligibility is stricter — KPI pass is necessary, not
        # sufficient (headroom, outcome volume, sample, recent change).
        eligibility: str | None = None
        eligibility_reason: str | None = None
        if action in SCALE_ACTIONS and action_context is not None:
            eligibility, eligibility_reason = scale_eligibility(action_context)
            if eligibility == "not_eligible":
                action = "hold"
            elif eligibility == "needs_more_evidence":
                action = "wait"
        confidence = "high" if top.score >= 6 else "medium"
        return Convergence(
            decision=action,
            top_hypothesis=top.hypothesis.id,
            confidence=confidence,
            rationale=top.rationale,
            exclusions=exclusions,
            missing_evidence=missing,
            review_condition="按约定窗口（X spend / Y impressions）复查",
            action_eligibility=eligibility,
            eligibility_reason=eligibility_reason,
            converged=True,
        )

    # Not enough to converge: name the decisive missing evidence.
    if missing:
        message = (
            f"暂时不要调。最缺的是 {', '.join(missing[:3])}；拿到后才能区分候选原因"
        )
    else:
        message = "证据不足以收敛到单一原因，先保持观察"
    return Convergence(
        decision="wait" if top.status != "weakened" else "investigate",
        # v3.6.0: the ranked diagnosis identity is ALWAYS preserved — an
        # honest wait still names its strongest candidate (top fields
        # derive from ONE selected evaluation; no evidence does not make
        # the candidate vanish).
        top_hypothesis=top.hypothesis.id,
        confidence="low",
        rationale=(message,),
        exclusions=exclusions,
        missing_evidence=missing,
        review_condition="补充证据后复查",
        converged=False,
    )
