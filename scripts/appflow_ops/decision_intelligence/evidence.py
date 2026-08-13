"""Signal extraction for Ads Decision Intelligence (v3.5.0).

Signals are the bridge between raw metrics/context and hypothesis
evaluation. A signal id is present (True) when the phenomenon is
observed; absent (False) when not observed. Signals come from the
metrics/facts of current observations plus run context (measurement /
maturity / recent changes) — never invented when data is missing.
"""

from __future__ import annotations

from collections.abc import Mapping

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
        if value <= -MATERIAL_CHANGE_PCT:
            if down is not None:
                signals[down] = True
        elif value >= MATERIAL_CHANGE_PCT:
            if up is not None:
                signals[up] = True
        elif abs(value) <= STABLE_CHANGE_PCT:
            if stable is not None:
                signals[stable] = True
        # else: ambiguous movement, no signal
    return signals


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


# Cross-aggregated signals: a raw per-platform signal counts as a
# CROSS-LEVEL signal when it fires on >= 2 platforms (v3.5.1). These ids
# are declared in SIGNAL_IDS and consumed by cross-platform hypotheses.
_CROSS_AGGREGATIONS: dict[str, str] = {
    "pay_rate_trend_down": "cross_pay_rate_drop",
    "cvr_trend_down": "cross_cvr_drop",
}


def signals_from_platforms(
    per_platform: Mapping[str, Mapping[str, object]],
) -> dict[str, bool]:
    """Extract signals per platform, merge them, and add cross-level
    aggregations (a phenomenon shared by >= 2 platforms). Single-platform
    input behaves exactly like signals_from_metrics."""
    signals: dict[str, bool] = {}
    per_platform_signals = {
        platform: signals_from_metrics(metrics)
        for platform, metrics in per_platform.items()
    }
    for platform_signals in per_platform_signals.values():
        signals.update(platform_signals)
    for raw_signal, cross_signal in _CROSS_AGGREGATIONS.items():
        count = sum(1 for ps in per_platform_signals.values() if ps.get(raw_signal))
        if count >= 2:
            signals[cross_signal] = True
    return signals
