"""State runtime session: the single integration point for Agent workflows.

The main router is the canonical lifecycle (docs/account-state.md): one
session per run, created after workspace resolution. Platform skills may
supply platform-specific observation mapping, but they must not implement
their own state lifecycle.

Lifecycle:

    before_reasoning()      -> load current summary + bounded history
    record_observation()    -> reliable new facts (deduped per run)
    record_decision()       -> operational recommendation (origin-aware)
    record_confirmed_change()-> ONLY after the operator confirms execution
    record_outcome()        -> only when later evidence justifies it

Rules enforced here:

- A recommendation alone never records a Change; only confirmed execution
  does (record_confirmed_change is intentionally named).
- An outcome is never written at decision time; it needs later evidence.
- Duplicate writes within one run are prevented by (type, source_digest)
  deduplication.
- Full assistant answers are never stored; only the structured summary.
- Every write goes through StateStore (validation, locking, workspace
  binding); the model never writes state files directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .account_state import RunContext, new_run_id
from .state_store import StateStore


class StateSession:
    """One run's workspace-scoped state integration."""

    def __init__(self, context: RunContext) -> None:
        self.context = context
        self.run_id = new_run_id()
        self.store = StateStore(context)
        self._written: set[tuple[str, str]] = set()

    # ── before reasoning (Part 7) ────────────────────────────────────────

    def load_context_summary(self) -> dict[str, Any]:
        """What Verify needs before reasoning: current state + bounded
        recent history. Semantic and bounded: terminology questions do not
        need to call this."""

        self.store.ensure_initialized()
        current = self.store.current_state()
        return {
            "run_id": self.run_id,
            "workspace_id": self.context.workspace_id,
            "current_state": current,
            "recent": {
                "observations": list(self.store.get_recent_observations(limit=5)),
                "changes": list(self.store.get_recent_changes(limit=5)),
                "decisions": list(self.store.get_recent_decisions(limit=5)),
                "outcomes": list(self.store.get_recent_outcomes(limit=5)),
            },
        }

    # ── after observation (Part 8.1) ────────────────────────────────────

    def record_observation(
        self,
        *,
        observed_at: str,
        platform: str,
        facts: Mapping[str, Any],
        source_type: str = "export",
        evidence_status: str = "confirmed",
        source_digest: str | None = None,
        refs: tuple[str, ...] = (),
    ) -> str | None:
        """Record one observation for reliable new facts. Same-run writes
        with the same (observation, source_digest) are deduplicated."""

        dedupe_key = ("observation", source_digest or "")
        if source_digest is not None and dedupe_key in self._written:
            return None
        event_id = self.store.append_observation(
            observed_at=observed_at,
            platform=platform,
            facts=facts,
            source_type=source_type,
            evidence_status=evidence_status,
            refs=refs,
            run_id=self.run_id,
        )
        self._written.add(dedupe_key)
        return event_id

    # ── after decision (Part 8.2) ────────────────────────────────────────

    def record_decision(
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
        source_digest: str | None = None,
    ) -> str | None:
        """Record one operational recommendation. ``origin`` defaults to
        ``agent_constrained`` (LLM interpretation constrained by runtime
        gates) — never claimed as purely deterministic unless it is."""

        dedupe_key = ("decision", source_digest or "")
        if source_digest is not None and dedupe_key in self._written:
            return None
        event_id = self.store.append_decision(
            decision_class=decision_class,
            reason=reason,
            evidence_refs=evidence_refs,
            policy_constraints=policy_constraints,
            measurement_state=measurement_state,
            maturity_state=maturity_state,
            confidence=confidence,
            origin=origin,
            review_condition=review_condition,
            review_after=review_after,
            run_id=self.run_id,
        )
        self._written.add(dedupe_key)
        return event_id

    # ── after confirmed change (Part 8.3) ────────────────────────────────

    def record_confirmed_change(
        self,
        *,
        change_type: str,
        direction: str,
        magnitude: float | None = None,
        source: str = "manual",
        origin: str = "operator",
        evidence_status: str = "confirmed",
        effective_at: str | None = None,
        source_digest: str | None = None,
        refs: tuple[str, ...] = (),
    ) -> str | None:
        """Record a change ONLY after execution is confirmed (operator
        confirmation or deterministic evidence). A recommendation alone
        must never reach this method."""

        dedupe_key = ("change", source_digest or "")
        if source_digest is not None and dedupe_key in self._written:
            return None
        event_id = self.store.append_change(
            change_type=change_type,
            direction=direction,
            magnitude=magnitude,
            source=source,
            origin=origin,
            evidence_status=evidence_status,
            effective_at=effective_at,
            refs=refs,
            run_id=self.run_id,
        )
        self._written.add(dedupe_key)
        return event_id

    # ── after outcome (Part 8.4) ─────────────────────────────────────────

    def record_outcome(
        self,
        *,
        outcome_class: str,
        decision_id: str | None = None,
        change_id: str | None = None,
        observation_ids: tuple[str, ...] = (),
        source_type: str = "export",
        evidence_status: str = "confirmed",
        source_digest: str | None = None,
    ) -> str | None:
        """Record an outcome only when later evidence justifies it — never
        at decision time."""

        dedupe_key = ("outcome", source_digest or "")
        if source_digest is not None and dedupe_key in self._written:
            return None
        event_id = self.store.append_outcome(
            outcome_class=outcome_class,
            decision_id=decision_id,
            change_id=change_id,
            observation_ids=observation_ids,
            source_type=source_type,
            evidence_status=evidence_status,
            run_id=self.run_id,
        )
        self._written.add(dedupe_key)
        return event_id
