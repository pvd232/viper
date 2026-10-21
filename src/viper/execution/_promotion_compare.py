"""Compare the original graph with its additional cloud publication."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .._cloud import ViperCloudRepository
from .._source import RunFetcher
from ..cloud import ViperCloud
from ..huggingface import HuggingFaceProvider
from ..references import (
    GitFileRef,
    GitSource,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StorageModel,
    resolve_snapshot_file_ref,
)
from ..reuse import stage_spec_sha256
from ..serialization import parse_yaml_bytes
from ..stages import Spec
from ._promotion_journal import SnapshotCopy
from ._promotion_transfer import TransferSpace
from .errors import RunPromotionError

_SPEC = TypeAdapter(Spec)


def _key(value: BaseModel | dict[str, Any]) -> str:
    """Give each complete source address a stable dictionary key."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _file(copy: SnapshotCopy, member: SnapshotFileRef) -> ResolvedFileRef:
    """Locate an original file using the saved snapshot and file identity."""
    if isinstance(copy.source, GitSource):
        location = GitFileRef(**copy.source.model_dump(), path=member.path)
        return ResolvedFileRef(
            stored_at=location, sha256=member.sha256, bytes=member.bytes
        )
    return resolve_snapshot_file_ref(copy.source, member)


def _match(expected: Any, actual: Any, path: str = "document") -> None:
    """Reject changed references, fields, and list members with a useful path."""
    if isinstance(expected, dict):
        if "stored_at" in expected or expected.get("kind") in {
            "gcs",
            "huggingface",
            "local",
            "viper_cloud",
        }:
            if expected != actual:
                raise RunPromotionError(f"graph relationship changed: {path}")
            return
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise RunPromotionError(f"unexpected metadata change: {path}")
        for name, value in expected.items():
            _match(value, actual[name], f"{path}.{name}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise RunPromotionError(f"unexpected metadata change: {path}")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            _match(left, right, f"{path}[{index}]")
    elif type(expected) is not type(actual) or expected != actual:
        raise RunPromotionError(f"unexpected metadata change: {path}")


class GraphComparison:
    """Check file contents and allowed metadata changes from saved copy records."""

    def __init__(
        self,
        copies: Sequence[SnapshotCopy],
        documents: Sequence[StorageModel],
        source: RunFetcher,
        destination: RunFetcher,
        *,
        destination_repository: ViperCloudRepository,
        space: TransferSpace | None = None,
    ) -> None:
        """Build exact file mappings from independently readable copy records."""
        if source.cache_root == destination.cache_root:
            raise RunPromotionError(
                "source and destination checks require separate caches"
            )
        self.copies = tuple(copies)
        self.documents = {_key(file) for file in documents}
        self.source = source
        self.destination = destination
        self.space = space
        self.files: dict[str, ResolvedFileRef] = {}
        self.originals: dict[str, ResolvedFileRef] = {}
        self.containers: dict[str, SnapshotCopy] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.hashes: dict[str, str] = {}
        for copy in self.copies:
            if copy.published is None:
                raise RunPromotionError("publication is incomplete")
            if ViperCloud._repository_for(copy.published) != destination_repository:
                raise RunPromotionError("destination repository differs")
            self.snapshots[_key(copy.source)] = copy.published.model_dump(mode="json")
            destination_files = {file.path: file for file in copy.expected.files}
            if set(destination_files) != {file.path for file in copy.source_files}:
                raise RunPromotionError("snapshot membership changed")
            for member in copy.source_files:
                original = _file(copy, member)
                copied = resolve_snapshot_file_ref(
                    copy.published, destination_files[member.path]
                )
                key = _key(original.stored_at)
                if key in self.files and (
                    self.files[key] != copied or self.originals[key] != original
                ):
                    raise RunPromotionError("conflicting source identity")
                self.originals[key] = original
                self.files[key] = copied
                self.containers[key] = copy
                if member.sha256 != copied.sha256:
                    previous = self.hashes.setdefault(member.sha256, copied.sha256)
                    if previous != copied.sha256:
                        raise RunPromotionError("ambiguous changed document hash")

        if not self.documents <= self.originals.keys():
            raise RunPromotionError("document list names an uncopied file")

    def _expected(self, value: Any, copy: SnapshotCopy) -> Any:
        """Calculate the allowed reference and derived-hash changes from the source."""
        if isinstance(value, list):
            return [self._expected(item, copy) for item in value]
        if not isinstance(value, dict):
            return value
        location = value.get("stored_at")
        if isinstance(location, dict):
            target = self.files.get(_key(location))
            if target is None:
                if location.get("kind") == "git":
                    return value
                raise RunPromotionError(
                    "graph relationship changed: unmapped source file"
                )
            return {**value, **target.model_dump(mode="json")}
        if {"stage_id", "snapshot", "resolved_spec"} <= value.keys():
            target_snapshot = self.snapshots.get(_key(value["snapshot"]))
            if target_snapshot is None:
                raise RunPromotionError("graph relationship changed: unmapped stage")
            original_location = {
                **value["snapshot"],
                "path": value["resolved_spec"]["path"],
            }
            target = self.files[_key(original_location)]
            return {
                **value,
                "snapshot": target_snapshot,
                "resolved_spec": {
                    **value["resolved_spec"],
                    "sha256": target.sha256,
                    "bytes": target.bytes,
                },
            }
        kind = value.get("kind")
        if kind in {"local", "gcs", "huggingface", "viper_cloud"}:
            snapshot = self.snapshots.get(_key(value))
            if snapshot is not None:
                return snapshot
        if kind == "git" and str(value.get("path", "")).startswith(".viper/pointers/"):
            target = self.files.get(_key(value))
            if target is None:
                raise RunPromotionError("graph relationship changed: unmapped pointer")
            return {"kind": "artifact_pointer", **target.model_dump(mode="json")}
        result = {name: self._expected(item, copy) for name, item in value.items()}
        if {"run_id", "stages", "estimator"} <= value.keys():
            members = {file.path: file for file in copy.expected.files}
            for stage in result["stages"]:
                member = members[stage["spec"]]
                stage.update(sha256=member.sha256, bytes=member.bytes)
        if {"key", "source_stage"} <= value.keys():
            stage = value["source_stage"]
            location = {**stage["snapshot"], "path": stage["resolved_spec"]["path"]}
            key = _key(location)
            original = parse_yaml_bytes(self.source.read(self.originals[key]))
            expected_stage = self._expected(original, self.containers[key])
            result["key"]["stage_sha256"] = stage_spec_sha256(
                _SPEC.validate_python(expected_stage["spec"])
            )
        if {"roots", "nodes", "edges"} <= value.keys():
            for node in result["nodes"]:
                node["node_id"] = self._receipt_id(node["node_id"])
            for edge in result["edges"]:
                edge["source"] = self._receipt_id(edge["source"])
                edge["target"] = self._receipt_id(edge["target"])
            result["nodes"].sort(key=lambda node: node["node_id"])
            result["edges"].sort(
                key=lambda edge: (edge["source"], edge["target"], edge["relation"])
            )
            for roots in result["roots"].values():
                roots.sort(
                    key=lambda root: (
                        root["run_id"],
                        root["attempt_id"],
                        root["stage_id"],
                        root["input_name"],
                        root["stage_receipt"]["resolved_spec"]["sha256"],
                    )
                )
        return result

    def _receipt_id(self, value: str) -> str:
        """Update the receipt-hash part of a saved source-graph identifier."""
        if value.startswith(("pointer:", "reuse:")):
            prefix, digest = value.split(":", 1)
            return f"{prefix}:{self.hashes.get(digest, digest)}"
        prefix, marker, tail = value.partition("/receipt:")
        if not marker:
            return value
        digest, slash, rest = tail.partition("/")
        return f"{prefix}{marker}{self.hashes.get(digest, digest)}{slash}{rest}"

    def verify(
        self,
        roots: Sequence[ResolvedRunRef],
        required_files: Mapping[str, ResolvedFileRef],
    ) -> dict[str, Any]:
        """Check every copied file, the required inventory, and each graph root."""
        for role, reference in required_files.items():
            original = self.originals.get(_key(reference.stored_at))
            if original is None:
                raise RunPromotionError(f"inventory item is unreachable: {role}")
            if original.sha256 != reference.sha256 or original.bytes != reference.bytes:
                raise RunPromotionError(f"conflicting source identity: {role}")
        for copy in self.copies:
            assert copy.published is not None
            cloud = self.destination._cloud_service(copy.published)
            if isinstance(cloud.provider, HuggingFaceProvider):
                if cloud.provider.read_manifest(copy.published) != copy.expected:
                    raise RunPromotionError("destination snapshot differs")
            if self.destination.snapshot_files(copy.published) != copy.expected.files:
                raise RunPromotionError("destination snapshot differs")
            if isinstance(copy.source, LocalStageResultSnapshotRef):
                if set(self.source.list_snapshot_files(copy.source)) != {
                    file.path for file in copy.source_files
                }:
                    raise RunPromotionError("source snapshot files changed")
            elif not isinstance(copy.source, GitSource):
                if self.source.snapshot_files(copy.source) != copy.source_files:
                    raise RunPromotionError("source snapshot files changed")
        if self.space is not None:
            self.space.prepare_reader(self.source)
            self.space.prepare_reader(self.destination)
        for key, original in self.originals.items():
            copied = self.files[key]
            if self.space is not None:
                self.space.check(original.bytes + copied.bytes)
            if key in self.documents:
                source_document = parse_yaml_bytes(self.source.read(original))
                copied_document = parse_yaml_bytes(self.destination.read(copied))
                _match(
                    self._expected(source_document, self.containers[key]),
                    copied_document,
                )
            else:
                if (original.sha256, original.bytes) != (copied.sha256, copied.bytes):
                    raise RunPromotionError("scientific payload changed")
                self.source.path(original)
                self.destination.path(copied)
            if self.space is not None:
                self.space.check()
                self.space.release(self.source)
                self.space.release(self.destination)
        published_roots = []
        for root in roots:
            copied = self.files.get(_key(root.stored_at))
            if copied is None:
                raise RunPromotionError("selected root is missing from publication")
            original = self.originals[_key(root.stored_at)]
            if (original.sha256, original.bytes) != (root.sha256, root.bytes):
                raise RunPromotionError("conflicting source identity: selected root")
            published_roots.append(
                ResolvedRunRef(**copied.model_dump()).model_dump(mode="json")
            )
        return {
            "schema_version": 1,
            "passed": True,
            "source_roots": [root.model_dump(mode="json") for root in roots],
            "destination_roots": published_roots,
            "files_checked": len(self.files),
            "documents_checked": len(self.documents),
            "required_files_checked": len(required_files),
        }
