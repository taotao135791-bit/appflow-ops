"""Packaging, routing, and documentation contracts for UAC Experiment Loop."""

from __future__ import annotations

import json


def _read(repo_root, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def test_uac_triggers_route_before_generic_google(repo_root):
    router = _read(repo_root, "skills/appflow/SKILL.md")
    app_row = "| UAC, Google App campaigns, 应用安装/应用内行为广告, App tCPA/tROAS | `ads-google-app` |"
    google_row = "| Google Ads, Search, PMax, AI Max, broad match | `ads-google` |"
    assert app_row in router
    assert router.index(app_row) < router.index(google_row)

    description = _read(repo_root, "skills/ads-google-app/SKILL.md").split("---", 2)[1]
    for trigger in [
        "/appflow decide",
        "AC2.0",
        "AC2.5",
        "AC3.0",
        "UAC",
        "Google UAC",
        "App campaign",
        "Google App campaigns",
        "应用安装广告",
        "应用内行为广告",
        "tCPA App campaign",
        "tROAS App campaign",
        "Google 应用广告",
    ]:
        assert trigger in description


def test_uac_assets_and_scripts_are_installed(repo_root):
    shell = _read(repo_root, "install.sh")
    powershell = _read(repo_root, "install.ps1")
    for extension in ["*.md", "*.yaml", "*.yml", "*.json"]:
        assert extension in shell
    for extension in ["'.md'", "'.yaml'", "'.yml'", "'.json'"]:
        assert extension in powershell
    assert 'cp "${TEMP_DIR}/appflow-ops/scripts/"*.py' in shell
    assert 'Copy-Item (Join-Path $ScriptsSource "*.py")' in powershell
    assert "find \"${skill_dir}references\" -type f -name '*.md' -print0" in shell
    assert "Get-ChildItem -LiteralPath $SubskillReferences -File -Recurse" in powershell
    assert "$_.Extension -eq '.md' -and -not $_.LinkType" in powershell


def test_uac_natural_language_workflow_contract(repo_root):
    workflow_path = (
        repo_root / "skills" / "ads-google-app" / "references" / "agent-workflow.md"
    )
    assert workflow_path.is_file()
    workflow = workflow_path.read_text(encoding="utf-8")

    for heading in [
        "Intent 0: make a Quick Decision",
        "Intent 1: initialize a UAC project",
        "Intent 2: analyze the current period",
        "Intent 3: create an experiment draft",
        "Intent 4: record actual execution",
        "Intent 5: review the current experiment",
    ]:
        assert heading in workflow

    for command in [
        "decide",
        "init-workspace",
        "normalize",
        "doctor --workspace",
        "analyze",
        "validate-ledger",
        "review-ledger",
        "--append-experiment",
    ]:
        assert command in workflow

    assert "Do not write it to the ledger yet." in workflow
    assert "two different gates" in workflow
    assert "unfinished experiment" in workflow
    assert "YAML, schemas, or CLI syntax" in workflow

    skill = _read(repo_root, "skills/ads-google-app/SKILL.md")
    router = _read(repo_root, "skills/appflow/SKILL.md")
    assert "references/agent-workflow.md" in skill
    assert "references/quick-ops.md" in skill
    assert "references/agent-workflow.md" in router
    assert "references/quick-ops.md" in router
    assert "Do not append it to the ledger" in workflow


def test_readmes_document_capability_maturity_without_equating_platforms(repo_root):
    readme = _read(repo_root, "README.md")
    readme_en = _read(repo_root, "README.en.md")

    assert "确定性" in readme
    assert "deterministic" in readme_en

    assert "没有与 UAC 等价的确定性实验引擎" in readme
    assert "no deterministic experiment engine equivalent to UAC" in readme_en
    assert "## 边界（不会做的事）" in readme
    assert "## Boundaries (What It Will Not Do)" in readme_en


def test_operator_docs_prefer_private_workspace_without_hiding_stop_condition(
    repo_root,
):
    documents = [
        _read(repo_root, "README.md"),
        _read(repo_root, "README.en.md"),
        _read(repo_root, "QUICKSTART.zh-CN.md"),
        _read(repo_root, "QUICKSTART.en.md"),
    ]
    for document in documents:
        for command in [
            "init-workspace",
            "normalize --workspace",
            "doctor --workspace",
            "analyze --workspace",
        ]:
            assert command in document
        assert "draft" in document.lower()


def test_uac_version_and_docs_are_present(repo_root):
    manifest = json.loads(_read(repo_root, "appflow.plugin.json"))
    version = _read(repo_root, "VERSION").strip()
    assert manifest["version"] == version == "3.1.0"
    assert "UAC" in _read(repo_root, "README.md")
    assert "UAC" in _read(repo_root, "README.en.md")
    assert f"## {version}" in _read(repo_root, "CHANGELOG.md")
    assert f"AppFlowOps/{version}" in _read(repo_root, "scripts/fetch_page.py")
    assert f'__version__ = "{version}"' in _read(
        repo_root, "scripts/generate_report.py"
    )


def test_uac_schema_template_and_example_set_is_complete(repo_root):
    assets = repo_root / "skills" / "ads-google-app" / "assets"
    expected = {
        "UAC-INPUT.example.yaml",
        "UAC-QUICK-OPS.example.yaml",
        "UAC-QUICK-NUMERIC.example.yaml",
        "ADS-EXPERIMENTS.minimal.yaml",
        "ADS-EXPERIMENTS.full.yaml",
        "ADS-EXPERIMENTS.example.yaml",
        "uac-analysis.schema.json",
        "uac-quick-decision.schema.json",
        "ads-experiments.schema.json",
        "ads-experiments-v1.0.schema.json",
    }
    assert expected.issubset({path.name for path in assets.iterdir()})


def test_ci_installer_smoke_covers_numeric_quick_decision_package(repo_root):
    workflow = _read(repo_root, ".github/workflows/ci.yml")

    # The required-file list lives in the shared CI layout check, which the
    # installer smoke runs on both Unix and Windows.
    assert workflow.count("scripts/ci/check_install_layout.py") >= 2
    install_layout = _read(repo_root, "scripts/ci/check_install_layout.py")
    for installed_artifact in [
        "UAC-QUICK-NUMERIC.example.yaml",
        "scripts/appflow_ops/uac/signals.py",
        "scripts/appflow_ops/uac/numeric_decision.py",
        "scripts/appflow_ops/uac/policy_loader.py",
        "scripts/appflow_ops/uac/policies/uac-heuristic-policy.schema.json",
        "scripts/appflow_ops/uac/policies/uac-numeric-policy-v1.yaml",
        "scripts/appflow_ops/uac/policies/uac-signal-policy-v1.yaml",
    ]:
        assert installed_artifact in install_layout

    assert workflow.count("UAC-QUICK-NUMERIC.example.yaml") >= 3
    assert "scripts/ci/check_uac_decide_output.py" in workflow
    assert "scripts/ci/check_numeric_cap.py" in workflow

    # The numeric Quick Decision contract itself lives in the CI scripts.
    decide_check = _read(repo_root, "scripts/ci/check_uac_decide_output.py")
    assert "decide output is not deterministic" in decide_check
    assert "has_numeric_evidence" in decide_check
    assert "uac-numeric-policy-v1" in decide_check

    numeric_cap = _read(repo_root, "scripts/ci/check_numeric_cap.py")
    assert "STAGED_OPTIMIZATION" in numeric_cap
    assert "REQUIRES_FRESH_REVIEW" in numeric_cap
