"""Packaging and install-quality regression tests."""

from __future__ import annotations

import json
import re


def _read(repo_root, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def test_runtime_version_strings_stay_in_sync(repo_root):
    manifest = json.loads(_read(repo_root, "appflow.plugin.json"))
    version = _read(repo_root, "VERSION").strip()

    report = _read(repo_root, "scripts/generate_report.py")
    fetch_page = _read(repo_root, "scripts/fetch_page.py")

    assert manifest["version"] == version
    assert f'__version__ = "{version}"' in report
    assert f"AppFlowOps/{version}" in fetch_page
    assert "github.com/taotao135791-bit/appflow-ops" in fetch_page
    assert "github.com/taotao135791-bit/appflow-ops" in report

    # Every fixed-version install pin must match VERSION, so a release can
    # never ship with README still installing an older tag.
    for name in (
        "README.md",
        "README.en.md",
        "QUICKSTART.zh-CN.md",
        "QUICKSTART.en.md",
    ):
        text = _read(repo_root, name)
        pins = [
            line for line in text.splitlines() if "--ref=v" in line or "-Ref v" in line
        ]
        assert pins, f"{name} has no fixed-version install pin"
        for pin in pins:
            assert f"v{version}" in pin, f"{name} pins an older tag: {pin.strip()}"


def test_installer_uses_local_venv_without_breaking_system_packages(repo_root):
    install_sh = _read(repo_root, "install.sh")
    install_ps1 = _read(repo_root, "install.ps1")

    assert "--break-system-packages" not in install_sh
    assert "--break-system-packages" not in install_ps1
    assert "python3 -m venv" in install_sh
    assert "-m venv" in install_ps1
    assert ".venv" in install_sh
    assert ".venv" in install_ps1


def test_docs_describe_slash_entries_as_routing_shorthand(repo_root):
    router = _read(repo_root, "skills/appflow/SKILL.md")
    install_sh = _read(repo_root, "install.sh")

    assert "Users do not need slash commands" in router
    assert "Ask naturally" in install_sh
    assert "Run commands" not in install_sh


def test_reference_paths_have_installed_fallbacks(repo_root):
    skill_files = sorted((repo_root / "skills").glob("*/SKILL.md"))
    agent_files = sorted((repo_root / "agents").glob("*.md"))
    failures: list[str] = []

    for path in skill_files + agent_files:
        text = path.read_text(encoding="utf-8")
        if "appflow/references/" not in text or "## Reference Resolution" not in text:
            continue
        required = [
            "## Reference Resolution",
            "${APPFLOW_SKILL_DIR}/../appflow/references/<file>.md",
            "~/.appflow/skills/appflow/references/<file>.md",
            "~/.agents/skills/appflow/references/<file>.md",
            "appflow/references/<file>.md",
        ]
        missing = [phrase for phrase in required if phrase not in text]
        if missing:
            failures.append(f"{path.relative_to(repo_root)} missing {missing}")

    assert not failures, "shared reference path fallbacks missing:\n" + "\n".join(
        failures
    )


def test_gitignore_blocks_generated_python_cache(repo_root):
    gitignore = _read(repo_root, ".gitignore")
    assert "__pycache__/" in gitignore
    assert re.search(r"^\*\.py\[cod\]$", gitignore, re.MULTILINE)


def test_private_dashboard_tool_gate_keeps_safety_rules(repo_root):
    files = [
        "appflow/SKILL.md",
        "skills/appflow/SKILL.md",
        "appflow/references/orchestrator.md",
        "skills/appflow/references/orchestrator.md",
    ]
    required = [
        "MUST NOT use any headless or scripted browser automation",
        "screenshot scripts",
        "page HTML extraction",
        "network scraping",
        "against logged-in dashboards",
        "scripts/fetch_page.py",
    ]

    failures: list[str] = []
    for relative_path in files:
        # Normalize line wrapping so structural phrases match across
        # differently reflowed Markdown copies.
        text = re.sub(r"\s+", " ", _read(repo_root, relative_path))
        missing = [phrase for phrase in required if phrase not in text]
        if missing:
            failures.append(f"{relative_path} missing {missing}")

    assert not failures, "private dashboard tool gate softened:\n" + "\n".join(failures)
