# CFO-PB-01

**Status:** guided_foundations_partially_applied_gates_not_run; no implementation gate or completion asserted.

**Requirements:** CFO-REQ-01

**Dependencies:** none

Context: The identity work already exists in your working tree but has no observing offload tests or accepted completion evidence. Retain it and prove that exact copies cannot change the original seal or membership.

## Review the complete edits

Complete action payloads are authoritative. Diffs and hashes are generated from those bytes against the preceding packet, not instructions to overwrite the partially edited live worktree blindly.

**File: `src/viper/_cloud.py`**

[Complete proposed file](replace/src/viper/_cloud.py) · [Generated diff](diff/src/viper/_cloud.py.diff)

```diff
--- a/src/viper/_cloud.py
+++ b/src/viper/_cloud.py
@@ -16,9 +16,12 @@
 from .references import (
     CloudFileRef,
     CloudStageResultSnapshotRef,
+    GitSource,
+    LocalStageResultSnapshotRef,
     SnapshotFileRef,
+    StageResultSnapshotRef,
 )
-from .repository import PathError, resolve_path
+from .repository import resolve_path
 
 PublicationSource = bytes | Path
 
@@ -71,12 +74,8 @@
 
     @model_validator(mode="after")
     def require_revision_identity(self) -> RevisionManifest:
-        """Require unique sorted paths and the content-derived revision."""
-        paths = tuple(file.path for file in self.files)
-        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
-            raise ValueError("cloud manifest files must have unique sorted paths")
-        if manifest_revision(self.files) != self.revision:
-            raise ValueError("cloud manifest content does not match its revision")
+        """Validate manifest membership through the shared inventory check."""
+        validate_snapshot_inventory(self.files, revision=self.revision)
         return self
 
 
@@ -84,12 +83,112 @@
     """Derive one revision identity from sorted paths and file identities."""
     digest = hashlib.sha256()
     for file in sorted(files, key=lambda item: item.path):
-        encoded_path = str(file.path).encode("utf-8")
+        encoded_path = file.path.encode("utf-8")
         digest.update(len(encoded_path).to_bytes(8, "big"))
         digest.update(encoded_path)
         digest.update(file.bytes.to_bytes(8, "big"))
         digest.update(bytes.fromhex(file.sha256))
     return digest.hexdigest()
+
+
+def validate_snapshot_inventory(
+    files: tuple[SnapshotFileRef, ...],
+    *,
+    revision: SHA256 | None = None,
+) -> None:
+    """Require unique sorted file paths and check any supplied snapshot ID."""
+    paths = tuple(file.path for file in files)
+    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
+        raise ValueError("snapshot files must have unique sorted paths")
+
+    if revision is not None and manifest_revision(files) != revision:
+        raise ValueError("snapshot inventory does not match its revision")
+
+
+class SnapshotInventory(ProtocolModel):
+    """Record a snapshot and the complete list of its files, sizes and hashes."""
+
+    source: StageResultSnapshotRef | GitSource = Field(
+        description="Original snapshot reference preserved without rewriting."
+    )
+    source_files: tuple[SnapshotFileRef, ...] = Field(
+        min_length=1,
+        description="Complete original members in unique, sorted path order.",
+    )
+
+    @model_validator(mode="after")
+    def require_original_inventory(self) -> SnapshotInventory:
+        """Check the file list and, for a local snapshot, its snapshot ID."""
+        revision: SHA256 | None = None
+        if isinstance(self.source, LocalStageResultSnapshotRef):
+            revision = self.source.commit
+
+        validate_snapshot_inventory(self.source_files, revision=revision)
+        return self
+
+
+class LocalSource(ProtocolModel):
+    """Record a known local path and the file last observed there."""
+
+    path: RepoRelPath = Field(
+        description="Actual file path relative to the registered workspace root."
+    )
+    observed_stat: tuple[int, int, int, int] = Field(
+        description="Observed device, inode, modification time, and change time."
+    )
+    custody: Literal["output", "cache", "external"] = Field(
+        description="Whether this is an owned output, managed cache, or external file."
+    )
+    retired: bool = Field(
+        default=False,
+        description=(
+            "Whether Viper must stop using this saved location; "
+            "marking it retired does not authorize deleting the file."
+        ),
+    )
+
+
+class SnapshotSources(ProtocolModel):
+    """Pair the complete snapshot file list with known local copies."""
+
+    inventory: SnapshotInventory = Field(
+        description="Validated original snapshot and complete file identities."
+    )
+    locations: dict[RepoRelPath, tuple[LocalSource, ...]] = Field(
+        default_factory=dict,
+        description="Local locations grouped by original snapshot member path.",
+    )
+
+    @model_validator(mode="after")
+    def require_known_members(self) -> SnapshotSources:
+        """Require every recorded local copy to belong to the snapshot."""
+        members = {file.path for file in self.inventory.source_files}
+        if set(self.locations) - members:
+            raise ValueError("local locations contain an unknown snapshot member")
+        return self
+
+
+class SnapshotCopy(ProtocolModel):
+    """Record the original snapshot and the cloud copy required for publication."""
+
+    source: StageResultSnapshotRef | GitSource = Field(
+        description="Original snapshot address."
+    )
+    source_files: tuple[SnapshotFileRef, ...] = Field(
+        description="Original file paths, sizes, and hashes."
+    )
+    expected: RevisionManifest = Field(
+        description="Required destination files and their identities."
+    )
+    dependencies_sha256: SHA256 = Field(
+        description="Hash of the completed child mappings."
+    )
+    previous_head: str | None = Field(
+        description="Destination commit observed before copying."
+    )
+    published: CloudStageResultSnapshotRef | None = Field(
+        default=None, description="Verified destination snapshot, once available."
+    )
 
 
 def canonical_json_bytes(record: ProtocolModel) -> bytes:
@@ -113,7 +212,7 @@
     try:
         relative = candidate.relative_to(repository_root).as_posix()
         return resolve_path(repository_root, relative, operation="read")
-    except (OSError, ValueError, PathError) as error:
+    except (OSError, ValueError) as error:
         raise ViperCloudError("cloud publication source is invalid") from error
 
 
```

**File: `src/viper/storage.py`**

[Complete proposed file](replace/src/viper/storage.py) · [Generated diff](diff/src/viper/storage.py.diff)

```diff
--- a/src/viper/storage.py
+++ b/src/viper/storage.py
@@ -1,4 +1,4 @@
-"""Publish and retrieve immutable files through the local VIPER store."""
+"""Save and read files through the local Viper store or cloud storage."""
 
 from __future__ import annotations
 
@@ -23,6 +23,7 @@
     ViperCloudDestination,
     ViperCloudError,
     ViperCloudRepository,
+    manifest_revision,
     resolve_publication_source,
 )
 from ._schema import ProtocolModel, RepoRelPath
@@ -44,15 +45,15 @@
 
 
 class LocalStoreError(RuntimeError):
-    """Report an unsafe path or inconsistent immutable-store revision."""
+    """Report an unsafe path or missing or inconsistent stored files."""
 
 
 class StorageConfigurationError(ViperCloudError):
-    """Report invalid storage configuration or a changed run destination."""
+    """Report invalid storage settings or a changed run destination."""
 
 
 class LocalStorageDestination(ProtocolModel):
-    """Select repository-local immutable publication."""
+    """Save published files in the local Viper store."""
 
     kind: Literal["local"] = Field(
         default="local",
@@ -67,7 +68,7 @@
 
 
 class StorageSettings(ProtocolModel):
-    """Store the immutable-publication settings parsed from viper.toml."""
+    """Choose where to publish files and whether to keep local copies."""
 
     destination: StorageDestination = Field(
         default_factory=LocalStorageDestination,
@@ -77,20 +78,30 @@
         default=None,
         description="Cloud repository used when destination selects ViperCloud.",
     )
+    offload: bool = Field(
+        default=False,
+        strict=True,
+        description=(
+            "Automatically remove managed local copies after successful workflow "
+            "completion, verified cloud backing, and completion of their readers."
+        ),
+    )
 
     @model_validator(mode="after")
     def require_matching_repository(self) -> StorageSettings:
-        """Require a repository when publication selects ViperCloud."""
-        if (
-            isinstance(self.destination, ViperCloudDestination)
-            and self.repository is None
-        ):
+        """Require the cloud settings needed for the selected operation."""
+        uses_cloud = isinstance(self.destination, ViperCloudDestination)
+
+        if uses_cloud and self.repository is None:
             raise ValueError("viper_cloud repository is required for cloud destination")
+
+        if self.offload and not uses_cloud:
+            raise ValueError("storage.offload requires a viper_cloud destination")
+
         return self
 
-
 class RunPromotionPolicy(ProtocolModel):
-    """Select cloud hosts receiving the complete run graph."""
+    """Choose cloud destinations for a complete run."""
 
     hosts: tuple[ViperCloudRepository, ...] = Field(
         min_length=1,
@@ -99,7 +110,7 @@
 
 
 class TransferLimits(ProtocolModel):
-    """Limit disk use and connections for one graph copy."""
+    """Limit disk use and simultaneous cloud connections."""
 
     staging_bytes: int = Field(
         gt=0, strict=True, description="Maximum bytes in the copy's working directory."
@@ -117,7 +128,7 @@
 
 
 class SnapshotPublisher(Protocol):
-    """Publish one completed stage snapshot to a selected destination."""
+    """Save a completed stage record and its files."""
 
     def publish(
         self,
@@ -126,7 +137,7 @@
         resolved_stage: bytes,
         files: Mapping[RepoRelPath, Path],
     ) -> tuple[StageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
-        """Publish stage files and return their snapshot with computed hashes."""
+        """Save stage files and return their snapshot reference and hashes."""
         ...
 
     def publish_reuse(
@@ -138,34 +149,23 @@
         files: Mapping[RepoRelPath, SnapshotFileRef],
         source_bytes: Mapping[RepoRelPath, bytes],
     ) -> StageResultSnapshotRef:
-        """Publish a target stage document and remapped source snapshot files."""
+        """Save a new stage record with files reused from an earlier snapshot."""
         ...
 
 
-def content_revision(files: Mapping[RepoRelPath, bytes]) -> str:
-    """Derive one revision identity from ordered paths and file identities."""
-    return _content_revision(
-        tuple(snapshot_file(path, raw) for path, raw in sorted(files.items()))
-    )
-
-
-def _content_revision(files: tuple[SnapshotFileRef, ...]) -> str:
-    """Derive the existing revision encoding from previously computed hashes."""
-    digest = hashlib.sha256()
-    for file in files:
-        encoded_path = file.path.encode("utf-8")
-        digest.update(len(encoded_path).to_bytes(8, "big"))
-        digest.update(encoded_path)
-        digest.update(file.bytes.to_bytes(8, "big"))
-        digest.update(bytes.fromhex(file.sha256))
-    return digest.hexdigest()
-
+def content_revision(
+    files: Mapping[RepoRelPath, bytes] | tuple[SnapshotFileRef, ...],
+) -> str:
+    """Compute a snapshot ID from file paths, byte counts and SHA-256 hashes."""
+    if isinstance(files, Mapping):
+        files = tuple(snapshot_file(path, raw) for path, raw in files.items())
+    return manifest_revision(files)
 
 class LocalArtifactStore:
-    """Manage content-addressed output revisions beneath one repository root."""
+    """Save snapshot files and find their local paths."""
 
     def __init__(self, repository_root: Path, store: RepoRelPath = ".viper/store"):
-        """Bind the immutable store beneath one canonical workspace root."""
+        """Choose the workspace and local store."""
         self.repository_root = repository_root.resolve(strict=True)
         self.store = store
         try:
@@ -176,20 +176,20 @@
             raise LocalStoreError("local store escapes the workspace root") from error
 
     def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
-        """Write one immutable revision and return its content-derived identity."""
+        """Save the files and return their snapshot ID."""
         commit, _ = self._publish(files)
         return commit
 
     def _publish(
         self, files: Mapping[RepoRelPath, bytes]
     ) -> tuple[str, tuple[SnapshotFileRef, ...]]:
-        """Write one revision and retain the hashes computed from its payloads."""
+        """Save the files and return their snapshot ID and file hashes."""
         if not files:
             raise LocalStoreError("an immutable revision requires at least one file")
         identities = tuple(
             snapshot_file(path, raw) for path, raw in sorted(files.items())
         )
-        commit = _content_revision(identities)
+        commit = content_revision(identities)
         revision_root = self.store_root / commit
         for relative_path, raw in sorted(files.items()):
             target = (revision_root / relative_path).resolve()
@@ -220,7 +220,7 @@
         self,
         files: Mapping[RepoRelPath, bytes],
     ) -> LocalStageResultSnapshotRef:
-        """Publish one stage snapshot and return its immutable location."""
+        """Save the files and return their snapshot reference."""
         return LocalStageResultSnapshotRef(
             workspace=self.repository_root,
             store=self.store,
@@ -231,7 +231,7 @@
         self,
         files: Mapping[RepoRelPath, bytes],
     ) -> tuple[ResolvedFileRef, ...]:
-        """Publish related files and return exact references to each file."""
+        """Save the files and return a reference for each one."""
         commit, identities = self._publish(files)
         return tuple(
             ResolvedFileRef(
@@ -248,11 +248,11 @@
         )
 
     def fetch(self, location: StorageModel) -> bytes:
-        """Retrieve one local-store file after validating its revision path."""
+        """Read and check the file at the recorded address."""
         return self.path(location).read_bytes()
 
     def path(self, location: StorageModel) -> Path:
-        """Resolve one local-store file directly from its immutable reference."""
+        """Find the file at its recorded local store path."""
         if not isinstance(location, LocalFileRef):
             raise TypeError("LocalArtifactStore can resolve only LocalFileRef")
 
@@ -269,7 +269,7 @@
         self,
         snapshot: LocalStageResultSnapshotRef,
     ) -> tuple[RepoRelPath, ...]:
-        """List every regular file in one immutable local snapshot."""
+        """Return the complete recorded file list, including files absent locally."""
         if snapshot.workspace != self.repository_root or snapshot.store != self.store:
             raise LocalStoreError("local snapshot belongs to a different store")
 
@@ -289,15 +289,15 @@
 def local_artifact_store(
     location: LocalFileRef | LocalStageResultSnapshotRef,
 ) -> LocalArtifactStore:
-    """Open the local store named by one serialized local reference."""
+    """Open the store named in the original local reference."""
     return LocalArtifactStore(location.workspace, location.store)
 
 
 class LocalSnapshotPublisher:
-    """Publish stage snapshots through one repository-local artifact store."""
+    """Save stage records and their files in the local store."""
 
     def __init__(self, root: Path):
-        """Bind publication to the selected workspace root."""
+        """Choose the workspace and its local store."""
         self.root = root.resolve(strict=True)
         self.store = LocalArtifactStore(self.root)
 
@@ -308,7 +308,7 @@
         resolved_stage: bytes,
         files: Mapping[RepoRelPath, Path],
     ) -> tuple[LocalStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
-        """Publish local files and return the hashes of the stored bytes."""
+        """Save local stage files and return their references and hashes."""
         payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
         for path, source in files.items():
             payload[path] = read_publication_source(self.root, source)
@@ -329,7 +329,7 @@
         files: Mapping[RepoRelPath, SnapshotFileRef],
         source_bytes: Mapping[RepoRelPath, bytes],
     ) -> LocalStageResultSnapshotRef:
-        """Publish verified local snapshot files under their target paths."""
+        """Save a stage record with checked files from an earlier snapshot."""
         payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
         for target_path, source_file in files.items():
             if target_path == resolved_stage_path:
@@ -341,7 +341,7 @@
 
 
 def _parse_storage_destination(value: object) -> StorageDestination:
-    """Parse one public storage destination string into its protocol model."""
+    """Read the configured storage destination."""
     if value == "local":
         return LocalStorageDestination()
     if not isinstance(value, str) or not value.startswith("viper://"):
@@ -360,7 +360,7 @@
 
 
 def load_storage_settings(root: Path) -> StorageSettings:
-    """Load storage destination and cloud repository from ``viper.toml``."""
+    """Read storage settings from viper.toml."""
     try:
         marker = resolve_path(root, "viper.toml", operation="read")
         document = tomllib.loads(marker.read_text(encoding="utf-8"))
@@ -381,19 +381,19 @@
 
 
 def read_publication_source(root: Path, source: PublicationSource) -> bytes:
-    """Return bytes from one in-memory or root-confined publication source."""
+    """Read source bytes from memory or a file inside the workspace."""
     resolved = resolve_publication_source(root, source)
     return resolved if isinstance(resolved, bytes) else resolved.read_bytes()
 
 
 def _verify_reuse_source(source: SnapshotFileRef, raw: bytes) -> None:
-    """Reject source bytes that do not match their snapshot identity."""
+    """Reject bytes that differ from the recorded byte count or SHA-256."""
     if len(raw) != source.bytes or hashlib.sha256(raw).hexdigest() != source.sha256:
         raise StorageConfigurationError("reused snapshot file identity changed")
 
 
 def viper_cloud(root: Path) -> ViperCloud:
-    """Construct the cloud service selected by workspace configuration."""
+    """Create the cloud service configured for this workspace."""
     settings = load_storage_settings(root)
     if settings.repository is None:
         raise StorageConfigurationError("viper_cloud repository is required")
@@ -401,21 +401,21 @@
 
 
 def _gcs_progress_sink() -> GcsProgressSink | None:
-    """Return the configured GCS progress sink for workspace cloud operations."""
+    """Choose whether to report GCS transfer progress."""
     if os.environ.get("VIPER_GCS_PROGRESS") == "0":
         return None
     return stderr_gcs_progress
 
 
 class ViperCloudSnapshotPublisher:
-    """Publish stage snapshots through the workspace ViperCloud service."""
+    """Publish stage records and files to the configured cloud destination."""
 
     def __init__(
         self,
         root: Path,
         destination: ViperCloudDestination,
     ) -> None:
-        """Bind publication to one root and logical cloud destination."""
+        """Choose the workspace and cloud destination."""
         self.root = root.resolve(strict=True)
         self.destination = destination
         self.cloud = viper_cloud(self.root)
@@ -427,7 +427,7 @@
         resolved_stage: bytes,
         files: Mapping[RepoRelPath, Path],
     ) -> tuple[CloudStageResultSnapshotRef, tuple[SnapshotFileRef, ...]]:
-        """Publish stage files and return the provider's computed hashes."""
+        """Upload stage files and return the snapshot reference and file hashes."""
         return self.cloud.publish(
             self.destination,
             {resolved_stage_path: resolved_stage, **files},
@@ -442,7 +442,7 @@
         files: Mapping[RepoRelPath, SnapshotFileRef],
         source_bytes: Mapping[RepoRelPath, bytes],
     ) -> CloudStageResultSnapshotRef:
-        """Publish verified reused payloads under their target paths."""
+        """Publish checked files reused from an earlier cloud snapshot."""
         if not isinstance(
             source_snapshot,
             (GcsStageResultSnapshotRef, HuggingFaceStageResultSnapshotRef),
@@ -464,7 +464,7 @@
     root: Path,
     destination: StorageDestination,
 ) -> SnapshotPublisher:
-    """Create the stage publisher selected by workspace configuration."""
+    """Choose the local or cloud publisher from the storage settings."""
     if isinstance(destination, LocalStorageDestination):
         return LocalSnapshotPublisher(root)
     return ViperCloudSnapshotPublisher(root, destination)
@@ -475,7 +475,7 @@
     destination: StorageDestination,
     files: Mapping[RepoRelPath, PublicationSource],
 ) -> dict[RepoRelPath, ResolvedFileRef]:
-    """Publish standalone files and return references by canonical path."""
+    """Save files and return their exact references keyed by file path."""
     if isinstance(destination, LocalStorageDestination):
         payload = {
             path: read_publication_source(root, source)
@@ -495,7 +495,7 @@
     run_id: RunId,
     destination: StorageDestination,
 ) -> StorageDestination:
-    """Create or validate the immutable publication destination for one run."""
+    """Save the run's destination and reject a later change."""
     relative = f".viper/workspaces/{run_id}/storage-destination.json"
     try:
         target = resolve_path(root, relative, operation="write")
@@ -540,7 +540,7 @@
 
 
 def snapshot_file(path: RepoRelPath, raw: bytes) -> SnapshotFileRef:
-    """Describe one exact file included in a local stage snapshot."""
+    """Record a file's path, byte count and SHA-256."""
     return SnapshotFileRef(
         path=path,
         sha256=hashlib.sha256(raw).hexdigest(),
```

**File: `src/viper/_verification/storage.py`**

[Complete proposed file](replace/src/viper/_verification/storage.py) · [Generated diff](diff/src/viper/_verification/storage.py.diff)

```diff
--- a/src/viper/_verification/storage.py
+++ b/src/viper/_verification/storage.py
@@ -1,4 +1,4 @@
-"""Retrieve bytes and verify immutable file and artifact identities."""
+"""Read stored files and check their byte counts and hashes."""
 
 from __future__ import annotations
 
@@ -251,17 +251,23 @@
 def list_local_snapshot_files(
     snapshot: LocalStageResultSnapshotRef,
 ) -> tuple[RepoRelPath, ...]:
-    """List every regular file in one repository-local snapshot."""
-    revision_root = (Path.cwd() / snapshot.store / snapshot.commit).resolve()
-    if not revision_root.is_dir():
-        raise VerificationError("artifact.bundle: local snapshot is missing")
-    paths: list[RepoRelPath] = []
-    for path in sorted(revision_root.rglob("*")):
-        if path.is_symlink():
-            raise VerificationError("artifact.bundle: snapshot contains a symlink")
-        if path.is_file():
-            paths.append(path.relative_to(revision_root).as_posix())
-    return tuple(paths)
+    """List the snapshot through its owning local store."""
+    try:
+        return local_artifact_store(snapshot).list_snapshot_files(snapshot)
+    except LocalStoreError as error:
+        messages = {
+            "local snapshot revision is missing": (
+                "artifact.bundle: local snapshot is missing"
+            ),
+            "local snapshot contains a symlink": (
+                "artifact.bundle: snapshot contains a symlink"
+            ),
+        }
+        message = messages.get(
+            str(error),
+            "artifact.bundle: local snapshot listing failed",
+        )
+        raise VerificationError(message) from error
 
 
 def list_snapshot_files(
@@ -345,7 +351,7 @@
     fetcher: StorageFetcher | None = None,
 ) -> RunAttempt:
     """Retrieve one canonical attempt document and verify its path identity."""
-    path = str(reference.stored_at.path)
+    path = reference.stored_at.path
     prefix = f"{run_root(run)}/attempts/"
     suffix = "/resolved.yaml"
     if not path.startswith(prefix) or not path.endswith(suffix):
@@ -568,8 +574,8 @@
     elif isinstance(artifact, ResolvedBundleArtifact):
         roots: set[str] = set()
         for member in artifact.members:
-            full_path = str(member.file.path)
-            relative_path = str(member.relative_path)
+            full_path = member.file.path
+            relative_path = member.relative_path
             suffix = f"/{relative_path}"
             if not full_path.endswith(suffix):
                 raise VerificationError(
@@ -585,7 +591,7 @@
         published_paths = tuple(
             path
             for path in list_snapshot_files(stage.snapshot, fetcher=fetcher)
-            if str(path).startswith(f"{bundle_root}/")
+            if path.startswith(f"{bundle_root}/")
         )
         if published_paths != declared_paths:
             raise VerificationError(
@@ -671,7 +677,7 @@
         f"{artifact_name}:{target_path}",
         tuple(
             (
-                str(verified_file.reference.path),
+                verified_file.reference.path,
                 verified_file.reference.sha256,
                 verified_file.reference.bytes,
             )
```

**File: `src/viper/execution/_promotion_journal.py`**

[Complete proposed file](replace/src/viper/execution/_promotion_journal.py) · [Generated diff](diff/src/viper/execution/_promotion_journal.py.diff)

```diff
--- a/src/viper/execution/_promotion_journal.py
+++ b/src/viper/execution/_promotion_journal.py
@@ -15,6 +15,8 @@
     GcsRepository,
     PublicationSource,
     RevisionManifest,
+    SnapshotCopy,
+    SnapshotInventory,
     canonical_json_bytes,
     manifest_revision,
     source_file,
@@ -37,27 +39,22 @@
 from .errors import RunPromotionError
 
 
-class SnapshotCopy(ProtocolModel):
-    """Describe an original snapshot and its expected destination copy."""
-
-    source: StageResultSnapshotRef | GitSource = Field(
-        description="Original snapshot address."
-    )
-    source_files: tuple[SnapshotFileRef, ...] = Field(
-        description="Original file paths, sizes, and hashes."
-    )
-    expected: RevisionManifest = Field(
-        description="Required destination files and their identities."
-    )
-    dependencies_sha256: SHA256 = Field(
-        description="Hash of the completed child mappings."
-    )
-    previous_head: str | None = Field(
-        description="Destination commit observed before copying."
-    )
-    published: CloudStageResultSnapshotRef | None = Field(
-        default=None, description="Verified destination snapshot, once available."
-    )
+def validate_exact_snapshot_copy(copy: SnapshotCopy) -> SnapshotCopy:
+    """Require a destination to preserve a validated original inventory."""
+    try:
+        original = SnapshotInventory(
+            source=copy.source,
+            source_files=tuple(sorted(copy.source_files, key=lambda file: file.path)),
+        )
+    except ValueError as error:
+        raise RunPromotionError("original snapshot inventory differs") from error
+
+    if copy.expected.files != original.source_files:
+        raise RunPromotionError(
+            "destination inventory differs from the original snapshot"
+        )
+
+    return copy
 
 
 class _Progress(ProtocolModel):
```

**File: `tests/test_offload.py`**

[Complete proposed file](add/tests/test_offload.py) · [Generated diff](diff/tests/test_offload.py.diff)

```diff
--- a/tests/test_offload.py
+++ b/tests/test_offload.py
@@ -0,0 +1,103 @@
+"""Verify exact original snapshot bindings without changing their identities."""
+
+from __future__ import annotations
+
+import hashlib
+from pathlib import Path
+
+import pytest
+
+from viper._cloud import (
+    RevisionManifest,
+    SnapshotCopy,
+    SnapshotInventory,
+    manifest_revision,
+)
+from viper.execution._promotion_journal import validate_exact_snapshot_copy
+from viper.execution.errors import RunPromotionError
+from viper.references import LocalStageResultSnapshotRef, SnapshotFileRef
+from viper.storage import snapshot_file
+
+
+def _members(files: dict[str, bytes]) -> tuple[SnapshotFileRef, ...]:
+    """Use the existing file-identity owner to describe complete source bytes."""
+    return tuple(snapshot_file(path, raw) for path, raw in sorted(files.items()))
+
+
+def _copy(
+    root: Path,
+    original: tuple[SnapshotFileRef, ...],
+    destination: tuple[SnapshotFileRef, ...],
+    *,
+    commit: str | None = None,
+) -> SnapshotCopy:
+    """Bind one immutable local snapshot to an independently declared copy."""
+    return SnapshotCopy(
+        source=LocalStageResultSnapshotRef(
+            workspace=root,
+            commit=commit or manifest_revision(original),
+        ),
+        source_files=original,
+        expected=RevisionManifest(
+            owner="machina",
+            workspace="offload",
+            revision=manifest_revision(destination),
+            files=destination,
+        ),
+        dependencies_sha256=hashlib.sha256(b"[]").hexdigest(),
+        previous_head=None,
+    )
+
+
+def test_offload_binding_preserves_original_snapshot_identity(tmp_path: Path) -> None:
+    """Accept exact member copies without changing the original reference."""
+    members = _members({"model/config.json": b"{}", "model/weights.bin": b"weights"})
+    copy = _copy(tmp_path, members, members)
+    source_before = copy.source.model_dump(mode="json")
+
+    assert validate_exact_snapshot_copy(copy) is copy
+    assert copy.source.model_dump(mode="json") == source_before
+    assert copy.source_files == copy.expected.files
+    assert SnapshotInventory(source=copy.source, source_files=members).source == copy.source
+
+
+@pytest.mark.parametrize("change_source", [False, True])
+def test_offload_binding_rejects_changed_payload(
+    tmp_path: Path, change_source: bool
+) -> None:
+    """Reject destination changes and joint tampering under the original seal."""
+    original = _members({"model/weights.bin": b"weights"})
+    changed = _members({"model/weights.bin": b"changed"})
+    source = changed if change_source else original
+    copy = _copy(tmp_path, source, changed, commit=manifest_revision(original))
+
+    with pytest.raises(RunPromotionError, match="inventory"):
+        validate_exact_snapshot_copy(copy)
+
+
+@pytest.mark.parametrize("change", ["missing", "extra", "duplicate"])
+def test_offload_binding_rejects_changed_snapshot_membership(
+    tmp_path: Path, change: str
+) -> None:
+    """Reject member-set changes, including duplicate original member paths."""
+    original = _members({"model/config.json": b"{}", "model/weights.bin": b"weights"})
+    if change == "duplicate":
+        source = original + (original[-1],)
+        destination = original
+    elif change == "missing":
+        source = original
+        destination = original[:1]
+    else:
+        source = original
+        destination = _members(
+            {
+                "model/config.json": b"{}",
+                "model/extra.bin": b"extra",
+                "model/weights.bin": b"weights",
+            }
+        )
+    copy = _copy(tmp_path, source, destination, commit=manifest_revision(original))
+
+    with pytest.raises(RunPromotionError, match="inventory"):
+        validate_exact_snapshot_copy(copy)
+
```

**File: `tests/conftest.py`**

[Complete proposed file](replace/tests/conftest.py) · [Generated diff](diff/tests/conftest.py.diff)

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -5,6 +5,7 @@
 import pytest
 
 TIER_BY_MODULE = {
+    "test_offload": "contract",
     "test_autocast_weight_updates": "unit",
     "test_journals": "contract",
     "test_mcp_transport": "integration",
@@ -68,6 +69,7 @@
 }
 
 DOMAIN_BY_MODULE = {
+    "test_offload": "domain_storage",
     "test_autocast_weight_updates": "domain_execution",
     "test_journals": "domain_verification",
     "test_mcp_transport": "domain_application",
```

## Focused check and stop condition

After the actual dependency baseline and complete plan are frozen, the user runs Pyrefly first, then:

```bash
python -m pytest -q -p no:cacheprovider tests/test_offload.py
```

Require discovered semantic documentation/schema coverage and finish with non-mutating Ruff format/lint checks. Stop on a failed check; no gate has run from this packet.

## Boundary

Identity foundations and observing declarations only. User has typed these foundations; application gates remain deferred.

**File: `src/viper/execution/_promotion_compare.py`**

[Complete proposed file](replace/src/viper/execution/_promotion_compare.py) · [Generated diff](diff/src/viper/execution/_promotion_compare.py.diff)

```diff
--- a/src/viper/execution/_promotion_compare.py
+++ b/src/viper/execution/_promotion_compare.py
@@ -8,7 +8,7 @@
 
 from pydantic import BaseModel, TypeAdapter
 
-from .._cloud import ViperCloudRepository
+from .._cloud import SnapshotCopy, ViperCloudRepository
 from .._source import RunFetcher
 from ..cloud import ViperCloud
 from ..huggingface import HuggingFaceProvider
@@ -25,7 +25,6 @@
 from ..reuse import stage_spec_sha256
 from ..serialization import parse_yaml_bytes
 from ..stages import Spec
-from ._promotion_journal import SnapshotCopy
 from ._promotion_transfer import TransferSpace
 from .errors import RunPromotionError
 
```
