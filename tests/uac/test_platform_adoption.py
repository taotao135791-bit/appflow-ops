"""v3.3.4 platform adoption: Meta / TikTok / Creative consume AppFlow Core
through the shared runtime, state, and reasoning contracts — never through
copied loops or new state types. Cross-platform stays inside one workspace;
cross-workspace evidence stays denied.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.platform_adapters import (
    CREATIVE,
    META,
    TIKTOK,
    PlatformAdapter,
)
from appflow_ops.uac.run_lifecycle import (
    AppFlowRuntime,
    classify_state_access,
)
from appflow_ops.uac.state_runtime import StateSession
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _meta_day1(session: StateSession, *, platform: str = "meta") -> str:
    facts = META.project_observation(
        {
            "spend": 320.0,
            "ctr": 0.008,
            "cpm": 14.2,
            "frequency": 3.1,
            "installs": 40,
            "cpa": 8.0,
            "measurement_state": "stable",
        }
    )
    observation_id = session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform=platform,
        facts=facts,
        source_type="pasted_table",
    )
    session.record_decision(
        decision_class="replace",
        reason="CTR down while frequency up",
        origin="agent_constrained",
        review_condition="review new creative after 3 days",
    )
    assert observation_id is not None
    return observation_id


# ── adapter contract ─────────────────────────────────────────────────────


def test_meta_adapter_projects_sparse_facts_and_hypotheses() -> None:
    assert META.platform == "meta"
    assert "creative_fatigue" in META.hypothesis_families
    assert "auction_pressure" in META.hypothesis_families
    facts = META.project_observation(
        {
            "spend": 320.0,
            "ctr": 0.008,
            "cpm": 14.2,
            "frequency": 3.1,
            "purchases": 12,
            "purchase_cpa": 26.7,
            "account_id": "123-456-7890",  # must never be projected
            "ad_copy": "full creative text",  # must never be projected
        }
    )
    assert facts["spend"] == 320.0
    assert facts["frequency"] == 3.1
    assert "account_id" not in facts
    assert "ad_copy" not in facts
    assert isinstance(META, PlatformAdapter)


def test_tiktok_and_creative_adapters_exist() -> None:
    assert TIKTOK.platform == "tiktok"
    assert "creative_delivery_decay" in TIKTOK.hypothesis_families
    assert CREATIVE.platform == "creative"
    assert "fatigue" in CREATIVE.hypothesis_families
    assert len(CREATIVE.hypothesis_families) >= 5


# ── Meta follow-up through the real runtime ──────────────────────────────


def test_meta_followup_loads_workspace_state(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    _meta_day1(session)
    # Day 2: "这个素材现在呢?" — the runtime classifies it as a follow-up
    # and loads the workspace's Meta history automatically.
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="这个素材现在呢？")
    assert runtime.state_loaded
    context = runtime.state_context()
    assert context is not None
    assert context["last_decision"]["payload"]["decision_class"] == "replace"
    assert context["last_observation"]["payload"]["facts"]["ctr"] == 0.008
    assert context["pending_review"] is not None
    runtime.finish_run()


def test_meta_observation_and_decision_persist_through_shared_state(
    workspace,
) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    observation_id = _meta_day1(session)
    store = StateStore(RunContext.from_workspace(workspace))
    events = store.status()["events_by_type"]
    assert events["observation"] == 1
    assert events["decision"] == 1
    observation = store.get_event(observation_id)
    assert observation["platform"] == "meta"
    assert observation["payload"]["facts"]["frequency"] == 3.1
    # A recommendation never became a Change.
    assert events["change"] == 0


# ── TikTok adoption ──────────────────────────────────────────────────────


def test_tiktok_followup_reads_workspace_state(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    facts = TIKTOK.project_observation(
        {
            "spend": 210.0,
            "clicks": 3000,
            "ctr": 0.02,
            "installs": 60,
            "click_to_install_rate": 0.02,
            "delivery_state": "limited",
        }
    )
    session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="tiktok",
        facts=facts,
        source_type="export",
    )
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="TT还是没量")
    assert runtime.state_loaded
    context = runtime.state_context()
    assert context["last_observation"]["platform"] == "tiktok"
    assert (
        context["last_observation"]["payload"]["facts"]["delivery_state"] == "limited"
    )
    runtime.finish_run()


def test_tiktok_term_question_skips_state(workspace) -> None:
    assert classify_state_access("TikTok CPM 是什么？") == "not_needed"
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="TikTok CPM 是什么？")
    assert not runtime.state_loaded
    assert runtime.session.store.status()["event_count"] == 0
    runtime.finish_run()


# ── Creative diagnosis ───────────────────────────────────────────────────


def test_creative_question_enters_operational_reasoning(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="creative",
        facts={
            "ctr": 0.006,
            "spend": 150.0,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        source_type="screenshot",
    )
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="这个素材还能跑吗？")
    assert runtime.state_loaded
    context = runtime.state_context()
    assert context["last_observation"]["platform"] == "creative"
    # The creative hypothesis families are available to the reasoning layer.
    assert "fatigue" in CREATIVE.hypothesis_families
    runtime.finish_run()


def test_creative_decision_uses_shared_classes(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="replace",  # shared enum, not a new CreativeMemory type
        reason="CTR decayed below threshold for 5 days",
        origin="agent_constrained",
        review_condition="retest after new asset ships",
    )
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["type"] == "decision"
    assert decision["payload"]["decision_class"] == "replace"


# ── cross-platform, same workspace ───────────────────────────────────────


def test_cross_platform_same_workspace_evidence_available(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    _meta_day1(session)
    session.record_observation(
        observed_at="2026-08-10T09:00:00Z",
        platform="google_ads",
        facts={
            "spend": 900.0,
            "installs": 120,
            "registrations": 18,
            "payments": 2,
            "measurement_state": "stable",
        },
        source_type="deterministic_engine",
    )
    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="两个平台都掉了，是不是产品问题？")
    assert runtime.state_loaded
    context = runtime.state_context()
    assert context is not None
    recent = context["recent"]["observations"]
    platforms = {event["platform"] for event in recent}
    assert platforms == {"meta", "google_ads"}
    assert "google_ads" in platforms and "meta" in platforms
    runtime.finish_run()


def test_cross_platform_never_leaks_other_workspace(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("ios-main", base_dir=base, client_label="acme")
    workspace_b = initialize_workspace(
        "android-main", base_dir=base, client_label="beta"
    )
    session_a = StateSession(RunContext.from_workspace(workspace_a))
    session_b = StateSession(RunContext.from_workspace(workspace_b))
    _meta_day1(session_a)
    _meta_day1(session_b)  # B has a similar Meta issue
    runtime = AppFlowRuntime(workspace_a)
    runtime.begin_run(request_text="两个平台都掉了，是不是产品问题？")
    context = runtime.state_context()
    assert context is not None
    assert context["workspace_id"] == session_a.context.workspace_id
    assert context["workspace_id"] != session_b.context.workspace_id
    assert context["current_state"]["last_observation_id"] is not None
    # B's state count is untouched by A's reasoning.
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    assert store_b.status()["event_count"] == 2  # exactly B's own events
    runtime.finish_run()
