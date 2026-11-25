# CFO-PB-04

**Status:** guided_source_applied_tests_deferred; source entered and reviewed, application checks remain deferred. No implementation acceptance asserted.

**Requirements:** CFO-REQ-04, CFO-REQ-05

**Dependencies:** CFO-PB-03

Context: Make current global and exact-artifact preferences the single retention authority. Preserve complete-bundle keep and current-workspace lookup without capturing deletion permission when work is queued.

## Review the complete edits

Complete action payloads are authoritative. Diffs and hashes are generated from those bytes against the preceding packet, not instructions to overwrite the partially edited live worktree blindly.

**File: `src/viper/_storage_registry.py`**

[Complete proposed file](replace/src/viper/_storage_registry.py) · [Generated diff](diff/src/viper/_storage_registry.py.diff)

```diff
--- a/src/viper/_storage_registry.py
+++ b/src/viper/_storage_registry.py
@@ -1,4 +1,4 @@
-"""Save snapshot file lists and track their known local copies."""
+"""Save snapshot file lists and track known local copies and retention settings."""
 
 from __future__ import annotations
 
@@ -10,6 +10,7 @@
 from pathlib import Path
 from typing import Literal
 
+from pydantic import Field, TypeAdapter
 from yaml import YAMLError
 
 from ._cloud import (
@@ -18,8 +19,20 @@
     SnapshotSources,
     canonical_json_bytes,
 )
-from ._schema import SHA256, RepoRelPath
-from .references import GitSource, SnapshotFileRef, StageResultSnapshotRef
+from ._schema import SHA256, ProtocolModel, RepoRelPath
+from .artifacts import (
+    ResolvedArtifact,
+    ResolvedSingleFileArtifact,
+    StageArtifactRef,
+)
+from .references import (
+    FileIdentity,
+    GitSource,
+    ResolvedFileRef,
+    SnapshotFileRef,
+    StageResultSnapshotRef,
+    resolve_snapshot_file_ref,
+)
 from .repository import resolve_path
 from .serialization import document_digest, parse_yaml_bytes
 
@@ -61,12 +74,64 @@
 )
 
 
+_RETENTION_SCHEMA = (
+    """
+    CREATE TABLE IF NOT EXISTS artifact_versions (
+        key TEXT PRIMARY KEY,
+        snapshot_key TEXT NOT NULL,
+        preference TEXT NOT NULL DEFAULT 'inherit'
+            CHECK (preference IN ('inherit', 'keep', 'offload')),
+        UNIQUE (key, snapshot_key),
+        FOREIGN KEY (snapshot_key) REFERENCES snapshots(key)
+    )
+    """,
+    """
+    CREATE TABLE IF NOT EXISTS artifact_members (
+        artifact_key TEXT NOT NULL,
+        snapshot_key TEXT NOT NULL,
+        path TEXT NOT NULL,
+        PRIMARY KEY (artifact_key, path),
+        FOREIGN KEY (artifact_key, snapshot_key)
+            REFERENCES artifact_versions(key, snapshot_key),
+        FOREIGN KEY (snapshot_key, path)
+            REFERENCES snapshot_members(snapshot_key, path)
+    )
+    """,
+    "CREATE INDEX IF NOT EXISTS subscribers_by_member "
+    "ON artifact_members(snapshot_key, path)",
+)
+
+
+RetentionPreference = Literal["inherit", "keep", "offload"]
+_ArtifactSelection = StageArtifactRef | RepoRelPath
+_RETENTION_ADAPTER = TypeAdapter(RetentionPreference)
+
+
+class _ArtifactVersion(ProtocolModel):
+    """Identify an artifact by its snapshot and selected output or input."""
+
+    source: StageResultSnapshotRef = Field(
+        description="Snapshot containing the artifact."
+    )
+    selection: _ArtifactSelection = Field(
+        description="Stage and artifact name, or the path of one input file."
+    )
+
+
+def _artifact_key(
+    source: StageResultSnapshotRef,
+    selection: _ArtifactSelection,
+) -> SHA256:
+    """Compute the key for an artifact within its snapshot."""
+    return document_digest(_ArtifactVersion(source=source, selection=selection))
+
+
 class StorageRegistryError(RuntimeError):
     """Report invalid stored metadata or conflicting local file records."""
 
 
 class StorageRegistry:
-    """Track snapshot contents and known local file paths in one database."""
+    """Track snapshot files, local copies and preferences in one database."""
 
     def __init__(
         self, repository_root: Path, store: RepoRelPath = ".viper/store"
@@ -76,9 +141,7 @@
         self.store = store
         self.store_root = resolve_path(self.repository_root, store, operation="write")
         self.path = resolve_path(
-            self.repository_root,
-            f"{store}/registry.sqlite3",
-            operation="write",
+            self.repository_root, f"{store}/registry.sqlite3", operation="write"
         )
 
     @contextmanager
@@ -98,18 +161,14 @@
             )
             if write:
                 path.parent.mkdir(parents=True, exist_ok=True)
-
             mode = "rwc" if write else "ro"
             connection = sqlite3.connect(
-                f"{path.as_uri()}?mode={mode}",
-                uri=True,
-                isolation_level=None,
+                f"{path.as_uri()}?mode={mode}", uri=True, isolation_level=None
             )
             connection.row_factory = sqlite3.Row
             connection.execute("PRAGMA foreign_keys = ON")
             connection.execute("PRAGMA synchronous = FULL")
             connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
-
             version = connection.execute("PRAGMA user_version").fetchone()[0]
             if version == 0 and write:
                 tables = connection.execute(
@@ -122,7 +181,9 @@
                 connection.execute("PRAGMA user_version = 1")
             elif version != 1:
                 raise StorageRegistryError("unsupported storage registry version")
-
+            if write:
+                for statement in _RETENTION_SCHEMA:
+                    connection.execute(statement)
             yield connection
             connection.commit()
         except (OSError, ValueError, TypeError, sqlite3.Error, YAMLError) as error:
@@ -137,10 +198,7 @@
         return LocalSource(
             path=row["path"],
             observed_stat=(
-                row["device"],
-                row["inode"],
-                row["mtime_ns"],
-                row["ctime_ns"],
+                row["device"], row["inode"], row["mtime_ns"], row["ctime_ns"]
             ),
             custody=row["custody"],
             retired=bool(row["retired"]),
@@ -148,22 +206,20 @@
 
     @staticmethod
     def _inventory(
-        connection: sqlite3.Connection,
-        source: StageResultSnapshotRef | GitSource,
+        connection: sqlite3.Connection, source: StageResultSnapshotRef | GitSource
     ) -> SnapshotInventory | None:
         """Load the saved file list and check that database member records agree."""
         key = document_digest(source)
         row = connection.execute(
-            "SELECT inventory FROM snapshots WHERE key = ?",
-            (key,),
+            "SELECT inventory FROM snapshots WHERE key = ?", (key,)
         ).fetchone()
         if row is None:
             return None
-
-        inventory = SnapshotInventory.model_validate(parse_yaml_bytes(row["inventory"]))
+        inventory = SnapshotInventory.model_validate(
+            parse_yaml_bytes(row["inventory"])
+        )
         if inventory.source != source:
             raise StorageRegistryError("registered snapshot address differs")
-
         indexed = connection.execute(
             "SELECT path, sha256, bytes FROM snapshot_members "
             "WHERE snapshot_key = ? ORDER BY path",
@@ -177,8 +233,7 @@
         return inventory
 
     def snapshot(
-        self,
-        source: StageResultSnapshotRef | GitSource,
+        self, source: StageResultSnapshotRef | GitSource
     ) -> SnapshotSources | None:
         """Return the full file list and known local paths, including missing files."""
         try:
@@ -191,12 +246,10 @@
                 return None
         except (OSError, ValueError) as error:
             raise StorageRegistryError("storage registry path is invalid") from error
-
         with self._transaction() as connection:
             inventory = self._inventory(connection, source)
             if inventory is None:
                 return None
-
             locations = {}
             for member in inventory.source_files:
                 rows = connection.execute(
@@ -208,15 +261,10 @@
                     locations[member.path] = tuple(self._location(row) for row in rows)
             return SnapshotSources(inventory=inventory, locations=locations)
 
-    def _prepare(
-        self,
-        member: SnapshotFileRef,
-        location: LocalSource,
-    ) -> LocalSource:
+    def _prepare(self, member: SnapshotFileRef, location: LocalSource) -> LocalSource:
         """Check that the verified file still matches its recorded file details."""
         if location.retired:
             return location
-
         try:
             path = resolve_path(self.repository_root, location.path, operation="read")
             descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
@@ -228,12 +276,8 @@
                 os.close(descriptor)
         except (OSError, ValueError) as error:
             raise StorageRegistryError("local source is unavailable") from error
-
         observation = (
-            status.st_dev,
-            status.st_ino,
-            status.st_mtime_ns,
-            status.st_ctime_ns,
+            status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns
         )
         if (
             not stat.S_ISREG(status.st_mode)
@@ -254,7 +298,6 @@
             "SELECT * FROM local_bindings WHERE path = ? AND retired = 0",
             (location.path,),
         ).fetchone()
-
         if row is not None:
             same_payload = (
                 row["sha256"] == member.sha256 and row["bytes"] == member.bytes
@@ -280,16 +323,11 @@
                 )
             ):
                 raise StorageRegistryError("local source already has another binding")
-
         connection.execute(
             "INSERT OR REPLACE INTO local_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
             (
-                location.path,
-                member.sha256,
-                member.bytes,
-                *location.observed_stat,
-                location.custody,
-                int(location.retired),
+                location.path, member.sha256, member.bytes,
+                *location.observed_stat, location.custody, int(location.retired),
             ),
         )
 
@@ -301,12 +339,10 @@
             for location in record.locations.get(member.path, ())
         )
         key = document_digest(record.inventory.source)
-
         with self._transaction(write=True) as connection:
             previous = self._inventory(connection, record.inventory.source)
             if previous is not None and previous != record.inventory:
                 raise StorageRegistryError("original snapshot inventory changed")
-
             if previous is None:
                 connection.execute(
                     "INSERT INTO snapshots VALUES (?, ?)",
@@ -321,7 +357,6 @@
                         "INSERT INTO snapshot_members VALUES (?, ?, ?, ?)",
                         (key, member.path, member.sha256, member.bytes),
                     )
-
             for member, location in prepared:
                 self._bind(connection, member, location)
         return key
@@ -344,15 +379,12 @@
             LocalSource(
                 path=relative,
                 observed_stat=(
-                    status.st_dev,
-                    status.st_ino,
-                    status.st_mtime_ns,
-                    status.st_ctime_ns,
+                    status.st_dev, status.st_ino,
+                    status.st_mtime_ns, status.st_ctime_ns,
                 ),
                 custody=custody,
             ),
         )
-
         with self._transaction(write=True) as connection:
             inventory = self._inventory(connection, source)
             if inventory is None or member not in inventory.source_files:
@@ -372,3 +404,150 @@
                 (expected.path, *expected.observed_stat, expected.custody),
             )
             return changed.rowcount == 1
+
+    def register_artifact(
+        self,
+        source: StageResultSnapshotRef,
+        selection: _ArtifactSelection,
+        artifact: ResolvedArtifact,
+    ) -> SHA256:
+        """Register an exact artifact and all of its files.
+
+        The caller supplies a resolved producer artifact or captured input file.
+        Every file must belong to the recorded snapshot. Registering it again
+        preserves its retention preference.
+        """
+        files = (
+            (artifact.file,)
+            if isinstance(artifact, ResolvedSingleFileArtifact)
+            else tuple(member.file for member in artifact.members)
+        )
+        if isinstance(selection, str) and tuple(file.path for file in files) != (
+            selection,
+        ):
+            raise StorageRegistryError(
+                "artifact must contain only the file at the selected path"
+            )
+        paths = tuple(sorted({file.path for file in files}))
+        key = _artifact_key(source, selection)
+        snapshot_key = document_digest(source)
+        with self._transaction(write=True) as cnx:
+            inventory = self._inventory(cnx, source)
+            if inventory is None:
+                raise StorageRegistryError("artifact snapshot is not registered")
+            if not set(files).issubset(inventory.source_files):
+                raise StorageRegistryError("artifact differs from its snapshot")
+            previous = cnx.execute(
+                "SELECT key FROM artifact_versions WHERE key = ?",
+                (key,),
+            ).fetchone()
+            if previous is not None:
+                previous_paths = tuple(
+                    row["path"]
+                    for row in cnx.execute(
+                        "SELECT path FROM artifact_members "
+                        "WHERE artifact_key = ? ORDER BY path",
+                        (key,),
+                    )
+                )
+                if previous_paths != paths:
+                    raise StorageRegistryError("registered artifact changed")
+                return key
+            cnx.execute(
+                "INSERT INTO artifact_versions "
+                "(key, snapshot_key) VALUES (?, ?)",
+                (key, snapshot_key),
+            )
+            cnx.executemany(
+                "INSERT INTO artifact_members (artifact_key, snapshot_key, path) "
+                "VALUES (?, ?, ?)",
+                ((key, snapshot_key, path) for path in paths),
+            )
+        return key
+
+    def artifact_files(
+        self,
+        source: StageResultSnapshotRef,
+        selection: _ArtifactSelection,
+    ) -> tuple[ResolvedFileRef, ...]:
+        """Return references for every file in the registered artifact."""
+        key = _artifact_key(source, selection)
+        with self._transaction() as cnx:
+            inventory = self._inventory(cnx, source)
+            rows = cnx.execute(
+                "SELECT path FROM artifact_members "
+                "WHERE artifact_key = ? ORDER BY path",
+                (key,),
+            ).fetchall()
+            if inventory is None or not rows:
+                raise StorageRegistryError("artifact version is not registered")
+            paths = {row["path"] for row in rows}
+            return tuple(
+                resolve_snapshot_file_ref(source, file)
+                for file in inventory.source_files
+                if file.path in paths
+            )
+
+    def retention(
+        self,
+        source: StageResultSnapshotRef,
+        selection: _ArtifactSelection,
+    ) -> RetentionPreference:
+        """Read this artifact's saved preference."""
+        with self._transaction() as cnx:
+            row = cnx.execute(
+                "SELECT preference FROM artifact_versions WHERE key = ?",
+                (_artifact_key(source, selection),),
+            ).fetchone()
+            if row is None:
+                raise StorageRegistryError("artifact version is not registered")
+            return _RETENTION_ADAPTER.validate_python(row["preference"])
+
+    def set_retention(
+        self,
+        source: StageResultSnapshotRef,
+        selection: _ArtifactSelection,
+        preference: RetentionPreference,
+    ) -> None:
+        """Save this artifact's preference for future cleanup decisions."""
+        preference = _RETENTION_ADAPTER.validate_python(preference)
+        with self._transaction(write=True) as cnx:
+            changed = cnx.execute(
+                "UPDATE artifact_versions SET preference = ? WHERE key = ?",
+                (preference, _artifact_key(source, selection)),
+            )
+            if changed.rowcount != 1:
+                raise StorageRegistryError("artifact version is not registered")
+
+    @staticmethod
+    def offload_permitted(
+        connection: sqlite3.Connection,
+        identity: FileIdentity,
+        *,
+        default_offload: bool,
+    ) -> bool:
+        """Check whether every artifact sharing these bytes allows offloading.
+
+        Call this in the database transaction that authorizes deletion.
+        Check current preferences again when queued cleanup runs. Other
+        deletion checks still apply, including cloud copies and readers.
+        Files outside registered artifacts follow the current global default.
+        """
+        rows = connection.execute(
+            "SELECT DISTINCT artifact_versions.key, artifact_versions.preference "
+            "FROM artifact_versions "
+            "JOIN artifact_members "
+            "ON artifact_members.artifact_key = artifact_versions.key "
+            "JOIN snapshot_members "
+            "ON snapshot_members.snapshot_key = artifact_members.snapshot_key "
+            "AND snapshot_members.path = artifact_members.path "
+            "WHERE snapshot_members.sha256 = ? AND snapshot_members.bytes = ?",
+            (identity.sha256, identity.bytes),
+        ).fetchall()
+        if not rows:
+            return default_offload
+        return all(
+            row["preference"] == "offload"
+            or (row["preference"] == "inherit" and default_offload)
+            for row in rows
+        )
```

**File: `src/viper/retention.py`**

[Complete proposed file](replace/src/viper/retention.py) · [Generated diff](diff/src/viper/retention.py.diff)

```diff
--- a/src/viper/retention.py
+++ b/src/viper/retention.py
@@ -1,4 +1,4 @@
-"""Release local run artifacts only after verifying their cloud copies."""
+"""Set artifact retention preferences and remove verified cloud-backed local files."""
 
 from __future__ import annotations
 
@@ -10,6 +10,8 @@
 
 from ._cloud import ViperCloudError
 from ._schema import ProtocolModel, RepoRelPath
+from ._storage_registry import RetentionPreference
+from .artifacts import StageArtifactRef
 from .cloud import ViperCloud
 from .execution.results import RunResult
 from .ids import RunId
@@ -22,19 +24,21 @@
     ResolvedFileRef,
     ResolvedRunRef,
     SnapshotFileRef,
+    StageResultSnapshotRef,
 )
 from .repository import PathError, resolve_path
 from .runs import ResolvedRun, RunAttempt
 from .serialization import parse_yaml_bytes
+from .storage import LocalArtifactStore
 from .workspace import RunWorkspaceLock, WorkspaceError
 
 
 class RunFileEvictionError(RuntimeError):
-    """Report evidence that prevents safe removal of local run artifacts."""
+    """Report a check that prevents deleting local run files."""
 
 
 class RunFileEviction(ProtocolModel):
-    """Record local run bytes released after cloud verification."""
+    """Record which files were removed and how much local space was freed."""
 
     artifacts: tuple[SnapshotFileRef, ...] = Field(
         description="Cloud-verified artifact files removed from the local workspace."
@@ -53,7 +57,7 @@
     root: Path,
     reference: ResolvedFileRef,
 ) -> bytes:
-    """Read one small cloud record and verify its retained byte identity."""
+    """Read a cloud record and check its byte count and SHA-256."""
     location = reference.stored_at
     if not isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
         raise RunFileEvictionError("run record is not durably stored in Viper Cloud")
@@ -67,13 +71,13 @@
 
 
 def _artifact_path(path: RepoRelPath) -> bool:
-    """Recognize the canonical path of a stage-produced artifact file."""
+    """Recognize the standard path of a file produced by a stage."""
     parts = path.split("/")
     return len(parts) >= 9 and parts[0] == "experiments" and parts[5] == "artifacts"
 
 
 def _run_id_from_terminal_path(path: RepoRelPath) -> RunId:
-    """Read the run ID from one canonical terminal-record path."""
+    """Read the run ID from its final record path."""
     parts = path.split("/")
     if (
         len(parts) != 6
@@ -89,7 +93,7 @@
 
 
 def _directory_bytes(path: Path) -> int:
-    """Count regular-file bytes beneath one local directory."""
+    """Count file bytes under the directory."""
     return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
 
 
@@ -97,13 +101,12 @@
     repository_root: Path,
     run: RunResult | ResolvedRunRef,
 ) -> RunFileEviction:
-    """Remove one successful run's local artifacts after cloud-byte verification.
-
-    Keep canonical inputs, the local terminal record, attempt record, journal,
-    logs, measurements, and resolved stage documents. Remove the selected
-    attempt's transient materializations. Verify every existing artifact locally
-    and in its sealed cloud revision before deleting any file. Repeated calls are
-    safe: files already absent from the local workspace are ignored.
+    """Remove local output files after checking their cloud copies.
+
+    Keep inputs and run evidence, including stage records and measurements.
+    Also remove the selected attempt workspace. Check every existing output
+    locally and in its fixed cloud revision before deleting anything. Files
+    already absent are ignored.
     """
     root = repository_root.resolve(strict=True)
     reference = run.reference if isinstance(run, RunResult) else run
@@ -226,7 +229,29 @@
     )
 
 
+def set_artifact_retention(
+    repository_root: Path,
+    source: StageResultSnapshotRef,
+    selection: StageArtifactRef | RepoRelPath,
+    preference: RetentionPreference,
+    *,
+    store: RepoRelPath = ".viper/store",
+) -> None:
+    """Save an artifact preference and resolve all its files when keeping locally.
+
+    Keep is saved before resolving the files. Return after every file resolves
+    successfully. A failure leaves keep saved and raises the error. Inherit
+    and offload change the preference without retrieving or deleting files.
+    """
+    storage = LocalArtifactStore(repository_root, store)
+    storage.registry.set_retention(source, selection, preference)
+    if preference == "keep":
+        for reference in storage.registry.artifact_files(source, selection):
+            storage.resolve(reference)
+
+
 __all__ = [
+    "set_artifact_retention",
     "RunFileEvictionError",
     "RunFileEviction",
     "evict_cloud_backed_run_files",
```

**File: `tests/test_artifact_retention.py`**

[Complete proposed file](add/tests/test_artifact_retention.py) · [Generated diff](diff/tests/test_artifact_retention.py.diff)

```diff
--- a/tests/test_artifact_retention.py
+++ b/tests/test_artifact_retention.py
@@ -0,0 +1,393 @@
+"""Verify artifact overrides, shared subscribers and explicit keep completion."""
+
+import hashlib
+import sqlite3
+from pathlib import Path
+from typing import Literal
+
+import pytest
+from pydantic import ValidationError
+
+from viper._cloud import SnapshotInventory, SnapshotSources, manifest_revision
+from viper._storage_registry import StorageRegistry, StorageRegistryError
+from viper.artifacts import (
+    ResolvedBundleArtifact,
+    ResolvedBundleMember,
+    ResolvedSingleFileArtifact,
+    StageArtifactRef,
+)
+from viper.references import (
+    FileIdentity,
+    LocalFileRef,
+    LocalStageResultSnapshotRef,
+    ResolvedFileRef,
+    SnapshotFileRef,
+)
+from viper.retention import set_artifact_retention
+from viper.storage import (
+    LocalArtifactStore,
+    LocalStorageDestination,
+    StorageSettings,
+    ViperCloudDestination,
+)
+
+
+def _bundle(
+    registry: StorageRegistry,
+    *,
+    config: bytes = b"configuration-one",
+    source_workspace: Path | None = None,
+) -> tuple[LocalStageResultSnapshotRef, StageArtifactRef, ResolvedBundleArtifact]:
+    """Register a two-file artifact without creating any resident payload copy."""
+    payloads = {
+        "artifacts/model/config.json": config,
+        "artifacts/model/weights.bin": b"unchanged-model-weights",
+    }
+    files = tuple(
+        SnapshotFileRef(
+            path=path,
+            bytes=len(raw),
+            sha256=hashlib.sha256(raw).hexdigest(),
+        )
+        for path, raw in sorted(payloads.items())
+    )
+    source = LocalStageResultSnapshotRef(
+        workspace=source_workspace or registry.repository_root,
+        store=registry.store,
+        commit=manifest_revision(files),
+    )
+    registry.register_snapshot(
+        SnapshotSources(
+            inventory=SnapshotInventory(source=source, source_files=files)
+        )
+    )
+    selection = StageArtifactRef(stage_id="train", artifact_name="model")
+    artifact = ResolvedBundleArtifact(
+        relative_path="artifacts/model",
+        members=tuple(
+            ResolvedBundleMember(
+                relative_path=file.path.removeprefix("artifacts/model/"),
+                file=file,
+            )
+            for file in files
+        ),
+    )
+    registry.register_artifact(source, selection, artifact)
+    return source, selection, artifact
+
+
+def _permission(
+    registry: StorageRegistry,
+    identity: FileIdentity,
+    *,
+    default_offload: bool,
+) -> bool:
+    """Use the same transaction boundary required by final cleanup admission."""
+    with registry._transaction(write=True) as connection:
+        return registry.offload_permitted(
+            connection, identity, default_offload=default_offload
+        )
+
+
+def _input_version(
+    registry: StorageRegistry,
+    raw: bytes = b"training-records-version-one",
+) -> tuple[LocalStageResultSnapshotRef, ResolvedSingleFileArtifact]:
+    """Represent an already sealed standalone input without inventing a producer."""
+    member = SnapshotFileRef(
+        path="inputs/training.csv",
+        bytes=len(raw),
+        sha256=hashlib.sha256(raw).hexdigest(),
+    )
+    source = LocalStageResultSnapshotRef(
+        workspace=registry.repository_root,
+        store=registry.store,
+        commit=manifest_revision((member,)),
+    )
+    registry.register_snapshot(
+        SnapshotSources(
+            inventory=SnapshotInventory(source=source, source_files=(member,))
+        )
+    )
+    artifact = ResolvedSingleFileArtifact(relative_path=member.path, file=member)
+    registry.register_artifact(source, member.path, artifact)
+    return source, artifact
+
+
+def test_inherited_retention_uses_the_current_default(tmp_path: Path) -> None:
+    """Changing the default changes permission without rewriting subscriptions."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, artifact = _bundle(registry)
+    identity = artifact.members[0].file
+
+    assert not _permission(registry, identity, default_offload=False)
+    assert _permission(registry, identity, default_offload=True)
+    assert not _permission(registry, identity, default_offload=False)
+    assert registry.retention(source, selection) == "inherit"
+
+
+def test_explicit_overrides_work_in_both_directions(tmp_path: Path) -> None:
+    """Explicit offload permits release under keep, while explicit keep vetoes it."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, artifact = _bundle(registry)
+    identity = artifact.members[0].file
+
+    registry.set_retention(source, selection, "offload")
+    assert _permission(registry, identity, default_offload=False)
+    registry.set_retention(source, selection, "keep")
+    assert not _permission(registry, identity, default_offload=True)
+    registry.set_retention(source, selection, "inherit")
+    assert _permission(registry, identity, default_offload=True)
+
+
+def test_any_shared_artifact_keep_vetoes_offload(tmp_path: Path) -> None:
+    """Two named artifacts sharing payloads contribute independent preferences."""
+    registry = StorageRegistry(tmp_path)
+    source, first, artifact = _bundle(registry)
+    second = StageArtifactRef(stage_id="train", artifact_name="best_model")
+    first_key = registry.register_artifact(source, first, artifact)
+    second_key = registry.register_artifact(source, second, artifact)
+    assert first_key != second_key
+
+    registry.set_retention(source, first, "offload")
+    assert not _permission(
+        registry, artifact.members[0].file, default_offload=False
+    )
+    registry.set_retention(source, second, "offload")
+    assert _permission(registry, artifact.members[0].file, default_offload=False)
+    registry.set_retention(source, second, "keep")
+    assert not _permission(registry, artifact.members[0].file, default_offload=True)
+
+
+def test_distinct_versions_share_votes_without_merging_identity(tmp_path: Path) -> None:
+    """A changed bundle is a distinct version even when checkpoint bytes match."""
+    registry = StorageRegistry(tmp_path)
+    first, selection, old = _bundle(registry)
+    second, _, new = _bundle(registry, config=b"configuration-two")
+    assert first != second
+    assert old.members[1].file == new.members[1].file
+
+    registry.set_retention(first, selection, "keep")
+    registry.set_retention(second, selection, "offload")
+    assert not _permission(registry, new.members[1].file, default_offload=True)
+    assert _permission(registry, new.members[0].file, default_offload=False)
+
+
+def test_repeated_registration_and_restart_preserve_preference(tmp_path: Path) -> None:
+    """Later workflows reuse the same registration without adding or resetting votes."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, artifact = _bundle(registry)
+    key = registry.register_artifact(source, selection, artifact)
+    registry.set_retention(source, selection, "keep")
+
+    reopened = StorageRegistry(tmp_path)
+    for _ in range(3):
+        assert reopened.register_artifact(source, selection, artifact) == key
+    assert reopened.retention(source, selection) == "keep"
+    assert not _permission(reopened, artifact.members[0].file, default_offload=True)
+
+
+def test_artifact_registration_rejects_changed_bundle_membership(tmp_path: Path) -> None:
+    """A later registration cannot silently replace a bundle with one member."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, artifact = _bundle(registry)
+    subset = ResolvedSingleFileArtifact(
+        relative_path="artifacts/model/weights.bin", file=artifact.members[1].file
+    )
+
+    with pytest.raises(StorageRegistryError, match="registered artifact changed"):
+        registry.register_artifact(source, selection, subset)
+
+
+def test_artifact_registration_rejects_unsealed_member(tmp_path: Path) -> None:
+    """An artifact cannot subscribe to identities outside its sealed snapshot."""
+    registry = StorageRegistry(tmp_path)
+    source, _, artifact = _bundle(registry)
+    changed = artifact.members[0].file.model_copy(
+        update={"bytes": artifact.members[0].file.bytes + 1}
+    )
+    incorrect = ResolvedSingleFileArtifact(
+        relative_path="artifacts/model/config.json", file=changed
+    )
+
+    with pytest.raises(StorageRegistryError, match="artifact differs"):
+        registry.register_artifact(
+            source,
+            StageArtifactRef(stage_id="train", artifact_name="incorrect"),
+            incorrect,
+        )
+
+
+def test_standalone_input_can_keep_without_a_producer_selector(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """A registered dataset member receives keep through its existing source path."""
+    registry = StorageRegistry(tmp_path)
+    source, artifact = _input_version(registry)
+    calls: list[ResolvedFileRef] = []
+
+    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
+        """Confirm that dataset keep is durable before materialization starts."""
+        assert storage.registry.retention(source, artifact.file.path) == "keep"
+        calls.append(reference)
+        return tmp_path / reference.stored_at.path
+
+    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
+    set_artifact_retention(tmp_path, source, artifact.file.path, "keep")
+
+    assert len(calls) == 1
+    assert calls[0].sha256 == artifact.file.sha256
+    assert not _permission(registry, artifact.file, default_offload=True)
+    key = registry.register_artifact(source, artifact.file.path, artifact)
+    reopened = StorageRegistry(tmp_path)
+    assert reopened.register_artifact(source, artifact.file.path, artifact) == key
+    assert reopened.retention(source, artifact.file.path) == "keep"
+
+
+def test_changed_input_is_a_new_version_with_an_independent_override(
+    tmp_path: Path,
+) -> None:
+    """New dataset bytes at the same logical path do not inherit an old override."""
+    registry = StorageRegistry(tmp_path)
+    old, old_artifact = _input_version(registry)
+    registry.set_retention(old, old_artifact.file.path, "keep")
+    new, new_artifact = _input_version(registry, b"training-records-version-two")
+
+    assert old != new
+    assert old_artifact.file.path == new_artifact.file.path
+    assert registry.retention(new, new_artifact.file.path) == "inherit"
+    assert not _permission(registry, old_artifact.file, default_offload=True)
+    assert _permission(registry, new_artifact.file, default_offload=True)
+
+
+def test_member_selector_rejects_a_whole_bundle(tmp_path: Path) -> None:
+    """A member selector cannot silently stand in for a multi-file artifact."""
+    registry = StorageRegistry(tmp_path)
+    source, _, artifact = _bundle(registry)
+
+    with pytest.raises(StorageRegistryError, match="artifact must contain only"):
+        registry.register_artifact(source, artifact.members[0].file.path, artifact)
+
+
+def test_keep_resolves_every_member_after_persisting_preference(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Explicit keep records its veto before invoking normal full-bundle resolution."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, _ = _bundle(registry)
+    expected = registry.artifact_files(source, selection)
+    calls: list[ResolvedFileRef] = []
+
+    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
+        """Observe the retained preference while standing in for the normal resolver."""
+        assert storage.registry.retention(source, selection) == "keep"
+        calls.append(reference)
+        return tmp_path / reference.stored_at.path
+
+    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
+    set_artifact_retention(tmp_path, source, selection, "keep")
+
+    assert tuple(calls) == expected
+    assert len(calls) == 2
+
+
+def test_keep_uses_current_registry_with_missing_original_workspace(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """An old workspace address cannot redirect keep out of the active registry."""
+    registry = StorageRegistry(tmp_path)
+    old_workspace = tmp_path / "removed-producing-workspace"
+    source, selection, _ = _bundle(registry, source_workspace=old_workspace)
+    expected = registry.artifact_files(source, selection)
+    original = registry.snapshot(source)
+    calls: list[ResolvedFileRef] = []
+
+    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
+        """Observe keep admission before ordinary current-host materialization."""
+        assert storage.repository_root == tmp_path
+        assert storage.registry.retention(source, selection) == "keep"
+        assert isinstance(reference.stored_at, LocalFileRef)
+        assert reference.stored_at.workspace == old_workspace
+        calls.append(reference)
+        return tmp_path / "current-cache" / reference.stored_at.path
+
+    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
+    set_artifact_retention(tmp_path, source, selection, "keep")
+
+    assert tuple(calls) == expected
+    assert registry.retention(source, selection) == "keep"
+    assert registry.snapshot(source) == original
+    assert not old_workspace.exists()
+
+
+def test_failed_keep_preserves_the_preference(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """A failed second member does not erase a committed keep decision."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, _ = _bundle(registry)
+    calls: list[ResolvedFileRef] = []
+
+    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
+        """Fail a later member after confirming that keep already committed."""
+        assert storage.registry.retention(source, selection) == "keep"
+        calls.append(reference)
+        if len(calls) == 2:
+            raise OSError("cloud unavailable")
+        return tmp_path / reference.stored_at.path
+
+    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
+    with pytest.raises(OSError, match="cloud unavailable"):
+        set_artifact_retention(tmp_path, source, selection, "keep")
+
+    assert len(calls) == 2
+    assert StorageRegistry(tmp_path).retention(source, selection) == "keep"
+
+
+@pytest.mark.parametrize("preference", ["inherit", "offload"])
+def test_non_keep_changes_do_not_materialize_artifacts(
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+    preference: Literal["inherit", "offload"],
+) -> None:
+    """A policy update does not download a previously evicted artifact."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, _ = _bundle(registry)
+
+    def resolve(storage: LocalArtifactStore, reference: ResolvedFileRef) -> Path:
+        """Fail if a policy-only update accidentally requests payload bytes."""
+        raise AssertionError("policy-only update invoked the resolver")
+
+    monkeypatch.setattr(LocalArtifactStore, "resolve", resolve)
+    set_artifact_retention(tmp_path, source, selection, preference)
+    assert registry.retention(source, selection) == preference
+
+
+def test_retention_extends_an_existing_inventory_registry(tmp_path: Path) -> None:
+    """PB04 adds only its tables when upgrading a registry already used by PB02."""
+    registry = StorageRegistry(tmp_path)
+    source, selection, artifact = _bundle(registry)
+    original = registry.snapshot(source)
+    with sqlite3.connect(registry.path) as connection:
+        connection.execute("DROP TABLE artifact_members")
+        connection.execute("DROP TABLE artifact_versions")
+
+    reopened = StorageRegistry(tmp_path)
+    assert reopened.snapshot(source) == original
+    reopened.register_artifact(source, selection, artifact)
+    assert reopened.retention(source, selection) == "inherit"
+
+
+def test_retention_policy_is_independent_of_publication_destination() -> None:
+    """Offload may be enabled while new publications still select local storage."""
+    settings = StorageSettings(destination=LocalStorageDestination(), offload=True)
+    assert settings.offload
+    assert settings.repository is None
+
+
+def test_cloud_publication_still_requires_a_repository() -> None:
+    """Decoupling retention does not permit an incomplete cloud destination."""
+    with pytest.raises(ValidationError, match="repository is required"):
+        StorageSettings(
+            destination=ViperCloudDestination(owner="peter", workspace="models")
+        )
```

**File: `src/viper/storage.py`**

[Complete proposed file](replace/src/viper/storage.py) · [Generated diff](diff/src/viper/storage.py.diff)

```diff
--- a/src/viper/storage.py
+++ b/src/viper/storage.py
@@ -111,9 +111,6 @@
         if uses_cloud and self.repository is None:
             raise ValueError("viper_cloud repository is required for cloud destination")
 
-        if self.offload and not uses_cloud:
-            raise ValueError("storage.offload requires a viper_cloud destination")
-
         return self
 
 class RunPromotionPolicy(ProtocolModel):
```

**File: `tests/conftest.py`**

[Complete proposed file](replace/tests/conftest.py) · [Generated diff](diff/tests/conftest.py.diff)

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -5,6 +5,7 @@
 import pytest
 
 TIER_BY_MODULE = {
+    "test_artifact_retention": "contract",
     "test_shared_storage": "contract",
     "test_storage_readers": "contract",
     "test_storage_registry": "contract",
@@ -73,6 +74,7 @@
 }
 
 DOMAIN_BY_MODULE = {
+    "test_artifact_retention": "domain_storage",
     "test_shared_storage": "domain_storage",
     "test_storage_readers": "domain_storage",
     "test_storage_registry": "domain_storage",
```

## Focused check and stop condition

After the actual dependency baseline and complete plan are frozen, the user runs Pyrefly first, then:

```bash
python -m pytest -q -p no:cacheprovider tests/test_artifact_retention.py tests/test_storage_registry.py tests/test_shared_storage.py
```

Require discovered semantic documentation/schema coverage and finish with non-mutating Ruff format/lint checks. Stop on a failed check; no gate has run from this packet.

## Boundary

Preferences and complete-bundle keep do not implement queued deletion. Legacy eviction is connected to one live worker decision in PB07.
