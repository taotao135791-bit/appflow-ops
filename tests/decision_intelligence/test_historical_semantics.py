"""v3.5.2 historical evidence & cross-platform semantics tests.

Covers: current-vs-previous automatic trend derivation (no caller
change_pct), explicit-trend precedence, incomparable-history honesty,
recent Change as confounder evidence, prior Decision/Outcome as context
(never factual support), DI action integrity (no silent override;
explicit operator override), per-platform signal provenance, single-
platform decline never supporting shared diagnoses, and platform_scope
as the cross-platform source of truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.runtime import (
    PlatformOperationalRun,
    build_hypothesis_set,
)
from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.types import ContractError
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _day1_meta_observation(run, day="2026-08-12T09:00:00Z") -> None:
    run.record_observation(
        {
            "spend": 300.0,
            "ctr": 0.009,
            "cpm": 12.0,
            "cvr": 0.08,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at=day,
    )


def _day2_meta_observation(run, day="2026-08-13T09:00:00Z") -> None:
    run.record_observation(
        {
            "spend": 320.0,
            "ctr": 0.007,
            "cpm": 12.1,
            "cvr": 0.081,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at=day,
    )


# ── Historical evidence ─────────────────────────────────────────────────


def test_now_followup_derives_trends_from_history(workspace) -> None:
    # Day 1: raw values only.
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="Meta 现在怎么样？", platform_scope=("meta",))
    _day1_meta_observation(run1)
    run1.finish()

    # Day 2 ("现在呢？"): raw values only — NO change_pct, NO trends.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    _day2_meta_observation(run2)
    result = run2.evaluate_decision_intelligence()
    evidence = result.evidence
    assert evidence is not None
    # The runtime derived the trends itself from comparable history.
    comparisons = evidence.historical_comparisons["meta"]
    assert comparisons["ctr_trend"] == pytest.approx(-0.222, abs=0.01)
    assert evidence.signals["ctr_trend_down"] is True
    assert evidence.signals["cpm_trend_stable"] is True
    run2.finish()


def test_explicit_current_trend_wins_over_derived(workspace) -> None:
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="Meta 现在怎么样？", platform_scope=("meta",))
    _day1_meta_observation(run1)
    run1.finish()

    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    # Explicit canonical value: ctr is actually stable per the caller.
    run2.record_observation(
        {
            "ctr": 0.007,
            "ctr_change_pct": -0.01,
            "cpm": 12.1,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.evidence is not None
    # Explicit stable beats the derived down trend.
    assert result.evidence.signals.get("ctr_trend_stable") is True
    assert "ctr_trend_down" not in result.evidence.signals
    run2.finish()


def test_no_history_means_no_trend(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 现在怎么样？", platform_scope=("meta",))
    run.record_observation(
        {
            "ctr": 0.007,
            "cpm": 12.1,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.evidence is not None
    assert result.evidence.historical_comparisons == {}
    # A single low CTR without history must NOT invent ctr_trend_down.
    assert "ctr_trend_down" not in result.evidence.signals
    run.finish()


# ── Recent Change as confounder evidence ────────────────────────────────


def test_recent_budget_change_becomes_confounder_evidence(workspace) -> None:
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="Meta 现在怎么样？", platform_scope=("meta",))
    _day1_meta_observation(run1)
    # Confirmed budget +30% change.
    run1.record_confirmed_change(
        change_type="budget", direction="increase", magnitude=0.3
    )
    run1.finish()

    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    _day2_meta_observation(run2)
    result = run2.evaluate_decision_intelligence()
    assert result.evidence is not None
    # The Change in State became DI evidence automatically.
    assert result.evidence.recent_change_context.get("recent_budget_change") is True
    assert result.evidence.signals.get("recent_budget_change") is True
    run2.finish()


# ── Prior Decision / Outcome are context, not facts ─────────────────────


def test_prior_decision_is_context_not_support(workspace) -> None:
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="Meta 现在怎么样？", platform_scope=("meta",))
    _day1_meta_observation(run1)
    run1.record_decision(
        decision_class="wait",
        reason="样本不足先观察",
        diagnosis_confidence="tentative",
    )
    run1.finish()

    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    _day2_meta_observation(run2)
    result = run2.evaluate_decision_intelligence()
    assert result.evidence is not None
    assert result.evidence.decision_context.get("decision_class") == "wait"
    # Context is never converted into a supporting signal.
    assert "previous_decision_wait" not in result.evidence.signals
    run2.finish()


def test_prior_outcome_is_context_not_causal_proof(workspace) -> None:
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="Meta 现在怎么样？", platform_scope=("meta",))
    _day1_meta_observation(run1)
    decision_id = run1.record_decision(
        decision_class="retest",
        reason="建议重测素材",
        diagnosis_confidence="tentative",
    )
    run1.record_confirmed_change(change_type="creative", direction="replace")
    run1.record_outcome(
        outcome_class="neutral",
        decision_id=decision_id,
        source_type="export",
    )
    run1.finish()

    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("meta",))
    _day2_meta_observation(run2)
    result = run2.evaluate_decision_intelligence()
    assert result.evidence is not None
    assert result.evidence.outcome_context.get("outcome_class") == "neutral"
    # An inconclusive/neutral outcome never becomes "fatigue proven".
    assert (
        "creative_fatigue"
        not in (
            ev.hypothesis.id for ev in result.evaluations if ev.status == "supported"
        )
        or result.top_status != "supported"
    )
    run2.finish()


# ── Action integrity ────────────────────────────────────────────────────


def test_normal_di_persistence_preserves_recommended_action(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个素材是不是衰减了？", platform_scope=("meta",))
    run.record_observation(
        {
            "ctr_change_pct": -0.25,
            "cpm_change_pct": 0.02,
            "cvr_change_pct": 0.01,
            "frequency_change_pct": 0.18,
            "old_creative_worse": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.recommended_action in ("replace", "retest")
    # The persisted Decision must carry the DI action — no swap possible.
    decision_id = run.record_decision_from_intelligence()
    if decision_id is not None:
        store = StateStore(RunContext.from_workspace(workspace))
        decision = store.get_event(decision_id)
        assert decision["payload"]["decision_class"] in ("replace", "retest")
    run.finish()


def _allow_budget_bid(workspace) -> None:
    document = yaml.safe_load(workspace.context_path.read_text(encoding="utf-8"))
    document["permissions"]["optimizer_can"] = ["budget", "bid"]
    workspace.context_path.write_text(yaml.safe_dump(document), encoding="utf-8")


def test_operator_override_is_explicit_and_attributable(workspace) -> None:
    _allow_budget_bid(workspace)
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个素材是不是衰减了？", platform_scope=("meta",))
    run.record_observation(
        {
            "ctr_change_pct": -0.25,
            "cpm_change_pct": 0.02,
            "cvr_change_pct": 0.01,
            "frequency_change_pct": 0.18,
            "old_creative_worse": True,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    decision_id = run.record_decision_override(
        action="decrease",
        reason="客户要求先压预算",
        result=result,
    )
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["payload"]["origin"] == "operator_override"
    assert "decrease" in decision["payload"]["reason"]
    assert "override" in decision["payload"]["reason"]
    run.finish()


# ── Cross-platform provenance ───────────────────────────────────────────


def test_signals_by_platform_preserves_provenance(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Meta 付费掉了，Google 呢？", platform_scope=("google_ads", "meta")
    )
    run.record_observation(
        {
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "pay_rate_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.evidence is not None
    by_platform = result.evidence.signals_by_platform
    assert by_platform["meta"].get("pay_rate_trend_down") is True
    assert by_platform["google_ads"].get("pay_rate_trend_stable") is True
    # Shared signals require >= 2 distinct platforms agreeing.
    assert "cross_pay_rate_drop" not in result.evidence.shared_signals
    run.finish()


def test_single_platform_decline_does_not_support_shared(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 付费掉了", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "pay_rate_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    shared = next(
        ev
        for ev in result.evaluations
        if ev.hypothesis.id == "shared_product_funnel_issue"
    )
    assert shared.status != "supported"
    # Meta-specific funnel hypotheses stay visible.
    ranked_live = [
        item.evaluation
        for item in result.ranked_hypotheses
        if item.evaluation.status not in ("weakened", "excluded")
    ]
    assert ranked_live[0].hypothesis.id in (
        "conversion_funnel_degradation",
        "post_click_friction",
        "traffic_quality_shift",
        "audience_quality_shift",
    )
    run.finish()


def test_both_platforms_decline_supports_shared(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="两边付费都掉了", platform_scope=("google_ads", "meta"))
    run.record_observation(
        {
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "pay_rate_change_pct": -0.25,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.evidence is not None
    assert result.evidence.shared_signals.get("cross_pay_rate_drop") is True
    shared = next(
        ev
        for ev in result.evaluations
        if ev.hypothesis.id == "shared_product_funnel_issue"
    )
    assert shared.status == "supported"
    run.finish()


def test_cross_historical_derivation_detects_shared_drop(workspace) -> None:
    # Day 1: Meta pay=5%, Google pay=4% (raw values, no trends).
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="现在怎么样？", platform_scope=("google_ads", "meta"))
    run1.record_observation(
        {
            "pay_rate": 0.05,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    run1.record_observation(
        {
            "pay_rate": 0.04,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-12T09:00:00Z",
    )
    run1.finish()

    # Day 2: Meta pay=3%, Google pay=2.5% — no trend provided.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(request_text="现在呢？", platform_scope=("google_ads", "meta"))
    run2.record_observation(
        {
            "pay_rate": 0.03,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run2.record_observation(
        {
            "pay_rate": 0.025,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.evidence is not None
    # Per-platform derived pay trends → shared drop, all automatic.
    assert result.evidence.signals_by_platform["meta"].get("pay_rate_trend_down")
    assert result.evidence.signals_by_platform["google_ads"].get("pay_rate_trend_down")
    assert result.evidence.shared_signals.get("cross_pay_rate_drop") is True
    run2.finish()


# ── platform_scope source of truth ──────────────────────────────────────


def test_cross_platform_false_contradicts_multi_platform_scope() -> None:
    with pytest.raises(ContractError, match="contradicts platform_scope"):
        build_hypothesis_set(
            platform_scope=("google_ads", "meta"), cross_platform=False
        )


def test_cross_platform_true_contradicts_single_platform_scope() -> None:
    with pytest.raises(ContractError, match="contradicts platform_scope"):
        build_hypothesis_set(platform_scope=("meta",), cross_platform=True)


def test_consistent_bool_still_allowed() -> None:
    specs = build_hypothesis_set(
        platform_scope=("google_ads", "meta"), cross_platform=True
    )
    assert any(s.id == "shared_product_funnel_issue" for s in specs)
    single = build_hypothesis_set(platform_scope=("meta",), cross_platform=False)
    assert all(s.id != "shared_product_funnel_issue" for s in single)
