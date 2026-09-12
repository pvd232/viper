"""Observe CPython file-open events during one governed stage invocation."""

from __future__ import annotations

import builtins
import io
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from types import TracebackType
from typing import Any

from ..stages import StageFileAccessReceipt


class StageFileAccessError(RuntimeError):
    """Reject a governed audit event outside the stage's declared boundary."""


_LOCK = RLock()
_ACTIVE: StageFileAccessObserver | None = None
_AUDIT_HOOK_INSTALLED = False
_BUILTIN_OPEN = builtins.open
_IO_OPEN = io.open
_OS_OPEN = os.open
_ESCAPE_EVENTS = frozenset(
    {
        "_thread.start_new_thread",
        "_posixsubprocess.fork_exec",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "os.startfile/2",
        "os.system",
        "pty.spawn",
        "subprocess.Popen",
    }
)


def _contains(root: Path, path: Path) -> bool:
    """Return whether one resolved path equals or descends from another."""
    return path == root or root in path.parents


def _access_modes(mode: object, flags: object) -> tuple[bool, bool]:
    """Translate one CPython open event into read and write operations."""
    if isinstance(mode, str):
        return "r" in mode or "+" in mode, any(value in mode for value in "wax+")
    if not isinstance(flags, int):
        return False, False
    access = flags & os.O_ACCMODE
    reads = access != os.O_WRONLY
    writes = access != os.O_RDONLY or bool(
        flags & (os.O_APPEND | os.O_CREAT | os.O_TRUNC)
    )
    return reads, writes


def _audit(event: str, arguments: tuple[object, ...]) -> None:
    """Forward auditable operations to the active stage observer."""
    observer = _ACTIVE
    if observer is not None:
        observer.observe(event, arguments)


def _install_audit_hook() -> None:
    """Install the process-wide audit hook before the first governed call."""
    global _AUDIT_HOOK_INSTALLED
    if not _AUDIT_HOOK_INSTALLED:
        sys.addaudithook(_audit)
        _AUDIT_HOOK_INSTALLED = True


def _record_successful_open(
    path: object,
    mode: object,
    flags: object,
) -> None:
    """Record an open call after its underlying operation returns."""
    observer = _ACTIVE
    if observer is not None:
        observer.record_successful_open(path, mode, flags)


def _builtin_open(*args: Any, **kwargs: Any) -> Any:
    """Call ``builtins.open`` and record a returned file object."""
    handle = _BUILTIN_OPEN(*args, **kwargs)
    try:
        path = args[0] if args else kwargs["file"]
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        _record_successful_open(path, mode, None)
    except Exception:
        handle.close()
        raise
    return handle


def _io_open(*args: Any, **kwargs: Any) -> Any:
    """Call ``io.open`` and record a returned file object."""
    handle = _IO_OPEN(*args, **kwargs)
    try:
        path = args[0] if args else kwargs["file"]
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        _record_successful_open(path, mode, None)
    except Exception:
        handle.close()
        raise
    return handle


def _os_open(*args: Any, **kwargs: Any) -> int:
    """Call ``os.open`` and record a returned file descriptor."""
    descriptor = _OS_OPEN(*args, **kwargs)
    try:
        path = args[0] if args else kwargs["path"]
        flags = args[1] if len(args) > 1 else kwargs["flags"]
        _record_successful_open(path, None, flags)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


class StageFileAccessObserver:
    """Check cooperative Python code against one stage's declared file paths."""

    def __init__(
        self,
        repository_root: Path,
        inputs: Mapping[str, Path],
        outputs: Mapping[str, Path],
        managed_writes: tuple[Path, ...] = (),
    ) -> None:
        """Resolve the paths that the stage may read and write."""
        self._root = repository_root.resolve()
        self._inputs = {name: path.resolve() for name, path in sorted(inputs.items())}
        self._outputs = tuple(path.resolve() for path in outputs.values())
        self._managed_writes = tuple(path.resolve() for path in managed_writes)
        self._runtime_roots = tuple(
            dict.fromkeys(
                Path(value).resolve()
                for value in (sys.prefix, sys.base_prefix)
                if value
            )
        )
        self._reads: set[Path] = set()
        self._writes: set[Path] = set()

    def __enter__(self) -> StageFileAccessObserver:
        """Activate this observer for the worker process."""
        global _ACTIVE
        _LOCK.acquire()
        if _ACTIVE is not None:
            _LOCK.release()
            raise StageFileAccessError("stage.file_access: observer is already active")
        _install_audit_hook()
        _ACTIVE = self
        builtins.open = _builtin_open
        io.open = _io_open
        os.open = _os_open
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Deactivate this observer and require every input on success."""
        global _ACTIVE
        builtins.open = _BUILTIN_OPEN
        io.open = _IO_OPEN
        os.open = _OS_OPEN
        _ACTIVE = None
        _LOCK.release()
        if exception_type is None:
            self.require_every_input()

    def _path(self, value: object) -> Path | None:
        """Resolve one path-bearing audit argument from the worker's root."""
        if isinstance(value, int):
            return None
        try:
            raw = os.fsdecode(value)  # type: ignore[arg-type]
        except TypeError:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    def _is_runtime_path(self, path: Path) -> bool:
        """Identify interpreter files covered by the recorded runtime environment."""
        return any(_contains(root, path) for root in self._runtime_roots)

    def _location(self, path: Path) -> str:
        """Render a repository-relative location when the path is internal."""
        if _contains(self._root, path):
            return path.relative_to(self._root).as_posix()
        return str(path)

    def _check_read(self, path: Path) -> bool:
        """Accept a declared read path and identify retained workspace evidence."""
        allowed = (*self._inputs.values(), *self._outputs)
        if any(_contains(root, path) for root in allowed):
            return True
        if self._is_runtime_path(path):
            return False
        raise StageFileAccessError(
            f"stage.file_access: undeclared file read: {self._location(path)}"
        )

    def _check_write(self, path: Path) -> None:
        """Accept a declared output or metric write path."""
        if any(
            _contains(root, path) for root in (*self._outputs, *self._managed_writes)
        ):
            return
        raise StageFileAccessError(
            f"stage.file_access: undeclared file write: {self._location(path)}"
        )

    def observe(self, event: str, arguments: tuple[object, ...]) -> None:
        """Apply the declared policy to one CPython audit event."""
        if event in _ESCAPE_EVENTS:
            raise StageFileAccessError(
                "stage.file_access: child execution bypasses the declared file boundary"
            )
        if event == "os.chdir":
            raise StageFileAccessError(
                "stage.file_access: changing the working directory is forbidden"
            )
        if event != "open" or len(arguments) < 3:
            return
        path = self._path(arguments[0])
        if path is None:
            return
        reads, writes = _access_modes(arguments[1], arguments[2])
        if reads:
            self._check_read(path)
        if writes:
            self._check_write(path)

    def record_successful_open(
        self,
        path_value: object,
        mode: object,
        flags: object,
    ) -> None:
        """Retain a permitted file access after the open call succeeds."""
        path = self._path(path_value)
        if path is None:
            return
        reads, writes = _access_modes(mode, flags)
        if reads and self._check_read(path):
            self._reads.add(path)
        if writes:
            self._check_write(path)
            self._writes.add(path)

    def require_every_input(self) -> None:
        """Require a successful read-open beneath every declared input path."""
        missing = [
            name
            for name, root in self._inputs.items()
            if not any(_contains(root, path) for path in self._reads)
        ]
        if missing:
            raise StageFileAccessError(
                "stage.file_access: declared inputs lack read-open evidence: "
                + ", ".join(missing)
            )

    def receipt(self) -> StageFileAccessReceipt:
        """Return repository-relative paths observed by this invocation."""
        return StageFileAccessReceipt(
            reads=tuple(
                path.relative_to(self._root).as_posix() for path in sorted(self._reads)
            ),
            writes=tuple(
                path.relative_to(self._root).as_posix() for path in sorted(self._writes)
            ),
        )
