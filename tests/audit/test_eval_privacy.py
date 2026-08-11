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


def test_measurement_invalid_forbids_confident_deep_event_action() -> None:
    scenario = ReasoningScenario(
        measurement_state="invalid", maturity_state="sufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "aggressive_numeric_optimization" in behavior.forbid
    assert "confident_deep_event_diagnosis" in behavior.forbid


def test_immature_case_forbids_premature_numeric_action() -> None:
    scenario = ReasoningScenario(
        measurement_state="stable", maturity_state="insufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "premature_bid_change" in behavior.forbid


def test_policy_constraints_remain_authoritative() -> None:
    scenario = ReasoningScenario(
        measurement_state="stable", maturity_state="sufficient"
    )
    behavior = derive_expected_behavior(scenario)
    assert "premature_bid_change" not in behavior.forbid
    assert "aggressive_numeric_optimization" not in behavior.forbid


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
