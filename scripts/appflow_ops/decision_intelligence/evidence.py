"""Signal extraction for Ads Decision Intelligence (v3.5.0 → v3.6.0).

Signals are the bridge between raw metrics/context and hypothesis
evaluation. A signal id is present (True) when the phenomenon is
observed; absent (False) when not observed. Signals come from the
metrics/facts of current observations plus run context (measurement /
maturity / recent changes) — never invented when data is missing.

v3.5.2: evidence is CONTINUOUS, not a current snapshot:
- explicit canonical trend (``ctr_change_pct`` / ``ctr_trend``) wins
- otherwise a comparable previous observation derives the trend
- per-platform provenance is preserved (``signals_by_platform``);
  shared signals exist only when >= 2 distinct platforms agree

v3.6.0: business calibration — metric-family movement thresholds and
sample-aware evidence strength. A -25% CTR on 150 impressions is WEAK
evidence; the same movement on 100k impressions is normal. Metric-level
sufficiency is NOT campaign maturity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .calibration import sample_sufficiency, thresholds_for

# Metrics keys that are directly readable as trend signals when present.
# Every *_trend_* signal id in SIGNAL_IDS must be reachable through one of
# these keys (registry consistency is asserted by tests).
_TREND_KEYS: dict[str, tuple[str, ...]] = {
    "ctr_trend": ("ctr_trend_down", "ctr_trend_stable", "ctr_trend_up"),
    "cpm_trend": ("cpm_trend_up", "cpm_trend_stable", "cpm_trend_down"),
    "cvr_trend": ("cvr_trend_down", "cvr_trend_stable"),
    "frequency_trend": ("frequency_trend_up", "frequency_trend_stable"),
    "click_volume_trend": ("click_volume_trend_down", "click_volume_trend_stable"),
    "install_rate_trend": ("install_rate_trend_down", "install_rate_trend_stable"),
    "registration_rate_trend": (
        "registration_rate_trend_down",
        "registration_rate_trend_stable",
    ),
    "pay_rate_trend": ("pay_rate_trend_down", "pay_rate_trend_stable"),
}

# Material-change thresholds for numeric relative movement (e.g.
# ``ctr_change_pct: -0.25``). A value inside the stable band yields the
# stable signal; beyond the material threshold yields up/down; the gap in
# between is ambiguous and yields NOTHING (never guessed).
# v3.5.2: the SAME constants drive current-vs-history derivation.
# v3.6.0: metric families with a calibration entry use their own
# conservative bands (see ``calibration.METRIC_CALIBRATION``); these
# uniform values remain the fallback.
MATERIAL_CHANGE_PCT = 0.10
STABLE_CHANGE_PCT = 0.05

# Relative-movement keys map to explicit (down, stable, up) signal ids.
# None marks a direction that has NO declared signal (e.g. frequency never
# goes down in the registry) — that direction simply emits nothing.
_CHANGE_PCT_KEYS: dict[str, tuple[str | None, str | None, str | None]] = {
    "ctr_change_pct": ("ctr_trend_down", "ctr_trend_stable", "ctr_trend_up"),
    "cpm_change_pct": ("cpm_trend_down", "cpm_trend_stable", "cpm_trend_up"),
    "cvr_change_pct": ("cvr_trend_down", "cvr_trend_stable", None),
    "frequency_change_pct": (None, "frequency_trend_stable", "frequency_trend_up"),
    "click_volume_change_pct": (
        "click_volume_trend_down",
        "click_volume_trend_stable",
        None,
    ),
    "install_rate_change_pct": (
        "install_rate_trend_down",
        "install_rate_trend_stable",
        None,
    ),
    "registration_rate_change_pct": (
        "registration_rate_trend_down",
        "registration_rate_trend_stable",
        None,
    ),
    "pay_rate_change_pct": ("pay_rate_trend_down", "pay_rate_trend_stable", None),
}

# Raw numeric metric keys that can be compared across observations of the
# SAME platform to derive a trend (v3.5.2). Comparability = same platform
# + same metric family; anything else stays missing.
_HISTORY_METRIC_KEYS: dict[str, str] = {
    "ctr": "ctr_trend",
    "cpm": "cpm_trend",
    "cvr": "cvr_trend",
    "frequency": "frequency_trend",
    "clicks": "click_volume_trend",
    "click_to_install_rate": "install_rate_trend",
    "install_rate": "install_rate_trend",
    "registration_rate": "registration_rate_trend",
    "pay_rate": "pay_rate_trend",
}

# Comparable identity (v3.5.3 → v3.5.4): same platform does NOT imply
# comparable observations. Three explicit states:
#   - explicit account aggregate (entity_level="account" AND
#     aggregate_scope present): comparable to the same aggregate scope;
#   - explicit entity (entity_level + entity_key): comparable only to the
#     same entity;
#   - identity UNKNOWN (no level/key/aggregate metadata): NOT comparable
#     to anything — missing identity is never evidence of account-level
#     aggregation (v3.5.4).
# ``entity_key`` is a workspace-local opaque identifier; raw external IDs
# are never persisted (privacy contract).
_ENTITY_KEYS = ("entity_level", "entity_key", "breakdown_scope", "aggregate_scope")


def comparable_identity(facts: Mapping[str, object]) -> tuple[object, ...] | None:
    """Thin provenance key; None = identity UNKNOWN (never comparable)."""
    level = facts.get("entity_level")
    key = facts.get("entity_key") or facts.get("entity_id")  # legacy read
    breakdown = facts.get("breakdown_scope")
    aggregate = facts.get("aggregate_scope")
    if level is None and key is None and aggregate is None:
        return None
    if aggregate is not None and level in (None, "account"):
        # Explicit account aggregate: comparable to the same aggregate
        # scope (entity_key must match when both present).
        return ("account", aggregate, key or None, breakdown)
    return (str(level or "unknown_level"), key, breakdown)


def observations_comparable(
    current: Mapping[str, object], previous: Mapping[str, object]
) -> bool:
    """True only when both observations carry the same entity scope."""
    current_id = comparable_identity(current)
    previous_id = comparable_identity(previous)
    if current_id is None or previous_id is None:
        return False  # unknown identity is never comparable
    return current_id == previous_id


# Facts keys that map to a signal id directly.
_BOOL_KEYS: dict[str, str] = {
    "old_creative_worse": "old_creative_worse",
    "new_creative_also_dropping": "new_creative_also_dropping",
    "multi_creative_impacted": "multi_creative_impacted",
    "only_one_creative_declines": "only_one_creative_declines",
    "reach_growth_slowing": "reach_growth_slowing",
    "delivery_concentrated": "delivery_concentrated",
    "audience_expansion": "audience_expansion",
    "delivery_mix_shifted": "delivery_mix_shifted",
    "learning_reset": "learning_reset",
    "recent_budget_change": "recent_budget_change",
    "recent_bid_change": "recent_bid_change",
    "budget_utilization_high": "budget_utilization_high",
    "spend_hit_cap": "spend_hit_cap",
    "store_loading_issue": "store_loading_issue",
    "downstream_conversion_down": "downstream_conversion_down",
    "traffic_quality_signal": "traffic_quality_signal",
    "click_quality_signal": "click_quality_signal",
    "reporting_anomaly": "reporting_anomaly",
    "no_recent_change": "no_recent_change",
    "recent_creative_change": "recent_creative_change",
    "recent_audience_change": "recent_audience_change",
    "recent_campaign_change": "recent_campaign_change",
    "recent_campaign_restart": "recent_campaign_restart",
}

# Cross-aggregated signals: a raw per-platform signal counts as a
# CROSS-LEVEL signal when it fires on >= 2 DISTINCT platforms (v3.5.1+).
# Shared diagnoses require shared evidence.
_CROSS_AGGREGATIONS: dict[str, str] = {
    "pay_rate_trend_down": "cross_pay_rate_drop",
    "pay_rate_trend_stable": "cross_pay_rate_stable",
    "cvr_trend_down": "cross_cvr_drop",
    "registration_rate_trend_down": "cross_registration_drop",
    "install_rate_trend_down": "cross_install_drop",
    "cpm_trend_up": "cross_cpm_up",
}


def _change_pct_signals(
    down: str | None,
    stable: str | None,
    up: str | None,
    value: float,
    metric_family: str | None = None,
) -> tuple[str, ...]:
    """Map a numeric relative movement to trend signal ids (shared by the
    explicit change_pct path and the current-vs-history derivation).
    v3.6.0: metric-family calibration thresholds (fallback = legacy)."""
    stable_pct, material_pct = thresholds_for(metric_family or "")
    if value <= -material_pct:
        return (down,) if down is not None else ()
    if value >= material_pct:
        return (up,) if up is not None else ()
    if abs(value) <= stable_pct:
        return (stable,) if stable is not None else ()
    return ()  # ambiguous movement: no signal


def _signals_from_metrics(
    metrics: Mapping[str, object],
) -> tuple[dict[str, bool], dict[str, str]]:
    """(signals, strengths) extraction. v3.6.0: movement on a metric whose
    sample population is below the family minimum is WEAK evidence.
    v3.6.2: explicit canonical trend strings go through the SAME sample
    calibration as numeric change_pct — ``ctr_trend="down"`` on 150
    impressions is weak, never normal (trend-representation invariance:
    the same business fact must have the same strength regardless of how
    it was encoded). Boolean operational facts stay normal."""
    signals: dict[str, bool] = {}
    strengths: dict[str, str] = {}
    for key, ids in _TREND_KEYS.items():
        value = metrics.get(key)
        if isinstance(value, str):
            for signal_id in ids:
                if value == signal_id.replace(f"{key}_", ""):
                    signals[signal_id] = True
                    family = key.removesuffix("_trend")
                    strengths[signal_id] = (
                        "normal"
                        if sample_sufficiency(metrics, family) == "sufficient"
                        else "weak"
                    )
                    break
    for key, signal_id in _BOOL_KEYS.items():
        value = metrics.get(key)
        if value is True:
            signals[signal_id] = True
            strengths[signal_id] = "normal"
    # Relative movement: numeric change_pct → trend signal, via the
    # metric-family calibrated thresholds + sample sufficiency.
    # v3.6.1: missing sample context is UNKNOWN (weak), never sufficient
    # — a -25% CTR with no impressions fact is uncertainty.
    for key, (down, stable, up) in _CHANGE_PCT_KEYS.items():
        value = metrics.get(key)
        if not isinstance(value, (int, float)):
            continue
        family = key.removesuffix("_change_pct")
        strength = (
            "normal" if sample_sufficiency(metrics, family) == "sufficient" else "weak"
        )
        for signal_id in _change_pct_signals(down, stable, up, value, family):
            signals[signal_id] = True
            strengths[signal_id] = strength
    return signals, strengths


def signals_from_metrics(metrics: Mapping[str, object]) -> dict[str, bool]:
    """Extract present signals from a metrics/facts mapping. Only values
    that exist are extracted; missing data stays missing (never invented).
    """
    signals, _ = _signals_from_metrics(metrics)
    return signals


def derive_change_pcts(
    current: Mapping[str, object], previous: Mapping[str, object]
) -> dict[str, float]:
    """Current-vs-previous relative movement for comparable raw metrics.

    Comparability (v3.5.3) = same platform AND same entity scope (level /
    entity_id / breakdown); the same metric key must exist in BOTH
    observations; an absent or zero previous value produces NO change
    (never guessed). The returned change_pct values are consumed by the
    same thresholds as explicit change_pct.
    """
    if not observations_comparable(current, previous):
        return {}
    changes: dict[str, float] = {}
    for metric, trend_key in _HISTORY_METRIC_KEYS.items():
        current_value = current.get(metric)
        previous_value = previous.get(metric)
        if not isinstance(current_value, (int, float)) or not isinstance(
            previous_value, (int, float)
        ):
            continue
        if previous_value == 0:
            continue
        changes[trend_key] = (current_value - previous_value) / abs(previous_value)
    return changes


def signals_from_platforms(
    per_platform: Mapping[str, Mapping[str, object]],
) -> dict[str, bool]:
    """Merged aggregate signals (backward-compatible helper). Prefer
    ``build_evidence`` when provenance matters."""
    return build_evidence(per_platform=per_platform).signals


@dataclass(frozen=True)
class EvidenceResult:
    """Runtime evidence with provenance (v3.5.2).

    - ``signals``: merged aggregate signals (explicit > derived), used by
      the evaluator
    - ``signals_by_platform``: per-platform signals — a shared diagnosis
      can be audited ("Meta pay down, Google stable") instead of a flat
      ``pay_down=true`` blob
    - ``shared_signals``: ONLY signals true on >= 2 distinct media
      platforms (cross_pay_rate_drop etc.)
    - ``historical_comparisons``: platform -> trend_key -> change_pct
      derived from current-vs-previous (provenance preserved)
    - ``recent_change_context``: recent confirmed changes as confounder
      evidence (recent_budget_change / recent_bid_change / ...)
    - ``decision_context`` / ``outcome_context``: prior recommendation and
      outcome — CONTEXT only, never factual support
    - ``signal_strength`` / ``signal_strength_by_platform``: evidence
      strength (weak/normal) per signal id — sample-aware calibration
      (v3.6.0); weak evidence counts less in evaluation
    """

    signals: dict[str, bool] = field(default_factory=dict)
    signals_by_platform: dict[str, dict[str, bool]] = field(default_factory=dict)
    shared_signals: dict[str, bool] = field(default_factory=dict)
    historical_comparisons: dict[str, dict[str, float]] = field(default_factory=dict)
    recent_change_context: dict[str, bool] = field(default_factory=dict)
    # v3.5.3: temporal metadata of the latest relevant change (audit).
    change_context: dict[str, object] = field(default_factory=dict)
    decision_context: dict[str, object] = field(default_factory=dict)
    outcome_context: dict[str, object] = field(default_factory=dict)
    # v3.5.3: per-platform latest context retained alongside global latest.
    decisions_by_platform: dict[str, dict[str, object]] = field(default_factory=dict)
    outcomes_by_platform: dict[str, dict[str, object]] = field(default_factory=dict)
    # v3.6.0: sample-aware evidence strength (weak/normal) per signal id.
    signal_strength: dict[str, str] = field(default_factory=dict)
    signal_strength_by_platform: dict[str, dict[str, str]] = field(default_factory=dict)


def build_evidence(
    *,
    per_platform: Mapping[str, Mapping[str, object]],
    historical_by_platform: Mapping[str, Mapping[str, object]] | None = None,
    recent_changes: tuple[Mapping[str, object], ...] = (),
    recent_decisions: tuple[Mapping[str, object], ...] = (),
    recent_outcomes: tuple[Mapping[str, object], ...] = (),
    measurement_state: str = "unknown",
    maturity_state: str = "unknown",
    current_observed_at: Mapping[str, str] | None = None,
    historical_observed_at: Mapping[str, str] | None = None,
) -> EvidenceResult:
    """Assemble runtime evidence with provenance.

    Trend precedence (v3.5.2): explicit canonical current trend (string
    ``ctr_trend`` or numeric ``ctr_change_pct``) > derived current-vs-
    history trend > missing. A derived trend only exists when the previous
    observation is comparable (same platform, same metric family).
    """
    signals_by_platform: dict[str, dict[str, bool]] = {}
    signal_strength_by_platform: dict[str, dict[str, str]] = {}
    historical_comparisons: dict[str, dict[str, float]] = {}
    for platform, metrics in per_platform.items():
        platform_signals, platform_strengths = _signals_from_metrics(metrics)
        previous = (historical_by_platform or {}).get(platform) or {}
        changes = derive_change_pcts(metrics, previous)
        if changes:
            historical_comparisons[platform] = changes
        # Explicit wins: only fill trend slots that have NO explicit signal.
        explicit_trend_keys = set()
        for trend_key, ids in _TREND_KEYS.items():
            if any(signal_id in platform_signals for signal_id in ids):
                explicit_trend_keys.add(trend_key)
        for trend_key, change_pct in changes.items():
            if trend_key in explicit_trend_keys:
                continue
            family = trend_key.removesuffix("_trend")
            strength = (
                "normal"
                if sample_sufficiency(metrics, family) == "sufficient"
                else "weak"
            )
            for signal_id in _change_pct_signals(
                *_CHANGE_PCT_KEYS[f"{family}_change_pct"],
                change_pct,
                family,
            ):
                platform_signals[signal_id] = True
                platform_strengths[signal_id] = strength
        signals_by_platform[platform] = platform_signals
        signal_strength_by_platform[platform] = platform_strengths

    # Merged aggregate + shared signals (>= 2 distinct platforms only).
    # v3.6.0: a cross-level signal inherits the WEAKEST contributing
    # platform strength (two tiny-sample declines are not strong shared
    # evidence either).
    signal_strength: dict[str, str] = {}
    for platform_strengths in signal_strength_by_platform.values():
        for signal_id, strength in platform_strengths.items():
            if signal_id not in signal_strength or strength == "weak":
                signal_strength[signal_id] = strength
    signals: dict[str, bool] = {}
    for platform_signals in signals_by_platform.values():
        signals.update(platform_signals)
    shared_signals: dict[str, bool] = {}
    for raw_signal, cross_signal in _CROSS_AGGREGATIONS.items():
        platforms_with = [
            platform
            for platform, ps in signals_by_platform.items()
            if ps.get(raw_signal)
        ]
        if len(platforms_with) >= 2:
            signals[cross_signal] = True
            shared_signals[cross_signal] = True
            if all(
                signal_strength_by_platform[platform].get(raw_signal) == "weak"
                for platform in platforms_with
            ):
                signal_strength[cross_signal] = "weak"

    # Cross-platform comparison is available when >= 2 platforms show the
    # SAME downstream direction (both down, or both stable). A divergent
    # pair (Meta down + Google stable) is NOT comparable shared evidence
    # (v3.5.2) — it is exactly the single-platform decline case.
    down_platforms = {
        platform
        for platform, ps in signals_by_platform.items()
        if ps.get("pay_rate_trend_down") or ps.get("cvr_trend_down")
    }
    stable_platforms = {
        platform
        for platform, ps in signals_by_platform.items()
        if ps.get("pay_rate_trend_stable") or ps.get("cvr_trend_stable")
    }
    if len(down_platforms) >= 2 or len(stable_platforms) >= 2:
        signals["cross_platform_comparison_available"] = True
        shared_signals["cross_platform_comparison_available"] = True
    # Run-level divergence (v3.5.4): at least one platform declining
    # while at least one is stable on the same downstream metric — the
    # explicit run-level fact for platform_specific_independent_issues
    # (never assembled from a flat union).
    if down_platforms and stable_platforms:
        signals["platform_divergence"] = True
        shared_signals["platform_divergence"] = True

    # Measurement conflict (v3.5.3): exactly one platform EXPLICITLY
    # invalid while another EXPLICITLY stable. invalid + unknown is NOT a
    # conflict — it is incomplete coverage and stays conservative via the
    # aggregate invalid semantics instead.
    measurement_states = {
        platform: str(metrics.get("measurement_state") or "unknown")
        for platform, metrics in per_platform.items()
    }
    if (
        "invalid" in measurement_states.values()
        and "stable" in measurement_states.values()
    ):
        signals["measurement_conflict"] = True
        shared_signals["measurement_conflict"] = True
    # Shared measurement problem needs >= 2 platforms invalid (not the
    # aggregate invalid of one platform + one unknown).
    if sum(s == "invalid" for s in measurement_states.values()) >= 2:
        signals["cross_measurement_invalid"] = True
        shared_signals["cross_measurement_invalid"] = True

    add_context_signals(
        signals,
        measurement_state=measurement_state,
        maturity_state=maturity_state,
    )

    # Recent confirmed changes → confounder evidence (v3.5.3 temporal
    # semantics): a stored Change is NOT automatically recent. It is a
    # current confounder only when baseline_observed_at < effective_at
    # <= current_observed_at (the change intervened between the comparable
    # baseline and today). Changes before the baseline were already part
    # of the baseline state. Without usable timestamps the signal stays
    # off (age metadata is still retained for audit).
    recent_change_context: dict[str, bool] = {}
    change_context: dict[str, object] = {}
    for event in recent_changes:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        change_type = payload.get("change_type")
        direction = payload.get("direction")
        effective = payload.get("effective_at") or event.get("observed_at")
        # Change provenance (v3.5.4): a Change is a confounder ONLY for
        # the platform it affected (event platform / target_platform).
        # Changes without any platform attribution keep the legacy
        # broadcast behavior for backward compatibility.
        change_platform = event.get("platform") or payload.get("target_platform")
        if not isinstance(change_platform, str) or not change_platform:
            change_platform = None
        # Temporal window uses THAT platform's baseline/current.
        baseline_time = (
            historical_observed_at.get(change_platform)
            if change_platform and historical_observed_at
            else (
                next(iter(historical_observed_at.values()), None)
                if historical_observed_at
                else None
            )
        )
        current_time = (
            current_observed_at.get(change_platform)
            if change_platform and current_observed_at
            else (
                next(iter(current_observed_at.values()), None)
                if current_observed_at
                else None
            )
        )
        intervening = False
        if effective and current_time:
            if baseline_time is None or str(baseline_time) < str(effective):
                if str(effective) <= str(current_time):
                    intervening = True
        signal_name: str | None = None
        if change_type == "budget":
            signal_name = "recent_budget_change"
        elif change_type == "bid":
            signal_name = "recent_bid_change"
        elif change_type == "creative":
            signal_name = "recent_creative_change"
        elif change_type == "audience":
            signal_name = "recent_audience_change"
        elif change_type == "campaign":
            signal_name = "recent_campaign_change"
        elif change_type == "campaign_restart":
            signal_name = "recent_campaign_restart"
        if signal_name is not None:
            change_context[f"last_{change_type}_change_effective_at"] = effective
            if intervening and signal_name in _BOOL_KEYS.values():
                recent_change_context[signal_name] = True
                if change_platform is None or not signals_by_platform:
                    # Legacy unscoped Change: aggregate + every platform
                    # (backward compatible).
                    signals[signal_name] = True
                    for platform_signals in signals_by_platform.values():
                        platform_signals[signal_name] = True
                else:
                    # Provenance: only the affected platform sees it
                    # (aggregate union view still reflects it).
                    signals[signal_name] = True
                    signals_by_platform[change_platform][signal_name] = True
        if direction:
            change_context["last_change_direction"] = direction
        change_context["change_effective_at"] = effective
        change_context["change_platform"] = change_platform

    # Prior recommendation and outcome are CONTEXT, never factual support.
    # Global latest is chosen by canonical timestamp (effective_at /
    # observed_at) with deterministic event_id tie-break, NOT by tuple
    # order (v3.5.3); per-platform latest is retained alongside.
    def _event_timestamp(event: Mapping[str, object]) -> str:
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            effective = payload.get("effective_at")
            if isinstance(effective, str):
                return effective
        observed = event.get("observed_at")
        return str(observed) if isinstance(observed, str) else ""

    def _sort_key(event: Mapping[str, object]) -> tuple[str, str]:
        return (_event_timestamp(event), str(event.get("event_id", "")))

    def _latest_by_platform(
        events: tuple[Mapping[str, object], ...],
    ) -> tuple[dict[str, dict[str, object]], Mapping[str, object] | None]:
        by_platform: dict[str, dict[str, object]] = {}
        for event in events:
            platform = event.get("platform")
            if not isinstance(platform, str) or platform in by_platform:
                continue
            payload = event.get("payload")
            by_platform[platform] = {
                "event_id": event.get("event_id"),
                "observed_at": event.get("observed_at"),
                **(dict(payload) if isinstance(payload, Mapping) else {}),
            }
        global_latest: Mapping[str, object] | None = (
            max(events, key=_sort_key) if events else None
        )
        return by_platform, global_latest

    decisions_by_platform, latest_decision = _latest_by_platform(recent_decisions)
    decision_context: dict[str, object] = {}
    if latest_decision is not None:
        payload = latest_decision.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        decision_context["decision_class"] = payload.get("decision_class")
        decision_context["review_condition"] = payload.get("review_condition")
        decision_context["review_after"] = payload.get("review_after")
        decision_context["confidence"] = payload.get("confidence")
        decision_context["observed_at"] = latest_decision.get("observed_at")
    outcomes_by_platform, latest_outcome = _latest_by_platform(recent_outcomes)
    outcome_context: dict[str, object] = {}
    if latest_outcome is not None:
        payload = latest_outcome.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        outcome_context["outcome_class"] = payload.get("outcome_class")
        outcome_context["evidence_status"] = payload.get("evidence_status")
        outcome_context["linked_decision"] = latest_outcome.get("decision_id")
        outcome_context["linked_change"] = latest_outcome.get("change_id")
        outcome_context["observed_at"] = latest_outcome.get("observed_at")

    return EvidenceResult(
        signals=signals,
        signals_by_platform=signals_by_platform,
        shared_signals=shared_signals,
        historical_comparisons=historical_comparisons,
        recent_change_context=recent_change_context,
        change_context=change_context,
        decision_context=decision_context,
        outcome_context=outcome_context,
        decisions_by_platform=decisions_by_platform,
        outcomes_by_platform=outcomes_by_platform,
        signal_strength=signal_strength,
        signal_strength_by_platform=signal_strength_by_platform,
    )


def add_context_signals(
    signals: dict[str, bool],
    *,
    measurement_state: str,
    maturity_state: str,
) -> dict[str, bool]:
    """Augment with canonical safety context: invalid measurement and
    insufficient maturity are themselves strong signals; a STABLE
    measurement is positive evidence for funnel/product hypotheses
    (stable is evidence, not absence — v3.5.1)."""
    if measurement_state == "invalid":
        signals["measurement_invalid"] = True
    elif measurement_state == "stable":
        signals["measurement_stable"] = True
    if maturity_state == "insufficient":
        signals["maturity_insufficient"] = True
    return signals
