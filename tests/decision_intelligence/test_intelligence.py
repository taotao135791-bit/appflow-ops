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
    build_hypothesis_set,
    converge,
    evaluate_hypotheses,
    hypothesis_by_id,
    rank_hypotheses,
    signals_from_metrics,
    signals_from_platforms,
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


def test_exclusion_condition_excludes() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {"ctr_trend_down": True, "recent_budget_change": True}
    evals = evaluate_hypotheses(specs, signals)
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status == "excluded"


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


def test_budget_confounder_blocks_fatigue() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {
        "ctr_trend_down": True,
        "recent_budget_change": True,
        "delivery_mix_shifted": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    ranked = rank_hypotheses(evals)
    fatigue = next(
        r.evaluation for r in ranked if r.evaluation.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status == "excluded"
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
        cross_platform=case.get("cross_platform", False),
    )
    assert specs, f"{case['id']}: empty hypothesis set"
    # Layer 1: raw metrics → signals (v3.5.1). Fixtures may provide raw
    # relative movement instead of hand-polished signals; when both exist
    # the raw extraction runs FIRST and explicit signals only fill gaps.
    # Cross-platform fixtures may provide per-platform raw metrics, which
    # additionally produce cross-level aggregations.
    signals: dict[str, bool] = {}
    if case.get("per_platform_metrics"):
        signals.update(signals_from_platforms(case["per_platform_metrics"]))
        signals = {k: v for k, v in signals.items() if v}
    elif case.get("metrics"):
        signals.update(signals_from_metrics(case["metrics"]))
        signals = {k: v for k, v in signals.items() if v}
    signals.update({k: v for k, v in case.get("signals", {}).items() if v})
    evals = evaluate_hypotheses(
        specs,
        signals,
        measurement_state=case.get("measurement", "stable"),
        maturity_state=case.get("maturity", "sufficient"),
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

    # forbidden_top: a hypothesis that must NEVER be the ranked top.
    for forbidden in case.get("forbidden_top", []):
        assert not ranked_live or ranked_live[0].hypothesis.id != forbidden, (
            f"{case['id']}: forbidden top {forbidden}"
        )

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


def test_eval_case_set_size() -> None:
    assert len(CASES) >= 25, "eval set should be substantial"
