"""Store sealed VIPER revisions in Hugging Face repositories."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Literal

from huggingface_hub import CommitOperationAdd, HfApi, RepoFile, hf_hub_download
from pydantic import ValidationError

from ._cloud import (
    PublicationSource,
    RevisionManifest,
    ViperCloudDestination,
    ViperCloudError,
    ViperCloudProvider,
    canonical_json_bytes,
    resolve_publication_source,
)
from ._schema import SHA256, RepoRelPath
from .references import (
    CloudFileRef,
    CloudStageResultSnapshotRef,
    HuggingFaceFileRef,
    HuggingFaceStageResultSnapshotRef,
    SnapshotFileRef,
)

_MANIFEST_PATH: RepoRelPath = ".viper/revision-manifest.json"


class HuggingFaceProvider(ViperCloudProvider):
    """Store each sealed revision as one immutable Hugging Face commit."""

    def __init__(
        self,
        root: Path,
        repository: str,
        repo_type: Literal["model", "dataset", "space"],
        *,
        api: HfApi | None = None,
    ) -> None:
        """Bind publication to one Hugging Face repository."""
        super().__init__(root)
        if repo_type not in {"model", "dataset", "space"}:
            raise ValueError("Hugging Face repo_type is invalid")
        self.repository = repository
        self.repo_type: Literal["model", "dataset", "space"] = repo_type
        self.api = api or HfApi()

    @property
    def _api_repo_type(self) -> Literal["dataset", "space"] | None:
        """Return the repository type expected by huggingface_hub."""
        return None if self.repo_type == "model" else self.repo_type

    def publish_revision(
        self,
        *,
        destination: ViperCloudDestination,
        revision: SHA256,
        sources: Mapping[RepoRelPath, PublicationSource],
        files: tuple[SnapshotFileRef, ...],
    ) -> HuggingFaceStageResultSnapshotRef:
        """Commit payloads and their seal manifest as one repository revision."""
        manifest = RevisionManifest(
            owner=destination.owner,
            workspace=destination.workspace,
            revision=revision,
            files=files,
        )
        streams: list[BytesIO] = []
        operations: list[CommitOperationAdd] = []
        for path, source in sorted(sources.items()):
            resolved = resolve_publication_source(self.root, source)
            if isinstance(resolved, bytes):
                stream = BytesIO(resolved)
                streams.append(stream)
                payload: str | BytesIO = stream
            else:
                payload = str(resolved)
            operations.append(
                CommitOperationAdd(path_in_repo=path, path_or_fileobj=payload)
            )
        manifest_stream = BytesIO(canonical_json_bytes(manifest))
        streams.append(manifest_stream)
        operations.append(
            CommitOperationAdd(
                path_in_repo=_MANIFEST_PATH,
                path_or_fileobj=manifest_stream,
            )
        )
        self.api.create_repo(
            repo_id=self.repository,
            repo_type=self._api_repo_type,
            exist_ok=True,
        )
        commit = self.api.create_commit(
            repo_id=self.repository,
            repo_type=self._api_repo_type,
            operations=operations,
            commit_message=f"Publish VIPER revision {revision}",
        )
        return HuggingFaceStageResultSnapshotRef(
            repository=self.repository,
            commit=commit.oid,
            repo_type=self.repo_type,
        )

    def file_ref(
        self,
        snapshot: CloudStageResultSnapshotRef,
        path: RepoRelPath,
    ) -> HuggingFaceFileRef:
        """Address one canonical path in a Hugging Face commit."""
        if not isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
            raise TypeError(
                "HuggingFaceProvider requires a HuggingFaceStageResultSnapshotRef"
            )
        return HuggingFaceFileRef(
            repository=snapshot.repository,
            commit=snapshot.commit,
            path=path,
            repo_type=snapshot.repo_type,
        )

    def _download(self, location: HuggingFaceFileRef) -> Path:
        """Resolve one exact Hub file into the verified Hub cache."""
        try:
            downloaded = hf_hub_download(
                repo_id=location.repository,
                filename=location.path,
                repo_type=None if location.repo_type == "model" else location.repo_type,
                revision=location.commit,
            )
            return Path(downloaded)
        except (OSError, ValueError) as error:
            raise ViperCloudError(
                "Hugging Face could not retrieve the referenced file"
            ) from error

    def fetch(self, location: CloudFileRef) -> bytes:
        """Read one small file from the exact Hugging Face commit."""
        if not isinstance(location, HuggingFaceFileRef):
            raise TypeError("HuggingFaceProvider requires a HuggingFaceFileRef")
        return self._download(location).read_bytes()

    def fetch_to_path(
        self,
        location: CloudFileRef,
        identity: SnapshotFileRef,
        destination: Path,
    ) -> Path:
        """Materialize one Hugging Face file atomically beneath the workspace."""
        target = destination if destination.is_absolute() else self.root / destination
        target = target.resolve()
        if not target.is_relative_to(self.root):
            raise ViperCloudError("Hugging Face destination escapes the workspace")
        if target.exists():
            raise ViperCloudError("Hugging Face destination already exists")
        if not isinstance(location, HuggingFaceFileRef):
            raise TypeError("HuggingFaceProvider requires a HuggingFaceFileRef")
        if identity.path != location.path:
            raise ViperCloudError("Hugging Face file identity changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
        )
        temporary = Path(temporary_name)
        try:
            source = self._download(location)
            with (
                source.open("rb") as source_stream,
                os.fdopen(descriptor, "wb") as target_stream,
            ):
                shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            with temporary.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if temporary.stat().st_size != identity.bytes or digest != identity.sha256:
                raise ViperCloudError("Hugging Face file identity changed")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def list_files(
        self,
        snapshot: CloudStageResultSnapshotRef,
    ) -> tuple[SnapshotFileRef, ...]:
        """Read a VIPER seal or list a legacy external Hugging Face snapshot."""
        if not isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
            raise TypeError(
                "HuggingFaceProvider requires a HuggingFaceStageResultSnapshotRef"
            )
        manifest_ref = self.file_ref(snapshot, _MANIFEST_PATH)
        try:
            manifest = RevisionManifest.model_validate_json(self.fetch(manifest_ref))
            return manifest.files
        except (ViperCloudError, ValidationError):
            try:
                entries = self.api.list_repo_tree(
                    repo_id=snapshot.repository,
                    recursive=True,
                    revision=snapshot.commit,
                    repo_type=(
                        None if snapshot.repo_type == "model" else snapshot.repo_type
                    ),
                )
            except (OSError, ValueError) as error:
                raise ViperCloudError("Hugging Face snapshot listing failed") from error
            paths = tuple(
                sorted(entry.path for entry in entries if isinstance(entry, RepoFile))
            )
            identities = []
            for path in paths:
                raw = self.fetch(self.file_ref(snapshot, path))
                identities.append(
                    SnapshotFileRef(
                        path=path,
                        sha256=hashlib.sha256(raw).hexdigest(),
                        bytes=len(raw),
                    )
                )
            return tuple(identities)


__all__ = ["HuggingFaceProvider"]
