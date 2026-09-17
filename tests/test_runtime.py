"""Tests for active Python-environment observation and diagnosis."""

from __future__ import annotations

from pathlib import Path

import pytest

import viper.runtime as runtime


class _Distribution:
    """Supply the metadata interface used by importlib.metadata distributions."""

    def __init__(self, name: str, version: str, root: Path) -> None:
        self.metadata = {"Name": name}
        self.version = version
        self.root = root

    def locate_file(self, path: str) -> Path:
        """Resolve a package-relative path below the test installation root."""
        return self.root / path


def _install_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, ...]:
    """Install two synthetic cffi versions at distinct search roots."""
    roots = (tmp_path / "first-site", tmp_path / "second-site")
    distributions = (
        _Distribution("cffi", "1.16.0", roots[0]),
        _Distribution("CFFI", "1.17.0", roots[1]),
    )
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "distributions",
        lambda: distributions,
    )
    monkeypatch.setattr(runtime.sys, "executable", str(tmp_path / "bin/python"))
    monkeypatch.setattr(runtime.sys, "path", [str(root) for root in roots])
    return roots


def test_python_env_conflict_reports_actionable_locations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Name every conflicting version, root, interpreter, and search path."""
    roots = _install_conflict(monkeypatch, tmp_path)

    with pytest.raises(runtime.PythonEnvironmentError) as caught:
        runtime.observe_python_env()

    message = str(caught.value)
    assert "1.16.0" in message
    assert "1.17.0" in message
    assert all(str(root) in message for root in roots)
    assert str(tmp_path / "bin/python") in message
    assert "sys.path" in message
    assert caught.value.diagnosis.conflicts[0].name == "cffi"


def test_python_env_still_rejects_duplicate_versions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve strict rejection when normalized names have two versions."""
    _install_conflict(monkeypatch, tmp_path)

    with pytest.raises(runtime.PythonEnvironmentError):
        runtime.observe_python_env()
