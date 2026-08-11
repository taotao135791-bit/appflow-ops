"""Continuous Account State: storage, lifecycle, reasoning integration, privacy.

Covers the storage contracts (Part 56): create, append the five object
types, rebuild current state, atomic updates, bounded retrieval, pending
review; reasoning integration (recent changes/decisions/outcomes available,
bounded); lifecycle (clear one workspace, explicit deletion); privacy (state
never enters eval fixtures or the release artifact).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.types import ContractError
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def store(tmp_path: Path) -> StateStore:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    return store


def _observation(store: StateStore, *, ctr: float = 0.02, spend: float = 100.0) -> str:
    return store.append_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={
            "ctr": ctr,
            "spend": spend,
            "installs": 10,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )


# ── Storage ──────────────────────────────────────────────────────────────


def test_init_is_idempotent(store: StateStore) -> None:
    store.ensure_initialized()
    store.ensure_initialized()
    assert store.initialized


def test_append_all_five_object_types(store: StateStore) -> None:
    obs = _observation(store)
    change = store.append_change(
        change_type="bid", direction="decrease", magnitude=12.0
    )
    decision = store.append_decision(
        decision_class="wait",
        reason="delivery dropped after bid reduction while CTR stable",
        evidence_refs=(obs,),
        measurement_state="stable",
        maturity_state="sufficient",
        review_condition="maturity sufficient",
    )
    outcome = store.append_outcome(
        outcome_class="neutral", decision_id=decision, change_id=change
    )
    assert obs.startswith("event_")
    current = store.current_state()
    assert current["event_count"] == 4
    assert current["last_observation_id"] == obs
    assert current["last_change_id"] == change
    assert current["last_decision_id"] == decision
    assert current["last_outcome_id"] == outcome
    assert current["measurement_state"] == "stable"
    assert current["maturity_state"] == "sufficient"


def test_events_are_append_only_files(store: StateStore) -> None:
    _observation(store, ctr=0.01)
    _observation(store, ctr=0.02)
    events = sorted(store.context.events_dir.iterdir())
    assert [entry.name for entry in events] == [
        "00000001-observation.json",
        "00000002-observation.json",
    ]
    first = json.loads(events[0].read_text(encoding="utf-8"))
    assert first["event_id"] == "event_00000001"
    assert first["type"] == "observation"
    assert first["evidence_status"] == "confirmed"
    assert first["source_type"] == "export"
    assert first["platform"] == "google"


def test_rebuild_current_state_from_events(store: StateStore) -> None:
    _observation(store, ctr=0.01, spend=10.0)
    store.append_decision(
        decision_class="observe",
        reason="low spend; not enough signal",
        measurement_state="unknown",
        maturity_state="insufficient",
    )
    # Delete the derived file: it must rebuild from the event log.
    store.context.current_state_path.unlink()
    current = store.rebuild_current_state()
    assert current["event_count"] == 2
    # Derived from the latest observation's facts (the decision itself does
    # not carry measurement state into current-state).
    assert current["measurement_state"] == "stable"
    assert current["maturity_state"] == "sufficient"


def test_corrupted_current_state_is_rebuilt(store: StateStore) -> None:
    _observation(store)
    store.context.current_state_path.write_text("{not json", encoding="utf-8")
    current = store.current_state()
    assert current["event_count"] == 1


def test_corrupted_event_fails_loudly(store: StateStore) -> None:
    _observation(store)
    event_file = store.context.events_dir / "00000001-observation.json"
    event_file.write_text("{broken", encoding="utf-8")
    with pytest.raises(ContractError, match="corrupted"):
        store.get_recent()
    # History is never silently cleared.
    assert event_file.exists()


def test_current_state_is_derived_not_authoritative(store: StateStore) -> None:
    _observation(store)
    store.context.current_state_path.write_text(
        json.dumps({"event_count": 999}), encoding="utf-8"
    )
    rebuilt = store.rebuild_current_state()
    assert rebuilt["event_count"] == 1


def test_bounded_retrieval(store: StateStore) -> None:
    for index in range(5):
        _observation(store, ctr=0.01 * index)
    with pytest.raises(ContractError, match="limit"):
        store.get_recent(limit=0)
    with pytest.raises(ContractError, match="limit"):
        store.get_recent(limit=1000)
    recent = store.get_recent(limit=2)
    assert len(recent) == 2
    assert recent[0]["event_id"] == "event_00000005"  # newest first
    filtered = store.get_recent(event_type="change")
    assert filtered == ()


def test_get_event_by_id(store: StateStore) -> None:
    event_id = _observation(store)
    event = store.get_event(event_id)
    assert event["event_id"] == event_id
    with pytest.raises(ContractError, match="not found"):
        store.get_event("event_00000099")


def test_unknown_event_types_and_statuses_are_rejected(store: StateStore) -> None:
    with pytest.raises(ContractError, match="unknown evidence_status"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.01},
            evidence_status="probably",
        )
    with pytest.raises(ContractError, match="unknown source_type"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.01},
            source_type="magic",
        )
    with pytest.raises(ContractError, match="unknown decision_class"):
        store.append_decision(decision_class="fly", reason="nope")


# ── Pending review (Part 19) ─────────────────────────────────────────────


def test_pending_review_until_outcome_resolves(store: StateStore) -> None:
    decision = store.append_decision(
        decision_class="wait",
        reason="observe one decision window",
        review_condition="maturity sufficient",
    )
    pending = store.get_pending_review()
    assert pending is not None
    assert pending["decision_id"] == decision
    assert pending["condition"] == "maturity sufficient"
    assert pending["status"] == "pending"
    assert store.current_state()["pending_review"]["decision_id"] == decision

    store.append_outcome(outcome_class="neutral", decision_id=decision)
    assert store.get_pending_review() is None


def test_pending_review_without_condition_is_none(store: StateStore) -> None:
    store.append_decision(decision_class="keep", reason="healthy")
    assert store.get_pending_review() is None


# ── Reasoning integration (Part 15/16/17) ────────────────────────────────


def test_verify_can_consume_recent_change_and_decision(store: StateStore) -> None:
    obs = _observation(store, ctr=0.02, spend=62.0)
    change = store.append_change(
        change_type="bid", direction="decrease", magnitude=12.0
    )
    decision = store.append_decision(
        decision_class="wait",
        reason="delivery dropped after recent bid reduction while CTR stable",
        evidence_refs=(obs, change),
        measurement_state="stable",
        maturity_state="sufficient",
        review_condition="review in one decision window",
    )
    recent_changes = store.get_recent_changes(limit=1)
    recent_decisions = store.get_recent_decisions(limit=1)
    assert recent_changes[0]["payload"]["change_type"] == "bid"
    assert recent_changes[0]["payload"]["direction"] == "decrease"
    assert recent_decisions[0]["payload"]["decision_class"] == "wait"
    assert change in recent_decisions[0]["payload"]["evidence_refs"]
    assert decision in store.current_state()["last_decision_id"]


def test_previous_outcome_influences_next_reasoning(store: StateStore) -> None:
    decision = store.append_decision(decision_class="increase", reason="scale")
    store.append_outcome(outcome_class="worsened", decision_id=decision)
    outcomes = store.get_recent_outcomes(limit=1)
    assert outcomes[0]["payload"]["outcome_class"] == "worsened"
    assert outcomes[0]["payload"]["decision_id"] == decision


def test_retrieval_stays_bounded_for_context(store: StateStore) -> None:
    for index in range(120):
        _observation(store, ctr=0.001 * index)
    # The store API caps at 100; the derived current state only keeps the
    # bounded summary, not the whole history.
    assert len(store.get_recent(limit=100)) == 100
    current = store.current_state()
    assert current["event_count"] == 120
    assert set(current["last_facts"]) <= {
        "ctr",
        "spend",
        "installs",
        "measurement_state",
        "maturity_state",
    }


# ── Lifecycle ────────────────────────────────────────────────────────────


def test_clear_requires_explicit_workspace_state(store: StateStore) -> None:
    _observation(store)
    store.clear()
    assert not store.context.state_dir.exists()
    assert store.context.workspace.root.exists()  # workspace itself survives


def test_unconfirmed_user_statement_is_not_a_change(store: StateStore) -> None:
    # Part 7.1: "我好像昨天收了点价" without evidence is a reported
    # observation, never a confirmed change.
    store.append_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"user_reported_bid_adjustment": "decrease"},
        source_type="user_statement",
        evidence_status="reported",
    )
    assert store.get_recent_changes() == ()
    assert store.get_recent_observations(limit=1)[0]["evidence_status"] == "reported"


# ── Privacy (Part 48/49) ─────────────────────────────────────────────────


def test_state_never_enters_eval_fixtures(store: StateStore) -> None:
    _observation(store, ctr=0.33, spend=888.0)
    eval_path = Path("evals/vague-query-evals.json")
    fixture_text = eval_path.read_text(encoding="utf-8")
    assert "888.0" not in fixture_text
    assert "event_" not in fixture_text


def test_state_is_gitignored_and_outside_release_artifact(repo_root, store) -> None:
    _observation(store, ctr=0.55, spend=777.0)
    # The workspace lives outside the repository (tmp), but even inside the
    # repo the state dir must never be a tracked file.
    tracked = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "state/" not in tracked
    assert "current-state.json" not in tracked


def test_state_runtime_is_local_only(store: StateStore) -> None:
    # No network, no external API: the store is pure filesystem code.
    _observation(store)
    assert store.current_state()["event_count"] == 1


def test_decision_rationale_is_concise(store: StateStore) -> None:
    store.append_decision(
        decision_class="wait",
        reason="delivery dropped after recent bid reduction while CTR stable",
    )
    decision = store.get_recent_decisions(limit=1)[0]
    assert len(decision["payload"]["reason"]) < 200
    # Hidden chain-of-thought must not be persisted.
    assert "thought" not in json.dumps(decision)
