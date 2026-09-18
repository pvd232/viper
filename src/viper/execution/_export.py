"""Export complete verified-run evidence into a portable directory bundle."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError

from .._schema import SHA256, RepoRelPath
from .._verification.storage import verify_resolved_file_bytes
from ..config import Config, ConfigTypeRef
from ..evidence import VerificationError, VerificationPolicy
from ..http import ExternalExecutableSpec, ResolvedExternalExecutable
from ..references import (
    GcsFileRef,
    GcsStageResultSnapshotRef,
    GitFileRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    SnapshotFileRef,
    StageResultSnapshot,
    StorageModel,
    StorageRef,
)
from ..runs import ResolvedRun, RunSpec
from ..serialization import parse_yaml_bytes
from ..storage import LocalArtifactStore
from ..verification import verify_run_result
from ._source import RunFetcher
from .errors import RunExportError
from .results import (
    RunBundleEntry,
    RunBundleManifest,
    RunBundleSnapshot,
    RunExportResult,
)

_STORAGE_ADAPTER = TypeAdapter(StorageRef)
_SNAPSHOT_ADAPTER = TypeAdapter(StageResultSnapshot)


def _canonical_json(value: object) -> bytes:
    """Serialize one manifest value with stable object-key ordering."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _source_key(source: Mapping[str, Any]) -> str:
    """Return one stable identity for an original payload location."""
    return hashlib.sha256(_canonical_json(dict(source))).hexdigest()


def _snapshot_location(
    snapshot: StageResultSnapshot,
    path: RepoRelPath,
) -> StorageModel:
    """Build the concrete storage location of one snapshot member."""
    if isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
        return HuggingFaceFileRef(
            repository=snapshot.repository,
            commit=snapshot.commit,
            path=path,
            repo_type=snapshot.repo_type,
        )
    if isinstance(snapshot, LocalStageResultSnapshotRef):
        return LocalFileRef(
            workspace=snapshot.workspace,
            store=snapshot.store,
            store_id=snapshot.store_id,
            commit=snapshot.commit,
            path=path,
        )
    assert isinstance(snapshot, GcsStageResultSnapshotRef)
    return GcsFileRef(
        bucket=snapshot.bucket,
        prefix=snapshot.prefix,
        owner=snapshot.owner,
        workspace=snapshot.workspace,
        revision=snapshot.revision,
        path=path,
    )


class _RecordingFetcher:
    """Record every immutable payload read through the normal execution fetcher."""

    def __init__(self, delegate: RunFetcher) -> None:
        self.delegate = delegate
        self.payloads: dict[str, tuple[dict[str, Any], bytes]] = {}
        self.snapshots: dict[str, tuple[str, ...]] = {}
        self.snapshot_paths: dict[str, tuple[RepoRelPath, ...]] = {}

    def __call__(self, location: StorageModel) -> bytes:
        """Retrieve and retain one payload by its complete storage locator."""
        source = location.model_dump(mode="json")
        key = _source_key(source)
        if key in self.payloads:
            return self.payloads[key][1]
        raw = self.delegate(location)
        self.payloads[key] = (source, raw)
        return raw

    def _retain_local(self, source: dict[str, Any], raw: bytes) -> bytes:
        """Retain one verified host payload under its stable logical identity."""
        self.payloads[_source_key(source)] = (source, raw)
        return raw

    def read_viper_source(self, reference: ConfigTypeRef) -> bytes:
        """Read and retain one installed VIPER config source file."""
        raw = (
            Path(inspect.getfile(Config)).resolve().parent / reference.path
        ).read_bytes()
        return self._retain_local(
            {
                "kind": "viper_source",
                "bytes": reference.bytes,
                "path": reference.path,
                "sha256": reference.sha256,
                "symbol": reference.symbol,
            },
            raw,
        )

    def read_plan_source(self, location: GitFileRef) -> bytes:
        """Read and retain one workspace source dependency from a frozen plan."""
        return self(location)

    def read_external_executable(
        self,
        executable: ResolvedExternalExecutable,
    ) -> bytes:
        """Read and retain one resolved external executable."""
        return self._retain_local(
            {
                "kind": "executable",
                "bytes": executable.spec.bytes,
                "command": executable.spec.command,
                "executable_id": executable.spec.executable_id,
                "sha256": executable.spec.sha256,
            },
            executable.path.read_bytes(),
        )

    def read_external_executable_spec(self, spec: ExternalExecutableSpec) -> bytes:
        """Locate, read, and retain one executable required by a frozen plan."""
        selected = shutil.which(spec.command)
        if selected is None:
            raise RunExportError(f"required executable is unavailable: {spec.command}")
        return self._retain_local(
            {
                "kind": "executable",
                "bytes": spec.bytes,
                "command": spec.command,
                "executable_id": spec.executable_id,
                "sha256": spec.sha256,
            },
            Path(selected).resolve().read_bytes(),
        )

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshot,
    ) -> tuple[RepoRelPath, ...]:
        """Record the complete ordered membership of one immutable snapshot."""
        source = snapshot.model_dump(mode="json")
        snapshot_key = _source_key(source)
        if snapshot_key in self.snapshot_paths:
            return self.snapshot_paths[snapshot_key]
        paths = self.delegate.list_snapshot_files(snapshot)
        members = []
        for path in paths:
            location = _snapshot_location(snapshot, path)
            self(location)
            members.append(_source_key(location.model_dump(mode="json")))
        self.snapshots[snapshot_key] = tuple(members)
        self.snapshot_paths[snapshot_key] = paths
        return paths

    def observe_snapshot(
        self,
        snapshot: StageResultSnapshot,
        reference: SnapshotFileRef,
    ) -> None:
        """Retain membership and require the referenced file to belong to it."""
        if reference.path not in self.list_snapshot_files(snapshot):
            raise RunExportError("referenced file is absent from its snapshot")


class _BundleFetcher:
    """Serve exported evidence without falling back to any original backend."""

    def __init__(self, root: Path, manifest: RunBundleManifest) -> None:
        self.root = root
        self.entries = {entry.path: entry for entry in manifest.entries}
        self.entries_by_source = {
            _source_key(entry.source): entry.path
            for entry in manifest.entries
            if entry.source.get("kind") != "root_run"
        }
        self.bindings = {
            _source_key(entry.source): entry.path
            for entry in manifest.entries
            if entry.source.get("kind")
            not in {"root_run", "executable", "viper_source"}
        }
        self.snapshots = {
            snapshot.source_sha256: snapshot.members for snapshot in manifest.snapshots
        }
        self.consumed_paths: set[RepoRelPath] = set()
        self.consumed_snapshots: set[SHA256] = set()

    def __call__(self, location: StorageModel) -> bytes:
        """Read one bound object or reject the absent original location."""
        key = _source_key(location.model_dump(mode="json"))
        try:
            path = self.bindings[key]
        except KeyError as exc:
            raise RunExportError(
                "bundle has no binding for a referenced payload"
            ) from exc
        self.consumed_paths.add(path)
        return (self.root / path).read_bytes()

    def read_verified(self, reference: ResolvedFileRef) -> bytes:
        """Read and verify one resolved reference from the bundle."""
        return verify_resolved_file_bytes(reference, self(reference.stored_at))

    def _read_local(self, source: dict[str, Any]) -> bytes:
        """Read one bundled host payload by its stable logical identity."""
        try:
            path = self.entries_by_source[_source_key(source)]
        except KeyError as exc:
            raise RunExportError("bundle omits a required host payload") from exc
        self.consumed_paths.add(path)
        return (self.root / path).read_bytes()

    def read_viper_source(self, reference: ConfigTypeRef) -> bytes:
        """Read one bundled VIPER config source file."""
        return self._read_local(
            {
                "kind": "viper_source",
                "bytes": reference.bytes,
                "path": reference.path,
                "sha256": reference.sha256,
                "symbol": reference.symbol,
            }
        )

    def read_plan_source(self, location: GitFileRef) -> bytes:
        """Read one bundled workspace source dependency from a frozen plan."""
        return self(location)

    def read_external_executable(
        self,
        executable: ResolvedExternalExecutable,
    ) -> bytes:
        """Read one bundled executable selected by a resolved retrieval."""
        return self.read_external_executable_spec(executable.spec)

    def read_external_executable_spec(self, spec: ExternalExecutableSpec) -> bytes:
        """Read one bundled executable selected by a planned retrieval."""
        return self._read_local(
            {
                "kind": "executable",
                "bytes": spec.bytes,
                "command": spec.command,
                "executable_id": spec.executable_id,
                "sha256": spec.sha256,
            }
        )

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshot,
    ) -> tuple[RepoRelPath, ...]:
        """Return the complete retained membership of one snapshot."""
        key = _source_key(snapshot.model_dump(mode="json"))
        try:
            members = self.snapshots[key]
        except KeyError as exc:
            raise RunExportError("bundle has no snapshot membership") from exc
        self.consumed_snapshots.add(key)
        self.consumed_paths.update(members)
        paths = []
        for member in members:
            entry = self.entries[member]
            location = _model_or_none(_STORAGE_ADAPTER, entry.source)
            if not isinstance(
                location,
                (GitFileRef, HuggingFaceFileRef, LocalFileRef, GcsFileRef),
            ):
                raise RunExportError("snapshot member has no storage binding")
            if location != _snapshot_location(snapshot, location.path):
                raise RunExportError("snapshot member belongs to another snapshot")
            paths.append(location.path)
        return tuple(paths)

    def observe_snapshot(
        self,
        snapshot: StageResultSnapshot,
        reference: SnapshotFileRef,
    ) -> None:
        """Consume membership and require the referenced file to belong to it."""
        if reference.path not in self.list_snapshot_files(snapshot):
            raise RunExportError("referenced file is absent from its snapshot")

    def require_complete_consumption(self) -> None:
        """Reject manifest objects and snapshots outside the verified graph."""
        expected_paths = {
            entry.path
            for entry in self.entries.values()
            if entry.source.get("kind") != "root_run"
        }
        if self.consumed_paths != expected_paths:
            raise RunExportError("bundle contains an unreachable payload")
        if self.consumed_snapshots != set(self.snapshots):
            raise RunExportError("bundle contains an unreachable snapshot")


def _model_or_none(adapter: TypeAdapter[Any], value: object) -> Any | None:
    """Try one strict protocol model without treating mismatch as an error."""
    try:
        return adapter.validate_python(value)
    except (TypeError, ValidationError, ValueError):
        return None


def _entry(
    path: RepoRelPath,
    source: dict[str, Any],
    raw: bytes,
) -> RunBundleEntry:
    """Describe one retained payload with its exact byte identity."""
    return RunBundleEntry(
        path=path,
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        source=source,
    )


def _manifest_bytes(manifest: RunBundleManifest) -> bytes:
    """Serialize one bundle manifest deterministically."""
    return _canonical_json(manifest.model_dump(mode="json"))


def _source_repository(
    resolved_run: ResolvedRun,
    *,
    repository_root: Path,
    store: LocalArtifactStore,
) -> str:
    """Read the run's own frozen source identity without guessing from trust."""
    if isinstance(resolved_run.spec.stored_at, GitFileRef):
        return str(resolved_run.spec.stored_at.repository)
    bootstrap = RunFetcher(
        repository_root,
        store,
        "",
    )
    try:
        raw = verify_resolved_file_bytes(
            resolved_run.spec,
            bootstrap(resolved_run.spec.stored_at),
        )
        run = RunSpec.model_validate(parse_yaml_bytes(raw))
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        raise RunExportError("run specification is invalid") from exc
    return str(run.source.repository)


def export_run(
    repository_root: Path,
    resolved_run_path: Path,
    output: Path,
    *,
    trusted_source_repositories: frozenset[str],
) -> RunExportResult:
    """Verify and export one complete terminal run evidence graph."""
    root = repository_root.resolve()
    terminal_path = resolved_run_path.resolve()
    destination = output.resolve()
    if not terminal_path.is_relative_to(root):
        raise RunExportError("resolved run path is outside the workspace root")
    if destination.exists() or destination.is_symlink():
        raise RunExportError("bundle output already exists")
    terminal_raw = terminal_path.read_bytes()
    try:
        resolved_run = ResolvedRun.model_validate(parse_yaml_bytes(terminal_raw))
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        raise RunExportError("terminal run document is invalid") from exc
    store = LocalArtifactStore(root)
    source_repository = _source_repository(
        resolved_run,
        repository_root=root,
        store=store,
    )
    delegate = RunFetcher(
        root,
        store,
        source_repository,
    )
    recording = _RecordingFetcher(delegate)
    verify_run_result(
        resolved_run,
        policy=VerificationPolicy(
            trusted_source_repositories=trusted_source_repositories
        ),
        fetcher=recording,
    )
    payloads = recording.payloads
    entries = [_entry("root/resolved.yaml", {"kind": "root_run"}, terminal_raw)]
    objects: dict[RepoRelPath, bytes] = {"root/resolved.yaml": terminal_raw}
    for key, (source, raw) in sorted(payloads.items()):
        path: RepoRelPath = f"objects/{key[:2]}/{key}"
        entries.append(_entry(path, source, raw))
        objects[path] = raw
    snapshots = tuple(
        RunBundleSnapshot(
            source_sha256=key,
            members=tuple(f"objects/{item[:2]}/{item}" for item in members),
        )
        for key, members in sorted(recording.snapshots.items())
    )
    manifest = RunBundleManifest(
        root_run="root/resolved.yaml",
        entries=tuple(sorted(entries, key=lambda item: item.path)),
        snapshots=snapshots,
    )
    manifest_raw = _manifest_bytes(manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        for path, raw in sorted(objects.items()):
            target = temporary / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (temporary / "manifest.json").write_bytes(manifest_raw)
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return RunExportResult(
        bundle_path=destination,
        manifest_path=destination / "manifest.json",
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        file_count=len(entries),
        total_bytes=sum(item.bytes for item in entries),
    )


def _load_manifest(path: Path) -> tuple[RunBundleManifest, bytes]:
    """Load a duplicate-key-safe JSON bundle manifest."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RunExportError("bundle manifest is unavailable") from exc

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RunExportError(f"duplicate manifest key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
        return RunBundleManifest.model_validate(value), raw
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise RunExportError("bundle manifest is invalid") from exc


def verify_run_bundle(
    bundle_path: Path,
    *,
    trusted_source_repositories: frozenset[str],
    expected_manifest_sha256: SHA256 | None = None,
) -> RunExportResult:
    """Verify exact bundle membership and every retained payload offline."""
    root = bundle_path.resolve()
    if not root.is_dir() or bundle_path.is_symlink():
        raise RunExportError("bundle path is not a regular directory")
    manifest, manifest_raw = _load_manifest(root / "manifest.json")
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    if (
        expected_manifest_sha256 is not None
        and manifest_sha256 != expected_manifest_sha256
    ):
        raise RunExportError("bundle manifest SHA-256 differs")
    expected = {
        PurePosixPath("manifest.json"),
        *(PurePosixPath(e.path) for e in manifest.entries),
    }
    observed: set[PurePosixPath] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RunExportError("bundle contains a symlink")
        if path.is_file():
            observed.add(PurePosixPath(path.relative_to(root).as_posix()))
    if observed != expected:
        raise RunExportError("bundle files differ from the manifest")
    for entry in manifest.entries:
        raw = (root / entry.path).read_bytes()
        if len(raw) != entry.bytes:
            raise RunExportError(f"bundle byte count differs: {entry.path}")
        if hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise RunExportError(f"bundle SHA-256 differs: {entry.path}")
    if manifest.root_run not in {entry.path for entry in manifest.entries}:
        raise RunExportError("bundle root run is absent from the manifest")
    try:
        resolved_run = ResolvedRun.model_validate(
            parse_yaml_bytes((root / manifest.root_run).read_bytes())
        )
        fetcher = _BundleFetcher(root, manifest)
        verify_run_result(
            resolved_run,
            policy=VerificationPolicy(
                trusted_source_repositories=trusted_source_repositories
            ),
            fetcher=fetcher,
        )
        fetcher.require_complete_consumption()
    except (
        RunExportError,
        VerificationError,
        yaml.YAMLError,
        ValueError,
        TypeError,
    ) as exc:
        raise RunExportError("bundle evidence graph is invalid") from exc
    return RunExportResult(
        bundle_path=root,
        manifest_path=root / "manifest.json",
        manifest_sha256=manifest_sha256,
        file_count=len(manifest.entries),
        total_bytes=sum(item.bytes for item in manifest.entries),
    )
