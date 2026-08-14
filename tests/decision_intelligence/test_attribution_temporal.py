"""v3.5.3 evidence attribution & temporal comparability tests.

Covers: provenance-aware evaluation (platform-bound hypotheses consume
only their platform's signals — cross-platform splicing impossible),
shared-only cross evidence, market-wide false positives, measurement
conflict semantics (invalid+stable vs invalid+unknown), historical
comparability (same platform ≠ comparable; entity/level/breakdown),
temporal Change relevance (baseline < change <= current), distinct
change types, and global temporal context ordering.
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
)
from appflow_ops.runtime import (
    PlatformOperationalRun,
    summarize_decision_intelligence,
)
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


# ── Scenario 1: cross-platform signal splicing regression ────────────────


def test_tiktok_funnel_not_supported_by_meta_pay_drop() -> None:
    # Meta pay↓ + TikTok stable signals: TikTok's own evaluation must NOT
    # be supported by Meta's pay decline (splicing regression).
    evidence = build_evidence(
        per_platform={
            "meta": {"pay_rate_change_pct": -0.3},
            "tiktok": {
                "install_rate_change_pct": 0.01,
                "registration_rate_change_pct": 0.0,
                "pay_rate_change_pct": 0.01,
            },
        }
    )
    specs = build_hypothesis_set(platform_scope=("meta", "tiktok"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("meta", "tiktok"))
    tiktok_funnel = [ev for ev in evals if ev.hypothesis.id == "pay_funnel_degradation"]
    assert tiktok_funnel
    for evaluation in tiktok_funnel:
        assert evaluation.platform == "tiktok"
        assert evaluation.status != "supported"
        # Meta's pay decline must NEVER appear in the TikTok evaluation.
        assert "pay_rate_trend_down" not in evaluation.supporting


# ── Scenario 2: auction signal splicing ──────────────────────────────────


def test_auction_platform_bound_evaluations_do_not_splice() -> None:
    # Meta CPM↑ + CTR↓; Google CPM stable + CTR stable. The Meta auction
    # evaluation must only see Meta signals (no Google ctr_trend_stable
    # help), and vice versa.
    evidence = build_evidence(
        per_platform={
            "meta": {"cpm_change_pct": 0.3, "ctr_change_pct": -0.2},
            "google_ads": {"cpm_change_pct": 0.01, "ctr_change_pct": 0.0},
        }
    )
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    meta_auction = next(
        ev
        for ev in evals
        if ev.hypothesis.id == "auction_pressure" and ev.platform == "meta"
    )
    google_auction = next(
        ev
        for ev in evals
        if ev.hypothesis.id == "auction_pressure" and ev.platform == "google_ads"
    )
    # Meta: CPM↑ supports (2). Google: stable CPM contradicts (-2).
    assert "cpm_trend_up" in meta_auction.supporting
    assert "cpm_trend_stable" in google_auction.contradicting
    assert "ctr_trend_stable" not in meta_auction.supporting  # no Google help
    assert meta_auction.score > google_auction.score


# ── Scenario 3/4: shared vs one-platform decline ─────────────────────────


def test_true_shared_pay_drop_supports_shared() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {
                "pay_rate_change_pct": -0.3,
                "registrations": 1000,
                "payments": 300,
            },
            "google_ads": {
                "pay_rate_change_pct": -0.25,
                "registrations": 1000,
                "payments": 300,
            },
        }
    )
    assert evidence.shared_signals.get("cross_pay_rate_drop") is True
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    shared = next(
        ev for ev in evals if ev.hypothesis.id == "shared_product_funnel_issue"
    )
    assert shared.platform == "cross_platform"
    assert shared.status == "supported"


def test_one_platform_decline_does_not_support_shared() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"pay_rate_change_pct": -0.3},
            "google_ads": {"pay_rate_change_pct": 0.01},
        }
    )
    assert "cross_pay_rate_drop" not in evidence.shared_signals
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    shared = next(
        ev for ev in evals if ev.hypothesis.id == "shared_product_funnel_issue"
    )
    assert shared.status != "supported"
    assert not shared.supporting


# ── Scenario 5/6: market-wide false positive vs true cross CPM ───────────


def test_one_platform_cpm_rise_is_not_market_wide() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"cpm_change_pct": 0.35},
            "google_ads": {"cpm_change_pct": -0.01},
        }
    )
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    market = next(ev for ev in evals if ev.hypothesis.id == "market_wide_event")
    assert market.status != "supported"
    assert not market.supporting


def test_two_platform_cpm_rise_can_support_market_wide() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"cpm_change_pct": 0.35},
            "google_ads": {"cpm_change_pct": 0.3},
        }
    )
    assert evidence.shared_signals.get("cross_cpm_up") is True
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    market = next(ev for ev in evals if ev.hypothesis.id == "market_wide_event")
    # cross_cpm_up + comparison available → may be supported.
    assert "cross_cpm_up" in market.supporting


# ── Scenario 7/8: historical comparability ───────────────────────────────


def test_different_entity_derives_no_trend() -> None:
    previous = {"ctr": 0.009, "entity_id": "campaign_a"}
    current = {"ctr": 0.007, "entity_id": "campaign_b"}
    evidence = build_evidence(
        per_platform={"meta": current},
        historical_by_platform={"meta": previous},
    )
    assert evidence.historical_comparisons == {}
    assert "ctr_trend_down" not in evidence.signals


def test_same_entity_derives_trend() -> None:
    previous = {"ctr": 0.009, "entity_id": "campaign_a"}
    current = {"ctr": 0.007, "entity_id": "campaign_a"}
    evidence = build_evidence(
        per_platform={"meta": current},
        historical_by_platform={"meta": previous},
    )
    assert evidence.historical_comparisons["meta"]["ctr_trend"] == pytest.approx(
        -0.222, abs=0.01
    )
    assert evidence.signals["ctr_trend_down"] is True


def test_different_level_derives_no_trend() -> None:
    previous = {"ctr": 0.009, "entity_level": "account"}
    current = {"ctr": 0.007, "entity_level": "campaign"}
    evidence = build_evidence(
        per_platform={"meta": current},
        historical_by_platform={"meta": previous},
    )
    assert evidence.historical_comparisons == {}


def test_incompatible_breakdown_derives_no_trend() -> None:
    previous = {"ctr": 0.009, "breakdown_scope": "gender"}
    current = {"ctr": 0.007, "breakdown_scope": "all"}
    evidence = build_evidence(
        per_platform={"meta": current},
        historical_by_platform={"meta": previous},
    )
    assert evidence.historical_comparisons == {}


# ── Scenario 9/10: temporal change relevance ─────────────────────────────


def test_change_between_baseline_and_current_is_confounder() -> None:
    evidence = build_evidence(
        per_platform={"meta": {"ctr_change_pct": -0.2}},
        recent_changes=(
            {
                "payload": {
                    "change_type": "budget",
                    "direction": "increase",
                    "effective_at": "2026-08-12T18:00:00Z",
                },
                "observed_at": "2026-08-12T18:00:00Z",
            },
        ),
        current_observed_at={"meta": "2026-08-13T09:00:00Z"},
        historical_observed_at={"meta": "2026-08-12T09:00:00Z"},
    )
    assert evidence.recent_change_context.get("recent_budget_change") is True
    assert evidence.signals.get("recent_budget_change") is True
    assert evidence.change_context.get("last_budget_change_effective_at")


def test_change_before_baseline_is_not_confounder() -> None:
    evidence = build_evidence(
        per_platform={"meta": {"ctr_change_pct": -0.2}},
        recent_changes=(
            {
                "payload": {
                    "change_type": "budget",
                    "direction": "increase",
                    "effective_at": "2026-08-10T09:00:00Z",
                },
                "observed_at": "2026-08-10T09:00:00Z",
            },
        ),
        current_observed_at={"meta": "2026-08-13T09:00:00Z"},
        historical_observed_at={"meta": "2026-08-12T09:00:00Z"},
    )
    assert "recent_budget_change" not in evidence.recent_change_context
    assert "recent_budget_change" not in evidence.signals
    # Age metadata still retained for audit.
    assert evidence.change_context.get("last_budget_change_effective_at")


def test_very_old_latest_stored_change_is_not_recent() -> None:
    evidence = build_evidence(
        per_platform={"meta": {"ctr_change_pct": -0.2}},
        recent_changes=(
            {
                "payload": {
                    "change_type": "budget",
                    "direction": "increase",
                    "effective_at": "2026-06-01T09:00:00Z",
                },
                "observed_at": "2026-06-01T09:00:00Z",
            },
        ),
        current_observed_at={"meta": "2026-08-13T09:00:00Z"},
        historical_observed_at={"meta": "2026-08-12T09:00:00Z"},
    )
    assert "recent_budget_change" not in evidence.recent_change_context


# ── Scenario 11: change type separation ──────────────────────────────────


def test_audience_change_is_not_creative_change() -> None:
    evidence = build_evidence(
        per_platform={"meta": {"ctr": 0.008}},
        recent_changes=(
            {
                "payload": {
                    "change_type": "audience",
                    "direction": "change",
                    "effective_at": "2026-08-12T18:00:00Z",
                },
                "observed_at": "2026-08-12T18:00:00Z",
            },
        ),
        current_observed_at={"meta": "2026-08-13T09:00:00Z"},
        historical_observed_at={"meta": "2026-08-12T09:00:00Z"},
    )
    assert evidence.recent_change_context.get("recent_audience_change") is True
    assert "recent_creative_change" not in evidence.recent_change_context


def test_creative_and_campaign_changes_separate() -> None:
    evidence = build_evidence(
        per_platform={"meta": {"ctr": 0.008}},
        recent_changes=(
            {
                "payload": {
                    "change_type": "campaign",
                    "direction": "change",
                    "effective_at": "2026-08-12T18:00:00Z",
                },
                "observed_at": "2026-08-12T18:00:00Z",
            },
        ),
        current_observed_at={"meta": "2026-08-13T09:00:00Z"},
        historical_observed_at={"meta": "2026-08-12T09:00:00Z"},
    )
    assert evidence.recent_change_context.get("recent_campaign_change") is True
    assert "recent_creative_change" not in evidence.recent_change_context


# ── Scenario 12/13: measurement conflict semantics ───────────────────────


def test_invalid_plus_unknown_is_not_conflict() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid"},
            "google_ads": {"measurement_state": "unknown"},
        }
    )
    assert "measurement_conflict" not in evidence.shared_signals
    assert "measurement_conflict" not in evidence.signals


def test_invalid_plus_stable_is_conflict() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid"},
            "google_ads": {"measurement_state": "stable"},
        }
    )
    assert evidence.shared_signals.get("measurement_conflict") is True


def test_two_invalid_platforms_is_shared_measurement() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid"},
            "google_ads": {"measurement_state": "invalid"},
        }
    )
    assert evidence.shared_signals.get("cross_measurement_invalid") is True


# ── Context global ordering ──────────────────────────────────────────────


def test_latest_decision_by_timestamp_not_tuple_order() -> None:
    # Tuple order says Meta decision first; timestamps say Google is later.
    evidence = build_evidence(
        per_platform={"meta": {"ctr": 0.008}},
        recent_decisions=(
            {
                "event_id": "event_00000001",
                "platform": "meta",
                "observed_at": "2026-08-12T09:00:00Z",
                "payload": {
                    "decision_class": "wait",
                    "review_condition": None,
                    "review_after": None,
                    "confidence": "medium",
                },
            },
            {
                "event_id": "event_00000002",
                "platform": "google_ads",
                "observed_at": "2026-08-13T09:00:00Z",
                "payload": {
                    "decision_class": "investigate",
                    "review_condition": None,
                    "review_after": None,
                    "confidence": "medium",
                },
            },
        ),
    )
    assert evidence.decision_context.get("decision_class") == "investigate"
    assert "google_ads" in evidence.decisions_by_platform
    assert "meta" in evidence.decisions_by_platform


# ── Top platform attribution in user output ──────────────────────────────


def test_top_platform_attribution_in_summary(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Meta 越来越贵，Google 呢？", platform_scope=("google_ads", "meta")
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.35,
            "ctr_change_pct": 0.01,
            "cvr_change_pct": 0.0,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.01,
            "ctr_change_pct": 0.0,
            "cvr_change_pct": 0.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_platform == "meta"
    assert result.top_hypothesis == "auction_pressure"
    summary = summarize_decision_intelligence(result)
    assert "meta" in summary.lower()
    run.finish()
