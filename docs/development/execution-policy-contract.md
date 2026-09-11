# Execution Policy Contract

## 1. Status

**Contract status:** Implemented; CPU checks passed; CUDA acceptance pending
**Checklist variant:** Self-contained

The implementation uses independent [evidence records](../../src/viper/evidence.py)
and [verification operations](../../src/viper/verification.py). The
[checklist](execution-policy-contract.checklist.json) records acceptance results.

The [source API](../../src/viper/repository.py) supplies workspace identity.
[Verification tests](../../tests/test_verification_acceptance.py) check saved
readings; [workflow tests](../../tests/test_readme_workflow.py) execute the examples.

| ID | Implementation obligation |
|---|---|
| EP-00 | Resolve presets and validate detached custom settings without changing the runtime. |
| EP-01 | Resolve reproducible, relaxed, or custom settings once during authoring. |
| EP-02 | Require policy identity and concrete settings in every saved run. |
| EP-03 | Apply controls and observe effective worker settings before invocation. |
| EP-04 | Reject saved stage and metric readings that disagree with the run, including evidence reached through reuse. |
| EP-05 | Discover workspace source through the public API and provide complete examples for each execution policy. |

## 2. Required claim

VIPER freezes the selected execution policy in each new plan and verifies that
every executed stage and metric worker started with its applicable controls.

```math
S = R_v(m,c,q),\qquad A(p,w) \iff I(p) \land O(w)=P(S,b_w)
```

where:

- `S` is the complete `ReproducibilitySpec` frozen in plan `p`;
- `R_v` resolves policy version `v`, mode `m`, and custom settings `c`;
- `q` supplies explicit parallelism or the authoring-time thread defaults;
- `I(p)` checks that the policy identity and frozen settings agree;
- `O(w)` is worker `w`'s recorded startup observation;
- `P(S,b_w)` selects the controls applicable to worker backend `b_w`;
- `A(p,w)` is acceptance of the worker's policy evidence, in addition to all
  existing provenance checks.

This contract's settings check asks whether the selected controls were active
before user code ran. Both reproducible and relaxed runs can pass that check.
Existing checks of source, inputs and saved artifacts continue to apply in both
modes. Comparing the outputs of two runs is a different operation, described in
Section 7.

## 3. Runtime settings check

[Authoring](../../src/viper/authoring.py) resolves the selected policy into
`RunPlanDraft` and saves both the policy and its settings in
[RunSpec](../../src/viper/runs.py). [Runtime initialization](../../src/viper/runtime.py)
applies those settings. Immediately before invoking user code, each worker
reads PyTorch's active controls inside the selected autocast context.
[Verification](../../src/viper/_verification/runtime.py) compares those readings
with the plan.

```mermaid
flowchart LR
    P[Settings saved in plan] --> A[Apply settings]
    A --> O[Read active controls]
    O --> V[Compare with plan]
    P -->|expected values| V

    classDef plan fill:#1e3a8a,stroke:#60a5fa,color:#fff,stroke-width:2px
    classDef runtime fill:#115e59,stroke:#5eead4,color:#fff,stroke-width:2px
    classDef check fill:#581c87,stroke:#d8b4fe,color:#fff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
    class P plan
    class A,O runtime
    class V check
```

For `deterministic_algorithms`, the settings check works as follows:

| Selected mode | Saved setting | PyTorch reports | Settings check |
|---|---|---|---|
| Reproducible | `True` | `True` | Pass |
| Reproducible | `True` | `False` | Fail |
| Relaxed | `False` | `False` | Pass |
| Relaxed | `False` | `True` | Fail: active controls differ from the selection |

VIPER must read the active value from PyTorch. Copying the saved value into a
receipt supplies no independent reading. Workers read the controls before stage
and metric functions run. The saved-run verifier later compares those readings
with the plan. Each control has its corresponding comparison.

## 4. Models

### Record the author's choice

When you select `relaxed`, VIPER records that name and the preset version used
to choose its settings. `ExecutionPolicyRef` holds those two values. The concrete
settings remain in the existing `reproducibility` field, so a later execution
can use the saved values even if preset defaults change in a future release.

| Field in `ExecutionPolicyRef` | Type | Meaning |
|---|---|---|
| `mode` | `Literal["reproducible", "relaxed", "custom"]` | The selection made when preparing the run. |
| `version` | `Literal[1]` | The version of the rules used to resolve that selection. |

Both `RunPlanDraft.execution_policy` and `RunSpec.execution_policy` require
this record. Earlier development records missing it must be regenerated.

`plan()` prepares one run. `expand()` prepares several variant-replicate pairs.
Both accept a preset name or explicit `ReproducibilitySpec`, plus separate
`parallelism: ParallelismSpec | None` for presets. Explicit full settings select
custom mode. The [API reference](../reference/api.md) describes those arguments.

The two version fields describe different things: `ExecutionPolicyRef.version=1`
identifies the first preset definition; `RunSpec.schema_version=2` identifies the
current run-record format. Neither is the package release number. There is one
supported schema shape for this unreleased library, not a compatibility matrix.

### Record the settings read from PyTorch

Before calling a stage or metric function, VIPER applies the saved settings
and reads the active values from PyTorch. It saves those readings in
`RuntimeControlsReceipt`, attached as `ProcessStartupReceipt.observed_controls`.
The verifier compares the readings with the settings saved for that run.

For example, `deterministic_algorithms` records the boolean returned by
`torch.are_deterministic_algorithms_enabled()`. If relaxed mode saved `False`
and the getter returns `False`, that setting passes its check.

The fields and their read operations are listed below. The read operations use
[PyTorch's runtime API](https://docs.pytorch.org/docs/2.6/torch.html) and
[backend controls](https://docs.pytorch.org/docs/2.6/backends.html).

| Field in `RuntimeControlsReceipt` | Type | Read operation and purpose |
|---|---|---|
| `backend` | `Literal["cpu", "cuda"]` | Record the worker's selected compute kind and check it against the existing backend observation. It identifies which device-specific controls apply. |
| `deterministic_algorithms` | `bool` | `torch.are_deterministic_algorithms_enabled()`: whether deterministic algorithms are required. |
| `deterministic_warn_only` | `bool` | `torch.is_deterministic_algorithms_warn_only_enabled()`: whether an unsupported deterministic operation warns instead of failing. |
| `cudnn_deterministic` | `bool` | `torch.backends.cudnn.deterministic`: whether deterministic cuDNN algorithms are required. |
| `cudnn_benchmark` | `bool` | `torch.backends.cudnn.benchmark`: whether cuDNN benchmarks algorithms to select one. |
| `cudnn_allow_tf32` | `bool` | `torch.backends.cudnn.allow_tf32`: whether cuDNN may use TensorFloat-32 arithmetic. |
| `float32_matmul_precision` | `Literal["highest", "high", "medium"]` | `torch.get_float32_matmul_precision()`: the selected internal precision setting for float32 matrix multiplication. |
| `torch_intraop_threads` | `int`, at least 1 | `torch.get_num_threads()`: CPU thread count within an operation. |
| `torch_interop_threads` | `int`, at least 1 | `torch.get_num_interop_threads()`: CPU thread count for work across operations. |
| `autocast_enabled` | `bool` | `torch.is_autocast_enabled(backend)`: whether automatic mixed precision is enabled for this worker's device type. |
| `autocast_dtype` | `Literal["float16", "bfloat16"] \| None` | When enabled, read `torch.get_autocast_dtype(backend)` and save its matching dtype name. When disabled, save `None`. Reject unsupported enabled dtypes. |

Read the last two fields while the configured `torch.autocast(...)` context is
active, immediately before calling user code. Reading outside that context could
report different settings. PyTorch describes this scope in its
[automatic mixed precision documentation](https://docs.pytorch.org/docs/2.6/amp.html).

The cuDNN values remain readable on CPU, but they do not control CPU arithmetic.
Record them as configured values; apply their execution checks only to CUDA
workers. A backend mismatch fails separately. These readings describe settings,
not which GPU kernel actually executed.

### Keep existing observations in their existing records

`ProcessStartupReceipt.env` records process environment values, including
`CUBLAS_WORKSPACE_CONFIG`. Its `generators` field records seeded random number
generator identities and state hashes. `observed_controls` adds the PyTorch
readings to those existing observations.

Thread getters do not report how a DataLoader was constructed. Continue checking
worker and prefetch configuration through the existing DataLoader records.

### Preset values

The presets use these values:

| Setting | Reproducible | Relaxed |
|---|---|---|
| `deterministic_algorithms` | `True` | `False` |
| `deterministic_warn_only` | `False` | `False` |
| `cudnn_deterministic` | `True` | `False` |
| `cudnn_benchmark` | `False` | `True` |
| `cublas_workspace_config` | `":4096:8"` | `None` |
| Precision | `float32_matmul_precision="highest"`, `cudnn_allow_tf32=False`, `autocast_enabled=False`, `autocast_dtype=None` | Same |
| Default parallelism | One process; one intra-op and one inter-op thread | One process; retain the authoring process’s configured Torch thread counts |
| Default DataLoader | `workers=0`, `prefetch_factor=None`, `persistent_workers=False`, `in_order=True` | Same; either preset accepts explicit worker/prefetch settings |
| NumPy | `generators={}`, `capture_legacy_global=True` | Same |

Both presets use the declared run seed and existing backend selection. Relaxed
permits nondeterministic algorithms while retaining the same precision controls.
The axis is determinism. Parallelism is an independent resource choice: both
presets accept `parallelism: ParallelismSpec | None`. Explicit settings are copied
and validated, and do not change the preset label. Zero loader workers is a
default, not a restriction; choose workers and prefetching for the workload.
Resolve thread counts once at authoring and persist the resulting integers.
Replaying a saved plan must never read thread defaults from the new host.

Named NumPy generators or numerical overrides require a custom spec. A custom
spec already includes parallelism; supplying both is rejected. Existing runtime
limits, including single-process execution, still apply.
No preset supplies a workspace-specific generator name such as `training`.

## 5. Execution

1. When the author calls `plan()` or `expand()`, resolve the selected preset or
   validate custom settings. Copy the resulting values into each immutable draft.
2. When saving the plan, write its selected mode, preset version and concrete
   settings. Numerical overrides require custom mode; parallelism is independent.
3. When starting or retrying a run, load its saved values. Do not resolve the
   selection again using the installed release's defaults.
4. Before CUDA initializes, set the worker's process environment. Remove an
   inherited `CUBLAS_WORKSPACE_CONFIG` when the saved setting is `None`.
5. In the worker, apply the saved Torch controls and initialize the declared
   random number generators. Enter the configured autocast context, which controls
   automatic mixed precision while user code runs.
6. Before calling the stage or metric function, read and save the active controls
   listed in Section 4. A disagreement with the applicable saved settings fails
   the settings check.

This work retains the current single-process and single-CUDA-device limits.
User code can change controls or use untracked randomness after the check;
these startup readings do not monitor every later operation.

## 6. Persisted evidence

| Record | Required evidence |
|---|---|
| Saved authoring plan and `RunSpec` | Save the selected mode and version alongside the concrete settings. Include them in the existing plan serialization and hash checks. |
| Executed stage and metric startup receipts | Save the PyTorch readings from Section 4 before calling user code; retain the existing environment and random-generator records. |
| Reused stage evidence | Read the policy and startup record of the run that produced the reused result. Reusing a result does not start a new worker for that stage. |
| Artifact comparison receipt | Identify the two artifacts and save their hashes and comparison result. The selected execution mode does not supply this result. |

Saved runs require policy identity and the current schema. Regenerate development
records missing required fields. Unknown policy versions fail explicitly.

## 7. Verification

| Rule | Executable condition |
|---|---|
| EP-V1 | Omitted selection uses the reproducible preset; relaxed permits nondeterministic algorithms, preserves precision, and retains configured Torch thread counts; either preset accepts independent parallelism. |
| EP-V2 | Preset label/version matches its numerical settings; parallelism is validated independently and frozen. Custom retains all validated caller values. Unknown versions reject. |
| EP-V3 | Serialization, retry and execution consume frozen settings even when resolver defaults change. |
| EP-V4 | Recorded environment, generator receipts and queried controls match the plan for every executed stage and metric worker. Missing required observations fail the settings check. |
| EP-V5 | Reject a startup reading that differs from its applicable saved setting. Under reproducible mode, unsupported deterministic operations fail instead of warning and continuing. |
| EP-V6 | Missing policy identity rejects the saved run. Reuse retains and checks the producing run’s record. |
| EP-V7 | Byte comparison remains exact in every mode. Relaxed runs may pass provenance verification and fail a parity benchmark; metric tolerances do not change artifact equality. |

### What each check answers

| Check | Question | Passing result means |
|---|---|---|
| Execution settings | Were the selected controls active before user code ran? | The observed settings match the saved settings, including permitted nondeterminism in relaxed mode. |
| Saved-run verification | Do the recorded source, inputs, artifacts and measurements satisfy the run's verification rules? | The saved run passes those rules. A second run is not required. |
| Output comparison | Did two runs produce identical bytes for the selected artifacts? | Those particular artifacts match byte for byte. |

A relaxed run can pass saved-run verification even when its outputs differ from
a later run. A separate comparison can assess numerical agreement using declared
metric criteria; passing those criteria does not mean the artifact bytes match.
A strict rerun produces a new result and does not change how the original run
was executed.

Deterministic controls alone do not establish output equality across hardware
or software versions. [PyTorch documents those repeatability limits](https://docs.pytorch.org/docs/stable/notes/randomness.html).

## 8. Implementation owners

| Surface | Responsibility |
|---|---|
| [Authoring](../../src/viper/authoring.py), [runs](../../src/viper/runs.py), [runtime](../../src/viper/runtime.py) | Resolve modes, freeze identity/settings, observe effective controls, version records. |
| [Workers](../../src/viper/_workers), [verification](../../src/viper/_verification), [reuse](../../src/viper/reuse.py) | Observe inside invocation context; enforce new evidence and retain checks of reused results. |
| [Serialization](../../src/viper/serialization.py), [CLI](../../src/viper/cli.py) | Expose the updated required fields through existing schema/capability routes. |
| [README](../../README.md), [tutorial](../tutorials), [examples](../../examples), [API reference](../reference/api.md) | Show complete preset and custom examples; explain artifact comparison separately. |
| [Tests](../../tests) | Exercise policy selection, observed controls, saved-run rejection, and exact benchmark comparisons. |

## 9. Acceptance case

### Success

Run the complete CPU quickstart with the default selection and a fixed seed.
Save and reload the plan; execute it twice in the same environment. Verify every
stage and metric startup receipt. Compare the declared model artifact bytes and
report that specific comparison result. Repeat with relaxed and custom settings;
verify their actual controls without requiring relaxed artifacts to match.

The relaxed-run acceptance case must execute a complete run, close the producing
process, then verify the saved run through the public verifier in a fresh process.
Require successful provenance and measurement verification without demanding
byte identity with another run. Tampering with a saved artifact must still fail.
A separate strict rerun is a new run: assess any numerical agreement using declared
metric criteria, and report byte comparisons separately. Retain both run IDs and
the comparison result. The [workflow tests](../../tests/test_readme_workflow.py) exercise this full run;
preset-value and serialization tests cover only the individual settings.

For CUDA acceptance, retain the GPU model, driver, CUDA/cuDNN/PyTorch versions,
plan, receipts and selected artifact digests from two executions on the same
supported device. A host without CUDA leaves this gate pending. Run timestamps
and other execution metadata are outside the artifact comparison.

### Rejection

Change one recorded observed control while preserving the requested spec. Both
stage and metric verification must reject. Also reject a preset/settings mismatch,
an unknown policy version, missing required observations, and an unsupported
operation under the reproducible policy. A development record missing required fields must be regenerated.

## 10. Tests and remaining acceptance

The [checklist](execution-policy-contract.checklist.json) retains requirement IDs,
dependencies, and recorded results. Implementation and CPU checks are complete;
live CUDA acceptance remains open.

| Requirement | Implementation | Observing tests |
| --- | --- | --- |
| EP-00 | [Preset resolver](../../src/viper/runtime.py) | [Runtime boundary](../../tests/test_runtime_boundary.py) |
| EP-01 | [Authoring](../../src/viper/authoring.py) | [Authoring](../../tests/test_authoring.py) |
| EP-02 | [Run records](../../src/viper/runs.py), [policy validation](../../src/viper/runtime.py) | [Runtime boundary](../../tests/test_runtime_boundary.py), [authoring](../../tests/test_authoring.py) |
| EP-03 | [Runtime](../../src/viper/runtime.py), [workers](../../src/viper/_workers) | [Process startup](../../tests/test_process_startup.py), [policy execution](../../tests/test_execution_policy_acceptance.py) |
| EP-04 | [Control comparison](../../src/viper/_verification/runtime.py), [stage and metric verification](../../src/viper/_verification) | [Saved-reading tampering](../../tests/test_verification_acceptance.py) |
| EP-05 | [Source discovery](../../src/viper/repository.py), [complete examples](../../examples/README.md) | [Public workflows](../../tests/test_readme_workflow.py) |

From the repository root, run the CPU policy and saved-reading checks:

```bash
source .venv/bin/activate
python -m pytest -q tests/test_runtime_boundary.py tests/test_authoring.py tests/test_process_startup.py tests/test_execution_policy_acceptance.py tests/test_verification_acceptance.py -m "not live_cuda"
python -m pytest -q tests/test_readme_workflow.py tests/test_documentation.py
```

On the designated single-L4 host, retain the real-device receipts:

```bash
source .venv/bin/activate
VIPER_LIVE_CUDA=1 VIPER_POLICY_EVIDENCE_DIR=policy-evidence python -m pytest -q tests/test_execution_policy_acceptance.py tests/test_live_process_startup.py
```

The CUDA gate requires executed device cases. Each policy JSON receipt records
both runs' startup controls, software and device versions, output hashes, and
the byte-comparison result. Skipped cases leave this gate open.
