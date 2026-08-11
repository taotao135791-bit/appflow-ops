#!/usr/bin/env python3
"""Release preflight: the checks a version must pass before tagging.

Runs the highest-signal validations that previously only ran after a tag was
pushed, so an unhealthy version cannot be released normally:

- version consistency across VERSION / manifest / README+QUICKSTART pins
- reasoning contract present and referenced by the router
- vague-query eval fixtures schema-valid, synthetic-only, privacy-clean
- repository tree privacy scan (worktree, no history needed)

Offline-safe: no API keys, no network, no production workspace access.
Exit code 0 = healthy; 1 = fix before tagging.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from appflow_ops.evals.sanitize import identity_markers
from appflow_ops.evals.vague_query import (
    ProductionDataError,
    evaluate_fixture,
    load_cases,
)

_FAILURES: list[str] = []


def _fail(message: str) -> None:
    _FAILURES.append(message)
    print(f"FAIL  {message}")


def _ok(message: str) -> None:
    print(f"ok    {message}")


def check_version_consistency() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        _fail(f"VERSION is not semver: {version!r}")
        return
    # Manifest and README pins exist only in a source checkout; the installed
    # bundle carries VERSION and the skill tree only.
    manifest_path = ROOT / "appflow.plugin.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != version:
            _fail(f"manifest version {manifest.get('version')} != VERSION {version}")
    for name in (
        "README.md",
        "README.en.md",
        "QUICKSTART.zh-CN.md",
        "QUICKSTART.en.md",
    ):
        path = ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        pins = [
            line for line in text.splitlines() if "--ref=v" in line or "-Ref v" in line
        ]
        if not pins or not any(f"v{version}" in pin for pin in pins):
            _fail(f"{name} does not pin the install version to v{version}")
    _ok(f"version sources consistent at {version}")


def _first_existing(*paths: Path) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def check_reasoning_contract() -> None:
    contract = _first_existing(
        ROOT / "skills" / "appflow" / "references" / "reasoning-contract.md",
        ROOT / "references" / "reasoning-contract.md",
    )
    if contract is None:
        _fail("reasoning-contract.md missing")
        return
    text = contract.read_text(encoding="utf-8")
    for stage in ("Diverge", "Verify", "Eliminate", "Rank", "Converge"):
        if stage not in text:
            _fail(f"reasoning contract missing stage {stage}")
    router = _first_existing(
        ROOT / "skills" / "appflow" / "SKILL.md",
        ROOT / "SKILL.md",
    )
    if router is None or "reasoning-contract.md" not in router.read_text(
        encoding="utf-8"
    ):
        _fail("router does not reference the reasoning contract")
    _ok("reasoning contract present and referenced")


def check_eval_fixtures() -> None:
    fixture = ROOT / "evals" / "vague-query-evals.json"
    try:
        cases = load_cases(fixture)
    except ValueError as exc:
        _fail(f"eval fixture schema: {exc}")
        return
    for case in cases:
        if case.data_class != "synthetic":
            _fail(f"eval fixture {case.case_id} is not synthetic ({case.data_class})")
    try:
        _, results = evaluate_fixture(fixture, ROOT)
    except ProductionDataError as exc:
        _fail(f"eval runner refused fixtures: {exc}")
        return
    for result in results:
        if not result.passed:
            _fail(f"eval fixture {result.case_id} failed checks: {result.checks}")
    _ok(f"eval fixtures valid: {len(cases)} synthetic cases, all checks passed")


def check_eval_privacy() -> None:
    fixture = (ROOT / "evals" / "vague-query-evals.json").read_text(encoding="utf-8")
    markers = identity_markers(fixture)
    if markers:
        _fail(f"eval fixtures contain identity markers: {', '.join(markers)}")
    else:
        _ok("eval fixtures carry no identity markers")


def _is_git_repo() -> bool:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def check_worktree_privacy() -> None:
    if not _is_git_repo():
        # Installed bundles are not git checkouts; the privacy scan runs on
        # the source repository at release time.
        _ok("worktree privacy scan skipped outside a git checkout")
        return
    doctor = _first_existing(
        ROOT / "scripts" / "privacy_doctor.py",
        ROOT / "privacy_doctor.py",
    )
    if doctor is None:
        # Installed bundles do not ship the repository privacy scanner.
        _ok("worktree privacy scan not available in installed bundle")
        return
    completed = subprocess.run(
        [sys.executable, str(doctor), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        _fail("privacy_doctor worktree scan failed")
        return
    report = json.loads(completed.stdout)
    active = [f for f in report.get("findings", []) if not f.get("waived")]
    if active:
        kinds = ", ".join(sorted({f.get("kind", "?") for f in active}))
        _fail(f"worktree privacy findings: {kinds}")
    else:
        _ok("worktree privacy scan clean")


def main() -> int:
    print("AppFlow Ops release preflight")
    check_version_consistency()
    check_reasoning_contract()
    check_eval_fixtures()
    check_eval_privacy()
    check_worktree_privacy()
    if _FAILURES:
        print(f"\npreflight FAILED: {len(_FAILURES)} issue(s)")
        return 1
    print("\npreflight PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
