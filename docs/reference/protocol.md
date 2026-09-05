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

## Frozen plan

`RunSpec` identifies one experiment, variant, replicate, source revision,
environment, reproducibility specification, estimator artifact, optional
benchmark, and ordered set of stage specifications.

Each stage specification declares:

- one stage kind;
- the project implementation and parameter model selected by exact source
  identity;
- parameter values;
- input references;
- artifact declarations;
- metric IDs and, where required, an objective;
- an optional stage-specific environment and reuse policy.

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

## Artifacts and measurements

An artifact declaration reserves a file or bundle path, loader, and data role.
A resolved artifact replaces that declaration with the observed files and their
exact identities.

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

This keeps exact field definitions synchronized with the installed code instead
of copying Python model declarations into prose. The [Python API](api.md) names
the authoring interfaces, and [What VIPER guarantees](../explanation/guarantees.md)
states the claim boundary in reader-facing terms.

## Historical formalism

The original model-family, estimator, training-transition, and DataLoader/RNG
formalism is retained for maintainers in
[Archived foundational reproducibility formalism](../internal/foundational-reproducibility-formalism.md).
It is design history, not current field reference.
