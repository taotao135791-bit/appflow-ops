"""Private, local-first workspace layout for real UAC account data."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import _dump
from .types import CURRENT_LEDGER_SCHEMA_VERSION, ContractError

WORKSPACE_DIRECTORY_NAMES = (
    "input",
    "normalized",
    "analysis",
    "experiments",
    "reports",
    "replays",
)
WORKSPACE_CONTEXT_NAME = "project-context.yaml"
WORKSPACE_LEDGER_NAME = "ADS-EXPERIMENTS.yaml"
WORKSPACE_INPUT_NAME = "UAC-INPUT.yaml"
WORKSPACE_INPUT_DRAFT_NAME = "UAC-INPUT.draft.yaml"
WORKSPACE_ANALYSIS_NAME = "UAC-ANALYSIS.json"
WORKSPACE_REPORT_NAME = "UAC-REPORT.md"
WORKSPACE_QUICK_DECISION_NAME = "UAC-QUICK-DECISION.json"
WORKSPACE_QUICK_REPORT_NAME = "UAC-QUICK-DECISION.md"
WORKSPACE_NORMALIZATION_REPORT_NAME = "NORMALIZATION.json"

_CASE_NAMES = ("UAC-INPUT.yaml", "UAC-INPUT.yml", "UAC-INPUT.json")
_LEDGER_NAMES = (
    "ADS-EXPERIMENTS.yaml",
    "ADS-EXPERIMENTS.yml",
    "ADS-EXPERIMENTS.json",
)
_NORMALIZATION_SUFFIXES = {".csv", ".json", ".yaml", ".yml"}
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_INVALID_WINDOWS_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def validate_workspace_name(name: str) -> str:
    """Return a portable project directory name or fail before writing."""

    cleaned = name.strip()
    if not cleaned:
        raise ContractError("workspace name must be non-empty")
    if cleaned in {".", ".."}:
        raise ContractError("workspace name must not be . or ..")
    if len(cleaned) > 100:
        raise ContractError("workspace name must be at most 100 characters")
    if _INVALID_WINDOWS_NAME.search(cleaned):
        raise ContractError(
            "workspace name contains a path separator or a character unsupported on Windows"
        )
    if cleaned.endswith((" ", ".")):
        raise ContractError("workspace name must not end with a space or period")
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ContractError("workspace name is reserved on Windows")
    return cleaned


def _only_existing(paths: tuple[Path, ...], description: str) -> Path | None:
    symbolic_links = tuple(path for path in paths if path.is_symlink())
    if symbolic_links:
        rendered = ", ".join(path.name for path in symbolic_links)
        raise ContractError(f"{description} must not be a symbolic link ({rendered})")
    matches = tuple(path.resolve() for path in paths if path.is_file())
    if len(matches) > 1:
        rendered = ", ".join(path.name for path in matches)
        raise ContractError(
            f"multiple {description} files found ({rendered}); select one explicitly"
        )
    return matches[0] if matches else None


@dataclass(frozen=True)
class Workspace:
    """Absolute paths for one private account workspace."""

    root: Path

    @classmethod
    def at(cls, path: Path) -> Workspace:
        expanded = path.expanduser()
        absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
        absolute = Path(os.path.abspath(absolute))
        if absolute.parent == absolute:
            return cls(absolute)
        return cls(absolute.parent.resolve(strict=False) / absolute.name)

    @property
    def context_path(self) -> Path:
        return self.root / WORKSPACE_CONTEXT_NAME

    @property
    def gitignore_path(self) -> Path:
        return self.root / ".gitignore"

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def normalized_dir(self) -> Path:
        return self.root / "normalized"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def client_reports_dir(self) -> Path:
        """Client-facing deliverables live here, separate from internal reports."""

        return self.root / "reports" / "client"

    @property
    def replays_dir(self) -> Path:
        return self.root / "replays"

    @property
    def normalized_input_path(self) -> Path:
        return self.normalized_dir / WORKSPACE_INPUT_NAME

    @property
    def normalized_input_draft_path(self) -> Path:
        return self.normalized_dir / WORKSPACE_INPUT_DRAFT_NAME

    @property
    def normalization_report_path(self) -> Path:
        return self.normalized_dir / WORKSPACE_NORMALIZATION_REPORT_NAME

    @property
    def analysis_path(self) -> Path:
        return self.analysis_dir / WORKSPACE_ANALYSIS_NAME

    @property
    def quick_decision_path(self) -> Path:
        return self.analysis_dir / WORKSPACE_QUICK_DECISION_NAME

    @property
    def report_path(self) -> Path:
        return self.reports_dir / WORKSPACE_REPORT_NAME

    @property
    def quick_decision_report_path(self) -> Path:
        return self.reports_dir / WORKSPACE_QUICK_REPORT_NAME

    @property
    def ledger_path(self) -> Path:
        return self.experiments_dir / WORKSPACE_LEDGER_NAME

    @property
    def initialized(self) -> bool:
        required_directories = tuple(
            self.root / name for name in WORKSPACE_DIRECTORY_NAMES
        )
        required_files = (self.gitignore_path, self.context_path, self.ledger_path)
        return (
            self.root.is_dir()
            and not self.root.is_symlink()
            and all(
                path.is_dir() and not path.is_symlink() and self._is_contained(path)
                for path in required_directories
            )
            and all(
                path.is_file() and not path.is_symlink() and self._is_contained(path)
                for path in required_files
            )
            and self._privacy_ignore_is_active()
        )

    def _privacy_ignore_is_active(self) -> bool:
        try:
            rules = [
                line.strip()
                for line in self.gitignore_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        except (OSError, UnicodeError):
            return False
        return rules == ["*", "!.gitignore"]

    def _is_contained(self, path: Path) -> bool:
        try:
            path.expanduser().resolve(strict=False).relative_to(
                self.root.resolve(strict=False)
            )
        except (OSError, RuntimeError, ValueError):
            return False
        return True

    def require_contained_path(self, path: Path, description: str) -> Path:
        """Resolve one workspace path and reject symlink or traversal escapes."""

        if self.root.is_symlink():
            raise ContractError("workspace root must not be a symbolic link")
        expanded = path.expanduser()
        candidate = expanded if expanded.is_absolute() else Path.cwd() / expanded
        candidate = Path(os.path.abspath(candidate))
        resolved_root = self.root.resolve(strict=False)
        current = candidate
        while current.parent != current:
            if current.is_symlink():
                try:
                    current.parent.resolve(strict=False).relative_to(resolved_root)
                except ValueError:
                    pass
                else:
                    raise ContractError(f"{description} must not use a symbolic link")
            current = current.parent
        try:
            relative = candidate.resolve(strict=False).relative_to(resolved_root)
        except ValueError as exc:
            raise ContractError(
                f"{description} must stay inside the private workspace"
            ) from exc

        contained = self.root / relative
        if not self._is_contained(contained):
            raise ContractError(f"{description} must stay inside the private workspace")
        return contained

    def require_initialized(self) -> None:
        if not self.initialized:
            raise ContractError(
                f"workspace is not initialized: {self.root}; run init-workspace first"
            )

    def protect_file(self, path: Path) -> None:
        """Apply private permissions to a file only when it belongs to this workspace."""

        contained = self.require_contained_path(path, "private output")
        _best_effort_chmod(contained, 0o600)

    def discover_case(self) -> Path | None:
        """Prefer normalized input, then private raw input, then a legacy root file."""

        if self.normalization_report_path.is_file():
            try:
                envelope = json.loads(
                    self.normalization_report_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError):
                return None
            if (
                not isinstance(envelope, dict)
                or envelope.get("analysis_ready") is not True
            ):
                completed = _only_existing(
                    tuple(self.normalized_dir / name for name in _CASE_NAMES),
                    "UAC input",
                )
                if completed is None:
                    return None
                blocked_digest = envelope.get("blocked_ready_input_sha256")
                current_digest = _file_sha256(completed)
                if (
                    "blocked_ready_input_sha256" in envelope
                    and current_digest is not None
                    and current_digest != blocked_digest
                ):
                    return completed
                if "blocked_ready_input_sha256" in envelope:
                    return None
                try:
                    completed_after_envelope = (
                        completed.stat().st_mtime_ns
                        > self.normalization_report_path.stat().st_mtime_ns
                    )
                except OSError:
                    return None
                if not completed_after_envelope:
                    return None
                return completed
        for directory in (self.normalized_dir, self.input_dir, self.root):
            selected = _only_existing(
                tuple(directory / name for name in _CASE_NAMES), "UAC input"
            )
            if selected is not None:
                return selected
        return None

    def require_case(self) -> Path:
        selected = self.discover_case()
        if selected is None:
            raise ContractError(
                "workspace has no normalized UAC input; put one CSV/JSON/YAML summary "
                "in input/ and run normalize --workspace first"
            )
        return selected

    def discover_normalization_source(self) -> Path | None:
        """Find one explicit, non-example raw summary in ``input/``."""

        preferred = _only_existing(
            tuple(self.input_dir / name for name in _CASE_NAMES), "UAC input"
        )
        if preferred is not None:
            return preferred
        candidates = tuple(
            path
            for path in sorted(self.input_dir.iterdir())
            if path.suffix.lower() in _NORMALIZATION_SUFFIXES
            and ".example." not in path.name.lower()
            and not path.name.startswith(".")
        )
        symbolic_links = tuple(path for path in candidates if path.is_symlink())
        if symbolic_links:
            rendered = ", ".join(path.name for path in symbolic_links)
            raise ContractError(
                f"normalization input must not be a symbolic link ({rendered})"
            )
        matches = tuple(path.resolve() for path in candidates if path.is_file())
        if len(matches) > 1:
            rendered = ", ".join(path.name for path in matches)
            raise ContractError(
                "multiple raw input files found in workspace input/ "
                f"({rendered}); pass one input path explicitly"
            )
        return matches[0] if matches else None

    def require_normalization_source(self) -> Path:
        selected = self.discover_normalization_source()
        if selected is None:
            raise ContractError(
                "workspace input/ has no raw CSV, JSON, or YAML summary; add one first"
            )
        return selected

    def discover_ledger(self) -> Path | None:
        """Prefer the workspace ledger while retaining a legacy root fallback."""

        for directory in (self.experiments_dir, self.root):
            selected = _only_existing(
                tuple(directory / name for name in _LEDGER_NAMES),
                "experiment ledger",
            )
            if selected is not None:
                return selected
        return None

    def normalized_input_sha256(self) -> str | None:
        """Fingerprint the current ready input without exposing its contents."""

        return _file_sha256(self.normalized_input_path)


def is_workspace_directory(path: Path) -> bool:
    """Recognize an initialized workspace without mutating it."""

    return Workspace.at(path).initialized


def reject_cross_workspace_reference(
    workspace: Workspace, path: Path, description: str
) -> Path:
    """Resolve ``path`` and reject references into another private workspace.

    Paths inside the current workspace pass through. Any path that belongs to
    a different initialized workstation (another client or account) is a
    contract error: client and business isolation forbid cross-workspace
    reads, copies, or comparisons.
    """

    candidate = workspace.require_contained_path(path, description)
    return candidate


def workspace_migration_notice(path: Path | None) -> str | None:
    """Suggest the private layout for a supported legacy root-level filename."""

    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if resolved.name not in {*_CASE_NAMES, *_LEDGER_NAMES}:
        return None
    if resolved.parent.name in {"input", "normalized", "experiments"}:
        return None
    return (
        "migration suggestion: legacy root-level UAC files remain supported; "
        "use init-workspace and --workspace to keep real account data private"
    )


def _project_context(
    name: str, *, client_label: str | None = None, business_line: str | None = None
) -> dict[str, Any]:
    from .account_state import new_workspace_id

    return {
        "schema_version": "1.0",
        "project": {
            "name": name,
            "client_label": client_label,
            "business_line": business_line or "app_promotion",
            "platform": "google_ads",
            "campaign_type": "app_campaign",
            "account_label": None,
            "workspace_id": new_workspace_id(),
        },
        "privacy": {
            "contains_real_account_data": True,
            "commit_allowed": False,
            "anonymize_before_sharing": True,
        },
        "permissions": {
            "optimizer_can": [],
            "client_approval_required": ["budget", "bid", "creative"],
        },
        "campaign_level_glossary": {},
        "minimum_data_needed": [
            "date range and timezone",
            "country and operating system",
            "spend, installs, registrations, and payments",
            "daily budget and target CPA",
            "conversion delay and measurement reconciliation",
            "allowed and unavailable actions",
        ],
        "status": "initialized_waiting_for_data",
    }


def _raw_input_example() -> dict[str, Any]:
    return {
        "start_date": None,
        "end_date": None,
        "timezone": None,
        "country": None,
        "os": None,
        "spend": None,
        "installs": None,
        "registrations": None,
        "payments": None,
        "daily_budget": None,
        "target_cpa": None,
    }


def _best_effort_chmod(path: Path, mode: int) -> None:
    """Use private Unix permissions while remaining usable on Windows."""

    try:
        path.chmod(mode)
    except OSError:
        pass


def initialize_workspace(
    name: str,
    *,
    base_dir: Path = Path("workspaces"),
    client_label: str | None = None,
    business_line: str | None = None,
) -> Workspace:
    """Atomically create a private workstation without any real-account values.

    With ``client_label`` the layout becomes
    ``<base_dir>/<client>/<project>/`` so each client's accounts stay in
    separate, isolated trees. One workstation = one client = one business
    line; workstations must never reference each other.
    """

    safe_name = validate_workspace_name(name)
    base = base_dir.expanduser().resolve()
    if client_label is not None:
        safe_client = validate_workspace_name(client_label)
        if safe_client == safe_name:
            raise ContractError("workspace name must differ from its client label")
        target = base / safe_client / safe_name
    else:
        target = base / safe_name
    if target.exists():
        raise ContractError(
            f"workspace already exists: {target}; no existing files were changed"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{safe_name}.", dir=target.parent))
    try:
        workspace = Workspace.at(temporary)
        _best_effort_chmod(temporary, 0o700)
        for directory in WORKSPACE_DIRECTORY_NAMES:
            (temporary / directory).mkdir()
            _best_effort_chmod(temporary / directory, 0o700)
        workspace.client_reports_dir.mkdir()
        _best_effort_chmod(workspace.client_reports_dir, 0o700)
        (temporary / ".gitignore").write_text(
            "# Private advertising workspace: do not commit its contents.\n*\n!.gitignore\n",
            encoding="utf-8",
        )
        _dump(
            workspace.context_path,
            _project_context(
                safe_name,
                client_label=client_label,
                business_line=business_line,
            ),
        )
        _dump(
            workspace.input_dir / "raw-summary.example.yaml",
            _raw_input_example(),
        )
        _dump(
            workspace.ledger_path,
            {
                "schema_version": CURRENT_LEDGER_SCHEMA_VERSION,
                "project": {"name": safe_name},
                "experiments": [],
            },
        )
        for private_file in (
            temporary / ".gitignore",
            workspace.context_path,
            workspace.input_dir / "raw-summary.example.yaml",
            workspace.ledger_path,
        ):
            _best_effort_chmod(private_file, 0o600)
        os.replace(temporary, target)
    except Exception:
        for child in sorted(temporary.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        temporary.rmdir()
        raise
    return Workspace.at(target)
