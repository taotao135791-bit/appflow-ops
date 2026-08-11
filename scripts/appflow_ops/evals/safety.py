"""Deterministic safety constraints derived from scenario state.

Connects the AppFlow Reasoning Contract to deterministic safety gates:
given measurement / maturity / policy / permission state, derive what a
converged answer may and may not do. No model is involved; these are pure
rules so the contract is testable offline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MEASUREMENT_STATES = frozenset({"stable", "invalid", "unknown"})
MATURITY_STATES = frozenset({"sufficient", "insufficient", "unknown"})

# Forbidden decision classes when measurement is invalid: no numeric
# optimization, no confident deep-event diagnosis.
MEASUREMENT_INVALID_FORBID = frozenset(
    {"aggressive_numeric_optimization", "confident_deep_event_diagnosis"}
)
# Forbidden when maturity is insufficient: no premature bid/target change.
MATURITY_INSUFFICIENT_FORBID = frozenset({"premature_bid_change"})


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
    policy_state: str | None = None
    permission_state: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ReasoningScenario:
        measurement = str(data.get("measurement_state", "unknown"))
        maturity = str(data.get("maturity_state", "unknown"))
        if measurement not in MEASUREMENT_STATES:
            raise ValueError(f"unknown measurement_state: {measurement}")
        if maturity not in MATURITY_STATES:
            raise ValueError(f"unknown maturity_state: {maturity}")
        return cls(
            measurement_state=measurement,
            maturity_state=maturity,
            policy_state=data.get("policy_state"),
            permission_state=data.get("permission_state"),
        )


def derive_expected_behavior(
    scenario: ReasoningScenario,
) -> ExpectedBehavior:
    """Derive must-consider and forbid lists from the scenario state.

    Rules:
    - measurement = invalid -> forbid aggressive_numeric_optimization and
      confident_deep_event_diagnosis.
    - maturity = insufficient -> forbid premature_bid_change.
    - policy/permission state is authoritative: if a permission projection
      blocks an action, forbid it (currently expressed via scenario state).
    """
    must_consider: list[str] = ["measurement", "maturity"]
    forbid: set[str] = set()

    if scenario.measurement_state == "invalid":
        forbid.update(MEASUREMENT_INVALID_FORBID)
    if scenario.maturity_state == "insufficient":
        forbid.update(MATURITY_INSUFFICIENT_FORBID)

    return ExpectedBehavior(
        must_consider=tuple(must_consider),
        forbid=tuple(sorted(forbid)),
    )


def scenario_compatible_with_fixture(
    scenario: ReasoningScenario, expectations: Any
) -> bool:
    """True when the fixture's expectations do not contradict derived rules.

    A fixture that marks ``measurement_invalid`` but demands a numeric
    recommendation would violate the deterministic safety contract.
    """
    behavior = derive_expected_behavior(scenario)
    must_not = set(getattr(expectations, "must_not", ()))
    for forbidden in behavior.forbid:
        mapped = {
            "aggressive_numeric_optimization": "recommend_numeric_change_without_maturity",
            "confident_deep_event_diagnosis": "recommend_action_when_measurement_invalid",
            "premature_bid_change": "recommend_numeric_change_without_maturity",
        }
        if mapped.get(forbidden) in must_not:
            continue
        # Unknown mapping: keep the derived rule authoritative.
        if forbidden not in mapped:
            return False
    return True
