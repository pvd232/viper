"""Planned acceptance tests for the PAC-01 config vocabulary migration."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from typing import get_args

import pytest
from pydantic import ValidationError

PAIR_BLOCK_ID = "P0-PAC-01"
REQUIREMENT_ID = "PAC-01"
PLANNED_DESTINATION = "tests/test_config_contract.py"


def test_config_module_exposes_only_approved_public_bases() -> None:
    """Expose the approved config class family from one public module."""
    config = importlib.import_module("viper.config")
    expected = {
        "Config",
        "BuildConfig",
        "EmbedConfig",
        "TrainConfig",
        "EvalConfig",
        "MetricConfig",
        "HttpConfig",
        "DiagnosticConfig",
        "ConfigTypeRef",
    }
    assert expected <= set(config.__all__)


def test_retired_parameter_modules_are_not_importable() -> None:
    """Remove compatibility modules for the retired alpha vocabulary."""
    assert importlib.util.find_spec("viper.params") is None
    assert importlib.util.find_spec("viper.parameters") is None
    assert importlib.util.find_spec("viper._parameter") is None


def test_config_bases_are_frozen_pydantic_models() -> None:
    """Validate and freeze user configuration at the authoring boundary."""
    config = importlib.import_module("viper.config")
    for name in (
        "Config",
        "BuildConfig",
        "EmbedConfig",
        "TrainConfig",
        "EvalConfig",
        "MetricConfig",
        "HttpConfig",
        "DiagnosticConfig",
    ):
        model = getattr(config, name)
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"


def test_workspace_config_can_extend_one_stage_base() -> None:
    """Allow a workspace to add typed fields to a stage-specific config."""
    config = importlib.import_module("viper.config")

    class TrainConfig(config.TrainConfig):
        epochs: int

    selected = TrainConfig(epochs=3)
    assert selected.epochs == 3
    with pytest.raises(ValidationError):
        TrainConfig(epochs="three")


def test_config_type_reference_uses_workspace_owner() -> None:
    """Distinguish workspace-authored config from installed VIPER config."""
    config = importlib.import_module("viper.config")
    fields = config.ConfigTypeRef.model_fields
    assert "owner" in fields
    assert set(get_args(fields["owner"].annotation)) == {"workspace", "viper"}


def test_stage_decorators_accept_config_not_params() -> None:
    """Use one keyword for every public stage decorator."""
    stages = importlib.import_module("viper.stages")
    for name in ("build", "embed", "train", "eval", "diagnostic"):
        parameters = inspect.signature(getattr(stages, name)).parameters
        assert "config" in parameters
        assert "params" not in parameters


def test_live_context_exposes_config_not_params() -> None:
    """Carry the validated config into workspace code without renaming it."""
    stages = importlib.import_module("viper.stages")
    fields = stages.Context.__dataclass_fields__
    assert "config" in fields
    assert "params" not in fields


def test_serialized_protocol_uses_config_fields_only() -> None:
    """Remove all retired config spellings from affected version-2 models."""
    modules_and_models = {
        "viper.stages": ("ParameterizedSpec", "StageContextBinding"),
        "viper.metrics": ("MetricSpec", "MetricExecutionReceipt"),
        "viper.experiments": ("VariantSpec",),
        "viper.http": ("WorkspaceHttpImplementationSpec",),
    }
    retired = {"params", "parameter_model", "stage_params"}
    for module_name, model_names in modules_and_models.items():
        module = importlib.import_module(module_name)
        for model_name in model_names:
            fields = set(getattr(module, model_name).model_fields)
            assert not fields & retired
            assert fields & {"config", "config_type", "stage_configs"}


def test_stage_definition_retains_the_config_class() -> None:
    """Bind a decorated callable to its exact config class."""
    config = importlib.import_module("viper.config")
    stages = importlib.import_module("viper.stages")

    class TrainConfig(config.TrainConfig):
        epochs: int

    @stages.train(config=TrainConfig)
    def fit(context: object) -> None:
        del context

    definition = stages.stage_definition(fit)
    assert definition.kind == "train"
    assert definition.config_type is TrainConfig
    assert not hasattr(definition, "parameter_model")
