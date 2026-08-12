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
    persist Decision (allowed/constrained only)

This is NOT a new safety model: it only applies the existing four gates to
concrete decision classes. No numeric rewriting happens — when the runtime
cannot safely clamp, it rejects and tells the Agent which actions remain.
"""

from __future__ import annotations

from dataclasses import dataclass

from appflow_ops.evals.safety import (
    MATURITY_STATES,
    MEASUREMENT_STATES,
    PERMISSION_STATES,
    POLICY_STATES,
)

SAFETY_OUTCOMES = ("allowed", "constrained", "rejected")

# Decision classes that are numeric/aggressive actions.
NUMERIC_ACTIONS = frozenset({"increase", "decrease"})
AGGRESSIVE_ACTIONS = frozenset({"increase", "decrease", "pause"})
# Actions always available even under read_only permission.
READ_ONLY_ALLOWED_ACTIONS = frozenset(
    {"keep", "wait", "observe", "investigate", "retest"}
)

# Execution-claim vocabulary: a decision phrased as already executed.
EXECUTION_CLAIM_WORDS = (
    "已暂停",
    "已执行",
    "已调整",
    "已应用",
    "已改",
    "已更新",
    "paused",
    "executed",
    "applied",
    "updated",
    "changed",
)


@dataclass(frozen=True)
class SafetyVerdict:
    """Outcome of validating one candidate decision."""

    outcome: str  # allowed | constrained | rejected
    reason_code: str | None = None
    allowed_next_actions: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.outcome in ("allowed", "constrained")


def reason_contains_execution_claim(reason: str) -> bool:
    lowered = reason.lower()
    return any(word in lowered for word in EXECUTION_CLAIM_WORDS)


def validate_decision_action(
    *,
    decision_class: str,
    reason: str,
    measurement_state: str = "unknown",
    maturity_state: str = "unknown",
    policy_state: str = "none",
    permission_state: str = "read_only",
    execution_status: str | None = None,
) -> SafetyVerdict:
    """Classify one candidate decision against the four shared gates.

    Order: permission → execution claim → measurement → maturity → policy.
    Returns rejected with a short reason_code and the actions the Agent may
    still converge to; never rewrites the candidate.
    """

    if measurement_state not in MEASUREMENT_STATES:
        measurement_state = "unknown"
    if maturity_state not in MATURITY_STATES:
        maturity_state = "unknown"
    if policy_state not in POLICY_STATES:
        policy_state = "none"
    if permission_state not in PERMISSION_STATES:
        permission_state = "read_only"

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
    execution_claim = execution_status is not None or reason_contains_execution_claim(
        reason
    )
    if execution_claim and permission_state not in {"full", "budget_bid_creative"}:
        return SafetyVerdict(
            outcome="rejected",
            reason_code="permission_recommend_only"
            if permission_state == "recommend_only"
            else "permission_read_only",
            allowed_next_actions=("investigate", "observe"),
        )
    if (
        execution_claim
        and execution_status is not None
        and permission_state
        in {
            "full",
            "budget_bid_creative",
        }
    ):
        # Execution claim allowed only with permission AND (per the
        # Decision != Change contract) it must be recorded as a Change, not
        # claimed inside a Decision. A decision is a recommendation.
        return SafetyVerdict(
            outcome="rejected",
            reason_code="execution_claim_in_decision",
            allowed_next_actions=("record_confirmed_change",),
        )

    # ── measurement gate ─────────────────────────────────────────────────
    if measurement_state == "invalid" and decision_class in NUMERIC_ACTIONS:
        return SafetyVerdict(
            outcome="rejected",
            reason_code="measurement_invalid",
            allowed_next_actions=("observe", "investigate", "wait"),
        )

    # ── maturity gate ────────────────────────────────────────────────────
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
        # No numeric rewriting exists: the candidate is accepted only as a
        # constrained recommendation with the cap recorded, never silently
        # clamped.
        return SafetyVerdict(
            outcome="constrained",
            reason_code="policy_cap_20pct",
            allowed_next_actions=("investigate", "observe"),
        )
    if policy_state == "staged_required" and decision_class in NUMERIC_ACTIONS:
        return SafetyVerdict(
            outcome="constrained",
            reason_code="policy_staged_required",
            allowed_next_actions=("investigate", "observe"),
        )

    return SafetyVerdict(outcome="allowed")
