# CFO-PB-02

**Status:** guided_foundations_partially_applied_gates_not_run; no implementation gate or completion asserted.

**Requirements:** CFO-REQ-02

**Dependencies:** CFO-PB-01

Context: Persist complete immutable membership and mutable physical bindings through one registry. Reconcile the already typed post-write registration, member-name and Generator corrections before later partial-residency work.

## Review the complete edits

Complete action payloads are authoritative. Diffs and hashes are generated from those bytes against the preceding packet, not instructions to overwrite the partially edited live worktree blindly.

**File: `src/viper/_storage_registry.py`**

[Complete proposed file](add/src/viper/_storage_registry.py) · [Generated diff](diff/src/viper/_storage_registry.py.diff)

```diff
--- a/src/viper/_storage_registry.py
+++ b/src/viper/_storage_registry.py
@@ -0,0 +1,374 @@
+"""Save snapshot file lists and track their known local copies."""
+
+from __future__ import annotations
+
+import os
+import sqlite3
+import stat
+from collections.abc import Generator
+from contextlib import contextmanager
+from pathlib import Path
+from typing import Literal
+
+from yaml import YAMLError
+
+from ._cloud import (
+    LocalSource,
+    SnapshotInventory,
+    SnapshotSources,
+    canonical_json_bytes,
+)
+from ._schema import SHA256, RepoRelPath
+from .references import GitSource, SnapshotFileRef, StageResultSnapshotRef
+from .repository import resolve_path
+from .serialization import document_digest, parse_yaml_bytes
+
+_SCHEMA = (
+    """CREATE TABLE payloads (
+        sha256 TEXT NOT NULL,
+        bytes INTEGER NOT NULL CHECK (bytes >= 0),
+        PRIMARY KEY (sha256, bytes)
+    )""",
+    """CREATE TABLE snapshots (
+        key TEXT PRIMARY KEY NOT NULL,
+        inventory BLOB NOT NULL
+    )""",
+    """CREATE TABLE snapshot_members (
+        snapshot_key TEXT NOT NULL REFERENCES snapshots(key),
+        path TEXT NOT NULL,
+        sha256 TEXT NOT NULL,
+        bytes INTEGER NOT NULL,
+        PRIMARY KEY (snapshot_key, path),
+        FOREIGN KEY (sha256, bytes) REFERENCES payloads(sha256, bytes)
+    )""",
+    """CREATE TABLE local_bindings (
+        path TEXT NOT NULL,
+        sha256 TEXT NOT NULL,
+        bytes INTEGER NOT NULL,
+        device INTEGER NOT NULL,
+        inode INTEGER NOT NULL,
+        mtime_ns INTEGER NOT NULL,
+        ctime_ns INTEGER NOT NULL,
+        custody TEXT NOT NULL CHECK (custody IN ('output', 'cache', 'external')),
+        retired INTEGER NOT NULL CHECK (retired IN (0, 1)),
+        PRIMARY KEY (path, sha256, bytes),
+        FOREIGN KEY (sha256, bytes) REFERENCES payloads(sha256, bytes)
+    )""",
+    "CREATE INDEX members_by_payload ON snapshot_members(sha256, bytes)",
+    "CREATE INDEX bindings_by_payload ON local_bindings(sha256, bytes)",
+    "CREATE UNIQUE INDEX active_binding_by_path "
+    "ON local_bindings(path) WHERE retired = 0",
+)
+
+
+class StorageRegistryError(RuntimeError):
+    """Report invalid stored metadata or conflicting local file records."""
+
+
+class StorageRegistry:
+    """Track snapshot contents and known local file paths in one database."""
+
+    def __init__(
+        self, repository_root: Path, store: RepoRelPath = ".viper/store"
+    ) -> None:
+        """Choose the database path without creating the database or files."""
+        self.repository_root = repository_root.resolve(strict=True)
+        self.store = store
+        self.store_root = resolve_path(self.repository_root, store, operation="write")
+        self.path = resolve_path(
+            self.repository_root,
+            f"{store}/registry.sqlite3",
+            operation="write",
+        )
+
+    @contextmanager
+    def _transaction(
+        self, *, write: bool = False
+    ) -> Generator[sqlite3.Connection, None, None]:
+        """Read or update metadata in a short SQLite transaction.
+
+        Keep file hashing and cloud transfers outside this block.
+        """
+        connection: sqlite3.Connection | None = None
+        try:
+            path = resolve_path(
+                self.repository_root,
+                f"{self.store}/registry.sqlite3",
+                operation="write" if write else "read",
+            )
+            if write:
+                path.parent.mkdir(parents=True, exist_ok=True)
+
+            mode = "rwc" if write else "ro"
+            connection = sqlite3.connect(
+                f"{path.as_uri()}?mode={mode}",
+                uri=True,
+                isolation_level=None,
+            )
+            connection.row_factory = sqlite3.Row
+            connection.execute("PRAGMA foreign_keys = ON")
+            connection.execute("PRAGMA synchronous = FULL")
+            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
+
+            version = connection.execute("PRAGMA user_version").fetchone()[0]
+            if version == 0 and write:
+                tables = connection.execute(
+                    "SELECT name FROM sqlite_master WHERE type = 'table'"
+                ).fetchall()
+                if tables:
+                    raise StorageRegistryError("unrecognized storage registry")
+                for statement in _SCHEMA:
+                    connection.execute(statement)
+                connection.execute("PRAGMA user_version = 1")
+            elif version != 1:
+                raise StorageRegistryError("unsupported storage registry version")
+
+            yield connection
+            connection.commit()
+        except (OSError, ValueError, TypeError, sqlite3.Error, YAMLError) as error:
+            raise StorageRegistryError("storage registry is invalid") from error
+        finally:
+            if connection is not None:
+                connection.close()
+
+    @staticmethod
+    def _location(row: sqlite3.Row) -> LocalSource:
+        """Read a local file record from a database row."""
+        return LocalSource(
+            path=row["path"],
+            observed_stat=(
+                row["device"],
+                row["inode"],
+                row["mtime_ns"],
+                row["ctime_ns"],
+            ),
+            custody=row["custody"],
+            retired=bool(row["retired"]),
+        )
+
+    @staticmethod
+    def _inventory(
+        connection: sqlite3.Connection,
+        source: StageResultSnapshotRef | GitSource,
+    ) -> SnapshotInventory | None:
+        """Load the saved file list and check that database member records agree."""
+        key = document_digest(source)
+        row = connection.execute(
+            "SELECT inventory FROM snapshots WHERE key = ?",
+            (key,),
+        ).fetchone()
+        if row is None:
+            return None
+
+        inventory = SnapshotInventory.model_validate(parse_yaml_bytes(row["inventory"]))
+        if inventory.source != source:
+            raise StorageRegistryError("registered snapshot address differs")
+
+        indexed = connection.execute(
+            "SELECT path, sha256, bytes FROM snapshot_members "
+            "WHERE snapshot_key = ? ORDER BY path",
+            (key,),
+        ).fetchall()
+        expected = tuple(
+            (file.path, file.sha256, file.bytes) for file in inventory.source_files
+        )
+        if tuple(tuple(item) for item in indexed) != expected:
+            raise StorageRegistryError("registered membership index differs")
+        return inventory
+
+    def snapshot(
+        self,
+        source: StageResultSnapshotRef | GitSource,
+    ) -> SnapshotSources | None:
+        """Return the full file list and known local paths, including missing files."""
+        try:
+            path = resolve_path(
+                self.repository_root,
+                f"{self.store}/registry.sqlite3",
+                operation="write",
+            )
+            if not path.exists():
+                return None
+        except (OSError, ValueError) as error:
+            raise StorageRegistryError("storage registry path is invalid") from error
+
+        with self._transaction() as connection:
+            inventory = self._inventory(connection, source)
+            if inventory is None:
+                return None
+
+            locations = {}
+            for member in inventory.source_files:
+                rows = connection.execute(
+                    "SELECT * FROM local_bindings WHERE sha256 = ? AND bytes = ? "
+                    "ORDER BY path",
+                    (member.sha256, member.bytes),
+                ).fetchall()
+                if rows:
+                    locations[member.path] = tuple(self._location(row) for row in rows)
+            return SnapshotSources(inventory=inventory, locations=locations)
+
+    def _prepare(
+        self,
+        member: SnapshotFileRef,
+        location: LocalSource,
+    ) -> LocalSource:
+        """Check that the verified file still matches its recorded file details."""
+        if location.retired:
+            return location
+
+        try:
+            path = resolve_path(self.repository_root, location.path, operation="read")
+            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
+            try:
+                if location.custody != "external":
+                    os.fsync(descriptor)
+                status = os.fstat(descriptor)
+            finally:
+                os.close(descriptor)
+        except (OSError, ValueError) as error:
+            raise StorageRegistryError("local source is unavailable") from error
+
+        observation = (
+            status.st_dev,
+            status.st_ino,
+            status.st_mtime_ns,
+            status.st_ctime_ns,
+        )
+        if (
+            not stat.S_ISREG(status.st_mode)
+            or status.st_size != member.bytes
+            or observation[:3] != location.observed_stat[:3]
+        ):
+            raise StorageRegistryError("source changed before registration")
+        return location.model_copy(update={"observed_stat": observation})
+
+    def _bind(
+        self,
+        connection: sqlite3.Connection,
+        member: SnapshotFileRef,
+        location: LocalSource,
+    ) -> None:
+        """Register a checked local copy and reject conflicting file records."""
+        row = connection.execute(
+            "SELECT * FROM local_bindings WHERE path = ? AND retired = 0",
+            (location.path,),
+        ).fetchone()
+
+        if row is not None:
+            same_payload = (
+                row["sha256"] == member.sha256 and row["bytes"] == member.bytes
+            )
+            if location.retired:
+                if same_payload:
+                    raise StorageRegistryError(
+                        "active binding needs explicit retirement"
+                    )
+            elif row["custody"] == location.custody == "external":
+                if not same_payload:
+                    connection.execute(
+                        "UPDATE local_bindings SET retired = 1 "
+                        "WHERE path = ? AND retired = 0",
+                        (location.path,),
+                    )
+            elif (
+                not same_payload
+                or row["custody"] != location.custody
+                or (
+                    (row["device"], row["inode"]) != location.observed_stat[:2]
+                    and location.custody != "cache"
+                )
+            ):
+                raise StorageRegistryError("local source already has another binding")
+
+        connection.execute(
+            "INSERT OR REPLACE INTO local_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
+            (
+                location.path,
+                member.sha256,
+                member.bytes,
+                *location.observed_stat,
+                location.custody,
+                int(location.retired),
+            ),
+        )
+
+    def register_snapshot(self, record: SnapshotSources) -> SHA256:
+        """Save the snapshot's file list and register its known local copies."""
+        prepared = tuple(
+            (member, self._prepare(member, location))
+            for member in record.inventory.source_files
+            for location in record.locations.get(member.path, ())
+        )
+        key = document_digest(record.inventory.source)
+
+        with self._transaction(write=True) as connection:
+            previous = self._inventory(connection, record.inventory.source)
+            if previous is not None and previous != record.inventory:
+                raise StorageRegistryError("original snapshot inventory changed")
+
+            if previous is None:
+                connection.execute(
+                    "INSERT INTO snapshots VALUES (?, ?)",
+                    (key, canonical_json_bytes(record.inventory)),
+                )
+                for member in record.inventory.source_files:
+                    connection.execute(
+                        "INSERT OR IGNORE INTO payloads VALUES (?, ?)",
+                        (member.sha256, member.bytes),
+                    )
+                    connection.execute(
+                        "INSERT INTO snapshot_members VALUES (?, ?, ?, ?)",
+                        (key, member.path, member.sha256, member.bytes),
+                    )
+
+            for member, location in prepared:
+                self._bind(connection, member, location)
+        return key
+
+    def record_materialization(
+        self,
+        source: StageResultSnapshotRef | GitSource,
+        member: SnapshotFileRef,
+        path: Path,
+        *,
+        custody: Literal["output", "cache", "external"] = "cache",
+    ) -> LocalSource:
+        """Register a local file that the caller has already verified."""
+        candidate = path if path.is_absolute() else self.repository_root / path
+        relative = candidate.relative_to(self.repository_root).as_posix()
+        actual = resolve_path(self.repository_root, relative, operation="read")
+        status = actual.stat()
+        location = self._prepare(
+            member,
+            LocalSource(
+                path=relative,
+                observed_stat=(
+                    status.st_dev,
+                    status.st_ino,
+                    status.st_mtime_ns,
+                    status.st_ctime_ns,
+                ),
+                custody=custody,
+            ),
+        )
+
+        with self._transaction(write=True) as connection:
+            inventory = self._inventory(connection, source)
+            if inventory is None or member not in inventory.source_files:
+                raise StorageRegistryError(
+                    "materialization is outside registered inventory"
+                )
+            self._bind(connection, member, location)
+        return location
+
+    def retire_materialization(self, expected: LocalSource) -> bool:
+        """Mark the file record unusable without deleting the file."""
+        with self._transaction(write=True) as connection:
+            changed = connection.execute(
+                "UPDATE local_bindings SET retired = 1 WHERE path = ? "
+                "AND device = ? AND inode = ? AND mtime_ns = ? AND ctime_ns = ? "
+                "AND custody = ? AND retired = 0",
+                (expected.path, *expected.observed_stat, expected.custody),
+            )
+            return changed.rowcount == 1
```

**File: `src/viper/_cloud.py`**

[Complete proposed file](replace/src/viper/_cloud.py) · [Generated diff](diff/src/viper/_cloud.py.diff)

```diff
```

**File: `src/viper/storage.py`**

[Complete proposed file](replace/src/viper/storage.py) · [Generated diff](diff/src/viper/storage.py.diff)

```diff
--- a/src/viper/storage.py
+++ b/src/viper/storage.py
@@ -19,14 +19,19 @@
 )
 
 from ._cloud import (
+    LocalSource,
     PublicationSource,
+    SnapshotInventory,
+    SnapshotSources,
     ViperCloudDestination,
     ViperCloudError,
     ViperCloudRepository,
     manifest_revision,
     resolve_publication_source,
+    source_file,
 )
 from ._schema import ProtocolModel, RepoRelPath
+from ._storage_registry import StorageRegistry
 from .cloud import ViperCloud
 from .gcs import GcsProgressSink, stderr_gcs_progress
 from .ids import RunId
@@ -175,30 +180,37 @@
         except PathError as error:
             raise LocalStoreError("local store escapes the workspace root") from error
 
+        self.registry = StorageRegistry(self.repository_root, self.store)
+
     def publish(self, files: Mapping[RepoRelPath, bytes]) -> str:
         """Save the files and return their snapshot ID."""
         commit, _ = self._publish(files)
         return commit
 
     def _publish(
-        self, files: Mapping[RepoRelPath, bytes]
+        self,
+        files: Mapping[RepoRelPath, bytes],
     ) -> tuple[str, tuple[SnapshotFileRef, ...]]:
         """Save the files and return their snapshot ID and file hashes."""
         if not files:
             raise LocalStoreError("an immutable revision requires at least one file")
+
         identities = tuple(
             snapshot_file(path, raw) for path, raw in sorted(files.items())
         )
         commit = content_revision(identities)
         revision_root = self.store_root / commit
+
         for relative_path, raw in sorted(files.items()):
             target = (revision_root / relative_path).resolve()
             if not target.is_relative_to(revision_root):
                 raise LocalStoreError("published file escapes its immutable revision")
+
             if target.exists():
                 if not target.is_file() or target.read_bytes() != raw:
                     raise LocalStoreError("immutable revision contains different bytes")
                 continue
+
             target.parent.mkdir(parents=True, exist_ok=True)
             file_descriptor, temporary_name = tempfile.mkstemp(
                 dir=target.parent,
@@ -211,11 +223,50 @@
                     os.fsync(temporary_file.fileno())
                 os.replace(temporary_name, target)
             finally:
-                temporary_path = Path(temporary_name)
-                if temporary_path.exists():
-                    temporary_path.unlink()
+                Path(temporary_name).unlink(missing_ok=True)
+
+        snapshot = LocalStageResultSnapshotRef(
+            workspace=self.repository_root,
+            store=self.store,
+            commit=commit,
+        )
+        self.registry.register_snapshot(
+            SnapshotSources(
+                inventory=SnapshotInventory(
+                    source=snapshot,
+                    source_files=identities,
+                ),
+                locations={
+                    member.path: (
+                        self._observe(
+                            revision_root / member.path,
+                            custody="cache",
+                        ),
+                    )
+                    for member in identities
+                },
+            )
+        )
         return commit, identities
 
+    def _observe(
+        self,
+        path: Path,
+        *,
+        custody: Literal["output", "cache", "external"],
+    ) -> LocalSource:
+        """Record the path and file-system details of a file already checked."""
+        status = path.stat()
+        return LocalSource(
+            path=path.relative_to(self.repository_root).as_posix(),
+            observed_stat=(
+                status.st_dev,
+                status.st_ino,
+                status.st_mtime_ns,
+                status.st_ctime_ns,
+            ),
+            custody=custody,
+        )
     def snapshot(
         self,
         files: Mapping[RepoRelPath, bytes],
@@ -265,25 +316,63 @@
             raise LocalStoreError("local immutable file is missing")
         return target
 
+    def _local_snapshot(
+        self,
+        source: LocalStageResultSnapshotRef,
+    ) -> SnapshotSources:
+        """Read the saved file list or register files from the older store layout."""
+        registered = self.registry.snapshot(source)
+        if registered is not None:
+            return registered
+
+        if source.workspace != self.repository_root or source.store != self.store:
+            raise LocalStoreError("local snapshot belongs to a different store")
+
+        directory = resolve_path(
+            self.repository_root,
+            f"{self.store}/{source.commit}",
+            operation="write",
+        )
+        if not directory.is_dir():
+            raise LocalStoreError("local snapshot revision is missing")
+
+        members = []
+        locations = {}
+        for path in sorted(directory.rglob("*")):
+            if path.is_symlink():
+                raise LocalStoreError("local snapshot contains a symlink")
+            if path.is_file():
+                member_path = path.relative_to(directory).as_posix()
+                member = source_file(self.repository_root, member_path, path)
+                members.append(member)
+                locations[member_path] = (self._observe(path, custody="cache"),)
+
+        try:
+            inventory = SnapshotInventory(
+                source=source,
+                source_files=tuple(sorted(members, key=lambda member: member.path)),
+            )
+        except ValueError as error:
+            raise LocalStoreError(
+                "local snapshot inventory differs from its revision"
+            ) from error
+
+        record = SnapshotSources(
+            inventory=inventory,
+            locations=locations,
+        )
+        self.registry.register_snapshot(record)
+        return record
+
     def list_snapshot_files(
         self,
         snapshot: LocalStageResultSnapshotRef,
     ) -> tuple[RepoRelPath, ...]:
         """Return the complete recorded file list, including files absent locally."""
-        if snapshot.workspace != self.repository_root or snapshot.store != self.store:
-            raise LocalStoreError("local snapshot belongs to a different store")
-
-        revision_root = (self.store_root / snapshot.commit).resolve()
-        if not revision_root.is_dir():
-            raise LocalStoreError("local snapshot revision is missing")
-
-        paths: list[RepoRelPath] = []
-        for path in sorted(revision_root.rglob("*")):
-            if path.is_symlink():
-                raise LocalStoreError("local snapshot contains a symlink")
-            if path.is_file():
-                paths.append(path.relative_to(revision_root).as_posix())
-        return tuple(paths)
+        return tuple(
+            member.path
+            for member in self._local_snapshot(snapshot).inventory.source_files
+        )
 
 
 def local_artifact_store(
@@ -331,11 +420,11 @@
     ) -> LocalStageResultSnapshotRef:
         """Save a stage record with checked files from an earlier snapshot."""
         payload: dict[RepoRelPath, bytes] = {resolved_stage_path: resolved_stage}
-        for target_path, source_file in files.items():
+        for target_path, member in files.items():
             if target_path == resolved_stage_path:
                 raise StorageConfigurationError("reused file replaces resolved stage")
             raw = source_bytes[target_path]
-            _verify_reuse_source(source_file, raw)
+            _verify_reuse_source(member, raw)
             payload[target_path] = raw
         return self.store.snapshot(payload)
 
```

**File: `tests/test_storage_registry.py`**

[Complete proposed file](add/tests/test_storage_registry.py) · [Generated diff](diff/tests/test_storage_registry.py.diff)

```diff
--- a/tests/test_storage_registry.py
+++ b/tests/test_storage_registry.py
@@ -0,0 +1,316 @@
+"""Observe inventory persistence and shared physical binding behavior."""
+
+import hashlib
+import sqlite3
+from pathlib import Path
+from typing import Literal
+
+import pytest
+
+from viper._cloud import (
+    LocalSource,
+    SnapshotInventory,
+    SnapshotSources,
+    manifest_revision,
+)
+from viper._storage_registry import StorageRegistry, StorageRegistryError
+from viper.references import (
+    GcsStageResultSnapshotRef,
+    LocalStageResultSnapshotRef,
+    SnapshotFileRef,
+)
+
+
+def _inventory(root: Path, files: dict[str, bytes]) -> SnapshotInventory:
+    """Build an original local inventory using the shared revision function."""
+    members = tuple(
+        SnapshotFileRef(
+            path=path, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
+        )
+        for path, raw in sorted(files.items())
+    )
+    return SnapshotInventory(
+        source=LocalStageResultSnapshotRef(
+            workspace=root, commit=manifest_revision(members)
+        ),
+        source_files=members,
+    )
+
+
+def _location(
+    root: Path,
+    path: Path,
+    *,
+    custody: Literal["output", "cache", "external"] = "output",
+) -> LocalSource:
+    """Capture a real source observation after its producer has finished."""
+    status = path.stat()
+    return LocalSource(
+        path=path.relative_to(root).as_posix(),
+        observed_stat=(
+            status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns
+        ),
+        custody=custody,
+    )
+
+
+def test_unregistered_lookup_does_not_initialize_storage(tmp_path: Path) -> None:
+    """Leave legacy lookup free of registry creation or payload writes."""
+    registry = StorageRegistry(tmp_path)
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
+
+    assert registry.snapshot(inventory.source) is None
+    assert not registry.path.exists()
+    assert not registry.store_root.exists()
+
+
+def test_inventory_survives_restart_and_payload_absence(tmp_path: Path) -> None:
+    """Keep full declared membership after one member disappears locally."""
+    weights = tmp_path / "model.pt"
+    report = tmp_path / "report.json"
+    weights.write_bytes(b"weights")
+    report.write_bytes(b"{}")
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights", "report.json": b"{}"})
+    record = SnapshotSources(
+        inventory=inventory,
+        locations={
+            "weights.pt": (_location(tmp_path, weights),),
+            "report.json": (_location(tmp_path, report),),
+        },
+    )
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(record)
+    registry.register_snapshot(record)
+    weights.unlink()
+
+    reopened = StorageRegistry(tmp_path).snapshot(inventory.source)
+
+    assert reopened is not None
+    assert reopened.inventory == inventory
+    assert tuple(file.path for file in reopened.inventory.source_files) == (
+        "report.json", "weights.pt"
+    )
+    assert reopened.locations == record.locations
+    assert report.read_bytes() == b"{}"
+
+
+def test_equal_content_shares_original_without_another_payload(tmp_path: Path) -> None:
+    """Let another snapshot use an already registered physical payload."""
+    original = tmp_path / "checkpoint.pt"
+    original.write_bytes(b"weights")
+    first = _inventory(tmp_path, {"weights.pt": b"weights"})
+    second = _inventory(tmp_path, {"reused.pt": b"weights"})
+    location = _location(tmp_path, original)
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(
+        SnapshotSources(inventory=first, locations={"weights.pt": (location,)})
+    )
+    registry.register_snapshot(SnapshotSources(inventory=second))
+
+    shared = registry.snapshot(second.source)
+
+    assert shared is not None
+    assert first.source != second.source
+    assert shared.inventory == second
+    assert shared.locations["reused.pt"] == (location,)
+    assert original.read_bytes() == b"weights"
+
+
+def test_registered_inventory_cannot_change(tmp_path: Path) -> None:
+    """Reject changed membership under one exact cloud snapshot address."""
+    local = _inventory(tmp_path, {"weights.pt": b"weights"})
+    source = GcsStageResultSnapshotRef(
+        bucket="test-bucket", owner="machina", workspace="jep", revision="a" * 64
+    )
+    original = SnapshotInventory(source=source, source_files=local.source_files)
+    changed = SnapshotInventory(
+        source=source,
+        source_files=(
+            SnapshotFileRef(path="extra.bin", sha256="b" * 64, bytes=1),
+            *local.source_files,
+        ),
+    )
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(SnapshotSources(inventory=original))
+
+    with pytest.raises(StorageRegistryError, match="inventory changed"):
+        registry.register_snapshot(SnapshotSources(inventory=changed))
+
+    saved = registry.snapshot(source)
+    assert saved is not None
+    assert saved.inventory == original
+
+
+def test_custody_conflict_rolls_back_new_snapshot(tmp_path: Path) -> None:
+    """Do not acquire ownership of an existing external physical path."""
+    original = tmp_path / "dataset.bin"
+    original.write_bytes(b"data")
+    first = _inventory(tmp_path, {"input.bin": b"data"})
+    second = _inventory(tmp_path, {"claimed.bin": b"data"})
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(
+        SnapshotSources(
+            inventory=first,
+            locations={
+                "input.bin": (_location(tmp_path, original, custody="external"),)
+            },
+        )
+    )
+
+    with pytest.raises(StorageRegistryError, match="another binding"):
+        registry.register_snapshot(
+            SnapshotSources(
+                inventory=second,
+                locations={"claimed.bin": (_location(tmp_path, original),)},
+            )
+        )
+
+    assert registry.snapshot(second.source) is None
+    saved = registry.snapshot(first.source)
+    assert saved is not None
+    assert saved.locations["input.bin"][0].custody == "external"
+    assert original.read_bytes() == b"data"
+
+
+def test_source_replacement_before_registration_is_rejected(tmp_path: Path) -> None:
+    """Reject a saved observation whose path now names a replacement file."""
+    original = tmp_path / "checkpoint.pt"
+    original.write_bytes(b"weights")
+    stale = _location(tmp_path, original)
+    replacement = tmp_path / "replacement.pt"
+    replacement.write_bytes(b"weights")
+    replacement.replace(original)
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
+    registry = StorageRegistry(tmp_path)
+
+    with pytest.raises(StorageRegistryError, match="source changed"):
+        registry.register_snapshot(
+            SnapshotSources(inventory=inventory, locations={"weights.pt": (stale,)})
+        )
+
+    assert registry.snapshot(inventory.source) is None
+
+
+def test_dataset_reseal_retires_only_its_old_binding(tmp_path: Path) -> None:
+    """Keep original inventory while a declared dataset path gains a new version."""
+    dataset = tmp_path / "dataset.bin"
+    dataset.write_bytes(b"old data")
+    first = _inventory(tmp_path, {"input.bin": b"old data"})
+    registry = StorageRegistry(tmp_path)
+    old = _location(tmp_path, dataset, custody="external")
+    registry.register_snapshot(
+        SnapshotSources(inventory=first, locations={"input.bin": (old,)})
+    )
+    dataset.write_bytes(b"new data")
+    second = _inventory(tmp_path, {"input.bin": b"new data"})
+    current = _location(tmp_path, dataset, custody="external")
+
+    registry.register_snapshot(
+        SnapshotSources(inventory=second, locations={"input.bin": (current,)})
+    )
+
+    before = registry.snapshot(first.source)
+    after = registry.snapshot(second.source)
+    assert before is not None and after is not None
+    assert before.inventory == first
+    assert before.locations["input.bin"][0].retired
+    assert after.locations["input.bin"] == (current,)
+    assert dataset.read_bytes() == b"new data"
+
+
+def test_invalidating_external_binding_does_not_delete_file(tmp_path: Path) -> None:
+    """Permit stale input-binding invalidation without granting deletion custody."""
+    dataset = tmp_path / "dataset.bin"
+    dataset.write_bytes(b"data")
+    inventory = _inventory(tmp_path, {"input.bin": b"data"})
+    location = _location(tmp_path, dataset, custody="external")
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(
+        SnapshotSources(inventory=inventory, locations={"input.bin": (location,)})
+    )
+
+    assert registry.retire_materialization(location)
+    saved = registry.snapshot(inventory.source)
+    assert saved is not None
+    assert saved.locations["input.bin"][0].retired
+    assert dataset.read_bytes() == b"data"
+
+
+@pytest.mark.parametrize("batch", (False, True))
+def test_verified_cache_repair_defeats_stale_retirement(
+    tmp_path: Path, batch: bool
+) -> None:
+    """Install a verified replacement without letting an older job retire it."""
+    cached = tmp_path / "cached.bin"
+    cached.write_bytes(b"weights")
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
+    old = _location(tmp_path, cached, custody="cache")
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(
+        SnapshotSources(inventory=inventory, locations={"weights.pt": (old,)})
+    )
+    replacement = tmp_path / "verified.bin"
+    replacement.write_bytes(b"weights")
+    replacement.replace(cached)
+
+    if batch:
+        current = _location(tmp_path, cached, custody="cache")
+        registry.register_snapshot(
+            SnapshotSources(
+                inventory=inventory, locations={"weights.pt": (current,)}
+            )
+        )
+    else:
+        current = registry.record_materialization(
+            inventory.source, inventory.source_files[0], cached
+        )
+
+    assert not registry.retire_materialization(old)
+    saved = registry.snapshot(inventory.source)
+    assert saved is not None
+    assert saved.locations["weights.pt"] == (current,)
+    assert not current.retired
+    assert cached.read_bytes() == b"weights"
+
+
+def test_retirement_preserves_inventory_and_does_not_unlink(tmp_path: Path) -> None:
+    """Record release without giving the registry independent deletion authority."""
+    output = tmp_path / "checkpoint.pt"
+    output.write_bytes(b"weights")
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
+    location = _location(tmp_path, output)
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(
+        SnapshotSources(inventory=inventory, locations={"weights.pt": (location,)})
+    )
+
+    assert registry.retire_materialization(location)
+    assert not registry.retire_materialization(location)
+    saved = registry.snapshot(inventory.source)
+    assert saved is not None
+    assert saved.inventory == inventory
+    assert saved.locations["weights.pt"][0].retired
+    assert output.read_bytes() == b"weights"
+
+
+def test_registered_index_corruption_does_not_become_unmanaged(tmp_path: Path) -> None:
+    """Fail closed when saved membership no longer matches its inventory."""
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
+    registry = StorageRegistry(tmp_path)
+    registry.register_snapshot(SnapshotSources(inventory=inventory))
+    with sqlite3.connect(registry.path) as connection:
+        connection.execute("DELETE FROM snapshot_members")
+
+    with pytest.raises(StorageRegistryError, match="membership index differs"):
+        registry.snapshot(inventory.source)
+
+
+def test_corrupt_registry_does_not_become_unmanaged(tmp_path: Path) -> None:
+    """Distinguish absent metadata from an existing unreadable registry."""
+    registry = StorageRegistry(tmp_path)
+    registry.path.parent.mkdir(parents=True)
+    registry.path.write_bytes(b"not a SQLite database")
+    inventory = _inventory(tmp_path, {"weights.pt": b"weights"})
+
+    with pytest.raises(StorageRegistryError, match="registry is invalid"):
+        registry.snapshot(inventory.source)
```

**File: `tests/test_storage_inventory.py`**

[Complete proposed file](add/tests/test_storage_inventory.py) · [Generated diff](diff/tests/test_storage_inventory.py.diff)

```diff
--- a/tests/test_storage_inventory.py
+++ b/tests/test_storage_inventory.py
@@ -0,0 +1,74 @@
+"""Observe immutable local inventory independently of resident payload files."""
+
+from pathlib import Path
+
+import pytest
+
+from viper.references import LocalStageResultSnapshotRef
+from viper.storage import LocalArtifactStore, LocalStoreError, content_revision
+
+
+def test_new_snapshot_listing_survives_missing_payload_and_restart(
+    tmp_path: Path,
+) -> None:
+    """Removing a resident member cannot shrink the declared snapshot inventory."""
+    store = LocalArtifactStore(tmp_path)
+    files = {"bundle/a.bin": b"first", "bundle/b.bin": b"second"}
+    source = store.snapshot(files)
+    reference = store.resolved_files(files)[0]
+    store.path(reference.stored_at).unlink()
+
+    assert LocalArtifactStore(tmp_path).list_snapshot_files(source) == tuple(files)
+
+
+def test_legacy_adoption_rejects_incomplete_original_membership(
+    tmp_path: Path,
+) -> None:
+    """A partial legacy directory cannot be admitted as a complete snapshot."""
+    files = {"bundle/a.bin": b"first", "bundle/b.bin": b"second"}
+    source = LocalStageResultSnapshotRef(
+        workspace=tmp_path, commit=content_revision(files)
+    )
+    present = tmp_path / ".viper/store" / source.commit / "bundle/a.bin"
+    present.parent.mkdir(parents=True)
+    present.write_bytes(files["bundle/a.bin"])
+    store = LocalArtifactStore(tmp_path)
+
+    with pytest.raises(LocalStoreError, match="inventory differs"):
+        store.list_snapshot_files(source)
+    assert store.registry.snapshot(source) is None
+
+
+def test_complete_legacy_inventory_is_persisted_before_eviction(tmp_path: Path) -> None:
+    """Adopt a valid old snapshot once and preserve its full listing afterward."""
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
+def test_legacy_adoption_uses_canonical_posix_member_order(tmp_path: Path) -> None:
+    """Directory traversal order cannot change an otherwise valid snapshot seal."""
+    files = {"checkpoint.json": b"{}", "checkpoint/weights.pt": b"weights"}
+    source = LocalStageResultSnapshotRef(
+        workspace=tmp_path, commit=content_revision(files)
+    )
+    directory = tmp_path / ".viper/store" / source.commit
+    for name, raw in files.items():
+        path = directory / name
+        path.parent.mkdir(parents=True, exist_ok=True)
+        path.write_bytes(raw)
+
+    assert LocalArtifactStore(tmp_path).list_snapshot_files(source) == tuple(
+        sorted(files)
+    )
```

**File: `tests/conftest.py`**

[Complete proposed file](replace/tests/conftest.py) · [Generated diff](diff/tests/conftest.py.diff)

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -5,6 +5,8 @@
 import pytest
 
 TIER_BY_MODULE = {
+    "test_storage_registry": "contract",
+    "test_storage_inventory": "contract",
     "test_offload": "contract",
     "test_autocast_weight_updates": "unit",
     "test_journals": "contract",
@@ -69,6 +71,8 @@
 }
 
 DOMAIN_BY_MODULE = {
+    "test_storage_registry": "domain_storage",
+    "test_storage_inventory": "domain_storage",
     "test_offload": "domain_storage",
     "test_autocast_weight_updates": "domain_execution",
     "test_journals": "domain_verification",
```

## Focused check and stop condition

After the actual dependency baseline and complete plan are frozen, the user runs Pyrefly first, then:

```bash
python -m pytest -q -p no:cacheprovider tests/test_storage_registry.py tests/test_storage_inventory.py
```

Require discovered semantic documentation/schema coverage and finish with non-mutating Ruff format/lint checks. Stop on a failed check; no gate has run from this packet.

## Boundary

Production foundations were typed; tests/gates remain deferred. Registry retirement does not publish or authorize deletion.

**File: `src/viper/_verification/storage.py`**

[Complete proposed file](replace/src/viper/_verification/storage.py) · [Generated diff](diff/src/viper/_verification/storage.py.diff)

```diff
--- a/src/viper/_verification/storage.py
+++ b/src/viper/_verification/storage.py
@@ -1,4 +1,4 @@
-"""Read stored files and check their byte counts and hashes."""
+"""Read stored files and check their sizes and hashes."""
 
 from __future__ import annotations
 
@@ -16,6 +16,7 @@
 import viper._subprocess as subprocess
 
 from .._schema import ArtifactName, DataRole, RepoRelPath
+from .._storage_registry import StorageRegistryError
 from ..artifact_loaders import (
     ArtifactLoaderError,
     ArtifactValidationResult,
@@ -251,10 +252,10 @@
 def list_local_snapshot_files(
     snapshot: LocalStageResultSnapshotRef,
 ) -> tuple[RepoRelPath, ...]:
-    """List the snapshot through its owning local store."""
+    """Read the complete snapshot file list through its local store."""
     try:
         return local_artifact_store(snapshot).list_snapshot_files(snapshot)
-    except LocalStoreError as error:
+    except (LocalStoreError, StorageRegistryError) as error:
         messages = {
             "local snapshot revision is missing": (
                 "artifact.bundle: local snapshot is missing"
```
