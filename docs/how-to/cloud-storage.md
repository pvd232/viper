# Publish, restore, and retain cloud-backed runs

Cloud publication is optional. Local execution needs no cloud account. Configure
an existing repository and authenticate before
selecting a cloud destination. VIPER does not provision a machine or bucket.

## Choose a repository and destination

VIPER installs the GCS client as a base dependency. In your activated Python
environment, install VIPER and authenticate:

```bash
python -m pip install --upgrade 'viper-provenance==0.3.0'
gcloud auth application-default login
```

The GCS client uses [Application Default Credentials](https://cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).
Select a bucket your account can access. Replace the bucket and destination
below with your own values:

```toml
[storage]
destination = "viper://researcher/model_runs"
offload = false

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
offload = false

[viper_cloud]
provider = "huggingface"
repository = "your-account/your-evidence-repository"
repo_type = "dataset"
```

`repo_type` also accepts `model` and `space`. Keep credentials outside committed
configuration. Set `destination = "local"` to keep ordinary runs local even
with a cloud repository configured.

## Execute with cloud publication

After saving `viper.toml`, run your existing experiment as usual. From the VIPER
repository, you can also run the complete [CPU quickstart](../../examples/cpu_quickstart.py):

```bash
python -m examples.cpu_quickstart
```

Native `plan()` and `execution.run()` calls keep their existing invocation.
Completed outputs are registered at their original paths and queued for publication.
Small protocol records use the immutable store. The runner returns after local
verification and durable admission; network transfer and cloud verification continue
in a separate process. References, file hashes and run-record bytes stay unchanged.
New native runs do not use graph-rewriting promotion or a cloud `resolved.ref.yaml`.
Changing the workspace destination still does not change a retry's recorded destination.

Set `storage.offload = true` to permit automatic removal of managed payloads.
The default `false` retains produced and accessed files. Neither setting downloads
historical artifacts proactively. Cloud destinations control publication independently.

Keep related calls inside one driver lifetime:

```python
from viper import execution
from viper.storage import publication_status, workflow

with workflow(root) as storage_work:
    candidate = execution.run(draft, repository_root=root)
    comparison = execution.benchmark(root, candidate.path, benchmark_spec)

print(publication_status(storage_work.operation_path).status)
```

`draft` is an existing `RunPlanDraft`; `benchmark_spec` is its saved benchmark path.
Native child calls borrow the driver lifetime. Training, evaluation, diagnostics
and confirmation can use the same local bytes between calls. Separate future Python
calls are not predicted. Applications that already register their whole driver need
no extra scope at each read.

The result's `publication_path` locates pending, complete or failed publication.
Use `publication_status(path, wait=True, timeout_seconds=...)` only after the outer
scope closes when completion is required. `retry_publication(path)` retries saved
failed uploads without recomputing the experiment. `publication_copies(path, source,
wait=True)` observes one enrolled snapshot while the outer scope remains open.
Existing explicit APIs promising a verified cloud reference continue to wait.

Upload failure preserves local sources and does not turn successful scientific
results into failed results. Scope failure prevents automatic deletion. Pending bytes
and their disk must remain available until verification completes; a queue record
cannot preserve a disk that is destroyed.

### Follow an artifact through the workflow

| Point in the workflow | Local payload | Cloud publication |
| --- | --- | --- |
| Training finishes writing an output | The completed original is registered without a mandatory second payload copy. | The durable worker can begin uploading while later computation continues. |
| Inference, evaluation or diagnostics still use it | Readers use the available local bytes. | Upload and verification continue independently. |
| The whole driver succeeds | Current readers and keep preferences still protect required bytes. | Collection closes; required objects and final receipts must verify. |
| Offload becomes eligible | The worker may delete the exact managed local copy. Inventory and references remain. | Verified backing supplies future restoration. |
| A later workflow requests an absent payload | The resolver downloads, verifies and installs it in the store before returning a path. | The existing published artifact is reused. |

The worker queues cleanup for reconsideration; it checks current policy and
readers when removing a file. Finishing one training or read call does not by
itself authorize deletion. Keep all related calls in the same outer workflow
when their local files should remain available between calls.

### Local availability and retention

Viper returns a verified resident original or shared store payload first. Only a
missing payload needs restoration. Exact-artifact preferences are `inherit`, `keep`
and `offload`; `inherit` follows the current global setting. Use
`retention.set_artifact_retention(root, snapshot, selection, preference)` for an
explicit override. A bundle preference covers its complete membership. `keep` saves
the preference before resolving every member and returns only after local availability.
One keep subscriber preserves shared bytes; reading adds no permanent subscription.

Automatic cleanup runs in the same worker after successful whole-driver completion,
closed publication collection, verified required copies and final receipts. It also
requires current offload permission, completed readers and an unchanged owned file.
Busy or retained files remain local. Cleanup never treats a directory name as permission
to delete its contents. Inventory, reference and recovery metadata survive removal.

`execution.artifact_reference(root, run_ref, selection, member=...)` returns an expected
immutable file reference. `execution.artifact_path(...)` resolves a verified path and
requires the enclosing `workflow`, so cleanup cannot remove it before its consumer
finishes. Ordinary native stages already have that protection. Physical paths may
change after restoration; serialized references remain unchanged.

### Restore on another machine

`publication_receipt(path)` returns the completed portable receipt after all required
cloud proofs verify. Copy that small receipt to the new workspace and call
`import_publication_receipt(root, receipt, targets=...)`. The importer independently
verifies each new supplied remote copy and retains downloaded bytes for reuse;
already registered verified proofs are reused. Reimporting a known proof does not
prefetch its evicted payloads; the resolver restores requested files. Complete inventory remains separate
from resident files, including inventories whose bytes share another snapshot's backing.
It does not recreate the previous machine's absolute directories.

For a selected set of snapshot proofs use `import_publication_copies(...)`. These are
verified per-snapshot copies; they do not assert that a still-open driver has finished.
Explicit imports are restoration operations and can transfer the complete supplied
snapshots. Use only the proofs needed for the restoration.

Applications requiring an attached GCP identity can pass explicit `PublicationTarget`
records to the outer `workflow`. `google_project_id` and `gcp_service_account` select
attached credentials without a key or ADC fallback; nested default scopes inherit those
targets. Keep credential secrets outside records and configuration.

## Publish files from an application

An application can use the same workflow for completed files outside an
experiment. The example assumes the configured cloud destination above and an
existing `results/diagnostics.json` whose writer has finished and closed it:

```python
from pathlib import Path

from viper.storage import (
    load_storage_settings,
    publication_status,
    publish_resolved_files,
    workflow,
)

root = Path.cwd()
settings = load_storage_settings(root)
with workflow(root) as storage_work:
    references = publish_resolved_files(
        root,
        settings.destination,
        {"results/diagnostics.json": root / "results/diagnostics.json"},
    )

print(references["results/diagnostics.json"].model_dump_json())
print(publication_status(storage_work.operation_path).status)
```

This call enrolls the supplied completed files as managed outputs. With offload
enabled, VIPER can remove them after the workflow and publication conditions
pass. Keep the source available and unchanged until publication verifies.
The returned references identify exact bytes; pending work is not a completed
cloud reference. Applications use the native status and recovery operations
instead of starting another uploader or maintaining another publication queue.

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

## Explicit cleanup of older cloud-backed runs

`retention.evict_cloud_backed_run_files(root, result)` remains the explicit compatibility
API for older runs whose terminal records already contain verified cloud references.
It uses the same current policy, reader and exact-file deletion checks as automatic
cleanup. An explicit keep still vetoes removal. Inherited preferences honor this
explicit cleanup request even if the automatic global default is keep.

Native runs retain their original local references and use their finalized publication
operation for automatic cleanup. Passing a promoted reference does not replace an
older local terminal record. Explicit promotion remains useful for migrating existing
local runs; new cloud-managed runs use direct queued publication.

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
