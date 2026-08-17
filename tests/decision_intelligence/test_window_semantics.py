"""v3.6.6 window semantics & entity attribution tests.

Every derived decision window must be SEMANTICALLY VALID before its
duration is calibrated:

- A number is not automatically a cumulative counter (count_mode:
  cumulative / interval / unknown); only explicit cumulative counters
  are subtractable, interval values never are, missing semantics are
  unknown.
- A change belongs to an ENTITY, not only a platform: a Campaign A
  budget change never resets Campaign B's window, and reverse-action
  protection never crosses entity boundaries.
- Relevant change types depend on the ACTION FAMILY: a creative change
  resets the creative test window, never the budget scale window.
- Timestamps compare as parsed timezone-aware instants, never ISO
  strings.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    change_matches_entity,
    derive_window_outcomes,
    normalize_count_mode,
    parse_event_time,
    relevant_change_types,
    resolve_relevant_change,
)
from appflow_ops.runtime import PlatformOperationalRun
from appflow_ops.uac.run_lifecycle import StateAccess
from appflow_ops.uac.workspace import initialize_workspace

ACCOUNT = {
    "entity_level": "account",
    "aggregate_scope": "account",
    "count_mode": "cumulative",
}


def _campaign(key: str) -> dict:
    return {"entity_level": "campaign", "entity_key": key, "count_mode": "cumulative"}


def _obs(
    event_id: str,
    observed_at: str,
    facts: dict,
    platform: str = "meta",
) -> dict:
    return {
        "event_id": event_id,
        "platform": platform,
        "observed_at": observed_at,
        "payload": {"facts": facts},
    }


def _change(
    platform: str = "meta",
    change_type: str = "budget",
    effective_at: str = "2026-08-15T10:00:00Z",
    entity: dict | None = None,
    event_id: str = "chg",
) -> dict:
    payload = {
        "change_type": change_type,
        "direction": "increase",
        "effective_at": effective_at,
    }
    if entity:
        payload.update(entity)
    return {
        "event_id": event_id,
        "platform": platform,
        "observed_at": effective_at,
        "payload": payload,
    }


def _pay_facts(payments: int, pay_cpa: float = 70.0, **extra) -> dict:
    base = {
        **ACCOUNT,
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": pay_cpa,
        "payments": payments,
    }
    base.update(extra)
    return base


# ── Count semantics ───────────────────────────────────────────────────


def test_cumulative_counter_derives_delta() -> None:
    # Case 1: baseline 100 → current 130, cumulative → delta 30.
    window = derive_window_outcomes(
        facts=_pay_facts(130),
        changes=[_change()],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "derived"
    assert window.window_outcomes == 30.0


def test_interval_counts_are_not_subtracted() -> None:
    # Case 2: Day1 20 → Day2 25 are INDEPENDENT intervals; 25-20=5 has
    # no business meaning. No subtraction, window stays unknown.
    interval = {"count_mode": "interval"}
    window = derive_window_outcomes(
        facts={**_pay_facts(25), **interval},
        changes=[_change()],
        observations=[
            _obs("o1", "2026-08-15T09:00:00Z", {**_pay_facts(20), **interval})
        ],
        platform="meta",
        current_observed_at="2026-08-16T09:00:00Z",
    )
    assert window.status == "unknown"
    assert window.reason == "interval"
    assert window.window_outcomes is None


def test_missing_count_mode_is_unknown() -> None:
    # Case 3: 100 → 130 but no declared semantics → unknown, never 30.
    no_mode = {
        "entity_level": "account",
        "aggregate_scope": "account",
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": 70.0,
    }
    window = derive_window_outcomes(
        facts={**no_mode, "payments": 130},
        changes=[_change()],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", {**no_mode, "payments": 100})],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "unknown"
    assert window.reason == "unknown_count_semantics"
    assert window.window_outcomes is None


def test_counter_reset_is_not_comparable() -> None:
    # Case 4: 150 → 20 cumulative → counter_reset, never -130.
    window = derive_window_outcomes(
        facts=_pay_facts(20),
        changes=[_change()],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(150))],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "not_comparable"
    assert window.reason == "counter_reset"
    assert window.window_outcomes is None


def test_count_mode_mismatch_is_not_comparable() -> None:
    # §12: baseline cumulative, current interval → not_comparable.
    window = derive_window_outcomes(
        facts={**_pay_facts(130), "count_mode": "interval"},
        changes=[_change()],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "not_comparable"
    assert window.reason == "count_mode_mismatch"


def test_per_metric_count_mode_overrides_generic() -> None:
    # §49-50: payments_count_mode wins over a generic count_mode.
    facts = {
        **_pay_facts(130),
        "count_mode": "interval",
        "payments_count_mode": "cumulative",
    }
    baseline = {
        **_pay_facts(100),
        "count_mode": "interval",
        "payments_count_mode": "cumulative",
    }
    window = derive_window_outcomes(
        facts=facts,
        changes=[_change()],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", baseline)],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "derived"
    assert window.window_outcomes == 30.0
    assert normalize_count_mode(facts, "payments") == "cumulative"
    assert normalize_count_mode({"count_mode": "interval"}, "payments") == "interval"
    assert normalize_count_mode({}, "payments") == "unknown"


# ── Entity attribution ────────────────────────────────────────────────


def test_change_entity_does_not_cross_campaigns() -> None:
    # Case 5/6: Campaign A changed, Campaign B selected. A's change must
    # NOT reset B, and A-change + B-baseline must never form B's window
    # even when B has a valid pre-change baseline.
    changes = [_change(entity=_campaign("A"), event_id="chg-a")]
    observations = [
        _obs(
            "b1",
            "2026-08-15T09:00:00Z",
            {
                **_campaign("B"),
                "primary_kpi": "pay_cpa",
                "target_pay_cpa": 100.0,
                "pay_cpa": 70.0,
                "payments": 200,
            },
        ),
    ]
    current = {
        **_campaign("B"),
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": 70.0,
        "payments": 240,
    }
    window = derive_window_outcomes(
        facts=current,
        changes=changes,
        observations=observations,
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "no_relevant_change"
    assert window.window_outcomes is None  # no fake cross-entity window


def test_change_entity_matching_uses_selected_entity() -> None:
    # §19-20: exact match first — a change on the SELECTED campaign is
    # relevant; change_matches_entity distinguishes match / no_match.
    change_a = _change(entity=_campaign("A"), event_id="chg-a")
    change_b = _change(
        entity=_campaign("B"), event_id="chg-b", effective_at="2026-08-15T11:00:00Z"
    )
    selected = resolve_relevant_change(
        [change_a, change_b], "meta", current_facts=_campaign("B")
    )
    assert selected is change_b  # B's own change, not A's
    assert change_matches_entity(change_a["payload"], _campaign("B")) == "no_match"
    assert change_matches_entity(change_b["payload"], _campaign("B")) == "match"


def test_legacy_change_without_entity_is_conservative() -> None:
    # §22: a legacy platform-only change is fine for an account-level
    # selection (backward compatible) but never silently adopted by a
    # campaign-level selection.
    legacy = _change(event_id="legacy")  # no entity fields
    account_window = derive_window_outcomes(
        facts=_pay_facts(130),
        changes=[legacy],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert account_window.status == "derived"  # account compat preserved
    campaign_window = derive_window_outcomes(
        facts={
            **_campaign("B"),
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 130,
        },
        changes=[legacy],
        observations=[
            _obs(
                "o1",
                "2026-08-15T09:00:00Z",
                {
                    **_campaign("B"),
                    "primary_kpi": "pay_cpa",
                    "target_pay_cpa": 100.0,
                    "pay_cpa": 70.0,
                    "payments": 100,
                },
            )
        ],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert campaign_window.status == "unknown"
    assert campaign_window.reason == "legacy_change_scope_unknown"


# ── Action-family-specific resets ─────────────────────────────────────


def test_relevant_change_types_by_action_family() -> None:
    # §30-32: budget/bid/restart gate scale/descale; creative/restart
    # gate creative; a creative change is NOT a scale/descale reset.
    assert relevant_change_types("scale") == ("budget", "bid", "campaign_restart")
    assert relevant_change_types("descale") == ("budget", "bid", "campaign_restart")
    assert relevant_change_types("creative") == ("creative", "campaign_restart")
    assert "creative" not in relevant_change_types("scale")


def test_creative_change_does_not_reset_scale_window() -> None:
    # Case 7: budget stable 48h, creative refreshed 2h ago → the scale
    # window is NOT reset by the creative change alone.
    changes = [
        _change(
            change_type="creative", effective_at="2026-08-17T08:00:00Z", event_id="cr"
        )
    ]
    window = derive_window_outcomes(
        facts=_pay_facts(130),
        changes=changes,
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
        platform="meta",
        action_family="scale",
        current_observed_at="2026-08-17T10:00:00Z",
    )
    assert window.status == "no_relevant_change"


def test_creative_change_resets_creative_window() -> None:
    # Case 8: the SAME creative change DOES reset the creative window.
    changes = [
        _change(
            change_type="creative", effective_at="2026-08-17T08:00:00Z", event_id="cr"
        )
    ]
    window = derive_window_outcomes(
        facts=_pay_facts(130),
        changes=changes,
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
        platform="meta",
        action_family="creative",
        current_observed_at="2026-08-17T10:00:00Z",
    )
    assert window.change_type == "creative"
    assert window.change_effective_at == "2026-08-17T08:00:00Z"


def test_campaign_restart_resets_both_families() -> None:
    # Case 9: campaign restart resets scale AND creative windows.
    changes = [
        _change(
            change_type="campaign_restart",
            effective_at="2026-08-17T08:00:00Z",
            event_id="rs",
        )
    ]
    for family in ("scale", "creative", "descale"):
        window = derive_window_outcomes(
            facts=_pay_facts(130),
            changes=changes,
            observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
            platform="meta",
            action_family=family,
            current_observed_at="2026-08-17T10:00:00Z",
        )
        assert window.change_type == "campaign_restart", family


def test_reverse_action_protection_is_entity_scoped() -> None:
    # Case 11 / PART K: Campaign A recently scaled, Campaign B mature
    # bad. B must NOT be held back by A's reverse-action protection —
    # A's change is simply not B's window anchor.
    changes = [
        _change(
            entity=_campaign("A"), event_id="chg-a", effective_at="2026-08-16T09:00:00Z"
        )
    ]
    b_baseline = {
        **_campaign("B"),
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": 70.0,
        "payments": 200,
    }
    b_current = {
        **_campaign("B"),
        "primary_kpi": "pay_cpa",
        "target_pay_cpa": 100.0,
        "pay_cpa": 140.0,
        "payments": 245,
    }
    # A's own window IS derived (its change + its counters)...
    a_window = derive_window_outcomes(
        facts={
            **_campaign("A"),
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 130,
        },
        changes=changes,
        observations=[
            _obs(
                "a1",
                "2026-08-16T08:00:00Z",
                {
                    **_campaign("A"),
                    "primary_kpi": "pay_cpa",
                    "target_pay_cpa": 100.0,
                    "pay_cpa": 70.0,
                    "payments": 100,
                },
            )
        ],
        platform="meta",
        current_observed_at="2026-08-16T11:00:00Z",
    )
    assert a_window.status == "derived"
    # ...but B sees no relevant change of its own: A's recent scale never
    # puts B inside a reverse-action protection window.
    b_window = derive_window_outcomes(
        facts=b_current,
        changes=changes,
        observations=[_obs("b1", "2026-08-16T08:00:00Z", b_baseline)],
        platform="meta",
        current_observed_at="2026-08-17T15:00:00Z",
    )
    assert b_window.status == "no_relevant_change"
    assert b_window.window_outcomes is None


# ── Timestamp canonicalization ────────────────────────────────────────


def test_window_timestamps_compare_as_instants() -> None:
    # Case 12 / §46: mixed offsets must order by REAL instant.
    # baseline 10:00+08:00 (=02:00Z) < change 03:00Z < current 12:00+09:00
    # (=03:00Z). Lexical ordering would place "+08:00" wrong.
    assert parse_event_time("2026-08-17T10:00:00+08:00") < parse_event_time(
        "2026-08-17T03:00:00Z"
    )
    window = derive_window_outcomes(
        facts=_pay_facts(130),
        changes=[_change(effective_at="2026-08-17T03:00:00Z", event_id="c")],
        observations=[_obs("o1", "2026-08-17T10:00:00+08:00", _pay_facts(100))],
        platform="meta",
        current_observed_at="2026-08-17T12:00:00+09:00",
    )
    assert window.status == "derived"
    assert window.window_outcomes == 30.0


def test_invalid_timestamp_is_conservative() -> None:
    window = derive_window_outcomes(
        facts=_pay_facts(130),
        changes=[_change(effective_at="not-a-timestamp", event_id="c")],
        observations=[_obs("o1", "2026-08-15T09:00:00Z", _pay_facts(100))],
        platform="meta",
        current_observed_at="2026-08-15T15:00:00Z",
    )
    assert window.status == "unknown"
    assert window.reason == "invalid_timestamp"


# ── Runtime-native E2E ────────────────────────────────────────────────


@pytest.fixture()
def workspace(tmp_path):
    ws = initialize_workspace("app-us", base_dir=tmp_path, client_label="acme")
    yield ws


def test_runtime_interval_counts_wait(workspace) -> None:
    # Interval daily counts must not be subtracted at the runtime level.
    run1 = PlatformOperationalRun(workspace)
    run1.begin(
        request_text="预算加不加？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run1.record_observation(
        {
            "entity_level": "account",
            "aggregate_scope": "account",
            "count_mode": "interval",
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 20,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T09:00:00Z",
    )
    run1.evaluate_decision_intelligence()
    run1.record_decision_from_intelligence()
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
            "entity_level": "account",
            "aggregate_scope": "account",
            "count_mode": "interval",
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 78.0,
            "payments": 25,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-16T09:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.decision_window is not None
    assert result.decision_window.status == "unknown"
    assert result.decision_window.reason == "interval"
    assert result.recommended_action in ("hold", "wait")
    run2.finish()


def test_runtime_campaign_change_isolation(workspace) -> None:
    # Case 5 runtime: a confirmed Campaign A budget change must not gate
    # the selected Campaign B (no fake cross-entity window).
    run1 = PlatformOperationalRun(workspace)
    run1.begin(
        request_text="Campaign A 预算？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run1.record_observation(
        {
            **_campaign("A"),
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 70.0,
            "payments": 100,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T09:00:00Z",
    )
    run1.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=0.2,
        effective_at="2026-08-15T10:00:00Z",
        entity_level="campaign",
        entity_key="A",
    )
    run1.finish()
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="Campaign B 现在呢？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        {
            **_campaign("B"),
            "budget_utilization_high": True,
            "spend_hit_cap": True,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": 30.0,
            "payments": 240,
            "conversions": 300,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-15T12:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    # Campaign A's change is NOT B's window anchor: B sees no relevant
    # change of its own, so A's recent scale cannot hold B back.
    assert result.decision_window is not None
    assert result.decision_window.status == "no_relevant_change"
    run2.finish()


def test_runtime_mature_descale_happens_through_runtime(workspace) -> None:
    # PART J / Case 10: full State → Runtime → Decision(decrease). No
    # hand-written window_outcomes; the runtime derives 245-200=45 and a
    # genuinely rival-free mature deterioration converges to a small
    # decrease. Three persisted observations are required: a pre-change
    # baseline (the window anchor), a post-change settled reading (which
    # takes the change out of the "recent/intervening" set), and the
    # current mature bad reading.
    def _descale_facts(pay_cpa, payments, cvr, ctr, cpm, clicks):
        return {
            **ACCOUNT,
            "primary_kpi": "pay_cpa",
            "target_pay_cpa": 100.0,
            "pay_cpa": pay_cpa,
            "payments": payments,
            "cvr_change_pct": cvr,
            "ctr_change_pct": ctr,
            "cpm_change_pct": cpm,
            "impressions": 100000,
            "clicks": clicks,
            "conversions": 100,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        }

    run1 = PlatformOperationalRun(workspace)
    run1.begin(
        request_text="预算加不加？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run1.record_observation(
        _descale_facts(70.0, 200, 0.01, 0.01, 0.01, 5000),
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
    # Post-change settled reading: takes the change out of the recent
    # window so the later deterioration is judged on its own merits.
    run_mid = PlatformOperationalRun(workspace)
    run_mid.begin(
        request_text="怎么样？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run_mid.record_observation(
        _descale_facts(75.0, 210, 0.01, 0.01, 0.01, 5200),
        platform="meta",
        observed_at="2026-08-16T09:00:00Z",
    )
    run_mid.finish()
    # Mature bad follow-up: 245 payments (45 new since the pre-change
    # baseline), Pay CPA 140, a persistent cvr deterioration, stable
    # measurement, mature sample, no intervening change.
    run2 = PlatformOperationalRun(workspace)
    run2.begin(
        request_text="现在要不要收？",
        platform_scope=("meta",),
        state_access=StateAccess.REQUIRED,
    )
    run2.record_observation(
        _descale_facts(140.0, 245, -0.3, 0.2, 0.3, 7000),
        platform="meta",
        observed_at="2026-08-17T15:00:00Z",
    )
    result = run2.evaluate_decision_intelligence()
    assert result.decision_window is not None
    assert result.decision_window.status == "derived"
    assert result.decision_window.window_outcomes == 45.0
    assert result.action_readiness == "ready"
    assert result.recommended_action == "decrease"
    assert result.action_magnitude == "small"
    run2.finish()
