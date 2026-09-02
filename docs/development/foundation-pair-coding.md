# Foundation Pair-Coding Guide

This document contains the exact bounded foundation edits scheduled by Master Phase 0 of the
[master execution checklist](master-execution-checklist.md).
The checklist decides order. Each `PairBlock` below supplies the code, target,
focused test, and completion gate for one checkbox.

## 1. PairBlock contract

Each checklist checkbox owns exactly one `PairBlock`. A block may change
several targets when splitting the edit leaves the code unable to compile.
Each block begins with a short **Context** paragraph written in everyday
English. It states why the change is necessary, what the change adds, and which
next operation needs it. Keep the manifest and implementation steps separate.
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

**Context:** Later commands currently choose their working directory
independently. `viper.toml`, `find_root()`, and `resolve_root()` let every
command select the same validated Git project root.

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

**Context:** A generated project needs the root marker and reserved input
directory before later commands can discover or use it. `ROOT_FILES` adds those
paths to every scaffold from one definition.

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
targets = ["src/viper/api.py:FreezeRunRequest", "src/viper/api.py:PreflightRequest", "src/viper/api.py:ExecuteStageRequest", "src/viper/api.py:RunRequest", "src/viper/api.py:ExecuteBenchmarkRequest", "src/viper/api.py:PlanDiffRequest", "src/viper/api.py:VerificationRequest", "src/viper/api.py:CompareRunsRequest", "src/viper/_api/handlers.py:_root", "src/viper/_api/handlers.py:freeze_run", "src/viper/_api/handlers.py:preflight", "src/viper/_api/handlers.py:execute_stage", "src/viper/_api/handlers.py:run_request", "src/viper/_api/handlers.py:retry_request", "src/viper/_api/handlers.py:execute_benchmark", "src/viper/_api/handlers.py:plan_diff"]
tests = ["tests/test_validation_architecture.py:test_operations_resolve_project_root_once"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k operations_resolve_project_root_once -q"
depends_on = ["P0-PDR-01"]
```

**Context:** Public operations currently resolve supplied paths through
different boundaries. Each operation must resolve its supplied `root` once and
pass the resulting `project_root` to every internal consumer.

Replace every public `repository_root` field with `root`. Comparison requests
use `left_root` and `right_root`. `P0-MOD-03` later moves these completed bodies
into `api.py` unchanged.

`src/viper/api.py`

```python pair-edit
class FreezeRunRequest(APIModel):
    """Select one run-plan draft and project root."""

    draft: Path
    root: Path


class PreflightRequest(APIModel):
    """Select one frozen plan for pre-execution inspection."""

    run_spec: Path
    root: Path


class ExecuteStageRequest(APIModel):
    """Select one stage from a frozen local run plan."""

    run_spec: Path
    stage_id: StageId
    root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class RunRequest(APIModel):
    """Select one frozen plan for complete local execution."""

    run_spec: Path
    root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class ExecuteBenchmarkRequest(APIModel):
    """Select one candidate run and frozen benchmark specification."""

    resolved_run: Path
    benchmark_spec: Path
    root: Path
    timeout_seconds: float | None = Field(default=None, gt=0)


class PlanDiffRequest(APIModel):
    """Select two frozen plans and their project roots."""

    left_run_spec: Path
    right_run_spec: Path
    left_root: Path
    right_root: Path


class VerificationRequest(PathRequest):
    """Select evidence, its project root, and trusted source repositories."""

    root: Path
    trusted_source_repositories: frozenset[str] = Field(min_length=1)


class CompareRunsRequest(APIModel):
    """Select two terminal runs and their project roots."""

    left_path: Path
    right_path: Path
    left_root: Path
    right_root: Path
    trusted_source_repositories: frozenset[str] = Field(min_length=1)
```


`src/viper/_api/handlers.py`

```python pair-edit
def _root(root: Path, operation: OperationName) -> Path:
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
                    "root": root.as_posix(),
                },
            )
        ) from error


def freeze_run(request: FreezeRunRequest) -> FreezeRunSuccess:
    """Freeze one draft into canonical stage and run documents."""
    project_root = _root(request.root, "freeze_run")
    try:
        draft = load_run_plan_draft(request.draft)
        frozen = freeze_run_plan(project_root, draft)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise _document_error("freeze_run", request.draft, error) from error
    return FreezeRunSuccess(run_id=frozen.run.run_id, files=frozen.files)


def preflight(request: PreflightRequest) -> PreflightSuccess:
    """Inspect one complete local plan before allocating a run attempt."""
    project_root = _root(request.root, "preflight")
    report = preflight_plan(project_root, request.run_spec)
    return PreflightSuccess(
        run_id=report.run_id,
        ready=report.ready,
        checks=report.checks,
    )


def execute_stage(request: ExecuteStageRequest) -> ExecuteStageSuccess:
    """Execute one selected stage and identify its declared outputs."""
    project_root = _root(request.root, "execute_stage")
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
    project_root = _root(request.root, "run")
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
    project_root = _root(request.root, "retry")
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
    project_root = _root(request.root, "execute_benchmark")
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
    left_root = _root(request.left_root, "plan_diff")
    right_root = _root(request.right_root, "plan_diff")
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

Verification requests require a root. Verification functions may still receive
an injected `StorageFetcher` for tests and custom storage access. `P0-PDR-05`
binds their default local fetchers to `request.root`, `request.left_root`, or
`request.right_root` after the store accepts canonical project roots.

<!-- pair-block-definition: P0-PDR-04 -->
```toml pair-block
id = "P0-PDR-04"
requirements = ["PDR-04"]
targets = ["src/viper/cli.py:add_root", "src/viper/cli.py:build_parser", "src/viper/api.py:_stage_parser", "src/viper/api.py:run", "src/viper/api.py:retry"]
tests = ["tests/test_generated_project_acceptance.py:test_generated_project_executes_five_stage_benchmark"]
gate = "conda run -n mantra python -m pytest tests/test_generated_project_acceptance.py -k generated_project_executes_five_stage_benchmark -q"
depends_on = ["P0-PDR-03"]
```

**Context:** The CLI and Python API have used different names for the same
project-root input. `add_root()` gives ordinary and comparison commands the
same `root`, `left_root`, and `right_root` vocabulary as their request models.

`src/viper/cli.py`

```python pair-edit
RootArg = Literal["root", "left_root", "right_root"]


def add_root(parser: argparse.ArgumentParser, name: RootArg = "root") -> None:
    """Add one project-root option with current-directory discovery."""
    option = f"--{name.replace('_', '-')}"
    parser.add_argument(
        option,
        dest=name,
        type=Path,
        default=Path.cwd(),
        help="VIPER project root; defaults to discovery from the current directory",
    )


def build_parser() -> ArgumentParser:
    """Build the VIPER command parser and its API subcommands."""
    parser = ViperArgumentParser(prog="viper")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit one machine-readable result document",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("validate-stage", "validate one authored stage specification"),
        ("validate-resolved-stage", "validate one resolved stage specification"),
        ("validate-run", "validate one frozen run specification"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("path", type=Path)

    freeze = commands.add_parser(
        "freeze-run",
        help="write canonical stage specs and a hash-bound RunSpec",
    )
    freeze.add_argument("draft", type=Path)
    add_root(freeze)

    preflight = commands.add_parser(
        "preflight",
        help="inspect every applicable check before local execution",
    )
    preflight.add_argument("run_spec", type=Path)
    add_root(preflight)

    execute = commands.add_parser(
        "execute-stage",
        help="run one stage from a frozen local run plan",
    )
    execute.add_argument("run_spec", type=Path)
    execute.add_argument("stage_id")
    add_root(execute)
    execute.add_argument("--timeout-seconds", type=float)

    run_command = commands.add_parser(
        "run",
        help="execute and verify one complete run on this host",
    )
    run_command.add_argument("run_spec", type=Path)
    add_root(run_command)
    run_command.add_argument("--timeout-seconds", type=float)

    retry_command = commands.add_parser(
        "retry",
        help="append one attempt to a failed frozen run",
    )
    retry_command.add_argument("run_spec", type=Path)
    add_root(retry_command)
    retry_command.add_argument("--timeout-seconds", type=float)

    benchmark_command = commands.add_parser(
        "execute-benchmark",
        help="execute and verify one independent benchmark confirmation",
    )
    benchmark_command.add_argument("resolved_run", type=Path)
    benchmark_command.add_argument("benchmark_spec", type=Path)
    add_root(benchmark_command)
    benchmark_command.add_argument("--timeout-seconds", type=float)

    plan_diff = commands.add_parser(
        "plan-diff",
        help="compare two complete frozen run plans",
    )
    plan_diff.add_argument("left_run_spec", type=Path)
    plan_diff.add_argument("right_run_spec", type=Path)
    add_root(plan_diff, "left_root")
    add_root(plan_diff, "right_root")

    status = commands.add_parser(
        "status",
        help="read the latest durable state of one local attempt",
    )
    status.add_argument("path", type=Path)

    compare_runs = commands.add_parser(
        "compare-runs",
        help="compare all connected evidence from two verified runs",
    )
    compare_runs.add_argument("left_path", type=Path)
    compare_runs.add_argument("right_path", type=Path)
    add_root(compare_runs, "left_root")
    add_root(compare_runs, "right_root")
    compare_runs.add_argument(
        "--trust-source",
        action="append",
        required=True,
        help="source repository URL approved to supply executable loaders",
    )

    for name, help_text in (
        ("verify-run", "verify one terminal resolved run"),
        ("verify-benchmark", "verify one benchmark result"),
        ("verify-pointer", "verify one promoted artifact pointer"),
        ("lineage", "return the verified upstream lineage of one run"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("path", type=Path)
        add_root(command)
        command.add_argument(
            "--trust-source",
            action="append",
            required=True,
            help="source repository URL approved to supply executable loaders",
        )

    schema = commands.add_parser("schema", help="return one public JSON Schema")
    schema.add_argument("name")
    commands.add_parser("capabilities", help="list installed VIPER capabilities")
    initialize = commands.add_parser(
        "init",
        help="create a five-stage starter project",
    )
    initialize.add_argument("path", type=Path)
    initialize.add_argument("--package", required=True)
    return parser
```


`src/viper/api.py`

```python pair-edit
def _stage_parser() -> argparse.ArgumentParser:
    """Build the parser used by one project stage entrypoint."""
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--run", required=True, dest="run_spec", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
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
    root: Path,
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

**Context:** `resolve_root()` validates only the project directory. A relative
file path can traverse outside the project or pass through a symlink.
`resolve_path()` blocks those paths before storage and other local operations
use them.

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

**Context:** A valid project root leaves the local store path unchecked.
`LocalArtifactStore` uses `resolve_path()` before it writes or retrieves
immutable files.

`src/viper/storage.py`

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
```


`src/viper/_api/handlers.py`

```python pair-edit
def _local_fetcher(
    project_root: Path,
    fetcher: StorageFetcher | None,
) -> StorageFetcher:
    """Use an injected fetcher or bind the selected project's local store."""
    if fetcher is not None:
        return fetcher
    return LocalArtifactStore(project_root).fetch


# verify_run()
project_root = _root(request.root, "verify_run")
fetcher = _local_fetcher(project_root, fetcher)

# lineage()
project_root = _root(request.root, "lineage")
fetcher = _local_fetcher(project_root, fetcher)

# verify_benchmark()
project_root = _root(request.root, "verify_benchmark")
fetcher = _local_fetcher(project_root, fetcher)

# verify_pointer()
project_root = _root(request.root, "verify_pointer")
fetcher = _local_fetcher(project_root, fetcher)

# compare_runs()
left_root = _root(request.left_root, "compare_runs")
right_root = _root(request.right_root, "compare_runs")
left_fetcher = _local_fetcher(
    left_root,
    left_fetcher,
)
right_fetcher = _local_fetcher(
    right_root,
    right_fetcher,
)
```

Rename internal `repository_root` attributes to `project_root`. Preserve the
persisted `LocalFileRef.store` value `.viper/store`. Import
`LocalArtifactStore` in `_api/handlers.py`, add `_local_fetcher()` beside
`_root()`, and place each shown binding before its verifier call. Pass those
bound values to the existing verifier calls. An explicitly injected fetcher
replaces immutable-file retrieval after the operation validates its root.

## 3. Contract traceability

The dedicated [Contract Traceability Pair-Coding
guide](contract-traceability-pair-coding.md) owns `P0-CRT-01` through
`P0-CRT-05` and `P0-PROOF-01` through `P0-PROOF-04`. It contains the
complete proposed edits, focused tests, dependencies, stop conditions, and
phase gate. This combined reference links to that single source.

## 4. Public module ownership

The dedicated [Public Module Ownership Pair-Coding
Guide](module-ownership-pair-coding.md) owns `P0-MOD-01` through
`P0-MOD-04`. It contains the complete file-separated edits, focused tests,
dependencies, stop conditions, and handoff to the System Impact Compiler.

## 5. Focused proof

These blocks add the tests named by the checklist. Imports belong at the top
of each target test module.

The [contract traceability guide](contract-traceability-pair-coding.md)
owns `P0-PROOF-01` through `P0-PROOF-04`.

<!-- pair-block-definition: P0-PROOF-05 -->
```toml pair-block
id = "P0-PROOF-05"
requirements = ["PDR-01", "PDR-04"]
targets = ["tests/test_project_init.py:test_init_establishes_discoverable_root"]
tests = ["tests/test_project_init.py:test_init_establishes_discoverable_root", "tests/test_generated_project_acceptance.py:test_generated_project_executes_five_stage_benchmark"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py tests/test_generated_project_acceptance.py -k 'establishes_discoverable_root or generated_project_executes_five_stage_benchmark' -q"
depends_on = ["P0-PDR-01", "P0-PDR-02", "P0-PDR-04"]
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
        "verify_run": 1,
        "lineage": 1,
        "compare_runs": 2,
        "verify_benchmark": 1,
        "verify_pointer": 1,
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
            and node.func.id == "_root"
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
