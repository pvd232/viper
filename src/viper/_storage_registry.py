"""Save snapshot file lists and track their known local copies."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter
from yaml import YAMLError

from ._cloud import (
    LocalSource,
    SnapshotInventory,
    SnapshotSources,
    canonical_json_bytes,
)
from ._schema import SHA256, ProtocolModel, RepoRelPath
from .artifacts import (
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from .references import (
    FileIdentity,
    GitSource,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    resolve_snapshot_file_ref,
)
from .repository import resolve_path
from .serialization import document_digest, parse_yaml_bytes

_SCHEMA = (
    """CREATE TABLE payloads (
        sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL CHECK (bytes >= 0),
        PRIMARY KEY (sha256, bytes)
    )""",
    """CREATE TABLE snapshots (
        key TEXT PRIMARY KEY NOT NULL,
        inventory BLOB NOT NULL
    )""",
    """CREATE TABLE snapshot_members (
        snapshot_key TEXT NOT NULL REFERENCES snapshots(key),
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        PRIMARY KEY (snapshot_key, path),
        FOREIGN KEY (sha256, bytes) REFERENCES payloads(sha256, bytes)
    )""",
    """CREATE TABLE local_bindings (
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        device INTEGER NOT NULL,
        inode INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        ctime_ns INTEGER NOT NULL,
        custody TEXT NOT NULL CHECK (custody IN ('output', 'cache', 'external')),
        retired INTEGER NOT NULL CHECK (retired IN (0, 1)),
        PRIMARY KEY (path, sha256, bytes),
        FOREIGN KEY (sha256, bytes) REFERENCES payloads(sha256, bytes)
    )""",
    "CREATE INDEX members_by_payload ON snapshot_members(sha256, bytes)",
    "CREATE INDEX bindings_by_payload ON local_bindings(sha256, bytes)",
    "CREATE UNIQUE INDEX active_binding_by_path "
    "ON local_bindings(path) WHERE retired = 0",
)

_RETENTION_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS artifact_versions (
        key TEXT PRIMARY KEY,
        snapshot_key TEXT NOT NULL,
        preference TEXT NOT NULL DEFAULT 'inherit'
            CHECK (preference IN ('inherit', 'keep', 'offload')),
        UNIQUE (key, snapshot_key),
        FOREIGN KEY (snapshot_key) REFERENCES snapshots(key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifact_members (
        artifact_key TEXT NOT NULL,
        snapshot_key TEXT NOT NULL,
        path TEXT NOT NULL,
        PRIMARY KEY (artifact_key, path),
        FOREIGN KEY (artifact_key, snapshot_key)
            REFERENCES artifact_versions(key, snapshot_key),
        FOREIGN KEY (snapshot_key, path)
            REFERENCES snapshot_members(snapshot_key, path)
    )
    """,
    "CREATE INDEX IF NOT EXISTS subscribers_by_member "
    "ON artifact_members(snapshot_key, path)",
)

RetentionPreference = Literal["inherit", "keep", "offload"]

_ArtifactSelection = StageArtifactRef | RepoRelPath
_RETENTION_ADAPTER = TypeAdapter(RetentionPreference)


class _ArtifactVersion(ProtocolModel):
    """Identify an artifact by its snapshot and selected output or input ."""

    source: StageResultSnapshotRef = Field(
        description="Snapshot containing the artifact"
    )
    selection: _ArtifactSelection = Field(
        description="Stage and artifact name, or the path of one input file."
    )


def _artifact_key(
    source: StageResultSnapshotRef,
    selection: _ArtifactSelection,
) -> SHA256:
    """Compute the key for an artifact within its snapshot."""
    return document_digest(_ArtifactVersion(source=source, selection=selection))


class StorageRegistryError(RuntimeError):
    """Report invalid stored metadata or conflicting local file records."""


class StorageRegistry:
    """Track snapshot contents and known local file paths in one database."""

    def __init__(
        self, repository_root: Path, store: RepoRelPath = ".viper/store"
    ) -> None:
        """Choose the database path without creating the database or files."""
        self.repository_root = repository_root.resolve(strict=True)
        self.store = store
        self.store_root = resolve_path(self.repository_root, store, operation="write")
        self.path = resolve_path(
            self.repository_root,
            f"{store}/registry.sqlite3",
            operation="write",
        )

    @contextmanager
    def _transaction(
        self, *, write: bool = False
    ) -> Generator[sqlite3.Connection, None, None]:
        """Read or update metadata in a short SQLite transaction.

        Keep file hashing and cloud transfers outside this block.
        """
        cnx: sqlite3.Connection | None = None
        try:
            path = resolve_path(
                self.repository_root,
                f"{self.store}/registry.sqlite3",
                operation="write" if write else "read",
            )
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)

            mode = "rwc" if write else "ro"
            cnx = sqlite3.connect(
                f"{path.as_uri()}?mode={mode}",
                uri=True,
                isolation_level=None,
            )
            cnx.row_factory = sqlite3.Row
            cnx.execute("PRAGMA foreign_keys = ON")
            cnx.execute("PRAGMA synchronous = FULL")
            cnx.execute("BEGIN IMMEDIATE" if write else "BEGIN")

            version = cnx.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and write:
                tables = cnx.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                if tables:
                    raise StorageRegistryError("unrecognized storage registry")
                for statement in _SCHEMA:
                    cnx.execute(statement)
                cnx.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise StorageRegistryError("unsupported storage registry version")

            if write:
                for stmt in _RETENTION_SCHEMA:
                    cnx.execute(stmt)
            yield cnx
            cnx.commit()
        except (OSError, ValueError, TypeError, sqlite3.Error, YAMLError) as error:
            raise StorageRegistryError("storage registry is invalid") from error
        finally:
            if cnx is not None:
                cnx.close()

    @staticmethod
    def _location(row: sqlite3.Row) -> LocalSource:
        """Read a local file record from a database row."""
        return LocalSource(
            path=row["path"],
            observed_stat=(
                row["device"],
                row["inode"],
                row["mtime_ns"],
                row["ctime_ns"],
            ),
            custody=row["custody"],
            retired=bool(row["retired"]),
        )

    @staticmethod
    def _inventory(
        cnx: sqlite3.Connection,
        source: StageResultSnapshotRef | GitSource,
    ) -> SnapshotInventory | None:
        """Load the saved file list and check that database member records agree."""
        key = document_digest(source)
        row = cnx.execute(
            "SELECT inventory FROM snapshots WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        inventory = SnapshotInventory.model_validate(parse_yaml_bytes(row["inventory"]))
        if inventory.source != source:
            raise StorageRegistryError("registered snapshot address differs")

        indexed = cnx.execute(
            "SELECT path, sha256, bytes FROM snapshot_members "
            "WHERE snapshot_key = ? ORDER BY path",
            (key,),
        ).fetchall()
        expected = tuple(
            (file.path, file.sha256, file.bytes) for file in inventory.source_files
        )
        if tuple(tuple(item) for item in indexed) != expected:
            raise StorageRegistryError("registered membership index differs")
        return inventory

    def snapshot(
        self,
        source: StageResultSnapshotRef | GitSource,
    ) -> SnapshotSources | None:
        """Return the full file list and known local paths, including missing files."""
        try:
            path = resolve_path(
                self.repository_root,
                f"{self.store}/registry.sqlite3",
                operation="write",
            )
            if not path.exists():
                return None
        except (OSError, ValueError) as error:
            raise StorageRegistryError("storage registry path is invalid") from error

        with self._transaction() as cnx:
            inventory = self._inventory(cnx, source)
            if inventory is None:
                return None

            locations = {}
            for member in inventory.source_files:
                rows = cnx.execute(
                    "SELECT * FROM local_bindings WHERE sha256 = ? AND bytes = ? "
                    "ORDER BY path",
                    (member.sha256, member.bytes),
                ).fetchall()
                if rows:
                    locations[member.path] = tuple(self._location(row) for row in rows)
            return SnapshotSources(inventory=inventory, locations=locations)

    def _prepare(
        self,
        member: SnapshotFileRef,
        location: LocalSource,
    ) -> LocalSource:
        """Check that the verified file still matches its recorded file details."""
        if location.retired:
            return location

        try:
            path = resolve_path(self.repository_root, location.path, operation="read")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if location.custody != "external":
                    os.fsync(descriptor)
                status = os.fstat(descriptor)
            finally:
                os.close(descriptor)
        except (OSError, ValueError) as error:
            raise StorageRegistryError("local source is unavailable") from error

        observation = (
            status.st_dev,
            status.st_ino,
            status.st_mtime_ns,
            status.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_size != member.bytes
            or observation[:3] != location.observed_stat[:3]
        ):
            raise StorageRegistryError("source changed before registration")
        return location.model_copy(update={"observed_stat": observation})

    def _bind(
        self,
        cnx: sqlite3.Connection,
        member: SnapshotFileRef,
        location: LocalSource,
    ) -> None:
        """Register a checked local copy and reject conflicting file records."""
        row = cnx.execute(
            "SELECT * FROM local_bindings WHERE path = ? AND retired = 0",
            (location.path,),
        ).fetchone()

        if row is not None:
            same_payload = (
                row["sha256"] == member.sha256 and row["bytes"] == member.bytes
            )
            if location.retired:
                if same_payload:
                    raise StorageRegistryError(
                        "active binding needs explicit retirement"
                    )
            elif row["custody"] == location.custody == "external":
                if not same_payload:
                    cnx.execute(
                        "UPDATE local_bindings SET retired = 1 "
                        "WHERE path = ? AND retired = 0",
                        (location.path,),
                    )
            elif (
                not same_payload
                or row["custody"] != location.custody
                or (
                    (row["device"], row["inode"]) != location.observed_stat[:2]
                    and location.custody != "cache"
                )
            ):
                raise StorageRegistryError("local source already has another binding")

        cnx.execute(
            "INSERT OR REPLACE INTO local_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                location.path,
                member.sha256,
                member.bytes,
                *location.observed_stat,
                location.custody,
                int(location.retired),
            ),
        )

    def register_snapshot(self, record: SnapshotSources) -> SHA256:
        """Save the snapshot's file list and register its known local copies."""
        prepared = tuple(
            (member, self._prepare(member, location))
            for member in record.inventory.source_files
            for location in record.locations.get(member.path, ())
        )
        key = document_digest(record.inventory.source)

        with self._transaction(write=True) as cnx:
            previous = self._inventory(cnx, record.inventory.source)
            if previous is not None and previous != record.inventory:
                raise StorageRegistryError("original snapshot inventory changed")

            if previous is None:
                cnx.execute(
                    "INSERT INTO snapshots VALUES (?, ?)",
                    (key, canonical_json_bytes(record.inventory)),
                )
                for member in record.inventory.source_files:
                    cnx.execute(
                        "INSERT OR IGNORE INTO payloads VALUES (?, ?)",
                        (member.sha256, member.bytes),
                    )
                    cnx.execute(
                        "INSERT INTO snapshot_members VALUES (?, ?, ?, ?)",
                        (key, member.path, member.sha256, member.bytes),
                    )

            for member, location in prepared:
                self._bind(cnx, member, location)
        return key

    def record_materialization(
        self,
        source: StageResultSnapshotRef | GitSource,
        member: SnapshotFileRef,
        path: Path,
        *,
        custody: Literal["output", "cache", "external"] = "cache",
    ) -> LocalSource:
        """Register a local file that the caller has already verified."""
        candidate = path if path.is_absolute() else self.repository_root / path
        relative = candidate.relative_to(self.repository_root).as_posix()
        actual = resolve_path(self.repository_root, relative, operation="read")
        status = actual.stat()
        location = self._prepare(
            member,
            LocalSource(
                path=relative,
                observed_stat=(
                    status.st_dev,
                    status.st_ino,
                    status.st_mtime_ns,
                    status.st_ctime_ns,
                ),
                custody=custody,
            ),
        )

        with self._transaction(write=True) as cnx:
            inventory = self._inventory(cnx, source)
            if inventory is None or member not in inventory.source_files:
                raise StorageRegistryError(
                    "materialization is outside registered inventory"
                )
            self._bind(cnx, member, location)
        return location

    def register_artifact(
        self,
        source: StageResultSnapshotRef,
        selection: _ArtifactSelection,
        artifact: ResolvedArtifact,
    ) -> SHA256:
        """Register an exact artifact and all of its files.

        The caller supplies a resolved producer artifact or captured input file.
        Every file must belong to the recorded snapshot. Registering it again
        preserves its retention preference.
        """
        files = (
            (artifact.file,)
            if isinstance(artifact, ResolvedSingleFileArtifact)
            else tuple(member.file for member in artifact.members)
        )
        if isinstance(selection, str) and tuple(file.path for file in files) != (
            selection,
        ):
            raise StorageRegistryError(
                "artifact must contain only the file at the selected path"
            )
        paths = tuple(sorted({file.path for file in files}))
        key = _artifact_key(source, selection)
        snapshot_key = document_digest(source)

        with self._transaction(write=True) as cnx:
            inventory = self._inventory(cnx, source)
            if inventory is None:
                raise StorageRegistryError("artifact snapshot is not registered")
            if not set(files).issubset(inventory.source_files):
                raise StorageRegistryError("artifact differs from its snapshot")

            previous = cnx.execute(
                "SELECT key FROM artifact_versions WHERE key = ?",
                (key,),
            ).fetchone()
            if previous is not None:
                previous_paths = tuple(
                    row["path"]
                    for row in cnx.execute(
                        "SELECT path FROM artifact_members "
                        "WHERE artifact_key = ? ORDER BY path",
                        (key,),
                    )
                )
                if previous_paths != paths:
                    raise StorageRegistryError("registered artifact changed")
                return key

            cnx.execute(
                "INSERT INTO artifact_versions (key, snapshot_key) VALUES (?, ?)",
                (key, snapshot_key),
            )
            cnx.executemany(
                "INSERT INTO artifact_members (artifact_key, snapshot_key, path) "
                "VALUES (?, ?, ?)",
                ((key, snapshot_key, path) for path in paths),
            )
        return key

    def retire_materialization(self, expected: LocalSource) -> bool:
        """Mark the file record unusable without deleting the file."""
        with self._transaction(write=True) as cnx:
            changed = cnx.execute(
                "UPDATE local_bindings SET retired = 1 WHERE path = ? "
                "AND device = ? AND inode = ? AND mtime_ns = ? AND ctime_ns = ? "
                "AND custody = ? AND retired = 0",
                (expected.path, *expected.observed_stat, expected.custody),
            )
            return changed.rowcount == 1

    def retention(
        self,
        source: StageResultSnapshotRef,
        selection: _ArtifactSelection,
    ) -> RetentionPreference:
        """Read this artifact's saved preference."""
        with self._transaction() as cnx:
            row = cnx.execute(
                "SELECT preference FROM artifact_versions WHERE key = ?",
                (_artifact_key(source, selection),),
            ).fetchone()
            if row is None:
                raise StorageRegistryError("artifact version is not registered")
            return _RETENTION_ADAPTER.validate_python(row["preference"])

    def set_retention(
        self,
        source: StageResultSnapshotRef,
        selection: _ArtifactSelection,
        preference: RetentionPreference,
    ) -> None:
        """Save this artifact's preference for future cleanup decisions."""
        preference = _RETENTION_ADAPTER.validate_python(preference)
        with self._transaction(write=True) as cnx:
            changed = cnx.execute(
                "UPDATE artifact_versions SET preference = ? WHERE key = ?",
                (preference, _artifact_key(source, selection)),
            )
            if changed.rowcount != 1:
                raise StorageRegistryError("artifact version is not registered")

    def artifact_files(
        self,
        source: StageResultSnapshotRef,
        selection: _ArtifactSelection,
    ) -> tuple[ResolvedFileRef, ...]:
        """Return references for every file in the registered artifact."""
        key = _artifact_key(source, selection)
        with self._transaction() as cnx:
            inventory = self._inventory(cnx, source)
            rows = cnx.execute(
                "SELECT path FROM artifact_members "
                "WHERE artifact_key = ? ORDER BY path",
                (key,),
            ).fetchall()
            if inventory is None or not rows:
                raise StorageRegistryError("artifact version is not registered")
            paths = {row["path"] for row in rows}
            return tuple(
                resolve_snapshot_file_ref(source, file)
                for file in inventory.source_files
                if file.path in paths
            )

    @staticmethod
    def offload_permitted(
        connection: sqlite3.Connection,
        identity: FileIdentity,
        *,
        default_offload: bool,
    ) -> bool:
        """Check whether every artifact sharing these bytes allows offloading.

        Call this in the database transaction that authorizes deletion.
        Check current preferences again when queued cleanup runs. Other
        deletion checks still apply, including cloud copies and readers.
        Files outside registered artifacts follow the current global default.
        """
        rows = connection.execute(
            "SELECT DISTINCT artifact_versions.key, artifact_versions.preference "
            "FROM artifact_versions "
            "JOIN artifact_members "
            "ON artifact_members.artifact_key = artifact_versions.key "
            "JOIN snapshot_members "
            "ON snapshot_members.snapshot_key = artifact_members.snapshot_key "
            "AND snapshot_members.path = artifact_members.path "
            "WHERE snapshot_members.sha256 = ? AND snapshot_members.bytes = ?",
            (identity.sha256, identity.bytes),
        ).fetchall()
        if not rows:
            return default_offload
        return all(
            row["preference"] == "offload"
            or (row["preference"] == "inherit" and default_offload)
            for row in rows
        )
