# README workflow startup observations

The initial README module run failed before its repaired artifact assertions:
`examples.variants` exceeded the original 240-second child-process budget. Saved
worker receipts showed 4–7 seconds per stage invocation, with longer intervals
before worker entry and between runs. See the [original failure](original-240s-failure.txt).

A separate diagnostic ran the same four-plan, two-concurrent example in a fresh
copy of its temporary source repository. A scratch `sitecustomize.py` recorded
all Python threads every five seconds in the controller and child interpreters.
The diagnostic intentionally terminated its own process tree after 60 seconds.
It is neither a successful experiment nor a baseline wall-time comparison.

The [command record](command.json) preserves the interpreter, source workspace,
start time, 60.33-second elapsed time, and terminated process IDs. The exact
[trace driver](trace-driver.txt) ran with the project `.venv` active:

```bash
python /tmp/viper_readme_trace.py
```

Observed frames:

- [Controller](controller-stack.txt): initial Torch import, repeated Git commands,
  then both executor threads waiting for isolated configuration validation and
  stage execution.
- [Configuration worker](config-stack.txt): `serialization` → `stages` → `metrics`
  → `runtime` → Torch import and meta registration.
- [Stage worker](stage-stack.txt): Torch meta registration followed by Dynamo and
  Inductor imports before callable entry.

The defining callers validate each stage during preflight and again before
execution. Four two-stage plans therefore start sixteen configuration workers
and eight stage workers. No SQLite, fsync, or deletion-lock wait appeared in this
sample; the sample does not exclude such work at other times. No production
source or numerical behavior changed for this diagnostic.

The next module run used `-vv -x --tb=short --durations=10`. The variants case
passed in 210.84 seconds under an interim 480-second aggregate budget, including
all four model results and both distinct weights. Evaluation then exceeded its
unchanged 240-second budget before reaching the repaired artifact assertions.
The module stopped with one pass and one failure. See the
[raw output](rerun-variants-pass-evaluation-timeout.txt) and
[JUnit report](rerun-variants-pass-evaluation-timeout.xml).

The evaluation-only diagnostic retained its source workspace and sampled all
Python threads every ten seconds. It kept the original 240-second bound and
terminated only its own process tree. Its [journal timeline](evaluation/journals.json)
shows the first two-stage attempt closing at 71.91 seconds, the second attempt
closing at 174.39 seconds, and independent benchmark confirmation starting at
224.13 seconds. The [controller samples](evaluation/controller-stack.txt) show
isolated configuration, stage, artifact-loader verification, and metric workers.
The [metric worker sample](evaluation/metric-stack.txt) shows deterministic
runtime initialization importing Torch Dynamo and Inductor. See the
[command record](evaluation/command.json),
[exact driver](evaluation/trace-driver.txt), and
[diagnostic outcome](evaluation/diagnostic-output.txt). The bounded diagnostic
is not an acceptance pass or a baseline performance comparison.

Complete extended example programs now share a 600-second aggregate budget.
Journal search keeps its existing derived budget. The individual 120-second
helper limits and all numerical, verification, reuse, replay, and corruption
assertions remain unchanged. The remaining fifteen execution cases run with
an explicit temporary root so later pytest cleanup cannot erase their records.
Their final result, rather than these samples, must establish acceptance.

Eleven direct documentation and source checks passed in 14.95 seconds. The
sixteen example, quickstart, and policy workflow cases were deselected. See
[raw output](direct-doc-checks.txt) and [JUnit report](direct-doc-checks.xml).
The exact command was:

```bash
python -m pytest tests/test_readme_workflow.py -q \
  -k 'not extended_examples and not cpu_quickstart and not policy_example' \
  --basetemp=/tmp/viper-readme-doc-checks-20261125 \
  --junitxml=/tmp/viper-readme-doc-checks.xml
```

The final fifteen execution cases passed in 2191.20 seconds. See the
[exact command](remaining-execution-command.json),
[raw output](../readme-final15.log), and [JUnit report](../readme-final15.xml).
Evaluation took 328.31 seconds of call time, stages 241.87 seconds, and
inspection 234.48 seconds. Every original numerical, reuse, restore, checkpoint,
runtime-control, and corruption assertion passed. Individual 120-second child
limits remained unchanged. The complete [success union](successful-nodes.json)
contains all 27 distinct README nodes: the previously passing variants case,
eleven direct checks, and these fifteen execution cases. This is combined
evidence from bounded invocations, rather than a claim that the earlier failed
full-module runs passed.

During the final run, one inaccurate comment was corrected from “stored
artifact, rather than the mutable workspace copy” to “managed payload returned
by the resolver.” Replacing that comment in the final file reconstructs the
exact source SHA-256 saved before the run. The Python AST is identical, ignoring
source positions. The success manifest records both hashes and this comparison;
no executable behavior changed during the final run.
