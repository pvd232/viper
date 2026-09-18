"""Promote a verified local run graph to configured cloud storage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..cloud import ViperCloud
from ..evidence import VerificationPolicy
from ..references import (
    CloudStageResultSnapshotRef,
    GcsFileRef,
    GitFileRef,
    HuggingFaceFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
)
from ..runs import ResolvedRun, RunSpec
from ..serialization import parse_yaml_bytes
from ..storage import (
    LocalArtifactStore,
    ViperCloudDestination,
    content_revision,
    load_storage_settings,
    local_artifact_store,
)
from ..verification import verify_run_result
from ._restore import resolve_run_reference
from ._source import RunFetcher
from .errors import RunPromotionError


class _RunGraphPromoter:
    """Rewrite one verified local reference DAG from its leaves upward."""

    def __init__(
        self,
        root: Path,
        cloud: ViperCloud,
        destination: ViperCloudDestination,
    ) -> None:
        self.root = root
        self.cloud = cloud
        self.destination = destination
        self.files: dict[LocalFileRef, ResolvedFileRef] = {}
        self.snapshots: dict[
            LocalStageResultSnapshotRef,
            CloudStageResultSnapshotRef,
        ] = {}
        self.snapshot_files: dict[
            LocalStageResultSnapshotRef,
            tuple[SnapshotFileRef, ...],
        ] = {}

    def promote_reference(self, reference: ResolvedFileRef) -> ResolvedFileRef:
        """Promote one local file after rewriting its referenced descendants."""
        location = reference.stored_at
        if isinstance(location, (GcsFileRef, HuggingFaceFileRef)):
            return reference
        if not isinstance(location, LocalFileRef):
            return reference
        remembered = self.files.get(location)
        if remembered is not None:
            return remembered
        try:
            raw = local_artifact_store(location).fetch(location)
        except (OSError, RuntimeError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
        if (
            len(raw) != reference.bytes
            or hashlib.sha256(raw).hexdigest() != reference.sha256
        ):
            raise RunPromotionError("source run graph is unavailable")
        snapshot = LocalStageResultSnapshotRef(
            workspace=location.workspace,
            store=location.store,
            store_id=location.store_id,
            commit=location.commit,
        )
        promoted_snapshot = self.promote_snapshot(snapshot)
        matches = tuple(
            file for file in self.snapshot_files[snapshot] if file.path == location.path
        )
        if len(matches) != 1:
            raise RunPromotionError("source run graph is unavailable")
        identity = matches[0]
        promoted = ResolvedFileRef(
            sha256=identity.sha256,
            bytes=identity.bytes,
            stored_at=self.cloud.file_ref(promoted_snapshot, identity.path),
        )
        self.files[location] = promoted
        return promoted

    def promote_snapshot(
        self,
        snapshot: LocalStageResultSnapshotRef,
    ) -> CloudStageResultSnapshotRef:
        """Promote every member of one local snapshot as a sealed unit."""
        remembered = self.snapshots.get(snapshot)
        if remembered is not None:
            return remembered
        store = local_artifact_store(snapshot)
        try:
            paths = store.list_snapshot_files(snapshot)
            original = {
                path: store.fetch(
                    LocalFileRef(
                        workspace=snapshot.workspace,
                        store=snapshot.store,
                        store_id=snapshot.store_id,
                        commit=snapshot.commit,
                        path=path,
                    )
                )
                for path in paths
            }
            if content_revision(original) != snapshot.commit:
                raise RunPromotionError("source run graph is unavailable")
            sources = {
                path: self.rewrite_payload(path, raw) for path, raw in original.items()
            }
        except (OSError, RuntimeError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
        promoted, files = self.cloud.publish(self.destination, sources)
        self.snapshots[snapshot] = promoted
        self.snapshot_files[snapshot] = files
        return promoted

    def rewrite_stage_reference(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Rewrite one stage snapshot and the identity of its resolved record."""
        try:
            snapshot = LocalStageResultSnapshotRef.model_validate(value["snapshot"])
            resolved_spec = dict(value["resolved_spec"])
            path = resolved_spec["path"]
        except (KeyError, TypeError, ValueError) as error:
            raise RunPromotionError("source run graph is unavailable") from error
        promoted_snapshot = self.promote_snapshot(snapshot)
        matches = tuple(
            file for file in self.snapshot_files[snapshot] if file.path == path
        )
        if len(matches) != 1:
            raise RunPromotionError("source run graph is unavailable")
        identity = matches[0]
        rewritten = {
            key: self.rewrite_value(item)
            for key, item in value.items()
            if key not in {"snapshot", "resolved_spec"}
        }
        rewritten["snapshot"] = promoted_snapshot.model_dump(mode="json")
        resolved_spec.update(sha256=identity.sha256, bytes=identity.bytes)
        rewritten["resolved_spec"] = resolved_spec
        return rewritten

    def rewrite_payload(self, path: str, raw: bytes) -> bytes:
        """Rewrite local references inside one structured protocol document."""
        if not path.endswith((".yaml", ".yml", ".json")):
            return raw
        try:
            value = parse_yaml_bytes(raw)
        except (UnicodeDecodeError, ValueError, yaml.YAMLError):
            return raw
        rewritten = self.rewrite_value(value)
        if _contains_local_reference(rewritten):
            raise RunPromotionError("promoted run graph retains local storage")
        if rewritten == value:
            return raw
        if path.endswith(".json"):
            return (
                json.dumps(rewritten, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        rendered = yaml.safe_dump(rewritten, allow_unicode=True, sort_keys=False)
        return rendered.encode("utf-8")

    def rewrite_value(self, value: Any) -> Any:
        """Replace local file and snapshot nodes while preserving other values."""
        if isinstance(value, list):
            return [self.rewrite_value(item) for item in value]
        if not isinstance(value, dict):
            return value
        if (
            isinstance(value.get("snapshot"), Mapping)
            and value["snapshot"].get("kind") == "local"
            and isinstance(value.get("resolved_spec"), Mapping)
        ):
            return self.rewrite_stage_reference(value)
        stored_at = value.get("stored_at")
        if (
            isinstance(stored_at, dict)
            and stored_at.get("kind") == "local"
            and "path" in stored_at
            and "sha256" in value
            and "bytes" in value
        ):
            try:
                reference = ResolvedFileRef(
                    sha256=value["sha256"],
                    bytes=value["bytes"],
                    stored_at=LocalFileRef.model_validate(stored_at),
                )
            except ValueError as error:
                raise RunPromotionError("source run graph is unavailable") from error
            promoted = self.promote_reference(reference)
            rewritten = dict(value)
            rewritten.update(
                sha256=promoted.sha256,
                bytes=promoted.bytes,
                stored_at=promoted.stored_at.model_dump(mode="json"),
            )
            return rewritten
        if (
            value.get("kind") == "local"
            and "commit" in value
            and "path" not in value
            and "workspace" in value
        ):
            try:
                snapshot = LocalStageResultSnapshotRef.model_validate(value)
            except ValueError as error:
                raise RunPromotionError("source run graph is unavailable") from error
            return self.promote_snapshot(snapshot).model_dump(mode="json")
        return {key: self.rewrite_value(item) for key, item in value.items()}


def _source_repository(root: Path, run: ResolvedRun) -> str:
    """Read the source repository from a local run's immutable plan."""
    location = run.spec.stored_at
    if isinstance(location, GitFileRef):
        return str(location.repository)
    if isinstance(location, LocalFileRef):
        raw = local_artifact_store(location).fetch(location)
    else:
        raw = RunFetcher(root, LocalArtifactStore(root), "")(location)
    return str(RunSpec.model_validate(parse_yaml_bytes(raw)).source.repository)


def _contains_local_reference(value: Any) -> bool:
    """Return whether a serialized promoted graph still names local storage."""
    if isinstance(value, list):
        return any(_contains_local_reference(item) for item in value)
    if isinstance(value, Mapping):
        if (
            value.get("kind") == "local"
            and "workspace" in value
            and "store" in value
            and "store_id" in value
            and "commit" in value
        ):
            return True
        return any(_contains_local_reference(item) for item in value.values())
    return False


def promote_run_to_cloud(
    repository_root: Path,
    source: Path | ResolvedRunRef,
    destination: ViperCloudDestination,
) -> ResolvedRunRef:
    """Verify and promote one local run graph to the required destination."""
    root = repository_root.resolve(strict=True)
    reference = resolve_run_reference(root, source)
    if not isinstance(reference.stored_at, LocalFileRef):
        raise RunPromotionError("source run graph is unavailable")
    try:
        raw = local_artifact_store(reference.stored_at).fetch(reference.stored_at)
        record = ResolvedRun.model_validate(parse_yaml_bytes(raw))
        source_repository = _source_repository(root, record)
        fetcher = RunFetcher(root, LocalArtifactStore(root), source_repository)
        verify_run_result(
            record,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({source_repository})
            ),
            fetcher=fetcher,
        )
    except Exception as error:
        raise RunPromotionError("source run graph is unavailable") from error
    settings = load_storage_settings(root)
    if settings.repository is None:
        raise RunPromotionError("cloud destination is not configured")
    promoter = _RunGraphPromoter(
        root,
        ViperCloud(root, settings.repository),
        destination,
    )
    promoted = promoter.promote_reference(reference)
    result = ResolvedRunRef.model_validate(promoted.model_dump(mode="python"))
    if not isinstance(result.stored_at, (GcsFileRef, HuggingFaceFileRef)):
        raise RunPromotionError("promoted run graph is not cloud-backed")
    return result


__all__ = ["promote_run_to_cloud"]
