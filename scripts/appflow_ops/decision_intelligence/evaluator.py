"""Hypothesis evaluation for Ads Decision Intelligence (v3.5.0).

evaluate_hypotheses() turns a hypothesis set + observed signals into
structured evaluations: status, score (interpretable: +2 support, -2
contradiction, 0 missing), supporting/contradicting evidence, missing
evidence, and short rationale lines. No chain-of-thought is produced or
persisted — only the evidence summary is exposed.

Safety gates cap status: with invalid measurement only the measurement
hypothesis may be supported; with insufficient maturity nothing may be
supported (Scenario 7/8).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .evidence import EvidenceResult
from .hypotheses import HypothesisSpec

# Evidence keys whose presence can be satisfied by multiple signal ids.
# e.g. required evidence "measurement_health" is satisfied when the
# signal measurement_invalid (or measurement_stable) is present.
_EVIDENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "measurement_health": ("measurement_invalid", "measurement_stable"),
    "per_platform_comparison": ("only_one_creative_declines", "delivery_mix_shifted"),
    "cross_platform_comparison": (
        "cross_pay_rate_drop",
        "cross_cvr_drop",
        "cross_registration_drop",
        "cross_install_drop",
        "cross_platform_comparison_available",
    ),
    "recent_change": (
        "recent_budget_change",
        "recent_bid_change",
        "learning_reset",
        "no_recent_change",
    ),
    "maturity_state": ("maturity_insufficient", "maturity_sufficient"),
    "delivery_state": ("delivery_mix_shifted", "delivery_concentrated"),
    "downstream_data": ("downstream_conversion_down", "pay_rate_trend_down"),
}

HYPOTHESIS_STATUSES = (
    "supported",
    "unverified",
    "weakened",
    "excluded",
    "insufficient_evidence",
)

# Interpretable scoring (must stay explainable; never a hidden ML score).
SUPPORT_WEIGHT = 2
CONTRADICTION_WEIGHT = -2
# Strong support (>= 6) survives missing non-required evidence; moderate
# support (4-5) requires no missing required evidence to be "supported".
SUPPORTED_THRESHOLD = 4
STRONG_SUPPORTED_THRESHOLD = 6
# Missing more than this share of required evidence caps confidence.
MAX_MISSING_REQUIRED_SHARE = 0.5


@dataclass(frozen=True)
class HypothesisEvaluation:
    """Evaluation of one hypothesis against observed signals."""

    hypothesis: HypothesisSpec
    status: str  # one of HYPOTHESIS_STATUSES
    score: int
    supporting: tuple[str, ...]
    contradicting: tuple[str, ...]
    missing: tuple[str, ...]
    rationale: tuple[str, ...]
    safety_capped: bool = False
    # v3.5.3: evidence attribution — the platform this evaluation is
    # bound to ("cross_platform" for shared hypotheses, a media platform
    # for platform-bound evaluations, None for generic "*" hypotheses).
    platform: str | None = None


def _evidence_present(evidence: str, signals: Mapping[str, bool]) -> bool:
    """Whether required evidence is satisfied by observed signals (direct
    signal id, signal prefix, or an alias mapping)."""
    for signal in signals:
        if signal == evidence or signal.startswith(f"{evidence}_"):
            return True
    return any(alias in signals for alias in _EVIDENCE_ALIASES.get(evidence, ()))


def evaluate_hypothesis(
    hypothesis: HypothesisSpec,
    signals: Mapping[str, bool],
    *,
    measurement_state: str = "stable",
    maturity_state: str = "sufficient",
    platform: str | None = None,
) -> HypothesisEvaluation:
    """Evaluate one hypothesis. Deterministic and repeatable.

    Order: exclusion → support/contradiction scoring → missing-evidence
    cap → safety cap (invalid measurement / insufficient maturity).
    ``platform`` records the evidence attribution of this evaluation.
    """
    supporting = tuple(
        signal for signal in hypothesis.supporting_signals if signals.get(signal)
    )
    contradicting = tuple(
        signal for signal in hypothesis.contradicting_signals if signals.get(signal)
    )
    excluded = any(
        signals.get(condition) for condition in hypothesis.exclusion_conditions
    )
    missing = tuple(
        evidence
        for evidence in hypothesis.required_evidence
        if not _evidence_present(evidence, signals)
    )

    if excluded:
        return HypothesisEvaluation(
            hypothesis=hypothesis,
            status="excluded",
            score=0,
            supporting=supporting,
            contradicting=contradicting,
            missing=missing,
            rationale=(
                f"{hypothesis.label}：{contradicting[0] if contradicting else '排除条件命中'}",
            ),
            platform=platform,
        )

    score = SUPPORT_WEIGHT * len(supporting) + CONTRADICTION_WEIGHT * len(contradicting)
    safety_capped = False
    # Safety caps: with invalid measurement, only the measurement
    # hypothesis may claim support; with insufficient maturity, no
    # hypothesis may claim support (not enough data to confirm anything).
    if measurement_state == "invalid" and hypothesis.id != "measurement_instability":
        safety_capped = True
    if maturity_state == "insufficient":
        safety_capped = True

    if (
        score >= STRONG_SUPPORTED_THRESHOLD
        and not safety_capped
        or score >= SUPPORTED_THRESHOLD
        and not missing
        and not safety_capped
    ):
        status = "supported"
    elif score < 0:
        status = "weakened"
    elif (
        missing
        and len(missing) / max(len(hypothesis.required_evidence), 1)
        > MAX_MISSING_REQUIRED_SHARE
    ):
        status = "insufficient_evidence"
    else:
        status = "unverified"

    rationale: list[str] = []
    if supporting:
        rationale.append(f"{hypothesis.label}：支持证据 {', '.join(supporting)}")
    if contradicting:
        rationale.append(f"{hypothesis.label}：反驳证据 {', '.join(contradicting)}")
    if safety_capped:
        rationale.append(f"{hypothesis.label}：当前 measurement/maturity 不足以确认")
    if not rationale:
        rationale.append(f"{hypothesis.label}：证据不足，保持待验证")
    return HypothesisEvaluation(
        hypothesis=hypothesis,
        status=status,
        score=score,
        supporting=supporting,
        contradicting=contradicting,
        missing=missing,
        rationale=tuple(rationale),
        safety_capped=safety_capped,
        platform=platform,
    )


def evaluate_hypotheses(
    hypotheses: tuple[HypothesisSpec, ...],
    signals_or_evidence: Mapping[str, bool] | EvidenceResult,
    *,
    platform_scope: tuple[str, ...] = (),
    measurement_state: str = "stable",
    maturity_state: str = "sufficient",
) -> tuple[HypothesisEvaluation, ...]:
    """Evaluate every hypothesis in the set (deterministic order).

    Provenance-aware (v3.5.3): when an ``EvidenceResult`` is passed,
    every hypothesis only consumes the evidence that is semantically
    valid for it —

    - cross-platform hypotheses (applicable_platforms contains
      "cross_platform") consume ``shared_signals`` only;
    - generic "*" hypotheses consume the aggregate union (generic cases);
    - platform-bound hypotheses are evaluated PER PLATFORM against that
      platform's own ``signals_by_platform`` — Meta signals can never be
      spliced into a Google evaluation (or vice versa).

    The canonical safety context is injected as signals (invalid
    measurement / insufficient maturity / stable measurement), so eval
    fixtures and the runtime path share identical signal semantics.
    """
    from .evidence import add_context_signals

    if isinstance(signals_or_evidence, EvidenceResult):
        evidence: EvidenceResult = signals_or_evidence
    else:
        # Plain-dict mode (unit tests / library callers): no per-platform
        # provenance exists, so platform-bound hypotheses fall back to the
        # aggregate union exactly like the pre-v3.5.3 behavior.
        evidence = EvidenceResult(signals=dict(signals_or_evidence))

    evaluations: list[HypothesisEvaluation] = []
    for hypothesis in hypotheses:
        applicable = hypothesis.applicable_platforms
        if "cross_platform" in applicable:
            augmented = dict(evidence.shared_signals)
            add_context_signals(
                augmented,
                measurement_state=measurement_state,
                maturity_state=maturity_state,
            )
            evaluations.append(
                evaluate_hypothesis(
                    hypothesis,
                    augmented,
                    measurement_state=measurement_state,
                    maturity_state=maturity_state,
                    platform="cross_platform",
                )
            )
        elif "*" in applicable:
            augmented = dict(evidence.signals)
            add_context_signals(
                augmented,
                measurement_state=measurement_state,
                maturity_state=maturity_state,
            )
            evaluations.append(
                evaluate_hypothesis(
                    hypothesis,
                    augmented,
                    measurement_state=measurement_state,
                    maturity_state=maturity_state,
                    platform=None,
                )
            )
        else:
            if evidence.signals_by_platform:
                # Provenance mode: evaluate the hypothesis PER PLATFORM
                # against that platform's own signals only.
                for platform in platform_scope:
                    if platform not in applicable:
                        continue
                    augmented = dict(evidence.signals_by_platform.get(platform, {}))
                    add_context_signals(
                        augmented,
                        measurement_state=measurement_state,
                        maturity_state=maturity_state,
                    )
                    evaluations.append(
                        evaluate_hypothesis(
                            hypothesis,
                            augmented,
                            measurement_state=measurement_state,
                            maturity_state=maturity_state,
                            platform=platform,
                        )
                    )
            else:
                # Plain-dict / no-provenance mode (unit tests, library
                # callers): legacy aggregate evaluation, unbound.
                augmented = dict(evidence.signals)
                add_context_signals(
                    augmented,
                    measurement_state=measurement_state,
                    maturity_state=maturity_state,
                )
                evaluations.append(
                    evaluate_hypothesis(
                        hypothesis,
                        augmented,
                        measurement_state=measurement_state,
                        maturity_state=maturity_state,
                        platform=None,
                    )
                )
    return tuple(evaluations)
