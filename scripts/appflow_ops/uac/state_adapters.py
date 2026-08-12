"""UAC → State projection adapters (v3.3.3).

These adapters are projections ONLY: they select and rename fields from the
deterministic engine's output into the state vocabulary. They never
recompute diagnosis, policy, maturity, or measurement — the deterministic
engine is the source of truth. Sparse by design: only facts that future
reasoning can actually use are kept; raw exports and full reports never
enter state.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

# Metric keys worth persisting for future reasoning. Missing keys are simply
# omitted (sparse); this is a projection, not a schema contract.
OBSERVATION_METRIC_KEYS = (
    "spend",
    "installs",
    "registrations",
    "payments",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "cpi",
    "cpa",
    "daily_budget",
    "target_cpa",
)

_MEASUREMENT_MAP = {
    "measurement_reliable": "stable",
    "measurement_unreliable": "invalid",
}
_MATURITY_MAP = {
    "LEARNABLE": "sufficient",
    "NOT_LEARNABLE": "insufficient",
    "MATURE": "sufficient",
    "NOT_MATURE": "insufficient",
}


def project_analysis_observation(
    case: Mapping[str, Any], analysis: Mapping[str, Any]
) -> dict[str, Any]:
    """Project one analyze result into observation facts.

    Keeps: business metrics (from the normalized case's own metrics),
    measurement/maturity state (from the engine output), and the key funnel
    rate/drop (from the engine's funnel state). Everything else stays in the
    analysis files, not in state.
    """

    facts: dict[str, Any] = {}
    metrics = case.get("facts", {}).get("metrics", {})
    if isinstance(metrics, Mapping):
        for key in OBSERVATION_METRIC_KEYS:
            if key in metrics and metrics[key] is not None:
                facts[key] = metrics[key]
    measurement = analysis.get("measurement_state", {}).get("status")
    facts["measurement_state"] = _MEASUREMENT_MAP.get(str(measurement), "unknown")
    learning = analysis.get("learning_eligibility", {}).get("status")
    facts["maturity_state"] = _MATURITY_MAP.get(str(learning), "unknown")
    funnel = analysis.get("funnel_state", {})
    if isinstance(funnel, Mapping):
        rates = funnel.get("observed_rates")
        if isinstance(rates, list) and rates:
            facts["funnel_rates"] = [
                {
                    "from": rate.get("from"),
                    "to": rate.get("to"),
                    "rate": rate.get("rate"),
                    "drop": rate.get("drop"),
                }
                for rate in rates
                if isinstance(rate, Mapping)
            ]
        largest_drop = funnel.get("largest_observed_drop")
        if isinstance(largest_drop, Mapping) and largest_drop.get("drop") is not None:
            facts["largest_funnel_drop"] = largest_drop["drop"]
    return facts


def project_quick_decision(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one decide result into decision metadata.

    Keeps: maturity state (from derived_signals), policy version identifiers
    (never policy contents), measurement (unknown — the quick-decision
    result does not output a measurement verdict), and a review_after date
    derived from the engine's review_condition.after_days.

    ``evidence_refs`` are resolved by the caller (the runtime write path),
    not here.
    """

    derived = result.get("derived_signals", {})
    metadata: dict[str, Any] = {}
    maturity = derived.get("maturity", {})
    if isinstance(maturity, Mapping) and maturity.get("state"):
        metadata["maturity_state"] = _MATURITY_MAP.get(
            str(maturity["state"]), "unknown"
        )
    else:
        metadata["maturity_state"] = "unknown"
    metadata["measurement_state"] = "unknown"
    policy = result.get("policy", {})
    if isinstance(policy, Mapping):
        constraints: dict[str, Any] = {}
        for kind in ("numeric", "signal"):
            entry = policy.get(kind)
            if isinstance(entry, Mapping) and entry.get("policy_version"):
                constraints[f"{kind}_policy"] = entry["policy_version"]
        if constraints:
            metadata["policy_constraints"] = constraints
    review = result.get("review_condition")
    if isinstance(review, Mapping) and review.get("after_days"):
        metadata["review_after"] = (
            date.today() + timedelta(days=int(review["after_days"]))
        ).isoformat()
    return metadata
