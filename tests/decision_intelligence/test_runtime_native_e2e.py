"""v3.5.1 runtime-native Decision Intelligence E2E tests.

Every scenario goes through the REAL run path:

    run.begin(...) → run.record_observation(...) → run.evaluate_decision_intelligence()

Tests must NOT assemble the pipeline manually (no build_hypothesis_set /
signals_from_metrics / evaluate / rank / converge calls). Raw evidence is
provided as raw relative movement (change_pct) — never hand-polished
signals.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.runtime import (
    PlatformOperationalRun,
    summarize_decision_intelligence,
)
from appflow_ops.uac.workspace import initialize_workspace


def _workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _run(
    workspace,
    request: str,
    scope,
    metrics,
    platform="meta",
    observed_at="2026-08-13T09:00:00Z",
):
    run = PlatformOperationalRun(workspace)
    run.begin(request_text=request, platform_scope=tuple(scope))
    run.record_observation(metrics, platform=platform, observed_at=observed_at)
    return run


# ── Scenario 1: runtime-native Meta fatigue ──────────────────────────────


def test_scenario1_meta_fatigue_raw_evidence(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = _run(
        ws,
        "Meta 这个素材是不是衰减了？",
        ("meta",),
        {
            "spend": 320.0,
            "ctr_change_pct": -0.25,
            "cpm_change_pct": 0.02,
            "cvr_change_pct": 0.01,
            "frequency_change_pct": 0.18,
            "impressions": 50000,
            "clicks": 2500,
            "conversions": 60,
            "old_creative_worse": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "creative_fatigue"
    assert result.top_status == "supported"
    # Auction weakened by stable CPM — no material alternative.
    auction = next(
        ev for ev in result.evaluations if ev.hypothesis.id == "auction_pressure"
    )
    assert auction.status == "weakened"
    assert result.convergence_status == "converged"
    assert result.recommended_action in ("replace", "retest")
    run.finish()


# ── Scenario 2: runtime-native Meta auction ──────────────────────────────


def test_scenario2_meta_auction_raw_evidence(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = _run(
        ws,
        "这两天怎么越来越贵了？",
        ("meta",),
        {
            "spend": 320.0,
            "cpm_change_pct": 0.35,
            "ctr_change_pct": 0.01,
            "cvr_change_pct": -0.01,
            "frequency_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "auction_pressure"
    fatigue = next(
        ev for ev in result.evaluations if ev.hypothesis.id == "creative_fatigue"
    )
    assert fatigue.status != "supported"  # creative must not top
    run.finish()


# ── Scenario 3: supported rival → no confident convergence ───────────────


def test_scenario3_supported_rival_no_confident_convergence(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = _run(
        ws,
        "Meta 量掉了，帮我看下原因",
        ("meta",),
        {
            "spend": 320.0,
            "ctr_change_pct": -0.22,
            "cpm_change_pct": 0.28,
            "frequency_change_pct": 0.15,
            "impressions": 50000,
            "clicks": 2500,
            "old_creative_worse": True,
            "reach_growth_slowing": True,
            "delivery_concentrated": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    result = run.evaluate_decision_intelligence()
    assert result.convergence_status != "converged"
    assert len(result.material_alternatives) >= 2
    assert result.next_discriminating_evidence
    assert result.recommended_action in ("investigate", "wait", "observe")
    run.finish()


# ── Scenario 4: TikTok click→install ─────────────────────────────────────


def test_scenario4_tiktok_click_install(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = _run(
        ws,
        "TikTok 点击还行，为什么安装掉了？",
        ("tiktok",),
        {
            "spend": 210.0,
            "ctr_change_pct": 0.01,
            "click_volume_change_pct": 0.0,
            "install_rate_change_pct": -0.2,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="tiktok",
    )
    result = run.evaluate_decision_intelligence()
    ranked_live = [
        item.evaluation
        for item in result.ranked_hypotheses
        if item.evaluation.status not in ("weakened", "excluded")
    ]
    assert ranked_live[0].hypothesis.id in (
        "click_to_install_friction",
        "store_page_friction",
        "traffic_quality_shift",
        "install_measurement_issue",
    )
    assert ranked_live[0].hypothesis.id != "creative_fatigue"
    run.finish()


# ── Scenario 5: TikTok pay funnel ────────────────────────────────────────


def test_scenario5_tiktok_pay_funnel(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = _run(
        ws,
        "TikTok 安装没掉，付费掉了",
        ("tiktok",),
        {
            "spend": 210.0,
            "install_rate_change_pct": 0.01,
            "registration_rate_change_pct": -0.01,
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="tiktok",
    )
    result = run.evaluate_decision_intelligence()
    ranked_live = [
        item.evaluation
        for item in result.ranked_hypotheses
        if item.evaluation.status not in ("weakened", "excluded")
    ]
    assert ranked_live[0].hypothesis.id == "pay_funnel_degradation"
    run.finish()


# ── Scenario 6: cross-platform product signal ────────────────────────────


def test_scenario6_cross_platform_product_signal(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = PlatformOperationalRun(ws)
    run.begin(
        request_text="Google 和 Meta 付费都掉了", platform_scope=("google_ads", "meta")
    )
    run.record_observation(
        {
            "spend": 500.0,
            "pay_rate_change_pct": -0.25,
            "click_volume_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "spend": 320.0,
            "pay_rate_change_pct": -0.3,
            "click_volume_change_pct": 0.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.operational_domain in ("funnel", "cross_platform", "general")
    ranked_live = [
        item.evaluation
        for item in result.ranked_hypotheses
        if item.evaluation.status not in ("weakened", "excluded")
    ]
    assert ranked_live[0].hypothesis.id in (
        "shared_product_funnel_issue",
        "shared_measurement_issue",
    )
    run.finish()


# ── Scenario 7: cross-platform measurement conflict ──────────────────────


def test_scenario7_cross_measurement_conflict(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = PlatformOperationalRun(ws)
    run.begin(
        request_text="两边付费都掉，是产品问题吗？",
        platform_scope=("google_ads", "meta"),
    )
    run.record_observation(
        {
            "spend": 500.0,
            "pay_rate_change_pct": -0.25,
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "spend": 320.0,
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    # Measurement conflict: no confident product convergence; measurement
    # investigation stays material.
    assert result.convergence_status in ("investigate", "wait")
    assert result.safety_context["measurement_state"] == "invalid"
    assert result.recommended_action in (
        "investigate",
        "investigate_measurement",
        "wait",
    )
    run.finish()


# ── Scenario 8: “这素材还能跑吗？” vague query ───────────────────────────


def test_scenario8_vague_creative_query(tmp_path) -> None:
    ws = _workspace(tmp_path)
    run = _run(
        ws,
        "这素材还能跑吗？",
        ("meta",),
        {
            "spend": 320.0,
            "ctr_change_pct": -0.05,
            "cpm_change_pct": 0.01,
            "cvr_change_pct": 0.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    result = run.evaluate_decision_intelligence()
    summary = summarize_decision_intelligence(result)
    # Short, user-facing answer; no full ranking table; conservative
    # wording when evidence is not decisive ("还能跑，但先别加量" semantics).
    assert len(summary.splitlines()) <= 12
    assert "先别调" in summary or "先观察" in summary or "保持观察" in summary
    assert "CTR" in summary  # strongest evidence line
    run.finish()


# ── “现在呢？” follow-up: previous Decision + Change + new Observation ───


def test_follow_up_now_uses_previous_state(tmp_path) -> None:
    ws = _workspace(tmp_path)
    # Run 1: fatigue diagnosis + confirmed change.
    run1 = _run(
        ws,
        "Meta 素材是不是衰减了？",
        ("meta",),
        {
            "spend": 320.0,
            "ctr_change_pct": -0.25,
            "cpm_change_pct": 0.02,
            "cvr_change_pct": 0.01,
            "frequency_change_pct": 0.18,
            "old_creative_worse": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )
    result1 = run1.evaluate_decision_intelligence()
    assert result1.top_hypothesis == "creative_fatigue"
    run1.finish()

    # Run 2 (next day): new observation, vague request. The runtime reads
    # history itself — the test never assembles historical signals.
    run2 = _run(
        ws,
        "现在呢？",
        ("meta",),
        {
            "spend": 340.0,
            "ctr_change_pct": -0.02,
            "cpm_change_pct": 0.01,
            "cvr_change_pct": 0.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        observed_at="2026-08-14T09:00:00Z",
    )
    result2 = run2.evaluate_decision_intelligence()
    assert result2.platform_scope == ("meta",)
    # Stabilizing CTR: no confident fatigue conclusion anymore.
    assert (
        result2.top_hypothesis != "creative_fatigue"
        or result2.top_status != "supported"
    )
    run2.finish()
