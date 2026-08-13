"""v3.5.0 Phase A (late-bound scope rebind) + runtime integration tests."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.runtime import (
    PlatformOperationalRun,
    build_hypothesis_set,
    converge,
    detect_operational_domain,
    evaluate_hypotheses,
    rank_hypotheses,
)
from appflow_ops.uac.workspace import initialize_workspace


def _workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _meta_metrics(**overrides):
    metrics = {
        "spend": 320.0,
        "ctr": 0.008,
        "installs": 40,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


# ── Phase A: late-bound scope rebinds historical state ───────────────────


def test_late_bound_scope_rebinds_historical_state(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    # History: Meta + TikTok events.
    meta_run = PlatformOperationalRun(workspace)
    meta_run.begin(request_text="Meta 这两天为什么越来越贵？")
    meta_run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-10T09:00:00Z"
    )
    meta_run.record_decision(decision_class="wait", reason="先观察")
    meta_run.finish()
    tiktok_run = PlatformOperationalRun(workspace)
    tiktok_run.begin(request_text="TT还是没量")
    tiktok_run.record_observation(
        _meta_metrics(spend=210.0, ctr=0.02),
        platform="tiktok",
        observed_at="2026-08-10T09:00:00Z",
    )
    tiktok_run.record_decision(decision_class="wait", reason="先观察")
    tiktok_run.finish()

    # Empty-scope run with state REQUIRED (vague follow-up).
    followup = PlatformOperationalRun(workspace)
    followup.begin(request_text="现在呢？")
    assert followup.platform_scope == ()
    assert followup.state_loaded
    # Pre-rebind snapshot may contain both platforms.
    context_before = followup.operational_context()
    assert "tiktok" in context_before.state_context["platforms"]

    # First observation binds Meta and MUST rebind history to Meta-only.
    followup.record_observation(
        _meta_metrics(ctr=0.006),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    assert followup.platform_scope == ("meta",)
    context = followup.operational_context()
    assert context.state_context is not None
    platforms = context.state_context["platforms"]
    assert platforms == ("meta",)  # TikTok history gone after rebind
    assert context.current_observation is not None
    assert context.current_observation["platform"] == "meta"
    followup.finish()


def test_rebind_keeps_meta_history_and_current_separate(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    meta_run = PlatformOperationalRun(workspace)
    meta_run.begin(request_text="Meta 这两天为什么越来越贵？")
    meta_run.record_observation(
        _meta_metrics(spend=300.0), platform="meta", observed_at="2026-08-10T09:00:00Z"
    )
    meta_run.finish()
    followup = PlatformOperationalRun(workspace)
    followup.begin(request_text="现在呢？")
    followup.record_observation(
        _meta_metrics(spend=320.0), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    context = followup.operational_context()
    # Historical snapshot contains yesterday's observation, not today's.
    historical = context.state_context["by_platform"]["meta"]["observations"]
    assert historical[0]["payload"]["facts"]["spend"] == 300.0
    # Current observation is today's evidence.
    assert context.current_observation["payload"]["facts"]["spend"] == 320.0
    followup.finish()


# ── Phase B: runtime + DI integration ────────────────────────────────────


def test_runtime_domain_hint_uses_full_domain_detector(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个素材是不是衰减了？")
    assert run.platform_scope == ("meta",)
    assert run.domain_hint == "creative"
    assert detect_operational_domain("Meta 这个素材是不是衰减了？") == "creative"
    run.finish()


def test_end_to_end_meta_fatigue_diagnosis(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 素材是不是衰减了？")
    run.record_observation(
        {
            "spend": 320.0,
            "ctr": 0.006,
            "cpm": 14.2,
            "ctr_trend": "down",
            "cpm_trend": "stable",
            "cvr_trend": "stable",
            "frequency_trend": "up",
            "old_creative_worse": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    context = run.operational_context()
    specs = build_hypothesis_set(
        platform_scope=run.platform_scope, domain=run.domain_hint
    )
    signals = {
        "ctr_trend_down": True,
        "cpm_trend_stable": True,
        "cvr_trend_stable": True,
        "frequency_trend_up": True,
        "old_creative_worse": True,
    }
    evals = evaluate_hypotheses(
        specs,
        signals,
        measurement_state=context.safety.measurement_state,
        maturity_state=context.safety.maturity_state,
    )
    ranked = rank_hypotheses(evals)
    assert ranked[0].evaluation.hypothesis.id == "creative_fatigue"
    result = converge(ranked)
    assert result.converged
    assert result.top_hypothesis == "creative_fatigue"
    assert result.decision in ("replace", "retest")
    run.finish()


def test_runtime_safety_feeds_di_convergence(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="现在呢？")
    run.record_observation(
        {
            "spend": 320.0,
            "ctr": 0.006,
            "ctr_trend": "down",
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    context = run.operational_context()
    specs = build_hypothesis_set(platform_scope=run.platform_scope)
    evals = evaluate_hypotheses(
        specs,
        {"ctr_trend_down": True},
        measurement_state=context.safety.measurement_state,
        maturity_state=context.safety.maturity_state,
    )
    result = converge(
        rank_hypotheses(evals),
        measurement_state=context.safety.measurement_state,
        maturity_state=context.safety.maturity_state,
    )
    assert result.decision == "investigate_measurement"
    assert result.converged is False
    run.finish()
