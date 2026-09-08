# VIPER protocol

The VIPER protocol connects an intended experiment to one observed execution
and its terminal result. This page defines the stable record roles and the
relationships verification checks. Use the installed JSON Schemas for exact
fields.

## Record graph

```text
Git source + experiment selection + runtime request
                         |
                         v
                RunSpec + stage specs
                         |
                         v
                 one or more attempts
                         |
                         v
      resolved stages + artifacts + measurements
                         |
                         v
                    ResolvedRun
```

The authored Python objects are not protocol evidence by themselves. The
compiler resolves them into canonical records before execution.

## Core acceptance relation

Let \(P\) be one frozen plan, \(A\) one successful attempt, \(O\) the observed
outputs, and \(R\) the terminal run. Acceptance requires:

```math
\operatorname{Accept}(R)
\Rightarrow
\operatorname{PlanOf}(A)=P
\land
\operatorname{OutputsOf}(A)=O
\land
\operatorname{AttemptOf}(R)=A
\land
\operatorname{PlanOf}(R)=P.
```

Every separately stored record in that relation is checked by content identity,
not by path alone.

## Exact file identity

A file reference records:

- where the bytes are stored;
- the byte count;
- the SHA-256 digest of those bytes.

Verification accepts referenced bytes \(b\) only when:

```math
|b|=n
\land
\operatorname{SHA256}(b)=h,
```

where \(n\) and \(h\) are the recorded count and digest. Storage revisions add
the identity of the immutable publication that owns the path.

## Run plan

`RunSpec` records the complete request for a run. It selects the experiment
variant and replicate, source revision, runtime, reproducibility settings,
estimator output, optional benchmark, and stages in execution order.

Each stage record gives VIPER the information it needs to execute and verify
that stage:

- the stage kind;
- the workspace function and config class, each tied to its exact source;
- the validated config values;
- the inputs to read and outputs to write;
- the metrics to record and, when applicable, the objective;
- any stage-specific runtime or reuse policy.

The source models live in [`viper.runs`](../../src/viper/runs.py),
[`viper.stages`](../../src/viper/stages.py), and
[`viper.authoring`](../../src/viper/authoring.py).

## Inputs and dependencies

An internal stage input has one of three origins:

| Input record | Meaning |
| --- | --- |
| `ExternalInputRef` | Repository-owned bytes captured for this plan. |
| `FutureInputRef` | An artifact that an earlier stage in the same plan must produce. |
| `StoredInputRef` | An immutable artifact pointer from a verified prior run. |

HTTP requests belong to a download stage. The request fixes the expected body
identity; the retrieval receipt records what the server returned and the
artifact preserves the accepted bytes.

## Outputs, artifacts, and measurements

Before execution, an output declaration tells VIPER where the stage will write
a file or directory, how to load it, and what role its data serves. After the
stage finishes, an artifact record identifies the bytes written there.

A measurement belongs to a declared metric ID and stage. A stateless metric
computes one value from its current arguments or declared files. A stateful
metric accumulates observations through `update()` and reports its current
value through `compute()`.

Objectives select whether a metric should be minimized or maximized. Benchmark
criteria separately state whether a confirmed metric must be at least or at
most a threshold.

## Attempts and terminal runs

Execution appends durable attempt-state records. A retry creates another
attempt for the same frozen plan; it does not mutate the plan.

One terminal `ResolvedRun` is `succeeded`, `failed`, or `cancelled`. A succeeded
run names exactly one successful attempt. Verification rejects a terminal
record whose attempt, stage, artifact, measurement, source, or plan references
do not close over the same run.

## Environment and reproducibility

The plan records a requested local or GCE environment plus run-wide controls
for deterministic algorithms, precision, parallelism, and random generators.
Execution records the realized environment and process startup state.

These records show what VIPER requested and observed. They do not claim that
uncontrolled hardware, third-party libraries, or external services are
universally deterministic.

## Verification boundaries

| Boundary | What it checks |
| --- | --- |
| Plan | Referenced stage files, source identity, ordering, and cross-record IDs. |
| Resolved stage | Inputs, runtime observations, produced artifacts, and measurements match the stage declaration. |
| Attempt | Stage results and durable state transitions belong to one attempt. |
| Terminal run | One coherent plan and terminal attempt support the reported status. |
| Benchmark | Fixed prior-run inputs, metric confirmations, criteria, and benchmark result agree. |
| Restore | Retrieved bytes match the recorded artifact before destination replacement. |

The implementation is under [`viper.verification`](../../src/viper/verification/)
and [`viper.execution`](../../src/viper/execution/).

## Schema discovery

Ask the installed package for the exact current schema:

```bash
viper --json schema RunSpec
viper --json schema ResolvedRun
viper --json schema Spec
```

List every available schema and operation:

```bash
viper --json capabilities
```

These commands read the schemas from the installed package, so this page does
not duplicate field-by-field model definitions. See the [Python API](api.md)
for authoring interfaces and [What VIPER guarantees](../explanation/guarantees.md)
for the checks applied to a completed run.
