"""Readiness gates for candidate events, value signals, and split capacity."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import _mapping
from .quick_ops_base import _tri_state_gate, _unique


def _candidate_event_gate(
    quick: Mapping[str, Any], analysis: Mapping[str, Any]
) -> tuple[str, list[str], list[str]]:
    candidate = _mapping(quick.get("candidate_event"))
    state, blocked, unknown = _tri_state_gate(
        candidate,
        true_fields=("reliable", "delay_mature"),
        enum_fields={
            "volume_assessment": "sufficient",
            "stability_assessment": "stable",
            "relationship_to_business_goal": "stronger",
        },
        prefix="candidate_event",
    )
    measurement = _mapping(analysis.get("measurement_state")).get("status")
    if measurement == "measurement_unreliable":
        blocked.append("measurement_state_unreliable")
        state = "blocked"
    elif measurement != "measurement_reliable" and state != "blocked":
        unknown.append("measurement_state_not_confirmed")
        state = "unknown"
    return state, _unique(blocked), _unique(unknown)


def _value_gate(
    quick: Mapping[str, Any],
    analysis: Mapping[str, Any],
    campaign: Mapping[str, Any],
) -> tuple[str, list[str], list[str]]:
    signal = _mapping(quick.get("value_signal"))
    state, blocked, unknown = _tri_state_gate(
        signal,
        true_fields=(
            "business_kpi_is_value",
            "strategy_supports_value",
            "payment_reliable",
            "value_reliable",
            "currency_reliable",
            "duplicates_handled",
            "refunds_handled",
            "subscriptions_defined",
            "delay_mature",
        ),
        enum_fields={
            "value_reconciliation": "consistent",
            "volume_assessment": "sufficient",
            "stability_assessment": "stable",
            "single_campaign_budget_assessment": "sufficient",
        },
        prefix="value_signal",
    )
    value_optimization = campaign.get("value_optimization")
    if value_optimization is False:
        blocked.append("candidate_campaign_value_optimization_failed")
        state = "blocked"
    elif value_optimization is not True and state != "blocked":
        unknown.append("candidate_campaign_value_optimization_unknown")
        state = "unknown"
    bidding_strategy = str(campaign.get("bidding_strategy", "")).lower()
    if bidding_strategy in {
        "cpi",
        "tcpi",
        "tcpa",
        "maximize_conversions",
        "max_conversions",
    }:
        blocked.append("candidate_campaign_value_bidding_strategy_failed")
        state = "blocked"
    elif not bidding_strategy and state != "blocked":
        unknown.append("candidate_campaign_value_bidding_strategy_unknown")
        state = "unknown"
    measurement = _mapping(analysis.get("measurement_state")).get("status")
    if measurement == "measurement_unreliable":
        blocked.append("measurement_state_unreliable")
        state = "blocked"
    elif measurement != "measurement_reliable" and state != "blocked":
        unknown.append("measurement_state_not_confirmed")
        state = "unknown"
    return state, _unique(blocked), _unique(unknown)


def _split_gate(quick: Mapping[str, Any]) -> tuple[str, list[str], list[str]]:
    split = _mapping(quick.get("split_capacity"))
    return _tri_state_gate(
        split,
        true_fields=("isolatable",),
        enum_fields={
            "budget_assessment": "sufficient",
            "event_volume_assessment": "sufficient",
        },
        prefix="split_capacity",
    )
