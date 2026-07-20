"""Deterministic signal derivation for UAC Quick Decisions.

The functions in this module only transform supplied account facts. They do
not read an advertising account, write files, or treat platform guidance as a
substitute for account evidence.

The implementation is split into signals_context (numeric context extraction)
and signals_derive (individual signal derivations); this module keeps the
public entry points and re-exports ``_numeric_context`` for numeric_decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ._common import _mapping
from .policy_loader import LoadedPolicy, load_policy
from .signals_context import (
    SIGNAL_DERIVATION_SCHEMA_VERSION,
    _numeric_context,
    _round_metric,
    _signal_policy_values,
)
from .signals_derive import (
    _creative_quality,
    _derive_budget_delivery,
    _derive_event_volume,
    _derive_maturity,
    _derive_split,
    _derive_target_constraint,
    _derive_value_signal,
    _rank_event_candidates,
)
from .types import ContractError


def derive_signals(
    case: Mapping[str, Any], *, policy: LoadedPolicy | None = None
) -> dict[str, Any]:
    """Derive business signals from normalized, multi-day account facts."""

    if not isinstance(case, Mapping):
        raise ContractError("UAC input must be an object")
    loaded_policy = policy or load_policy("signal")
    policy_values = _signal_policy_values(loaded_policy)
    context = _numeric_context(case, loaded_policy)
    priority = context.get("optimization_priority")
    if priority not in {"scale", "efficiency", "balanced"}:
        raise ContractError(
            "goal.optimization_priority must be scale, efficiency, or balanced"
        )
    maturity = _derive_maturity(context)
    budget = _derive_budget_delivery(case, context)
    event_volume = _derive_event_volume(case, context, policy_values)
    target = _derive_target_constraint(case, context, maturity, budget)
    value = _derive_value_signal(case, context, maturity, event_volume, policy_values)
    split = _derive_split(case, event_volume, policy_values)
    evidence = [
        {
            "type": "ACCOUNT_EVIDENCE",
            "fact": "multi_day_budget_delivery",
            "value": budget.get("delivery_rate"),
        },
        {
            "type": "ACCOUNT_EVIDENCE",
            "fact": "mature_actual_cpa",
            "value": _round_metric(context.get("mature_actual_cpa"), 4),
        },
        {
            "type": "ACCOUNT_EVIDENCE",
            "fact": "mature_actual_roas",
            "value": _round_metric(context.get("mature_actual_roas"), 4),
        },
        {
            "type": "BUSINESS_CONSTRAINT",
            "fact": "maximum_acceptable_cpa",
            "value": context.get("maximum_acceptable_cpa"),
        },
        {
            "type": "BUSINESS_CONSTRAINT",
            "fact": "minimum_acceptable_roas",
            "value": context.get("minimum_acceptable_roas"),
        },
    ]
    return {
        "schema_version": SIGNAL_DERIVATION_SCHEMA_VERSION,
        "has_numeric_evidence": context["has_numeric_evidence"],
        "maturity": maturity,
        "budget_delivery": budget,
        "target_constraint": target,
        "event_volume": event_volume,
        "value_signal": value,
        "split_feasibility": split,
        "event_candidates": _rank_event_candidates(case, policy_values),
        "creative_quality": _creative_quality(case, policy_values),
        "policy": loaded_policy.as_record(),
        "calculation_evidence": evidence,
        "heuristics_used": [
            "multi_day_delivery_bands_are_diagnostic_not_platform_laws",
            "event_stability_uses_account_series_coefficient_of_variation",
            "proxy_event_scores_rank_only_candidates_inside_this_account",
        ],
    }


def apply_derived_signals(
    case: Mapping[str, Any], derived: Mapping[str, Any]
) -> dict[str, Any]:
    """Project derived facts onto legacy Quick gates without mutating input."""

    projected = deepcopy(dict(case))
    quick_value = projected.get("quick_ops")
    quick = dict(quick_value) if isinstance(quick_value, Mapping) else {}
    projected["quick_ops"] = quick
    if derived.get("has_numeric_evidence") is not True:
        return projected

    split = _mapping(derived.get("split_feasibility"))
    split_state = split.get("state")
    if split_state != "INSUFFICIENT_EVIDENCE" or _mapping(
        _mapping(case.get("facts")).get("split_plan")
    ):
        legacy_split = dict(_mapping(quick.get("split_capacity")))
        if split_state == "SPLIT_FEASIBLE":
            legacy_split.update(
                {
                    "budget_assessment": "sufficient",
                    "event_volume_assessment": "sufficient",
                    "isolatable": True,
                    "source": "derived_account_evidence",
                }
            )
        elif split_state == "SPLIT_BORDERLINE":
            legacy_split.update(
                {
                    "budget_assessment": "borderline",
                    "event_volume_assessment": "borderline",
                    "isolatable": True,
                    "source": "derived_account_evidence",
                }
            )
        elif split_state == "SPLIT_NOT_FEASIBLE":
            legacy_split.update(
                {
                    "budget_assessment": "insufficient",
                    "event_volume_assessment": "insufficient",
                    "isolatable": False,
                    "source": "derived_account_evidence",
                }
            )
        else:
            legacy_split.update(
                {
                    "budget_assessment": "unknown",
                    "event_volume_assessment": "unknown",
                    "isolatable": None,
                    "source": "derived_account_evidence",
                }
            )
        quick["split_capacity"] = legacy_split

    value = _mapping(derived.get("value_signal"))
    value_state = value.get("state")
    measurement = _mapping(case.get("measurement"))
    goal = _mapping(case.get("goal"))
    business_goal = str(goal.get("business_goal", "")).lower()
    event_state = _mapping(derived.get("event_volume")).get("state")
    maturity_state = _mapping(derived.get("maturity")).get("state")
    legacy_value = dict(_mapping(quick.get("value_signal")))
    if value_state == "VALUE_SIGNAL_READY":
        legacy_value.update(
            {
                "payment_reliable": True,
                "value_reliable": True,
                "currency_reliable": True,
                "duplicates_handled": measurement.get("duplicate_events") is False,
                "refunds_handled": measurement.get("payment_trial_refund_distinguished")
                is True,
                "subscriptions_defined": (
                    measurement.get("subscription_renewal_included") is True
                    if business_goal in {"subscription", "subscriptions", "retention"}
                    else True
                ),
                "delay_mature": maturity_state == "MATURE",
                "value_reconciliation": "consistent",
                "volume_assessment": (
                    "sufficient"
                    if event_state
                    in {"SUFFICIENT_AND_STABLE", "SUFFICIENT_BUT_VOLATILE"}
                    else "insufficient"
                ),
                "stability_assessment": (
                    "stable" if event_state == "SUFFICIENT_AND_STABLE" else "volatile"
                ),
                "source": "derived_account_evidence",
            }
        )
    elif value_state == "VALUE_SIGNAL_UNRELIABLE":
        legacy_value.update(
            {
                "value_reliable": False,
                "currency_reliable": False,
                "value_reconciliation": "material_mismatch",
                "source": "derived_account_evidence",
            }
        )
    elif value_state == "VALUE_SIGNAL_BORDERLINE":
        legacy_value.update(
            {
                "volume_assessment": "borderline",
                "stability_assessment": "volatile",
                "source": "derived_account_evidence",
            }
        )
    else:
        legacy_value.update(
            {
                "volume_assessment": "unknown",
                "stability_assessment": "unknown",
                "source": "derived_account_evidence",
            }
        )
    quick["value_signal"] = legacy_value

    candidates = derived.get("event_candidates")
    if isinstance(candidates, list) and candidates:
        best = next(
            (
                item
                for item in candidates
                if isinstance(item, Mapping)
                and item.get("recommendation") == "current_best_proxy"
            ),
            candidates[0],
        )
        legacy_candidate = dict(_mapping(quick.get("candidate_event")))
        ready = (
            best.get("recommendation") == "current_best_proxy"
            and maturity_state == "MATURE"
            and event_state == "SUFFICIENT_AND_STABLE"
        )
        legacy_candidate.update(
            {
                "reliable": ready,
                "delay_mature": best.get("delay_score") != "low",
                "volume_assessment": (
                    "sufficient"
                    if best.get("volume_score") != "low"
                    else "insufficient"
                ),
                "stability_assessment": "stable" if ready else "unknown",
                "relationship_to_business_goal": (
                    "stronger"
                    if best.get("payment_relationship_score") != "low"
                    else "unknown"
                ),
                "source": "derived_account_evidence",
            }
        )
        quick["candidate_event"] = legacy_candidate

    creative_quality = derived.get("creative_quality")
    if isinstance(creative_quality, list) and creative_quality:
        classifications = {
            item.get("classification")
            for item in creative_quality
            if isinstance(item, Mapping)
        }
        creative = dict(_mapping(quick.get("creative")))
        creative["asset_grain_available"] = True
        creative["mature"] = any(
            classification != "INSUFFICIENT_DATA" for classification in classifications
        )
        creative["lowest_cpi_worst_payment_rate"] = (
            "CHEAP_LOW_QUALITY" in classifications
        )
        creative["fatigued"] = "FATIGUING" in classifications
        quick["creative"] = creative
    return projected


__all__ = [
    "SIGNAL_DERIVATION_SCHEMA_VERSION",
    "apply_derived_signals",
    "derive_signals",
]
