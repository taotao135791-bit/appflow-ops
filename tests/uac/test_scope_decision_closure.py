"""v3.4.2 scope & decision safety closure tests.

Covers the seven focus scenarios: cross-platform Change target, Outcome
scope inheritance, full-permission execution-claim invariant, constrained
candidate non-persistence, diagnostic-claim safety, run-local reset, and
legacy compatibility.
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
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


def _google_metrics(**overrides):
    metrics = {
        "spend": 900.0,
        "installs": 120,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


# ── Scenario 1: cross-platform Change requires explicit target ───────────


def test_cross_platform_change_without_target_rejected(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        _google_metrics(), platform="google_ads", observed_at="2026-08-11T09:00:00Z"
    )
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    with pytest.raises(ContractError, match="explicit target_platform"):
        run.record_confirmed_change(change_type="budget", direction="increase")
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["change"] == 0  # nothing written


def test_cross_platform_change_with_valid_target_persists(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        _google_metrics(), platform="google_ads", observed_at="2026-08-11T09:00:00Z"
    )
    change_id = run.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=10.0,
        target_platform="meta",
    )
    run.finish()
    assert change_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    change = store.get_event(change_id)
    assert change["platform"] == "meta"
    # Meta-filtered retrieval sees the change; TikTok does not.
    assert (
        store.get_recent_changes(limit=10, platform="meta")[0]["event_id"] == change_id
    )
    assert store.get_recent_changes(limit=10, platform="tiktok") == ()


def test_cross_platform_change_with_invalid_target_rejected(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    with pytest.raises(ContractError, match="outside the run"):
        run.record_confirmed_change(
            change_type="budget",
            direction="decrease",
            target_platform="tiktok",
        )
    run.finish()


# ── Scenario 2: cross-platform Outcome scope inheritance ─────────────────


def test_cross_platform_outcome_inherits_scope(workspace) -> None:
    _set_permission(workspace, ["recommend"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        _google_metrics(), platform="google_ads", observed_at="2026-08-11T09:00:00Z"
    )
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(
        decision_class="investigate",
        reason="两个平台支付一起掉，先查产品支付漏斗",
        diagnosis_confidence="tentative",
    )
    run.finish()
    assert decision_id is not None
    # Day 2: outcome inherits the cross-platform scope from the decision.
    day2 = PlatformOperationalRun(workspace)
    day2.begin()
    outcome_id = day2.record_outcome(
        outcome_class="inconclusive", decision_id=decision_id
    )
    day2.finish()
    assert outcome_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    outcome = store.get_event(outcome_id)
    assert outcome["platform"] == "cross_platform"
    assert outcome["payload"]["platform_scope"] == ["google_ads", "meta"]
    # Platform-filtered retrieval: visible for meta and google, not tiktok.
    meta_outcomes = store.get_recent_outcomes(limit=10, platform="meta")
    google_outcomes = store.get_recent_outcomes(limit=10, platform="google_ads")
    tiktok_outcomes = store.get_recent_outcomes(limit=10, platform="tiktok")
    assert outcome_id in {event["event_id"] for event in meta_outcomes}
    assert outcome_id in {event["event_id"] for event in google_outcomes}
    assert tiktok_outcomes == ()


def test_outcome_conflicting_platform_and_cross_scope_rejected(workspace) -> None:
    _set_permission(workspace, ["recommend"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    run.record_observation(
        _google_metrics(), platform="google_ads", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="investigate", reason="查支付漏斗")
    run.finish()
    assert decision_id is not None
    day2 = PlatformOperationalRun(workspace)
    day2.begin()
    with pytest.raises(ContractError, match="conflicts"):
        day2.record_outcome(
            outcome_class="improved",
            decision_id=decision_id,
            platform="tiktok",
        )
    day2.finish()


# ── Scenario 3: Decision != Change under every permission ────────────────


@pytest.mark.parametrize(
    "capabilities",
    [[], ["recommend"], ["budget", "bid"], ["budget", "bid", "creative", "full"]],
)
def test_execution_claim_rejected_in_decision_for_all_permissions(
    workspace, capabilities
) -> None:
    _set_permission(workspace, capabilities)
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个广告组是不是该关了？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    rejected_id = run.record_decision(
        decision_class="pause", reason="已经暂停 Meta 广告组"
    )
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.outcome == "rejected"
    assert run.last_verdict.reason_code == "execution_claim_in_decision"
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 0


def test_full_permission_recommend_and_change_paths(workspace) -> None:
    _set_permission(workspace, ["budget", "bid", "creative", "full"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个广告组是不是该关了？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    # 1. recommend pause → Decision allowed
    decision_id = run.record_decision(decision_class="pause", reason="建议暂停")
    assert decision_id is not None
    # 2. execution claim written as Decision → rejected
    rejected_id = run.record_decision(
        decision_class="pause", reason="已暂停", execution_status="paused"
    )
    assert rejected_id is None
    # 3. confirmed executed pause → Change allowed
    change_id = run.record_confirmed_change(
        change_type="campaign",
        direction="pause",
    )
    run.finish()
    assert change_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 1
    assert store.status()["events_by_type"]["change"] == 1


# ── Scenario 4: constrained candidate never persists ─────────────────────


def test_cap_20pct_constrained_candidate_not_persisted(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Meta 这两天为什么越来越贵？",
        policy_state="cap_20pct",
    )
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    rejected_id = run.record_decision(
        decision_class="increase", reason="建议预算提高 100%"
    )
    assert rejected_id is None  # constrained without validated candidate
    assert run.last_verdict is not None
    assert run.last_verdict.outcome == "constrained"
    assert run.last_verdict.reason_code == "policy_cap_20pct"
    assert "re_decide_within_cap" in run.last_verdict.allowed_next_actions
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 0  # never written


def test_staged_required_constrained_candidate_not_persisted(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Meta 这两天为什么越来越贵？",
        policy_state="staged_required",
    )
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    rejected_id = run.record_decision(
        decision_class="increase", reason="立即大幅提高预算"
    )
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "policy_staged_required"
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 0


def test_allowed_candidate_still_persists(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(
        decision_class="decrease",
        reason="预算降低 10%（在安全范围内）",
        review_condition="review after 3 days",
    )
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert (
        decision["payload"]["policy_constraints"]["safety_result"]["outcome"]
        == "allowed"
    )


# ── Scenario 5: diagnostic claim safety ──────────────────────────────────


def test_invalid_measurement_blocks_confirmed_diagnosis(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    # Action is observe (safe) but the claim is confirmed: must reject.
    rejected_id = run.record_decision(
        decision_class="observe",
        reason="支付漏斗已经确认崩溃",
        diagnosis_confidence="confirmed",
    )
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "measurement_invalid_diagnosis"
    # Tentative hypothesis stays allowed.
    tentative_id = run.record_decision(
        decision_class="investigate",
        reason="支付测量可能有问题，需要验证",
        diagnosis_confidence="tentative",
    )
    assert tentative_id is not None
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 1


def test_insufficient_maturity_blocks_confirmed_diagnosis(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="TT还是没量")
    run.record_observation(
        {
            "spend": 210.0,
            "clicks": 3000,
            "ctr": 0.02,
            "installs": 60,
            "measurement_state": "stable",
            "maturity_state": "insufficient",
        },
        platform="tiktok",
        observed_at="2026-08-11T09:00:00Z",
    )
    rejected_id = run.record_decision(
        decision_class="replace",
        reason="素材已经确认衰减",
        diagnosis_confidence="confirmed",
    )
    assert rejected_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "maturity_insufficient_diagnosis"
    possible_id = run.record_decision(
        decision_class="observe",
        reason="素材可能衰减，继续观察",
        diagnosis_confidence="tentative",
    )
    assert possible_id is not None
    run.finish()


def test_diagnosis_confidence_persisted_with_decision(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(
        decision_class="investigate",
        reason="可能是 auction pressure",
        diagnosis_confidence="probable",
    )
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["payload"]["diagnosis_confidence"] == "probable"


def test_cross_platform_mixed_measurement_no_confirmed_diagnosis(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("google_ads", "meta"))
    run.record_observation(
        _google_metrics(measurement_state="stable"),
        platform="google_ads",
        observed_at="2026-08-11T09:00:00Z",
    )
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-11T09:00:00Z",
    )
    run.finish()
    cross = PlatformOperationalRun(workspace)
    cross.begin(request_text="Google 和 Meta 支付一起掉了，是产品问题吗？")
    rejected_id = cross.record_decision(
        decision_class="investigate",
        reason="已确认是产品支付问题",
        diagnosis_confidence="confirmed",
    )
    assert rejected_id is None
    assert cross.last_verdict is not None
    assert cross.last_verdict.reason_code == "measurement_invalid_diagnosis"
    tentative_id = cross.record_decision(
        decision_class="investigate",
        reason="产品支付问题可能性上升，先验证",
        diagnosis_confidence="tentative",
    )
    assert tentative_id is not None
    cross.finish()


# ── Scenario 7: run-local reset ──────────────────────────────────────────


def test_run_reuse_resets_all_run_local_state(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    # Run 1: Meta with a verdict.
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    run.record_decision(decision_class="decrease", reason="降预算")
    assert run.last_verdict is not None
    run.finish()
    # Run 2: TikTok — no Meta residue anywhere.
    run.begin(request_text="TT还是没量")
    assert run.platform_scope == ("tiktok",)  # no cross-platform scope leak
    assert run._current_observations == {}  # no Meta current observation leak
    assert run._persistence_warnings == []
    assert run.last_verdict is None  # no previous verdict leak
    context = run.operational_context()
    assert context.current_observation is None
    assert context.current_observations == {}
    run.record_observation(
        {
            "spend": 210.0,
            "ctr": 0.02,
            "installs": 60,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="tiktok",
        observed_at="2026-08-11T09:00:00Z",
    )
    assert context is not run.operational_context()
    assert run.operational_context().current_observation["platform"] == "tiktok"
    run.finish()


# ── legacy compatibility ─────────────────────────────────────────────────


def test_legacy_outcome_without_scope_readable(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    legacy_id = store.append_outcome(
        outcome_class="inconclusive",
        platform="meta",
        # platform_scope absent: v3.4.1 shape
    )
    assert store.get_event(legacy_id)["payload"]["outcome_class"] == "inconclusive"
    assert store.rebuild_current_state()["event_count"] == 1
    assert (
        store.get_recent_outcomes(limit=10, platform="meta")[0]["event_id"] == legacy_id
    )
    # Older shape: no platform at all — readable, not broadcast.
    older_id = store.append_outcome(outcome_class="neutral")
    assert store.get_event(older_id) is not None
    assert store.get_recent_outcomes(limit=10, platform="tiktok") == ()
