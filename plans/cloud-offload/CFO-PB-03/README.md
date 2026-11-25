# CFO-PB-03

**Status:** guided_foundations_partially_applied_gates_not_run; no implementation gate or completion asserted.

**Requirements:** CFO-REQ-03, CFO-REQ-05

**Dependencies:** CFO-PB-02

Context: Fresh fetchers must reuse registered originals and complete inventory before constructing a provider. Consolidate ordinary verified storage, stream managed payload downloads into the shared store, and prepare whole-admitted-workflow reader protection without enabling deletion.

## Review the complete edits

Complete action payloads are authoritative. Diffs and hashes are generated from those bytes against the preceding packet, not instructions to overwrite the partially edited live worktree blindly.

**File: `src/viper/storage.py`**

[Complete proposed file](replace/src/viper/storage.py) · [Generated diff](diff/src/viper/storage.py.diff)

```diff
--- a/src/viper/storage.py
+++ b/src/viper/storage.py
@@ -7,7 +7,7 @@
 import os
 import tempfile
 import tomllib
-from collections.abc import Mapping
+from collections.abc import Callable, Mapping
 from pathlib import Path
 from typing import Annotated, Literal, Protocol
 
@@ -32,12 +32,18 @@
 )
 from ._schema import ProtocolModel, RepoRelPath
 from ._storage_registry import StorageRegistry
+from ._verified_cache import VerifiedObjectCache
 from .cloud import ViperCloud
+from .evidence import VerificationError
 from .gcs import GcsProgressSink, stderr_gcs_progress
+from .huggingface import HuggingFaceProvider
 from .ids import RunId
 from .references import (
     CloudStageResultSnapshotRef,
+    GcsFileRef,
     GcsStageResultSnapshotRef,
+    GitFileRef,
+    HuggingFaceFileRef,
     HuggingFaceStageResultSnapshotRef,
     LocalFileRef,
     LocalStageResultSnapshotRef,
@@ -45,8 +51,13 @@
     SnapshotFileRef,
     StageResultSnapshotRef,
     StorageModel,
+    ViperCloudFileRef,
+    ViperCloudStageResultSnapshotRef,
+    resolve_snapshot_file_ref,
 )
 from .repository import PathError, resolve_path
+
+_CloudSource = ViperCloud | Callable[[], ViperCloud]
 
 
 class LocalStoreError(RuntimeError):
@@ -167,10 +178,16 @@
     return manifest_revision(files)
 
 class LocalArtifactStore:
-    """Save snapshot files and find their local paths."""
-
-    def __init__(self, repository_root: Path, store: RepoRelPath = ".viper/store"):
-        """Choose the workspace and local store."""
+    """Save snapshot file lists and find the files in local or cloud storage."""
+
+    def __init__(
+        self,
+        repository_root: Path,
+        store: RepoRelPath = ".viper/store",
+        *,
+        cache_root: Path | None = None,
+    ) -> None:
+        """Choose the store and an optional separate cache for transfer work."""
         self.repository_root = repository_root.resolve(strict=True)
         self.store = store
         try:
@@ -179,8 +196,15 @@
             )
         except PathError as error:
             raise LocalStoreError("local store escapes the workspace root") from error
-
         self.registry = StorageRegistry(self.repository_root, self.store)
+        self._objects = VerifiedObjectCache(self.store_root / "objects")
+        self.task_owned_cache = cache_root is not None
+        download_root = (
+            self._objects.root if cache_root is None else cache_root.resolve()
+        )
+        if not download_root.is_relative_to(self.repository_root):
+            raise LocalStoreError("file cache must be inside the workspace")
+        self.downloads = VerifiedObjectCache(download_root)
 
     def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
         """Save the files and return their snapshot ID."""
@@ -188,154 +212,79 @@
         return commit
 
     def _publish(
-        self,
-        files: Mapping[RepoRelPath, bytes],
+        self, files: Mapping[RepoRelPath, bytes]
     ) -> tuple[str, tuple[SnapshotFileRef, ...]]:
-        """Save the files and return their snapshot ID and file hashes."""
+        """Store each distinct file by hash and save the complete snapshot file list."""
         if not files:
             raise LocalStoreError("an immutable revision requires at least one file")
-
         identities = tuple(
             snapshot_file(path, raw) for path, raw in sorted(files.items())
         )
         commit = content_revision(identities)
-        revision_root = self.store_root / commit
-
-        for relative_path, raw in sorted(files.items()):
-            target = (revision_root / relative_path).resolve()
-            if not target.is_relative_to(revision_root):
-                raise LocalStoreError("published file escapes its immutable revision")
-
-            if target.exists():
-                if not target.is_file() or target.read_bytes() != raw:
-                    raise LocalStoreError("immutable revision contains different bytes")
-                continue
-
-            target.parent.mkdir(parents=True, exist_ok=True)
-            file_descriptor, temporary_name = tempfile.mkstemp(
-                dir=target.parent,
-                prefix=f".{target.name}.",
-            )
-            try:
-                with os.fdopen(file_descriptor, "wb") as temporary_file:
-                    temporary_file.write(raw)
-                    temporary_file.flush()
-                    os.fsync(temporary_file.fileno())
-                os.replace(temporary_name, target)
-            finally:
-                Path(temporary_name).unlink(missing_ok=True)
-
         snapshot = LocalStageResultSnapshotRef(
-            workspace=self.repository_root,
-            store=self.store,
-            commit=commit,
-        )
+            workspace=self.repository_root, store=self.store, commit=commit
+        )
+        locations = {}
+        for member in identities:
+            reference = resolve_snapshot_file_ref(snapshot, member)
+            path = self._objects.verified_path(reference)
+            if path is None:
+                self._objects.write(reference, files[member.path])
+                path = self._objects.path(reference)
+            locations[member.path] = (self._observe(path, custody="cache"),)
         self.registry.register_snapshot(
             SnapshotSources(
-                inventory=SnapshotInventory(
-                    source=snapshot,
-                    source_files=identities,
-                ),
-                locations={
-                    member.path: (
-                        self._observe(
-                            revision_root / member.path,
-                            custody="cache",
-                        ),
-                    )
-                    for member in identities
-                },
+                inventory=SnapshotInventory(source=snapshot, source_files=identities),
+                locations=locations,
             )
         )
         return commit, identities
 
     def _observe(
-        self,
-        path: Path,
-        *,
-        custody: Literal["output", "cache", "external"],
+        self, path: Path, *, custody: Literal["output", "cache", "external"]
     ) -> LocalSource:
         """Record the path and file-system details of a file already checked."""
         status = path.stat()
         return LocalSource(
             path=path.relative_to(self.repository_root).as_posix(),
             observed_stat=(
-                status.st_dev,
-                status.st_ino,
-                status.st_mtime_ns,
-                status.st_ctime_ns,
+                status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns
             ),
             custody=custody,
         )
+
     def snapshot(
-        self,
-        files: Mapping[RepoRelPath, bytes],
+        self, files: Mapping[RepoRelPath, bytes]
     ) -> LocalStageResultSnapshotRef:
         """Save the files and return their snapshot reference."""
         return LocalStageResultSnapshotRef(
-            workspace=self.repository_root,
-            store=self.store,
-            commit=self.publish(files),
+            workspace=self.repository_root, store=self.store, commit=self.publish(files)
         )
 
     def resolved_files(
-        self,
-        files: Mapping[RepoRelPath, bytes],
+        self, files: Mapping[RepoRelPath, bytes]
     ) -> tuple[ResolvedFileRef, ...]:
         """Save the files and return a reference for each one."""
         commit, identities = self._publish(files)
+        snapshot = LocalStageResultSnapshotRef(
+            workspace=self.repository_root, store=self.store, commit=commit
+        )
         return tuple(
-            ResolvedFileRef(
-                sha256=identity.sha256,
-                bytes=identity.bytes,
-                stored_at=LocalFileRef(
-                    workspace=self.repository_root,
-                    store=self.store,
-                    commit=commit,
-                    path=identity.path,
-                ),
-            )
-            for identity in identities
-        )
-
-    def fetch(self, location: StorageModel) -> bytes:
-        """Read and check the file at the recorded address."""
-        return self.path(location).read_bytes()
-
-    def path(self, location: StorageModel) -> Path:
-        """Find the file at its recorded local store path."""
-        if not isinstance(location, LocalFileRef):
-            raise TypeError("LocalArtifactStore can resolve only LocalFileRef")
-
-        if location.workspace != self.repository_root or location.store != self.store:
-            raise LocalStoreError("local file belongs to a different store")
-
-        revision_root = (self.store_root / location.commit).resolve()
-        target = (revision_root / location.path).resolve()
-        if not target.is_relative_to(revision_root) or not target.is_file():
-            raise LocalStoreError("local immutable file is missing")
-        return target
-
-    def _local_snapshot(
-        self,
-        source: LocalStageResultSnapshotRef,
-    ) -> SnapshotSources:
+            resolve_snapshot_file_ref(snapshot, member) for member in identities
+        )
+
+    def _local_snapshot(self, source: LocalStageResultSnapshotRef) -> SnapshotSources:
         """Read the saved file list or register files from the older store layout."""
         registered = self.registry.snapshot(source)
         if registered is not None:
             return registered
-
         if source.workspace != self.repository_root or source.store != self.store:
             raise LocalStoreError("local snapshot belongs to a different store")
-
         directory = resolve_path(
-            self.repository_root,
-            f"{self.store}/{source.commit}",
-            operation="write",
+            self.repository_root, f"{self.store}/{source.commit}", operation="write"
         )
         if not directory.is_dir():
             raise LocalStoreError("local snapshot revision is missing")
-
         members = []
         locations = {}
         for path in sorted(directory.rglob("*")):
@@ -346,7 +295,6 @@
                 member = source_file(self.repository_root, member_path, path)
                 members.append(member)
                 locations[member_path] = (self._observe(path, custody="cache"),)
-
         try:
             inventory = SnapshotInventory(
                 source=source,
@@ -356,23 +304,211 @@
             raise LocalStoreError(
                 "local snapshot inventory differs from its revision"
             ) from error
-
+        record = SnapshotSources(inventory=inventory, locations=locations)
+        return self._register_snapshot(record)
+
+    def _register_snapshot(self, record: SnapshotSources) -> SnapshotSources:
+        """Save the snapshot's file list and look up its known local copies."""
+        self.registry.register_snapshot(record)
+        registered = self.registry.snapshot(record.inventory.source)
+        if registered is None:
+            raise LocalStoreError("registered snapshot is unavailable")
+        return registered
+
+    def _snapshot_record(
+        self, source: StageResultSnapshotRef, *, cloud: _CloudSource | None = None
+    ) -> SnapshotSources:
+        """Get the complete snapshot file list from the registry or cloud storage."""
+        if isinstance(source, LocalStageResultSnapshotRef):
+            return self._local_snapshot(source)
+        registered = None if self.task_owned_cache else self.registry.snapshot(source)
+        if registered is not None:
+            return registered
+        service = self._cloud(source, cloud)
         record = SnapshotSources(
-            inventory=inventory,
-            locations=locations,
-        )
-        self.registry.register_snapshot(record)
+            inventory=SnapshotInventory(
+                source=source, source_files=service.list_files(source)
+            )
+        )
+        if not self.task_owned_cache:
+            return self._register_snapshot(record)
         return record
 
+    def _reference(
+        self, location: StorageModel, *, cloud: _CloudSource | None = None
+    ) -> ResolvedFileRef:
+        """Look up the file's recorded size and SHA-256 hash."""
+        if isinstance(location, GitFileRef):
+            raise TypeError("Git source retrieval remains with its Git reader")
+        source = TypeAdapter(StageResultSnapshotRef).validate_python(
+            location.model_dump(exclude={"path"})
+        )
+        for member in self._snapshot_record(source, cloud=cloud).inventory.source_files:
+            if member.path == location.path:
+                return resolve_snapshot_file_ref(source, member)
+        raise LocalStoreError("immutable file is outside the snapshot inventory")
+
+    def fetch(
+        self, location: StorageModel, *, cloud: _CloudSource | None = None
+    ) -> bytes:
+        """Read and check the file at the recorded address."""
+        return self.read(self._reference(location, cloud=cloud), cloud=cloud)
+
+    def path(self, location: StorageModel) -> Path:
+        """Find the file's current local path and check its bytes."""
+        return self.resolve(self._reference(location))
+
+    def resolve(
+        self, reference: ResolvedFileRef, *, cloud: _CloudSource | None = None
+    ) -> Path:
+        """Find and check a registered original or stored copy of the file."""
+        resolved = self._resolve(reference, as_bytes=False, cloud=cloud)
+        assert isinstance(resolved, Path)
+        return resolved
+
+    def read(
+        self, reference: ResolvedFileRef, *, cloud: _CloudSource | None = None
+    ) -> bytes:
+        """Read the file once and check its byte count and SHA-256."""
+        return self.read_resolved(reference, cloud=cloud)[0]
+
+    def read_resolved(
+        self, reference: ResolvedFileRef, *, cloud: _CloudSource | None = None
+    ) -> tuple[bytes, Path]:
+        """Read and check the file, returning its bytes and local path."""
+        resolved = self._resolve(reference, as_bytes=True, cloud=cloud)
+        assert isinstance(resolved, tuple)
+        return resolved
+
+    def cached_read(self, reference: ResolvedFileRef) -> tuple[bytes, Path] | None:
+        """Read cached bytes if their byte count and SHA-256 match the reference."""
+        raw = self.downloads.read(reference)
+        return None if raw is None else (raw, self.downloads.path(reference))
+
+    def cache_verified_bytes(self, reference: ResolvedFileRef, raw: bytes) -> Path:
+        """Store bytes that the caller has already checked against the reference."""
+        self.downloads.write(reference, raw)
+        return self.downloads.path(reference)
+
+    def _resolve(
+        self,
+        reference: ResolvedFileRef,
+        *,
+        as_bytes: bool,
+        cloud: _CloudSource | None,
+    ) -> tuple[bytes, Path] | Path:
+        """Check a registered local copy or restore a missing cloud file."""
+        location = reference.stored_at
+        if isinstance(location, GitFileRef):
+            raise TypeError("Git source retrieval remains with its Git reader")
+        source = TypeAdapter(StageResultSnapshotRef).validate_python(
+            location.model_dump(exclude={"path"})
+        )
+        record = self._snapshot_record(source, cloud=cloud)
+        member = SnapshotFileRef(
+            path=location.path, sha256=reference.sha256, bytes=reference.bytes
+        )
+        failure: VerificationError | None = None
+        if member not in record.inventory.source_files:
+            raise VerificationError(
+                "resolved file differs from its snapshot inventory"
+            )
+        aliases = sorted(
+            record.locations.get(member.path, ()),
+            key=lambda alias: alias.custody == "cache",
+        )
+        for alias in aliases:
+            if alias.retired:
+                continue
+            try:
+                path = resolve_path(
+                    self.repository_root, alias.path, operation="read"
+                )
+                status = path.stat()
+                if (status.st_dev, status.st_ino) != alias.observed_stat[:2]:
+                    continue
+                if as_bytes:
+                    return VerifiedObjectCache.read_path(reference, path), path
+                return VerifiedObjectCache.verify_path(reference, path)
+            except (FileNotFoundError, PathError):
+                continue
+            except VerificationError as error:
+                if alias.custody != "cache":
+                    raise
+                failure = error
+        cache = (
+            self._objects
+            if isinstance(source, LocalStageResultSnapshotRef)
+            else self.downloads
+        )
+        cached = cache.read(reference) if as_bytes else cache.verified_path(reference)
+        if cached is not None:
+            if not self.task_owned_cache:
+                self.registry.record_materialization(
+                    source, member, cache.path(reference), custody="cache"
+                )
+            if isinstance(cached, bytes):
+                return cached, cache.path(reference)
+            return cached
+        if isinstance(source, LocalStageResultSnapshotRef):
+            if failure is not None:
+                raise failure
+            raise LocalStoreError("registered local payload is unavailable")
+        service = self._cloud(location, cloud)
+        if isinstance(service.provider, HuggingFaceProvider):
+            service.provider.stream_files = True
+        temporary = cache.temporary_path(reference)
+        try:
+            restored = service.fetch_to_path(reference, temporary)
+            installed = cache.adopt_verified_path(reference, restored)
+        finally:
+            temporary.unlink(missing_ok=True)
+        if not self.task_owned_cache:
+            self.registry.record_materialization(
+                source, member, installed, custody="cache"
+            )
+        return (installed.read_bytes(), installed) if as_bytes else installed
+
+    def _cloud(
+        self,
+        location: StorageModel | CloudStageResultSnapshotRef,
+        cloud: _CloudSource | None = None,
+    ) -> ViperCloud:
+        """Create or reuse a cloud service after local lookup fails."""
+        if cloud is not None:
+            return cloud() if callable(cloud) else cloud
+        if isinstance(
+            location, (ViperCloudFileRef, ViperCloudStageResultSnapshotRef)
+        ):
+            return viper_cloud(self.repository_root)
+        if isinstance(
+            location, (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef)
+        ):
+            return ViperCloud.for_snapshot(self.repository_root, location)
+        if isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
+            return ViperCloud.for_reference(self.repository_root, location)
+        raise TypeError("reference is not cloud-backed")
+
+    def snapshot_files(
+        self,
+        snapshot: StageResultSnapshotRef,
+        *,
+        cloud: _CloudSource | None = None,
+    ) -> tuple[SnapshotFileRef, ...]:
+        """List every recorded file with its byte count and SHA-256."""
+        return self._snapshot_record(snapshot, cloud=cloud).inventory.source_files
+
     def list_snapshot_files(
         self,
-        snapshot: LocalStageResultSnapshotRef,
+        snapshot: StageResultSnapshotRef,
+        *,
+        cloud: _CloudSource | None = None,
     ) -> tuple[RepoRelPath, ...]:
         """Return the complete recorded file list, including files absent locally."""
         return tuple(
-            member.path
-            for member in self._local_snapshot(snapshot).inventory.source_files
-        )
+            member.path for member in self.snapshot_files(snapshot, cloud=cloud)
+        )
+
 
 
 def local_artifact_store(
```

**File: `src/viper/_source.py`**

[Complete proposed file](replace/src/viper/_source.py) · [Generated diff](diff/src/viper/_source.py.diff)

```diff
--- a/src/viper/_source.py
+++ b/src/viper/_source.py
@@ -1,4 +1,4 @@
-"""Retrieve exact source and immutable output bytes for run execution."""
+"""Read the source and saved output files needed to execute a run."""
 
 from __future__ import annotations
 
@@ -21,6 +21,7 @@
     HuggingFaceFileRef,
     HuggingFaceStageResultSnapshotRef,
     LocalFileRef,
+    LocalStageResultSnapshotRef,
     ResolvedFileRef,
     ResolvedGitFileRef,
     ResolvedRunRef,
@@ -36,7 +37,7 @@
 
 
 def run_git(repository_root: Path, *arguments: str) -> bytes:
-    """Run one bounded Git query against the selected repository."""
+    """Read Git data from the selected repository."""
     try:
         return subprocess.run(
             ("git", "-C", str(repository_root), *arguments),
@@ -48,7 +49,7 @@
 
 
 class RunFetcher:
-    """Read run files and reuse their content checks within one execution."""
+    """Read files and remember checks already completed during this execution."""
 
     def __init__(
         self,
@@ -58,11 +59,11 @@
         *,
         cache_root: Path | None = None,
     ) -> None:
-        """Bind retrieval and its per-file cache to one execution.
-
-        cache_root selects a task-owned cache beneath the workspace.
-        Files must remain unchanged for the lifetime of the fetcher. A new
-        execution creates a new fetcher and checks pre-existing files again.
+        """Set up file access for one execution.
+
+        cache_root keeps temporary transfer files separate from shared storage.
+        Files used by this fetcher must stay unchanged until the execution ends.
+        A new fetcher checks existing files again.
         """
         self.repository_root = repository_root.resolve()
         self.store = store
@@ -75,9 +76,12 @@
         self._external_git_files: dict[GitFileRef, bytes] = {}
         self._external_git_cache_bytes = 0
         self._external_git_checkout_root = self.cache_root / "git-checkouts"
-        self._verified_objects = VerifiedObjectCache(
-            self.cache_root / "verified-objects"
-        )
+        if self.cache_root != self.repository_root / ".viper/cache":
+            self.store = LocalArtifactStore(
+                store.repository_root,
+                store.store,
+                cache_root=self.cache_root / "verified-objects",
+            )
         self._verified_paths: dict[ResolvedFileRef, Path] = {}
         self._verified_producers: dict[
             tuple[ResolvedRunRef, VerificationPolicy],
@@ -85,8 +89,13 @@
         ] = {}
         self._cloud_services: dict[tuple[str, str, str], ViperCloud] = {}
 
+    @property
+    def _verified_objects(self) -> VerifiedObjectCache:
+        """Return the store cache used by existing transfer code."""
+        return self.store.downloads
+
     def _cloud_service(self, reference: CloudReference) -> ViperCloud:
-        """Keep a provider's sealed-manifest cache for this fetcher's lifetime."""
+        """Reuse a cloud service and its checked file lists during this execution."""
         if isinstance(reference, (GcsFileRef, GcsStageResultSnapshotRef)):
             key = ("gcs", reference.bucket, reference.prefix)
         elif isinstance(
@@ -108,12 +117,31 @@
             cloud.provider, HuggingFaceProvider
         ):
             cloud.provider.cache_dir = self.cache_root / "hub"
-            cloud.provider.stream_files = True
         self._cloud_services[key] = cloud
         return cloud
 
+    def _local_store(
+        self, location: LocalFileRef | LocalStageResultSnapshotRef
+    ) -> LocalArtifactStore:
+        """Check this workspace, then the workspace saved in the reference."""
+        if (
+            location.workspace == self.store.repository_root
+            and location.store == self.store.store
+        ):
+            return self.store
+        source = (
+            LocalStageResultSnapshotRef.model_validate(
+                location.model_dump(exclude={"path"})
+            )
+            if isinstance(location, LocalFileRef)
+            else location
+        )
+        if self.store.registry.snapshot(source) is not None:
+            return self.store
+        return local_artifact_store(location)
+
     def __call__(self, location: StorageModel) -> bytes:
-        """Retrieve one file from its declared immutable backend."""
+        """Read a file from the location recorded in its reference."""
         if isinstance(location, GitFileRef):
             if str(location.repository) != self.source_repository:
                 try:
@@ -140,83 +168,62 @@
             location,
             (GcsFileRef, HuggingFaceFileRef, ViperCloudFileRef),
         ):
-            cloud = self._cloud_service(location)
-            return cloud.fetch(location)
+            return self.store.fetch(
+                location, cloud=lambda: self._cloud_service(location)
+            )
         if isinstance(location, LocalFileRef):
-            return local_artifact_store(location).fetch(location)
+            return self._local_store(location).fetch(location)
         return self.store.fetch(location)
 
     def read(self, reference: ResolvedFileRef) -> bytes:
-        """Read bytes, checking size and SHA-256 on first use in this execution."""
+        """Read the file and check its byte count and SHA-256 on first use."""
         remembered = self._verified_paths.get(reference)
         if remembered is not None:
             return remembered.read_bytes()
-        cacheable = not isinstance(reference.stored_at, LocalFileRef)
-        if cacheable:
-            cached = self._verified_objects.read(reference)
+        if isinstance(reference.stored_at, GitFileRef):
+            cached = self.store.cached_read(reference)
             if cached is not None:
-                self._verified_paths[reference] = self._verified_objects.path(reference)
-                return cached
-        raw = verify_resolved_file_bytes(reference, self(reference.stored_at))
-        if cacheable:
-            self._verified_objects.write(reference, raw)
-            path = self._verified_objects.path(reference)
-        else:
-            assert isinstance(reference.stored_at, LocalFileRef)
-            path = local_artifact_store(reference.stored_at).path(reference.stored_at)
+                raw, path = cached
+            else:
+                raw = verify_resolved_file_bytes(reference, self(reference.stored_at))
+                path = self.store.cache_verified_bytes(reference, raw)
+        else:
+            store = (
+                self._local_store(reference.stored_at)
+                if isinstance(reference.stored_at, LocalFileRef)
+                else self.store
+            )
+            cloud = (
+                None
+                if isinstance(reference.stored_at, LocalFileRef)
+                else lambda: self._cloud_service(reference.stored_at)
+            )
+            raw, path = store.read_resolved(reference, cloud=cloud)
         self._verified_paths[reference] = path
         return raw
 
     def path(self, reference: ResolvedFileRef) -> Path:
-        """Return a local path after its first size and SHA-256 check per execution."""
+        """Return a local path after checking the file on first use."""
         remembered = self._verified_paths.get(reference)
         if remembered is not None:
             return remembered
-
-        if isinstance(reference.stored_at, LocalFileRef):
-            path = local_artifact_store(reference.stored_at).path(reference.stored_at)
-            if path.stat().st_size != reference.bytes:
-                raise VerificationError(
-                    f"byte-count mismatch: expected {reference.bytes}, "
-                    f"received {path.stat().st_size}"
-                )
-            with path.open("rb") as stream:
-                digest = hashlib.file_digest(stream, "sha256").hexdigest()
-            if digest != reference.sha256:
-                raise VerificationError(
-                    f"SHA-256 mismatch: expected {reference.sha256}, received {digest}"
-                )
-            self._verified_paths[reference] = path
-            return path
-
-        if not isinstance(
-            reference.stored_at,
-            (GcsFileRef, HuggingFaceFileRef, ViperCloudFileRef),
-        ):
+        if isinstance(reference.stored_at, GitFileRef):
             self.read(reference)
             return self._verified_paths[reference]
-
-        cached = self._verified_objects.verified_path(reference)
-        if cached is not None:
-            self._verified_paths[reference] = cached
-            return cached
-
-        temporary = self._verified_objects.temporary_path(reference)
-        try:
-            cloud = self._cloud_service(reference.stored_at)
-            restored = cloud.fetch_to_path(reference, temporary)
-            cached = self._verified_objects.adopt_verified_path(reference, restored)
-        finally:
-            temporary.unlink(missing_ok=True)
-
-        self._verified_paths[reference] = cached
-        return cached
+        if isinstance(reference.stored_at, LocalFileRef):
+            path = self._local_store(reference.stored_at).resolve(reference)
+        else:
+            path = self.store.resolve(
+                reference, cloud=lambda: self._cloud_service(reference.stored_at)
+            )
+        self._verified_paths[reference] = path
+        return path
 
     def remember_path(self, reference: ResolvedFileRef, path: Path) -> None:
-        """Cache a file using the size and hash returned by successful publication.
+        """Remember a file whose byte count and SHA-256 were checked during publication.
 
         The caller must pass the published file or its unchanged upload source.
-        Publication must establish the reference's SHA-256 before registration.
+        Its bytes must still match the reference.
         """
         if path.stat().st_size != reference.bytes:
             raise VerificationError(
@@ -230,7 +237,7 @@
         reference: ResolvedRunRef,
         policy: VerificationPolicy,
     ) -> VerifiedProducerRun | None:
-        """Return producer structure verified earlier in this execution."""
+        """Return a producer run already verified during this execution."""
         return self._verified_producers.get((reference, policy))
 
     def remember_verified_producer(
@@ -239,20 +246,22 @@
         policy: VerificationPolicy,
         producer: VerifiedProducerRun,
     ) -> None:
-        """Reuse one immutable producer proof without retaining artifact bytes."""
+        """Remember a verified producer run for later reads in this execution."""
         self._verified_producers[(reference, policy)] = producer
 
     def snapshot_files(
         self, snapshot: CloudStageResultSnapshotRef
     ) -> tuple[SnapshotFileRef, ...]:
-        """Return each file's path, size, and SHA-256 hash from a cloud snapshot."""
-        return self._cloud_service(snapshot).list_files(snapshot)
+        """List every file in a cloud snapshot with its byte count and SHA-256."""
+        return self.store.snapshot_files(
+            snapshot, cloud=lambda: self._cloud_service(snapshot)
+        )
 
     def list_snapshot_files(
         self,
         snapshot: StageResultSnapshotRef,
     ) -> tuple[RepoRelPath, ...]:
-        """List every regular file in one immutable stage snapshot."""
+        """Return the snapshot's complete list of file paths."""
         if isinstance(
             snapshot,
             (
@@ -262,14 +271,14 @@
             ),
         ):
             return tuple(file.path for file in self.snapshot_files(snapshot))
-        return local_artifact_store(snapshot).list_snapshot_files(snapshot)
+        return self._local_store(snapshot).list_snapshot_files(snapshot)
 
 
 def resolve_git_file(
     fetcher: RunFetcher,
     location: GitFileRef,
 ) -> ResolvedGitFileRef:
-    """Retrieve and identify one exact file in the local Git checkout."""
+    """Read a file at a fixed Git commit and record its byte count and SHA-256."""
     raw = fetcher(location)
     return ResolvedGitFileRef(
         sha256=hashlib.sha256(raw).hexdigest(),
```

**File: `src/viper/_verified_cache.py`**

[Complete proposed file](replace/src/viper/_verified_cache.py) · [Generated diff](diff/src/viper/_verified_cache.py.diff)

```diff
--- a/src/viper/_verified_cache.py
+++ b/src/viper/_verified_cache.py
@@ -1,4 +1,4 @@
-"""Persist immutable bytes after validating their recorded content identity."""
+"""Check file bytes and save checked files in the local cache."""
 
 from __future__ import annotations
 
@@ -14,35 +14,57 @@
 
 @dataclass(frozen=True)
 class VerifiedObjectCache:
-    """Store files by SHA-256 and revalidate every cache hit."""
+    """Store files by SHA-256 and check their bytes before reuse."""
 
     root: Path
 
+    @staticmethod
+    def read_path(reference: ResolvedFileRef, path: Path) -> bytes:
+        """Read the file once and check its byte count and SHA-256."""
+        raw = path.read_bytes()
+        if len(raw) != reference.bytes:
+            raise VerificationError(
+                f"byte-count mismatch: expected {reference.bytes}, received {len(raw)}"
+            )
+        digest = hashlib.sha256(raw).hexdigest()
+        if digest != reference.sha256:
+            raise VerificationError(
+                f"SHA-256 mismatch: expected {reference.sha256}, received {digest}"
+            )
+        return raw
+
+    @staticmethod
+    def verify_path(reference: ResolvedFileRef, path: Path) -> Path:
+        """Read the file in chunks to check its byte count and SHA-256."""
+        size = path.stat().st_size
+        if size != reference.bytes:
+            raise VerificationError(
+                f"byte-count mismatch: expected {reference.bytes}, received {size}"
+            )
+        with path.open("rb") as stream:
+            digest = hashlib.file_digest(stream, "sha256").hexdigest()
+        if digest != reference.sha256:
+            raise VerificationError(
+                f"SHA-256 mismatch: expected {reference.sha256}, received {digest}"
+            )
+        return path
+
     def read(self, reference: ResolvedFileRef) -> bytes | None:
-        """Return cached bytes only when both recorded identity fields match."""
-        path = self._path(reference.sha256)
+        """Return cached bytes if their byte count and SHA-256 match the reference."""
         try:
-            raw = path.read_bytes()
-        except FileNotFoundError:
+            return self.read_path(reference, self._path(reference.sha256))
+        except (FileNotFoundError, VerificationError):
             return None
-        if self._matches(reference, raw):
-            return raw
-        return None
 
     def verified_path(self, reference: ResolvedFileRef) -> Path | None:
-        """Return a cached path only when its complete identity still matches."""
-        path = self._path(reference.sha256)
+        """Return the cached path if its file matches the reference."""
         try:
-            if path.stat().st_size != reference.bytes:
-                return None
-            with path.open("rb") as stream:
-                digest = hashlib.file_digest(stream, "sha256").hexdigest()
-        except OSError:
+            return self.verify_path(reference, self._path(reference.sha256))
+        except (OSError, VerificationError):
             return None
-        return path if digest == reference.sha256 else None
 
     def adopt_verified_path(self, reference: ResolvedFileRef, source: Path) -> Path:
-        """Atomically retain a path already verified by its storage client."""
+        """Move a downloaded file into the cache after the client has checked it."""
         if source.stat().st_size != reference.bytes:
             raise VerificationError(
                 "retrieved file size differs from its resolved reference"
@@ -53,7 +75,7 @@
         return path
 
     def temporary_path(self, reference: ResolvedFileRef) -> Path:
-        """Allocate an absent same-filesystem path for one streamed restore."""
+        """Choose a temporary download path on the same filesystem as the cache."""
         parent = self._path(reference.sha256).parent
         parent.mkdir(parents=True, exist_ok=True)
         descriptor, temporary_name = tempfile.mkstemp(dir=parent)
@@ -63,15 +85,11 @@
         return temporary
 
     def path(self, reference: ResolvedFileRef) -> Path:
-        """Return the content-addressed path for one resolved reference."""
+        """Build the cache path from the recorded SHA-256."""
         return self._path(reference.sha256)
 
     def write(self, reference: ResolvedFileRef, raw: bytes) -> None:
-        """Atomically store bytes in the cache.
-
-        Callers must verify raw's byte count and SHA-256 against reference
-        before calling write().
-        """
+        """Save bytes the caller has checked, replacing the cache file in one rename."""
         path = self._path(reference.sha256)
         path.parent.mkdir(parents=True, exist_ok=True)
         descriptor, temporary_name = tempfile.mkstemp(dir=path.parent)
@@ -85,12 +103,8 @@
             Path(temporary_name).unlink(missing_ok=True)
 
     def _path(self, sha256: str) -> Path:
-        """Shard one digest beneath the cache root."""
-        return self.root / sha256[:2] / sha256
-
-    @staticmethod
-    def _matches(reference: ResolvedFileRef, raw: bytes) -> bool:
-        """Compare bytes with the complete recorded content identity."""
-        return len(raw) == reference.bytes and (
-            hashlib.sha256(raw).hexdigest() == reference.sha256
-        )
+        """Build the cache filename from the SHA-256 hash."""
+        path = self.root / sha256[:2] / sha256
+        if any(part.is_symlink() for part in (self.root, path.parent, path)):
+            raise VerificationError("verified payload path contains a symlink")
+        return path
```

**File: `src/viper/_storage_locks.py`**

[Complete proposed file](add/src/viper/_storage_locks.py) · [Generated diff](diff/src/viper/_storage_locks.py.diff)

```diff
--- a/src/viper/_storage_locks.py
+++ b/src/viper/_storage_locks.py
@@ -0,0 +1,112 @@
+"""Prevent Viper from deleting files while workflows still need them."""
+
+from __future__ import annotations
+
+import fcntl
+import os
+from collections.abc import Generator
+from contextlib import ExitStack, contextmanager
+from pathlib import Path
+from threading import Lock
+from types import TracebackType
+from typing import Self
+
+from ._schema import RepoRelPath, validate_repo_rel_path
+from .references import FileIdentity
+from .repository import resolve_path
+
+
+class PayloadLocks:
+    """Share read locks between workflows and give cleanup exclusive access."""
+
+    def __init__(
+        self, repository_root: Path, store: RepoRelPath = ".viper/store"
+    ) -> None:
+        """Keep lock files separate from the files cleanup may delete."""
+        self.repository_root = repository_root.resolve(strict=True)
+        self.store = validate_repo_rel_path(store)
+
+    def _open(self, identity: FileIdentity) -> int:
+        """Open the lock file for this file hash."""
+        path = resolve_path(
+            self.repository_root,
+            f"{self.store}/.locks/{identity.sha256[:2]}/{identity.sha256}.lock",
+            operation="write",
+        )
+        path.parent.mkdir(parents=True, exist_ok=True)
+        return os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
+
+    @contextmanager
+    def reader(self, identity: FileIdentity) -> Generator[None, None, None]:
+        """Keep a read lock until the caller exits this block."""
+        descriptor = self._open(identity)
+        try:
+            fcntl.flock(descriptor, fcntl.LOCK_SH)
+            yield
+        finally:
+            os.close(descriptor)
+
+    @contextmanager
+    def exclusive(self, identity: FileIdentity) -> Generator[bool, None, None]:
+        """Try an exclusive lock without waiting and report whether it succeeded."""
+        descriptor = self._open(identity)
+        try:
+            try:
+                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
+            except BlockingIOError:
+                yield False
+                return
+            yield True
+        finally:
+            os.close(descriptor)
+
+
+class WorkflowReaders:
+    """Keep files protected until all work in the workflow has finished.
+
+    Share this instance across managed stages. Returning from one read or
+    stage does not release its locks. Close it after all managed work ends.
+    """
+
+    def __init__(self, locks: PayloadLocks) -> None:
+        """Use the same file locks as cleanup."""
+        self._locks = locks
+        self._held: set[tuple[str, int]] = set()
+        self._stack = ExitStack()
+        self._mutex = Lock()
+        self._closed = False
+
+    def __enter__(self) -> Self:
+        """Return this workflow lock holder."""
+        return self
+
+    def hold(self, identity: FileIdentity) -> None:
+        """Lock this file until the workflow closes, reusing an existing lock."""
+        key = (identity.sha256, identity.bytes)
+        with self._mutex:
+            if self._closed:
+                raise RuntimeError("workflow readers are already closed")
+            if key not in self._held:
+                self._stack.enter_context(self._locks.reader(identity))
+                self._held.add(key)
+
+    def close(self) -> None:
+        """Release all locks after every managed user has finished."""
+        with self._mutex:
+            if self._closed:
+                return
+            self._closed = True
+            self._stack.close()
+            self._held.clear()
+
+    def __exit__(
+        self,
+        kind: type[BaseException] | None,
+        error: BaseException | None,
+        trace: TracebackType | None,
+    ) -> None:
+        """Release locks when the block ends, including on exceptions.
+
+        Cleanup must still check workflow success and current retention settings.
+        """
+        self.close()
```

**File: `tests/test_shared_storage.py`**

[Complete proposed file](add/tests/test_shared_storage.py) · [Generated diff](diff/tests/test_shared_storage.py.diff)

```diff
--- a/tests/test_shared_storage.py
+++ b/tests/test_shared_storage.py
@@ -0,0 +1,514 @@
+"""Observe shared resolution, immutable listing, and bounded transfer staging."""
+
+from __future__ import annotations
+
+import hashlib
+from pathlib import Path
+from typing import cast
+
+import httpx
+import pytest
+from huggingface_hub import HfApi
+
+from viper._cloud import (
+    HuggingFaceRepository,
+    LocalSource,
+    RevisionManifest,
+    SnapshotInventory,
+    SnapshotSources,
+    canonical_json_bytes,
+)
+from viper._source import RunFetcher
+from viper._storage_registry import StorageRegistryError
+from viper.cloud import ViperCloud
+from viper.evidence import VerificationError
+from viper.huggingface import HuggingFaceProvider
+from viper.references import (
+    GcsStageResultSnapshotRef,
+    HuggingFaceFileRef,
+    HuggingFaceStageResultSnapshotRef,
+    LocalFileRef,
+    LocalStageResultSnapshotRef,
+    ResolvedFileRef,
+    SnapshotFileRef,
+    StageResultSnapshotRef,
+    resolve_snapshot_file_ref,
+)
+from viper.storage import (
+    LocalArtifactStore,
+    LocalStoreError,
+    content_revision,
+    snapshot_file,
+)
+
+
+class MemoryCloud:
+    """Represent verified cloud downloads without network access."""
+
+    def __init__(self, files: dict[str, bytes]) -> None:
+        """Bind one complete published inventory and count payload transfers."""
+        self.files = files
+        self.provider = object()
+        self.members = tuple(
+            snapshot_file(path, raw) for path, raw in sorted(files.items())
+        )
+        self.snapshot = GcsStageResultSnapshotRef(
+            bucket="private-jep",
+            owner="owner",
+            workspace="experiments",
+            revision=content_revision(self.members),
+        )
+        self.downloads = 0
+        self.fail_download = False
+
+    def list_files(self, snapshot: object) -> tuple[SnapshotFileRef, ...]:
+        """Return the sealed full inventory used by the storage resolver."""
+        assert snapshot == self.snapshot
+        return self.members
+
+    def fetch_to_path(self, reference: ResolvedFileRef, target: Path) -> Path:
+        """Honor the provider contract by verifying before returning a path."""
+        self.downloads += 1
+        if self.fail_download:
+            target.write_bytes(b"partial")
+            raise VerificationError("cloud download was interrupted")
+        raw = self.files[reference.stored_at.path]
+        assert len(raw) == reference.bytes
+        assert hashlib.sha256(raw).hexdigest() == reference.sha256
+        target.write_bytes(raw)
+        return target
+
+
+def test_local_members_share_payload_without_changing_references(
+    tmp_path: Path,
+) -> None:
+    """Different immutable member addresses share one verified physical payload."""
+    store = LocalArtifactStore(tmp_path)
+    first = store.resolved_files({"first/weights.bin": b"same weights"})[0]
+    second = store.resolved_files({"second/weights.bin": b"same weights"})[0]
+
+    assert first.stored_at != second.stored_at
+    assert first.stored_at.path == "first/weights.bin"
+    assert second.stored_at.path == "second/weights.bin"
+    assert store.resolve(first) == store.resolve(second)
+    assert store.resolve(first).read_bytes() == b"same weights"
+    assert store.resolve(first).is_relative_to(tmp_path / ".viper/store/objects")
+
+
+def test_registered_original_is_used_without_a_payload_copy(tmp_path: Path) -> None:
+    """Explicitly registered sealed originals serve readers directly."""
+    original = tmp_path / "outputs/checkpoint.pt"
+    original.parent.mkdir()
+    original.write_bytes(b"checkpoint")
+    member = snapshot_file("weights.bin", b"checkpoint")
+    source = LocalStageResultSnapshotRef(
+        workspace=tmp_path, commit=content_revision((member,))
+    )
+    status = original.stat()
+    store = LocalArtifactStore(tmp_path)
+    store.registry.register_snapshot(
+        SnapshotSources(
+            inventory=SnapshotInventory(source=source, source_files=(member,)),
+            locations={
+                member.path: (
+                    LocalSource(
+                        path="outputs/checkpoint.pt",
+                        observed_stat=(
+                            status.st_dev, status.st_ino,
+                            status.st_mtime_ns, status.st_ctime_ns,
+                        ),
+                        custody="output",
+                    ),
+                )
+            },
+        )
+    )
+
+    assert store.resolve(resolve_snapshot_file_ref(source, member)) == original
+    assert not (tmp_path / ".viper/store/objects").exists()
+
+
+def test_listing_survives_partial_residency_and_restart(tmp_path: Path) -> None:
+    """Payload loss cannot silently turn an immutable bundle into a shorter listing."""
+    store = LocalArtifactStore(tmp_path)
+    source = store.snapshot(
+        {"bundle/config.json": b"{}", "bundle/weights.bin": b"weights"}
+    )
+    references = store.resolved_files(
+        {"bundle/config.json": b"{}", "bundle/weights.bin": b"weights"}
+    )
+    store.resolve(references[0]).unlink()
+    restarted = LocalArtifactStore(tmp_path)
+
+    assert restarted.list_snapshot_files(source) == (
+        "bundle/config.json", "bundle/weights.bin"
+    )
+    with pytest.raises(LocalStoreError, match="unavailable"):
+        restarted.resolve(references[0])
+    assert restarted.read(references[1]) == b"weights"
+
+
+def test_complete_legacy_snapshot_is_adopted_before_partial_residency(
+    tmp_path: Path,
+) -> None:
+    """Existing resident snapshots gain validated inventory without rewritten refs."""
+    files = {"bundle/a.bin": b"first", "bundle/b.bin": b"second"}
+    source = LocalStageResultSnapshotRef(
+        workspace=tmp_path, commit=content_revision(files)
+    )
+    directory = tmp_path / ".viper/store" / source.commit
+    for name, raw in files.items():
+        path = directory / name
+        path.parent.mkdir(parents=True, exist_ok=True)
+        path.write_bytes(raw)
+    store = LocalArtifactStore(tmp_path)
+
+    assert store.list_snapshot_files(source) == tuple(files)
+    (directory / "bundle/a.bin").unlink()
+    assert LocalArtifactStore(tmp_path).list_snapshot_files(source) == tuple(files)
+
+
+def test_corrupt_registered_original_is_reported(tmp_path: Path) -> None:
+    """An original with changed bytes is not silently replaced by another copy."""
+    original = tmp_path / "original.bin"
+    original.write_bytes(b"right")
+    member = snapshot_file("artifact.bin", b"right")
+    source = LocalStageResultSnapshotRef(
+        workspace=tmp_path, commit=content_revision((member,))
+    )
+    status = original.stat()
+    store = LocalArtifactStore(tmp_path)
+    store.registry.register_snapshot(
+        SnapshotSources(
+            inventory=SnapshotInventory(source=source, source_files=(member,)),
+            locations={member.path: (LocalSource(
+                path="original.bin",
+                observed_stat=(
+                    status.st_dev, status.st_ino,
+                    status.st_mtime_ns, status.st_ctime_ns,
+                ),
+                custody="output",
+            ),)},
+        )
+    )
+    original.write_bytes(b"wrong")
+
+    with pytest.raises(VerificationError, match="SHA-256 mismatch"):
+        store.resolve(resolve_snapshot_file_ref(source, member))
+
+
+def test_run_fetcher_uses_shared_store_across_executions(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Ordinary cloud readers share the store instead of creating a second cache."""
+    cloud = MemoryCloud({"weights.bin": b"weights"})
+    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
+    monkeypatch.setattr(
+        RunFetcher, "_cloud_service", lambda *_: cast(ViperCloud, cloud)
+    )
+    first = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
+    path = first.path(reference)
+    second = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
+
+    assert second.read(reference) == b"weights"
+    assert second.path(reference) == path
+    assert cloud.downloads == 1
+    assert path.is_relative_to(tmp_path / ".viper/store/objects")
+    assert not (tmp_path / ".viper/cache/verified-objects").exists()
+
+
+def test_failed_download_never_installs_a_shared_payload(tmp_path: Path) -> None:
+    """An interrupted restore preserves inventory while discarding partial bytes."""
+    cloud = MemoryCloud({"weights.bin": b"weights"})
+    cloud.fail_download = True
+    store = LocalArtifactStore(tmp_path)
+    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
+
+    with pytest.raises(VerificationError, match="interrupted"):
+        store.resolve(reference, cloud=cast(ViperCloud, cloud))
+    assert not store.downloads.path(reference).exists()
+    assert store.registry.snapshot(cloud.snapshot) is not None
+    assert all(
+        path.is_dir() for path in (tmp_path / ".viper/store/objects").rglob("*")
+    )
+
+
+def test_bounded_transfer_downloads_stay_in_their_task_cache(tmp_path: Path) -> None:
+    """Independent transfer verification does not borrow a source's local bytes."""
+    ordinary = LocalArtifactStore(tmp_path)
+    original = ordinary.resolved_files({"weights.bin": b"weights"})[0]
+    cloud = MemoryCloud({"weights.bin": b"weights"})
+    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
+    cache_root = tmp_path / "transfer/cache/verified-objects"
+    bounded = LocalArtifactStore(tmp_path, cache_root=cache_root)
+
+    path = bounded.resolve(reference, cloud=cast(ViperCloud, cloud))
+    assert path.is_relative_to(cache_root)
+    assert path != ordinary.resolve(original)
+    assert cloud.downloads == 1
+    assert bounded.registry.snapshot(cloud.snapshot) is None
+
+
+def test_corrupt_shared_cache_is_repaired_on_the_next_execution(
+    tmp_path: Path,
+) -> None:
+    """Verified cloud restoration may replace a corrupt cache generation."""
+    cloud = MemoryCloud({"weights.bin": b"weights"})
+    reference = resolve_snapshot_file_ref(cloud.snapshot, cloud.members[0])
+    first = LocalArtifactStore(tmp_path)
+    path = first.resolve(reference, cloud=cast(ViperCloud, cloud))
+    path.write_bytes(b"changed")
+
+    restored = LocalArtifactStore(tmp_path).resolve(
+        reference, cloud=cast(ViperCloud, cloud)
+    )
+    assert restored == path
+    assert restored.read_bytes() == b"weights"
+    assert cloud.downloads == 2
+
+
+def test_republishing_exact_bytes_repairs_shared_cache_without_new_refs(
+    tmp_path: Path,
+) -> None:
+    """Local publication can repair its verified cache without changing identity."""
+    store = LocalArtifactStore(tmp_path)
+    reference = store.resolved_files({"weights.bin": b"weights"})[0]
+    store.resolve(reference).write_bytes(b"changed")
+
+    assert store.resolved_files({"weights.bin": b"weights"})[0] == reference
+    assert store.read(reference) == b"weights"
+
+
+def _register_original(
+    store: LocalArtifactStore,
+    source: StageResultSnapshotRef,
+    member: SnapshotFileRef,
+    original: Path,
+) -> ResolvedFileRef:
+    """Register a verified original without requiring its producing host to exist."""
+    status = original.stat()
+    store.registry.register_snapshot(
+        SnapshotSources(
+            inventory=SnapshotInventory(source=source, source_files=(member,)),
+            locations={
+                member.path: (
+                    LocalSource(
+                        path=original.relative_to(store.repository_root).as_posix(),
+                        observed_stat=(
+                            status.st_dev,
+                            status.st_ino,
+                            status.st_mtime_ns,
+                            status.st_ctime_ns,
+                        ),
+                        custody="output",
+                    ),
+                )
+            },
+        )
+    )
+    return resolve_snapshot_file_ref(source, member)
+
+
+def _no_cloud_client(*_args: object) -> ViperCloud:
+    """Fail if resident artifact access attempts to create a cloud client."""
+    raise AssertionError("resident artifact access must not create a cloud client")
+
+
+def test_fresh_fetcher_reuses_registered_original_without_cloud_client(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Separate runs use the registered original before another cache or cloud."""
+    store = LocalArtifactStore(tmp_path)
+    cached = store.resolved_files({"already-cached.bin": b"weights"})[0]
+    cached_path = store.resolve(cached)
+    original = tmp_path / "outputs/checkpoint.pt"
+    original.parent.mkdir()
+    original.write_bytes(b"weights")
+    published = MemoryCloud({"weights.bin": b"weights"})
+    reference = _register_original(
+        store, published.snapshot, published.members[0], original
+    )
+    monkeypatch.setattr(RunFetcher, "_cloud_service", _no_cloud_client)
+    first = RunFetcher(tmp_path, store, "")
+    second = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
+
+    assert cached_path != original
+    assert first.path(reference) == original
+    assert second.read(reference) == b"weights"
+    assert second.path(reference) == original
+    assert second.snapshot_files(published.snapshot) == published.members
+    assert second.list_snapshot_files(published.snapshot) == ("weights.bin",)
+
+
+def test_fetcher_uses_active_registry_for_foreign_local_reference(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """An immutable old-host reference resolves through the current host's binding."""
+    departed = tmp_path / "departed-workspace"
+    member = snapshot_file("weights.bin", b"weights")
+    source = LocalStageResultSnapshotRef(
+        workspace=departed, commit=content_revision((member,))
+    )
+    original = tmp_path / "checkpoint.pt"
+    original.write_bytes(b"weights")
+    store = LocalArtifactStore(tmp_path)
+    reference = _register_original(store, source, member, original)
+    monkeypatch.setattr("viper._source.local_artifact_store", _no_cloud_client)
+    fetcher = RunFetcher(tmp_path, store, "")
+
+    assert fetcher.path(reference) == original
+    assert fetcher.read(reference) == b"weights"
+    assert fetcher(reference.stored_at) == b"weights"
+    assert fetcher.list_snapshot_files(source) == ("weights.bin",)
+    assert isinstance(reference.stored_at, LocalFileRef)
+    assert reference.stored_at.workspace == departed
+    assert not departed.exists()
+
+
+def test_fetcher_propagates_invalid_active_registry_before_legacy_fallback(
+    tmp_path: Path,
+) -> None:
+    """A malformed current registry cannot be bypassed using a healthy old store."""
+    producer_root = tmp_path / "producer"
+    active_root = tmp_path / "active"
+    producer_root.mkdir()
+    active_root.mkdir()
+    producer = LocalArtifactStore(producer_root)
+    reference = producer.resolved_files({"weights.bin": b"weights"})[0]
+    current = LocalArtifactStore(active_root)
+    current.registry.path.parent.mkdir(parents=True)
+    current.registry.path.write_bytes(b"malformed SQLite storage registry")
+    fetcher = RunFetcher(active_root, current, "")
+
+    with pytest.raises(StorageRegistryError, match="invalid"):
+        fetcher.path(reference)
+    assert producer.read(reference) == b"weights"
+
+
+def _huggingface_cloud(
+    root: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> tuple[ViperCloud, ResolvedFileRef, httpx.Client, list[str]]:
+    """Use the actual HF streaming provider with mocked metadata and HTTP bytes."""
+    payload = b"weights"
+    member = snapshot_file("weights.bin", payload)
+    snapshot = HuggingFaceStageResultSnapshotRef(
+        repository="owner/checkpoint", commit="a" * 40, repo_type="model"
+    )
+    metadata = root / "metadata/revision-manifest.json"
+    metadata.parent.mkdir()
+    metadata.write_bytes(
+        canonical_json_bytes(
+            RevisionManifest(
+                owner="owner",
+                workspace="experiments",
+                revision=content_revision((member,)),
+                files=(member,),
+            )
+        )
+    )
+    provider = HuggingFaceProvider(
+        root, snapshot.repository, "model", api=HfApi(token=False)
+    )
+
+    def download_metadata(location: HuggingFaceFileRef) -> Path:
+        """Allow ordinary manifest retrieval while rejecting a second payload cache."""
+        assert location.path == ".viper/revision-manifest.json"
+        return metadata
+
+    requests: list[str] = []
+
+    def respond(request: httpx.Request) -> httpx.Response:
+        """Serve the single immutable payload through the streaming HTTP path."""
+        requests.append(request.url.path)
+        return httpx.Response(200, content=payload, request=request)
+
+    client = httpx.Client(transport=httpx.MockTransport(respond))
+    monkeypatch.setattr(provider, "_download", download_metadata)
+    monkeypatch.setattr("viper.huggingface.get_session", lambda: client)
+    cloud = ViperCloud(
+        root,
+        HuggingFaceRepository(repository=snapshot.repository, repo_type="model"),
+        provider=provider,
+    )
+    monkeypatch.setattr(ViperCloud, "for_reference", lambda *_: cloud)
+    return cloud, resolve_snapshot_file_ref(snapshot, member), client, requests
+
+
+def test_managed_huggingface_restore_streams_into_shared_store(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """An ordinary HF restore creates its verified payload only in shared storage."""
+    _, reference, client, requests = _huggingface_cloud(tmp_path, monkeypatch)
+    fetcher = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
+
+    with client:
+        restored = fetcher.path(reference)
+    assert restored.read_bytes() == b"weights"
+    assert restored.is_relative_to(tmp_path / ".viper/store/objects")
+    assert len(requests) == 1
+    assert requests[0].endswith("/weights.bin")
+
+
+def test_bounded_huggingface_restore_keeps_task_cache(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """Transfer verification streams to its own cache despite shared local bytes."""
+    ordinary = LocalArtifactStore(tmp_path)
+    resident = ordinary.resolved_files({"local-weights.bin": b"weights"})[0]
+    _, reference, client, requests = _huggingface_cloud(tmp_path, monkeypatch)
+    task_cache = tmp_path / "transfer/cache"
+    fetcher = RunFetcher(tmp_path, ordinary, "", cache_root=task_cache)
+
+    with client:
+        restored = fetcher.path(reference)
+    assert restored.read_bytes() == b"weights"
+    assert restored.is_relative_to(task_cache / "verified-objects")
+    assert restored != ordinary.resolve(resident)
+    assert len(requests) == 1
+    assert requests[0].endswith("/weights.bin")
+
+
+def test_registered_cache_hit_does_not_construct_cloud_provider(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """A later run can reuse a verified shared cache without cloud credentials."""
+    published = MemoryCloud({"weights.bin": b"weights"})
+    reference = resolve_snapshot_file_ref(published.snapshot, published.members[0])
+    store = LocalArtifactStore(tmp_path)
+    resident = store.resolve(reference, cloud=cast(ViperCloud, published))
+    monkeypatch.setattr(RunFetcher, "_cloud_service", _no_cloud_client)
+    fresh = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), "")
+
+    assert fresh.read(reference) == b"weights"
+    assert fresh.path(reference) == resident
+    assert published.downloads == 1
+
+
+def test_new_snapshot_uses_registered_equal_content_original_without_downloading(
+    tmp_path: Path,
+) -> None:
+    """First access to another snapshot reuses an original with the same bytes."""
+    store = LocalArtifactStore(tmp_path)
+    original = tmp_path / "checkpoint.pt"
+    original.write_bytes(b"weights")
+    old_member = snapshot_file("old/weights.bin", b"weights")
+    old_source = LocalStageResultSnapshotRef(
+        workspace=tmp_path, commit=content_revision((old_member,))
+    )
+    _register_original(store, old_source, old_member, original)
+    published = MemoryCloud({"new/weights.bin": b"weights"})
+    reference = resolve_snapshot_file_ref(published.snapshot, published.members[0])
+
+    resolved = store.resolve(reference, cloud=cast(ViperCloud, published))
+
+    assert resolved == original
+    assert resolved.read_bytes() == b"weights"
+    assert published.downloads == 0
+    assert store.registry.snapshot(published.snapshot) is not None
+    assert not (tmp_path / ".viper/store/objects").exists()
```

**File: `tests/test_storage_readers.py`**

[Complete proposed file](add/tests/test_storage_readers.py) · [Generated diff](diff/tests/test_storage_readers.py.diff)

```diff
--- a/tests/test_storage_readers.py
+++ b/tests/test_storage_readers.py
@@ -0,0 +1,105 @@
+"""Exercise native reader lifetimes and process-exit cleanup protection."""
+
+from __future__ import annotations
+
+import multiprocessing
+import os
+from multiprocessing.synchronize import Event
+from pathlib import Path
+
+import pytest
+
+from viper._storage_locks import PayloadLocks, WorkflowReaders
+from viper.references import FileIdentity
+
+
+def _identity() -> FileIdentity:
+    """Return one valid content identity used only to name a lock."""
+    return FileIdentity(sha256="1" * 64, bytes=8)
+
+
+def _reader_process(root: str, ready: Event, finish: Event) -> None:
+    """Exit abruptly while holding a reader so the OS must release it."""
+    with PayloadLocks(Path(root)).reader(_identity()):
+        ready.set()
+        if not finish.wait(10):
+            os._exit(2)
+        os._exit(0)
+
+
+def test_reader_defers_cleanup_until_workflow_completion(tmp_path: Path) -> None:
+    """A later admitted consumer keeps its payload resident between stage calls."""
+    locks = PayloadLocks(tmp_path)
+    with WorkflowReaders(locks) as readers:
+        readers.hold(_identity())
+        with locks.exclusive(_identity()) as acquired:
+            assert not acquired
+        readers.hold(_identity())
+        with locks.exclusive(_identity()) as acquired:
+            assert not acquired
+    with locks.exclusive(_identity()) as acquired:
+        assert acquired
+
+
+def test_overlapping_workflows_keep_independent_reader_holds(tmp_path: Path) -> None:
+    """One completed workflow cannot release another workflow's reader."""
+    locks = PayloadLocks(tmp_path)
+    first = WorkflowReaders(locks)
+    second = WorkflowReaders(locks)
+    try:
+        first.hold(_identity())
+        second.hold(_identity())
+        first.close()
+        with locks.exclusive(_identity()) as acquired:
+            assert not acquired
+    finally:
+        first.close()
+        second.close()
+    with locks.exclusive(_identity()) as acquired:
+        assert acquired
+
+
+def test_exception_releases_reader_without_authorizing_deletion(tmp_path: Path) -> None:
+    """Reader lifetime ends on failure; publication and retention gates still apply."""
+    locks = PayloadLocks(tmp_path)
+    with pytest.raises(RuntimeError, match="experiment failed"):
+        with WorkflowReaders(locks) as readers:
+            readers.hold(_identity())
+            raise RuntimeError("experiment failed")
+    with locks.exclusive(_identity()) as acquired:
+        assert acquired
+
+
+def test_process_exit_releases_reader_without_a_registry_counter(tmp_path: Path) -> None:
+    """An interrupted worker leaves no permanent reader subscription or count."""
+    context = multiprocessing.get_context("spawn")
+    ready = context.Event()
+    finish = context.Event()
+    process = context.Process(
+        target=_reader_process,
+        args=(str(tmp_path), ready, finish),
+    )
+    process.start()
+    locks = PayloadLocks(tmp_path)
+    try:
+        assert ready.wait(10)
+        with locks.exclusive(_identity()) as acquired:
+            assert not acquired
+        finish.set()
+        process.join(10)
+        assert process.exitcode == 0
+        with locks.exclusive(_identity()) as acquired:
+            assert acquired
+    finally:
+        finish.set()
+        if process.is_alive():
+            process.kill()
+        process.join(10)
+
+
+def test_closed_workflow_rejects_new_readers(tmp_path: Path) -> None:
+    """A completed scope cannot silently acquire untracked new readers."""
+    readers = WorkflowReaders(PayloadLocks(tmp_path))
+    readers.close()
+    with pytest.raises(RuntimeError, match="already closed"):
+        readers.hold(_identity())
```

**File: `tests/conftest.py`**

[Complete proposed file](replace/tests/conftest.py) · [Generated diff](diff/tests/conftest.py.diff)

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -5,6 +5,8 @@
 import pytest
 
 TIER_BY_MODULE = {
+    "test_shared_storage": "contract",
+    "test_storage_readers": "contract",
     "test_storage_registry": "contract",
     "test_storage_inventory": "contract",
     "test_offload": "contract",
@@ -71,6 +73,8 @@
 }
 
 DOMAIN_BY_MODULE = {
+    "test_shared_storage": "domain_storage",
+    "test_storage_readers": "domain_storage",
     "test_storage_registry": "domain_storage",
     "test_storage_inventory": "domain_storage",
     "test_offload": "domain_storage",
```

**File: `src/viper/references.py`**

[Complete proposed file](replace/src/viper/references.py) · [Generated diff](diff/src/viper/references.py.diff)

```diff
--- a/src/viper/references.py
+++ b/src/viper/references.py
@@ -86,11 +86,18 @@
 
 
 class LocalFileRef(ProtocolModel):
-    """Reference to the file at ``workspace / store / commit / path``."""
+    """Identify one file within a local snapshot.
+
+    workspace, store and commit keep the original snapshot address.
+    path selects a file; Viper finds its current local location.
+    """
 
     kind: Literal["local"] = "local"
     workspace: AbsolutePath = Field(
-        description="Absolute root of the workspace that owns the local store."
+        description=(
+            "Original workspace recorded in this immutable address; active-store "
+            "resolution may use another local root or verified cloud backing."
+        )
     )
     store: RepoRelPath = ".viper/store"
     commit: SHA256
@@ -98,23 +105,30 @@
 
 
 class LocalStageResultSnapshotRef(ProtocolModel):
-    """Reference to a saved file collection at ``workspace / store / commit``.
-
-    ``commit`` names the directory derived from file paths, sizes, and hashes.
-    A ``LocalFileRef`` adds ``path`` to select one file within that directory.
+    """Identify a fixed collection of files in a local Viper store.
+
+    commit is derived from the files' paths, sizes and hashes.
+    The registry keeps their complete file list and known local locations.
     """
 
     kind: Literal["local"] = Field(
-        default="local", description="Select the repository-local storage backend."
+        default="local", description="Select an original local snapshot address."
     )
     workspace: AbsolutePath = Field(
-        description="Absolute workspace directory beneath which store is located."
+        description=(
+            "Original workspace recorded in the snapshot address; payloads need "
+            "not remain on that host."
+        )
     )
     store: RepoRelPath = Field(
-        default=".viper/store", description="Store directory relative to workspace."
+        default=".viper/store",
+        description="Original store namespace relative to the recorded workspace."
     )
     commit: SHA256 = Field(
-        description="Revision directory derived from file paths, sizes, and hashes."
+        description=(
+            "Content-derived identity of the original complete snapshot; it need "
+            "not name a currently resident directory."
+        )
     )
 
 
@@ -233,7 +247,7 @@
 
 
 class ResolvedFileRef(FileIdentity):
-    """Identify one hashed file and its immutable storage location."""
+    """Identify exact file bytes and the reference used to retrieve them."""
 
     stored_at: StorageRef
 
@@ -246,7 +260,7 @@
     """
 
     path: RepoRelPath = Field(
-        description="Member path appended to the containing snapshot's root address."
+        description="File path within the snapshot."
     )
 
 
```

**File: `tests/test_storage.py`**

[Complete proposed file](replace/tests/test_storage.py) · [Generated diff](diff/tests/test_storage.py.diff)

```diff
--- a/tests/test_storage.py
+++ b/tests/test_storage.py
@@ -13,7 +13,11 @@
 from viper._cloud import GcsRepository, ViperCloudProvider, manifest_revision
 from viper._schema import SHA256, RepoRelPath
 from viper._source import RunFetcher
-from viper._verification.storage import read_resolved_file, read_snapshot_file
+from viper._verification.storage import (
+    read_resolved_file,
+    read_snapshot_file,
+    verify_resolved_file_bytes,
+)
 from viper.artifacts import ResolvedBundleArtifact, ResolvedSingleFileArtifact
 from viper.cloud import ViperCloud
 from viper.evidence import VerificationError, VerificationPolicy
@@ -84,26 +88,44 @@
     monkeypatch: pytest.MonkeyPatch,
     payload: bytes,
     fetches: list[HuggingFaceFileRef],
-) -> None:
-    """Route one Hugging Face reference through an inspectable fake service."""
+    reference: ResolvedFileRef,
+) -> None:
+    """Route one complete immutable HF inventory through a fake cloud facade."""
+    identity = SnapshotFileRef(
+        path=reference.stored_at.path,
+        sha256=reference.sha256,
+        bytes=reference.bytes,
+    )
 
     class _Remote:
+        """Implement the inventory and verified-path facade used by storage."""
+
+        provider = object()
+
         def fetch(self, location: HuggingFaceFileRef) -> bytes:
+            """Return the selected payload and record its transport request."""
             fetches.append(location)
             return payload
 
-        def fetch_to_path(self, reference: ResolvedFileRef, destination: Path) -> Path:
-            assert isinstance(reference.stored_at, HuggingFaceFileRef)
-            fetches.append(reference.stored_at)
+        def list_files(
+            self, snapshot: CloudStageResultSnapshotRef
+        ) -> tuple[SnapshotFileRef, ...]:
+            """Expose the complete identity expected by the selected reference."""
+            return (identity,)
+
+        def fetch_to_path(self, selected: ResolvedFileRef, destination: Path) -> Path:
+            """Verify bytes before satisfying the cloud path-transfer contract."""
+            assert isinstance(selected.stored_at, HuggingFaceFileRef)
+            raw = verify_resolved_file_bytes(selected, self.fetch(selected.stored_at))
             destination.parent.mkdir(parents=True, exist_ok=True)
-            destination.write_bytes(payload)
+            destination.write_bytes(raw)
             return destination
 
     remote = _Remote()
     monkeypatch.setattr(
         ViperCloud,
         "for_reference",
-        classmethod(lambda cls, root, reference: remote),
+        classmethod(lambda cls, root, selected: remote),
     )
 
 
@@ -330,7 +352,7 @@
     )
     fetches: list[HuggingFaceFileRef] = []
 
-    _install_remote_bytes(monkeypatch, payload, fetches)
+    _install_remote_bytes(monkeypatch, payload, fetches, reference)
     store = LocalArtifactStore(tmp_path)
 
     assert (
@@ -357,19 +379,53 @@
     """Share manifest caches within a backend while separating buckets and prefixes."""
     created: list[tuple[str, str]] = []
 
+    payload = b"verified file"
+
     class Remote:
-        def fetch(self, location):
-            return b"verified file"
-
-        def list_files(self, snapshot):
-            return (SnapshotFileRef(path="data.bin", sha256="a" * 64, bytes=13),)
-
-    def service(root, reference):
+        """Serve complete one-file revisions through a pooled cloud facade."""
+
+        provider = object()
+
+        def fetch(self, location: GcsFileRef) -> bytes:
+            """Return the same verified bytes from the fixture's revisions."""
+            return payload
+
+        def list_files(
+            self, snapshot: GcsStageResultSnapshotRef
+        ) -> tuple[SnapshotFileRef, ...]:
+            """Keep each immutable revision's declared member list truthful."""
+            path = "other.bin" if snapshot.revision == "b" * 64 else "data.bin"
+            return (
+                SnapshotFileRef(
+                    path=path,
+                    sha256=hashlib.sha256(payload).hexdigest(),
+                    bytes=len(payload),
+                ),
+            )
+
+        def fetch_to_path(self, selected: ResolvedFileRef, destination: Path) -> Path:
+            """Return a streamed path only after exact-file verification."""
+            assert isinstance(selected.stored_at, GcsFileRef)
+            raw = verify_resolved_file_bytes(selected, self.fetch(selected.stored_at))
+            destination.parent.mkdir(parents=True, exist_ok=True)
+            destination.write_bytes(raw)
+            return destination
+
+    def service(
+        cls: type[ViperCloud],
+        root: Path,
+        reference: GcsFileRef | GcsStageResultSnapshotRef,
+    ) -> Remote:
+        """Count real facade construction independently of the selected revision."""
         created.append((reference.bucket, reference.prefix))
         return Remote()
 
-    monkeypatch.setattr("viper._source.ViperCloud.for_reference", service)
-    monkeypatch.setattr("viper._source.ViperCloud.for_snapshot", service)
+    monkeypatch.setattr(
+        "viper._source.ViperCloud.for_reference", classmethod(service)
+    )
+    monkeypatch.setattr(
+        "viper._source.ViperCloud.for_snapshot", classmethod(service)
+    )
     fetcher = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), CONSUMER_REPOSITORY)
     location = GcsFileRef(
         bucket="first-bucket",
@@ -381,7 +437,10 @@
     )
     assert fetcher(location) == b"verified file"
     assert (
-        fetcher(location.model_copy(update={"path": "other.bin"})) == b"verified file"
+        fetcher(
+            location.model_copy(update={"path": "other.bin", "revision": "b" * 64})
+        )
+        == b"verified file"
     )
     snapshot = GcsStageResultSnapshotRef(
         bucket=location.bucket,
@@ -423,7 +482,7 @@
     fetcher = RunFetcher(tmp_path, LocalArtifactStore(tmp_path), CONSUMER_REPOSITORY)
     cache_path = (
         tmp_path
-        / ".viper/cache/verified-objects"
+        / ".viper/store/objects"
         / reference.sha256[:2]
         / reference.sha256
     )
@@ -489,7 +548,8 @@
 
     def count_bytes(raw: bytes = b"", *, usedforsecurity: bool = True):
         """Count checks of byte content."""
-        checks.append("bytes")
+        if raw == payload:
+            checks.append("bytes")
         return sha256(raw, usedforsecurity=usedforsecurity)
 
     def count_file(stream: BufferedReader, digest: str):
@@ -509,7 +569,7 @@
     assert fetcher.read(reference) == payload
     assert checks == ["path" if path_first else "bytes"]
     conflicting = reference.model_copy(update={"sha256": "0" * 64})
-    with pytest.raises(VerificationError, match="SHA-256 mismatch"):
+    with pytest.raises(VerificationError, match="snapshot inventory"):
         fetcher.path(conflicting)
 
 
@@ -525,7 +585,7 @@
 
     def count_bytes(raw: bytes = b"", *, usedforsecurity: bool = True):
         """Count hashes of publication payloads separately from the revision hash."""
-        if raw:
+        if raw in payloads.values():
             hashed.append(raw)
         return sha256(raw, usedforsecurity=usedforsecurity)
 
@@ -559,13 +619,13 @@
     )
     fetches: list[HuggingFaceFileRef] = []
 
-    _install_remote_bytes(monkeypatch, payload, fetches)
+    _install_remote_bytes(monkeypatch, payload, fetches, reference)
     store = LocalArtifactStore(tmp_path)
     fetcher = RunFetcher(tmp_path, store, CONSUMER_REPOSITORY)
     fetcher.read(reference)
     cache_path = (
         tmp_path
-        / ".viper/cache/verified-objects"
+        / ".viper/store/objects"
         / reference.sha256[:2]
         / reference.sha256
     )
@@ -599,12 +659,29 @@
     fetches: list[GcsFileRef] = []
 
     class Remote:
-        """Count the cloud requests made for the fixture's stage snapshot."""
+        """Count verified transfers from a complete simulated cloud snapshot."""
+
+        provider = object()
 
         def fetch(self, location: GcsFileRef) -> bytes:
             """Return the original metadata from the simulated cloud store."""
             fetches.append(location)
             return payload
+
+        def list_files(
+            self, selected: CloudStageResultSnapshotRef
+        ) -> tuple[SnapshotFileRef, ...]:
+            """Expose the complete sealed inventory needed by shared storage."""
+            assert selected == snapshot
+            return (reference,)
+
+        def fetch_to_path(self, selected: ResolvedFileRef, destination: Path) -> Path:
+            """Honor exact-file verification before returning a downloaded path."""
+            assert isinstance(selected.stored_at, GcsFileRef)
+            raw = verify_resolved_file_bytes(selected, self.fetch(selected.stored_at))
+            destination.parent.mkdir(parents=True, exist_ok=True)
+            destination.write_bytes(raw)
+            return destination
 
     remote = Remote()
     monkeypatch.setattr(
@@ -623,7 +700,7 @@
     )
     cache = (
         tmp_path
-        / ".viper/cache/verified-objects"
+        / ".viper/store/objects"
         / reference.sha256[:2]
         / reference.sha256
     )
@@ -667,7 +744,11 @@
     assert rebuilt.resolved_files(files)[0] == reference
     assert rebuilt.snapshot(files) == snapshot
     assert rebuilt.list_snapshot_files(snapshot) == ("model.bin",)
-    assert set(path.name for path in rebuilt.store_root.iterdir()) == {snapshot.commit}
+    assert {
+        path
+        for path in (rebuilt.store_root / "objects").rglob("*")
+        if path.is_file()
+    } == {rebuilt.path(reference.stored_at)}
     assert RunFetcher(tmp_path, rebuilt, "").read(reference) == b"model bytes"
 
     rebuilt.path(reference.stored_at).write_bytes(b"wrong bytes")
@@ -1029,7 +1110,13 @@
         owner=location.owner,
         workspace=location.workspace,
         revision=location.revision,
-        files=(),
+        files=(
+            SnapshotFileRef(
+                path=location.path,
+                sha256=hashlib.sha256(raw).hexdigest(),
+                bytes=len(raw),
+            ),
+        ),
     )
     fetcher = RunFetcher(
         tmp_path,
```

## Focused check and stop condition

After the actual dependency baseline and complete plan are frozen, the user runs Pyrefly first, then:

```bash
python -m pytest -q -p no:cacheprovider tests/test_shared_storage.py tests/test_storage_readers.py tests/test_storage_inventory.py tests/test_storage.py
```

Require discovered semantic documentation/schema coverage and finish with non-mutating Ruff format/lint checks. Stop on a failed check; no gate has run from this packet.

## Boundary

Cache/lock primitives were typed; remaining resolver files are proposed successors. Native original-Path admission, real outer-owner wiring and cold original-local-ref backing remain PB06. No automatic cleanup is enabled.

**File: `docs/how-to/inputs.md`**

[Complete proposed file](replace/docs/how-to/inputs.md) · [Generated diff](diff/docs/how-to/inputs.md.diff)

```diff
--- a/docs/how-to/inputs.md
+++ b/docs/how-to/inputs.md
@@ -201,12 +201,11 @@
 before attempt-owned materialization retain their recorded destination so their
 execution evidence remains verifiable.
 
-The producer and consumer may use different local VIPER workspaces on the same
-machine. A local file reference records the producer workspace's absolute path
-and store directory, so the consumer opens the producer's `.viper/store`
-rather than searching its own store. The producer workspace must remain at that
-recorded path. Use Hugging Face or Viper Cloud storage when the consumer runs on
-another machine or the producer workspace will move.
+A local file reference records the producer's workspace path and store directory.
+VIPER first checks whether the current workspace's registry knows that snapshot.
+Otherwise, it opens the producer's store at the recorded path. The reference
+alone cannot discover an unregistered copy on another machine. Use cloud
+storage when the consumer cannot reach either registered local copy.
 
 The selected data role must agree with the stored artifact. Training accepts
 `training` and `validation` inputs. Evaluation test data uses `eval` or
```

**File: `docs/how-to/troubleshooting.md`**

[Complete proposed file](replace/docs/how-to/troubleshooting.md) · [Generated diff](diff/docs/how-to/troubleshooting.md.diff)

```diff
--- a/docs/how-to/troubleshooting.md
+++ b/docs/how-to/troubleshooting.md
@@ -67,7 +67,11 @@
 
 ## Reclaim verification-cache space
 
-VIPER stores reusable remote bytes in `.viper/cache/verified-objects/` and
-external Git commits in `.viper/cache/git-checkouts/`. These directories contain
-retrieval caches, not run evidence. They may be removed while no VIPER process is
-using the workspace. The next verification retrieves the required objects again.
+VIPER stores reusable file bytes under `.viper/store/objects/`. This shared
+store can also contain the only copy of a locally published file. Keep
+`.viper/store` intact: it contains published files, their inventories and the
+registry database.
+
+External Git checkouts live under `.viper/cache/git-checkouts/`. You can remove
+those checkouts while no VIPER process is using the workspace. A later execution
+retrieves the required commits again.
```

**File: `docs/explanation/guarantees.md`**

[Complete proposed file](replace/docs/explanation/guarantees.md) · [Generated diff](diff/docs/explanation/guarantees.md.diff)

```diff
--- a/docs/explanation/guarantees.md
+++ b/docs/explanation/guarantees.md
@@ -30,10 +30,10 @@
 configured with file dependencies and a comparator are also recomputed from
 the saved files and checked against their recorded values.
 
-For a resolved remote file, VIPER may retain the verified bytes beneath
-`.viper/cache/verified-objects/`. A later execution rechecks the cached byte
-count and SHA-256 before use. A failed check causes retrieval from the recorded
-backend; cached bytes never replace the identity stored in the run record.
+VIPER keeps reusable files under `.viper/store/objects/`, named by their SHA-256
+hashes. A later execution checks each file's size and hash before using it.
+Cloud-backed files can be downloaded again if their cached copies fail
+verification. The stored references continue to identify the expected bytes.
 External Git commits use locked checkouts beneath `.viper/cache/git-checkouts/`.
 VIPER checks the checkout's repository and commit before reading a file.
 
```
