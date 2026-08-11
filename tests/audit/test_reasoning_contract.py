"""Reasoning Contract and Vague Query Eval regression tests.

Covers the eight contracts from the Release → Contract → Eval plan:
router reference, skill inheritance, README consistency, no duplicate
definitions, version alignment, release artifact, eval schema, and
deterministic UAC consistency.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.evals.vague_query import (  # noqa: E402
    coverage,
    evaluate_fixture,
    load_cases,
)

# Diagnosis skills that must inherit the contract (Part 3).
INHERITING_SKILLS = [
    "appflow",  # main router
    "ads-ops",
    "ads-google-app",
    "ads-google",
    "ads-meta",
    "ads-tiktok",
    "ads-youtube",
    "ads-audit",
    "ads-attribution",
    "ads-server-side-tracking",
    "ads-creative",
    "ads-levers",
    "ads-budget",
]

FIVE_STAGES = ["Diverge", "Verify", "Eliminate", "Rank", "Converge"]

CONTRACT_PATH = "skills/appflow/references/reasoning-contract.md"
EVAL_PATH = "evals/vague-query-evals.json"


def _read(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


# Test 1 — the main router must reference the contract.
def test_main_router_references_reasoning_contract(repo_root: Path) -> None:
    router = _read(repo_root, "skills/appflow/SKILL.md")
    assert "reasoning-contract.md" in router
    assert "Diverge → Verify → Eliminate → Rank → Converge" in router
    assert (repo_root / CONTRACT_PATH).is_file()


# Test 2 — key diagnosis skills must inherit the contract by reference.
def test_diagnosis_skills_inherit_the_contract(repo_root: Path) -> None:
    failures: list[str] = []
    for skill in INHERITING_SKILLS:
        path = repo_root / "skills" / skill / "SKILL.md"
        if not path.is_file():
            failures.append(f"missing skill: {skill}")
            continue
        text = path.read_text(encoding="utf-8")
        if "reasoning-contract.md" not in text:
            failures.append(f"{skill} does not reference the reasoning contract")
    assert not failures, "skills missing contract inheritance:\n" + "\n".join(
        failures
    )


# Test 3 — README's reasoning loop must be consistent with the contract.
def test_readme_matches_contract_definitions(repo_root: Path) -> None:
    contract = _read(repo_root, CONTRACT_PATH)
    for stage in FIVE_STAGES:
        assert stage in contract, f"contract missing stage {stage}"
    # Contract defines the canonical order via the stage headings.
    stage_positions = [
        contract.index(f"## Stage {index} — {stage}")
        for index, stage in enumerate(FIVE_STAGES, 1)
    ]
    assert stage_positions == sorted(stage_positions), "contract stages are out of order"

    for readme_name in ("README.md", "README.en.md"):
        readme = _read(repo_root, readme_name)
        assert "Diverge → Verify → Eliminate → Rank → Converge" in readme
        assert "Problem over procedure" in readme or "Problem over procedure" in contract
        assert "Broad internally, concise externally" in readme


# Test 4 — no conflicting five-stage definitions outside the canonical source.
def test_no_duplicate_five_stage_definitions(repo_root: Path) -> None:
    duplicated = []
    for path in sorted((repo_root / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        # A full definition would carry stage headings; references may only
        # name the loop.
        if "## Stage 1 — Diverge" in text or "## Stage 1 - Diverge" in text:
            duplicated.append(str(path.relative_to(repo_root)))
    assert not duplicated, "full five-stage definitions found outside the contract"


# Test 5 — README pinned install version must equal the repository version.
def test_readme_pinned_version_matches_repository_version(repo_root: Path) -> None:
    version = _read(repo_root, "VERSION").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"bad VERSION: {version}"

    manifest = json.loads(_read(repo_root, "appflow.plugin.json"))
    assert manifest["version"] == version

    documents = [
        "README.md",
        "README.en.md",
        "QUICKSTART.zh-CN.md",
        "QUICKSTART.en.md",
    ]
    for name in documents:
        text = _read(repo_root, name)
        install_line = [
            line for line in text.splitlines() if "--ref=v" in line or "-Ref v" in line
        ]
        assert install_line, f"{name} has no pinned install command"
        pinned = "".join(install_line)
        assert f"--ref=v{version}" in pinned or f"-Ref v{version}" in pinned, (
            f"{name} pins a version different from VERSION {version}"
        )

    report = _read(repo_root, "scripts/generate_report.py")
    assert f'__version__ = "{version}"' in report
    fetch_page = _read(repo_root, "scripts/fetch_page.py")
    assert f"AppFlowOps/{version}" in fetch_page


# Test 6 — the release artifact must include the Reasoning Contract.
def test_release_artifact_contains_reasoning_contract(repo_root: Path) -> None:
    assert (repo_root / CONTRACT_PATH).is_file()
    installer = _read(repo_root, "install.sh")
    # The installer copies the whole references/ glob of the main skill.
    assert 'skills/appflow/references/"*.md' in installer

    install_layout = _read(repo_root, "scripts/ci/check_install_layout.py")
    assert "references/reasoning-contract.md" in install_layout


# Test 7 — eval fixtures must all be schema-valid with required coverage.
def test_vague_query_eval_fixtures_are_valid(repo_root: Path) -> None:
    cases = load_cases(repo_root / EVAL_PATH)
    assert len(cases) >= 20, f"need >=20 cases, got {len(cases)}"
    platform_counts = coverage(cases)
    for platform in ("google_uac", "meta", "tiktok", "cross_platform", "measurement"):
        assert platform_counts[platform] >= 1, f"no eval cases for {platform}"

    for case in cases:
        assert case.expectations.must_consider
        assert case.expectations.must_not
        assert case.expectations.must_converge
        assert case.expectations.must_have_primary_action


# Test 8 — eval expectations must not conflict with deterministic UAC output.
def test_vague_query_evals_consistent_with_deterministic_uac(
    repo_root: Path,
) -> None:
    cases, results = evaluate_fixture(repo_root / EVAL_PATH, repo_root)
    failures = [
        f"{result.case_id}: {result.checks}" for result in results if not result.passed
    ]
    assert not failures, "eval expectations conflict with deterministic UAC:\n" + "\n".join(
        failures
    )
    assert any(case.uac_fixture for case in cases), "no golden uac_fixture cases"


# Test 8b — the suite is offline-safe: no model API keys anywhere.
def test_eval_suite_is_offline_safe(repo_root: Path) -> None:
    eval_module = _read(repo_root, "scripts/appflow_ops/evals/vague_query.py")
    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "KIMI_API_KEY",
        "requests.",
    ]:
        assert key not in eval_module, f"eval module must stay offline, found {key}"


# Test 9 — eval fixture checks runnable via CLI-adjacent path (pytest smoke).
def test_eval_runner_smoke_invocation(repo_root: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, 'scripts'); "
                "from appflow_ops.evals.vague_query import evaluate_fixture; "
                "import pathlib; "
                "cases, results = evaluate_fixture("
                "pathlib.Path('evals/vague-query-evals.json'), pathlib.Path('.')); "
                "print(len(cases), all(r.passed for r in results))"
            ),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip().endswith("True")
