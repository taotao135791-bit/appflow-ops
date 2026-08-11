"""Funnel diagnosis dashboard contracts: deterministic, self-contained, honest."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.funnel import (
    build_funnel,
    render_funnel_html,
    write_funnel_dashboard,
)


def _example_case(repo_root: Path) -> dict:
    path = repo_root / "skills" / "ads-google-app" / "assets" / "UAC-INPUT.example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_funnel_bottleneck_is_the_lowest_conversion_transition(
    repo_root: Path,
) -> None:
    case = _example_case(repo_root)
    diagnosis = build_funnel(case)

    rates = {
        conversion.to_key: conversion.rate_percent
        for conversion in diagnosis.conversions
        if conversion.rate_percent is not None
    }
    assert rates, "example case must produce conversions"
    assert diagnosis.bottleneck_key == min(rates, key=rates.get)
    assert diagnosis.spend == case["facts"]["metrics"]["spend"]
    assert diagnosis.missing == ()


def test_funnel_html_is_self_contained_and_labeled(repo_root: Path) -> None:
    diagnosis = build_funnel(_example_case(repo_root))
    html = render_funnel_html(
        diagnosis, source_label="fixture.yaml", generated_at="2026-08-11 00:00 UTC"
    )

    assert "<script" not in html
    assert "http://" not in html and "https://github" not in html
    assert "瓶颈层" in html
    assert "仅供内部诊断" in html
    assert "观察（输入事实）" in html
    assert "推断（诊断结论）" in html


def test_missing_funnel_layer_is_reported_not_invented(repo_root: Path) -> None:
    case = copy.deepcopy(_example_case(repo_root))
    del case["facts"]["metrics"]["payments"]

    diagnosis = build_funnel(case)
    assert "payments" in diagnosis.missing
    assert diagnosis.costs["cost_per_payment"] is None

    html = render_funnel_html(
        diagnosis, source_label="fixture.yaml", generated_at="2026-08-11 00:00 UTC"
    )
    assert "数据缺失" in html
    assert "补齐这些数据前" in html


def test_funnel_dashboard_cli_writes_a_private_html_file(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "funnel.html"
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "uac_experiment.py"),
            "funnel-dashboard",
            str(
                repo_root
                / "skills"
                / "ads-google-app"
                / "assets"
                / "UAC-INPUT.example.yaml"
            ),
            "--output",
            str(output),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.is_file()
    assert "internal diagnosis only" in completed.stdout
    assert "漏斗诊断看板" in output.read_text(encoding="utf-8")


def test_funnel_dashboard_workspace_output_stays_inside_workspace(
    repo_root: Path, tmp_path: Path
) -> None:
    from appflow_ops.uac.workspace import initialize_workspace

    workspace = initialize_workspace(
        "funnel-project", base_dir=tmp_path, client_label="acme"
    )
    case = _example_case(repo_root)
    input_path = workspace.normalized_dir / "UAC-INPUT.yaml"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(yaml.safe_dump(case, allow_unicode=True), encoding="utf-8")

    written = write_funnel_dashboard(workspace=workspace)
    assert written == workspace.reports_dir / "funnel-dashboard.html"
    assert written.is_file()
