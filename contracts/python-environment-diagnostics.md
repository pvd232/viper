# Python Environment Diagnostics

## 1. Status

**Contract status:** Planned in the [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md) checklist.

<!-- contract-protocol:generated:start -->
**In progress.** [Jump to current PairBlock](#ped-pb-01)

**Checklist:** [CleaRx-driven VIPER friction repairs](../checklists/clearrx-viper-friction.md)

### PairBlocks

<a id="ped-pb-01"></a>

#### <nobr><code>PED-PB-01</code></nobr>

**Status:** drafting

**Requirement contribution:** Retain strict Python-environment rejection while exposing enough evidence to diagnose it before execution.

**Plan:** None

**Current receipt:** None

**Dependencies:** <nobr><code>ARE-PB-02</code></nobr>

**Next action:** Run the current PairBlock plan.


### Requirements

| Requirement | Claim | Progress | Verifiers | PairBlocks |
|---|---|---|---|---|
| <nobr><code>PED-REQ-01</code></nobr> | When Python distribution metadata contains more than one version of a normalized package name, observe_python_env() must reject the environment and report every conflicting version, distribution root, the interpreter path, and the sys.path entries from which the conflict can be investigated. | in_progress | <nobr><code>PED-VR-01</code></nobr> | <nobr><code>PED-PB-01</code></nobr> |
| <nobr><code>PED-REQ-02</code></nobr> | viper env doctor must inspect the active interpreter without starting a run, emit the same structured environment diagnosis used by observe_python_env(), and return a failing status when duplicate distributions or another strict environment violation is present. | in_progress | <nobr><code>PED-VR-02</code></nobr> | <nobr><code>PED-PB-01</code></nobr> |

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
