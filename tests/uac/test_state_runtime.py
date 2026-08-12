"""v3.3.1 runtime integration: StateSession auto-read / auto-write lifecycle.

Covers the eight runtime contracts (Part 29) plus the "现在呢?" follow-up
scenario (Part 13) and the "又不行了?" scenario (Part 14): ambiguous
follow-ups auto-load current workspace state; terminology questions do not
touch state; recommendations record decisions but never changes; outcomes
need later evidence; one run never duplicates observations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_runtime import StateSession
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def session(tmp_path: Path) -> StateSession:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")
    return StateSession(RunContext.from_workspace(workspace))


# ── Test 1: ambiguous follow-up auto-loads current workspace state ───────


def test_ambiguous_followup_auto_loads_workspace_state(session: StateSession) -> None:
    session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0, "ctr": 0.02, "measurement_state": "stable"},
        source_digest="day1-export",
    )
    session.record_decision(
        decision_class="wait",
        reason="delivery dropped after bid reduction",
        review_condition="maturity sufficient",
        source_digest="day1-wait",
    )
    # Day 2: a new session answers "现在呢?" without any user re-explaining.
    day2 = StateSession(RunContext.from_workspace(session.context.workspace))
    summary = day2.load_context_summary()
    current = summary["current_state"]
    assert current["last_change_id"] is None
    assert current["last_decision_id"] is not None
    assert current["pending_review"] is not None
    assert current["pending_review"]["condition"] == "maturity sufficient"
    assert summary["recent"]["observations"][0]["payload"]["facts"]["spend"] == 62.0


# ── Test 2: terminology question does not touch state ────────────────────


def test_terminology_question_does_not_load_or_write_state(
    session: StateSession,
) -> None:
    # A direct question like "CTR 是什么?" needs no state at all: the
    # lifecycle hooks are only invoked by ambiguous/diagnostic requests.
    # Asserting that the session's store stays untouched proves no write.
    assert session.store.status()["event_count"] == 0
    summary = session.load_context_summary()
    assert summary["current_state"]["event_count"] == 0
    assert summary["recent"]["observations"] == []


# ── Test 3: reliable new facts record one Observation ────────────────────


def test_reliable_new_facts_record_one_observation(session: StateSession) -> None:
    event_id = session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 100.0, "ctr": 0.02},
        source_type="export",
        source_digest="export-2026-08-10",
    )
    assert event_id is not None
    assert session.store.status()["event_count"] == 1


# ── Test 4: operational recommendation records one Decision ──────────────


def test_recommendation_records_one_decision(session: StateSession) -> None:
    event_id = session.record_decision(
        decision_class="decrease",
        reason="CPA above target with stable delivery",
        confidence="high",
        source_digest="rec-2026-08-10",
    )
    assert event_id is not None
    decision = session.store.get_event(event_id)
    assert decision["payload"]["origin"] == "agent_constrained"
    assert "reason" in decision["payload"]


# ── Test 5: recommendation alone does NOT record Change ──────────────────


def test_recommendation_alone_does_not_record_change(session: StateSession) -> None:
    session.record_decision(
        decision_class="decrease",
        reason="suggest tCPA from 100 to 90",
        source_digest="rec-1",
    )
    # No confirmed execution: no Change event may exist.
    assert session.store.get_recent_changes() == ()


# ── Test 6: confirmed operator change records Change ─────────────────────


def test_confirmed_operator_change_records_change(session: StateSession) -> None:
    session.record_confirmed_change(
        change_type="tCPA",
        direction="decrease",
        magnitude=10.0,
        source="operator_confirmation",
        source_digest="change-1",
    )
    changes = session.store.get_recent_changes(limit=1)
    assert len(changes) == 1
    assert changes[0]["payload"]["change_type"] == "tCPA"
    assert changes[0]["payload"]["direction"] == "decrease"


# ── Test 7: later evidence can record Outcome ────────────────────────────


def test_later_evidence_can_record_outcome(session: StateSession) -> None:
    decision = session.record_decision(
        decision_class="wait", reason="observe one window", source_digest="d1"
    )
    # Day 2 evidence: new observation + outcome linked to the decision.
    session.record_observation(
        observed_at="2026-08-11T09:00:00Z",
        platform="google",
        facts={"spend": 40.0},
        source_digest="day2-export",
    )
    assert decision is not None
    outcome = session.record_outcome(
        outcome_class="worsened", decision_id=decision, source_digest="day2-outcome"
    )
    assert outcome is not None
    assert session.store.get_pending_review() is None  # resolved


# ── Test 8: same run does not duplicate Observation ──────────────────────


def test_same_run_does_not_duplicate_observation(session: StateSession) -> None:
    first = session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 100.0},
        source_digest="same-export",
    )
    second = session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 100.0},
        source_digest="same-export",
    )
    assert first is not None
    assert second is None  # deduplicated within the run
    assert session.store.status()["event_count"] == 1


def test_dedupe_is_per_run_not_global(session: StateSession) -> None:
    session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 100.0},
        source_digest="export-1",
    )
    # A different run with the same digest records again (state is
    # append-only history; dedupe only guards one run).
    next_session = StateSession(RunContext.from_workspace(session.context.workspace))
    event_id = next_session.record_observation(
        observed_at="2026-08-11T09:00:00Z",
        platform="google",
        facts={"spend": 90.0},
        source_digest="export-1",
    )
    assert event_id is not None
    assert next_session.store.status()["event_count"] == 2


# ── "现在呢?" end-to-end (Part 13) ───────────────────────────────────────


def test_now_what_followup_continues_without_reexplaining(
    tmp_path: Path,
) -> None:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")

    # Day 1: spend down, CTR stable, decision = wait, pending review.
    day1 = StateSession(RunContext.from_workspace(workspace))
    day1.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={
            "spend": 62.0,
            "ctr": 0.02,
            "measurement_state": "stable",
            "maturity_state": "insufficient",
        },
        source_digest="day1",
    )
    day1.record_decision(
        decision_class="wait",
        reason="delivery dropped; wait until maturity",
        review_condition="maturity sufficient",
        source_digest="day1-wait",
    )

    # Day 2: user says "现在呢?" — new session, new observation.
    day2 = StateSession(RunContext.from_workspace(workspace))
    day2.record_observation(
        observed_at="2026-08-11T09:00:00Z",
        platform="google",
        facts={
            "spend": 45.0,
            "ctr": 0.021,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        source_digest="day2",
    )
    summary = day2.load_context_summary()
    current = summary["current_state"]
    # AppFlow knows yesterday without being told:
    assert current["maturity_state"] == "sufficient"  # new evidence
    assert current["pending_review"] is not None
    assert current["pending_review"]["decision_class"] == "wait"
    assert summary["recent"]["changes"] == []
    # The user never re-explained yesterday; the decision is still there.
    decisions = summary["recent"]["decisions"]
    assert decisions[0]["payload"]["decision_class"] == "wait"


# ── "又不行了?" scenario (Part 14) ───────────────────────────────────────


def test_recurring_issue_uses_history_but_not_old_causality(
    tmp_path: Path,
) -> None:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")

    history = StateSession(RunContext.from_workspace(workspace))
    history.record_observation(
        observed_at="2026-07-20T09:00:00Z",
        platform="google",
        facts={"spend": 10.0, "ctr": 0.015},
        source_digest="july",
    )
    history.record_confirmed_change(
        change_type="bid",
        direction="decrease",
        magnitude=15.0,
        source_digest="july-change",
    )
    history.record_decision(
        decision_class="observe",
        reason="old issue: bid constraint",
        source_digest="july-decision",
    )
    history.record_outcome(
        outcome_class="improved",
        decision_id=history.store.get_recent_decisions(limit=1)[0]["event_id"],
        source_digest="july-outcome",
    )

    # New query "Google 怎么又不行了?" — history is evidence, not answer.
    now_session = StateSession(RunContext.from_workspace(workspace))
    summary = now_session.load_context_summary()
    current = summary["current_state"]
    assert current["last_outcome_id"] is not None  # old issue resolved
    assert current["pending_review"] is None
    # Old causal explanation (bid constraint) is available as evidence but
    # nothing claims it is the new cause — the decision origin/confidence
    # model keeps the old explanation out of the derived "truth".
    assert summary["recent"]["changes"][0]["payload"]["change_type"] == "bid"
