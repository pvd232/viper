# Load local and HTTP inputs

Use a local input when the bytes already live in the workspace. Use a download stage
when execution must retrieve bytes over HTTP and record the response.

## Select a local file

Pass the repository-relative path and its role to `input()`:

```python
from viper.authoring import input

dataset = input("examples/data/tiny.csv", data_role="training")
```

Continue inside `main()` from the [CPU tutorial](../tutorials/getting-started.md),
after its `training` declaration. Reuse its function, outputs, and configured metric
to connect a different input:

```python
from viper.authoring import stage
from viper.config import TrainConfig
from viper.metrics import min


training = stage(
    fit,
    config=TrainConfig(),
    inputs={"dataset": dataset},
    outputs=training.spec.outputs,
    metrics=(mse,),
    objective=min(mse),
)
```

Inside `fit()`, `context.inputs["dataset"]` is the materialized path. The authoring name
and the context lookup must match.

## Declare an HTTP download

HTTP retrieval is a stage because the response is observed during execution. The request
records the expected body identity; the policy limits where the runner may connect and
how much it may accept.

This declaration retrieves the quickstart CSV from a fixed VIPER source commit.
The expected digest and size identify that committed file.

```python
from pathlib import Path

from viper.outputs import StageOutputs, output
from viper.authoring import download
from viper.http import HttpRequestSpec, HttpRetrievalPolicy

def load_rows(path: Path) -> list[tuple[float, float]]:
    lines = path.read_text(encoding="utf-8").splitlines()[1:]
    return [(float(x), float(y)) for x, y in (line.split(",") for line in lines)]


fetch_data = download(
    inputs={
        "dataset": HttpRequestSpec(
            url=(
                "https://raw.githubusercontent.com/pvd232/viper/"
                "327d1f89ad38d855e500f5386bdd2894d049a899/examples/data/tiny.csv"
            ),
            version="327d1f89ad38d855e500f5386bdd2894d049a899",
            expected_body_sha256="5962ba6c35b56dabeb8121dd6656aba7b1e60afe0d2ddec498feb191057d15fe",
            expected_body_bytes=16,
        )
    },
    outputs=StageOutputs.model_validate({
        "dataset": output(
            path="train.csv",
            loader=load_rows,
            data_role="training",
        )
    }),
    policy=HttpRetrievalPolicy(
        allowed_schemes=frozenset({"https"}),
        allowed_hosts=frozenset({"raw.githubusercontent.com"}),
        allowed_ports=frozenset({443}),
        max_redirects=0,
        max_body_bytes=20_000,
        timeout_seconds=30.0,
    ),
)
```

Obtain the expected byte count and SHA-256 digest from a trusted dataset release,
manifest, or one reviewed acquisition before freezing the experiment. VIPER uses those
values to detect a server response that changed. The expected identity must come from a
source you trust before the request runs.

## Feed downloaded bytes to another stage

Select the download stage's output in the downstream stage:

```python
training = stage(
    fit,
    config=TrainConfig(),
    inputs={"dataset": fetch_data.outputs["dataset"]},
    outputs=training.spec.outputs,
    metrics=(mse,),
    objective=min(mse),
)
```

Include both stages in the variant, with the download before training. Freezing turns
the output reference into a same-run dependency. The download input and output names
must match: `"dataset"` selects the retrieved body in this example.

For the complete HTTP protocol and credential model, use the [Python API
reference](../reference/api.md) and [`viper.http`](../../src/viper/http.py).

## Output names and paths

`output(path="model.json", ...)` selects a path beneath that output's directory. For a
stage named `train` and an output named `model`, the working file is
`artifacts/train/model/model.json` beneath the run directory. Use `kind="bundle"` for a
directory whose member files are recorded together.

`TrainOutputs` requires `model` and `resume_state`; `EvalOutputs` requires
`predictions`. Other stage outputs use `StageOutputs`. An output declaration reserves
the path and loader; your function writes the file. The recorded file then becomes an
artifact.

## Use an artifact from a completed run

Use the completed run's `.reference` and the producing stage and output names:

```python
from viper.artifacts import StageArtifactRef
from viper.authoring import run_artifact

test_data = run_artifact(
    data_run.reference,
    StageArtifactRef(stage_id="build", artifact_name="test_data"),
    path="inputs/test.csv",
    data_role="eval",
)
test_split = run_artifact(
    data_run.reference,
    StageArtifactRef(stage_id="build", artifact_name="test_split"),
    path="inputs/holdout.json",
    data_role="eval",
)
```

Here `data_run` is the result of an earlier `execution.run()` that produced the
named artifacts. Each `path` is the consuming workspace's materialization path;
use distinct paths for distinct inputs. Freezing publishes a pointer to the
selected artifact. Execution verifies the pointer and retrieves the bytes
before invoking the consumer.

The selected data role must agree with the stored artifact. Training accepts
`training` and `validation` inputs. Evaluation test data uses `eval` or
`benchmark`. Output roles retain the restrictions imposed by their inputs;
VIPER rejects relabeling benchmark data as training data.

## Customize HTTP retrieval

Use the built-in HTTP implementation for ordinary downloads. To integrate a
workspace-specific client, decorate a function with `viper.http.http`, then
pass a `CustomHttpDraft` through `download(http=...)`. The function receives an
`HttpContext` containing the request, policy, config, and destination, and
returns an `HttpResult` describing the observed response.

The custom implementation still obeys the declared host, redirect, body-size,
and digest checks. See the exact callable and draft signatures in
[`viper.http`](../../src/viper/http.py), and the custom-client cases in
[HTTP retrieval tests](../../tests/test_http_retrieval.py). Credentials are supplied
through the execution environment. Keep versioned URLs free of credentials.
