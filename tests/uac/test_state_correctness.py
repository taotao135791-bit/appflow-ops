"""v3.3.3 state correctness: semantic dedupe, state-access minimization,
UAC persistence completeness, freshness exactness, and guard bounds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.run_lifecycle import (
    AppFlowRuntime,
    StateAccess,
    classify_state_access,
)
from appflow_ops.uac.state_adapters import (
    project_analysis_observation,
    project_quick_decision,
)
from appflow_ops.uac.state_guard import (
    MAX_COLLECTION_ITEMS,
    MAX_MAPPING_KEYS,
    MAX_PAYLOAD_BYTES,
    StatePayloadError,
    check_state_payload,
)
from appflow_ops.uac.state_store import StateStore
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


# ── semantic dedupe: business semantics participate, volatility does not ─


def test_observation_same_value_different_days_are_two_events(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    first = runtime.record_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"spend_index": 100.0},
    )
    second = runtime.record_observation(
        observed_at="2026-08-11T00:00:00Z",
        platform="google",
        facts={"spend_index": 100.0},
    )
    third = runtime.record_observation(
        observed_at="2026-08-12T00:00:00Z",
        platform="google",
        facts={"spend_index": 100.0},
    )
    runtime.finish_run()
    assert first and second and third
    assert runtime.session.store.status()["event_count"] == 3
    # The derived state expresses "stable for three days".
    current = runtime.session.store.current_state()
    assert current["last_observation_id"] == third


def test_observation_exact_duplicate_in_one_run_is_one_event(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"spend": 100.0, "ctr": 0.02},
    )
    duplicate = runtime.record_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"spend": 100.0, "ctr": 0.02},
    )
    runtime.finish_run()
    assert duplicate is None
    assert runtime.session.store.status()["event_count"] == 1


def test_decision_same_class_different_review_time_are_two_events(
    workspace,
) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_decision(
        decision_class="wait",
        reason="delivery drop",
        review_condition="review tomorrow",
        review_after="2026-08-13",
    )
    second = runtime.record_decision(
        decision_class="wait",
        reason="delivery drop",
        review_condition="review in 7 days",
        review_after="2026-08-19",
    )
    runtime.finish_run()
    assert second is not None
    assert runtime.session.store.status()["event_count"] == 2


def test_decision_exact_duplicate_is_one_event(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_decision(
        decision_class="keep",
        reason="still profitable",
        review_condition=None,
        review_after=None,
    )
    duplicate = runtime.record_decision(
        decision_class="keep",
        reason="still profitable",
        review_condition=None,
        review_after=None,
    )
    runtime.finish_run()
    assert duplicate is None
    assert runtime.session.store.status()["event_count"] == 1


def test_change_same_magnitude_different_effective_time_are_two_events(
    workspace,
) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=20.0,
        effective_at="2026-08-10",
    )
    second = runtime.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=20.0,
        effective_at="2026-08-14",
    )
    runtime.finish_run()
    assert second is not None
    assert runtime.session.store.status()["event_count"] == 2


def test_digest_ignores_dict_key_order(workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run()
    runtime.record_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"ctr": 0.02, "spend": 100.0},
    )
    duplicate = runtime.record_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"spend": 100.0, "ctr": 0.02},  # reordered keys
    )
    runtime.finish_run()
    assert duplicate is None
    assert runtime.session.store.status()["event_count"] == 1


# ── state-access minimization ────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "昨天美国有什么行业新闻？",
        "帮我写个素材brief",
        "把这段翻译成英文",
        "翻译这句话",
        "给甲方写一句解释CPA上涨的话",
        "昨天有什么新闻？",
        "CTR 是什么？",
        "帮我写个给甲方的信息",
    ],
)
def test_non_operational_requests_never_load_state(query: str, workspace) -> None:
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text=query)
    assert not runtime.state_loaded
    assert runtime.session.store.status()["event_count"] == 0
    runtime.finish_run()


@pytest.mark.parametrize(
    "query",
    [
        "昨天那个调整现在怎么样？",
        "Google怎么又不行了？",
        "这个campaign还能跑吗？",
        "现在该继续等还是调价？",
        "现在呢？",
    ],
)
def test_operational_followups_load_state(query: str, workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    store.append_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"spend": 62.0},
    )
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text=query)
    assert runtime.state_loaded
    assert runtime.state_context()["current_state"]["event_count"] == 1
    runtime.finish_run()


def test_classify_state_access_categories() -> None:
    assert classify_state_access("翻译这句话") == StateAccess.NOT_NEEDED
    assert classify_state_access("昨天美国有什么行业新闻？") == StateAccess.NOT_NEEDED
    assert classify_state_access("帮我写个素材brief") == StateAccess.NOT_NEEDED
    assert (
        classify_state_access("给甲方写一句解释CPA上涨的话") == StateAccess.NOT_NEEDED
    )
    assert classify_state_access("现在呢？") == StateAccess.REQUIRED
    assert classify_state_access("Google怎么又不行了？") == StateAccess.REQUIRED
    assert classify_state_access("这个campaign还能跑吗？") == StateAccess.REQUIRED
    assert classify_state_access("现在该继续等还是调价？") == StateAccess.REQUIRED
    # Unknown phrasing stays closed.
    assert classify_state_access("帮我看看这个文件") == StateAccess.UNCERTAIN


# ── UAC persistence completeness ─────────────────────────────────────────


def _run_cli(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "uac_experiment.py"), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_analyze_persists_future_relevant_structured_facts(
    repo_root, tmp_path
) -> None:
    workspace = initialize_workspace("cli-e2e", base_dir=tmp_path)
    shutil.copyfile(
        repo_root / "skills" / "ads-google-app" / "assets" / "UAC-INPUT.example.yaml",
        workspace.input_dir / "anonymous-export.yaml",
    )
    normalized = _run_cli(repo_root, "normalize", "--workspace", str(workspace.root))
    assert normalized.returncode == 0, normalized.stderr
    completed = _run_cli(repo_root, "analyze", "--workspace", str(workspace.root))
    assert completed.returncode == 0, completed.stderr
    store = StateStore(RunContext.from_workspace(workspace))
    observation = store.get_recent_observations(limit=1)[0]
    facts = observation["payload"]["facts"]
    assert facts["spend"] == 1200
    assert facts["installs"] == 600
    assert facts["registrations"] == 180
    assert facts["payments"] == 18
    assert facts["measurement_state"] == "stable"
    assert facts["maturity_state"] == "sufficient"
    # Funnel structure from the engine, not the raw export.
    assert facts["funnel_rates"][0]["from"] == "installs"
    assert facts["largest_funnel_drop"] == 0.7


def test_cli_decide_persists_context_and_links_evidence(repo_root, tmp_path) -> None:
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
    analyzed = _run_cli(repo_root, "analyze", "--workspace", str(workspace.root))
    assert analyzed.returncode == 0, analyzed.stderr
    completed = _run_cli(repo_root, "decide", "--workspace", str(workspace.root))
    assert completed.returncode == 0, completed.stderr
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_recent_decisions(limit=1)[0]
    payload = decision["payload"]
    assert payload["origin"] == "deterministic"
    assert "measurement_state" in payload
    assert "maturity_state" in payload
    assert payload["policy_constraints"]["numeric_policy"] == "uac-numeric-policy-v1"
    assert payload["policy_constraints"]["signal_policy"] == "uac-signal-policy-v1"
    # Evidence is a real linked observation, not free-form text only.
    assert len(payload["evidence_refs"]) == 1
    observation = store.get_event(payload["evidence_refs"][0])
    assert observation["type"] == "observation"
    assert payload["review_condition"]
    assert payload.get("review_after")


def test_adapters_are_projection_only(repo_root) -> None:
    """Adapters must not recompute engine logic: feeding a changed input
    only changes the projected fields, never inventing new ones."""
    import yaml

    path = repo_root / "skills" / "ads-google-app" / "assets" / "UAC-INPUT.example.yaml"
    case = yaml.safe_load(path.read_text(encoding="utf-8"))
    metrics = case["facts"]["metrics"]
    analysis = {
        "measurement_state": {"status": "measurement_reliable"},
        "learning_eligibility": {"status": "LEARNABLE"},
        "funnel_state": {"observed_rates": [], "largest_observed_drop": None},
    }
    facts = project_analysis_observation(case, analysis)
    assert facts["spend"] == metrics["spend"]
    assert facts["measurement_state"] == "stable"
    assert "funnel_rates" not in facts  # engine provided none -> stays absent
    projected = project_quick_decision(
        {
            "derived_signals": {"maturity": {"state": "MATURE"}},
            "policy": {
                "numeric": {"policy_version": "v1"},
                "signal": {"policy_version": "v1"},
            },
            "review_condition": {"after_days": 3},
        }
    )
    assert projected["maturity_state"] == "sufficient"
    assert projected["policy_constraints"] == {
        "numeric_policy": "v1",
        "signal_policy": "v1",
    }
    assert projected["review_after"]


# ── freshness exactness ──────────────────────────────────────────────────


def test_freshness_rejects_derived_through_above_actual_max(store: StateStore) -> None:
    store.append_observation(
        observed_at="2026-08-10T00:00:00Z",
        platform="google",
        facts={"spend": 1.0},
    )
    store.append_change(change_type="budget", direction="increase")
    current_path = store.context.current_state_path
    document = json.loads(current_path.read_text(encoding="utf-8"))
    document["derived_through_sequence"] = 999  # above the real max of 2
    current_path.write_text(json.dumps(document), encoding="utf-8")
    current = store.current_state()
    assert current["derived_through_sequence"] == 2  # rebuilt, not trusted
    report = store.verify()
    assert report["healthy"]


# ── guard bounds ─────────────────────────────────────────────────────────


def test_guard_rejects_oversized_collection(store: StateStore) -> None:
    with pytest.raises(StatePayloadError, match="collection has"):
        store.append_observation(
            observed_at="2026-08-10T00:00:00Z",
            platform="google",
            facts={"values": list(range(MAX_COLLECTION_ITEMS + 1))},
        )
    assert store.status()["event_count"] == 0


def test_guard_rejects_oversized_mapping(store: StateStore) -> None:
    with pytest.raises(StatePayloadError, match="mapping has"):
        store.append_observation(
            observed_at="2026-08-10T00:00:00Z",
            platform="google",
            facts={f"metric_{index}": index for index in range(MAX_MAPPING_KEYS + 1)},
        )
    assert store.status()["event_count"] == 0


def test_guard_rejects_oversized_payload_bytes(store: StateStore) -> None:
    # A single string under the per-string limit but with enough total size
    # to exceed the payload byte budget.
    chunk = "x" * 2000
    with pytest.raises(StatePayloadError, match="bytes"):
        store.append_observation(
            observed_at="2026-08-10T00:00:00Z",
            platform="google",
            facts={
                f"f_{index}": chunk for index in range(MAX_PAYLOAD_BYTES // 2000 + 2)
            },
        )
    assert store.status()["event_count"] == 0


def test_guard_rejects_embedded_email_in_sentence(store: StateStore) -> None:
    with pytest.raises(StatePayloadError, match="email address"):
        store.append_decision(
            decision_class="wait",
            reason="Contact client" + "@" + "example.com tomorrow",
        )


def test_guard_rejects_embedded_credentials(store: StateStore) -> None:
    for text in (
        "Authorization=" + "Bearer" + " abc123",
        "redirect?token=" + "xyz789",
        "api_key=" + "sk_live_1234",
    ):
        with pytest.raises(StatePayloadError, match="credential/token"):
            store.append_observation(
                observed_at="2026-08-10T00:00:00Z",
                platform="google",
                facts={"ctr": 0.02, "note": text},
            )
    assert store.status()["event_count"] == 0


def test_guard_allows_plain_product_url_and_ad_metrics() -> None:
    # Plain URLs and normal platform metrics must keep passing.
    check_state_payload(
        {
            "ctr": 0.02,
            "cpm": 12.5,
            "frequency": 2.3,
            "purchase_cpa": 8.0,
            "tCPA": 5.0,
            "install_rate": 0.4,
            "landing_url": "https://example.com/product",
            "note": "see https://example.com/docs for reference",
        },
        context="meta-facts",
    )
