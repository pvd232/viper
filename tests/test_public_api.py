"""Tests for the documented source and installed-package import inventory."""

from __future__ import annotations

import ast
import importlib
import inspect
from importlib import resources
from pathlib import Path

import viper
import viper.api as api
import viper.execution as execution
import viper.stages as stages
from viper._api import handlers
from viper.execution.errors import BenchmarkExecutionError, RunError
from viper.execution.results import BenchmarkExecutionResult, RunResult

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


def _root_package_statements(path: Path) -> list[ast.stmt]:
    """Return package-root statements after the module docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = list(tree.body)
    if ast.get_docstring(tree) is not None:
        body.pop(0)
    return body


def test_root_package_defines_no_forwarding_exports() -> None:
    """Require callers to import each public name from its defining module."""
    package_root = Path(viper.__file__)
    tree = ast.parse(package_root.read_text(encoding="utf-8"))

    assert ast.get_docstring(tree) == "VIPER package."
    assert _root_package_statements(package_root) == []


def test_root_package_rejects_a_forwarding_import(tmp_path: Path) -> None:
    """Reject a package-root import of a name owned by a public module."""
    package_root = tmp_path / "__init__.py"
    package_root.write_text(
        '"""VIPER package."""\n\nfrom .stages import Context\n',
        encoding="utf-8",
    )

    statements = _root_package_statements(package_root)

    assert len(statements) == 1
    assert isinstance(statements[0], ast.ImportFrom)


def test_every_public_module_imports() -> None:
    """Import every module promised by the public API inventory."""
    for name in PUBLIC_MODULES:
        assert importlib.import_module(f"viper.{name}") is not None


def test_execution_namespace_owns_only_operations() -> None:
    """Keep execution records and errors in their defining modules."""
    assert tuple(execution.__all__) == (
        "benchmark",
        "retry",
        "run",
    )
    assert issubclass(BenchmarkExecutionError, RuntimeError)
    assert issubclass(RunError, RuntimeError)
    assert BenchmarkExecutionResult.__module__ == "viper.execution.results"
    assert RunResult.__module__ == "viper.execution.results"
    assert callable(execution.run)
    assert callable(execution.retry)
    assert callable(execution.benchmark)


def test_stage_interface_uses_parsimonious_names() -> None:
    """Let the stage module supply the category once at each use site."""
    assert stages.Context.__module__ == "viper.stages"
    assert tuple(
        operation.__name__
        for operation in (stages.download, stages.build, stages.embed, stages.train)
    ) == ("download", "build", "embed", "train")
    assert stages.eval.__name__ == "eval"


def test_public_modules_export_only_local_definitions() -> None:
    """Reject a public ``__all__`` entry imported from another module."""
    package_root = Path(viper.__file__).parent
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if any(part.startswith("_") for part in relative.parts):
            continue
        module_name = ".".join(("viper", *relative.with_suffix("").parts))
        if module_name.endswith(".__init__"):
            module_name = module_name.removesuffix(".__init__")
        module = importlib.import_module(module_name)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        local_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else (node.target,)
                )
                local_names.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
        assert set(getattr(module, "__all__", ())) <= local_names, module_name


def test_api_exports_and_registries_are_complete() -> None:
    """Resolve every exported name and every declared API operation."""
    for name in api.__all__:
        assert getattr(api, name) is not None
    assert tuple(api.REQUEST_REGISTRY) == api.OPERATIONS
    assert tuple(api.HANDLER_REGISTRY) == api.OPERATIONS


def test_api_wrappers_preserve_handler_signatures() -> None:
    """Keep each public wrapper's arguments identical to its handler."""
    for name in (
        "validate_stage",
        "validate_resolved_stage",
        "validate_run_spec",
        "freeze_run",
        "preflight",
        "execute_stage",
        "run_request",
        "retry_request",
        "execute_benchmark",
        "plan_diff",
        "lineage",
        "status",
        "compare_runs",
        "verify_run",
        "verify_benchmark",
        "verify_pointer",
        "get_schema",
        "get_capabilities",
        "init_project",
    ):
        assert inspect.signature(getattr(api, name)) == inspect.signature(
            getattr(handlers, name)
        )


def test_parameter_categories_form_the_public_extension_namespace() -> None:
    """Expose one parameter category for each supported extension role."""
    parameters = importlib.import_module("viper.parameters")
    assert tuple(parameters.__all__) == (
        "Build",
        "Download",
        "Embed",
        "Evaluate",
        "HttpTransport",
        "Metric",
        "ParameterModelRef",
        "Train",
    )
    assert issubclass(parameters.Train, parameters.ParameterSet)


def test_installed_package_declares_inline_type_information() -> None:
    """Ship the PEP 561 marker beside VIPER's inline type annotations."""
    assert resources.files(viper).joinpath("py.typed").is_file()
