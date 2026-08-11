"""Vague Query Eval Suite: fixture contracts and a thin evaluator interface.

The suite tests whether AppFlow's vague-question behavior satisfies the
AppFlow Reasoning Contract
(``skills/appflow/references/reasoning-contract.md``). Today it runs
offline and deterministically: fixture schema validation plus consistency
checks between eval expectations and the deterministic UAC engine output on
the same fixture.

A future model runner implements :class:`Evaluator` to score real model
responses (hypothesis coverage, evidence discipline, elimination quality,
ranking quality, convergence, question count, policy violations). This
module requires no model API key and no network access.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..uac.quick_ops import decide_case

EVAL_SCHEMA_VERSION = "1.0"

PLATFORMS = frozenset(
    {"google_uac", "google", "meta", "tiktok", "cross_platform", "measurement"}
)
SAFETY_GATES = frozenset({"none", "measurement_invalid", "maturity_pending"})
MINIMUM_CASE_COUNT = 20

# Data tiers (docs/eval-privacy.md):
# - synthetic: fully authored fixtures; the ONLY data class allowed in the
#   repository, CI, and future external benchmarks.
# - sanitized: a local transformation boundary derived from real replays by
#   the local sanitizer; generated locally for inspection and pattern
#   extraction, NOT committed by default.
# - production: real operator data; DENY BY DEFAULT for any evaluation
#   runner and never committed.
DATA_CLASSES = frozenset({"synthetic", "sanitized", "production"})
SOURCE_TYPES = frozenset({"authored", "replay"})

_KNOWN_MUST_NOT = frozenset(
    {
        "claim_causality_without_evidence",
        "recommend_new_campaign_immediately",
        "recommend_pause_immediately",
        "recommend_action_when_measurement_invalid",
        "recommend_numeric_change_when_measurement_invalid",
        "recommend_numeric_change_without_maturity",
        "recommend_numeric_change_when_policy_forbids",
        "claim_execution_without_permission",
        "ask_for_full_metric_checklist",
    }
)


class ProductionDataError(RuntimeError):
    """Raised when production advertising data reaches the default runner.

    Production data may only be used in an operator-controlled local
    environment; the default evaluation runner refuses it loudly instead of
    degrading silently.
    """


@dataclass(frozen=True)
class EvalExpectations:
    must_consider: tuple[str, ...]
    must_not: tuple[str, ...]
    must_converge: bool
    must_have_primary_action: bool
    must_not_ask_more_than: int | None
    safety_gate: str


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    query: str
    platform: str
    context: Mapping[str, Any]
    expectations: EvalExpectations
    uac_fixture: str | None = None
    data_class: str = "synthetic"
    source_type: str = "authored"


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    passed: bool
    checks: Mapping[str, bool]
    notes: tuple[str, ...] = ()


class Evaluator(Protocol):
    """Thin future model-runner interface.

    Implement ``evaluate`` to score a model's response to ``case.query``
    against the contract dimensions. The built-in checks in this module stay
    deterministic and offline; model scoring is intentionally out of scope.
    """

    def evaluate(self, case: EvalCase) -> EvalResult: ...


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a non-empty list of strings")
    return tuple(str(item).strip() for item in value)


def parse_expectations(data: Mapping[str, Any]) -> EvalExpectations:
    must_consider = _string_list(
        data.get("must_consider"), "expectations.must_consider"
    )
    must_not = _string_list(data.get("must_not"), "expectations.must_not")
    _require(
        len(must_consider) >= 1,
        "expectations.must_consider must list at least one hypothesis family",
    )
    _require(len(must_not) >= 1, "expectations.must_not must list at least one rule")
    unknown = sorted(set(must_not) - _KNOWN_MUST_NOT)
    _require(
        not unknown,
        f"expectations.must_not contains unknown rules: {', '.join(unknown)}",
    )
    _require(
        isinstance(data.get("must_converge"), bool),
        "expectations.must_converge must be boolean",
    )
    _require(
        isinstance(data.get("must_have_primary_action"), bool),
        "expectations.must_have_primary_action must be boolean",
    )
    max_questions = data.get("must_not_ask_more_than")
    _require(
        isinstance(max_questions, int)
        and not isinstance(max_questions, bool)
        and max_questions >= 0
        or max_questions is None,
        "expectations.must_not_ask_more_than must be a non-negative integer or null",
    )
    safety_gate = data.get("safety_gate", "none")
    _require(
        isinstance(safety_gate, str) and safety_gate in SAFETY_GATES,
        f"unknown safety_gate: {safety_gate}",
    )
    return EvalExpectations(
        must_consider=must_consider,
        must_not=must_not,
        must_converge=bool(data["must_converge"]),
        must_have_primary_action=bool(data["must_have_primary_action"]),
        must_not_ask_more_than=max_questions,
        safety_gate=str(safety_gate),
    )


def parse_case(data: Mapping[str, Any]) -> EvalCase:
    case_id = data.get("id")
    _require(
        bool(isinstance(case_id, str) and case_id.strip()),
        "case.id must be non-empty",
    )
    query = data.get("query")
    _require(
        bool(isinstance(query, str) and query.strip()),
        "case.query must be non-empty",
    )
    platform = data.get("platform")
    _require(
        isinstance(platform, str) and platform in PLATFORMS,
        f"unknown platform: {platform}",
    )
    context = data.get("context", {})
    _require(isinstance(context, Mapping), "case.context must be an object")
    fixture = data.get("uac_fixture")
    _require(
        fixture is None or (isinstance(fixture, str) and fixture.endswith(".yaml")),
        "case.uac_fixture must be a .yaml path or null",
    )
    data_class = data.get("data_class", "synthetic")
    _require(
        isinstance(data_class, str) and data_class in DATA_CLASSES,
        f"unknown data_class: {data_class}",
    )
    source_type = data.get("source_type", "authored")
    _require(
        isinstance(source_type, str) and source_type in SOURCE_TYPES,
        f"unknown source_type: {source_type}",
    )
    _require(
        data_class == "synthetic" or source_type == "replay",
        "sanitized/production cases must declare source_type: replay",
    )
    expectations = parse_expectations(data.get("expectations", {}))
    return EvalCase(
        case_id=str(case_id),
        query=str(query),
        platform=str(platform),
        context=dict(context),
        expectations=expectations,
        uac_fixture=str(fixture) if fixture is not None else None,
        data_class=str(data_class),
        source_type=str(source_type),
    )


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    """Load and validate the eval fixture file. Pure and offline."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    _require(
        raw.get("schema_version") == EVAL_SCHEMA_VERSION,
        f"unsupported eval schema_version: {raw.get('schema_version')!r}",
    )
    entries = raw.get("cases")
    _require(
        isinstance(entries, list) and len(entries) > 0,
        "eval file must have a cases list",
    )
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for entry in entries:
        _require(isinstance(entry, Mapping), "each case must be an object")
        case = parse_case(entry)
        _require(case.case_id not in seen, f"duplicate case id: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    _require(
        len(cases) >= MINIMUM_CASE_COUNT,
        f"vague query eval needs at least {MINIMUM_CASE_COUNT} cases, got {len(cases)}",
    )
    return tuple(cases)


def coverage(cases: Sequence[EvalCase]) -> Mapping[str, int]:
    """Count cases per platform for coverage reporting."""
    counts = {platform: 0 for platform in PLATFORMS}
    for case in cases:
        counts[case.platform] = counts.get(case.platform, 0) + 1
    return counts


def _load_uac_fixture(fixture_name: str, repo_root: Path) -> dict[str, Any]:
    # Source layout: <root>/skills/ads-google-app/assets/. Installed bundle:
    # <root>/../ads-google-app/assets/ (skill base is the router's parent).
    candidates = (
        repo_root / "skills" / "ads-google-app" / "assets" / fixture_name,
        repo_root.parent / "ads-google-app" / "assets" / fixture_name,
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise FileNotFoundError(f"uac_fixture not found: {fixture_name}")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise TypeError(f"uac_fixture must be a mapping: {fixture_name}")
    return dict(data)


def uac_consistency_checks(
    case: EvalCase, engine_decision: Mapping[str, Any], repo_root: Path
) -> Mapping[str, bool]:
    """Golden checks between eval expectations and deterministic engine output.

    The agent may explore beyond the engine, but must not override
    deterministic safety gates. These checks detect fixture/expectation
    conflicts with the real UAC engine on the same input.
    """
    checks: dict[str, bool] = {}
    if case.uac_fixture is None:
        return checks
    verdict = str(engine_decision.get("decision", {}).get("verdict", "")).upper()
    campaign_action = str(
        engine_decision.get("campaign_level_decision", {}).get("action", "")
    ).upper()
    classification = str(
        engine_decision.get("classification", {}).get("operation_classification", "")
    ).upper()
    do_not_do = engine_decision.get("do_not_do", [])
    if not isinstance(do_not_do, list):
        do_not_do = []

    checks["no_new_campaign_conflict"] = not (
        "recommend_new_campaign_immediately" in case.expectations.must_not
        and ("NEW_CAMPAIGN" in verdict or campaign_action in {"REOPEN", "NEW"})
    )
    checks["no_pause_conflict"] = not (
        "recommend_pause_immediately" in case.expectations.must_not
        and campaign_action in {"PAUSE", "PAUSE_CAMPAIGN"}
    )
    if case.expectations.safety_gate == "measurement_invalid":
        checks["no_numeric_change_when_measurement_invalid"] = classification not in {
            "NORMAL_OPTIMIZATION",
            "STAGED_OPTIMIZATION",
        }
    else:
        checks["no_numeric_change_when_measurement_invalid"] = True
    checks["engine_has_guardrails"] = len(do_not_do) > 0
    return checks


def evaluate_fixture(
    path: Path, repo_root: Path
) -> tuple[tuple[EvalCase, ...], tuple[EvalResult, ...]]:
    """Run the offline fixture checks. Returns (cases, results).

    ``production`` data is rejected: it must not leave the operator's
    environment. ``sanitized`` cases are likewise not part of the repository
    benchmark (synthetic-only); the runner rejects them too so a locally
    sanitized fixture cannot silently enter CI.
    """
    cases = load_cases(path)
    results: list[EvalResult] = []
    for case in cases:
        if case.data_class in {"production", "sanitized"}:
            raise ProductionDataError(
                f"{case.data_class} data cannot be used by the default "
                "evaluation runner; repository evals are synthetic-only, "
                f"and {case.data_class} data stays local by default."
            )
        checks: dict[str, bool] = {"fixture_schema_valid": True}
        if case.uac_fixture is not None:
            fixture = _load_uac_fixture(case.uac_fixture, repo_root)
            engine_decision = decide_case(fixture)
            checks.update(uac_consistency_checks(case, engine_decision, repo_root))
        results.append(
            EvalResult(
                case_id=case.case_id,
                passed=all(checks.values()),
                checks=checks,
            )
        )
    return cases, tuple(results)
