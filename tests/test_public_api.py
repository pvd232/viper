"""Tests for the documented source and installed-package import inventory."""

from __future__ import annotations

import importlib
from importlib import resources

import viper
from viper import api, execution

PUBLIC_MODULES = (
    "api",
    "artifacts",
    "benchmark",
    "execution",
    "experiments",
    "http",
    "metrics",
    "parameters",
    "randomness",
    "references",
    "resume",
    "runs",
    "runtime",
    "serialization",
    "stages",
    "storage",
    "verification",
)

ROOT_EXPORTS = (
    "parameters",
    "StageContext",
    "DownloadContext",
    "HttpRetrievalHandle",
    "HttpTransportContext",
    "HttpTransportResult",
    "build_stage",
    "download_stage",
    "embed_stage",
    "evaluate_stage",
    "train_stage",
    "http_transport",
    "run",
    "retry",
)


def test_root_package_exports_project_interface() -> None:
    """Keep the package root limited to the project-facing interface."""
    assert tuple(viper.__all__) == ROOT_EXPORTS
    assert viper.parameters.__name__ == "viper.parameters"


def test_every_public_module_imports() -> None:
    """Import every module promised by the public API inventory."""
    for name in PUBLIC_MODULES:
        assert importlib.import_module(f"viper.{name}") is not None


def test_execution_namespace_uses_operation_names_once() -> None:
    """Expose execution operations and their public result and error types."""
    assert tuple(execution.__all__) == (
        "BenchmarkExecutionError",
        "BenchmarkExecutionResult",
        "RunError",
        "RunResult",
        "benchmark",
        "retry",
        "run",
    )
    assert issubclass(execution.BenchmarkExecutionError, RuntimeError)
    assert issubclass(execution.RunError, RuntimeError)
    assert callable(execution.run)
    assert callable(execution.retry)
    assert callable(execution.benchmark)


def test_api_exports_and_registries_are_complete() -> None:
    """Resolve every exported name and every declared API operation."""
    for name in api.__all__:
        assert getattr(api, name) is not None
    assert tuple(api.REQUEST_REGISTRY) == api.OPERATIONS
    assert tuple(api.HANDLER_REGISTRY) == api.OPERATIONS


def test_parameter_categories_form_the_public_extension_namespace() -> None:
    """Expose one parameter category for each supported extension role."""
    assert tuple(viper.parameters.__all__) == (
        "Build",
        "Download",
        "Embed",
        "Evaluate",
        "HttpTransport",
        "Metric",
        "ParameterModelRef",
        "Train",
    )
    assert issubclass(viper.parameters.Train, viper.parameters.ParameterSet)


def test_installed_package_declares_inline_type_information() -> None:
    """Ship the PEP 561 marker beside VIPER's inline type annotations."""
    assert resources.files(viper).joinpath("py.typed").is_file()
