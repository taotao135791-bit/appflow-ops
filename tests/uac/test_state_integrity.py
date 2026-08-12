"""v3.3.1 state integrity: concurrency, workspace identity, references,
time semantics, full-log derivation, freshness, and migration."""

from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.account_state import RunContext, new_run_id
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
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
    )


# ── Concurrency (Part 1/28) ──────────────────────────────────────────────


def test_100_concurrent_writes_produce_unique_sequences(store: StateStore) -> None:
    writer_count = 100
    results: list[str] = [""] * writer_count
    errors: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            results[index] = _observation(store, ctr=0.001 * index)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(index,)) for index in range(writer_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], errors[:3]
    event_ids = [event_id for event_id in results if event_id]
    assert len(event_ids) == writer_count
    assert len(set(event_ids)) == writer_count  # no duplicates, no overwrite
    current = store.rebuild_current_state()
    assert current["event_count"] == writer_count  # no missing events


def test_stale_or_missing_current_state_rebuilds(store: StateStore) -> None:
    # Crash window: event written but derived file deleted. Reading must
    # rebuild from the full log instead of treating the file as truth.
    _observation(store)
    store.context.current_state_path.unlink()
    current = store.current_state()
    assert current["event_count"] == 1
    assert current["derived_through_sequence"] == 1


def test_workspace_a_b_concurrent_writes_stay_isolated(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("app-us", base_dir=base, client_label="client-a")
    workspace_b = initialize_workspace(
        "product-x", base_dir=base, client_label="client-b"
    )
    store_a = StateStore(RunContext.from_workspace(workspace_a))
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    store_a.ensure_initialized()
    store_b.ensure_initialized()
    errors: list[BaseException] = []

    def writer_a(index: int) -> None:
        try:
            _observation(store_a, ctr=0.001 * index)
        except BaseException as exc:
            errors.append(exc)

    def writer_b(index: int) -> None:
        try:
            store_b.append_observation(
                observed_at="2026-08-10T09:00:00Z",
                platform="meta",
                facts={"ctr": 0.002 * index},
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        *(threading.Thread(target=writer_a, args=(index,)) for index in range(25)),
        *(threading.Thread(target=writer_b, args=(index,)) for index in range(25)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], errors[:3]
    assert store_a.status()["event_count"] == 25
    assert store_b.status()["event_count"] == 25
    # No data mixed: A's current state carries no B facts.
    assert store_a.current_state()["last_facts"].get("ctr", 0) < 0.03


# ── Workspace identity (Part 2) ──────────────────────────────────────────


def test_copied_foreign_state_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("app-us", base_dir=base, client_label="client-a")
    workspace_b = initialize_workspace(
        "product-x", base_dir=base, client_label="client-b"
    )
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    store_b.ensure_initialized()
    _observation(store_b, ctr=0.99, spend=999.0)

    # Copy B's state tree into A.
    shutil.copytree(store_b.context.state_dir, workspace_a.root / "state")
    store_a = StateStore(RunContext.from_workspace(workspace_a))
    with pytest.raises(ContractError, match="belongs to a different workspace"):
        store_a.ensure_initialized()


def test_workspace_move_keeps_identity(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")
    context = RunContext.from_workspace(workspace)
    store = StateStore(context)
    store.ensure_initialized()
    _observation(store)

    # Moving the workspace directory is a legal operation; identity comes
    # from metadata, not the absolute path.
    moved = tmp_path / "moved"
    shutil.move(str(workspace.root), str(moved))
    moved_workspace = workspace.__class__.at(moved)
    moved_store = StateStore(RunContext.from_workspace(moved_workspace))
    moved_store.ensure_initialized()
    assert moved_store.current_state()["event_count"] == 1


def test_legacy_fingerprint_state_migrates_when_match(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")
    context = RunContext.from_workspace(workspace)
    store = StateStore(context)
    store.ensure_initialized()
    _observation(store)

    # Rewrite schema as legacy v3.3.0 (fingerprint only, no workspace_id).
    import hashlib

    legacy = {
        "schema_version": 1,
        "workspace_fingerprint": hashlib.sha256(
            str(workspace.root).encode("utf-8")
        ).hexdigest()[:16],
    }
    context.schema_path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = StateStore(RunContext.from_workspace(workspace))
    migrated.ensure_initialized()  # must bind, not fail
    schema = json.loads(context.schema_path.read_text(encoding="utf-8"))
    assert schema["workspace_id"] == context.workspace_id
    assert migrated.current_state()["event_count"] == 1


def test_legacy_fingerprint_mismatch_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace = initialize_workspace("app-us", base_dir=base, client_label="acme")
    context = RunContext.from_workspace(workspace)
    store = StateStore(context)
    store.ensure_initialized()
    _observation(store)

    legacy = {"schema_version": 1, "workspace_fingerprint": "deadbeefdeadbeef"}
    context.schema_path.write_text(json.dumps(legacy), encoding="utf-8")

    rejected = StateStore(RunContext.from_workspace(workspace))
    with pytest.raises(ContractError, match="fingerprint does not match"):
        rejected.ensure_initialized()


# ── Reference integrity (Part 4) ─────────────────────────────────────────


def test_decision_ref_must_exist_and_be_observation_or_change(
    store: StateStore,
) -> None:
    with pytest.raises(ContractError, match="not found"):
        store.append_decision(
            decision_class="wait", reason="x", evidence_refs=("event_00000099",)
        )
    outcome_id = store.append_outcome(outcome_class="neutral")
    with pytest.raises(ContractError, match="expected observation or change"):
        store.append_decision(
            decision_class="wait", reason="x", evidence_refs=(outcome_id,)
        )


def test_outcome_refs_are_type_checked_per_field(store: StateStore) -> None:
    obs = _observation(store)
    with pytest.raises(ContractError, match="expected decision"):
        store.append_outcome(outcome_class="neutral", decision_id=obs)
    change = store.append_change(change_type="bid", direction="decrease")
    with pytest.raises(ContractError, match="expected change"):
        store.append_outcome(outcome_class="neutral", change_id=obs)
    with pytest.raises(ContractError, match="expected observation"):
        store.append_outcome(outcome_class="neutral", observation_ids=(change,))


def test_reference_resolves_only_inside_current_workspace(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("app-us", base_dir=base, client_label="client-a")
    workspace_b = initialize_workspace(
        "product-x", base_dir=base, client_label="client-b"
    )
    store_a = StateStore(RunContext.from_workspace(workspace_a))
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    store_a.ensure_initialized()
    store_b.ensure_initialized()
    event_b = _observation(store_b, ctr=0.88)
    # The same event id string does not exist in A.
    with pytest.raises(ContractError, match="not found"):
        store_a.append_decision(
            decision_class="wait", reason="x", evidence_refs=(event_b,)
        )


# ── Time semantics (Part 3) ──────────────────────────────────────────────


def test_observed_at_lives_only_in_envelope(store: StateStore) -> None:
    store.append_observation(
        observed_at="2026-08-09T00:00:00Z",
        platform="google",
        facts={"spend": 10.0},
    )
    event = store.get_recent_observations(limit=1)[0]
    assert event["observed_at"] == "2026-08-09T00:00:00Z"
    assert "observed_at" not in event["payload"]


def test_out_of_order_observed_at_uses_log_order_for_derivation(
    store: StateStore,
) -> None:
    # Yesterday's report imported today, then a correction: the later write
    # is the latest business knowledge even if its observed_at is earlier.
    store.append_observation(
        observed_at="2026-08-09T00:00:00Z",
        platform="google",
        facts={"measurement_state": "invalid"},
    )
    store.append_observation(
        observed_at="2026-08-08T00:00:00Z",
        platform="google",
        facts={"measurement_state": "stable"},
    )
    current = store.current_state()
    assert current["measurement_state"] == "stable"


def test_timeline_does_not_depend_on_file_write_order(store: StateStore) -> None:
    decision = store.append_decision(
        decision_class="wait", reason="observe", review_condition="tomorrow"
    )
    store.append_outcome(outcome_class="neutral", decision_id=decision)
    events = store.get_recent(limit=10)
    assert [event["type"] for event in reversed(events)] == [
        "decision",
        "outcome",
    ]


# ── Full-log derivation (Part 5/6/18) ────────────────────────────────────


def test_current_state_correct_beyond_recent_window(store: StateStore) -> None:
    for index in range(120):
        store.append_observation(
            observed_at=f"2026-08-01T00:{index % 60:02d}:00Z",
            platform="google",
            facts={
                "ctr": 0.01,
                "measurement_state": "invalid" if index < 110 else "stable",
                "maturity_state": "sufficient",
            },
        )
    current = store.current_state()
    assert current["event_count"] == 120
    # The latest observation (event 120, outside any 100-event window) still
    # drives the derived state.
    assert current["measurement_state"] == "stable"
    assert current["last_observation_id"] == "event_00000120"


def test_old_pending_review_survives_many_later_events(store: StateStore) -> None:
    old_decision = store.append_decision(
        decision_class="wait", reason="wait for maturity", review_condition="maturity"
    )
    for index in range(120):
        _observation(store, ctr=0.001 * index)
    pending = store.get_pending_review()
    assert pending is not None
    assert pending["decision_id"] == old_decision
    assert store.current_state()["pending_review"]["decision_id"] == old_decision


def test_pending_review_clears_when_outcome_arrives(store: StateStore) -> None:
    decision = store.append_decision(
        decision_class="wait", reason="observe", review_condition="tomorrow"
    )
    assert store.get_pending_review() is not None
    store.append_outcome(outcome_class="neutral", decision_id=decision)
    assert store.get_pending_review() is None


def test_current_state_freshness_detects_stale_derived_file(store: StateStore) -> None:
    _observation(store)
    current = store.current_state()
    assert current["derived_through_sequence"] == 1
    # Simulate a crash between event write and rebuild: write an event file
    # directly, then read current state (must detect staleness and rebuild).
    store.append_observation(
        observed_at="2026-08-10T09:00:00Z", platform="google", facts={"ctr": 0.03}
    )
    stale = json.loads(store.context.current_state_path.read_text(encoding="utf-8"))
    assert stale["derived_through_sequence"] == 2
    # Manually regress the derived file to simulate the crash window.
    stale["derived_through_sequence"] = 1
    store.context.current_state_path.write_text(json.dumps(stale), encoding="utf-8")
    refreshed = store.current_state()
    assert refreshed["derived_through_sequence"] == 2


# ── Event integrity (Part 19) ────────────────────────────────────────────


def test_event_id_mismatch_with_filename_is_detected(store: StateStore) -> None:
    _observation(store)
    event_file = store.context.events_dir / "00000001-observation.json"
    document = json.loads(event_file.read_text(encoding="utf-8"))
    document["event_id"] = "event_00000099"
    event_file.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContractError, match="id mismatch"):
        store.get_recent()


def test_verify_reports_integrity_problems_without_fixing(store: StateStore) -> None:
    _observation(store)
    assert store.verify()["healthy"] is True
    # Break a reference and verify() must report it.
    store.append_decision(
        decision_class="wait", reason="x", evidence_refs=("event_00000001",)
    )
    event_file = store.context.events_dir / "00000002-decision.json"
    document = json.loads(event_file.read_text(encoding="utf-8"))
    document["refs"] = ["event_00000099"]
    event_file.write_text(json.dumps(document), encoding="utf-8")
    report = store.verify()
    assert report["healthy"] is False
    assert any("missing event_00000099" in issue for issue in report["issues"])


# ── Provenance (Part 10/11) ──────────────────────────────────────────────


def test_decision_provenance_is_origin_aware(store: StateStore) -> None:
    store.append_decision(decision_class="wait", reason="agent reasoning")
    event = store.get_recent_decisions(limit=1)[0]
    assert event["payload"]["origin"] == "agent_constrained"
    assert event["evidence_status"] == "inferred"
    assert event["source_type"] == "agent"
    store.append_decision(
        decision_class="keep", reason="engine output", origin="deterministic"
    )
    engine_event = store.get_recent_decisions(limit=1)[0]
    assert engine_event["payload"]["origin"] == "deterministic"
    assert engine_event["source_type"] == "deterministic_engine"
    store.append_decision(
        decision_class="keep", reason="operator choice", origin="operator"
    )
    operator_event = store.get_recent_decisions(limit=1)[0]
    assert operator_event["payload"]["origin"] == "operator"
    assert operator_event["source_type"] == "manual"


def test_run_id_is_recorded_and_local(store: StateStore) -> None:
    run_id = new_run_id()
    store.append_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"ctr": 0.01},
        run_id=run_id,
    )
    event = store.get_recent_observations(limit=1)[0]
    assert event["run_id"] == run_id
