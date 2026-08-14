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
from typing import TYPE_CHECKING, Any

from .account_state import DECISION_CLASSES, RunContext
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

if TYPE_CHECKING:
    from appflow_ops.decision_intelligence.ranking import RankedHypothesis
    from appflow_ops.decision_intelligence.result import DecisionIntelligenceResult

# Per-platform retrieval budget: bounded regardless of platform count.
PER_PLATFORM_OBSERVATIONS = 3
PER_PLATFORM_CHANGES = 2
PER_PLATFORM_DECISIONS = 2
PER_PLATFORM_OUTCOMES = 1

# DI action classes → canonical Decision classes (v3.5.1). Decision
# Intelligence only RECOMMENDS; the mapping keeps its vocabulary inside
# the canonical decision classes (never an execution claim).
_DI_ACTION_TO_DECISION: dict[str, str] = {
    "investigate_measurement": "investigate",
    "hold": "keep",
    "refresh_variant": "replace",
}
MAX_PLATFORM_SCOPE = 4

_PLATFORM_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_ads", re.compile(r"google|谷歌|uac", re.IGNORECASE)),
    ("meta", re.compile(r"meta|facebook|fb\b|instagram|ins\b", re.IGNORECASE)),
    # tt must not match inside English words ("attention"), but must match
    # "TT还是没量" where the boundary is CJK.
    ("tiktok", re.compile(r"tiktok|(?:^|[^a-z])tt(?:[^a-z]|$)", re.IGNORECASE)),
)

# Operational domains are NOT media platforms: keywords shape the
# diagnosis domain, never the platform scope (v3.4.6 boundary). The full
# domain vocabulary lives in decision_intelligence.domains; begin()
# stores a lightweight domain hint via detect_domain().


def detect_platforms(text: str) -> tuple[str, ...]:
    """Lightweight platform-scope detection from a request (Router may
    override with an explicit ``platform_scope``). Unknown stays empty.
    Creative/domain keywords are deliberately NOT platforms here — a
    "Meta 素材是不是衰减" request yields (meta,) with domain_hint=creative.
    """
    return tuple(
        platform for platform, pattern in _PLATFORM_HINTS if pattern.search(text)
    )


def detect_domain(text: str) -> str | None:
    """Operational domain hint (creative / funnel / measurement / ...) for
    routing and context only — never part of the platform scope. Delegates
    to the Ads Decision Intelligence domain detector (v3.5.0)."""
    from appflow_ops.decision_intelligence.domains import (
        detect_operational_domain,
    )

    domain = detect_operational_domain(text)
    return None if domain == "general" else domain


def canonicalize_platform_scope(
    scope: tuple[str, ...] | None,
) -> tuple[str, ...]:
    """Single canonicalization + validation for EVERY platform scope
    entering the runtime (explicit and router-detected alike):

    - registered platforms only (from the adapter registry; an unknown
      platform is rejected BEFORE begin completes)
    - duplicates removed (("meta", "meta") is ONE platform, never a
      cross-platform run)
    - deterministic ordering (sorted)
    - bounded by MAX_PLATFORM_SCOPE (oversized scope is rejected, never
      silently truncated)
    """
    if not scope:
        return ()
    seen: list[str] = []
    for platform in scope:
        if adapter_for(platform) is None:
            raise ContractError(
                f"unknown platform in platform_scope {platform!r}: no adapter "
                "registered"
            )
        if platform not in seen:
            seen.append(platform)
    if len(seen) > MAX_PLATFORM_SCOPE:
        raise ContractError(
            f"platform_scope exceeds MAX_PLATFORM_SCOPE={MAX_PLATFORM_SCOPE}: "
            f"{len(seen)} unique platforms {seen}"
        )
    return tuple(sorted(seen))


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
    domain_hint: str | None = None
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


def _latest_change_effective_at(
    change_context: Mapping[str, object] | None,
) -> str | None:
    """The latest confirmed material Change time from the evidence
    change context (v3.6.4): keys are ``last_<type>_change_effective_at``
    (e.g. last_budget_change_effective_at) plus the generic
    ``change_effective_at`` — never assume a bare ``last_change_*`` key.
    """
    if not change_context:
        return None
    candidates = [
        value
        for key, value in change_context.items()
        if key == "change_effective_at"
        or (key.startswith("last_") and key.endswith("_change_effective_at"))
    ]
    timestamps = [str(value) for value in candidates if isinstance(value, str)]
    return max(timestamps) if timestamps else None


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

        The object is REUSABLE-BUT-RESET: begin() creates a NEW
        StateSession (fresh run_id + empty run-local dedupe set) and clears
        every run-local field from any previous run (current observations,
        persistence warnings, last verdict, platform scope, state
        snapshot), so a second run is a genuinely independent run.
        """
        self.request = request_text or ""
        self.session = StateSession(self.context)  # new run_id + empty dedupe
        self.store = StateStore(self.context)
        # EVERY scope entering the runtime is canonicalized here (explicit
        # and router-detected alike): registered-only, unique, sorted,
        # bounded by MAX_PLATFORM_SCOPE. Failures happen at the run
        # boundary, never later inside persistence.
        self.platform_scope = canonicalize_platform_scope(
            platform_scope or self.explicit_platform_scope
        )
        if not self.platform_scope and request_text:
            self.platform_scope = canonicalize_platform_scope(
                detect_platforms(request_text)
            )
        self.domain_hint = detect_domain(self.request)
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
        # Platform Scope Boundary: evidence must obey the run's scope. A
        # scoped run rejects out-of-scope observations BEFORE anything is
        # persisted or enters current context. An EMPTY run binds to its
        # first valid platform observation (from then on it is a
        # single-platform run and can never silently expand).
        if self.platform_scope:
            if platform not in self.platform_scope:
                raise ContractError(
                    f"observation_platform_outside_run_scope: platform "
                    f"{platform!r} is not in the run's platform scope "
                    f"{self.platform_scope}"
                )
        else:
            self.platform_scope = canonicalize_platform_scope((platform,))
            # Late-bound scope: the historical snapshot loaded at begin()
            # (state_access REQUIRED) was probed from an EMPTY scope and
            # may contain other platforms. Rebind it to the bound scope
            # BEFORE persisting the current observation, so historical and
            # current evidence share the same platform boundary.
            if self.state_access == StateAccess.REQUIRED and self._platform_state:
                self._platform_state = _platform_bounded_state(
                    self.session, self.platform_scope
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
        # Single-platform current observation is EXACT-platform only — a
        # Meta run never falls back to another platform's evidence (no
        # arbitrary "last" substitution). Cross-platform runs keep the
        # per-platform map; the scalar convenience is None.
        current_observation = None
        if len(self.platform_scope) == 1:
            current_observation = self._current_observations.get(self.platform_scope[0])
        return OperationalContext(
            request=self.request,
            workspace=self.workspace,
            platform_scope=self.platform_scope,
            state_context=self._platform_state,
            current_observation=current_observation,
            current_observations=dict(self._current_observations),
            domain_hint=self.domain_hint,
            hypotheses=hypotheses,
            safety=safety,
        )

    def evaluate_decision_intelligence(self) -> DecisionIntelligenceResult:
        """Run the native DI pipeline over this run's real evidence.

        The pipeline is assembled HERE, not by callers: raw evidence from
        current observations → signals → hypotheses → evaluation →
        ranking → convergence. The canonical safety context computed by
        the SAME resolvers used in ``record_decision()`` feeds both the
        signal layer and the evaluator — never optimistic defaults.
        """
        self._require_started()
        from appflow_ops.decision_intelligence import (
            SafetyContext,
            build_evidence,
            build_hypothesis_set,
            converge,
            detect_operational_domain,
            evaluate_hypotheses,
            rank_hypotheses,
        )
        from appflow_ops.decision_intelligence.result import from_convergence

        measurement_by_platform, maturity_by_platform = self._safety_states()
        measurement_state = self._aggregate_safety(
            measurement_by_platform, self.platform_scope
        )
        maturity_state = self._aggregate_safety(
            maturity_by_platform, self.platform_scope
        )
        operational_domain = detect_operational_domain(self.request)

        # Current evidence: same boundary as operational_context.
        per_platform: dict[str, dict[str, object]] = {}
        observed_platforms = self.platform_scope or tuple(self._current_observations)
        current_event_ids: set[str] = set()
        current_observed_at: dict[str, str] = {}
        historical_observed_at: dict[str, str] = {}
        for platform in observed_platforms:
            event = self._current_observations.get(platform)
            if event is None:
                continue
            facts = event.get("payload", {}).get("facts", {})
            per_platform[platform] = facts
            event_id = event.get("event_id")
            if isinstance(event_id, str):
                current_event_ids.add(event_id)
            observed = event.get("observed_at")
            if isinstance(observed, str):
                current_observed_at[platform] = observed

        # Historical evidence: for each platform pick the most recent
        # observation BEFORE the current one (same platform ⇒ comparable
        # metric family). Only the bounded state loaded at begin() is
        # used; absent history stays missing (never guessed).
        historical_by_platform: dict[str, dict[str, object]] = {}
        recent_changes: tuple[dict[str, object], ...] = ()
        recent_decisions: tuple[dict[str, object], ...] = ()
        recent_outcomes: tuple[dict[str, object], ...] = ()
        from appflow_ops.decision_intelligence.evidence import (
            observations_comparable,
        )

        by_platform = (self._platform_state or {}).get("by_platform") or {}
        for platform in observed_platforms:
            bucket = by_platform.get(platform) or {}
            observations = bucket.get("observations") or ()
            current_facts = per_platform.get(platform) or {}
            # Newest-comparable selection (v3.5.4): the newest observation
            # may be a different entity — keep walking the bounded list to
            # find the newest COMPARABLE baseline; incomparable records
            # never block an older comparable one.
            for event in observations:
                event_id = event.get("event_id")
                if event_id in current_event_ids:
                    continue
                facts = event.get("payload", {}).get("facts", {})
                if not facts:
                    continue
                if not observations_comparable(current_facts, facts):
                    continue
                historical_by_platform[platform] = facts
                observed = event.get("observed_at")
                if isinstance(observed, str):
                    historical_observed_at[platform] = observed
                break
            changes = bucket.get("changes") or ()
            if changes:
                recent_changes = tuple(changes) + recent_changes
            decisions = bucket.get("decisions") or ()
            if decisions:
                recent_decisions = tuple(decisions) + recent_decisions
            outcomes = bucket.get("outcomes") or ()
            if outcomes:
                recent_outcomes = tuple(outcomes) + recent_outcomes

        evidence = build_evidence(
            per_platform=per_platform,
            historical_by_platform=historical_by_platform,
            recent_changes=recent_changes,
            recent_decisions=recent_decisions,
            recent_outcomes=recent_outcomes,
            measurement_state=measurement_state,
            maturity_state=maturity_state,
            current_observed_at=current_observed_at,
            historical_observed_at=historical_observed_at,
        )
        specs = build_hypothesis_set(
            platform_scope=self.platform_scope, domain=operational_domain
        )
        evaluations = evaluate_hypotheses(
            specs,
            evidence,
            platform_scope=self.platform_scope,
            measurement_state=measurement_state,
            maturity_state=maturity_state,
            # v3.5.4: Safety follows evidence provenance — platform-bound
            # evaluations use THAT platform's measurement/maturity.
            measurement_by_platform=measurement_by_platform,
            maturity_by_platform=maturity_by_platform,
        )
        ranked = rank_hypotheses(evaluations)
        # v3.5.5: convergence consumes Safety resolved from the SELECTED
        # evaluation's scope — a platform-bound top uses that platform's
        # measurement/maturity; shared/run tops use the aggregate states.
        # Another platform's invalid state is a warning, never a global
        # veto.
        safety_context = SafetyContext(
            measurement_by_platform=measurement_by_platform,
            maturity_by_platform=maturity_by_platform,
            aggregate_measurement=measurement_state,
            aggregate_maturity=maturity_state,
        )
        # v3.6.0: action eligibility context — the selected evaluation's
        # facts (KPI/efficiency/sample) plus recent-change confounders, so
        # a scaling action is gated by real eligibility, not by the
        # diagnosis alone (constraint != permission to scale).
        # v3.6.1: eligibility follows the selected evaluation's
        # PROVENANCE — a platform-bound top only sees THAT platform's
        # facts and recent changes; another platform's change never
        # blocks this platform's scale (aggregate signals are only used
        # for shared/run-level tops).
        action_context: dict[str, object] = {}
        selected = ranked[0].evaluation if ranked else None
        if (
            selected is not None
            and selected.platform
            and selected.platform in per_platform
        ):
            action_context.update(per_platform[selected.platform])
            platform_signals = evidence.signals_by_platform.get(selected.platform, {})
            for key in ("recent_budget_change", "recent_bid_change"):
                if platform_signals.get(key):
                    action_context[key] = True
        else:
            for platform_facts in per_platform.values():
                action_context.update(platform_facts)
            for key in ("recent_budget_change", "recent_bid_change"):
                if evidence.signals.get(key):
                    action_context[key] = True
        convergence = converge(
            ranked,
            safety_context=safety_context,
            action_context=action_context or None,
            # v3.6.4: the decision window — last confirmed material
            # Change and the current observation time — gates action
            # READINESS (eligibility != readiness): a second material
            # action needs enough NEW evidence since the change.
            window_context=(
                {
                    "last_change_effective_at": _latest_change_effective_at(
                        evidence.change_context
                    ),
                    "current_observed_at": (
                        next(iter(current_observed_at.values()), None)
                        if current_observed_at
                        else None
                    ),
                }
                if evidence.change_context
                else None
            ),
        )
        from appflow_ops.decision_intelligence.calibration import (
            resolve_primary_kpi,
        )

        primary_kpi, _ = resolve_primary_kpi(action_context or {})
        return from_convergence(
            convergence=convergence,
            platform_scope=self.platform_scope,
            operational_domain=operational_domain,
            evaluations=evaluations,
            ranked=ranked,
            safety_context={
                "measurement_state": measurement_state,
                "maturity_state": maturity_state,
                "policy_state": self.policy_state,
                "permission_state": self.permission_state,
            },
            platform_warnings=self._platform_safety_warnings(
                ranked, measurement_by_platform, maturity_by_platform
            ),
            evidence=evidence,
            primary_kpi=primary_kpi,
        )

    def record_decision_from_intelligence(self) -> str | None:
        """Persist the DI recommendation through the existing safety path.

        The action ALWAYS comes from ``DecisionIntelligenceResult.
        recommended_action`` — callers cannot silently swap it (v3.5.2
        action integrity). Human overrides are explicit and attributable
        via ``record_decision_override()``. Returns ``None`` when the DI
        result carries no actionable recommendation or the safety
        validator rejects it.
        """
        result = self.evaluate_decision_intelligence()
        decision_class = result.recommended_action
        if decision_class is None:
            return None
        decision_class = _DI_ACTION_TO_DECISION.get(decision_class, decision_class)
        if decision_class not in DECISION_CLASSES:
            return None
        confidence = (
            "probable" if result.convergence_status == "converged" else "tentative"
        )
        # v3.5.5: attribution AND safety follow the SELECTED evaluation.
        # A platform-bound diagnosis persists with that platform and is
        # validated with that platform's measurement/maturity — another
        # platform's invalid state never vetoes it; a shared diagnosis
        # stays cross-platform with aggregate safety (conservative).
        from appflow_ops.decision_intelligence import (
            SafetyContext,
            resolve_evaluation_safety,
        )
        from appflow_ops.decision_intelligence.result import decision_attribution

        measurement_by_platform, maturity_by_platform = self._safety_states()
        measurement_state = self._aggregate_safety(
            measurement_by_platform, self.platform_scope
        )
        maturity_state = self._aggregate_safety(
            maturity_by_platform, self.platform_scope
        )
        platform, platform_scope = decision_attribution(
            result.selected_evaluation, self.platform_scope
        )
        resolved_measurement, resolved_maturity = resolve_evaluation_safety(
            result.selected_evaluation,
            SafetyContext(
                measurement_by_platform=measurement_by_platform,
                maturity_by_platform=maturity_by_platform,
                aggregate_measurement=measurement_state,
                aggregate_maturity=maturity_state,
            ),
        )
        return self.record_decision(
            decision_class=decision_class,
            reason=result.reason_summary,
            diagnosis_confidence=confidence,
            platform=platform,
            platform_scope=platform_scope,
            safety_measurement_state=resolved_measurement,
            safety_maturity_state=resolved_maturity,
        )

    def record_decision_override(
        self,
        *,
        action: str,
        reason: str,
        result: DecisionIntelligenceResult,
    ) -> str | None:
        """Explicit, attributable human override of a DI recommendation.

        Distinct semantics from ``record_decision_from_intelligence``:
        ``origin="operator_override"``, and the original DI action plus
        the override reason are persisted with the Decision — it never
        masquerades as a DI recommendation. Safety gates (measurement /
        maturity / policy / permission / Decision != Change) still apply.
        """
        decision_class = _DI_ACTION_TO_DECISION.get(action, action)
        if decision_class not in DECISION_CLASSES:
            return None
        original_action = result.recommended_action or "none"
        reason_text = f"operator override: {original_action} -> {action}; {reason}"
        return self.record_decision(
            decision_class=decision_class,
            reason=reason_text,
            origin="operator_override",
            evidence_refs=(),
            diagnosis_confidence="none",
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
        platform: str | None = None,
        platform_scope: tuple[str, ...] | None = None,
        safety_measurement_state: str | None = None,
        safety_maturity_state: str | None = None,
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

        Platform attribution is inherited from the run's platform scope,
        or overridden explicitly (v3.5.5: the DI path passes the
        SELECTED evaluation's attribution — a platform-bound diagnosis
        persists with that platform). ``safety_measurement_state`` /
        ``safety_maturity_state`` override the aggregate states for
        validation (v3.5.5: the DI path validates with the selected
        evaluation's resolved Safety — what was evaluated is what is
        validated).
        """
        self._require_started()
        measurement_by_platform, maturity_by_platform = self._safety_states()
        measurement_state = (
            safety_measurement_state
            if safety_measurement_state is not None
            else self._aggregate_safety(measurement_by_platform, self.platform_scope)
        )
        maturity_state = (
            safety_maturity_state
            if safety_maturity_state is not None
            else self._aggregate_safety(maturity_by_platform, self.platform_scope)
        )
        # The SAME canonical values used by the validator are persisted with
        # the Decision (What was validated must be what was persisted).
        verdict = validate_decision_action(
            decision_class=decision_class,
            reason=reason,
            measurement_state=measurement_state,
            maturity_state=maturity_state,
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
        if platform_scope is None and platform is None:
            resolved_platform, resolved_scope = self._decision_platform()
        else:
            resolved_platform, resolved_scope = platform, platform_scope or ()
            if (
                resolved_platform is not None
                and resolved_platform != "cross_platform"
                and self.platform_scope
                and resolved_platform not in self.platform_scope
            ):
                raise ContractError(
                    f"platform {resolved_platform!r} is outside the run's "
                    f"platform scope {self.platform_scope}"
                )
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
            measurement_state=measurement_state,
            maturity_state=maturity_state,
            platform=resolved_platform,
            platform_scope=resolved_scope,
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

        Attribution precedence: confirmed Change > Decision (an Outcome
        linked to an executed Meta Change answers "what happened after that
        Meta change", even when it also references a cross-platform
        Decision). A cross-platform Decision alone keeps its scope; refs
        with conflicting platforms are rejected rather than guessed.
        """
        self._require_started()
        change_platform: str | None = None
        decision_platform: str | None = None
        decision_scope: tuple[str, ...] = ()
        if change_id is not None:
            event = self.store.get_event(change_id)
            change_platform = event.get("platform")
            if change_platform == "cross_platform":
                change_platform = None  # legacy only; never newly written
        if decision_id is not None:
            event = self.store.get_event(decision_id)
            event_platform = event.get("platform")
            if event_platform == "cross_platform":
                scope = event.get("payload", {}).get("platform_scope", ())
                if isinstance(scope, (list, tuple)):
                    decision_scope = tuple(scope)
            else:
                decision_platform = event_platform
        if change_platform is not None and decision_platform is not None:
            if change_platform != decision_platform:
                raise ContractError(
                    "outcome refs disagree on platform "
                    f"({decision_platform!r} decision vs {change_platform!r} "
                    "change); pass platform explicitly"
                )
        # Precedence: a confirmed single-platform Change narrows the
        # Outcome (its cross-platform Decision scope is dropped — the
        # Outcome answers "what happened after that Meta change"); a
        # cross-platform Decision alone keeps its scope. Every step must
        # first pass scope compatibility: the Change platform must BELONG
        # to the Decision's scope, otherwise the attribution is
        # contradictory and rejected.
        derived = change_platform or decision_platform
        if decision_scope and change_platform and change_platform not in decision_scope:
            raise ContractError(
                f"change platform {change_platform!r} is outside the linked "
                f"decision's platform scope {decision_scope}"
            )
        if platform is not None and derived is not None and platform != derived:
            raise ContractError(
                f"outcome platform {platform!r} conflicts with derived "
                f"platform {derived!r} from its refs"
            )
        if platform is not None and decision_scope and platform != "cross_platform":
            raise ContractError(
                f"outcome platform {platform!r} conflicts with the derived "
                f"cross-platform scope {decision_scope}"
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
            or ("cross_platform" if decision_scope else None),
            platform_scope=decision_scope
            if derived is None and (platform is None or platform == "cross_platform")
            else (),
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

        Freshness rule (absent ≠ unknown): if the CURRENT observation
        contains the field, its canonical value wins — including an
        explicit "unknown", which is itself new safety evidence and MUST
        override stale historical certainty. History is only searched when
        the current observation is MISSING the field. History is read
        platform-scoped — a Meta request can never inherit TikTok's state.
        """
        measurement: dict[str, str] = {}
        maturity: dict[str, str] = {}
        for platform, event in self._current_observations.items():
            facts = event.get("payload", {}).get("facts", {})
            value = facts.get("measurement_state")
            if isinstance(value, str):
                measurement[platform] = value  # explicit unknown included
            value = facts.get("maturity_state")
            if isinstance(value, str):
                maturity[platform] = value
        for platform in self.platform_scope:
            if platform not in measurement:
                for event in self.store.get_recent_observations(
                    limit=5, platform=platform
                ):
                    facts = event.get("payload", {}).get("facts", {})
                    value = facts.get("measurement_state")
                    if isinstance(value, str):
                        measurement[platform] = value
                        break
            if platform not in maturity:
                for event in self.store.get_recent_observations(
                    limit=5, platform=platform
                ):
                    facts = event.get("payload", {}).get("facts", {})
                    value = facts.get("maturity_state")
                    if isinstance(value, str):
                        maturity[platform] = value
                        break
        return measurement, maturity

    @staticmethod
    def _aggregate_safety(states: Mapping[str, str], scope: tuple[str, ...]) -> str:
        """Conservative aggregation over the FULL scope: a platform with
        no safety evidence is treated as "unknown" (never silently
        ignored — stable + missing must NOT aggregate to stable). Never an
        average, never a flat scalar that hides platform differences.
        Measurement vocabulary: any invalid → invalid; else unknown; else
        stable. Maturity vocabulary: any insufficient → insufficient;
        else unknown; else sufficient.
        """
        relevant = [states.get(platform, "unknown") for platform in scope]
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

    @staticmethod
    def _platform_safety_warnings(
        ranked: tuple[RankedHypothesis, ...],
        measurement_by_platform: Mapping[str, str],
        maturity_by_platform: Mapping[str, str],
    ) -> dict[str, tuple[str, ...]]:
        """Safety warnings per NON-selected platform (v3.5.5): e.g.
        {"meta": ("measurement_invalid",)} when Meta's measurement is
        invalid but the selected diagnosis is Google's. The selected
        platform's own safety is expressed by ``safety_block``, not
        duplicated here. A warning is never a veto on an independent
        diagnosis — it only says "this platform cannot be judged yet".
        """
        top = ranked[0].evaluation if ranked else None
        selected_platform = top.platform if top is not None else None
        warnings: dict[str, tuple[str, ...]] = {}
        for platform in sorted(
            set(measurement_by_platform) | set(maturity_by_platform)
        ):
            if platform == selected_platform:
                continue
            items: list[str] = []
            if measurement_by_platform.get(platform) == "invalid":
                items.append("measurement_invalid")
            if maturity_by_platform.get(platform) == "insufficient":
                items.append("maturity_insufficient")
            if items:
                warnings[platform] = tuple(items)
        return warnings

    def _decision_platform(self) -> tuple[str | None, tuple[str, ...]]:
        """Platform attribution inherited from the run's scope. An empty
        scope run has NO platform (the first observation binds the scope,
        so there is no observation-only inference fallback — attribution,
        safety, retrieval and context all share the same boundary)."""
        if len(self.platform_scope) == 1:
            return self.platform_scope[0], ()
        if len(self.platform_scope) > 1:
            return "cross_platform", self.platform_scope
        return None, ()

    def _resolve_policy_state(self, explicit: str | None) -> str:
        """Real policy context only: explicit argument or a workspace-level
        policy file; never a hardcoded default. Malformed explicit values
        FAIL CLOSED (ContractError) — a typo must never silently degrade to
        "none" and disable the policy gate."""
        from appflow_ops.evals.safety import POLICY_STATES

        if explicit is not None:
            if explicit not in POLICY_STATES:
                raise ContractError(
                    f"invalid policy_state {explicit!r}; "
                    f"expected one of {POLICY_STATES}"
                )
            return explicit
        try:
            from .io import _load

            for name in ("policy.yaml", "ads-policy.yaml"):
                path = self.workspace.root / name
                if path.is_file() and not path.is_symlink():
                    document = _load(path)
                    if isinstance(document, dict):
                        value = document.get("policy_state")
                        if isinstance(value, str):
                            if value not in POLICY_STATES:
                                raise ContractError(
                                    f"invalid policy_state {value!r} in "
                                    f"{name}; expected one of {POLICY_STATES}"
                                )
                            return value
        except ContractError:
            raise
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
