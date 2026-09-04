"""Discover and validate the root of a Git-backed VIPER project."""

from __future__ import annotations

import re
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

import viper._subprocess as subprocess

from ._schema import ProtocolModel, RepoRelPath

PACKAGE_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
ROOT_FILES: dict[str, str] = {
    "viper.toml": "[project]\nschema_version = 1\n",
    "inputs/.gitkeep": "",
}


class InitError(RuntimeError):
    """Report an invalid target or a failed scaffold write."""


class Settings(ProtocolModel):
    """Represent the ``[project]`` table stored in ``viper.toml``."""

    schema_version: Literal[1] = Field(
        description="Version of the project-marker schema."
    )


class RootError(ValueError):
    """Report failure to discover or validate a VIPER project root."""


class PathError(RootError):
    """Report a project path that escapes its root or uses a symlink."""


PathOperation = Literal["read", "write"]


def find_root(start: Path) -> Path:
    """Return the nearest ancestor of ``start`` that contains ``viper.toml``."""
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "viper.toml").is_file():
            return directory
    raise RootError(f"no viper.toml found from {start}")


def _require_git_work_tree(root: Path) -> None:
    """Require ``root`` to equal the top level of its Git work tree."""
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise RootError(f"project root is not in a Git work tree: {root}")
    if Path(completed.stdout.strip()).resolve() != root:
        raise RootError(f"viper.toml must be a Git work-tree root: {root}")


def resolve_root(root: Path | None = None) -> Path:
    """Return a project root with a valid marker at its Git work-tree boundary."""
    resolved = find_root(root if root is not None else Path.cwd())
    marker = resolved / "viper.toml"
    try:
        data = tomllib.loads(marker.read_text(encoding="utf-8"))
        Settings.model_validate(data.get("project", {}))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise RootError(f"invalid project marker: {marker}") from error

    _require_git_work_tree(resolved)
    return resolved


def resolve_path(
    project_root: Path,
    path: RepoRelPath,
    *,
    operation: PathOperation,
) -> Path:
    """Resolve one symlink-free project path for a local read or write."""
    root = project_root.resolve(strict=True)
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise PathError(f"project path escapes ROOT: {path}")

    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PathError(f"project path contains a symlink: {path}")
        if not current.exists():
            break

    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise PathError(f"resolved project path escapes ROOT: {path}")
    if operation == "read" and not resolved.is_file():
        raise PathError(f"project file is missing: {path}")
    return resolved


def validate_package_name(package: str) -> None:
    """Require one importable lowercase Python package name."""
    if PACKAGE_PATTERN.fullmatch(package) is None:
        raise InitError("package must match ^[a-z][a-z0-9_]*$")


def _project_files(package: str) -> dict[str, str]:
    """Return the complete starter-project file mapping."""
    stage_definitions = {
        "build": ("BuildParameters", "build", "prior"),
        "embed": ("EmbedParameters", "embed", "embedding"),
        "train": ("TrainParameters", "train", "parameters"),
        "eval": ("EvalParameters", "eval", "predictions"),
    }
    files: dict[str, str] = {
        **ROOT_FILES,
        ".gitignore": ".viper/\n__pycache__/\n*.egg-info/\n",
        "README.md": f"""# {package}

This project contains one decorated callable for each VIPER stage kind.

Run the focused project tests:

    python -m pytest -q

After replacing the stage templates, commit the project and write an experiment
draft under `experiments/`. The draft selects the stages and files for one run.
`viper freeze-run` turns that draft into the exact plan used for execution.

Benchmark specifications belong under `benchmarks/`.
""",
        "pyproject.toml": f'''[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "{package.replace("_", "-")}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["viper-provenance>=0.1.0a2"]

[project.optional-dependencies]
test = ["pytest>=9,<10"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
''',
        f"src/{package}/__init__.py": (
            f'"""Project-owned stages and provenance extensions for {package}."""\n'
        ),
        f"src/{package}/params.py": (
            '''"""Define project-owned stage parameter models."""

from pydantic import Field
from viper import parameters


class BuildParameters(params.Build):
    """Select the delimiter consumed by the prior builder."""

    delimiter: str = ","


class EmbedParameters(params.Embed):
    """Select the dimension of the example embedding."""

    dimensions: int = Field(default=2, gt=0)


class TrainParameters(params.Train):
    """Select the number of example training passes."""

    epochs: int = Field(default=1, gt=0)


class EvalParameters(params.Eval):
    """Select the label written beside the example predictions."""

    label: str = "baseline"
'''
        ),
        f"src/{package}/artifact_loaders/__init__.py": (
            '"""Project-owned artifact reconstruction functions."""\n'
        ),
        f"src/{package}/artifact_loaders/bytes_file.py": (
            '''"""Load one file artifact as exact bytes."""

from pathlib import Path


def load(path: Path) -> bytes:
    """Return the complete file contents."""
    return path.read_bytes()
'''
        ),
        f"src/{package}/artifact_loaders/resume_state.py": (
            '''"""Reconstruct the example terminal training state."""

from pathlib import Path

from viper.randomness import (
    LegacyNumPyRNGState,
    MainProcessRNGState,
    NumPyRNGState,
    PCG64GeneratorState,
    PCG64InternalState,
    PythonRNGState,
)
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
)


def load(path: Path) -> ResumeState:
    """Return the example resume state after confirming the file exists."""
    path.read_bytes()
    return ResumeState(
        optimizer_state={"state": {}, "param_groups": []},
        main_process_rng=MainProcessRNGState(
            python=PythonRNGState(
                version=3,
                internal_state=(1,),
                gaussian_cache=None,
            ),
            numpy=NumPyRNGState(
                generators={
                    "training": PCG64GeneratorState(
                        state=PCG64InternalState(state=1, inc=1),
                        has_uint32=0,
                        uinteger=0,
                    )
                },
                legacy_global=LegacyNumPyRNGState(
                    keys=(0,) * 624,
                    position=0,
                    has_gaussian=0,
                    cached_gaussian=0.0,
                ),
            ),
            torch_cpu=b"torch-cpu",
            torch_cuda=(),
        ),
        dataloader=DataLoaderResumeState(
            configuration=DataLoaderConfiguration(workers=0),
            state_dict={"num_yielded": 1},
        ),
    )
'''
        ),
        f"src/{package}/metrics/__init__.py": (
            '"""Project-owned metric implementations."""\n'
        ),
        f"src/{package}/metrics/eval.py": (
            '''"""Define one recomputed eval metric."""

from viper.metrics import metric


@metric(metric_id="prediction_bytes", kind="eval", mode="recompute")
def prediction_bytes(context) -> float:
    """Return the byte count of the verified prediction artifact."""
    return float(len(context.artifacts["predictions"].read_bytes()))
'''
        ),
        "experiments/README.md": """# Experiments

Freeze authored experiment, variant, stage, and run documents here. VIPER
binds every implementation through its repository-relative path and exact
source identity.
""",
        "benchmarks/README.md": """# Benchmarks

A benchmark governs one eval contract across candidate run plans and
requires an independently executed confirmation.
""",
        "train.py": f'''"""Run one frozen project plan."""

from {package}.stages.train import train
from viper.api import run


def main() -> None:
    """Execute the complete plan selected by the command-line arguments."""
    run(train)


if __name__ == "__main__":
    main()
''',
        "tests/test_stage_definitions.py": (
            f'''"""Verify generated stages expose their VIPER definitions."""

from {package}.stages.build import build
from {package}.stages.embed import embed
from {package}.stages.eval import eval
from {package}.stages.train import train

from viper.stages import stage_definition


def test_stage_kinds() -> None:
    """Match each callable with the stage kind fixed by its decorator."""
    stages = (build, embed, train, eval)

    assert tuple(stage_definition(stage).kind for stage in stages) == (
        "build",
        "embed",
        "train",
        "eval",
    )
'''
        ),
    }
    for stage, (parameter_class, decorator, artifact) in stage_definitions.items():
        if stage == "eval":
            input_read = "    payload = context.inputs['parameters'].read_bytes()\n"
        else:
            input_read = (
                "    source = next(iter(context.inputs.values()))\n"
                "    payload = source.read_bytes()\n"
            )
        extra_artifact = ""
        if stage == "train":
            extra_artifact = (
                "    context.artifacts['resume_state'].write_bytes(b'resume')\n"
            )
        destination_line = f'    destination = context.artifacts["{artifact}"]\n'
        stage_body = f"""{input_read}{destination_line}\
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
{extra_artifact}"""
        files[
            f"src/{package}/stages/{stage}.py"
        ] = f'''"""Execute the example {stage} stage."""

from {package}.parameters import {parameter_class}
from viper.stages import {decorator}


@{decorator}(params={parameter_class})
def {stage}(context) -> None:
    """Write the declared {artifact} artifact from verified inputs."""
{stage_body}'''
    files[f"src/{package}/stages/__init__.py"] = (
        '"""Project-owned decorated stage callables."""\n'
    )
    return files


def init(path: Path, package: str) -> tuple[Path, ...]:
    """Write the starter project into one absent or empty directory."""
    validate_package_name(package)
    target = path.resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise InitError("target directory must be absent or empty")

    files = _project_files(package)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        for relative_path, content in files.items():
            destination = staging / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        if target.exists():
            target.rmdir()
        staging.replace(target)
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise InitError("project scaffold could not be written") from exc
    return tuple(target / relative_path for relative_path in sorted(files))
