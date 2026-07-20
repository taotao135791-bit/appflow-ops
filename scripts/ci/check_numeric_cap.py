#!/usr/bin/env python3
"""Verify the numeric change-cap staging contract of UAC `decide`.

Rebuilds the staged fixture from
``skills/ads-google-app/assets/UAC-QUICK-NUMERIC.example.yaml`` with
``target_cpa = 2.0`` and ``maximum_acceptable_cpa = 8.0``, runs the ``decide``
CLI, and asserts the numeric-safety contract:

* raw candidate 5.0 is change-limited to 2.4 (tCPA 2.0 with a 20% cap allows
  at most +0.4), so the final recommendation is 2.4;
* the operation is classified ``STAGED_OPTIMIZATION`` with stage 1 immediate
  and every later stage requiring fresh review and no automatic execution;
* the run stays read-only (no account or ledger writes).

Usage:
    python scripts/ci/check_numeric_cap.py

    python scripts/ci/check_numeric_cap.py \
        --input skills/ads-google-app/assets/UAC-QUICK-NUMERIC.example.yaml \
        --staged-input-output out/staged-input.yaml \
        --json-output out/staged-output.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows consoles default to cp1252; keep the ✓/✗ markers from crashing CI.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    REPO_ROOT
    / "skills"
    / "ads-google-app"
    / "assets"
    / "UAC-QUICK-NUMERIC.example.yaml"
)
DEFAULT_SCRIPT = REPO_ROOT / "scripts" / "uac_experiment.py"

STAGED_TARGET_CPA = 2.0
STAGED_MAXIMUM_ACCEPTABLE_CPA = 8.0


def _load_yaml(path: Path):
    try:
        import yaml
    except ImportError as error:  # pragma: no cover - CI environment guard
        raise SystemExit(
            "PyYAML is required to rebuild the staged numeric fixture; "
            "install requirements-dev.txt"
        ) from error
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _dump_yaml(data, path: Path) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def build_staged_input(source: Path, destination: Path) -> None:
    """Copy the numeric fixture with a tightened target CPA window."""
    case = _load_yaml(source)
    case["goal"].update(
        {
            "target_cpa": STAGED_TARGET_CPA,
            "maximum_acceptable_cpa": STAGED_MAXIMUM_ACCEPTABLE_CPA,
        }
    )
    _dump_yaml(case, destination)


def run_decide(script: Path, input_path: Path, json_output: Path) -> None:
    command = [
        sys.executable,
        str(script),
        "decide",
        str(input_path),
        "--json-output",
        str(json_output),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(
            f"decide CLI failed with exit code {completed.returncode}: "
            + " ".join(command)
        )


def check_staged_contract(result: dict) -> list[str]:
    """Return human-readable violations of the staged numeric-cap contract."""
    failures: list[str] = []

    def expect(container: dict, key: str, expected, label: str) -> None:
        actual = container.get(key)
        if isinstance(expected, bool):
            if actual is not expected:
                failures.append(f"{label}: expected {expected}, got {actual!r}")
        elif actual != expected:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    safety = result.get("target_recommendation", {}).get("numeric_safety", {})
    expect(safety, "raw_candidate", 5.0, "numeric_safety.raw_candidate")
    expect(
        safety,
        "change_limited_candidate",
        2.4,
        "numeric_safety.change_limited_candidate",
    )
    expect(
        safety,
        "final_recommendation",
        2.4,
        "numeric_safety.final_recommendation",
    )
    expect(
        safety,
        "operation_classification",
        "STAGED_OPTIMIZATION",
        "numeric_safety.operation_classification",
    )

    staged_plan = safety.get("staged_plan", {})
    expect(staged_plan, "immediate_stage", 1, "staged_plan.immediate_stage")
    stages = staged_plan.get("stages", [])
    if not stages:
        failures.append("staged_plan.stages: expected at least one stage")
    else:
        expect(stages[0], "immediate", True, "staged_plan.stages[0].immediate")
        for index, stage in enumerate(stages[1:], start=1):
            expect(
                stage,
                "approval_state",
                "REQUIRES_FRESH_REVIEW",
                f"staged_plan.stages[{index}].approval_state",
            )
            expect(
                stage,
                "automatic_execution",
                False,
                f"staged_plan.stages[{index}].automatic_execution",
            )

    expect(result, "account_write", False, "account_write")
    expect(result, "ledger_write", False, "ledger_write")
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="numeric quick-decision fixture to stage (default: %(default)s)",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT,
        help="uac_experiment.py to invoke (default: %(default)s)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="directory for generated files (default: a temp directory)",
    )
    parser.add_argument(
        "--staged-input-output",
        type=Path,
        help="where to write the staged input YAML (default: <work-dir>/)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="where the decide CLI writes JSON (default: <work-dir>/)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.is_file():
        raise SystemExit(f"numeric fixture not found: {args.input}")
    if not args.script.is_file():
        raise SystemExit(f"decide CLI script not found: {args.script}")

    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="uac-numeric-cap-") as temp_dir:
        work_dir = args.work_dir or Path(temp_dir)
        staged_input = args.staged_input_output or work_dir / "staged-input.yaml"
        json_output = args.json_output or work_dir / "staged-output.json"
        json_output.parent.mkdir(parents=True, exist_ok=True)

        build_staged_input(args.input, staged_input)
        run_decide(args.script, staged_input, json_output)
        result = json.loads(json_output.read_text(encoding="utf-8"))
        failures = check_staged_contract(result)

    if failures:
        for failure in failures:
            print(f"✗ {failure}", file=sys.stderr)
        return 1
    print(
        "✓ numeric cap contract holds: tCPA "
        f"{STAGED_TARGET_CPA}, raw candidate 5.0, 20% cap → "
        "2.4 (STAGED_OPTIMIZATION, read-only)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
