# Publish, restore, and retain cloud-backed runs

Cloud publication is optional. Local execution needs no cloud account. Configure
an existing repository and authenticate before
selecting a cloud destination. VIPER does not provision a machine or bucket.

## Choose a repository and destination

VIPER installs the GCS client as a base dependency. From the checkout with its
virtual environment active, install VIPER and authenticate:

```bash
python -m pip install -e .
gcloud auth application-default login
```

The GCS client uses [Application Default Credentials](https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).
Select a bucket your account can access. Replace the bucket and destination
below with your own values:

```toml
[storage]
destination = "viper://researcher/model_runs"

[viper_cloud]
provider = "gcs"
bucket = "your-existing-bucket"
prefix = "viper"
```

For Hugging Face, [authenticate with the installed Hub client](https://huggingface.co/docs/huggingface_hub/en/guides/cli#hf-auth-login)
and select an existing repository you can write:

```bash
hf auth login
```

```toml
[storage]
destination = "viper://researcher/model_runs"

[viper_cloud]
provider = "huggingface"
repository = "your-account/your-evidence-repository"
repo_type = "dataset"
```

`repo_type` also accepts `model` and `space`. Keep credentials outside committed
configuration. Set `destination = "local"` to keep ordinary runs local even
with a cloud repository configured.

## Execute with cloud publication

After saving `viper.toml`, run the complete [CPU quickstart](../../examples/cpu_quickstart.py):

```bash
python -m examples.cpu_quickstart
```

The same `plan()` and `execution.run()` calls now publish to the configured
destination. Returned file references identify the provider and sealed revision.
`resolved.ref.yaml` beside the local terminal result preserves its durable
reference after a restart. Changing the workspace destination does not relocate
an existing run or change a retry's destination.

## Promote a completed local run without rerunning it

Keep `destination = "local"` and configure either repository above. In the
[inspection program's](../../examples/inspect_results.py) `main()`, after `left`
has been produced, use:

```python
from viper import execution
from viper.restoration import ArtifactRestoreSelector
from viper.storage import ViperCloudDestination

promoted = execution.promote_run_to_cloud(
    root,
    left.reference,
    ViperCloudDestination(owner="researcher", workspace="model_runs"),
)
restored = execution.restore(
    root,
    promoted,
    artifacts=(ArtifactRestoreSelector(stage_id="train", artifact_name="model"),),
    output=root / "restored" / f"{left.reference.sha256}_cloud.json",
)
print(promoted.model_dump_json())
print(restored.artifacts[0].files[0].path)
```

Replace the owner and workspace names. Promotion returns a new immutable
`ResolvedRunRef`; retain that reference for later retrieval. It rewrites and
verifies the saved graph and uploads its files. It performs no training or model
inference. The original local reference remains a distinct local object.

## Release local copies after accepting a cloud run

For a run originally published to cloud, continue inside the CPU quickstart's
`main()` after inspecting `resolved_run` and accepting its result:

```python
from viper.repository import resolve_root
from viper.retention import evict_cloud_backed_run_files

released = evict_cloud_backed_run_files(resolve_root(), resolved_run)
print(released.bytes_released)
print(released.attempt_workspace_bytes_released)
```

This call deletes local output copies and transient attempt materializations
only after checking every candidate's local and cloud bytes. It preserves plans,
terminal and attempt records, measurements, journals, logs, and canonical inputs.
Restore can retrieve the deleted outputs from their immutable cloud references.
Run the call only after accepting the result; deletion is not part of the
quickstart by default. A local-only run is rejected. A promotion reference alone
does not replace the local terminal record required by retention.

See [the protocol's retention boundary](../reference/protocol.md#disk-retention-boundary)
for the remaining rejection conditions. Provider tests use controlled stores;
their success does not establish that your credentials or live bucket work.
