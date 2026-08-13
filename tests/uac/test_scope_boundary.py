"""v3.4.6 platform scope boundary tests.

Covers: observation scope enforcement (out-of-scope evidence rejected,
never persisted, never enters context), begin() scope canonicalization
(registered-only, unique, bounded, deterministic), empty-run binding to
first valid observation, exact-platform current evidence (no cross-platform
fallback), creative-as-domain separation, and regressions.
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
    detect_domain,
    detect_platforms,
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
        "installs": 40,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


# ── Scenario 1: Meta run rejects TikTok evidence ─────────────────────────


def test_out_of_scope_observation_rejected_and_not_persisted(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    with pytest.raises(ContractError, match="observation_platform_outside_run_scope"):
        run.record_observation(
            _meta_metrics(spend=999.0),
            platform="tiktok",
            observed_at="2026-08-12T09:05:00Z",
        )
    run.finish()
    # 0 TikTok observation written; Meta context untouched.
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 1
    events = store.get_recent_observations(limit=10, platform="meta")
    assert len(events) == 1
    assert events[0]["payload"]["facts"]["spend"] == 320.0
    assert store.get_recent_observations(limit=10, platform="tiktok") == ()


def test_out_of_scope_observation_never_enters_current_context(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    try:
        run.record_observation(
            _meta_metrics(spend=999.0),
            platform="tiktok",
            observed_at="2026-08-12T09:05:00Z",
        )
    except ContractError:
        pass
    context = run.operational_context()
    assert context.current_observations.keys() == {"meta"}
    assert context.current_observation["platform"] == "meta"
    run.finish()


def test_cross_platform_run_rejects_third_platform(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("meta", "tiktok"))
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    run.record_observation(
        _meta_metrics(spend=210.0, ctr=0.02),
        platform="tiktok",
        observed_at="2026-08-12T09:00:00Z",
    )
    with pytest.raises(ContractError, match="observation_platform_outside_run_scope"):
        run.record_observation(
            _meta_metrics(spend=900.0),
            platform="google_ads",
            observed_at="2026-08-12T09:00:00Z",
        )
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 2


# ── Scenario 2: no cross-platform current fallback ───────────────────────


def test_single_platform_context_without_own_evidence_is_none(workspace) -> None:
    # History has TikTok observations only.
    tiktok_run = PlatformOperationalRun(workspace)
    tiktok_run.begin(request_text="TT还是没量")
    tiktok_run.record_observation(
        _meta_metrics(spend=210.0, ctr=0.02),
        platform="tiktok",
        observed_at="2026-08-12T09:00:00Z",
    )
    tiktok_run.finish()
    # A fresh Meta run has NO Meta current observation: current_observation
    # must be None — never the TikTok evidence.
    meta_run = PlatformOperationalRun(workspace)
    meta_run.begin(request_text="Meta 这两天为什么越来越贵？")
    context = meta_run.operational_context()
    assert context.current_observation is None
    assert context.current_observations == {}
    meta_run.finish()


def test_cross_platform_context_keeps_per_platform_map(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("meta", "tiktok"))
    run.record_observation(
        _meta_metrics(measurement_state="invalid"),
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    run.record_observation(
        _meta_metrics(spend=210.0, ctr=0.02, measurement_state="stable"),
        platform="tiktok",
        observed_at="2026-08-12T09:00:00Z",
    )
    context = run.operational_context()
    # Each platform keeps its own evidence; nothing is substituted.
    assert set(context.current_observations) == {"meta", "tiktok"}
    assert (
        context.current_observations["meta"]["payload"]["facts"]["measurement_state"]
        == "invalid"
    )
    assert (
        context.current_observations["tiktok"]["payload"]["facts"]["measurement_state"]
        == "stable"
    )
    run.finish()


# ── Scenario 3: empty run binds to first observation ─────────────────────


def test_empty_run_binds_meta_and_uses_bound_scope_for_safety(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin()
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    assert run.platform_scope == ("meta",)
    decision_id = run.record_decision(decision_class="wait", reason="继续观察")
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    # Safety, attribution and persistence all saw the same Meta boundary.
    assert decision["platform"] == "meta"
    assert decision["payload"]["measurement_state"] == "stable"
    assert decision["payload"]["maturity_state"] == "sufficient"


# ── Scenario 4: bound run cannot expand ──────────────────────────────────


def test_bound_meta_run_rejects_tiktok_expansion(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    assert run.platform_scope == ("meta",)
    with pytest.raises(ContractError, match="observation_platform_outside_run_scope"):
        run.record_observation(
            _meta_metrics(spend=210.0, ctr=0.02),
            platform="tiktok",
            observed_at="2026-08-12T09:05:00Z",
        )
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 1


# ── Scenario 5: duplicate explicit scope ─────────────────────────────────


def test_duplicate_explicit_scope_canonicalizes_to_single(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("meta", "meta"))
    assert run.platform_scope == ("meta",)  # NOT cross-platform
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    decision_id = run.record_decision(decision_class="wait", reason="继续观察")
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.get_event(decision_id)["platform"] == "meta"


# ── Scenario 6: oversized explicit scope ─────────────────────────────────


def test_oversized_explicit_scope_rejected(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    with pytest.raises(ContractError, match="MAX_PLATFORM_SCOPE"):
        run.begin(
            platform_scope=("google_ads", "meta", "tiktok", "creative", "generic")
        )


# ── Scenario 7: registered-only ──────────────────────────────────────────


def test_unknown_platform_in_explicit_scope_rejected_at_begin(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    with pytest.raises(ContractError, match="no adapter registered"):
        run.begin(platform_scope=("meta", "foo"))
    with pytest.raises(ContractError, match="no adapter registered"):
        run.begin(platform_scope=("meta", "unknown_ads_network"))


# ── scope canonicalization: deterministic ordering ───────────────────────


def test_scope_order_is_canonicalized(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("meta", "google_ads", "meta"))
    assert run.platform_scope == ("google_ads", "meta")
    run2 = PlatformOperationalRun(workspace)
    run2.begin(platform_scope=("google_ads", "meta"))
    assert run2.platform_scope == ("google_ads", "meta")
    run.finish()
    run2.finish()


def test_detected_scope_uses_same_canonicalization(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 和 Google 都掉了")
    assert run.platform_scope == ("google_ads", "meta")  # sorted, detected
    run.finish()


# ── creative is a domain hint, not a platform ────────────────────────────


def test_creative_keyword_is_domain_hint_not_platform(workspace) -> None:
    assert detect_platforms("Meta 素材是不是衰减") == ("meta",)
    assert detect_domain("Meta 素材是不是衰减") == "creative"
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 素材是不是衰减")
    assert run.platform_scope == ("meta",)  # creative NOT in scope
    assert run.domain_hint == "creative"
    context = run.operational_context()
    assert context.domain_hint == "creative"
    run.finish()


def test_creative_adapter_still_available_explicitly(workspace) -> None:
    # The creative adapter remains registered and usable via explicit
    # scope (backward compatible — no migration this round).
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("creative",))
    observation_id = run.record_observation(
        {
            "creative_id_local": "creative-7",
            "creative_age_bucket": "10-20d",
            "ctr": 0.012,
        },
        platform="creative",
        observed_at="2026-08-12T09:00:00Z",
    )
    run.finish()
    assert observation_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 1


# ── regression: run reuse keeps identity semantics ───────────────────────


def test_run_reuse_does_not_inherit_previous_scope(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    assert run.platform_scope == ("meta",)
    run.finish()
    run.begin(request_text="TT还是没量")
    assert run.platform_scope == ("tiktok",)  # never inherits Meta
    run.finish()


# ── regression: v3.4.5 freshness + v3.4.4 safety context ────────────────


def test_freshness_and_safety_context_regression(workspace) -> None:
    _set_permission(workspace, ["budget", "bid"])
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(measurement_state="unknown"),  # explicit unknown
        platform="meta",
        observed_at="2026-08-12T09:00:00Z",
    )
    decision_id = run.record_decision(decision_class="observe", reason="继续观察")
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["payload"]["measurement_state"] == "unknown"
    assert decision["payload"]["maturity_state"] == "sufficient"  # absent→history


def test_safety_contamination_blocked_by_scope_boundary(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-12T09:00:00Z"
    )
    try:
        run.record_observation(
            _meta_metrics(measurement_state="stable"),
            platform="tiktok",
            observed_at="2026-08-12T09:05:00Z",
        )
    except ContractError:
        pass
    context = run.operational_context()
    # Meta safety is determined only by Meta evidence.
    assert context.safety.measurement_by_platform == {"meta": "stable"}
    run.finish()
