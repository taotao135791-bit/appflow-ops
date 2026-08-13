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
_TREND_KEYS: dict[str, tuple[str, ...]] = {
    "ctr_trend": ("ctr_trend_down", "ctr_trend_stable", "ctr_trend_up"),
    "cpm_trend": ("cpm_trend_up", "cpm_trend_stable", "cpm_trend_down"),
    "cvr_trend": ("cvr_trend_down", "cvr_trend_stable"),
    "frequency_trend": ("frequency_trend_up", "frequency_trend_stable"),
    "click_volume_trend": ("click_volume_trend_down", "click_volume_trend_stable"),
    "install_rate_trend": ("install_rate_trend_down", "install_rate_trend_stable"),
    "registration_rate_trend": ("registration_rate_trend_down",),
    "pay_rate_trend": ("pay_rate_trend_down",),
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
    return signals


def add_context_signals(
    signals: dict[str, bool],
    *,
    measurement_state: str,
    maturity_state: str,
) -> dict[str, bool]:
    """Augment with canonical safety context: invalid measurement and
    insufficient maturity are themselves strong signals."""
    if measurement_state == "invalid":
        signals["measurement_invalid"] = True
    if maturity_state == "insufficient":
        signals["maturity_insufficient"] = True
    return signals
