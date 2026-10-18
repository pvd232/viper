"""Store sealed VIPER revisions in Hugging Face repositories."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Literal

from huggingface_hub import (
    CommitOperationAdd,
    HfApi,
    get_session,
    hf_hub_download,
    hf_hub_url,
    hf_raise_for_status,
)
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.utils._headers import build_hf_headers

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
        self.stream_files = False
        self.cache_dir: Path | None = None
        self.upload_threads = 5

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
        attempt = 0
        while True:
            try:
                commit = self.api.create_commit(
                    repo_id=self.repository,
                    repo_type=self._api_repo_type,
                    operations=operations,
                    commit_message=f"Publish VIPER revision {revision}",
                    num_threads=self.upload_threads,
                )
                break
            except HfHubHTTPError as error:
                if error.response.status_code != 429 or attempt == 3:
                    raise
                attempt += 1
                # A 429 rejects the write; lost responses still reach the journal.
                retry_after = error.response.headers.get("Retry-After", "").strip()
                delay = int(retry_after) + 1 if retry_after.isdigit() else 3601
                logging.getLogger(__name__).warning(
                    "Hub rejected commit for %s with HTTP 429; retrying in %ss",
                    self.repository,
                    delay,
                )
                time.sleep(delay)
        return HuggingFaceStageResultSnapshotRef(
            repository=self.repository,
            commit=commit.oid,
            repo_type=self.repo_type,
        )

    def publication_head(self) -> str:
        """Read the current commit before saving a publication intent."""
        head = self.api.repo_info(self.repository, repo_type=self._api_repo_type).sha
        if head is None:
            raise ViperCloudError("destination commit is unavailable")
        return head

    def find_publication(
        self, expected: RevisionManifest, previous_head: str
    ) -> HuggingFaceStageResultSnapshotRef | None:
        """Find the exact committed files after a lost upload response."""
        found = []
        reached_previous = False
        for commit in self.api.list_repo_commits(
            self.repository, repo_type=self._api_repo_type
        ):
            if commit.commit_id == previous_head:
                reached_previous = True
                break
            if commit.title != f"Publish VIPER revision {expected.revision}":
                continue
            snapshot = HuggingFaceStageResultSnapshotRef(
                repository=self.repository,
                repo_type=self.repo_type,
                commit=commit.commit_id,
            )
            manifest = RevisionManifest.model_validate_json(
                self.fetch(self.file_ref(snapshot, _MANIFEST_PATH))
            )
            if manifest == expected:
                found.append(snapshot)
        if not reached_previous or len(found) > 1:
            raise ViperCloudError("remote publication outcome is unresolved")
        return found[0] if found else None

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
                cache_dir=self.cache_dir,
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
            digest_state = hashlib.sha256()
            size = 0
            with os.fdopen(descriptor, "wb") as target_stream:
                if self.stream_files:
                    url = hf_hub_url(
                        self.repository,
                        location.path,
                        repo_type=self._api_repo_type,
                        revision=location.commit,
                    )
                    with get_session().stream(
                        "GET",
                        url,
                        headers=build_hf_headers(token=self.api.token),
                        follow_redirects=True,
                        timeout=120,
                    ) as response:
                        hf_raise_for_status(response)
                        for chunk in response.iter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > identity.bytes:
                                raise ViperCloudError(
                                    "Hugging Face file exceeds its recorded size"
                                )
                            digest_state.update(chunk)
                            target_stream.write(chunk)
                else:
                    with self._download(location).open("rb") as source_stream:
                        while chunk := source_stream.read(1024 * 1024):
                            size += len(chunk)
                            if size > identity.bytes:
                                raise ViperCloudError(
                                    "Hugging Face file exceeds its recorded size"
                                )
                            digest_state.update(chunk)
                            target_stream.write(chunk)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            digest = digest_state.hexdigest()
            if temporary.stat().st_size != identity.bytes or digest != identity.sha256:
                raise ViperCloudError("Hugging Face file identity changed")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def read_manifest(self, snapshot: CloudStageResultSnapshotRef) -> RevisionManifest:
        """Read the file list and owner saved in a snapshot."""
        if not isinstance(snapshot, HuggingFaceStageResultSnapshotRef):
            raise TypeError(
                "HuggingFaceProvider requires a HuggingFaceStageResultSnapshotRef"
            )
        manifest_ref = self.file_ref(snapshot, _MANIFEST_PATH)
        return RevisionManifest.model_validate_json(self.fetch(manifest_ref))

    def list_files(
        self, snapshot: CloudStageResultSnapshotRef
    ) -> tuple[SnapshotFileRef, ...]:
        """Return each saved file's path, size, and hash."""
        return self.read_manifest(snapshot).files


__all__ = ["HuggingFaceProvider"]
