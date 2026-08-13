"""v3.5.1 raw evidence bridge & semantic tests.

Layer 1-2 coverage: raw metrics → signals (numeric change_pct thresholds,
stable-as-evidence, missing-stays-missing), signal registry consistency
(no declared-but-unreachable trend signal), cross-platform hypothesis
auto-detection (platform_scope is the source of truth; no ALL_HYPOTHESES
fallback for multi-platform scopes), and supported-rival convergence.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    SIGNAL_IDS,
    build_hypothesis_set,
    converge,
    evaluate_hypotheses,
    rank_hypotheses,
    signals_from_metrics,
)

# ── Layer 1: raw metrics → signals ──────────────────────────────────────


def test_change_pct_generates_trend_signals() -> None:
    metrics = {
        "ctr_change_pct": -0.25,
        "cpm_change_pct": 0.02,
        "frequency_change_pct": 0.18,
        "cvr_change_pct": 0.01,
    }
    signals = signals_from_metrics(metrics)
    assert signals["ctr_trend_down"] is True
    assert signals["cpm_trend_stable"] is True
    assert signals["frequency_trend_up"] is True
    assert signals["cvr_trend_stable"] is True


def test_pay_and_registration_stable_signals_reachable() -> None:
    # The v3.5.0 gap: hypotheses could require these but the bridge could
    # never produce them. Both string-trend and numeric-change paths work.
    assert signals_from_metrics({"pay_rate_trend": "stable"}) == {
        "pay_rate_trend_stable": True
    }
    assert signals_from_metrics({"pay_rate_change_pct": 0.01}) == {
        "pay_rate_trend_stable": True
    }
    assert signals_from_metrics({"registration_rate_trend": "stable"}) == {
        "registration_rate_trend_stable": True
    }
    assert signals_from_metrics({"registration_rate_change_pct": -0.03}) == {
        "registration_rate_trend_stable": True
    }


def test_ambiguous_change_pct_generates_nothing() -> None:
    # -0.07 is inside neither the stable band nor the material threshold:
    # no signal is invented.
    assert signals_from_metrics({"ctr_change_pct": -0.07}) == {}


def test_missing_window_stays_missing() -> None:
    # No comparison window → no cpm signal at all (stable is never guessed
    # from a single current value).
    assert signals_from_metrics({"cpm": 15.0}) == {}


def test_stable_is_evidence_not_missing() -> None:
    signals = signals_from_metrics({"cpm_trend": "stable"})
    assert "cpm_trend_stable" in signals
    assert "cpm_trend_up" not in signals


def test_metric_existence_is_not_hypothesis_support() -> None:
    # A bare CPM value never supports auction_pressure; only a material
    # rise does.
    signals = signals_from_metrics({"cpm": 15.0})
    assert "cpm_trend_up" not in signals


# ── Signal registry consistency ──────────────────────────────────────────


def test_every_trend_signal_is_reachable() -> None:
    """SIGNAL_IDS vs extraction outputs: every *_trend_* signal must have
    a production path (string trend key or numeric change_pct)."""
    for signal_id in SIGNAL_IDS:
        if (
            not signal_id.endswith("_trend_down")
            and not signal_id.endswith("_trend_stable")
            and not signal_id.endswith("_trend_up")
        ):
            continue
        # Simulate the owning key with the signal's direction value.
        base = signal_id.rsplit("_", 2)[0]  # e.g. ctr_trend_down -> ctr
        trend_key = f"{base}_trend"
        direction = signal_id.rsplit("_", 1)[-1]
        extracted = signals_from_metrics({trend_key: direction})
        assert signal_id in extracted, (
            f"{signal_id} is declared but unreachable through {trend_key}"
        )


def test_extraction_outputs_are_declared() -> None:
    """Every signal the bridge can produce must exist in SIGNAL_IDS."""
    probe = {
        "ctr_trend": "down",
        "cpm_trend": "up",
        "cvr_trend": "stable",
        "frequency_trend": "stable",
        "click_volume_trend": "down",
        "install_rate_trend": "down",
        "registration_rate_trend": "down",
        "pay_rate_trend": "down",
        "old_creative_worse": True,
        "no_recent_change": True,
        "measurement_state": "invalid",
        "maturity_state": "insufficient",
    }
    signals = signals_from_metrics(probe)
    for signal_id in signals:
        assert signal_id in SIGNAL_IDS, f"undeclared signal {signal_id}"


# ── Cross-platform hypothesis construction ──────────────────────────────


def test_multi_platform_scope_auto_enables_cross_platform() -> None:
    # No explicit bool: scope itself is the source of truth.
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    ids = {s.id for s in specs}
    assert "shared_product_funnel_issue" in ids
    assert "shared_measurement_issue" in ids


def test_meta_google_scope_excludes_tiktok_only_hypotheses() -> None:
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    ids = {s.id for s in specs}
    assert "click_to_install_friction" not in ids  # TikTok-only
    assert "hook_or_click_quality" not in ids  # TikTok-only
    # Shared hypotheses (applicable to at least one in-scope platform).
    assert "creative_fatigue" in ids
    assert "auction_pressure" in ids
    assert len(specs) < len(build_hypothesis_set(platform_scope=()))


def test_meta_tiktok_scope_keeps_shared_and_cross() -> None:
    specs = build_hypothesis_set(platform_scope=("meta", "tiktok"))
    ids = {s.id for s in specs}
    assert "click_to_install_friction" in ids
    assert "creative_fatigue" in ids
    assert "shared_product_funnel_issue" in ids
    assert "budget_constraint" in ids


def test_explicit_bool_backward_compatible() -> None:
    # Explicit cross_platform=True still works (compat), but scope wins.
    auto = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    explicit = build_hypothesis_set(
        platform_scope=("google_ads", "meta"), cross_platform=True
    )
    assert {s.id for s in auto} == {s.id for s in explicit}
    single = build_hypothesis_set(platform_scope=("meta",), cross_platform=False)
    assert "shared_product_funnel_issue" not in {s.id for s in single}


def test_applicable_platforms_really_filters_single_platform() -> None:
    meta_ids = {s.id for s in build_hypothesis_set(platform_scope=("meta",))}
    assert "pay_funnel_degradation" not in meta_ids  # TikTok funnel
    assert "creative_fatigue" in meta_ids


# ── Supported-rival convergence ──────────────────────────────────────────


def test_supported_rival_blocks_confident_convergence() -> None:
    # Strong evidence for fatigue (CTR↓ + old worse + freq↑), auction
    # (CPM↑ + multi-creative), and saturation (freq↑ + reach slowing +
    # concentrated) SIMULTANEOUSLY — three material supported rivals.
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {
        "ctr_trend_down": True,
        "old_creative_worse": True,
        "frequency_trend_up": True,
        "cpm_trend_up": True,
        "multi_creative_impacted": True,
        "reach_growth_slowing": True,
        "delivery_concentrated": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    ranked = rank_hypotheses(evals)
    supported = [
        item.evaluation.hypothesis.id
        for item in ranked
        if item.evaluation.status == "supported"
    ]
    assert {"creative_fatigue", "auction_pressure", "audience_saturation"} <= set(
        supported
    ), supported
    result = converge(ranked)
    assert result.converged is False
    assert result.decision == "investigate"
    assert len(result.material_alternatives) >= 2
    assert result.next_discriminating_evidence, "must name discriminating evidence"


def test_weakened_runner_up_allows_convergence() -> None:
    # Fatigue supported; auction weakened by stable CPM.
    specs = build_hypothesis_set(platform_scope=("meta",))
    signals = {
        "ctr_trend_down": True,
        "cpm_trend_stable": True,
        "cvr_trend_stable": True,
        "frequency_trend_up": True,
        "old_creative_worse": True,
    }
    evals = evaluate_hypotheses(specs, signals)
    ranked = rank_hypotheses(evals)
    top = ranked[0].evaluation
    assert top.hypothesis.id == "creative_fatigue"
    result = converge(ranked)
    assert result.converged is True
    assert result.decision in ("replace", "retest")


def test_insufficient_evidence_returns_wait() -> None:
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(specs, {"ctr_trend_down": True})
    ranked = rank_hypotheses(evals)
    result = converge(ranked)
    assert result.converged is False
    assert result.decision in ("wait", "investigate")
