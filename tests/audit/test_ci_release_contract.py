"""CI, coverage, and release-gate contracts."""

from __future__ import annotations

from pathlib import Path


def _read(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def test_ordinary_ci_enforces_quality_coverage_and_operator_smokes(
    repo_root: Path,
) -> None:
    workflow = _read(repo_root, ".github/workflows/ci.yml")

    for contract in [
        "ruff check .",
        "ruff format --check .",
        "python -m mypy scripts/kimi_ads/uac",
        "--cov=kimi_ads.uac",
        "--cov-report=xml:coverage.xml",
        "--cov-fail-under=80",
        "scripts/privacy_doctor.py --json",
        "scripts/sync_skill_layout.py --check",
        "scripts/knowledge_doctor.py --json",
        "validate-ledger",
        "review-ledger",
        "migrate-ledger",
        "init-workspace",
        "--workspace",
        "examples/replays/example-anonymized --json",
        "scripts/ci/check_install_layout.py",
        "scripts/ci/check_uac_decide_output.py",
        "scripts/ci/check_uac_policies.py",
        "scripts/ci/check_numeric_cap.py",
        "shellcheck install.sh",
        "pip-audit --strict",
        "uac-report.md",
    ]:
        assert contract in workflow

    assert "privacy_doctor.py --history" not in workflow

    # The installed-artifact contract itself lives in the shared CI script.
    install_layout = _read(repo_root, "scripts/ci/check_install_layout.py")
    assert "references/agent-workflow.md" in install_layout


def test_release_privacy_gate_requires_complete_history(repo_root: Path) -> None:
    workflow = _read(repo_root, ".github/workflows/release-gate.yml")

    for contract in [
        "tags:",
        '- "v*"',
        "workflow_dispatch:",
        "fetch-depth: 0",
        "git rev-parse --is-shallow-repository",
        "privacy_doctor.py --history --json",
        "github.ref_type == 'tag'",
        'os.environ["GITHUB_REF_NAME"]',
        'manifest.get("version")',
        'git cat-file -t "refs/tags/${GITHUB_REF_NAME}"',
        "git fetch --no-tags origin main",
        "git rev-parse FETCH_HEAD^{commit}",
    ]:
        assert contract in workflow


def test_subprocess_coverage_and_release_documentation_are_explicit(
    repo_root: Path,
) -> None:
    pyproject = _read(repo_root, "pyproject.toml")
    requirements = _read(repo_root, "requirements-dev.txt")
    releasing = _read(repo_root, "docs/releasing.md")

    assert 'patch = ["subprocess"]' in pyproject
    assert "coverage[toml]>=7.10,<8.0" in requirements
    assert "(11) verify fixed-version install and" in releasing
    assert "--cov-report=xml:coverage.xml" in releasing
    assert "--cov-fail-under=80" in releasing
    assert "Release Privacy Gate" in releasing
    assert "not eligible for a tag or GitHub Release" in releasing
    assert "do not create or push a tag" in releasing
    assert "python3 scripts/privacy_doctor.py --json" in releasing
    assert "tagger metadata and the tag message" in releasing
    assert "automatic remote Release Privacy Gate" in releasing
