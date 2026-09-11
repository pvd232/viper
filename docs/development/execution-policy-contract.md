# Execution Policy Contract

## 1. Status

**Contract status:** Implemented; CPU checks passed; CUDA acceptance pending
**Checklist variant:** Self-contained

The implementation uses independent [evidence records](../../src/viper/evidence.py)
and [verification operations](../../src/viper/verification.py). The
[checklist](execution-policy-contract.checklist.json) records acceptance results.

**Public source API: [EP-B5](#ep-b5-public-source-and-execution-code).**
**Acceptance tests: [saved records](#ep-vb4-verify-saved-runs-and-reuse) and
[complete workflows](#ep-vb5-verify-public-workflows).**

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

## 3. Current gap

### Inspected path

[Authoring](../../src/viper/authoring.py) now accepts a policy choice or custom
settings in `plan()` and `expand()`. It freezes the selected settings in
`RunPlanDraft` and compiles them into [RunSpec](../../src/viper/runs.py).
[Runtime initialization](../../src/viper/runtime.py) applies controls but stores
the requested spec in `ProcessStartupReceipt.reproducibility`.
[Stage verification](../../src/viper/_verification/attempt.py) and
[metric verification](../../src/viper/_verification/metrics.py) compare that
copy with the plan. This comparison does not independently observe Torch flags.

### Proposed check

Authors select a preset or supply custom settings. The proposed change adds a
readback step: after applying the saved settings, VIPER asks PyTorch which
controls are active, before calling the stage or metric function.

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

For `deterministic_algorithms`, the proposed settings check works as follows:

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

[Authoring](../../src/viper/authoring.py) already puts this record in
`RunPlanDraft.execution_policy`. EP-B2 will add `RunSpec.execution_policy` so the
saved run also retains the choice. EP-B2 makes the record required. Earlier development records must be regenerated.

`plan()` prepares one run. `expand()` prepares several variant-replicate pairs.
Both already accept a preset name or explicit `ReproducibilitySpec`, plus separate
`parallelism: ParallelismSpec | None` for presets. Explicit full settings select
custom mode. The [API reference](../reference/api.md) describes those arguments.

The two version fields describe different things: `ExecutionPolicyRef.version=1`
identifies the first preset definition; `RunSpec.schema_version=2` identifies the
current run-record format. Neither is the package release number. There is one
supported schema shape for this unreleased library, not a compatibility matrix.

### Record the settings read from PyTorch

Before calling your stage or metric function, VIPER will apply the saved settings
and then read the active values from PyTorch. It will save those readings in a
proposed `RuntimeControlsReceipt`, attached as
`ProcessStartupReceipt.observed_controls`. The verifier will compare the readings
with the settings saved for that run. This record is not implemented yet.

For example, `deterministic_algorithms` records the boolean returned by
`torch.are_deterministic_algorithms_enabled()`. If relaxed mode saved `False`
and the getter returns `False`, that setting passes its check.

The proposed fields are listed individually below. The read operations use
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

`ProcessStartupReceipt.env` already records process environment values, including
`CUBLAS_WORKSPACE_CONFIG`. Its `generators` field already records seeded random
number generator identities and state hashes. Keep those fields; the proposed
record above adds the PyTorch readings that are currently missing.

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

VIPER is unreleased. Update the current schema directly and require policy
identity. Regenerate development records and fixtures missing the new field.
Keep a single schema version; do not add a legacy reader, compatibility default
or migration layer. Unknown policy versions fail explicitly.

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

## 8. Propagation

| Surface | Required change |
|---|---|
| [Authoring](../../src/viper/authoring.py), [runs](../../src/viper/runs.py), [runtime](../../src/viper/runtime.py) | Resolve modes, freeze identity/settings, observe effective controls, version records. |
| [Workers](../../src/viper/_workers), [verification](../../src/viper/_verification), [reuse](../../src/viper/reuse.py) | Observe inside invocation context; enforce new evidence and retain checks of reused results. |
| [Serialization](../../src/viper/serialization.py), [CLI](../../src/viper/cli.py) | Expose the updated required fields through existing schema/capability routes. |
| [README](../../README.md), [tutorial](../tutorials), [examples](../../examples), [API reference](../reference/api.md) | Replace preset boilerplate only after implementation; show a complete custom example and explain parity separately. |
| [Tests](../../tests) | Add the observing cases assigned below; preserve exact benchmark comparison semantics. |

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
the comparison result. This end-to-end check belongs to EP-VB5; a test
of preset values or a settings serialization round trip cannot close it.

For CUDA acceptance, retain the GPU model, driver, CUDA/cuDNN/PyTorch versions,
plan, receipts and selected artifact digests from two executions on the same
supported device. A host without CUDA leaves this gate pending. Run timestamps
and other execution metadata are outside the artifact comparison.

### Rejection

Change one recorded observed control while preserving the requested spec. Both
stage and metric verification must reject. Also reject a preset/settings mismatch,
an unknown policy version, missing required observations, and an unsupported
operation under the reproducible policy. A development record missing required fields must be regenerated.

## 10. Implementation order

1. Resolve policies and expose the authoring parameter (EP-B0, EP-B1; implemented).
2. Persist policy identity and enforce its consistency with saved settings (EP-B2a, EP-B2b).
3. Record active worker controls (EP-B3).
4. Enforce those observations in saved-run verification (EP-B4).
5. Publish complete policy examples and update their documentation (EP-B5).

Tests and acceptance execution belong to the EP-VB verification blocks. The
production verifier in EP-B4 is library behavior; EP-VB4 tests that behavior.

## 11. Master checklist

Implementation and verification have separate blocks. Existing completion
records for EP-B0 and EP-B1 remain in the manifest. Later blocks remain open
until their working-checkout results are recorded.

- [x] EP-B0 — EP-00: preset resolver. Verification: EP-VB0.
- [x] EP-B1 — EP-01: authoring selection. Verification: EP-VB1.
- [x] EP-B2a — EP-02: required saved identity; depends on EP-B1. Verification: EP-VB2a.
- [x] EP-B2b — EP-02: saved policy/settings consistency; depends on EP-B2a. Verification: EP-VB2b.
- [x] EP-B3 — EP-03: runtime recording; depends on EP-B2b. Verification: EP-VB3.
- [x] EP-B4 — EP-04: production verifier; depends on EP-B3. Verification: EP-VB4.
- [ ] EP-B5 — EP-05: examples and documentation implemented; CPU workflows pass. The EP-VB5 CUDA gate remains open.
- [x] EP-VB0 — existing resolver test evidence.
- [x] EP-VB1 — existing authoring test evidence.
- [x] EP-VB2a — schema, writer, and reader checks.
- [x] EP-VB2b — settings consistency and replay checks.
- [x] EP-VB3 — getter, autocast, and process-start checks; run after EP-B4 is present.
- [x] EP-VB4 — saved stage, metric, reuse, and byte-comparison checks.
- [ ] EP-VB5 — public workflows and CPU acceptance pass; CUDA acceptance requires the single-L4 host.

CUDA access is required for CUDA acceptance. Source discovery convenience,
multiprocess execution, and continuous control monitoring remain outside this
contract. The user applies production code; Codex prepares the contract and
runs candidate checks when requested.

## 12. Contract-owned PairBlocks

Start with [EP-B2a](#ep-b2a-schema-and-writer-code), then
[EP-B2b](#ep-b2b-runtime-code), [EP-B3](#ep-b3-runtime-code),
[EP-B4](#ep-b4-comparison-code), and [EP-B5](#ep-b5-example-code).
Test code and acceptance instructions follow in the verification blocks.

### EP-B0: Resolve execution settings

- Requirement: EP-00; dependencies: none.
- Targets: `src/viper/runtime.py` and `tests/test_runtime_boundary.py` only.
- Edit: insert `ExecutionPolicyRef` and `resolve_execution_policy` at module
  scope after the final field of `ReproducibilitySpec`; replace the test file
  with the complete contents below.
- Focused test: `pytest -q tests/test_runtime_boundary.py -k execution_policy`.
- Completion gate: reviewed diff, focused tests, Ruff and Pyright for both
  target files, followed by the same checks after the user applies the edit.

**Context:** Callers currently construct every reproducibility setting themselves.
This block defines the two presets and validates a separate copy of custom
settings. It returns policy identity and settings without changing Torch state;
EP-B1 will connect those values to authoring.

<!-- pair-code-start: EP-B0 -->
#### EP-B0 runtime code

**File: `src/viper/runtime.py`**

Open [src/viper/runtime.py](../../src/viper/runtime.py) and find
`class ReproducibilitySpec(ProtocolModel):`. Its last field is
`numpy_randomness: NumPyRandomnessSpec` (line 144 in the inspected baseline).
Insert the code below after that class, at module scope with no indentation.
Keep the following existing declarations in place. No import changes are needed.

```python
class ExecutionPolicyRef(ProtocolModel):
    """Identify the mode and version used to select execution settings."""

    mode: Literal["reproducible", "relaxed", "custom"] = Field(
        description="Preset used to select settings, or custom for caller settings."
    )
    version: Literal[1] = Field(
        default=1,
        description="Version of the preset definitions and custom selection rules.",
    )


def resolve_execution_policy(
    selection: Literal["reproducible", "relaxed"] | ReproducibilitySpec = (
        "reproducible"
    ),
    *,
    parallelism: ParallelismSpec | None = None,
) -> tuple[ExecutionPolicyRef, ReproducibilitySpec]:
    """Return policy identity and validated settings without changing the runtime.

    Explicit settings select custom, even when their values equal a preset.
    Revalidate and copy those settings so caller-owned mappings remain separate.
    Presets accept parallelism independently of numerical controls. Relaxed
    defaults retain the authoring process's configured Torch thread counts;
    callers supply DataLoader worker settings for their workload.
    """
    if isinstance(selection, ReproducibilitySpec):
        if parallelism is not None:
            raise ValueError("custom settings already include parallelism")
        settings = ReproducibilitySpec.model_validate(selection.model_dump())
        return ExecutionPolicyRef(mode="custom"), settings
    if selection not in {"reproducible", "relaxed"}:
        raise ValueError("execution policy must be reproducible, relaxed, or a spec")

    deterministic = selection == "reproducible"
    if parallelism is None:
        parallelism = ParallelismSpec(
            process_count=1,
            torch_intraop_threads=1 if deterministic else torch.get_num_threads(),
            torch_interop_threads=(
                1 if deterministic else torch.get_num_interop_threads()
            ),
            dataloader=DataLoaderConfiguration(workers=0),
        )
    parallelism = ParallelismSpec.model_validate(parallelism.model_dump())
    settings = ReproducibilitySpec(
        determinism=TorchDeterminismSpec(
            deterministic_algorithms=deterministic,
            deterministic_warn_only=False,
            cudnn_deterministic=deterministic,
            cudnn_benchmark=not deterministic,
            cublas_workspace_config=":4096:8" if deterministic else None,
        ),
        precision=TorchPrecisionSpec(
            float32_matmul_precision="highest",
            cudnn_allow_tf32=False,
            autocast_enabled=False,
            autocast_dtype=None,
        ),
        parallelism=parallelism,
        numpy_randomness=NumPyRandomnessSpec(
            generators={},
            capture_legacy_global=True,
        ),
    )
    return ExecutionPolicyRef(mode=selection), settings
```

Tests and acceptance commands: [EP-VB0](#ep-vb0-verification-of-ep-b0).

<!-- pair-code-end: EP-B0 -->

The Python blocks are the authoritative proposed code for EP-B0. Each has an
exact insertion or replacement instruction; neither target needs another
propagation edit to compile. The explicit string `optimized` in the rejection
test checks that the retired selection is rejected.

**Validation:** The first block is now applied in the active checkout. Its
Python blocks match the runtime declarations and test file. Focused runtime tests,
Ruff and Pyright validate this block; authoring integration and the fresh-process
verification acceptance case remain pending in EP-B1 through EP-B4.

**Check:** The commands below verify the implemented EP-B0 block.

```bash
source .venv/bin/activate
python -m ruff check src/viper/runtime.py tests/test_runtime_boundary.py
python -m pyright src/viper/runtime.py tests/test_runtime_boundary.py
python -m pytest -q tests/test_runtime_boundary.py -k execution_policy
```

EP-B1 is implemented below. The remaining production edits and their
verification blocks follow in dependency order.

### EP-B1: Author execution policies

- Requirement: EP-01; dependency: completed EP-00.
- Targets: `src/viper/authoring.py`, `tests/test_authoring.py`, and `docs/reference/api.md`.
- Focused check: `python -m pytest -q tests/test_authoring.py -k execution_policy`.
- Gate: the focused check, Ruff and Pyright for the two Python files, and your
  review of the resulting edits before proceeding to EP-B2.

**Context:** An author currently supplies every reproducibility setting when
preparing a run. This edit lets `plan()` prepare one run with a policy choice,
and lets `expand()` prepare several runs with the same resolved policy. Both
freeze the settings and policy identity in their returned drafts.

This block is written as instructions from the preceding implementation. The
current checkout already contains these edits in `50ac550`; review the code
below without inserting duplicate definitions. That commit was applied by Codex,
not by the user. The recorded test results do not substitute for your review.

#### EP-B1 authoring code

**File: `src/viper/authoring.py`**

Replace the existing `from .runtime import ...` statement with the import group
below. Then replace each complete declaration named `RunPlanDraft`,
`_plan_with_run_id`, `plan`, and `expand` with its corresponding declaration
below, at its existing location. Leave all intervening declarations in place.
Do not replace the whole module with this block.

```python
from .runtime import (
    EnvSpec,
    ExecutionPolicyRef,
    ParallelismSpec,
    ReproducibilitySpec,
    resolve_execution_policy,
)


class RunPlanDraft(BaseModel):
    """Select one immutable experiment variant and replicate for execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    run_id: RunId
    experiment: ExperimentDraft
    variant: VariantId
    replicate: ReplicateId
    benchmark: BenchmarkDraft | None = None
    source: GitSource
    env: EnvSpec
    reproducibility: ReproducibilitySpec
    execution_policy: ExecutionPolicyRef = Field(
        description="Mode and preset version selected when authoring this run.",
    )


def _plan_with_run_id(
    *,
    experiment: ExperimentDraft,
    variant: VariantId,
    replicate: ReplicateId,
    run_id: RunId,
    benchmark: BenchmarkDraft | None,
    source: GitSource,
    env: EnvSpec,
    reproducibility: ReproducibilitySpec,
    execution_policy: ExecutionPolicyRef,
) -> RunPlanDraft:
    """Create one plan with an already assigned run ID."""
    if variant not in experiment.variants:
        raise ValueError("variant is absent from the experiment")
    if replicate not in experiment.replicates:
        raise ValueError("replicate is absent from the experiment")
    draft = RunPlanDraft(
        run_id=run_id,
        experiment=experiment,
        variant=variant,
        replicate=replicate,
        benchmark=benchmark,
        source=source,
        env=env,
        reproducibility=reproducibility,
        execution_policy=execution_policy,
    )
    return _deep_freeze(draft)


def plan(
    *,
    experiment: ExperimentDraft,
    variant: VariantId,
    replicate: ReplicateId,
    benchmark: BenchmarkDraft | None = None,
    source: GitSource,
    env: EnvSpec,
    reproducibility: Literal["reproducible", "relaxed"] | ReproducibilitySpec = (
        "reproducible"
    ),
    parallelism: ParallelismSpec | None = None,
) -> RunPlanDraft:
    """Select a variant and replicate and assign a new run ID.

    Copy and freeze the declarations so later caller edits leave this plan
    unchanged. Compilation and file writes occur when freeze_run_plan() or
    execution.run() consumes the draft. Both selected names must exist in
    the experiment. Resolve the numerical policy and resource settings once;
    later execution consumes the frozen settings without consulting defaults.
    """
    execution_policy, settings = resolve_execution_policy(
        reproducibility, parallelism=parallelism
    )
    return _plan_with_run_id(
        experiment=experiment,
        variant=variant,
        replicate=replicate,
        run_id=_new_run_id(),
        benchmark=benchmark,
        source=source,
        env=env,
        reproducibility=settings,
        execution_policy=execution_policy,
    )


def expand(
    experiment: ExperimentDraft,
    *,
    run_ids: RunIdMap,
    benchmark: BenchmarkDraft | None = None,
    source: GitSource,
    env: EnvSpec,
    reproducibility: Literal["reproducible", "relaxed"] | ReproducibilitySpec = (
        "reproducible"
    ),
    parallelism: ParallelismSpec | None = None,
    variants: tuple[VariantId, ...] | None = None,
    replicates: tuple[ReplicateId, ...] | None = None,
) -> tuple[RunPlanDraft, ...]:
    """Create plans for selected variant-replicate pairs in declaration order.

    run_ids maps each selected variant to each selected replicate's unique
    run ID. Omitted filters select all declared names. The returned tuple is
    ordered by variant, then replicate, regardless of filter order. Each plan
    is copied and frozen as in plan(); file writes occur during freezing.
    Resolve policy and resource defaults once for the entire selected set.
    """
    if variants is not None and len(variants) != len(set(variants)):
        raise ValueError("variant filter contains duplicates")
    if replicates is not None and len(replicates) != len(set(replicates)):
        raise ValueError("replicate filter contains duplicates")

    variant_filter = None if variants is None else set(variants)
    replicate_filter = None if replicates is None else set(replicates)
    if variant_filter is not None and not variant_filter <= set(experiment.variants):
        raise ValueError("variant filter contains an unknown ID")
    if replicate_filter is not None and not replicate_filter <= set(
        experiment.replicates
    ):
        raise ValueError("replicate filter contains an unknown ID")

    selected_variants = tuple(
        variant_id
        for variant_id in experiment.variants
        if variant_filter is None or variant_id in variant_filter
    )
    selected_replicates = tuple(
        replicate_id
        for replicate_id in experiment.replicates
        if replicate_filter is None or replicate_id in replicate_filter
    )
    if set(run_ids) != set(selected_variants) or any(
        set(run_ids[variant_id]) != set(selected_replicates)
        for variant_id in selected_variants
    ):
        raise ValueError("run ID map must match the selected pairs")

    assigned = tuple(
        run_ids[variant_id][replicate_id]
        for variant_id in selected_variants
        for replicate_id in selected_replicates
    )
    if len(assigned) != len(set(assigned)):
        raise ValueError("run IDs must be unique")

    execution_policy, settings = resolve_execution_policy(
        reproducibility, parallelism=parallelism
    )
    return tuple(
        _plan_with_run_id(
            experiment=experiment,
            variant=variant_id,
            replicate=replicate_id,
            run_id=run_ids[variant_id][replicate_id],
            benchmark=benchmark,
            source=source,
            env=env,
            reproducibility=settings,
            execution_policy=execution_policy,
        )
        for variant_id in selected_variants
        for replicate_id in selected_replicates
    )
```

`resolve_execution_policy()` returns the selection identity and concrete settings.
`plan()` passes both to `_plan_with_run_id()`, which copies and freezes the draft.
`expand()` resolves once before its loop, then gives each run its own frozen copy.
Calls to `plan()` and `expand()` populate the field. EP-B2 makes it required
for manually constructed drafts too.

Tests and acceptance commands: [EP-VB1](#ep-vb1-verification-of-ep-b1).

#### EP-B1 API documentation

**File: `docs/reference/api.md`**

Insert the following paragraphs immediately before `## Naming conventions`.
If the paragraphs are already present, replace them rather than duplicating them.

```markdown
`plan()` and `expand()` default to `reproducibility="reproducible"`. Pass
`reproducibility="relaxed"` to permit nondeterministic algorithms while preserving
precision, or pass a `ReproducibilitySpec` for custom settings. Either preset
accepts a separate `parallelism=ParallelismSpec(...)`; custom settings already
contain their parallelism. Both types are defined in
[`viper.runtime`](../../src/viper/runtime.py).

The returned draft stores the selected mode in `execution_policy` and concrete
settings in `reproducibility`. Expansion resolves defaults once for the batch.
Current saved run specifications retain the concrete settings; policy
mode/version persistence is pending in the
[execution-policy contract](../development/execution-policy-contract.md).
```

**Stop:** Review these changes and run the following commands before changing
EP-B2 implementation files. Report a failing check before proceeding.

```bash
source .venv/bin/activate
python -m pytest -q tests/test_authoring.py -k execution_policy
python -m ruff check src/viper/authoring.py tests/test_authoring.py
python -m pyright src/viper/authoring.py tests/test_authoring.py
```

Recorded validation for `50ac550`: all 20 authoring tests passed; 14 execution/plan
compatibility tests passed with 2 skips; 15 documentation tests passed. Ruff and
Pyright passed. Those are Codex-run checks from implementation, not user-reported
results. The code blocks above reproduce the current declarations exactly.

### EP-B2a: Require policy identity in saved plans

- Requirement: EP-02; dependency: completed EP-B1 / EP-01.
- Targets: the two production modules and nine test files listed below.
- Baseline: `defaf213e451040fbfc59d9c20a1c9f53566e4d4`, including correction of
  the partially applied compatibility edit in `src/viper/runs.py`.
- Focused test: `python -m pytest -q tests/test_authoring.py -k policy_persistence`.
- Gate: all checks below pass after you apply the complete block.

**Context:** The library is unreleased. Make policy identity required in both the
draft and saved run, copy it during compilation, and update development fixtures.
Do not maintain readers or defaults for earlier draft shapes. This block replaces
the withdrawn dual-version proposal in full.

Records without the required `execution_policy` field must be regenerated.
The two version fields are explained once in [Models](#4-models).

#### EP-B2a schema and writer code

**File: `src/viper/runs.py`**

Replace the `.runtime` import and the complete `RunSpec` class with the declarations below. This replaces any partially applied `Literal[2, 3]`, optional policy field, or compatibility validator from the withdrawn block.

```python
from .runtime import EnvSpec, ExecutionPolicyRef, ReproducibilitySpec


class RunSpec(ProtocolModel):
    """Freeze one run plan and its ordered stage specifications."""

    schema_version: Literal[2] = 2
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    benchmark_id: BenchmarkId | None = None

    seed: RNGSeed
    source: GitSource
    env: EnvSpec
    reproducibility: ReproducibilitySpec
    execution_policy: ExecutionPolicyRef = Field(
        description="Mode and preset version selected when authoring this run.",
    )
```

**File: `src/viper/authoring.py`**

Replace the complete `RunPlanDraft` class. Inside `_compile_plan()`, replace the `run = RunSpec(...)` assignment with the complete assignment below, retaining its indentation inside that function. Existing imports supply all names.

```python
class RunPlanDraft(BaseModel):
    """Select one immutable experiment variant and replicate for execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    run_id: RunId
    experiment: ExperimentDraft
    variant: VariantId
    replicate: ReplicateId
    benchmark: BenchmarkDraft | None = None
    source: GitSource
    env: EnvSpec
    reproducibility: ReproducibilitySpec
    execution_policy: ExecutionPolicyRef = Field(
        description="Mode and preset version selected when authoring this run.",
    )


run = RunSpec(
    run_id=draft.run_id,
    experiment_id=experiment_draft.experiment_id,
    variant_id=draft.variant,
    replicate_id=draft.replicate,
    benchmark_id=(None if benchmark_spec is None else benchmark_spec.benchmark_id),
    seed=replicate_draft.seed,
    source=draft.source,
    env=draft.env,
    reproducibility=draft.reproducibility,
    execution_policy=draft.execution_policy,
    stages=tuple(stage_refs),
    estimator=StageArtifactRef(
        stage_id=estimator_stage,
        artifact_name=variant_draft.estimator.output_name,
    ),
)
```

Tests and acceptance commands: [EP-VB2a](#ep-vb2a-verification-of-ep-b2a).

### EP-B2b: Check policy identity against saved settings

Requirement: EP-02. Dependency: applied and checked EP-B2a.
Status: implemented.
Targets: [runtime.py](../../src/viper/runtime.py),
[runs.py](../../src/viper/runs.py), and
[test_authoring.py](../../tests/test_authoring.py).

**Context:** A saved run labelled `reproducible` must contain the reproducible
preset's numerical settings. This check rejects a relaxed run relabelled
`reproducible` and accepts independently selected parallelism. Reloading uses
the saved settings. Custom
settings retain their existing schema validation.

#### EP-B2b runtime code

**File: `src/viper/runtime.py`**

Replace `resolve_execution_policy` with the function below and the two following
helpers. Keep the surrounding declarations in place. `_preset_settings` supplies
both authoring and validation with the same preset definition.

```python
def resolve_execution_policy(
    selection: Literal["reproducible", "relaxed"] | ReproducibilitySpec = (
        "reproducible"
    ),
    *,
    parallelism: ParallelismSpec | None = None,
) -> tuple[ExecutionPolicyRef, ReproducibilitySpec]:
    """Return policy identity and validated settings without changing the runtime.

    Explicit settings select custom, even when their values equal a preset.
    Revalidate and copy those settings so caller-owned mappings remain separate.
    Presets accept parallelism independently of numerical controls. Relaxed
    defaults retain the authoring process's configured Torch thread counts;
    callers supply DataLoader worker settings for their workload.
    """
    if isinstance(selection, ReproducibilitySpec):
        if parallelism is not None:
            raise ValueError("custom settings already include parallelism")
        settings = ReproducibilitySpec.model_validate(selection.model_dump())
        return ExecutionPolicyRef(mode="custom"), settings
    if selection not in {"reproducible", "relaxed"}:
        raise ValueError("execution policy must be reproducible, relaxed, or a spec")

    deterministic = selection == "reproducible"
    if parallelism is None:
        parallelism = ParallelismSpec(
            process_count=1,
            torch_intraop_threads=1 if deterministic else torch.get_num_threads(),
            torch_interop_threads=(
                1 if deterministic else torch.get_num_interop_threads()
            ),
            dataloader=DataLoaderConfiguration(workers=0),
        )
    parallelism = ParallelismSpec.model_validate(parallelism.model_dump())
    return ExecutionPolicyRef(mode=selection), _preset_settings(selection, parallelism)


def _preset_settings(
    mode: Literal["reproducible", "relaxed"], parallelism: ParallelismSpec
) -> ReproducibilitySpec:
    """Build numerical settings for the current policy definition, version 1."""
    deterministic = mode == "reproducible"
    return ReproducibilitySpec(
        determinism=TorchDeterminismSpec(
            deterministic_algorithms=deterministic,
            deterministic_warn_only=False,
            cudnn_deterministic=deterministic,
            cudnn_benchmark=not deterministic,
            cublas_workspace_config=":4096:8" if deterministic else None,
        ),
        precision=TorchPrecisionSpec(
            float32_matmul_precision="highest",
            cudnn_allow_tf32=False,
            autocast_enabled=False,
            autocast_dtype=None,
        ),
        parallelism=parallelism,
        numpy_randomness=NumPyRandomnessSpec(
            generators={},
            capture_legacy_global=True,
        ),
    )


def validate_execution_policy(
    policy: ExecutionPolicyRef, settings: ReproducibilitySpec
) -> None:
    """Reject a preset label whose saved numerical settings differ from that preset."""
    if policy.mode == "custom":
        return
    # Parallelism is independent of the numerical preset and is already frozen.
    expected = _preset_settings(policy.mode, settings.parallelism)
    if settings.model_dump(exclude={"parallelism"}) != expected.model_dump(
        exclude={"parallelism"}
    ):
        raise ValueError("execution policy differs from saved numerical settings")
```

#### EP-B2b run validation code

**File: `src/viper/runs.py`**

Replace the `.runtime` import with this import group. Inside `RunSpec`, replace
`validate_common_invariants` with the function below, indented as a class method.

```python
from .runtime import (
    EnvSpec,
    ExecutionPolicyRef,
    ReproducibilitySpec,
    validate_execution_policy,
)

@model_validator(mode="after")
def validate_common_invariants(self) -> RunSpec:
    """Enforce ordered-stage identity and estimator selection invariants."""
    validate_execution_policy(self.execution_policy, self.reproducibility)
    stage_ids = tuple(stage.stage_id for stage in self.stages)
    if len(set(stage_ids)) != len(stage_ids):
        raise ValueError("stage IDs must be unique")

    stage_spec_paths = tuple(stage.spec for stage in self.stages)
    if len(set(stage_spec_paths)) != len(stage_spec_paths):
        raise ValueError("stage spec paths must be unique")

    run_root = (
        f"experiments/{self.experiment_id}/runs/{self.variant_id}/{self.run_id}"
    )
    for stage in self.stages:
        expected_path = f"{run_root}/stages/{stage.stage_id}/spec.yaml"
        if stage.spec != expected_path:
            raise ValueError(
                f"stage {stage.stage_id!r} spec must use its canonical run path"
            )

    if self.estimator.stage_id not in set(stage_ids):
        raise ValueError("estimator must select a declared run stage")

    if self.estimator.artifact_name != keys.Train.MODEL:
        raise ValueError("estimator must select the model artifact")

    return self
```

Tests and acceptance commands: [EP-VB2b](#ep-vb2b-verification-of-ep-b2b).

### EP-B3: Record active worker controls

Requirement: EP-03. Dependency: EP-B2b. Gate: EP-VB3.
Targets: `src/viper/runtime.py`, both modules in `src/viper/_workers`,
and `src/viper/execution/_stage.py` and `_metric.py`.

Context: Workers currently save the requested settings. Add a required record of
PyTorch's active settings inside the autocast context immediately
before calling user code. Clear an inherited cuBLAS workspace setting before
launching either worker, then apply the saved environment.

#### EP-B3 runtime code

**File: `src/viper/runtime.py`**

Insert `RuntimeControlsReceipt` and `observe_runtime_controls` immediately before
`ProcessStartupReceipt`; replace that existing class with the declaration below.

```python
class RuntimeControlsReceipt(ProtocolModel):
    """Record PyTorch controls read before a worker invokes user code."""

    backend: Literal["cpu", "cuda"] = Field(
        description="Device type used for autocast queries and backend-specific checks."
    )
    deterministic_algorithms: bool = Field(
        description="Whether PyTorch required deterministic algorithms at invocation."
    )
    deterministic_warn_only: bool = Field(
        description="Whether unsupported deterministic operations warn at invocation."
    )
    cudnn_deterministic: bool = Field(
        description="Observed cuDNN determinism setting, checked for CUDA workers."
    )
    cudnn_benchmark: bool = Field(
        description="Observed cuDNN benchmarking setting, checked for CUDA workers."
    )
    cudnn_allow_tf32: bool = Field(
        description="Observed cuDNN TF32 permission, checked for CUDA workers."
    )
    float32_matmul_precision: Literal["highest", "high", "medium"] = Field(
        description="Observed internal precision for float32 matrix multiplication."
    )
    torch_intraop_threads: int = Field(
        ge=1, description="Observed CPU thread count used within a PyTorch operation."
    )
    torch_interop_threads: int = Field(
        ge=1, description="Observed CPU thread count used across PyTorch operations."
    )
    autocast_enabled: bool = Field(
        description="Whether autocast was enabled in the user call context."
    )
    autocast_dtype: Literal["float16", "bfloat16"] | None = Field(
        description="Autocast dtype at invocation; None when autocast was disabled."
    )


def observe_runtime_controls(
    backend: Literal["cpu", "cuda"],
) -> RuntimeControlsReceipt:
    """Read controls inside the autocast context used for the invocation."""
    enabled = torch.is_autocast_enabled(backend)
    # A configured dtype has no effect while autocast is disabled.
    dtype: Literal["float16", "bfloat16"] | None = None
    if enabled:
        active_dtype = torch.get_autocast_dtype(backend)
        if active_dtype == torch.float16:
            dtype = "float16"
        elif active_dtype == torch.bfloat16:
            dtype = "bfloat16"
        else:
            raise ValueError("startup.controls: unsupported autocast dtype")
    precision = torch.get_float32_matmul_precision()
    if precision not in ("highest", "high", "medium"):
        raise ValueError("startup.controls: unsupported matmul precision")
    return RuntimeControlsReceipt(
        backend=backend,
        deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
        deterministic_warn_only=torch.is_deterministic_algorithms_warn_only_enabled(),
        cudnn_deterministic=torch.backends.cudnn.deterministic,
        cudnn_benchmark=torch.backends.cudnn.benchmark,
        cudnn_allow_tf32=torch.backends.cudnn.allow_tf32,
        float32_matmul_precision=precision,
        torch_intraop_threads=torch.get_num_threads(),
        torch_interop_threads=torch.get_num_interop_threads(),
        autocast_enabled=enabled,
        autocast_dtype=dtype,
    )


class ProcessStartupReceipt(ProtocolModel):
    """Record the startup env, applied controls, and seeded generators."""

    env: dict[StartupVariable, str] = Field(
        description="Allowlisted process environment read before the user call."
    )
    observed_controls: RuntimeControlsReceipt = Field(
        description="PyTorch settings read inside the context used for the user call."
    )
    reproducibility: ReproducibilitySpec = Field(
        description="Requested run settings, retained alongside independent readings."
    )
    generators: tuple[GeneratorInitializationReceipt, ...] = Field(
        description="Seeds and initial-state identities recorded at initialization."
    )
```

Replace `RuntimeInitialization` with this declaration. Initialization returns
live generators and their seed records; the worker constructs the startup receipt
when it is ready to invoke user code.

```python
@dataclass(frozen=True)
class RuntimeInitialization:
    """Return live NumPy generators and records of their initialization."""

    numpy_generators: dict[str, np.random.Generator]
    generators: tuple[GeneratorInitializationReceipt, ...]
```

In `apply_reproducibility`, replace the final return statement with the following
statement. If you applied the earlier proposal, also remove its preceding
`backend = ...` assignment and `with autocast_context(...)` reading.

```python
return RuntimeInitialization(
    numpy_generators=named_generators,
    generators=tuple(receipts),
)
```

Add this function immediately after `apply_reproducibility`. It constructs the
complete receipt from the initialization records and the current readings.

```python
def observe_process_startup(
    initialization: RuntimeInitialization,
    reproducibility: ReproducibilitySpec,
    backend: Literal["cpu", "cuda"],
) -> ProcessStartupReceipt:
    """Read active settings and construct the receipt saved with the worker result.

    Call inside the worker's autocast context immediately before user code.
    Generator records describe initialization; controls describe invocation.
    """
    return ProcessStartupReceipt(
        env=_startup_environment(),
        reproducibility=reproducibility,
        generators=initialization.generators,
        observed_controls=observe_runtime_controls(backend),
    )
```

Replace `autocast_context` with:

```python
def autocast_context(
    reproducibility: ReproducibilitySpec,
    *,
    backend: Literal["cpu", "cuda"] | None = None,
) -> Any:
    """Construct the autocast context for the selected worker backend."""
    precision = reproducibility.precision
    device_type = backend or ("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.float16 if precision.autocast_dtype == "float16" else torch.bfloat16
    return torch.autocast(
        device_type=device_type,
        dtype=dtype,
        enabled=precision.autocast_enabled,
    )
```

**File: `src/viper/_workers/stages.py`**

Remove `from dataclasses import replace` if present. Replace the `..runtime`
import group with the following group. In `main`, replace the complete
`with autocast_context(...)` statement with the following statement, retaining
its indentation inside `try`.

```python
from ..runtime import (
    ProcessStartupReceipt,
    apply_reproducibility,
    autocast_context,
    observe_execution,
    observe_process_startup,
    observe_python_env,
)

with autocast_context(
    run.reproducibility, backend=effective_environment.compute.kind
):
    # StageWorkerResult saves this receipt after the call, including failures.
    startup = observe_process_startup(
        initialization, run.reproducibility, effective_environment.compute.kind
    )
    function(context)
```

Immediately before the existing `initialization = None` statement, insert:

```python
startup: ProcessStartupReceipt | None = None
```

In both `StageWorkerResult(...)` calls, replace the `startup` argument with
`startup=startup`. Before the success-path `assert initialization is not None`,
insert `assert startup is not None`.

A failure before capture returns `startup=None`. A failure after capture retains
the receipt of the settings under which the user function was invoked.

**File: `src/viper/_workers/metrics.py`**

Remove `from dataclasses import replace` if present. Replace the `..runtime`
import group with the following group. In `main`, replace the complete
`with autocast_context(...)` statement with the following statement, retaining
its indentation inside `try`.

```python
from ..runtime import (
    apply_reproducibility,
    autocast_context,
    observe_execution,
    observe_process_startup,
    observe_python_env,
)

with autocast_context(
    context.run.reproducibility, backend=effective_environment.compute.kind
):
    # MetricExecutionReceipt saves these readings with the computed value.
    startup = observe_process_startup(
        initialization,
        context.run.reproducibility,
        effective_environment.compute.kind,
    )
    value = float(
        callable_metric(
            MetricContext(
                inputs=input_paths,
                artifacts=artifact_paths,
                config=context.metric.config,
            )
        )
    )
```

In `MetricExecutionReceipt(...)`, replace `startup=initialization.receipt` with
`startup=startup`. Its existing exception path continues to report failures.

**File: `src/viper/execution/_stage.py`**

Replace the single `env = os.environ.copy()` statement with these two statements.
The following existing `process_environment(...)` call installs a saved value
when the plan specifies one.

```python
env = os.environ.copy()
# The parent may have strict settings while this run requests relaxed settings.
env.pop("CUBLAS_WORKSPACE_CONFIG", None)
```

**File: `src/viper/execution/_metric.py`**

Replace the single `env = os.environ.copy()` statement with these two statements.
The following existing `process_environment(...)` call installs a saved value
when the plan specifies one.

```python
env = os.environ.copy()
# The parent may have strict settings while this run requests relaxed settings.
env.pop("CUBLAS_WORKSPACE_CONFIG", None)
```

Apply these edits with the receipt updates in EP-VB3, then apply EP-B4.
The two production blocks form one runtime increment; run their verification
blocks after both are present.

### EP-B4: Enforce worker observations in the verifier

Requirement: EP-04. Dependency: EP-B3 code applied. Gate: EP-VB4.
Targets: `src/viper/_verification/runtime.py`, `src/viper/_verification/attempt.py`,
`src/viper/_verification/metrics.py`, and `src/viper/reuse.py`.

Context: The production verifier must compare recorded readings with the saved
run. This block adds that comparison to both stage and metric verification.
The comparison uses each run's concrete settings, so matching relaxed readings
pass. The existing reuse route verifies the producing run and its startup record.

#### EP-B4 comparison code

**File: `src/viper/_verification/runtime.py`**

Create this module. It raises `ValueError`; the two public verification paths
translate that failure to their existing `VerificationError`.

```python
"""Compare worker control readings with the saved run settings."""

from ..runtime import ReproducibilitySpec, RuntimeControlsReceipt


def verify_runtime_controls(
    observed: RuntimeControlsReceipt,
    settings: ReproducibilitySpec,
    backend: str,
) -> None:
    """Compare saved readings with planned settings and raise ValueError on mismatch.

    Read only the supplied records; leave the active PyTorch settings unchanged.
    Stage and metric verifiers translate failures to VerificationError.
    """
    if observed.backend != backend:
        raise ValueError("startup.controls: backend differs from the plan")
    # Compare the worker readings with the saved run, including relaxed values.
    expected: dict[str, object] = {
        "deterministic_algorithms": settings.determinism.deterministic_algorithms,
        "deterministic_warn_only": settings.determinism.deterministic_warn_only,
        "float32_matmul_precision": settings.precision.float32_matmul_precision,
        "torch_intraop_threads": settings.parallelism.torch_intraop_threads,
        "torch_interop_threads": settings.parallelism.torch_interop_threads,
        "autocast_enabled": settings.precision.autocast_enabled,
        "autocast_dtype": (
            settings.precision.autocast_dtype
            if settings.precision.autocast_enabled
            else None
        ),
    }
    # cuDNN controls GPU operations. Include these expected values only for
    # CUDA verification; this dictionary update leaves PyTorch state unchanged.
    if backend == "cuda":
        expected.update(
            cudnn_deterministic=settings.determinism.cudnn_deterministic,
            cudnn_benchmark=settings.determinism.cudnn_benchmark,
            cudnn_allow_tf32=settings.precision.cudnn_allow_tf32,
        )
    readings = observed.model_dump()
    for field, value in expected.items():
        if readings[field] != value:
            raise ValueError(f"startup.controls: {field} differs from the plan")
```

**File: `src/viper/_verification/attempt.py`**

Add this module-scope import:

```python
from .runtime import verify_runtime_controls
```

After the existing `compute = (stage.env or run.env).compute` statement in the
startup-verification function, insert the following statements. Preserve the
existing requested-settings, environment, backend, and generator checks.

```python
try:
    verify_runtime_controls(
        startup.observed_controls, run.reproducibility, compute.kind
    )
except ValueError as exc:
    raise VerificationError(str(exc)) from exc
```

**File: `src/viper/_verification/metrics.py`**

Add this module-scope import:

```python
from .runtime import verify_runtime_controls
```

After the existing `compute = (stage.env or run.env).compute` statement in the
startup-verification function, insert the following statements. Preserve the
existing requested-settings, environment, backend, and generator checks.

```python
try:
    verify_runtime_controls(
        startup.observed_controls, run.reproducibility, compute.kind
    )
except ValueError as exc:
    raise VerificationError(str(exc)) from exc
```

Reuse disposition: retain the producing-run traversal in
[verification.py](../../src/viper/verification.py). It calls the
stage and metric verification paths above for the source evidence. A reused stage
keeps its producer's readings; it receives no fabricated new startup receipt.

**File: `src/viper/reuse.py`**

Replace `verified_input_identity` with this function. A single-file input keeps
its filename because `path.relative_to(root)` would otherwise produce `.`.

```python
def verified_input_identity(
    input_name: InputName,
    value: _VerifiedInput,
) -> ReuseInputIdentity:
    """Build one reuse identity from input bytes already accepted by verification."""
    files = []
    for file in value.files:
        path = Path(file.reference.path)
        root = Path(value.path)
        # A single-file input uses its filename; relative_to would produce ".".
        if path == root:
            relative = path.name
        else:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = path.name
        files.append(
            ReuseFileIdentity(
                relative_path=relative,
                sha256=file.reference.sha256,
                bytes=file.reference.bytes,
            )
        )
    return ReuseInputIdentity(
        input_name=input_name,
        data_role=value.data_role,
        files=tuple(sorted(files, key=lambda item: item.relative_path)),
    )
```

#### Test EP-B4

First apply the [EP-VB3 test setup](#ep-vb3-verify-worker-control-recording):
create `tests/test_execution_policy_controls.py`, register it in `tests/conftest.py`,
and update the startup-receipt builders. Those tests consume the required fields
introduced by EP-B3.

From the repository root, run:

```bash
source .venv/bin/activate
python -m ruff check src/viper/_verification/runtime.py src/viper/_verification/attempt.py src/viper/_verification/metrics.py
python -m pyright src/viper/_verification/runtime.py src/viper/_verification/attempt.py src/viper/_verification/metrics.py
python -m pytest -q tests/test_execution_policy_controls.py tests/test_process_startup.py tests/test_verification.py tests/test_verification_acceptance.py tests/test_benchmark_execution.py
```

Require both static checks and every selected test to pass. A missing test file
means the test setup above is incomplete. A failure means stop here and inspect
its traceback.

The [EP-VB4 acceptance cases](#ep-vb4-verify-saved-runs-and-reuse) additionally
require tampered persisted stage, metric, and reused-producer records. Those cases
must be implemented and pass before marking EP-B4 complete. After verification,
continue to [EP-B5](#ep-b5-example-code).


### EP-B5: Publish complete policy examples

Requirement: EP-05. Dependency: EP-B4. Gate: EP-VB5.
Targets: `src/viper/repository.py`, `src/viper/execution/__init__.py`,
`examples/cpu_quickstart.py`, new `examples/execution_policies.py`, `README.md`,
`docs/tutorials/getting-started.md`, `docs/reference/api.md`,
`docs/how-to/execution.md`, and `docs/how-to/variants-and-replicates.md`.

Context: VIPER discovers the workspace and reads its committed source. The default
example selects reproducible execution by omitting the policy argument. The policy
example selects relaxed or custom execution around the same training experiment.
Both entry points have parameterless `main()` functions.

#### EP-B5 public source and execution code

**File: `src/viper/repository.py`**

Add this module-level import:

```python
from .references import GitSource
```

Insert this function immediately after `resolve_root`:

```python
def read_source(root: Path | None = None, *, remote: str = "origin") -> GitSource:
    """Read the checked-out commit and HTTP(S) URL of the selected Git remote.

    Return the committed source identity used by plans. Raise RootError when
    the workspace, HEAD, or remote is unavailable. GitSource validates the URL.
    """
    repository_root = resolve_root(root)
    try:
        commit = subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        repository = subprocess.run(
            ("git", "-C", str(repository_root), "remote", "get-url", remote),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RootError(
            "cannot read the committed source and selected Git remote"
        ) from exc
    return GitSource.model_validate({"repository": repository, "commit": commit})
```

In the generated runner returned by `workspace_files`, replace the call
`return execution.run(root, draft)` with:

```python
return execution.run(draft, repository_root=root)
```

**File: `src/viper/execution/__init__.py`**

Add this module-level import:

```python
from ..repository import resolve_root
```

Replace `run` with this complete function:

```python
def run(
    plan: RunPlanDraft | Path,
    *,
    repository_root: Path | None = None,
    timeout_seconds: float | None = None,
    cloud_client: ViperCloudClient | None = None,
) -> RunResult:
    """Execute a Python draft or a saved run specification.

    Discover the workspace from the current directory unless a root is supplied.
    A draft is frozen before execution; a Path selects an existing RunSpec.
    Return a verified RunResult with direct status and path attributes.
    Execution and verification failures raise and leave attempt evidence for
    inspection. timeout_seconds bounds each stage or metric worker invocation.
    """
    repository_root = resolve_root(repository_root)
    if isinstance(plan, Path):
        return _run(
            repository_root,
            plan,
            timeout_seconds=timeout_seconds,
            cloud_client=cloud_client,
        )
    frozen = freeze_run_plan(
        repository_root,
        plan,
        cloud_client=cloud_client,
    )
    run_path = repository_root.resolve() / frozen.reference.stored_at.path
    return _run(
        repository_root,
        run_path,
        plan=frozen.reference,
        timeout_seconds=timeout_seconds,
        cloud_client=cloud_client,
    )
```

`read_source()` searches upward from the current directory for `viper.toml`,
checks its Git work-tree boundary, and reads HEAD and the selected remote.
`execution.run(draft)` uses the same workspace discovery. An explicit location
uses `read_source(root)` and `execution.run(draft, repository_root=root)`.

#### EP-B5 example code

**File: `examples/cpu_quickstart.py`**

Replace the file with this complete program:

```python
"""Run one complete VIPER training plan on the local CPU."""

from __future__ import annotations

import json
from pathlib import Path

from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, measure, metric, min
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng
from viper.references import GitFileRef
from viper.repository import read_source
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    """Load one model or checkpoint written by the training stage."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> ResumeState:
    """Load and validate the terminal training state."""
    return load_resume_state(path)


@metric(metric_id="mean_squared_error", mode="stateless")
def mean_squared_error(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    """Compute mean squared error over matching predictions and targets."""
    if not targets:
        raise ValueError("mean_squared_error requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)


@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    """Fit ``y = weight * x`` with gradient descent on the local CPU."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"]
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    targets = tuple(y for _, y in rows)
    weight = 0.0
    loss = 0.0
    epoch = 0
    for epoch in range(1, 21):
        predictions = tuple(weight * x for x, _ in rows)
        measurement = context.metrics["mean_squared_error"].record(
            predictions, targets, epoch=epoch, step=epoch
        )
        loss = measurement.value
        errors = tuple(
            prediction - target for prediction, target in zip(predictions, targets)
        )
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient

    model = context.outputs["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    save_resume_state(
        context.outputs["resume_state"],
        ResumeState(
            optimizer_state={"weight": weight, "loss": loss},
            main_process_rng=capture_main_process_rng(
                context.numpy_generators,
                capture_legacy_global=True,
            ),
            dataloader=DataLoaderResumeState(
                configuration=DataLoaderConfiguration(workers=0),
                state_dict={"epoch": epoch},
            ),
        ),
    )


mse = measure(mean_squared_error, config=MetricConfig())
training = stage(
    fit,
    config=TrainConfig(),
    inputs={
        "dataset": input(
            "examples/data/tiny.csv",
            data_role="training",
        )
    },
    outputs=TrainOutputs(
        model=output(
            path="model.json",
            loader=load_json,
            data_role="training",
        ),
        resume_state=output(
            path="resume_state.pt",
            loader=load_state,
            data_role="training",
        ),
    ),
    metrics=(mse,),
    objective=min(mse),
)
study = experiment(
    experiment_id="cpu_quickstart",
    variants={
        "baseline": variant(
            levels={},
            stages={"train": training},
            estimator=training.outputs["model"],
        )
    },
    replicates={"seed_7": replicate(seed=7)},
)


def main() -> None:
    """Run the training experiment with the default reproducible policy."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
    )
    resolved_run = execution.run(draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")


if __name__ == "__main__":
    main()
```

**File: `examples/execution_policies.py`**

Replace the file with this complete program:

```python
"""Run the complete CPU example with a selected execution policy."""

from argparse import ArgumentParser

from cpu_quickstart import study

from viper import execution
from viper.authoring import plan
from viper.references import GitFileRef
from viper.repository import read_source
from viper.resume import DataLoaderConfiguration
from viper.runtime import (
    LocalEnvSpec,
    NumPyRandomnessSpec,
    ParallelismSpec,
    ReproducibilitySpec,
    TorchDeterminismSpec,
    TorchPrecisionSpec,
    observe_python_env,
)


def main() -> None:
    """Select a policy, create its plan, and execute the training experiment."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("policy", choices=("reproducible", "relaxed", "custom"))
    arguments = parser.parse_args()
    selection = arguments.policy
    if selection == "custom":
        selection = ReproducibilitySpec(
            determinism=TorchDeterminismSpec(
                deterministic_algorithms=False,
                deterministic_warn_only=False,
                cudnn_deterministic=False,
                cudnn_benchmark=True,
                cublas_workspace_config=None,
            ),
            precision=TorchPrecisionSpec(
                float32_matmul_precision="highest",
                cudnn_allow_tf32=False,
                autocast_enabled=False,
                autocast_dtype=None,
            ),
            parallelism=ParallelismSpec(
                process_count=1,
                torch_intraop_threads=2,
                torch_interop_threads=1,
                dataloader=DataLoaderConfiguration(workers=0),
            ),
            numpy_randomness=NumPyRandomnessSpec(
                generators={},
                capture_legacy_global=True,
            ),
        )

    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
        reproducibility=selection,
    )
    resolved_run = execution.run(draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")


if __name__ == "__main__":
    main()
```

#### EP-B5 documentation edits

**File: `README.md`**

Replace the section beginning `## Follow the execution` and ending immediately before
`## What the run preserves` with:

````markdown
## Follow the execution

The following blocks form the complete [CPU quickstart](examples/cpu_quickstart.py).
Save them together as `examples/cpu_quickstart.py`, commit the file, and run it.

### Define the metric and training stage

```python
"""Run one complete VIPER training plan on the local CPU."""

from __future__ import annotations

import json
from pathlib import Path

from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, measure, metric, min
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng
from viper.references import GitFileRef
from viper.repository import read_source
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    """Load one model or checkpoint written by the training stage."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> ResumeState:
    """Load and validate the terminal training state."""
    return load_resume_state(path)


@metric(metric_id="mean_squared_error", mode="stateless")
def mean_squared_error(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    """Compute mean squared error over matching predictions and targets."""
    if not targets:
        raise ValueError("mean_squared_error requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)

@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    """Fit ``y = weight * x`` with gradient descent on the local CPU."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"]
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    targets = tuple(y for _, y in rows)
    weight = 0.0
    loss = 0.0
    epoch = 0
    for epoch in range(1, 21):
        predictions = tuple(weight * x for x, _ in rows)
        measurement = context.metrics["mean_squared_error"].record(
            predictions, targets, epoch=epoch, step=epoch
        )
        loss = measurement.value
        errors = tuple(
            prediction - target for prediction, target in zip(predictions, targets)
        )
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient

    model = context.outputs["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    save_resume_state(
        context.outputs["resume_state"],
        ResumeState(
            optimizer_state={"weight": weight, "loss": loss},
            main_process_rng=capture_main_process_rng(
                context.numpy_generators,
                capture_legacy_global=True,
            ),
            dataloader=DataLoaderResumeState(
                configuration=DataLoaderConfiguration(workers=0),
                state_dict={"epoch": epoch},
            ),
        ),
    )
```

### Declare the experiment

```python
mse = measure(mean_squared_error, config=MetricConfig())
training = stage(
    fit,
    config=TrainConfig(),
    inputs={
        "dataset": input(
            "examples/data/tiny.csv",
            data_role="training",
        )
    },
    outputs=TrainOutputs(
        model=output(
            path="model.json",
            loader=load_json,
            data_role="training",
        ),
        resume_state=output(
            path="resume_state.pt",
            loader=load_state,
            data_role="training",
        ),
    ),
    metrics=(mse,),
    objective=min(mse),
)
study = experiment(
    experiment_id="cpu_quickstart",
    variants={
        "baseline": variant(
            levels={},
            stages={"train": training},
            estimator=training.outputs["model"],
        )
    },
    replicates={"seed_7": replicate(seed=7)},
)
```

### Run the experiment

`read_source()` identifies the checked-out commit and repository URL.
`plan()` uses the reproducible policy by default.

```python
def main() -> None:
    """Run the training experiment with the default reproducible policy."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
    )
    resolved_run = execution.run(draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")


if __name__ == "__main__":
    main()
```

The complete policy example (`examples/execution_policies.py`) runs the same
experiment with `reproducible`, `relaxed`, or `custom` settings. Relaxed permits
nondeterministic algorithms. Verification checks each run against its own plan;
comparing artifacts from two runs is a separate operation.
````

**File: `docs/tutorials/getting-started.md`**

Replace the section beginning `## Read the complete program` and ending immediately before
`## Inspect the result` with:

````markdown
## Read the complete program

These four blocks form [cpu_quickstart.py](../../examples/cpu_quickstart.py).
The stage fits a linear model and records mean squared error from predictions
and targets.

### 1. Define the metric and output loaders

```python
"""Run one complete VIPER training plan on the local CPU."""

from __future__ import annotations

import json
from pathlib import Path

from viper import execution
from viper.authoring import experiment, input, plan, replicate, stage, variant
from viper.config import MetricConfig, TrainConfig
from viper.metrics import MetricContext, measure, metric, min
from viper.outputs import TrainOutputs, output
from viper.randomness import capture_main_process_rng
from viper.references import GitFileRef
from viper.repository import read_source
from viper.resume import (
    DataLoaderConfiguration,
    DataLoaderResumeState,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from viper.runtime import LocalEnvSpec, observe_python_env
from viper.stages import Context, train


def load_json(path: Path) -> dict[str, float | int]:
    """Load one model or checkpoint written by the training stage."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> ResumeState:
    """Load and validate the terminal training state."""
    return load_resume_state(path)


@metric(metric_id="mean_squared_error", mode="stateless")
def mean_squared_error(
    _context: MetricContext[MetricConfig],
    predictions: tuple[float, ...],
    targets: tuple[float, ...],
) -> float:
    """Compute mean squared error over matching predictions and targets."""
    if not targets:
        raise ValueError("mean_squared_error requires at least one target")
    return sum(
        (prediction - target) ** 2
        for prediction, target in zip(predictions, targets, strict=True)
    ) / len(targets)
```

### 2. Train the model and write its outputs

```python
@train(config=TrainConfig)
def fit(context: Context[TrainConfig]) -> None:
    """Fit ``y = weight * x`` with gradient descent on the local CPU."""
    rows = [
        tuple(float(value) for value in line.split(","))
        for line in context.inputs["dataset"]
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    targets = tuple(y for _, y in rows)
    weight = 0.0
    loss = 0.0
    epoch = 0
    for epoch in range(1, 21):
        predictions = tuple(weight * x for x, _ in rows)
        measurement = context.metrics["mean_squared_error"].record(
            predictions, targets, epoch=epoch, step=epoch
        )
        loss = measurement.value
        errors = tuple(
            prediction - target for prediction, target in zip(predictions, targets)
        )
        gradient = 2 * sum(error * x for error, (x, _) in zip(errors, rows)) / len(rows)
        weight -= 0.05 * gradient

    model = context.outputs["model"]
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"weight": weight}) + "\n", encoding="utf-8")
    save_resume_state(
        context.outputs["resume_state"],
        ResumeState(
            optimizer_state={"weight": weight, "loss": loss},
            main_process_rng=capture_main_process_rng(
                context.numpy_generators,
                capture_legacy_global=True,
            ),
            dataloader=DataLoaderResumeState(
                configuration=DataLoaderConfiguration(workers=0),
                state_dict={"epoch": epoch},
            ),
        ),
    )
```

### 3. Declare the experiment

```python
mse = measure(mean_squared_error, config=MetricConfig())
training = stage(
    fit,
    config=TrainConfig(),
    inputs={
        "dataset": input(
            "examples/data/tiny.csv",
            data_role="training",
        )
    },
    outputs=TrainOutputs(
        model=output(
            path="model.json",
            loader=load_json,
            data_role="training",
        ),
        resume_state=output(
            path="resume_state.pt",
            loader=load_state,
            data_role="training",
        ),
    ),
    metrics=(mse,),
    objective=min(mse),
)
study = experiment(
    experiment_id="cpu_quickstart",
    variants={
        "baseline": variant(
            levels={},
            stages={"train": training},
            estimator=training.outputs["model"],
        )
    },
    replicates={"seed_7": replicate(seed=7)},
)
```

### 4. Identify the source and run the experiment

`read_source()` returns the checked-out commit and the `origin` repository URL.
Omitting `reproducibility` selects reproducible execution.

```python
def main() -> None:
    """Run the training experiment with the default reproducible policy."""
    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_7",
        source=source,
        env=environment,
    )
    resolved_run = execution.run(draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")


if __name__ == "__main__":
    main()
```

Run the [policy example](../../examples/execution_policies.py) to select a policy
for the same training computation:

```bash
python examples/execution_policies.py reproducible
python examples/execution_policies.py relaxed
python examples/execution_policies.py custom
```

Only custom mode constructs the complete numerical settings. Its example uses
two intra-operation CPU threads and permits nondeterministic algorithms.
````

**File: `docs/reference/api.md`**

In “Author and execute an experiment”, import `read_source` from
`viper.repository`, assign `source = read_source()` before `plan`, and use
`execution.run(draft)`. Add this paragraph after the example:

```markdown
`read_source()` returns a `GitSource` containing the checked-out commit and the
HTTP(S) URL of `origin`. It discovers the workspace from the current directory.
Select another remote with `read_source(remote="mirror")`, or another workspace
with `read_source(root)`. An unavailable workspace, commit, or remote raises
`RootError`; an invalid source URL fails `GitSource` validation.

`execution.run(draft)` discovers the workspace from the current directory.
Supply `repository_root=root` to execute in another workspace. A saved plan
path can be supplied in place of the draft.

`plan()` defaults to reproducible execution. `reproducibility="relaxed"` permits
nondeterministic algorithms. Pass a `ReproducibilitySpec` for custom settings.
Saved plans retain both the selected policy and its complete settings. Worker
receipts record the controls read from PyTorch immediately before user code.
Verification compares those readings with the saved settings. Comparing artifact
bytes from separate runs is a separate check.
```

In the public-module table, describe `viper.repository` as “Workspace
initialization, source identification, and path resolution”.

**Files: `docs/how-to/execution.md`, `docs/how-to/variants-and-replicates.md`**

Use `execution.run(draft, repository_root=root)` and
`execution.run(plan_path, repository_root=root)` where these guides supply an
explicit workspace root.

Stop after the commands in [EP-VB5](#ep-vb5-verify-public-workflows) pass.

### EP-VB0: Verification of EP-B0

#### EP-B0 test code

**File: `tests/test_runtime_boundary.py`**

Replace the file with the following complete contents. This retains the existing
tests and adds the required imports and execution-policy tests.

```python
"""Acceptance tests for the PAC-10 runtime boundary."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import torch
from pydantic import ValidationError

import viper.metrics as metrics
import viper.stages as stages
from viper.resume import DataLoaderConfiguration
from viper.runtime import ParallelismSpec, ReproducibilitySpec, resolve_execution_policy

PAIR_BLOCK_ID = "P3-PAC-10"
REQUIREMENT_ID = "PAC-10"


def test_runtime_contexts_are_frozen_slotted_dataclasses() -> None:
    """Keep live contexts lightweight while preventing reassignment."""
    for runtime_type in (stages.Context, metrics.MetricContext):
        assert dataclasses.is_dataclass(runtime_type)
        assert getattr(runtime_type, "__dataclass_params__").frozen is True
        assert "__slots__" in runtime_type.__dict__
        assert "model_fields" not in runtime_type.__dict__


def test_runtime_context_rejects_field_reassignment() -> None:
    """Preserve the logical immutability supplied by frozen dataclasses."""
    context = stages.Context.__new__(stages.Context)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        context.stage_id = "other"  # pyright: ignore[reportAttributeAccessIssue]


def _stateful_metric_type(metrics_module: Any) -> type[Any]:
    """Create one valid stateful metric against the runtime module."""

    class TestMetric(metrics_module.StatefulMetric):
        """Accumulate raw values without constructing protocol records."""

        def __init__(self, context: object) -> None:
            del context
            self.total = 0.0

        def update(self, value: Any) -> None:
            """Accept an arbitrary tensor-like value by reference."""
            self.total += float(value)

        def compute(self) -> float:
            """Return the in-memory aggregate."""
            return self.total

    return TestMetric


class _ExplodingSink:
    """Fail if a high-frequency update touches persistence."""

    def append(self, value: float, **kwargs: object) -> object:
        """Reject every attempted durable append."""
        del value, kwargs
        raise AssertionError("MetricHandle.update touched the persistence sink")


def test_metric_update_does_not_validate_or_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward raw batch values only to the in-memory metric state."""

    def reject_measurement(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("MetricHandle.update constructed Measurement")

    monkeypatch.setattr(metrics, "Measurement", reject_measurement)
    handle = metrics.MetricHandle(
        _stateful_metric_type(metrics),
        cast("Any", _ExplodingSink()),
        cast("Any", object()),
    )
    handle.update(2.5)
    assert handle._stateful is not None
    assert getattr(handle._stateful, "total") == 2.5


class _RecordingSink:
    """Record append calls without performing file I/O."""

    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, object]]] = []

    def append(self, value: float, **kwargs: object) -> object:
        """Retain one measurement publication request."""
        self.calls.append((value, kwargs))
        return object()


def test_metric_record_persists_one_measurement() -> None:
    """Publish exactly one measurement at an explicit reporting boundary."""
    sink = _RecordingSink()
    handle = metrics.MetricHandle(
        _stateful_metric_type(metrics), cast("Any", sink), cast("Any", object())
    )
    handle.update(1.25)
    handle.update(2.75)
    handle.record(epoch=2, step=40)
    assert sink.calls == [(4.0, {"epoch": 2, "step": 40})]


def test_measurement_sink_constructs_one_measurement(tmp_path: Path) -> None:
    """Construct exactly one Measurement per append."""
    sink = metrics.MeasurementSink(
        tmp_path / "measurements.jsonl",
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        attempt_id=1,
        stage_id="train",
        metric_id="loss",
    )

    with patch.object(metrics, "Measurement", wraps=metrics.Measurement) as constructor:
        sink.append(0.5)
        constructor.assert_called_once()


def test_measurement_sink_writes_expected_record(tmp_path: Path) -> None:
    """Persist one record with the supplied identity, value, and timestamp."""
    path = tmp_path / "measurements.jsonl"
    measured_at = datetime(2026, 1, 1, tzinfo=UTC)
    sink = metrics.MeasurementSink(
        path,
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        attempt_id=1,
        stage_id="train",
        metric_id="loss",
    )

    returned = sink.append(0.5, measured_at=measured_at, epoch=1)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    saved = metrics.Measurement.model_validate_json(lines[0])
    assert saved == returned
    assert saved.run_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert saved.attempt_id == 1
    assert saved.stage_id == "train"
    assert saved.metric_id == "loss"
    assert saved.value == 0.5
    assert saved.measured_at == measured_at
    assert saved.epoch == 1
    assert saved.step is None


def test_execution_policy_reproducible_default() -> None:
    """Require deterministic operations and conservative default parallelism."""
    policy, settings = resolve_execution_policy()
    assert policy.mode == "reproducible"
    assert policy.version == 1
    assert settings.determinism.model_dump() == {
        "deterministic_algorithms": True,
        "deterministic_warn_only": False,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "cublas_workspace_config": ":4096:8",
    }
    assert settings.parallelism.torch_intraop_threads == 1
    assert settings.parallelism.torch_interop_threads == 1
    assert settings.parallelism.dataloader.workers == 0


def test_execution_policy_relaxed_allows_nondeterminism() -> None:
    """Permit nondeterministic algorithms without reducing numerical precision."""
    _, strict = resolve_execution_policy()
    policy, relaxed = resolve_execution_policy("relaxed")
    assert policy.mode == "relaxed"
    assert relaxed.determinism.model_dump() == {
        "deterministic_algorithms": False,
        "deterministic_warn_only": False,
        "cudnn_deterministic": False,
        "cudnn_benchmark": True,
        "cublas_workspace_config": None,
    }
    assert relaxed.precision == strict.precision
    assert relaxed.precision.float32_matmul_precision == "highest"
    assert relaxed.precision.cudnn_allow_tf32 is False
    assert relaxed.precision.autocast_enabled is False
    assert relaxed.numpy_randomness == strict.numpy_randomness
    assert relaxed.parallelism.torch_intraop_threads == torch.get_num_threads()
    assert (
        relaxed.parallelism.torch_interop_threads == torch.get_num_interop_threads()
    )


@pytest.mark.parametrize("mode", ["reproducible", "relaxed"])
def test_execution_policy_parallelism_is_independent(mode: str) -> None:
    """Allow worker and thread choices without changing the numerical policy."""
    resources = ParallelismSpec(
        process_count=1,
        torch_intraop_threads=4,
        torch_interop_threads=2,
        dataloader=DataLoaderConfiguration(workers=2, prefetch_factor=2),
    )
    policy, settings = resolve_execution_policy(cast(Any, mode), parallelism=resources)
    assert policy.mode == mode
    assert settings.parallelism == resources
    assert settings.parallelism is not resources
    assert settings.determinism.deterministic_algorithms == (mode == "reproducible")


def test_execution_policy_saved_settings_preserve_parallelism() -> None:
    """Keep resolved thread counts in saved settings without consulting the host."""
    _, settings = resolve_execution_policy("relaxed")
    saved = settings.model_dump_json()
    restored = ReproducibilitySpec.model_validate_json(saved)
    assert restored == settings
    assert restored.determinism.deterministic_algorithms is False


def test_execution_policy_custom_preserves_and_copies_settings() -> None:
    """Keep explicit numerical settings custom and detach caller-owned mappings."""
    _, settings = resolve_execution_policy()
    settings.numpy_randomness.generators["sampling"] = "PCG64"
    policy, copied = resolve_execution_policy(settings)
    assert policy.mode == "custom"
    assert copied == settings
    settings.numpy_randomness.generators.clear()
    assert copied.numpy_randomness.generators == {"sampling": "PCG64"}
    with pytest.raises(ValueError, match="already include parallelism"):
        resolve_execution_policy(settings, parallelism=settings.parallelism)


def test_execution_policy_revalidates_custom_settings() -> None:
    """Reject unchecked custom copies with inconsistent autocast settings."""
    _, settings = resolve_execution_policy()
    invalid = settings.model_copy(
        update={
            "precision": settings.precision.model_copy(
                update={"autocast_enabled": True, "autocast_dtype": None}
            )
        }
    )
    with pytest.raises(ValidationError, match="autocast_dtype is required"):
        resolve_execution_policy(invalid)


@pytest.mark.parametrize("selection", ["optimized", "custom", "unknown"])
def test_execution_policy_rejects_unknown_names(selection: str) -> None:
    """Require a supported preset name or explicit custom settings."""
    with pytest.raises(ValueError, match="execution policy must be"):
        resolve_execution_policy(cast(Any, selection))
```

### EP-VB1: Verification of EP-B1

#### EP-B1 test code

**File: `tests/test_authoring.py`**

Replace the module-level import section between the module docstring and `RUN_ID`
with the imports below. Add the four complete test functions at the end of the
file. If those functions already exist, replace them by name. Retain the existing
tests and `_immutable_plan()` builder; the added tests use that builder's experiment.

```python
import hashlib
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

import viper.authoring as authoring
import viper.config as config
from viper import _subprocess as subprocess
from viper.artifacts import (
    ArtifactLoaderRef,
    BundleArtifactDraft,
    SingleFileArtifactDraft,
    StageArtifactRef,
    artifact,
)
from viper.authoring import (
    RunIdMap,
    RunPlanDraft,
    TrainSpecDraft,
    VariantDraft,
    _compile_plan,
    _CompiledPlan,
    expand,
    expand_http_url,
    experiment,
    factor,
    freeze_run_plan,
    plan,
    replicate,
    stage,
    variant,
    write_experiment_spec,
    write_variant_spec,
)
from viper.authoring import input as external_input
from viper.benchmark import RunArtifactDraft, at_least, benchmark
from viper.config import ConfigTypeRef
from viper.experiments import (
    ExperimentSpec,
    FactorSpec,
    ReplicateSpec,
    TrainVariantStageConfig,
    VariantSpec,
)
from viper.http import (
    CustomHttpDraft,
    HttpContext,
    HttpResult,
    ObservedHttpResponse,
    http,
)
from viper.keys import Train as TrainKeys
from viper.metrics import (
    FloatComparator,
    MetricDependency,
    MetricImplementationRef,
    MetricSpec,
    measure,
    metric,
    min,
)
from viper.outputs import EvalOutputs, output
from viper.preflight import preflight_plan
from viper.references import GitSource, LocalFileRef, ResolvedRunRef
from viper.resume import DataLoaderConfiguration
from viper.runs import RunSpec
from viper.runtime import EnvSpec, ParallelismSpec, ReproducibilitySpec
from viper.serialization import parse_yaml_bytes, serialize_document
from viper.stages import (
    Context,
    StageImplementationRef,
    TrainSpec,
    train,
)
from viper.storage import LocalArtifactStore


def test_execution_policy_plan_defaults_to_reproducible() -> None:
    """Freeze the default policy identity with its resolved numerical controls."""
    baseline, _ = _immutable_plan()
    selected = plan(
        experiment=baseline.experiment,
        variant=baseline.variant,
        replicate=baseline.replicate,
        source=baseline.source,
        env=baseline.env,
    )
    assert selected.execution_policy is not None
    assert selected.execution_policy.mode == "reproducible"
    assert selected.execution_policy.version == 1
    assert selected.reproducibility.determinism.deterministic_algorithms is True
    with pytest.raises(ValidationError):
        selected.reproducibility.parallelism.torch_intraop_threads = 8


def test_execution_policy_plan_relaxed_with_parallelism() -> None:
    """Freeze relaxed numerical controls and explicit resource settings together."""
    baseline, _ = _immutable_plan()
    resources = ParallelismSpec(
        process_count=1,
        torch_intraop_threads=4,
        torch_interop_threads=2,
        dataloader=DataLoaderConfiguration(workers=2, prefetch_factor=2),
    )
    selected = plan(
        experiment=baseline.experiment,
        variant=baseline.variant,
        replicate=baseline.replicate,
        source=baseline.source,
        env=baseline.env,
        reproducibility="relaxed",
        parallelism=resources,
    )
    assert selected.execution_policy is not None
    assert selected.execution_policy.mode == "relaxed"
    assert selected.reproducibility.determinism.deterministic_algorithms is False
    assert selected.reproducibility.parallelism == resources
    assert selected.reproducibility.parallelism is not resources


def test_execution_policy_plan_custom_is_detached() -> None:
    """Retain custom values without retaining caller-owned generator mappings."""
    baseline, _ = _immutable_plan()
    settings = ReproducibilitySpec.model_validate(baseline.reproducibility.model_dump())
    settings.numpy_randomness.generators["sampling"] = "PCG64"
    expected_generators = dict(settings.numpy_randomness.generators)
    selected = plan(
        experiment=baseline.experiment,
        variant=baseline.variant,
        replicate=baseline.replicate,
        source=baseline.source,
        env=baseline.env,
        reproducibility=settings,
    )
    settings.numpy_randomness.generators.clear()
    assert selected.execution_policy is not None
    assert selected.execution_policy.mode == "custom"
    assert selected.reproducibility.numpy_randomness.generators == expected_generators


def test_execution_policy_expand_resolves_once() -> None:
    """Use one policy resolution for all selected variant-replicate pairs."""
    baseline, _ = _immutable_plan()
    declaration = baseline.experiment.model_copy(
        update={
            "replicates": {
                "replicate_01": replicate(seed=42),
                "replicate_02": replicate(seed=43),
            }
        }
    )
    with patch.object(
        authoring, "resolve_execution_policy", wraps=authoring.resolve_execution_policy
    ) as resolver:
        selected = expand(
            declaration,
            run_ids={
                "baseline": {
                    "replicate_01": RUN_ID,
                    "replicate_02": "01ARZ3NDEKTSV4RRFFQ69G5FAX",
                }
            },
            source=baseline.source,
            env=baseline.env,
            reproducibility="relaxed",
        )
        resolver.assert_called_once_with("relaxed", parallelism=None)
    assert len(selected) == 2
    assert selected[0].execution_policy == selected[1].execution_policy
    assert selected[0].execution_policy is not None
    assert selected[0].execution_policy.mode == "relaxed"
    assert selected[0].reproducibility == selected[1].reproducibility
    assert selected[0].reproducibility is not selected[1].reproducibility
```

The first three tests check default, relaxed, and custom plans. The expansion
test prepares two replicates and checks that their settings come from one resolver
call. Its `patch.object(..., wraps=...)` counts calls while invoking the real
resolver, and restores the original function when the `with` block ends.


### EP-VB2a: Verification of EP-B2a

#### EP-B2a fixture changes

These builders already supply explicit settings. Add the matching policy once
in each location below, immediately after `reproducibility`, if it is absent.

For **constructor arguments**, add
`execution_policy=ExecutionPolicyRef(mode="custom"),` to the `RunSpec(...)` or
`RunPlanDraft(...)` call. In those files, also add `ExecutionPolicyRef` to the
existing `from viper.runtime import (...)` group.

For **dictionary entries**, add
`"execution_policy": {"mode": "custom", "version": 1},` to the run dictionary.
No import is needed for these entries.

| File | Containing function | Add |
|---|---|---|
| [test_protocol.py](../../tests/test_protocol.py) | `run_payload()` | Dictionary entry |
| [test_generated_project_acceptance.py](../../tests/test_generated_project_acceptance.py) | `_freeze()` | Constructor argument |
| [test_run_execution.py](../../tests/test_run_execution.py) | `freeze_protocol_plan()` | Constructor argument |
| [test_preflight.py](../../tests/test_preflight.py) | `test_preflight_reports_all_plan_failures()` | Dictionary entry |
| [test_inspection.py](../../tests/test_inspection.py) | `_run()` | Dictionary entry |
| [test_verification_acceptance.py](../../tests/test_verification_acceptance.py) | `make_run()` | Constructor argument |
| [test_execution_signals.py](../../tests/test_execution_signals.py) | `freeze()` | Constructor argument |
| [test_verification.py](../../tests/test_verification.py) | `run_spec()` | Constructor argument |

**File: `tests/test_authoring.py`**

Append these two tests. Existing imports and `_compiled_plan()` supply all names. Remove `test_policy_persistence_schema_roundtrip` and `test_policy_persistence_schema_rejects_invalid_versions` if you added them from the withdrawn block.

```python
def test_policy_persistence_writer_roundtrip(tmp_path: Path) -> None:
    """Save the selected mode and settings and read both back unchanged."""
    compiled, draft = _compiled_plan(tmp_path)
    raw = compiled.files[compiled.run_path]
    restored = RunSpec.model_validate(parse_yaml_bytes(raw))
    assert restored.execution_policy == draft.execution_policy
    assert restored.reproducibility == draft.reproducibility
    assert serialize_document(restored) == raw
    assert RunSpec.model_json_schema()["required"].count("execution_policy") == 1


def test_policy_persistence_requires_policy_identity(tmp_path: Path) -> None:
    """Reject missing policy identity instead of inferring a historical mode."""
    compiled, _ = _compiled_plan(tmp_path)
    payload = compiled.run.model_dump(mode="json")
    del payload["execution_policy"]
    with pytest.raises(ValidationError, match="execution_policy"):
        RunSpec.model_validate(payload)
```

**What changes:** `execution_policy` is required, with no default and no conditional
serialization. `_compile_plan()` copies the draft's selection into the saved run.
Old development records missing the field must be regenerated from their source
builders; the reader does not guess a selection for them.

**Stop:** Apply the complete block, then run these checks and report their results
before starting EP-B2b. Do not apply only the schema declaration: the writer and
fixtures must supply the new required field in the same edit.

```bash
source .venv/bin/activate
python -m pytest -q tests/test_authoring.py tests/test_protocol.py tests/test_preflight.py tests/test_inspection.py tests/test_verification.py
python -m ruff check src/viper/runs.py src/viper/authoring.py tests/test_authoring.py tests/test_protocol.py tests/test_preflight.py tests/test_inspection.py tests/test_verification.py tests/test_verification_acceptance.py tests/test_run_execution.py tests/test_generated_project_acceptance.py tests/test_execution_signals.py
python -m pyright src/viper/runs.py src/viper/authoring.py tests/test_authoring.py tests/test_protocol.py tests/test_preflight.py tests/test_inspection.py tests/test_verification.py tests/test_verification_acceptance.py tests/test_run_execution.py tests/test_generated_project_acceptance.py tests/test_execution_signals.py
```


### EP-VB2b: Verification of EP-B2b

#### EP-B2b test code

**File: `tests/test_authoring.py`**

Replace the `viper.runtime` import with this group and append these two tests.
The second test makes thread-default queries fail while reading the saved run,
so an accidental recalculation fails the test.

```python
from viper.runtime import (
    EnvSpec,
    ParallelismSpec,
    ReproducibilitySpec,
    resolve_execution_policy,
)


def test_policy_persistence_consistency(tmp_path: Path) -> None:
    """Accept matching presets and reject a relabelled relaxed run."""
    compiled, _ = _compiled_plan(tmp_path)
    payload = compiled.run.model_dump(mode="json")
    for mode in ("reproducible", "relaxed"):
        policy, settings = resolve_execution_policy(mode)
        payload.update(
            execution_policy=policy.model_dump(mode="json"),
            reproducibility=settings.model_dump(mode="json"),
        )
        restored = RunSpec.model_validate(payload)
        assert restored.execution_policy.mode == mode
        assert restored.reproducibility == settings

    payload["execution_policy"] = {"mode": "reproducible", "version": 1}
    with pytest.raises(ValidationError, match="saved numerical settings"):
        RunSpec.model_validate(payload)


def test_policy_persistence_replay(tmp_path: Path) -> None:
    """Read the saved controls without consulting current thread defaults."""
    compiled, _ = _compiled_plan(tmp_path)
    policy, settings = resolve_execution_policy("relaxed")
    payload = compiled.run.model_dump(mode="json")
    payload.update(
        execution_policy=policy.model_dump(mode="json"),
        reproducibility=settings.model_dump(mode="json"),
    )
    saved = serialize_document(RunSpec.model_validate(payload))
    with patch(
        "viper.runtime.torch.get_num_threads",
        side_effect=AssertionError("saved runs must not consult thread defaults"),
    ), patch(
        "viper.runtime.torch.get_num_interop_threads",
        side_effect=AssertionError("saved runs must not consult thread defaults"),
    ):
        restored = RunSpec.model_validate(parse_yaml_bytes(saved))
    assert restored.execution_policy == policy
    assert restored.reproducibility == settings
    assert serialize_document(restored) == saved
```

#### EP-B2b check and stop

After applying all three file blocks, run:

```bash
source .venv/bin/activate
python -m ruff check src/viper/runtime.py src/viper/runs.py tests/test_authoring.py
python -m pyright src/viper/runtime.py src/viper/runs.py tests/test_authoring.py
python -m pytest -q tests/test_authoring.py tests/test_runtime_boundary.py
```

EP-02 requires the schema, writer, and consistency checks above to pass. EP-B3 adds observations of active worker
settings; comparing saved labels and settings here establishes only their
consistency.


### EP-VB3: Verify worker control recording

Observes EP-03. Dependencies: EP-B3 and EP-VB2b. These checks establish behavior;
they introduce no additional product requirement.

**File: `tests/test_execution_policy_controls.py`**

Create this complete test module. Its CUDA receipt case checks the comparison
logic with supplied readings; real CUDA execution remains in EP-VB5.

```python
"""Check observed policy controls and reject altered worker readings."""

import os
import sys
from pathlib import Path

import pytest
import torch

from viper import _subprocess as subprocess
from viper._verification.runtime import verify_runtime_controls
from viper.runtime import (
    ProcessStartupReceipt,
    RuntimeControlsReceipt,
    observe_runtime_controls,
    resolve_execution_policy,
)


@pytest.mark.parametrize("mode", ["reproducible", "relaxed", "custom"])
def test_policy_controls_from_fresh_worker(mode: str) -> None:
    """Apply one policy in a fresh process and verify its recorded readings."""
    program = """
import sys
from viper.runtime import (
    apply_reproducibility, autocast_context, observe_process_startup,
    resolve_execution_policy,
)
from viper._verification.runtime import verify_runtime_controls
mode = sys.argv[1]
selection = resolve_execution_policy("relaxed")[1] if mode == "custom" else mode
policy, settings = resolve_execution_policy(selection)
initialization = apply_reproducibility(7, settings)
with autocast_context(settings, backend="cpu"):
    startup = observe_process_startup(initialization, settings, "cpu")
verify_runtime_controls(startup.observed_controls, settings, "cpu")
print(startup.observed_controls.model_dump_json())
"""
    completed = subprocess.run(
        (sys.executable, "-c", program, mode),
        env={
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "src"),
            "CUDA_VISIBLE_DEVICES": "",
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    observed = RuntimeControlsReceipt.model_validate_json(completed.stdout)
    assert observed.deterministic_algorithms == (mode == "reproducible")
    assert observed.autocast_enabled is False


def test_policy_controls_observe_autocast_scope() -> None:
    """Read the enabled dtype while the caller's autocast context is active."""
    with torch.autocast("cpu", dtype=torch.bfloat16):
        observed = observe_runtime_controls("cpu")
    assert observed.autocast_enabled is True
    assert observed.autocast_dtype == "bfloat16"
    with torch.autocast("cpu", enabled=False):
        disabled = observe_runtime_controls("cpu")
    assert disabled.autocast_enabled is False
    assert disabled.autocast_dtype is None


@pytest.mark.parametrize(
    "field",
    [
        "deterministic_algorithms",
        "deterministic_warn_only",
        "cudnn_deterministic",
        "cudnn_benchmark",
        "cudnn_allow_tf32",
        "float32_matmul_precision",
        "torch_intraop_threads",
        "torch_interop_threads",
        "autocast_enabled",
        "autocast_dtype",
        "backend",
    ],
)
def test_policy_controls_reject_altered_reading(field: str) -> None:
    """Reject each altered CUDA receipt field while preserving requested settings."""
    _, settings = resolve_execution_policy()
    values = {
        "backend": "cuda",
        "deterministic_algorithms": True,
        "deterministic_warn_only": False,
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "cudnn_allow_tf32": False,
        "float32_matmul_precision": "highest",
        "torch_intraop_threads": 1,
        "torch_interop_threads": 1,
        "autocast_enabled": False,
        "autocast_dtype": None,
    }
    verify_runtime_controls(
        RuntimeControlsReceipt.model_validate(values), settings, "cuda"
    )
    altered = {
        "backend": "cpu",
        "deterministic_algorithms": False,
        "deterministic_warn_only": True,
        "cudnn_deterministic": False,
        "cudnn_benchmark": True,
        "cudnn_allow_tf32": True,
        "float32_matmul_precision": "high",
        "torch_intraop_threads": 2,
        "torch_interop_threads": 2,
        "autocast_enabled": True,
        "autocast_dtype": "bfloat16",
    }
    values[field] = altered[field]
    with pytest.raises(ValueError, match=field):
        verify_runtime_controls(
            RuntimeControlsReceipt.model_validate(values), settings, "cuda"
        )

def test_policy_receipt_fields_describe_saved_values() -> None:
    """Preserve a generated-schema description for every receipt field."""
    for model in (RuntimeControlsReceipt, ProcessStartupReceipt):
        properties = model.model_json_schema()["properties"]
        for name, schema in properties.items():
            assert schema.get("description", "").strip(), (model.__name__, name)

```

**File: `tests/test_process_startup.py`**

In `test_named_numpy_receipt_identifies_the_delivered_generator`, replace
`initialized.receipt.generators` with `initialized.generators`. The test inspects
the seed records returned by initialization.

The saved receipt must contain the settings active when your function starts,
including whether autocast is enabled and which dtype it uses.

**File: `tests/conftest.py`**

Add `"test_execution_policy_controls": "integration"` to `TIER_BY_MODULE`, and
`"test_execution_policy_controls": "domain_execution"` to `DOMAIN_BY_MODULE`.

Update the following two existing test-data builders when introducing the
required receipt field. These values construct synthetic test evidence;
production workers obtain the values through getters in EP-B3.

**File: `tests/test_verification.py`**

Add `RuntimeControlsReceipt` to the existing `viper.runtime` import. Replace the
final return statement of `startup_receipt(run)` with this statement, indented
inside the function:

```python
return ProcessStartupReceipt(
    env=process_environment(
        run.seed,
        run.reproducibility,
        CPUComputeSpec(),
    ),
    reproducibility=run.reproducibility,
    generators=tuple(generators),
    observed_controls=RuntimeControlsReceipt(
        backend="cpu",
        deterministic_algorithms=run.reproducibility.determinism.deterministic_algorithms,
        deterministic_warn_only=run.reproducibility.determinism.deterministic_warn_only,
        cudnn_deterministic=run.reproducibility.determinism.cudnn_deterministic,
        cudnn_benchmark=run.reproducibility.determinism.cudnn_benchmark,
        cudnn_allow_tf32=run.reproducibility.precision.cudnn_allow_tf32,
        float32_matmul_precision=run.reproducibility.precision.float32_matmul_precision,
        torch_intraop_threads=run.reproducibility.parallelism.torch_intraop_threads,
        torch_interop_threads=run.reproducibility.parallelism.torch_interop_threads,
        autocast_enabled=run.reproducibility.precision.autocast_enabled,
        autocast_dtype=run.reproducibility.precision.autocast_dtype,
    ),
)
```

**File: `tests/test_verification_acceptance.py`**

Add `RuntimeControlsReceipt` to the existing `viper.runtime` import. Replace the
final return statement of `startup_receipt(run)` with this statement, indented
inside the function:

```python
return ProcessStartupReceipt(
    env=process_environment(
        run.seed,
        run.reproducibility,
        CPUComputeSpec(),
    ),
    reproducibility=run.reproducibility,
    generators=tuple(generators),
    observed_controls=RuntimeControlsReceipt(
        backend="cpu",
        deterministic_algorithms=run.reproducibility.determinism.deterministic_algorithms,
        deterministic_warn_only=run.reproducibility.determinism.deterministic_warn_only,
        cudnn_deterministic=run.reproducibility.determinism.cudnn_deterministic,
        cudnn_benchmark=run.reproducibility.determinism.cudnn_benchmark,
        cudnn_allow_tf32=run.reproducibility.precision.cudnn_allow_tf32,
        float32_matmul_precision=run.reproducibility.precision.float32_matmul_precision,
        torch_intraop_threads=run.reproducibility.parallelism.torch_intraop_threads,
        torch_interop_threads=run.reproducibility.parallelism.torch_interop_threads,
        autocast_enabled=run.reproducibility.precision.autocast_enabled,
        autocast_dtype=run.reproducibility.precision.autocast_dtype,
    ),
)
```

Gate (run after EP-B4 supplies the comparison used by the tests):

```bash
python -m pytest -q tests/test_execution_policy_controls.py tests/test_process_startup.py
```

The acceptance cases read controls in fresh CPU processes for all three modes,
observe enabled and disabled autocast scopes, and reject each changed comparison
field. Require every selected case to execute.

### EP-VB4: Verify saved runs and reuse

Observes EP-04. Dependencies: EP-B4 and EP-VB3.
Targets: `tests/test_verification_acceptance.py` and the existing verifier tests.

Context: Alter a saved reading while preserving the requested settings and valid
outer file hashes. Verification must reject the changed reading for a stage,
a metric, and a producing run reached through reuse.

**File: `tests/test_verification_acceptance.py`**

Add these names to the module-level `viper.reuse` import:

```python
from viper.reuse import (
    ResolvedStageReuseRef,
    ReusedStageCompletion,
    verified_input_identity,
)
```

Append these complete helpers and tests:

```python
def _policy_stage_reading_changed(
    store: DocumentStore, result: ResolvedRun
) -> ResolvedRun:
    """Change the saved evaluation reading and rebuild its containing references."""
    attempt = fetch_attempt(store, result.attempts[-1])
    stage = attempt.resolved_stages[-1]
    assert stage.stage_id == "evaluate"
    location = hf_file(snapshot_revision(stage.snapshot), str(stage.resolved_spec.path))
    resolved = ResolvedEvaluateSpec.model_validate(
        yaml.safe_load(store.fetch(location))
    )
    assert isinstance(resolved.completion, ExecutedStageCompletion)
    startup = resolved.completion.startup
    deterministic = startup.observed_controls.deterministic_algorithms
    changed_controls = startup.observed_controls.model_copy(
        update={"deterministic_algorithms": not deterministic}
    )
    changed_startup = startup.model_copy(update={"observed_controls": changed_controls})
    completion = resolved.completion.model_copy(update={"startup": changed_startup})
    changed = resolved.model_copy(update={"completion": completion})
    assert completion.startup.reproducibility == startup.reproducibility
    # Rebuild enclosing digests so verification reaches the changed reading.
    changed_stage = publish_resolved_stage(
        store,
        run_root_path=str(result.spec.stored_at.path).removesuffix("/spec.yaml"),
        stage_id="evaluate",
        snapshot_commit=snapshot_revision(stage.snapshot),
        resolved_spec=changed,
    )
    changed_attempt = attempt.model_copy(
        update={"resolved_stages": (*attempt.resolved_stages[:-1], changed_stage)}
    )
    return replace_run_attempts(store, result, (changed_attempt,))


def test_policy_rejects_saved_stage_reading() -> None:
    """Reject an altered stage reading with valid settings and hashes."""
    result, store, _ = build_complete_fixture()
    verify_run_result(result, policy=POLICY, fetcher=store.fetch)
    changed = _policy_stage_reading_changed(store, result)
    with pytest.raises(
        VerificationError, match="startup.controls: deterministic_algorithms"
    ):
        verify_run_result(changed, policy=POLICY, fetcher=store.fetch)


@pytest.mark.parametrize("execution", ["production", "recomputation"])
def test_policy_rejects_saved_metric_reading(execution: str) -> None:
    """Reject changed controls in either saved metric invocation."""
    result, store, _ = build_complete_fixture()
    verify_run_result(result, policy=POLICY, fetcher=store.fetch)
    attempt = fetch_attempt(store, result.attempts[-1])
    reference = attempt.metric_verification_files[0]
    receipt = MetricVerificationReceipt.model_validate(
        yaml.safe_load(store.fetch(reference.stored_at))
    )
    invocation = (
        receipt.production if execution == "production" else receipt.recomputation
    )
    controls = invocation.startup.observed_controls
    changed_controls = controls.model_copy(
        update={"deterministic_algorithms": not controls.deterministic_algorithms}
    )
    changed_startup = invocation.startup.model_copy(
        update={"observed_controls": changed_controls}
    )
    changed = invocation.model_copy(update={"startup": changed_startup})
    assert changed.startup.reproducibility == invocation.startup.reproducibility
    raw = yaml_bytes(receipt.model_copy(update={execution: changed}))
    store.put(reference.stored_at, raw)
    # The receipt and attempt hashes remain valid after changing the reading.
    changed_reference = reference.model_copy(
        update={"sha256": sha256(raw), "bytes": len(raw)}
    )
    changed_attempt = attempt.model_copy(
        update={"metric_verification_files": (changed_reference,)}
    )
    changed_result = replace_run_attempts(store, result, (changed_attempt,))
    with pytest.raises(
        VerificationError, match="startup.controls: deterministic_algorithms"
    ):
        verify_run_result(changed_result, policy=POLICY, fetcher=store.fetch)


def _policy_reused_evaluation(
    store: DocumentStore, source: ResolvedRun, verified: VerifiedRunResult
) -> ResolvedRun:
    """Reuse one saved evaluation, retaining references to its producing run."""
    source_attempt = fetch_attempt(store, source.attempts[-1])
    source_stage = source_attempt.resolved_stages[-1]
    source_location = hf_file(
        snapshot_revision(source_stage.snapshot), str(source_stage.resolved_spec.path)
    )
    source_result = ResolvedEvaluateSpec.model_validate(
        yaml.safe_load(store.fetch(source_location))
    )
    run = verified.plan.run
    run_root = str(source.spec.stored_at.path).removesuffix("/spec.yaml")
    source_raw = yaml_bytes(source)
    source_run_location = hf_file("d" * 40, f"{run_root}/resolved.yaml")
    store.put(source_run_location, source_raw)
    source_run = ResolvedRunRef(
        stored_at=source_run_location, sha256=sha256(source_raw), bytes=len(source_raw)
    )
    inputs = tuple(
        verified_input_identity(name, value)
        for name, value in sorted(verified.inputs["evaluate"].items())
    )
    artifact = source_result.artifacts["predictions"]
    assert isinstance(artifact, ResolvedSingleFileArtifact)
    reuse = StageReuseReceipt(
        stage_id="evaluate",
        key=build_stage_reuse_key(
            stage_id="evaluate",
            stage=source_result.spec,
            inputs=inputs,
            seed=run.seed,
            env=source_result.spec.env or run.env,
            reproducibility=run.reproducibility,
            metrics={
                metric.metric_id: metric for metric in verified.plan.experiment.metrics
            },
        ),
        source_run=source_run,
        source_attempt=source.attempts[-1],
        source_stage=source_stage,
        files=(
            ReusedStageFile(
                artifact_name="predictions", source=artifact.file, target=artifact.file
            ),
        ),
        metrics=(
            ReusedMetricEvidence(
                metric_id="pearson_correlation",
                measurement=source_attempt.measurement_files[0],
                verification=source_attempt.metric_verification_files[0],
            ),
        ),
        completed_at=source_result.completed_at,
    )
    raw = yaml_bytes(reuse)
    location = hf_file("e" * 40, f"{run_root}/stages/evaluate/reuse.yaml")
    store.put(location, raw)
    target = source_result.model_copy(
        update={
            "completion": ReusedStageCompletion(
                receipt=ResolvedStageReuseRef(
                    stored_at=location, sha256=sha256(raw), bytes=len(raw)
                )
            )
        }
    )
    # Preserve the original snapshot: the target refers back to its source.
    copy_snapshot_files(store, snapshot_revision(source_stage.snapshot), "e" * 40)
    target_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="evaluate",
        snapshot_commit="e" * 40,
        resolved_spec=target,
    )
    target_attempt = source_attempt.model_copy(
        update={
            "resolved_stages": (*source_attempt.resolved_stages[:-1], target_stage),
            "invocations": source_attempt.invocations[:-1],
            "metric_verification_files": (),
        }
    )
    target_reference = publish_attempt(
        store, run_root_path=run_root, attempt=target_attempt, commit="f" * 40
    )
    return source.model_copy(update={"attempts": (target_reference,)})


def test_policy_rejects_reused_producer_reading() -> None:
    """Follow reuse to its producer and reject the producer's changed controls."""
    result, store, _ = build_complete_fixture()
    verified = verify_run_result(result, policy=POLICY, fetcher=store.fetch)
    target = _policy_reused_evaluation(store, result, verified)
    verify_run_result(target, policy=POLICY, fetcher=store.fetch)

    # A separate store preserves the accepted case and its immutable references.
    result, store, _ = build_complete_fixture()
    verified = verify_run_result(result, policy=POLICY, fetcher=store.fetch)
    changed_source = _policy_stage_reading_changed(store, result)
    changed_target = _policy_reused_evaluation(store, changed_source, verified)
    with pytest.raises(
        VerificationError, match="startup.controls: deterministic_algorithms"
    ):
        verify_run_result(changed_target, policy=POLICY, fetcher=store.fetch)
```

Run from the workspace root after activating `.venv`:

```bash
python -m pytest -q tests/test_verification.py tests/test_verification_acceptance.py tests/test_execution_policy_controls.py tests/test_benchmark_execution.py
```

Stop after this command passes.

### EP-VB5: Verify public workflows

Observes EP-05. Dependencies: EP-B5 and EP-VB4.
Targets: `tests/test_readme_workflow.py`, `tests/test_plan_execution.py`,
`tests/test_project_init.py`, `tests/test_run_execution.py`,
`tests/test_execution_signals.py`, `tests/test_execution_policy_acceptance.py`,
`tests/conftest.py`, and the existing documentation and CUDA tests.

Context: Each policy example executes as a program. A second process verifies its
saved run, then rejects a changed artifact. Two reproducible runs must produce
the same model bytes. Existing explicit-root callers use the keyword argument.

**File: `tests/test_readme_workflow.py`**

Add this module-level import:

```python
from viper.repository import RootError, read_source
```

Append these complete declarations:

```python
_POLICY_VERIFY_PROGRAM = """
import hashlib
import json
import sys
from pathlib import Path

from viper.execution._source import RunFetcher
from viper.runs import ResolvedRun, RunSpec
from viper.serialization import parse_yaml_bytes
from viper.storage import LocalArtifactStore
from viper.verification import verify_run_result
from viper.evidence import VerificationPolicy

root = Path(sys.argv[1])
result = ResolvedRun.model_validate(parse_yaml_bytes(Path(sys.argv[2]).read_bytes()))
store = LocalArtifactStore(root)
run = RunSpec.model_validate(parse_yaml_bytes(store.fetch(result.spec.stored_at)))
fetcher = RunFetcher(root, store, str(run.source.repository))
policy = VerificationPolicy(
    trusted_source_repositories=frozenset({str(run.source.repository)})
)
verified = verify_run_result(result, policy=policy, fetcher=fetcher)
stage = verified.resolved_stages["train"]
reference = verified.attempts[-1].resolved_stages[0]
model = stage.artifacts["model"].file
model_path = root / reference.snapshot.store / reference.snapshot.commit / model.path
print(json.dumps({
    "run_id": run.run_id,
    "policy": run.execution_policy.mode,
    "controls": stage.completion.startup.observed_controls.model_dump(),
    "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
    "model_path": str(model_path),
}))
"""


@pytest.fixture
def policy_workspace(tmp_path: Path) -> Path:
    """Create a committed workspace containing both complete policy examples."""
    root = tmp_path / "policy"
    (root / "examples/data").mkdir(parents=True)
    for name in ("cpu_quickstart.py", "execution_policies.py"):
        shutil.copy(Path("examples") / name, root / "examples" / name)
    shutil.copy("examples/data/tiny.csv", root / "examples/data/tiny.csv")
    shutil.copy("pyproject.toml", root / "pyproject.toml")
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    _run(root, "git", "init", "--quiet")
    _run(root, "git", "config", "user.email", "viper@example.com")
    _run(root, "git", "config", "user.name", "VIPER Policy Test")
    _run(root, "git", "remote", "add", "origin", "https://github.com/example/viper")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "--quiet", "-m", "policy source")
    return root


def test_read_source_identifies_commit_and_selected_remote(
    policy_workspace: Path,
) -> None:
    """Return HEAD and the requested remote through the public repository API."""
    source = read_source(policy_workspace)
    assert (
        source.commit
        == _run(policy_workspace, "git", "rev-parse", "HEAD").stdout.strip()
    )
    assert str(source.repository) == "https://github.com/example/viper"
    _run(
        policy_workspace,
        "git",
        "remote",
        "add",
        "mirror",
        "https://github.com/example/mirror",
    )
    mirror = read_source(policy_workspace, remote="mirror")
    assert mirror.commit == source.commit
    assert str(mirror.repository) == "https://github.com/example/mirror"


def test_read_source_rejects_missing_remote(policy_workspace: Path) -> None:
    """Report an unavailable source remote at the repository API boundary."""
    with pytest.raises(RootError, match="selected Git remote"):
        read_source(policy_workspace, remote="absent")


@pytest.mark.parametrize("mode", ["reproducible", "relaxed", "custom"])
def test_policy_example_verifies_after_exit(policy_workspace: Path, mode: str) -> None:
    """Verify each saved policy run and reject changed artifact bytes."""
    root = policy_workspace
    environment = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    # A relaxed child must discard an inherited strict cuBLAS setting.
    environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    records = []
    result_paths: list[Path] = []
    for _ in range(2 if mode == "reproducible" else 1):
        completed = subprocess.run(
            (sys.executable, "examples/execution_policies.py", mode),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        result_line = next(
            line
            for line in completed.stdout.splitlines()
            if line.startswith("result: ")
        )
        result_path = root / result_line.removeprefix("result: ")
        result_paths.append(result_path)
        # The producer has exited; this independent interpreter reads its saved run.
        verification = subprocess.run(
            (sys.executable, "-c", _POLICY_VERIFY_PROGRAM, str(root), str(result_path)),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        record = json.loads(verification.stdout)
        assert record["policy"] == mode
        assert record["controls"]["deterministic_algorithms"] == (
            mode == "reproducible"
        )
        assert record["controls"]["autocast_enabled"] is False
        records.append(record)
    if mode == "reproducible":
        assert records[0]["run_id"] != records[1]["run_id"]
        assert records[0]["model_sha256"] == records[1]["model_sha256"]
    if mode == "custom":
        assert records[-1]["controls"]["torch_intraop_threads"] == 2
    # Corrupt the stored artifact, rather than the mutable workspace copy.
    Path(records[-1]["model_path"]).write_bytes(b"changed model\n")
    rejected = subprocess.run(
        (sys.executable, "-c", _POLICY_VERIFY_PROGRAM, str(root), str(result_paths[-1])),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "VerificationError" in rejected.stderr


def test_read_source_discovers_from_nested_directory(
    policy_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Find the containing workspace without a caller-supplied root."""
    expected = read_source(policy_workspace)
    monkeypatch.chdir(policy_workspace / "examples")
    assert read_source() == expected
```

**File: `tests/test_plan_execution.py`**

Replace `test_run_compiles_plan_before_first_attempt` with:

```python
def test_run_compiles_plan_before_first_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish the plan before handing its exact reference to the runner."""
    draft = RunPlanDraft.model_construct()
    reference = SimpleNamespace(stored_at=SimpleNamespace(path="run.yaml"))
    frozen = SimpleNamespace(reference=reference)
    result = object()
    calls: list[str] = []

    def freeze(
        root: Path,
        selected: RunPlanDraft,
        *,
        cloud_client: object | None = None,
    ):
        calls.append("freeze")
        assert root == tmp_path
        assert selected is draft
        assert cloud_client is None
        return frozen

    def run(root: Path, path: Path, **kwargs: object):
        calls.append("run")
        assert root == tmp_path
        assert path == tmp_path / "run.yaml"
        assert kwargs["plan"] is reference
        return result

    def resolve_root(selected: Path | None) -> Path:
        """Keep this ordering test independent of workspace discovery."""
        assert selected == tmp_path
        return tmp_path

    monkeypatch.setattr(execution, "resolve_root", resolve_root)
    monkeypatch.setattr(execution, "freeze_run_plan", freeze)
    monkeypatch.setattr(execution, "_run", run)

    assert execution.run(draft, repository_root=tmp_path) is result
    assert calls == ["freeze", "run"]
```

**File: `tests/test_run_execution.py`**

In `test_two_stage_local_run_writes_and_verifies_terminal_result`, replace the existing execution call or assertion with:

```python
execute_run(frozen.files[-1], repository_root=root)
```

In `test_train_stage_captures_local_external_input`, replace the existing execution call or assertion with:

```python
result = execute_run(frozen.files[-1], repository_root=root)
```

**File: `tests/test_execution_signals.py`**

In `test_live_l4_stage_records_requested_backend`, replace the existing execution call or assertion with:

```python
result = execute_run(run_path, repository_root=root)
```

**File: `tests/test_project_init.py`**

In `test_init_generates_importable_python_project`, replace the existing execution call or assertion with:

```python
assert "execution.run(draft, repository_root=root)" in runner
```

Run the CPU and documentation checks from the workspace root:

```bash
source .venv/bin/activate
python -m pytest -q tests/test_plan_execution.py tests/test_project_init.py tests/test_run_execution.py tests/test_execution_signals.py tests/test_readme_workflow.py tests/test_documentation.py
```

The policy tests verify each saved run after its producer exits and reject
changed artifact bytes. Reproducible repetition compares model digests. Relaxed
execution permits nondeterminism; equal bytes on a CPU do not invalidate that
policy.

On the supported CUDA host, run the real-device checks:

```bash
VIPER_LIVE_CUDA=1 python -m pytest -q tests/test_live_process_startup.py
```

Stop after the CPU and CUDA checks pass. A skipped CUDA check leaves the CUDA
acceptance gate open.

#### CPU and CUDA execution-policy acceptance

**File: `tests/test_execution_policy_acceptance.py`**

Create this complete test module:

```python
"""Exercise execution policies in fresh CPU and optional CUDA processes."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from viper import _subprocess as subprocess

_PROGRAM = """
import hashlib
import json
import os
import sys

import torch

from viper._verification.runtime import verify_runtime_controls
from viper.runtime import (
    CPUComputeSpec, CUDAComputeSpec, apply_reproducibility, autocast_context,
    observe_process_startup, process_environment, resolve_execution_policy,
)

backend, mode = sys.argv[1:]
selection = resolve_execution_policy("relaxed")[1] if mode == "custom" else mode
policy, settings = resolve_execution_policy(selection)
compute = CPUComputeSpec() if backend == "cpu" else CUDAComputeSpec(
    model="NVIDIA L4", count=1
)
for key, value in process_environment(
    7, settings, compute, cuda_ordinal=0 if backend == "cuda" else None
).items():
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
initialization = apply_reproducibility(7, settings)
with autocast_context(settings, backend=backend):
    startup = observe_process_startup(initialization, settings, backend)
    values = torch.randn((64, 64), device=backend)
    result = values @ values.T
    # put_ without accumulation has no supported deterministic implementation.
    rejected = False
    try:
        torch.zeros(2, device=backend).put_(
            torch.tensor([0, 1], device=backend),
            torch.tensor([1.0, 2.0], device=backend),
            accumulate=False,
        )
    except RuntimeError as error:
        if "deterministic" not in str(error):
            raise
        rejected = True
verify_runtime_controls(startup.observed_controls, settings, backend)
print(json.dumps({
    "policy": policy.model_dump(mode="json"),
    "startup": startup.model_dump(mode="json"),
    "sha256": hashlib.sha256(result.cpu().numpy().tobytes()).hexdigest(),
    "unsupported_operation_rejected": rejected,
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "cudnn": torch.backends.cudnn.version(),
    "device": torch.cuda.get_device_name(0) if backend == "cuda" else "cpu",
}))
"""


@pytest.mark.parametrize("mode", ["reproducible", "relaxed", "custom"])
@pytest.mark.parametrize(
    "backend",
    [
        "cpu",
        pytest.param(
            "cuda",
            marks=[
                pytest.mark.live_cuda,
                pytest.mark.skipif(
                    os.environ.get("VIPER_LIVE_CUDA") != "1",
                    reason="set VIPER_LIVE_CUDA=1 on the single-L4 acceptance host",
                ),
            ],
        ),
    ],
)
def test_policy_execution_and_repetition(
    tmp_path: Path, backend: str, mode: str
) -> None:
    """Check active controls, operation eligibility, and repeated output bytes."""
    reports = []
    for _ in range(2):
        completed = subprocess.run(
            (sys.executable, "-c", _PROGRAM, backend, mode),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        report = json.loads(completed.stdout)
        assert report["policy"]["mode"] == mode
        assert report["unsupported_operation_rejected"] == (mode == "reproducible")
        controls = report["startup"]["observed_controls"]
        assert controls["backend"] == backend
        assert controls["deterministic_algorithms"] == (mode == "reproducible")
        if backend == "cuda":
            assert report["device"] == "NVIDIA L4"
            assert controls["cudnn_benchmark"] == (mode != "reproducible")
        reports.append(report)
    equal_bytes = reports[0]["sha256"] == reports[1]["sha256"]
    if mode == "reproducible":
        assert equal_bytes
    # Keep relaxed comparisons separate from acceptance of the saved controls.
    evidence_root = Path(os.environ.get("VIPER_POLICY_EVIDENCE_DIR", str(tmp_path)))
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / f"{backend}-{mode}.json").write_text(
        json.dumps({"runs": reports, "equal_bytes": equal_bytes}, indent=2),
        encoding="utf-8",
    )
```

**File: `tests/conftest.py`**

Add `"test_execution_policy_acceptance": "integration"` to `TIER_BY_MODULE`
and `"test_execution_policy_acceptance": "domain_execution"` to `DOMAIN_BY_MODULE`.

Run the CPU cases:

```bash
python -m pytest -q tests/test_execution_policy_acceptance.py -k cpu
```

Run the CUDA cases on the single-L4 host and retain their receipts:

```bash
VIPER_LIVE_CUDA=1 VIPER_POLICY_EVIDENCE_DIR=policy-evidence python -m pytest -q tests/test_execution_policy_acceptance.py tests/test_live_process_startup.py
```

Each JSON file contains both startup receipts, software and device versions,
output hashes, and the byte-comparison result. Reproducible execution rejects an
operation without a deterministic implementation; relaxed and custom execution
permit it.

### Executed checks

- Runtime, authoring, benchmark execution, plan execution, and workspace
  initialization: 53 tests passed.
- Runtime-control receipts, CPU policy execution, and process startup: 32 tests
  passed; three CUDA policy cases require the designated host.
- Saved-run verification and benchmark checks: 69 tests and two subtests passed.
- Documentation, public API, and saved-reading tampering selection: 37 tests passed.
- CPU coverage: 470 tests and 29 subtests passed across the full suite and
  focused checks. Nine live-device cases require the designated CUDA host.
- Ruff and Pyright: passed.

The CUDA commands above retain startup receipts, device/software versions, and
output hashes. Their acceptance gate remains open until executed on that host.

## 13. ContractTarget

Production owners are the exact paths in EP-B0 through EP-B5. The new internal
comparison module is `src/viper/_verification/runtime.py`; its stage and metric
callers translate comparison failures to `VerificationError`. Reuse consumes
those checks through the existing producing-run traversal.

EP-VB0 through EP-VB5 own test code, test-data updates, and acceptance execution.
Each implementation block requires its corresponding tests to pass, including
the CUDA and persisted-record tampering cases where specified.
