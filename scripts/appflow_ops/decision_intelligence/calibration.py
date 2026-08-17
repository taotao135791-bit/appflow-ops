"""Business calibration for Ads Decision Intelligence (v3.6.4).

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
G. the PRIMARY KPI (explicit or unambiguously implied by a single
   target) drives the target/actual comparison, the headroom judgment
   AND the outcome-volume check — never a hardcoded CPA→CPI→ROAS
   precedence, and never an install volume standing in for a pay/purchase
   KPI (v3.6.2). All goal sources are validated TOGETHER: primary_kpi /
   optimization_goal / conversion_event must agree; a purchase event
   cannot silently choose purchase_cpa over ROAS (v3.6.4).
H. ACTION ELIGIBILITY != ACTION READINESS (v3.6.4): an action may be
   eligible in principle but not ready now because the previous material
   change has not accumulated enough NEW evidence (elapsed time +
   KPI-matched window outcomes). One material lever at a time; wait must
   name what evidence triggers the next review. Timing thresholds are
   conservative internal operational heuristics, not universal media
   benchmarks.

Values are internal operational heuristics, not universal benchmarks —
expected to be tuned by real cases in v3.6.x.
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


def kpi_outcome_key(kpi_type: str) -> str | None:
    """The cumulative counter KEY matching a KPI family (v3.6.5):
    CPI → installs, pay CPA → payments, ... — the state-native decision
    window subtracts THIS counter between a comparable pre-change
    baseline and the current observation, never a borrowed metric."""
    spec = _KPI_SPECS.get(kpi_type)
    return spec[2] if spec is not None else None


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

# Short reason codes for deferring/blocking a scale action (v3.6.2
# adds the positive-safety and KPI-alignment reasons; v3.6.4 adds the
# goal-conflict and timing reasons).
ELIGIBILITY_REASONS = (
    "thin_kpi_headroom",
    "low_conversion_volume",
    "weak_sample",
    "recent_change",
    "material_rival",
    "measurement_unreliable",
    "maturity_insufficient",
    "missing_outcome_volume",
    "measurement_unknown",
    "maturity_unknown",
    "ambiguous_primary_kpi",
    "ambiguous_goal_semantics",
    "recent_change_unsettled",
)

# ── Primary KPI (v3.6.2) ────────────────────────────────────────────────

# The only KPI types the current product needs. An explicit primary_kpi
# outside this set is UNKNOWN (conservative) — never silently coerced.
PRIMARY_KPIS = (
    "cpi",
    "cpa",
    "registration_cpa",
    "pay_cpa",
    "purchase_cpa",
    "roas",
)

# primary_kpi → (target_key, actual_key, outcome_key, direction).
# direction: "lower" = actual below target is better; "higher" = above.
_KPI_SPECS: dict[str, tuple[str, str, str, str]] = {
    "cpi": ("target_cpi", "cpi", "installs", "lower"),
    "cpa": ("target_cpa", "cpa", "conversions", "lower"),
    "registration_cpa": (
        "target_registration_cpa",
        "registration_cpa",
        "registrations",
        "lower",
    ),
    "pay_cpa": ("target_pay_cpa", "pay_cpa", "payments", "lower"),
    "purchase_cpa": (
        "target_purchase_cpa",
        "purchase_cpa",
        "purchases",
        "lower",
    ),
    # ROAS outcome is resolved separately (v3.6.3): generic conversions
    # are NOT automatically revenue-generating outcomes.
    "roas": ("target_roas", "roas", "purchases", "higher"),
}

# KPI → the conversion EVENT it optimizes (v3.6.3 §22): the goal is not
# just "lower is better" — pay_cpa means the pay/payment event.
_KPI_EVENTS: dict[str, str] = {
    "cpi": "install",
    "cpa": "conversion",
    "registration_cpa": "registration",
    "pay_cpa": "pay",
    "purchase_cpa": "purchase",
    "roas": "revenue",
}

# Event/goal semantics → KPI normalization (v3.6.3 §16). conversion_event
# and optimization_goal are EVENT semantics (pay, purchase, ...) — related
# to but NOT literal synonyms of the KPI enum (pay_cpa, purchase_cpa, ...).
_EVENT_TO_KPI: dict[str, str] = {
    "install": "cpi",
    "registration": "registration_cpa",
    "pay": "pay_cpa",
    "payment": "pay_cpa",
    "purchase": "purchase_cpa",
    "revenue": "roas",
    "conversion": "cpa",
}


# KPI-family minimum outcome evidence before a scale decision (v3.6.3
# §42-51). Outcome density differs: installs are high-frequency events
# and need MORE evidence; deep pay/purchase events are sparse and cannot
# mechanically demand the same counts. Conservative internal operational
# heuristics — NOT universal industry benchmarks; unknown families never
# fall back to an arbitrary universal count.
KPI_SCALE_MINIMUMS: dict[str, int] = {
    "cpi": 50,
    "registration_cpa": 30,
    "cpa": 20,  # legacy MIN_SCALE_CONVERSIONS for the generic family
    "pay_cpa": 10,
    "purchase_cpa": 10,
    "roas": 10,
}


def normalize_goal_to_kpi(value: str) -> str | None:
    """Normalize a goal/event string to a KPI type (v3.6.3 §16): a
    literal KPI enum passes through; event semantics (install / pay /
    payment / purchase / revenue / conversion) map to their KPI family.
    Returns None for unknown values — never guessed."""
    normalized = value.strip().lower()
    if normalized in PRIMARY_KPIS:
        return normalized
    return _EVENT_TO_KPI.get(normalized)


# Facts keys consulted when the observation declares its goal. Only
# ``primary_kpi`` is the literal KPI enum; the other two carry EVENT
# semantics and are normalized through ``normalize_goal_to_kpi`` (v3.6.3).
_PRIMARY_KPI_KEYS = ("primary_kpi", "optimization_goal", "conversion_event")


def resolve_primary_kpi(facts: Mapping[str, object]) -> tuple[str | None, str | None]:
    """(kpi_type, reason): which KPI governs THIS action (v3.6.4).

    ALL goal sources are validated TOGETHER — never ``A or B`` first-
    wins (§A.1-3):

    1. explicit ``primary_kpi`` is authoritative; a simultaneously
       declared goal/event that normalizes to a DIFFERENT KPI is a real
       conflict → ambiguous (never guess);
    2. ``optimization_goal`` and ``conversion_event`` are BOTH normalized
       and must AGREE — install vs pay → ``ambiguous_goal_semantics``;
       a revenue goal + purchase event resolves to ROAS (§A.4);
    3. a purchase event with a ROAS target present is not enough to pick
       purchase_cpa vs roas → ``ambiguous_primary_kpi`` unless a goal
       (revenue) disambiguates;
    4. resolved event/goal + the matching target exists → that KPI;
    5. exactly ONE target → that KPI (backward compatible);
    6. multiple targets without any declaration → ambiguous;
    7. no targets → (None, None).

    ``conversion_event="pay"`` is NOT the literal enum ``pay_cpa`` — it
    is an event semantic that normalizes to pay_cpa when appropriate.
    """
    explicit = facts.get("primary_kpi")
    goal = facts.get("optimization_goal")
    event = facts.get("conversion_event")
    explicit_kpi = (
        normalize_goal_to_kpi(explicit)
        if isinstance(explicit, str) and explicit
        else None
    )
    goal_kpi = normalize_goal_to_kpi(goal) if isinstance(goal, str) and goal else None
    event_kpi = (
        normalize_goal_to_kpi(event) if isinstance(event, str) and event else None
    )
    if isinstance(explicit, str) and explicit:
        if explicit_kpi is None:
            return None, "ambiguous_primary_kpi"  # unknown value: no guessing
        if (goal_kpi is not None and goal_kpi != explicit_kpi) or (
            event_kpi is not None and event_kpi != explicit_kpi
        ):
            # Explicit KPI vs explicit goal/event conflict: do not guess.
            return None, "ambiguous_primary_kpi"
        return explicit_kpi, None
    if goal_kpi is not None and event_kpi is not None and goal_kpi != event_kpi:
        if "roas" in (goal_kpi, event_kpi) and "purchase_cpa" in (goal_kpi, event_kpi):
            resolved: str | None = "roas"  # revenue goal disambiguates (§A.4)
        else:
            # Conflicting goal semantics (install vs pay): never pick one.
            return None, "ambiguous_goal_semantics"
    else:
        resolved = goal_kpi if goal_kpi is not None else event_kpi
    if resolved is not None:
        # §A.4: a purchase event alone cannot choose purchase_cpa vs roas
        # when a ROAS target is also present.
        if resolved == "purchase_cpa" and isinstance(
            facts.get("target_roas"), (int, float)
        ):
            return None, "ambiguous_primary_kpi"
        target_key = _KPI_SPECS[resolved][0]
        if isinstance(facts.get(target_key), (int, float)):
            # Event/goal + matching target: unambiguous (§16/18/20).
            return resolved, None
    present_targets = [
        kpi
        for kpi, (target_key, _, _, _) in _KPI_SPECS.items()
        if isinstance(facts.get(target_key), (int, float))
    ]
    if len(present_targets) == 1:
        return present_targets[0], None
    if len(present_targets) > 1:
        return None, "ambiguous_primary_kpi"
    return None, None


def resolve_kpi_outcome_volume(
    kpi_type: str, facts: Mapping[str, object]
) -> int | None:
    """The outcome count MATCHING the KPI being optimized (v3.6.3):
    CPI → installs, registration CPA → registrations, pay CPA → payments,
    purchase CPA → purchases, generic CPA → canonical conversions. NEVER
    first-available across KPIs — 1000 installs cannot stand in for a
    pay-CPA scale decision.

    ROAS (v3.6.3 §23-26): generic conversions are NOT automatically
    revenue-generating outcomes — purchases (or conversions ONLY when the
    declared conversion event is known to map to purchase/pay/revenue)
    count as outcome evidence; unknown conversion meaning → None.
    """
    spec = _KPI_SPECS.get(kpi_type)
    if spec is None:
        return None
    _, _, outcome_key, _ = spec
    if kpi_type == "roas":
        purchases = facts.get("purchases")
        if isinstance(purchases, (int, float)):
            return int(purchases)
        event = facts.get("conversion_event") or facts.get("optimization_goal")
        if isinstance(event, str) and event:
            event_kpi = normalize_goal_to_kpi(event)
            if event_kpi in ("purchase_cpa", "pay_cpa", "roas"):
                conversions = facts.get("conversions")
                if isinstance(conversions, (int, float)):
                    return int(conversions)
        return None  # generic conversions without revenue semantics
    for key in (outcome_key,):
        value = facts.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def resolve_primary_kpi_context(
    facts: Mapping[str, object],
) -> dict[str, object] | None:
    """One lightweight resolution of the KPI context for the current
    action (v3.6.3). Returns None when no KPI context exists at all;
    otherwise a plain dict with:

    - ``kpi_type``: the governing KPI (None when ambiguous)
    - ``target`` / ``actual``: numeric target and actual (None when the
      fact is missing)
    - ``outcome_event``: the conversion EVENT the KPI optimizes
      (install / conversion / registration / pay / purchase / revenue)
    - ``outcome_volume``: the KPI-matched outcome count (None when
      missing)
    - ``direction``: "lower" | "higher" (which way is better)
    - ``headroom``: strong_headroom | thin_headroom | no_headroom | None
    - ``reason``: ambiguous_primary_kpi | thin_kpi_headroom | None
    - ``resolution_source``: explicit_primary_kpi | optimization_goal |
      conversion_event | single_target (audit)
    """
    kpi_type, kpi_reason = resolve_primary_kpi(facts)
    if kpi_type is None and kpi_reason is None:
        return None  # no KPI context at all
    context: dict[str, object] = {
        "kpi_type": kpi_type,
        "target": None,
        "actual": None,
        "outcome_event": _KPI_EVENTS.get(kpi_type) if kpi_type else None,
        "outcome_volume": None,
        "direction": None,
        "headroom": None,
        "reason": kpi_reason,
        "resolution_source": _resolution_source(facts),
    }
    if kpi_type is None:
        return context
    target_key, actual_key, _, direction = _KPI_SPECS[kpi_type]
    target = facts.get(target_key)
    actual = facts.get(actual_key)
    if kpi_type == "cpa" and not isinstance(actual, (int, float)):
        actual = facts.get("cost_per_result")  # platform alias for CPA
    if isinstance(target, (int, float)) and isinstance(actual, (int, float)):
        context["target"] = float(target)
        context["actual"] = float(actual)
        context["direction"] = direction
        if direction == "higher":
            if float(actual) >= float(target) / KPI_HEADROOM_RATIO:
                context["headroom"] = "strong_headroom"
            elif float(actual) >= float(target):
                context["headroom"] = "thin_headroom"
                context["reason"] = "thin_kpi_headroom"
            else:
                context["headroom"] = "no_headroom"
        else:
            if float(actual) <= float(target) * KPI_HEADROOM_RATIO:
                context["headroom"] = "strong_headroom"
            elif float(actual) <= float(target):
                context["headroom"] = "thin_headroom"
                context["reason"] = "thin_kpi_headroom"
            else:
                context["headroom"] = "no_headroom"
    context["outcome_volume"] = resolve_kpi_outcome_volume(kpi_type, facts)
    return context


def _resolution_source(facts: Mapping[str, object]) -> str | None:
    """Audit: which input resolved the primary KPI (v3.6.3 §21)."""
    if isinstance(facts.get("primary_kpi"), str) and facts.get("primary_kpi"):
        return "explicit_primary_kpi"
    if isinstance(facts.get("optimization_goal"), str) and facts.get(
        "optimization_goal"
    ):
        return "optimization_goal"
    if isinstance(facts.get("conversion_event"), str) and facts.get("conversion_event"):
        return "conversion_event"
    return "single_target"


# Conservative headroom ratio (internal operational heuristic, NOT a
# universal benchmark): an actual CPA within 15% of target is THIN
# headroom — passing is necessary, not sufficient.
KPI_HEADROOM_RATIO = 0.85

# Minimum outcome volume before a scale decision: 1-2 conversions are
# never evidence of sustainable efficiency.
MIN_SCALE_CONVERSIONS = 20


def _kpi_headroom(facts: Mapping[str, object]) -> tuple[str | None, str | None]:
    """(headroom, reason) resolved from the PRIMARY KPI (v3.6.2) — never
    a hardcoded CPA→CPI→ROAS precedence. None/None when no KPI context.
    ``ambiguous_primary_kpi`` surfaces when multiple targets exist without
    a declaration (the caller must not guess)."""
    context = resolve_primary_kpi_context(facts)
    if context is None:
        return None, None
    if context.get("kpi_type") is None:
        reason = context.get("reason")
        return None, str(reason) if reason else None
    headroom = context.get("headroom")
    reason = context.get("reason")
    return (str(headroom) if headroom else None), (str(reason) if reason else None)


def _outcome_volume(facts: Mapping[str, object]) -> int | None:
    """Legacy wrapper: outcome volume of the (implied or declared)
    primary KPI — never first-available across KPI families (v3.6.2)."""
    kpi_type, _ = resolve_primary_kpi(facts)
    if kpi_type is None:
        return None
    return resolve_kpi_outcome_volume(kpi_type, facts)


def scale_eligibility(
    facts: Mapping[str, object],
) -> tuple[str, str | None]:
    """(state, reason_code): whether a scaling action is currently
    eligible — v3.6.2.

    Diagnosis and action eligibility are DIFFERENT: ``budget_constraint``
    proves the campaign hits its budget cap, it does NOT prove that
    increasing the budget is a good idea. Scale requires POSITIVE
    evidence on every axis (v3.6.2):

    - measurement explicitly ``stable`` (``unknown`` is not enough —
      investigation may continue on unknown safety, scale may not);
    - maturity explicitly ``sufficient``;
    - the PRIMARY KPI is known (explicit declaration or a single target;
      multiple targets without a declaration → ``ambiguous_primary_kpi``);
    - headroom on THAT KPI is strong (a marginal pass is thin);
    - the KPI-MATCHED outcome volume exists and is sufficient (pay CPA
      never borrows installs; missing outcome volume is not scale
      evidence — impressions cannot stand in for conversions).
    """
    measurement = str(facts.get("measurement_state") or "")
    if measurement == "invalid":
        return "not_eligible", "measurement_unreliable"
    if measurement == "unknown" or not measurement:
        return "needs_more_evidence", "measurement_unknown"
    maturity = str(facts.get("maturity_state") or "")
    if maturity == "insufficient":
        return "not_eligible", "maturity_insufficient"
    if maturity == "unknown" or not maturity:
        return "needs_more_evidence", "maturity_unknown"
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
        if reason == "ambiguous_primary_kpi":
            return "needs_more_evidence", "ambiguous_primary_kpi"
        if reason == "ambiguous_goal_semantics":
            # v3.6.4: conflicting goal sources (install vs pay) defer.
            return "needs_more_evidence", "ambiguous_goal_semantics"
        return "needs_more_evidence", None  # no KPI context
    volume = _outcome_volume(facts)
    if volume is None:
        # v3.6.2: unknown outcome volume is NOT scale evidence — impressions
        # can prove a CTR sample, never a stable CPA/pay CPA.
        return "needs_more_evidence", "missing_outcome_volume"
    # v3.6.3 §42-51: minimum scale evidence is KPI-family aware — 20
    # installs and 20 payments are NOT the same scale evidence. Unknown
    # KPI family never falls back to an arbitrary universal count.
    kpi_type, _ = resolve_primary_kpi(facts)
    minimum = KPI_SCALE_MINIMUMS.get(kpi_type or "")
    if minimum is None:
        return "needs_more_evidence", None
    if volume < minimum:
        return "needs_more_evidence", "low_conversion_volume"
    return "eligible", None


# ── H. Action readiness & timing (v3.6.4) ───────────────────────────────

# Action readiness states (v3.6.4 §B.8): eligibility is NOT readiness.
ACTION_READINESS_STATES = ("ready", "wait", "needs_more_evidence", "not_eligible")

# Action magnitude (v3.6.4 §H): small | normal | none — never an
# aggressive band; numeric Safety remains the final cap.
ACTION_MAGNITUDES = ("small", "normal", "none")

# Timing calibration constants (v3.6.4 §P): all thresholds live HERE,
# never scattered magic numbers. Conservative internal operational
# heuristics — starting calibration values, NOT universal platform
# benchmarks.
TIMING_CALIBRATION: dict[str, dict[str, object]] = {
    # Post-change settling: how much NEW evidence must accumulate after
    # the last confirmed material Change before another material action
    # (scale / descale / bid change) is allowed. Lifetime totals do NOT
    # prove post-change readiness.
    "change_settle": {
        "min_elapsed_hours": 24,
        "min_new_outcomes": {
            "cpi": 100,  # high-frequency event: more evidence required
            "registration_cpa": 50,
            "cpa": 30,
            "pay_cpa": 15,  # deep events are sparse
            "purchase_cpa": 15,
            "roas": 15,
        },
    },
    # New / refreshed creative test window: enough impressions before
    # judging a creative (early winners and early losers are both noise).
    "creative_test": {
        "min_impressions": 2000,
    },
}

# Negative trend signals that can justify a descale (v3.6.4 §I).
_DESCALE_TREND_SIGNALS = (
    "cvr_trend_down",
    "pay_rate_trend_down",
    "registration_rate_trend_down",
    "install_rate_trend_down",
    "ctr_trend_down",
)

# Review trigger labels per KPI family (v3.6.4 §M): wait decisions must
# name what evidence triggers the next review.
_REVIEW_TRIGGERS: dict[str, str] = {
    "cpi": "more_installs",
    "registration_cpa": "more_registrations",
    "pay_cpa": "more_pay_outcomes",
    "purchase_cpa": "more_purchase_outcomes",
    "roas": "more_revenue_outcomes",
    "cpa": "more_outcomes",
}


def _hours_between(earlier_iso: str, later_iso: str) -> float | None:
    """Elapsed hours between two ISO timestamps; None when unparsable."""
    try:
        from datetime import datetime

        def _parse(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        delta = _parse(later_iso) - _parse(earlier_iso)
        return max(delta.total_seconds() / 3600.0, 0.0)
    except (ValueError, TypeError):
        return None


def evaluate_action_readiness(
    facts: Mapping[str, object],
    window_context: Mapping[str, object] | None = None,
) -> tuple[str, str | None, str | None]:
    """(state, wait_reason, next_review_trigger): v3.6.4 §B-G.

    Eligibility says the action is principled; readiness says it is
    safe to execute NOW. After the last confirmed material Change,
    another material action requires enough NEW evidence: elapsed time
    AND KPI-matched window outcomes. Missing either dimension defers —
    time alone is not enough, and lifetime totals never prove
    post-change readiness. No pending change → ready (eligibility
    governs).

    v3.6.5: the window outcome comes from the STATE-DERIVED decision
    window first (``window_context["window_outcomes"]`` +
    ``window_status`` — reconstructed by the runtime from persisted
    observations and confirmed changes); the legacy caller-supplied
    ``window_outcomes`` fact is a compatibility fallback only. A
    window whose counters are not comparable (entity change, counter
    reset, missing baseline) waits — never a guessed delta.
    """
    window = window_context or {}
    change_at = window.get("last_change_effective_at")
    current_at = window.get("current_observed_at")
    if not isinstance(change_at, str) or not isinstance(current_at, str):
        return "ready", None, None  # no pending change
    window_status = window.get("window_status")
    if window_status == "not_comparable":
        # Cumulative counters cannot be subtracted across entity
        # changes or counter resets (v3.6.5 §12-14) — wait, never a
        # negative or guessed outcome count.
        return "wait", "counter_not_comparable", "more_evidence"
    if window_status == "unknown":
        # Missing baseline / missing counter / unknown identity: the
        # runtime could not reconstruct the post-change window.
        return "wait", "recent_change_unsettled", "more_evidence"
    elapsed = _hours_between(change_at, current_at)
    if elapsed is None:
        return "wait", "recent_change_unsettled", "more_evidence"
    kpi_type, _ = resolve_primary_kpi(facts)
    spec = TIMING_CALIBRATION["change_settle"]
    min_hours = spec["min_elapsed_hours"]
    min_new = spec["min_new_outcomes"]
    assert isinstance(min_new, Mapping)
    min_outcomes = min_new.get(kpi_type or "cpa")
    window_outcomes = window.get("window_outcomes")
    if not isinstance(window_outcomes, (int, float)):
        # Compatibility fallback: legacy caller-supplied fact (v3.6.5
        # §45 — derived state always wins; this is only read when the
        # runtime could not derive a window at all).
        window_outcomes = facts.get("window_outcomes")
    if (
        isinstance(min_hours, (int, float))
        and isinstance(min_outcomes, (int, float))
        and isinstance(window_outcomes, (int, float))
        and elapsed >= float(min_hours)
        and float(window_outcomes) >= float(min_outcomes)
    ):
        return "ready", None, None
    return "wait", "recent_change_unsettled", _review_trigger(kpi_type)


def _review_trigger(kpi_type: str | None) -> str:
    return _REVIEW_TRIGGERS.get(kpi_type or "cpa", "more_outcomes")


def resolve_action_magnitude(
    action: str,
    facts: Mapping[str, object],
    material_context_ids: tuple[str, ...] = (),
) -> str:
    """small | normal | none (v3.6.4 §H): scale is small when headroom is
    thin, material context is present (market-wide CPM up), or the KPI is
    a deep event; normal only with strong headroom, no material context,
    settled history. Descale is always small (§I). Numeric Safety remains
    the final cap — magnitude never invents its own percentages."""
    if action not in ("increase", "scale", "decrease"):
        return "none"
    if action == "decrease":
        return "small"
    context = resolve_primary_kpi_context(facts)
    if material_context_ids:
        return "small"  # market context: stay staged, never enlarge
    if context is not None and context.get("kpi_type") in (
        "pay_cpa",
        "purchase_cpa",
        "roas",
    ):
        return "small"  # deep-event KPI: first scale is small
    headroom = str(context.get("headroom") or "") if context else ""
    if headroom == "strong_headroom":
        return "normal"
    return "small"


def resolve_action_lever(hypothesis_id: str | None) -> str | None:
    """budget | bid | creative | measurement | None (v3.6.4 §J): the ONE
    material lever the action moves. Sequencing means never moving two
    levers in one decision (one material lever at a time)."""
    if hypothesis_id == "budget_constraint":
        return "budget"
    if hypothesis_id == "bid_constraint":
        return "bid"
    if hypothesis_id in (
        "creative_fatigue",
        "creative_message_mismatch",
        "creative_format_mismatch",
    ):
        return "creative"
    if hypothesis_id in (
        "measurement_instability",
        "install_measurement_issue",
        "shared_measurement_issue",
    ):
        return "measurement"
    return None


def evaluate_descale_candidate(
    facts: Mapping[str, object],
    top_supporting: tuple[str, ...],
) -> bool:
    """v3.6.4 §I: a small decrease is justified only when the KPI is
    materially worse AND the deterioration is persistent (negative trend
    in the SELECTED evidence) with no transient explanation: measurement
    stable, maturity sufficient, no recent change, mature sample. Bad
    KPI right after a change is a window problem, never an automatic
    descale (no ping-pong)."""
    if str(facts.get("measurement_state") or "") != "stable":
        return False
    if str(facts.get("maturity_state") or "") != "sufficient":
        return False
    if (
        facts.get("recent_budget_change") is True
        or facts.get("recent_bid_change") is True
    ):
        return False
    if not any(signal in top_supporting for signal in _DESCALE_TREND_SIGNALS):
        return False
    context = resolve_primary_kpi_context(facts)
    if context is None or context.get("headroom") != "no_headroom":
        return False
    volume = context.get("outcome_volume")
    # tiny sample: wait, never react
    return isinstance(volume, (int, float)) and float(volume) >= 10


def resolve_creative_action(
    hypothesis_id: str,
    supporting: tuple[str, ...],
    facts: Mapping[str, object],
) -> str:
    """v3.6.4 §K/L: refresh | retest | pause | hold | observe for creative
    hypotheses — fatigue is not only replace:

    - pause: a SPECIFIC creative is consistently worse with sufficient
      sample and no confounder (only_one_creative_declines + mature);
    - retest: weak/inconclusive evidence or a recent delivery change
      confounds the result (recent budget/bid change present);
    - hold: a new creative is still in its test window (recent creative
      change + tiny sample);
    - refresh: fatigue with acceptable overall KPI (default).

    A creative issue never automatically causes a budget change."""
    if hypothesis_id not in ("creative_fatigue", "creative_message_mismatch"):
        return "observe"
    min_impressions = TIMING_CALIBRATION["creative_test"]["min_impressions"]
    assert isinstance(min_impressions, (int, float))
    impressions = facts.get("impressions")
    if (
        facts.get("recent_creative_change") is True
        or facts.get("recent_campaign_restart") is True
    ):
        if not isinstance(impressions, (int, float)) or float(impressions) < float(
            min_impressions
        ):
            return "hold"  # new creative too early to judge
    if (
        facts.get("recent_budget_change") is True
        or facts.get("recent_bid_change") is True
    ):
        return "retest"  # delivery change confounds: retest, never pause
    if (
        facts.get("only_one_creative_declines") is True
        and isinstance(impressions, (int, float))
        and float(impressions) >= float(min_impressions)
    ):
        return "pause"  # clear specific loser with sufficient sample
    return "refresh"
