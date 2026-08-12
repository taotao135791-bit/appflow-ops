"""Append-only, workspace-scoped state store (v3.3.1 integrity).

Layout (physical isolation per workspace):

    workspaces/<client>/<project>/state/
    ├── schema.json              # schema version + workspace_id
    ├── .write.lock              # workspace-local write lock
    ├── events/
    │   ├── 00000001-observation.json
    │   ├── 00000002-change.json
    │   └── ...
    └── current-state.json       # DERIVED, rebuildable from events

Invariants:

- No API accepts an arbitrary path; every path is derived from the bound
  RunContext workspace and resolved through Workspace.require_contained_path
  (traversal and symlink escapes are rejected).
- All writers (append / rebuild / clear) take the workspace-local write
  lock, so concurrent runs cannot allocate the same sequence or observe
  half-written state. Lock files are per workspace; A and B never block
  each other.
- The state store proves it belongs to the bound workspace: schema
  ``workspace_id`` must equal RunContext.workspace_id. A copied foreign
  state tree is rejected. Legacy v3.3.0 stores (fingerprint only) migrate
  safely when the fingerprint matches; otherwise they are rejected.
- Events are append-only; current-state.json is derived from the FULL event
  log (streaming scan, bounded memory) and carries ``derived_through_sequence``
  so stale/missing derived state is detected and rebuilt on read.
- Event references are validated for existence and type inside the current
  workspace; a reference to another workspace's same-named event is
  impossible by construction.
- Corrupted current state rebuilds from events; corrupted events fail
  loudly (never silently cleared).
- Writes are atomic (temp file + fsync + os.replace, same as io._dump).
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
    DECISION_CLASSES,
    MATURITY_STATES,
    MEASUREMENT_STATES,
    OUTCOME_CLASSES,
    STATE_SCHEMA_VERSION,
    WORKSPACE_ID_KEY,
    WRITE_LOCK_NAME,
    RunContext,
    build_event,
    is_event_id,
    validate_decision_origin,
    validate_event_type,
    validate_refs,
)
from .io import _dump
from .state_guard import check_state_payload
from .state_lock import WorkspaceWriteLock
from .types import ContractError

_EVENT_FILE_RE = re.compile(r"^([0-9]{8})-(observation|change|decision|outcome)\.json$")
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 100
_LOCK_TIMEOUT_SECONDS = 30.0

_REF_TYPE_RULES = {
    "decision": {"observation", "change"},
    "outcome": {"decision"},
}
_OUTCOME_REF_FIELDS = (
    ("decision_id", "decision"),
    ("change_id", "change"),
    ("observation_ids", "observation"),
)


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
        """Idempotently create the state store, then prove identity."""

        self.context.workspace.require_initialized()
        if self.initialized:
            self._validate_workspace_identity()
            return
        events_dir = self._resolved_events_dir()
        events_dir.mkdir(parents=True, exist_ok=False)
        _best_effort_chmod(events_dir, 0o700)
        _dump(
            self._resolved_schema_path(),
            {
                "schema_version": STATE_SCHEMA_VERSION,
                WORKSPACE_ID_KEY: self.context.workspace_id,
            },
        )
        _best_effort_chmod(self._resolved_schema_path(), 0o600)

    def _validate_workspace_identity(self) -> None:
        """State store must prove it belongs to the currently bound workspace.

        - schema has workspace_id: must equal RunContext.workspace_id, else
          the state was copied from another workspace and is rejected.
        - legacy v3.3.0 schema (fingerprint only): accepted only when the
          fingerprint matches the current absolute path; then the state is
          bound by writing workspace_id into the schema.
        """

        if not self.context.workspace_id:
            raise ContractError(
                "workspace has no workspace_id; state cannot be bound safely"
            )
        schema = self._load_schema()
        stored_id = schema.get(WORKSPACE_ID_KEY)
        if isinstance(stored_id, str) and stored_id:
            if stored_id != self.context.workspace_id:
                raise ContractError(
                    "state store belongs to a different workspace; refusing to "
                    "open (copied or moved state tree?)"
                )
            return
        # Legacy v3.3.0: fingerprint = hash(absolute path).
        legacy_fingerprint = schema.get("workspace_fingerprint")
        if not isinstance(legacy_fingerprint, str) or not legacy_fingerprint:
            raise ContractError(
                "state schema has no workspace_id and no legacy fingerprint; "
                "refusing to bind ambiguous state"
            )
        if legacy_fingerprint != self._legacy_path_fingerprint():
            raise ContractError(
                "state schema fingerprint does not match this workspace; "
                "refusing to bind state that may belong elsewhere"
            )
        schema[WORKSPACE_ID_KEY] = self.context.workspace_id
        schema["schema_version"] = STATE_SCHEMA_VERSION
        _dump(self._resolved_schema_path(), schema)
        _best_effort_chmod(self._resolved_schema_path(), 0o600)

    def _load_schema(self) -> dict[str, Any]:
        path = self._resolved_schema_path()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ContractError(f"state schema is corrupted: {exc}") from exc
        if not isinstance(document, dict):
            raise ContractError("state schema is not an object")
        return document

    def _legacy_path_fingerprint(self) -> str:
        import hashlib

        return hashlib.sha256(
            str(self.context.workspace.root).encode("utf-8")
        ).hexdigest()[:16]

    def clear(self) -> None:
        """Delete this workspace's state only (locked). Other workspaces are
        untouched.

        The lock file itself is removed AFTER the lock is released: on
        Windows a held file handle prevents deletion, and deleting our own
        lock file while holding it would fail.
        """

        state_dir = self._resolved_state_dir()
        if not state_dir.exists():
            return
        with WorkspaceWriteLock(self._resolved_lock_path()):
            for entry in list(state_dir.iterdir()):
                if entry.name == WRITE_LOCK_NAME:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
        try:
            self._resolved_lock_path().unlink()
        except OSError:
            pass
        try:
            state_dir.rmdir()
        except OSError:
            pass  # a concurrent writer re-created content; leave the tree alone

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

    def _resolved_lock_path(self) -> Path:
        return self.context.workspace.require_contained_path(
            self.context.write_lock_path, "state write lock"
        )

    def _event_path(self, sequence: int, event_type: str) -> Path:
        return self._resolved_events_dir() / f"{sequence:08d}-{event_type}.json"

    # ── append (all writes under the workspace-local lock) ───────────────

    def _append(
        self,
        *,
        event_type: str,
        platform: str | None,
        payload: Mapping[str, Any],
        source_type: str,
        evidence_status: str,
        refs: tuple[str, ...] = (),
        observed_at: str | None = None,
        run_id: str | None = None,
        ref_type_map: Mapping[str, str] | None = None,
    ) -> str:
        check_state_payload(payload, context=f"{event_type} payload")
        with WorkspaceWriteLock(self._resolved_lock_path()):
            self.ensure_initialized()
            validate_refs(refs, self.context.workspace)
            self._validate_ref_types(refs, ref_type_map)
            sequence = self._next_sequence()
            event = build_event(
                event_type=event_type,
                platform=platform,
                payload=payload,
                source_type=source_type,
                evidence_status=evidence_status,
                refs=refs,
                observed_at=observed_at,
                run_id=run_id,
            )
            event["event_id"] = _event_id(sequence)
            path = self._event_path(sequence, event_type)
            _dump(path, event)
            _best_effort_chmod(path, 0o600)
            self._rebuild_locked()
            return event["event_id"]

    def _next_sequence(self) -> int:
        highest = 0
        for sequence, _kind, _path in self._iter_event_files(
            self._resolved_events_dir()
        ):
            highest = max(highest, sequence)
        return highest + 1

    def _validate_ref_types(
        self, refs: tuple[str, ...], ref_type_map: Mapping[str, str] | None
    ) -> None:
        """References must exist in THIS workspace and have the expected type.

        Decision refs: observations/changes. Outcome refs: per-field
        (decision_id -> decision, change_id -> change, observation_ids ->
        observation). Same-named events in another workspace can never be
        resolved because resolution only reads the bound workspace's events
        directory.
        """

        for ref in refs:
            if not is_event_id(ref):
                continue  # artifact paths are validated separately
            target = self.get_event(ref)
            if ref_type_map is not None:
                expected = ref_type_map.get(ref)
                if expected is not None and target.get("type") != expected:
                    raise ContractError(
                        f"reference {ref} points to a {target.get('type')}; "
                        f"expected {expected}"
                    )
            elif target.get("type") not in {"observation", "change"}:
                raise ContractError(
                    f"decision reference {ref} points to a {target.get('type')}; "
                    "expected observation or change"
                )

    def append_observation(
        self,
        *,
        observed_at: str,
        platform: str,
        facts: Mapping[str, Any],
        source_type: str = "export",
        evidence_status: str = "confirmed",
        refs: tuple[str, ...] = (),
        run_id: str | None = None,
    ) -> str:
        """Record what was actually known at a point in time (facts, not
        explanations). ``observed_at`` is the business time and lives only
        in the envelope; ``facts`` may carry measurement_state/maturity_state
        plus platform-specific keys (without repeating the timestamps)."""

        payload = {"facts": dict(facts)}
        return self._append(
            event_type="observation",
            platform=platform,
            payload=payload,
            source_type=source_type,
            evidence_status=evidence_status,
            refs=refs,
            observed_at=observed_at,
            run_id=run_id,
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
        effective_at: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Record a confirmed account/operation change. Unconfirmed user
        statements belong in an observation with evidence_status=reported,
        not here. ``effective_at`` is optional and only for changes with a
        real execution-time difference."""

        payload: dict[str, Any] = {
            "change_type": change_type,
            "direction": direction,
            "source": source,
            "origin": origin,
        }
        if magnitude is not None:
            payload["magnitude"] = magnitude
        if effective_at is not None:
            payload["effective_at"] = effective_at
        return self._append(
            event_type="change",
            platform=None,
            payload=payload,
            source_type="manual",
            evidence_status=evidence_status,
            refs=refs,
            run_id=run_id,
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
        origin: str = "agent_constrained",
        review_condition: str | None = None,
        review_after: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Record one operational recommendation with minimal context.

        A decision is a recommendation, not a business fact: provenance is
        expressed by ``origin`` (deterministic / agent_constrained /
        operator), certainty by ``confidence``, and the event's
        evidence_status is ``inferred`` by default — the engine never
        claims decisions as confirmed facts. Hidden chain-of-thought is
        never persisted (Broad internally, concise persistently).
        """

        if decision_class not in DECISION_CLASSES:
            raise ContractError(f"unknown decision_class: {decision_class}")
        if measurement_state not in MEASUREMENT_STATES:
            raise ContractError(f"unknown measurement_state: {measurement_state}")
        if maturity_state not in MATURITY_STATES:
            raise ContractError(f"unknown maturity_state: {maturity_state}")
        if confidence not in CONFIDENCE_LEVELS:
            raise ContractError(f"unknown confidence: {confidence}")
        validate_decision_origin(origin)
        payload: dict[str, Any] = {
            "decision_class": decision_class,
            "reason": reason[:500],
            "evidence_refs": sorted(evidence_refs),
            "policy_constraints": dict(policy_constraints or {}),
            "measurement_state": measurement_state,
            "maturity_state": maturity_state,
            "confidence": confidence,
            "origin": origin,
        }
        if review_condition is not None:
            payload["review_condition"] = review_condition
        if review_after is not None:
            payload["review_after"] = review_after
        return self._append(
            event_type="decision",
            platform=None,
            payload=payload,
            source_type={
                "deterministic": "deterministic_engine",
                "agent_constrained": "agent",
                "operator": "manual",
            }[origin],
            evidence_status="inferred",
            refs=tuple(evidence_refs),
            run_id=run_id,
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
        run_id: str | None = None,
    ) -> str:
        """Record what happened after a previous decision/change. References
        are validated for existence and exact type."""

        if outcome_class not in OUTCOME_CLASSES:
            raise ContractError(f"unknown outcome_class: {outcome_class}")
        refs: list[str] = []
        for event_id in (decision_id, change_id):
            if event_id is not None:
                if not is_event_id(event_id):
                    raise ContractError(f"invalid event reference: {event_id}")
                refs.append(event_id)
        for observation_id in observation_ids:
            if not is_event_id(observation_id):
                raise ContractError(f"invalid event reference: {observation_id}")
        refs.extend(observation_ids)
        ref_type_map: dict[str, str] = {}
        if decision_id is not None:
            ref_type_map[decision_id] = "decision"
        if change_id is not None:
            ref_type_map[change_id] = "change"
        for observation_id in observation_ids:
            ref_type_map[observation_id] = "observation"
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
            run_id=run_id,
            ref_type_map=ref_type_map,
        )

    # ── retrieval (bounded for the model, full log for derivation) ───────

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
        match = _EVENT_FILE_RE.fullmatch(resolved.name)
        if match is not None:
            sequence, filename_type = int(match.group(1)), match.group(2)
            event_id = document.get("event_id")
            if event_id != _event_id(sequence):
                raise ContractError(
                    f"state event id mismatch in {resolved.name}: "
                    f"file implies {_event_id(sequence)}, content has {event_id!r}"
                )
            if document.get("type") != filename_type:
                raise ContractError(
                    f"state event type mismatch in {resolved.name}: "
                    f"file implies {filename_type}, content has {document.get('type')!r}"
                )
        return document

    def get_recent(
        self,
        *,
        limit: int = _DEFAULT_LIMIT,
        event_type: str | None = None,
        platform: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the newest events, newest first. Bounded by default.

        ``platform`` filters on the event's platform field (a workspace-
        internal filter; it can never reach another workspace). Platform-
        aware retrieval prevents one platform's recent history from
        starving another platform out of a bounded context.
        """
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
        if platform is None:
            return tuple(self._read_event(path) for _, _, path in entries[:limit])
        matched: list[dict[str, Any]] = []
        for _sequence, _kind, path in entries:
            if len(matched) >= limit:
                break
            event = self._read_event(path)
            if event.get("platform") == platform:
                matched.append(event)
        return tuple(matched)

    def get_recent_observations(
        self, limit: int = _DEFAULT_LIMIT, *, platform: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="observation", platform=platform)

    def get_recent_changes(
        self, limit: int = _DEFAULT_LIMIT, *, platform: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="change", platform=platform)

    def get_recent_decisions(
        self, limit: int = _DEFAULT_LIMIT, *, platform: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="decision", platform=platform)

    def get_recent_outcomes(
        self, limit: int = _DEFAULT_LIMIT, *, platform: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        return self.get_recent(limit=limit, event_type="outcome", platform=platform)

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
        """Derived from the FULL event log, not a recent window (Part 6).

        An old decision with a review condition stays pending even after
        hundreds of later events, as long as no outcome links to it.
        """
        with WorkspaceWriteLock(self._resolved_lock_path()):
            return self._derive_pending_review_locked()

    # ── derived current state (full log) ─────────────────────────────────

    def current_state(self) -> dict[str, Any]:
        """Read the derived current state; detect staleness and rebuild.

        Freshness: if the event log has advanced past
        ``derived_through_sequence`` (e.g. a crash between event write and
        rebuild), the derived file is stale and is rebuilt from the full
        log before returning.
        """
        path = self._resolved_current_path()
        if not path.is_file():
            return self.rebuild_current_state()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.rebuild_current_state()
        if not isinstance(document, dict):
            return self.rebuild_current_state()
        derived_through = document.get("derived_through_sequence")
        if not isinstance(derived_through, int):
            return self.rebuild_current_state()
        actual_max, actual_count = self._log_extent()
        stored_count = document.get("event_count")
        # Exact equality on BOTH dimensions: a derived_through ABOVE the real
        # max (e.g. 999 vs 100) is corrupted/invalid, not "ahead and fresh".
        if (
            derived_through != actual_max
            or stored_count != actual_count
            or not isinstance(stored_count, int)
        ):
            return self.rebuild_current_state()
        return document

    def rebuild_current_state(self) -> dict[str, Any]:
        """Rebuild from the full event log (streaming scan, bounded memory)."""

        with WorkspaceWriteLock(self._resolved_lock_path()):
            return self._rebuild_locked()

    def _rebuild_locked(self) -> dict[str, Any]:
        events_dir = self._resolved_events_dir()
        entries = (
            sorted(self._iter_event_files(events_dir)) if events_dir.is_dir() else []
        )
        self._assert_sequence_continuity(entries)
        last: dict[str, str | None] = {
            "observation": None,
            "change": None,
            "decision": None,
            "outcome": None,
        }
        measurement_state: str = "unknown"
        maturity_state: str = "unknown"
        last_facts: dict[str, Any] = {}
        resolved_decisions: set[str] = set()
        review_candidates: list[dict[str, Any]] = []
        for sequence, kind, path in entries:
            event = self._read_event(path)
            last[kind] = event.get("event_id")
            if kind == "observation":
                facts = event.get("payload", {}).get("facts", {})
                if isinstance(facts, dict):
                    last_facts = dict(facts)
                    measurement_state = str(
                        facts.get("measurement_state", measurement_state)
                    )
                    maturity_state = str(facts.get("maturity_state", maturity_state))
            elif kind == "outcome":
                decision_id = event.get("payload", {}).get("decision_id")
                if isinstance(decision_id, str) and is_event_id(decision_id):
                    resolved_decisions.add(decision_id)
            elif kind == "decision":
                payload = event.get("payload", {})
                if "review_condition" in payload:
                    review_candidates.append(event)
        pending_review = next(
            (
                {
                    "decision_id": candidate["event_id"],
                    "decision_class": candidate.get("payload", {}).get(
                        "decision_class"
                    ),
                    "condition": candidate.get("payload", {}).get("review_condition"),
                    "review_after": candidate.get("payload", {}).get("review_after"),
                    "status": "pending",
                }
                for candidate in reversed(review_candidates)
                if candidate["event_id"] not in resolved_decisions
            ),
            None,
        )
        max_sequence = entries[-1][0] if entries else 0
        current = {
            "schema_version": STATE_SCHEMA_VERSION,
            "derived_at": _now_iso(),
            "derived_through_sequence": max_sequence,
            "event_count": len(entries),
            "last_observation_id": last["observation"],
            "last_change_id": last["change"],
            "last_decision_id": last["decision"],
            "last_outcome_id": last["outcome"],
            "measurement_state": measurement_state,
            "maturity_state": maturity_state,
            "pending_review": pending_review,
            "open_questions": [],
            "last_facts": last_facts,
        }
        _dump(self._resolved_current_path(), current)
        _best_effort_chmod(self._resolved_current_path(), 0o600)
        return current

    def _assert_sequence_continuity(self, entries: list[tuple[int, str, Path]]) -> None:
        """The event log must be one continuous sequence 1..max.

        A gap or duplicate sequence means the event history itself is
        broken (deleted or copied files); this fails loudly instead of
        silently rebuilding a "healthy" derived state on top of a damaged
        log.
        """

        sequences = [sequence for sequence, _kind, _path in entries]
        if not sequences:
            return
        expected = set(range(1, max(sequences) + 1))
        missing = sorted(expected.difference(sequences))
        if missing:
            raise ContractError(
                "state event log has sequence gap(s): "
                + ", ".join(f"event_{number:08d}" for number in missing[:5])
                + "; event history is damaged, fix it before continuing"
            )
        duplicates = [
            sequence for sequence in sequences if sequences.count(sequence) > 1
        ]
        if duplicates:
            raise ContractError(
                "state event log has duplicate sequence(s): "
                + ", ".join(f"event_{number:08d}" for number in sorted(set(duplicates)))
            )

    def _derive_pending_review_locked(self) -> dict[str, Any] | None:
        events_dir = self._resolved_events_dir()
        if not events_dir.is_dir():
            return None
        resolved_decisions: set[str] = set()
        review_candidates: list[dict[str, Any]] = []
        for _sequence, kind, path in sorted(self._iter_event_files(events_dir)):
            event = self._read_event(path)
            if kind == "outcome":
                decision_id = event.get("payload", {}).get("decision_id")
                if isinstance(decision_id, str) and is_event_id(decision_id):
                    resolved_decisions.add(decision_id)
            elif kind == "decision":
                payload = event.get("payload", {})
                if "review_condition" in payload:
                    review_candidates.append(event)
        return next(
            (
                {
                    "decision_id": candidate["event_id"],
                    "decision_class": candidate.get("payload", {}).get(
                        "decision_class"
                    ),
                    "condition": candidate.get("payload", {}).get("review_condition"),
                    "review_after": candidate.get("payload", {}).get("review_after"),
                    "status": "pending",
                }
                for candidate in reversed(review_candidates)
                if candidate["event_id"] not in resolved_decisions
            ),
            None,
        )

    def _max_sequence(self) -> int:
        return self._log_extent()[0]

    def _log_extent(self) -> tuple[int, int]:
        """(max sequence, event count) for the current event log."""

        events_dir = self._resolved_events_dir()
        if not events_dir.is_dir():
            return (0, 0)
        sequences = [
            sequence for sequence, _kind, _path in self._iter_event_files(events_dir)
        ]
        return (max(sequences, default=0), len(sequences))

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
            "workspace_id_bound": self._identity_bound(),
        }

    def _identity_bound(self) -> bool:
        if not self.initialized:
            return False
        try:
            self._validate_workspace_identity()
            return True
        except ContractError:
            return False

    def verify(self) -> dict[str, Any]:
        """State doctor: report integrity problems without fixing them.

        Checks: workspace identity, schema validity, sequence uniqueness,
        filename/event-id consistency, reference validity, current-state
        freshness, symlink escapes. Problems are listed; nothing is
        silently repaired.
        """

        issues: list[str] = []
        if not self.initialized:
            return {"healthy": False, "issues": ["state store not initialized"]}
        try:
            self._validate_workspace_identity()
        except ContractError as exc:
            issues.append(f"workspace identity: {exc}")
        try:
            self._load_schema()
        except ContractError as exc:
            issues.append(f"schema: {exc}")
        events_dir = self._resolved_events_dir()
        if events_dir.is_dir():
            try:
                entries = sorted(self._iter_event_files(events_dir))
                self._assert_sequence_continuity(entries)
            except ContractError as exc:
                issues.append(f"event log: {exc}")
                entries = []
            seen_sequences: set[int] = set()
            for sequence, kind, path in entries:
                if sequence in seen_sequences:
                    issues.append(f"duplicate sequence {sequence}")
                seen_sequences.add(sequence)
                try:
                    event = self._read_event(path)
                except ContractError as exc:
                    issues.append(f"event {path.name}: {exc}")
                    continue
                # Reference existence + type validation.
                event_type = event.get("type")
                if event_type == "decision":
                    allowed_types = {"observation", "change"}
                elif event_type == "outcome":
                    payload = event.get("payload", {})
                    allowed_by_ref: dict[str, str] = {}
                    decision_ref = payload.get("decision_id")
                    if isinstance(decision_ref, str):
                        allowed_by_ref[decision_ref] = "decision"
                    change_ref = payload.get("change_id")
                    if isinstance(change_ref, str):
                        allowed_by_ref[change_ref] = "change"
                    for observation_ref in payload.get("observation_ids", ()):
                        if isinstance(observation_ref, str):
                            allowed_by_ref[observation_ref] = "observation"
                    allowed_types = None
                else:
                    allowed_by_ref = {}
                    allowed_types = None
                for ref in event.get("refs", ()):
                    if not is_event_id(ref):
                        continue
                    try:
                        target = self.get_event(ref)
                    except ContractError:
                        issues.append(
                            f"event {event.get('event_id')} refs missing {ref}"
                        )
                        continue
                    if allowed_types is not None:
                        if target.get("type") not in allowed_types:
                            issues.append(
                                f"event {event.get('event_id')} ref {ref} has "
                                f"wrong type {target.get('type')}"
                            )
                    elif (
                        ref in allowed_by_ref
                        and target.get("type") != allowed_by_ref[ref]
                    ):
                        issues.append(
                            f"event {event.get('event_id')} ref {ref} has "
                            f"wrong type {target.get('type')}; "
                            f"expected {allowed_by_ref[ref]}"
                        )
        current = self._resolved_current_path()
        if current.is_file():
            try:
                document = json.loads(current.read_text(encoding="utf-8"))
                derived_through = document.get("derived_through_sequence")
                stored_count = document.get("event_count")
                try:
                    actual_max, actual_count = self._log_extent()
                except ContractError as exc:
                    issues.append(f"event log: {exc}")
                    actual_max, actual_count = 0, 0
                if (
                    not isinstance(derived_through, int)
                    or derived_through != actual_max
                    or not isinstance(stored_count, int)
                    or stored_count != actual_count
                ):
                    issues.append("current state is stale (rebuild needed)")
            except (OSError, ValueError):
                issues.append("current state is corrupted (rebuild needed)")
        return {"healthy": not issues, "issues": issues}

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
