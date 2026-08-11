"""Workspace-scoped continuous account state: event model and run context.

Isolation-first design (docs/account-state.md):

- State belongs to a workspace, never to AppFlow globally. There is no
  global business memory, no global index, and no tenant-column store.
- One workspace = one state store, physically located under the workspace
  root (``state/``), so client/project isolation is a filesystem property.
- All state access is workspace-bound through :class:`RunContext`; no API
  accepts an arbitrary filesystem path.
- Cross-workspace access is denied by default; explicit comparison is a
  future capability and not implemented here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import _load
from .types import ContractError
from .workspace import Workspace

STATE_SCHEMA_VERSION = 1
STATE_DIR_NAME = "state"
EVENTS_DIR_NAME = "events"
CURRENT_STATE_NAME = "current-state.json"
SCHEMA_NAME = "schema.json"
WORKSPACE_CONTEXT_KEY = "workspace_sha256"

EVENT_TYPES = ("observation", "change", "decision", "outcome")
# Evidence certainty: confirmed = deterministic/imported fact, reported =
# user statement, inferred = derived by AppFlow. Never a complex probability.
EVIDENCE_STATUSES = ("confirmed", "reported", "inferred")
SOURCE_TYPES = (
    "export",
    "screenshot",
    "pasted_table",
    "user_statement",
    "deterministic_engine",
    "replay",
    "manual",
)

DECISION_CLASSES = (
    "keep",
    "increase",
    "decrease",
    "pause",
    "reopen",
    "replace",
    "wait",
    "observe",
    "investigate",
)
OUTCOME_CLASSES = (
    "improved",
    "worsened",
    "neutral",
    "inconclusive",
    "rolled_back",
    "not_executed",
)
MEASUREMENT_STATES = ("stable", "invalid", "unknown")
MATURITY_STATES = ("sufficient", "insufficient", "unknown")
CONFIDENCE_LEVELS = ("high", "medium", "low")

_EVENT_ID_RE = re.compile(r"^event_[0-9]{8,}$")


@dataclass(frozen=True)
class RunContext:
    """The immutable runtime scope one run is bound to.

    Created once per run from the resolved workspace. Every state read or
    write inside this run stays inside this workspace; switching to another
    workspace requires a new context (cross-workspace operations are a
    future, explicitly authorized capability).
    """

    workspace: Workspace
    client_scope: str | None = None
    project_scope: str | None = None

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> RunContext:
        context = workspace.context_path
        client: str | None = None
        project: str | None = None
        if context.is_file() and not context.is_symlink():
            try:
                document = _load(context)
                project_info = document.get("project", {})
                if isinstance(project_info, dict):
                    client = project_info.get("client_label")
                    project = project_info.get("name")
            except (OSError, ValueError, TypeError):
                pass
        return cls(
            workspace=workspace,
            client_scope=str(client) if client is not None else None,
            project_scope=str(project) if project is not None else None,
        )

    # All state paths are derived from the bound workspace root only.
    @property
    def state_dir(self) -> Path:
        return self.workspace.root / STATE_DIR_NAME

    @property
    def events_dir(self) -> Path:
        return self.state_dir / EVENTS_DIR_NAME

    @property
    def current_state_path(self) -> Path:
        return self.state_dir / CURRENT_STATE_NAME

    @property
    def schema_path(self) -> Path:
        return self.state_dir / SCHEMA_NAME


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def validate_event_type(event_type: str) -> str:
    if event_type not in EVENT_TYPES:
        raise ContractError(
            f"unknown state event type {event_type!r}; expected one of "
            + ", ".join(EVENT_TYPES)
        )
    return event_type


def validate_evidence_status(status: str) -> str:
    if status not in EVIDENCE_STATUSES:
        raise ContractError(
            f"unknown evidence_status {status!r}; expected one of "
            + ", ".join(EVIDENCE_STATUSES)
        )
    return status


def validate_source_type(source_type: str) -> str:
    if source_type not in SOURCE_TYPES:
        raise ContractError(
            f"unknown source_type {source_type!r}; expected one of "
            + ", ".join(SOURCE_TYPES)
        )
    return source_type


def is_event_id(value: str) -> bool:
    return _EVENT_ID_RE.fullmatch(value) is not None


def validate_refs(refs: tuple[str, ...], workspace: Workspace) -> tuple[str, ...]:
    """State references may only point inside the current workspace.

    Accepted forms: event ids (``event_00000001``) or workspace-relative
    artifact paths. Absolute paths, ``..`` traversal, symlink escapes, and
    any reference into another workspace are contract errors.
    """

    for ref in refs:
        if is_event_id(ref):
            continue
        candidate = workspace.require_contained_path(
            workspace.root / ref, "state reference"
        )
        relative = candidate.relative_to(workspace.root)
        if ".." in relative.parts:
            raise ContractError(
                f"state reference must stay inside the workspace: {ref}"
            )
    return tuple(refs)


def build_event(
    *,
    event_type: str,
    platform: str | None,
    payload: Mapping[str, Any],
    source_type: str,
    evidence_status: str,
    refs: tuple[str, ...] = (),
    recorded_at: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build one validated state event envelope (platform-neutral)."""

    validate_event_type(event_type)
    validate_source_type(source_type)
    validate_evidence_status(evidence_status)
    if not isinstance(payload, Mapping):
        raise ContractError("state event payload must be an object")
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "type": event_type,
        "recorded_at": recorded_at or _utc_now(),
        "observed_at": observed_at or recorded_at or _utc_now(),
        "source_type": source_type,
        "evidence_status": evidence_status,
        "platform": platform,
        "refs": sorted(refs),
        "payload": dict(payload),
    }
