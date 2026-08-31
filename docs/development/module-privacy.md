# Module privacy protocol

**Status:** Implemented

The later [automatic input-resolution contract](automatic-input-resolution.md#target-artifact-and-http-drafts)
reserves `viper.http` for the public HTTP interface. Its implementation phase
keeps every supported HTTP name in that defining module. The package root
forwards no names.

## Required claim

Every VIPER import path must show one clear boundary between supported public
code and private implementation code.

For example, `viper.execution.run` is public. Its implementation may call
`viper.execution._attempt.execute_attempt`, where `_attempt` marks the private
boundary. A second underscore on `execute_attempt` repeats the same signal.

## Original gap

**Original state:** VIPER used three conflicting patterns:

```text
viper._parameter._validation
viper.execution._attempt._execute_attempt
viper._verification.attempt.verify_attempt_stages
```

The first path marks both the package and module as private. The second marks
both the module and a function shared with another module. The third marks the
private package once and gives its shared function a normal name.

The original repository permitted all three patterns. The implemented
source-tree checks now enforce one convention.

## Contract

VIPER uses a leading underscore at the first path component that becomes
private.

```text
viper.execution              public package
viper.execution._stage       private module inside a public package
viper._verification          private package
viper._verification.attempt  module inside a private package
```

A function called only within its defining module keeps a leading underscore.
A function imported by another module uses a normal function name because its
package or module path already marks the private boundary.

This protocol defines five static checks:

| Check | Rule |
| --- | --- |
| `package.private` | An underscored package contains normally named modules, except `__init__.py`. |
| `package.import` | Reject an import of a single-underscore symbol from another module. |
| `package.execution` | Results and errors returned or raised by public execution functions have public import paths. |
| `package.export` | Every name in a public module's `__all__` is defined in that module. |
| `package.root` | `src/viper/__init__.py` contains only the package docstring. |

The source tree also rejects `from module import name as name`. A public module
lists only local definitions in `__all__`. Every caller imports a name from the
module that defines it. Ruff rejects every redundant self-alias through
`PLC0414`.

These checks govern Python source structure. Runtime execution and the
serialized provenance protocol retain their current behavior.

## Execution

Python resolves the renamed modules and symbols when it imports VIPER. The
executor then follows the same function bodies and passes the same values.
All changes finish during Python import, before experiment execution begins.

## Persisted evidence

The committed source tree is the complete evidence for this contract. Run
plans, attempt files, artifacts, measurements, and `resolved.yaml` remain
byte-for-byte outside its scope.

## Verification

`tests/test_validation_architecture.py` inspects Python files beneath
`src/viper`. The test applies `package.private` to file paths and
`package.import` to `from ... import ...` statements.

`tests/test_public_api.py` applies `package.execution` by
importing result types from `viper.execution.results` and errors from
`viper.execution.errors`. The same test parses every public module and rejects
an exported name that lacks a local definition. `package.root` parses
`src/viper/__init__.py` and requires its package docstring to be the only
statement.

The source tree is the inspected value. The tests are the verifier. The Git
commit records the checked source, while runtime receipts continue to describe
experiment execution.

## Fixed comparisons

### Parameter validation

The input is one frozen training stage with a project-defined parameter class.
The expected result is the same validated parameter object and the same
validation errors.

**Current:** [`preflight_plan()`](../../src/viper/preflight.py) imports
`validate_stage_parameters()` through this path:

```text
viper._parameter._validation.validate_stage_parameters
```

Both `_parameter` and `_validation` mark the same implementation as private.

**Proposed:** Rename `_validation.py` to `validation.py`:

```text
viper._parameter.validation.validate_stage_parameters
```

The function body and every accepted or rejected parameter value remain the
same.

### Run execution

The input is one call to:

```python
from viper import execution

result = execution.run(repository_root, run_spec_path)
```

The expected result is the same `RunResult`, artifact files, attempt file,
journal, and terminal `resolved.yaml`.

**Current:** The public function reaches the attempt coordinator through an
underscored module and an underscored function:

```text
execution.run()
-> execution._run.run()
-> execution._attempt._execute_attempt()
```

**Proposed:** Keep `_attempt.py` private and rename the function it shares with
`_run.py`:

```text
execution.run()
-> execution._run.run()
-> execution._attempt.execute_attempt()
```

The executor performs the same operations. The rename only tells a maintainer
that `execute_attempt()` is shared inside the private execution implementation.

### Execution results

The input is the `RunResult` returned by `execution.run()`.

**Original state:** `RunResult` was defined in `execution/_results.py`, even
though the module docstring called it public. `BenchmarkExecutionResult` was
defined in `execution/_benchmark.py`, which was also private.

**Implemented:** [`execution/results.py`](../../src/viper/execution/results.py)
now owns `RunResult` and `BenchmarkExecutionResult`. The implementation renamed
`_results.py` to `results.py`, moved `BenchmarkExecutionResult` into that
module:

```python
from viper.execution.results import BenchmarkExecutionResult, RunResult
```

`RunError` and `BenchmarkExecutionError` live in
[`viper.execution.errors`](../../src/viper/execution/errors.py). Callers inspect
returned values and catch execution errors through their defining modules.

## Exact changes

### Package and module paths

| Original path | Implemented path | Required updates |
| --- | --- | --- |
| `viper/_parameter/_validation.py` | `viper/_parameter/validation.py` | Update imports in authoring, HTTP, preflight, execution, verification, workers, and parameter tests. |
| `viper/execution/_results.py` | `viper/execution/results.py` | Update callers to import `RunResult` and `BenchmarkExecutionResult` from the defining module. |
| `viper/execution/_errors.py` | `viper/execution/errors.py` | Update callers to import `RunError` and `BenchmarkExecutionError` from the defining module. |

`BenchmarkExecutionResult` moved from `execution/_benchmark.py` to
`execution/results.py`. `BenchmarkExecutionError` moved from
`execution/_benchmark.py` to `execution/errors.py`.

### Shared execution functions

These functions cross an internal module boundary. Their defining modules stay
private.

| Defining module | Current | Proposed | Consumers |
| --- | --- | --- | --- |
| `_attempt.py` | `_execute_attempt` | `execute_attempt` | `_run.py` |
| `_materialization.py` | `_resolve_inputs` | `resolve_inputs` | `_attempt.py` |
| `_materialization.py` | `_retrieve_download_inputs` | `retrieve_download_inputs` | `_attempt.py` |
| `_metric.py` | `_run_after_stage_metrics` | `run_after_stage_metrics` | `_attempt.py` |
| `_publication.py` | `_publish_attempt_files` | `publish_attempt_files` | `_attempt.py`, `_recovery.py` |
| `_publication.py` | `_publish_invocation_receipt` | `publish_invocation_receipt` | `_attempt.py` |
| `_publication.py` | `_replace_synchronized` | `replace_synchronized` | `_attempt.py` |
| `_publication.py` | `_write_attempt_document` | `write_attempt_document` | `_attempt.py`, `_recovery.py` |
| `_publication.py` | `_write_synchronized` | `write_synchronized` | `_attempt.py`, `_metric.py` |
| `_recovery.py` | `_reconcile_abandoned_attempts` | `reconcile_abandoned_attempts` | `_attempt.py` |
| `_resolution.py` | `_resolved_environment` | `resolve_environment` | `_attempt.py` |
| `_resolution.py` | `_resolved_stage` | `resolve_stage` | `_attempt.py` |
| `_source.py` | `_git` | `run_git` | `_attempt.py` |
| `_source.py` | `_resolved_git_file` | `resolve_git_file` | `_attempt.py`, `_resolution.py` |

Functions that stay inside one module retain their leading underscore. For
example, `_write_materialized_file()` remains local to `_materialization.py`.

### Shared verification functions

[`verification.py`](../../src/viper/verification.py) and the private attempt
verifier import two functions from `_verification/storage.py`.

| Current | Proposed |
| --- | --- |
| `_artifact_revision_identity` | `artifact_revision_identity` |
| `_snapshot_identity` | `snapshot_identity` |

The functions return the same values and enforce the same comparisons.

### Public API operations

The initial privacy refactor gave shared application handlers normal names and
left their bodies in the private `_api` package. The approved
[public module ownership contract](module-ownership.md) completes that move:
`viper.api` defines each public operation body and registers that same local
function. The pass-through wrappers and `_api/handlers.py` are retired.

Existing request models, result models, operation names, signatures, and
returned values remain unchanged.

### Shared test support

`test_generated_project_acceptance.py` currently imports `_git` and
`REPOSITORY` from `test_run_execution.py`. Move the shared Git operation and
repository value into `tests/git_repository.py`:

```python
from tests.git_repository import REPOSITORY, run_git
```

Test-local `_git()` functions may remain local. The refactor only moves the
helper already shared between test modules.

### Enforced convention

Add this rule to the repository instructions:

> A leading underscore marks the first private package or module boundary.
> Functions imported by another module use normal names. Functions confined to
> one module use a leading underscore.

Extend the existing validation-architecture test so it rejects:

1. an underscored Python file inside an underscored package, except
   `__init__.py`; and
2. a cross-module import whose imported symbol begins with one underscore.

The test scans production code beneath `src/viper`. Tests may import a private
module when they directly test that module.

## Propagation and impact

| Surface | Current | Proposed | Effect |
| --- | --- | --- | --- |
| Runtime behavior | Internal callers use underscored shared functions. | Internal callers use normal names within private modules. | Preserved. Function bodies and call order stay unchanged. |
| Parameter validation | `_parameter/_validation.py` owns validation. | `_parameter/validation.py` owns validation. | Preserved. Only the internal import path changes. |
| Public Python API | Execution returned types defined in private modules. | `viper.execution.results` owns result types; `viper.execution.errors` owns error types; `viper.execution` owns only operations. | Strengthened. Every public value has one defining module. |
| Persisted files | Existing schema classes produce YAML and JSON. | The same classes produce the same fields and bytes. | Preserved. Schema versions stay unchanged. |
| Verification | Verification functions perform the existing comparisons. | The same functions receive normal internal names. | Preserved. The same checks remain active. |
| CLI | CLI operations call the application API. | The handler imports change internally. | Preserved. Commands, arguments, output, and exit status stay unchanged. |
| Packaging | Private result modules ship inside the wheel. | Public result and error modules ship inside the wheel. | Changed Python import paths; wheel contents gain supported public modules. |
| Tests | One acceptance test imports a helper from another test module. | Shared Git support has its own test module. | Strengthened test ownership. |

## Invariants

**Preserved:** Every run uses the same plan, stage order, process controls,
artifact publication, attempt closure, and verification rules. Existing focused
execution tests must return equal result models before and after the refactor.

**Preserved:** Serialized field names, discriminators, schema versions, file
paths, SHA-256 values, and byte counts remain unchanged.

**Changed:** Python code that imports private paths must use the new owner. VIPER
is an alpha package, so release notes must list these import changes.

**Introduced:** `viper.execution.results` owns execution results,
`viper.execution.errors` owns execution errors, and `viper.execution` owns the
`run()`, `retry()`, and `benchmark()` operations.

## Acceptance cases

The success case contains one private execution module with a shared function:

```python
from ._attempt import execute_attempt
```

`package.import` accepts the import because `_attempt.py` already marks
the private boundary.

The targeted rejection contains a redundant function marker:

```python
from ._attempt import _execute_attempt
```

`package.import` rejects `_execute_attempt` because another module
imports it. A separate rejection creates `_parameter/_validation.py` and
expects `package.private` to reject the doubly marked path.

A package-root rejection adds this forwarding import:

```python
from .stages import Context
```

`package.root` rejects the import because callers must import
`Context` from `viper.stages`.

## Master execution checklist

A checkbox closes after the listed files pass their focused checks. Complete
the phases in order. Each commit must contain only the files named by its phase.

### Terminal outcome

The refactor is complete because VIPER exposes execution results through
`viper.execution.results`, execution errors through `viper.execution.errors`,
and operations through `viper.execution`. Every shared internal function
follows the module-privacy protocol, and the architecture test rejects a
redundant underscore. The public-API test rejects a package-root forwarding
import.

### Coverage

| Work unit | Current state | Owning phase | Completion evidence |
| --- | --- | --- | --- |
| Parameter validation path | `_parameter/_validation.py` remains | Phase 1 | Parameter and preflight tests pass with the new import path. |
| Shared internal functions | Cross-module imports use underscored symbols | Phase 2 | Execution, verification, and application tests pass after the renames. |
| Execution results and errors | Public result and error modules own their local types | Phase 3 | Public import tests pass. |
| Shared Git test support | One test imports `_git` from another test module | Phase 4 | Both test modules import `tests.git_repository`. |
| Enforced convention | The source tree permits all three patterns and package-root forwarding | Phase 5 | The architecture and public-API rejection cases pass. |

### Phase 1. Normalize parameter validation

**Depends on:** None

- [x] Rename `src/viper/_parameter/_validation.py` to
      `src/viper/_parameter/validation.py`.
- [x] Update imports in `authoring.py`, `http.py`, `preflight.py`,
      `execution/_stage.py`, `_verification/attempt.py`,
      `_verification/plan.py`, `_workers/parameters.py`, and
      `_workers/stages.py`.
- [x] Update `tests/test_parameter_validation.py` to import
      `_parameter.validation`.
- [x] Confirm that active imports beneath `src/` and `tests/` use
      `_parameter.validation`.

**Acceptance gate**

```bash
ruff check src/viper/_parameter src/viper/authoring.py src/viper/http.py \
  src/viper/preflight.py src/viper/execution/_stage.py \
  src/viper/_verification src/viper/_workers tests/test_parameter_validation.py
pyright
python -m pytest tests/test_parameter_validation.py tests/test_preflight.py -q
```

**Commit boundary:** `Normalize private parameter validation path`

### Phase 2. Normalize shared internal functions

**Depends on:** Phase 1

- [x] Rename `_execute_attempt()` to `execute_attempt()`.
- [x] Rename `_resolve_inputs()` to `resolve_inputs()`.
- [x] Rename `_retrieve_download_inputs()` to
      `retrieve_download_inputs()`.
- [x] Rename `_run_after_stage_metrics()` to `run_after_stage_metrics()`.
- [x] Rename `_publish_attempt_files()` to `publish_attempt_files()`.
- [x] Rename `_publish_invocation_receipt()` to
      `publish_invocation_receipt()`.
- [x] Rename `_replace_synchronized()` to `replace_synchronized()`.
- [x] Rename `_write_attempt_document()` to `write_attempt_document()`.
- [x] Rename `_write_synchronized()` to `write_synchronized()`.
- [x] Rename `_reconcile_abandoned_attempts()` to
      `reconcile_abandoned_attempts()`.
- [x] Rename `_resolved_environment()` to `resolve_environment()`.
- [x] Rename `_resolved_stage()` to `resolve_stage()`.
- [x] Rename `_git()` to `run_git()`.
- [x] Rename `_resolved_git_file()` to `resolve_git_file()`.
- [x] Update all imports and calls beneath `src/viper/execution/`.
- [x] Rename `_artifact_revision_identity()` and `_snapshot_identity()` and
      update verification callers.
- [x] Rename `_run_request()` to `run_request()` and `_retry_request()` to
      `retry_request()`, then update the operation registry, Python entry
      points, and mocks.
- [x] Confirm that each remaining underscored function is called only within
      its defining module.

**Acceptance gate**

```bash
ruff check src/viper/execution src/viper/_verification src/viper/verification.py \
  src/viper/_api src/viper/api.py tests/test_run_execution.py \
  tests/test_verification.py tests/test_api.py
pyright
python -m pytest tests/test_run_execution.py tests/test_verification.py \
  tests/test_api.py -q
```

**Commit boundary:** `Normalize private subsystem operations`

### Phase 3. Publish execution result and error types

**Depends on:** Phase 2

- [x] Rename `execution/_results.py` to `execution/results.py`.
- [x] Move `BenchmarkExecutionResult` into `execution/results.py`.
- [x] Rename `execution/_errors.py` to `execution/errors.py`.
- [x] Move `BenchmarkExecutionError` into `execution/errors.py`.
- [x] Export `RunResult` and `BenchmarkExecutionResult` from
      `viper.execution.results`. Export `RunError` and
      `BenchmarkExecutionError` from `viper.execution.errors`. Keep
      `viper.execution.__all__` limited to `run`, `retry`, and `benchmark`.
- [x] Add `viper.randomness` to the public-module inventory introduced with
      the RNG ownership split.
- [x] Update `docs/reference/api.md` with the supported imports.
- [x] Add the private-path changes to the next alpha release notes.

**Acceptance gate**

```bash
ruff check src/viper/execution tests/test_public_api.py \
  tests/test_benchmark_execution.py tests/test_run_execution.py
pyright
python -m pytest tests/test_public_api.py tests/test_benchmark_execution.py \
  tests/test_run_execution.py -q
```

**Commit boundary:** `Publish execution results and errors`

### Phase 4. Repair shared test support

**Depends on:** Phase 2

- [x] Add `tests/git_repository.py` with `REPOSITORY` and `run_git()`.
- [x] Update `test_run_execution.py` and
      `test_generated_project_acceptance.py` to import the shared names.
- [x] Leave helpers used by only one test module local and underscored.

**Acceptance gate**

```bash
ruff check tests/git_repository.py tests/test_run_execution.py \
  tests/test_generated_project_acceptance.py
python -m pytest tests/test_run_execution.py -q
python -m pytest tests/test_generated_project_acceptance.py --collect-only -q
```

**Commit boundary:** `Give shared Git test support one owner`

### Phase 5. Enforce the boundary

**Depends on:** Phases 3 and 4

- [x] Add the private-boundary rule to `AGENTS.md`.
- [x] Add the two structural checks to
      `tests/test_validation_architecture.py`.
- [x] Add one temporary invalid source tree for each rejection case.
- [x] Require `src/viper/__init__.py` to remain docstring-only and add one
      rejected forwarding import to `tests/test_public_api.py`.
- [x] Run the structural test against the completed source tree.

**Acceptance gate**

```bash
ruff check tests/test_validation_architecture.py tests/test_public_api.py
python -m pytest tests/test_validation_architecture.py tests/test_public_api.py -q
```

**Commit boundary:** `Enforce private interface boundaries`

## Final gate

The refactor crosses parameter validation, execution, verification, and the
application API. The final gate covers one observing test for each changed
import path.

```bash
pyright
ruff check src/viper tests
python -m pytest tests/test_parameter_validation.py tests/test_preflight.py \
  tests/test_run_execution.py tests/test_benchmark_execution.py \
  tests/test_verification.py tests/test_api.py \
  tests/test_public_api.py tests/test_validation_architecture.py -q
```

## Verdict

The five phases are implemented. Each private boundary has one visible marker,
each public execution value has one defining module, and the experiment and
verification behavior remains unchanged.
