"""Create bounded local workspaces for VIPER run attempts."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path

from .ids import RunId


class WorkspaceError(RuntimeError):
    """Report an unsafe path or conflicting attempt workspace."""


@dataclass(frozen=True)
class RunWorkspaceLock:
    """Hold advisory ownership while one coordinator allocates and runs attempts."""

    path: Path
    _descriptor: int | None = None

    @classmethod
    def for_run(cls, workspace_root: Path, run_id: RunId) -> RunWorkspaceLock:
        """Select the persistent lock file for one run identity."""
        return cls(workspace_root.resolve() / str(run_id) / ".active.lock")

    def acquire(self) -> None:
        """Acquire the run lock without waiting for another coordinator."""
        if self._descriptor is not None:
            raise WorkspaceError("run workspace already has an active owner")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise WorkspaceError("run workspace already has an active owner") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode())
        os.fsync(descriptor)
        object.__setattr__(self, "_descriptor", descriptor)

    def release(self) -> None:
        """Release this coordinator's run lock."""
        descriptor = self._descriptor
        if descriptor is None:
            return
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        object.__setattr__(self, "_descriptor", None)


@dataclass(frozen=True)
class AttemptWorkspace:
    """Identify every writable directory owned by one local run attempt."""

    root: Path
    control: Path
    source: Path
    inputs: Path
    stages: Path
    measurements: Path
    logs: Path
    terminal: Path
    lock: Path
    _lock_descriptor: int | None = None

    @classmethod
    def create(
        cls,
        workspace_root: Path,
        run_id: RunId,
        attempt_id: int,
    ) -> AttemptWorkspace:
        """Create the canonical directory set for one attempt."""
        if attempt_id < 1:
            raise WorkspaceError("attempt_id must be positive")
        root = workspace_root.resolve() / str(run_id) / f"attempt-{attempt_id}"
        root.mkdir(parents=True, exist_ok=True)
        workspace = cls(
            root=root,
            control=root / "control",
            source=root / "source",
            inputs=root / "inputs",
            stages=root / "stages",
            measurements=root / "measurements",
            logs=root / "logs",
            terminal=root / "resolved.yaml",
            lock=root.parent / ".active.lock",
        )
        for directory in (
            workspace.control,
            workspace.source,
            workspace.inputs,
            workspace.stages,
            workspace.measurements,
            workspace.logs,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return workspace

    def resolve(self, relative_path: str) -> Path:
        """Resolve one relative path beneath this attempt root."""
        if Path(relative_path).is_absolute():
            raise WorkspaceError("workspace path must be relative")
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise WorkspaceError("workspace path escapes the attempt root")
        return candidate

    def acquire(self) -> None:
        """Acquire operating-system-managed ownership of the run workspace."""
        if self._lock_descriptor is not None:
            raise WorkspaceError("run workspace already has an active owner")
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.lock,
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise WorkspaceError("run workspace already has an active owner") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode())
        os.fsync(descriptor)
        object.__setattr__(self, "_lock_descriptor", descriptor)

    def release(self) -> None:
        """Release this process's advisory run-workspace lock."""
        descriptor = self._lock_descriptor
        if descriptor is None:
            return
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        object.__setattr__(self, "_lock_descriptor", None)


def next_attempt_id(workspace_root: Path, run_id: RunId) -> int:
    """Return one greater than every durable local attempt directory."""
    run_root = workspace_root.resolve() / str(run_id)
    attempt_ids: list[int] = []
    if run_root.is_dir():
        for path in run_root.iterdir():
            if not path.is_dir() or not path.name.startswith("attempt-"):
                continue
            suffix = path.name.removeprefix("attempt-")
            if suffix.isdecimal() and int(suffix) >= 1:
                attempt_ids.append(int(suffix))
    return max(attempt_ids, default=0) + 1
