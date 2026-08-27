"""Tests for the documented source and installed-package import inventory."""

from __future__ import annotations

import importlib
from importlib import resources

import viper
from viper import application

ROOT_MODULES = (
    "application",
    "artifacts",
    "authoring",
    "benchmark",
    "execution",
    "experiments",
    "http",
    "ids",
    "inspection",
    "journal",
    "local_store",
    "materialization",
    "metrics",
    "parameters",
    "preflight",
    "references",
    "resume",
    "runs",
    "runtime",
    "stage_execution",
    "stages",
    "worker",
    "workspace",
)

ROOT_EXPORTS = (
    *ROOT_MODULES,
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

PUBLIC_MODULES = (
    *ROOT_MODULES,
    "serialization",
    "verification",
)


def test_root_package_exports_documented_modules() -> None:
    """Keep the root module inventory equal to the documented public surface."""
    assert tuple(viper.__all__) == ROOT_EXPORTS
    for name in ROOT_MODULES:
        assert getattr(viper, name).__name__ == f"viper.{name}"


def test_every_public_module_imports() -> None:
    """Import every module promised by the public API inventory."""
    for name in PUBLIC_MODULES:
        assert importlib.import_module(f"viper.{name}") is not None


def test_application_exports_and_registries_are_complete() -> None:
    """Resolve every exported name and every declared application operation."""
    for name in application.__all__:
        assert getattr(application, name) is not None
    assert tuple(application.REQUEST_REGISTRY) == application.OPERATIONS
    assert tuple(application.HANDLER_REGISTRY) == application.OPERATIONS


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
