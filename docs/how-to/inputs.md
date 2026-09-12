# Load local and HTTP inputs

Use a local input when the bytes already live in the workspace. Use a download stage
when execution must retrieve bytes over HTTP and record the response.

Run the complete [download-and-training program](../../examples/download_training.py)
from the repository root with `python -m examples.download_training`. It retrieves
the pinned CSV over HTTPS, checks its bytes, and passes the downloaded artifact
to the training stage. The sections below explain each declaration.

## Select a local file

Give `input()` a name, repository-relative path, and data role:

```python
from viper.authoring import input

dataset = input("dataset", path="examples/data/tiny.csv", data_role="training")
```

In the [CPU tutorial](../tutorials/getting-started.md#3-declare-the-experiment),
use `dataset` in the training declaration before constructing `study`.
The tutorial defines `fit`, `mse`, `load_json`, and `load_state`:

```python
from viper.authoring import stage
from viper.metrics import min
from viper.outputs import TrainOutputs, output

training_outputs = TrainOutputs(
    model=output(path="model.json", loader=load_json, data_role="training"),
    resume_state=output(
        path="resume_state.pt", loader=load_state, data_role="training"
    ),
)

training = stage(
    fit,
    stage_id="train",
    inputs=(dataset,),
    outputs=training_outputs,
    metrics=(mse,),
    objective=min(mse),
)
```

Inside `fit()`, `context.inputs["dataset"]` is the local input path. The authoring name
and the context lookup must match.

Pass an upstream output directly: `inputs=(prepared.outputs["dataset"],)`.
It keeps the name `dataset`. To rename it for the receiving function, use
`input("features", source=prepared.outputs["dataset"])`. Both forms retain the
producer and its data role. Duplicate input names are rejected.

## Declare an HTTP download

HTTP retrieval is a stage because the response is observed during execution. The request
records the expected body identity; the policy limits where the runner may connect and
how much it may accept.

This declaration retrieves the quickstart CSV from a fixed VIPER source commit.
The expected digest and size identify that committed file.
`load_text` comes from [workflow_functions.py](../../examples/workflow_functions.py)
and reads the retrieved CSV as UTF-8 text.

```python
from examples.workflow_functions import load_text
from viper.outputs import StageOutputs, output
from viper.authoring import download
from viper.http import HttpRequestSpec, HttpRetrievalPolicy


fetch_data = download(
    stage_id="download",
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
    outputs=StageOutputs(
        dataset=output(
            path="train.csv",
            loader=load_text,
            data_role="training",
        )
    ),
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

Continue with the training function, metric, and `training_outputs` defined
above. Select the download stage's output in the downstream stage:

```python
training = stage(
    fit,
    stage_id="train",
    inputs=(fetch_data.outputs["dataset"],),
    outputs=training_outputs,
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

Define loaders as top-level functions in a module whose imports are available
in the verification environment. Verification retrieves that module from the
recorded commit; sibling workspace modules require separate installation in
the environment. The examples keep shared loaders in
[workflow_functions.py](../../examples/workflow_functions.py), whose imports
are satisfied by the installed VIPER environment.

`TrainOutputs` specifies required output names. Set each output’s `data_role`
explicitly to preserve the restrictions inherited from input data. If a
training stage consumes validation data, its outputs must retain at least the
`validation` role. Declaring them as `training` would discard that restriction
and is rejected. Training stages accept only `training` and `validation` inputs.

## Use an artifact from a completed run

The [evaluation example](../../examples/evaluation.py) first runs
`prepare_test_data`, which copies the held-out CSV and writes its split indices.
It stores the completed result in `data_run`. Inside that example's `main()`,
the following calls select those outputs for the evaluation run:

```python
from viper.artifacts import StageArtifactRef
from viper.authoring import run_artifact

test_data = run_artifact(
    data_run.reference,
    StageArtifactRef(stage_id="build", artifact_name="test_data"),
    path="inputs/test.csv",
    data_role="benchmark",
)
test_split = run_artifact(
    data_run.reference,
    StageArtifactRef(stage_id="build", artifact_name="test_split"),
    path="inputs/holdout.json",
    data_role="benchmark",
)
```

Here `data_run` is the result of an earlier `execution.run()` that produced the
named artifacts. Each `path` is the local destination for the retrieved file;
use distinct paths for distinct inputs. Execution saves a pointer to the
selected artifact. Execution verifies the pointer and retrieves the bytes
before invoking the consumer.

The producer and consumer may use different local VIPER workspaces on the same
machine. A local file reference records the producer workspace's absolute path
and durable store identity, so the consumer opens the producer's `.viper/store`
rather than searching its own store. The producer workspace must remain at that
recorded path. Use Hugging Face or Viper Cloud storage when the consumer runs on
another machine or the producer workspace will move.

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

The `HttpContext` fields provide the values needed by the client:

| Field | Use |
| --- | --- |
| `request` | Read the URL and expected response identity. |
| `policy` | Enforce the allowed hosts, redirects, body size, and timeout. |
| `credential` | Use the resolved header, prefix, and secret value when credentials were requested. |
| `destination` | Write the response body to this path. |
| `workspace` | Use this directory for temporary request files. |
| `config` | Read your validated `HttpConfig` settings. |
| `executables` | Look up declared external commands by their assigned names. |

Return `HttpResult(body=context.destination, response=observed_response)` after
writing the body. `observed_response` must be an `ObservedHttpResponse` populated
from the actual HTTP response. Its schema in [viper.http](../../src/viper/http.py)
defines the status, headers, redirect history, and body identity to record.
