#!/usr/bin/env python3
"""Verify the installed AppFlow Ops layout after install.sh / install.ps1.

This is the single source of truth for the installer-smoke required-file
list, shared by the Unix and Windows CI steps. It checks that the main
skill, sub-skills, scripts (including the ``appflow_ops`` package), references,
and agent persona briefs all landed where the installers promise to put them.

Usage:
    python scripts/ci/check_install_layout.py \
        --skill-dir "${RUNNER_TEMP}/appflow-ops-skills" \
        --agents-dir "${RUNNER_TEMP}/appflow-ops-agents"

``--agents-dir`` is the separate agent install root used by hosts such as
cursor/codex. Omit it for the local layout, where persona briefs live
inside the main skill at ``<skill-dir>/ads/agents``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252; keep the ✓/✗ markers from crashing CI.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REQUIRED_SKILL_FILES = [
    "ads/SKILL.md",
    "ads/VERSION",
    "ads/references/reasoning-contract.md",
    "ads/scripts/uac_experiment.py",
    "ads/scripts/appflow_ops/uac/engine.py",
    "ads/scripts/appflow_ops/uac/quick_ops.py",
    "ads/scripts/appflow_ops/uac/signals.py",
    "ads/scripts/appflow_ops/uac/numeric_decision.py",
    "ads/scripts/appflow_ops/uac/policy_loader.py",
    "ads/scripts/appflow_ops/uac/policies/uac-heuristic-policy.schema.json",
    "ads/scripts/appflow_ops/uac/policies/uac-numeric-policy-v1.yaml",
    "ads/scripts/appflow_ops/uac/policies/uac-signal-policy-v1.yaml",
    "ads-google-app/SKILL.md",
    "ads-google-app/assets/UAC-INPUT.example.yaml",
    "ads-google-app/assets/UAC-QUICK-OPS.example.yaml",
    "ads-google-app/assets/UAC-QUICK-NUMERIC.example.yaml",
    "ads-google-app/assets/ads-experiments.schema.json",
    "ads-google-app/assets/uac-quick-decision.schema.json",
    "ads-google-app/references/agent-workflow.md",
    "ads-google-app/references/quick-ops.md",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        required=True,
        help="skill install root passed to the installer (contains ads/ etc.)",
    )
    parser.add_argument(
        "--agents-dir",
        type=Path,
        help="separate agent install root; omit for the in-skill agents layout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    skill_dir = args.skill_dir
    failures: list[str] = []

    if not skill_dir.is_dir():
        raise SystemExit(f"skill install root not found: {skill_dir}")

    for relative in REQUIRED_SKILL_FILES:
        if not (skill_dir / relative).is_file():
            failures.append(f"missing installed artifact: {skill_dir / relative}")

    reference_files = sorted((skill_dir / "ads" / "references").glob("*.md"))
    if not reference_files:
        failures.append(
            f"no Markdown reference files under {skill_dir / 'ads' / 'references'}"
        )

    agents_dir = args.agents_dir or skill_dir / "ads" / "agents"
    agent_files = sorted(agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    if not agent_files:
        failures.append(f"no agent persona briefs (*.md) under {agents_dir}")

    sub_skills = sorted(
        path
        for path in skill_dir.glob("ads-*")
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    if not sub_skills:
        failures.append(f"no installed sub-skills (ads-*/SKILL.md) under {skill_dir}")

    if failures:
        for failure in failures:
            print(f"✗ {failure}", file=sys.stderr)
        return 1
    print(
        "✓ installed layout OK: "
        f"{len(REQUIRED_SKILL_FILES)} required files, "
        f"{len(sub_skills)} sub-skills, "
        f"{len(reference_files)} reference files, "
        f"{len(agent_files)} agent briefs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
