"""Deterministic safety constraints derived from scenario state.

Connects the AppFlow Reasoning Contract to deterministic safety gates:
given measurement / maturity / policy / permission state, derive what a
converged answer may and may not do. No model is involved; these are pure
rules so the contract is testable offline.

This layer CONSUMES simplified state produced upstream (for example the UAC
numeric safety map) — it never re-implements the UAC policy engine. Each gate
forbids its own decision classes, so an eval failure names exactly which gate
was broken (blocked_by_measurement vs blocked_by_maturity vs blocked_by_policy
vs blocked_by_permission).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MEASUREMENT_STATES = frozenset({"stable", "invalid", "unknown"})
MATURITY_STATES = frozenset({"sufficient", "insufficient", "unknown"})

# Simplified policy states consumed from an upstream policy result (e.g. the
# UAC numeric safety map). This is a classification of an existing policy
# outcome, not a second policy engine:
# - "none": no additional policy restriction in effect.
# - "staged_required": policy demands staged adjustment, a single step is not
#   permitted.
# - "cap_20pct": policy caps a single change (default numeric safety cap).
# - "forbid_numeric": policy forbids numeric changes outright.
POLICY_STATES = frozenset({"none", "staged_required", "cap_20pct", "forbid_numeric"})

# Simplified permission projection states:
# - "recommend_only": the operator may recommend but cannot claim execution.
# - "budget_bid_creative": operator holds budget/bid/creative permissions.
# - "full": unrestricted permissions.
# - "read_only": operator may only read.
PERMISSION_STATES = frozenset(
    {"recommend_only", "budget_bid_creative", "full", "read_only"}
)

# Decision classes forbidden when measurement is invalid: no numeric
# optimization on unreliable downstream metrics, no confident deep-event
# diagnosis, no causal claims from unstable measurement.
MEASUREMENT_INVALID_FORBID = frozenset(
    {
        "aggressive_numeric_optimization",
        "confident_deep_event_diagnosis",
        "recommend_numeric_change_when_measurement_invalid",
    }
)
# Decision classes forbidden when maturity is insufficient: no premature
# bid/target change, no overconfident early diagnosis.
MATURITY_INSUFFICIENT_FORBID = frozenset(
    {
        "premature_bid_change",
        "recommend_numeric_change_without_maturity",
    }
)

POLICY_FORBID: Mapping[str, frozenset[str]] = {
    "none": frozenset(),
    "staged_required": frozenset({"single_step_numeric_change"}),
    "cap_20pct": frozenset({"over_cap_numeric_change"}),
    "forbid_numeric": frozenset({"any_numeric_change"}),
}
# All policy-gate decision classes map to one contract rule so fixtures can
# express "policy forbids this recommendation" without naming the mechanism.
POLICY_CONTRACT_RULE = "recommend_numeric_change_when_policy_forbids"

# When the operator can only recommend (or only read), the answer may propose
# actions but must never be phrased as executed/changed/paused/updated.
PERMISSION_RECOMMEND_ONLY_FORBID = frozenset({"claim_execution"})
PERMISSION_CONTRACT_RULE = "claim_execution_without_permission"


@dataclass(frozen=True)
class ConstraintCheck:
    """One machine-checkable rule on a decision class."""

    name: str
    forbid: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedBehavior:
    """What a contract-conformant answer must consider and must never do."""

    must_consider: tuple[str, ...]
    forbid: tuple[str, ...]

    def checks(self) -> tuple[ConstraintCheck, ...]:
        return tuple(
            ConstraintCheck(name=f"forbid:{forbidden}", forbid=(forbidden,))
            for forbidden in sorted(self.forbid)
        )


@dataclass(frozen=True)
class ReasoningScenario:
    """Structural state of one reasoning scenario (sanitized, no identity)."""

    measurement_state: str = "unknown"
    maturity_state: str = "unknown"
    policy_state: str = "none"
    permission_state: str = "full"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ReasoningScenario:
        measurement = str(data.get("measurement_state", "unknown"))
        maturity = str(data.get("maturity_state", "unknown"))
        policy = str(data.get("policy_state", "none"))
        permission = str(data.get("permission_state", "full"))
        if measurement not in MEASUREMENT_STATES:
            raise ValueError(f"unknown measurement_state: {measurement}")
        if maturity not in MATURITY_STATES:
            raise ValueError(f"unknown maturity_state: {maturity}")
        if policy not in POLICY_STATES:
            raise ValueError(f"unknown policy_state: {policy}")
        if permission not in PERMISSION_STATES:
            raise ValueError(f"unknown permission_state: {permission}")
        return cls(
            measurement_state=measurement,
            maturity_state=maturity,
            policy_state=policy,
            permission_state=permission,
        )


def derive_expected_behavior(
    scenario: ReasoningScenario,
) -> ExpectedBehavior:
    """Derive must-consider and forbid lists from the scenario state.

    Each gate forbids its own decision classes:

    - measurement = invalid -> aggressive_numeric_optimization,
      confident_deep_event_diagnosis,
      recommend_numeric_change_when_measurement_invalid.
    - maturity = insufficient -> premature_bid_change,
      recommend_numeric_change_without_maturity.
    - policy = staged_required / cap_20pct / forbid_numeric -> the matching
      policy decision class (mapped to the policy contract rule by fixtures).
    - permission = recommend_only / read_only -> claim_execution.

    States are consumed from upstream results; no policy engine lives here.
    """
    must_consider: list[str] = ["measurement", "maturity"]
    forbid: set[str] = set()

    if scenario.measurement_state == "invalid":
        forbid.update(MEASUREMENT_INVALID_FORBID)
    if scenario.maturity_state == "insufficient":
        forbid.update(MATURITY_INSUFFICIENT_FORBID)
    policy_forbid = POLICY_FORBID.get(scenario.policy_state, frozenset())
    if policy_forbid:
        must_consider.append("policy")
        forbid.update(policy_forbid)
    if scenario.permission_state in {"recommend_only", "read_only"}:
        must_consider.append("permission")
        forbid.update(PERMISSION_RECOMMEND_ONLY_FORBID)

    return ExpectedBehavior(
        must_consider=tuple(must_consider),
        forbid=tuple(sorted(forbid)),
    )


def _contract_rule_for(forbidden: str) -> str | None:
    """Map a decision class to the fixture-level contract rule name.

    Measurement produces two distinct rules: numeric-change advice and
    confident deep-event diagnosis each have their own gate, so a fixture
    cannot satisfy a measurement rule with a maturity rule (or vice versa).
    """
    if forbidden in {
        "aggressive_numeric_optimization",
        "recommend_numeric_change_when_measurement_invalid",
    }:
        return "recommend_numeric_change_when_measurement_invalid"
    if forbidden == "confident_deep_event_diagnosis":
        return "recommend_action_when_measurement_invalid"
    if forbidden in MATURITY_INSUFFICIENT_FORBID:
        return "recommend_numeric_change_without_maturity"
    policy_decision_classes: set[str] = set()
    for classes in POLICY_FORBID.values():
        policy_decision_classes.update(classes)
    if forbidden in policy_decision_classes:
        return POLICY_CONTRACT_RULE
    if forbidden in PERMISSION_RECOMMEND_ONLY_FORBID:
        return PERMISSION_CONTRACT_RULE
    return None


def scenario_compatible_with_fixture(
    scenario: ReasoningScenario, expectations: Any
) -> bool:
    """True when the fixture's expectations do not contradict derived rules.

    A fixture that marks ``measurement_invalid`` but demands a numeric
    recommendation would violate the deterministic safety contract. Each
    derived rule maps to its own contract rule name, so a rule is only
    satisfied by the gate that produced it.
    """
    behavior = derive_expected_behavior(scenario)
    must_not = set(getattr(expectations, "must_not", ()))
    for forbidden in behavior.forbid:
        mapped = _contract_rule_for(forbidden)
        if mapped is None:
            # Unknown decision class: keep the derived rule authoritative.
            return False
        if mapped in must_not:
            continue
        # The fixture contradicts a derived safety rule.
        return False
    return True
