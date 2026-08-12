"""v3.4.4 safety context consistency tests.

Covers: validator/persisted Decision sharing the same canonical safety
context, unified fail-closed enum validation, cross-platform Outcome scope
membership, explicit cross_platform scope preservation, StateStore platform
attribution defense-in-depth, and legacy compatibility.
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


def _meta_metrics(**overrides):
    metrics = {
        "spend": 320.0,
        "ctr": 0.008,
        "installs": 40,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


# ── Scenario 1: safety metadata preservation ─────────────────────────────


def test_persisted_decision_keeps_validator_safety_context(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="replace", reason="建议换素材")
    assert decision_id is not None
    assert run.last_verdict is not None and run.last_verdict.outcome == "allowed"
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    payload = decision["payload"]
    # What was validated must be what was persisted — NOT unknown.
    assert payload["measurement_state"] == "stable"
    assert payload["maturity_state"] == "sufficient"


def test_semantic_digest_uses_real_safety_states(workspace) -> None:
    session = StateSession(RunContext.from_workspace(workspace))
    id_a = session.record_decision(
        decision_class="observe",
        reason="继续观察",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
    )
    id_b = session.record_decision(
        decision_class="observe",
        reason="继续观察",
        measurement_state="invalid",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
    )
    assert id_a is not None
    assert id_b is not None  # different safety states → different identity
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["decision"] == 2


# ── Scenario 2-3: malformed enums fail closed ────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"measurement_state": "invlaid"},
        {"measurement_state": "STABLE"},
        {"measurement_state": "stable "},
        {"maturity_state": "insufficent"},
        {"maturity_state": "sufficient "},
        {"policy_state": "forbid_numeric "},
        {"policy_state": "CAP_20PCT"},
        {"permission_state": "full_acess"},
        {"permission_state": "READ_ONLY"},
    ],
)
def test_malformed_safety_enums_fail_closed(kwargs) -> None:
    with pytest.raises(ContractError):
        validate_decision_action(decision_class="wait", reason="继续观察", **kwargs)


def test_canonical_unknown_remains_valid() -> None:
    verdict = validate_decision_action(
        decision_class="wait",
        reason="确实不知道，先等",
        measurement_state="unknown",
        maturity_state="unknown",
        policy_state="none",
        permission_state="read_only",
    )
    assert verdict.outcome == "allowed"


def test_runtime_malformed_measurement_rejects_before_persistence(
    workspace,
) -> None:
    # Runtime measurement states come from observations (already canonical),
    # so malformed values can only arrive via direct paths; every layer
    # must fail closed — StateSession (persistence) included.
    session = StateSession(RunContext.from_workspace(workspace))
    with pytest.raises(ContractError, match="unknown measurement_state"):
        session.record_decision(
            decision_class="decrease",
            reason="降预算",
            measurement_state="invlaid",
            maturity_state="sufficient",
            confidence="medium",
            origin="agent_constrained",
        )


def test_runtime_malformed_policy_cannot_disable_policy_gate(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    # Malformed explicit policy fails closed at begin() — it must never be
    # silently degraded to "none" (which would disable the policy gate).
    with pytest.raises(ContractError, match="invalid policy_state"):
        run.begin(
            request_text="Meta 这两天为什么越来越贵？",
            policy_state="forbid_numeric ",
        )
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"].get("decision", 0) == 0


# ── Scenario 4: cross-platform scope membership ──────────────────────────


def test_change_outside_decision_scope_rejected(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="investigate",
        reason="查漏斗",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("google_ads", "tiktok"),
    )
    change_id = session.record_confirmed_change(
        change_type="budget", direction="decrease", platform="meta"
    )
    assert decision_id is not None and change_id is not None
    run = PlatformOperationalRun(workspace)
    run.begin()
    with pytest.raises(ContractError, match="outside the linked"):
        run.record_outcome(
            outcome_class="improved",
            decision_id=decision_id,
            change_id=change_id,
        )
    run.finish()


# ── Scenario 5: valid narrowing ──────────────────────────────────────────


def test_change_inside_decision_scope_narrows_outcome(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="investigate",
        reason="查漏斗",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("google_ads", "meta"),
    )
    change_id = session.record_confirmed_change(
        change_type="budget", direction="decrease", platform="meta"
    )
    assert decision_id is not None and change_id is not None
    run = PlatformOperationalRun(workspace)
    run.begin()
    outcome_id = run.record_outcome(
        outcome_class="improved",
        decision_id=decision_id,
        change_id=change_id,
    )
    run.finish()
    assert outcome_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    outcome = store.get_event(outcome_id)
    assert outcome["platform"] == "meta"
    assert "platform_scope" not in outcome["payload"]


# ── Scenario 6: explicit cross_platform keeps inherited scope ────────────


def test_explicit_cross_platform_outcome_keeps_scope(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="investigate",
        reason="查漏斗",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("google_ads", "meta"),
    )
    assert decision_id is not None
    run = PlatformOperationalRun(workspace)
    run.begin()
    outcome_id = run.record_outcome(
        outcome_class="inconclusive",
        decision_id=decision_id,
        platform="cross_platform",  # explicit: must not erase scope
    )
    run.finish()
    assert outcome_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    outcome = store.get_event(outcome_id)
    assert outcome["platform"] == "cross_platform"
    assert outcome["payload"]["platform_scope"] == ["google_ads", "meta"]


def test_explicit_incompatible_platform_rejected(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    session = StateSession(RunContext.from_workspace(workspace))
    decision_id = session.record_decision(
        decision_class="investigate",
        reason="查漏斗",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("google_ads", "tiktok"),
    )
    assert decision_id is not None
    run = PlatformOperationalRun(workspace)
    run.begin()
    with pytest.raises(ContractError, match="conflicts with the derived"):
        run.record_outcome(
            outcome_class="improved",
            decision_id=decision_id,
            platform="meta",  # meta ∉ [google_ads, tiktok]
        )
    run.finish()


# ── StateStore platform attribution defense-in-depth ─────────────────────


def test_store_rejects_contradictory_single_platform_scope(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    with pytest.raises(ContractError, match="cannot carry a platform_scope"):
        store.append_decision(
            decision_class="investigate",
            reason="查漏斗",
            measurement_state="stable",
            maturity_state="sufficient",
            confidence="medium",
            origin="agent_constrained",
            platform="meta",
            platform_scope=("meta", "google_ads"),
        )


def test_store_rejects_cross_platform_without_scope(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    with pytest.raises(ContractError, match=">= 2 unique platforms"):
        store.append_outcome(outcome_class="neutral", platform="cross_platform")


def test_store_accepts_valid_attribution_and_canonicalizes(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    decision_id = store.append_decision(
        decision_class="investigate",
        reason="查漏斗",
        measurement_state="stable",
        maturity_state="sufficient",
        confidence="medium",
        origin="agent_constrained",
        platform="cross_platform",
        platform_scope=("meta", "google_ads", "meta"),  # dup + unsorted
    )
    event = store.get_event(decision_id)
    assert event["payload"]["platform_scope"] == ["google_ads", "meta"]
    single_id = store.append_decision(
        decision_class="wait",
        reason="继续观察",
        measurement_state="unknown",
        maturity_state="unknown",
        confidence="low",
        origin="agent_constrained",
        platform="meta",
    )
    assert store.get_event(single_id)["platform"] == "meta"


def test_legacy_events_without_platform_still_readable(workspace) -> None:
    store = StateStore(RunContext.from_workspace(workspace))
    store.ensure_initialized()
    legacy_id = store.append_decision(
        decision_class="wait",
        reason="继续观察",
        measurement_state="unknown",
        maturity_state="unknown",
        confidence="low",
        origin="agent_constrained",
        # platform absent: legacy shape
    )
    assert store.get_event(legacy_id)["platform"] is None
    assert store.rebuild_current_state()["event_count"] == 1
