"""Runtime safety validator for operational decisions (v3.4.1).

Reuses the canonical safety vocabulary from
``appflow_ops.evals.safety`` (Measurement / Maturity / Policy / Permission)
— the runtime never defines its own strings. It classifies a CANDIDATE
decision before persistence:

    candidate decision
        ↓
    SafetyDecisionValidator.validate(...)
        ↓
    allowed | constrained | rejected   (+ reason_code, allowed_next_actions)
        ↓
    allowed → persist
    rejected → never
    constrained without validated candidate → never

This is NOT a new safety model: it only applies the existing four gates to
concrete decision classes. No numeric rewriting happens — when the runtime
cannot safely clamp, it rejects and tells the Agent which actions remain.
Unknown structured enum values (e.g. malformed ``diagnosis_confidence``)
fail closed with a ContractError before safety evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from appflow_ops.evals.safety import (
    MATURITY_STATES,
    MEASUREMENT_STATES,
    PERMISSION_STATES,
    POLICY_STATES,
)
from appflow_ops.uac.types import ContractError

SAFETY_OUTCOMES = ("allowed", "constrained", "rejected")

# Structured diagnosis confidence for candidate decisions. Confirmed
# claims depend on trustworthy measurement/maturity; tentative hypotheses
# always stay allowed.
DIAGNOSIS_CONFIDENCE = ("none", "tentative", "probable", "confirmed")

# Decision classes that are numeric/aggressive actions.
NUMERIC_ACTIONS = frozenset({"increase", "decrease"})
AGGRESSIVE_ACTIONS = frozenset({"increase", "decrease", "pause"})
# Actions always available even under read_only permission.
READ_ONLY_ALLOWED_ACTIONS = frozenset(
    {"keep", "wait", "observe", "investigate", "retest"}
)

# Execution-claim vocabulary: a decision phrased as already executed.
# Execution-claim detection is STRUCTURED-FIRST (execution_status is the
# primary signal; this natural-language pass is conservative defense-in-
# depth only). Patterns require an action verb plus an operational object
# or a strong execution marker — bare words like "changed" / "updated" /
# "已改" are deliberately NOT matched, so harmless performance language
# ("CTR changed after the audience expanded") stays allowed.
EXECUTION_CLAIM_PATTERNS = (
    # Chinese: strong completed-action markers (execution claims)
    r"已暂停",
    r"已经暂停",
    r"已执行",
    r"已经执行",
    r"已应用",
    r"已经应用",
    r"(?:我们|已(?:经)?)调整(?:了)?(?:预算|出价|tCPA|素材|广告|campaign)",
    r"已(?:经)?改(?:了)?(?:预算|出价|素材|广告|campaign)",
    r"(?:预算|出价|tCPA)已(?:经)?(?:从.*?)?(?:调|改|降|升)(?:到|为)",
    # English: we-claims and object-scoped claims
    r"\bwe (?:paused|changed|updated|executed|applied)\b",
    r"\b(?:was|were|has been|have been) (?:paused|applied|executed)\b",
    r"\bchanged the (?:bid|budget|target|tCPA|campaign|ad group|adset)\b",
    r"\bupdated the (?:bid|budget|target|tCPA|campaign|ad group|adset)\b",
    # English: strong single execution markers kept
    r"\bexecuted\b",
    r"\bapplied\b",
)

_EXECUTION_CLAIM_RE = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in EXECUTION_CLAIM_PATTERNS
)


def reason_contains_execution_claim(reason: str) -> bool:
    """Conservative natural-language defense-in-depth for execution claims.
    Structured ``execution_status`` is the primary signal; this pass only
    flags clear action-verb + operational-object phrasings."""
    return any(pattern.search(reason) for pattern in _EXECUTION_CLAIM_RE)


@dataclass(frozen=True)
class SafetyVerdict:
    """Outcome of validating one candidate decision."""

    outcome: str  # allowed | constrained | rejected
    reason_code: str | None = None
    allowed_next_actions: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        """Backward-compatible alias of ``is_allowed``: only ``allowed``
        outcomes may persist — constrained without a rewritten candidate
        never persists."""
        return self.outcome == "allowed"

    @property
    def is_allowed(self) -> bool:
        return self.outcome == "allowed"


def validate_decision_action(
    *,
    decision_class: str,
    reason: str,
    measurement_state: str = "unknown",
    maturity_state: str = "unknown",
    policy_state: str = "none",
    permission_state: str = "read_only",
    execution_status: str | None = None,
    diagnosis_confidence: str = "none",
) -> SafetyVerdict:
    """Classify one candidate decision against the shared gates.

    Order: Decision≠Change (execution claim is ALWAYS rejected in a
    Decision, regardless of permission) → permission → diagnostic claim →
    measurement → maturity → policy. Returns rejected with a short
    reason_code and the actions the Agent may still converge to; never
    rewrites the candidate.
    """

    # Structured safety enums fail closed: canonical "unknown"/"none" are
    # valid states, but a malformed explicit value is NEVER silently
    # converted to a less restrictive state (e.g. a typo'd policy must not
    # become "none" and disable the gate). Derivation of states belongs to
    # the runtime resolvers, not to silent normalization here.
    if measurement_state not in MEASUREMENT_STATES:
        raise ContractError(
            f"invalid measurement_state {measurement_state!r}; "
            f"expected one of {MEASUREMENT_STATES}"
        )
    if maturity_state not in MATURITY_STATES:
        raise ContractError(
            f"invalid maturity_state {maturity_state!r}; "
            f"expected one of {MATURITY_STATES}"
        )
    if policy_state not in POLICY_STATES:
        raise ContractError(
            f"invalid policy_state {policy_state!r}; expected one of {POLICY_STATES}"
        )
    if permission_state not in PERMISSION_STATES:
        raise ContractError(
            f"invalid permission_state {permission_state!r}; "
            f"expected one of {PERMISSION_STATES}"
        )
    if diagnosis_confidence not in DIAGNOSIS_CONFIDENCE:
        # Fail closed: a malformed enum must never be silently treated as
        # "none" (which would let a claim dodge its safety gate).
        raise ContractError(
            f"invalid diagnosis_confidence {diagnosis_confidence!r}; "
            f"expected one of {DIAGNOSIS_CONFIDENCE}"
        )

    # ── Decision != Change: execution claims never belong in a Decision ──
    # Regardless of permission level (even full), a Decision that states
    # "已暂停/executed/applied/..." must be rejected: execution belongs in a
    # Change, and a Decision is always a recommendation/conclusion.
    execution_claim = execution_status is not None or reason_contains_execution_claim(
        reason
    )
    if execution_claim:
        return SafetyVerdict(
            outcome="rejected",
            reason_code="execution_claim_in_decision",
            allowed_next_actions=(
                "persist_recommendation_as_decision",
                "persist_confirmed_execution_as_change",
            ),
        )

    # ── permission gates ─────────────────────────────────────────────────
    if (
        permission_state == "read_only"
        and decision_class not in READ_ONLY_ALLOWED_ACTIONS
    ):
        return SafetyVerdict(
            outcome="rejected",
            reason_code="permission_read_only",
            allowed_next_actions=tuple(sorted(READ_ONLY_ALLOWED_ACTIONS)),
        )

    # ── diagnostic claim gates ───────────────────────────────────────────
    # Safety applies to confidence-bearing diagnostic claims as well as to
    # actions: a "confirmed" diagnosis depends on trustworthy measurement
    # and sufficient sample maturity.
    if (
        diagnosis_confidence in {"probable", "confirmed"}
        and measurement_state == "invalid"
    ):
        return SafetyVerdict(
            outcome="rejected",
            reason_code="measurement_invalid_diagnosis",
            allowed_next_actions=(
                "investigate_measurement",
                "observe",
                "diagnose_tentatively",
            ),
        )
    if diagnosis_confidence == "confirmed" and maturity_state == "insufficient":
        return SafetyVerdict(
            outcome="rejected",
            reason_code="maturity_insufficient_diagnosis",
            allowed_next_actions=("wait", "investigate", "diagnose_tentatively"),
        )

    # ── measurement gate (actions) ───────────────────────────────────────
    if measurement_state == "invalid" and decision_class in NUMERIC_ACTIONS:
        return SafetyVerdict(
            outcome="rejected",
            reason_code="measurement_invalid",
            allowed_next_actions=("observe", "investigate", "wait"),
        )

    # ── maturity gate (actions) ──────────────────────────────────────────
    if maturity_state == "insufficient" and decision_class in AGGRESSIVE_ACTIONS:
        return SafetyVerdict(
            outcome="rejected",
            reason_code="maturity_insufficient",
            allowed_next_actions=("observe", "investigate", "wait", "keep"),
        )

    # ── policy gate ──────────────────────────────────────────────────────
    if policy_state == "forbid_numeric" and decision_class in NUMERIC_ACTIONS:
        return SafetyVerdict(
            outcome="rejected",
            reason_code="policy_forbid_numeric",
            allowed_next_actions=("investigate", "observe", "wait"),
        )
    if policy_state == "cap_20pct" and decision_class in NUMERIC_ACTIONS:
        # No numeric rewriting exists; without a validated compliant
        # candidate the runtime must NOT persist the original candidate.
        return SafetyVerdict(
            outcome="constrained",
            reason_code="policy_cap_20pct",
            allowed_next_actions=("re_decide_within_cap", "investigate", "observe"),
        )
    if policy_state == "staged_required" and decision_class in NUMERIC_ACTIONS:
        return SafetyVerdict(
            outcome="constrained",
            reason_code="policy_staged_required",
            allowed_next_actions=("re_decide_staged", "investigate", "observe"),
        )

    return SafetyVerdict(outcome="allowed")
