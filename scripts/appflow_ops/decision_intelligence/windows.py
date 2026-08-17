"""State-native decision windows (v3.6.5 → v3.6.6).

Timing is a native consequence of PERSISTED STATE, not caller arithmetic.
The runtime reconstructs "what happened since the last confirmed change"
from the bounded state it already loads:

    selected platform/entity
    → relevant action family
    → latest relevant confirmed Change for THAT entity
    → comparable pre-change Observation
    → are the KPI counters semantically comparable (count mode)?
    → normalize timestamps to real instants
    → derived KPI-aligned post-change outcome delta

v3.6.6 makes every derived window SEMANTICALLY VALID before its
duration is calibrated:

- A number is not automatically a cumulative counter: only an explicit
  ``count_mode = cumulative`` allows ``current − baseline``; interval
  values are never subtracted; missing semantics are ``unknown``.
- A Change belongs to an ENTITY, not only a platform: a Campaign A
  budget change never resets Campaign B's window.
- Relevant change types depend on the ACTION FAMILY being evaluated:
  a creative change resets the creative test window, never the budget
  scale window.
- Timestamps compare as parsed timezone-aware instants, never ISO
  strings.

Deliberately THIN helpers only — no Window Engine, no Entity Runtime,
no Metric Ontology, no interval aggregation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .calibration import kpi_outcome_key, resolve_primary_kpi
from .evidence import comparable_identity, observations_comparable

# Change types that materially reset the decision window (v3.6.5 §6-8).
# Kept as the broad legacy/compatibility set; v3.6.6 callers resolve
# relevance per ACTION FAMILY via ``relevant_change_types()`` instead.
MATERIAL_CHANGE_TYPES = (
    "budget",
    "bid",
    "creative",
    "campaign_restart",
    "campaign",
    "audience",
)

# Action families the window resolver knows about (v3.6.6 §29-32):
# budget/bid/campaign restart reset scale/descale windows; creative
# changes and restarts reset the creative test window; audience changes
# and restarts reset audience windows. A creative change alone NEVER
# resets the scale/descale window (confounder context only, §33-34).
ACTION_FAMILIES = ("scale", "descale", "creative", "audience")

RELEVANT_CHANGE_TYPES_BY_ACTION_FAMILY: dict[str, tuple[str, ...]] = {
    "scale": ("budget", "bid", "campaign_restart"),
    "descale": ("budget", "bid", "campaign_restart"),
    "creative": ("creative", "campaign_restart"),
    "audience": ("audience", "campaign_restart"),
}

# Outcome count semantics (v3.6.6 §1-6): a number is not automatically
# a cumulative counter. Only ``cumulative`` counters are subtractable;
# ``interval`` values are independent reporting periods (daily/24h
# counts) and never participate in a cumulative delta; ``unknown`` is
# the conservative default whenever semantics are undeclared.
COUNT_MODES = ("cumulative", "interval", "unknown")

# Window derivation statuses (v3.6.5 §15 / v3.6.6 §M):
#   derived            — comparable counters, delta computed
#   no_relevant_change — no relevant confirmed change for this
#                        platform/entity/action family (timing does not
#                        gate)
#   unknown            — cannot derive (see ``reason``)
#   not_comparable     — counters must not be subtracted (see ``reason``)
WINDOW_STATUSES = (
    "derived",
    "no_relevant_change",
    "unknown",
    "not_comparable",
)

# Why a window is unknown / not comparable (v3.6.6 §M) — a short, fixed
# vocabulary; the user-facing summary translates these.
WINDOW_REASONS = (
    "unknown_count_semantics",
    "count_mode_mismatch",
    "counter_reset",
    "entity_mismatch",
    "missing_baseline",
    "invalid_timestamp",
    "legacy_change_scope_unknown",
)


@dataclass(frozen=True)
class DecisionWindow:
    """Light audit record of HOW a timing window was derived (v3.6.5 §19).

    The result carries this so the runtime can explain:
    "上次预算调整前累计 150 个 Pay，现在 195 → 这次调整后新增 45 个 Pay"
    instead of an opaque "窗口不成熟". ``reason`` names WHY a window is
    unknown / not comparable (v3.6.6 §M).
    """

    platform: str | None = None
    action_family: str | None = None
    change_type: str | None = None
    change_effective_at: str | None = None
    baseline_observed_at: str | None = None
    current_observed_at: str | None = None
    outcome_metric: str | None = None
    baseline_outcomes: float | None = None
    current_outcomes: float | None = None
    window_outcomes: float | None = None
    status: str = "no_relevant_change"
    reason: str | None = None


def parse_event_time(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC instant
    (v3.6.6 §43-47). Window ordering compares THESE instants, never raw
    strings: ``2026-08-17T10:00:00+08:00`` and ``2026-08-17T03:00:00Z``
    must order by real time. Naive timestamps follow the repository's
    canonical UTC convention; unparsable values return None and the
    window is handled conservatively (``invalid_timestamp``)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def relevant_change_types(action_family: str | None) -> tuple[str, ...]:
    """Change types that reset THIS action family's window (v3.6.6 §27-35).

    Not every material change resets every window: budget/bid/restart
    gate scale/descale; creative/restart gate the creative test window.
    Unknown families fall back to the broad legacy set (conservative).
    """
    return RELEVANT_CHANGE_TYPES_BY_ACTION_FAMILY.get(
        action_family or "", MATERIAL_CHANGE_TYPES
    )


def normalize_count_mode(facts: Mapping[str, object], outcome_key: str) -> str:
    """cumulative | interval | unknown for ONE outcome counter (v3.6.6
    §49-50): the per-metric ``<metric>_count_mode`` wins; a generic
    ``count_mode`` applies when the observation declares one shared
    semantic; MISSING semantics are ``unknown`` — never assumed
    cumulative. Different counters in the same observation may carry
    different semantics, so this is resolved per metric."""
    per_metric = facts.get(f"{outcome_key}_count_mode")
    if isinstance(per_metric, str) and per_metric in COUNT_MODES:
        return per_metric
    generic = facts.get("count_mode")
    if isinstance(generic, str) and generic in COUNT_MODES:
        return generic
    return "unknown"


def _is_account_level(facts: Mapping[str, object]) -> bool:
    """Explicit account-aggregate identity (mirrors the v3.5.4
    comparability contract: aggregate_scope with no sub-account entity)."""
    level = facts.get("entity_level")
    return facts.get("aggregate_scope") is not None and level in (None, "account")


def change_matches_entity(
    change_payload: Mapping[str, object],
    current_facts: Mapping[str, object],
) -> str:
    """match | no_match | unknown (v3.6.6 §19-22).

    A change belongs to an ENTITY, not only a platform. Exact identity
    equality → ``match``; different entity identity → ``no_match`` (a
    Campaign A change never resets Campaign B); a legacy change without
    entity attribution is ``unknown`` — account-level selections keep
    backward compatibility, campaign-level selections must never
    silently adopt it.
    """
    change_identity = comparable_identity(change_payload)
    current_identity = comparable_identity(current_facts)
    if change_identity is not None and current_identity is not None:
        return "match" if change_identity == current_identity else "no_match"
    return "unknown"


def _change_time(event: Mapping[str, object]) -> datetime | None:
    payload = event.get("payload")
    effective = (
        payload.get("effective_at") if isinstance(payload, Mapping) else None
    ) or event.get("observed_at")
    return parse_event_time(effective)


def resolve_relevant_change(
    changes: Iterable[Mapping[str, object]],
    platform: str | None,
    *,
    relevant_types: Iterable[str] = MATERIAL_CHANGE_TYPES,
    current_facts: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    """Latest confirmed material Change for ONE platform/entity (v3.6.5
    §6/25, v3.6.6 §19-22).

    Timing provenance follows the selected evaluation: only Changes
    attributed to this platform AND (when identity information exists)
    to the SAME entity count. Exact entity matches are preferred; when
    no exact match exists, legacy entity-less changes are returned as a
    conservative fallback ONLY for account-level selections — a
    campaign-level selection never adopts a legacy platform-only change
    (the derivation then reports ``legacy_change_scope_unknown``).
    """
    types = tuple(relevant_types)
    exact: list[Mapping[str, object]] = []
    legacy: list[Mapping[str, object]] = []
    for event in changes:
        if platform is not None and event.get("platform") != platform:
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if payload.get("change_type") not in types:
            continue
        if current_facts is not None:
            entity_state = change_matches_entity(payload, current_facts)
            if entity_state == "no_match":
                continue  # another entity's change: never relevant
            if entity_state == "unknown" and not _is_account_level(current_facts):
                # Legacy change + campaign-level selection: remembered
                # separately — derive reports it as unknown scope rather
                # than silently adopting or forgetting it.
                legacy.append(event)
                continue
        exact.append(event)

    def _instant_key(event: Mapping[str, object]) -> tuple[datetime, str]:
        # Compare parsed instants, not ISO strings (v3.6.6 §43-46);
        # unparsable times sort first (never picked as "latest").
        instant = _change_time(event)
        fallback = datetime.min.replace(tzinfo=timezone.utc)
        return (instant or fallback, str(event.get("event_id") or ""))

    if exact:
        return max(exact, key=_instant_key)
    if legacy and current_facts is not None and _is_account_level(current_facts):
        return max(legacy, key=_instant_key)
    if legacy:
        return max(legacy, key=_instant_key)
    return None


def resolve_window_baseline(
    observations: Iterable[Mapping[str, object]],
    change_effective_at: str,
    current_facts: Mapping[str, object],
    *,
    current_event_ids: Iterable[str] = (),
) -> tuple[Mapping[str, object], str] | tuple[None, None]:
    """Latest comparable Observation at or before the Change (v3.6.5 §9).

    The baseline must carry the SAME entity scope as the current
    observation (v3.5.4 comparability: unknown identity is never
    comparable) and must have been observed before the change took
    effect — ordering uses PARSED INSTANTS, so mixed timezone offsets
    compare correctly (v3.6.6 §43-46). Missing → (None, None).
    """
    change_instant = parse_event_time(change_effective_at)
    if change_instant is None:
        return None, None
    excluded = set(current_event_ids)
    candidates: list[tuple[datetime, Mapping[str, object], str]] = []
    for event in observations:
        if event.get("event_id") in excluded:
            continue
        observed = event.get("observed_at")
        observed_instant = parse_event_time(observed)
        if observed_instant is None:
            continue  # invalid timestamp: never a baseline
        if observed_instant > change_instant:
            continue  # after the change: not a pre-change baseline
        payload = event.get("payload")
        facts = payload.get("facts") if isinstance(payload, Mapping) else None
        if not isinstance(facts, Mapping) or not facts:
            continue
        if not observations_comparable(current_facts, facts):
            continue
        candidates.append(
            (observed_instant, facts, observed if isinstance(observed, str) else "")
        )
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], ""))
    return candidates[-1][1], candidates[-1][2]


def counter_is_comparable(baseline_value: float, current_value: float) -> bool:
    """A cumulative counter must be monotonic (v3.6.5 §14).

    A decrease means the counter was reset (or the scope changed): the
    delta would be negative and meaningless. Such windows are
    ``not_comparable``, never negative outcomes.
    """
    return current_value >= baseline_value


def derive_window_outcomes(
    *,
    facts: Mapping[str, object],
    changes: Iterable[Mapping[str, object]],
    observations: Iterable[Mapping[str, object]],
    platform: str | None,
    action_family: str | None = "scale",
    current_observed_at: str | None = None,
    current_event_ids: Iterable[str] = (),
) -> DecisionWindow:
    """Derive the KPI-aligned post-change outcome delta from STATE.

    v3.6.5 §1-18 + v3.6.6: the window outcome is ``current_counter −
    baseline_counter`` where the counter matches the PRIMARY KPI (Pay
    CPA → payments, CPI → installs — never a borrowed metric) and the
    baseline is the latest comparable observation at or before the
    latest relevant confirmed Change FOR THE SELECTED ENTITY AND ACTION
    FAMILY. Every subtraction is validated first:

    - count semantics: only ``count_mode=cumulative`` on BOTH sides is
      subtractable; interval values are never subtracted; missing
      semantics → ``unknown`` (``unknown_count_semantics``); mixed
      modes → ``not_comparable`` (``count_mode_mismatch``);
    - entity scope: change, baseline and current must agree (§11);
    - monotonicity: a decreased counter → ``counter_reset``;
    - timestamps: compared as parsed instants (§43).

    Anything unresolved defers the action (readiness waits) — never a
    guessed delta.
    """
    window = DecisionWindow(
        platform=platform,
        action_family=action_family,
        current_observed_at=current_observed_at,
    )
    change = resolve_relevant_change(
        changes,
        platform,
        relevant_types=relevant_change_types(action_family),
        current_facts=facts,
    )
    if change is None:
        return window  # no_relevant_change: timing does not gate
    payload = change.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    change_at = payload.get("effective_at") or change.get("observed_at")
    if parse_event_time(change_at) is None:
        return replace(window, status="unknown", reason="invalid_timestamp")
    window = replace(
        window,
        change_type=str(payload.get("change_type") or ""),
        change_effective_at=change_at if isinstance(change_at, str) else None,
    )
    # Entity safety (v3.6.6 §19-22): a legacy change without entity
    # attribution may serve an account-level selection, but must never
    # silently anchor a campaign-level window.
    entity_state = change_matches_entity(payload, facts)
    if entity_state == "unknown" and not _is_account_level(facts):
        return replace(window, status="unknown", reason="legacy_change_scope_unknown")
    kpi_type, _ = resolve_primary_kpi(facts)
    outcome_key = kpi_outcome_key(kpi_type or "")
    if outcome_key is None:
        return replace(window, status="unknown", reason="missing_baseline")
    window = replace(window, outcome_metric=outcome_key)
    current_value = facts.get(outcome_key)
    if not isinstance(current_value, (int, float)):
        return replace(window, status="unknown", reason="missing_baseline")
    if parse_event_time(current_observed_at) is None and current_observed_at:
        return replace(window, status="unknown", reason="invalid_timestamp")
    baseline = resolve_window_baseline(
        observations,
        change_at if isinstance(change_at, str) else "",
        facts,
        current_event_ids=current_event_ids,
    )
    baseline_facts, baseline_at = baseline
    if baseline_facts is None:
        # First counter reading AFTER the change (v3.6.5 §10): never
        # guess that the whole count is new — the window is unknown.
        return replace(window, status="unknown", reason="missing_baseline")
    # Count semantics BEFORE any subtraction (v3.6.6 §1-6/12-14): both
    # counters must be EXPLICIT cumulative and AGREE. Two independent
    # interval readings are never subtracted (unknown, not an error); a
    # cumulative-vs-interval mix is a hard comparability violation.
    current_mode = normalize_count_mode(facts, outcome_key)
    baseline_mode = normalize_count_mode(baseline_facts, outcome_key)
    if current_mode != baseline_mode:
        if "unknown" in (current_mode, baseline_mode):
            # An undeclared side means comparability cannot be proven.
            return replace(
                window,
                baseline_observed_at=baseline_at or None,
                status="unknown",
                reason="unknown_count_semantics",
            )
        return replace(
            window,
            baseline_observed_at=baseline_at or None,
            status="not_comparable",
            reason="count_mode_mismatch",
        )
    if current_mode != "cumulative":
        reason = "unknown_count_semantics" if current_mode == "unknown" else "interval"
        return replace(
            window,
            baseline_observed_at=baseline_at or None,
            status="unknown",
            reason=reason,
        )
    baseline_value = baseline_facts.get(outcome_key)
    if not isinstance(baseline_value, (int, float)):
        return replace(
            window,
            baseline_observed_at=baseline_at or None,
            status="unknown",
            reason="missing_baseline",
        )
    if not counter_is_comparable(float(baseline_value), float(current_value)):
        # Counter decreased → reset or scope change: a subtraction would
        # produce a meaningless negative outcome count (v3.6.5 §12-14).
        return replace(
            window,
            baseline_observed_at=baseline_at or None,
            baseline_outcomes=float(baseline_value),
            current_outcomes=float(current_value),
            status="not_comparable",
            reason="counter_reset",
        )
    return replace(
        window,
        baseline_observed_at=baseline_at or None,
        baseline_outcomes=float(baseline_value),
        current_outcomes=float(current_value),
        window_outcomes=float(current_value) - float(baseline_value),
        status="derived",
    )
