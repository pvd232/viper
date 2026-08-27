# Process startup

## Status

Runner-launched stages receive process-start environment variables and
run-wide library controls. Python and CLI execution use the same coordinator
and child-process path. Named NumPy generator initialization, delivery, and
persisted identity form one connected contract.

## Required claim

Every VIPER-governed stage callable executes in a child process whose start-time
environment and runtime controls derive from the frozen `RunSpec` and the
stage's effective environment.

## Implementation status

[`execute_stage_process()`](../../src/viper/stage_execution.py) derives environment
variables through `process_environment()` and supplies them when launching
`viper.stage_worker`. [`stage_worker.main()`](../../src/viper/stage_worker.py) then
applies library controls before executing the project script.

The public package supplies the decorated callable and
`viper.run(stage_callable)` interfaces. The worker records
`CPUBackendContext` for CPU stages and `CUDABackendContext` for CUDA stages.
The verifier applies `startup.backend` to backend kind, CUDA device count, and
CUDA model.

The designated L4 acceptance gate ran one CPU stage and one single-device CUDA
stage. The CPU stage recorded `CPUBackendContext`. The CUDA stage performed a
CUDA calculation and recorded the matching `CUDABackendContext` for one NVIDIA
L4. The complete Phase 1 VM gate passed 33 tests.

## Project interface

The project declares one stage callable:

```python
import viper


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    ...


if __name__ == "__main__":
    viper.run(train)
```

The user starts the program with ordinary Python execution:

```text
python train.py --run <run-spec> --stage train
```

During that initial invocation, `viper.run(stage_callable)` reads `--run` and
`--stage`, confirms that the callable represents the selected frozen stage, and
submits the run to the application coordinator. The coordinator follows the
complete order stored in `RunSpec.stages`. The stage argument binds the launched
callable to its stage specification. Each remaining stage is loaded from its
own frozen implementation reference.

The installed command supplies a whole-plan adapter:

```text
viper run <run-spec>
```

Both interfaces call the same application coordinator.

The Python form preserves a project's normal executable module. The CLI form
gives agents, CI jobs, and automation a generic complete-plan command.

## Startup sequence

The coordinator performs this sequence for each stage:

```text
load and verify RunSpec and selected stage spec
-> validate the decorated callable and parameter model
-> derive the start-time environment from RunSpec.reproducibility
   and the stage's effective environment
-> launch one child process with that environment
-> apply library-level controls inside the child
-> initialize the configured named NumPy generators
-> observe the host CPU and selected compute backend
-> construct the typed StageContext with those generator objects
-> invoke the decorated callable
-> write the invocation and runtime evidence
-> publish and verify the stage result
```

The start-time environment contains every control that the operating system,
Python interpreter, or numerical runtime consumes during process startup. The
current mapping includes `PYTHONHASHSEED`, `OMP_NUM_THREADS`,
`MKL_NUM_THREADS`, and the selected `CUBLAS_WORKSPACE_CONFIG`.

Python uses an integer `PYTHONHASHSEED` to fix hash randomization for the
process: [Python command-line and environment documentation](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONHASHSEED).

The child then applies the supported Python, NumPy, PyTorch, CUDA,
determinism, precision, and thread controls through
[`apply_reproducibility()`](../../src/viper/runtime.py).

## CPU and CUDA observation

The child process always records `CPUContext` because the CPU executes the
Python interpreter and submits accelerator work. `ExecutionContext.backend`
records the compute backend selected by the stage's effective environment.

```text
controlled child process
├── CPUContext
│   └── host CPU executing Python and PyTorch
└── ComputeBackendContext
    ├── CPUBackendContext for a CPU stage
    └── CUDABackendContext for a CUDA stage
```

The effective compute request selects the branch. CUDA availability confirms
that the selected branch can execute. This distinction lets a CPU stage remain
a CPU stage on a host that also contains a GPU.

The coordinator selects the device before launching the child:

```python
compute = effective_environment.compute
child_environment = process_environment(run.seed, run.reproducibility)

if compute.kind == "cuda":
    selected_device = select_cuda_device(model=compute.model)
    child_environment["CUDA_VISIBLE_DEVICES"] = str(selected_device.host_ordinal)

launch_child(environment=child_environment)
```

The child observes the resulting runtime:

```python
if compute.kind == "cuda":
    require_cuda_available()
    backend = observe_cuda_backend()
else:
    backend = CPUBackendContext()

execution_context = ExecutionContext(
    host=observe_host(),
    cpu=observe_cpu(),
    backend=backend,
    numerical_runtime=observe_numerical_runtime(),
)
```

The child records the controls it applied:

```python
class GeneratorInitializationReceipt(ProtocolModel):
    family: Literal[
        "python",
        "numpy_generator",
        "numpy_legacy",
        "torch_cpu",
        "torch_cuda",
    ]
    seed: RNGSeed
    name: HumanId | None = None
    device_index: int | None = Field(default=None, ge=0)
    state_sha256: SHA256


StartupVariable = Literal[
    "CUBLAS_WORKSPACE_CONFIG",
    "CUDA_VISIBLE_DEVICES",
    "MKL_NUM_THREADS",
    "OMP_NUM_THREADS",
    "PYTHONHASHSEED",
]


class ProcessStartupReceipt(ProtocolModel):
    environment: dict[StartupVariable, str]
    reproducibility: ReproducibilitySpec
    generators: tuple[GeneratorInitializationReceipt, ...]
```

`environment` contains the allowlisted startup variables derived by
`process_environment()`. The child reads those values from its own environment.
After `apply_reproducibility()` returns, the child queries the supported
PyTorch controls and thread counts and records them in `reproducibility`. Each
generator receipt contains the frozen run seed and a digest of that generator's
state immediately after initialization.

Each configured NumPy generator produces one `numpy_generator` receipt whose
`name` equals its key in `NumPyRandomnessSpec.generators`. The optional legacy
global generator produces one `numpy_legacy` receipt. A CUDA generator receipt
uses `device_index`. `name` is present exactly for `numpy_generator`, and
`device_index` is present exactly for `torch_cuda`.

The DataLoader state enters the training `resume_state` artifact at a checkpoint
boundary. A future runner-owned DataLoader construction contract can add a
startup receipt for a dedicated loader generator.

`apply_reproducibility()` returns the named NumPy generator objects it creates.
The child wraps that name-to-object mapping in a read-only mapping and assigns
it to `StageContext.numpy_generators`. The stage callable therefore receives the
same generator objects the child hashed for the `numpy_generator` receipts.

`StageContextBinding.numpy_generator_names` stores the sorted names from
`NumPyRandomnessSpec.generators`. The binding carries generator identity across
the process boundary. `ProcessStartupReceipt.generators` carries each
generator's initialized-state digest. The child constructs the runtime mapping
with exactly those names before invoking the stage callable.

The child owns the join:

```python
named_generators, generator_receipts = apply_reproducibility(run_controls)

if tuple(sorted(named_generators)) != binding.numpy_generator_names:
    fail_startup("startup.context")

context = StageContext(
    run_id=binding.run_id,
    attempt_id=binding.attempt_id,
    stage_id=binding.stage_id,
    params=params,
    inputs=resolve_paths(binding.inputs, workspace),
    artifacts=resolve_paths(binding.artifacts, workspace),
    metrics=metric_handles,
    numpy_generators=MappingProxyType(named_generators),
)
```

The worker hashes each value in `named_generators` to construct its
`GeneratorInitializationReceipt`, then passes that same mapping to
`StageContext`. A name mismatch ends startup before callable invocation and
produces a failed invocation receipt.

For a CUDA stage, the coordinator selects one device whose model satisfies the
frozen `CUDAComputeSpec`. `CUDA_VISIBLE_DEVICES` exposes that device to the
child before process startup. The child constructs `CUDABackendContext` from
the exposed device, the NVIDIA driver, the PyTorch CUDA build, and cuDNN. The
existing resolved-stage validator compares the observed backend kind, device
count, and device model with the effective compute request.

NVIDIA defines `CUDA_VISIBLE_DEVICES` as the pre-start control for which devices
a CUDA application can see and how CUDA enumerates them:
[CUDA environment variables](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html#cuda-visible-devices).

VIPER 0.1 governs one host process and one selected CUDA device per stage.
Preflight rejects a CUDA request whose `count` exceeds `1` with
`startup.distributed`. NVIDIA defines a CUDA context as the device
execution state made current to a host thread; the host process submits kernels
through that context: [CUDA Driver API](https://docs.nvidia.com/cuda/cuda-programming-guide/03-advanced/driver-api.html#context).

## Direct-script boundary

Ordinary Python execution imports the project module before its `__main__`
block calls `viper.run(stage_callable)`. A conforming stage module limits its
import phase to imports, definitions, and decorator registration. Data access,
accelerator initialization, model construction, and training occur inside the
decorated callable.

The coordinator launches that callable in the controlled child process. The
child receives `VIPER_CONTEXT_PATH`, which identifies one versioned context
document containing the run, attempt, stage, and path bindings. Absence of
`VIPER_CONTEXT_PATH` selects coordination mode. A coordinator-launched child
validates the context document and invokes the callable exactly once.

VIPER's execution claim begins with the controlled child process. The initial
module import performed by `python train.py` belongs to trusted project setup in
0.1. The installed `viper run` command starts coordination before importing a
project stage module.

## Persisted evidence

`ResolvedBaseSpec` stores `ProcessStartupReceipt` and the stage invocation
reference defined by
[Stage invocation](STAGE_INVOCATION.md). The resolved stage also stores the
`ExecutionContext` observed inside the child process.

The receipt binds the callable identity and typed context to one process
outcome. `ExecutionContext.cpu` records the host CPU.
`ExecutionContext.backend` records the selected CPU or CUDA backend.
`ExecutionContext.numerical_runtime` records the language and numerical-library
versions active in the child.

## Verification

| Check | Rule |
|---|---|
| `startup.plan` | The child context identifies the frozen run and selected stage. |
| `startup.environment` | The values read by the child equal the canonical allowlisted mapping derived from the run controls and effective stage environment. |
| `startup.controls` | The controls queried after application equal `RunSpec.reproducibility`. |
| `startup.randomness` | The named generator receipts and `StageContextBinding.numpy_generator_names` match `NumPyRandomnessSpec.generators`. Every generator receipt contains `RunSpec.seed` and its initialized-state digest. |
| `startup.callable` | The child invokes the exact decorated callable frozen by the stage spec. |
| `startup.context` | The callable receives the typed context bound to the selected stage. Its `numpy_generators` mapping contains the exact initialized objects named by the binding. |
| `startup.runtime` | The resolved stage contains the host CPU and numerical runtime observed inside the child. |
| `startup.backend` | The observed backend kind equals the effective compute kind. A CUDA backend contains one device whose model equals the frozen request, plus the observed driver, PyTorch CUDA, and cuDNN versions. |
| `startup.distributed` | A CUDA request with `count` greater than `1` fails preflight and directs the run to the future distributed-execution contract. |
| `startup.outcome` | One successful resolved stage contains one successful child-process receipt. |

## Propagation

| Surface | Required change |
|---|---|
| Public package | Export stage decorators, typed contexts, and `viper.run`. |
| Application | Expose one host-neutral complete-run coordinator. |
| Worker | Load the frozen callable and invoke it with the typed context. |
| Stage execution | Use the same child-process startup path for Python and CLI callers. |
| Runtime | Select the compute backend from the effective environment and observe the host CPU plus the selected CPU or CUDA backend. |
| Persistence | Store the applied startup receipt, generator names, invocation reference, CPU, compute-backend, and numerical-runtime evidence on the resolved stage. |
| Verification | Apply the ten startup checks above. |
| Tests | Exercise direct Python execution, CLI execution, named generator delivery, start-time controls, one invocation, CPU execution on a GPU-capable host, one CUDA device, and a multi-device rejection. |

## Acceptance case

`TrainSpec.params.epochs` equals `3`. The user runs `python train.py` with the
frozen run path and stage ID. The coordinator starts a controlled child, the
decorated function receives `TrainParameters(epochs=3)`, and the resolved stage
records the child environment, callable identity, context digest, and successful
outcome.

The same stage configures a named `augmentation` generator. The callable
retrieves `context.numpy_generators["augmentation"]` and draws its first value.
The initialized-state digest in `ProcessStartupReceipt` belongs to that named
generator. Omitting `augmentation` from the runtime context fails
`startup.context`; changing its configured name or receipt fails
`startup.randomness`.

The rejection case changes the child context to another stage ID. The
`startup.plan` check rejects the invocation before the project callable runs.

A CUDA case selects `CUDAComputeSpec(model="NVIDIA L4", count=1)`. The
coordinator exposes one matching L4 to the child. The resolved stage contains
the host `CPUContext` and a `CUDABackendContext` for that L4. The
`startup.backend` check accepts the backend. A request with `count=2` fails
`startup.distributed` during preflight.

## Deferred contract: multi-GPU distributed execution

Multi-GPU distributed training introduces several coordinated child processes.
The future contract will bind each rank to one device, initialize one process
group, persist rank-local runtime and replay state, and verify collective
membership before accepting the distributed stage result. PyTorch's
`DistributedDataParallel` documentation recommends one process per GPU and
requires each process to operate on its assigned device:
[DistributedDataParallel](https://docs.pytorch.org/docs/stable/generated/torch.nn.parallel.DistributedDataParallel.html).

## Implementation order

1. Add the stage decorators and callable metadata.
2. Add the direct `viper.run(stage_callable)` adapter.
3. Generalize the application coordinator and CLI command to `run`.
4. Invoke every callable through the controlled child-process path.
5. Return the configured named NumPy generators from control application and
   bind them to `StageContext`.
6. Select the effective compute backend and observe the host CPU plus the CPU or
   CUDA backend inside the child.
7. Persist and verify the startup evidence.
8. Add direct-Python, CLI, CPU, and single-GPU acceptance tests for the same
   frozen run.
