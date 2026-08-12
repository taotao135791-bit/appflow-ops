"""v3.3.2 runtime enforcement: real entry points, migration race, integrity,
deduplication, payload guard, and isolation.

The follow-up scenarios must go through the real runtime entry
(AppFlowRuntime.begin_run), never by manually calling
load_context_summary() in the test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.run_lifecycle import (
    AppFlowRuntime,
    classify_request,
    should_load_state,
)
from appflow_ops.uac.state_guard import (
    MAX_STRING_LENGTH,
    StatePayloadError,
    check_state_payload,
)
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.types import ContractError
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


@pytest.fixture()
def store(workspace) -> StateStore:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    return store


def _day1(store: StateStore) -> tuple[str, str]:
    observation_id = store.append_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={
            "spend": 62.0,
            "ctr": 0.02,
            "measurement_state": "stable",
            "maturity_state": "insufficient",
        },
    )
    decision_id = store.append_decision(
        decision_class="wait",
        reason="delivery dropped after bid reduction",
        review_condition="maturity sufficient",
    )
    return observation_id, decision_id


# ── request classification ──────────────────────────────────────────────


def test_classify_direct_informational_vs_operational() -> None:
    assert classify_request("CTR 是什么？") == "direct_informational"
    assert classify_request("CPA 是什么意思？") == "direct_informational"
    assert classify_request("Google 最近怎么跑不动了？") == "operational_diagnosis"
    assert classify_request("CPA 为什么突然高了？") == "operational_diagnosis"
    assert classify_request("现在呢？") == "follow_up"
    assert classify_request("Google 怎么又不行了？") == "follow_up"
    assert classify_request("还是没量。") == "follow_up"
    assert classify_request("这个还能跑吗？") == "follow_up"
    assert classify_request("该调预算还是调出价？") == "decision_request"
    assert classify_request("这个 campaign 要不要重新开？") == "decision_request"


def test_should_load_state_only_excludes_direct_informational() -> None:
    assert not should_load_state(classify_request("CTR 是什么？"))
    assert should_load_state(classify_request("现在呢？"))
    assert should_load_state(classify_request("为什么有点击但是没安装？"))
    assert should_load_state(classify_request("该不该降预算？"))


# ── Scenario A: "现在呢？" through the real runtime entry ────────────────


def test_followup_request_auto_loads_state_through_runtime(store: StateStore) -> None:
    _day1(store)
    # Day 2: the real runtime entry answers "现在呢?" — the test never calls
    # load_context_summary() directly.
    runtime = AppFlowRuntime(store.context.workspace)
    runtime.begin_run(request_text="现在呢？")
    assert runtime.state_loaded
    context = runtime.state_context()
    assert context is not None
    current = context["current_state"]
    assert current["last_observation_id"] is not None
    assert current["last_decision_id"] is not None
    assert current["pending_review"] is not None
    assert current["pending_review"]["condition"] == "maturity sufficient"
    # previous decision and latest observation are available to reasoning
    assert context["last_decision"]["payload"]["decision_class"] == "wait"
    assert context["last_observation"]["payload"]["facts"]["spend"] == 62.0
    # loading state wrote no business events
    assert store.status()["event_count"] == 2
    runtime.finish_run()


def test_followup_run_can_record_new_decision_and_observation(
    store: StateStore,
) -> None:
    _day1(store)
    runtime = AppFlowRuntime(store.context.workspace)
    runtime.begin_run(request_text="现在呢？")
    runtime.record_observation(
        observed_at="2026-08-11T09:00:00Z",
        platform="google",
        facts={
            "spend": 45.0,
            "maturity_state": "sufficient",
            "measurement_state": "stable",
        },
    )
    runtime.record_decision(
        decision_class="decrease",
        reason="maturity now sufficient; bid can move within policy bounds",
        origin="agent_constrained",
        review_condition="review after 3 days",
    )
    runtime.finish_run()
    events = store.status()
    assert events["event_count"] == 4
    decisions = store.get_recent_decisions(limit=1)[0]
    assert decisions["payload"]["origin"] == "agent_constrained"
    assert decisions["source_type"] == "agent"


# ── Scenario B: direct question skips state entirely ─────────────────────


def test_direct_term_question_skips_state_read(store: StateStore) -> None:
    runtime = AppFlowRuntime(store.context.workspace)
    runtime.begin_run(request_text="CTR 是什么？")
    assert not runtime.state_loaded
    assert runtime.state_context() is None
    assert store.status()["event_count"] == 0
    runtime.finish_run()


# ── lifecycle write rules through the runtime ────────────────────────────


def test_runtime_records_reliable_observation(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="Google 最近怎么跑不动了？")
    event_id = runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0, "measurement_state": "stable"},
    )
    runtime.finish_run()
    assert event_id is not None
    assert runtime.session.store.status()["event_count"] == 1


def test_runtime_records_operational_decision(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="该调预算还是调出价？")
    event_id = runtime.record_decision(
        decision_class="decrease", reason="bid above mature CPA"
    )
    runtime.finish_run()
    assert event_id is not None
    event = runtime.session.store.get_recent_decisions(limit=1)[0]
    assert event["payload"]["origin"] == "agent_constrained"
    assert event["source_type"] == "agent"


def test_runtime_does_not_record_change_from_recommendation(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="这个还能跑吗？")
    runtime.record_decision(decision_class="keep", reason="still profitable")
    runtime.finish_run()
    assert runtime.session.store.status()["events_by_type"]["change"] == 0


def test_runtime_records_confirmed_change(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="现在呢？")
    runtime.record_decision(decision_class="decrease", reason="tCPA too high")
    runtime.record_confirmed_change(
        change_type="bid", direction="decrease", magnitude=12.0
    )
    runtime.finish_run()
    events = runtime.session.store.status()["events_by_type"]
    assert events["decision"] == 1
    assert events["change"] == 1


def test_runtime_records_later_outcome(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    decision_id = runtime.record_decision(decision_class="decrease", reason="x")
    assert decision_id is not None
    # Day 2: later evidence justifies an outcome.
    outcome_id = runtime.record_outcome(
        outcome_class="improved", decision_id=decision_id
    )
    runtime.finish_run()
    assert outcome_id is not None
    event = runtime.session.store.get_recent_outcomes(limit=1)[0]
    assert event["payload"]["decision_id"] == decision_id


# ── Scenario D: runtime-owned deduplication ──────────────────────────────


def test_runtime_dedupes_same_observation_without_explicit_digest(
    workspace,
) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="现在呢？")
    first = runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0, "ctr": 0.02, "measurement_state": "stable"},
        source_type="export",
    )
    second = runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0, "ctr": 0.02, "measurement_state": "stable"},
        source_type="export",
    )
    runtime.finish_run()
    assert first is not None
    assert second is None
    assert runtime.session.store.status()["event_count"] == 1


def test_auto_digest_ignores_volatile_fields(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    # Same facts with a different observed_at must still dedupe: the digest
    # is built from canonical payload, not timestamps.
    runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0},
    )
    duplicate = runtime.record_observation(
        observed_at="2026-08-11T09:00:00Z",
        platform="google",
        facts={"spend": 62.0},
    )
    runtime.finish_run()
    assert duplicate is None
    assert runtime.session.store.status()["event_count"] == 1


def test_explicit_source_digest_still_supported_and_wins(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0},
        source_digest="export-2026-08-10",
    )
    duplicate = runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0},
        source_digest="export-2026-08-10",
    )
    runtime.finish_run()
    assert duplicate is None
    assert runtime.session.store.status()["event_count"] == 1


def test_dedupe_is_run_local_not_global(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={"spend": 62.0},
    )
    runtime.finish_run()
    day2 = AppFlowRuntime(workspace)
    day2.begin_run()
    day2.record_observation(
        observed_at="2026-08-11T09:00:00Z",
        platform="google",
        facts={"spend": 62.0},
    )
    day2.finish_run()
    assert day2.session.store.status()["event_count"] == 2


# ── Scenario C: legacy migration race ────────────────────────────────────


def _strip_workspace_id(workspace) -> None:
    context = workspace.context_path
    document = yaml.safe_load(context.read_text(encoding="utf-8"))
    document["project"].pop("workspace_id", None)
    context.write_text(yaml.safe_dump(document), encoding="utf-8")


def test_legacy_migration_race_yields_one_workspace_id(workspace) -> None:
    _strip_workspace_id(workspace)
    results: list[str] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def open_context() -> None:
        try:
            context = RunContext.from_workspace(workspace)
            with lock:
                results.append(context.workspace_id)
        except Exception as exc:  # pragma: no cover - failure path
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=open_context) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(results) == 50
    assert len(set(results)) == 1
    assert results[0]
    # The bound id is persisted.
    document = yaml.safe_load(workspace.context_path.read_text(encoding="utf-8"))
    assert document["project"]["workspace_id"] == results[0]


# ── integrity: freshness, gaps, corruption ───────────────────────────────


def test_freshness_detects_event_count_mismatch(store: StateStore) -> None:
    _day1(store)
    current_path = store.context.current_state_path
    document = json.loads(current_path.read_text(encoding="utf-8"))
    document["event_count"] = 999  # tamper with the derived metadata
    current_path.write_text(json.dumps(document), encoding="utf-8")
    current = store.current_state()
    assert current["event_count"] == 2  # rebuilt from the real log
    assert current["derived_through_sequence"] == 2


def test_sequence_gap_fails_doctor_and_rebuild(store: StateStore) -> None:
    _day1(store)
    store.append_change(change_type="budget", direction="decrease")  # event 3
    events_dir = store.context.events_dir
    # Delete the MIDDLE event -> log is 1..3 with a gap at 2.
    (events_dir / "00000002-decision.json").unlink()
    report = store.verify()
    assert not report["healthy"]
    assert any("sequence gap" in issue for issue in report["issues"])
    with pytest.raises(ContractError, match="sequence gap"):
        store.current_state()
    with pytest.raises(ContractError, match="sequence gap"):
        store.rebuild_current_state()


def test_duplicate_sequence_fails_doctor(store: StateStore) -> None:
    _day1(store)
    events_dir = store.context.events_dir
    # Copy event 1 under a different type with the same sequence number.
    source = events_dir / "00000001-observation.json"
    duplicate = events_dir / "00000001-change.json"
    duplicate.write_bytes(source.read_bytes())
    report = store.verify()
    assert not report["healthy"]
    assert any("duplicate sequence" in issue for issue in report["issues"])


def test_corrupted_event_fails_clearly(store: StateStore) -> None:
    _day1(store)
    event_path = store.context.events_dir / "00000001-observation.json"
    event_path.write_text("{not json", encoding="utf-8")
    report = store.verify()
    assert not report["healthy"]
    assert any("corrupted" in issue for issue in report["issues"])
    # The doctor detects it, and every rebuild path fails loudly instead of
    # skipping the broken event.
    with pytest.raises(ContractError, match="corrupted"):
        store.rebuild_current_state()


# ── Scenario E: payload guard ────────────────────────────────────────────


def test_payload_guard_rejects_credential_fields(store: StateStore) -> None:
    with pytest.raises(StatePayloadError, match="access_token"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.03, "access_token": "abc"},
        )
    with pytest.raises(StatePayloadError, match="client_email"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.03, "client_email": "someone" + "@" + "example.com"},
        )
    with pytest.raises(StatePayloadError, match="password"):
        store.append_decision(
            decision_class="wait",
            reason="x",
            policy_constraints={"password": "hunter2"},
        )
    assert store.status()["event_count"] == 0  # nothing was written


def test_payload_guard_rejects_nested_forbidden_keys(store: StateStore) -> None:
    with pytest.raises(StatePayloadError, match="raw_chat"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.03, "nested": {"raw_chat": "full conversation text"}},
        )
    with pytest.raises(StatePayloadError, match="api_key"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.03, "creds": [{"api_key": "sk-1234"}]},
        )


def test_payload_guard_rejects_oversized_and_email_strings(
    store: StateStore,
) -> None:
    with pytest.raises(StatePayloadError, match="exceeds"):
        store.append_observation(
            observed_at="2026-08-10T09:00:00Z",
            platform="google",
            facts={"ctr": 0.03, "primary_reason": "x" * (MAX_STRING_LENGTH + 1)},
        )
    with pytest.raises(StatePayloadError, match="email address"):
        store.append_decision(
            decision_class="wait", reason="client" + "@" + "acme.example"
        )


def test_payload_guard_allows_normal_business_fields(store: StateStore) -> None:
    # Allowed: metric indexes, states, short reasons — and a business field
    # whose name merely contains a forbidden substring is not误伤.
    check_state_payload(
        {
            "spend_index": {"before": 100.0, "after": 38.1},
            "ctr": 0.02,
            "measurement_state": "stable",
            "primary_reason": "short summary",
            "email_ctr": 0.004,
        },
        context="facts",
    )
    store.append_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google",
        facts={
            "spend_index": {"before": 100.0, "after": 38.1},
            "ctr": 0.02,
            "measurement_state": "stable",
            "email_ctr": 0.004,
        },
    )
    assert store.status()["event_count"] == 1


# ── Scenario F: isolation with runtime ───────────────────────────────────


def test_runtime_a_never_loads_b_state(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("ios-main", base_dir=base, client_label="acme")
    workspace_b = initialize_workspace(
        "android-main", base_dir=base, client_label="beta"
    )
    store_a = StateStore(RunContext.from_workspace(workspace_a))
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    store_a.ensure_initialized()
    store_b.ensure_initialized()
    _day1(store_a)
    _day1(store_b)  # B has the same sequence ids and a similar decision
    runtime = AppFlowRuntime(workspace_a)
    runtime.begin_run(request_text="现在呢？")
    context = runtime.state_context()
    assert context is not None
    assert context["workspace_id"] == store_a.context.workspace_id
    assert context["workspace_id"] != store_b.context.workspace_id
    assert context["pending_review"]["decision_id"] == "event_00000002"
    # B's identical sequence ids must not leak into A's context.
    assert context["current_state"]["last_observation_id"] == "event_00000001"
    assert (
        context["last_decision"]["payload"]["review_condition"] == "maturity sufficient"
    )
    assert runtime.session.store.context.workspace_id == store_a.context.workspace_id
    runtime.finish_run()


def test_runtime_writes_stay_in_a_only(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("ios-main", base_dir=base, client_label="acme")
    workspace_b = initialize_workspace(
        "android-main", base_dir=base, client_label="beta"
    )
    runtime = AppFlowRuntime(workspace_a)
    runtime.begin_run(request_text="现在呢？")
    runtime.record_decision(decision_class="wait", reason="x")
    runtime.finish_run()
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    store_b.ensure_initialized()
    assert store_b.status()["event_count"] == 0
    assert runtime.session.store.status()["event_count"] == 1


# ── dry-run / replay / eval never write live state ───────────────────────


def test_replay_does_not_mutate_live_state(workspace, repo_root: Path) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    _day1(store)
    before = store.status()["event_count"]
    # A real anonymized replay directory (same shape as examples/).
    example_dir = repo_root / "examples" / "replays" / "example-anonymized"
    replay_dir = workspace.replays_dir / "example-anonymized"
    replay_dir.mkdir()
    for source in example_dir.glob("*.yaml"):
        (replay_dir / source.name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    script = SCRIPTS_DIR / "uac_experiment.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "replay",
            str(replay_dir),
            "--workspace",
            str(workspace.root),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert store.status()["event_count"] == before


def test_runtime_begin_run_without_records_writes_nothing(store: StateStore) -> None:
    runtime = AppFlowRuntime(store.context.workspace)
    runtime.begin_run(request_text="现在呢？")
    runtime.finish_run()
    assert store.status()["event_count"] == 0


# ── CLI deterministic paths reuse the same lifecycle ─────────────────────


def _run_cli(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "uac_experiment.py"), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _workspace_with_ready_input(repo_root: Path, tmp_path: Path, fixture: str):
    workspace = initialize_workspace("cli-e2e", base_dir=tmp_path)
    shutil.copyfile(
        repo_root / "skills" / "ads-google-app" / "assets" / fixture,
        workspace.input_dir / "anonymous-export.yaml",
    )
    normalized = _run_cli(repo_root, "normalize", "--workspace", str(workspace.root))
    assert normalized.returncode == 0, normalized.stderr
    return workspace


def test_cli_decide_records_one_deterministic_decision(repo_root, tmp_path) -> None:

    workspace = _workspace_with_ready_input(
        repo_root, tmp_path, "UAC-QUICK-OPS.example.yaml"
    )
    completed = _run_cli(repo_root, "decide", "--workspace", str(workspace.root))
    assert completed.returncode == 0, completed.stderr
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"] == {
        "observation": 0,
        "change": 0,
        "decision": 1,
        "outcome": 0,
    }
    decision = store.get_recent_decisions(limit=1)[0]
    assert decision["payload"]["origin"] == "deterministic"
    assert decision["source_type"] == "deterministic_engine"
    assert decision["payload"]["decision_class"] in {
        "keep",
        "increase",
        "decrease",
        "pause",
        "reopen",
        "replace",
        "wait",
        "observe",
        "investigate",
    }


def test_cli_analyze_records_one_observation(repo_root, tmp_path) -> None:

    workspace = _workspace_with_ready_input(
        repo_root, tmp_path, "UAC-INPUT.example.yaml"
    )
    completed = _run_cli(repo_root, "analyze", "--workspace", str(workspace.root))
    assert completed.returncode == 0, completed.stderr
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 1
    observation = store.get_recent_observations(limit=1)[0]
    facts = observation["payload"]["facts"]
    assert facts["spend"] == 1200
    assert facts["measurement_state"] == "stable"
    assert observation["source_type"] == "deterministic_engine"
    assert observation["observed_at"] == "2026-06-28T00:00:00Z"


def test_cli_replay_and_normalize_do_not_write_state(repo_root, tmp_path) -> None:
    workspace = initialize_workspace("cli-e2e", base_dir=tmp_path)
    shutil.copyfile(
        repo_root
        / "skills"
        / "ads-google-app"
        / "assets"
        / "UAC-QUICK-OPS.example.yaml",
        workspace.input_dir / "anonymous-export.yaml",
    )
    normalized = _run_cli(repo_root, "normalize", "--workspace", str(workspace.root))
    assert normalized.returncode == 0, normalized.stderr
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["event_count"] == 0  # normalize never writes state
