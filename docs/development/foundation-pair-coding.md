# Foundation Pair-Coding Guide

This document contains the exact bounded foundation edits scheduled by Master Phase 0 of the
[master execution checklist](master-execution-checklist.md).
The checklist decides order. Each `PairBlock` below supplies the code, target,
focused test, and completion gate for one checkbox.

## 1. PairBlock contract

Each checklist checkbox owns exactly one `PairBlock`. A block may change
several targets when splitting the edit leaves the code unable to compile.
Every dependency names an earlier block. The documentation
validator rejects duplicate ownership, missing blocks, unknown requirements,
unknown targets, dependency cycles, placeholders, and invalid Python.

```text
ContractRequirement
        |
        v
Master Phase 0 checkbox -> PairBlock -> exact source target
                         |              |
                         v              v
                   focused test -> completion gate
```

The implementation uses five ordinary data-structure operations:

1. Dictionaries join stable requirement, block, path, symbol, test, and gate
   identifiers.
2. A directed graph records `depends_on` edges between blocks.
3. A topological sort proves that every producer precedes its consumer.
4. Reverse adjacency traversal later finds the tests and contract surfaces
   affected by a changed source node.
5. Canonical JSON plus SHA-256 identifies one reviewed graph and permits exact
   set difference between revisions.

This workflow compares foundation nodes through their stable identities. Graph
isomorphism applies later when two normalized experiment graphs lack shared IDs
and the question concerns structural equivalence. Exact revision identity uses
stable IDs and set difference.

### Audit boundary

The foundation work uses two audit layers.

The deterministic layer parses markers, manifests, Python syntax, live imports,
model fields, dependencies, targets, tests, and gates. It reports exact
mismatches. The worked-example check now preserves one rejected fixture that
imports the retired `RuleImplementation` model and supplies the retired
`ContractRequirement.phase` field. The test must continue to reject both.

The semantic layer asks whether a surviving name, edge, or guarantee means the
same thing as the contract. A reviewer still owns that judgment until the
system graph can derive the affected-file closure. Every semantic defect found
during review must become a rejected fixture and a deterministic validator
before its review cycle closes. This rule turns a one-time inference into a
repeatable regression check.


## 2. Project root

<!-- pair-block-definition: P0-PDR-01 -->
```toml pair-block
id = "P0-PDR-01"
requirements = ["PDR-01"]
targets = ["src/viper/project.py:Settings", "src/viper/project.py:find_root", "src/viper/project.py:resolve_root"]
tests = ["tests/test_project_init.py:test_init_establishes_discoverable_root"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py -k establishes_discoverable_root -q"
depends_on = []
```

Create `src/viper/project.py` with the root marker model and resolver.

```python pair-edit
"""Discover and validate the root of a Git-backed VIPER project."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from ._schema import ProtocolModel


class Settings(ProtocolModel):
    """Represent the ``[project]`` table stored in ``viper.toml``."""

    schema_version: Literal[1] = Field(
        description="Version of the project-marker schema."
    )


class RootError(ValueError):
    """Report a missing, invalid, or incompatible project root."""


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
```

<!-- pair-block-definition: P0-PDR-02 -->
```toml pair-block
id = "P0-PDR-02"
requirements = ["PDR-01"]
targets = ["src/viper/project.py:ROOT_FILES"]
tests = ["tests/test_project_init.py:test_init_establishes_discoverable_root"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py -k establishes_discoverable_root -q"
depends_on = ["P0-PDR-01"]
```

Define the reserved root files once, then unpack them at the start of the
mapping returned by `_project_files()`.

```python pair-edit
ROOT_FILES: dict[str, str] = {
    "viper.toml": "[project]\nschema_version = 1\n",
    "inputs/.gitkeep": "",
}
```

Keep the existing benchmark and experiment README entries in `_project_files()`.
Insert `**ROOT_FILES` as the first entry in its `files` mapping.

<!-- pair-block-definition: P0-PDR-03 -->
```toml pair-block
id = "P0-PDR-03"
requirements = ["PDR-02", "PDR-04"]
targets = ["src/viper/api.py:FreezeRunRequest", "src/viper/api.py:PreflightRequest", "src/viper/api.py:ExecuteStageRequest", "src/viper/api.py:RunRequest", "src/viper/api.py:ExecuteBenchmarkRequest", "src/viper/api.py:PlanDiffRequest", "src/viper/api.py:VerificationRequest", "src/viper/api.py:CompareRunsRequest", "src/viper/_api/handlers.py:_project_root", "src/viper/_api/handlers.py:freeze_run", "src/viper/_api/handlers.py:preflight", "src/viper/_api/handlers.py:execute_stage", "src/viper/_api/handlers.py:run_request", "src/viper/_api/handlers.py:retry_request", "src/viper/_api/handlers.py:execute_benchmark", "src/viper/_api/handlers.py:plan_diff"]
tests = ["tests/test_validation_architecture.py:test_operations_resolve_project_root_once"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k operations_resolve_project_root_once -q"
depends_on = ["P0-PDR-01"]
```

Replace every public `repository_root` field with an optional `root`. Comparison
requests use `left_root` and `right_root`. Resolve each value once in the
current operation body and pass the canonical `project_root` to internal code.
`P0-MOD-03` later moves these completed bodies into `api.py` unchanged.

```python pair-edit
class FreezeRunRequest(APIModel):
    """Select one run-plan draft and project root."""

    draft: Path
    root: Path | None = None


class PreflightRequest(APIModel):
    """Select one frozen plan for pre-execution inspection."""

    run_spec: Path
    root: Path | None = None


class ExecuteStageRequest(APIModel):
    """Select one stage from a frozen local run plan."""

    run_spec: Path
    stage_id: StageId
    root: Path | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class RunRequest(APIModel):
    """Select one frozen plan for complete local execution."""

    run_spec: Path
    root: Path | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class ExecuteBenchmarkRequest(APIModel):
    """Select one candidate run and frozen benchmark specification."""

    resolved_run: Path
    benchmark_spec: Path
    root: Path | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class PlanDiffRequest(APIModel):
    """Select two frozen plans and their project roots."""

    left_run_spec: Path
    right_run_spec: Path
    left_root: Path | None = None
    right_root: Path | None = None


class VerificationRequest(PathRequest):
    """Select evidence, its project root, and trusted source repositories."""

    root: Path | None = None
    trusted_source_repositories: frozenset[str] = Field(min_length=1)


class CompareRunsRequest(APIModel):
    """Select two terminal runs and their project roots."""

    left_path: Path
    right_path: Path
    left_root: Path | None = None
    right_root: Path | None = None
    trusted_source_repositories: frozenset[str] = Field(min_length=1)


def _project_root(root: Path | None, operation: OperationName) -> Path:
    """Resolve one operation root or raise its stable API failure."""
    try:
        return resolve_root(root)
    except RootError as error:
        raise ViperError(
            ViperFailure(
                operation=operation,
                origin="application",
                code="invalid_document",
                message="project root is invalid",
                details={
                    "root": None if root is None else root.as_posix(),
                },
            )
        ) from error


def freeze_run(request: FreezeRunRequest) -> FreezeRunSuccess:
    """Freeze one draft into canonical stage and run documents."""
    project_root = _project_root(request.root, "freeze_run")
    try:
        draft = load_run_plan_draft(request.draft)
        frozen = freeze_run_plan(project_root, draft)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _document_error("freeze_run", request.draft, error) from error
    return FreezeRunSuccess(run_id=frozen.run.run_id, files=frozen.files)


def preflight(request: PreflightRequest) -> PreflightSuccess:
    """Inspect one complete local plan before allocating a run attempt."""
    project_root = _project_root(request.root, "preflight")
    report = preflight_plan(project_root, request.run_spec)
    return PreflightSuccess(
        run_id=report.run_id,
        ready=report.ready,
        checks=report.checks,
    )


def execute_stage(request: ExecuteStageRequest) -> ExecuteStageSuccess:
    """Execute one selected stage and identify its declared outputs."""
    project_root = _project_root(request.root, "execute_stage")
    try:
        run = _load_model(request.run_spec, RunSpec)
        assert isinstance(run, RunSpec)
        reference = next(
            (stage for stage in run.stages if stage.stage_id == request.stage_id),
            None,
        )
        if reference is None:
            raise ValueError("selected stage is absent from the run plan")
        stage = load_stage_spec(project_root / reference.spec)
        result = execute_stage_process(
            project_root,
            run,
            reference,
            stage,
            timeout_seconds=request.timeout_seconds,
        )
    except StageExecutionError as error:
        raise ViperError(
            ViperFailure(
                operation="execute_stage",
                origin="application",
                code="execution_failed",
                message="stage process failed",
                details={"stage_id": request.stage_id},
            )
        ) from error
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _document_error("execute_stage", request.run_spec, error) from error
    return ExecuteStageSuccess(
        stage_id=request.stage_id,
        command=result.command,
        artifacts=result.artifacts,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_request(request: RunRequest) -> RunSuccess:
    """Execute, publish, and verify one complete run on the active host."""
    project_root = _project_root(request.root, "run")
    try:
        result = execute_run(
            project_root,
            request.run_spec,
            timeout_seconds=request.timeout_seconds,
        )
    except (RunError, StageExecutionError) as error:
        raise ViperError(
            ViperFailure(
                operation="run",
                origin="application",
                code="execution_failed",
                message="run failed",
            )
        ) from error
    except VerificationError as error:
        raise ViperError(
            ViperFailure(
                operation="run",
                origin="application",
                code="verification_failed",
                message="run verification failed",
            )
        ) from error
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _document_error("run", request.run_spec, error) from error
    run_spec = RunSpec.model_validate(parse_yaml_bytes(request.run_spec.read_bytes()))
    attempt_id = result.resolved_run.successful_attempt_id
    assert attempt_id is not None
    return RunSuccess(
        run_id=run_spec.run_id,
        attempt_id=attempt_id,
        resolved_attempt=(
            result.resolved_run_path.parent
            / "attempts"
            / str(attempt_id)
            / "resolved.yaml"
        ),
        resolved_run=result.resolved_run_path,
        journal=result.journal_path,
    )


def retry_request(request: RetryRequest) -> RetrySuccess:
    """Append one attempt to a failed frozen run and verify its result."""
    project_root = _project_root(request.root, "retry")
    try:
        result = execute_run(
            project_root,
            request.run_spec,
            timeout_seconds=request.timeout_seconds,
            retry=True,
        )
    except (RunError, StageExecutionError) as error:
        raise ViperError(
            ViperFailure(
                operation="retry",
                origin="application",
                code="execution_failed",
                message="retry failed",
            )
        ) from error
    except VerificationError as error:
        raise ViperError(
            ViperFailure(
                operation="retry",
                origin="application",
                code="verification_failed",
                message="retry verification failed",
            )
        ) from error
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _document_error("retry", request.run_spec, error) from error
    run_spec = RunSpec.model_validate(parse_yaml_bytes(request.run_spec.read_bytes()))
    attempt_id = result.resolved_run.successful_attempt_id
    assert attempt_id is not None
    return RetrySuccess(
        run_id=run_spec.run_id,
        attempt_id=attempt_id,
        resolved_run=result.resolved_run_path,
        journal=result.journal_path,
    )


def execute_benchmark(
    request: ExecuteBenchmarkRequest,
) -> ExecuteBenchmarkSuccess:
    """Execute and verify one independent benchmark confirmation."""
    project_root = _project_root(request.root, "execute_benchmark")
    try:
        execution = execute_benchmark_run(
            project_root,
            request.resolved_run,
            request.benchmark_spec,
            timeout_seconds=request.timeout_seconds,
        )
    except BenchmarkExecutionError as error:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark execution failed",
            )
        ) from error
    except (RunError, StageExecutionError) as error:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="execution_failed",
                message="benchmark confirmation failed",
            )
        ) from error
    except VerificationError as error:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark verification failed",
            )
        ) from error
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _document_error(
            "execute_benchmark",
            request.resolved_run,
            error,
        ) from error
    return ExecuteBenchmarkSuccess(
        result=execution.result,
        result_path=execution.result_path,
    )


def plan_diff(request: PlanDiffRequest) -> PlanDiffSuccess:
    """Compare two frozen plans and their referenced stage specs."""
    left_root = _project_root(request.left_root, "plan_diff")
    right_root = _project_root(request.right_root, "plan_diff")
    try:
        result = compare_frozen_plans(
            left_root,
            request.left_run_spec,
            right_root,
            request.right_run_spec,
        )
    except (InspectionError, OSError, ValueError, yaml.YAMLError) as error:
        raise ViperError(
            ViperFailure(
                operation="plan_diff",
                origin="application",
                code="invalid_document",
                message="frozen plans could not be compared",
                details={
                    "left_run_spec": request.left_run_spec.as_posix(),
                    "right_run_spec": request.right_run_spec.as_posix(),
                },
            )
        ) from error
    return PlanDiffSuccess(
        left_run_id=result.left_run_id,
        right_run_id=result.right_run_id,
        identical=result.identical,
        changes=result.changes,
    )
```

The existing verification operation bodies keep their optional injected
fetchers. `P0-PDR-05` binds their default local fetchers to `request.root`,
`request.left_root`, or `request.right_root` after the store accepts canonical
project roots.

<!-- pair-block-definition: P0-PDR-04 -->
```toml pair-block
id = "P0-PDR-04"
requirements = ["PDR-04"]
targets = ["src/viper/cli.py:add_root", "src/viper/api.py:_stage_parser", "src/viper/api.py:run", "src/viper/api.py:retry"]
tests = ["tests/test_documentation.py:test_project_root_vocabulary"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k project_root_vocabulary -q"
depends_on = ["P0-PDR-03"]
```

Use one CLI helper for the ordinary, left, and right forms. Its `name` selects
both the option spelling and request-field destination.

```python pair-edit
RootArg = Literal["root", "left_root", "right_root"]


def add_root(parser: argparse.ArgumentParser, name: RootArg = "root") -> None:
    """Add one optional project-root override to a command parser."""
    option = f"--{name.replace('_', '-')}"
    parser.add_argument(
        option,
        dest=name,
        type=Path,
        default=None,
        help="VIPER project root; defaults to discovery from the current directory",
    )


def _stage_parser() -> argparse.ArgumentParser:
    """Build the parser used by one project stage entrypoint."""
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--run", required=True, dest="run_spec", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=float)
    return parser


def run(
    stage_callable: Callable[[Any], None],
    *,
    argv: Sequence[str] | None = None,
) -> RunSuccess:
    """Bind one launched callable to a frozen stage and execute its run."""
    arguments = _stage_parser().parse_args(None if argv is None else list(argv))
    project_root = resolve_root(arguments.root)
    run_spec_path = arguments.run_spec
    if not run_spec_path.is_absolute():
        run_spec_path = project_root / run_spec_path
    run_spec_path = run_spec_path.resolve()
    if not run_spec_path.is_relative_to(project_root):
        raise PythonRunError("run specification is outside the project root")
    run_spec = RunSpec.model_validate(parse_yaml_bytes(run_spec_path.read_bytes()))
    selected = next(
        (stage for stage in run_spec.stages if stage.stage_id == arguments.stage),
        None,
    )
    if selected is None:
        raise PythonRunError("selected stage ID is absent from the run plan")
    stage_path = (project_root / selected.spec).resolve()
    stage_raw = stage_path.read_bytes()
    if len(stage_raw) != selected.bytes or hashlib.sha256(stage_raw).hexdigest() != (
        selected.sha256
    ):
        raise PythonRunError("selected stage specification differs from RunStageRef")
    stage = load_stage_spec(stage_path)
    if not isinstance(stage, ParameterizedSpec):
        raise PythonRunError("selected stage is not parameterized")

    source_file = getattr(stage_callable, "__viper_source_path__", None)
    if source_file is None:
        source_file = inspect.getsourcefile(stage_callable)
    if source_file is None:
        raise PythonRunError("launched stage callable has no source file")
    source_path = Path(source_file).resolve()
    if not source_path.is_relative_to(project_root):
        raise PythonRunError("launched stage callable is outside the project root")
    relative_source = source_path.relative_to(project_root).as_posix()
    if relative_source != stage.implementation.path:
        raise PythonRunError("launched stage callable path differs from the plan")
    if stage_callable.__name__ != stage.implementation.symbol:
        raise PythonRunError("launched stage callable symbol differs from the plan")
    verify_stage_implementation_bytes(stage.implementation, source_path.read_bytes())
    definition = stage_definition(stage_callable)
    if definition.kind != stage.kind:
        raise PythonRunError("launched stage decorator kind differs from the plan")
    if definition.parameter_model.__name__ != stage.parameter_model.symbol:
        raise PythonRunError("launched parameter class differs from the plan")

    return run_request(
        RunRequest(
            run_spec=run_spec_path,
            root=project_root,
            timeout_seconds=arguments.timeout_seconds,
        )
    )


def retry(
    run_spec: Path,
    *,
    root: Path | None = None,
    timeout_seconds: float | None = None,
) -> RetrySuccess:
    """Append one attempt to a failed frozen run."""
    project_root = resolve_root(root)
    selected = run_spec if run_spec.is_absolute() else project_root / run_spec
    selected = selected.resolve()
    if not selected.is_relative_to(project_root):
        raise PythonRunError("run specification is outside the project root")
    return retry_request(
        RetryRequest(
            run_spec=selected,
            root=project_root,
            timeout_seconds=timeout_seconds,
        )
    )
```

Call `add_root()` for `freeze-run`, `preflight`, `execute-stage`, `run`,
`retry`, `execute-benchmark`, `verify-run`, `lineage`, `verify-benchmark`, and
`verify-pointer`. Call `add_root(plan_diff, "left_root")` and
`add_root(plan_diff, "right_root")`. Use the same two calls for
`compare-runs`. Delete every `--repository-root`, `--left-repository-root`, and
`--right-repository-root` option.

<!-- pair-block-definition: P0-PDR-06 -->
```toml pair-block
id = "P0-PDR-06"
requirements = ["PDR-03"]
targets = ["src/viper/project.py:PathError", "src/viper/project.py:PathOperation", "src/viper/project.py:resolve_path"]
tests = ["tests/test_validation_architecture.py:test_project_paths_reject_symlinks"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k project_paths_reject_symlinks -q"
depends_on = ["P0-PDR-01"]
```

Add the path error, operation vocabulary, and resolver to `src/viper/project.py`.

```python pair-edit
class PathError(RootError):
    """Report a path that violates project-root custody."""


PathOperation = Literal["read", "write"]


def resolve_path(
    project_root: Path,
    path: RepoRelPath,
    *,
    operation: PathOperation,
) -> Path:
    """Return one symlink-free path beneath the canonical project root."""
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
```

`read` requires the final file. `write` permits a missing suffix because its
caller may create the destination directories after this boundary check.

<!-- pair-block-definition: P0-PDR-05 -->
```toml pair-block
id = "P0-PDR-05"
requirements = ["PDR-02"]
targets = ["src/viper/storage.py:LocalArtifactStore.__init__", "src/viper/_api/handlers.py:_local_fetcher"]
tests = ["tests/test_storage.py:test_store_uses_selected_project_root"]
gate = "conda run -n mantra python -m pytest tests/test_storage.py -k uses_selected_project_root -q"
depends_on = ["P0-PDR-04", "P0-PDR-06"]
```

Replace the store constructor with the shared project-path boundary.

```python pair-edit
class LocalArtifactStore:
    def __init__(self, project_root: Path, store: RepoRelPath = ".viper/store"):
        """Bind the immutable store beneath one canonical project root."""
        self.project_root = project_root.resolve(strict=True)
        self.store = store
        try:
            self.store_root = resolve_path(
                self.project_root,
                store,
                operation="write",
            )
        except PathError as error:
            raise LocalStoreError("local store escapes the project root") from error


def _local_fetcher(
    root: Path | None,
    operation: OperationName,
    fetcher: StorageFetcher | None,
) -> StorageFetcher:
    """Use an injected fetcher or bind the selected project's local store."""
    if fetcher is not None:
        return fetcher
    project_root = _project_root(root, operation)
    return LocalArtifactStore(project_root).fetch


# verify_run()
fetcher = _local_fetcher(request.root, "verify_run", fetcher)

# lineage()
fetcher = _local_fetcher(request.root, "lineage", fetcher)

# verify_benchmark()
fetcher = _local_fetcher(request.root, "verify_benchmark", fetcher)

# verify_pointer()
fetcher = _local_fetcher(request.root, "verify_pointer", fetcher)

# compare_runs()
left_fetcher = _local_fetcher(
    request.left_root,
    "compare_runs",
    left_fetcher,
)
right_fetcher = _local_fetcher(
    request.right_root,
    "compare_runs",
    right_fetcher,
)
```

Rename internal `repository_root` attributes to `project_root`. Preserve the
persisted `LocalFileRef.store` value `.viper/store`. Import
`LocalArtifactStore` in `_api/handlers.py`, add `_local_fetcher()` beside
`_project_root()`, and place each shown binding before its verifier call.
Pass those bound values to the existing verifier calls. An explicitly injected
fetcher stays active; its local project root remains optional.

## 3. Contract traceability

The dedicated [Contract Traceability Pair-Coding
guide](contract-traceability-pair-coding.md) owns `P0-CRT-01` through
`P0-CRT-05` and `P0-PROOF-01` through `P0-PROOF-04`. It contains the
complete proposed edits, focused tests, dependencies, stop conditions, and
phase gate. This combined reference links to that single source.

## 4. Public module ownership

<!-- pair-block-definition: P0-MOD-01 -->
```toml pair-block
id = "P0-MOD-01"
requirements = ["MOD-01"]
targets = ["src/viper/verification/models.py:VerificationPolicy", "src/viper/verification/models.py:VerifiedRunResult"]
tests = ["tests/test_public_api.py:test_verification_namespace_separates_operations_and_models"]
gate = "conda run -n mantra python -m pytest tests/test_public_api.py -k verification_namespace_separates_operations_and_models -q"
depends_on = ["P0-CRT-05"]
```

Create `src/viper/verification/models.py`. Move these declarations from
`verification.py` while preserving their fields, methods, and aliases.

```python pair-edit
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .._schema import DataRole, RepoRelPath
from ..artifacts import ResolvedArtifact
from ..benchmark import BenchmarkResult, BenchmarkSpec
from ..experiments import ExperimentSpec, VariantSpec
from ..ids import StageId
from ..metrics import Measurement
from ..references import (
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
)
from ..runs import ResolvedRun, RunAttempt, RunSpec
from ..stages import BaseSpec, ResolvedBaseSpec


class VerificationError(ValueError):
    """A referenced file could not be retrieved or failed verification."""


@dataclass(frozen=True)
class VerificationPolicy:
    """Define which source repositories may execute project-owned code."""

    trusted_source_repositories: frozenset[str]

    def permits_source(self, repository: object) -> bool:
        """Return whether project code from one repository may execute."""
        normalized = str(repository).rstrip("/")
        return normalized in {
            trusted.rstrip("/") for trusted in self.trusted_source_repositories
        }


@dataclass(frozen=True)
class VerifiedSnapshotFile:
    """One snapshot file whose bytes match its recorded identity."""

    reference: SnapshotFileRef
    content: bytes


@dataclass(frozen=True)
class VerifiedArtifact:
    """One resolved artifact and all of its verified files."""

    artifact: ResolvedArtifact
    files: tuple[VerifiedSnapshotFile, ...]
    data_role: DataRole
    references: tuple[ResolvedFileRef, ...] = ()


@dataclass(frozen=True)
class VerifiedInput:
    """A verified artifact and the local path where a stage consumes it."""

    path: RepoRelPath
    data_role: DataRole
    artifact: ResolvedArtifact
    files: tuple[VerifiedSnapshotFile, ...]
    references: tuple[ResolvedFileRef, ...] = ()


@dataclass(frozen=True)
class VerifiedRunPlan:
    """The connected records constituting one verified run plan."""

    run: RunSpec
    experiment: ExperimentSpec
    variant: VariantSpec
    benchmark: BenchmarkSpec | None
    stages: dict[StageId, BaseSpec]


@dataclass(frozen=True)
class VerifiedRunResult:
    """A verified terminal run and its connected records."""

    result: ResolvedRun
    plan: VerifiedRunPlan
    attempts: tuple[RunAttempt, ...]
    resolved_stages: dict[StageId, ResolvedBaseSpec]
    measurements: tuple[Measurement, ...]


@dataclass(frozen=True)
class VerifiedBenchmarkResult:
    """A benchmark result and its verified run and confirmation execution."""

    result: BenchmarkResult
    run: VerifiedRunResult
    confirmation: RunAttempt
    confirmation_stages: dict[StageId, ResolvedBaseSpec]
    confirmation_measurements: tuple[Measurement, ...]


StorageFetcher = Callable[[StorageModel], bytes]
StageSnapshot = StageResultSnapshotRef | LocalStageResultSnapshotRef


__all__ = [
    "StageSnapshot",
    "StorageFetcher",
    "VerificationError",
    "VerificationPolicy",
    "VerifiedArtifact",
    "VerifiedBenchmarkResult",
    "VerifiedInput",
    "VerifiedRunPlan",
    "VerifiedRunResult",
    "VerifiedSnapshotFile",
]
```

<!-- pair-block-definition: P0-MOD-02 -->
```toml pair-block
id = "P0-MOD-02"
requirements = ["MOD-01"]
targets = ["src/viper/verification/__init__.py:verify_run_result"]
tests = ["tests/test_public_api.py:test_verification_namespace_separates_operations_and_models", "tests/test_verification.py:test_verify_complete_run"]
gate = "conda run -n mantra python -m pytest tests/test_public_api.py tests/test_verification.py -k 'verification_namespace_separates_operations_and_models or verify_complete_run' -q"
depends_on = ["P0-MOD-01"]
```

Create `src/viper/verification/__init__.py`. Move these six public operation
bodies from `verification.py` while preserving their signatures and statements:
`verify_run_result`, `verify_promoted_artifact`,
`verify_stored_input_selections`, `verify_stored_inputs`,
`verify_attempt_future_inputs`, and `verify_benchmark_result`. Import shared
types from `.models`. Delete `src/viper/verification.py` after every importer
uses the package.

This block contains the complete target operation module.

```python pair-edit
from __future__ import annotations

from collections.abc import Mapping

import yaml

from .._schema import (
    PARAMETERS,
    PARAMETERS_INPUT,
    PREDICTIONS,
    RESUME_STATE,
    RESUME_STATE_INPUT,
    DataRole,
    RepoRelPath,
)
from ..artifacts import ArtifactPointer, ResolvedArtifact, StageArtifactRef
from ..benchmark import BenchmarkResult
from ..ids import InputName, StageId
from ..inputs import (
    FutureInputRef,
    ResolvedFutureInputRef,
    ResolvedStoredInputRef,
    StoredInputRef,
)
from ..metrics import Measurement, MetricVerificationReceipt
from ..references import GitFileRef, ResolvedFileRef, SnapshotFileRef
from ..runs import ResolvedRun, RunAttempt, RunSpec
from ..serialization import document_digest, parse_yaml_bytes
from ..stages import (
    EvaluateSpec,
    InternalSpec,
    ResolvedBaseSpec,
    ResolvedInternalSpec,
    TrainSpec,
)
from .._verification.attempt import (
    verify_attempt_files,
    verify_attempt_journal,
    verify_attempt_stages,
    verify_measurement_stage_times,
)
from .._verification.metrics import verify_recomputed_metrics
from .._verification.paths import run_root
from .._verification.plan import verify_run_plan
from .._verification.storage import (
    artifact_revision_identity,
    load_verified_artifact,
    read_attempt_reference,
    read_resolved_file,
    snapshot_identity,
    verify_run_attempt_references,
    verify_snapshot_artifact,
)
from .models import (
    StorageFetcher,
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedBenchmarkResult,
    VerifiedInput,
    VerifiedRunResult,
)


__all__ = [
    "verify_attempt_future_inputs",
    "verify_benchmark_result",
    "verify_promoted_artifact",
    "verify_run_result",
    "verify_stored_input_selections",
    "verify_stored_inputs",
]


def verify_run_result(
    resolved_run: ResolvedRun,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> VerifiedRunResult:
    """Verify a terminal run from its RunSpec through every completed attempt."""
    plan = verify_run_plan(resolved_run, fetcher=fetcher)
    attempts = verify_run_attempt_references(
        resolved_run,
        plan.run,
        fetcher=fetcher,
    )
    all_measurements: list[Measurement] = []
    successful_stages: dict[StageId, ResolvedBaseSpec] = {}
    stage_result_snapshots: set[tuple[str, ...]] = set()
    attempt_file_snapshots: set[tuple[str, ...]] = set()

    for attempt in attempts:
        current_stage_result_snapshots = {
            snapshot_identity(stage.snapshot) for stage in attempt.resolved_stages
        }
        if stage_result_snapshots & current_stage_result_snapshots:
            raise VerificationError(
                "run attempts must use distinct stage-result snapshots"
            )
        stage_result_snapshots.update(current_stage_result_snapshots)

        current_attempt_file_snapshots = {
            identity
            for reference in (
                attempt.journal,
                *attempt.measurement_files,
                *attempt.metric_verification_files,
                *attempt.log_files,
            )
            if (identity := artifact_revision_identity(reference.stored_at)) is not None
        }
        if attempt_file_snapshots & current_attempt_file_snapshots:
            raise VerificationError(
                "run attempts must use distinct measurement and log snapshots"
            )
        attempt_file_snapshots.update(current_attempt_file_snapshots)

    if stage_result_snapshots & attempt_file_snapshots:
        raise VerificationError(
            "stage-result and attempt-file snapshots must be distinct"
        )

    for attempt in attempts:
        complete = attempt.status == "succeeded"
        verify_attempt_journal(attempt, plan.run, fetcher=fetcher)
        verified_stages = verify_attempt_stages(
            attempt,
            plan.run,
            plan.stages,
            require_complete=complete,
            policy=policy,
            fetcher=fetcher,
        )
        stored_inputs = verify_stored_inputs(
            verified_stages,
            policy=policy,
            fetcher=fetcher,
        )
        future_inputs = verify_attempt_future_inputs(
            attempt,
            plan.run,
            verified_stages,
            fetcher=fetcher,
        )
        attempt_measurements = verify_attempt_files(
            attempt,
            plan.run,
            plan.experiment,
            plan.stages,
            fetcher=fetcher,
        )
        verify_measurement_stage_times(
            verified_stages,
            attempt_measurements,
            plan.experiment,
        )
        verify_recomputed_metrics(
            attempt,
            plan,
            verified_stages,
            attempt_measurements,
            stored_inputs,
            future_inputs,
            policy=policy,
            fetcher=fetcher,
        )
        all_measurements.extend(attempt_measurements)
        if attempt.attempt_id == resolved_run.successful_attempt_id:
            successful_stages = verified_stages

    if resolved_run.status == "succeeded":
        estimator_stage = successful_stages.get(plan.run.estimator.stage_id)
        if estimator_stage is None:
            raise VerificationError("successful run has no estimator-producing stage")
        if plan.run.estimator.artifact_name not in estimator_stage.artifacts:
            raise VerificationError("successful run has no selected estimator artifact")

    return VerifiedRunResult(
        result=resolved_run,
        plan=plan,
        attempts=attempts,
        resolved_stages=successful_stages,
        measurements=tuple(all_measurements),
    )

def verify_promoted_artifact(
    pointer: ArtifactPointer,
    *,
    policy: VerificationPolicy,
    expected_data_role: DataRole | None = None,
    materialization_path: RepoRelPath | None = None,
    fetcher: StorageFetcher | None = None,
) -> VerifiedArtifact:
    """Follow a promoted artifact pointer through its completed producer run."""
    resolved_run_raw = read_resolved_file(pointer.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(resolved_run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "artifact pointer run is not a valid ResolvedRun document"
        ) from exc

    verified_run = verify_run_result(resolved_run, policy=policy, fetcher=fetcher)
    expected_run_path = f"{run_root(verified_run.plan.run)}/resolved.yaml"
    if pointer.run.stored_at.path != expected_run_path:
        raise VerificationError(
            "artifact pointer run reference is outside the canonical run path"
        )

    if (
        verified_run.plan.run.benchmark_id is not None
        and pointer.artifact == verified_run.plan.run.estimator
        and pointer.benchmark_result is None
    ):
        raise VerificationError(
            "promotion of a benchmarked estimator requires a benchmark result"
        )

    producer_spec = verified_run.resolved_stages.get(pointer.artifact.stage_id)
    if producer_spec is None:
        raise VerificationError("artifact pointer selects an absent producer stage")

    artifact = producer_spec.artifacts.get(pointer.artifact.artifact_name)
    if artifact is None:
        raise VerificationError("artifact pointer selects an undeclared artifact")
    declaration = producer_spec.spec.artifacts[pointer.artifact.artifact_name]

    if pointer.benchmark_result is not None:
        benchmark_result_raw = read_resolved_file(
            pointer.benchmark_result,
            fetcher=fetcher,
        )
        try:
            benchmark_result = BenchmarkResult.model_validate(
                parse_yaml_bytes(benchmark_result_raw)
            )
        except (yaml.YAMLError, ValueError) as exc:
            raise VerificationError(
                "artifact pointer benchmark result is invalid"
            ) from exc

        verify_benchmark_result(
            benchmark_result,
            policy=policy,
            fetcher=fetcher,
        )
        expected_result_path = (
            f"{run_root(verified_run.plan.run)}/benchmark.result.yaml"
        )
        if pointer.benchmark_result.stored_at.path != expected_result_path:
            raise VerificationError(
                "artifact pointer benchmark result is outside the canonical run path"
            )
        if benchmark_result.status != "passed":
            raise VerificationError(
                "artifact pointer benchmark result must have passed"
            )
        if benchmark_result.run != pointer.run:
            raise VerificationError(
                "artifact pointer and benchmark result select different runs"
            )
        if pointer.artifact != verified_run.plan.run.estimator:
            raise VerificationError("benchmark promotion must select the run estimator")

    successful_attempt = next(
        attempt
        for attempt in verified_run.attempts
        if attempt.attempt_id == resolved_run.successful_attempt_id
    )
    producer_stage = next(
        stage
        for stage in successful_attempt.resolved_stages
        if stage.stage_id == pointer.artifact.stage_id
    )
    verified_artifact = verify_snapshot_artifact(
        producer_stage,
        artifact,
        data_role=declaration.data_role,
        fetcher=fetcher,
    )
    if (
        expected_data_role is not None
        and verified_artifact.data_role != expected_data_role
    ):
        raise VerificationError(
            f"selected artifact data_role {verified_artifact.data_role!r} does not "
            f"match stored input data_role {expected_data_role!r}"
        )
    if materialization_path is not None:
        load_verified_artifact(
            verified_run.plan.run,
            declaration,
            pointer.artifact.artifact_name,
            verified_artifact,
            policy=policy,
            materialization_path=materialization_path,
            fetcher=fetcher,
        )
    return verified_artifact


def verify_stored_input_selections(
    stage_id: StageId,
    stage_spec: InternalSpec,
    pointers: Mapping[InputName, ArtifactPointer],
) -> None:
    """Verify relationships among stored pointers consumed by one stage."""
    if isinstance(stage_spec, TrainSpec):
        model_input = stage_spec.inputs.get(PARAMETERS_INPUT)
        state_input = stage_spec.inputs.get(RESUME_STATE_INPUT)
        if isinstance(model_input, StoredInputRef) and isinstance(
            state_input,
            StoredInputRef,
        ):
            model_pointer = pointers[PARAMETERS_INPUT]
            state_pointer = pointers[RESUME_STATE_INPUT]
            if model_pointer.run != state_pointer.run:
                raise VerificationError(
                    f"stored checkpoint inputs of stage {stage_id!r} must select "
                    "one resolved run"
                )
            if model_pointer.artifact.stage_id != state_pointer.artifact.stage_id:
                raise VerificationError(
                    f"stored checkpoint inputs of stage {stage_id!r} must select "
                    "one producer stage"
                )
            if model_pointer.artifact.artifact_name != PARAMETERS:
                raise VerificationError(
                    f"stored checkpoint model input of stage {stage_id!r} must "
                    "select parameters"
                )
            if state_pointer.artifact.artifact_name != RESUME_STATE:
                raise VerificationError(
                    f"stored checkpoint state input of stage {stage_id!r} must "
                    "select resume_state"
                )

    if isinstance(stage_spec, EvaluateSpec):
        model_input = stage_spec.inputs[PARAMETERS_INPUT]
        if isinstance(model_input, StoredInputRef):
            model_pointer = pointers[PARAMETERS_INPUT]
            if model_pointer.artifact.artifact_name != PARAMETERS:
                raise VerificationError(
                    f"stored evaluation model input of stage {stage_id!r} must "
                    "select parameters"
                )


def verify_stored_inputs(
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify every promoted artifact consumed by the resolved stages."""
    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}

    for stage_id, resolved_stage in resolved_stages.items():
        if not isinstance(resolved_stage, ResolvedInternalSpec):
            continue

        stage_inputs: dict[InputName, VerifiedInput] = {}
        parsed_pointers: dict[InputName, ArtifactPointer] = {}

        for input_name, spec_input in resolved_stage.spec.inputs.items():
            if not isinstance(spec_input, StoredInputRef):
                continue

            resolved_input = resolved_stage.inputs.get(input_name)
            if not isinstance(resolved_input, ResolvedStoredInputRef):
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} has no "
                    "resolved stored-input reference"
                )

            if resolved_input.pointer.stored_at != spec_input.pointer:
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} resolved "
                    "a different pointer location than the stage spec"
                )

            pointer_raw = read_resolved_file(
                resolved_input.pointer,
                fetcher=fetcher,
            )
            try:
                pointer = ArtifactPointer.model_validate(parse_yaml_bytes(pointer_raw))
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    f"stored input {input_name!r} of stage {stage_id!r} pointer "
                    "is not a valid ArtifactPointer document"
                ) from exc

            parsed_pointers[input_name] = pointer

            verified_artifact = verify_promoted_artifact(
                pointer,
                policy=policy,
                expected_data_role=spec_input.data_role,
                materialization_path=spec_input.path,
                fetcher=fetcher,
            )
            stage_inputs[input_name] = VerifiedInput(
                path=spec_input.path,
                data_role=spec_input.data_role,
                artifact=verified_artifact.artifact,
                files=verified_artifact.files,
                references=verified_artifact.references,
            )

        verify_stored_input_selections(
            stage_id,
            resolved_stage.spec,
            parsed_pointers,
        )

        if stage_inputs:
            verified_inputs[stage_id] = stage_inputs

    return verified_inputs


def verify_attempt_future_inputs(
    attempt: RunAttempt,
    run: RunSpec,
    resolved_stages: Mapping[StageId, ResolvedBaseSpec],
    *,
    fetcher: StorageFetcher | None = None,
) -> dict[StageId, dict[InputName, VerifiedInput]]:
    """Verify same-attempt inputs consumed by every completed stage."""
    stage_positions: dict[StageId, int] = {}
    for position, stage_reference in enumerate(run.stages):
        stage_positions[stage_reference.stage_id] = position

    completed_stages = {stage.stage_id: stage for stage in attempt.resolved_stages}

    verified_inputs: dict[StageId, dict[InputName, VerifiedInput]] = {}
    for consumer_stage_id, resolved_consumer_spec in resolved_stages.items():
        # Not checking download specs because they don't have any inputs to verify
        if not isinstance(resolved_consumer_spec, ResolvedInternalSpec):
            continue

        stage_inputs: dict[InputName, VerifiedInput] = {}

        for input_name, spec_input in resolved_consumer_spec.spec.inputs.items():
            if not isinstance(spec_input, FutureInputRef):
                continue

            resolved_input = resolved_consumer_spec.inputs[input_name]

            if not isinstance(resolved_input, ResolvedFutureInputRef):
                raise VerificationError(
                    f"future input {input_name!r} of stage "
                    f"{consumer_stage_id!r} has no resolved future-input "
                    "reference"
                )

            producer_stage_id = spec_input.producer_stage_id

            if consumer_stage_id not in stage_positions:
                raise VerificationError(
                    f"consumer stage {consumer_stage_id!r} is not in the run plan"
                )

            if producer_stage_id not in stage_positions:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} is not in the run plan"
                )

            if stage_positions[producer_stage_id] >= stage_positions[consumer_stage_id]:
                raise VerificationError(
                    f"future input {input_name!r} must name an earlier stage"
                )

            resolved_producer_spec = resolved_stages.get(producer_stage_id)

            if resolved_producer_spec is None:
                raise VerificationError(
                    f"resolved producer stage {producer_stage_id!r} is missing"
                )

            producer_stage_reference = completed_stages.get(producer_stage_id)
            if producer_stage_reference is None:
                raise VerificationError(
                    f"successful attempt has no resolved stage for "
                    f"{producer_stage_id!r}"
                )

            if resolved_input.producer != producer_stage_reference:
                raise VerificationError(
                    f"future input {input_name!r} of stage "
                    f"{consumer_stage_id!r} does not identify the completed "
                    "producer stage"
                )

            artifact_name = spec_input.producer_artifact
            artifact = resolved_producer_spec.artifacts.get(artifact_name)
            if artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} has no artifact "
                    f"named {artifact_name!r}"
                )

            declared_artifact = resolved_producer_spec.spec.artifacts.get(artifact_name)
            if declared_artifact is None:
                raise VerificationError(
                    f"producer stage {producer_stage_id!r} did not declare "
                    f"artifact {artifact_name!r}"
                )

            verified_artifact = verify_snapshot_artifact(
                producer_stage_reference,
                artifact,
                data_role=declared_artifact.data_role,
                fetcher=fetcher,
            )
            stage_inputs[input_name] = VerifiedInput(
                path=declared_artifact.path,
                data_role=declared_artifact.data_role,
                artifact=verified_artifact.artifact,
                files=verified_artifact.files,
                references=verified_artifact.references,
            )

        if stage_inputs:
            verified_inputs[consumer_stage_id] = stage_inputs

    return verified_inputs


def verify_benchmark_result(
    result: BenchmarkResult,
    *,
    policy: VerificationPolicy,
    fetcher: StorageFetcher | None = None,
) -> VerifiedBenchmarkResult:
    """Verify benchmark parity and metric criteria across two executions."""
    benchmark_raw = read_resolved_file(result.benchmark, fetcher=fetcher)
    try:
        benchmark = BenchmarkSpec.model_validate(parse_yaml_bytes(benchmark_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid BenchmarkSpec"
        ) from exc

    run_raw = read_resolved_file(result.run, fetcher=fetcher)
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(run_raw))
    except (yaml.YAMLError, ValueError) as exc:
        raise VerificationError(
            "benchmark result does not reference a valid ResolvedRun"
        ) from exc

    verified_run = verify_run_result(resolved_run, policy=policy, fetcher=fetcher)

    if result.completed_at < resolved_run.completed_at:
        raise VerificationError(
            "benchmark result cannot precede the selected run completion"
        )

    expected_run_location = f"{run_root(verified_run.plan.run)}/resolved.yaml"
    if result.run.stored_at.path != expected_run_location:
        raise VerificationError(
            "benchmark result run reference is outside the canonical run path"
        )

    expected_benchmark_location = GitFileRef(
        repository=verified_run.plan.run.source.repository,
        commit=verified_run.plan.run.source.commit,
        path=f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    if result.benchmark.stored_at != expected_benchmark_location:
        raise VerificationError(
            "benchmark result reference does not match the run source snapshot"
        )

    if verified_run.plan.benchmark != benchmark:
        raise VerificationError(
            "benchmark result and run plan select different benchmark specs"
        )

    confirmation = read_attempt_reference(
        result.confirmation,
        verified_run.plan.run,
        fetcher=fetcher,
    )
    if confirmation.status != "succeeded":
        raise VerificationError("benchmark confirmation attempt must succeed")
    if confirmation.purpose != "benchmark_confirmation":
        raise VerificationError("benchmark confirmation has the wrong purpose")
    if result.completed_at < confirmation.completed_at:
        raise VerificationError(
            "benchmark result cannot precede confirmation completion"
        )

    selected_attempt = next(
        attempt
        for attempt in verified_run.attempts
        if attempt.attempt_id == resolved_run.successful_attempt_id
    )
    original_attempt_ids = {attempt.attempt_id for attempt in verified_run.attempts}
    if confirmation.attempt_id in original_attempt_ids:
        raise VerificationError("benchmark confirmation must use a new attempt ID")
    if confirmation.attempt_id <= max(original_attempt_ids):
        raise VerificationError(
            "benchmark confirmation attempt ID must follow the candidate history"
        )

    original_snapshots = {
        snapshot_identity(stage.snapshot)
        for attempt in verified_run.attempts
        for stage in attempt.resolved_stages
    }
    confirmation_snapshots = {
        snapshot_identity(stage.snapshot) for stage in confirmation.resolved_stages
    }
    if original_snapshots & confirmation_snapshots:
        raise VerificationError(
            "benchmark confirmation must use new stage-result snapshots"
        )

    original_attempt_file_snapshots = {
        identity
        for attempt in verified_run.attempts
        for reference in (
            attempt.journal,
            *attempt.measurement_files,
            *attempt.metric_verification_files,
            *attempt.log_files,
        )
        if (identity := artifact_revision_identity(reference.stored_at)) is not None
    }
    confirmation_attempt_file_snapshots = {
        identity
        for reference in (
            confirmation.journal,
            *confirmation.measurement_files,
            *confirmation.metric_verification_files,
            *confirmation.log_files,
        )
        if (identity := artifact_revision_identity(reference.stored_at)) is not None
    }
    if original_attempt_file_snapshots & confirmation_attempt_file_snapshots:
        raise VerificationError(
            "benchmark confirmation must use a new measurement and log snapshot"
        )
    if confirmation_snapshots & confirmation_attempt_file_snapshots:
        raise VerificationError(
            "benchmark confirmation stage-result and attempt-file snapshots "
            "must be distinct"
        )

    confirmation_stages = verify_attempt_stages(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.stages,
        require_complete=True,
        policy=policy,
        fetcher=fetcher,
    )
    confirmation_stored_inputs = verify_stored_inputs(
        confirmation_stages,
        policy=policy,
        fetcher=fetcher,
    )
    confirmation_future_inputs = verify_attempt_future_inputs(
        confirmation,
        verified_run.plan.run,
        confirmation_stages,
        fetcher=fetcher,
    )
    confirmation_measurements = verify_attempt_files(
        confirmation,
        verified_run.plan.run,
        verified_run.plan.experiment,
        verified_run.plan.stages,
        fetcher=fetcher,
    )
    verify_measurement_stage_times(
        confirmation_stages,
        confirmation_measurements,
        verified_run.plan.experiment,
    )
    verify_recomputed_metrics(
        confirmation,
        verified_run.plan,
        confirmation_stages,
        confirmation_measurements,
        confirmation_stored_inputs,
        confirmation_future_inputs,
        policy=policy,
        fetcher=fetcher,
    )

    estimator_ref = verified_run.plan.run.estimator
    selected_estimator = verified_run.resolved_stages[estimator_ref.stage_id].artifacts[
        estimator_ref.artifact_name
    ]
    confirmation_estimator = confirmation_stages[estimator_ref.stage_id].artifacts[
        estimator_ref.artifact_name
    ]
    estimator_parity = selected_estimator == confirmation_estimator

    evaluation_stage_ids = [
        stage_id
        for stage_id, stage in verified_run.plan.stages.items()
        if isinstance(stage, EvaluateSpec)
    ]
    if len(evaluation_stage_ids) != 1:
        raise VerificationError("benchmark verification requires one evaluation stage")
    evaluation_stage_id = evaluation_stage_ids[0]
    selected_predictions = verified_run.resolved_stages[evaluation_stage_id].artifacts[
        PREDICTIONS
    ]
    confirmation_predictions = confirmation_stages[evaluation_stage_id].artifacts[
        PREDICTIONS
    ]
    prediction_parity = selected_predictions == confirmation_predictions

    expected_artifacts = {
        (estimator_ref.stage_id, estimator_ref.artifact_name): (
            estimator_ref,
            next(
                stage
                for stage in selected_attempt.resolved_stages
                if stage.stage_id == estimator_ref.stage_id
            ),
            next(
                stage
                for stage in confirmation.resolved_stages
                if stage.stage_id == estimator_ref.stage_id
            ),
            selected_estimator,
            confirmation_estimator,
        ),
        (evaluation_stage_id, PREDICTIONS): (
            StageArtifactRef(
                stage_id=evaluation_stage_id,
                artifact_name=PREDICTIONS,
            ),
            next(
                stage
                for stage in selected_attempt.resolved_stages
                if stage.stage_id == evaluation_stage_id
            ),
            next(
                stage
                for stage in confirmation.resolved_stages
                if stage.stage_id == evaluation_stage_id
            ),
            selected_predictions,
            confirmation_predictions,
        ),
    }
    received_artifacts = {
        (receipt.artifact.stage_id, receipt.artifact.artifact_name): receipt
        for receipt in result.artifacts
    }
    if set(received_artifacts) != set(expected_artifacts):
        raise VerificationError(
            "benchmark.artifacts: result must compare parameters and predictions"
        )
    for artifact_key, expected in expected_artifacts.items():
        (
            artifact_ref,
            candidate_stage,
            confirmation_stage,
            candidate,
            confirmed,
        ) = expected
        receipt = received_artifacts[artifact_key]
        expected_candidate_digest = document_digest(candidate)
        expected_confirmation_digest = document_digest(confirmed)
        if (
            receipt.candidate_stage != candidate_stage
            or receipt.confirmation_stage != confirmation_stage
            or receipt.candidate_digest != expected_candidate_digest
            or receipt.confirmation_digest != expected_confirmation_digest
            or receipt.passed
            != (expected_candidate_digest == expected_confirmation_digest)
        ):
            raise VerificationError(
                "benchmark.artifacts: artifact comparison receipt differs"
            )

    def metric_receipts(
        attempt: RunAttempt,
    ) -> dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]]:
        """Load the evaluation metric receipts owned by one attempt."""
        receipts: dict[str, tuple[ResolvedFileRef, MetricVerificationReceipt]] = {}
        for reference in attempt.metric_verification_files:
            raw = read_resolved_file(reference, fetcher=fetcher)
            try:
                receipt = MetricVerificationReceipt.model_validate(
                    parse_yaml_bytes(raw)
                )
            except (yaml.YAMLError, ValueError) as exc:
                raise VerificationError(
                    "benchmark.metrics: metric verification receipt is invalid"
                ) from exc
            if receipt.stage_id != evaluation_stage_id:
                continue
            receipts[receipt.metric_id] = (reference, receipt)
        return receipts

    candidate_metric_receipts = metric_receipts(selected_attempt)
    confirmation_metric_receipts = metric_receipts(confirmation)
    criteria = {criterion.metric_id: criterion for criterion in benchmark.metrics}
    received_metrics = {receipt.metric_id: receipt for receipt in result.metrics}
    if set(received_metrics) != set(criteria):
        raise VerificationError(
            "benchmark.metrics: result metric IDs differ from the benchmark"
        )
    criteria_pass = True
    for metric_id, criterion in criteria.items():
        if (
            metric_id not in candidate_metric_receipts
            or metric_id not in confirmation_metric_receipts
        ):
            raise VerificationError(
                f"benchmark.metrics: metric {metric_id!r} lacks verification evidence"
            )
        candidate_ref, candidate_receipt = candidate_metric_receipts[metric_id]
        confirmation_ref, confirmation_receipt = confirmation_metric_receipts[metric_id]
        values = (
            candidate_receipt.recomputation.value,
            confirmation_receipt.recomputation.value,
        )
        criterion_passed = (
            all(value >= criterion.threshold for value in values)
            if criterion.comparison == "ge"
            else all(value <= criterion.threshold for value in values)
        )
        receipt = received_metrics[metric_id]
        if (
            not candidate_receipt.passed
            or not confirmation_receipt.passed
            or receipt.candidate_verification != candidate_ref
            or receipt.confirmation_verification != confirmation_ref
            or receipt.comparison != criterion.comparison
            or receipt.threshold != criterion.threshold
            or receipt.passed != criterion_passed
        ):
            raise VerificationError(
                "benchmark.metrics: metric criterion receipt differs"
            )
        criteria_pass &= criterion_passed

    passed = estimator_parity and prediction_parity and criteria_pass
    expected_status = "passed" if passed else "failed"
    if result.status != expected_status:
        raise VerificationError(
            "benchmark result status does not match parity and metric checks"
        )

    return VerifiedBenchmarkResult(
        result=result,
        run=verified_run,
        confirmation=confirmation,
        confirmation_stages=confirmation_stages,
        confirmation_measurements=confirmation_measurements,
    )
```

<!-- pair-block-definition: P0-MOD-03 -->
```toml pair-block
id = "P0-MOD-03"
requirements = ["MOD-01"]
targets = ["src/viper/api.py:validate_stage", "src/viper/api.py:HANDLER_REGISTRY"]
tests = ["tests/test_public_api.py:test_api_operations_are_locally_defined", "tests/test_api.py:test_validate_stage_returns_typed_success"]
gate = "conda run -n mantra python -m pytest tests/test_public_api.py tests/test_api.py -k 'api_operations_are_locally_defined or validate_stage_returns_typed_success' -q"
depends_on = ["P0-MOD-02"]
```

Move `_load_model`, `_document_error`, `_policy`, and all nineteen public
operation bodies from `_api/handlers.py` into `api.py`. Delete the late
`_handlers` import and every pass-through wrapper. Preserve this exact registry
order, then delete `_api/handlers.py` and the empty `_api` package.

```python pair-edit
import yaml
from pydantic import TypeAdapter

from .authoring import freeze_run_plan, load_run_plan_draft
from .execution._benchmark import benchmark as execute_benchmark_run
from .execution._run import run as execute_run
from .execution._stage import StageExecutionError, execute_stage_process
from .execution.errors import BenchmarkExecutionError, RunError
from .inspection import InspectionError
from .inspection import attempt_status as inspect_attempt_status
from .inspection import compare_runs as compare_verified_runs
from .inspection import lineage as build_lineage
from .inspection import plan_diff as compare_frozen_plans
from .preflight import preflight_plan
from .project import InitError, RootError, init, resolve_root
from .serialization import load_resolved_stage
from .storage import LocalArtifactStore
from .verification import (
    verify_benchmark_result,
    verify_promoted_artifact,
    verify_run_result,
)
from .verification.models import (
    StorageFetcher,
    VerificationError,
    VerificationPolicy,
)


def _load_model(path: Path, model_type: type[BaseModel]) -> BaseModel:
    """Load one local YAML document through its concrete Pydantic model."""
    return model_type.model_validate(parse_yaml_bytes(path.read_bytes()))


def _document_error(
    operation: OperationName,
    path: Path,
    exc: Exception,
) -> ViperError:
    """Translate a local document failure into the stable API model."""
    if isinstance(exc, FileNotFoundError):
        code: ErrorCode = "not_found"
        message = "document path does not exist"
    elif isinstance(exc, OSError):
        code = "io_failed"
        message = "document could not be read"
    else:
        code = "invalid_document"
        message = "document failed schema validation"
    return ViperError(
        ViperFailure(
            operation=operation,
            origin="application",
            code=code,
            message=message,
            details={"path": path.as_posix()},
        )
    )


def _project_root(root: Path | None, operation: OperationName) -> Path:
    """Resolve one operation root or raise its stable API failure."""
    try:
        return resolve_root(root)
    except RootError as error:
        raise ViperError(
            ViperFailure(
                operation=operation,
                origin="application",
                code="invalid_document",
                message="project root is invalid",
                details={
                    "root": None if root is None else root.as_posix(),
                },
            )
        ) from error


def _local_fetcher(
    root: Path | None,
    operation: OperationName,
    fetcher: StorageFetcher | None,
) -> StorageFetcher:
    """Use an injected fetcher or bind the selected project's local store."""
    if fetcher is not None:
        return fetcher
    project_root = _project_root(root, operation)
    return LocalArtifactStore(project_root).fetch


def validate_stage(request: ValidateStageRequest) -> ValidateStageSuccess:
    """Validate one authored stage document."""
    try:
        stage = load_stage_spec(request.path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("validate_stage", request.path, exc) from exc
    return ValidateStageSuccess(path=request.path, stage_kind=stage.kind)


def validate_resolved_stage(
    request: ValidateResolvedStageRequest,
) -> ValidateResolvedStageSuccess:
    """Validate one resolved stage document."""
    try:
        stage = load_resolved_stage(request.path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("validate_resolved_stage", request.path, exc) from exc
    return ValidateResolvedStageSuccess(path=request.path, stage_kind=stage.kind)


def validate_run_spec(request: ValidateRunSpecRequest) -> ValidateRunSpecSuccess:
    """Validate one RunSpec document and return its ordered stage identities."""
    try:
        run = _load_model(request.path, RunSpec)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("validate_run_spec", request.path, exc) from exc
    assert isinstance(run, RunSpec)
    return ValidateRunSpecSuccess(
        path=request.path,
        run_id=run.run_id,
        stage_ids=tuple(stage.stage_id for stage in run.stages),
    )


def freeze_run(request: FreezeRunRequest) -> FreezeRunSuccess:
    """Freeze one draft into canonical stage and run documents."""
    project_root = _project_root(request.root, "freeze_run")
    try:
        draft = load_run_plan_draft(request.draft)
        frozen = freeze_run_plan(project_root, draft)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("freeze_run", request.draft, exc) from exc
    return FreezeRunSuccess(run_id=frozen.run.run_id, files=frozen.files)


def preflight(request: PreflightRequest) -> PreflightSuccess:
    """Inspect one complete local plan before allocating a run attempt."""
    project_root = _project_root(request.root, "preflight")
    report = preflight_plan(project_root, request.run_spec)
    return PreflightSuccess(
        run_id=report.run_id,
        ready=report.ready,
        checks=report.checks,
    )


def execute_stage(request: ExecuteStageRequest) -> ExecuteStageSuccess:
    """Execute one selected stage and identify its declared outputs."""
    project_root = _project_root(request.root, "execute_stage")
    try:
        run = _load_model(request.run_spec, RunSpec)
        assert isinstance(run, RunSpec)
        reference = next(
            (stage for stage in run.stages if stage.stage_id == request.stage_id),
            None,
        )
        if reference is None:
            raise ValueError("selected stage is absent from the run plan")
        stage = load_stage_spec(project_root / reference.spec)
        result = execute_stage_process(
            project_root,
            run,
            reference,
            stage,
            timeout_seconds=request.timeout_seconds,
        )
    except StageExecutionError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_stage",
                origin="application",
                code="execution_failed",
                message="stage process failed",
                details={"stage_id": request.stage_id},
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("execute_stage", request.run_spec, exc) from exc
    return ExecuteStageSuccess(
        stage_id=request.stage_id,
        command=result.command,
        artifacts=result.artifacts,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_request(request: RunRequest) -> RunSuccess:
    """Execute, publish, and verify one complete run on the active host."""
    project_root = _project_root(request.root, "run")
    try:
        result = execute_run(
            project_root,
            request.run_spec,
            timeout_seconds=request.timeout_seconds,
        )
    except (RunError, StageExecutionError) as exc:
        raise ViperError(
            ViperFailure(
                operation="run",
                origin="application",
                code="execution_failed",
                message="run failed",
            )
        ) from exc
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="run",
                origin="application",
                code="verification_failed",
                message="run verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("run", request.run_spec, exc) from exc
    run = RunSpec.model_validate(parse_yaml_bytes(request.run_spec.read_bytes()))
    attempt_id = result.resolved_run.successful_attempt_id
    assert attempt_id is not None
    return RunSuccess(
        run_id=run.run_id,
        attempt_id=attempt_id,
        resolved_attempt=(
            result.resolved_run_path.parent
            / "attempts"
            / str(attempt_id)
            / "resolved.yaml"
        ),
        resolved_run=result.resolved_run_path,
        journal=result.journal_path,
    )


def retry_request(request: RetryRequest) -> RetrySuccess:
    """Append one attempt to a failed frozen run and verify its terminal result."""
    project_root = _project_root(request.root, "retry")
    try:
        result = execute_run(
            project_root,
            request.run_spec,
            timeout_seconds=request.timeout_seconds,
            retry=True,
        )
    except (RunError, StageExecutionError) as exc:
        raise ViperError(
            ViperFailure(
                operation="retry",
                origin="application",
                code="execution_failed",
                message="retry failed",
            )
        ) from exc
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="retry",
                origin="application",
                code="verification_failed",
                message="retry verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("retry", request.run_spec, exc) from exc
    run_spec = RunSpec.model_validate(parse_yaml_bytes(request.run_spec.read_bytes()))
    attempt_id = result.resolved_run.successful_attempt_id
    assert attempt_id is not None
    return RetrySuccess(
        run_id=run_spec.run_id,
        attempt_id=attempt_id,
        resolved_run=result.resolved_run_path,
        journal=result.journal_path,
    )


def execute_benchmark(
    request: ExecuteBenchmarkRequest,
) -> ExecuteBenchmarkSuccess:
    """Execute and verify one independent benchmark confirmation."""
    project_root = _project_root(request.root, "execute_benchmark")
    try:
        execution = execute_benchmark_run(
            project_root,
            request.resolved_run,
            request.benchmark_spec,
            timeout_seconds=request.timeout_seconds,
        )
    except BenchmarkExecutionError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark execution failed",
            )
        ) from exc
    except (RunError, StageExecutionError) as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="execution_failed",
                message="benchmark confirmation failed",
            )
        ) from exc
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="execute_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("execute_benchmark", request.resolved_run, exc) from exc
    return ExecuteBenchmarkSuccess(
        result=execution.result,
        result_path=execution.result_path,
    )


def plan_diff(request: PlanDiffRequest) -> PlanDiffSuccess:
    """Compare two frozen plans, including their referenced stage specs."""
    left_root = _project_root(request.left_root, "plan_diff")
    right_root = _project_root(request.right_root, "plan_diff")
    try:
        result = compare_frozen_plans(
            left_root,
            request.left_run_spec,
            right_root,
            request.right_run_spec,
        )
    except (InspectionError, OSError, ValueError, yaml.YAMLError) as exc:
        raise ViperError(
            ViperFailure(
                operation="plan_diff",
                origin="application",
                code="invalid_document",
                message="frozen plans could not be compared",
                details={
                    "left_run_spec": request.left_run_spec.as_posix(),
                    "right_run_spec": request.right_run_spec.as_posix(),
                },
            )
        ) from exc
    return PlanDiffSuccess(
        left_run_id=result.left_run_id,
        right_run_id=result.right_run_id,
        identical=result.identical,
        changes=result.changes,
    )


def status(request: StatusRequest) -> StatusSuccess:
    """Return the latest durable state recorded by one attempt journal."""
    try:
        result = inspect_attempt_status(request.path)
    except (OSError, ValueError) as exc:
        raise _document_error("status", request.path, exc) from exc
    return StatusSuccess(
        path=result.journal,
        entry_count=result.entry_count,
        state=result.state,
        event=result.event,
        recorded_at=result.recorded_at,
        details=result.details,
        next_states=result.next_states,
        terminal=result.terminal,
    )


def _policy(repositories: frozenset[str]) -> VerificationPolicy:
    """Construct the verifier policy carried by one API request."""
    return VerificationPolicy(trusted_source_repositories=repositories)


def verify_run(
    request: VerifyRunRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyRunSuccess:
    """Verify one terminal run and summarize the connected evidence."""
    fetcher = _local_fetcher(request.root, "verify_run", fetcher)
    try:
        resolved = _load_model(request.path, ResolvedRun)
        assert isinstance(resolved, ResolvedRun)
        verified = verify_run_result(
            resolved,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="verify_run",
                origin="application",
                code="verification_failed",
                message="run verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("verify_run", request.path, exc) from exc
    return VerifyRunSuccess(
        run_id=verified.plan.run.run_id,
        run_status=resolved.status,
        successful_attempt_id=resolved.successful_attempt_id,
        stage_ids=tuple(verified.resolved_stages),
        measurement_count=len(verified.measurements),
    )


def lineage(
    request: LineageRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> LineageSuccess:
    """Verify one terminal run and return its upstream lineage graph."""
    fetcher = _local_fetcher(request.root, "lineage", fetcher)
    try:
        resolved = _load_model(request.path, ResolvedRun)
        assert isinstance(resolved, ResolvedRun)
        verified = verify_run_result(
            resolved,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="lineage",
                origin="application",
                code="verification_failed",
                message="run verification failed before lineage construction",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("lineage", request.path, exc) from exc
    result = build_lineage(verified)
    return LineageSuccess(
        run_id=result.run_id,
        nodes=result.nodes,
        edges=result.edges,
    )


def compare_runs(
    request: CompareRunsRequest,
    *,
    left_fetcher: StorageFetcher | None = None,
    right_fetcher: StorageFetcher | None = None,
) -> CompareRunsSuccess:
    """Verify two terminal runs and compare all of their connected evidence."""
    left_fetcher = _local_fetcher(
        request.left_root,
        "compare_runs",
        left_fetcher,
    )
    right_fetcher = _local_fetcher(
        request.right_root,
        "compare_runs",
        right_fetcher,
    )
    try:
        left_resolved = _load_model(request.left_path, ResolvedRun)
        right_resolved = _load_model(request.right_path, ResolvedRun)
        assert isinstance(left_resolved, ResolvedRun)
        assert isinstance(right_resolved, ResolvedRun)
        policy = _policy(request.trusted_source_repositories)
        left = verify_run_result(
            left_resolved,
            policy=policy,
            fetcher=left_fetcher,
        )
        right = verify_run_result(
            right_resolved,
            policy=policy,
            fetcher=right_fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="compare_runs",
                origin="application",
                code="verification_failed",
                message="run verification failed before comparison",
                details={
                    "left_path": request.left_path.as_posix(),
                    "right_path": request.right_path.as_posix(),
                },
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ViperError(
            ViperFailure(
                operation="compare_runs",
                origin="application",
                code="invalid_document",
                message="terminal runs could not be loaded",
                details={
                    "left_path": request.left_path.as_posix(),
                    "right_path": request.right_path.as_posix(),
                },
            )
        ) from exc
    result = compare_verified_runs(left, right)
    return CompareRunsSuccess(
        left_run_id=result.left_run_id,
        right_run_id=result.right_run_id,
        identical=result.identical,
        changes=result.changes,
    )


def verify_benchmark(
    request: VerifyBenchmarkRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyBenchmarkSuccess:
    """Verify one benchmark result and summarize its confirmation."""
    fetcher = _local_fetcher(request.root, "verify_benchmark", fetcher)
    try:
        result = _load_model(request.path, BenchmarkResult)
        assert isinstance(result, BenchmarkResult)
        verified = verify_benchmark_result(
            result,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="verify_benchmark",
                origin="application",
                code="verification_failed",
                message="benchmark verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("verify_benchmark", request.path, exc) from exc
    benchmark = verified.run.plan.benchmark
    assert benchmark is not None
    return VerifyBenchmarkSuccess(
        benchmark_id=benchmark.benchmark_id,
        run_id=verified.run.plan.run.run_id,
        benchmark_status=result.status,
        confirmation_attempt_id=verified.confirmation.attempt_id,
    )


def verify_pointer(
    request: VerifyPointerRequest,
    *,
    fetcher: StorageFetcher | None = None,
) -> VerifyPointerSuccess:
    """Verify one promoted artifact and report its physical file count."""
    fetcher = _local_fetcher(request.root, "verify_pointer", fetcher)
    try:
        pointer = _load_model(request.path, ArtifactPointer)
        assert isinstance(pointer, ArtifactPointer)
        artifact = verify_promoted_artifact(
            pointer,
            policy=_policy(request.trusted_source_repositories),
            fetcher=fetcher,
        )
    except VerificationError as exc:
        raise ViperError(
            ViperFailure(
                operation="verify_pointer",
                origin="application",
                code="verification_failed",
                message="artifact verification failed",
            )
        ) from exc
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _document_error("verify_pointer", request.path, exc) from exc
    return VerifyPointerSuccess(file_count=len(artifact.files))


def get_schema(request: SchemaRequest) -> SchemaSuccess:
    """Return JSON Schema for one explicitly registered public type."""
    model = SCHEMA_REGISTRY.get(request.name)
    if model is None:
        raise ViperError(
            ViperFailure(
                operation="get_schema",
                origin="application",
                code="invalid_request",
                message="schema name is not registered",
                details={"name": request.name},
            )
        )
    return SchemaSuccess(
        name=request.name,
        json_schema=TypeAdapter(model).json_schema(),
    )


def get_capabilities(request: CapabilitiesRequest) -> CapabilitiesSuccess:
    """Return installed operations and available execution backends."""
    del request
    return CapabilitiesSuccess(
        protocol_version=1,
        operations=OPERATIONS,
        schemas=tuple(sorted(SCHEMA_REGISTRY)),
        execution_backends=("trusted_local",),
    )


def init_project(request: InitProjectRequest) -> InitProjectSuccess:
    """Generate one runnable five-stage starter project."""
    try:
        files = init(request.path, request.package)
    except InitError as exc:
        occupied = request.path.exists() and (
            not request.path.is_dir() or any(request.path.iterdir())
        )
        code: ErrorCode = "write_conflict" if occupied else "io_failed"
        raise ViperError(
            ViperFailure(
                operation="init_project",
                origin="application",
                code=code,
                message=str(exc),
                details={"path": request.path.as_posix()},
            )
        ) from exc
    return InitProjectSuccess(
        project_root=request.path.resolve(),
        files=files,
    )


HANDLER_REGISTRY: dict[OperationName, Handler] = {
    "validate_stage": validate_stage,
    "validate_resolved_stage": validate_resolved_stage,
    "validate_run_spec": validate_run_spec,
    "freeze_run": freeze_run,
    "preflight": preflight,
    "execute_stage": execute_stage,
    "run": run_request,
    "retry": retry_request,
    "execute_benchmark": execute_benchmark,
    "plan_diff": plan_diff,
    "lineage": lineage,
    "status": status,
    "compare_runs": compare_runs,
    "verify_run": verify_run,
    "verify_benchmark": verify_benchmark,
    "verify_pointer": verify_pointer,
    "get_schema": get_schema,
    "get_capabilities": get_capabilities,
    "init_project": init_project,
}
```

The block contains every moved helper and operation body. The focused ownership
test compares the complete operation set with `OPERATIONS`; an omitted body or
stale private callable fails the block.

<!-- pair-block-definition: P0-MOD-04 -->
```toml pair-block
id = "P0-MOD-04"
requirements = ["MOD-01"]
targets = ["tests/test_public_api.py:test_api_operations_are_locally_defined", "tests/test_public_api.py:test_verification_namespace_separates_operations_and_models", "tests/test_documentation.py:test_module_ownership_pair_blocks_cover_every_moved_definition"]
tests = ["tests/test_public_api.py:test_api_operations_are_locally_defined", "tests/test_public_api.py:test_verification_namespace_separates_operations_and_models", "tests/test_documentation.py:test_module_ownership_pair_blocks_cover_every_moved_definition"]
gate = "conda run -n mantra python -m pytest tests/test_public_api.py tests/test_api.py tests/test_verification.py tests/test_documentation.py -k 'api_operations_are_locally_defined or verification_namespace_separates_operations_and_models or module_ownership_pair_blocks_cover_every_moved_definition or validate_stage_returns_typed_success or verify_complete_run' -q"
depends_on = ["P0-MOD-03"]
```

Replace the wrapper-signature test with these ownership checks. Keep the
existing behavior tests in `test_api.py` and `test_verification.py`.

```python pair-edit
def test_api_operations_are_locally_defined() -> None:
    """Require each registered API operation to be defined by viper.api."""
    assert tuple(api.HANDLER_REGISTRY) == api.OPERATIONS
    for operation in api.HANDLER_REGISTRY.values():
        assert operation.__module__ == "viper.api"
    package = Path(api.__file__).parent
    assert not package.joinpath("_api", "handlers.py").exists()


def test_verification_namespace_separates_operations_and_models() -> None:
    """Keep verification operations and types in their defining modules."""
    operations = (
        verification.verify_run_result,
        verification.verify_promoted_artifact,
        verification.verify_stored_input_selections,
        verification.verify_stored_inputs,
        verification.verify_attempt_future_inputs,
        verification.verify_benchmark_result,
    )
    models = (
        verification_models.VerificationError,
        verification_models.VerificationPolicy,
        verification_models.VerifiedArtifact,
        verification_models.VerifiedBenchmarkResult,
        verification_models.VerifiedInput,
        verification_models.VerifiedRunPlan,
        verification_models.VerifiedRunResult,
        verification_models.VerifiedSnapshotFile,
    )
    assert all(value.__module__ == "viper.verification" for value in operations)
    assert all(
        value.__module__ == "viper.verification.models" for value in models
    )
    package = Path(viper.__file__).parent
    assert not package.joinpath("verification.py").exists()


def test_module_ownership_pair_blocks_cover_every_moved_definition() -> None:
    """Keep each planned move equal to the complete current definition set."""
    reference = MASTER_PHASE_ZERO_PAIR_CODING.read_text(encoding="utf-8")

    def planned_tree(block_id: str) -> ast.Module:
        definition = next(
            match
            for match in _PAIR_BLOCK_DEFINITION.finditer(reference)
            if match.group("id") == block_id
        )
        edit = _PAIR_EDIT.search(definition.group("body"))
        assert edit is not None
        return ast.parse(edit.group("code"))

    verification_source = ast.parse(
        (ROOT / "src/viper/verification.py").read_text(encoding="utf-8")
    )
    verification_target = planned_tree("P0-MOD-02")
    source_operations = {
        node.name: node
        for node in verification_source.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    target_operations = {
        node.name: node
        for node in verification_target.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("verify_")
    }
    assert source_operations.keys() == target_operations.keys()
    assert {
        name: _normalized(node) for name, node in source_operations.items()
    } == {
        name: _normalized(node) for name, node in target_operations.items()
    }

    model_names = {
        "VerificationError",
        "VerificationPolicy",
        "VerifiedSnapshotFile",
        "VerifiedArtifact",
        "VerifiedInput",
        "VerifiedRunPlan",
        "VerifiedRunResult",
        "VerifiedBenchmarkResult",
    }
    model_target = planned_tree("P0-MOD-01")
    source_models = {
        node.name: node
        for node in verification_source.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    target_models = {
        node.name: node
        for node in model_target.body
        if isinstance(node, ast.ClassDef) and node.name in model_names
    }
    assert source_models.keys() == target_models.keys()
    assert {name: _normalized(node) for name, node in source_models.items()} == {
        name: _normalized(node) for name, node in target_models.items()
    }

    api_source = ast.parse(
        (ROOT / "src/viper/_api/handlers.py").read_text(encoding="utf-8")
    )
    api_target = planned_tree("P0-MOD-03")
    source_handlers = {
        node.name: node
        for node in api_source.body
        if isinstance(node, ast.FunctionDef)
    }
    target_handlers = {
        node.name: node
        for node in api_target.body
        if isinstance(node, ast.FunctionDef)
    }
    root_migration = {
        "freeze_run",
        "preflight",
        "execute_stage",
        "run_request",
        "retry_request",
        "execute_benchmark",
        "plan_diff",
        "verify_run",
        "lineage",
        "compare_runs",
        "verify_benchmark",
        "verify_pointer",
    }
    added_helpers = {"_project_root", "_local_fetcher"}
    assert target_handlers.keys() == source_handlers.keys() | added_helpers
    unchanged = source_handlers.keys() - root_migration
    assert {
        name: _normalized(source_handlers[name]) for name in unchanged
    } == {
        name: _normalized(target_handlers[name]) for name in unchanged
    }
```

## 5. Focused proof

These blocks add the tests named by the checklist. Imports belong at the top
of each target test module.

The [contract traceability guide](contract-traceability-pair-coding.md)
owns `P0-PROOF-01` through `P0-PROOF-04`.

<!-- pair-block-definition: P0-PROOF-05 -->
```toml pair-block
id = "P0-PROOF-05"
requirements = ["PDR-01"]
targets = ["tests/test_project_init.py:test_init_establishes_discoverable_root"]
tests = ["tests/test_project_init.py:test_init_establishes_discoverable_root"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py -k establishes_discoverable_root -q"
depends_on = ["P0-PDR-01", "P0-PDR-02"]
```

```python pair-edit
def test_init_establishes_discoverable_root(tmp_path: Path) -> None:
    target = tmp_path / "outside" / "starter"
    init(target, "sample_project")
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    child = target / "src" / "sample_project"
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
```

<!-- pair-block-definition: P0-PROOF-06 -->
```toml pair-block
id = "P0-PROOF-06"
requirements = ["PDR-02"]
targets = ["tests/test_storage.py:test_store_uses_selected_project_root", "tests/test_validation_architecture.py:test_operations_resolve_project_root_once"]
tests = ["tests/test_storage.py:test_store_uses_selected_project_root", "tests/test_validation_architecture.py:test_operations_resolve_project_root_once"]
gate = "conda run -n mantra python -m pytest tests/test_storage.py tests/test_validation_architecture.py -k 'uses_selected_project_root or operations_resolve_project_root_once' -q"
depends_on = ["P0-PDR-03", "P0-PDR-05"]
```

```python pair-edit
def test_operations_resolve_project_root_once() -> None:
    source = ast.parse(
        (ROOT / "src/viper/_api/handlers.py").read_text(encoding="utf-8")
    )
    expected_calls = {
        "freeze_run": 1,
        "preflight": 1,
        "execute_stage": 1,
        "run_request": 1,
        "retry_request": 1,
        "execute_benchmark": 1,
        "plan_diff": 2,
    }
    functions = {
        node.name: node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
    }
    for name, expected in expected_calls.items():
        calls = tuple(
            node
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_project_root"
        )
        assert len(calls) == expected, name


def test_store_uses_selected_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "artifacts" / "model.bin"
    source.parent.mkdir()
    source.write_bytes(b"original")
    store = LocalArtifactStore(root)
    reference = store.resolved_files({"artifacts/model.bin": source.read_bytes()})[0]
    source.write_bytes(b"changed")
    assert store.store_root == root / ".viper" / "store"
    assert store.fetch(reference.stored_at) == b"original"
    with pytest.raises(LocalStoreError):
        LocalArtifactStore(root, "../escape")
```

<!-- pair-block-definition: P0-PROOF-07 -->
```toml pair-block
id = "P0-PROOF-07"
requirements = ["PDR-03"]
targets = ["tests/test_validation_architecture.py:test_project_paths_reject_symlinks"]
tests = ["tests/test_validation_architecture.py:test_project_paths_reject_symlinks"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k project_paths_reject_symlinks -q"
depends_on = ["P0-PDR-06"]
```

```python pair-edit
def test_project_paths_reject_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n", encoding="utf-8")
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "link.csv").symlink_to(outside)
    with pytest.raises(PathError, match="symlink"):
        resolve_path(root, "inputs/link.csv", operation="read")
    with pytest.raises(PathError, match="escapes"):
        resolve_path(root, "../outside.csv", operation="read")
```

<!-- pair-block-definition: P0-PROOF-08 -->
```toml pair-block
id = "P0-PROOF-08"
requirements = ["PDR-04"]
targets = ["tests/test_documentation.py:test_project_root_vocabulary"]
tests = ["tests/test_documentation.py:test_project_root_vocabulary"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k project_root_vocabulary -q"
depends_on = ["P0-PDR-04"]
```

```python pair-edit
def test_project_root_vocabulary() -> None:
    api = ast.parse((ROOT / "src/viper/api.py").read_text(encoding="utf-8"))
    request_names = {
        "FreezeRunRequest",
        "PreflightRequest",
        "ExecuteStageRequest",
        "RunRequest",
        "ExecuteBenchmarkRequest",
        "PlanDiffRequest",
        "VerificationRequest",
        "CompareRunsRequest",
    }
    fields = {
        node.name: {
            member.target.id
            for member in node.body
            if isinstance(member, ast.AnnAssign)
            and isinstance(member.target, ast.Name)
        }
        for node in api.body
        if isinstance(node, ast.ClassDef) and node.name in request_names
    }
    assert all("repository_root" not in names for names in fields.values())
    assert fields["PlanDiffRequest"] >= {"left_root", "right_root"}
    assert fields["CompareRunsRequest"] >= {"left_root", "right_root"}
    assert all(
        "root" in fields[name]
        for name in request_names - {"PlanDiffRequest", "CompareRunsRequest"}
    )

    cli = (ROOT / "src/viper/cli.py").read_text(encoding="utf-8")
    assert "--repository-root" not in cli
    assert "--left-repository-root" not in cli
    assert "--right-repository-root" not in cli
```

## 6. Foundation gate

Run the focused test after each block. Run this gate after every foundation
block has passed:

```bash
conda run -n mantra python -m pytest \
  tests/test_project_init.py \
  tests/test_storage.py \
  tests/test_public_api.py \
  tests/test_api.py \
  tests/test_verification.py \
  tests/test_validation_architecture.py \
  tests/test_inspection.py \
  tests/test_documentation.py -q
```

Close each review cycle only after the focused gate passes, the diff contains
the intended block, and the local and upstream commits are equal.

## 7. Design basis

The local `PairBlock` format is a VIPER design. Its primitives come from
established systems:

- Ferrante, Ottenstein, and Warren model control and data dependencies as
  explicit graph edges in the program dependence graph.
- Horwitz, Reps, and Binkley extend dependency traversal across procedure
  boundaries through the system dependence graph.
- Tarjan's depth-first algorithm computes strongly connected components in
  linear time. VIPER collapses those components before topological ordering.
- Git assigns immutable object IDs from object type and contents, stores file
  contents as blobs, and stores path structure in trees. VIPER inventories one
  selected commit. The working tree remains outside source identity.
- GitHub's stack graphs build file-incremental name-binding graphs and resolve a
  reference by graph search. VIPER extends that file-anchored principle across
  contract, runtime, and verification relationships.
- NASA's software traceability guidance links requirements through
  implementation and verification evidence. `PairBlock` makes that link
  executable at the checklist-task boundary.
- W3C PROV separates entities, activities, and typed provenance relations.
  VIPER retains node roles, relation kinds, and edge evidence.

Primary sources:

1. Ferrante, Ottenstein, and Warren, [The Program Dependence Graph and Its Use
   in Optimization](https://doi.org/10.1145/24039.24041), 1987.
2. Horwitz, Reps, and Binkley, [Interprocedural Slicing Using Dependence
   Graphs](https://doi.org/10.1145/77606.77608), 1990.
3. Tarjan, [Depth-First Search and Linear Graph
   Algorithms](https://doi.org/10.1137/0201010), 1972.
4. Git, [Core data model](https://git-scm.com/docs/gitdatamodel.html) and
   [`git diff-tree`](https://git-scm.com/docs/git-diff-tree.html).
5. Creager and van Antwerpen, [Stack Graphs: Name Resolution at
   Scale](https://arxiv.org/abs/2211.01224), 2022.
6. NASA, [Bidirectional Traceability](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695427/SWE-052%2B-%2BBidirectional%2BTraceability).
7. W3C, [PROV-O](https://www.w3.org/TR/prov-o/).
