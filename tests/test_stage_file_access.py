"""Tests for declared stage file-access enforcement and evidence."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
import torch

from viper._verification.attempt import _verify_declared_file_access
from viper._workers.file_access import (
    StageFileAccessError,
    StageFileAccessObserver,
)
from viper._workers.stages import _frozen_python_sources
from viper.evidence import VerificationError
from viper.stages import (
    ParameterizedSpec,
    StageFileAccessReceipt,
    StageInvocationReceipt,
)


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create one workspace input, output path, and undeclared file."""
    root = tmp_path / "workspace"
    source = root / "inputs/source.bin"
    output = root / "artifacts/result.bin"
    hidden = root / "inputs/hidden.bin"
    source.parent.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    hidden.write_bytes(b"hidden")
    return root, source, output


def _commit_files(root: Path, *paths: Path) -> str:
    """Commit selected fixture paths and return the resulting revision."""
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    subprocess.run(
        ("git", "-C", str(root), "add", *(path.name for path in paths)),
        check=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=VIPER Tests",
            "-c",
            "user.email=viper@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ),
        check=True,
    )
    return subprocess.run(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_workspace(tmp_path: Path) -> tuple[Path, str, Path, Path, Path]:
    """Commit one Python source and one non-Python file beside an untracked source."""
    root = tmp_path / "workspace"
    root.mkdir()
    tracked_source = root / "model.py"
    tracked_data = root / "model.json"
    untracked_source = root / "untracked.py"
    tracked_source.write_text("VALUE = 1\n", encoding="utf-8")
    tracked_data.write_text("{}\n", encoding="utf-8")
    untracked_source.write_text("VALUE = 2\n", encoding="utf-8")
    commit = _commit_files(root, tracked_source, tracked_data)
    return root, commit, tracked_source, tracked_data, untracked_source


def test_frozen_python_source_is_runtime_code(tmp_path: Path) -> None:
    """Permit exact tracked Python source without recording a data read."""
    root, commit, tracked_source, _tracked_data, _untracked_source = (
        _source_workspace(tmp_path)
    )
    sources = _frozen_python_sources(root, commit)
    observer = StageFileAccessObserver(root, {}, {}, source_reads=sources)

    with observer:
        assert tracked_source.read_text(encoding="utf-8") == "VALUE = 1\n"

    assert sources == (tracked_source,)
    assert observer.receipt().reads == ()


def test_untracked_python_source_is_rejected(tmp_path: Path) -> None:
    """Keep an untracked Python file outside the frozen source boundary."""
    root, commit, _tracked_source, _tracked_data, untracked_source = (
        _source_workspace(tmp_path)
    )

    with pytest.raises(StageFileAccessError, match="undeclared file read"):
        with StageFileAccessObserver(
            root,
            {},
            {},
            source_reads=_frozen_python_sources(root, commit),
        ):
            untracked_source.read_text(encoding="utf-8")


def test_tracked_non_python_file_is_rejected(tmp_path: Path) -> None:
    """Keep tracked non-Python bytes inside the declared data boundary."""
    root, commit, _tracked_source, tracked_data, _untracked_source = (
        _source_workspace(tmp_path)
    )

    with pytest.raises(StageFileAccessError, match="undeclared file read"):
        with StageFileAccessObserver(
            root,
            {},
            {},
            source_reads=_frozen_python_sources(root, commit),
        ):
            tracked_data.read_text(encoding="utf-8")


def test_tracked_python_symlink_is_rejected(tmp_path: Path) -> None:
    """Reject a tracked Python name that redirects to other workspace bytes."""
    root = tmp_path / "workspace"
    root.mkdir()
    data = root / "data.bin"
    source = root / "model.py"
    data.write_bytes(b"data")
    source.symlink_to(data.name)
    commit = _commit_files(root, data, source)

    sources = _frozen_python_sources(root, commit)
    assert sources == ()
    with pytest.raises(StageFileAccessError, match="undeclared file read"):
        with StageFileAccessObserver(root, {}, {}, source_reads=sources):
            source.read_text(encoding="utf-8")


def test_declared_access_records_input_read_and_output_write(tmp_path: Path) -> None:
    """Retain the exact paths used by a conforming stage invocation."""
    root, source, output = _paths(tmp_path)
    observer = StageFileAccessObserver(root, {"source": source}, {"result": output})

    with observer:
        output.write_bytes(source.read_bytes())

    assert observer.receipt().model_dump(mode="json") == {
        "schema_version": 1,
        "reads": ["inputs/source.bin"],
        "writes": ["artifacts/result.bin"],
    }


def test_declared_access_observes_numpy_archive_load(tmp_path: Path) -> None:
    """Retain a read-open event emitted by NumPy's archive loader."""
    root = tmp_path / "workspace"
    source = root / "inputs/values.npz"
    source.parent.mkdir(parents=True)
    np.savez(source, values=np.array([1.0, 2.0]))
    observer = StageFileAccessObserver(root, {"values": source}, {})

    with observer, np.load(source) as archive:
        values = archive["values"]

    assert values.tolist() == [1.0, 2.0]
    assert observer.receipt().reads == ("inputs/values.npz",)


def test_declared_access_observes_torch_checkpoint_load(tmp_path: Path) -> None:
    """Retain a read-open event emitted by PyTorch's checkpoint loader."""
    root = tmp_path / "workspace"
    source = root / "inputs/model.pt"
    source.parent.mkdir(parents=True)
    torch.save({"weight": torch.tensor([1.0])}, source)
    observer = StageFileAccessObserver(root, {"model": source}, {})

    with observer:
        checkpoint = torch.load(source, weights_only=True)

    assert checkpoint["weight"].tolist() == [1.0]
    assert observer.receipt().reads == ("inputs/model.pt",)


def test_null_device_is_runtime_plumbing(tmp_path: Path) -> None:
    """Exclude successful null-device reads and writes from stage evidence."""
    observer = StageFileAccessObserver(tmp_path, {}, {})

    with observer:
        with open(os.devnull, "rb") as source:
            assert source.read() == b""
        with open(os.devnull, "wb") as sink:
            assert sink.write(b"discarded") == 9

    assert observer.receipt().reads == ()
    assert observer.receipt().writes == ()


@pytest.mark.skipif(not Path("/dev/zero").exists(), reason="requires /dev/zero")
def test_undeclared_device_is_rejected(tmp_path: Path) -> None:
    """Keep device paths other than the operating system null device governed."""
    with pytest.raises(StageFileAccessError, match="undeclared file read"):
        with StageFileAccessObserver(tmp_path, {}, {}):
            Path("/dev/zero").read_bytes()


def test_declared_access_rejects_unused_input(tmp_path: Path) -> None:
    """Require each declared input edge to produce a read-open event."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="lack read-open evidence"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            output.write_bytes(b"constant")


def test_declared_access_rejects_failed_input_open(tmp_path: Path) -> None:
    """Require the declared input open to return successfully."""
    root = tmp_path / "workspace"
    source = root / "inputs/missing.bin"
    output = root / "artifacts/result.bin"
    output.parent.mkdir(parents=True)

    with pytest.raises(StageFileAccessError, match="lack read-open evidence"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            try:
                source.read_bytes()
            except FileNotFoundError:
                pass
            output.write_bytes(b"constant")


def test_importing_observer_preserves_unrestricted_process() -> None:
    """Keep the audit hook absent until a declared observer activates."""
    script = """
import sys

hooks = []
sys.addaudithook = hooks.append
import viper._workers.file_access
print(len(hooks))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "0"


def test_declared_access_rejects_undeclared_workspace_read(tmp_path: Path) -> None:
    """Reject a workspace read outside the declared input edges."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="undeclared file read"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            (root / "inputs/hidden.bin").read_bytes()


def test_declared_access_rejects_undeclared_write(tmp_path: Path) -> None:
    """Reject a write outside every declared output root."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="undeclared file write"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            source.read_bytes()
            (root / "undeclared.bin").write_bytes(b"undeclared")


def test_declared_access_rejects_child_process(tmp_path: Path) -> None:
    """Reject a child process whose file operations escape the observer."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="child execution bypasses"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            source.read_bytes()
            subprocess.run([sys.executable, "-c", "pass"], check=True)


def test_declared_access_rejects_os_process_launch(tmp_path: Path) -> None:
    """Reject a direct operating-system launch outside the subprocess module."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="child execution bypasses"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            source.read_bytes()
            os.system("true")


def test_declared_access_rejects_python_thread_launch(tmp_path: Path) -> None:
    """Reject a Python thread that could outlive the active observer."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="child execution bypasses"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            source.read_bytes()
            threading.Thread(target=lambda: None).start()


def test_declared_access_rejects_working_directory_change(tmp_path: Path) -> None:
    """Reject a directory change that would alter relative path resolution."""
    root, source, output = _paths(tmp_path)

    with pytest.raises(StageFileAccessError, match="working directory"):
        with StageFileAccessObserver(root, {"source": source}, {"result": output}):
            source.read_bytes()
            os.chdir(root)


@pytest.mark.parametrize(
    ("receipt", "message"),
    [
        (None, "omitted declared file-access evidence"),
        (
            StageFileAccessReceipt(
                reads=("inputs/other.bin",),
                writes=("artifacts/result.bin",),
            ),
            "undeclared file read",
        ),
        (
            StageFileAccessReceipt(
                reads=("inputs/source.bin",),
                writes=("artifacts/other.bin",),
            ),
            "undeclared file write",
        ),
        (
            StageFileAccessReceipt(reads=(), writes=("artifacts/result.bin",)),
            "did not open every declared input",
        ),
    ],
)
def test_verifier_rejects_invalid_file_access_receipts(
    receipt: StageFileAccessReceipt | None,
    message: str,
) -> None:
    """Reject missing, extra, or incomplete evidence during verification."""
    with pytest.raises(VerificationError, match=message):
        _verify_declared_file_access(
            stage_id="prepare",
            access=receipt,
            input_paths=(Path("inputs/source.bin"),),
            output_paths=(Path("artifacts/result.bin"),),
            measurement_paths=(),
        )


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (StageFileAccessReceipt, "schema_version"),
        (StageFileAccessReceipt, "reads"),
        (StageFileAccessReceipt, "writes"),
        (StageInvocationReceipt, "file_access"),
        (ParameterizedSpec, "file_access"),
    ],
)
def test_file_access_schema_fields_explain_retained_evidence(
    model: type[StageFileAccessReceipt]
    | type[StageInvocationReceipt]
    | type[ParameterizedSpec],
    field: str,
) -> None:
    """Keep semantic descriptions in the generated protocol schema."""
    description = model.model_json_schema()["properties"][field].get("description")

    assert isinstance(description, str)
    assert description.strip()
