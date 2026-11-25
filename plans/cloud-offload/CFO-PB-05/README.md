# CFO-PB-05

**Status:** authored_not_applied_gates_not_run; no implementation gate or completion asserted.

**Requirements:** CFO-REQ-07, CFO-REQ-09

**Dependencies:** CFO-PB-04

Context: Publish exact completed originals with existing provider verification and recovery. These synchronous physical operations are worker primitives; native durable admission and deferred cleanup remain PB06/PB07 connectors.

## Review the complete edits

Complete action payloads are authoritative. Diffs and hashes are generated from those bytes against the preceding packet, not instructions to overwrite the partially edited live worktree blindly.

**File: `src/viper/execution/_promotion_journal.py`**

[Complete proposed file](replace/src/viper/execution/_promotion_journal.py) · [Generated diff](diff/src/viper/execution/_promotion_journal.py.diff)

```diff
--- a/src/viper/execution/_promotion_journal.py
+++ b/src/viper/execution/_promotion_journal.py
@@ -3,6 +3,7 @@
 from __future__ import annotations
 
 import fcntl
+import hashlib
 import os
 import tempfile
 from pathlib import Path
@@ -150,8 +151,10 @@
         source_files: tuple[SnapshotFileRef, ...],
         sources: dict[str, PublicationSource],
         dependencies_sha256: SHA256,
+        *,
+        exact_bytes: bool = False,
     ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
-        """Save intent, publish once, and verify the destination files."""
+        """Upload files with saved progress and verify them before returning."""
         if self._lock is None:
             raise RunPromotionError("publication journal is not locked")
         if not sources:
@@ -167,8 +170,18 @@
             revision=manifest_revision(files),
             files=files,
         )
+        candidate = SnapshotCopy(
+            source=source,
+            source_files=original_files,
+            expected=expected,
+            dependencies_sha256=dependencies_sha256,
+            previous_head=None,
+        )
+        if exact_bytes:
+            validate_exact_snapshot_copy(candidate)
         key = document_digest(source)
         saved = self.progress.copies.get(key)
+        published: CloudStageResultSnapshotRef | None = None
         if saved is not None:
             if (
                 saved.source != source
@@ -177,20 +190,26 @@
                 or saved.dependencies_sha256 != dependencies_sha256
             ):
                 raise RunPromotionError("publication journal differs")
-            published = saved.published or self._recover(saved)
+            published = saved.published
+            if published is None:
+                if not exact_bytes:
+                    published = self._recover(saved)
+                elif isinstance(self.cloud.provider, HuggingFaceProvider):
+                    if saved.previous_head is None:
+                        raise RunPromotionError("publication journal differs")
+                    published = self.cloud.provider.find_publication(
+                        expected, saved.previous_head
+                    )
+                elif not isinstance(self.cloud.repository, GcsRepository):
+                    raise RunPromotionError("publication provider cannot resume")
         else:
             previous = None
             if isinstance(self.cloud.provider, HuggingFaceProvider):
                 previous = self.cloud.provider.publication_head()
-            saved = SnapshotCopy(
-                source=source,
-                source_files=original_files,
-                expected=expected,
-                dependencies_sha256=dependencies_sha256,
-                previous_head=previous,
-            )
+            saved = candidate.model_copy(update={"previous_head": previous})
             self.progress.copies[key] = saved
             self._save()
+        if published is None:
             try:
                 published = self.cloud.provider.publish_revision(
                     destination=self.destination,
@@ -208,7 +227,7 @@
         return published, files
 
     def _recover(self, saved: SnapshotCopy) -> CloudStageResultSnapshotRef:
-        """Find an earlier successful copy using its exact manifest."""
+        """Find the cloud location to check after an interrupted upload."""
         provider = self.cloud.provider
         if isinstance(provider, HuggingFaceProvider):
             if saved.previous_head is None:
@@ -228,10 +247,12 @@
                 )
         raise RunPromotionError("remote publication outcome is unresolved")
 
-    def _verify(
-        self, snapshot: CloudStageResultSnapshotRef, expected: RevisionManifest
+    def verify_destination(
+        self,
+        snapshot: CloudStageResultSnapshotRef,
+        expected: RevisionManifest,
     ) -> None:
-        """Read every destination file and check its saved size and hash."""
+        """Verify an address and manifest without downloading payloads."""
         if ViperCloud._repository_for(snapshot) != self.cloud.repository:
             raise RunPromotionError("destination repository differs")
         if isinstance(snapshot, GcsStageResultSnapshotRef) and (
@@ -245,6 +266,14 @@
                 raise RunPromotionError("destination snapshot differs")
         elif self.cloud.list_files(snapshot) != expected.files:
             raise RunPromotionError("destination snapshot differs")
+
+    def _verify(
+        self,
+        snapshot: CloudStageResultSnapshotRef,
+        expected: RevisionManifest,
+    ) -> None:
+        """Read every destination file and check its saved size and hash."""
+        self.verify_destination(snapshot, expected)
         if self.space is not None:
             self.space.check(
                 largest_file=max((file.bytes for file in expected.files), default=0)
@@ -262,3 +291,40 @@
                 if self.space is not None:
                     self.space.check()
                 target.unlink()
+
+
+def publish_captured_snapshot(
+    journal: PublicationJournal,
+    inventory: SnapshotInventory,
+    sources: dict[str, PublicationSource],
+) -> SnapshotCopy:
+    """Upload the snapshot's files or reuse its verified cloud publication.
+
+    This call waits for upload and verification.
+    """
+    if journal._lock is None:
+        raise RunPromotionError("publication journal is not locked")
+    key = document_digest(inventory.source)
+    dependencies = hashlib.sha256(b"[]").hexdigest()
+    saved = journal.progress.copies.get(key)
+    if saved is not None:
+        validate_exact_snapshot_copy(saved)
+        if (
+            saved.source != inventory.source
+            or saved.source_files != inventory.source_files
+            or saved.expected.owner != journal.destination.owner
+            or saved.expected.workspace != journal.destination.workspace
+            or saved.dependencies_sha256 != dependencies
+        ):
+            raise RunPromotionError("captured snapshot binding differs")
+        if saved.published is not None:
+            journal.verify_destination(saved.published, saved.expected)
+            return saved
+    journal.publish(
+        inventory.source,
+        inventory.source_files,
+        sources,
+        dependencies,
+        exact_bytes=True,
+    )
+    return validate_exact_snapshot_copy(journal.progress.copies[key])
```

**File: `src/viper/huggingface.py`**

[Complete proposed file](replace/src/viper/huggingface.py) · [Generated diff](diff/src/viper/huggingface.py.diff)

```diff
--- a/src/viper/huggingface.py
+++ b/src/viper/huggingface.py
@@ -143,7 +143,12 @@
         )
 
     def publication_head(self) -> str:
-        """Read the current commit before saving a publication intent."""
+        """Create the repository if needed and return its current commit."""
+        self.api.create_repo(
+            repo_id=self.repository,
+            repo_type=self._api_repo_type,
+            exist_ok=True,
+        )
         head = self.api.repo_info(self.repository, repo_type=self._api_repo_type).sha
         if head is None:
             raise ViperCloudError("destination commit is unavailable")
```

**File: `tests/test_cloud_service.py`**

[Complete proposed file](replace/tests/test_cloud_service.py) · [Generated diff](diff/tests/test_cloud_service.py.diff)

```diff
--- a/tests/test_cloud_service.py
+++ b/tests/test_cloud_service.py
@@ -22,15 +22,21 @@
 from viper._cloud import (
     GcsRepository,
     HuggingFaceRepository,
+    PublicationSource,
+    SnapshotInventory,
     ViperCloudDestination,
     ViperCloudError,
+    manifest_revision,
     source_file,
 )
 from viper._source import RunFetcher
 from viper.authoring import freeze_run_plan
 from viper.cloud import ViperCloud
 from viper.execution._promotion_compare import GraphComparison
-from viper.execution._promotion_journal import PublicationJournal
+from viper.execution._promotion_journal import (
+    PublicationJournal,
+    publish_captured_snapshot,
+)
 from viper.execution._promotion_transfer import (
     TransferSpace,
     directory_bytes,
@@ -42,6 +48,7 @@
     GcsFileRef,
     HuggingFaceFileRef,
     HuggingFaceStageResultSnapshotRef,
+    LocalStageResultSnapshotRef,
     ResolvedFileRef,
     ResolvedRunRef,
     SnapshotFileRef,
@@ -822,3 +829,350 @@
         assert all(
             source_reader.path(ref).is_file() for ref in store.resolved_files(payloads)
         )
+
+
+def _native_publication_sources(
+    root: Path,
+) -> tuple[SnapshotInventory, dict[str, PublicationSource]]:
+    """Seal a complete bundle directly from producer-owned original paths."""
+    sources: dict[str, PublicationSource] = {}
+    for name, raw in {
+        "artifacts/weights.bin": b"weights",
+        "artifacts/tokenizer.json": b'{"v": 1}\n',
+    }.items():
+        path = root / "originals" / name
+        path.parent.mkdir(parents=True, exist_ok=True)
+        path.write_bytes(raw)
+        sources[name] = path
+    files = tuple(
+        source_file(root, name, source)
+        for name, source in sorted(sources.items())
+    )
+    inventory = SnapshotInventory(
+        source=LocalStageResultSnapshotRef(
+            workspace=root,
+            commit=manifest_revision(files),
+        ),
+        source_files=files,
+    )
+    return inventory, sources
+
+
+def _native_gcs_cloud(
+    root: Path,
+    *,
+    rejected_seals: int = 0,
+) -> tuple[ViperCloud, InMemoryViperCloudProvider]:
+    """Reuse the existing in-memory adapter for journal contract checks."""
+    provider = InMemoryViperCloudProvider(root, rejected_seals=rejected_seals)
+    cloud = ViperCloud(
+        root,
+        GcsRepository(bucket=provider.bucket, prefix=provider.prefix),
+        provider=provider,
+    )
+    return cloud, provider
+
+
+def _native_hub_cloud(
+    root: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> tuple[ViperCloud, MemoryHub]:
+    """Use real Hub publication and verification against the existing fake API."""
+    api = MemoryHub(root / "hub")
+    provider = HuggingFaceProvider(
+        root, "owner/copies", "dataset", api=cast(Any, api)
+    )
+    monkeypatch.setattr(provider, "_download", api.download)
+    cloud = ViperCloud(
+        root,
+        HuggingFaceRepository(repository="owner/copies", repo_type="dataset"),
+        provider=provider,
+    )
+    return cloud, api
+
+
+def test_direct_publication_preserves_original_bundle_and_verifies_before_return(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Upload original files unchanged and acknowledge only after all checks."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, provider = _native_gcs_cloud(tmp_path)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    publish = Mock(wraps=provider.publish_revision)
+    fetch = provider.fetch_to_path
+    verified = []
+
+    def verify_before_ack(*args: Any, **kwargs: Any) -> Path:
+        """Require the persisted intent to remain pending during byte checks."""
+        saved = json.loads(progress.read_bytes())
+        assert all(copy["published"] is None for copy in saved["copies"].values())
+        result = fetch(*args, **kwargs)
+        verified.append(args[1])
+        return result
+
+    monkeypatch.setattr(provider, "publish_revision", publish)
+    monkeypatch.setattr(provider, "fetch_to_path", verify_before_ack)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        copy = publish_captured_snapshot(journal, inventory, sources)
+
+    assert copy.source == inventory.source
+    assert copy.source_files == inventory.source_files
+    assert copy.expected.files == inventory.source_files
+    assert copy.published is not None
+    assert len(verified) == len(inventory.source_files)
+    assert publish.call_args.kwargs["sources"] == sources
+    assert not (tmp_path / ".viper/store").exists()
+    for member in inventory.source_files:
+        assert source_file(tmp_path, member.path, sources[member.path]) == member
+
+
+@pytest.mark.parametrize("change", ("bytes", "missing", "extra"))
+def test_direct_publication_rejects_changed_inventory_before_saving_intent(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+    change: str,
+) -> None:
+    """Reject changed bytes or bundle membership before any provider write."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, provider = _native_gcs_cloud(tmp_path)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    if change == "bytes":
+        selected = sources["artifacts/weights.bin"]
+        assert isinstance(selected, Path)
+        selected.write_bytes(b"WEIGHTS")
+    elif change == "missing":
+        del sources["artifacts/weights.bin"]
+    else:
+        extra = tmp_path / "originals/extra.bin"
+        extra.write_bytes(b"extra")
+        sources["artifacts/extra.bin"] = extra
+    publish = Mock(side_effect=AssertionError("upload started before validation"))
+    monkeypatch.setattr(provider, "publish_revision", publish)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(RunPromotionError, match="destination inventory differs"):
+            publish_captured_snapshot(journal, inventory, sources)
+        assert not journal.progress.copies
+    publish.assert_not_called()
+    assert not progress.exists()
+
+
+def test_direct_gcs_publication_resumes_interrupted_seal_after_restart(
+    tmp_path: Path,
+) -> None:
+    """Retry the saved immutable publication without rerunning its producer."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, provider = _native_gcs_cloud(tmp_path, rejected_seals=1)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(RunPromotionError, match="outcome is unresolved"):
+            publish_captured_snapshot(journal, inventory, sources)
+        assert all(copy.published is None for copy in journal.progress.copies.values())
+    for source in sources.values():
+        assert isinstance(source, Path)
+        assert source.is_file()
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        copy = publish_captured_snapshot(journal, inventory, sources)
+    assert copy.published is not None
+    assert copy.expected.files == inventory.source_files
+    assert provider.seal_calls == 2
+    assert len(provider.uploads) == len(inventory.source_files)
+
+
+@pytest.mark.parametrize("failure", ("before_commit", "lost_response"))
+def test_direct_hub_publication_reconciles_before_retrying(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+    failure: str,
+) -> None:
+    """Retry a missing commit and recover a completed commit without duplication."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, api = _native_hub_cloud(tmp_path, monkeypatch)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    create_commit = api.create_commit
+    calls = []
+    api.fail_after_commit = failure == "lost_response"
+
+    def interrupted_commit(**kwargs: Any) -> Any:
+        """Lose either the request or its response on the first attempt."""
+        calls.append(kwargs)
+        if len(calls) == 1 and failure == "before_commit":
+            raise ConnectionError("request never committed")
+        return create_commit(**kwargs)
+
+    monkeypatch.setattr(api, "create_commit", interrupted_commit)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(RunPromotionError, match="outcome is unresolved"):
+            publish_captured_snapshot(journal, inventory, sources)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        copy = publish_captured_snapshot(journal, inventory, sources)
+    assert copy.published is not None
+    assert len(api.commits) == 2
+    assert len(calls) == (1 if failure == "lost_response" else 2)
+
+
+def test_direct_hub_publication_does_not_retry_uncertain_history(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Retain unresolved intent when reconciliation cannot establish an outcome."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, api = _native_hub_cloud(tmp_path, monkeypatch)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    api.fail_after_commit = True
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(RunPromotionError, match="outcome is unresolved"):
+            publish_captured_snapshot(journal, inventory, sources)
+    saved = progress.read_bytes()
+    assert isinstance(cloud.provider, HuggingFaceProvider)
+    unresolved = Mock(side_effect=ViperCloudError("outcome is unresolved"))
+    forbidden = Mock(side_effect=AssertionError("duplicated an uncertain commit"))
+    monkeypatch.setattr(cloud.provider, "find_publication", unresolved)
+    monkeypatch.setattr(cloud.provider, "publish_revision", forbidden)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(ViperCloudError, match="outcome is unresolved"):
+            publish_captured_snapshot(journal, inventory, sources)
+    forbidden.assert_not_called()
+    assert progress.read_bytes() == saved
+
+
+def test_committed_direct_copy_reuses_proof_after_originals_are_evicted(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Reuse committed proof without source reads or another payload download."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, provider = _native_gcs_cloud(tmp_path)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        original = publish_captured_snapshot(journal, inventory, sources)
+    for source in sources.values():
+        assert isinstance(source, Path)
+        source.unlink()
+    saved = progress.read_bytes()
+    forbidden = Mock(side_effect=AssertionError("reopened an evicted payload"))
+    monkeypatch.setattr("viper.execution._promotion_journal.source_file", forbidden)
+    monkeypatch.setattr(provider, "publish_revision", forbidden)
+    monkeypatch.setattr(provider, "fetch_to_path", forbidden)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        observed = publish_captured_snapshot(journal, inventory, {})
+    assert observed == original
+    assert progress.read_bytes() == saved
+    forbidden.assert_not_called()
+
+
+def test_direct_publication_does_not_acknowledge_failed_cloud_hash_check(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Keep source files and pending intent when cloud bytes fail verification."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, api = _native_hub_cloud(tmp_path, monkeypatch)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    create_commit = api.create_commit
+    member = inventory.source_files[0]
+
+    def corrupt_commit(**kwargs: Any) -> Any:
+        """Return a successful commit whose payload was not stored correctly."""
+        result = create_commit(**kwargs)
+        api.commits[api.head][member.path] = b"X" * member.bytes
+        return result
+
+    monkeypatch.setattr(api, "create_commit", corrupt_commit)
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(ViperCloudError, match="file identity changed"):
+            publish_captured_snapshot(journal, inventory, sources)
+        assert all(copy.published is None for copy in journal.progress.copies.values())
+    for original in sources.values():
+        assert isinstance(original, Path)
+        assert original.is_file()
+
+
+def test_pending_direct_publication_accepts_new_physical_source_locations(
+    tmp_path: Path,
+) -> None:
+    """Resume the same intent after registry-owned source locations change."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, _ = _native_gcs_cloud(tmp_path, rejected_seals=1)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        with pytest.raises(RunPromotionError, match="outcome is unresolved"):
+            publish_captured_snapshot(journal, inventory, sources)
+    before = json.loads(progress.read_bytes())
+    relocated: dict[str, PublicationSource] = {}
+    for member, original in sources.items():
+        assert isinstance(original, Path)
+        target = tmp_path / "relocated" / member
+        target.parent.mkdir(parents=True, exist_ok=True)
+        original.rename(target)
+        relocated[member] = target
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        copy = publish_captured_snapshot(journal, inventory, relocated)
+    after = json.loads(progress.read_bytes())
+    assert before["operation_sha256"] == after["operation_sha256"]
+    assert before["copies"].keys() == after["copies"].keys()
+    assert copy.source == inventory.source
+    assert copy.expected.files == inventory.source_files
+    assert copy.published is not None
+
+
+@pytest.mark.parametrize("changed_source", (False, True))
+def test_direct_hub_first_publication_initializes_repository_after_exact_guard(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+    changed_source: bool,
+) -> None:
+    """Create a missing repository before its head lookup after local validation."""
+    inventory, sources = _native_publication_sources(tmp_path)
+    cloud, api = _native_hub_cloud(tmp_path, monkeypatch)
+    destination = ViperCloudDestination(owner="owner", workspace="models")
+    progress = tmp_path / "progress.json"
+    created = False
+    events = []
+    create_repo = api.create_repo
+    repo_info = api.repo_info
+
+    def create_repository(**kwargs: Any) -> None:
+        """Model the missing repository becoming available idempotently."""
+        nonlocal created
+        assert kwargs == {
+            "repo_id": "owner/copies",
+            "repo_type": "dataset",
+            "exist_ok": True,
+        }
+        events.append("create")
+        create_repo(**kwargs)
+        created = True
+
+    def repository_info(*args: Any, **kwargs: Any) -> Any:
+        """Reject a head lookup while the repository does not exist."""
+        events.append("head")
+        if not created:
+            raise FileNotFoundError("repository has not been created")
+        return repo_info(*args, **kwargs)
+
+    monkeypatch.setattr(api, "create_repo", create_repository)
+    monkeypatch.setattr(api, "repo_info", repository_info)
+    if changed_source:
+        weights = sources["artifacts/weights.bin"]
+        assert isinstance(weights, Path)
+        weights.write_bytes(b"WEIGHTS")
+    with PublicationJournal(progress, "a" * 64, cloud, destination) as journal:
+        if changed_source:
+            with pytest.raises(RunPromotionError, match="destination inventory differs"):
+                publish_captured_snapshot(journal, inventory, sources)
+            assert not events
+            assert not journal.progress.copies
+        else:
+            copy = publish_captured_snapshot(journal, inventory, sources)
+            assert events[:2] == ["create", "head"]
+            assert copy.published is not None
+            assert len(api.commits) == 2
```

**File: `tests/conftest.py`**

[Complete proposed file](replace/tests/conftest.py) · [Generated diff](diff/tests/conftest.py.diff)

```diff
```

## Focused check and stop condition

After the actual dependency baseline and complete plan are frozen, the user runs Pyrefly first, then:

```bash
python -m pytest -q -p no:cacheprovider tests/test_cloud_service.py::test_direct_publication_preserves_original_bundle_and_verifies_before_return tests/test_cloud_service.py::test_direct_publication_rejects_changed_inventory_before_saving_intent tests/test_cloud_service.py::test_direct_gcs_publication_resumes_interrupted_seal_after_restart tests/test_cloud_service.py::test_direct_hub_publication_reconciles_before_retrying tests/test_cloud_service.py::test_direct_hub_publication_does_not_retry_uncertain_history tests/test_cloud_service.py::test_committed_direct_copy_reuses_proof_after_originals_are_evicted tests/test_cloud_service.py::test_direct_publication_does_not_acknowledge_failed_cloud_hash_check tests/test_cloud_service.py::test_pending_direct_publication_accepts_new_physical_source_locations tests/test_cloud_service.py::test_direct_hub_first_publication_initializes_repository_after_exact_guard
```

Require discovered semantic documentation/schema coverage and finish with non-mutating Ruff format/lint checks. Stop on a failed check; no gate has run from this packet.

## Boundary

Synchronous physical publication belongs inside the future independent worker. This packet is not durable admission, final root closure or cleanup authorization.
