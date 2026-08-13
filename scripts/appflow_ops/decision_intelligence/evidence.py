"""Signal extraction for Ads Decision Intelligence (v3.5.0 → v3.5.2).

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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

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
    "no_recent_change": "no_recent_change",
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
}


def _change_pct_signals(
    down: str | None, stable: str | None, up: str | None, value: float
) -> tuple[str, ...]:
    """Map a numeric relative movement to trend signal ids (shared by the
    explicit change_pct path and the current-vs-history derivation)."""
    if value <= -MATERIAL_CHANGE_PCT:
        return (down,) if down is not None else ()
    if value >= MATERIAL_CHANGE_PCT:
        return (up,) if up is not None else ()
    if abs(value) <= STABLE_CHANGE_PCT:
        return (stable,) if stable is not None else ()
    return ()  # ambiguous movement: no signal


def signals_from_metrics(metrics: Mapping[str, object]) -> dict[str, bool]:
    """Extract present signals from a metrics/facts mapping. Only values
    that exist are extracted; missing data stays missing (never invented).
    """
    signals: dict[str, bool] = {}
    for key, ids in _TREND_KEYS.items():
        value = metrics.get(key)
        if isinstance(value, str):
            for signal_id in ids:
                if value == signal_id.replace(f"{key}_", ""):
                    signals[signal_id] = True
                    break
    for key, signal_id in _BOOL_KEYS.items():
        value = metrics.get(key)
        if value is True:
            signals[signal_id] = True
    # Relative movement: numeric change_pct → trend signal, via thresholds.
    # Missing value or ambiguous band → no signal (stable is never guessed).
    for key, (down, stable, up) in _CHANGE_PCT_KEYS.items():
        value = metrics.get(key)
        if not isinstance(value, (int, float)):
            continue
        for signal_id in _change_pct_signals(down, stable, up, value):
            signals[signal_id] = True
    return signals


def derive_change_pcts(
    current: Mapping[str, object], previous: Mapping[str, object]
) -> dict[str, float]:
    """Current-vs-previous relative movement for comparable raw metrics.

    Comparability = the same metric key exists in BOTH observations (the
    runtime guarantees same-platform selection); an absent or zero previous
    value produces NO change (never guessed). The returned change_pct
    values are consumed by the same thresholds as explicit change_pct.
    """
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
    """

    signals: dict[str, bool] = field(default_factory=dict)
    signals_by_platform: dict[str, dict[str, bool]] = field(default_factory=dict)
    shared_signals: dict[str, bool] = field(default_factory=dict)
    historical_comparisons: dict[str, dict[str, float]] = field(default_factory=dict)
    recent_change_context: dict[str, bool] = field(default_factory=dict)
    decision_context: dict[str, object] = field(default_factory=dict)
    outcome_context: dict[str, object] = field(default_factory=dict)


def build_evidence(
    *,
    per_platform: Mapping[str, Mapping[str, object]],
    historical_by_platform: Mapping[str, Mapping[str, object]] | None = None,
    recent_changes: tuple[Mapping[str, object], ...] = (),
    recent_decisions: tuple[Mapping[str, object], ...] = (),
    recent_outcomes: tuple[Mapping[str, object], ...] = (),
    measurement_state: str = "unknown",
    maturity_state: str = "unknown",
) -> EvidenceResult:
    """Assemble runtime evidence with provenance.

    Trend precedence (v3.5.2): explicit canonical current trend (string
    ``ctr_trend`` or numeric ``ctr_change_pct``) > derived current-vs-
    history trend > missing. A derived trend only exists when the previous
    observation is comparable (same platform, same metric family).
    """
    signals_by_platform: dict[str, dict[str, bool]] = {}
    historical_comparisons: dict[str, dict[str, float]] = {}
    for platform, metrics in per_platform.items():
        platform_signals = signals_from_metrics(metrics)
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
            for signal_id in _change_pct_signals(
                *_CHANGE_PCT_KEYS[f"{trend_key.rsplit('_', 1)[0]}_change_pct"],
                change_pct,
            ):
                platform_signals[signal_id] = True
        signals_by_platform[platform] = platform_signals

    # Merged aggregate + shared signals (>= 2 distinct platforms only).
    signals: dict[str, bool] = {}
    for platform_signals in signals_by_platform.values():
        signals.update(platform_signals)
    shared_signals: dict[str, bool] = {}
    for raw_signal, cross_signal in _CROSS_AGGREGATIONS.items():
        count = sum(1 for ps in signals_by_platform.values() if ps.get(raw_signal))
        if count >= 2:
            signals[cross_signal] = True
            shared_signals[cross_signal] = True

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

    # Measurement conflict: >= 1 platform invalid while >= 1 is not.
    measurement_states = {
        platform: (metrics.get("measurement_state") or "unknown")
        for platform, metrics in per_platform.items()
    }
    if any(s == "invalid" for s in measurement_states.values()) and any(
        s != "invalid" for s in measurement_states.values()
    ):
        signals["measurement_conflict"] = True
        shared_signals["measurement_conflict"] = True

    add_context_signals(
        signals,
        measurement_state=measurement_state,
        maturity_state=maturity_state,
    )

    # Recent confirmed changes → confounder evidence (v3.5.2). Only facts
    # already present in Change events are projected; no invented taxonomy.
    recent_change_context: dict[str, bool] = {}
    for event in recent_changes:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        change_type = payload.get("change_type")
        direction = payload.get("direction")
        if change_type == "budget":
            recent_change_context["recent_budget_change"] = True
        elif change_type == "bid":
            recent_change_context["recent_bid_change"] = True
        elif change_type in ("creative", "audience", "campaign"):
            recent_change_context["recent_creative_change"] = True
        if direction:
            recent_change_context["last_change_direction"] = True
    for signal_id in recent_change_context:
        if signal_id in _BOOL_KEYS.values():
            signals[signal_id] = True

    # Prior recommendation and outcome are CONTEXT, never factual support.
    decision_context: dict[str, object] = {}
    if recent_decisions:
        latest = recent_decisions[0]
        payload = latest.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        decision_context["decision_class"] = payload.get("decision_class")
        decision_context["review_condition"] = payload.get("review_condition")
        decision_context["review_after"] = payload.get("review_after")
        decision_context["confidence"] = payload.get("confidence")
    outcome_context: dict[str, object] = {}
    if recent_outcomes:
        latest = recent_outcomes[0]
        payload = latest.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        outcome_context["outcome_class"] = payload.get("outcome_class")
        outcome_context["evidence_status"] = payload.get("evidence_status")
        outcome_context["linked_decision"] = latest.get("decision_id")
        outcome_context["linked_change"] = latest.get("change_id")

    return EvidenceResult(
        signals=signals,
        signals_by_platform=signals_by_platform,
        shared_signals=shared_signals,
        historical_comparisons=historical_comparisons,
        recent_change_context=recent_change_context,
        decision_context=decision_context,
        outcome_context=outcome_context,
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
