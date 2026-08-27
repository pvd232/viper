# Use VIPER in a project

VIPER fixes an experiment before execution and verifies the evidence produced by
each attempt. The same Python package runs on a workstation or inside an
already provisioned VM.

## Create the project source

Install the package, then generate the starter source tree:

```bash
python -m pip install viper-provenance
viper init my-project --package my_project
cd my-project
python -m pytest -q
```

The generated project contains one callable for each stage kind. VIPER accepts
any source layout. Frozen specifications identify each callable, parameter
class, metric, and artifact loader by repository-relative path and exact file
identity.

## Define a stage

A stage callable receives one typed context. Its parameter class belongs to the
project:

```python
from pydantic import Field

import viper
import viper


class TrainParameters(viper.parameters.Train):
    epochs: int = Field(gt=0)


@viper.train_stage(parameter_model=TrainParameters)
def train(context: viper.StageContext[TrainParameters]) -> None:
    dataset = context.inputs["dataset"]
    parameters = context.artifacts["parameters"]
    # Project training code reads dataset and writes parameters.
```

VIPER validates the frozen parameter mapping through `TrainingParameters`,
constructs the typed value in the stage worker, and supplies it as
`context.params`.

## Retrieve HTTP inputs

`DownloadSpec` fixes each request URL, expected body digest, expected byte
count, retrieval policy, and transport. The built-in `httpx` transport covers
ordinary HTTP requests. A project transport uses `@viper.http_transport` and
returns the response body and terminal response metadata through the same
contract.

The download callable reads verified bodies from `context.retrievals`. Runtime
credentials arrive through authorized environment references and stay outside
persisted protocol documents.

## Declare artifacts and metrics

Each artifact declaration fixes its logical name, output path, data-use role,
and loader. Training reserves `parameters` and `resume_state`. Evaluation
reserves `predictions` while leaving its file format to the project.

A metric is a decorated function or stateful class. Recomputed metrics run in a
dedicated verification worker from the frozen implementation, verified inputs,
and frozen parameters. Live training metrics write measurements through the
stage context.

## Freeze and run

Commit the project source before freezing a plan. `RunSpec.source.commit` fixes
the implementation source. The Git revision containing the plan fixes the
authored protocol files.

```bash
viper freeze-run path/to/draft.yaml --repository-root .
viper preflight path/to/run/spec.yaml --repository-root .
viper run path/to/run/spec.yaml --repository-root .
```

Project code can start the same complete-run coordinator through ordinary
Python:

```python
if __name__ == "__main__":
    viper.run(train)
```

```bash
python path/to/train.py \
  --run path/to/run/spec.yaml \
  --stage train \
  --repository-root .
```

## Retry and benchmark

`viper retry` appends a new attempt to a failed or cancelled frozen run. It
preserves earlier attempt documents and executes the same plan.

`viper execute-benchmark` creates an independent confirmation attempt for one
verified candidate. The benchmark compares estimator artifacts, prediction
artifacts, and recomputed metric criteria before it reports success.

Evaluation datasets and splits enter candidate runs through promoted artifact
pointers. This keeps benchmark data outside training stages and lets one
benchmark govern several candidate plans.

## Run on GCE

Provision the VM, connect to it, install the same wheel, and invoke the same
Python or CLI entrypoint. A `GCEEnvironmentSpec` fixes the provisioning image,
machine type, compute backend, lockfile, and Python environment. VIPER records
the observed host, CPU, CUDA device, driver, PyTorch CUDA runtime, cuDNN runtime,
and numerical controls inside each stage result.

The current release supports one host process and one CUDA device per stage.
The [cloud execution contract](contracts/CLOUD_EXECUTION.md) defines the exact
requested and observed fields.

## Inspect results

```bash
viper --json status path/to/journal.jsonl
viper --json verify-run path/to/resolved.yaml --trust-source <repository>
viper --json lineage path/to/resolved.yaml --trust-source <repository>
viper --json compare-runs left.yaml right.yaml --trust-source <repository>
```

JSON mode emits one canonical document and a stable error code. `viper schema`
returns a public JSON Schema. `viper capabilities` returns the installed
operations, schemas, and execution backends.
