#!/usr/bin/env python3
"""Assert the stable UAC Quick Decision contract on `decide` JSON output.

Two ways to obtain the output under test:

* Pass an existing JSON file with ``--json PATH`` (the CLI was already run).
* Pass a UAC input YAML as the positional argument to run the ``decide`` CLI
  first (``--script`` selects which ``uac_experiment.py`` to invoke, e.g. an
  installed copy during installer smoke tests).

Profiles:

* ``quick-ops``: mode/read-only contract for UAC-QUICK-OPS style inputs.
* ``numeric``:   the stable numeric-evidence contract of
  ``skills/ads-google-app/assets/UAC-QUICK-NUMERIC.example.yaml``.

Usage:
    python scripts/ci/check_uac_decide_output.py \
        skills/ads-google-app/assets/UAC-QUICK-NUMERIC.example.yaml \
        --profile numeric --determinism \
        --json-output out/a.json --determinism-output out/b.json

    python scripts/ci/check_uac_decide_output.py \
        --json out/uac-quick-decision.json --profile quick-ops \
        --markdown out/uac-quick-decision.md
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
DEFAULT_SCRIPT = REPO_ROOT / "scripts" / "uac_experiment.py"
CONCLUSION_PREFIX = "结论："


def _dig(result: dict, dotted_path: str, failures: list[str]):
    """Walk a dotted key path, recording a failure instead of raising."""
    node = result
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            failures.append(f"missing key '{dotted_path}' in decide output")
            return None
        node = node[key]
    return node


def _expect(failures: list[str], result: dict, dotted_path: str, expected) -> None:
    actual = _dig(result, dotted_path, failures)
    if isinstance(expected, bool):
        if actual is not expected:
            failures.append(f"{dotted_path}: expected {expected}, got {actual!r}")
    elif actual != expected:
        failures.append(f"{dotted_path}: expected {expected!r}, got {actual!r}")


def check_decide_contract(result: dict, profile: str) -> list[str]:
    """Return a list of human-readable contract violations (empty = pass)."""
    failures: list[str] = []
    _expect(failures, result, "mode", "quick_decision")
    _expect(failures, result, "account_write", False)
    _expect(failures, result, "ledger_write", False)
    if profile == "numeric":
        _expect(failures, result, "derived_signals.has_numeric_evidence", True)
        _expect(
            failures,
            result,
            "constraint_analysis.primary_constraint",
            "TARGET_LIKELY_TOO_TIGHT",
        )
        _expect(
            failures, result, "target_recommendation.recommended_action", "INCREASE"
        )
        _expect(failures, result, "target_recommendation.recommended_value", 5.5)
        _expect(
            failures,
            result,
            "target_recommendation.numeric_safety.operation_classification",
            "NORMAL_OPTIMIZATION",
        )
        _expect(
            failures,
            result,
            "target_recommendation.numeric_safety.policy_version",
            "uac-numeric-policy-v1",
        )
        _expect(
            failures,
            result,
            "policy.numeric.policy_version",
            "uac-numeric-policy-v1",
        )
        _expect(
            failures,
            result,
            "policy.signal.policy_version",
            "uac-signal-policy-v1",
        )
        _expect(
            failures,
            result,
            "budget_recommendation.recommended_action",
            "NO_CHANGE",
        )
        if not result.get("calculation_evidence"):
            failures.append("calculation_evidence: expected a non-empty evidence list")
    return failures


def check_markdown_conclusion(markdown_path: Path) -> list[str]:
    """Assert the Quick Decision card carries a 结论： line."""
    if not markdown_path.is_file():
        return [f"markdown output not found: {markdown_path}"]
    text = markdown_path.read_text(encoding="utf-8")
    if not any(line.startswith(CONCLUSION_PREFIX) for line in text.splitlines()):
        return [
            (
                f"{markdown_path}: no line starts with "
                f"'{CONCLUSION_PREFIX}' (Quick Decision card contract)"
            )
        ]
    return []


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="UAC input YAML to run through the decide CLI (omit with --json)",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT,
        help="uac_experiment.py to invoke (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        help="existing decide JSON output to check instead of running the CLI",
    )
    parser.add_argument(
        "--profile",
        choices=["quick-ops", "numeric"],
        required=True,
        help="which stable output contract to assert",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="existing Markdown decision card to check for the 结论： line",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="where the CLI writes JSON when running (default: temp file)",
    )
    parser.add_argument(
        "--determinism",
        action="store_true",
        help="run the CLI a second time and require byte-identical JSON",
    )
    parser.add_argument(
        "--determinism-output",
        type=Path,
        help="where the determinism re-run writes JSON (default: temp file)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.input is not None and args.json_path is not None:
        raise SystemExit("pass either an input YAML or --json, not both")
    if args.input is None and args.json_path is None:
        raise SystemExit("pass an input YAML or --json PATH")

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="uac-decide-check-") as temp_dir:
        temp = Path(temp_dir)
        if args.json_path is not None:
            json_path = args.json_path
            if not json_path.is_file():
                raise SystemExit(f"decide JSON output not found: {json_path}")
        else:
            if not args.script.is_file():
                raise SystemExit(f"decide CLI script not found: {args.script}")
            json_path = args.json_output or temp / "decide-output.json"
            json_path.parent.mkdir(parents=True, exist_ok=True)
            run_decide(args.script, args.input, json_path)
            if args.determinism:
                rerun_path = args.determinism_output or temp / "decide-rerun.json"
                rerun_path.parent.mkdir(parents=True, exist_ok=True)
                run_decide(args.script, args.input, rerun_path)
                if json_path.read_bytes() != rerun_path.read_bytes():
                    failures.append(
                        "decide output is not deterministic: "
                        f"{json_path} differs from {rerun_path}"
                    )
        result = json.loads(json_path.read_text(encoding="utf-8"))
        failures.extend(check_decide_contract(result, args.profile))
        if args.markdown is not None:
            failures.extend(check_markdown_conclusion(args.markdown))
    _report(failures, args.profile, json_path)
    return 1 if failures else 0


def _report(failures: list[str], profile: str, json_path: Path) -> None:
    if failures:
        for failure in failures:
            print(f"✗ {failure}", file=sys.stderr)
        return
    print(f"✓ decide output contract '{profile}' holds: {json_path}")


if __name__ == "__main__":
    raise SystemExit(main())
