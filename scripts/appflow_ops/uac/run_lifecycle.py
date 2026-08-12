"""Runtime-enforced State Lifecycle (v3.3.2).

The canonical integration point that turns the State Lifecycle from a
prompt contract into something the runtime itself executes: one entry per
run, request classification decides whether state is loaded at all, and all
writes go through the same workspace-bound session.

    runtime = AppFlowRuntime(workspace)
    runtime.begin_run(request_text="现在呢？")
    if runtime.state_context() is not None:
        context = runtime.state_context()   # bounded, never the full history
    runtime.record_decision(...)            # after an operational decision forms
    runtime.finish_run()

Rules enforced here (docs/account-state.md):

- Direct informational questions ("CTR 是什么？") never read or write state.
- Follow-up / diagnosis / decision requests load bounded state automatically.
- A recommendation alone never records a Change; outcomes need later evidence.
- No global registry, no cross-workspace access: everything is bound to the
  workspace passed to the constructor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .account_state import RunContext
from .state_runtime import StateSession
from .workspace import Workspace

# ── request classification (lightweight, no LLM classifier) ──────────────

_DIRECT_INFORMATIONAL_RE = re.compile(
    r"(什么|是什么意思|是什么|怎么算|什么意思|解释|define|meaning|what is)",
    re.IGNORECASE,
)
_DIAGNOSIS_RE = re.compile(
    r"(跑不动|掉量|掉了|没量|突然|异常|为什么|涨了|下降|不行了|为什么有点击|没安装|没转化)",
    re.IGNORECASE,
)
_FOLLOW_UP_RE = re.compile(
    r"(现在呢|现在怎么样|昨天那个|昨天那|上次|之前那个|上次那个|又不行|还是没量|还能跑吗|还能不能跑|要不要继续调|那这个|看看现在)",
    re.IGNORECASE,
)
_DECISION_REQUEST_RE = re.compile(
    r"(该不该|要不要|还是调|还是停|还是开|先处理什么|该调|该停|该开|重新开|降还是|加还是|该继续等|继续等还是)",
    re.IGNORECASE,
)

# Explicit non-operational intent: these never unlock business state even
# when they share vocabulary with operational phrasing ("昨天" + "新闻",
# "解释" + "给甲方写").
_NON_OPERATIONAL_RE = re.compile(
    r"(新闻|行业新闻|翻译|translate|素材brief|创意brief|brief|给甲方|甲方消息|客户消息|写.*给甲方)",
    re.IGNORECASE,
)


class RequestIntent:
    """Semantic class of one user request, derived by lightweight rules."""

    DIRECT_INFORMATIONAL = "direct_informational"
    OPERATIONAL_DIAGNOSIS = "operational_diagnosis"
    FOLLOW_UP = "follow_up"
    DECISION_REQUEST = "decision_request"


RequestIntentValue = str


class StateAccess:
    """Whether business state may be loaded for this request.

    Router / skill layer understands the request category and may pass
    ``state_access`` explicitly to the runtime; the runtime enforces it.
    """

    REQUIRED = "required"
    NOT_NEEDED = "not_needed"
    UNCERTAIN = "uncertain"


StateAccessValue = str


def classify_request(text: str) -> str:
    """Classify one natural-language request into an intent label.

    Order matters: an explicit meaning question wins over diagnosis words
    ("CPA 是什么意思" is informational even though it contains 什么); an
    explicit follow-up reference wins over generic diagnosis words.
    """

    if _FOLLOW_UP_RE.search(text):
        return RequestIntent.FOLLOW_UP
    if _DIRECT_INFORMATIONAL_RE.search(text) and not _DIAGNOSIS_RE.search(text):
        return RequestIntent.DIRECT_INFORMATIONAL
    if _DIAGNOSIS_RE.search(text):
        return RequestIntent.OPERATIONAL_DIAGNOSIS
    if _DECISION_REQUEST_RE.search(text):
        return RequestIntent.DECISION_REQUEST
    return RequestIntent.OPERATIONAL_DIAGNOSIS


def classify_state_access(text: str) -> str:
    """Decide state access with a safe default: UNKNOWN never unlocks
    production business state (Part 4 / 6 of the v3.3.3 contract).

    Non-operational intents (news, translation, brief writing, client
    message drafting, terminology) are detected first so vocabulary overlap
    ("昨天" + "新闻") cannot leak state access.
    """

    if _NON_OPERATIONAL_RE.search(text):
        return StateAccess.NOT_NEEDED
    if _DIRECT_INFORMATIONAL_RE.search(text) and not _DIAGNOSIS_RE.search(text):
        return StateAccess.NOT_NEEDED
    if (
        _FOLLOW_UP_RE.search(text)
        or _DIAGNOSIS_RE.search(text)
        or _DECISION_REQUEST_RE.search(text)
    ):
        return StateAccess.REQUIRED
    return StateAccess.UNCERTAIN


def should_load_state(state_access: str) -> bool:
    """Only an explicitly required access loads business state."""
    return state_access == StateAccess.REQUIRED


# ── bounded state context ────────────────────────────────────────────────

_RECENT_LIMIT = 5


def build_state_context(session: StateSession) -> dict[str, Any]:
    """One bounded, stable StateContext for reasoning (never the full log)."""

    session.store.ensure_initialized()
    current = session.store.current_state()
    observations = session.store.get_recent_observations(limit=_RECENT_LIMIT)
    changes = session.store.get_recent_changes(limit=_RECENT_LIMIT)
    decisions = session.store.get_recent_decisions(limit=_RECENT_LIMIT)
    outcomes = session.store.get_recent_outcomes(limit=_RECENT_LIMIT)
    return {
        "workspace_id": session.context.workspace_id,
        "client_scope": session.context.client_scope,
        "project_scope": session.context.project_scope,
        "current_state": current,
        "last_observation": observations[0] if observations else None,
        "last_change": changes[0] if changes else None,
        "last_decision": decisions[0] if decisions else None,
        "last_outcome": outcomes[0] if outcomes else None,
        "pending_review": current.get("pending_review"),
        "recent": {
            "observations": observations,
            "changes": changes,
            "decisions": decisions,
            "outcomes": outcomes,
        },
    }


# ── runtime ──────────────────────────────────────────────────────────────


class AppFlowRuntime:
    """One run's workspace-bound state lifecycle entry point."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.context = RunContext.from_workspace(workspace)
        self.session = StateSession(self.context)
        self.intent: str | None = None
        self.state_access: str | None = None
        self._state_context: dict[str, Any] | None = None
        self._started = False

    def begin_run(
        self,
        request_text: str | None = None,
        *,
        state_access: str | None = None,
    ) -> AppFlowRuntime:
        """Start one run: classify the request, then conditionally load state.

        Loading state never writes business events; a stale/missing derived
        current-state file may be rebuilt internally, which is store
        maintenance, not a business write.

        ``request_text=None`` marks a deterministic tool path (CLI
        analyze/decide): no classification, no state load — the tool has its
        own input files and only records outcomes.

        ``state_access`` lets the Router / skill layer declare intent
        explicitly (required / not_needed / uncertain); the runtime enforces
        it instead of guessing from a few words. Unknown requests default to
        NO state access.
        """

        if state_access is not None:
            self.state_access = state_access
        elif request_text is None:
            self.state_access = StateAccess.NOT_NEEDED
        else:
            self.state_access = classify_state_access(request_text)
        self.intent = None if request_text is None else classify_request(request_text)
        if should_load_state(self.state_access):
            self._state_context = build_state_context(self.session)
        self._started = True
        return self

    @property
    def state_loaded(self) -> bool:
        """True when the run loaded the workspace state context."""
        return self._state_context is not None

    def state_context(self) -> dict[str, Any] | None:
        """Bounded context for reasoning; None for direct informational runs."""
        return self._state_context

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
        self._require_started()
        return self.session.record_observation(
            observed_at=observed_at,
            platform=platform,
            facts=facts,
            source_type=source_type,
            evidence_status=evidence_status,
            source_digest=source_digest,
            refs=refs,
        )

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
        self._require_started()
        return self.session.record_decision(
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
            source_digest=source_digest,
        )

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
        self._require_started()
        return self.session.record_confirmed_change(
            change_type=change_type,
            direction=direction,
            magnitude=magnitude,
            source=source,
            origin=origin,
            evidence_status=evidence_status,
            effective_at=effective_at,
            source_digest=source_digest,
            refs=refs,
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
        source_digest: str | None = None,
    ) -> str | None:
        self._require_started()
        return self.session.record_outcome(
            outcome_class=outcome_class,
            decision_id=decision_id,
            change_id=change_id,
            observation_ids=observation_ids,
            source_type=source_type,
            evidence_status=evidence_status,
            source_digest=source_digest,
        )

    def finish_run(self) -> None:
        """Close the run. No global state is touched; the session is local."""
        self._started = False
        self._state_context = None

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("begin_run() must be called before record_*()")
