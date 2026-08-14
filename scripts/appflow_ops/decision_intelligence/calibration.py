"""Business calibration for Ads Decision Intelligence (v3.6.1).

Thin constants + helpers — deliberately NOT an architecture layer.
Calibration themes (Decision Quality Calibration):

A. measurement hypotheses require actual measurement evidence
B. recent changes are confounders, not logical exclusions
C. diagnosis != action eligibility (constraint != permission to scale)
D. metric movement without enough sample is weak evidence
E. rate evidence considers BOTH base population (denominator) and
   successful-event count (numerator) when those facts are available
F. scale eligibility requires headroom, outcome volume, stability, and
   no unresolved recent-change/rival risk — a marginal KPI pass is
   never enough ("Better to miss a scale opportunity than to recommend
   a bad scale").

The first version of every threshold is CONSERVATIVE: prefer fewer false
positives over more sensitivity. Values are internal operational
heuristics, not universal benchmarks — expected to be tuned by real
cases in v3.6.x.
"""

from __future__ import annotations

from collections.abc import Mapping

# Metric-family movement calibration. The legacy uniform 5%/10%
# thresholds remain the FALLBACK for uncalibrated families.
# ``sample_key``/``min_sample`` is the base population (denominator);
# ``numerator_key``/``min_numerator`` is the successful-event count
# (numerator) when the schema carries it — 2000 clicks with 2
# conversions is NOT strong CVR evidence (v3.6.1).
METRIC_CALIBRATION: dict[str, dict[str, object]] = {
    "ctr": {
        "stable": 0.05,
        "material": 0.10,
        "sample_key": "impressions",
        "min_sample": 5000,
        "numerator_key": "clicks",
        "min_numerator": 100,
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
        "numerator_key": "conversions",
        "min_numerator": 30,
    },
    "install_rate": {
        "stable": 0.05,
        "material": 0.15,
        "sample_key": "clicks",
        "min_sample": 2000,
        "numerator_key": "installs",
        "min_numerator": 30,
    },
    "registration_rate": {
        "stable": 0.05,
        "material": 0.15,
        "sample_key": "installs",
        "min_sample": 200,
        "numerator_key": "registrations",
        "min_numerator": 30,
    },
    "pay_rate": {
        "stable": 0.05,
        "material": 0.15,
        "sample_key": "registrations",
        "min_sample": 200,
        "numerator_key": "payments",
        "min_numerator": 20,
    },
}

# Evidence strength buckets: weak evidence does not count like normal
# evidence. ``strong`` is reserved for future calibration.
SIGNAL_STRENGTHS = ("weak", "normal", "strong")

# Sample sufficiency states (v3.6.1): missing sample size is
# UNCERTAINTY, not proof of sufficiency — unknown downgrades evidence
# strength just like a tiny sample.
SAMPLE_STATES = ("sufficient", "insufficient", "unknown")

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


def sample_sufficiency(metrics: Mapping[str, object], metric_family: str) -> str:
    """sufficient | insufficient | unknown (v3.6.1).

    A movement on a tiny population (150 impressions, pay count 5 → 3)
    is weak evidence even when the run-level maturity is sufficient —
    metric-level sufficiency is NOT campaign maturity. When the base
    population or the success-event count is MISSING, the state is
    ``unknown`` (never ``sufficient``): a -25% CTR with no impressions
    fact is uncertainty, not proof of a mature sample. Rate evidence
    considers both the denominator and the numerator when available.
    """
    spec = METRIC_CALIBRATION.get(metric_family)
    if spec is None:
        return "sufficient"  # uncalibrated family: legacy behavior
    sample_key = spec["sample_key"]
    assert isinstance(sample_key, str)
    base = metrics.get(sample_key)
    if not isinstance(base, (int, float)):
        return "unknown"
    min_sample = spec["min_sample"]
    assert isinstance(min_sample, (int, float))
    if float(base) < float(min_sample):
        return "insufficient"
    numerator_key = spec.get("numerator_key")
    if numerator_key is not None and isinstance(numerator_key, str):
        numerator = metrics.get(numerator_key)
        if not isinstance(numerator, (int, float)):
            return "unknown"
        min_numerator = spec.get("min_numerator")
        assert isinstance(min_numerator, (int, float))
        if float(numerator) < float(min_numerator):
            return "insufficient"
    return "sufficient"


def sample_sufficient(metrics: Mapping[str, object], metric_family: str) -> bool:
    """Legacy boolean wrapper (sufficient only when explicitly so)."""
    return sample_sufficiency(metrics, metric_family) == "sufficient"


# ── C. Action eligibility ────────────────────────────────────────────────

# Actions that scale budget/bid — only allowed when scale is eligible.
SCALE_ACTIONS = frozenset({"increase", "scale"})

# Eligibility states (lightweight, deliberately no confidence framework).
ELIGIBILITY_STATES = ("eligible", "not_eligible", "needs_more_evidence")

# Short reason codes for deferring/blocking a scale action.
ELIGIBILITY_REASONS = (
    "thin_kpi_headroom",
    "low_conversion_volume",
    "weak_sample",
    "recent_change",
    "material_rival",
    "measurement_unreliable",
    "maturity_insufficient",
)

# Conservative headroom ratio (internal operational heuristic, NOT a
# universal benchmark): an actual CPA within 15% of target is THIN
# headroom — passing is necessary, not sufficient.
KPI_HEADROOM_RATIO = 0.85

# Minimum outcome volume before a scale decision: 1-2 conversions are
# never evidence of sustainable efficiency.
MIN_SCALE_CONVERSIONS = 20


def _kpi_headroom(facts: Mapping[str, object]) -> tuple[str | None, str | None]:
    """(headroom, reason): strong_headroom | thin_headroom | no_headroom |
    None (no KPI context). CPA/CPI: below target; ROAS: above target —
    never mixed into the same mathematical direction."""
    target_cpa = facts.get("target_cpa")
    cpa = facts.get("cpa") or facts.get("purchase_cpa") or facts.get("cost_per_result")
    if isinstance(target_cpa, (int, float)) and isinstance(cpa, (int, float)):
        if float(cpa) <= float(target_cpa) * KPI_HEADROOM_RATIO:
            return "strong_headroom", None
        if float(cpa) <= float(target_cpa):
            return "thin_headroom", "thin_kpi_headroom"
        return "no_headroom", None
    target_cpi = facts.get("target_cpi")
    cpi = facts.get("cpi")
    if isinstance(target_cpi, (int, float)) and isinstance(cpi, (int, float)):
        if float(cpi) <= float(target_cpi) * KPI_HEADROOM_RATIO:
            return "strong_headroom", None
        if float(cpi) <= float(target_cpi):
            return "thin_headroom", "thin_kpi_headroom"
        return "no_headroom", None
    roas = facts.get("roas")
    target_roas = facts.get("target_roas")
    if isinstance(roas, (int, float)) and isinstance(target_roas, (int, float)):
        if float(roas) >= float(target_roas) / KPI_HEADROOM_RATIO:
            return "strong_headroom", None
        if float(roas) >= float(target_roas):
            return "thin_headroom", "thin_kpi_headroom"
        return "no_headroom", None
    return None, None


def _outcome_volume(facts: Mapping[str, object]) -> int | None:
    """Absolute outcome volume for the selected platform (any canonical
    conversion count). None when no outcome volume fact exists."""
    for key in ("conversions", "purchases", "payments", "installs"):
        value = facts.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def scale_eligibility(
    facts: Mapping[str, object],
) -> tuple[str, str | None]:
    """(state, reason_code): whether a scaling action is currently
    eligible — v3.6.1.

    Diagnosis and action eligibility are DIFFERENT: ``budget_constraint``
    proves the campaign hits its budget cap, it does NOT prove that
    increasing the budget is a good idea. KPI pass is NECESSARY but NOT
    SUFFICIENT — eligibility also requires KPI headroom (a marginal pass
    is thin), sufficient outcome volume (1-2 conversions are never
    evidence of sustainable efficiency), and no unresolved recent-change
    risk. Missing KPI/volume context → ``needs_more_evidence``
    (conservative: wait).
    """
    if str(facts.get("measurement_state") or "") == "invalid":
        return "not_eligible", "measurement_unreliable"
    if str(facts.get("maturity_state") or "") == "insufficient":
        return "not_eligible", "maturity_insufficient"
    if (
        facts.get("recent_budget_change") is True
        or facts.get("recent_bid_change") is True
    ):
        # Recent change unsettled: a scale decision on top of it would be
        # confounded — wait for the change to settle (v3.6.0 Case 8).
        return "not_eligible", "recent_change"
    headroom, reason = _kpi_headroom(facts)
    if headroom == "no_headroom":
        return "not_eligible", None
    if headroom == "thin_headroom":
        return "needs_more_evidence", reason
    if headroom is None:
        return "needs_more_evidence", None  # no KPI context
    volume = _outcome_volume(facts)
    if volume is not None and volume < MIN_SCALE_CONVERSIONS:
        return "needs_more_evidence", "low_conversion_volume"
    if volume is None:
        # No outcome volume fact: a small impression base is weak sample.
        impressions = facts.get("impressions")
        if isinstance(impressions, (int, float)) and float(impressions) < 5000:
            return "needs_more_evidence", "weak_sample"
    return "eligible", None
