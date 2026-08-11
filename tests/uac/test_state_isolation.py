"""Cross-workspace isolation contracts for the state store.

The most important tests in the Continuous Account State round (Part 33):
workspace A can never read, write, search, reference, or delete workspace B
state, and adversarial paths (traversal, symlinks) are denied. There is no
global business store, so there is nothing outside a workspace to leak into.
"""

from __future__ import annotations

import json
import os
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
def two_workspaces(tmp_path: Path):
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("app-us", base_dir=base, client_label="client-a")
    workspace_b = initialize_workspace(
        "product-x", base_dir=base, client_label="client-b"
    )
    store_a = StateStore(RunContext.from_workspace(workspace_a))
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    store_a.ensure_initialized()
    store_b.ensure_initialized()
    return {
        "base": base,
        "a": workspace_a,
        "b": workspace_b,
        "store_a": store_a,
        "store_b": store_b,
    }


def _write_observation(store: StateStore, *, ctr: float, spend: float) -> str:
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


# ── Test A/B: A cannot read or write B ───────────────────────────────────


def test_workspace_a_state_cannot_read_b(two_workspaces) -> None:
    _write_observation(two_workspaces["store_b"], ctr=0.05, spend=999.0)
    recent = two_workspaces["store_a"].get_recent()
    assert recent == ()
    assert all("999.0" not in json.dumps(event) for event in recent)


def test_workspace_a_state_cannot_write_b(two_workspaces) -> None:
    store_a = two_workspaces["store_a"]
    store_b = two_workspaces["store_b"]
    # The only path API accepts is derived from A's own RunContext; there is
    # no API that accepts B's path at all. Writing through B's store from
    # A's context must be impossible structurally: verify B's store stays
    # untouched even when A writes many events.
    for index in range(3):
        _write_observation(store_a, ctr=0.01 * index, spend=10.0)
    assert store_b.status()["event_count"] == 0


def test_run_context_cannot_be_rebound_to_another_workspace(two_workspaces) -> None:
    # RunContext is frozen and derived from one workspace; there is no
    # setter and no API accepting a foreign path.
    context_a = RunContext.from_workspace(two_workspaces["a"])
    with pytest.raises(AttributeError):
        context_a.workspace = two_workspaces["b"]  # type: ignore[misc]


# ── Test C: path traversal cannot escape A ───────────────────────────────


def test_path_traversal_cannot_escape_a(two_workspaces) -> None:
    workspace_a = two_workspaces["a"]
    with pytest.raises(ContractError, match="must stay inside"):
        workspace_a.require_contained_path(
            workspace_a.root / "state" / ".." / ".." / "client-b", "traversal"
        )
    with pytest.raises(ContractError, match="must stay inside"):
        workspace_a.require_contained_path(Path("../../client-b/state"), "traversal")


def test_absolute_external_path_is_rejected(two_workspaces) -> None:
    with pytest.raises(ContractError, match="must stay inside"):
        two_workspaces["a"].require_contained_path(
            two_workspaces["b"].root / "state", "absolute external path"
        )


# ── Test D: symlink cannot escape A ──────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs Windows privileges")
def test_symlink_escape_is_denied(two_workspaces) -> None:
    store_a = two_workspaces["store_a"]
    # Replace the events directory with a symlink pointing at B's events.
    events_dir = store_a.context.events_dir
    target = two_workspaces["store_b"].context.events_dir
    events_dir.rename(events_dir.with_suffix(".real"))
    try:
        os.symlink(target, events_dir)
        with pytest.raises(ContractError, match="symbolic link"):
            store_a.get_recent()
        with pytest.raises(ContractError, match="symbolic link"):
            store_a.append_observation(
                observed_at="2026-08-10T09:00:00Z",
                platform="google",
                facts={"ctr": 0.01},
            )
        # B's state was never read or written.
        assert store_b_status(two_workspaces) == 0
    finally:
        events_dir.unlink()
        events_dir.with_suffix(".real").rename(events_dir)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs Windows privileges")
def test_nested_symlink_inside_events_is_denied(two_workspaces) -> None:
    store_a = two_workspaces["store_a"]
    events_dir = store_a.context.events_dir
    planted = events_dir / "00000099-change.json"
    os.symlink(two_workspaces["store_b"].context.events_dir, planted)
    try:
        with pytest.raises(ContractError, match="symbolic link"):
            store_a.get_recent()
    finally:
        planted.unlink()


def test_state_dir_symlink_is_rejected_at_resolution(two_workspaces) -> None:
    store_a = two_workspaces["store_a"]
    state_dir = store_a.context.state_dir
    state_dir.rename(state_dir.with_suffix(".real"))
    try:
        os.symlink(two_workspaces["b"].root / "state", state_dir)
        with pytest.raises(ContractError, match="symbolic link"):
            store_a.current_state()
    finally:
        state_dir.unlink()
        state_dir.with_suffix(".real").rename(state_dir)


def store_b_status(two_workspaces) -> int:
    return two_workspaces["store_b"].status()["event_count"]


# ── Test E: deleting A never deletes B ───────────────────────────────────


def test_clearing_a_never_touches_b(two_workspaces) -> None:
    _write_observation(two_workspaces["store_a"], ctr=0.01, spend=1.0)
    _write_observation(two_workspaces["store_b"], ctr=0.99, spend=999.0)
    two_workspaces["store_a"].clear()
    assert not two_workspaces["store_a"].context.state_dir.exists()
    assert store_b_status(two_workspaces) == 1
    assert two_workspaces["store_b"].current_state()["event_count"] == 1


def test_deleting_workspace_a_leaves_no_global_copy(two_workspaces) -> None:
    _write_observation(two_workspaces["store_a"], ctr=0.01, spend=1.0)
    workspace_a_root = two_workspaces["a"].root
    import shutil

    shutil.rmtree(workspace_a_root)
    # No global index/cache exists by design; B's store is the only other
    # state and it contains no A data.
    remaining_state = list(two_workspaces["base"].rglob("state"))
    assert remaining_state == [two_workspaces["store_b"].context.state_dir]
    assert store_b_status(two_workspaces) == 0


# ── Test F: rebuilding A cannot read B events ────────────────────────────


def test_rebuild_a_cannot_read_b_events(two_workspaces) -> None:
    _write_observation(two_workspaces["store_b"], ctr=0.42, spend=777.0)
    current = two_workspaces["store_a"].rebuild_current_state()
    assert current["event_count"] == 0
    serialized = json.dumps(current)
    assert "0.42" not in serialized
    assert "777.0" not in serialized


# ── Test G: retrieval in A returns no B data ─────────────────────────────


def test_retrieval_in_a_returns_no_b_data(two_workspaces) -> None:
    _write_observation(two_workspaces["store_b"], ctr=0.88, spend=555.0)
    for event_type in ("observation", "change", "decision", "outcome"):
        events = two_workspaces["store_a"].get_recent(event_type=event_type)
        assert events == ()
    assert two_workspaces["store_a"].get_pending_review() is None


# ── Test H: current-state for A contains no B identifiers ────────────────


def test_current_state_for_a_contains_no_b_identifiers(two_workspaces) -> None:
    _write_observation(two_workspaces["store_b"], ctr=0.77, spend=444.0)
    decision_b = two_workspaces["store_b"].append_decision(
        decision_class="increase",
        reason="scale winning campaign",
    )
    current_a = two_workspaces["store_a"].current_state()
    serialized = json.dumps(current_a)
    assert decision_b not in serialized
    assert "client-b" not in serialized
    assert "product-x" not in serialized


# ── Cross-workspace source references are denied ─────────────────────────


def test_cross_workspace_source_reference_is_denied(two_workspaces) -> None:
    store_a = two_workspaces["store_a"]
    foreign_absolute = two_workspaces["b"].root / "state" / "events"
    with pytest.raises(ContractError, match="must stay inside"):
        store_a.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.01},
            refs=(str(foreign_absolute),),
        )
    with pytest.raises(ContractError, match="must stay inside"):
        store_a.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.01},
            refs=("../../client-b/state/events/00000001-observation.json",),
        )


def test_traversal_variants_are_rejected(two_workspaces) -> None:
    workspace_a = two_workspaces["a"]
    for hostile in (
        "state/../../client-b",
        "state/../../../client-b",
        "../client-b/state",
        "../../client-b/state",
    ):
        with pytest.raises(ContractError):
            workspace_a.require_contained_path(
                workspace_a.root / hostile, "hostile path"
            )
