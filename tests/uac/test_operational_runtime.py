"""v3.4.0 platform operational runtime tests.

The operational lifecycle goes through PlatformOperationalRun — tests never
fake it with manual StateSession.record_* calls. Covers platform-aware
retrieval (starvation regression), per-platform projection, safety gates,
cross-platform same-workspace E2E, and cross-workspace denial.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.evals.safety import (
    ReasoningScenario,
    derive_expected_behavior,
)
from appflow_ops.runtime import (
    CREATIVE,
    META,
    TIKTOK,
    PlatformOperationalRun,
    detect_domain,
    detect_platforms,
)
from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _meta_metrics(**overrides: float | str) -> dict:
    metrics: dict = {
        "spend": 320.0,
        "ctr": 0.008,
        "cpm": 14.2,
        "frequency": 3.1,
        "installs": 40,
        "cpa": 8.0,
        "purchase_cpa": 26.0,
        "learning_state": "learning",
        "click_to_install_rate": 0.05,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


def _tiktok_metrics(**overrides: float | str) -> dict:
    metrics: dict = {
        "spend": 210.0,
        "clicks": 3000,
        "ctr": 0.02,
        "installs": 60,
        "click_to_install_rate": 0.02,
        "install_to_purchase_rate": 0.08,
        "creative_delivery_state": "decaying",
        "cost_per_result": 3.5,
        "delivery_state": "limited",
        "measurement_state": "stable",
        "maturity_state": "sufficient",
    }
    metrics.update(overrides)
    return metrics


# ── platform detection ───────────────────────────────────────────────────


def test_detect_platforms() -> None:
    assert detect_platforms("Meta 这两天为什么越来越贵？") == ("meta",)
    assert detect_platforms("TT还是没量") == ("tiktok",)
    assert detect_platforms("这个素材还能跑吗？") == ()
    assert detect_domain("这个素材还能跑吗？") == "creative"
    assert detect_domain("Meta 素材是不是衰减") == "creative"
    assert detect_platforms("Google 和 Meta 都掉了") == ("google_ads", "meta")
    assert detect_platforms("CTR 是什么？") == ()


# ── platform-aware retrieval: starvation regression (Part 14/52) ─────────


def test_cross_platform_retrieval_does_not_starve_google(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("google_ads", "meta"))
    # Meta writes 10 recent observations; Google only 2, both OLDER.
    for index in range(10):
        run.record_observation(
            _meta_metrics(spend=100.0 + index),
            platform="meta",
            observed_at=f"2026-08-0{index + 1}T09:00:00Z",
        )
    # (out-of-scope evidence is rejected by the scope boundary; only
    # in-scope platforms are written here)
    run.record_observation(
        {"spend": 900.0, "installs": 120, "measurement_state": "stable"},
        platform="google_ads",
        observed_at="2026-08-01T09:00:00Z",
    )
    run.finish()

    # Cross-platform follow-up: both platforms must be present in context.
    followup = PlatformOperationalRun(workspace)
    followup.begin(request_text="Google 和 Meta 都怎么了？")
    assert followup.state_loaded
    context = followup.operational_context()
    assert context.state_context is not None
    platforms = context.state_context["platforms"]
    assert "google_ads" in platforms
    assert "meta" in platforms
    google_events = context.state_context["by_platform"]["google_ads"]["observations"]
    meta_events = context.state_context["by_platform"]["meta"]["observations"]
    assert google_events, "Google evidence must not be starved out"
    assert len(google_events) == 1
    assert len(meta_events) == 3  # bounded per platform
    followup.finish()


def test_single_platform_request_only_loads_that_platform(workspace) -> None:
    # History is written per-platform by scoped runs.
    meta_run = PlatformOperationalRun(workspace)
    meta_run.begin(request_text="Meta 这两天为什么越来越贵？")
    meta_run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-01T09:00:00Z"
    )
    meta_run.finish()
    tiktok_run = PlatformOperationalRun(workspace)
    tiktok_run.begin(request_text="TT还是没量")
    tiktok_run.record_observation(
        _tiktok_metrics(), platform="tiktok", observed_at="2026-08-01T09:00:00Z"
    )
    tiktok_run.finish()

    followup = PlatformOperationalRun(workspace)
    followup.begin(request_text="Meta 这两天为什么越来越贵？")
    context = followup.operational_context()
    platforms = context.state_context["platforms"]
    assert platforms == ("meta",)
    assert context.state_context["by_platform"]["meta"]["observations"]
    followup.finish()


def test_per_platform_retrieval_stays_bounded(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    for index in range(10):
        run.record_observation(
            _meta_metrics(spend=100.0 + index),
            platform="meta",
            observed_at=f"2026-08-0{index + 1}T09:00:00Z",
        )
    run.finish()
    followup = PlatformOperationalRun(workspace)
    followup.begin(request_text="Meta 为什么越来越贵？")
    context = followup.operational_context()
    meta = context.state_context["by_platform"]["meta"]
    assert len(meta["observations"]) <= 3
    assert len(meta["changes"]) <= 2
    assert len(meta["decisions"]) <= 2
    followup.finish()


# ── projection: platform-specific fields preserved (Part 16-18) ──────────


def test_meta_projection_preserves_platform_specific_fields(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    event_id = run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-01T09:00:00Z"
    )
    run.finish()
    assert event_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    event = store.get_event(event_id)
    facts = event["payload"]["facts"]
    assert facts["frequency"] == 3.1
    assert facts["purchase_cpa"] == 26.0
    assert facts["learning_state"] == "learning"
    assert facts["click_to_install_rate"] == 0.05
    assert facts["cpm"] == 14.2  # common envelope


def test_tiktok_projection_preserves_platform_specific_fields(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    event_id = run.record_observation(
        _tiktok_metrics(), platform="tiktok", observed_at="2026-08-01T09:00:00Z"
    )
    run.finish()
    assert event_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    event = store.get_event(event_id)
    facts = event["payload"]["facts"]
    assert facts["creative_delivery_state"] == "decaying"
    assert facts["install_to_purchase_rate"] == 0.08
    assert facts["click_to_install_rate"] == 0.02
    assert facts["cost_per_result"] == 3.5


def test_creative_projection_preserves_relevant_fields(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    event_id = run.record_observation(
        {
            "creative_id_local": "creative-7",
            "creative_age_bucket": "10-20d",
            "ctr": 0.006,
            "frequency": 4.2,
            "delivery_change": -0.3,
            "downstream_conversion": 0.012,
            "recent_budget_change": 0.1,
            "measurement_state": "stable",
        },
        platform="creative",
        observed_at="2026-08-01T09:00:00Z",
    )
    run.finish()
    assert event_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    event = store.get_event(event_id)
    facts = event["payload"]["facts"]
    assert facts["creative_age_bucket"] == "10-20d"
    assert facts["delivery_change"] == -0.3
    assert facts["recent_budget_change"] == 0.1
    assert facts["ctr"] == 0.006


def test_unknown_raw_fields_never_persist(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin()
    run.record_observation(
        {
            **_meta_metrics(),
            "raw_account_dump": "huge export",
            "ad_copy_full": "creative text",
            "account_id": "123-456-7890",
        },
        platform="meta",
        observed_at="2026-08-01T09:00:00Z",
    )
    run.finish()
    store = StateStore(RunContext.from_workspace(workspace))
    facts = store.get_recent_observations(limit=1)[0]["payload"]["facts"]
    assert "raw_account_dump" not in facts
    assert "ad_copy_full" not in facts
    assert "account_id" not in facts


# ── operational lifecycle E2E (Part 48-50) ───────────────────────────────


def test_meta_operational_lifecycle_auto_persists(workspace) -> None:
    """Evidence in → runtime → Observation auto-persist → context → Decision
    auto-persist. No manual StateSession calls."""
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这两天为什么越来越贵？")
    assert run.state_loaded
    observation_id = run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    assert observation_id is not None
    context = run.operational_context(META)
    assert "auction_pressure" in context.hypotheses
    assert context.safety.measurement_state == "stable"
    decision_id = run.record_decision(
        decision_class="observe",
        reason="CPM up with stable CTR and frequency; wait for learning to finish",
        evidence_refs=(observation_id,),
    )
    result = run.result(
        conclusion="cost rise with stable CTR points to auction pressure",
        primary_action="observe",
        evidence_refs=(observation_id,),
        decision_id=decision_id,
    )
    run.finish()
    assert result.decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    assert store.status()["events_by_type"]["observation"] == 1
    assert store.status()["events_by_type"]["decision"] == 1
    assert store.status()["events_by_type"]["change"] == 0


def test_tiktok_operational_lifecycle(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="TT 点击挺多，为什么安装不行？")
    observation_id = run.record_observation(
        _tiktok_metrics(), platform="tiktok", observed_at="2026-08-11T09:00:00Z"
    )
    context = run.operational_context(TIKTOK)
    assert "click_to_install_degradation" in context.hypotheses
    decision_id = run.record_decision(
        decision_class="investigate",
        reason="click volume healthy but click→install rate low; check traffic "
        "quality and store friction before touching bids",
        evidence_refs=(observation_id,),
    )
    run.finish()
    assert decision_id is not None


def test_creative_operational_lifecycle(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="这个素材还能跑吗？")
    observation_id = run.record_observation(
        {
            "creative_id_local": "creative-7",
            "creative_age_bucket": "10-20d",
            "ctr": 0.006,
            "frequency": 4.2,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="creative",
        observed_at="2026-08-11T09:00:00Z",
    )
    context = run.operational_context(CREATIVE)
    assert "fatigue" in context.hypotheses
    decision_id = run.record_decision(
        decision_class="retest",
        reason="CTR decayed with rising frequency; retest a refreshed asset "
        "before pausing the campaign",
        evidence_refs=(observation_id,),
        review_condition="compare refreshed asset CTR after 3 days",
    )
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    assert decision["payload"]["decision_class"] == "retest"


# ── safety gates on non-Google platforms (Part 51) ───────────────────────


def test_meta_measurement_invalid_blocks_confident_diagnosis() -> None:
    scenario = ReasoningScenario(
        measurement_state="invalid", maturity_state="sufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "confident_deep_event_diagnosis" in behavior.forbid
    assert "aggressive_numeric_optimization" in behavior.forbid


def test_meta_immature_blocks_aggressive_action() -> None:
    scenario = ReasoningScenario(
        measurement_state="stable", maturity_state="insufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "premature_bid_change" in behavior.forbid


def test_recommend_only_permission_cannot_claim_execution(workspace) -> None:
    # Explicit capability: recommend only ([] would be read_only).
    import yaml

    context_path = workspace.context_path
    document = yaml.safe_load(context_path.read_text(encoding="utf-8"))
    document["permissions"]["optimizer_can"] = ["recommend"]
    context_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="Meta 这个广告组是不是该关了？")
    run.record_observation(
        _meta_metrics(), platform="meta", observed_at="2026-08-11T09:00:00Z"
    )
    decision_id = run.record_decision(
        decision_class="pause",
        reason="recommendation only; operator must execute",
    )
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    decision = store.get_event(decision_id)
    # A recommendation never becomes a Change, and the permission state is
    # recorded with the decision.
    assert store.status()["events_by_type"]["change"] == 0
    assert (
        decision["payload"]["policy_constraints"]["permission_state"]
        == "recommend_only"
    )


def test_creative_insufficient_evidence_converges_to_observe(workspace) -> None:
    scenario = ReasoningScenario(
        measurement_state="unknown", maturity_state="insufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "premature_bid_change" in behavior.forbid
    run = PlatformOperationalRun(workspace)
    run.begin(request_text="这个素材还能跑吗？")
    run.record_observation(
        {
            "ctr": 0.006,
            "measurement_state": "unknown",
            "maturity_state": "insufficient",
        },
        platform="creative",
        observed_at="2026-08-11T09:00:00Z",
    )
    decision_id = run.record_decision(
        decision_class="observe",
        reason="insufficient evidence for a hard kill; observe one more window",
    )
    run.finish()
    assert decision_id is not None


# ── cross-platform E2E (Part 53/54) ──────────────────────────────────────


def test_cross_platform_e2e_both_platforms_evidence(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(platform_scope=("google_ads", "meta"))
    run.record_observation(
        _meta_metrics(ctr=0.008), platform="meta", observed_at="2026-08-10T09:00:00Z"
    )
    run.record_observation(
        {
            "spend": 900.0,
            "installs": 120,
            "registrations": 18,
            "payments": 2,
            "measurement_state": "stable",
        },
        platform="google_ads",
        observed_at="2026-08-10T09:00:00Z",
    )
    run.finish()

    followup = PlatformOperationalRun(workspace)
    followup.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    context = followup.operational_context()
    assert "google_ads" in context.state_context["platforms"]
    assert "meta" in context.state_context["platforms"]
    # Cross-platform hypothesis space is supplied to the reasoning layer.
    assert context.hypotheses
    decision_id = followup.record_decision(
        decision_class="investigate",
        reason="both platforms show deep conversion decline with stable CTR; "
        "product/funnel/measurement hypotheses rank above platform-specific ones",
    )
    result = followup.result(
        conclusion="shared funnel degradation more plausible; verify before acting",
        primary_action="investigate",
        decision_id=decision_id,
    )
    followup.finish()
    assert result.primary_action == "investigate"


def test_cross_platform_never_reads_other_workspace(tmp_path: Path) -> None:
    base = tmp_path / "workspaces"
    workspace_a = initialize_workspace("ios-main", base_dir=base, client_label="acme")
    workspace_b = initialize_workspace(
        "android-main", base_dir=base, client_label="beta"
    )
    for workspace in (workspace_a, workspace_b):
        run = PlatformOperationalRun(workspace)
        run.begin()
        run.record_observation(
            _meta_metrics(), platform="meta", observed_at="2026-08-10T09:00:00Z"
        )
        run.finish()
    followup = PlatformOperationalRun(workspace_a)
    followup.begin(request_text="Google 和 Meta 都掉了，是产品问题吗？")
    context = followup.operational_context()
    # Platform scope comes from the request (google + meta); A has no google
    # events, so that bucket is empty — but Meta shows A's own single
    # observation, never B's.
    assert "google_ads" in context.state_context["platforms"]
    assert "meta" in context.state_context["platforms"]
    assert context.state_context["by_platform"]["google_ads"]["observations"] == []
    meta_a = context.state_context["by_platform"]["meta"]["observations"]
    store_b = StateStore(RunContext.from_workspace(workspace_b))
    assert store_b.status()["event_count"] == 1  # B untouched
    assert len(meta_a) == 1  # A's own single observation only
    followup.finish()
