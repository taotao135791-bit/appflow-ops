"""State-native decision windows (v3.6.5).

Timing is a native consequence of PERSISTED STATE, not caller arithmetic.
The runtime reconstructs "what happened since the last confirmed change"
from the bounded state it already loads:

    selected platform/entity
    → latest relevant confirmed Change
    → comparable pre-change baseline Observation
    → current Observation
    → derived KPI-aligned post-change outcome delta

Callers must never be required to pre-compute ``window_outcomes`` —
when the counters are comparable the delta is derived here; when they
are not (entity change, counter reset, missing baseline, unknown
identity) the window status says so and readiness conservatively waits.

Deliberately THIN helpers only — no Window Engine, no aggregation
subsystem, no new persistence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from .calibration import kpi_outcome_key, resolve_primary_kpi
from .evidence import observations_comparable

# Change types that materially reset the decision window (v3.6.5 §6-8).
# Budget/bid/campaign restart reset the scale/descale window; creative
# changes additionally reset the creative test window. Unlisted change
# types (audience/campaign) reuse the same conservative set.
MATERIAL_CHANGE_TYPES = (
    "budget",
    "bid",
    "creative",
    "campaign_restart",
    "campaign",
    "audience",
)

# Window derivation statuses (v3.6.5 §15):
#   derived          — baseline + current comparable, delta computed
#   no_pending_change— no relevant confirmed change for this platform
#   unknown          — missing baseline / missing counter / unknown identity
#   not_comparable   — entity mismatch or detected counter reset
WINDOW_STATUSES = (
    "derived",
    "no_pending_change",
    "unknown",
    "not_comparable",
)


@dataclass(frozen=True)
class DecisionWindow:
    """Light audit record of HOW a timing window was derived (v3.6.5 §19).

    The result carries this so the runtime can explain:
    "上次预算调整前 Pay=150，现在 Pay=152 → 这次调整后新增 2 个 Pay"
    instead of an opaque "窗口不成熟".
    """

    platform: str | None = None
    change_type: str | None = None
    change_effective_at: str | None = None
    baseline_observed_at: str | None = None
    current_observed_at: str | None = None
    outcome_metric: str | None = None
    baseline_outcomes: float | None = None
    current_outcomes: float | None = None
    window_outcomes: float | None = None
    status: str = "no_pending_change"


def _event_sort_key(event: Mapping[str, object]) -> str:
    """Canonical (timestamp, event_id) sort key for deterministic picks."""
    payload = event.get("payload")
    effective = (
        payload.get("effective_at") if isinstance(payload, Mapping) else None
    ) or event.get("observed_at")
    return f"{effective or ''}|{event.get('event_id') or ''}"


def resolve_relevant_change(
    changes: Iterable[Mapping[str, object]],
    platform: str | None,
    *,
    relevant_types: Iterable[str] = MATERIAL_CHANGE_TYPES,
) -> Mapping[str, object] | None:
    """Latest confirmed material Change for ONE platform (v3.6.5 §6/25).

    Timing provenance follows the selected evaluation: only Changes
    attributed to this platform count — another platform's latest change
    never resets this platform's window. Changes without any platform
    attribution are ignored here (legacy broadcast changes are already
    handled as confounder signals by the evidence layer).
    """
    types = tuple(relevant_types)
    candidates: list[Mapping[str, object]] = []
    for event in changes:
        if platform is not None and event.get("platform") != platform:
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if payload.get("change_type") not in types:
            continue
        candidates.append(event)
    if not candidates:
        return None
    return max(candidates, key=_event_sort_key)


def resolve_window_baseline(
    observations: Iterable[Mapping[str, object]],
    change_effective_at: str,
    current_facts: Mapping[str, object],
    *,
    current_event_ids: Iterable[str] = (),
) -> tuple[Mapping[str, object], str] | None:
    """Latest comparable Observation at or before the Change (v3.6.5 §9).

    The baseline must carry the SAME entity scope as the current
    observation (v3.5.4 comparability: unknown identity is never
    comparable) and must have been observed before the change took
    effect. Missing → None (window stays unknown, never guessed).
    """
    excluded = set(current_event_ids)
    candidates: list[tuple[str, Mapping[str, object]]] = []
    for event in observations:
        if event.get("event_id") in excluded:
            continue
        observed = event.get("observed_at")
        if not isinstance(observed, str) or not observed:
            continue
        if observed > change_effective_at:
            continue  # after the change: not a pre-change baseline
        payload = event.get("payload")
        facts = payload.get("facts") if isinstance(payload, Mapping) else None
        if not isinstance(facts, Mapping) or not facts:
            continue
        if not observations_comparable(current_facts, facts):
            continue
        candidates.append((observed, facts))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1], candidates[-1][0]


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
    current_observed_at: str | None = None,
    current_event_ids: Iterable[str] = (),
) -> DecisionWindow:
    """Derive the KPI-aligned post-change outcome delta from STATE.

    v3.6.5 §1-18: the window outcome is ``current_counter −
    baseline_counter`` where the counter matches the PRIMARY KPI (Pay CPA
    → payments, CPI → installs — never a borrowed metric) and the
    baseline is the latest comparable observation at or before the
    latest relevant confirmed Change. Missing baseline, missing counter
    or unknown identity → ``unknown``; entity mismatch or counter reset
    → ``not_comparable``. Both defer the action (readiness waits).
    """
    window = DecisionWindow(
        platform=platform,
        current_observed_at=current_observed_at,
    )
    change = resolve_relevant_change(changes, platform)
    if change is None:
        return window  # no_pending_change: timing does not gate
    payload = change.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    change_at = payload.get("effective_at") or change.get("observed_at")
    if not isinstance(change_at, str) or not change_at:
        return window
    window = DecisionWindow(
        platform=platform,
        change_type=str(payload.get("change_type") or ""),
        change_effective_at=change_at,
        current_observed_at=current_observed_at,
    )
    kpi_type, _ = resolve_primary_kpi(facts)
    outcome_key = kpi_outcome_key(kpi_type or "")
    if outcome_key is None:
        return replace(window, status="unknown")
    window = replace(window, outcome_metric=outcome_key)
    current_value = facts.get(outcome_key)
    if not isinstance(current_value, (int, float)):
        return replace(window, status="unknown")
    baseline = resolve_window_baseline(
        observations,
        change_at,
        facts,
        current_event_ids=current_event_ids,
    )
    if baseline is None:
        # First counter reading AFTER the change (v3.6.5 §10): never
        # guess that the whole count is new — the window is unknown.
        return replace(window, status="unknown")
    baseline_facts, baseline_at = baseline
    baseline_value = baseline_facts.get(outcome_key)
    if not isinstance(baseline_value, (int, float)):
        return replace(window, status="unknown")
    if not counter_is_comparable(float(baseline_value), float(current_value)):
        # Counter decreased → reset or scope change: a subtraction would
        # produce a meaningless negative outcome count (v3.6.5 §12-14).
        return replace(
            window,
            baseline_observed_at=baseline_at,
            baseline_outcomes=float(baseline_value),
            current_outcomes=float(current_value),
            status="not_comparable",
        )
    return replace(
        window,
        baseline_observed_at=baseline_at,
        baseline_outcomes=float(baseline_value),
        current_outcomes=float(current_value),
        window_outcomes=float(current_value) - float(baseline_value),
        status="derived",
    )
