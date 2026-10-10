"""Acceptance tests for the installed project scaffold operation."""

from __future__ import annotations

import sys
from os import environ
from pathlib import Path

from viper import _subprocess as subprocess
from viper.api import (
    InitWorkspaceRequest,
    ViperFailure,
    dispatch,
    init_workspace,
)
from viper.repository import find_root, resolve_root
from viper.repository import init_workspace as create_workspace


def test_init_rejects_occupied_target_without_mutation(
    tmp_path: Path,
) -> None:
    """Preserve every existing file when the target directory is occupied."""
    target = tmp_path / "occupied"
    target.mkdir()
    existing = target / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    result = dispatch(
        "init_workspace",
        {"path": target, "package": "sample_project"},
    )

    assert isinstance(result, ViperFailure)
    assert result.code == "write_conflict"
    assert existing.read_text(encoding="utf-8") == "keep"
    assert tuple(target.iterdir()) == (existing,)


def test_init_rejects_invalid_package_before_writing(
    tmp_path: Path,
) -> None:
    """Reject an invalid import name at the request-validation boundary."""
    target = tmp_path / "starter"

    result = dispatch(
        "init_workspace",
        {"path": target, "package": "Bad-Package"},
    )

    assert isinstance(result, ViperFailure)
    assert result.origin == "request"
    assert result.code == "invalid_request"
    assert not target.exists()


def test_init_establishes_discoverable_root(tmp_path: Path) -> None:
    """Guarantee that project root discovery and resolution == project init path ."""
    target = tmp_path / "outside" / "starter"
    create_workspace(target, "sample_workspace")
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    child = target / "src" / "sample_workspace"
    assert find_root(child) == target.resolve()
    assert resolve_root(child) == target.resolve()
    required = {
        "viper.toml",
        "inputs",
        "benchmarks",
        "experiments",
        ".gitignore",
        "pyproject.toml",
    }
    assert required <= {path.name for path in target.iterdir()}


def test_init_generates_importable_python_project(
    tmp_path: Path,
) -> None:
    """Generate the project and execute its focused tests without editing it."""
    target = tmp_path / "starter"
    environment = environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd())

    result = init_workspace(
        InitWorkspaceRequest(path=target, package="sample_workspace")
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=target,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.repository_root == target.resolve()
    assert len(result.files) == 23
    assert target / "viper.toml" in result.files
    assert target / "inputs" / ".gitkeep" in result.files
    ignore_rules = (target / ".gitignore").read_text(encoding="utf-8").splitlines()
    readme = (target / "README.md").read_text(encoding="utf-8")
    runner = (target / "run.py").read_text(encoding="utf-8")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout
    assert "experiments/**/artifacts/" in ignore_rules
    assert "freeze-run" not in readme
    assert "viper.execution.run()" in readme
    assert "execution.run(draft, repository_root=root)" in runner


def test_generated_checkpoint_loader_reconstructs_saved_state(tmp_path: Path) -> None:
    """Execute the generated template and restore its actual serialized RNG state."""
    target = tmp_path / "starter"
    create_workspace(target, "sample_workspace")
    environment = environ.copy()
    environment["PYTHONPATH"] = str(target / "src")
    program = """
from pathlib import Path
from types import SimpleNamespace

from sample_workspace.artifact_loaders.resume_state import load
from sample_workspace.config import TrainConfig
from sample_workspace.stages.train import train
from viper.resume import load_resume_state

dataset = Path("inputs/train.csv")
dataset.write_bytes(b"x,y\\n1,2\\n")
model = Path("model.bin")
checkpoint = Path("resume_state.pt")
context = SimpleNamespace(
    inputs={"dataset": dataset},
    outputs={"model": model, "resume_state": checkpoint},
    config=TrainConfig(), numpy_generators={},
    metrics={"training_loss": SimpleNamespace(record=lambda *args, **kwargs: None)},
)
train(context)
saved = load_resume_state(checkpoint)
assert load(checkpoint) == saved
assert saved.dataloader.state_dict == {"num_yielded": 1}
assert len(saved.main_process_rng.torch_cpu) > 100
assert model.read_bytes() == dataset.read_bytes()
checkpoint.write_bytes(b"invalid checkpoint")
try:
    load(checkpoint)
except Exception:
    pass
else:
    raise AssertionError("loader accepted an invalid checkpoint")
"""
    completed = subprocess.run(
        (sys.executable, "-c", program),
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
