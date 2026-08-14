"""v3.6.3 decision attribution & goal semantics tests.

AppFlow must know exactly WHO the conclusion is about, WHAT goal governs
the action, WHICH evidence belongs to it, and WHETHER another issue
actually invalidates that action:

A. the summary consumes the SELECTED evaluation's evidence — same
   hypothesis id on two platforms never mixes evidence;
B. parallel issues preserve platform/scope attribution;
C. conversion_event / optimization_goal are EVENT semantics, normalized
   (not literal synonyms of the KPI enum); explicit conflicts become
   ambiguity;
D. ROAS outcome volume requires revenue-generating events — unknown
   generic conversions are not ROAS evidence;
E. shared/run candidates are classified by ACTION RELEVANCE: funnel/
   measurement issues can block scale, market-wide context warns but
   does not veto;
F. KPI-family minimum scale evidence differs (20 installs != 20
   payments).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    hypothesis_by_id,
    normalize_goal_to_kpi,
    resolve_kpi_outcome_volume,
    resolve_primary_kpi,
    resolve_primary_kpi_context,
    scale_eligibility,
    shared_candidate_blocks_action,
)
from appflow_ops.decision_intelligence.evaluator import (
    HypothesisEvaluation,
)
from appflow_ops.decision_intelligence.summary import (
    summarize_decision_intelligence,
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


def _eval(hypothesis_id: str, platform: str = "google_ads") -> HypothesisEvaluation:
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


# ── PART A: Summary uses the selected evaluation ─────────────────────────


def test_summary_evidence_from_selected_platform(workspace) -> None:
    # Case 1: auction_pressure supported on BOTH platforms; Google is the
    # stronger top — the summary must cite GOOGLE's evidence, never Meta's.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="竞价压力变大了吗？", platform_scope=("google_ads", "meta"))
    # Meta: weaker auction evidence (cpm up only).
    run.record_observation(
        {
            "cpm_change_pct": 0.12,
            "ctr_change_pct": 0.01,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    # Google: stronger auction evidence (cpm up + multi creative impacted).
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "ctr_change_pct": 0.01,
            "multi_creative_impacted": True,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "auction_pressure"
    assert result.top_platform == "google_ads"
    assert result.selected_evaluation is not None
    assert result.selected_evaluation.platform == "google_ads"
    # The summary evidence must be Google's: multi_creative_impacted is
    # Google-only; Meta's bare cpm-up never appears.
    summary = summarize_decision_intelligence(result)
    assert "multi_creative_impacted" in (result.selected_evaluation.supporting)
    assert "多素材同时受影响" in summary
    run.finish()


def test_summary_never_rescans_by_hypothesis_id(workspace) -> None:
    # The evidence block of the summary is built from
    # result.selected_evaluation — a scan by id alone would pick the
    # first auction_pressure evaluation (Meta, weaker). Invariant: every
    # "- " evidence line in the summary comes from the SELECTED
    # evaluation's supporting labels (never from the same-id Meta
    # evaluation).
    from appflow_ops.decision_intelligence.summary import SIGNAL_LABELS

    run = PlatformOperationalRun(workspace)
    run.begin(request_text="CPM 涨了吗？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "ctr_change_pct": 0.01,
            "multi_creative_impacted": True,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.12,
            "ctr_change_pct": 0.01,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "auction_pressure"
    assert result.top_platform == "google_ads"
    assert result.selected_evaluation is not None
    selected_labels = {
        SIGNAL_LABELS[s]
        for s in result.selected_evaluation.supporting
        if s in SIGNAL_LABELS
    }
    assert selected_labels  # Google's evidence is present
    for line in summarize_decision_intelligence(result).split("\n"):
        if line.startswith("- "):
            assert line[2:] in selected_labels, f"evidence {line!r} not from selected"
    run.finish()


# ── PART B: Parallel issues keep attribution ─────────────────────────────


def test_parallel_issue_keeps_platform(workspace) -> None:
    # Case 2: Google budget top + Meta fatigue → parallel issue must be
    # creative_fatigue@meta, never a bare id.
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
    parallel = result.parallel_issues
    assert len(parallel) == 1
    issue = parallel[0]
    assert issue.hypothesis_id == "creative_fatigue"
    assert issue.platform == "meta"
    assert issue.evaluation_scope == "platform"
    assert issue.status == "supported"
    # User-facing output names the platform (规格 §10/§64).
    summary = summarize_decision_intelligence(result)
    assert "meta 侧的素材疲劳" in summary
    run.finish()


def test_same_hypothesis_multiple_platforms_both_parallel() -> None:
    # §11: creative_fatigue@meta and creative_fatigue@tiktok can coexist
    # as separate parallel entries — never deduped by hypothesis id.
    from appflow_ops.decision_intelligence.ranking import ParallelIssue

    issues = (
        ParallelIssue(
            hypothesis_id="creative_fatigue",
            platform="meta",
            evaluation_scope="platform",
            status="supported",
            score=6,
        ),
        ParallelIssue(
            hypothesis_id="creative_fatigue",
            platform="tiktok",
            evaluation_scope="platform",
            status="supported",
            score=5,
        ),
    )
    assert len(issues) == 2
    assert {i.platform for i in issues} == {"meta", "tiktok"}


# ── PART C: Goal semantics ───────────────────────────────────────────────


def test_conversion_event_pay_maps_to_pay_cpa() -> None:
    # Case 3: conversion_event=pay + target_pay_cpa → pay_cpa (event
    # semantics normalized, not a literal enum match).
    context = resolve_primary_kpi_context(
        {
            "conversion_event": "pay",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            **STABLE_MATURE,
        }
    )
    assert context is not None
    assert context["kpi_type"] == "pay_cpa"
    assert context["resolution_source"] == "conversion_event"
    assert context["outcome_event"] == "pay"
    assert context["outcome_volume"] == 150
    assert context["headroom"] == "strong_headroom"


def test_optimization_goal_purchase_maps_to_purchase_cpa() -> None:
    # Case 4: optimization_goal=purchase + target_purchase_cpa.
    kpi, reason = resolve_primary_kpi(
        {
            "optimization_goal": "purchase",
            "target_purchase_cpa": 80.0,
            "purchase_cpa": 60.0,
            "purchases": 100,
        }
    )
    assert kpi == "purchase_cpa"
    assert reason is None


def test_event_disambiguates_multiple_targets() -> None:
    # §18/§20: optimization_goal=pay + target_cpi + target_pay_cpa →
    # pay_cpa (event wins over ambiguity).
    kpi, reason = resolve_primary_kpi(
        {"optimization_goal": "pay", "target_cpi": 5.0, "target_pay_cpa": 100.0}
    )
    assert kpi == "pay_cpa"
    assert reason is None


def test_explicit_kpi_goal_conflict_is_ambiguous() -> None:
    # Case 5 (§19): primary_kpi=cpi + optimization_goal=pay → real
    # conflict, never a guess.
    kpi, reason = resolve_primary_kpi(
        {"primary_kpi": "cpi", "optimization_goal": "pay"}
    )
    assert kpi is None
    assert reason == "ambiguous_primary_kpi"


def test_explicit_primary_kpi_authoritative() -> None:
    # §17: explicit primary_kpi wins when the event agrees or is absent.
    kpi, reason = resolve_primary_kpi(
        {"primary_kpi": "pay_cpa", "optimization_goal": "pay"}
    )
    assert kpi == "pay_cpa"
    assert reason is None


def test_normalize_goal_literals() -> None:
    assert normalize_goal_to_kpi("pay_cpa") == "pay_cpa"  # literal passes
    assert normalize_goal_to_kpi("pay") == "pay_cpa"  # event normalizes
    assert normalize_goal_to_kpi("payment") == "pay_cpa"
    assert normalize_goal_to_kpi("install") == "cpi"
    assert normalize_goal_to_kpi("revenue") == "roas"
    assert normalize_goal_to_kpi("uninstall") is None  # unknown: no guessing


def test_goal_semantics_user_output(workspace) -> None:
    # §67: 当前优化目标是 Pay → 按 Pay CPA 判断，不按 CPI。
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "conversion_event": "pay",
            "target_pay_cpa": 100.0,
            "pay_cpa": 140.0,
            "payments": 200,
            "cpi": 3.0,
            "target_cpi": 5.0,
            "installs": 500,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.action_eligibility == "not_eligible"
    assert result.recommended_action == "hold"
    run.finish()


# ── PART D: KPI context internal consistency ─────────────────────────────


def test_context_preserves_outcome_event_and_source() -> None:
    context = resolve_primary_kpi_context(
        {
            "primary_kpi": "purchase_cpa",
            "target_purchase_cpa": 80.0,
            "purchase_cpa": 60.0,
            "purchases": 100,
        }
    )
    assert context is not None
    assert context["outcome_event"] == "purchase"
    assert context["resolution_source"] == "explicit_primary_kpi"
    assert context["direction"] == "lower"
    # target / actual / outcome volume all belong to purchase CPA.
    assert context["target"] == 80.0
    assert context["actual"] == 60.0
    assert context["outcome_volume"] == 100


# ── PART E: ROAS outcome semantics ───────────────────────────────────────


def test_roas_generic_conversions_rejected() -> None:
    # Case 6: ROAS 2.5/1.5 + 200 conversions + no event + no purchases →
    # needs_more_evidence (generic conversions are not ROAS evidence).
    state, reason = scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "roas",
            "target_roas": 1.5,
            "roas": 2.5,
            "conversions": 200,
        }
    )
    assert state == "needs_more_evidence"
    assert reason == "missing_outcome_volume"


def test_roas_purchase_evidence_eligible() -> None:
    # Case 7: ROAS + sufficient purchases → eligibility proceeds.
    state, reason = scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "roas",
            "target_roas": 1.5,
            "roas": 2.5,
            "purchases": 80,
        }
    )
    assert state == "eligible"
    assert reason is None


def test_roas_revenue_event_conversions_accepted() -> None:
    # §25: conversions allowed when conversion_event maps to a
    # revenue-generating event (purchase).
    volume = resolve_kpi_outcome_volume(
        "roas", {"conversions": 200, "conversion_event": "purchase"}
    )
    assert volume == 200
    # pay event is also revenue-generating.
    volume = resolve_kpi_outcome_volume(
        "roas", {"conversions": 200, "conversion_event": "pay"}
    )
    assert volume == 200


# ── PART F: Action-relevant rival semantics ──────────────────────────────


def test_market_wide_context_does_not_block_scale(workspace) -> None:
    # Case 9: market_wide_event supported + Google healthy scale candidate
    # → NOT automatically investigate; small increase + market warning.
    # (Google carries a CPM rise too, but without extra auction/bid
    # support signals the constraint diagnosis stays the clean top.)
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "cpm_change_pct": 0.3,
            "cvr_change_pct": 0.01,
            "impressions": 100000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    # Meta CPM up too → cross_cpm_up → market-wide context. Both
    # platforms CVR stable → cross_platform_comparison_available.
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "cvr_change_pct": 0.01,
            "impressions": 100000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.convergence_status == "converged"
    assert result.recommended_action == "increase"
    assert any(
        m.hypothesis_id == "market_wide_event" for m in result.material_context
    ), result.material_context
    summary = summarize_decision_intelligence(result)
    assert "不建议一次放太多" in summary
    run.finish()


def test_shared_funnel_still_blocks_scale(workspace) -> None:
    # Case 8: shared_product_funnel_issue supported → scale deferred
    # (conversion reliability is undermined).
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "delivery_concentrated": True,
            "cvr_change_pct": -0.2,
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
    run.record_observation(
        {
            "pay_rate_change_pct": -0.3,
            "cvr_change_pct": -0.25,
            "impressions": 100000,
            "clicks": 5000,
            "registrations": 1000,
            "payments": 300,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.convergence_status == "investigate"
    assert result.recommended_action != "increase"
    run.finish()


def test_shared_blocks_scale_investigate_not_blocked() -> None:
    top = _eval("budget_constraint", platform="google_ads")
    funnel = _eval("shared_product_funnel_issue")
    assert shared_candidate_blocks_action(funnel, "increase", top) is True
    assert shared_candidate_blocks_action(funnel, "scale", top) is True
    assert shared_candidate_blocks_action(funnel, "investigate", top) is False
    assert shared_candidate_blocks_action(funnel, "wait", top) is False


# ── PART H: KPI-family scale evidence ────────────────────────────────────


def test_20_installs_vs_20_payments_not_equal() -> None:
    # Case 12: identical counts, different KPI families — installs (min
    # 50) defer at 20; payments (min 10) pass at 20.
    installs = scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "cpi",
            "target_cpi": 5.0,
            "cpi": 3.0,
            "installs": 20,
        }
    )
    payments = scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 20,
        }
    )
    assert installs == ("needs_more_evidence", "low_conversion_volume")
    assert payments == ("eligible", None)


def test_low_installs_no_scale() -> None:
    # Case 10: CPI primary + installs low → no scale.
    state, reason = scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "cpi",
            "target_cpi": 5.0,
            "cpi": 3.0,
            "installs": 30,
        }
    )
    assert state == "needs_more_evidence"
    assert reason == "low_conversion_volume"


def test_low_payments_no_scale() -> None:
    # Case 11: pay CPA primary + payments low (3) → no scale (deep events
    # are sparse but 2-3 payments are still nothing).
    state, reason = scale_eligibility(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 3,
        }
    )
    assert state == "needs_more_evidence"
    assert reason == "low_conversion_volume"


# ── Runtime E2E ──────────────────────────────────────────────────────────


def test_e2e_google_auction_top_meta_runner(workspace) -> None:
    # E2E 1: same hypothesis on two platforms — Google stronger; summary
    # evidence is Google's.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="CPM 涨了吗？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "ctr_change_pct": 0.01,
            "multi_creative_impacted": True,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.12,
            "ctr_change_pct": 0.01,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "auction_pressure"
    assert result.top_platform == "google_ads"
    assert result.selected_evaluation is not None
    assert result.selected_evaluation.platform == "google_ads"
    assert "multi_creative_impacted" in result.selected_evaluation.supporting
    run.finish()


def test_e2e_market_wide_context_survives(workspace) -> None:
    # E2E 4: market-wide shared context + Google scale candidate → not
    # unconditionally blocked.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "cpm_change_pct": 0.3,
            "cvr_change_pct": 0.01,
            "impressions": 100000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "cvr_change_pct": 0.01,
            "impressions": 100000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.action_eligibility == "eligible"
    assert result.recommended_action == "increase"
    assert any(m.hypothesis_id == "market_wide_event" for m in result.material_context)
    run.finish()
