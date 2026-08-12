"""Workspace-local exclusive lock shared by state writes and metadata
migration.

One lock file per workspace; concurrent runs of different workspaces never
touch each other's lock. POSIX ``flock`` / Windows ``msvcrt``.

Lock ordering (docs/account-state.md): workspace identity initialization
(metadata lock) always happens BEFORE any StateStore write lock, so the two
lock families are never held at the same time and ABBA deadlock is
impossible. After initialization, normal appends only take the state write
lock.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .types import ContractError

_LOCK_TIMEOUT_SECONDS = 30.0


class WorkspaceWriteLock:
    """Workspace-local exclusive lock (POSIX flock / Windows msvcrt)."""

    def __init__(self, lock_path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS) -> None:
        self.lock_path = lock_path
        self.timeout = timeout
        self._handle: Any = None

    def __enter__(self) -> WorkspaceWriteLock:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure the lock file exists with at least one byte so msvcrt can
        # lock a byte range on Windows. Exclusive-create is atomic: exactly
        # one writer initializes the byte, so no thread ever writes into a
        # byte range another thread has already locked (which would raise
        # PermissionError on Windows).
        try:
            descriptor = os.open(
                self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except OSError:
            pass  # already exists (or created by a concurrent writer)
        else:
            try:
                os.write(descriptor, b"\0")
            finally:
                os.close(descriptor)
        handle = open(self.lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise ContractError(
                                f"state write lock timed out: {self.lock_path}"
                            ) from None
                        time.sleep(0.02)
            else:
                import fcntl

                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise ContractError(
                                f"state write lock timed out: {self.lock_path}"
                            ) from None
                        time.sleep(0.02)
        except Exception:
            handle.close()
            raise
        self._handle = handle
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
