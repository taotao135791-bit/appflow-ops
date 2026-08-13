"""v3.5.5 convergence safety provenance tests.

Covers the last correctness gap: the evaluator already consumed
provenance-aware Safety, but convergence could still reintroduce the
aggregate Safety and let one platform's problem veto an independent
diagnosis for another platform. These tests lock:

- Safety resolution per selected evaluation scope (platform/shared/run,
  missing platform safety → unknown, never an aggregate fallback);
- platform-bound tops survive another platform's invalid/insufficient
  state; shared tops stay conservatively gated by aggregate Safety;
- top_hypothesis / top_platform / top_evaluation_scope derive from ONE
  selected evaluation (hard invariant);
- a safety block changes the action, never the ranked diagnosis identity;
- persisted Decision attribution matches the selected evaluation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.decision_intelligence import (
    SafetyContext,
    build_hypothesis_set,
    converge,
    evaluate_hypotheses,
    rank_hypotheses,
    resolve_evaluation_safety,
)
from appflow_ops.decision_intelligence.evaluator import (
    HypothesisEvaluation,
)
from appflow_ops.decision_intelligence.evidence import (
    EvidenceResult,
)
from appflow_ops.decision_intelligence.result import (
    decision_attribution,
    from_convergence,
)
from appflow_ops.runtime import (
    PlatformOperationalRun,
)
from appflow_ops.uac.account_state import RunContext
from appflow_ops.uac.state_store import StateStore
from appflow_ops.uac.workspace import initialize_workspace


@pytest.fixture()
def workspace(tmp_path: Path):
    base = tmp_path / "workspaces"
    return initialize_workspace("app-us", base_dir=base, client_label="acme")


def _safety_context(
    measurement_by_platform: dict[str, str] | None = None,
    maturity_by_platform: dict[str, str] | None = None,
    *,
    aggregate_measurement: str = "stable",
    aggregate_maturity: str = "sufficient",
) -> SafetyContext:
    return SafetyContext(
        measurement_by_platform=measurement_by_platform or {},
        maturity_by_platform=maturity_by_platform or {},
        aggregate_measurement=aggregate_measurement,
        aggregate_maturity=aggregate_maturity,
    )


def _evaluation(hypothesis_id: str, platform: str, scope: str = "platform") -> HypothesisEvaluation:
    """Minimal real evaluation: pick the spec and evaluate with no signals."""
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    spec = next(s for s in specs if s.id == hypothesis_id)
    return HypothesisEvaluation(
        hypothesis=spec,
        status="unverified",
        score=0,
        supporting=(),
        contradicting=(),
        missing=(),
        rationale=(),
        platform=platform,
    )


# ── Unit: Safety resolution per selected evaluation scope (spec §32) ─────


def test_resolve_platform_evaluation_safety() -> None:
    evaluation = _evaluation("auction_pressure", "google_ads")
    measurement, maturity = resolve_evaluation_safety(
        evaluation,
        _safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    assert (measurement, maturity) == ("stable", "sufficient")


def test_resolve_shared_evaluation_safety() -> None:
    evaluation = _evaluation("shared_product_funnel_issue", "cross_platform", "shared")
    measurement, maturity = resolve_evaluation_safety(
        evaluation,
        _safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            aggregate_measurement="invalid",
        ),
    )
    # Shared conclusions use aggregate Safety — one invalid platform gates
    # the cross-platform conclusion even though Google is stable.
    assert (measurement, maturity) == ("invalid", "sufficient")


def test_resolve_run_evaluation_safety() -> None:
    evaluation = _evaluation("platform_specific_independent_issues", None, "run")
    measurement, maturity = resolve_evaluation_safety(
        evaluation,
        _safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            aggregate_measurement="invalid",
        ),
    )
    assert (measurement, maturity) == ("invalid", "sufficient")


def test_missing_platform_safety_resolves_to_unknown() -> None:
    # Google hypothesis top, but no Google safety evidence: "unknown" —
    # never borrowed from Meta stable nor from the aggregate.
    evaluation = _evaluation("auction_pressure", "google_ads")
    measurement, maturity = resolve_evaluation_safety(
        evaluation,
        _safety_context(
            measurement_by_platform={"meta": "stable"},
            aggregate_measurement="stable",
        ),
    )
    assert (measurement, maturity) == ("unknown", "unknown")


# ── Convergence: provenance-aware Safety (spec §33) ──────────────────────


def _google_auction_evals(aggregate_measurement: str) -> tuple:
    """Meta invalid + Google stable CPM↑/CTR stable: Google auction is the
    only supported evaluation; Meta evaluations are capped by their own
    invalid state."""
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evidence = EvidenceResult(
        signals={"cpm_trend_up": True, "ctr_trend_stable": True},
        signals_by_platform={
            "meta": {},
            "google_ads": {"cpm_trend_up": True, "ctr_trend_stable": True},
        },
        shared_signals={},
    )
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state=aggregate_measurement,
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
        maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
    )
    return rank_hypotheses(evals)


def _shared_pay_drop_evals() -> tuple:
    """Meta pay↓ invalid + Google pay↓ stable: cross_pay_rate_drop fires;
    the shared product funnel ranks with evidence but is capped by
    aggregate Safety."""
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evidence = EvidenceResult(
        signals={
            "cross_pay_rate_drop": True,
            "cross_platform_comparison_available": True,
        },
        signals_by_platform={
            "meta": {"pay_rate_trend_down": True},
            "google_ads": {"pay_rate_trend_down": True},
        },
        shared_signals={
            "cross_pay_rate_drop": True,
            "cross_platform_comparison_available": True,
        },
    )
    evals = evaluate_hypotheses(
        specs,
        evidence,
        platform_scope=("google_ads", "meta"),
        measurement_state="invalid",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
        maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
    )
    return rank_hypotheses(evals)


def test_platform_top_not_vetoed_by_other_platform_invalid() -> None:
    ranked = _google_auction_evals(aggregate_measurement="invalid")
    top = ranked[0].evaluation
    assert top.hypothesis.id == "auction_pressure"
    assert top.platform == "google_ads"
    assert top.status == "supported"
    # Aggregate measurement is invalid (Meta), but the SELECTED evaluation
    # is Google-bound — convergence must use Google's own safety.
    result = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    assert result.converged is True
    assert result.decision == "wait"
    assert result.top_hypothesis == "auction_pressure"
    assert result.safety_block is None


def test_platform_top_not_vetoed_by_other_platform_insufficient() -> None:
    ranked = _google_auction_evals(aggregate_measurement="stable")
    result = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "stable", "google_ads": "stable"},
            maturity_by_platform={"meta": "insufficient", "google_ads": "sufficient"},
            aggregate_measurement="stable",
            aggregate_maturity="insufficient",
        ),
    )
    # Meta's immaturity must not turn the whole run into a wait.
    assert result.converged is True
    assert result.top_hypothesis == "auction_pressure"


def test_shared_top_still_blocked_by_one_platform_invalid() -> None:
    ranked = _shared_pay_drop_evals()
    top = ranked[0].evaluation
    # The shared diagnosis ranks (unverified with real evidence, capped by
    # aggregate Safety) — it stays the selected diagnosis.
    assert top.hypothesis.id == "shared_product_funnel_issue"
    result = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    # Shared scope → aggregate Safety → still conservatively blocked.
    assert result.converged is False
    assert result.decision == "investigate_measurement"
    assert result.safety_block == "measurement_invalid"
    # The block changes the action, NOT the ranked diagnosis identity.
    assert result.top_hypothesis == "shared_product_funnel_issue"


def test_run_top_uses_aggregate_safety() -> None:
    specs = build_hypothesis_set(platform_scope=("google_ads", "meta"))
    evals = evaluate_hypotheses(
        specs,
        {
            "signals_by_platform": {
                "meta": {"pay_rate_trend_down": True},
                "google_ads": {"pay_rate_trend_stable": True},
            },
            "shared_signals": {"platform_divergence": True},
            "signals": {"platform_divergence": True},
        },
        platform_scope=("google_ads", "meta"),
        measurement_state="invalid",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
        maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
    )
    ranked = rank_hypotheses(evals)
    run_evals = [
        item.evaluation
        for item in ranked
        if item.evaluation.hypothesis.evaluation_scope == "run"
    ]
    assert run_evals and run_evals[0].hypothesis.id == "platform_specific_independent_issues"
    result = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    assert result.converged is False
    assert result.decision == "investigate_measurement"
    assert result.safety_block == "measurement_invalid"


def test_single_platform_invalid_semantics_unchanged() -> None:
    # One-platform Meta run with invalid measurement stays conservative —
    # the provenance fix must never relax the single-platform gate.
    specs = build_hypothesis_set(platform_scope=("meta",))
    evals = evaluate_hypotheses(
        specs,
        {"cvr_trend_down": True},
        platform_scope=("meta",),
        measurement_state="invalid",
        maturity_state="sufficient",
        measurement_by_platform={"meta": "invalid"},
        maturity_by_platform={"meta": "unknown"},
    )
    ranked = rank_hypotheses(evals)
    result = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid"},
            maturity_by_platform={"meta": "unknown"},
            aggregate_measurement="invalid",
        ),
    )
    assert result.converged is False
    assert result.decision == "investigate_measurement"


# ── Result consistency: top fields from ONE evaluation (spec §34) ────────


def test_top_fields_derive_from_same_selected_evaluation() -> None:
    ranked = _google_auction_evals(aggregate_measurement="invalid")
    convergence = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    result = from_convergence(
        convergence=convergence,
        platform_scope=("google_ads", "meta"),
        operational_domain="general",
        evaluations=tuple(r.evaluation for r in ranked),
        ranked=ranked,
        safety_context={"measurement_state": "invalid"},
    )
    selected = result.selected_evaluation
    assert selected is not None
    assert result.top_hypothesis == selected.hypothesis.id
    assert result.top_platform == selected.platform
    assert result.top_evaluation_scope == selected.hypothesis.evaluation_scope
    assert result.top_hypothesis == "auction_pressure"
    assert result.top_platform == "google_ads"
    assert result.top_evaluation_scope == "platform"


def test_attribution_mismatch_is_impossible() -> None:
    # Scenario 4 (spec §29): ranked[0] = auction_pressure@google while the
    # aggregate measurement is invalid. The old code produced
    # top_hypothesis=measurement_instability + top_platform=google_ads;
    # that mixed-source outcome must never occur.
    ranked = _google_auction_evals(aggregate_measurement="invalid")
    convergence = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    assert convergence.top_hypothesis == "auction_pressure"
    result = from_convergence(
        convergence=convergence,
        platform_scope=("google_ads", "meta"),
        operational_domain="general",
        evaluations=tuple(r.evaluation for r in ranked),
        ranked=ranked,
        safety_context={"measurement_state": "invalid"},
    )
    assert not (
        result.top_hypothesis == "measurement_instability"
        and result.top_platform == "google_ads"
    )
    assert result.top_hypothesis == result.selected_evaluation.hypothesis.id


def test_safety_block_never_rewrites_diagnosis_identity() -> None:
    # Spec §18/19: investigate_measurement on a ranked diagnosis does NOT
    # mean top_hypothesis becomes measurement_instability.
    ranked = _shared_pay_drop_evals()
    result = converge(
        ranked,
        safety_context=_safety_context(
            measurement_by_platform={"meta": "invalid", "google_ads": "stable"},
            maturity_by_platform={"meta": "unknown", "google_ads": "sufficient"},
            aggregate_measurement="invalid",
        ),
    )
    assert result.decision == "investigate_measurement"
    assert result.safety_block == "measurement_invalid"
    assert result.top_hypothesis == "shared_product_funnel_issue"


# ── Persistence: Decision attribution matches selected evaluation (§35) ──


def _run_scenario1(workspace) -> tuple[PlatformOperationalRun, object]:
    """Meta invalid + Google stable CPM↑/CTR stable (spec §26 Scenario 1)."""
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Google 越来越贵？", platform_scope=("google_ads", "meta")
    )
    run.record_observation(
        {"measurement_state": "invalid", "maturity_state": "sufficient"},
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.3,
            "ctr_change_pct": 0.01,
            "cvr_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    return run, run.evaluate_decision_intelligence()


def test_runtime_e2e_meta_invalid_google_auction_survives(workspace) -> None:
    run, result = _run_scenario1(workspace)
    # Google's diagnosis is the final answer, not globally vetoed.
    assert result.top_hypothesis == "auction_pressure"
    assert result.top_platform == "google_ads"
    assert result.top_evaluation_scope == "platform"
    assert result.convergence_status == "converged"
    assert result.recommended_action == "wait"
    assert result.safety_block is None
    # Meta's measurement problem is a WARNING, not a veto (spec §13/31).
    assert result.platform_warnings == {"meta": ("measurement_invalid",)}
    run.finish()


def test_runtime_e2e_meta_insufficient_google_mature_survives(workspace) -> None:
    # Spec §27 Scenario 2: Meta immature must not block mature Google.
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="Google 越来越贵？", platform_scope=("google_ads", "meta")
    )
    run.record_observation(
        {"measurement_state": "stable", "maturity_state": "insufficient"},
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "cpm_change_pct": 0.3,
            "ctr_change_pct": 0.01,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "auction_pressure"
    assert result.top_platform == "google_ads"
    assert result.convergence_status == "converged"
    assert result.platform_warnings == {"meta": ("maturity_insufficient",)}
    run.finish()


def test_runtime_e2e_shared_diagnosis_still_blocked(workspace) -> None:
    # Spec §28 Scenario 3: Meta pay↓ invalid + Google pay↓ stable →
    # shared product funnel ranks but aggregate Safety blocks it.
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="两边付费都掉，是产品问题吗？",
        platform_scope=("google_ads", "meta"),
    )
    run.record_observation(
        {
            "pay_rate_change_pct": -0.25,
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    result = run.evaluate_decision_intelligence()
    assert result.top_hypothesis == "shared_product_funnel_issue"
    assert result.top_platform == "cross_platform"
    assert result.top_evaluation_scope == "shared"
    assert result.convergence_status == "investigate"
    assert result.recommended_action == "investigate_measurement"
    assert result.safety_block == "measurement_invalid"
    run.finish()


def test_persisted_platform_decision_matches_selected_evaluation(workspace) -> None:
    run, _ = _run_scenario1(workspace)
    decision_id = run.record_decision_from_intelligence()
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    event = store.get_event(decision_id)
    # Platform-bound diagnosis persists with THAT platform, not the run's
    # cross-platform scope (spec §21/35).
    assert event["platform"] == "google_ads"
    payload = event["payload"]
    assert payload["decision_class"] == "wait"
    assert payload["diagnosis_confidence"] == "probable"


def test_persisted_shared_decision_stays_cross_platform(workspace) -> None:
    run = PlatformOperationalRun(workspace)
    run.begin(
        request_text="两边付费都掉，是产品问题吗？",
        platform_scope=("google_ads", "meta"),
    )
    run.record_observation(
        {
            "pay_rate_change_pct": -0.25,
            "measurement_state": "invalid",
            "maturity_state": "sufficient",
        },
        platform="meta",
        observed_at="2026-08-13T09:00:00Z",
    )
    run.record_observation(
        {
            "pay_rate_change_pct": -0.3,
            "measurement_state": "stable",
            "maturity_state": "sufficient",
        },
        platform="google_ads",
        observed_at="2026-08-13T09:00:00Z",
    )
    decision_id = run.record_decision_from_intelligence()
    run.finish()
    assert decision_id is not None
    store = StateStore(RunContext.from_workspace(workspace))
    event = store.get_event(decision_id)
    # A safety action (investigate measurement) never rewrites the
    # diagnostic attribution: still cross-platform (spec §22).
    assert event["platform"] == "cross_platform"
    assert event["payload"]["platform_scope"] == ["google_ads", "meta"]


# ── Attribution helper ───────────────────────────────────────────────────


def test_decision_attribution_follows_selected_evaluation() -> None:
    platform_ev = _evaluation("auction_pressure", "google_ads")
    assert decision_attribution(platform_ev, ("google_ads", "meta")) == (
        "google_ads",
        (),
    )
    shared_ev = _evaluation("shared_product_funnel_issue", "cross_platform", "shared")
    assert decision_attribution(shared_ev, ("google_ads", "meta")) == (
        "cross_platform",
        ("google_ads", "meta"),
    )
    run_ev = _evaluation("platform_specific_independent_issues", None, "run")
    assert decision_attribution(run_ev, ("google_ads", "meta")) == (
        "cross_platform",
        ("google_ads", "meta"),
    )
    assert decision_attribution(None, ()) == (None, ())
