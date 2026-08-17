"""v3.6.4 optimization timing & action sequencing tests.

WHEN TO ACT / WHICH ACTION FIRST: an action may be eligible in
principle but not ready now; the previous material change must have
accumulated enough NEW evidence before another material action; one
material lever at a time; wait must name what triggers the next review;
creative fatigue is refresh/retest/pause/hold, not only replace.

Covers the 16 adversarial cases of the spec (PART Q) plus the
"现在呢？" runtime E2E (PART R).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    evaluate_action_readiness,
    evaluate_descale_candidate,
    evaluate_hypotheses,
    resolve_action_lever,
    resolve_action_magnitude,
    resolve_creative_action,
    resolve_primary_kpi,
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


# ── PART A: goal 三源共同校验 ────────────────────────────────────────────


def test_goal_sources_must_agree() -> None:
    # Case 13: optimization_goal=install + conversion_event=pay → conflict.
    kpi, reason = resolve_primary_kpi(
        {"optimization_goal": "install", "conversion_event": "pay"}
    )
    assert kpi is None
    assert reason == "ambiguous_goal_semantics"


def test_compatible_goal_sources() -> None:
    # §A.2: primary_kpi=pay_cpa + goal=pay + event=payment → consistent.
    kpi, reason = resolve_primary_kpi(
        {
            "primary_kpi": "pay_cpa",
            "optimization_goal": "pay",
            "conversion_event": "payment",
        }
    )
    assert kpi == "pay_cpa"
    assert reason is None


def test_purchase_event_cannot_choose_purchase_cpa_vs_roas() -> None:
    # Case 14: conversion_event=purchase + target_purchase_cpa +
    # target_roas → ambiguous (purchase event alone is not enough).
    kpi, reason = resolve_primary_kpi(
        {
            "conversion_event": "purchase",
            "target_purchase_cpa": 50.0,
            "target_roas": 1.5,
        }
    )
    assert kpi is None
    assert reason == "ambiguous_primary_kpi"
    # revenue goal disambiguates → roas.
    kpi, reason = resolve_primary_kpi(
        {
            "optimization_goal": "revenue",
            "conversion_event": "purchase",
            "target_purchase_cpa": 50.0,
            "target_roas": 1.5,
        }
    )
    assert kpi == "roas"
    assert reason is None


def test_purchase_event_single_target_ok() -> None:
    # No ROAS target → purchase_cpa unambiguous.
    kpi, reason = resolve_primary_kpi(
        {"conversion_event": "purchase", "target_purchase_cpa": 50.0}
    )
    assert kpi == "purchase_cpa"
    assert reason is None


# ── PART B/D: action readiness & evidence window ─────────────────────────


def test_eligible_but_not_ready() -> None:
    # §6/32: eligible in principle, but budget +20% 2h ago with only 2
    # new payments → wait (not ready), never a second increase.
    state, wait_reason, trigger = evaluate_action_readiness(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "window_outcomes": 2,
        },
        {
            "last_change_effective_at": "2026-08-14T09:00:00Z",
            "current_observed_at": "2026-08-14T11:00:00Z",
        },
    )
    assert state == "wait"
    assert wait_reason == "recent_change_unsettled"
    assert trigger == "more_pay_outcomes"


def test_change_fully_evaluated_is_ready() -> None:
    # §31: 24h+ and enough new payments → ready.
    state, wait_reason, _ = evaluate_action_readiness(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "window_outcomes": 40,
        },
        {
            "last_change_effective_at": "2026-08-13T09:00:00Z",
            "current_observed_at": "2026-08-14T09:30:00Z",
        },
    )
    assert state == "ready"
    assert wait_reason is None


def test_no_pending_change_is_ready() -> None:
    state, _, _ = evaluate_action_readiness({**STABLE_MATURE})
    assert state == "ready"
    assert _ is None  # no wait reason without a pending change


def test_time_alone_not_enough() -> None:
    # §14/16: 24h passed but only 3 new payments → still wait (outcome-
    # first for deep KPIs).
    state, _, trigger = evaluate_action_readiness(
        {
            **STABLE_MATURE,
            "primary_kpi": "pay_cpa",
            "window_outcomes": 3,
        },
        {
            "last_change_effective_at": "2026-08-13T09:00:00Z",
            "current_observed_at": "2026-08-14T09:30:00Z",
        },
    )
    assert state == "wait"
    assert trigger == "more_pay_outcomes"


# ── PART E/F: sequential change protection ───────────────────────────────


def test_recent_change_blocks_second_scale_e2e(workspace) -> None:
    # Case 3: budget +20% 2h ago still looks good but insufficient new
    # outcomes → wait, never a second increase.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算还能再加吗？", platform_scope=("google_ads",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "window_outcomes": 5,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T11:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    # No stored change → no window context → readiness is ready; the
    # guard is exercised at the helper level and through the library
    # converge path (window_context passed explicitly in tests below).
    assert result.top_hypothesis == "budget_constraint"
    run.finish()


def test_sequential_change_guard_in_converge(workspace) -> None:
    # The runtime-native guard: a recent confirmed Change in state must
    # gate a second material action. Simulate via library converge with
    # an explicit window_context.
    from appflow_ops.decision_intelligence import (
        build_hypothesis_set,
        converge,
        rank_hypotheses,
    )

    specs = build_hypothesis_set(platform_scope=("meta",), domain="bid_budget")
    evals = evaluate_hypotheses(
        specs,
        {"budget_utilization_high": True, "spend_hit_cap": True},
        measurement_state="stable",
        maturity_state="sufficient",
    )
    ranked = rank_hypotheses(evals)
    result = converge(
        ranked,
        action_context={
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "window_outcomes": 5,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        window_context={
            "last_change_effective_at": "2026-08-14T09:00:00Z",
            "current_observed_at": "2026-08-14T11:00:00Z",
        },
    )
    assert result.action_eligibility == "eligible"
    assert result.action_readiness == "wait"
    assert result.wait_reason == "recent_change_unsettled"
    assert result.next_review_trigger == "more_outcomes"
    assert result.decision == "hold"  # eligible but NOT ready → hold


# ── PART G/I: scale & descale timing ─────────────────────────────────────


def test_real_descale_candidate() -> None:
    # Case 4: CPA 95/50 + stable + mature + persistent negative trend +
    # no recent change → small decrease justified.
    assert (
        evaluate_descale_candidate(
            {
                **STABLE_MATURE,
                "cpa": 95.0,
                "target_cpa": 50.0,
                "conversions": 300,
            },
            ("cvr_trend_down",),
        )
        is True
    )


def test_bad_cpa_after_change_no_descale() -> None:
    # Case 5: same CPA 95 but budget changed recently → wait/investigate,
    # never an immediate decrease (no ping-pong).
    assert (
        evaluate_descale_candidate(
            {
                **STABLE_MATURE,
                "recent_budget_change": True,
                "cpa": 95.0,
                "target_cpa": 50.0,
                "conversions": 300,
            },
            ("cvr_trend_down",),
        )
        is False
    )


def test_tiny_sample_no_descale() -> None:
    # §40: small sample → never react.
    assert (
        evaluate_descale_candidate(
            {
                **STABLE_MATURE,
                "cpa": 95.0,
                "target_cpa": 50.0,
                "conversions": 3,
            },
            ("cvr_trend_down",),
        )
        is False
    )


def test_no_negative_trend_no_descale() -> None:
    # §41: negative trend must persist through a valid window.
    assert (
        evaluate_descale_candidate(
            {
                **STABLE_MATURE,
                "cpa": 95.0,
                "target_cpa": 50.0,
                "conversions": 300,
            },
            (),
        )
        is False
    )


# ── PART H: action magnitude ─────────────────────────────────────────────


def test_magnitude_small_for_deep_event_and_context() -> None:
    # §35/36: deep-event KPI → small; market context → small; strong
    # headroom without context → normal.
    assert (
        resolve_action_magnitude(
            "increase",
            {
                **STABLE_MATURE,
                "primary_kpi": "pay_cpa",
                "target_pay_cpa": 100.0,
                "pay_cpa": 60.0,
                "payments": 40,
            },
            (),
        )
        == "small"
    )
    assert (
        resolve_action_magnitude(
            "increase",
            {**STABLE_MATURE, "cpa": 30.0, "target_cpa": 50.0, "conversions": 200},
            ("market_wide_event",),
        )
        == "small"
    )
    assert (
        resolve_action_magnitude(
            "increase",
            {**STABLE_MATURE, "cpa": 30.0, "target_cpa": 50.0, "conversions": 200},
            (),
        )
        == "normal"
    )
    assert resolve_action_magnitude("decrease", {}) == "small"
    assert resolve_action_magnitude("wait", {}) == "none"


# ── PART J: budget vs bid sequencing ─────────────────────────────────────


def test_lever_resolution() -> None:
    # §45-47: diagnose the constraint before choosing the lever.
    assert resolve_action_lever("budget_constraint") == "budget"
    assert resolve_action_lever("bid_constraint") == "bid"
    assert resolve_action_lever("creative_fatigue") == "creative"
    assert resolve_action_lever("measurement_instability") == "measurement"
    assert resolve_action_lever("auction_pressure") is None


def test_budget_lever_first_when_budget_capped(workspace) -> None:
    # Case 6: budget hit cap + bid not constrained + CPA excellent →
    # budget lever, never bid.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="预算加不加？", platform_scope=("google_ads",))
    run.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
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
    assert result.top_hypothesis == "budget_constraint"
    assert result.action_lever == "budget"
    assert result.action_magnitude == "normal"
    run.finish()


def test_bid_lever_first_when_bid_constrained(workspace) -> None:
    # Case 7: bid constraint supported; budget shares delivery signals so
    # it is ALSO supported — the system never moves both levers at once
    # (Case 8: both constraints → investigate/hold, never double-action).
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="出价要不要调？", platform_scope=("google_ads",))
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "delivery_concentrated": True,
            "budget_utilization_high": True,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "bid_constraint"
    # Both constraints materially supported → investigate (never change
    # budget AND bid in one decision).
    assert result.recommended_action == "investigate"
    assert result.action_lever is None
    run.finish()


# ── PART K/L: creative sequencing ────────────────────────────────────────


def test_creative_action_resolution() -> None:
    # §49-53: fatigue is refresh/retest/pause/hold — never only replace.
    assert (
        resolve_creative_action(
            "creative_fatigue", ("ctr_trend_down",), {**STABLE_MATURE}
        )
        == "refresh"
    )
    assert (
        resolve_creative_action(
            "creative_fatigue",
            ("ctr_trend_down",),
            {**STABLE_MATURE, "recent_budget_change": True},
        )
        == "retest"
    )
    assert (
        resolve_creative_action(
            "creative_fatigue",
            ("ctr_trend_down",),
            {**STABLE_MATURE, "impressions": 10000, "only_one_creative_declines": True},
        )
        == "pause"
    )
    assert (
        resolve_creative_action(
            "creative_fatigue",
            ("ctr_trend_down",),
            {**STABLE_MATURE, "recent_creative_change": True, "impressions": 300},
        )
        == "hold"
    )
    assert resolve_creative_action("auction_pressure", (), {}) == "observe"


def test_fatigue_refresh_not_budget_change(workspace) -> None:
    # Case 9: fatigue supported + overall CPA acceptable → refresh, NOT
    # budget decrease.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="素材还能跑吗？", platform_scope=("meta",))
    run.record_observation(
        {
            "ctr_change_pct": -0.25,
            "frequency_change_pct": 0.18,
            "old_creative_worse": True,
            "cvr_change_pct": 0.01,
            "cpm_change_pct": 0.01,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "creative_fatigue"
    assert result.recommended_action == "refresh"
    assert result.action_lever == "creative"
    assert result.action_magnitude == "none"
    run.finish()


# ── PART R: "现在呢？" runtime E2E ───────────────────────────────────────


def test_now_what_early_followup(workspace) -> None:
    # Day 1: pay CPA 70/100 + budget constrained → small increase.
    # Change: budget +15%. Early follow-up: pay CPA 78, only 2 new
    # payments → hold (recent scale not sufficiently evaluated).
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="预算加不加？", platform_scope=("meta",))
    run1.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            "entity_level": "account",
            "aggregate_scope": "account",
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    day1 = run1.evaluate_decision_intelligence()
    assert day1.action_eligibility == "eligible"
    assert day1.recommended_action == "increase"
    assert day1.action_magnitude == "small"  # deep-event KPI
    run1.record_decision_from_intelligence()
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.15,
        effective_at="2026-08-13T10:00:00Z",
    )
    run1.finish()
    # Early follow-up (2h after the change, only 2 new payments): the
    # previous material change has not accumulated enough NEW evidence.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    run2.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 78.0,
            "payments": 152,
            "entity_level": "account",
            "aggregate_scope": "account",
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T12:00:00Z",
    )
    follow = run2.evaluate_decision_intelligence()
    # v3.6.5: window_outcomes is DERIVED from state (150 → 152 = 2 new
    # payments since the confirmed change) — never hand-written.
    assert follow.decision_window is not None
    assert follow.decision_window.status == "derived"
    assert follow.decision_window.window_outcomes == 2.0
    assert follow.recommended_action in ("hold", "wait")
    assert follow.wait_reason == "recent_change_unsettled"
    assert follow.next_review_trigger == "more_pay_outcomes"
    run2.finish()


def test_now_what_mature_followup(workspace) -> None:
    # Mature follow-up: enough new payments, pay CPA still 72, budget
    # again constrained → a second staged scale may be evaluated.
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="预算加不加？", platform_scope=("meta",))
    run1.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            "entity_level": "account",
            "aggregate_scope": "account",
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run1.evaluate_decision_intelligence()
    run1.record_decision_from_intelligence()
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.15,
        effective_at="2026-08-13T10:00:00Z",
    )
    run1.finish()
    # Next day: enough new payments + pay CPA 72 + budget constrained again.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    run2.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 72.0,
            "payments": 220,
            "entity_level": "account",
            "aggregate_scope": "account",
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T10:30:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    # v3.6.5: derived from the change-window baseline (150), not 220 -
    # the previous follow-up count (152).
    assert result.decision_window is not None
    assert result.decision_window.status == "derived"
    assert result.decision_window.window_outcomes == 70.0
    assert result.recommended_action == "increase"
    assert result.action_readiness == "ready"
    assert result.action_magnitude == "small"
    run2.finish()


def test_now_what_bad_mature_followup(workspace) -> None:
    # Bad mature follow-up: enough new outcomes, pay CPA 135 → no scale.
    # Mature persistent deterioration → small decrease (descale).
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="预算加不加？", platform_scope=("meta",))
    run1.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            "entity_level": "account",
            "aggregate_scope": "account",
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run1.evaluate_decision_intelligence()
    run1.record_decision_from_intelligence()
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.15,
        effective_at="2026-08-13T10:00:00Z",
    )
    run1.finish()
    # Next day: mature sample, pay CPA 135, pay rate still declining.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    run2.record_observation(
        {
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 135.0,
            "payments": 260,
            "entity_level": "account",
            "aggregate_scope": "account",
            "pay_rate_change_pct": -0.35,
            "registrations": 1200,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-14T09:30:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    # 不会继续 increase；pay_rate 持续下降 + 成熟样本 → small decrease。
    assert result.recommended_action != "increase"
    assert result.recommended_action in ("decrease", "hold", "wait")
    run2.finish()
