# How VIPER works

VIPER turns one Python experiment into evidence that connects what was planned,
what ran, and what was produced. This page follows the repository's checked CPU
example through that complete path.

## Executed example

The example is [`examples/cpu_quickstart.py`](../../examples/cpu_quickstart.py).
Its acceptance test runs the file in a clean Git repository and observes:

```text
status: succeeded
model: {"weight": 1.999...}
result: experiments/cpu_quickstart/runs/baseline/<run-id>/resolved.yaml
```

That observation is established by
[`test_cpu_quickstart_executes_and_verifies_one_run()`](../../tests/test_readme_workflow.py).
The rest of this page explains how VIPER produces it.

## Cast

| Object | Role in this run |
| --- | --- |
| `training_loss` | Gives the recorded scalar a stable metric ID. |
| `fit` | Reads the dataset, trains the model, records loss, and writes artifacts. |
| `training` | Connects `fit` to its parameters, inputs, outputs, metric, and objective. |
| `study` | Names the variant graph and reproducible seed. |
| `draft` | Selects one variant and replicate plus exact source, environment, and reproducibility settings. |
| `result` | Returns the verified terminal run and its stored path. |

## Execution trace

```text
Python declarations
        |
        v
RunPlanDraft tied to a Git commit
        |
        v
canonical run and stage files
        |
        v
preflight -> stage attempt -> artifacts and measurements
        |
        v
terminal verification
        |
        v
RunResult + resolved.yaml
```

### 1. Python declares the intended work

The decorated `fit()` function remains ordinary project code. The call to
[`stage()`](../../src/viper/authoring.py) adds the information execution needs:
which inputs may be read, which artifacts may be written, which metric IDs may
be recorded, and which objective is attached to the stage.

The stage receives those values through [`Context`](../../src/viper/stages.py).
For the quickstart:

```python
@train(params=params.Train)
def fit(context: Context[params.Train]) -> None:
    model = context.artifacts["model"]
```

- `context.inputs["dataset"]` is the materialized CSV path;
- `context.artifacts["model"]` and `context.artifacts["state"]` are writable
  paths declared before execution;
- `context.metrics["training_loss"]` is the handle authorized to record loss.

The function reads the CSV, performs gradient descent, records twenty loss
values, then writes the model and checkpoint. VIPER does not implement that
scientific computation.

### 2. `plan()` fixes the selected experiment

[`plan()`](../../src/viper/authoring.py) selects one experiment, variant, and
replicate. It also records the source repository and Git commit, local runtime
and lockfile, deterministic execution settings, and a new run ID.

The returned `RunPlanDraft` is detached from later mutation of caller-owned
lists and dictionaries. It is still a Python object, not yet the persisted run
protocol.

### 3. `execution.run()` compiles before executing

[`execution.run()`](../../src/viper/execution/__init__.py) accepts either a
`RunPlanDraft` or a path to an already frozen plan. With a draft, it first calls
the internal plan compiler. That compiler resolves Python
functions and parameter models to their source files and digests, resolves
input and artifact references, and writes canonical run and stage documents.

The same call then executes the stored plan. This is why the public workflow is
`plan() -> execution.run()` rather than a separate user-visible freeze step.

### 4. Preflight rejects work that cannot satisfy the plan

Before the stage starts, VIPER checks the frozen files and the selected local
runtime. It rejects a changed or missing source file, invalid input identity,
unsupported environment, or inconsistent plan relationship before treating
the stage as executable.

### 5. The stage attempt records observed work

The runner creates a durable attempt and starts the stage worker. The worker
loads the exact declared function, constructs its `Context`, and invokes it.
During the call, metric records are written through the declared handle,
artifact writes land at declared paths, and the attempt journal records durable
state transitions.

After the function returns, VIPER hashes the produced bytes and records their
paths and sizes. A successful Python return alone does not establish a
successful VIPER run.

### 6. Verification closes the run

Terminal verification reconnects the observed attempt to the frozen plan. It
checks that required stages completed, declared artifacts exist with recorded
identities, measurements belong to declared metrics, and the terminal record
references one coherent run. Only then does the returned result report
`status: succeeded`.

## What persists

| Question | Recorded evidence |
| --- | --- |
| Which code was selected? | Repository, commit, source path, symbol, byte count, and digest. |
| Which data entered the stage? | Materialized input references and their recorded identities. |
| Which runtime was requested and observed? | Environment, compute, reproducibility, and startup records. |
| What did the stage produce? | Artifact and measurement files with paths, sizes, and digests. |
| Which attempt completed the run? | Attempt journal, resolved stages, and terminal reference. |

This evidence supports later [restore and comparison](../how-to/retry-restore-compare.md),
[catalog searches](../how-to/catalog-knowledge-mcp.md), and independent
benchmark confirmation.

## Boundaries

VIPER verifies the identities and relationships represented by its protocol.
It does not prove that a model is scientifically correct, that a dataset is
unbiased, or that a metric answers the right research question. Those judgments
remain with the experiment author and reviewer. See
[What VIPER guarantees](guarantees.md) for the exact boundary.

VIPER `0.1.0a2` is available from PyPI. The
[release report](../releases/0.1.0a2.md) records the published files, source
identity, and validation evidence.
