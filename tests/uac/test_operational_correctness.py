"""v3.4.1 operational context & safety correctness tests.

Covers the eight focus scenarios: same-run current observation, platform
attribution & filtered retrieval, platform-scoped safety (no pollution),
multi-platform safety without scalar flattening, recommend-only /
read-only / policy enforcement, execution-claim rejection, unknown-platform
rejection, and legacy (v3.4.0) event compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.runtime import (
    META,
    PlatformOperationalRun,
)
from appflow_ops.uac.account_state import RunContext
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


def _meta_metrics(**overrides):
    metrics = {
        "spend": 320.0,
        "ctr": 0.008,
        "cpm": 14.2,
        "frequency": 3.1,
        "installs": 40,
        "cpa": 8.0,
        "purchase_cpa": 26.0,
        "click_to_install_rate": 0.05,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


def _tiktok_metrics(**overrides):
    metrics = {
        "spend": 210.0,
        "clicks": 3000,
        "ctr": 0.02,
        "installs": 60,
        "click_to_install_rate": 0.02,
        "delivery_state": "limited",
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


# ── Scenario 1: same-run current observation ─────────────────────────────


def test_same_run_current_observation_present(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(cpm=17.8, purchase_cpa=33.8),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    context = run.operational_context(META)
    assert context.current_observation is not None
    facts = context.current_observation["payload"]["facts"]
    assert facts["cpm"] == 17.8  # current evidence, not just hypotheses
    assert facts["purchase_cpa"] == 33.8
    assert facts["frequency"] == 3.1
    # Current observation is also visible per platform.
    assert context.current_observations["meta"]["payload"]["facts"]["cpm"] == 17.8
    run.finish()


def test_current_observation_overrides_stale_history(workspace) -> None:
    # History says stable; today's current evidence says invalid.
    run = PlatformOperationalRun(workspace)
    run.begin()
    run.record_observation(
        _meta_metrics(measurement_state="stable"),
        platform="meta",
        observed_at="2026-08-09T09:00:00Z",
    )
    run.finish()
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    context = run.operational_context(META)
    assert context.safety.measurement_state == "invalid"  # current wins
    run.finish()


# ── Scenario 2: Meta previous decision retrieval ─────────────────────────


def test_meta_previous_decision_retrieved_platform_filtered(workspace) -> None:
    # Meta run: observation + decision both attributed to meta.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-10T09:00:00Z"
    )
    meta_decision = run.record_decision(
        decision_class="wait",
        reason="delivery dropped; wait for learning",
    )
    run.finish()
    # TikTok run: its own decision stays separate.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="TT还是没量", platform_scope=("tiktok",))
    run.record_observation(
        _tiktok_metrics(), platform="tiktok", observed_at="2026-08-10T09:00:00Z"
    )
    tiktok_decision = run.record_decision(
        decision_class="keep",
        reason="tiktok fine",
    )
    run.finish()
    assert meta_decision is not None and tiktok_decision is not None
    store = StateStore(RunContext.from_workspace(workspace))
    meta_decisions = store.get_recent_decisions(limit=10, platform="meta")
    tiktok_decisions = store.get_recent_decisions(limit=10, platform="tiktok")
    assert [event["event_id"] for event in meta_decisions] == [meta_decision]
    assert [event["event_id"] for event in tiktok_decisions] == [tiktok_decision]
    # The persisted decisions carry platform attribution.
    assert store.get_event(meta_decision)["platform"] == "meta"
    assert store.get_event(tiktok_decision)["platform"] == "tiktok"


def test_next_day_meta_followup_finds_previous_decision(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-10T09:00:00Z"
    )
    run.record_decision(
        decision_class="wait",
        reason="delivery dropped; wait for learning",
        review_condition="review after maturity",
    )
    run.finish()
    day2 = PlatformOperationalRun(workspace)
    day2.begin(request_text="Meta 现在呢？")
    context = day2.operational_context(META)
    decisions = context.state_context["by_platform"]["meta"]["decisions"]
    assert decisions, "Meta previous decision must be retrievable"
    assert decisions[0]["payload"]["decision_class"] == "wait"
    day2.finish()


# ── Scenarios 3 & 4: platform-scoped safety ──────────────────────────────


def test_tiktok_measurement_cannot_pollute_meta(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("tiktok", "meta"))
    run.record_observation(
        _tiktok_metrics(measurement_state="stable"),
        platform="tiktok",
        observed_at="2026-08-11T09:00:00Z",  # NEWER
    )
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-10T09:00:00Z",
    )
    run.finish()
    meta_run = PlatformOperationalRun(workspace)
    meta_run.begin(request_text="Meta支付怎么掉了？")
    context = meta_run.operational_context(META)
    # Meta's own (older) invalid state wins over TikTok's newer stable.
    assert context.safety.measurement_state == "invalid"
    assert context.safety.measurement_by_platform.get("meta") == "invalid"
    assert "tiktok" not in context.safety.measurement_by_platform
    meta_run.finish()


def test_cross_platform_mixed_safety_not_flattened(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("google_ads", "meta"))
    run.record_observation(
        {"spend": 900.0, "installs": 120, "measurement_state": "stable"},
        platform="google_ads",
        observed_at="2026-08-10T09:00:00Z",
    )
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-10T09:00:00Z",
    )
    run.finish()
    cross = PlatformOperationalRun(workspace)
    cross.begin(request_text="Google 和 Meta 支付一起掉了，是产品问题吗？")
    context = cross.operational_context()
    assert context.safety.measurement_by_platform == {
        "google_ads": "stable",
        "meta": "invalid",
    }
    # Conservative aggregate: any invalid → invalid.
    assert context.safety.measurement_state == "invalid"
    cross.finish()


# ── Scenarios 5 & 6: permission / policy enforcement ─────────────────────


def test_recommend_only_allows_recommendation_but_rejects_execution_claim(
    workspace,
) -> None:
    _set_permission(workspace, ["recommend"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个广告组是不是该关了？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    allowed_id = run.record_decision(
        decision_class="pause", reason="建议暂停这个广告组"
    )
    assert allowed_id is not None
    assert run.last_verdict is not None and run.last_verdict.outcome == "allowed"
    # Execution claim in the reason must be rejected by the runtime —
    # regardless of permission level (Decision != Change invariant).
    rejected_id = run.record_decision(decision_class="pause", reason="已暂停这个广告组")
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.outcome == "rejected"
    assert run.last_verdict.reason_code == "execution_claim_in_decision"
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 1  # only the allowed one


def test_read_only_blocks_execution_actions(workspace) -> None:
    # Default workspace has no capabilities → read_only.
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个广告组是不是该关了？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    rejected_id = run.record_decision(decision_class="pause", reason="建议暂停")
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "permission_read_only"
    observe_id = run.record_decision(decision_class="observe", reason="再观察一个窗口")
    assert observe_id is not None  # diagnosis actions stay available
    run.finish()


def test_policy_forbid_numeric_rejects_numeric_decision(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Meta 这个广告组是不是该关了？",
        policy_state="forbid_numeric",
    )
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    rejected_id = run.record_decision(
        decision_class="decrease", reason="建议降低预算 20%"
    )
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "policy_forbid_numeric"
    investigate_id = run.record_decision(
        decision_class="investigate", reason="先查清原因再动预算"
    )
    assert investigate_id is not None
    run.finish()


def test_measurement_invalid_blocks_numeric_decision(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    rejected_id = run.record_decision(
        decision_class="decrease", reason="deep conversion failure confirmed, cut spend"
    )
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "measurement_invalid"
    observe_id = run.record_decision(
        decision_class="observe", reason="measurement unstable; observe first"
    )
    assert observe_id is not None
    run.finish()


def test_maturity_insufficient_blocks_aggressive_action(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="TT还是没量")
    run.record_observation(
        _tiktok_metrics(maturity_state="insufficient"),
        platform="tiktok",
        observed_at="2026-08-11T09:00:00Z",
    )
    rejected_id = run.record_decision(decision_class="decrease", reason="大砍预算")
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "maturity_insufficient"
    wait_id = run.record_decision(
        decision_class="wait", reason="数据不足，等一个决策窗口"
    )
    assert wait_id is not None
    run.finish()


def test_safety_result_recorded_with_decision(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="observe", reason="观察一个窗口")
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    safety = decision["payload"]["policy_constraints"]["safety_result"]
    assert safety["outcome"] == "allowed"
    assert (
        decision["payload"]["policy_constraints"]["permission_state"]
        == "budget_bid_creative"
    )


# ── Scenario 7: unknown platform rejection ───────────────────────────────


def test_unknown_platform_rejected_no_raw_passthrough(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    with pytest.raises(ContractError, match="no adapter registered"):
        run.record_observation(
            {
                "spend": 100,
                "account_id": "123-456-7890",
                "raw_private_data": "secret",
            },
            platform="unknown_ads_network",
            observed_at="2026-08-11T09:00:00Z",
        )
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["event_count"] == 0  # nothing persisted


def test_generic_adapter_requires_opt_in_and_allowlist(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    with pytest.raises(ContractError, match="allow_generic"):
        run.record_observation(
            {"spend": 100, "ctr": 0.01, "raw_field": "x"},
            platform="generic",
            observed_at="2026-08-11T09:00:00Z",
        )
    event_id = run.record_observation(
        {"spend": 100, "ctr": 0.01, "raw_field": "x"},
        platform="generic",
        observed_at="2026-08-11T09:00:00Z",
        allow_generic=True,
    )
    run.finish()
    assert event_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    facts = store.get_event(event_id)["payload"]["facts"]
    assert facts["spend"] == 100
    assert facts["ctr"] == 0.01
    assert "raw_field" not in facts  # allowlist only


def test_google_uses_safe_projection(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    event_id = run.record_observation(
        {
            "spend": 900.0,
            "installs": 120,
            "target_cpa": 5.0,
            "daily_budget": 100.0,
            "account_id": "987-654-3210",
        },
        platform="google_ads",
        observed_at="2026-08-11T09:00:00Z",
    )
    run.finish()
    assert event_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    facts = store.get_event(event_id)["payload"]["facts"]
    assert facts["target_cpa"] == 5.0
    assert "account_id" not in facts


# ── Scenario 8: cross-platform decision scope ────────────────────────────


def test_cross_platform_decision_scope_visibility(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        {"spend": 900.0, "measurement_state": "stable"},
        platform="google_ads",
        observed_at="2026-08-11T09:00:00Z",
    )
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(
        decision_class="investigate",
        reason="两个平台支付一起掉，先查产品支付漏斗",
    )
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["platform"] == "cross_platform"
    assert decision["payload"]["platform_scope"] == ["google_ads", "meta"]
    # Meta retrieval sees it; TikTok retrieval does not.
    meta_decisions = store.get_recent_decisions(limit=10, platform="meta")
    tiktok_decisions = store.get_recent_decisions(limit=10, platform="tiktok")
    assert decision_id in {event["event_id"] for event in meta_decisions}
    assert tiktok_decisions == ()


# ── Change / Outcome platform attribution ────────────────────────────────


def test_change_platform_attribution_and_scope_validation(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    change_id = run.record_confirmed_change(
        change_type="budget", direction="increase", magnitude=10.0
    )
    run.finish()
    assert change_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    change = store.get_event(change_id)
    assert change["platform"] == "meta"
    # Cross-platform run requires an explicit, in-scope target.
    cross = PlatformOperationalRun(workspace)
    cross.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    with pytest.raises(ContractError, match="outside the run"):
        cross.record_confirmed_change(
            change_type="budget",
            direction="decrease",
            target_platform="tiktok",  # not in scope
        )
    cross_id = cross.record_confirmed_change(
        change_type="budget",
        direction="decrease",
        target_platform="meta",
    )
    cross.finish()
    assert cross_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.get_event(cross_id)["platform"] == "meta"


def test_outcome_platform_derived_from_refs(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="observe", reason="观察一个窗口")
    assert decision_id is not None
    outcome_id = run.record_outcome(
        outcome_class="inconclusive", decision_id=decision_id
    )
    run.finish()
    assert outcome_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    outcome = store.get_event(outcome_id)
    assert outcome["platform"] == "meta"  # derived from the decision ref
    # Conflicting explicit platform is rejected.
    run = PlatformOperationalRun(workspace)
    run.begin()
    with pytest.raises(ContractError, match="conflicts"):
        run.record_outcome(
            outcome_class="inconclusive",
            decision_id=decision_id,
            platform="tiktok",
        )
    run.finish()


# ── Legacy (v3.4.0) events compatibility ─────────────────────────────────


def test_legacy_unscoped_events_readable_but_not_broadcast(workspace) -> None:
    # Write a legacy-style decision directly (no platform) as v3.4.0 did.
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    legacy_id = store.append_decision(
        decision_class="wait", reason="legacy decision without platform"
    )
    # Rebuild must not break.
    current = store.rebuild_current_state()
    assert current["event_count"] == 1
    # Unfiltered history still shows it.
    assert store.get_recent_decisions(limit=10)[0]["event_id"] == legacy_id
    # Platform-filtered retrieval never broadcasts legacy events.
    assert store.get_recent_decisions(limit=10, platform="meta") == ()
    assert store.get_recent_decisions(limit=10, platform="tiktok") == ()
    # New platform-attributed events still work alongside legacy.
    run = PlatformOperationalRun(workspace)
    run.begin()
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    meta_decision = run.record_decision(decision_class="keep", reason="meta fine")
    run.finish()
    assert meta_decision is not None
    assert (
        store.get_recent_decisions(limit=10, platform="meta")[0]["event_id"]
        == meta_decision
    )
