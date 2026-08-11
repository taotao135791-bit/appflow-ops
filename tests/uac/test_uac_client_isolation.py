"""Client/account/business isolation contracts for agency workspaces."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from appflow_ops.uac.types import ContractError
from appflow_ops.uac.workspace import (
    Workspace,
    initialize_workspace,
    reject_cross_workspace_reference,
)


def _script(repo_root: Path) -> Path:
    return repo_root / "scripts" / "uac_experiment.py"


def _run(
    repo_root: Path, *arguments: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_script(repo_root)), *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_init_workspace_with_client_creates_nested_isolated_layout(
    repo_root: Path, tmp_path: Path
) -> None:
    completed = _run(
        repo_root,
        "init-workspace",
        "ios-main",
        "--client",
        "acme",
        "--root",
        str(tmp_path),
        cwd=repo_root,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    workspace_root = tmp_path / "acme" / "ios-main"
    assert Workspace.at(workspace_root).initialized
    assert "one workspace = one client" in completed.stdout

    context = yaml.safe_load(
        (workspace_root / "project-context.yaml").read_text(encoding="utf-8")
    )
    assert context["project"]["client_label"] == "acme"
    assert context["project"]["business_line"] == "app_promotion"
    assert (workspace_root / "reports" / "client").is_dir()


def test_cli_init_workspace_rejects_client_equal_to_project_name(
    repo_root: Path, tmp_path: Path
) -> None:
    completed = _run(
        repo_root,
        "init-workspace",
        "acme",
        "--client",
        "acme",
        "--root",
        str(tmp_path),
        cwd=repo_root,
    )
    assert completed.returncode != 0
    assert not (tmp_path / "acme" / "acme").exists()


def test_legacy_flat_workspace_layout_still_initializes(tmp_path: Path) -> None:
    workspace = initialize_workspace("legacy-project", base_dir=tmp_path)
    assert workspace.initialized
    assert workspace.root == (tmp_path / "legacy-project").resolve()
    context = yaml.safe_load(workspace.context_path.read_text(encoding="utf-8"))
    assert context["project"]["client_label"] is None


def test_cross_client_workspace_reference_is_rejected(tmp_path: Path) -> None:
    client_a = initialize_workspace("project-a", base_dir=tmp_path, client_label="acme")
    client_b = initialize_workspace(
        "project-b", base_dir=tmp_path, client_label="globex"
    )

    internal = client_a.input_dir / "note.txt"
    internal.write_text("internal\n", encoding="utf-8")
    assert (
        reject_cross_workspace_reference(client_a, internal, "note")
        == internal.resolve()
    )

    with pytest.raises(ContractError):
        reject_cross_workspace_reference(
            client_a, client_b.ledger_path, "other client ledger"
        )
    with pytest.raises(ContractError):
        reject_cross_workspace_reference(
            client_a, client_b.context_path, "other client context"
        )


def test_two_clients_can_hold_the_same_project_name(tmp_path: Path) -> None:
    acme = initialize_workspace("main", base_dir=tmp_path, client_label="acme")
    globex = initialize_workspace("main", base_dir=tmp_path, client_label="globex")
    assert acme.root != globex.root
    assert acme.initialized and globex.initialized
