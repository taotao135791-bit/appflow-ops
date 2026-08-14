"""Unit tests for hypothesis construction, evidence evaluation, ranking,
adversarial/confounder/missing-data semantics, and the eval case set."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    ALL_HYPOTHESES,
    META_HYPOTHESES,
    SIGNAL_IDS,
    TIKTOK_HYPOTHESES,
    SafetyContext,
    build_evidence,
    build_hypothesis_set,
    converge,
    evaluate_hypotheses,
    hypothesis_by_id,
    rank_hypotheses,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── construction ─────────────────────────────────────────────────────────


def test_hypothesis_ids_unique() -> None:
    ids = [spec.id for spec in ALL_HYPOTHESES]
    assert len(ids) == len(set(ids))


def test_signal_ids_are_known() -> None:
    known = set(SIGNAL_IDS)
    for spec in ALL_HYPOTHESES:
        for signal in (
            *spec.supporting_signals,
            *spec.contradicting_signals,
            *spec.exclusion_conditions,
        ):
            assert signal in known, f"{spec.id}: unknown signal {signal}"


def test_hypothesis_registry_lookup() -> None:
    assert hypothesis_by_id("creative_fatigue") is not None
    assert hypothesis_by_id("nope") is None


def test_build_hypothesis_set_platform_and_domain() -> None:
    # domain is a routing hint: the evaluation set covers every
    # platform-appropriate candidate so rivals are always compared.
    meta = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    ids = {spec.id for spec in meta}
    assert {
        "creative_fatigue",
        "creative_message_mismatch",
        "creative_format_mismatch",
    } <= ids
    assert "auction_pressure" in ids  # rival stays in the set
    tiktok = build_hypothesis_set(platform_scope=("tiktok",))
    tiktok_ids = {spec.id for spec in tiktok}
    assert "click_to_install_friction" in tiktok_ids
    assert "shared_product_funnel_issue" not in tiktok_ids  # cross-only


def test_build_hypothesis_set_cross_platform() -> None:
    specs = build_hypothesis_set(
        platform_scope=("google_ads", "meta"), cross_platform=True
    )
    ids = {spec.id for spec in specs}
    assert "shared_product_funnel_issue" in ids
    assert "shared_measurement_issue" in ids


def test_meta_families_present() -> None:
    ids = {spec.id for spec in META_HYPOTHESES}
    assert {
        "creative_fatigue",
        "creative_message_mismatch",
        "creative_format_mismatch",
        "auction_pressure",
        "delivery_mix_shift",
        "learning_or_relearning",
        "audience_saturation",
        "audience_quality_shift",
        "post_click_friction",
        "conversion_funnel_degradation",
        "measurement_instability",
        "bid_constraint",
        "budget_constraint",
        "recent_budget_bid_interference",
    } <= ids


def test_tiktok_funnel_hypotheses_present() -> None:
    ids = {spec.id for spec in TIKTOK_HYPOTHESES}
    assert {
        "click_to_install_friction",
        "store_page_friction",
        "registration_friction",
        "pay_funnel_degradation",
        "install_measurement_issue",
        "traffic_quality_shift",
        "hook_or_click_quality",
    } <= ids


# ── evaluation ───────────────────────────────────────────────────────────


def test_fatigue_supported_with_strong_signals() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    signals = {
        "ctr_trend_down": True,
        "old_creative_worse": True,
        "frequency_trend_up": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status == "supported"
    assert fatigue.score == 6


def test_contradiction_weakens() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {"ctr_trend_stable": True}
    evals = evaluate_hypotheses(specs, signals)
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status == "weakened"
    assert fatigue.score == -2


def test_recent_change_is_confounder_not_exclusion() -> None:
    # v3.6.0: a recent budget change never proves fatigue impossible — it
    # weakens it (contradiction), it does not exclude it (confounder).
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {"ctr_trend_down": True, "recent_budget_change": True}
    evals = evaluate_hypotheses(specs, signals)
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status != "excluded"
    assert fatigue.status in ("unverified", "weakened")


def test_missing_required_evidence_blocks_moderate_support() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    # Moderate support (4) but required creative_age_data missing.
    signals = {"ctr_trend_down": True, "old_creative_worse": True}
    evals = evaluate_hypotheses(specs, signals)
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status != "supported"
    assert fatigue.missing  # creative_age_data


def test_invalid_measurement_caps_all_but_measurement() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {
        "ctr_trend_down": True,
        "cpm_trend_stable": True,
        "measurement_invalid": True,
    }
    evals = evaluate_hypotheses(
        specs, signals, measurement_state="invalid", maturity_state="sufficient"
    )
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status != "supported"
    assert fatigue.safety_capped
    measurement = next(e for e in evals if e.hypothesis.id == "measurement_instability")
    assert measurement.status == "unverified"  # only 2 points, not enough


def test_insufficient_maturity_caps_everything() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {"ctr_trend_down": True, "old_creative_worse": True}
    evals = evaluate_hypotheses(
        specs, signals, measurement_state="stable", maturity_state="insufficient"
    )
    assert all(e.status != "supported" for e in evals)


# ── ranking & convergence ────────────────────────────────────────────────


def test_ranking_is_deterministic() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    signals = {
        "ctr_trend_down": True,
        "old_creative_worse": True,
        "frequency_trend_up": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    first = rank_hypotheses(evals)
    second = rank_hypotheses(evals)
    assert [(r.rank, r.evaluation.hypothesis.id) for r in first] == [
        (r.rank, r.evaluation.hypothesis.id) for r in second
    ]
    assert first[0].evaluation.hypothesis.id == "creative_fatigue"


def test_converge_wait_when_unsupported() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(specs, {"ctr_trend_stable": True})
    ranked = rank_hypotheses(evals)
    result = converge(ranked)
    assert result.decision == "wait"
    assert result.converged is False


def test_converge_investigates_measurement_when_invalid() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(
        specs, {"cvr_trend_down": True}, measurement_state="invalid"
    )
    ranked = rank_hypotheses(evals)
    result = converge(ranked, measurement_state="invalid")
    assert result.decision == "investigate_measurement"
    assert result.converged is False


def test_converge_honest_wait_on_insufficient_maturity() -> None:
    specs = build_hypothesis_set(platform_scope=("tiktok",))
    evals = evaluate_hypotheses(
        specs, {"ctr_trend_down": True}, maturity_state="insufficient"
    )
    ranked = rank_hypotheses(evals)
    result = converge(ranked, maturity_state="insufficient")
    assert result.decision == "wait"
    assert result.converged is False


def test_converge_names_missing_evidence() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(specs, {"ctr_trend_down": True})
    ranked = rank_hypotheses(evals)
    result = converge(ranked)
    assert result.converged is False
    assert result.missing_evidence  # names the decisive gap


# ── adversarial / confounder / missing data ──────────────────────────────


def test_single_metric_cannot_confirm_fatigue() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    evals = evaluate_hypotheses(specs, {"ctr_trend_down": True})
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status != "supported"  # 2 points only


def test_recent_change_confounder_keeps_fatigue_candidate() -> None:
    # v3.6.0: recent change + real fatigue evidence can coexist; the
    # change hypothesis ranks first without hard-excluding fatigue.
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {
        "ctr_trend_down": True,
        "recent_budget_change": True,
        "delivery_mix_shifted": True,
        "old_creative_worse": True,
        "frequency_trend_up": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    ranked = rank_hypotheses(evals)
    fatigue = next(
        r.evaluation for r in ranked if r.evaluation.hypothesis.id == "creative_fatigue"
    )
    # Fatigue is NOT excluded: 6 support - 2 confounder = 4 (supported).
    assert fatigue.status != "excluded"
    assert fatigue.score == 4
    top = ranked[0].evaluation
    assert top.hypothesis.id == "recent_budget_bid_interference" or (
        top.hypothesis.id == "delivery_mix_shift"
    )


def test_missing_cpm_keeps_auction_candidate() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(
        specs, {"ctr_trend_down": True, "old_creative_worse": True}
    )
    auction = next(e for e in evals if e.hypothesis.id == "auction_pressure")
    assert auction.status != "excluded"  # never wrongly excluded
    assert auction.missing  # cpm_trend required, absent


def test_missing_frequency_keeps_saturation_candidate() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(specs, {"ctr_trend_down": True})
    saturation = next(e for e in evals if e.hypothesis.id == "audience_saturation")
    assert saturation.status != "supported"  # no frequency evidence
    assert saturation.missing


# ── eval case set (real scenarios) ───────────────────────────────────────


def _load_cases():
    path = REPO_ROOT / "evals" / "decision-intelligence-cases.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


CASES = _load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_eval_case(case) -> None:
    specs = build_hypothesis_set(
        platform_scope=tuple(case.get("platform_scope", ())),
        domain=case.get("domain"),
        # v3.5.2: cross semantics are DERIVED from platform_scope; the
        # legacy fixture field is no longer correctness-critical (None =
        # derive, and an explicit value contradicting the scope fails).
        cross_platform=case.get("cross_platform"),
    )
    assert specs, f"{case['id']}: empty hypothesis set"
    # Layer 1-2: raw metrics → signals (v3.5.1), with optional comparable
    # previous metrics deriving trends (v3.5.2). Fixtures may provide raw
    # relative movement instead of hand-polished signals; when both exist
    # the raw extraction runs FIRST and explicit signals only fill gaps.
    signals: dict[str, bool] = {}
    current_platforms = case.get("per_platform_metrics") or (
        {case["platform_scope"][0]: case["metrics"]}
        if case.get("metrics") and case.get("platform_scope")
        else None
    )
    previous_platforms = case.get("previous_per_platform_metrics") or (
        {case["platform_scope"][0]: case["previous_metrics"]}
        if case.get("previous_metrics") and case.get("platform_scope")
        else None
    )
    # v3.5.4 identity contract: a fixture's previous/current raw metrics
    # are EXPLICIT account-aggregate observations (entity_level=account +
    # aggregate_scope=account). Without this explicit marker, unknown
    # identity would legitimately block trend derivation.
    if previous_platforms:
        for platform_metrics in previous_platforms.values():
            platform_metrics.setdefault("entity_level", "account")
            platform_metrics.setdefault("aggregate_scope", "account")
    if current_platforms:
        for platform_metrics in current_platforms.values():
            platform_metrics.setdefault("entity_level", "account")
            platform_metrics.setdefault("aggregate_scope", "account")
    # v3.5.5: fixtures may declare per-platform Safety
    # (measurement_by_platform / maturity_by_platform) — the evaluator
    # then applies platform-bound Safety exactly like the runtime;
    # without the fields the legacy aggregate semantics apply.
    measurement_by_platform = case.get("measurement_by_platform")
    maturity_by_platform = case.get("maturity_by_platform")
    if current_platforms:
        recent_change_events: list[dict[str, object]] = []
        for change in case.get("recent_changes", []):
            change_type = str(change)
            recent_change_events.append(
                {
                    "payload": {
                        # fixture syntax "budget_increase" → canonical
                        # change_type "budget" + direction.
                        "change_type": change_type.split("_")[0],
                        "direction": "increase"
                        if change_type.endswith("increase")
                        else "decrease",
                        # Temporal semantics (v3.5.3): a Change is a
                        # confounder only when it intervened between the
                        # comparable baseline and the current observation.
                        "effective_at": case.get(
                            "recent_change_effective_at", "2026-08-13T12:00:00Z"
                        ),
                    },
                    "observed_at": "2026-08-13T12:00:00Z",
                }
            )
        evidence = build_evidence(
            per_platform=current_platforms,
            historical_by_platform=previous_platforms or None,
            recent_changes=tuple(recent_change_events),
            current_observed_at=(
                {platform: "2026-08-13T18:00:00Z" for platform in current_platforms}
                if current_platforms
                else None
            ),
            historical_observed_at=(
                {platform: "2026-08-12T09:00:00Z" for platform in previous_platforms}
                if previous_platforms
                else None
            ),
        )
        # Provenance mode (v3.5.3): the EvidenceResult goes to the
        # evaluator as-is — platform-bound hypotheses consume only their
        # platform's signals; shared hypotheses consume shared signals.
        # Legacy explicit-signal fixtures are treated as global facts:
        # they are visible at every layer (compat with old assertions).
        extra = {k: v for k, v in case.get("signals", {}).items() if v}
        if extra:
            evidence.signals.update(extra)
            for platform_signals in evidence.signals_by_platform.values():
                platform_signals.update(extra)
            evidence.shared_signals.update(extra)
        evals = evaluate_hypotheses(
            specs,
            evidence,
            platform_scope=tuple(case.get("platform_scope", ())),
            measurement_state=case.get("measurement", "stable"),
            maturity_state=case.get("maturity", "sufficient"),
            measurement_by_platform=measurement_by_platform,
            maturity_by_platform=maturity_by_platform,
        )
    else:
        signals = {k: v for k, v in case.get("signals", {}).items() if v}
        evals = evaluate_hypotheses(
            specs,
            signals,
            platform_scope=tuple(case.get("platform_scope", ())),
            measurement_state=case.get("measurement", "stable"),
            maturity_state=case.get("maturity", "sufficient"),
            measurement_by_platform=measurement_by_platform,
            maturity_by_platform=maturity_by_platform,
        )
    ranked = rank_hypotheses(evals)
    top = ranked[0].evaluation

    # acceptable top MUST be judged on RANKED results (v3.5.1): the first
    # non-weakened/non-excluded hypothesis in rank order. Registry order is
    # never a fallback — a wrong ranked top cannot be rescued by fixture
    # ordering (false-green).
    ranked_live = [
        item.evaluation
        for item in ranked
        if item.evaluation.status not in ("weakened", "excluded")
    ]
    acceptable_top = case.get("acceptable_top", [])
    if acceptable_top:
        assert ranked_live, f"{case['id']}: no live hypotheses to judge"
        assert ranked_live[0].hypothesis.id in acceptable_top, (
            f"{case['id']}: ranked top={ranked_live[0].hypothesis.id}"
            f"({ranked_live[0].status}) not in {acceptable_top}"
        )

    # forbidden_top: a hypothesis that must NEVER be the ranked top WITH
    # material (supported) evidence. An unverified top is an honest
    # "not enough evidence" answer, not a wrong conclusion (v3.5.3).
    for forbidden in case.get("forbidden_top", []):
        assert (
            not ranked_live
            or ranked_live[0].hypothesis.id != forbidden
            or ranked_live[0].status != "supported"
        ), f"{case['id']}: forbidden top {forbidden}"

    # creative must not be top for funnel-degradation cases.
    if case.get("creative_not_top"):
        assert top.hypothesis.id != "creative_fatigue", (
            f"{case['id']}: creative_fatigue wrongly top"
        )

    # required considerations must be evaluated (present in the set);
    # being excluded/weakened by evidence IS the point of consideration.
    for consideration in case.get("required_considerations", []):
        assert hypothesis_by_id(consideration) in specs or any(
            s.id == consideration for s in specs
        ), f"{case['id']}: missing consideration {consideration}"
        assert any(e.hypothesis.id == consideration for e in evals), (
            f"{case['id']}: consideration {consideration} not evaluated"
        )

    result = converge(
        ranked,
        measurement_state=case.get("measurement", "stable"),
        maturity_state=case.get("maturity", "sufficient"),
        # v3.5.5: convergence resolves Safety from the selected
        # evaluation's scope when per-platform Safety is declared — a
        # platform-bound top uses that platform's own Safety.
        safety_context=(
            SafetyContext(
                measurement_by_platform=measurement_by_platform or {},
                maturity_by_platform=maturity_by_platform or {},
                aggregate_measurement=case.get("measurement", "stable"),
                aggregate_maturity=case.get("maturity", "sufficient"),
            )
            if measurement_by_platform or maturity_by_platform
            else None
        ),
        # v3.6.0: action eligibility context — fixtures may declare
        # KPI/efficiency facts (cpa/target_cpa/...) to gate scale actions.
        # v3.6.4: fixtures may also declare window_context (last change /
        # current time) to gate action READINESS.
        action_context=case.get("action_context"),
        window_context=case.get("window_context"),
    )
    if case.get("convergence_blocked"):
        assert result.converged is False, (
            f"{case['id']}: expected non-convergence, got {result.decision}"
        )
    assert result.decision in case["acceptable_actions"], (
        f"{case['id']}: decision {result.decision} not in {case['acceptable_actions']}"
    )
    assert result.decision not in case.get("forbidden_actions", []), (
        f"{case['id']}: forbidden action {result.decision}"
    )
    # v3.5.5: attribution integrity — the final result fields must all
    # derive from the SAME selected evaluation (hard invariant, checked
    # for EVERY fixture), and fixtures may pin platform/scope/block.
    from appflow_ops.decision_intelligence.result import from_convergence

    result_full = from_convergence(
        convergence=result,
        platform_scope=tuple(case.get("platform_scope", ())),
        operational_domain=case.get("domain") or "general",
        evaluations=evals,
        ranked=ranked,
        safety_context={},
    )
    assert result_full.top_hypothesis == result_full.selected_evaluation.hypothesis.id
    if case.get("expected_top_platform") is not None:
        assert result_full.top_platform == case["expected_top_platform"], (
            f"{case['id']}: top platform {result_full.top_platform} != "
            f"{case['expected_top_platform']}"
        )
    if case.get("expected_top_scope") is not None:
        assert result_full.top_evaluation_scope == case["expected_top_scope"], (
            f"{case['id']}: top scope {result_full.top_evaluation_scope} != "
            f"{case['expected_top_scope']}"
        )
    if case.get("expected_safety_block") is not None:
        assert result_full.safety_block == case["expected_safety_block"], (
            f"{case['id']}: safety_block {result_full.safety_block} != "
            f"{case['expected_safety_block']}"
        )
    # v3.6.0: action eligibility assertions — diagnosis and action
    # eligibility are evaluated separately; a constraint diagnosis never
    # implies permission to scale.
    if case.get("expected_eligibility") is not None:
        assert result.action_eligibility == case["expected_eligibility"], (
            f"{case['id']}: action_eligibility {result.action_eligibility} != "
            f"{case['expected_eligibility']}"
        )
    if case.get("expected_eligibility_reason") is not None:
        assert result.eligibility_reason == case["expected_eligibility_reason"], (
            f"{case['id']}: eligibility_reason {result.eligibility_reason} != "
            f"{case['expected_eligibility_reason']}"
        )
    # v3.6.1: sample-strength assertions (weak/normal) for raw-metric
    # fixtures — e.g. expected_signal_strength: {ctr_trend_down: weak}.
    if case.get("expected_signal_strength") and current_platforms:
        for signal_id, strength in case["expected_signal_strength"].items():
            observed = evidence.signal_strength_by_platform.get(
                case["platform_scope"][0], {}
            ).get(signal_id)
            assert observed == strength, (
                f"{case['id']}: {signal_id} strength {observed} != {strength}"
            )
    # v3.6.2: parallel-issue assertions — supported independent issues
    # on OTHER platforms (e.g. expected_parallel_issues: [creative_fatigue])
    # must be recorded without blocking the selected platform's action.
    # v3.6.3: entries are attributed (ParallelIssue); fixtures declare
    # hypothesis ids only, the runner compares on the id dimension.
    if case.get("expected_parallel_issues") is not None:
        observed_ids = {p.hypothesis_id for p in result_full.parallel_issues}
        assert observed_ids == set(case["expected_parallel_issues"]), (
            f"{case['id']}: parallel_issues {observed_ids} != "
            f"{case['expected_parallel_issues']}"
        )
    # v3.6.3: material-context assertions — supported shared/run facts
    # that do NOT block the action (market-wide event, ...).
    if case.get("expected_material_context") is not None:
        observed_context = {m.hypothesis_id for m in result_full.material_context}
        assert observed_context == set(case["expected_material_context"]), (
            f"{case['id']}: material_context {observed_context} != "
            f"{case['expected_material_context']}"
        )
    # v3.6.4: timing assertions — eligibility != readiness; wait must
    # carry a reason and a next-review trigger; magnitude is small/normal.
    if case.get("expected_action_readiness") is not None:
        assert result.action_readiness == case["expected_action_readiness"], (
            f"{case['id']}: action_readiness {result.action_readiness} != "
            f"{case['expected_action_readiness']}"
        )
    if case.get("expected_wait_reason") is not None:
        assert result.wait_reason == case["expected_wait_reason"], (
            f"{case['id']}: wait_reason {result.wait_reason} != "
            f"{case['expected_wait_reason']}"
        )
    if case.get("expected_next_review_trigger") is not None:
        assert result.next_review_trigger == case["expected_next_review_trigger"], (
            f"{case['id']}: next_review_trigger {result.next_review_trigger} != "
            f"{case['expected_next_review_trigger']}"
        )
    if case.get("expected_action_magnitude") is not None:
        assert result.action_magnitude == case["expected_action_magnitude"], (
            f"{case['id']}: action_magnitude {result.action_magnitude} != "
            f"{case['expected_action_magnitude']}"
        )


def test_eval_case_set_size() -> None:
    assert len(CASES) >= 25, "eval set should be substantial"
