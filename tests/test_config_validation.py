"""Tests for project-owned config identity and value validation."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.fixtures import artifact_loader_ref, stage_implementation_ref
from viper import config
from viper._config.validation import (
    ConfigValidationError,
    load_config_type,
    validate_config,
    validate_stage_config,
    verify_config_type_bytes,
)
from viper.config import ConfigTypeRef
from viper.inputs import StoredInputRef
from viper.keys import Train as TrainKeys
from viper.metrics import MetricObjectiveSpec
from viper.outputs import OutputSpec
from viper.references import ArtifactPointerRef
from viper.serialization import serialize_document
from viper.stages import (
    TrainSpec,
)


def _model_file(tmp_path: Path) -> tuple[Path, bytes]:
    """Write one constrained training-config class for focused tests."""
    raw = (
        b"from pydantic import Field\n"
        b"from viper import config\n\n"
        b"class TinyTrainConfig(config.TrainConfig):\n"
        b"    epochs: int = Field(gt=0)\n"
        b"    learning_rate: float = Field(gt=0)\n"
    )
    path = tmp_path / "tiny_train_config.py"
    path.write_bytes(raw)
    return path, raw


def _reference(raw: bytes) -> ConfigTypeRef:
    """Identify the exact config-type bytes written by the test."""
    return ConfigTypeRef(
        owner="workspace",
        path="project/config/tiny_train.py",
        symbol="TinyTrainConfig",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )


def test_config_type_validates_project_fields(tmp_path: Path) -> None:
    """Validate supplied values through the selected training category."""
    path, raw = _model_file(tmp_path)

    validated = validate_config(
        path,
        _reference(raw),
        config.TrainConfig.model_validate({"epochs": 2, "learning_rate": 0.1}),
        config.TrainConfig,
    )

    assert validated["epochs"] == 2
    assert validated["learning_rate"] == 0.1


def test_config_type_rejects_invalid_project_values(tmp_path: Path) -> None:
    """Propagate project Pydantic constraints for an invalid config value."""
    path, raw = _model_file(tmp_path)

    with pytest.raises(ValidationError, match="greater than 0"):
        validate_config(
            path,
            _reference(raw),
            config.TrainConfig.model_validate({"epochs": 0, "learning_rate": 0.1}),
            config.TrainConfig,
        )


def test_config_type_rejects_implicit_defaults(tmp_path: Path) -> None:
    """Require every effective project-model value in the frozen mapping."""
    raw = (
        b"from viper import config\n\n"
        b"class DefaultedTrainConfig(config.TrainConfig):\n"
        b"    epochs: int\n"
        b"    dropout: float = 0.1\n"
    )
    path = tmp_path / "defaulted.py"
    path.write_bytes(raw)
    reference = ConfigTypeRef(
        owner="workspace",
        path="project/config/defaulted.py",
        symbol="DefaultedTrainConfig",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )

    with pytest.raises(ConfigValidationError, match="every effective"):
        validate_config(
            path,
            reference,
            config.TrainConfig.model_validate({"epochs": 2}),
            config.TrainConfig,
        )


def test_config_type_rejects_type_coercion(tmp_path: Path) -> None:
    """Keep project field types identical to the frozen JSON value types."""
    path, raw = _model_file(tmp_path)

    with pytest.raises(ValidationError):
        validate_config(
            path,
            _reference(raw),
            config.TrainConfig.model_validate({"epochs": "2", "learning_rate": 0.1}),
            config.TrainConfig,
        )


def test_config_type_requires_the_stage_specific_base(tmp_path: Path) -> None:
    """Reject a selected class outside the training config category."""
    path = tmp_path / "wrong.py"
    path.write_text(
        'class WrongConfig:\n    """Uses no VIPER config category."""\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="subclass TrainConfig"):
        load_config_type(path, "WrongConfig", config.TrainConfig)


def test_config_type_reports_import_failure(tmp_path: Path) -> None:
    """Report an exception raised while importing the selected project file."""
    path = tmp_path / "broken.py"
    path.write_text(
        'raise RuntimeError("broken import")\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="raised during import"):
        load_config_type(path, "BrokenConfig", config.TrainConfig)


def test_config_type_rejects_tampered_bytes(tmp_path: Path) -> None:
    """Reject implementation bytes that differ from the frozen reference."""
    _, raw = _model_file(tmp_path)
    reference = _reference(raw)

    with pytest.raises(ConfigValidationError, match="byte count"):
        verify_config_type_bytes(reference, raw + b"# changed\n")


def test_stage_config_validation_runs_in_a_worker(tmp_path: Path) -> None:
    """Validate a stage while keeping project imports outside this process."""
    _, raw = _model_file(tmp_path)
    reference = _reference(raw)
    model_path = tmp_path / reference.path
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(raw)
    stage = TrainSpec(
        metric_ids=("training_loss",),
        objective=MetricObjectiveSpec(
            metric_id="training_loss",
            direction="min",
        ),
        implementation=stage_implementation_ref("project/train.py"),
        config_type=reference,
        inputs={
            "dataset": StoredInputRef(
                pointer=ArtifactPointerRef.model_validate(
                    {
                        "repository": "https://github.com/example/project",
                        "commit": "a" * 40,
                        "path": (
                            ".viper/pointers/"
                            + "a" * 64
                            + "/download/dataset.pointer.yaml"
                        ),
                    }
                ),
                path="inputs/datasets/example/data.bin",
                data_role="training",
            )
        },
        config=config.TrainConfig.model_validate({"epochs": 2, "learning_rate": 0.1}),
        outputs={  # pyright: ignore[reportArgumentType]
            TrainKeys.MODEL: OutputSpec(
                path="experiments/example/runs/baseline/"
                "01JABCDEFGHJKMNPQRSTVWXYZ0/artifacts/train/model/parameters.bin",
                loader=artifact_loader_ref("project/loaders/parameters.py"),
                data_role="training",
            ),
            TrainKeys.RESUME_STATE: OutputSpec(
                path="experiments/example/runs/baseline/"
                "01JABCDEFGHJKMNPQRSTVWXYZ0/artifacts/train/"
                "resume_state/resume.bin",
                loader=artifact_loader_ref("project/loaders/resume.py"),
                data_role="training",
            ),
        },
    )
    stage_path = tmp_path / "drafts/train.yaml"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_bytes(serialize_document(stage))

    validated = validate_stage_config(tmp_path, stage_path, stage)

    assert validated["epochs"] == 2
    assert validated["learning_rate"] == 0.1

    invalid_stage = stage.model_copy(
        update={
            "config": config.TrainConfig.model_validate(
                {"epochs": 0, "learning_rate": 0.1}
            )
        }
    )
    stage_path.write_bytes(serialize_document(invalid_stage))
    with pytest.raises(ConfigValidationError, match="worker failed"):
        validate_stage_config(tmp_path, stage_path, invalid_stage)
