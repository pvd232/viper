"""Tests for frozen stage-callable identity and live typed contexts."""

import hashlib
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from viper import parameters
from viper.stages import (
    Context,
    StageDefinitionError,
    StageImplementationRef,
    load_stage_callable,
    stage_definition,
    train,
)


class ExampleTrainParameters(parameters.Train):
    """Define one project-owned parameter field for decorator tests."""

    epochs: int


@train(params=ExampleTrainParameters)
def train(context: Context[ExampleTrainParameters]) -> None:
    """Consume one typed context in the direct decorator fixture."""
    assert context.params.epochs > 0


def test_train_decorator_exposes_stage_kind_and_parameter_model() -> None:
    """Expose the exact authoring metadata attached to one callable."""
    definition = stage_definition(train)

    assert definition.kind == "train"
    assert definition.parameter_model is ExampleTrainParameters


def test_stage_context_keeps_live_values_outside_pydantic() -> None:
    """Carry paths and generator objects through the frozen runtime dataclass."""
    generator = np.random.Generator(np.random.PCG64(7))
    context = Context(
        run_id="01JABCDEFGHJKMNPQRSTVWXYZ0",
        attempt_id=1,
        stage_id="train",
        params=ExampleTrainParameters(epochs=3),
        inputs=MappingProxyType({"dataset": Path("inputs/data.bin")}),
        artifacts=MappingProxyType({"parameters": Path("artifacts/model.bin")}),
        metrics=MappingProxyType({}),
        numpy_generators=MappingProxyType({"augmentation": generator}),
    )

    assert context.params.epochs == 3
    assert context.numpy_generators["augmentation"] is generator


def test_stage_loader_requires_exact_decorated_top_level_callable(
    tmp_path: Path,
) -> None:
    """Load the selected symbol only when its bytes and decorator agree."""
    raw = (
        b"from viper.stages import train\n"
        b"from viper import parameters\n\n"
        b"class Params(parameters.Train):\n"
        b"    epochs: int\n\n"
        b"@train(params=Params)\n"
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
    (package_root / "parameters.py").write_text(
        "from viper import parameters\n\n"
        "class ProjectParameters(parameters.Train):\n"
        "    epochs: int\n",
        encoding="utf-8",
    )
    raw = (
        b"from example_project.parameters import ProjectParameters\n"
        b"from viper.stages import train\n\n"
        b"@train(params=ProjectParameters)\n"
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

    assert stage_definition(loaded).parameter_model.__name__ == "ProjectParameters"
