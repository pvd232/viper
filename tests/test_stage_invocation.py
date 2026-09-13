"""Tests for frozen stage-callable identity and live typed contexts."""

import hashlib
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Protocol, cast

import numpy as np
import pytest

from viper import config
from viper._workers.file_access import StageFileAccessObserver
from viper._workers.stages import _activate_workspace_modules
from viper.stages import (
    StageContext,
    StageDefinitionError,
    StageImplementationRef,
    load_stage_callable,
    stage_definition,
)
from viper.stages import (
    train as train_stage,
)


class WorkspaceModuleCallable(Protocol):
    """Expose the workspace modules retained on a loaded stage callable."""

    __viper_workspace_modules__: Mapping[str, ModuleType]

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Invoke the stage callable."""
        ...


class ExampleTrainConfig(config.TrainConfig):
    """Define one project-owned parameter field for decorator tests."""

    epochs: int


@train_stage(config=ExampleTrainConfig)
def train(context: StageContext[ExampleTrainConfig]) -> None:
    """Consume one typed context in the direct decorator fixture."""
    assert context.config.epochs > 0


def test_train_decorator_exposes_stage_kind_and_config_type() -> None:
    """Expose the exact authoring metadata attached to one callable."""
    definition = stage_definition(train)

    assert definition.kind == "train"
    assert definition.config_type is ExampleTrainConfig


def test_stage_context_keeps_live_values_outside_pydantic() -> None:
    """Carry paths and generator objects through the frozen runtime dataclass."""
    generator = np.random.Generator(np.random.PCG64(7))
    context = StageContext(
        run_id="01JABCDEFGHJKMNPQRSTVWXYZ0",
        attempt_id=1,
        stage_id="train",
        config=ExampleTrainConfig(epochs=3),
        inputs=MappingProxyType({"dataset": Path("inputs/data.bin")}),
        outputs=MappingProxyType({"parameters": Path("artifacts/model.bin")}),
        metrics=MappingProxyType({}),
        numpy_generators=MappingProxyType({"augmentation": generator}),
    )

    assert context.config.epochs == 3
    assert context.numpy_generators["augmentation"] is generator


def test_stage_loader_requires_exact_decorated_top_level_callable(
    tmp_path: Path,
) -> None:
    """Load the selected symbol only when its bytes and decorator agree."""
    raw = (
        b"from viper.stages import train\n"
        b"from viper import config\n\n"
        b"class Params(config.TrainConfig):\n"
        b"    epochs: int\n\n"
        b"@train(config=Params)\n"
        b"def fit(context):\n"
        b"    return None\n"
    )
    path = tmp_path / "fit.py"
    path.write_bytes(raw)
    reference = StageImplementationRef(
        path="fit.py",
        symbol="fit",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )

    loaded = load_stage_callable(path, reference, import_root=tmp_path)

    assert stage_definition(loaded).kind == "train"
    with pytest.raises(StageDefinitionError, match="byte count"):
        load_stage_callable(
            path,
            reference.model_copy(update={"bytes": len(raw) + 1}),
            import_root=tmp_path,
        )
    path.write_bytes(raw.replace(b"return None", b"return 3   "))
    with pytest.raises(StageDefinitionError, match="SHA-256"):
        load_stage_callable(path, reference, import_root=tmp_path)


def test_stage_loader_resolves_standard_src_layout(tmp_path: Path) -> None:
    """Load project imports from a repository-local ``src`` package root."""
    package_root = tmp_path / "src/example_project"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text(
        '"""Example project package."""\n',
        encoding="utf-8",
    )
    (package_root / "config.py").write_text(
        "from viper import config\n\n"
        "class ProjectConfig(config.TrainConfig):\n"
        "    epochs: int\n",
        encoding="utf-8",
    )
    raw = (
        b"from example_project.config import ProjectConfig\n"
        b"from viper.stages import train\n\n"
        b"@train(config=ProjectConfig)\n"
        b"def fit(context):\n"
        b"    return None\n"
    )
    path = package_root / "fit.py"
    path.write_bytes(raw)
    reference = StageImplementationRef(
        path="src/example_project/fit.py",
        symbol="fit",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )

    loaded = load_stage_callable(path, reference, import_root=tmp_path)

    assert stage_definition(loaded).config_type.__name__ == "ProjectConfig"
    workspace_modules = cast(
        WorkspaceModuleCallable, loaded
    ).__viper_workspace_modules__
    assert workspace_modules["example_project.config"].ProjectConfig is (
        stage_definition(loaded).config_type
    )


def test_stage_worker_activates_loaded_workspace_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve the loader's exact module objects only during stage execution."""
    package = ModuleType("example_project")
    dependency = ModuleType("example_project.dependency")
    previous = ModuleType("example_project")

    def fit() -> None:
        return None

    fit_with_modules = cast(WorkspaceModuleCallable, fit)
    fit_with_modules.__viper_workspace_modules__ = MappingProxyType(
        {
            "example_project": package,
            "example_project.dependency": dependency,
        }
    )
    monkeypatch.setitem(sys.modules, "example_project", previous)
    sys.modules.pop("example_project.dependency", None)

    observer = StageFileAccessObserver(tmp_path, {}, {})
    with _activate_workspace_modules(fit_with_modules), observer:
        assert sys.modules["example_project"] is package
        assert sys.modules["example_project.dependency"] is dependency

    assert observer.receipt().reads == ()
    assert sys.modules["example_project"] is previous
    assert "example_project.dependency" not in sys.modules


def test_stage_loader_keeps_framework_identity_in_viper_repository(
    tmp_path: Path,
) -> None:
    """Load a stage without replacing the running VIPER package."""
    root = Path(__file__).parents[1]
    path = tmp_path / "stage.py"
    raw = (
        b"from viper.config import TrainConfig\n"
        b"from viper.stages import train\n\n"
        b"@train(config=TrainConfig)\n"
        b"def fit(context):\n"
        b"    return None\n"
    )
    path.write_bytes(raw)
    reference = StageImplementationRef(
        path="stage.py",
        symbol="fit",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )

    loaded = load_stage_callable(path, reference, import_root=root)

    assert stage_definition(loaded).kind == "train"
