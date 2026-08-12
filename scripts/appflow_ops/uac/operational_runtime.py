"""Platform Operational Runtime (v3.4.0).

The canonical operational lifecycle for non-Google platforms (Meta, TikTok,
Creative, cross-platform): one entry point that resolves workspace and
platform scope, decides state access, loads platform-aware bounded state,
projects and persists new evidence, supplies hypothesis families + safety
envelope, accepts a structured decision, and persists it.

Callers no longer manage StateSession manually for normal operational runs.
The reasoning loop stays in the Reasoning Contract; this runtime only
orchestrates it. Google UAC keeps its deterministic engine as a stronger
decision component — this runtime does not replace it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .account_state import RunContext
from .platform_adapters import (
    CROSS_PLATFORM_HYPOTHESES,
    GENERIC,
    PlatformAdapter,
    adapter_for,
)
from .run_lifecycle import (
    AppFlowRuntime,
    StateAccess,
    build_state_context,
    classify_state_access,
)
from .safety_validator import SafetyVerdict, validate_decision_action
from .state_runtime import StateSession
from .state_store import StateStore
from .types import ContractError
from .workspace import Workspace

# Per-platform retrieval budget: bounded regardless of platform count.
PER_PLATFORM_OBSERVATIONS = 3
PER_PLATFORM_CHANGES = 2
PER_PLATFORM_DECISIONS = 2
PER_PLATFORM_OUTCOMES = 1
MAX_PLATFORM_SCOPE = 4

_PLATFORM_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_ads", re.compile(r"google|谷歌|uac", re.IGNORECASE)),
    ("meta", re.compile(r"meta|facebook|fb\b|instagram|ins\b", re.IGNORECASE)),
    # tt must not match inside English words ("attention"), but must match
    # "TT还是没量" where the boundary is CJK.
    ("tiktok", re.compile(r"tiktok|(?:^|[^a-z])tt(?:[^a-z]|$)", re.IGNORECASE)),
    ("creative", re.compile(r"素材|creative|广告创意", re.IGNORECASE)),
)


def detect_platforms(text: str) -> tuple[str, ...]:
    """Lightweight platform-scope detection from a request (Router may
    override with an explicit ``platform_scope``). Unknown stays empty."""
    return tuple(
        platform for platform, pattern in _PLATFORM_HINTS if pattern.search(text)
    )


@dataclass(frozen=True)
class PlatformSafetyContext:
    """The four shared safety gates, platform-neutral vocabulary (values
    come from the canonical enums in appflow_ops.evals.safety).

    Single-platform runs expose ``measurement_state`` / ``maturity_state``
    as the platform's own value. Multi-platform runs keep per-platform
    values in ``measurement_by_platform`` / ``maturity_by_platform`` and
    expose conservative aggregates in the scalar fields (any relevant
    platform invalid → invalid; else any unknown → unknown; else stable).
    """

    measurement_state: str = "unknown"
    maturity_state: str = "unknown"
    measurement_by_platform: Mapping[str, str] = field(default_factory=dict)
    maturity_by_platform: Mapping[str, str] = field(default_factory=dict)
    policy_state: str = "none"
    permission_state: str = "read_only"
    platform_scope: tuple[str, ...] = ()


@dataclass
class OperationalContext:
    """Bounded context handed to the Agent/Reasoning layer.

    ``current_observation`` is a convenience for single-platform runs (the
    latest recorded observation of this run); ``current_observations``
    always holds the per-platform map so cross-platform runs see every
    platform's current evidence.
    """

    request: str
    workspace: Workspace
    platform_scope: tuple[str, ...]
    state_context: dict[str, Any] | None
    current_observation: dict[str, Any] | None = None
    current_observations: dict[str, Any] = field(default_factory=dict)
    hypotheses: tuple[str, ...] = ()
    safety: PlatformSafetyContext = field(default_factory=PlatformSafetyContext)


@dataclass
class OperationalResult:
    """Structured output of one operational run (Part 29)."""

    platform_scope: tuple[str, ...]
    conclusion: str
    primary_action: str
    evidence_refs: tuple[str, ...] = ()
    ruled_out: tuple[str, ...] = ()
    uncertainty: str = "medium"
    review_condition: str | None = None
    decision_id: str | None = None


def _platform_bounded_state(
    session: StateSession, platforms: tuple[str, ...] | None
) -> dict[str, Any]:
    """Per-platform bounded retrieval with a total budget.

    Never a global limit=1000: each platform contributes at most
    (3 observations + 2 changes + 2 decisions + 1 outcome), and the scope
    is capped at MAX_PLATFORM_SCOPE platforms. Unknown scope probes the
    platforms that actually appear in the workspace's recent observations
    and applies the same per-platform budget.
    """
    if platforms is None or not platforms:
        probe = session.store.get_recent_observations(limit=_MAX_LIMIT_PROBE)
        platforms = tuple(
            dict.fromkeys(
                str(event.get("platform")) for event in probe if event.get("platform")
            )
        )[:MAX_PLATFORM_SCOPE]
    by_platform: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        by_platform[platform] = {
            "observations": list(
                session.store.get_recent_observations(
                    limit=PER_PLATFORM_OBSERVATIONS, platform=platform
                )
            ),
            "changes": list(
                session.store.get_recent_changes(
                    limit=PER_PLATFORM_CHANGES, platform=platform
                )
            ),
            "decisions": list(
                session.store.get_recent_decisions(
                    limit=PER_PLATFORM_DECISIONS, platform=platform
                )
            ),
            "outcomes": list(
                session.store.get_recent_outcomes(
                    limit=PER_PLATFORM_OUTCOMES, platform=platform
                )
            ),
        }
    return {"platforms": platforms, "by_platform": by_platform}


_MAX_LIMIT_PROBE = 50


class PlatformOperationalRun:
    """One operational run for Meta / TikTok / Creative / cross-platform.

    Lifecycle (Part 3.2): begin → resolve workspace → resolve platform
    scope → state access → platform-aware state load → project evidence →
    record Observation → hypothesis families + safety envelope → decision →
    record Decision → finish.
    """

    def __init__(
        self,
        workspace: Workspace,
        *,
        platform_scope: tuple[str, ...] | None = None,
    ) -> None:
        self.workspace = workspace
        self.context = RunContext.from_workspace(workspace)
        self.session = StateSession(self.context)
        self.store = StateStore(self.context)
        self.explicit_platform_scope = platform_scope
        self.platform_scope: tuple[str, ...] = ()
        self.state_access: str = StateAccess.NOT_NEEDED
        self.request = ""
        self.policy_state: str = "none"
        self.permission_state: str = "read_only"
        self._platform_state: dict[str, Any] | None = None
        self._current_observations: dict[str, Any] = {}
        self._persistence_warnings: list[str] = []
        self.last_verdict: SafetyVerdict | None = None
        self._started = False

    def begin(
        self,
        request_text: str | None = None,
        *,
        state_access: str | None = None,
        platform_scope: tuple[str, ...] | None = None,
        policy_state: str | None = None,
    ) -> PlatformOperationalRun:
        """Start the run: resolve platform scope and state access, then
        load platform-aware state when required. ``policy_state`` comes from
        real policy context when available (explicit or workspace policy
        file); it is never a hardcoded default.

        The object is REUSABLE-BUT-RESET: begin() clears every run-local
        field from any previous run (current observations, persistence
        warnings, last verdict, platform scope, state snapshot), so a
        second run never inherits residue from the first.
        """
        self.request = request_text or ""
        self.platform_scope = tuple(
            platform_scope or self.explicit_platform_scope or ()
        )
        if not self.platform_scope and request_text:
            self.platform_scope = detect_platforms(request_text)
        self.policy_state = self._resolve_policy_state(policy_state)
        self.permission_state = self._permission_state()
        self.state_access = StateAccess.NOT_NEEDED
        self._platform_state = None
        self._current_observations = {}
        self._persistence_warnings = []
        self.last_verdict = None
        if state_access is not None:
            self.state_access = state_access
        elif request_text is None:
            self.state_access = StateAccess.NOT_NEEDED
        else:
            self.state_access = classify_state_access(request_text)
        if self.state_access == StateAccess.REQUIRED:
            self.store.ensure_initialized()
            self._platform_state = _platform_bounded_state(
                self.session, self.platform_scope or None
            )
        self._started = True
        return self

    @property
    def state_loaded(self) -> bool:
        return self._platform_state is not None

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("begin() must be called before using the run")

    def record_observation(
        self,
        metrics: Mapping[str, Any],
        *,
        platform: str,
        observed_at: str,
        source_type: str = "export",
        evidence_status: str = "confirmed",
        allow_generic: bool = False,
    ) -> str | None:
        """Project new evidence through the platform adapter and persist one
        Observation (deduped by the shared runtime).

        Unknown platforms are REJECTED (no raw passthrough); the explicit
        ``generic`` adapter is allowlist-only and requires ``allow_generic``.
        The projected observation also becomes THIS run's current evidence,
        so the same-run reasoning context sees it without a full reload.
        If persistence fails, reasoning continues with the in-memory
        current observation (``persisted=False``) and a recorded warning;
        nothing is pretended to be persisted.
        """
        self._require_started()
        adapter = adapter_for(platform)
        if adapter is None:
            raise ContractError(
                f"unknown platform {platform!r}: no adapter registered; "
                "raw passthrough is not allowed (use a known platform or "
                "the explicit 'generic' adapter)"
            )
        if adapter is GENERIC and not allow_generic:
            raise ContractError(
                "the 'generic' adapter requires allow_generic=True (explicit opt-in)"
            )
        facts = adapter.project_observation(metrics)
        funnel = adapter.project_funnel(metrics)
        facts.update(funnel)
        event_id: str | None = None
        persisted = True
        try:
            event_id = self.session.record_observation(
                observed_at=observed_at,
                platform=platform,
                facts=facts,
                source_type=source_type,
                evidence_status=evidence_status,
            )
        except ContractError as exc:  # pragma: no cover - failure path
            persisted = False
            self._persistence_warnings.append(f"observation not persisted: {exc}")
        self._current_observations[platform] = {
            "event_id": event_id,
            "type": "observation",
            "platform": platform,
            "observed_at": observed_at,
            "persisted": persisted,
            "payload": {"facts": facts},
        }
        return event_id

    def operational_context(
        self, adapter: PlatformAdapter | None = None
    ) -> OperationalContext:
        """Bounded context for the reasoning layer: current evidence (this
        run) + platform-scoped historical state + hypotheses + safety."""
        self._require_started()
        measurement_by_platform, maturity_by_platform = self._safety_states()
        safety = PlatformSafetyContext(
            measurement_state=self._aggregate_safety(
                measurement_by_platform, self.platform_scope
            ),
            maturity_state=self._aggregate_safety(
                maturity_by_platform, self.platform_scope
            ),
            measurement_by_platform=measurement_by_platform,
            maturity_by_platform=maturity_by_platform,
            policy_state=self.policy_state,
            permission_state=self.permission_state,
            platform_scope=self.platform_scope,
        )
        hypotheses: tuple[str, ...] = ()
        if adapter is not None:
            hypotheses = adapter.hypothesis_families
        elif len(self.platform_scope) > 1:
            hypotheses = CROSS_PLATFORM_HYPOTHESES
        else:
            single = self.platform_scope[0] if self.platform_scope else None
            found = adapter_for(single) if single else None
            hypotheses = found.hypothesis_families if found else ()
        current_observation = None
        if self._current_observations:
            last = list(self._current_observations.values())[-1]
            if len(self.platform_scope) == 1:
                current_observation = self._current_observations.get(
                    self.platform_scope[0], last
                )
            else:
                current_observation = last
        return OperationalContext(
            request=self.request,
            workspace=self.workspace,
            platform_scope=self.platform_scope,
            state_context=self._platform_state,
            current_observation=current_observation,
            current_observations=dict(self._current_observations),
            hypotheses=hypotheses,
            safety=safety,
        )

    def record_decision(
        self,
        *,
        decision_class: str,
        reason: str,
        evidence_refs: tuple[str, ...] = (),
        confidence: str = "medium",
        origin: str = "agent_constrained",
        review_condition: str | None = None,
        review_after: str | None = None,
        execution_status: str | None = None,
        diagnosis_confidence: str = "none",
    ) -> str | None:
        """Persist one operational Decision through the shared session.

        The candidate ALWAYS runs through the runtime safety validator
        (Decision≠Change, permission, diagnostic claim, measurement,
        maturity, policy) before persistence. Persistence contract:

        - allowed → persists
        - rejected → never persists (None + ``last_verdict``)
        - constrained WITHOUT a validated compliant candidate → never
          persists (None + ``last_verdict``); a constrained candidate must
          never be written verbatim into state.

        Platform attribution is inherited from the run's platform scope.
        """
        self._require_started()
        measurement_by_platform, maturity_by_platform = self._safety_states()
        verdict = validate_decision_action(
            decision_class=decision_class,
            reason=reason,
            measurement_state=self._aggregate_safety(
                measurement_by_platform, self.platform_scope
            ),
            maturity_state=self._aggregate_safety(
                maturity_by_platform, self.platform_scope
            ),
            policy_state=self.policy_state,
            permission_state=self.permission_state,
            execution_status=execution_status,
            diagnosis_confidence=diagnosis_confidence,
        )
        self.last_verdict = verdict
        if verdict.outcome != "allowed":
            # rejected, or constrained without a validated candidate:
            # the original candidate is never persisted.
            return None
        platform, platform_scope = self._decision_platform()
        policy_constraints: dict[str, Any] = {
            "permission_state": self.permission_state,
            "policy_state": self.policy_state,
            "safety_result": {
                "outcome": verdict.outcome,
                "reason_code": verdict.reason_code,
            },
        }
        return self.session.record_decision(
            decision_class=decision_class,
            reason=reason,
            evidence_refs=evidence_refs,
            confidence=confidence,
            origin=origin,
            review_condition=review_condition,
            review_after=review_after,
            policy_constraints=policy_constraints,
            platform=platform,
            platform_scope=platform_scope,
            diagnosis_confidence=diagnosis_confidence,
        )

    def record_confirmed_change(
        self,
        *,
        change_type: str,
        direction: str,
        magnitude: float | None = None,
        effective_at: str | None = None,
        target_platform: str | None = None,
        refs: tuple[str, ...] = (),
    ) -> str | None:
        """Record a confirmed change ONLY after execution is confirmed.

        Platform attribution: a single-platform run inherits its platform;
        a cross-platform run REQUIRES an explicit ``target_platform`` that
        belongs to the run's scope (a recommendation never becomes a
        Change, and a Change is never mislabeled to another platform).
        """
        self._require_started()
        platform: str | None
        if target_platform is not None:
            if self.platform_scope and target_platform not in self.platform_scope:
                raise ContractError(
                    f"target_platform {target_platform!r} is outside the run's "
                    f"platform scope {self.platform_scope}"
                )
            platform = target_platform
        elif len(self.platform_scope) == 1:
            platform = self.platform_scope[0]
        else:
            # Cross-platform run: a real Change acts on ONE explicit
            # platform. Never write an unscoped Change.
            raise ContractError(
                "cross-platform change requires an explicit target_platform "
                "inside the run's platform scope"
            )
        return self.session.record_confirmed_change(
            change_type=change_type,
            direction=direction,
            magnitude=magnitude,
            effective_at=effective_at,
            refs=refs,
            platform=platform,
        )

    def record_outcome(
        self,
        *,
        outcome_class: str,
        decision_id: str | None = None,
        change_id: str | None = None,
        observation_ids: tuple[str, ...] = (),
        source_type: str = "export",
        evidence_status: str = "confirmed",
        platform: str | None = None,
    ) -> str | None:
        """Record an outcome only when later evidence justifies it.

        Platform attribution is derived from the linked decision/change when
        the caller does not pass it; a cross-platform decision's scope is
        inherited by the outcome; conflicting explicit platforms are
        rejected rather than guessed.
        """
        self._require_started()
        derived: str | None = None
        derived_scope: tuple[str, ...] = ()
        for ref in (decision_id, change_id):
            if ref is None:
                continue
            event = self.store.get_event(ref)
            event_platform = event.get("platform")
            if event_platform == "cross_platform":
                scope = event.get("payload", {}).get("platform_scope", ())
                if isinstance(scope, (list, tuple)) and scope:
                    if derived_scope and tuple(scope) != derived_scope:
                        raise ContractError(
                            "outcome refs disagree on cross-platform scope; "
                            "pass platform explicitly"
                        )
                    derived_scope = tuple(scope)
                continue
            if event_platform and event_platform != "cross_platform":
                if derived is None:
                    derived = str(event_platform)
                elif derived != event_platform:
                    raise ContractError(
                        "outcome refs disagree on platform "
                        f"({derived!r} vs {event_platform!r}); pass platform explicitly"
                    )
        if platform is not None and derived is not None and platform != derived:
            raise ContractError(
                f"outcome platform {platform!r} conflicts with derived "
                f"platform {derived!r} from its refs"
            )
        if platform is not None and derived_scope and platform != "cross_platform":
            raise ContractError(
                f"outcome platform {platform!r} conflicts with the derived "
                f"cross-platform scope {derived_scope}"
            )
        return self.session.record_outcome(
            outcome_class=outcome_class,
            decision_id=decision_id,
            change_id=change_id,
            observation_ids=observation_ids,
            source_type=source_type,
            evidence_status=evidence_status,
            platform=platform
            or derived
            or ("cross_platform" if derived_scope else None),
            platform_scope=derived_scope,
        )

    def result(
        self,
        *,
        conclusion: str,
        primary_action: str,
        evidence_refs: tuple[str, ...] = (),
        ruled_out: tuple[str, ...] = (),
        uncertainty: str = "medium",
        review_condition: str | None = None,
        decision_id: str | None = None,
    ) -> OperationalResult:
        return OperationalResult(
            platform_scope=self.platform_scope,
            conclusion=conclusion,
            primary_action=primary_action,
            evidence_refs=evidence_refs,
            ruled_out=ruled_out,
            uncertainty=uncertainty,
            review_condition=review_condition,
            decision_id=decision_id,
        )

    def finish(self) -> None:
        self._started = False
        self._platform_state = None

    # ── safety state (platform-scoped, current-first) ────────────────────

    def _safety_states(self) -> tuple[dict[str, str], dict[str, str]]:
        """(measurement_by_platform, maturity_by_platform).

        Current observations of THIS run take priority over history, and
        history is read platform-scoped — a Meta request can never inherit
        TikTok's measurement state, even when TikTok's events are newer.
        """
        measurement: dict[str, str] = {}
        maturity: dict[str, str] = {}
        for platform, event in self._current_observations.items():
            facts = event.get("payload", {}).get("facts", {})
            value = facts.get("measurement_state")
            if isinstance(value, str) and value != "unknown":
                measurement[platform] = value
            value = facts.get("maturity_state")
            if isinstance(value, str) and value != "unknown":
                maturity[platform] = value
        for platform in self.platform_scope:
            if platform not in measurement:
                for event in self.store.get_recent_observations(
                    limit=5, platform=platform
                ):
                    facts = event.get("payload", {}).get("facts", {})
                    value = facts.get("measurement_state")
                    if isinstance(value, str) and value != "unknown":
                        measurement[platform] = value
                        break
            if platform not in maturity:
                for event in self.store.get_recent_observations(
                    limit=5, platform=platform
                ):
                    facts = event.get("payload", {}).get("facts", {})
                    value = facts.get("maturity_state")
                    if isinstance(value, str) and value != "unknown":
                        maturity[platform] = value
                        break
        return measurement, maturity

    @staticmethod
    def _aggregate_safety(states: Mapping[str, str], scope: tuple[str, ...]) -> str:
        """Conservative aggregation over the RELEVANT platforms only.
        Never an average, never a flat scalar that hides platform
        differences (per-platform values stay in the by_platform maps).
        Measurement vocabulary: any invalid → invalid; else unknown; else
        stable. Maturity vocabulary: any insufficient → insufficient;
        else unknown; else sufficient.
        """
        relevant = [states[platform] for platform in scope if platform in states]
        if not relevant:
            return "unknown"
        if "invalid" in relevant:
            return "invalid"
        if "insufficient" in relevant:
            return "insufficient"
        if "unknown" in relevant:
            return "unknown"
        if all(value in {"sufficient", "stable"} for value in relevant):
            return "sufficient" if "sufficient" in relevant else "stable"
        return relevant[-1]

    def _decision_platform(self) -> tuple[str | None, tuple[str, ...]]:
        """Platform attribution inherited from the run's scope; when the
        scope is empty but this run recorded exactly one platform's
        observation, that platform is inherited (never guessed from
        history)."""
        if len(self.platform_scope) == 1:
            return self.platform_scope[0], ()
        if len(self.platform_scope) > 1:
            return "cross_platform", self.platform_scope
        if len(self._current_observations) == 1:
            return next(iter(self._current_observations)), ()
        return None, ()

    def _resolve_policy_state(self, explicit: str | None) -> str:
        """Real policy context only: explicit argument or a workspace-level
        policy file; never a hardcoded default. Unknown values degrade to
        "none" (no additional policy restriction)."""
        from appflow_ops.evals.safety import POLICY_STATES

        if explicit is not None:
            return explicit if explicit in POLICY_STATES else "none"
        try:
            from .io import _load

            for name in ("policy.yaml", "ads-policy.yaml"):
                path = self.workspace.root / name
                if path.is_file() and not path.is_symlink():
                    document = _load(path)
                    if isinstance(document, dict):
                        value = document.get("policy_state")
                        if isinstance(value, str) and value in POLICY_STATES:
                            return value
        except (OSError, ValueError, TypeError):
            pass
        return "none"

    def _permission_state(self) -> str:
        """Capability-based permission tier (canonical PERMISSION_STATES):
        [] → read_only; recommend-only → recommend_only; budget/bid/creative
        execution set → budget_bid_creative; explicit full/execute → full.
        Never a non-empty-list shortcut.
        """

        allowed: set[str] = set()
        try:
            document = self.workspace.context_path
            if document.is_file() and not document.is_symlink():
                from .io import _load

                context = _load(document)
                permissions = context.get("permissions", {})
                if isinstance(permissions, dict):
                    raw = permissions.get("optimizer_can", [])
                    if isinstance(raw, list):
                        allowed = {str(item) for item in raw}
        except (OSError, ValueError, TypeError):
            pass
        if "full" in allowed or "execute" in allowed:
            return "full"
        if allowed & {"budget", "bid", "creative", "structure", "campaign"}:
            return "budget_bid_creative"
        if "recommend" in allowed:
            return "recommend_only"
        return "read_only"


def build_operational_context(
    workspace: Workspace,
    request_text: str,
    *,
    platform_scope: tuple[str, ...] | None = None,
    state_access: str | None = None,
) -> OperationalContext:
    """One-shot helper: begin a run and return the operational context."""
    run = PlatformOperationalRun(workspace, platform_scope=platform_scope)
    run.begin(request_text, state_access=state_access)
    return run.operational_context()


# re-export the shared runtime pieces used by platform flows
__all__ = [
    "PER_PLATFORM_CHANGES",
    "PER_PLATFORM_DECISIONS",
    "PER_PLATFORM_OBSERVATIONS",
    "PER_PLATFORM_OUTCOMES",
    "AppFlowRuntime",
    "OperationalContext",
    "OperationalResult",
    "PlatformOperationalRun",
    "PlatformSafetyContext",
    "RunContext",
    "StateAccess",
    "build_operational_context",
    "build_state_context",
    "classify_state_access",
    "detect_platforms",
]
