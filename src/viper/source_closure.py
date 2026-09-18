"""Freeze the workspace modules reached by one stage callable."""

from __future__ import annotations

import hashlib
import inspect
import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from .stages import StageDependencyRef


def workspace_dependency_refs(
    root: Path,
    implementation: Callable[..., Any],
    *,
    exclude: tuple[Path, ...] = (),
) -> tuple[StageDependencyRef, ...]:
    """Identify workspace source files referenced by a callable's global closure."""
    repository = root.resolve()
    tracked = {
        (repository / relative.decode("utf-8")).resolve()
        for relative in subprocess.run(
            ("git", "-C", str(repository), "ls-files", "-z"),
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        if relative
    }
    excluded = {path.resolve() for path in exclude}
    pending: deque[object] = deque([implementation])
    visited_objects: set[int] = set()
    files: dict[Path, StageDependencyRef] = {}

    while pending:
        value = pending.popleft()
        identity = id(value)
        if identity in visited_objects:
            continue
        visited_objects.add(identity)
        source = (
            inspect.getsourcefile(value)
            if inspect.ismodule(value)
            or inspect.isclass(value)
            or inspect.ismethod(value)
            or inspect.isfunction(value)
            else None
        )
        if source is not None:
            path = Path(source).resolve()
            if path in tracked and path not in excluded:
                raw = path.read_bytes()
                files[path] = StageDependencyRef(
                    path=path.relative_to(repository).as_posix(),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),
                )
        if inspect.isfunction(value):
            try:
                closure = inspect.getclosurevars(value)
            except TypeError:
                continue
            pending.extend(closure.globals.values())
        elif isinstance(value, ModuleType):
            continue

    return tuple(files[path] for path in sorted(files))
