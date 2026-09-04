"""Tests for compiling authored plans at the execution boundary."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import viper.execution as execution
from tests.test_authoring import _compiled_plan
from viper.authoring import RunPlanDraft
from viper.references import (
    LocalFileRef,
    ResolvedBenchmarkSpecRef,
    ResolvedRunSpecRef,
    storage_file,
)


def test_run_compiles_plan_before_first_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish the plan before handing its exact reference to the runner."""
    draft = RunPlanDraft.model_construct()
    reference = SimpleNamespace(stored_at=SimpleNamespace(path="run.yaml"))
    frozen = SimpleNamespace(reference=reference)
    result = object()
    calls: list[str] = []

    def freeze(root: Path, selected: RunPlanDraft):
        calls.append("freeze")
        assert root == tmp_path
        assert selected is draft
        return frozen

    def run(root: Path, path: Path, **kwargs: object):
        calls.append("run")
        assert root == tmp_path
        assert path == tmp_path / "run.yaml"
        assert kwargs["plan"] is reference
        return result

    monkeypatch.setattr(execution, "freeze_run_plan", freeze)
    monkeypatch.setattr(execution, "_run", run)

    assert execution.run(tmp_path, draft) is result
    assert calls == ["freeze", "run"]


def test_source_and_plan_revisions_are_independent(tmp_path: Path) -> None:
    """Keep project code in Git while generated documents use plan storage."""
    compiled, draft = _compiled_plan(tmp_path)
    run_raw = compiled.files[compiled.run_path]
    plan = ResolvedRunSpecRef(
        sha256="b" * 64,
        bytes=len(run_raw),
        stored_at=LocalFileRef(commit="c" * 64, path=compiled.run_path),
    )

    assert draft.source.commit != plan.stored_at.commit
    assert plan.stored_at.path == compiled.run_path


def test_plan_documents_share_one_storage_revision() -> None:
    """Address every generated document inside the run's plan revision."""
    run = ResolvedRunSpecRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=LocalFileRef(commit="b" * 64, path="runs/run.yaml"),
    )

    stage = storage_file(run.stored_at, "runs/stages/train.yaml")

    assert stage.commit == run.stored_at.commit
    assert stage.path == "runs/stages/train.yaml"


def test_benchmark_spec_accepts_the_plan_revision() -> None:
    """Keep benchmark and run specifications in the same storage union."""
    location = LocalFileRef(commit="b" * 64, path="benchmarks/tiny.yaml")

    benchmark = ResolvedBenchmarkSpecRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=location,
    )

    assert benchmark.stored_at == location
