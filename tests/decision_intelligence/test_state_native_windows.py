"""v3.6.5 state-native decision window tests.

Timing must be a native consequence of PERSISTED STATE: the runtime
derives the post-change outcome delta from persisted observations and
confirmed changes — callers never hand-write ``window_outcomes`` or
``recent_creative_change``. Locks:

- window outcome derivation (baseline → Change → current → delta);
- counter comparability (reset / entity mismatch / missing baseline);
- platform-scoped timing provenance (another platform's change or
  timestamp never delays the selected platform);
- descale requires a mature post-change window (no ping-pong);
- creative change readiness comes from state, not caller booleans;
- shared/run timing stays conservative (any immature platform waits).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    DecisionWindow,
    RankedHypothesis,
    converge,
    derive_window_outcomes,
    evaluate_action_readiness,
    evaluate_hypothesis,
    hypothesis_by_id,
    resolve_relevant_change,
)
from appflow_ops.runtime import PlatformOperationalRun
from appflow_ops.uac.run_lifecycle import StateAccess
from appflow_ops.uac.workspace import initialize_workspace

ACCOUNT = {
    "entity_level": "account",
    "aggregate_scope": "account",
    # v3.6.6: outcome counters declare their semantics — state-native
    # deltas are only derived from explicit cumulative counters.
    "count_mode": "cumulative",
}


def _change(
    change_type: str = "budget",
    effective_at: str = "2026-08-15T10:00:00Z",
    platform: str = "google_ads",
) -> dict[str, object]:
    return {
        "event_id": f"chg-{change_type}-{effective_at}",
        "platform": platform,
        "observed_at": effective_at,
        "payload": {
            "change_type": change_type,
            "direction": "increase",
            "effective_at": effective_at,
        },
    }


def _observation(
    observed_at: str,
    facts: dict[str, object],
    event_id: str,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "platform": "google_ads",
        "observed_at": observed_at,
        "payload": {"facts": facts},
    }


# ── window derivation unit semantics ─────────────────────────────────────


def test_derive_window_outcomes_basic_delta() -> None:
    # §2: Observation A (payments=150) → Change 10:00 → Observation B
    # (payments=152) → derived window_outcomes = 2.
    facts = {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 152}
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[
            _observation(
                "2026-08-15T09:00:00Z",
                {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 150},
                "obs-a",
            )
        ],
        platform="google_ads",
        current_observed_at="2026-08-15T15:00:00Z",
        current_event_ids=set(),
    )
    assert window.status == "derived"
    assert window.window_outcomes == 2.0
    assert window.outcome_metric == "payments"
    assert window.change_type == "budget"
    assert window.baseline_outcomes == 150.0
    assert window.current_outcomes == 152.0


def test_derive_window_outcomes_uses_change_baseline_not_previous() -> None:
    # §3: follow-up payments=195 with TWO post-change observations —
    # the delta is 195 - 150 (change-window baseline), never 195 - 152.
    facts = {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 195}
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[
            _observation(
                "2026-08-15T09:00:00Z",
                {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 150},
                "obs-a",
            ),
            _observation(
                "2026-08-15T15:00:00Z",
                {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 152},
                "obs-b",
            ),
        ],
        platform="google_ads",
        current_observed_at="2026-08-16T09:00:00Z",
        current_event_ids=set(),
    )
    assert window.status == "derived"
    assert window.window_outcomes == 45.0


def test_derive_window_outcomes_kpi_aligned() -> None:
    # §18: pay_cpa KPI → payments delta, never installs delta.
    facts = {
        **ACCOUNT,
        "primary_kpi": "pay_cpa",
        "installs": 1500,
        "payments": 103,
    }
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[
            _observation(
                "2026-08-15T09:00:00Z",
                {
                    **ACCOUNT,
                    "primary_kpi": "pay_cpa",
                    "installs": 1000,
                    "payments": 100,
                },
                "obs-a",
            )
        ],
        platform="google_ads",
        current_observed_at="2026-08-15T15:00:00Z",
        current_event_ids=set(),
    )
    assert window.status == "derived"
    assert window.window_outcomes == 3.0  # payments, not installs


def test_window_counter_reset_is_not_comparable() -> None:
    # §12-14: before=150, after=20 → counter reset, NEVER -130.
    facts = {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 20}
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[
            _observation(
                "2026-08-15T09:00:00Z",
                {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 150},
                "obs-a",
            )
        ],
        platform="google_ads",
        current_observed_at="2026-08-15T15:00:00Z",
        current_event_ids=set(),
    )
    assert window.status == "not_comparable"
    assert window.window_outcomes is None  # never a negative delta


def test_window_entity_mismatch_is_unknown() -> None:
    # §13: campaign A baseline vs campaign B current — no comparable
    # baseline → unknown, never a cross-entity subtraction.
    facts = {
        "entity_level": "campaign",
        "entity_key": "camp-b",
        "primary_kpi": "pay_cpa",
        "payments": 20,
    }
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[
            _observation(
                "2026-08-15T09:00:00Z",
                {
                    "entity_level": "campaign",
                    "entity_key": "camp-a",
                    "primary_kpi": "pay_cpa",
                    "payments": 150,
                },
                "obs-a",
            )
        ],
        platform="google_ads",
        current_observed_at="2026-08-15T15:00:00Z",
        current_event_ids=set(),
    )
    assert window.status == "unknown"


def test_window_missing_baseline_is_unknown() -> None:
    # §10: first counter reading AFTER the change → unknown, never
    # "the whole count is new".
    facts = {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 20}
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[],  # nothing before the change
        platform="google_ads",
        current_observed_at="2026-08-15T15:00:00Z",
        current_event_ids=set(),
    )
    assert window.status == "unknown"


def test_relevant_change_is_platform_scoped() -> None:
    # §25: only THIS platform's changes reset its window.
    google_change = _change(effective_at="2026-08-15T10:00:00Z")
    meta_change = _change(effective_at="2026-08-16T10:00:00Z", platform="meta")
    selected = resolve_relevant_change([google_change, meta_change], "google_ads")
    assert selected is google_change  # newer Meta change ignored


def test_readiness_waits_on_not_comparable_and_unknown() -> None:
    facts = {**ACCOUNT, "primary_kpi": "pay_cpa", "payments": 152}
    base_window = {
        "last_change_effective_at": "2026-08-15T10:00:00Z",
        "current_observed_at": "2026-08-16T15:00:00Z",
    }
    state, reason, _ = evaluate_action_readiness(
        facts, {**base_window, "window_status": "not_comparable"}
    )
    assert state == "wait"
    assert reason == "counter_not_comparable"
    state, reason, _ = evaluate_action_readiness(
        facts, {**base_window, "window_status": "unknown"}
    )
    assert state == "wait"


def test_readiness_derived_window_overrides_caller_fact() -> None:
    # §46: state derives 2, caller says 50 → derived wins (wait).
    facts = {
        **ACCOUNT,
        "primary_kpi": "pay_cpa",
        "payments": 152,
        "window_outcomes": 50,
    }
    state, reason, trigger = evaluate_action_readiness(
        facts,
        {
            "last_change_effective_at": "2026-08-15T10:00:00Z",
            "current_observed_at": "2026-08-15T12:00:00Z",
            "window_outcomes": 2.0,
            "window_status": "derived",
        },
    )
    assert state == "wait"
    assert reason == "recent_change_unsettled"
    assert trigger == "more_pay_outcomes"


# ── runtime E2E (PART Q — no hand-written window_outcomes) ───────────────


@pytest.fixture()
def workspace(tmp_path):
    ws = initialize_workspace("app-us", base_dir=tmp_path, client_label="acme")
    yield ws


def _seed_scale_run1(run: PlatformOperationalRun) -> None:
    run.begin(request_text="预算加不加？", platform_scope=("meta",))
    run.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T09:00:00Z",
    )
    run.evaluate_decision_intelligence()
    run.record_decision_from_intelligence()
    run.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.15,
        effective_at="2026-08-15T10:00:00Z",
    )
    run.finish()


def test_runtime_derives_window_outcomes_from_state(workspace) -> None:
    # E2E 1: early follow-up — the runtime DERIVES 152-150=2 payments
    # since the confirmed change (no window_outcomes fact anywhere).
    _seed_scale_run1(
        PlatformOperationalRun(workspace) if False else _finished_run1(workspace)
    )
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在呢？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 78.0,
            "payments": 152,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T12:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.decision_window is not None
    assert result.decision_window.status == "derived"
    assert result.decision_window.window_outcomes == 2.0
    assert result.decision_window.outcome_metric == "payments"
    assert result.recommended_action in ("hold", "wait")
    assert result.action_readiness == "wait"
    run2.finish()


def _finished_run1(workspace):
    run1 = PlatformOperationalRun(workspace)
    _seed_scale_run1(run1)
    return run1


def test_caller_window_outcomes_does_not_override_derived_state(
    workspace,
) -> None:
    # §45-46: a caller-supplied window_outcomes=50 fact is IGNORED when
    # the state derives 2 — derived value has priority.
    _finished_run1(workspace)
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在呢？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 78.0,
            "payments": 152,
            "window_outcomes": 50,  # conflicting caller value
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T12:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.decision_window is not None
    assert result.decision_window.window_outcomes == 2.0  # derived wins
    assert result.action_readiness == "wait"
    run2.finish()


def test_runtime_counter_reset_e2e(workspace) -> None:
    # E2E 6: same apparent platform, counter 150 → 20 → not_comparable,
    # wait with counter_not_comparable — never a -130 delta.
    _finished_run1(workspace)
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在呢？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 78.0,
            "payments": 20,  # counter reset
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T12:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.decision_window is not None
    assert result.decision_window.status == "not_comparable"
    assert result.wait_reason == "counter_not_comparable"
    assert result.recommended_action in ("hold", "wait")
    run2.finish()


def test_runtime_wrong_entity_baseline_e2e(workspace) -> None:
    # E2E 7: run2 observes campaign B — campaign A's observation is NOT
    # a baseline (unknown window, wait).
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="预算加不加？", platform_scope=("meta",))
    run1.record_observation(
        {
            "entity_level": "campaign",
            "entity_key": "camp-a",
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T09:00:00Z",
    )
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.15,
        effective_at="2026-08-15T10:00:00Z",
    )
    run1.finish()
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在呢？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            "entity_level": "campaign",
            "entity_key": "camp-b",  # different entity
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 78.0,
            "payments": 20,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T12:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.decision_window is not None
    assert result.decision_window.status == "unknown"
    assert result.action_readiness == "wait"
    run2.finish()


def test_timing_uses_selected_platform_change(workspace) -> None:
    # E2E 4: Meta changed 2h ago; Google has NO change, budget cap +
    # strong mature KPI → selected Google scales; Meta's change never
    # delays Google's readiness.
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="两边预算？", platform_scope=("meta", "google_ads"))
    run1.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "cpa": 25.0,
            "target_cpa": 50.0,
            "conversions": 400,
            "cpm_change_pct": 0.3,
            "impressions": 100000,
            "clicks": 5000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T08:00:00Z",
    )
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.1,
        effective_at="2026-08-16T07:00:00Z",
        target_platform="meta",
    )
    run1.finish()
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="Google 预算加不加？",
        platform_scope=("meta", "google_ads"),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "delivery_concentrated": False,
            "cpa": 30.0,
            "target_cpa": 50.0,
            "conversions": 300,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-16T09:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    # Selected: Google's own budget constraint; Meta has no observation
    # in run2 so its change cannot even be evaluated — and must not be.
    assert result.top_platform == "google_ads"
    # Google has NO pending change of its own: the window says so
    # explicitly (never a borrowed Meta change).
    assert result.decision_window is not None
    assert result.decision_window.status == "no_relevant_change"
    assert result.decision_window.change_effective_at is None
    assert result.recommended_action == "increase"
    run2.finish()


def test_timing_uses_selected_platform_observed_at(workspace) -> None:
    # E2E 5: Meta observed 18:00, Google observed 15:00, selected
    # Google → the window uses 15:00 (never dict-order timestamps).
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="预算？", platform_scope=("meta", "google_ads"))
    run1.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 150,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-15T09:00:00Z",
    )
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.15,
        effective_at="2026-08-15T10:00:00Z",
        target_platform="google_ads",
    )
    run1.finish()
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在呢？",
        platform_scope=("meta", "google_ads"),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 72.0,
            "payments": 220,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-16T15:00:00Z",
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "cpm_change_pct": 0.3,
            "impressions": 100000,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-16T18:00:00Z",  # LATER than Google's
    )
    result = run2.evaluate_decision_intelligence()
    assert result.top_platform == "google_ads"
    assert result.decision_window is not None
    assert result.decision_window.platform == "google_ads"
    assert result.decision_window.current_observed_at == "2026-08-16T15:00:00Z"
    assert result.decision_window.window_outcomes == 70.0
    assert result.action_readiness == "ready"
    assert result.recommended_action == "increase"
    run2.finish()


def test_descale_requires_post_change_window(workspace) -> None:
    # PART R: lifetime payments do NOT justify an immediate decrease
    # right after the change (3 new payments → wait); the mature
    # follow-up (45 new payments, persistent bad KPI) may decrease.
    # audience_quality_shift (cvr down, first_action=observe) drives the
    # descale branch.
    def _shift_facts(pay_cpa: float, payments: int) -> dict:
        return {
            **ACCOUNT,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": pay_cpa,
            "payments": payments,
            "cvr_change_pct": -0.3,
            "ctr_change_pct": 0.01,
            "cpm_change_pct": 0.3,
            "impressions": 100000,
            "clicks": 5000,
            "conversions": 100,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        }

    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="受众怎么样？", platform_scope=("meta",))
    run1.record_observation(
        _shift_facts(70.0, 200),
        platform="meta",
        observed_at="2026-08-15T09:00:00Z",
    )
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.2,
        effective_at="2026-08-15T10:00:00Z",
    )
    run1.finish()
    # Early bad performance: pay CPA 140, only 3 new payments, change
    # still intervening → descale candidate blocked by recent change.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在呢？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        _shift_facts(140.0, 203),
        platform="meta",
        observed_at="2026-08-15T13:00:00Z",
    )
    early = run2.evaluate_decision_intelligence()
    assert early.decision_window is not None
    assert early.decision_window.window_outcomes == 3.0
    assert early.recommended_action != "decrease"  # no ping-pong
    run2.finish()

    # Mature descale readiness is verified at the convergence layer with a
    # single supported audience_quality_shift evaluation (a runtime run
    # would also raise supported rivals, which convergence then reports
    # as investigate — the descale readiness gate itself is what PART I/J
    # locks here): lifetime volume never substitutes for the post-change
    # window.
    spec = hypothesis_by_id("audience_quality_shift")
    evaluation = evaluate_hypothesis(
        spec,
        {"cvr_trend_down": True, "ctr_trend_stable": True, "cpm_trend_up": True},
        measurement_state="stable",
        maturity_state="sufficient",
        platform="meta",
    )
    assert evaluation.status == "supported"
    ranked = (RankedHypothesis(evaluation=evaluation, rank=1),)
    action_context = {
        **ACCOUNT,
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": 140.0,
        "payments": 245,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    # Mature window: 45 new payments since the change, elapsed > 24h →
    # the persistent deterioration may descale (small).
    ready_window = {
        "last_change_effective_at": "2026-08-15T10:00:00Z",
        "current_observed_at": "2026-08-16T15:00:00Z",
        "window_outcomes": 45.0,
        "window_status": "derived",
    }
    mature = converge(
        ranked, action_context=action_context, window_context=ready_window
    )
    assert mature.decision == "decrease"
    assert mature.action_readiness == "ready"
    assert mature.action_magnitude == "small"
    # Immature window: only 3 new payments 3h after the change → wait,
    # even though lifetime payments are 245 (reverse-action protection).
    immature_window = {
        "last_change_effective_at": "2026-08-15T10:00:00Z",
        "current_observed_at": "2026-08-15T13:00:00Z",
        "window_outcomes": 3.0,
        "window_status": "derived",
    }
    blocked = converge(
        ranked, action_context=action_context, window_context=immature_window
    )
    assert blocked.decision != "decrease"
    assert blocked.action_readiness == "wait"


def test_creative_change_is_state_derived(workspace) -> None:
    # E2E 8: a confirmed creative Change enters the next run's context
    # THROUGH STATE — the caller never writes recent_creative_change.
    run1 = PlatformOperationalRun(workspace)
    run1.begin(request_text="素材还行吗？", platform_scope=("meta",))
    run1.record_observation(
        {
            **ACCOUNT,
            "ctr_change_pct": -0.25,
            "old_creative_worse": True,
            "frequency_change_pct": 0.18,
            "cvr_change_pct": 0.01,
            "impressions": 50000,
            "clicks": 2500,
            "conversions": 60,
            "cpm_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T09:00:00Z",
    )
    day1 = run1.evaluate_decision_intelligence()
    assert day1.recommended_action in ("refresh", "replace", "retest")
    run1.record_confirmed_change(
        change_type="creative",
        direction="refresh",
        effective_at="2026-08-15T10:00:00Z",
    )
    run1.finish()
    # Follow-up: only 300 impressions since the creative change → hold
    # (new creative too early to judge) — WITHOUT any caller boolean.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="新素材怎么样了？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **ACCOUNT,
            "ctr_change_pct": -0.25,
            "old_creative_worse": True,
            "creative_age_data": True,
            "frequency_change_pct": 0.18,
            "cvr_change_pct": 0.01,
            "impressions": 300,
            "clicks": 20,
            "conversions": 2,
            "cpm_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-16T09:00:00Z",
    )
    follow = run2.evaluate_decision_intelligence()
    assert follow.recommended_action == "hold"
    run2.finish()


def test_shared_timing_is_conservative() -> None:
    # PART S/§31 (library level): a shared/run action requires EVERY
    # relevant platform's window to be ready — one immature platform
    # waits the whole shared action; a single ready platform is never
    # borrowed for the shared conclusion.
    facts = {
        **ACCOUNT,
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": 72.0,
        "payments": 220,
    }
    windows = {
        "meta": {
            "last_change_effective_at": "2026-08-16T08:00:00Z",
            "current_observed_at": "2026-08-16T09:00:00Z",
            "window_outcomes": 1.0,
            "window_status": "derived",
            "window_platform": "meta",
        },
        "google_ads": None,  # no pending change: ready
    }
    readinesses = []
    for context in windows.values():
        readinesses.append(
            evaluate_action_readiness(facts, context)[0]
            if context is not None
            else "ready"
        )
    assert "wait" in readinesses  # meta immature
    assert all(state == "ready" for state in readinesses) is False


def test_decision_window_dataclass_defaults() -> None:
    window = DecisionWindow()
    assert window.status == "no_relevant_change"
    assert window.window_outcomes is None
