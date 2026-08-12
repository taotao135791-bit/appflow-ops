"""v3.4.3 run identity & semantic validation tests.

Covers: fresh run identity per begin() (new StateSession + run_id + empty
dedupe), platform-aware semantic digests, fail-closed diagnosis_confidence,
mixed-reference Outcome attribution precedence, conservative execution-claim
detection, and SafetyVerdict persistence semantics.
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
from appflow_ops.uac.safety_validator import (
    reason_contains_execution_claim,
    validate_decision_action,
)
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


def _metrics(platform: str = "meta", **overrides):
    metrics = {
        "spend": 320.0,
        "ctr": 0.008,
        "installs": 40,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


def _decision_count(workspace) -> int:
    store = StateStore(RunContext.from_workspace(workspace))
    return store.status()["events_by_type"].get("decision", 0)


# ── Scenario 1: new run identity per begin() ─────────────────────────────


def test_each_begin_creates_new_run_identity(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    session_1 = run.session
    run_id_1 = session_1.run_id
    run.finish()
    run.begin(request_text="TT还是没量")
    assert run.session is not session_1  # new StateSession object
    assert run.session.run_id != run_id_1  # new run_id
    assert run.session._written == set()  # empty dedupe cache
    assert run._current_observations == {}
    assert run.last_verdict is None
    assert run._persistence_warnings == []
    run.finish()


def test_cross_run_dedupe_does_not_swallow_second_run(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    # Run 1: Meta decrease budget.
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    first_id = run.record_decision(decision_class="decrease", reason="降低预算")
    assert first_id is not None
    run.finish()
    # Run 2: TikTok decrease budget — identical content, different run.
    run.begin(request_text="TT还是没量")
    run.record_observation(
        _metrics("tiktok"),
        platform="tiktok",
        observed_at="2026-08-12T09:00:00Z",
    )
    second_id = run.record_decision(decision_class="decrease", reason="降低预算")
    assert second_id is not None  # not swallowed by stale _written
    run.finish()
    assert _decision_count(workspace) == 2
    store = StateStore(RunContext.from_workspace(workspace))
    platforms = {
        store.get_event(decision_id)["platform"]
        for decision_id in (first_id, second_id)
    }
    assert platforms == {"meta", "tiktok"}


def test_same_payload_same_run_still_dedupes(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    first_id = run.record_decision(decision_class="decrease", reason="降低预算")
    second_id = run.record_decision(decision_class="decrease", reason="降低预算")
    run.finish()
    assert first_id is not None
    assert second_id is None  # same platform, same run → same identity
    assert _decision_count(workspace) == 1


# ── Scenario 2: same Decision different platform ─────────────────────────


def test_same_decision_different_platform_is_two_events(workspace) -> None:
    # Direct StateSession path: identical content, different platform →
    # platform is part of the business identity.
    session = StateSession(RunContext.from_workspace(workspace))
    meta_id = session.record_decision(
        decision_class="decrease",
        reason="降低预算",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="meta",
    )
    tiktok_id = session.record_decision(
        decision_class="decrease",
        reason="降低预算",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="tiktok",
    )
    assert meta_id is not None
    assert tiktok_id is not None  # platform is part of identity
    assert _decision_count(workspace) == 2


def test_cross_platform_scope_order_canonicalized(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    first_id = session.record_decision(
        decision_class="wait",
        reason="继续观察",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("google_ads", "meta"),
    )
    second_id = session.record_decision(
        decision_class="wait",
        reason="继续观察",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("meta", "google_ads"),  # reversed order
    )
    assert first_id is not None
    assert second_id is None  # canonicalized scope → same semantic identity
    assert _decision_count(workspace) == 1


def test_different_diagnosis_confidence_is_two_events(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    tentative_id = run.record_decision(
        decision_class="investigate",
        reason="可能是漏斗问题",
        diagnosis_confidence="tentative",
    )
    confirmed_id = run.record_decision(
        decision_class="investigate",
        reason="可能是漏斗问题",
        diagnosis_confidence="confirmed",
    )
    run.finish()
    assert tentative_id is not None
    assert confirmed_id is not None  # confidence is part of identity
    assert _decision_count(workspace) == 2


# ── Scenario 3: same Change different platform ───────────────────────────


def test_same_change_different_platform_is_two_events(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Google 和 Meta 都掉了")
    meta_id = run.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=10.0,
        target_platform="meta",
    )
    google_id = run.record_confirmed_change(
        change_type="budget",
        direction="increase",
        magnitude=10.0,
        target_platform="google_ads",
    )
    run.finish()
    assert meta_id is not None
    assert google_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["change"] == 2


# ── Scenario 4: invalid diagnosis confidence fails closed ────────────────


def test_runtime_rejects_malformed_diagnosis_confidence(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta", measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    # Trailing space: must NOT be normalized to "none" (which would pass).
    with pytest.raises(ContractError, match="invalid diagnosis_confidence"):
        run.record_decision(
            decision_class="observe",
            reason="支付漏斗已经确认崩溃",
            diagnosis_confidence="confirmed ",
        )
    run.finish()
    assert _decision_count(workspace) == 0


def test_state_store_direct_path_rejects_malformed_confidence(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    with pytest.raises(ContractError, match="diagnosis_confidence"):
        store.append_decision(
            decision_class="investigate",
            reason="可能是漏斗问题",
            measurement_state="stable",
            maturity_state="sufficient",
            confidence="medium",
            origin="agent_constrained",
            diagnosis_confidence="very_high",
        )


def test_all_canonical_confidence_values_accepted(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    for i, level in enumerate(("none", "tentative", "probable", "confirmed")):
        decision_id = run.record_decision(
            decision_class="investigate",
            reason=f"诊断 {i}",
            diagnosis_confidence=level,
        )
        assert decision_id is not None, level
    run.finish()
    assert _decision_count(workspace) == 4


# ── Scenario 5: mixed-reference Outcome attribution ──────────────────────


def test_cross_platform_decision_plus_meta_change_narrows_outcome(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Google 和 Meta 都掉了",
        platform_scope=("google_ads", "meta"),
    )
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="investigate", reason="查漏斗")
    change_id = run.record_confirmed_change(
        change_type="budget", direction="decrease", target_platform="meta"
    )
    run.finish()
    assert decision_id is not None and change_id is not None
    day2 = PlatformOperationalRun(workspace)
    day2.begin()
    outcome_id = day2.record_outcome(
        outcome_class="improved",
        decision_id=decision_id,
        change_id=change_id,
    )
    day2.finish()
    assert outcome_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    outcome = store.get_event(outcome_id)
    assert outcome["platform"] == "meta"  # Change attribution wins
    assert "platform_scope" not in outcome["payload"]  # scope dropped


def test_cross_platform_decision_only_keeps_scope(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Google 和 Meta 都掉了",
        platform_scope=("google_ads", "meta"),
    )
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="investigate", reason="查漏斗")
    run.finish()
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


def test_conflicting_decision_and_change_platforms_rejected(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="investigate",
        reason="查漏斗",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="meta",
    )
    change_id = session.record_confirmed_change(
        change_type="budget", direction="decrease", platform="tiktok"
    )
    assert decision_id is not None and change_id is not None
    run = PlatformOperationalRun(workspace)
    run.begin()
    with pytest.raises(ContractError, match="disagree on platform"):
        run.record_outcome(
            outcome_class="improved",
            decision_id=decision_id,
            change_id=change_id,
        )
    run.finish()


# ── Scenario 6: execution-claim detection precision ──────────────────────


@pytest.mark.parametrize(
    "reason",
    [
        "CTR changed after the audience expanded, so keep observing.",
        "CPM has improved but purchases remain weak.",
        "数据已经改善，但我建议继续观察。",
        "数据改善后我建议继续观察。",
    ],
)
def test_harmless_performance_language_allowed(reason: str) -> None:
    assert reason_contains_execution_claim(reason) is False


@pytest.mark.parametrize(
    "reason",
    [
        "已暂停 Meta 广告组",
        "预算已经从 100 调到 80",
        "We changed the bid to $25.",
        "The campaign was paused.",
        "我们调整了预算",
    ],
)
def test_true_execution_claims_detected(reason: str) -> None:
    assert reason_contains_execution_claim(reason) is True


def test_execution_claim_detector_runtime_end_to_end(workspace) -> None:
    _set_permission(workspace, ["budget", "bid", "creative", "full"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个广告组是不是该关了？")
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    allowed_id = run.record_decision(
        decision_class="observe",
        reason="CTR changed after the audience expanded, so keep observing.",
    )
    assert allowed_id is not None  # harmless language persists
    rejected_id = run.record_decision(
        decision_class="pause",
        reason="We changed the bid to $25.",
    )
    assert rejected_id is None  # true claim rejected
    assert run.last_verdict is not None
    assert run.last_verdict.reason_code == "execution_claim_in_decision"
    run.finish()
    assert _decision_count(workspace) == 1


# ── Scenario 7: SafetyVerdict persistence semantics ──────────────────────


def test_safety_verdict_accepted_means_allowed_only() -> None:
    allowed = validate_decision_action(decision_class="wait", reason="继续观察")
    constrained = validate_decision_action(
        decision_class="increase",
        reason="提高预算",
        policy_state="cap_20pct",
        permission_state="budget_bid_creative",
    )
    rejected = validate_decision_action(decision_class="pause", reason="已暂停广告组")
    assert allowed.outcome == "allowed"
    assert allowed.is_allowed is True
    assert allowed.accepted is True  # alias
    assert constrained.outcome == "constrained"
    assert constrained.is_allowed is False  # not persistable without rewrite
    assert constrained.accepted is False
    assert rejected.outcome == "rejected"
    assert rejected.is_allowed is False
    assert rejected.accepted is False


def test_constrained_candidate_still_not_persisted_via_any_helper(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？", policy_state="cap_20pct")
    run.record_observation(
        _metrics("meta"), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="increase", reason="预算提高 100%")
    assert decision_id is None
    assert run.last_verdict is not None
    assert run.last_verdict.outcome == "constrained"
    assert run.last_verdict.is_allowed is False
    run.finish()
    assert _decision_count(workspace) == 0


# ── dedupe contract regression: same observation across runs ─────────────


def test_same_observation_payload_across_runs_is_two_events(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta", spend=100.0),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    run.finish()
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _metrics("meta", spend=100.0),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 2
