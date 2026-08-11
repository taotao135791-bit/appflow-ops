"""Append-only, workspace-scoped state store.

Layout (physical isolation per workspace):

    workspaces/<client>/<project>/state/
    ├── schema.json              # schema version + workspace fingerprint
    ├── events/
    │   ├── 00000001-observation.json
    │   ├── 00000002-change.json
    │   └── ...
    └── current-state.json       # DERIVED, rebuildable from events

Invariants:

- No API accepts an arbitrary path; every path is derived from the bound
  RunContext workspace and resolved through Workspace.require_contained_path
  (traversal and symlink escapes are rejected).
- Events are append-only; current-state.json is always rebuildable from the
  event log. Corrupted current state is rebuilt, corrupted events fail
  loudly (never silently cleared).
- Writes are atomic (temp file + fsync + os.replace, same as io._dump).
- Retrieval is bounded; the store never loads the whole history into memory
  by default.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .account_state import (
    CONFIDENCE_LEVELS,
    MATURITY_STATES,
    MEASUREMENT_STATES,
    STATE_SCHEMA_VERSION,
    RunContext,
    build_event,
    is_event_id,
    validate_event_type,
    validate_refs,
)
from .io import _dump
from .types import ContractError

_EVENT_FILE_RE = re.compile(r"^([0-9]{8})-(observation|change|decision|outcome)\.json$")
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 100


def _event_id(sequence: int) -> str:
    return f"event_{sequence:08d}"


class StateStore:
    """One workspace's continuous account state store."""

    def __init__(self, context: RunContext) -> None:
        self.context = context

    # ── lifecycle ────────────────────────────────────────────────────────

    @property
    def initialized(self) -> bool:
        schema = self._resolved_schema_path()
        return (
            schema.is_file()
            and not schema.is_symlink()
            and self._resolved_events_dir().is_dir()
            and not self._resolved_events_dir().is_symlink()
        )

    def ensure_initialized(self) -> None:
        """Idempotently create the state store for the bound workspace."""

        self.context.workspace.require_initialized()
        if self.initialized:
            return
        events_dir = self._resolved_events_dir()
        events_dir.mkdir(parents=True, exist_ok=False)
        _best_effort_chmod(events_dir, 0o700)
        _dump(
            self._resolved_schema_path(),
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "workspace_fingerprint": self._workspace_fingerprint(),
            },
        )
        _best_effort_chmod(self._resolved_schema_path(), 0o600)

    def _workspace_fingerprint(self) -> str:
        import hashlib

        return hashlib.sha256(
            str(self.context.workspace.root).encode("utf-8")
        ).hexdigest()[:16]

    def clear(self) -> None:
        """Delete this workspace's state only. Other workspaces are untouched."""

        state_dir = self._resolved_state_dir()
        if not state_dir.exists():
            return
        shutil.rmtree(state_dir)

    # ── path resolution (workspace-bound, containment enforced) ──────────

    def _resolved_state_dir(self) -> Path:
        return self.context.workspace.require_contained_path(
            self.context.state_dir, "state directory"
        )

    def _resolved_events_dir(self) -> Path:
        return self.context.workspace.require_contained_path(
            self.context.events_dir, "state events directory"
        )

    def _resolved_schema_path(self) -> Path:
        return self.context.workspace.require_contained_path(
            self.context.schema_path, "state schema"
        )

    def _resolved_current_path(self) -> Path:
        return self.context.workspace.require_contained_path(
            self.context.current_state_path, "current state"
        )

    def _event_path(self, sequence: int, event_type: str) -> Path:
        return self._resolved_events_dir() / f"{sequence:08d}-{event_type}.json"

    # ── append ───────────────────────────────────────────────────────────

    def _append(
        self,
        *,
        event_type: str,
        platform: str | None,
        payload: Mapping[str, Any],
        source_type: str,
        evidence_status: str,
        refs: tuple[str, ...] = (),
    ) -> str:
        self.ensure_initialized()
        validate_refs(refs, self.context.workspace)
        sequence = self._next_sequence()
        event = build_event(
            event_type=event_type,
            platform=platform,
            payload=payload,
            source_type=source_type,
            evidence_status=evidence_status,
            refs=refs,
        )
        event["event_id"] = _event_id(sequence)
        path = self._event_path(sequence, event_type)
        _dump(path, event)
        _best_effort_chmod(path, 0o600)
        self.rebuild_current_state()
        return event["event_id"]

    def _next_sequence(self) -> int:
        highest = 0
        for sequence, _event_type, _path in self._iter_event_files(
            self._resolved_events_dir()
        ):
            highest = max(highest, sequence)
        return highest + 1

    def append_observation(
        self,
        *,
        observed_at: str,
        platform: str,
        facts: Mapping[str, Any],
        source_type: str = "export",
        evidence_status: str = "confirmed",
        refs: tuple[str, ...] = (),
    ) -> str:
        """Record what was actually known at a point in time (facts, not
        explanations). ``facts`` may carry measurement_state/maturity_state
        plus platform-specific keys."""

        payload = {"observed_at": observed_at, "facts": dict(facts)}
        return self._append(
            event_type="observation",
            platform=platform,
            payload=payload,
            source_type=source_type,
            evidence_status=evidence_status,
            refs=refs,
        )

    def append_change(
        self,
        *,
        change_type: str,
        direction: str,
        magnitude: float | None = None,
        source: str = "manual",
        origin: str = "operator",
        evidence_status: str = "confirmed",
        refs: tuple[str, ...] = (),
    ) -> str:
        """Record a confirmed account/operation change. Unconfirmed user
        statements belong in an observation with evidence_status=reported,
        not here."""

        payload: dict[str, Any] = {
            "change_type": change_type,
            "direction": direction,
            "source": source,
            "origin": origin,
        }
        if magnitude is not None:
            payload["magnitude"] = magnitude
        return self._append(
            event_type="change",
            platform=None,
            payload=payload,
            source_type="manual",
            evidence_status=evidence_status,
            refs=refs,
        )

    def append_decision(
        self,
        *,
        decision_class: str,
        reason: str,
        evidence_refs: tuple[str, ...] = (),
        policy_constraints: Mapping[str, Any] | None = None,
        measurement_state: str = "unknown",
        maturity_state: str = "unknown",
        confidence: str = "medium",
        review_condition: str | None = None,
        review_after: str | None = None,
    ) -> str:
        """Record one operational recommendation with minimal context. The
        rationale is a concise summary; hidden chain-of-thought is never
        persisted (Broad internally, concise persistently)."""

        if decision_class not in {
            "keep",
            "increase",
            "decrease",
            "pause",
            "reopen",
            "replace",
            "wait",
            "observe",
            "investigate",
        }:
            raise ContractError(f"unknown decision_class: {decision_class}")
        if measurement_state not in MEASUREMENT_STATES:
            raise ContractError(f"unknown measurement_state: {measurement_state}")
        if maturity_state not in MATURITY_STATES:
            raise ContractError(f"unknown maturity_state: {maturity_state}")
        if confidence not in CONFIDENCE_LEVELS:
            raise ContractError(f"unknown confidence: {confidence}")
        payload: dict[str, Any] = {
            "decision_class": decision_class,
            "reason": reason[:500],
            "evidence_refs": sorted(evidence_refs),
            "policy_constraints": dict(policy_constraints or {}),
            "measurement_state": measurement_state,
            "maturity_state": maturity_state,
            "confidence": confidence,
        }
        if review_condition is not None:
            payload["review_condition"] = review_condition
        if review_after is not None:
            payload["review_after"] = review_after
        return self._append(
            event_type="decision",
            platform=None,
            payload=payload,
            source_type="deterministic_engine",
            evidence_status="confirmed",
            refs=tuple(evidence_refs),
        )

    def append_outcome(
        self,
        *,
        outcome_class: str,
        decision_id: str | None = None,
        change_id: str | None = None,
        observation_ids: tuple[str, ...] = (),
        source_type: str = "export",
        evidence_status: str = "confirmed",
    ) -> str:
        """Record what happened after a previous decision/change."""

        if outcome_class not in {
            "improved",
            "worsened",
            "neutral",
            "inconclusive",
            "rolled_back",
            "not_executed",
        }:
            raise ContractError(f"unknown outcome_class: {outcome_class}")
        refs: list[str] = []
        for event_id in (decision_id, change_id):
            if event_id is not None:
                if not is_event_id(event_id):
                    raise ContractError(f"invalid event reference: {event_id}")
                refs.append(event_id)
        refs.extend(observation_ids)
        payload = {
            "outcome_class": outcome_class,
            "decision_id": decision_id,
            "change_id": change_id,
            "observation_ids": sorted(observation_ids),
        }
        return self._append(
            event_type="outcome",
            platform=None,
            payload=payload,
            source_type=source_type,
            evidence_status=evidence_status,
            refs=tuple(refs),
        )

    # ── retrieval (bounded) ──────────────────────────────────────────────

    def _read_event(self, path: Path) -> dict[str, Any]:
        resolved = self.context.workspace.require_contained_path(path, "state event")
        try:
            document = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError(
                f"state event is corrupted: {resolved.name}: {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise ContractError(f"state event is not an object: {resolved.name}")
        return document

    def get_recent(
        self, *, limit: int = _DEFAULT_LIMIT, event_type: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Return the newest events, newest first. Bounded by default."""
        if event_type is not None:
            validate_event_type(event_type)
        if not 0 < limit <= _MAX_LIMIT:
            raise ContractError(f"state limit must be 1..{_MAX_LIMIT}")
        events_dir = self._resolved_events_dir()
        if not events_dir.is_dir():
            return ()
        entries = [
            (sequence, kind, path)
            for sequence, kind, path in self._iter_event_files(events_dir)
            if event_type is None or kind == event_type
        ]
        entries.sort(reverse=True)
        return tuple(self._read_event(path) for _, _, path in entries[:limit])

    def get_recent_observations(
        self, limit: int = _DEFAULT_LIMIT
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="observation")

    def get_recent_changes(
        self, limit: int = _DEFAULT_LIMIT
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="change")

    def get_recent_decisions(
        self, limit: int = _DEFAULT_LIMIT
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="decision")

    def get_recent_outcomes(
        self, limit: int = _DEFAULT_LIMIT
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="outcome")

    def get_event(self, event_id: str) -> dict[str, Any]:
        if not is_event_id(event_id):
            raise ContractError(f"invalid event id: {event_id}")
        sequence = int(event_id.rsplit("_", 1)[1])
        for entry_sequence, _kind, path in self._iter_event_files(
            self._resolved_events_dir()
        ):
            if entry_sequence == sequence:
                return self._read_event(path)
        raise ContractError(f"state event not found: {event_id}")

    def get_pending_review(self) -> dict[str, Any] | None:
        """Return the most recent decision that is still waiting for review.

        A decision with ``review_condition`` is pending until an outcome
        links to it (or the review_after time has passed; that check is the
        caller's, not a background job's).
        """
        decisions = self.get_recent_decisions(limit=20)
        outcomes = self.get_recent_outcomes(limit=50)
        resolved_decisions = {
            outcome["payload"].get("decision_id") for outcome in outcomes
        }
        for decision in decisions:
            decision_id = decision.get("event_id")
            if decision_id in resolved_decisions:
                continue
            payload = decision.get("payload", {})
            if "review_condition" not in payload:
                continue
            return {
                "decision_id": decision_id,
                "decision_class": payload.get("decision_class"),
                "condition": payload.get("review_condition"),
                "review_after": payload.get("review_after"),
                "status": "pending",
            }
        return None

    # ── derived current state ────────────────────────────────────────────

    def current_state(self) -> dict[str, Any]:
        """Read the derived current state; rebuild it when corrupted."""
        path = self._resolved_current_path()
        if not path.is_file():
            return self.rebuild_current_state()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.rebuild_current_state()
        if not isinstance(document, dict):
            return self.rebuild_current_state()
        return document

    def rebuild_current_state(self) -> dict[str, Any]:
        """Replay the event log and derive current-state.json (Part 10/30).

        The derived file is never the single source of truth; deleting it
        only forces a rebuild from events. A corrupted event log fails
        loudly instead of silently clearing history. Derivation only
        consumes the most recent events (bounded); the count reflects the
        full log.
        """
        events_dir = self._resolved_events_dir()
        total_count = 0
        if events_dir.is_dir():
            total_count = len(self._iter_event_files(events_dir))
        events = self.get_recent(limit=_MAX_LIMIT)
        events = tuple(reversed(events))  # oldest first
        last: dict[str, str | None] = {
            "observation": None,
            "change": None,
            "decision": None,
            "outcome": None,
        }
        measurement_state: str = "unknown"
        maturity_state: str = "unknown"
        last_facts: dict[str, Any] = {}
        for event in events:
            event_type = event.get("type")
            if event_type in last:
                last[event_type] = event.get("event_id")
            if event_type == "observation":
                facts = event.get("payload", {}).get("facts", {})
                if isinstance(facts, dict):
                    last_facts = dict(facts)
                    measurement_state = str(
                        facts.get("measurement_state", measurement_state)
                    )
                    maturity_state = str(facts.get("maturity_state", maturity_state))
        current = {
            "schema_version": STATE_SCHEMA_VERSION,
            "derived_at": _now_iso(),
            "event_count": total_count,
            "last_observation_id": last["observation"],
            "last_change_id": last["change"],
            "last_decision_id": last["decision"],
            "last_outcome_id": last["outcome"],
            "measurement_state": measurement_state,
            "maturity_state": maturity_state,
            "pending_review": self.get_pending_review(),
            "open_questions": [],
            "last_facts": last_facts,
        }
        _dump(self._resolved_current_path(), current)
        _best_effort_chmod(self._resolved_current_path(), 0o600)
        return current

    # ── diagnostics ──────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        events_dir = self._resolved_events_dir()
        count = 0
        by_type: dict[str, int] = {
            event_type: 0
            for event_type in ("observation", "change", "decision", "outcome")
        }
        if events_dir.is_dir():
            for _sequence, kind, _path in self._iter_event_files(events_dir):
                count += 1
                by_type[kind] = by_type.get(kind, 0) + 1
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "initialized": self.initialized,
            "event_count": count,
            "events_by_type": by_type,
            "current_state_path": str(self.context.current_state_path),
            "client_scope": self.context.client_scope,
            "project_scope": self.context.project_scope,
        }

    def _iter_event_files(self, events_dir: Path) -> list[tuple[int, str, Path]]:
        """List event files, rejecting any symbolic link explicitly.

        A symlink inside events/ is treated as an attack (it could point at
        another workspace's state) and fails loudly instead of being
        silently skipped.
        """
        entries: list[tuple[int, str, Path]] = []
        for entry in events_dir.iterdir():
            if entry.is_symlink():
                raise ContractError(
                    "state events must not use symbolic links: " + entry.name
                )
            if entry.is_file():
                match = _EVENT_FILE_RE.fullmatch(entry.name)
                if match is not None:
                    entries.append((int(match.group(1)), match.group(2), entry))
        return entries


def _now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _best_effort_chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass
