"""Ranking and convergence for Ads Decision Intelligence (v3.5.0).

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
"""

from __future__ import annotations

from dataclasses import dataclass

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
) -> Convergence:
    """Converge to the smallest useful action (or an honest wait)."""
    top = ranked[0].evaluation if ranked else None
    if top is None:
        return Convergence(
            decision="investigate", top_hypothesis=None, rationale=("没有可用假设",)
        )

    exclusions = tuple(
        ev.evaluation.hypothesis.id
        for ev in ranked
        if ev.evaluation.status == "excluded"
    )
    missing = tuple(sorted({item for ev in ranked for item in ev.evaluation.missing}))

    # Measurement first: invalid measurement blocks confident convergence
    # (Scenario 7) — investigate measurement before anything else.
    if measurement_state == "invalid":
        return Convergence(
            decision="investigate_measurement",
            top_hypothesis="measurement_instability",
            confidence="medium",
            rationale=("当前 measurement 不可信，先排查数据/归因问题",),
            exclusions=exclusions,
            missing_evidence=missing,
            review_condition="measurement 恢复可信后再重新诊断",
            converged=False,
        )

    # Insufficient maturity: honest wait (Scenario 8).
    if maturity_state == "insufficient":
        return Convergence(
            decision="wait",
            top_hypothesis=top.hypothesis.id if top.status == "supported" else None,
            confidence="low",
            rationale=("样本/数据成熟度不足，不能确认任何原因；先观察一个完整窗口",),
            exclusions=exclusions,
            missing_evidence=missing,
            review_condition="积累足够样本后复查",
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
        confidence = "high" if top.score >= 6 else "medium"
        return Convergence(
            decision=action,
            top_hypothesis=top.hypothesis.id,
            confidence=confidence,
            rationale=top.rationale,
            exclusions=exclusions,
            missing_evidence=missing,
            review_condition="按约定窗口（X spend / Y impressions）复查",
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
        top_hypothesis=top.hypothesis.id
        if top.status in ("supported", "unverified")
        else None,
        confidence="low",
        rationale=(message,),
        exclusions=exclusions,
        missing_evidence=missing,
        review_condition="补充证据后复查",
        converged=False,
    )
