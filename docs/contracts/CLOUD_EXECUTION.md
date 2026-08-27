# Cloud execution

## Status

Implemented for VIPER 0.1. The runner executes frozen plans on a
pre-provisioned GCE instance, records the immutable provisioning source and
realized runtime, and verifies both against the effective stage environment.

## Required claim

VIPER executes a frozen run on the host where the user invokes it and verifies
that each realized stage environment satisfies the effective
`GCEEnvironmentSpec`.

## Implemented path

[`GCEEnvironmentSpec`](../../src/viper/protocol.py) fixes the requested host,
provisioning source, compute backend, lockfile, and installed Python
environment. [`observe_execution()`](../../src/viper/runtime.py) selects the local
or GCE observer from that effective environment. The GCE observer constructs
[`GCEHostContext`](../../src/viper/protocol.py), the CPU context, the selected CPU or
CUDA backend context, and the numerical runtime context.

[`run()`](../../src/viper/runner.py) resolves each stage's effective environment,
launches the stage on the active host, and stores
[`ResolvedGCEEnvironment`](../../src/viper/protocol.py) with the observed execution
context. [`verify_run_result()`](../../src/viper/verifier.py) checks the complete
requested, resolved, and observed relationship before returning success.

GCE supports two provisioning sources used by this project. A VM created from
a boot image exposes that source through `instance/image`. A VM restored from a
machine image has an empty `instance/image` value because machine-image restore
leaves `disks.sourceImage` empty. The provisioning contract must represent
both sources: [Machine images](https://docs.cloud.google.com/compute/docs/machine-images),
[machine-image restore limitations](https://docs.cloud.google.com/compute/docs/machine-images/create-machine-images#instance-and-disk-properties-not-supported-by-machine-image),
and [VM metadata](https://docs.cloud.google.com/compute/docs/metadata/querying-metadata#querying).

## Execution location

The user provisions and enters the execution host with their normal
infrastructure tools. VIPER begins inside that host.

```text
local workstation
└── python train.py --run <run-spec> --stage train

GCE terminal
└── python train.py --run <run-spec> --stage train
```

The same Python interface operates in both locations. The whole-plan command
uses the same application operation:

```text
viper run <run-spec>
```

The Python form preserves the project's ordinary stage entrypoint. The CLI
form gives agents, CI jobs, and automation one project-independent command.
Both forms execute the complete ordered plan. In the Python form, `--stage`
binds the launched callable to its frozen stage specification.

VIPER derives the host kind from the effective stage environment and observed
runtime. The user's infrastructure tooling owns VM provisioning, terminal
access, source placement, and cloud-resource lifecycle.

## Environment selection

The protocol defines one tagged provisioning-source union:

```python
class GCEBootImageRef(ProtocolModel):
    kind: Literal["boot_image"] = "boot_image"
    project: NonEmptyStr
    name: NonEmptyStr
    id: NonEmptyStr


class GCEMachineImageRef(ProtocolModel):
    kind: Literal["machine_image"] = "machine_image"
    project: NonEmptyStr
    name: NonEmptyStr
    id: NonEmptyStr


GCEProvisioningRef = Annotated[
    GCEBootImageRef | GCEMachineImageRef,
    Field(discriminator="kind"),
]


class PythonDistributionSpec(ProtocolModel):
    name: NormalizedDistributionName
    version: NonEmptyStr


class PythonEnvironmentSpec(ProtocolModel):
    python_version: NonEmptyStr
    distributions: tuple[PythonDistributionSpec, ...] = Field(min_length=1)
```

Distribution names use lowercase form with each run of `.`, `_`, or `-`
replaced by `-`. The distribution tuple is sorted by name and contains one
entry per name. This follows the Python packaging name-normalization rule:
[Name normalization](https://packaging.python.org/en/latest/specifications/name-normalization/).

`GCEEnvironmentSpec.provisioning` and
`ResolvedGCEEnvironment.provisioning` carry this value. The author selects the
server-defined resource ID before freezing. Plan freezing preserves that
immutable selection.

For a boot-image VM, VIPER reads the project and name from `instance/image`,
then retrieves the resource ID with `images.get`. For a machine-image VM, the
provisioner writes the selected kind, project, name, and ID into the reserved
`viper-provisioning-*` instance metadata keys. VIPER retrieves the named machine
image through `machineImages.get` and requires the API resource ID to equal the
metadata value. VIPER compares the observed provisioning reference with the
frozen selection: [Compute Engine `images.get`](https://docs.cloud.google.com/compute/docs/reference/rest/v1/images/get)
and [Compute Engine `machineImages.get`](https://docs.cloud.google.com/compute/docs/reference/rest/v1/machineImages/get).

The machine-image metadata keys form a provisioner attestation under the 0.1
trusted-host boundary. They establish which immutable machine-image resource
the provisioner selected. The resulting instance and restored disk expose
their realized disk identity, so the provisioner supplies the source-machine-
image identity through these keys.

`GCEEnvironmentSpec.python_environment` stores the exact Python version and
the sorted installed-distribution mapping selected by the author. VIPER exposes
an environment-observation helper for authoring. Plan freezing validates the
selected value. The child reconstructs the same mapping through Python package
metadata and stores it as `ResolvedGCEEnvironment.python_environment`.

The lockfile reference identifies the environment-construction input. The
Python environment value constrains the distributions that actually execute
the stage. `ExecutionContext.numerical_runtime` continues to record PyTorch,
NumPy, BLAS, LAPACK, CUDA, and thread-pool facts used by numerical execution.

For each stage, the stage environment override supplies the selected
environment when present. `RunSpec.environment` supplies the selected
environment for every remaining stage.

When the selected value is `GCEEnvironmentSpec`, the runtime observer reads the
instance metadata and numerical runtime from the active VM. Compute Engine
exposes instance metadata from a server available to the instance:
[View and query VM metadata](https://docs.cloud.google.com/compute/docs/metadata/querying-metadata).

The observer constructs:

```text
ResolvedGCEEnvironment
├── immutable provisioning-source identity
├── machine type
├── CPU or CUDA compute request
├── resolved lockfile identity
└── resolved Python environment

ExecutionContext
├── GCEHostContext
│   ├── instance project
│   └── observed provisioning-source identity
├── CPUContext
├── CPUBackendContext or CUDABackendContext
└── NumericalRuntimeContext

ProcessStartupReceipt
├── applied startup environment
├── queried reproducibility controls
└── initialized generator-state digests
```

The [process-startup contract](PROCESS_STARTUP.md) applies the run-wide controls
before the stage callable executes.

## Persisted evidence

Each resolved stage stores its `ResolvedGCEEnvironment` and `ExecutionContext`.
The ordinary attempt journal, stage snapshots, artifacts, measurements, logs,
and terminal `resolved.yaml` remain in the repository's configured VIPER
workspace and store on the active host.

The application result returns the run ID, attempt ID, terminal result path,
and journal path. A later storage backend may publish the same immutable files
to durable object storage while preserving the execution contract.

## Verification

| Check | Rule |
|---|---|
| `environment.kind` | The resolved environment and observed host both identify GCE. |
| `gce.provisioning` | The observed provisioning kind, project, name, and server-defined ID equal the frozen request. |
| `gce.machine_type` | The resolved environment and observed host report the requested machine type. |
| `gce.compute` | The observed backend kind, CUDA model, and device count satisfy the frozen compute request. |
| `gce.lockfile` | The resolved lockfile points to the exact lockfile selected by the effective environment. |
| `gce.python` | The Python version and installed-distribution mapping observed by the child equal the frozen `python_environment`. |
| `runtime.controls` | The execution context records the run-wide determinism, precision, parallelism, and randomness controls. |
| `run.result` | The terminal result passes ordinary run verification. |

## Propagation

| Surface | Implemented mechanism |
|---|---|
| Protocol | `GCEProvisioningRef`, `PythonEnvironmentSpec`, and `ComputeSpec` define the requested environment. |
| Coordinator | Effective-environment selection governs each stage. |
| Preflight | Local and GCE plans are checked against the active host kind. |
| Runtime | The shared compute observer and GCE host observer produce the realized context. |
| Application | One `run` operation executes on the active host. |
| Python interface | `viper.run(stage_callable)` uses the shared coordinator and process-startup contract. |
| CLI | `viper run` calls the application `run` operation. |
| Verification | Eight named checks establish the completed environment relationship. |
| Tests | Local CPU, local CUDA, deterministic GCE, and live GCE cases exercise the contract. |

## Acceptance case

A frozen run selects a `GCEEnvironmentSpec` containing one machine image,
machine type, L4 accelerator, and lockfile. The user opens a terminal on the
matching VM and invokes the installed project entrypoint. VIPER executes the
run on that VM, records the GCE and CUDA evidence, publishes the terminal run,
and verifies every environment relationship.

A second case executes the same plan on a VM with another machine type. The
`gce.machine_type` check rejects the resolved stage. A third case changes one
installed distribution version and fails `gce.python`.

## Live acceptance evidence

On 2026-08-25, the public 0.1.0a1 wheel executed on `mantra-g2-spot`. Its
SHA-256 was
`7edbc6d36bf2d8226ddeab153411bfb531fbf79dd8d13979cc6fa2c188523fec`.
Python 3.14.5 imported VIPER from the installed wheel. Six live process and
stage checks passed on one NVIDIA L4 in 73.63 seconds. The generated project
then completed acquisition, the five-stage candidate, Python entrypoint,
benchmark confirmation, and verification under a frozen GCE environment in
282.71 seconds. The worker recorded machine-image ID
`4030260845309136958`, machine type `g2-standard-12`, the host and CPU context,
and the installed Python environment.

## Release boundary

VIPER 0.1 supports a trusted, pre-provisioned single host containing the frozen
source, credentials, dependency environment, accelerator software, workspace,
and artifact store. Each stage uses one CPU backend or one selected CUDA device.

The user's infrastructure tooling owns host provisioning and terminal access.
OCI confinement supplies filesystem and network enforcement in the stable
hardening release. Distributed execution and durable remote publication receive
separate contracts when their first implementations enter scope.

## Completed implementation sequence

1. Model immutable boot-image and machine-image identities.
2. Route Python and CLI execution through the host-neutral `run` operation.
3. Resolve the effective environment during preflight and stage execution.
4. Observe the GCE host, provisioning source, CPU, CUDA backend, and numerical
   runtime.
5. Verify each completed stage against its effective environment.
6. Exercise deterministic local and GCE cases.
7. Install the wheel and run the maintained acceptance case on the L4 profile.
