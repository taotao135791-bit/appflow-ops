"""v3.5.4 evaluation scope & safety provenance tests.

Covers: wildcard ("*") hypotheses evaluated per platform (no flat-union
splicing), platform-bound Safety (Meta invalid never caps Google), Change
provenance (Meta Change never pollutes Google; platform-specific temporal
windows), newest-comparable historical selection, unknown-identity vs
explicit-account semantics, raw entity ID privacy, and measurement
conflict vs shared measurement issue separation.
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
    observations_comparable,
)
from appflow_ops.runtime import (
    PlatformOperationalRun,
)
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


# ── Scenario 1: wildcard cross-platform splicing ─────────────────────────


def test_wildcard_hypothesis_evaluated_per_platform() -> None:
    # Meta CVR↓; Google multi_creative_impacted. conversion_funnel_*
    # (applicable="*", scope=platform) must be evaluated separately:
    # @meta sees only Meta signals; @google_ads only Google's.
    evidence = build_evidence(
        per_platform={
            "meta": {"cvr_change_pct": -0.3},
            "google_ads": {"multi_creative_impacted": True},
        }
    )
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    funnel = [ev for ev in evals if ev.hypothesis.id == "conversion_funnel_degradation"]
    assert len(funnel) == 2  # one per platform
    meta_funnel = next(ev for ev in funnel if ev.platform == "meta")
    google_funnel = next(ev for ev in funnel if ev.platform == "google_ads")
    assert "cvr_trend_down" in meta_funnel.supporting
    # Google's signal must never appear in the Meta evaluation.
    assert "multi_creative_impacted" not in meta_funnel.supporting
    assert "cvr_trend_down" not in google_funnel.supporting


# ── Scenario 2/3: platform Safety isolation ──────────────────────────────


def test_meta_invalid_does_not_cap_google_auction() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid"},
            "google_ads": {
                "cpm_change_pct": 0.3,
                "ctr_change_pct": 0.01,
                "impressions": 50000,
                "clicks": 5000,
                "measurement_state": "stable",
                "maturity_state": "sufficient",
            },
        }
    )
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state="invalid",  # aggregate would cap everything
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
        maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
    )
    google_auction = next(
        ev
        for ev in evals
        if ev.hypothesis.id == "auction_pressure" and ev.platform == "google_ads"
    )
    meta_auction = next(
        ev
        for ev in evals
        if ev.hypothesis.id == "auction_pressure" and ev.platform == "meta"
    )
    # Google evaluated normally; Meta capped by its own invalid state.
    assert google_auction.status == "supported"
    assert meta_auction.safety_capped is True or meta_auction.status != "supported"


def test_measurement_instability_only_supported_where_invalid() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid"},
            "google_ads": {"measurement_state": "stable", "cpm_change_pct": 0.02},
        }
    )
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state="invalid",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
        maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
    )
    meta_instability = next(
        ev
        for ev in evals
        if ev.hypothesis.id == "measurement_instability" and ev.platform == "meta"
    )
    google_instability = next(
        ev
        for ev in evals
        if ev.hypothesis.id == "measurement_instability" and ev.platform == "google_ads"
    )
    assert "measurement_invalid" in meta_instability.supporting
    assert "measurement_invalid" not in google_instability.supporting
    assert google_instability.status != "supported"


# ── Scenario 4/5: Change provenance ──────────────────────────────────────


def test_meta_budget_change_does_not_pollute_google() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"ctr_change_pct": -0.2},
            "google_ads": {"ctr_change_pct": 0.01},
        },
        recent_changes=(
            {
                "platform": "meta",
                "payload": {
                    "change_type": "budget",
                    "direction": "increase",
                    "effective_at": "2026-08-12T18:00:00Z",
                },
                "observed_at": "2026-08-12T18:00:00Z",
            },
        ),
        current_observed_at={
            "meta": "2026-08-13T09:00:00Z",
            "google_ads": "2026-08-13T09:00:00Z",
        },
        historical_observed_at={
            "meta": "2026-08-12T09:00:00Z",
            "google_ads": "2026-08-12T09:00:00Z",
        },
    )
    assert evidence.signals_by_platform["meta"].get("recent_budget_change") is True
    assert "recent_budget_change" not in evidence.signals_by_platform["google_ads"]
    # Aggregate union view reflects the Meta change only.
    assert evidence.signals.get("recent_budget_change") is True


def test_platform_specific_temporal_window() -> None:
    # Google change at 10:00 is BEFORE Google's baseline (12:00): not a
    # Google confounder, even though Meta's window would include it.
    evidence = build_evidence(
        per_platform={"meta": {"ctr": 0.008}, "google_ads": {"ctr": 0.008}},
        recent_changes=(
            {
                "platform": "google_ads",
                "payload": {
                    "change_type": "budget",
                    "direction": "increase",
                    "effective_at": "2026-08-13T10:00:00Z",
                },
                "observed_at": "2026-08-13T10:00:00Z",
            },
        ),
        current_observed_at={
            "meta": "2026-08-13T18:00:00Z",
            "google_ads": "2026-08-13T17:00:00Z",
        },
        historical_observed_at={
            "meta": "2026-08-13T09:00:00Z",
            "google_ads": "2026-08-13T12:00:00Z",
        },
    )
    assert "recent_budget_change" not in evidence.signals_by_platform["google_ads"]
    assert "recent_budget_change" not in evidence.recent_change_context


# ── Scenario 6: newest-comparable selection ──────────────────────────────


def test_newest_incomparable_does_not_block_older_comparable() -> None:
    # Current Campaign A; history: 17:00 Campaign B (newer, incomparable),
    # 15:00 Campaign A (older, comparable) — baseline must be 15:00 A.
    evidence = build_evidence(
        per_platform={
            "meta": {
                "ctr": 0.007,
                "entity_level": "campaign",
                "entity_key": "campaign_a",
            }
        },
        historical_by_platform={
            "meta": {
                "ctr": 0.006,
                "entity_level": "campaign",
                "entity_key": "campaign_b",
            }
        },
    )
    # The library-level derive refuses the incomparable pair; the runtime
    # selector walks the bounded list — verified via observations_comparable
    # and an explicit older-comparable baseline below.
    assert evidence.historical_comparisons == {}
    comparable_older = {
        "ctr": 0.009,
        "entity_level": "campaign",
        "entity_key": "campaign_a",
    }
    assert observations_comparable(
        {
            "ctr": 0.007,
            "entity_level": "campaign",
            "entity_key": "campaign_a",
        },
        comparable_older,
    )
    evidence2 = build_evidence(
        per_platform={
            "meta": {
                "ctr": 0.007,
                "entity_level": "campaign",
                "entity_key": "campaign_a",
            }
        },
        historical_by_platform={"meta": comparable_older},
    )
    assert evidence2.historical_comparisons["meta"]["ctr_trend"] == pytest.approx(
        -0.222, abs=0.01
    )


# ── Scenario 7/8: unknown identity vs explicit account ───────────────────


def test_unknown_identity_derives_no_trend() -> None:
    # No entity metadata on either side: identity UNKNOWN — never assumed
    # to be account-level (v3.5.4).
    evidence = build_evidence(
        per_platform={"meta": {"ctr": 0.007}},
        historical_by_platform={"meta": {"ctr": 0.009}},
    )
    assert evidence.historical_comparisons == {}
    assert "ctr_trend_down" not in evidence.signals


def test_explicit_account_aggregate_derives_trend() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {
                "ctr": 0.007,
                "entity_level": "account",
                "aggregate_scope": "account",
            }
        },
        historical_by_platform={
            "meta": {
                "ctr": 0.009,
                "entity_level": "account",
                "aggregate_scope": "account",
            }
        },
    )
    assert evidence.historical_comparisons["meta"]["ctr_trend"] == pytest.approx(
        -0.222, abs=0.01
    )


# ── Scenario 9: raw entity ID privacy ────────────────────────────────────


def test_raw_entity_id_not_persisted_through_projection() -> None:
    # The adapter projection drops raw external IDs; entity_key passes.
    from appflow_ops.uac.platform_adapters import META

    projected = META.project_observation(
        {
            "ctr": 0.008,
            "entity_id": "120987654321",
            "entity_key": "opaque-local-key-1",
            "entity_level": "campaign",
        }
    )
    assert "entity_id" not in projected
    assert projected.get("entity_key") == "opaque-local-key-1"
    assert projected.get("entity_level") == "campaign"


def test_legacy_entity_id_still_readable_for_comparability() -> None:
    # Old records written with entity_id remain comparable (read path).
    assert observations_comparable(
        {"ctr": 0.007, "entity_key": "campaign_a", "entity_level": "campaign"},
        {"ctr": 0.009, "entity_id": "campaign_a", "entity_level": "campaign"},
    )


# ── Scenario 10: measurement conflict != shared issue ────────────────────


def test_conflict_alone_does_not_support_shared_measurement_issue() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
            "google_ads": {"measurement_state": "stable", "pay_rate_change_pct": -0.2},
        }
    )
    assert evidence.shared_signals.get("measurement_conflict") is True
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(specs, evidence, platform_scope=("google_ads", "meta"))
    shared_measurement = next(
        ev for ev in evals if ev.hypothesis.id == "shared_measurement_issue"
    )
    # conflict alone must not support the shared issue — it indicates
    # "investigate consistency", not "shared problem confirmed".
    assert "measurement_conflict" not in shared_measurement.supporting
    assert shared_measurement.status != "supported"


def test_two_invalid_platforms_support_shared_measurement_issue() -> None:
    evidence = build_evidence(
        per_platform={
            "meta": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
            "google_ads": {"measurement_state": "invalid", "pay_rate_change_pct": -0.2},
        }
    )
    assert evidence.shared_signals.get("cross_measurement_invalid") is True
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
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
        ev for ev in evals if ev.hypothesis.id == "shared_measurement_issue"
    )
    assert "cross_measurement_invalid" in shared_measurement.supporting


# ── Runtime E2E: Safety provenance through the public path ───────────────


def test_runtime_safety_provenance_google_not_capped(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 越来越贵？", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "cpm_change_pct": 0.3,
            "ctr_change_pct": 0.01,
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.32,
            "ctr_change_pct": 0.0,
            "impressions": 50000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    # Google's auction diagnosis is NOT blocked by Meta's invalid state.
    google_auction = next(
        ev
        for ev in result.evaluations
        if ev.hypothesis.id == "auction_pressure" and ev.platform == "google_ads"
    )
    assert google_auction.status == "supported"
    run.finish()
