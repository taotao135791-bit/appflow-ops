"""Privacy-safe evaluation contracts: data tiers, sanitization, and gates."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.evals.safety import (
    ReasoningScenario,
    derive_expected_behavior,
    scenario_compatible_with_fixture,
)
from appflow_ops.evals.sanitize import (
    assert_sanitized,
    bucket_age,
    identity_markers,
    sanitize_replay,
)
from appflow_ops.evals.vague_query import (
    ProductionDataError,
    evaluate_fixture,
    load_cases,
)

EVAL_PATH = Path("evals/vague-query-evals.json")


def _read(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


# ── Data tiers ────────────────────────────────────────────────────────────


def test_eval_cases_declare_synthetic_data_class(repo_root: Path) -> None:
    cases = load_cases(repo_root / EVAL_PATH)
    for case in cases:
        assert case.data_class == "synthetic", case.case_id
        assert case.source_type == "authored", case.case_id


def test_production_fixture_rejected_by_default_runner(repo_root: Path) -> None:
    raw = json.loads(_read(repo_root, EVAL_PATH))
    production = dict(raw)
    production["cases"] = [
        {**dict(case), "data_class": "production", "source_type": "replay"}
        for case in raw["cases"]
    ]
    path = repo_root / "tmp-production-evals.json"
    path.write_text(json.dumps(production), encoding="utf-8")
    try:
        with pytest.raises(ProductionDataError, match="cannot be used by the default"):
            evaluate_fixture(path, repo_root)
    finally:
        path.unlink(missing_ok=True)


def test_sanitized_fixture_rejected_by_default_runner(repo_root: Path) -> None:
    """Repository benchmark is synthetic-only: sanitized never enters CI."""

    raw = json.loads(_read(repo_root, EVAL_PATH))
    sanitized = dict(raw)
    sanitized["cases"] = [
        {**dict(case), "data_class": "sanitized", "source_type": "replay"}
        for case in raw["cases"]
    ]
    path = repo_root / "tmp-sanitized-evals.json"
    path.write_text(json.dumps(sanitized), encoding="utf-8")
    try:
        with pytest.raises(ProductionDataError, match="synthetic-only"):
            evaluate_fixture(path, repo_root)
    finally:
        path.unlink(missing_ok=True)


def test_synthetic_cases_have_no_sensitive_fields(repo_root: Path) -> None:
    text = _read(repo_root, EVAL_PATH)
    assert identity_markers(text) == ()


# ── Sanitization ──────────────────────────────────────────────────────────


def _raw_replay() -> dict:
    return {
        "platform": "google_uac",
        "objective_class": "app_promotion",
        "client": "Acme" + " Corp",
        "account_id": "123" + "-456" + "-7890",
        "campaign_id": "9876543210",
        "creative_copy": "Hurry! 50% off today only",
        "email": "operator" + "@acme.example",
        "landing_url": "https" + "://acme.example/app?token=secret",
        "workspace_path": "/" + "Users/operator/.appflow/workspaces/acme/ios-main",
        "notes": "client wants CPA under 5 by Friday",
        "spend_before": 423.0,
        "spend_after": 161.0,
        "tcpa_before": 97.0,
        "tcpa_after": 82.0,
        "executed_at": 12.5,
        "changed_at": 40.0,
        "measurement_state": "stable",
        "maturity_state": "sufficient",
        "permission_state": "budget_bid_creative",
    }


def test_sanitizer_removes_identity_and_free_text() -> None:
    result = sanitize_replay(_raw_replay())
    dropped = set(result.dropped_keys)
    for key in (
        "client",
        "account_id",
        "campaign_id",
        "creative_copy",
        "email",
        "landing_url",
        "workspace_path",
        "notes",
    ):
        assert key in dropped, key
    assert "client" not in result.data
    assert_sanitized(result.data)


def test_sanitizer_normalizes_money_to_index() -> None:
    result = sanitize_replay(_raw_replay())
    assert result.data["spend_index"] == {"before": 100.0, "after": 38.1}
    assert result.data["tcpa_index"] == {"before": 100.0, "after": 84.5}
    assert "spend_before" not in result.data
    assert "tcpa_after" not in result.data


def test_sanitizer_buckets_time() -> None:
    result = sanitize_replay(_raw_replay())
    assert result.data["executed_at_bucket"] == "6-24h"
    assert result.data["changed_at_bucket"] == "1-3d"
    assert bucket_age(3) == "<6h"
    assert bucket_age(20) == "6-24h"
    assert bucket_age(30) == "1-3d"
    assert bucket_age(150) == "3-7d"
    assert bucket_age(400) == ">7d"


def test_sanitizer_keeps_decision_shape() -> None:
    result = sanitize_replay(_raw_replay())
    assert result.data["platform"] == "google_uac"
    assert result.data["measurement_state"] == "stable"
    assert result.data["maturity_state"] == "sufficient"
    assert result.data["permission_state"] == "budget_bid_creative"


def test_sanitizer_is_one_way_without_mapping() -> None:
    result = sanitize_replay(_raw_replay())
    serialized = json.dumps(result.data, default=str)
    for original in ("Acme Corp", "123-456-7890", "9876543210", "423.0", "161.0"):
        assert original not in serialized, original
    # No reversible id mapping exists in the output shape.
    assert "original_id" not in serialized
    assert "mapping" not in serialized


def test_identity_markers_detect_common_leaks() -> None:
    assert "email" in identity_markers("reach me at a" + "@b.example please")
    assert "url" in identity_markers("see https" + "://acme.example/x")
    assert "absolute_path" in identity_markers("file at /" + "Users/op/workspaces/x")
    assert "stable_id" in identity_markers("customer 1234567890")


# ── Safety gates ──────────────────────────────────────────────────────────


def test_invalid_measurement_blocks_confident_deep_event_action() -> None:
    scenario = ReasoningScenario(
        measurement_state="invalid", maturity_state="sufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "aggressive_numeric_optimization" in behavior.forbid
    assert "confident_deep_event_diagnosis" in behavior.forbid


def test_invalid_measurement_uses_measurement_specific_constraint() -> None:
    scenario = ReasoningScenario(
        measurement_state="invalid", maturity_state="sufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "recommend_numeric_change_when_measurement_invalid" in behavior.forbid
    assert "recommend_numeric_change_without_maturity" not in behavior.forbid
    assert "premature_bid_change" not in behavior.forbid


def test_insufficient_maturity_blocks_premature_numeric_action() -> None:
    scenario = ReasoningScenario(
        measurement_state="stable", maturity_state="insufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "premature_bid_change" in behavior.forbid
    assert "recommend_numeric_change_without_maturity" in behavior.forbid


def test_maturity_constraint_is_distinct_from_measurement_constraint() -> None:
    immature = derive_expected_behavior(
        ReasoningScenario(measurement_state="stable", maturity_state="insufficient")
    )
    invalid = derive_expected_behavior(
        ReasoningScenario(measurement_state="invalid", maturity_state="sufficient")
    )
    # Each gate forbids its own decision classes; a maturity rule must never
    # be satisfied by a measurement rule and vice versa.
    assert "premature_bid_change" in immature.forbid
    assert "premature_bid_change" not in invalid.forbid
    assert "aggressive_numeric_optimization" in invalid.forbid
    assert "aggressive_numeric_optimization" not in immature.forbid


def test_policy_forbidden_action_is_rejected() -> None:
    scenario = ReasoningScenario(
        measurement_state="stable",
        maturity_state="sufficient",
        policy_state="forbid_numeric",
    )
    behavior = derive_expected_behavior(scenario)
    assert "any_numeric_change" in behavior.forbid
    assert "policy" in behavior.must_consider


def test_policy_cap_remains_authoritative() -> None:
    capped = derive_expected_behavior(
        ReasoningScenario(
            measurement_state="stable",
            maturity_state="sufficient",
            policy_state="cap_20pct",
        )
    )
    staged = derive_expected_behavior(
        ReasoningScenario(
            measurement_state="stable",
            maturity_state="sufficient",
            policy_state="staged_required",
        )
    )
    assert "over_cap_numeric_change" in capped.forbid
    assert "single_step_numeric_change" in staged.forbid
    assert "over_cap_numeric_change" not in staged.forbid


def test_permission_recommend_only_cannot_claim_execution() -> None:
    scenario = ReasoningScenario(
        measurement_state="stable",
        maturity_state="sufficient",
        permission_state="recommend_only",
    )
    behavior = derive_expected_behavior(scenario)
    assert "claim_execution" in behavior.forbid
    assert "permission" in behavior.must_consider


def test_full_permission_and_none_policy_add_no_forbid() -> None:
    behavior = derive_expected_behavior(
        ReasoningScenario(
            measurement_state="stable",
            maturity_state="sufficient",
            policy_state="none",
            permission_state="full",
        )
    )
    assert "claim_execution" not in behavior.forbid
    assert "any_numeric_change" not in behavior.forbid


def test_policy_and_permission_states_are_validated() -> None:
    with pytest.raises(ValueError, match="unknown policy_state"):
        ReasoningScenario.from_mapping({"policy_state": "nonsense"})
    with pytest.raises(ValueError, match="unknown permission_state"):
        ReasoningScenario.from_mapping({"permission_state": "nonsense"})


def test_fixture_cannot_satisfy_measurement_rule_with_maturity_rule() -> None:
    scenario = ReasoningScenario(measurement_state="invalid", maturity_state="stable")

    # The fixture only declares the maturity rule: measurement rules are
    # unsatisfied, so the fixture is incompatible with the scenario.
    class FakeExpectations:
        must_not = ("recommend_numeric_change_without_maturity",)

    assert not scenario_compatible_with_fixture(scenario, FakeExpectations())

    # Declaring the measurement-specific rules makes it compatible.
    class CompatibleExpectations:
        must_not = (
            "recommend_numeric_change_when_measurement_invalid",
            "recommend_action_when_measurement_invalid",
        )

    assert scenario_compatible_with_fixture(scenario, CompatibleExpectations())


def test_policy_and_permission_gates_require_their_own_rules() -> None:
    policy_scenario = ReasoningScenario(
        measurement_state="stable",
        maturity_state="sufficient",
        policy_state="forbid_numeric",
    )

    class PolicyExpectations:
        must_not = ("recommend_numeric_change_when_policy_forbids",)

    assert scenario_compatible_with_fixture(policy_scenario, PolicyExpectations())

    permission_scenario = ReasoningScenario(
        measurement_state="stable",
        maturity_state="sufficient",
        permission_state="recommend_only",
    )

    class PermissionExpectations:
        must_not = ("claim_execution_without_permission",)

    assert scenario_compatible_with_fixture(
        permission_scenario, PermissionExpectations()
    )

    class WrongGateExpectations:
        must_not = ("recommend_numeric_change_when_measurement_invalid",)

    assert not scenario_compatible_with_fixture(
        permission_scenario, WrongGateExpectations()
    )


def test_safety_gate_fixtures_are_compatible_with_derived_rules(
    repo_root: Path,
) -> None:
    cases = load_cases(repo_root / EVAL_PATH)
    for case in cases:
        scenario = ReasoningScenario(
            measurement_state=(
                "invalid"
                if case.expectations.safety_gate == "measurement_invalid"
                else "stable"
            ),
            maturity_state=(
                "insufficient"
                if case.expectations.safety_gate == "maturity_pending"
                else "sufficient"
            ),
        )
        assert scenario_compatible_with_fixture(scenario, case.expectations), (
            case.case_id
        )


# ── Release preflight ─────────────────────────────────────────────────────


def test_release_preflight_passes(repo_root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "release_check.py")],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "preflight PASS" in completed.stdout


def test_preflight_rejects_version_drift(repo_root: Path, tmp_path: Path) -> None:
    import shutil

    scratch = tmp_path / "repo"
    shutil.copytree(
        repo_root, scratch, ignore=shutil.ignore_patterns(".git", "workspaces", "*.pyc")
    )
    (scratch / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(scratch / "scripts" / "release_check.py")],
        cwd=scratch,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "manifest version" in completed.stdout


def test_preflight_full_history_mode_passes_with_allowlist(repo_root: Path) -> None:
    """--full runs the same full-history gate as the release workflow."""

    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "release_check.py"),
            "--full",
            "--allowlist",
            "privacy-allowlist.json",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "full-history privacy scan clean" in completed.stdout
    assert "preflight PASS" in completed.stdout
