# Execution Policy Contract

## 1. Status

**Contract status:** Planned
**Checklist variant:** Self-contained

Baseline: `da24218f94489d35eb44659433594b6feed7e487`. All changes below
are proposed. The [checklist](execution-policy-contract.checklist.json) owns
implementation status. Later blocks remain planning metadata until we inspect
and prepare each one.

**Start here: [EP-B0 — proposed code and checks](#ep-b0-resolve-execution-settings).**
Jump directly to the [runtime code](#ep-b0-runtime-code) or
[tests](#ep-b0-test-code).

| ID | Implementation obligation |
|---|---|
| EP-00 | Resolve version-1 presets and validate detached custom settings without changing the runtime. |
| EP-01 | Resolve reproducible, relaxed, or custom settings once during authoring. |
| EP-02 | Freeze policy identity and concrete settings; distinguish legacy plans. |
| EP-03 | Apply controls and observe effective worker settings before invocation. |
| EP-04 | Verify those observations without implying that outputs repeat byte for byte. |
| EP-05 | Demonstrate all three modes through complete examples and acceptance tests. |

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

The default requests deterministic execution. Byte parity is a separate result
obtained by comparing the bytes of selected artifacts from repeated runs.
Neither successful startup verification nor the mode name establishes parity.
Repeatability depends on compatible hardware and software, deterministic user
code, controlled inputs and randomness, and stable artifact serialization.
[PyTorch documents the platform and release limits](https://docs.pytorch.org/docs/stable/notes/randomness.html).

## 3. Current gap

### Inspected path

[Authoring](../../src/viper/authoring.py) requires a complete
`ReproducibilitySpec` in `plan()` and `expand()`. It freezes that value in
`RunPlanDraft` and compiles it into [RunSpec](../../src/viper/runs.py).
[Runtime initialization](../../src/viper/runtime.py) applies controls but stores
the requested spec in `ProcessStartupReceipt.reproducibility`.
[Stage verification](../../src/viper/_verification/attempt.py) and
[metric verification](../../src/viper/_verification/metrics.py) compare that
copy with the plan. This comparison does not independently observe Torch flags.

### Proposed check

VIPER will let authors select a preset or supply custom settings. It will save
those settings in the plan, apply them in each worker, and read back the active
controls before invoking user code.

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

For example, if the plan requires `deterministic_algorithms=True` but the worker
reports `False`, verification rejects the worker's evidence—even if its copy of
the requested settings still says `True`. This applies to stage and metric workers.

A match establishes that the observed startup controls agree with the plan.
Checking whether repeated runs produced identical artifact bytes remains a
separate comparison.

## 4. Models

The following public boundaries are proposed; existing setting types retain
ownership in [runtime](../../src/viper/runtime.py).

| Boundary | Contract |
|---|---|
| `plan()` and `expand()` arguments | Add optional `parallelism: ParallelismSpec \| None`; for `reproducibility`, accept `Literal["reproducible", "relaxed"] \| ReproducibilitySpec`, default `"reproducible"`. Passing a spec selects custom. |
| `ExecutionPolicyRef` | New runtime model: `mode: Literal["reproducible", "relaxed", "custom"]`, `version: Literal[1]`. Version identifies these selection semantics. |
| `RunPlanDraft.execution_policy` and `RunSpec.execution_policy` | Required `ExecutionPolicyRef` for newly authored plans. Existing `.reproducibility` stores the complete settings. |
| `ProcessStartupReceipt.observed_controls` | New `RuntimeControlsReceipt`: `backend: Literal["cpu", "cuda"]`; queried deterministic/warn-only flags, cuDNN deterministic/benchmark/TF32 flags, float32 matmul precision, intra/inter-op thread counts, and autocast enabled/dtype observed inside the invocation context. Types match their corresponding settings. |
| Existing startup environment and generator receipts | Retain environment values, seed identities and state hashes; do not duplicate them in `RuntimeControlsReceipt`. |

Preset version 1 expands to these exact values:

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

1. Resolve the selection before freezing the plan. Reject unknown names and
   invalid custom settings. `expand()` applies the same policy to every run.
2. Persist both policy identity and concrete settings. Modified numerical
   controls require custom mode; parallelism remains an independent choice.
   Reject mismatched numerical controls and preset labels.
3. Execute, retry and restore from the saved settings. Never re-resolve an old
   plan against the installed release's default policy.
4. Configure the process environment before importing/initializing CUDA. Clear
   an inherited cuBLAS workspace value when the plan declares `None`.
5. Apply settings, initialize generators, enter the configured autocast context,
   and query controls before calling stage or metric code. Reject unsupported
   execution and mismatches. CPU workers record backend applicability explicitly;
   CUDA-only controls do not become claims about CPU arithmetic.
6. Preserve current single-process and single-CUDA-device support. DataLoader
   settings remain checked at their existing construction/state boundaries;
   Torch startup getters cannot establish loader behavior.

User callables remain trusted code: they can change global controls or use
untracked randomness after startup. This contract verifies startup configuration,
not continuous enforcement inside arbitrary Python or native code.

## 6. Persisted evidence

| Record | Required evidence |
|---|---|
| Saved authoring plan and `RunSpec` | Concrete settings and policy mode/version bound into existing immutable serialization and identity checks. |
| Executed stage and metric startup receipts | Effective controls, applicable backend, existing environment and generator observations. |
| Reused stage evidence | Original producer's policy and startup evidence, checked through the existing reuse path; never invent a consumer startup receipt. |
| Artifact comparison receipt | Existing artifact identities and byte digests. A mode label cannot substitute for comparison. |

Introduce `RunSpec` schema version 3 for the new required policy evidence. Retain
an explicit reader for version 2 and verify its existing guarantees as legacy.
Do not rewrite stored version-2 bytes, infer a historical preset, or grant legacy
receipts the new observed-controls guarantee. Unknown schema/policy versions
fail explicitly. Public schema/capability output must distinguish these versions.

## 7. Verification

| Rule | Executable condition |
|---|---|
| EP-V1 | Omitted selection equals version-1 reproducible expansion; relaxed permits nondeterministic algorithms, preserves precision, and retains configured Torch thread counts; either preset accepts independent parallelism. |
| EP-V2 | Preset label/version matches its numerical settings; parallelism is validated independently and frozen. Custom retains all validated caller values. Unknown versions reject. |
| EP-V3 | Serialization, retry and execution consume frozen settings even when resolver defaults change. |
| EP-V4 | Recorded environment, generator receipts and queried controls match the plan for every executed stage and metric worker. Missing observations reject version-3 evidence. |
| EP-V5 | A changed observed control rejects even when the copied requested spec still matches. Unsupported deterministic operations fail instead of warning and continuing. |
| EP-V6 | Legacy reading preserves original bytes and reports only legacy assurance. Reuse preserves and checks producer evidence. |
| EP-V7 | Byte comparison remains exact in every mode. Relaxed runs may pass provenance verification and fail a parity benchmark; metric tolerances do not change artifact equality. |

## 8. Propagation

| Surface | Required change |
|---|---|
| [Authoring](../../src/viper/authoring.py), [runs](../../src/viper/runs.py), [runtime](../../src/viper/runtime.py) | Resolve modes, freeze identity/settings, observe effective controls, version records. |
| [Workers](../../src/viper/_workers), [verification](../../src/viper/_verification), [reuse](../../src/viper/reuse.py) | Observe inside invocation context; enforce new evidence and preserve legacy/reuse boundaries. |
| [Serialization](../../src/viper/serialization.py), [CLI](../../src/viper/cli.py) | Dispatch schema versions and expose updated schemas through existing capability routes. |
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
the comparison result. This end-to-end check remains an EP-B4 obligation; a test
of preset values or a settings serialization round trip cannot close it.

For CUDA acceptance, retain the GPU model, driver, CUDA/cuDNN/PyTorch versions,
plan, receipts and selected artifact digests from two executions on the same
supported device. A host without CUDA leaves this gate pending. Run timestamps
and other execution metadata are outside the artifact comparison.

### Rejection

Change one recorded observed control while preserving the requested spec. Both
stage and metric verification must reject. Also reject a preset/settings mismatch,
an unknown policy version, missing version-3 observations, and an unsupported
operation under the reproducible policy. A legacy plan remains readable but
cannot pass the new policy-observation check.

## 10. Implementation order

1. Review and validate preset resolution in isolation ([EP-B0](#ep-b0-resolve-execution-settings)).
2. Integrate selection and immutable identity into authoring (EP-B1).
3. Add versioned persistence and legacy reading (EP-B2).
4. Observe and verify worker controls, including reuse (EP-B3).
5. Exercise CPU/CUDA acceptance and replace documentation boilerplate (EP-B4).

## 11. Master checklist

Each block ends with its focused gate and a reviewed task-scoped commit. All
requirements and blocks remain planned until their observing tests exist and
pass; the following test names are proposed, not executed evidence.

- [ ] [EP-B0](#ep-b0-resolve-execution-settings) — EP-00; phase 0, order 1; no dependencies; gate: `pytest -q tests/test_runtime_boundary.py -k execution_policy`.
- [ ] EP-B1 — EP-01; phase 1, order 1; depends on EP-00; gate: `pytest -q tests/test_authoring.py -k execution_policy`.
- [ ] EP-B2 — EP-02; phase 2, order 1; depends on EP-01; gate: `pytest -q tests/test_authoring.py -k policy_persistence`.
- [ ] EP-B3 — EP-03, EP-04; phase 3, order 1; depends on EP-02; gate: `pytest -q tests/test_process_startup.py tests/test_runtime_boundary.py tests/test_benchmark_execution.py -k execution_policy`.
- [ ] EP-B4 — EP-05; phase 4, order 1; depends on EP-03 and EP-04; gate: `pytest -q tests/test_documentation.py tests/test_live_process_startup.py -k execution_policy` on CPU and a supported CUDA host, with retained receipts.

In guided implementation, the user applies the reviewed edits and runs the
working-tree checks; Codex prepares each next block from the observed result. CUDA access is an external prerequisite
for EP-B4 closure, not permission to mark a skipped test complete. Source discovery
convenience, multiprocess/multi-GPU support and continuous control enforcement are
outside this contract.

## 12. Contract-owned PairBlocks

| Block | Requirements and dependencies | Owner and proposed observing tests |
|---|---|---|
| [EP-B0](#ep-b0-resolve-execution-settings) | EP-00; none | `runtime.py`; separate strict/relaxed tests, independent parallelism, saved settings, custom-copy, invalid-custom and unknown-name tests in `tests/test_runtime_boundary.py`. |
| EP-B1 | EP-01; EP-00 | `authoring.py`, `runtime.py`; `test_execution_policy_default`, `test_execution_policy_relaxed_precision`, `test_execution_policy_custom`, `test_execution_policy_expand` in `tests/test_authoring.py`. |
| EP-B2 | EP-02; EP-01 | `authoring.py`, `runs.py`, serialization/schema readers; `test_policy_persistence_roundtrip`, `test_policy_persistence_replay`, `test_policy_persistence_legacy`, `test_policy_persistence_unknown_version` in `tests/test_authoring.py`. |
| EP-B3 | EP-03 and EP-04; EP-02 | Worker/runtime/verifier/reuse owners; `test_execution_policy_observes_controls`, `test_execution_policy_rejects_tampering`, `test_execution_policy_metric_controls`, `test_execution_policy_reuse` in `tests/test_process_startup.py`; `test_execution_policy_unsupported_operation` in `tests/test_runtime_boundary.py`; `test_execution_policy_preserves_byte_comparison` in `tests/test_benchmark_execution.py`. |
| EP-B4 | EP-05; EP-03, EP-04 | Documentation/examples; `test_execution_policy_complete_examples` in `tests/test_documentation.py`, `test_execution_policy_cpu_repetition` and `test_execution_policy_cuda_repetition` in `tests/test_live_process_startup.py`. |

Traceability assessment: every requirement has an owner and proposed observing
tests. None has implementation completion evidence. Before closing each block,
inspect the resulting diff and retain the actual test node IDs, command result,
commit, and any CPU/CUDA receipt locations in the adjacent manifest. Zero selected
tests, skipped CUDA execution, and configuration-only mocks cannot close EP-B4.

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
<!-- pair-code-end: EP-B0 -->

The Python blocks are the authoritative proposed code for EP-B0. Each has an
exact insertion or replacement instruction; neither target needs another
propagation edit to compile. The explicit string `optimized` in the rejection
test checks that the retired selection is rejected.

**Validation:** The first block is now applied in the active checkout. Its
Python blocks match the runtime declarations and test file. Focused runtime tests,
Ruff and Pyright validate this block; authoring integration and the fresh-process
verification acceptance case remain pending in EP-B1 through EP-B4.

**Stop:** Review the applied EP-B0 changes before starting EP-B1. The commands
below check this block; a failure returns it to editing.

```bash
source .venv/bin/activate
python -m ruff check src/viper/runtime.py tests/test_runtime_boundary.py
python -m pyright src/viper/runtime.py tests/test_runtime_boundary.py
python -m pytest -q tests/test_runtime_boundary.py -k execution_policy
```

The remaining blocks above have no execution-ready code yet. Prepare EP-B1 from
the applied EP-B0 result; do not treat later test names as passing checks.

## 13. ContractTarget

Allowed action: modify the existing owner modules and their direct schema/reader
consumers within [src/viper](../../src/viper), add focused tests in the files named
above, and revise the listed user documentation/examples. EP-B0 owns preset
resolution; EP-B1 owns authoring selection;
EP-B2 owns persistence; EP-B3 owns application and verification; EP-B4 owns complete
examples and live acceptance. Any additional production owner must be traced and
added here before its block closes.

EP-B0 has complete Python code for both target files above. Later targets remain behavior and
scope declarations; their code will be prepared one block at a time. The
contract is the sole authoritative home of proposed edits.
