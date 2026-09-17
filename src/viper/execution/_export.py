"""Export complete verified-run evidence into a portable directory bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import deque
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError

from .._schema import SHA256, RepoRelPath
from .._verification.storage import verify_resolved_file_bytes
from ..evidence import VerificationError, VerificationPolicy
from ..http import ExternalExecutableSpec
from ..references import (
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    StageResultSnapshot,
    StorageModel,
    StorageRef,
    ViperCloudFileRef,
    ViperCloudStageResultSnapshotRef,
)
from ..runs import ResolvedRun
from ..serialization import parse_yaml_bytes
from ..storage import LocalArtifactStore, ViperCloudClient
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
    return ViperCloudFileRef(
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
        self.pending_documents: deque[tuple[StorageModel, bytes]] = deque()

    def __call__(self, location: StorageModel) -> bytes:
        """Retrieve and retain one payload by its complete storage locator."""
        source = location.model_dump(mode="json")
        key = _source_key(source)
        if key in self.payloads:
            return self.payloads[key][1]
        raw = self.delegate(location)
        self.payloads[key] = (source, raw)
        if str(location.path).endswith((".yaml", ".yml", ".json")):
            self.pending_documents.append((location, raw))
        return raw

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshot,
    ) -> tuple[RepoRelPath, ...]:
        """Record the complete ordered membership of one immutable snapshot."""
        paths = self.delegate.list_snapshot_files(snapshot)
        source = snapshot.model_dump(mode="json")
        snapshot_key = _source_key(source)
        members = []
        for path in paths:
            location = _snapshot_location(snapshot, path)
            self(location)
            members.append(_source_key(location.model_dump(mode="json")))
        self.snapshots[snapshot_key] = tuple(members)
        return paths


class _BundleFetcher:
    """Serve exported evidence without falling back to any original backend."""

    def __init__(self, root: Path, manifest: RunBundleManifest) -> None:
        self.root = root
        self.entries = {entry.path: entry for entry in manifest.entries}
        self.bindings = {
            _source_key(entry.source): entry.path
            for entry in manifest.entries
            if entry.source.get("kind")
            not in {"root_run", "executable", "viper_source"}
        }
        self.snapshots = {
            snapshot.source_sha256: snapshot.members for snapshot in manifest.snapshots
        }

    def __call__(self, location: StorageModel) -> bytes:
        """Read one bound object or reject the absent original location."""
        key = _source_key(location.model_dump(mode="json"))
        try:
            path = self.bindings[key]
        except KeyError as exc:
            raise RunExportError(
                "bundle has no binding for a referenced payload"
            ) from exc
        return (self.root / path).read_bytes()

    def read_verified(self, reference: ResolvedFileRef) -> bytes:
        """Read and verify one resolved reference from the bundle."""
        return verify_resolved_file_bytes(reference, self(reference.stored_at))

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
        paths = []
        for member in members:
            entry = self.entries[member]
            location = _model_or_none(_STORAGE_ADAPTER, entry.source)
            if not isinstance(
                location,
                (GitFileRef, HuggingFaceFileRef, LocalFileRef, ViperCloudFileRef),
            ):
                raise RunExportError("snapshot member has no storage binding")
            paths.append(location.path)
        return tuple(paths)


def _model_or_none(adapter: TypeAdapter[Any], value: object) -> Any | None:
    """Try one strict protocol model without treating mismatch as an error."""
    try:
        return adapter.validate_python(value)
    except (TypeError, ValidationError, ValueError):
        return None


def _walk_value(
    value: object,
    *,
    fetcher: _RecordingFetcher,
    source: GitSource,
    executable_payloads: dict[str, tuple[dict[str, Any], bytes]],
) -> None:
    """Follow storage, snapshot, source-code, and executable references."""
    if isinstance(value, Mapping):
        mapping = dict(value)
        if set(mapping) == {"sha256", "bytes", "stored_at"}:
            reference = _model_or_none(TypeAdapter(ResolvedFileRef), mapping)
            if isinstance(reference, ResolvedFileRef):
                verify_resolved_file_bytes(reference, fetcher(reference.stored_at))
        location = _model_or_none(_STORAGE_ADAPTER, mapping)
        if isinstance(
            location,
            (GitFileRef, HuggingFaceFileRef, LocalFileRef, ViperCloudFileRef),
        ):
            fetcher(location)
        snapshot = _model_or_none(_SNAPSHOT_ADAPTER, mapping)
        if isinstance(
            snapshot,
            (
                HuggingFaceStageResultSnapshotRef,
                LocalStageResultSnapshotRef,
                ViperCloudStageResultSnapshotRef,
            ),
        ):
            fetcher.list_snapshot_files(snapshot)
        if {"path", "symbol", "sha256", "bytes"} <= set(mapping):
            path = mapping.get("path")
            if isinstance(path, str) and path.endswith(".py"):
                if mapping.get("owner") == "viper":
                    raw = (Path(__file__).resolve().parents[1] / path).read_bytes()
                    if (
                        len(raw) != mapping["bytes"]
                        or hashlib.sha256(raw).hexdigest() != mapping["sha256"]
                    ):
                        raise RunExportError("installed VIPER source identity differs")
                    installed_source = {
                        "kind": "viper_source",
                        "path": path,
                        "symbol": mapping["symbol"],
                    }
                    executable_payloads[_source_key(installed_source)] = (
                        installed_source,
                        raw,
                    )
                else:
                    reference = ResolvedFileRef(
                        sha256=mapping["sha256"],
                        bytes=mapping["bytes"],
                        stored_at=GitFileRef(
                            repository=source.repository,
                            commit=source.commit,
                            path=path,
                        ),
                    )
                    verify_resolved_file_bytes(reference, fetcher(reference.stored_at))
        if {"executable_id", "command", "sha256", "bytes"} <= set(mapping):
            try:
                executable = ExternalExecutableSpec.model_validate(mapping)
            except ValueError:
                executable = None
            if executable is not None:
                selected = shutil.which(executable.command)
                if selected is None:
                    raise RunExportError(
                        f"required executable is unavailable: {executable.command}"
                    )
                raw = Path(selected).resolve().read_bytes()
                if (
                    len(raw) != executable.bytes
                    or hashlib.sha256(raw).hexdigest() != executable.sha256
                ):
                    raise RunExportError(
                        f"executable identity differs: {executable.command}"
                    )
                executable_source = {
                    "kind": "executable",
                    "command": executable.command,
                    "executable_id": executable.executable_id,
                }
                executable_payloads[_source_key(executable_source)] = (
                    executable_source,
                    raw,
                )
        for item in mapping.values():
            _walk_value(
                item,
                fetcher=fetcher,
                source=source,
                executable_payloads=executable_payloads,
            )
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_value(
                item,
                fetcher=fetcher,
                source=source,
                executable_payloads=executable_payloads,
            )


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


def export_run(
    repository_root: Path,
    resolved_run_path: Path,
    output: Path,
    *,
    trusted_source_repositories: frozenset[str],
    cloud_client: ViperCloudClient | None = None,
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
    source_repository = (
        str(resolved_run.spec.stored_at.repository)
        if isinstance(resolved_run.spec.stored_at, GitFileRef)
        else next(iter(trusted_source_repositories), "")
    )
    if not source_repository:
        raise RunExportError("run source repository cannot be determined")
    delegate = RunFetcher(
        root,
        LocalArtifactStore(root),
        source_repository,
        cloud_client=cloud_client,
    )
    recording = _RecordingFetcher(delegate)
    verified = verify_run_result(
        resolved_run,
        policy=VerificationPolicy(
            trusted_source_repositories=trusted_source_repositories
        ),
        fetcher=recording,
    )
    source = verified.plan.run.source
    executable_payloads: dict[str, tuple[dict[str, Any], bytes]] = {}
    _walk_value(
        resolved_run.model_dump(mode="json"),
        fetcher=recording,
        source=source,
        executable_payloads=executable_payloads,
    )
    while recording.pending_documents:
        _, raw = recording.pending_documents.popleft()
        try:
            parsed = parse_yaml_bytes(raw)
        except (yaml.YAMLError, ValueError, TypeError):
            continue
        _walk_value(
            parsed,
            fetcher=recording,
            source=source,
            executable_payloads=executable_payloads,
        )

    payloads = dict(recording.payloads)
    payloads.update(executable_payloads)
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
    raw = path.read_bytes()

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
        verify_run_result(
            resolved_run,
            policy=VerificationPolicy(
                trusted_source_repositories=trusted_source_repositories
            ),
            fetcher=_BundleFetcher(root, manifest),
        )
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
