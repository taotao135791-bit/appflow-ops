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
from dataclasses import dataclass
from typing import Any

from .account_state import RunContext
from .platform_adapters import (
    CROSS_PLATFORM_HYPOTHESES,
    PlatformAdapter,
    adapter_for,
)
from .run_lifecycle import (
    AppFlowRuntime,
    StateAccess,
    build_state_context,
    classify_state_access,
)
from .state_runtime import StateSession
from .state_store import StateStore
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
    """The four shared safety gates, platform-neutral."""

    measurement_state: str = "unknown"  # stable | invalid | unknown
    maturity_state: str = "unknown"  # sufficient | insufficient | unknown
    policy_state: str = "default"
    permission_state: str = "recommend_only"  # full_access | recommend_only | read_only


@dataclass
class OperationalContext:
    """Bounded context handed to the Agent/Reasoning layer."""

    request: str
    workspace: Workspace
    platform_scope: tuple[str, ...]
    state_context: dict[str, Any] | None
    current_observation: dict[str, Any] | None
    hypotheses: tuple[str, ...]
    safety: PlatformSafetyContext


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
        self._platform_state: dict[str, Any] | None = None
        self._started = False

    def begin(
        self,
        request_text: str | None = None,
        *,
        state_access: str | None = None,
        platform_scope: tuple[str, ...] | None = None,
    ) -> PlatformOperationalRun:
        """Start the run: resolve platform scope and state access, then
        load platform-aware state when required."""
        self.request = request_text or ""
        scope = platform_scope or self.explicit_platform_scope
        if scope is None and request_text:
            scope = detect_platforms(request_text)
        self.platform_scope = tuple(scope or ())
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
    ) -> str | None:
        """Project new evidence through the platform adapter and persist one
        Observation (deduped by the shared runtime)."""
        self._require_started()
        adapter = adapter_for(platform)
        facts = adapter.project_observation(metrics) if adapter else dict(metrics)
        funnel = adapter.project_funnel(metrics) if adapter else {}
        facts.update(funnel)
        return self.session.record_observation(
            observed_at=observed_at,
            platform=platform,
            facts=facts,
            source_type=source_type,
            evidence_status=evidence_status,
        )

    def operational_context(
        self, adapter: PlatformAdapter | None = None
    ) -> OperationalContext:
        """Bounded context for the reasoning layer: state + hypotheses +
        safety envelope."""
        self._require_started()
        safety = PlatformSafetyContext(
            measurement_state=self._measurement_state(),
            maturity_state=self._maturity_state(),
            permission_state=self._permission_state(),
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
        return OperationalContext(
            request=self.request,
            workspace=self.workspace,
            platform_scope=self.platform_scope,
            state_context=self._platform_state,
            current_observation=None,
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
    ) -> str | None:
        """Persist one operational Decision through the shared session."""
        self._require_started()
        return self.session.record_decision(
            decision_class=decision_class,
            reason=reason,
            evidence_refs=evidence_refs,
            confidence=confidence,
            origin=origin,
            review_condition=review_condition,
            review_after=review_after,
            policy_constraints={"permission_state": self._permission_state()},
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

    # ── safety state (live workspace evidence + permissions) ─────────────

    def _measurement_state(self) -> str:
        for event in self.store.get_recent_observations(limit=5):
            facts = event.get("payload", {}).get("facts", {})
            value = facts.get("measurement_state")
            if isinstance(value, str) and value != "unknown":
                return value
        return "unknown"

    def _maturity_state(self) -> str:
        for event in self.store.get_recent_observations(limit=5):
            facts = event.get("payload", {}).get("facts", {})
            value = facts.get("maturity_state")
            if isinstance(value, str) and value != "unknown":
                return value
        return "unknown"

    def _permission_state(self) -> str:
        try:
            document = self.workspace.context_path
            if document.is_file() and not document.is_symlink():
                from .io import _load

                context = _load(document)
                permissions = context.get("permissions", {})
                if isinstance(permissions, dict):
                    allowed = permissions.get("optimizer_can", [])
                    if isinstance(allowed, list):
                        return "full_access" if allowed else "recommend_only"
        except (OSError, ValueError, TypeError):
            pass
        return "recommend_only"


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
