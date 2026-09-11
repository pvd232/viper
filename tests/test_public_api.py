"""Tests for the documented source and installed-package import inventory."""

from __future__ import annotations

import ast
from importlib import resources
from importlib.util import resolve_name
from pathlib import Path

import viper
import viper.api as api
import viper.artifact_loaders as artifact_loaders
import viper.artifacts as artifacts
import viper.authoring as authoring
import viper.benchmark as benchmark
import viper.catalog as catalog
import viper.cli as cli
import viper.config as config
import viper.execution as execution
import viper.execution.errors as execution_errors
import viper.execution.results as execution_results
import viper.experiments as experiments
import viper.http as http
import viper.ids as ids
import viper.inputs as inputs
import viper.inspection as inspection
import viper.journal as journal
import viper.keys as keys
import viper.knowledge as knowledge
import viper.mcp as mcp
import viper.metrics as metrics
import viper.outputs as outputs
import viper.preflight as preflight
import viper.randomness as randomness
import viper.references as references
import viper.repository as repository
import viper.restoration as restoration
import viper.resume as resume
import viper.reuse as reuse
import viper.runs as runs
import viper.runtime as runtime
import viper.serialization as serialization
import viper.stages as stages
import viper.storage as storage
import viper.verification as verification
import viper.worker as worker
import viper.workspace as workspace
from viper import evidence
from viper.execution.errors import BenchmarkExecutionError, RunError
from viper.execution.results import BenchmarkExecutionResult, RunResult
from viper.stages import eval

PUBLIC_MODULES = (
    api,
    artifacts,
    benchmark,
    evidence,
    execution,
    experiments,
    http,
    metrics,
    config,
    randomness,
    references,
    resume,
    runs,
    runtime,
    serialization,
    stages,
    storage,
    verification,
)

PUBLIC_MODULES_BY_NAME = {
    module.__name__: module
    for module in (
        api,
        artifact_loaders,
        artifacts,
        authoring,
        benchmark,
        catalog,
        cli,
        config,
        evidence,
        execution,
        execution_errors,
        execution_results,
        experiments,
        http,
        ids,
        inputs,
        inspection,
        journal,
        keys,
        knowledge,
        mcp,
        metrics,
        outputs,
        preflight,
        repository,
        randomness,
        references,
        restoration,
        resume,
        reuse,
        runs,
        runtime,
        serialization,
        stages,
        storage,
        verification,
        worker,
        workspace,
    )
}


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
    assert all(module is not None for module in PUBLIC_MODULES)


def test_execution_namespace_owns_only_operations() -> None:
    """Keep execution records and errors in their defining modules."""
    assert tuple(execution.__all__) == (
        "benchmark",
        "retry",
        "restore",
        "run",
        "run_many",
    )
    assert issubclass(BenchmarkExecutionError, RuntimeError)
    assert issubclass(RunError, RuntimeError)
    assert BenchmarkExecutionResult.__module__ == "viper.execution.results"
    assert RunResult.__module__ == "viper.execution.results"
    assert callable(execution.run)
    assert callable(execution.retry)
    assert callable(execution.benchmark)
    assert callable(execution.restore)
    assert callable(execution.run_many)


def test_stage_interface_uses_parsimonious_names() -> None:
    """Let the stage module supply the category once at each use site."""
    assert stages.Context.__module__ == "viper.stages"
    assert tuple(
        operation.__name__ for operation in (stages.build, stages.embed, stages.train)
    ) == ("build", "embed", "train")
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
        module = PUBLIC_MODULES_BY_NAME[module_name]
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


def test_api_operations_are_locally_defined() -> None:
    """Require each registered API operation to be defined by viper.api."""
    assert tuple(api.HANDLER_REGISTRY) == api.OPERATIONS
    for operation in api.HANDLER_REGISTRY.values():
        assert operation.__module__ == "viper.api"
    package = Path(api.__file__).parent
    assert not package.joinpath("_api", "handlers.py").exists()


def test_verification_operations_depend_on_independent_evidence() -> None:
    """Keep verification operations separate from independent evidence records."""
    operations = (
        verification.verify_run_result,
        verification.verify_promoted_artifact,
        verification.verify_stage_reuse,
        verification.verify_stored_input_selections,
        verification.verify_stored_inputs,
        verification.verify_attempt_future_inputs,
        verification.verify_benchmark_result,
    )
    models = (
        evidence.VerificationError,
        evidence.VerificationPolicy,
        evidence.VerifiedArtifact,
        evidence.VerifiedBenchmarkResult,
        evidence.VerifiedInput,
        evidence.VerifiedRunPlan,
        evidence.VerifiedRunResult,
        evidence.VerifiedSnapshotFile,
    )
    assert all(value.__module__ == "viper.verification" for value in operations)
    assert all(value.__module__ == "viper.evidence" for value in models)
    assert set(verification.__all__) == {
        "verify_promoted_artifact",
        "verify_stored_input_selections",
        "verify_attempt_future_inputs",
        "verify_benchmark_result",
        "verify_stage_reuse",
        "verify_run_result",
        "verify_stored_inputs",
    }
    assert set(evidence.__all__) == {
        "VerificationError",
        "VerifiedInput",
        "VerifiedBenchmarkResult",
        "VerifiedRunPlan",
        "StorageFetcher",
        "VerificationPolicy",
        "VerifiedSnapshotFile",
        "StageSnapshot",
        "VerifiedRunResult",
        "VerifiedArtifact",
    }
    package = Path(viper.__file__).parent
    assert package.joinpath("verification.py").is_file()
    assert not package.joinpath("verification").exists()


def test_config_categories_form_the_public_extension_namespace() -> None:
    """Expose one config base for each supported extension role."""
    assert tuple(config.__all__) == (
        "BuildConfig",
        "ConfigOwner",
        "ConfigTypeRef",
        "Config",
        "DiagnosticConfig",
        "EmbedConfig",
        "EvalConfig",
        "HttpConfig",
        "MetricConfig",
        "TrainConfig",
        "type_ref",
    )
    assert issubclass(config.TrainConfig, config.Config)


def test_installed_package_declares_inline_type_information() -> None:
    """Ship the PEP 561 marker beside VIPER's inline type annotations."""
    assert resources.files(viper).joinpath("py.typed").is_file()


def test_stage_api_uses_target_decorators_params_and_keys() -> None:
    """Expose the concise parameter, key, and evaluation vocabulary."""
    assert keys.Train.MODEL == "model"
    assert keys.Train.RESUME_STATE == "resume_state"
    assert keys.Eval.MODEL == "model"
    assert keys.Eval.TEST == "test"
    assert keys.Eval.PREDICTIONS == "predictions"
    assert issubclass(config.EvalConfig, config.Config)
    assert callable(eval)


def test_env_vocabulary_is_complete() -> None:
    """Expose only the concise environment protocol vocabulary."""
    assert runtime.PythonEnvSpec.__name__ == "PythonEnvSpec"
    assert runtime.EnvSpec is not None
    assert runtime.ResolvedEnv is not None
    assert callable(runtime.observe_python_env)
    assert not hasattr(runtime, "PythonEnvironmentSpec")
    assert not hasattr(runtime, "EnvironmentSpec")


def test_verification_dependencies_are_acyclic() -> None:
    """Reject direct or transitive imports back into the public verifier."""
    package = Path(viper.__file__).parent
    modules: dict[str, Path] = {}
    for path in package.rglob("*.py"):
        parts = path.relative_to(package.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        modules[name] = path

    imports: dict[str, set[str]] = {}
    for name, path in modules.items():
        owner = name if path.name == "__init__.py" else name.rpartition(".")[0]
        dependencies: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                base = resolve_name(target, owner) if node.level else target
                dependencies.add(base)
                dependencies.update(f"{base}.{alias.name}" for alias in node.names)
        imports[name] = dependencies & modules.keys()

    def reachable(start: str) -> set[str]:
        """Follow module imports without executing package code."""
        seen: set[str] = set()
        pending = list(imports[start])
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(imports[current] - seen)
        return seen

    assert "viper.verification" not in reachable("viper.verification")
    evidence_dependencies = reachable("viper.evidence")
    assert "viper.verification" not in evidence_dependencies
    assert not any(
        name.startswith("viper._verification") for name in evidence_dependencies
    )
