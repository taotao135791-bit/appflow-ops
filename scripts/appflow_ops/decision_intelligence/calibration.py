"""Business calibration for Ads Decision Intelligence (v3.6.0).

Thin constants + helpers — deliberately NOT an architecture layer.
Four calibration themes (Decision Quality Calibration):

A. measurement hypotheses require actual measurement evidence
B. recent changes are confounders, not logical exclusions
C. diagnosis != action eligibility (constraint != permission to scale)
D. metric movement without enough sample is weak evidence

The first version of every threshold is CONSERVATIVE: prefer fewer false
positives over more sensitivity. Values are business calibration, never
claimed industry truth — they are expected to be tuned by real cases in
v3.6.x.
"""

from __future__ import annotations

from collections.abc import Mapping

# Metric-family movement calibration (v3.6.0). The legacy uniform 5%/10%
# thresholds remain the FALLBACK; families with an entry use their own
# (conservative) bands. ``sample_key`` is the metric that carries the
# comparison population; movement below ``min_sample`` is weak evidence.
# Downstream rates are stricter (larger material band, real conversion
# counts required) — a tiny pay count with a -40% rate is not material.
METRIC_CALIBRATION: dict[str, dict[str, object]] = {
    "ctr": {
        "stable": 0.05,
        "material": 0.10,
        "sample_key": "impressions",
        "min_sample": 5000,
    },
    "cpm": {
        "stable": 0.05,
        "material": 0.10,
        "sample_key": "impressions",
        "min_sample": 5000,
    },
    "frequency": {
        "stable": 0.05,
        "material": 0.10,
        "sample_key": "impressions",
        "min_sample": 5000,
    },
    "click_volume": {
        "stable": 0.05,
        "material": 0.10,
        "sample_key": "impressions",
        "min_sample": 5000,
    },
    "cvr": {
        "stable": 0.05,
        "material": 0.12,
        "sample_key": "clicks",
        "min_sample": 2000,
    },
    "install_rate": {
        "stable": 0.05,
        "material": 0.15,
        "sample_key": "clicks",
        "min_sample": 2000,
    },
    "registration_rate": {
        "stable": 0.05,
        "material": 0.15,
        "sample_key": "clicks",
        "min_sample": 2000,
    },
    "pay_rate": {
        "stable": 0.05,
        "material": 0.15,
        "sample_key": "payments",
        "min_sample": 20,
    },
}

# Evidence strength buckets (v3.6.0): weak evidence does not count like
# normal evidence. ``strong`` is reserved for future calibration — the
# first version only ever emits weak/normal.
SIGNAL_STRENGTHS = ("weak", "normal", "strong")

# Fallback: legacy uniform thresholds when a family has no calibration.
FALLBACK_STABLE_PCT = 0.05
FALLBACK_MATERIAL_PCT = 0.10


def thresholds_for(metric_family: str) -> tuple[float, float]:
    """(stable, material) movement thresholds for one metric family."""
    spec = METRIC_CALIBRATION.get(metric_family)
    if spec is None:
        return FALLBACK_STABLE_PCT, FALLBACK_MATERIAL_PCT
    stable = spec["stable"]
    material = spec["material"]
    assert isinstance(stable, (int, float)) and isinstance(material, (int, float))
    return float(stable), float(material)


def sample_sufficient(metrics: Mapping[str, object], metric_family: str) -> bool:
    """Metric-family aware sample sufficiency (v3.6.0).

    A movement on a tiny population (150 impressions, pay count 5 → 3) is
    weak evidence even when the run-level maturity is sufficient —
    metric-level sufficiency is NOT campaign maturity. A MISSING sample
    field keeps the legacy behavior (no gate): absence is not evidence of
    a tiny sample, and never guessed either way.
    """
    spec = METRIC_CALIBRATION.get(metric_family)
    if spec is None:
        return True
    sample_key = str(spec["sample_key"])
    value = metrics.get(sample_key)
    if not isinstance(value, (int, float)):
        return True  # no sample context: legacy fallback (not guessed)
    min_sample = spec["min_sample"]
    assert isinstance(min_sample, (int, float))
    return value >= float(min_sample)


# ── C. Action eligibility ────────────────────────────────────────────────

# Actions that scale budget/bid — only allowed when scale is eligible.
SCALE_ACTIONS = frozenset({"increase", "scale"})

# Eligibility states (lightweight, deliberately no confidence framework).
ELIGIBILITY_STATES = ("eligible", "not_eligible", "needs_more_evidence")


def scale_eligibility(facts: Mapping[str, object]) -> str:
    """Whether a scaling action (increase/scale) is currently eligible.

    Diagnosis and action eligibility are DIFFERENT: ``budget_constraint``
    proves the campaign hits its budget cap, it does NOT prove that
    increasing the budget is a good idea. Eligibility requires, at
    minimum:

    - measurement reliable (not invalid)
    - maturity sufficient (not insufficient)
    - recent change settled (no intervening budget/bid change)
    - efficiency acceptable relative to the KPI target (CPA/CPI <= target,
      or ROAS >= target)

    Missing KPI context → ``needs_more_evidence`` (conservative: wait).
    """
    if str(facts.get("measurement_state") or "") == "invalid":
        return "not_eligible"
    if str(facts.get("maturity_state") or "") == "insufficient":
        return "not_eligible"
    if (
        facts.get("recent_budget_change") is True
        or facts.get("recent_bid_change") is True
    ):
        # Recent change unsettled: a scale decision on top of it would be
        # confounded — wait for the change to settle (v3.6.0 Case 8).
        return "not_eligible"
    target_cpa = facts.get("target_cpa")
    cpa = facts.get("cpa") or facts.get("purchase_cpa") or facts.get("cost_per_result")
    if isinstance(target_cpa, (int, float)) and isinstance(cpa, (int, float)):
        if float(cpa) <= float(target_cpa):
            return "eligible"
        return "not_eligible"
    target_cpi = facts.get("target_cpi")
    cpi = facts.get("cpi")
    if isinstance(target_cpi, (int, float)) and isinstance(cpi, (int, float)):
        if float(cpi) <= float(target_cpi):
            return "eligible"
        return "not_eligible"
    roas = facts.get("roas")
    target_roas = facts.get("target_roas")
    if isinstance(roas, (int, float)) and isinstance(target_roas, (int, float)):
        if float(roas) >= float(target_roas):
            return "eligible"
        return "not_eligible"
    return "needs_more_evidence"
