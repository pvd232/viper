# Python Environment Diagnostics

## 1. Status

**Contract status:** Planned in the [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md) checklist.

<!-- contract-protocol:generated:start -->
**Complete.**

**Checklist:** [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md)

### PairBlocks

<a id="ped-pb-01"></a>

#### <nobr><code>PED-PB-01</code></nobr>

**Status:** complete

**Requirement contribution:** Retain strict Python-environment rejection while exposing enough evidence to diagnose it before execution.

**Review handoff**

**What changed**

- diagnose_python_env() retains the active interpreter spelling, sys.path entries, every normalized distribution version and installation root, and typed strict violations in one diagnosis.
- observe_python_env() returns the existing PythonEnvSpec for a healthy environment and raises PythonEnvironmentError carrying the same diagnosis for conflicting versions.
- The typed env_doctor operation and nested viper env doctor command expose the diagnosis without starting a run and fail for strict violations.
- Runtime, CLI, public API, capability, and documentation tests observe the accepted and rejected paths.

**Plan deviations:** No deviation from PED-REQ-01 or PED-REQ-02. Duplicate installations with the same version remain acceptable because the contract rejects conflicting versions, not redundant identical metadata.

**Start review:** [Open tested GitHub comparison](https://github.com/pvd232/viper/compare/06673105ad59aec6142618bed4accd6eaaed9eed...baf27866494e65eee2fea0ba569093ef208f04a6)

**Review these files**

- [Shared environment diagnosis](../src/viper/runtime.py#L64)
- [Typed doctor operation](../src/viper/api.py#L565)
- [Acceptance tests](../plans/python-environment-diagnostics/PED-PB-01/patches/python-environment-diagnostics.patch#L1)

**Evidence:** [Passing gate receipt](../evidence/gates/ped-pb-01-r5.json)

**Decision:** <nobr><code>PED-PB-01</code></nobr> is complete; no further decision is required.

<details>
<summary>Implementation details</summary>

**Plan:** [plan.toml](../plans/python-environment-diagnostics/PED-PB-01/plan.toml)

**Retained patch:** [patches/python-environment-diagnostics.patch](../plans/python-environment-diagnostics/PED-PB-01/patches/python-environment-diagnostics.patch)

**Implementation roots:** [pyproject.toml](../pyproject.toml) · [src/viper](../src/viper)

**Test roots:** [tests](../tests)

**Dependencies:** <nobr><code>ARE-PB-02</code></nobr>

**Gate steps:**

```bash
# typecheck
(cd . && pyright src/viper/runtime.py src/viper/api.py src/viper/cli.py tests/conftest.py tests/test_runtime.py tests/test_cli.py tests/test_documentation.py tests/test_public_api.py)
# test
(cd . && python3 -m pytest -q -p no:cacheprovider tests/test_runtime.py tests/test_cli.py::test_env_doctor_reports_active_interpreter tests/test_cli.py::test_env_doctor_fails_with_duplicate_distribution_evidence tests/test_cli.py::test_env_doctor_fails_when_no_distributions_are_installed tests/test_cli.py::CommandLineTests::test_every_command_emits_one_json_document_and_stable_exit_status tests/test_api_json.py tests/test_documentation.py::test_api_operation_table_matches_python_and_cli_surfaces tests/test_public_api.py)
# documentation
(cd . && ruff check --config pyproject.toml --select D src/viper/runtime.py src/viper/api.py src/viper/cli.py tests/test_runtime.py tests/test_cli.py)
# lint
(cd . && ruff format --check --config pyproject.toml src/viper/runtime.py src/viper/api.py src/viper/cli.py tests/conftest.py tests/test_runtime.py tests/test_cli.py tests/test_documentation.py tests/test_public_api.py)
# lint
(cd . && ruff check --config pyproject.toml src/viper/runtime.py src/viper/api.py src/viper/cli.py tests/conftest.py tests/test_runtime.py tests/test_cli.py tests/test_documentation.py tests/test_public_api.py)
```

</details>


### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>PED-REQ-01</code></nobr> | When Python distribution metadata contains more than one version of a normalized package name, observe_python_env() must reject the environment and report every conflicting version, distribution root, the interpreter path, and the sys.path entries from which the conflict can be investigated. | complete | <nobr><code>PED-VR-01</code></nobr> | <nobr><code>PED-PB-01</code></nobr> |
| <nobr><code>PED-REQ-02</code></nobr> | viper env doctor must inspect the active interpreter without starting a run, emit the same structured environment diagnosis used by observe_python_env(), and return a failing status when duplicate distributions or another strict environment violation is present. | complete | <nobr><code>PED-VR-02</code></nobr> | <nobr><code>PED-PB-01</code></nobr> |

### Verification rules

| Rule | Requirements | Acceptance conditions | Success case | Rejection cases |
|---|---|---|---|---|
| <nobr><code>PED-VR-01</code></nobr> | <nobr><code>PED-REQ-01</code></nobr> | Injected metadata for two versions of one normalized distribution raises an error that names both versions, both distribution roots, sys.executable, and the relevant sys.path entries. | [test_python_env_conflict_reports_actionable_locations](../tests/test_runtime.py) | [test_python_env_still_rejects_duplicate_versions](../tests/test_runtime.py) |
| <nobr><code>PED-VR-02</code></nobr> | <nobr><code>PED-REQ-02</code></nobr> | The CLI returns a structured healthy report for one unambiguous environment and a structured nonzero failure containing the duplicate-distribution evidence for a conflicting environment. | [test_env_doctor_reports_active_interpreter](../tests/test_cli.py) | [test_env_doctor_fails_with_duplicate_distribution_evidence](../tests/test_cli.py) |
<!-- contract-protocol:generated:end -->

## 2. Claim

VIPER rejects ambiguous Python environments with enough evidence to locate the conflicting installations before a run starts.

## 3. Models

| Model | Role |
|---|---|
| Proposed `PythonEnvironmentDiagnosis` | Records the interpreter, searched paths, discovered distribution versions and roots, and violations. |
| `PythonEnvSpec` | Carries the unambiguous package versions accepted for a run. |
| `ViperFailure` | Presents the same structured diagnosis through `viper env doctor`. |

## 4. Execution

1. The diagnosis operation reads `sys.executable`, `sys.path`, and installed distribution metadata.
2. It groups distributions by normalized name while retaining every version and root.
3. `observe_python_env()` returns `PythonEnvSpec` only when the diagnosis is unambiguous.
4. `viper env doctor` prints the diagnosis without freezing or executing a run and exits nonzero for any strict violation.

## 5. Persisted evidence

| Record | Evidence |
|---|---|
| CLI result document | Interpreter, search paths, discovered conflicting versions and roots, and health status. |
| Frozen `PythonEnvSpec` | Accepted package-name and version identity used by run preflight. |

## 6. Verification

Tests inject conflicting distribution metadata and require the runtime API and CLI to report the same locations while preserving strict rejection.

## 7. Propagation

| Surface | Required change |
|---|---|
| Runtime observation | Preserve distribution locations until conflict validation completes. |
| Typed API | Define the structured environment diagnosis. |
| CLI | Add `viper env doctor` and JSON output coverage. |
| Documentation | Point environment failures to the doctor command and reported paths. |

## 8. Acceptance case

### Success

One installed version per normalized name produces a healthy diagnosis and the same accepted `PythonEnvSpec` as current observation.

### Rejection

Two versions of `cffi` produce a nonzero doctor result and an `observe_python_env()` error that names both versions, their roots, the interpreter, and relevant search paths.

## 9. Implementation order

1. Add the shared diagnostic record and strict runtime validation.
2. Route the record through the typed API and nested CLI command.
3. Add public documentation and regression tests.

## 10. Contract-owned PairBlocks

One PairBlock owns the shared diagnosis and both presentation paths so their evidence cannot drift.

## 11. ContractTarget

The source-backed plan will bind the runtime record, API request/result, CLI routing, tests, and documentation to one reviewed candidate.
