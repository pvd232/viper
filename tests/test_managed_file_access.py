"""Check managed paths, child reader protection and durable control-file writes."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

import viper._workers.metrics as metric_worker
import viper._workers.stages as stage_worker
import viper.serialization as serialization
from tests.fixtures import (
    artifact_loader_ref,
    config_type_ref,
    stage_implementation_ref,
)
from viper._storage_locks import PayloadLocks
from viper._verification.attempt import _verify_declared_file_access
from viper._workers.file_access import StageFileAccessError, StageFileAccessObserver
from viper.config import BuildConfig
from viper.execution._metric import MetricWorkerContext, MetricWorkerResult
from viper.execution._stage import (
    StageWorkerContext,
    StageWorkerResult,
    _resolve_artifact,
    _resolved_output_paths,
)
from viper.metrics import MetricDependency, MetricSpec, ResolvedMetricDependency
from viper.outputs import OutputSpec
from viper.references import FileIdentity, LocalFileRef, ResolvedFileRef
from viper.runs import RunSpec
from viper.stages import BaseSpec, ParameterizedSpec, StageContextBinding

_RUN = "01ARZ3NDEKTSV4RRFFQ69G5FAB"


def _output() -> OutputSpec:
    """Declare one logical output without creating its physical file."""
    return OutputSpec(
        path=f"experiments/demo/runs/base/{_RUN}/artifacts/build/result/result.bin",
        relative_path="result.bin",
        loader=artifact_loader_ref("loader.py"),
        data_role="training",
    )


def _identity(raw: bytes) -> FileIdentity:
    """Identify the exact bytes protected by a child reader."""
    return FileIdentity(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def test_attempt_outputs_preserve_previous_original_and_logical_address(
    tmp_path: Path,
) -> None:
    """A confirmation attempt writes its own file without changing snapshot paths."""
    declaration = _output()
    paths = []
    for attempt, raw in ((1, b"candidate"), (2, b"confirmation")):
        output_root = (
            tmp_path / f".viper/workspaces/{_RUN}/attempt-{attempt}/stages/build"
        )
        actual = _resolved_output_paths(
            tmp_path, {"result": declaration}, output_root=output_root
        )["result"]
        actual.parent.mkdir(parents=True, exist_ok=True)
        actual.write_bytes(raw)
        artifact = _resolve_artifact(tmp_path, declaration, output_path=actual)
        assert artifact.kind == "file"
        assert artifact.file.path == declaration.path
        assert artifact.file.sha256 == hashlib.sha256(raw).hexdigest()
        paths.append(actual)
    assert paths[0] != paths[1]
    assert paths[0].read_bytes() == b"candidate"
    assert paths[1].read_bytes() == b"confirmation"
    assert not (tmp_path / declaration.path).exists()


def test_receipt_maps_shared_inputs_and_nested_output_to_declared_paths(
    tmp_path: Path,
) -> None:
    """Moved files keep checked logical receipt paths and complete input coverage."""
    source = tmp_path / ".viper/store/objects/source.bin"
    output = tmp_path / ".viper/workspaces/attempt/stages/model"
    source.parent.mkdir(parents=True)
    output.mkdir(parents=True)
    source.write_bytes(b"input")
    logical_inputs = {"first": "inputs/first.bin", "second": "inputs/second.bin"}
    logical_outputs = {"model": "artifacts/model"}
    observer = StageFileAccessObserver(
        tmp_path,
        {"first": source, "second": source},
        {"model": output},
        logical_inputs=logical_inputs,
        logical_outputs=logical_outputs,
    )
    with observer:
        (output / "weights.bin").write_bytes(source.read_bytes())
    receipt = observer.receipt()
    assert receipt.reads == ("inputs/first.bin", "inputs/second.bin")
    assert receipt.writes == ("artifacts/model/weights.bin",)
    _verify_declared_file_access(
        stage_id="build",
        access=receipt,
        input_paths=tuple(Path(path) for path in logical_inputs.values()),
        output_paths=tuple(Path(path) for path in logical_outputs.values()),
        measurement_paths=(),
    )


def test_logical_receipt_mapping_does_not_authorize_a_different_physical_write(
    tmp_path: Path,
) -> None:
    """Only the supplied physical output accepts writes during the stage."""
    actual = tmp_path / ".viper/workspaces/attempt/result.bin"
    logical = tmp_path / "artifacts/result.bin"
    actual.parent.mkdir(parents=True)
    logical.parent.mkdir(parents=True)
    observer = StageFileAccessObserver(
        tmp_path,
        {},
        {"result": actual},
        logical_outputs={"result": "artifacts/result.bin"},
    )
    with pytest.raises(StageFileAccessError, match="undeclared file write"):
        with observer:
            logical.write_bytes(b"wrong location")
    assert not logical.exists()


def test_stage_child_holds_inputs_before_validation_and_releases_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child protects its inputs even when the parent has no reader lock."""
    raw = b"training input"
    identity = _identity(raw)
    store = ".viper/child-store"
    locks = PayloadLocks(tmp_path, store)
    binding = StageContextBinding(
        run_id=_RUN,
        attempt_id=1,
        stage_id="build",
        config_type=config_type_ref("build"),
        config_digest=serialization.document_digest(BuildConfig()),
        inputs={"data": "inputs/data.bin"},
        outputs={"result": _output().path},
        metric_ids=(),
        numpy_generator_names=(),
    )
    context = StageWorkerContext(
        repository_root=tmp_path,
        run_spec_path=tmp_path / "run.yaml",
        stage_spec_path=tmp_path / "stage.yaml",
        binding=binding,
        result_path=tmp_path / "result.json",
        reader_files=(identity,),
        reader_store=store,
    )
    context_path = tmp_path / "context.json"
    context_path.write_text(context.model_dump_json())
    context.run_spec_path.write_bytes(b"{}")
    stage = ParameterizedSpec.model_construct(
        implementation=stage_implementation_ref("build.py")
    )
    monkeypatch.setenv("VIPER_CONTEXT_PATH", str(context_path))
    monkeypatch.setattr(
        RunSpec,
        "model_validate",
        classmethod(lambda cls, value: RunSpec.model_construct()),
    )
    monkeypatch.setattr(stage_worker, "load_stage_spec", lambda path: stage)

    def validation_boundary(*args: object) -> None:
        """Require real reader protection before the child validates data."""
        with locks.exclusive(identity) as acquired:
            assert not acquired
        raise ValueError("test validation stop")

    monkeypatch.setattr(stage_worker, "_planned_stage_context", validation_boundary)
    assert stage_worker.main([]) == 1
    result = StageWorkerResult.model_validate_json(context.result_path.read_bytes())
    assert result.error is not None and "test validation stop" in result.error
    with locks.exclusive(identity) as acquired:
        assert acquired


def test_metric_child_holds_dependency_files_before_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metric children protect references already present in their dependency list."""
    identity = _identity(b"predictions")
    reference = ResolvedFileRef(
        sha256=identity.sha256,
        bytes=identity.bytes,
        stored_at=LocalFileRef(workspace=tmp_path, commit="a" * 64, path="predictions"),
    )
    dependency = MetricDependency(source="artifact", name="result", data_role="eval")
    store = ".viper/metric-store"
    locks = PayloadLocks(tmp_path, store)
    context = MetricWorkerContext.model_construct(
        repository_root=tmp_path,
        reader_store=store,
        result_path=tmp_path / "result.json",
        metric=MetricSpec.model_construct(
            metric_id="score", dependencies=(dependency,)
        ),
        stage=BaseSpec.model_construct(metric_ids=("score",)),
        dependencies=(
            ResolvedMetricDependency(dependency=dependency, files=(reference,)),
        ),
    )
    context_path = tmp_path / "context.json"
    context_path.write_bytes(b"{}")
    monkeypatch.setenv("VIPER_METRIC_CONTEXT_PATH", str(context_path))
    monkeypatch.setattr(
        MetricWorkerContext,
        "model_validate_json",
        classmethod(lambda cls, value: context),
    )

    def validation_boundary(*args: object) -> None:
        """Require the child lock before metric dependency validation begins."""
        with locks.exclusive(identity) as acquired:
            assert not acquired
        raise ValueError("test validation stop")

    monkeypatch.setattr(
        metric_worker, "validate_metric_definition", validation_boundary
    )
    assert metric_worker.main([]) == 1
    result = MetricWorkerResult.model_validate_json(context.result_path.read_bytes())
    assert result.error is not None and "test validation stop" in result.error
    with locks.exclusive(identity) as acquired:
        assert acquired


def test_exact_control_write_keeps_identical_inode_and_rejects_changed_bytes(
    tmp_path: Path,
) -> None:
    """Recovery can reuse a durable control record without replacing its identity."""
    path = tmp_path / "record.json"
    serialization.write_synchronized(path, b"first")
    inode = path.stat().st_ino
    serialization.write_synchronized(path, b"first")
    assert path.stat().st_ino == inode
    with pytest.raises(FileExistsError, match="refusing to replace"):
        serialization.write_synchronized(path, b"different")
    assert path.read_bytes() == b"first"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_exact_control_write_cannot_overwrite_a_concurrent_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competing immutable record wins without its bytes being overwritten."""
    path = tmp_path / "record.json"
    original_link = os.link

    def competing_install(source: Path, destination: Path) -> None:
        """Install competing bytes immediately before the immutable link."""
        destination.write_bytes(b"other writer")
        original_link(source, destination)

    monkeypatch.setattr(serialization.os, "link", competing_install)
    with pytest.raises(FileExistsError, match="refusing to replace"):
        serialization.write_synchronized(path, b"this writer")
    assert path.read_bytes() == b"other writer"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_mutable_control_write_syncs_bytes_before_install_and_directory_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A returned mutable write has synchronized both its bytes and final name."""
    path = tmp_path / "head.json"
    events: list[str] = []
    original_fsync = os.fsync
    original_replace = os.replace

    def synchronized(descriptor: int) -> None:
        """Record which inode was synchronized while retaining real fsync."""
        events.append(
            "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
        )
        original_fsync(descriptor)

    def installed(source: Path, destination: Path) -> None:
        """Record the atomic replacement between file and directory sync."""
        events.append("install")
        original_replace(source, destination)

    monkeypatch.setattr(serialization.os, "fsync", synchronized)
    monkeypatch.setattr(serialization.os, "replace", installed)
    serialization.replace_synchronized(path, b"new head")
    assert events == ["file", "install", "directory"]
    assert path.read_bytes() == b"new head"
