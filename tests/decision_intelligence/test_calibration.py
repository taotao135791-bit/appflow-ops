"""v3.6.0 decision quality calibration tests.

Four calibration themes — the framework already reasons; these tests
calibrate whether the JUDGMENT resembles a mature media optimizer:

A. Measurement vs Real Funnel Problem — bad conversion performance is
   NOT measurement evidence; stable measurement contradicts instability.
B. Creative Fatigue vs Recent Operational Change — recent changes are
   confounders, not logical exclusions; fatigue can coexist.
C. Constraint Diagnosis vs Action Eligibility — budget/bid constraint
   never implies permission to scale; KPI/efficiency gates the action.
D. Signal Strength vs Sample Sufficiency — a -25% CTR on 150 impressions
   is weak evidence; the same movement on 100k impressions is normal.
   Metric-level sufficiency is NOT campaign maturity.
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
    scale_eligibility,
    thresholds_for,
)
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _converge_with(
    ranked, *, measurement="stable", maturity="sufficient", action_context=None
):
    return converge(
        ranked,
        measurement_state=measurement,
        maturity_state=maturity,
        action_context=action_context,
    )


# ── A. Measurement vs Real Funnel Problem ────────────────────────────────


def test_stable_measurement_weakens_measurement_instability() -> None:
    # Case 1: measurement stable + CTR stable + CVR -30% — funnel rises,
    # measurement_instability must NOT be top (it is contradicted).
    specs = build_hypothesis_set(platform_scope=("meta",))
    evidence = build_evidence(
        per_platform={
            "meta": {
                "cvr_change_pct": -0.3,
                "ctr_change_pct": 0.01,
                "measurement_state": "stable",
                "maturity_state": "sufficient",
            }
        },
        measurement_state="stable",
        maturity_state="sufficient",
    )
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("meta",),
        measurement_state="stable",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "stable"},
        maturity_by_platform={"meta": "sufficient"},
    )
    ranked = rank_hypotheses(evals)
    measurement = next(
        e
        for e in evals
        if e.hypothesis.id == "measurement_instability" and e.platform == "meta"
    )
    assert measurement.status == "weakened"
    assert "measurement_stable" in measurement.contradicting
    assert measurement.score < 0
    top = ranked[0].evaluation
    assert top.hypothesis.id in (
        "conversion_funnel_degradation",
        "post_click_friction",
        "audience_quality_shift",
    )
    assert top.hypothesis.id != "measurement_instability"


def test_cvr_down_alone_does_not_support_measurement() -> None:
    # CVR down is funnel evidence, never measurement evidence (supporting
    # signals no longer include cvr_trend_down / ctr_trend_stable).
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(
        specs,
        {"cvr_trend_down": True, "ctr_trend_stable": True},
        measurement_state="invalid",
        maturity_state="sufficient",
    )
    measurement = next(e for e in evals if e.hypothesis.id == "measurement_instability")
    assert "cvr_trend_down" not in measurement.supporting
    assert "ctr_trend_stable" not in measurement.supporting


def test_true_measurement_problem_stays_material() -> None:
    # Case 2: measurement invalid — investigation stays the top priority
    # (converge to investigate_measurement, not a creative action).
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(
        specs,
        {"measurement_invalid": True, "cvr_trend_down": True},
        measurement_state="invalid",
        maturity_state="sufficient",
    )
    ranked = rank_hypotheses(evals)
    result = _converge_with(ranked, measurement="invalid")
    assert result.decision == "investigate_measurement"
    assert result.safety_block == "measurement_invalid"


def test_shared_measurement_not_supported_by_downstream_decline() -> None:
    # Case 3 / spec §6-7: both platforms stable measurement + pay down →
    # shared_product_funnel_issue rises; shared_measurement_issue must NOT
    # be supported merely by the decline (no cross_measurement_invalid).
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evidence = build_evidence(
        per_platform={
            "meta": {
                "pay_rate_change_pct": -0.25,
                "measurement_state": "stable",
            },
            "google_ads": {
                "pay_rate_change_pct": -0.3,
                "measurement_state": "stable",
            },
        },
        measurement_state="stable",
        maturity_state="sufficient",
    )
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state="stable",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "stable", "google_ads": "stable"},
        maturity_by_platform={"meta": "sufficient", "google_ads": "sufficient"},
    )
    shared_measurement = next(
        e for e in evals if e.hypothesis.id == "shared_measurement_issue"
    )
    funnel = next(e for e in evals if e.hypothesis.id == "shared_product_funnel_issue")
    assert "cross_pay_rate_drop" not in shared_measurement.supporting
    assert shared_measurement.status != "supported"
    assert shared_measurement.status == "weakened"  # stable contradicts it
    assert funnel.status in ("supported", "unverified")


def test_shared_measurement_requires_real_anomaly() -> None:
    # >= 2 platforms invalid (cross_measurement_invalid) is the real
    # shared measurement evidence — and it stays supported.
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
            "google_ads": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
        },
        measurement_state="invalid",
        maturity_state="sufficient",
    )
    assert evidence.shared_signals.get("cross_measurement_invalid") is True
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state="invalid",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "invalid"},
        maturity_by_platform={"meta": "unknown", "google_ads": "unknown"},
    )
    shared_measurement = next(
        e for e in evals if e.hypothesis.id == "shared_measurement_issue"
    )
    assert "cross_measurement_invalid" in shared_measurement.supporting


# ── B. Creative Fatigue vs Recent Operational Change ─────────────────────


def _fatigue_evals(extra_signals: dict[str, bool], measurement="stable"):
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    signals = {
        "ctr_trend_down": True,
        "old_creative_worse": True,
        "frequency_trend_up": True,
        "cpm_trend_stable": True,
        "cvr_trend_stable": True,
        **extra_signals,
    }
    evals = evaluate_hypotheses(
        specs, signals, measurement_state=measurement, maturity_state="sufficient"
    )
    return rank_hypotheses(evals)


def test_fatigue_and_recent_change_can_coexist() -> None:
    # Case 4 (spec §12/§38A): real fatigue evidence + recent budget +20% —
    # fatigue stays supported AND recent_change_interference is supported;
    # convergence is investigate (no reckless full swap).
    ranked = _fatigue_evals({"recent_budget_change": True})
    supported = {
        r.evaluation.hypothesis.id for r in ranked if r.evaluation.status == "supported"
    }
    assert "creative_fatigue" in supported
    assert "recent_budget_bid_interference" in supported
    result = _converge_with(ranked)
    assert result.converged is False
    assert result.decision == "investigate"
    assert result.material_alternatives


def test_recent_change_no_longer_hard_excludes_fatigue() -> None:
    # spec §9-10: recent change is a confounder, never a logical exclusion.
    ranked = _fatigue_evals({"recent_budget_change": True})
    fatigue = next(
        r.evaluation for r in ranked if r.evaluation.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status != "excluded"
    assert fatigue.score == 6  # 8 support - 2 confounder


def test_delivery_change_outranks_fatigue_when_clear() -> None:
    # Case 5 (spec §38B): recent +40% + CPM up + delivery mix shifted +
    # no creative-level pattern → change/delivery hypotheses outrank
    # fatigue (fatigue has no old-creative divergence evidence).
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {
        "recent_budget_change": True,
        "ctr_trend_down": True,
        "cpm_trend_up": True,
        "delivery_mix_shifted": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    ranked = rank_hypotheses(evals)
    top = ranked[0].evaluation
    assert top.hypothesis.id in (
        "recent_budget_bid_interference",
        "delivery_mix_shift",
    )
    fatigue = next(
        r.evaluation for r in ranked if r.evaluation.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status != "supported"


# ── C. Constraint Diagnosis vs Action Eligibility ────────────────────────


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


def test_budget_constraint_bad_cpa_forbids_increase() -> None:
    # Case 6: budget hit cap + CPA 110 vs target 50 — constraint is a real
    # DIAGNOSIS, but increase is NOT eligible; action downgrades to hold.
    ranked = _budget_constraint_evals()
    result = _converge_with(
        ranked,
        action_context={
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 110.0,
            "target_cpa": 50.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_eligibility == "not_eligible"
    assert result.decision == "hold"
    assert result.converged is True  # diagnosis converged; action gated


def test_budget_constraint_good_cpa_allows_small_increase() -> None:
    # Case 7: budget hit cap + CPA 32 vs target 50 + measurement stable +
    # maturity sufficient + outcome volume + no recent change → small
    # increase eligible.
    ranked = _budget_constraint_evals()
    result = _converge_with(
        ranked,
        action_context={
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 32.0,
            "target_cpa": 50.0,
            "conversions": 200,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    assert result.action_eligibility == "eligible"
    assert result.decision == "increase"


def test_budget_constraint_recent_change_forces_wait() -> None:
    # Case 8: CPA good but budget changed recently — wait, never another
    # immediate increase (confounded scale decision).
    ranked = _budget_constraint_evals()
    result = _converge_with(
        ranked,
        action_context={
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 32.0,
            "target_cpa": 50.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
            "recent_budget_change": True,
        },
    )
    assert result.action_eligibility == "not_eligible"
    assert result.decision == "hold"


def test_budget_constraint_missing_kpi_is_conservative() -> None:
    # No KPI context → needs_more_evidence → wait (never a blind increase).
    ranked = _budget_constraint_evals()
    result = _converge_with(ranked, action_context={"spend_hit_cap": True})
    assert result.action_eligibility == "needs_more_evidence"
    assert result.decision == "wait"


def test_invalid_measurement_blocks_scale() -> None:
    ranked = _budget_constraint_evals()
    result = _converge_with(
        ranked,
        action_context={
            "spend_hit_cap": True,
            "cpa": 32.0,
            "target_cpa": 50.0,
            "measurement_state": "invalid",
        },
    )
    assert result.action_eligibility == "not_eligible"
    assert result.decision == "hold"


def test_scale_eligibility_helper() -> None:
    # v3.6.1: (state, reason) tuple; KPI pass is necessary, not sufficient.
    # v3.6.2: scale requires POSITIVE safety (stable/sufficient), a known
    # primary KPI, and KPI-matched outcome volume — missing any of them
    # defers scale.
    stable_mature = {
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    assert scale_eligibility(
        {**stable_mature, "cpa": 30.0, "target_cpa": 50.0, "conversions": 100}
    ) == ("eligible", None)
    assert scale_eligibility(
        {**stable_mature, "cpa": 110.0, "target_cpa": 50.0, "conversions": 100}
    ) == ("not_eligible", None)
    assert scale_eligibility(
        {**stable_mature, "cpi": 2.0, "target_cpi": 1.5, "installs": 100}
    ) == ("not_eligible", None)
    assert scale_eligibility(
        {
            **stable_mature,
            "roas": 3.0,
            "target_roas": 2.0,
            "purchases": 50,
        }
    ) == ("eligible", None)
    assert scale_eligibility({"measurement_state": "invalid"}) == (
        "not_eligible",
        "measurement_unreliable",
    )
    assert scale_eligibility(
        {"measurement_state": "stable", "maturity_state": "insufficient"}
    ) == ("not_eligible", "maturity_insufficient")
    # v3.6.2: unknown measurement/maturity defers scale (positive evidence
    # required — investigation may continue, scale may not).
    assert scale_eligibility(
        {"measurement_state": "unknown", "cpa": 30.0, "target_cpa": 50.0}
    ) == ("needs_more_evidence", "measurement_unknown")
    assert scale_eligibility(
        {
            "measurement_state": "stable",
            "maturity_state": "unknown",
            "cpa": 30.0,
            "target_cpa": 50.0,
        }
    ) == ("needs_more_evidence", "maturity_unknown")
    assert scale_eligibility(
        {
            "recent_budget_change": True,
            "cpa": 10.0,
            "target_cpa": 50.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        }
    ) == ("not_eligible", "recent_change")
    assert scale_eligibility({}) == ("needs_more_evidence", "measurement_unknown")
    # v3.6.1: thin headroom (49 vs 50) defers scale.
    assert scale_eligibility(
        {**stable_mature, "cpa": 49.0, "target_cpa": 50.0, "conversions": 100}
    ) == ("needs_more_evidence", "thin_kpi_headroom")
    # v3.6.1: good CPA but tiny outcome volume defers scale.
    assert scale_eligibility(
        {**stable_mature, "cpa": 30.0, "target_cpa": 50.0, "conversions": 2}
    ) == ("needs_more_evidence", "low_conversion_volume")
    # v3.6.2: good CPA but NO outcome volume defers scale — impressions
    # can prove a CTR sample, never a stable CPA (missing volume reason).
    assert scale_eligibility(
        {**stable_mature, "cpa": 30.0, "target_cpa": 50.0, "impressions": 150}
    ) == ("needs_more_evidence", "missing_outcome_volume")
    assert scale_eligibility(
        {**stable_mature, "cpa": 30.0, "target_cpa": 50.0, "impressions": 100000}
    ) == ("needs_more_evidence", "missing_outcome_volume")


# ── D. Signal Strength vs Sample Sufficiency ─────────────────────────────


def test_tiny_ctr_sample_is_weak_evidence() -> None:
    # Case 9: CTR -25% on 150 impressions → ctr_trend_down is WEAK → no
    # confident fatigue convergence.
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    evidence = build_evidence(
        per_platform={"meta": {"ctr_change_pct": -0.25, "impressions": 150}}
    )
    assert evidence.signal_strength_by_platform["meta"].get("ctr_trend_down") == "weak"
    evals = evaluate_hypotheses(
        specs, evidence, platform_scope=("meta",), measurement_state="stable"
    )
    ranked = rank_hypotheses(evals)
    fatigue = next(
        r.evaluation for r in ranked if r.evaluation.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status != "supported"
    assert fatigue.score <= 3  # weak evidence cannot carry fatigue


def test_mature_ctr_sample_is_normal_evidence() -> None:
    # Case 10: same -25% on 100k impressions → normal evidence → fatigue
    # can be supported.
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    evidence = build_evidence(
        per_platform={
            "meta": {
                "ctr_change_pct": -0.25,
                "impressions": 100_000,
                "clicks": 5000,
                "old_creative_worse": True,
                "frequency_trend": "up",
            }
        }
    )
    assert (
        evidence.signal_strength_by_platform["meta"].get("ctr_trend_down") == "normal"
    )
    evals = evaluate_hypotheses(
        specs, evidence, platform_scope=("meta",), measurement_state="stable"
    )
    ranked = rank_hypotheses(evals)
    fatigue = next(
        r.evaluation for r in ranked if r.evaluation.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status == "supported"


def test_tiny_pay_sample_is_inconclusive() -> None:
    # Case 11: pay rate -40% with pay count 5 → 3 → weak downstream
    # evidence; pay funnel must NOT be confidently supported.
    specs = build_hypothesis_set(platform_scope=("tiktok",), domain="funnel")
    evidence = build_evidence(
        per_platform={
            "tiktok": {
                "pay_rate_change_pct": -0.4,
                "payments": 3,
                "install_rate_trend": "stable",
            }
        }
    )
    assert (
        evidence.signal_strength_by_platform["tiktok"].get("pay_rate_trend_down")
        == "weak"
    )
    evals = evaluate_hypotheses(
        specs, evidence, platform_scope=("tiktok",), measurement_state="stable"
    )
    pay_funnel = next(e for e in evals if e.hypothesis.id == "pay_funnel_degradation")
    assert pay_funnel.status != "supported"


def test_large_pay_sample_is_material() -> None:
    # Case 12: same -40% with pay count 500 → 300 → normal downstream
    # evidence → pay funnel can be supported.
    specs = build_hypothesis_set(platform_scope=("tiktok",), domain="funnel")
    evidence = build_evidence(
        per_platform={
            "tiktok": {
                "pay_rate_change_pct": -0.4,
                "registrations": 1000,
                "payments": 300,
                # v3.6.2: install_rate_trend is sample-calibrated too —
                # a real campaign brings clicks AND installs (numerator).
                "clicks": 5000,
                "installs": 300,
                "install_rate_trend": "stable",
            }
        }
    )
    assert (
        evidence.signal_strength_by_platform["tiktok"].get("pay_rate_trend_down")
        == "normal"
    )
    evals = evaluate_hypotheses(
        specs, evidence, platform_scope=("tiktok",), measurement_state="stable"
    )
    pay_funnel = next(e for e in evals if e.hypothesis.id == "pay_funnel_degradation")
    assert pay_funnel.status == "supported"


def test_sample_sufficiency_is_metric_level_not_maturity() -> None:
    # spec §32: campaign maturity sufficient does NOT make every metric
    # comparison sufficient — the tiny-sample gate applies regardless.
    # v3.6.1: three states; missing sample is UNKNOWN, never sufficient.
    assert sample_sufficiency({"impressions": 150}, "ctr") == "insufficient"
    assert sample_sufficiency({"impressions": 100_000}, "ctr") == "unknown"  # no clicks
    assert (
        sample_sufficiency({"impressions": 100_000, "clicks": 5000}, "ctr")
        == "sufficient"
    )
    assert sample_sufficiency({"payments": 3}, "pay_rate") == "unknown"  # no base
    assert sample_sufficiency({"registrations": 10, "payments": 3}, "pay_rate") == (
        "insufficient"
    )
    assert (
        sample_sufficiency({"registrations": 1000, "payments": 300}, "pay_rate")
        == "sufficient"
    )
    assert sample_sufficiency({}, "ctr") == "unknown"


# ── E. Metric-specific calibration ───────────────────────────────────────


def test_metric_specific_thresholds_are_conservative() -> None:
    # spec §33-35: downstream rates are stricter than upper-funnel; the
    # first version prefers fewer false positives.
    assert thresholds_for("ctr") == (0.05, 0.10)
    assert thresholds_for("cvr") == (0.05, 0.12)
    assert thresholds_for("pay_rate") == (0.05, 0.15)
    assert thresholds_for("install_rate") == (0.05, 0.15)
    assert thresholds_for("no_such_family") == (0.05, 0.10)  # fallback
    # A -11% CVR movement is below the calibrated material band.
    evidence = build_evidence(
        per_platform={"meta": {"cvr_change_pct": -0.11, "clicks": 5000}}
    )
    assert "cvr_trend_down" not in evidence.signals


# ── Runtime E2E: calibration through the public path ─────────────────────


def test_runtime_e2e_stable_measurement_funnel_not_tracking(workspace) -> None:
    from appflow_ops.runtime import PlatformOperationalRun

    run = PlatformOperationalRun(workspace)
    run.begin(request_text="点击正常为什么转化掉？", platform_scope=("meta",))
    run.record_observation(
        {
            "cvr_change_pct": -0.3,
            "ctr_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis != "measurement_instability"
    assert result.top_hypothesis in (
        "conversion_funnel_degradation",
        "post_click_friction",
        "audience_quality_shift",
    )
    assert result.safety_block is None
    run.finish()


def test_runtime_e2e_budget_cap_bad_cpa_holds(workspace) -> None:
    from appflow_ops.runtime import PlatformOperationalRun

    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 110.0,
            "target_cpa": 50.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_eligibility == "not_eligible"
    assert result.recommended_action == "hold"
    run.finish()


def test_runtime_e2e_budget_cap_good_cpa_scales(workspace) -> None:
    from appflow_ops.runtime import PlatformOperationalRun

    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 32.0,
            "target_cpa": 50.0,
            "conversions": 200,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_eligibility == "eligible"
    assert result.recommended_action == "increase"
    run.finish()
