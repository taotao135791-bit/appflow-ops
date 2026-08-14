"""v3.6.2 action confidence & KPI alignment tests.

An action must be supported by the correct KPI, correct outcome evidence,
correct platform scope, and sufficient confidence:

A. missing outcome volume blocks scale — impressions can prove a CTR
   sample, never a stable CPA;
B. scale requires POSITIVE safety (measurement==stable, maturity==
   sufficient) — unknown defers scale even though investigation may
   continue;
C. the PRIMARY KPI drives target/actual comparison and outcome volume —
   multiple targets without a declaration are ambiguous, never silently
   resolved by a hardcoded CPA-first precedence;
D. KPI-aligned outcome volume — pay CPA never borrows installs;
E. scope-aware rivals — another platform's independent issue is a
   parallel issue, not a competing explanation;
F. trend-representation invariance — explicit trend strings go through
   the same sample calibration as numeric change_pct.
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
    evaluate_hypotheses,
    hypothesis_by_id,
    is_material_rival,
    resolve_kpi_outcome_volume,
    resolve_primary_kpi_context,
    scale_eligibility,
)
from appflow_ops.decision_intelligence.evaluator import (
    HypothesisEvaluation,
)
from appflow_ops.runtime import PlatformOperationalRun
from appflow_ops.uac.workspace import initialize_workspace

STABLE_MATURE = {
    "measurement_state": "stable",
    "maturity_state": "sufficient",
}


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _eval(
    hypothesis_id: str,
    platform: str = "google_ads",
) -> HypothesisEvaluation:
    """A minimal supported HypothesisEvaluation for rival classification."""
    spec = hypothesis_by_id(hypothesis_id)
    return HypothesisEvaluation(
        hypothesis=spec,
        status="supported",
        score=6,
        supporting=(),
        contradicting=(),
        missing=(),
        rationale=(),
        platform=platform,
    )


# ── PART A: Missing outcome volume blocks scale ──────────────────────────


def test_missing_volume_never_eligible_even_with_large_impressions() -> None:
    # Case 1: CPA 30/50 + stable + mature + NO outcome count → defer.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "impressions": 100000,
        }
    ) == ("needs_more_evidence", "missing_outcome_volume")


def test_volume_present_eligible() -> None:
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 100,
        }
    ) == ("eligible", None)


# ── PART B: Scale requires positive safety ───────────────────────────────


def test_measurement_unknown_defers_scale() -> None:
    # Case 2: CPA 30/50 + 200 conversions + measurement unknown → defer.
    assert scale_eligibility(
        {
            "measurement_state": "unknown",
            "maturity_state": "sufficient",
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 200,
        }
    ) == ("needs_more_evidence", "measurement_unknown")


def test_maturity_unknown_defers_scale() -> None:
    # Case 3.
    assert scale_eligibility(
        {
            "measurement_state": "stable",
            "maturity_state": "unknown",
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 200,
        }
    ) == ("needs_more_evidence", "maturity_unknown")


def test_unknown_safety_still_allows_diagnosis() -> None:
    # Unknown safety may continue INVESTIGATION — only scale is blocked.
    specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
    evals = evaluate_hypotheses(
        specs,
        {
            "ctr_trend_down": True,
            "old_creative_worse": True,
            "frequency_trend_up": True,
            "cvr_trend_stable": True,
            "cpm_trend_stable": True,
        },
        measurement_state="unknown",
        maturity_state="unknown",
    )
    fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
    assert fatigue.status != "excluded"


# ── PART C: Primary KPI ──────────────────────────────────────────────────


def test_single_target_implies_primary_kpi() -> None:
    # Single target_cpa → CPA implied (backward compatible).
    context = resolve_primary_kpi_context(
        {**STABLE_MATURE, "cpa": 30.0, "target_cpa": 50.0, "conversions": 100}
    )
    assert context is not None
    assert context["kpi_type"] == "cpa"
    assert context["headroom"] == "strong_headroom"
    assert context["outcome_volume"] == 100


def test_multiple_targets_without_primary_is_ambiguous() -> None:
    # Case 4: target CPI + target pay CPA, no declaration → ambiguous.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "target_cpi": 5.0,
            "target_pay_cpa": 100.0,
            "cpi": 3.0,
            "pay_cpa": 140.0,
        }
    ) == ("needs_more_evidence", "ambiguous_primary_kpi")


def test_explicit_pay_cpa_kpi_blocks_scale_on_bad_pay() -> None:
    # Case 5: primary_kpi=pay_cpa + pay CPA 140 > 100 → not eligible,
    # even though CPI 3/5 looks great.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 140.0,
            "payments": 200,
            "cpi": 3.0,
            "target_cpi": 5.0,
        }
    ) == ("not_eligible", None)


def test_cpi_primary_scales_on_installs() -> None:
    # Case 6: primary_kpi=cpi → installs are the correct outcome volume.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "cpi",
            "target_cpi": 5.0,
            "cpi": 3.0,
            "installs": 500,
        }
    ) == ("eligible", None)


def test_optimization_goal_legacy_read() -> None:
    # optimization_goal is a legacy alias for the primary KPI declaration.
    context = resolve_primary_kpi_context(
        {
            "optimization_goal": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
        }
    )
    assert context is not None
    assert context["kpi_type"] == "pay_cpa"
    assert context["headroom"] == "strong_headroom"


# ── PART D: KPI-aligned outcome volume ───────────────────────────────────


def test_pay_kpi_never_borrows_installs() -> None:
    # Case 7: pay_cpa KPI + payments missing + 1000 installs → missing
    # outcome volume, never sufficient.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "installs": 1000,
        }
    ) == ("needs_more_evidence", "missing_outcome_volume")


def test_kpi_outcome_mapping() -> None:
    facts = {"installs": 10, "registrations": 20, "payments": 30, "purchases": 40}
    assert resolve_kpi_outcome_volume("cpi", facts) == 10
    assert resolve_kpi_outcome_volume("registration_cpa", facts) == 20
    assert resolve_kpi_outcome_volume("pay_cpa", facts) == 30
    assert resolve_kpi_outcome_volume("purchase_cpa", facts) == 40
    assert resolve_kpi_outcome_volume("cpa", facts) is None  # conversions missing
    assert resolve_kpi_outcome_volume("roas", facts) == 40  # purchases first
    assert resolve_kpi_outcome_volume("roas", {"conversions": 9}) == 9


# ── PART E: Scope-aware rivals & parallel issues ─────────────────────────


def test_same_platform_rival_is_material() -> None:
    # Case 9: budget_constraint@google vs auction_pressure@google.
    top = _eval("budget_constraint")
    rival = _eval("auction_pressure")
    assert is_material_rival(top, rival) is True


def test_different_platform_issue_is_parallel() -> None:
    # Case 8: budget_constraint@google vs creative_fatigue@meta.
    top = _eval("budget_constraint", platform="google_ads")
    rival = _eval("creative_fatigue", platform="meta")
    assert is_material_rival(top, rival) is False


def test_shared_candidate_is_material_for_platform_top() -> None:
    # Case 10: a shared issue can undermine a platform action.
    top = _eval("budget_constraint", platform="google_ads")
    shared = _eval("shared_product_funnel_issue")
    assert is_material_rival(top, shared) is True


def test_google_scale_survives_meta_fatigue(workspace) -> None:
    # Case 8 E2E: Google scale remains eligible; Meta fatigue is recorded
    # as a parallel issue (both supported at the same score — id order
    # picks budget_constraint@google as the selected diagnosis).
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "delivery_concentrated": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    run.record_observation(
        {
            "ctr_change_pct": -0.25,
            "frequency_change_pct": 0.18,
            "impressions": 100000,
            "clicks": 5000,
            "old_creative_worse": True,
            "cvr_trend_stable": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "budget_constraint"
    assert result.top_platform == "google_ads"
    assert result.action_eligibility == "eligible"
    assert result.recommended_action == "increase"
    assert "creative_fatigue" in result.parallel_issues
    run.finish()


def test_google_budget_google_rival_still_blocks(workspace) -> None:
    # Case 9 E2E: Google budget/bid constraint + auction pressure BOTH
    # supported on the SAME platform → material rival → investigate,
    # never a direct scale.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "delivery_concentrated": True,
            "cpm_change_pct": 0.35,
            "ctr_change_pct": 0.01,
            "impressions": 100000,
            "clicks": 5000,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis in ("bid_constraint", "budget_constraint")
    # Same-platform supported candidates are REAL rivals: no confident
    # scale even with a perfect KPI.
    assert result.convergence_status == "investigate"
    assert result.recommended_action == "investigate"
    assert len(result.material_alternatives) >= 2
    assert result.action_eligibility is None  # not a scale decision
    run.finish()


# ── PART F: Trend-representation invariance ──────────────────────────────


def test_explicit_trend_uses_same_sample_calibration() -> None:
    # Case 11: ctr_trend="down" + 150 impressions is WEAK — identical to
    # the numeric encoding.
    explicit = build_evidence(
        per_platform={"meta": {"ctr_trend": "down", "impressions": 150}}
    )
    numeric = build_evidence(
        per_platform={"meta": {"ctr_change_pct": -0.25, "impressions": 150}}
    )
    assert (
        explicit.signal_strength_by_platform["meta"]["ctr_trend_down"]
        == numeric.signal_strength_by_platform["meta"]["ctr_trend_down"]
        == "weak"
    )


def test_explicit_trend_without_sample_is_weak() -> None:
    # Case 12: ctr_trend="down" with NO sample facts → weak.
    evidence = build_evidence(per_platform={"meta": {"ctr_trend": "down"}})
    assert evidence.signal_strength_by_platform["meta"]["ctr_trend_down"] == "weak"


def test_explicit_trend_large_sample_normal() -> None:
    explicit = build_evidence(
        per_platform={
            "meta": {
                "ctr_trend": "down",
                "impressions": 100000,
                "clicks": 5000,
            }
        }
    )
    numeric = build_evidence(
        per_platform={
            "meta": {
                "ctr_change_pct": -0.25,
                "impressions": 100000,
                "clicks": 5000,
            }
        }
    )
    assert (
        explicit.signal_strength_by_platform["meta"]["ctr_trend_down"]
        == numeric.signal_strength_by_platform["meta"]["ctr_trend_down"]
        == "normal"
    )


def test_trend_encodings_converge_to_same_action() -> None:
    # Both encodings (tiny sample) must NOT support confident fatigue.
    def _status(signals: dict[str, object]) -> str:
        specs = build_hypothesis_set(platform_scope=("meta",), domain="creative")
        evidence = build_evidence(per_platform={"meta": signals})
        evals = evaluate_hypotheses(specs, evidence, platform_scope=("meta",))
        fatigue = next(e for e in evals if e.hypothesis.id == "creative_fatigue")
        return fatigue.status

    explicit = _status(
        {
            "ctr_trend": "down",
            "old_creative_worse": True,
            "frequency_trend": "up",
            "cvr_trend": "stable",
            "impressions": 150,
        }
    )
    numeric = _status(
        {
            "ctr_change_pct": -0.25,
            "old_creative_worse": True,
            "frequency_change_pct": 0.18,
            "cvr_change_pct": 0.01,
            "impressions": 150,
        }
    )
    assert explicit == numeric
    assert explicit != "supported"


# ── PART K: KPI-aware scale cases ────────────────────────────────────────


def test_pay_cpa_strong_eligible() -> None:
    # §58: pay CPA 70/100 + 150 payments → eligible.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
        }
    ) == ("eligible", None)


def test_pay_cpa_low_volume_waits() -> None:
    # §59: pay CPA 70/100 + 3 payments → wait.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 3,
        }
    ) == ("needs_more_evidence", "low_conversion_volume")


def test_roas_strong_with_purchases_eligible() -> None:
    # §61: ROAS 2.3/1.5 + sufficient purchases → eligible.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "roas",
            "target_roas": 1.5,
            "roas": 2.3,
            "purchases": 80,
        }
    ) == ("eligible", None)


def test_roas_missing_outcome_waits() -> None:
    # §62: ROAS 3.0 but no purchase/conversion evidence → wait.
    assert scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "roas",
            "target_roas": 1.5,
            "roas": 3.0,
        }
    ) == ("needs_more_evidence", "missing_outcome_volume")


# ── Runtime-native E2E (PART M) ──────────────────────────────────────────


def test_e2e_pay_kpi_good_but_payments_missing(workspace) -> None:
    # E2E 1: pay KPI good, payments missing → wait.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.action_eligibility == "needs_more_evidence"
    assert result.eligibility_reason == "missing_outcome_volume"
    assert result.recommended_action == "wait"
    run.finish()


def test_e2e_multiple_kpi_ambiguous_no_increase(workspace) -> None:
    # E2E 3: CPI good + pay CPA bad + no primary KPI → no increase.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "target_cpi": 5.0,
            "cpi": 3.0,
            "target_pay_cpa": 100.0,
            "pay_cpa": 140.0,
            "installs": 500,
            "payments": 200,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.action_eligibility == "needs_more_evidence"
    assert result.eligibility_reason == "ambiguous_primary_kpi"
    assert result.recommended_action == "wait"
    run.finish()


def test_e2e_explicit_trend_tiny_sample_weak(workspace) -> None:
    # E2E 4: explicit trend + tiny sample → weak evidence → fatigue is
    # NOT supported (a small dip never justifies a swap).
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="素材还能跑吗？", platform_scope=("meta",))
    run.record_observation(
        {
            "ctr_trend": "down",
            "old_creative_worse": True,
            "frequency_trend": "up",
            "impressions": 150,
            "measurement_state": "stable",
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
    run.finish()
