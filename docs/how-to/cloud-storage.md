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


## Plan an additional cloud publication

`RunPromotionPolicy` in `viper.storage` names the target repositories in its
`hosts` tuple. Each entry uses the existing GCS or Hugging Face repository type.
The source workspace and existing saved references stay unchanged.

Graph discovery reads saved plans, run records, stage records, and cloud
manifests. A Hugging Face record can lead to a GCS input. Discovery follows
that link, lists the input, and keeps the dependency order for publication.
A separate required-file inventory detects missing application inputs.
Additional local files are listed with their sizes; their hashes are checked
when publication prepares the snapshot.

### Publish to additional hosts

Pass `policy=RunPromotionPolicy(hosts=(host, ...))` and `limits=TransferLimits(...)`
to `execution.promote_run_to_cloud(root, source, destination, ...)`. A host is an
existing `GcsRepository` or `HuggingFaceRepository`. `destination` supplies its
logical owner and workspace. Each target repository must already be accessible.

The policy form accepts one run reference or a tuple of run references. It
returns a tuple ordered by host, then by the supplied runs. `required_files`
can name exact input or output references that must appear in the discovered
graph. `trusted_source_repositories` permits additional pinned code repositories
during ordinary verification. The original publications, run pointers, and
workspace configuration remain unchanged.

`TransferLimits`, defined in `viper.storage`, has `staging_bytes`, `cache_bytes`,
and `connections`. Choose disk limits from the discovered graph and the available
working disk. The copy process checks space before loading source artifacts.
It uses a task-owned cache, serial file transfers, and a shared HTTP pool.
The dedicated process sets `HF_HUB_DISABLE_XET=1` to keep transfer connections
under that pool's control. Source file paths and shared caches remain intact.

Progress is saved under `.viper/promotion/<request-digest>/`. Repeating the exact
request checks saved publication intents and reuses completed destination
commits. An uncertain upload stays recorded until its outcome can be verified.
The source-to-destination comparison is saved before the final loader checks.
`result.json` records the completed additional publications.

The three-argument call retains its single-reference result and workspace-selected
destination. The additional-host path is opt-in.
