"""v3.6.1 calibration reliability & action eligibility tests.

Six reliability gaps fixed in this round:

A. scale eligibility follows the SELECTED evaluation's provenance — one
   platform's recent change never blocks another platform's scale;
B. measurement-DOMAIN diagnoses (not an ID whitelist) stay evaluable
   when measurement is invalid — invalid measurement is often the
   evidence FOR them;
C. missing sample size is UNKNOWN, never sufficient — evidence strength
   is downgraded, not inherited;
D. rate evidence considers numerator AND denominator — 2000 clicks with
   2 conversions is not a strong CVR decline;
E. scale eligibility requires KPI headroom, outcome volume, and settled
   recent changes — a marginal KPI pass (49 vs 50) defers scale;
F. bid eligibility follows the same gates.

Better to miss a scale opportunity than to recommend a bad scale.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    build_evidence,
    build_hypothesis_set,
    converge,
    evaluate_hypotheses,
    rank_hypotheses,
)
from appflow_ops.decision_intelligence.calibration import (
    sample_sufficiency,
)
from appflow_ops.runtime import PlatformOperationalRun
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


# ── A. Action provenance: platform isolation ─────────────────────────────


def test_google_scale_not_blocked_by_meta_recent_change(workspace) -> None:
    # Case 1 (spec §63): Meta changed budget recently; Google is a mature
    # scale candidate — Google eligibility must NOT inherit Meta's change.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "recent_budget_change": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 200,
            "impressions": 500000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.top_platform == "google_ads"
    # Meta's change must not leak into Google's eligibility.
    assert result.action_eligibility == "eligible"
    assert result.recommended_action == "increase"
    assert result.platform_warnings == {}  # Meta change is not a warning
    run.finish()


def test_meta_recent_change_blocks_meta_scale(workspace) -> None:
    # Same platform change DOES block that platform's own scale.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 200,
            "recent_budget_change": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_eligibility == "not_eligible"
    assert result.eligibility_reason == "recent_change"
    assert result.recommended_action == "hold"
    run.finish()


# ── B. Measurement-domain safety semantics ───────────────────────────────


def test_tiktok_install_measurement_supported_when_invalid(workspace) -> None:
    # Case 2 (spec §54): measurement invalid + reporting anomaly →
    # install_measurement_issue must be SUPPORTED — invalid measurement
    # is the evidence, never a cap on a measurement-domain diagnosis.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="安装回传是不是有问题？", platform_scope=("tiktok",))
    run.record_observation(
        {
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
            "reporting_anomaly": True,
            "clicks": 5000,
            "installs": 300,
        },
        platform="tiktok",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    install_measurement = next(
        ev
        for ev in result.evaluations
        if ev.hypothesis.id == "install_measurement_issue"
    )
    assert install_measurement.status == "supported"
    assert install_measurement.safety_capped is False
    assert "reporting_anomaly" in install_measurement.supporting
    run.finish()


def test_non_measurement_diagnoses_still_capped_when_invalid(workspace) -> None:
    # Case 55 (spec §55): invalid measurement + creative symptoms →
    # creative fatigue must NOT be confidently supported.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="素材衰减了吗？", platform_scope=("meta",))
    run.record_observation(
        {
            "ctr_change_pct": -0.25,
            "frequency_change_pct": 0.18,
            "impressions": 100000,
            "clicks": 5000,
            "old_creative_worse": True,
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    fatigue = next(
        ev for ev in result.evaluations if ev.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status != "supported"
    assert fatigue.safety_capped is True
    assert result.recommended_action == "investigate_measurement"
    run.finish()


def test_shared_measurement_evaluable_when_both_invalid() -> None:
    # Case 11 (spec §11): Meta+Google invalid + cross_measurement_invalid
    # → shared_measurement_issue evaluates normally (not capped by the
    # very invalidity that is its evidence).
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
            "google_ads": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
        },
        measurement_state="invalid",
        maturity_state="sufficient",
    )
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state="invalid",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "invalid"},
        maturity_by_platform={"meta": "unknown", "google_ads": "unknown"},
    )
    shared = next(e for e in evals if e.hypothesis.id == "shared_measurement_issue")
    assert shared.safety_capped is False
    assert "cross_measurement_invalid" in shared.supporting


# ── C. Sample sufficiency 三态 ───────────────────────────────────────────


def test_missing_ctr_sample_is_unknown_not_sufficient() -> None:
    # Case 3 (spec §57): CTR -25% with NO impressions fact → UNKNOWN →
    # weak evidence (missing sample is uncertainty, not sufficiency).
    evidence = build_evidence(per_platform={"meta": {"ctr_change_pct": -0.25}})
    assert sample_sufficiency({}, "ctr") == "unknown"
    assert evidence.signal_strength_by_platform["meta"].get("ctr_trend_down") == "weak"


def test_tiny_ctr_sample_weak_large_normal() -> None:
    # Cases 4/5 (spec §58/59).
    tiny = build_evidence(
        per_platform={"meta": {"ctr_change_pct": -0.25, "impressions": 150}}
    )
    assert tiny.signal_strength_by_platform["meta"]["ctr_trend_down"] == "weak"
    large = build_evidence(
        per_platform={
            "meta": {
                "ctr_change_pct": -0.25,
                "impressions": 100000,
                "clicks": 5000,
            }
        }
    )
    assert large.signal_strength_by_platform["meta"]["ctr_trend_down"] == "normal"


def test_cvr_large_traffic_tiny_conversions_is_weak() -> None:
    # Case 6 (spec §25): 2000 clicks + 2 conversions — the denominator is
    # large but the numerator is tiny; NOT strong evidence.
    evidence = build_evidence(
        per_platform={
            "meta": {
                "cvr_change_pct": -0.4,
                "clicks": 2000,
                "conversions": 2,
            }
        }
    )
    assert (
        sample_sufficiency({"clicks": 2000, "conversions": 2}, "cvr") == "insufficient"
    )
    assert evidence.signal_strength_by_platform["meta"]["cvr_trend_down"] == "weak"
    # Same movement with a real numerator is material.
    mature = build_evidence(
        per_platform={
            "meta": {
                "cvr_change_pct": -0.4,
                "clicks": 2000,
                "conversions": 200,
            }
        }
    )
    assert mature.signal_strength_by_platform["meta"]["cvr_trend_down"] == "normal"


def test_pay_rate_uses_base_population_and_count() -> None:
    # Cases 60/61 (spec §27): registrations 10 + payments 5→3 vs
    # registrations 1000 + payments 500→300 — never equal weight.
    tiny = build_evidence(
        per_platform={
            "tiktok": {
                "pay_rate_change_pct": -0.4,
                "registrations": 10,
                "payments": 3,
            }
        }
    )
    assert tiny.signal_strength_by_platform["tiktok"]["pay_rate_trend_down"] == "weak"
    large = build_evidence(
        per_platform={
            "tiktok": {
                "pay_rate_change_pct": -0.4,
                "registrations": 1000,
                "payments": 300,
            }
        }
    )
    assert (
        large.signal_strength_by_platform["tiktok"]["pay_rate_trend_down"] == "normal"
    )


# ── E. Scale eligibility 2.0 ─────────────────────────────────────────────


def _budget_constraint_evals():
    specs = build_hypothesis_set(platform_scope=("meta",), domain="bid_budget")
    evals = evaluate_hypotheses(
        specs,
        {"budget_utilization_high": True, "spend_hit_cap": True},
        measurement_state="stable",
        maturity_state="sufficient",
    )
    ranked = rank_hypotheses(evals)
    assert ranked[0].evaluation.hypothesis.id == "budget_constraint"
    return ranked


def test_barely_passing_cpa_defers_scale() -> None:
    # Case 7 (spec §46): CPA 49 vs target 50 + 2 conversions → thin
    # headroom + low volume → needs_more_evidence → wait, increase
    # forbidden.
    ranked = _budget_constraint_evals()
    result = converge(
        ranked,
        action_context={
            "cpa": 49.0,
            "target_cpa": 50.0,
            "conversions": 2,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    assert result.action_eligibility == "needs_more_evidence"
    assert result.decision == "wait"


def test_strong_scale_candidate_is_eligible() -> None:
    # Case 8 (spec §48): CPA 31 vs 50 + large volume + stable + mature +
    # no recent change → eligible → small staged increase.
    ranked = _budget_constraint_evals()
    result = converge(
        ranked,
        action_context={
            "cpa": 31.0,
            "target_cpa": 50.0,
            "conversions": 200,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    assert result.action_eligibility == "eligible"
    assert result.decision == "increase"


def test_good_cpa_but_creative_risk_blocks_scale() -> None:
    # Case 9 (spec §50): CPA strong + budget cap + creative_fatigue
    # supported → the supported rival blocks confident convergence — no
    # direct scale (investigate instead).
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(
        specs,
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "ctr_trend_down": True,
            "old_creative_worse": True,
            "frequency_trend_up": True,
            "cvr_trend_stable": True,
        },
        measurement_state="stable",
        maturity_state="sufficient",
    )
    ranked = rank_hypotheses(evals)
    result = converge(
        ranked,
        action_context={
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 200,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    assert result.converged is False
    assert result.decision == "investigate"
    assert result.material_alternatives


def test_bid_constraint_bad_efficiency_forbids_bid_increase() -> None:
    # Case 10 (spec §53): bid constrained + CPA far above KPI → bid
    # increase forbidden (not_eligible → hold).
    specs = build_hypothesis_set(platform_scope=("google_ads",), domain="bid_budget")
    evals = evaluate_hypotheses(
        specs,
        {"cpm_trend_up": True, "delivery_concentrated": True},
        measurement_state="stable",
        maturity_state="sufficient",
    )
    ranked = rank_hypotheses(evals)
    assert ranked[0].evaluation.hypothesis.id == "bid_constraint"
    result = converge(
        ranked,
        action_context={
            "cpa": 90.0,
            "target_cpa": 40.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    assert result.action_eligibility == "not_eligible"
    assert result.decision == "hold"


# ── Runtime E2E: tiny-sample scale → wait ────────────────────────────────


def test_runtime_tiny_sample_scale_waits(workspace) -> None:
    # Case 64 (spec §64): Google budget constrained + CPA good but only 2
    # conversions → wait, never increase.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 2,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_eligibility == "needs_more_evidence"
    assert result.eligibility_reason == "low_conversion_volume"
    assert result.recommended_action == "wait"
    run.finish()


def test_runtime_mature_scale_small_increase(workspace) -> None:
    # Case 65 (spec §65): mature, comfortable headroom, large volume →
    # small increase.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 31.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "impressions": 800000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_eligibility == "eligible"
    assert result.recommended_action == "increase"
    run.finish()
