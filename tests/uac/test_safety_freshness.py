"""v3.4.5 safety freshness semantics tests.

Covers: explicit current unknown overriding stale historical certainty
(absent ≠ unknown), cross-platform aggregation treating missing in-scope
platforms as unknown, platform=None + scope rejection, direct-path
policy/permission enum validation, and legacy compatibility.
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
)
from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_runtime import StateSession
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.types import ContractError
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _set_permission(workspace, capabilities: list[str]) -> None:
    document = yaml.safe_load(workspace.context_path.read_text(encoding="utf-8"))
    document["permissions"]["optimizer_can"] = capabilities
    workspace.context_path.write_text(yaml.safe_dump(document), encoding="utf-8")


def _facts(**overrides):
    facts = {"spend": 320.0, "ctr": 0.008, "installs": 40}
    facts.update(overrides)
    return facts


def _decision_count(workspace) -> int:
    store = StateStore(RunContext.from_workspace(workspace))
    return store.status()["events_by_type"].get("decision", 0)


# ── Scenario 1: current unknown beats historical stable ──────────────────


def test_current_unknown_overrides_historical_stable(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    # Yesterday: Meta measurement stable, maturity sufficient.
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _facts(measurement_state="stable", maturity_state="sufficient"),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    run.finish()
    # Today: same Meta, explicit measurement=unknown, maturity absent.
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _facts(measurement_state="unknown"),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    decision_id = run.record_decision(decision_class="observe", reason="继续观察")
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    # Explicit current unknown is evidence: it must NOT fall back to
    # yesterday's stable; absent maturity may use history.
    assert decision["payload"]["measurement_state"] == "unknown"
    assert decision["payload"]["maturity_state"] == "sufficient"


# ── Scenario 2: absent still uses history ────────────────────────────────


def test_absent_current_field_falls_back_to_history(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _facts(measurement_state="stable", maturity_state="sufficient"),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    run.finish()
    # Today: CTR/CPM only — measurement_state absent → history may be used.
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _facts(),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    decision_id = run.record_decision(decision_class="observe", reason="继续观察")
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["payload"]["measurement_state"] == "stable"
    assert decision["payload"]["maturity_state"] == "sufficient"


# ── Scenario 3: cross-platform missing → unknown ─────────────────────────


def test_cross_platform_missing_platform_aggregates_unknown(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    # Meta: stable. Google: observation with NO measurement_state at all.
    run.record_observation(
        _facts(measurement_state="stable", maturity_state="sufficient"),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    run.record_observation(
        _facts(spend=900.0),
        platform="google_ads",
        observed_at="2026-08-12T09:00:00Z",
    )
    # The runtime must use aggregate=unknown — NOT "fully stable" — even
    # though the diagnosis itself is allowed at unknown confidence.
    decision_id = run.record_decision(
        decision_class="investigate",
        reason="可能是产品支付问题",
        diagnosis_confidence="confirmed",
    )
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    # Google missing → unknown → aggregate unknown, persisted as such.
    assert decision["payload"]["measurement_state"] == "unknown"
    assert decision["payload"]["maturity_state"] == "unknown"


def test_cross_platform_stable_plus_missing_measurement_unknown(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        _facts(measurement_state="stable"),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    # Google has no measurement_state anywhere (history empty too).
    measurement_by_platform, _ = run._safety_states()
    assert measurement_by_platform.get("meta") == "stable"
    assert "google_ads" not in measurement_by_platform
    aggregate = PlatformOperationalRun._aggregate_safety(
        measurement_by_platform, ("google_ads", "meta")
    )
    assert aggregate == "unknown"  # stable + missing → unknown
    run.finish()


def test_cross_platform_aggregation_matrix(workspace) -> None:
    aggregate = PlatformOperationalRun._aggregate_safety
    assert aggregate({"meta": "stable"}, ("meta",)) == "stable"
    # stable + missing → unknown
    assert aggregate({"meta": "stable"}, ("google_ads", "meta")) == "unknown"
    # stable + unknown → unknown
    assert (
        aggregate({"meta": "stable", "google_ads": "unknown"}, ("google_ads", "meta"))
        == "unknown"
    )
    # stable + invalid → invalid
    assert (
        aggregate({"meta": "stable", "google_ads": "invalid"}, ("google_ads", "meta"))
        == "invalid"
    )
    # sufficient + missing → unknown
    assert aggregate({"meta": "sufficient"}, ("google_ads", "meta")) == "unknown"
    # sufficient + insufficient → insufficient
    assert (
        aggregate(
            {"meta": "sufficient", "google_ads": "insufficient"},
            ("google_ads", "meta"),
        )
        == "insufficient"
    )
    # empty scope → unknown
    assert aggregate({}, ()) == "unknown"


def test_meta_explicit_unknown_in_cross_platform_aggregate(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        _facts(measurement_state="stable"),
        platform="google_ads",
        observed_at="2026-08-12T09:00:00Z",
    )
    run.record_observation(
        _facts(measurement_state="unknown"),  # explicit unknown
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    measurement_by_platform, _ = run._safety_states()
    # explicit unknown is kept as current evidence, not dropped
    assert measurement_by_platform["meta"] == "unknown"
    aggregate = PlatformOperationalRun._aggregate_safety(
        measurement_by_platform, ("google_ads", "meta")
    )
    assert aggregate == "unknown"  # not stable
    run.finish()


# ── Scenario 4: cross-platform invalid ───────────────────────────────────


def test_cross_platform_invalid_beats_unknown(workspace) -> None:
    aggregate = PlatformOperationalRun._aggregate_safety
    assert (
        aggregate({"google_ads": "unknown", "meta": "invalid"}, ("google_ads", "meta"))
        == "invalid"
    )


# ── Scenario 5: platform=None + scope rejected ───────────────────────────


def test_store_rejects_none_platform_with_scope(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    with pytest.raises(ContractError, match="cannot carry a platform_scope"):
        store.append_decision(
            decision_class="investigate",
            reason="查漏斗",
            measurement_state="stable",
            maturity_state="sufficient",
            confidence="medium",
            origin="agent_constrained",
            platform=None,
            platform_scope=("google_ads", "meta"),
        )
    with pytest.raises(ContractError, match="cannot carry a platform_scope"):
        store.append_outcome(
            outcome_class="neutral",
            platform=None,
            platform_scope=("google_ads", "meta"),
        )


def test_legacy_unscoped_events_still_readable(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    legacy_id = store.append_decision(
        decision_class="wait",
        reason="继续观察",
        measurement_state="unknown",
        maturity_state="unknown",
        confidence="low",
        origin="agent_constrained",
        # platform None + scope empty: legacy shape, still allowed
    )
    assert store.get_event(legacy_id)["platform"] is None
    assert store.rebuild_current_state()["event_count"] == 1


# ── Scenario 6: direct-path policy/permission validation ─────────────────


def test_direct_path_rejects_malformed_policy_state(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    with pytest.raises(ContractError, match="unknown policy_state"):
        session.record_decision(
            decision_class="decrease",
            reason="降预算",
            measurement_state="stable",
            maturity_state="sufficient",
            confidence="medium",
            origin="agent_constrained",
            policy_constraints={"policy_state": "forbid_numeric "},
        )


def test_direct_path_rejects_malformed_permission_state(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    with pytest.raises(ContractError, match="unknown permission_state"):
        session.record_decision(
            decision_class="decrease",
            reason="降预算",
            measurement_state="stable",
            maturity_state="sufficient",
            confidence="medium",
            origin="agent_constrained",
            policy_constraints={"permission_state": "full_acess"},
        )


def test_direct_path_accepts_canonical_states_and_extra_metadata(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="decrease",
        reason="降预算",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        policy_constraints={
            "policy_state": "cap_20pct",
            "permission_state": "recommend_only",
            "max_budget_change_pct": 0.2,  # unrelated metadata still allowed
        },
    )
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    event = store.get_event(decision_id)
    assert event["payload"]["policy_constraints"]["policy_state"] == "cap_20pct"


def test_runtime_record_decision_unaffected(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？", policy_state="cap_20pct")
    run.record_observation(
        _facts(measurement_state="stable", maturity_state="sufficient"),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    # cap_20pct + decrease (numeric) → constrained, not persisted.
    decision_id = run.record_decision(decision_class="decrease", reason="降预算 5%")
    assert decision_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.outcome == "constrained"
    run.finish()
    assert _decision_count(workspace) == 0
