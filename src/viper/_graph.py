"""Read saved run dependencies without changing references or creating cloud clients."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, SerializeAsAny, TypeAdapter

from ._cloud import GcsRepository, PublicationSource
from ._offload import current_session
from ._schema import ArtifactName, ProtocolModel
from ._source import RunFetcher
from .artifacts import (
    ArtifactPointer,
    ResolvedArtifact,
    ResolvedSingleFileArtifact,
    StageArtifactRef,
)
from .benchmark import BenchmarkResult, BenchmarkSpec
from .evidence import VerificationPolicy
from .experiments import ExperimentSpec, VariantSpec
from .ids import InputName, StageId
from .inputs import ResolvedExternalInputRef, StoredInputRef
from .metrics import MetricVerificationReceipt
from .references import (
    ArtifactPointerRef,
    GitFileRef,
    GitSource,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedArtifactPointerRef,
    ResolvedBenchmarkResultRef,
    ResolvedBenchmarkSpecRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageRef,
    SnapshotFileRef,
    StageResultSnapshotRef,
    StorageModel,
    ViperCloudFileRef,
    resolve_snapshot_file_ref,
)
from .repository import read_source
from .reuse import ResolvedStageReuseRef, StageReuseReceipt
from .runs import ResolvedAttemptRef, ResolvedRun, RunAttempt, RunSpec
from .serialization import load_stage_spec, parse_yaml_bytes
from .stages import ResolvedBaseSpec, ResolvedSpec, Spec
from .storage import LocalArtifactStore, load_storage_settings
from .verification import verify_pointer_producer

_SPEC_ADAPTER = TypeAdapter(Spec)
_RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)
_DocumentDecoder = Callable[[object], BaseModel]
SourceSnapshot = StageResultSnapshotRef | GitSource
_SNAPSHOT_ADAPTER = TypeAdapter(SourceSnapshot)
_SourceSnapshotRef = SourceSnapshot


class _ReadBudget(Protocol):
    """Reuse the existing transfer budget while discovering a graph."""

    def prepare_reader(self, fetcher: RunFetcher) -> None:
        """Configure the clients already used by this reader."""
        ...

    def check(self, snapshot_bytes: int = 0, largest_file: int = 0) -> None:
        """Check space before reading the selected files."""
        ...


class PromotionInventory(ProtocolModel):
    """Name the runs and files that an additional publication must contain."""

    schema_version: Literal[1] = Field(
        default=1, description="Inventory format version."
    )
    roots: tuple[ResolvedRunRef, ...] = Field(
        min_length=1, description="Runs to publish."
    )
    supporting_roots: tuple[
        SerializeAsAny[ResolvedStageRef | ResolvedFileRef | ResolvedRunRef], ...
    ] = Field(
        default=(),
        description="Additional saved runs, stages, and source files.",
    )
    required_files: dict[str, ResolvedFileRef] = Field(
        description="Expected files, keyed by their role in the application."
    )


class RunGraphReader:
    """Follow the complete saved graph through its existing typed references."""

    def __init__(
        self,
        root: Path,
        *,
        fetcher: RunFetcher,
        error_type: type[Exception] = ValueError,
    ) -> None:
        """Use the caller's file resolver and error type."""
        self.root = root
        self.fetcher = fetcher
        self.error_type = error_type
        self._read_budget: _ReadBudget | None = None
        self.inventory: PromotionInventory | None = None
        self.source_files: dict[StorageModel, tuple[int, str | None]] = {}
        self.source_members: dict[SourceSnapshot, tuple[StorageModel, ...]] = {}
        self.dependencies: dict[SourceSnapshot, set[SourceSnapshot]] = {}
        self.documents: dict[SourceSnapshot, dict[str, BaseModel]] = {}
        self._reading: list[StorageModel] = []

    @staticmethod
    def snapshot_for(location: StorageModel) -> _SourceSnapshotRef:
        """Return the snapshot containing a file."""
        return _SNAPSHOT_ADAPTER.validate_python(location.model_dump(exclude={"path"}))

    @staticmethod
    def file_in_snapshot(
        snapshot: _SourceSnapshotRef, file: SnapshotFileRef
    ) -> ResolvedFileRef:
        """Combine a file's size and hash with its snapshot address."""
        if isinstance(snapshot, GitSource):
            location = GitFileRef(**snapshot.model_dump(), path=file.path)
            return ResolvedFileRef(
                stored_at=location, sha256=file.sha256, bytes=file.bytes
            )
        return resolve_snapshot_file_ref(snapshot, file)

    def _record_file(
        self, location: StorageModel, size: int, digest: str | None
    ) -> None:
        """Record a file once and reject conflicting sizes or hashes."""
        previous = self.source_files.get(location)
        if previous is not None:
            if previous[0] != size or (
                previous[1] and digest and previous[1] != digest
            ):
                raise self.error_type("conflicting source identity")
            digest = digest or previous[1]
        self.source_files[location] = (size, digest)

    def discover_snapshot(self, snapshot: _SourceSnapshotRef) -> None:
        """List a snapshot's files before reading any artifact bodies."""
        if snapshot in self.source_members or isinstance(snapshot, GitSource):
            return
        locations = []
        for member in self.fetcher.snapshot_files(snapshot):
            reference = resolve_snapshot_file_ref(snapshot, member)
            self._record_file(reference.stored_at, member.bytes, member.sha256)
            locations.append(reference.stored_at)
        self.source_members[snapshot] = tuple(locations)

    def discover_inventory(
        self, inventory: PromotionInventory
    ) -> tuple[_SourceSnapshotRef, ...]:
        """List the required files and return snapshots in dependency order."""
        self.inventory = inventory
        for reference in inventory.roots:
            self.discover_reference(reference, ResolvedRun.model_validate)
        for reference in inventory.supporting_roots:
            self.discover_typed(reference)
        for role, reference in inventory.required_files.items():
            actual = self.source_files.get(reference.stored_at)
            if actual is None:
                raise self.error_type(f"inventory item is unreachable: {role}")
            self._record_file(reference.stored_at, reference.bytes, reference.sha256)
        ordered: list[_SourceSnapshotRef] = []
        active: set[_SourceSnapshotRef] = set()
        complete: set[_SourceSnapshotRef] = set()

        def visit(snapshot: _SourceSnapshotRef) -> None:
            """Place each dependency before the snapshot that uses it."""
            if snapshot in active:
                raise self.error_type("storage cycle")
            if snapshot in complete:
                return
            active.add(snapshot)
            for child in sorted(
                self.dependencies.get(snapshot, ()), key=lambda x: x.model_dump_json()
            ):
                visit(child)
            active.remove(snapshot)
            complete.add(snapshot)
            ordered.append(snapshot)

        for snapshot in self.source_members:
            visit(snapshot)
        if self._read_budget is not None:
            self._read_budget.prepare_reader(self.fetcher)
            for locations in self.source_members.values():
                sizes = [self.source_files[file][0] for file in locations]
                self._read_budget.check(sum(sizes), max(sizes, default=0))
        return tuple(ordered)

    def read_document(self, reference: ResolvedFileRef) -> bytes:
        """Read a run document through the supplied fetcher."""
        try:
            if self._read_budget is not None:
                self._read_budget.check(reference.bytes, reference.bytes)
            return self.fetcher.read(reference)
        except Exception as err:
            raise self.error_type("source run graph is unavailable") from err

    @staticmethod
    def source_identity(path: str, source: PublicationSource) -> SnapshotFileRef:
        """Identify one publication source without retaining its payload."""
        if isinstance(source, bytes):
            return SnapshotFileRef(
                path=path,
                sha256=hashlib.sha256(source).hexdigest(),
                bytes=len(source),
            )
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return SnapshotFileRef(path=path, sha256=digest.hexdigest(), bytes=size)

    @staticmethod
    def document_decoder(reference: ResolvedFileRef) -> _DocumentDecoder | None:
        """Select a document schema from the reference's protocol role."""
        if isinstance(reference, ResolvedRunRef):
            return ResolvedRun.model_validate
        if isinstance(reference, ResolvedRunSpecRef):
            return RunSpec.model_validate
        if isinstance(reference, ResolvedAttemptRef):
            return RunAttempt.model_validate
        if isinstance(reference, ResolvedArtifactPointerRef):
            return ArtifactPointer.model_validate
        if isinstance(reference, ResolvedStageReuseRef):
            return StageReuseReceipt.model_validate
        if isinstance(reference, ResolvedBenchmarkSpecRef):
            return BenchmarkSpec.model_validate
        if isinstance(reference, ResolvedBenchmarkResultRef):
            return BenchmarkResult.model_validate
        return None

    def discover_reference(
        self,
        reference: ResolvedFileRef,
        decoder: _DocumentDecoder | None = None,
    ) -> None:
        """Record a file and follow the links in its saved document."""
        location = reference.stored_at
        if self.inventory is None and not isinstance(location, LocalFileRef):
            return
        if isinstance(location, ViperCloudFileRef):
            if not isinstance(
                load_storage_settings(self.root).repository, GcsRepository
            ):
                raise self.error_type("legacy source binding is required")
        self._record_file(location, reference.bytes, reference.sha256)
        snapshot = self.snapshot_for(location)
        if self.inventory is not None:
            self.discover_snapshot(snapshot)
            if self._reading:
                parent = self.snapshot_for(self._reading[-1])
                if parent != snapshot:
                    self.dependencies.setdefault(parent, set()).add(snapshot)
        selected_decoder = decoder or self.document_decoder(reference)
        if selected_decoder is None:
            return
        if location in self._reading:
            raise self.error_type("storage cycle")
        documents = self.documents.setdefault(snapshot, {})
        if location.path in documents:
            return
        self._reading.append(location)
        try:
            document = selected_decoder(parse_yaml_bytes(self.read_document(reference)))
            documents[location.path] = document
            if isinstance(document, RunSpec):
                self.discover_plan_members(snapshot, document)
            if isinstance(document, RunAttempt):
                for metric in document.metric_verification_files:
                    self.discover_reference(
                        metric, MetricVerificationReceipt.model_validate
                    )
            if isinstance(document, BenchmarkResult):
                for metric in document.metrics:
                    self.discover_reference(
                        metric.candidate_verification,
                        MetricVerificationReceipt.model_validate,
                    )
                    self.discover_reference(
                        metric.confirmation_verification,
                        MetricVerificationReceipt.model_validate,
                    )
            if isinstance(document, StageReuseReceipt):
                for metric in document.metrics:
                    if metric.verification is not None:
                        self.discover_reference(
                            metric.verification,
                            MetricVerificationReceipt.model_validate,
                        )
            self.discover_typed(document)
        except self.error_type:
            raise
        except Exception as error:
            raise self.error_type("source run graph is unavailable") from error
        finally:
            self._reading.pop()

    def discover_snapshot_document(
        self,
        snapshot: _SourceSnapshotRef,
        identity: SnapshotFileRef,
        decoder: _DocumentDecoder,
    ) -> None:
        """Follow a document using its snapshot, path, size, and hash."""
        self.discover_reference(self.file_in_snapshot(snapshot, identity), decoder)

    def discover_plan_document(
        self,
        snapshot: _SourceSnapshotRef,
        path: str,
        decoder: _DocumentDecoder,
    ) -> None:
        """Read a saved plan file and follow its references."""
        if isinstance(snapshot, (LocalStageResultSnapshotRef, GitSource)):
            placeholder = SnapshotFileRef(path=path, bytes=0, sha256="0" * 64)
            location = self.file_in_snapshot(snapshot, placeholder).stored_at
            raw = self.fetcher(location)
            identity = SnapshotFileRef(
                path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
            )
        else:
            identity = next(
                (
                    file
                    for file in self.fetcher.snapshot_files(snapshot)
                    if file.path == path
                ),
                None,
            )
            if identity is None:
                raise self.error_type("plan document is missing from snapshot")
        self.discover_snapshot_document(snapshot, identity, decoder)

    def discover_plan_members(
        self,
        snapshot: _SourceSnapshotRef,
        run: RunSpec,
    ) -> None:
        """Register every typed document selected by one frozen run plan."""
        if self.inventory is not None:
            self.discover_plan_document(
                snapshot,
                f"experiments/{run.experiment_id}/spec.yaml",
                ExperimentSpec.model_validate,
            )
            self.discover_plan_document(
                snapshot,
                f"experiments/{run.experiment_id}/variants/{run.variant_id}.spec.yaml",
                VariantSpec.model_validate,
            )
        for stage in run.stages:
            self.discover_snapshot_document(
                snapshot,
                SnapshotFileRef(
                    path=stage.spec,
                    sha256=stage.sha256,
                    bytes=stage.bytes,
                ),
                _SPEC_ADAPTER.validate_python,
            )
        if run.benchmark_id is not None:
            self.discover_plan_document(
                snapshot,
                f"benchmarks/{run.benchmark_id}.spec.yaml",
                BenchmarkSpec.model_validate,
            )

    def discover_stage_reference(self, reference: ResolvedStageRef) -> None:
        """Register the resolved stage document selected by a stage reference."""
        if self.inventory is not None or isinstance(
            reference.snapshot, LocalStageResultSnapshotRef
        ):
            self.discover_snapshot_document(
                reference.snapshot,
                reference.resolved_spec,
                _RESOLVED_SPEC_ADAPTER.validate_python,
            )

    def discover_typed(self, value: Any) -> None:
        """Walk typed objects and register every referenced protocol document."""
        if isinstance(value, ArtifactPointerRef) and self.inventory is not None:
            raw = self.fetcher(value)
            reference = ResolvedArtifactPointerRef(
                stored_at=value, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)
            )
            self.discover_reference(reference)
            return
        if isinstance(value, SnapshotFileRef) and self._reading:
            snapshot = self.snapshot_for(self._reading[-1])
            reference = self.file_in_snapshot(snapshot, value)
            if reference.stored_at in self.source_files:
                self._record_file(reference.stored_at, value.bytes, value.sha256)
            return
        if isinstance(value, ResolvedStageRef):
            self.discover_stage_reference(value)
            return
        if isinstance(value, ResolvedFileRef):
            self.discover_reference(value)
            return
        if isinstance(value, BaseModel):
            for item in value.__dict__.values():
                self.discover_typed(item)
            for item in (value.model_extra or {}).values():
                self.discover_typed(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                self.discover_typed(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                self.discover_typed(item)


def register_stage_artifacts(
    store: LocalArtifactStore,
    stage_id: StageId,
    snapshot: StageResultSnapshotRef,
    artifacts: Mapping[ArtifactName, ResolvedArtifact],
    captured: Mapping[InputName, SnapshotFileRef],
) -> None:
    """Register whole output artifacts and captured input files once."""
    for name, artifact in artifacts.items():
        store.registry.register_artifact(
            snapshot,
            StageArtifactRef(stage_id=stage_id, artifact_name=name),
            artifact,
        )
    for member in captured.values():
        store.registry.register_artifact(
            snapshot,
            member.path,
            ResolvedSingleFileArtifact(relative_path=member.path, file=member),
        )


def enroll_run(
    root: Path,
    reference: ResolvedRunRef,
    *,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> tuple[StageResultSnapshotRef, ...]:
    """Verify a saved producer and enroll its unchanged dependency graph."""
    session = current_session()
    if session is None:
        raise ValueError("run enrollment requires a workflow")
    previous = session.enrolled_runs.get(reference)
    if previous is not None:
        return previous
    store = LocalArtifactStore(root)
    repository = str(read_source(root).repository)
    fetcher = RunFetcher(root, store, repository)
    terminal = ResolvedRun.model_validate(parse_yaml_bytes(fetcher.read(reference)))
    plan = RunSpec.model_validate(parse_yaml_bytes(fetcher.read(terminal.spec)))
    verify_pointer_producer(
        ArtifactPointer(run=reference, artifact=plan.estimator),
        policy=VerificationPolicy(
            trusted_source_repositories=frozenset({repository})
            | trusted_source_repositories
        ),
        fetcher=fetcher,
    )
    reader = RunGraphReader(root, fetcher=fetcher)
    ordered = reader.discover_inventory(
        PromotionInventory(roots=(reference,), required_files={})
    )
    admitted: list[StageResultSnapshotRef] = []
    for snapshot in ordered:
        if isinstance(snapshot, GitSource):
            files = {}
            for location, (size, digest) in reader.source_files.items():
                if (
                    not isinstance(location, GitFileRef)
                    or reader.snapshot_for(location) != snapshot
                ):
                    continue
                if digest is None:
                    digest = hashlib.sha256(fetcher(location)).hexdigest()
                file = ResolvedFileRef(stored_at=location, sha256=digest, bytes=size)
                files[location.path] = fetcher.path(file)
            if files:
                commit, _ = store._publish(files, path_custody="cache")
                admitted.append(
                    LocalStageResultSnapshotRef(
                        workspace=root, store=store.store, commit=commit
                    )
                )
            continue
        members = fetcher.snapshot_files(snapshot)
        if isinstance(snapshot, LocalStageResultSnapshotRef):
            for member in members:
                file = resolve_snapshot_file_ref(snapshot, member)
                adopted = store.adopt_verified_reference(file, fetcher.path(file))
                fetcher.remember_path(file, adopted)
        else:
            store.snapshot_files(snapshot)
        registered = store.registry.snapshot(snapshot)
        if registered is None:
            raise ValueError("producer snapshot was not registered")
        session.admit(registered.inventory)
        admitted.append(snapshot)
    for documents in reader.documents.values():
        for document in documents.values():
            if not isinstance(document, RunAttempt):
                continue
            for stage in document.resolved_stages:
                resolved = reader.documents.get(stage.snapshot, {}).get(
                    stage.resolved_spec.path
                )
                if not isinstance(resolved, ResolvedBaseSpec):
                    raise ValueError("producer stage record is missing")
                captured = {
                    name: value.file
                    for name, value in getattr(resolved, "inputs", {}).items()
                    if isinstance(value, ResolvedExternalInputRef)
                }
                register_stage_artifacts(
                    store, stage.stage_id, stage.snapshot, resolved.artifacts, captured
                )
    sources = tuple(dict.fromkeys(admitted))
    session.enrolled_runs[reference] = sources
    return sources


def enroll_plan_inputs(
    root: Path,
    run: RunSpec,
    *,
    trusted_source_repositories: frozenset[str] = frozenset(),
) -> None:
    """Protect saved producer inputs before their run is scheduled."""
    if current_session() is None:
        return
    repository = str(read_source(root).repository)
    fetcher = RunFetcher(root, LocalArtifactStore(root), repository)
    enrolled: set[ResolvedRunRef] = set()
    for stage in run.stages:
        spec = load_stage_spec(root / stage.spec)
        for input_ref in getattr(spec, "inputs", {}).values():
            if not isinstance(input_ref, StoredInputRef):
                continue
            pointer_ref = input_ref.pointer
            raw = (
                fetcher.read(pointer_ref)
                if isinstance(pointer_ref, ResolvedFileRef)
                else fetcher(pointer_ref)
            )
            pointer = ArtifactPointer.model_validate(parse_yaml_bytes(raw))
            if pointer.run not in enrolled:
                enroll_run(
                    root,
                    pointer.run,
                    trusted_source_repositories=trusted_source_repositories,
                )
                enrolled.add(pointer.run)
