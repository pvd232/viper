# Load local and HTTP inputs

Use a local input when the bytes already live in the project. Use a download
stage when execution must retrieve bytes over HTTP and record the response.

## Select a local file

Pass the repository-relative path and its role to `input()`:

```python
from viper.authoring import input

dataset = input("data/train.csv", data_role="training")
```

Connect it to a stage under the name the stage function reads:

```python
training = stage(
    fit,
    params=params.Train(),
    inputs={"dataset": dataset},
    artifacts={...},
    metrics=(loss,),
    objective=min(loss),
)
```

Inside `fit()`, `context.inputs["dataset"]` is the materialized path. The
authoring name and the context lookup must match.

## Declare an HTTP download

HTTP retrieval is a stage because the response is observed during execution.
The request records the expected body identity; the policy limits where the
runner may connect and how much it may accept.

```python
from viper.artifacts import artifact
from viper.authoring import download
from viper.http import HttpRequestSpec, HttpRetrievalPolicy

fetch_data = download(
    inputs={
        "dataset": HttpRequestSpec(
            url="https://data.example.org/train.csv",
            version="2026-09-05",
            expected_body_sha256="<64 lowercase hex characters>",
            expected_body_bytes=12345,
        )
    },
    artifacts={
        "dataset": artifact(
            path="inputs/downloads/train.csv",
            loader=load_rows,
            data_role="training",
        )
    },
    policy=HttpRetrievalPolicy(
        allowed_schemes=frozenset({"https"}),
        allowed_hosts=frozenset({"data.example.org"}),
        allowed_ports=frozenset({443}),
        max_redirects=0,
        max_body_bytes=20_000,
        timeout_seconds=30.0,
    ),
)
```

Obtain the expected byte count and SHA-256 digest from a trusted dataset
release, manifest, or one reviewed acquisition before freezing the experiment.
VIPER uses those values to detect a server response that changed. It does not
discover the expected identity from the same untrusted response it is checking.

## Feed downloaded bytes to another stage

An artifact handle from one stage can become the input to a later stage. Use
the artifact selected from `fetch_data` in the downstream stage's `inputs`
mapping. Freezing turns that handle into a same-run dependency.

For the complete HTTP protocol and credential model, use the
[Python API reference](../reference/api.md) and
[`viper.http`](../../src/viper/http.py).
