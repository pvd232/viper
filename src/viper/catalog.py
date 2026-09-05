"""Build and query the local provenance catalog."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from ._schema import (
    SHA256,
    ArtifactName,
    BenchmarkId,
    DataRole,
    GitCommit,
)
from .benchmark import BenchmarkMetricResult
from .ids import ExperimentId, MetricId, ReplicateId, RunId, StageId, VariantId
from .inspection import RunLineage, lineage
from .knowledge import (
    AssertionQuery,
    AssignmentQuery,
    CatalogKnowledgeRecord,
    CatalogPrimitive,
    DeclaredPrimitiveAssignment,
    DiagnosticQuery,
    DiagnosticSignature,
    EffectEstimate,
    EffectQuery,
    ImpactAssessment,
    ImpactPolicy,
    ImpactQuery,
    InferredPrimitiveAssignment,
    JournalAssertion,
    KnowledgeManifest,
    KnowledgePage,
    KnowledgeRecordEnvelope,
    KnowledgeVector,
    Modulation,
    ModulationQuery,
    OntologySpec,
    PrimitivePage,
    PrimitiveQuery,
    PrimitiveRef,
    RetrievalJudgment,
    RetrievalJudgmentQuery,
    ReviewedPrimitiveAssignment,
    SimilarityMatch,
    SimilarityPage,
    SimilarityQuery,
)
from .references import (
    LocalFileRef,
    ResolvedBenchmarkResultRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshot,
)
from .reuse import StageReuseCandidate, StageReuseKey, stage_reuse_key_sha256
from .runs import RunAttempt
from .serialization import document_digest, parse_yaml_bytes, serialize_document
from .stages import DownloadSpec, InternalSpec
from .storage import LocalArtifactStore
from .verification.models import VerifiedBenchmarkResult, VerifiedRunResult

CatalogRunStatus = Literal["succeeded", "failed", "cancelled"]

CatalogBenchmarkStatus = Literal["verified", "passed", "failed"]

MeasurementOrigin = Literal["executed", "reused"]


class CatalogRun(BaseModel):
    """Return one verified run with its immutable terminal reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    status: CatalogRunStatus
    source_commit: GitCommit
    env_sha256: SHA256
    reproducibility_sha256: SHA256
    benchmark_id: BenchmarkId | None
    verification: Literal["verified"] = "verified"
    completed_at: AwareDatetime


class CatalogFile(BaseModel):
    """Identify one file inside a verified stage snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: StageResultSnapshot
    file: SnapshotFileRef


class CatalogArtifact(BaseModel):
    """Return one verified artifact and all of its file identities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    run_id: RunId
    stage_id: StageId
    artifact_name: ArtifactName
    kind: Literal["file", "bundle"]
    data_role: DataRole
    files: tuple[CatalogFile, ...] = Field(min_length=1)


class CatalogMeasurement(BaseModel):
    """Return one verified metric value and its immutable file reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    measurement: ResolvedFileRef
    run_id: RunId
    stage_id: StageId
    metric_id: MetricId
    value: float = Field(allow_inf_nan=False)
    epoch: int | None = Field(default=None, ge=0)
    step: int | None = Field(default=None, ge=0)
    origin: MeasurementOrigin
    measured_at: AwareDatetime


class CatalogBenchmark(BaseModel):
    """Return one independently verified benchmark result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: ResolvedBenchmarkResultRef
    run: ResolvedRunRef
    benchmark_id: BenchmarkId
    status: CatalogBenchmarkStatus
    metrics: tuple[BenchmarkMetricResult, ...] = Field(min_length=1)


class CatalogEdge(BaseModel):
    """Retain one lineage relationship from a verified run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef
    source: str
    target: str
    relation: Literal["produces", "selects", "consumes", "reuses"]


class RunQuery(BaseModel):
    """Filter verified runs by exact recorded identities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    replicate_ids: tuple[ReplicateId, ...] = ()
    statuses: tuple[CatalogRunStatus, ...] = ()
    source_commit: GitCommit | None = None
    env_sha256: SHA256 | None = None
    reproducibility_sha256: SHA256 | None = None
    benchmark_id: BenchmarkId | None = None
    input_sha256: SHA256 | None = None
    artifact_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class ArtifactQuery(BaseModel):
    """Filter verified artifacts by run, stage, role, or file identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    artifact_names: tuple[ArtifactName, ...] = ()
    data_roles: tuple[DataRole, ...] = ()
    sha256: SHA256 | None = None
    source_commit: GitCommit | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class MeasurementQuery(BaseModel):
    """Filter verified measurements by run context and scalar value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    input_sha256: SHA256 | None = None
    env_sha256: SHA256 | None = None
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    origins: tuple[MeasurementOrigin, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class BenchmarkQuery(BaseModel):
    """Filter verified benchmark results by run and evaluated evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: ExperimentId | None = None
    variant_ids: tuple[VariantId, ...] = ()
    benchmark_ids: tuple[BenchmarkId, ...] = ()
    statuses: tuple[CatalogBenchmarkStatus, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    source_commit: GitCommit | None = None
    env_sha256: SHA256 | None = None
    input_sha256: SHA256 | None = None
    artifact_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


ItemT = TypeVar("ItemT", bound=BaseModel)


class CatalogPage(BaseModel, Generic[ItemT]):
    """Return one deterministic page from an exact catalog query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[ItemT, ...]
    next_cursor: str | None = None


class RunPage(CatalogPage[CatalogRun]):
    """Return one page of verified runs."""


class ArtifactPage(CatalogPage[CatalogArtifact]):
    """Return one page of verified artifacts."""


class MeasurementPage(CatalogPage[CatalogMeasurement]):
    """Return one page of verified measurements."""


class BenchmarkPage(CatalogPage[CatalogBenchmark]):
    """Return one page of verified benchmark results."""


class CatalogRefreshResult(BaseModel):
    """Describe one complete atomic catalog replacement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    database: Path
    sha256: SHA256
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)


@dataclass(frozen=True)
class CatalogRunSource:
    """Pair one immutable terminal reference with its verified contents."""

    reference: ResolvedRunRef
    verified: VerifiedRunResult
    reuse_candidates: tuple[StageReuseCandidate, ...] = ()


@dataclass(frozen=True)
class CatalogBenchmarkSource:
    """Pair one immutable benchmark reference with its verified contents."""

    reference: ResolvedBenchmarkResultRef
    verified: VerifiedBenchmarkResult


_SCHEMA = """
PRAGMA user_version = 1;
CREATE TABLE sources (
    source_key TEXT PRIMARY KEY,
    reference_json TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    error TEXT
);
CREATE TABLE runs (
    source_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    lineage_json TEXT NOT NULL
);
CREATE TABLE stages (source_key TEXT NOT NULL, stage_id TEXT NOT NULL);
CREATE TABLE inputs (source_key TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE artifacts (
    source_key TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE files (
    source_key TEXT NOT NULL,
    artifact_name TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TABLE measurements (
    source_key TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE benchmarks (
    source_key TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE edges (
    source_key TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE stage_reuse_keys (
    key_sha256 TEXT NOT NULL,
    source_key TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    run_id TEXT NOT NULL,
    attempt_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (key_sha256, source_key)
);
CREATE TABLE knowledge_records (
    reference_key TEXT PRIMARY KEY,
    reference_json TEXT NOT NULL,
    record_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE knowledge_primitives (
    ontology_key TEXT NOT NULL,
    primitive_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (ontology_key, primitive_id)
);
"""


def _json(value: BaseModel) -> str:
    """Serialize one model for deterministic SQLite storage."""
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reference_key(reference: BaseModel) -> str:
    """Return one stable key for an immutable reference."""
    return hashlib.sha256(_json(reference).encode()).hexdigest()


def _source_error(source: CatalogRunSource) -> str | None:
    """Return why a verified result does not match its terminal reference."""
    raw = serialize_document(source.verified.result)
    if len(raw) != source.reference.bytes:
        return "terminal run byte count differs from its immutable reference"
    if hashlib.sha256(raw).hexdigest() != source.reference.sha256:
        return "terminal run digest differs from its immutable reference"
    return None


def _benchmark_error(
    source: CatalogBenchmarkSource,
    accepted_runs: set[str],
) -> str | None:
    """Return why a benchmark cannot enter the current catalog."""
    raw = serialize_document(source.verified.result)
    if len(raw) != source.reference.bytes:
        return "benchmark byte count differs from its immutable reference"
    if hashlib.sha256(raw).hexdigest() != source.reference.sha256:
        return "benchmark digest differs from its immutable reference"
    if _reference_key(source.verified.result.run) not in accepted_runs:
        return "benchmark run is absent from the accepted catalog sources"
    return None


def _digests(value: object) -> tuple[str, ...]:
    """Collect SHA-256 fields from one resolved input tree."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        found = [
            str(item)
            for key, item in value.items()
            if key == "sha256" and isinstance(item, str)
        ]
        for item in value.values():
            found.extend(_digests(item))
        return tuple(found)
    if isinstance(value, (list, tuple)):
        return tuple(digest for item in value for digest in _digests(item))
    return ()


def _successful_attempt(verified: VerifiedRunResult) -> RunAttempt | None:
    """Return the attempt selected by the terminal run."""
    selected = verified.result.successful_attempt_id
    return next(
        (attempt for attempt in verified.attempts if attempt.attempt_id == selected),
        None,
    )


def _run_row(source: CatalogRunSource) -> CatalogRun:
    """Build one searchable run row from verified evidence."""
    run = source.verified.plan.run
    return CatalogRun(
        run=source.reference,
        run_id=run.run_id,
        experiment_id=run.experiment_id,
        variant_id=run.variant_id,
        replicate_id=run.replicate_id,
        status=source.verified.result.status,
        source_commit=run.source.commit,
        env_sha256=document_digest(run.env),
        reproducibility_sha256=document_digest(run.reproducibility),
        benchmark_id=run.benchmark_id,
        completed_at=source.verified.result.completed_at,
    )


def _artifact_rows(source: CatalogRunSource) -> tuple[CatalogArtifact, ...]:
    """Build artifact rows from the successful verified stage snapshots."""
    attempt = _successful_attempt(source.verified)
    if attempt is None:
        return ()
    snapshots = {stage.stage_id: stage.snapshot for stage in attempt.resolved_stages}
    rows: list[CatalogArtifact] = []
    for stage_id, resolved in sorted(source.verified.resolved_stages.items()):
        snapshot = snapshots[stage_id]
        for name, artifact in sorted(resolved.artifacts.items()):
            declared = resolved.spec.artifacts[name]
            if artifact.kind == "file":
                files = (CatalogFile(snapshot=snapshot, file=artifact.file),)
            else:
                files = tuple(
                    CatalogFile(snapshot=snapshot, file=member.file)
                    for member in artifact.members
                )
            rows.append(
                CatalogArtifact(
                    run=source.reference,
                    run_id=source.verified.plan.run.run_id,
                    stage_id=stage_id,
                    artifact_name=name,
                    kind=artifact.kind,
                    data_role=declared.data_role,
                    files=files,
                )
            )
    return tuple(rows)


def _measurement_rows(source: CatalogRunSource) -> tuple[CatalogMeasurement, ...]:
    """Pair each verified measurement with its immutable measurement file."""
    files = {
        attempt.attempt_id: attempt.measurement_files
        for attempt in source.verified.attempts
    }
    counts: dict[int, int] = {}
    rows: list[CatalogMeasurement] = []
    for measurement in source.verified.measurements:
        position = counts.get(measurement.attempt_id, 0)
        available = files.get(measurement.attempt_id, ())
        if position >= len(available):
            raise ValueError("measurement is missing its immutable file reference")
        reference = available[position]
        counts[measurement.attempt_id] = position + 1
        rows.append(
            CatalogMeasurement(
                run=source.reference,
                measurement=reference,
                run_id=measurement.run_id,
                stage_id=measurement.stage_id,
                metric_id=measurement.metric_id,
                value=measurement.value,
                epoch=measurement.epoch,
                step=measurement.step,
                origin="executed",
                measured_at=measurement.measured_at,
            )
        )
    if any(
        counts.get(attempt_id, 0) != len(available)
        for attempt_id, available in files.items()
    ):
        raise ValueError("measurement file has no verified measurement")
    return tuple(rows)


def _query_digest(query: BaseModel) -> str:
    """Bind one cursor to every filter except its current cursor value."""
    payload = query.model_dump(mode="json", exclude={"cursor"})
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _cursor_offset(query: BaseModel) -> int:
    """Decode a cursor and reject one issued for another query."""
    cursor = getattr(query, "cursor")
    if cursor is None:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, json.JSONDecodeError) as error:
        raise ValueError("catalog cursor is invalid") from error
    if not isinstance(payload, dict) or set(payload) != {"query", "offset"}:
        raise ValueError("catalog cursor is invalid")
    if payload["query"] != _query_digest(query):
        raise ValueError("catalog cursor belongs to another query")
    offset = payload["offset"]
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("catalog cursor offset is invalid")
    return offset


def _next_cursor(query: BaseModel, offset: int) -> str:
    """Encode the next offset with the exact query identity."""
    raw = json.dumps(
        {"query": _query_digest(query), "offset": offset},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _validate_reuse_candidate(
    source: CatalogRunSource,
    candidate: StageReuseCandidate,
) -> None:
    """Keep every indexed candidate inside its verified successful attempt."""
    if candidate.source_run != source.reference:
        raise ValueError("reuse candidate belongs to another run")
    successful_id = source.verified.result.successful_attempt_id
    if candidate.source_attempt not in source.verified.result.attempts:
        raise ValueError("reuse candidate attempt is absent from its run")
    attempt = next(
        (
            item
            for item in source.verified.attempts
            if item.attempt_id == candidate.attempt_id
        ),
        None,
    )
    if attempt is None or attempt.attempt_id != successful_id:
        raise ValueError("reuse candidate does not use the successful attempt")
    if candidate.source_stage not in attempt.resolved_stages:
        raise ValueError("reuse candidate stage is absent from its attempt")


def _knowledge_bytes(root: Path, reference: ResolvedFileRef) -> bytes:
    """Load one local immutable file and verify its recorded identity."""
    if not isinstance(reference.stored_at, LocalFileRef):
        raise ValueError("catalog knowledge refresh currently requires local files")
    raw = LocalArtifactStore(root, reference.stored_at.store).fetch(reference.stored_at)
    if len(raw) != reference.bytes:
        raise ValueError("knowledge file byte count differs")
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ValueError("knowledge file digest differs")
    return raw


def _knowledge_chain(
    root: Path,
    heads: tuple[ResolvedFileRef, ...],
) -> tuple[CatalogKnowledgeRecord, ...]:
    """Walk manifest heads and return each immutable record once."""
    manifests: set[str] = set()
    records: dict[str, CatalogKnowledgeRecord] = {}

    def visit(manifest_ref: ResolvedFileRef, path: frozenset[str]) -> None:
        """Walk one chain while distinguishing cycles from shared history."""
        manifest_key = _reference_key(manifest_ref)
        if manifest_key in path:
            raise ValueError("knowledge manifest chain contains a cycle")
        if manifest_key in manifests:
            return
        manifests.add(manifest_key)
        manifest = KnowledgeManifest.model_validate(
            parse_yaml_bytes(_knowledge_bytes(root, manifest_ref))
        )
        record_key = _reference_key(manifest.record)
        if record_key not in records:
            envelope = KnowledgeRecordEnvelope.model_validate(
                parse_yaml_bytes(_knowledge_bytes(root, manifest.record))
            )
            records[record_key] = CatalogKnowledgeRecord(
                reference=manifest.record,
                record=envelope,
            )
        if manifest.previous is not None:
            visit(manifest.previous, path | {manifest_key})

    for head in heads:
        visit(head, frozenset())
    return tuple(records[key] for key in sorted(records))


class Catalog:
    """Refresh and query one derived SQLite catalog."""

    def __init__(self, root: Path):
        """Bind the catalog to one project root."""
        self.root = root.resolve()
        self.path = self.root / ".viper/catalog.sqlite3"

    def refresh(
        self,
        *,
        runs: tuple[CatalogRunSource, ...] = (),
        benchmarks: tuple[CatalogBenchmarkSource, ...] = (),
        knowledge: tuple[ResolvedFileRef, ...] = (),
    ) -> CatalogRefreshResult:
        """Rebuild the complete catalog and atomically replace the old index."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".catalog.",
            suffix=".sqlite3",
            dir=self.path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary)
        accepted = 0
        rejected = 0
        accepted_runs: set[str] = set()
        try:
            connection = sqlite3.connect(temporary_path)
            try:
                connection.executescript(_SCHEMA)
                for source in runs:
                    key = _reference_key(source.reference)
                    error = _source_error(source)
                    connection.execute(
                        "INSERT INTO sources VALUES (?, ?, ?, ?)",
                        (key, _json(source.reference), error is None, error),
                    )
                    if error is not None:
                        rejected += 1
                        continue
                    accepted += 1
                    accepted_runs.add(key)
                    row = _run_row(source)
                    run_lineage = lineage(source.verified)
                    connection.execute(
                        "INSERT INTO runs VALUES (?, ?, ?)",
                        (key, _json(row), _json(run_lineage)),
                    )
                    for stage_id in source.verified.resolved_stages:
                        connection.execute(
                            "INSERT INTO stages VALUES (?, ?)",
                            (key, str(stage_id)),
                        )
                    resolved_stages = source.verified.resolved_stages.values()
                    for digest in sorted(
                        set(
                            _digests(
                                tuple(
                                    stage.spec.inputs
                                    for stage in resolved_stages
                                    if isinstance(
                                        stage.spec,
                                        (DownloadSpec, InternalSpec),
                                    )
                                )
                            )
                        )
                    ):
                        connection.execute(
                            "INSERT INTO inputs VALUES (?, ?)",
                            (key, digest),
                        )
                    for artifact in _artifact_rows(source):
                        connection.execute(
                            "INSERT INTO artifacts VALUES (?, ?)",
                            (key, _json(artifact)),
                        )
                        for item in artifact.files:
                            connection.execute(
                                "INSERT INTO files VALUES (?, ?, ?)",
                                (key, str(artifact.artifact_name), item.file.sha256),
                            )
                    for measurement in _measurement_rows(source):
                        connection.execute(
                            "INSERT INTO measurements VALUES (?, ?)",
                            (key, _json(measurement)),
                        )
                    for edge in run_lineage.edges:
                        catalog_edge = CatalogEdge(
                            run=source.reference,
                            source=edge.source,
                            target=edge.target,
                            relation=edge.relation,
                        )
                        connection.execute(
                            "INSERT INTO edges VALUES (?, ?)",
                            (key, _json(catalog_edge)),
                        )
                    for candidate in source.reuse_candidates:
                        _validate_reuse_candidate(source, candidate)
                        connection.execute(
                            "INSERT INTO stage_reuse_keys VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                stage_reuse_key_sha256(candidate.key),
                                key,
                                candidate.completed_at.isoformat(),
                                str(row.run_id),
                                candidate.attempt_id,
                                _json(candidate),
                            ),
                        )
                for source in benchmarks:
                    key = _reference_key(source.reference)
                    error = _benchmark_error(source, accepted_runs)
                    connection.execute(
                        "INSERT INTO sources VALUES (?, ?, ?, ?)",
                        (key, _json(source.reference), error is None, error),
                    )
                    if error is not None:
                        rejected += 1
                        continue
                    accepted += 1
                    result = source.verified.result
                    benchmark_id = source.verified.run.plan.run.benchmark_id
                    if benchmark_id is None:
                        raise ValueError("verified benchmark run has no benchmark ID")
                    benchmark = CatalogBenchmark(
                        result=source.reference,
                        run=result.run,
                        benchmark_id=benchmark_id,
                        status=result.status,
                        metrics=result.metrics,
                    )
                    connection.execute(
                        "INSERT INTO benchmarks VALUES (?, ?)",
                        (key, _json(benchmark)),
                    )
                heads = list(knowledge)
                local_head = self.root / ".viper/knowledge/head.json"
                if local_head.is_file():
                    heads.append(
                        TypeAdapter(ResolvedFileRef).validate_json(
                            local_head.read_bytes()
                        )
                    )
                for item in _knowledge_chain(self.root, tuple(heads)):
                    key = _reference_key(item.reference)
                    inserted = connection.execute(
                        "INSERT OR IGNORE INTO knowledge_records VALUES (?, ?, ?, ?)",
                        (
                            key,
                            _json(item.reference),
                            item.record.record_kind,
                            _json(item),
                        ),
                    ).rowcount
                    accepted += inserted
                    if isinstance(item.record.value, OntologySpec):
                        ontology = item.record.value
                        for primitive in ontology.primitives:
                            row = CatalogPrimitive(
                                ontology=item.reference,
                                primitive=PrimitiveRef(
                                    ontology_id=ontology.ontology_id,
                                    ontology_version=ontology.version,
                                    primitive_id=primitive.primitive_id,
                                ),
                                dimension=primitive.dimension,
                                label=primitive.label,
                            )
                            connection.execute(
                                "INSERT INTO knowledge_primitives VALUES (?, ?, ?)",
                                (key, str(primitive.primitive_id), _json(row)),
                            )
                connection.commit()
            finally:
                connection.close()
            with temporary_path.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary_path.unlink(missing_ok=True)
        return CatalogRefreshResult(
            database=self.path,
            sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
            accepted=accepted,
            rejected=rejected,
        )

    def _payloads(self, table: str, model: type[ItemT]) -> tuple[ItemT, ...]:
        """Load typed rows from one fixed catalog table."""
        statements = {
            "runs": "SELECT payload_json FROM runs",
            "artifacts": "SELECT payload_json FROM artifacts",
            "measurements": "SELECT payload_json FROM measurements",
            "benchmarks": "SELECT payload_json FROM benchmarks",
        }
        statement = statements.get(table)
        if statement is None:
            raise ValueError("unknown catalog table")
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(statement).fetchall()
        return tuple(model.model_validate_json(row[0]) for row in rows)

    def _run_context(self) -> dict[str, CatalogRun]:
        """Index catalog runs by immutable reference identity."""
        return {
            _reference_key(item.run): item
            for item in self._payloads("runs", CatalogRun)
        }

    def _run_digests(self, table: str) -> dict[str, set[str]]:
        """Load input or artifact file digests for each run."""
        statements = {
            "inputs": "SELECT source_key, sha256 FROM inputs",
            "files": "SELECT source_key, sha256 FROM files",
        }
        statement = statements.get(table)
        if statement is None:
            raise ValueError("unknown catalog digest table")
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(statement).fetchall()
        grouped: dict[str, set[str]] = {}
        for key, digest in rows:
            grouped.setdefault(key, set()).add(digest)
        return grouped

    @staticmethod
    def _page_values(
        query: BaseModel,
        values: tuple[ItemT, ...],
    ) -> tuple[tuple[ItemT, ...], str | None]:
        """Return one cursor-bound slice of already sorted results."""
        offset = _cursor_offset(query)
        limit = getattr(query, "limit")
        items = values[offset : offset + limit]
        next_offset = offset + len(items)
        cursor = _next_cursor(query, next_offset) if next_offset < len(values) else None
        return items, cursor

    def runs(self, query: RunQuery = RunQuery()) -> RunPage:
        """Return verified runs matching every exact filter."""
        inputs = self._run_digests("inputs")
        artifacts = self._run_digests("files")
        values = tuple(
            sorted(
                (
                    item
                    for item in self._payloads("runs", CatalogRun)
                    if (
                        query.experiment_id is None
                        or item.experiment_id == query.experiment_id
                    )
                    and (not query.variant_ids or item.variant_id in query.variant_ids)
                    and (
                        not query.replicate_ids
                        or item.replicate_id in query.replicate_ids
                    )
                    and (not query.statuses or item.status in query.statuses)
                    and (
                        query.source_commit is None
                        or item.source_commit == query.source_commit
                    )
                    and (
                        query.env_sha256 is None or item.env_sha256 == query.env_sha256
                    )
                    and (
                        query.reproducibility_sha256 is None
                        or item.reproducibility_sha256 == query.reproducibility_sha256
                    )
                    and (
                        query.benchmark_id is None
                        or item.benchmark_id == query.benchmark_id
                    )
                    and (
                        query.input_sha256 is None
                        or query.input_sha256
                        in inputs.get(_reference_key(item.run), set())
                    )
                    and (
                        query.artifact_sha256 is None
                        or query.artifact_sha256
                        in artifacts.get(_reference_key(item.run), set())
                    )
                ),
                key=lambda item: (item.completed_at, str(item.run_id)),
            )
        )
        items, cursor = self._page_values(query, values)
        return RunPage(items=items, next_cursor=cursor)

    def artifacts(self, query: ArtifactQuery = ArtifactQuery()) -> ArtifactPage:
        """Return verified artifacts matching every exact filter."""
        runs = self._run_context()
        values = tuple(
            sorted(
                (
                    item
                    for item in self._payloads("artifacts", CatalogArtifact)
                    if (
                        query.experiment_id is None
                        or runs[_reference_key(item.run)].experiment_id
                        == query.experiment_id
                    )
                    and (
                        not query.variant_ids
                        or runs[_reference_key(item.run)].variant_id
                        in query.variant_ids
                    )
                    and (not query.stage_ids or item.stage_id in query.stage_ids)
                    and (
                        not query.artifact_names
                        or item.artifact_name in query.artifact_names
                    )
                    and (not query.data_roles or item.data_role in query.data_roles)
                    and (
                        query.sha256 is None
                        or any(file.file.sha256 == query.sha256 for file in item.files)
                    )
                    and (
                        query.source_commit is None
                        or runs[_reference_key(item.run)].source_commit
                        == query.source_commit
                    )
                ),
                key=lambda item: (
                    str(item.run_id),
                    str(item.stage_id),
                    str(item.artifact_name),
                ),
            )
        )
        items, cursor = self._page_values(query, values)
        return ArtifactPage(items=items, next_cursor=cursor)

    def measurements(
        self,
        query: MeasurementQuery = MeasurementQuery(),
    ) -> MeasurementPage:
        """Return verified measurements matching every exact filter."""
        runs = self._run_context()
        inputs = self._run_digests("inputs")
        values = tuple(
            sorted(
                (
                    item
                    for item in self._payloads("measurements", CatalogMeasurement)
                    if (
                        query.experiment_id is None
                        or runs[_reference_key(item.run)].experiment_id
                        == query.experiment_id
                    )
                    and (
                        not query.variant_ids
                        or runs[_reference_key(item.run)].variant_id
                        in query.variant_ids
                    )
                    and (not query.stage_ids or item.stage_id in query.stage_ids)
                    and (not query.metric_ids or item.metric_id in query.metric_ids)
                    and (
                        query.input_sha256 is None
                        or query.input_sha256
                        in inputs.get(_reference_key(item.run), set())
                    )
                    and (
                        query.env_sha256 is None
                        or runs[_reference_key(item.run)].env_sha256 == query.env_sha256
                    )
                    and (query.minimum is None or item.value >= query.minimum)
                    and (query.maximum is None or item.value <= query.maximum)
                    and (not query.origins or item.origin in query.origins)
                ),
                key=lambda item: (
                    str(item.run_id),
                    str(item.stage_id),
                    str(item.metric_id),
                    item.epoch is None,
                    -1 if item.epoch is None else item.epoch,
                    item.step is None,
                    -1 if item.step is None else item.step,
                    item.measured_at,
                    _reference_key(item.measurement),
                ),
            )
        )
        items, cursor = self._page_values(query, values)
        return MeasurementPage(items=items, next_cursor=cursor)

    def benchmarks(
        self,
        query: BenchmarkQuery = BenchmarkQuery(),
    ) -> BenchmarkPage:
        """Return verified benchmark results matching every exact filter."""
        runs = self._run_context()
        inputs = self._run_digests("inputs")
        artifacts = self._run_digests("files")
        values = tuple(
            sorted(
                (
                    item
                    for item in self._payloads("benchmarks", CatalogBenchmark)
                    if (
                        query.experiment_id is None
                        or runs[_reference_key(item.run)].experiment_id
                        == query.experiment_id
                    )
                    and (
                        not query.variant_ids
                        or runs[_reference_key(item.run)].variant_id
                        in query.variant_ids
                    )
                    and (
                        not query.benchmark_ids
                        or item.benchmark_id in query.benchmark_ids
                    )
                    and (not query.statuses or item.status in query.statuses)
                    and (
                        not query.metric_ids
                        or any(
                            metric.metric_id in query.metric_ids
                            for metric in item.metrics
                        )
                    )
                    and (
                        query.source_commit is None
                        or runs[_reference_key(item.run)].source_commit
                        == query.source_commit
                    )
                    and (
                        query.env_sha256 is None
                        or runs[_reference_key(item.run)].env_sha256 == query.env_sha256
                    )
                    and (
                        query.input_sha256 is None
                        or query.input_sha256
                        in inputs.get(_reference_key(item.run), set())
                    )
                    and (
                        query.artifact_sha256 is None
                        or query.artifact_sha256
                        in artifacts.get(_reference_key(item.run), set())
                    )
                ),
                key=lambda item: (
                    str(item.benchmark_id),
                    str(runs[_reference_key(item.run)].run_id),
                    _reference_key(item.result),
                ),
            )
        )
        items, cursor = self._page_values(query, values)
        return BenchmarkPage(items=items, next_cursor=cursor)

    def lineage(self, run: ResolvedRunRef) -> RunLineage:
        """Return the stored lineage graph for one immutable run reference."""
        key = _reference_key(run)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT lineage_json FROM runs WHERE source_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise KeyError("run is absent from the catalog")
        return RunLineage.model_validate_json(row[0])

    def reuse_candidate(self, key: StageReuseKey) -> StageReuseCandidate | None:
        """Return the newest verified candidate for one exact reuse key."""
        if not self.path.is_file():
            return None
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM stage_reuse_keys
                    WHERE key_sha256 = ?
                    ORDER BY completed_at DESC, run_id DESC, attempt_id DESC
                    LIMIT 1
                    """,
                    (stage_reuse_key_sha256(key),),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        candidate = StageReuseCandidate.model_validate_json(row[0])
        if candidate.key != key:
            raise ValueError("catalog reuse-key digest collision")
        return candidate

    @property
    def knowledge(self) -> KnowledgeCatalog:
        """Open exact and similarity queries over indexed knowledge records."""
        return KnowledgeCatalog(self.path)


class KnowledgeCatalog:
    """Query the immutable knowledge projection with exact filters first."""

    def __init__(self, path: Path):
        """Bind queries to one catalog database."""
        self.path = path

    def _records(self) -> tuple[CatalogKnowledgeRecord, ...]:
        """Load every typed knowledge row in stable reference order."""
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM knowledge_records ORDER BY reference_key"
            ).fetchall()
        return tuple(CatalogKnowledgeRecord.model_validate_json(row[0]) for row in rows)

    def _index(self) -> dict[str, CatalogKnowledgeRecord]:
        """Index knowledge rows by immutable reference identity."""
        return {_reference_key(item.reference): item for item in self._records()}

    @staticmethod
    def _value(
        index: dict[str, CatalogKnowledgeRecord],
        reference: ResolvedFileRef,
    ) -> BaseModel:
        """Resolve one required knowledge reference from the current index."""
        item = index.get(_reference_key(reference))
        if item is None:
            raise ValueError("knowledge reference is absent from the catalog")
        return item.record.value

    @classmethod
    def _modulation_primitives(
        cls,
        index: dict[str, CatalogKnowledgeRecord],
        modulation: Modulation,
    ) -> set[str]:
        """Resolve primitive IDs named by one modulation's assignments."""
        identifiers: set[str] = set()
        assignment_types = (
            DeclaredPrimitiveAssignment,
            InferredPrimitiveAssignment,
            ReviewedPrimitiveAssignment,
        )
        for change in modulation.changes:
            for reference in (
                change.baseline_assignment,
                change.candidate_assignment,
            ):
                if reference is None:
                    continue
                assignment = cls._value(index, reference)
                if not isinstance(assignment, assignment_types):
                    raise ValueError("modulation reference is not an assignment")
                identifiers.add(str(assignment.primitive.primitive_id))
        return identifiers

    @staticmethod
    def _page(
        query: BaseModel,
        values: tuple[CatalogKnowledgeRecord, ...],
    ) -> KnowledgePage:
        """Return one cursor-bound page from stable records."""
        offset = _cursor_offset(query)
        limit = getattr(query, "limit")
        items = values[offset : offset + limit]
        next_offset = offset + len(items)
        cursor = _next_cursor(query, next_offset) if next_offset < len(values) else None
        return KnowledgePage(items=items, next_cursor=cursor)

    def primitives(self, query: PrimitiveQuery = PrimitiveQuery()) -> PrimitivePage:
        """Return ontology primitives matching every exact filter."""
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM knowledge_primitives"
            ).fetchall()
        primitives = tuple(
            CatalogPrimitive.model_validate_json(row[0]) for row in rows
        )
        values = tuple(
            sorted(
                (
                    item
                    for item in primitives
                    if (
                        query.ontology_id is None
                        or item.primitive.ontology_id == query.ontology_id
                    )
                ),
                key=lambda item: (
                    str(item.primitive.ontology_id),
                    str(item.primitive.ontology_version),
                    str(item.primitive.primitive_id),
                    _reference_key(item.ontology),
                ),
            )
        )
        values = tuple(
            item
            for item in values
            if (
                not query.ontology_versions
                or item.primitive.ontology_version in query.ontology_versions
            )
            and (not query.dimensions or item.dimension in query.dimensions)
            and (
                not query.primitive_ids
                or item.primitive.primitive_id in query.primitive_ids
            )
            and (not query.labels or item.label in query.labels)
        )
        offset = _cursor_offset(query)
        items = values[offset : offset + query.limit]
        next_offset = offset + len(items)
        cursor = _next_cursor(query, next_offset) if next_offset < len(values) else None
        return PrimitivePage(items=items, next_cursor=cursor)

    def assignments(self, query: AssignmentQuery = AssignmentQuery()) -> KnowledgePage:
        """Return primitive assignments matching exact provenance fields."""
        assignment_types = (
            DeclaredPrimitiveAssignment,
            InferredPrimitiveAssignment,
            ReviewedPrimitiveAssignment,
        )
        values = tuple(
            item
            for item in self._records()
            if isinstance(item.record.value, assignment_types)
            and (not query.origins or item.record.value.origin in query.origins)
            and (
                not query.primitive_ids
                or item.record.value.primitive.primitive_id in query.primitive_ids
            )
            and (query.run is None or item.record.value.target.run == query.run)
            and (
                not query.stage_ids
                or getattr(item.record.value.target, "stage_id", None)
                in query.stage_ids
            )
            and (
                not query.decisions
                or (
                    isinstance(item.record.value, ReviewedPrimitiveAssignment)
                    and item.record.value.decision in query.decisions
                )
            )
        )
        return self._page(query, values)

    def modulations(self, query: ModulationQuery = ModulationQuery()) -> KnowledgePage:
        """Return controlled comparisons matching exact run and context fields."""
        index = self._index()
        values = tuple(
            item
            for item in self._records()
            if isinstance(item.record.value, Modulation)
            and (
                not query.baseline_runs
                or item.record.value.baseline_run in query.baseline_runs
            )
            and (
                not query.candidate_runs
                or item.record.value.candidate_run in query.candidate_runs
            )
            and (
                not query.dimensions
                or set(query.dimensions)
                <= {change.dimension for change in item.record.value.changes}
            )
            and (
                query.context_sha256 is None
                or document_digest(item.record.value.context) == query.context_sha256
            )
            and (
                not query.primitive_ids
                or set(query.primitive_ids)
                <= self._modulation_primitives(index, item.record.value)
            )
        )
        return self._page(query, values)

    def effects(self, query: EffectQuery = EffectQuery()) -> KnowledgePage:
        """Return paired effects matching exact metric and value filters."""
        index = self._index()

        def effect_contexts(effect: EffectEstimate) -> set[str]:
            """Resolve context digests from every paired modulation."""
            contexts: set[str] = set()
            for pair in effect.pairs:
                modulation = self._value(index, pair.modulation)
                if not isinstance(modulation, Modulation):
                    raise ValueError("effect pair does not reference a modulation")
                contexts.add(document_digest(modulation.context))
            return contexts

        def effect_primitives(effect: EffectEstimate) -> set[str]:
            """Resolve primitive IDs from every paired modulation."""
            identifiers: set[str] = set()
            for pair in effect.pairs:
                modulation = self._value(index, pair.modulation)
                if not isinstance(modulation, Modulation):
                    raise ValueError("effect pair does not reference a modulation")
                identifiers.update(self._modulation_primitives(index, modulation))
            return identifiers

        values = tuple(
            item
            for item in self._records()
            if isinstance(item.record.value, EffectEstimate)
            and (
                not query.metric_ids
                or item.record.value.metric_id in query.metric_ids
            )
            and (
                not query.directions or item.record.value.direction in query.directions
            )
            and (
                query.minimum_improvement is None
                or item.record.value.mean_improvement >= query.minimum_improvement
            )
            and (
                query.maximum_improvement is None
                or item.record.value.mean_improvement <= query.maximum_improvement
            )
            and (
                query.context_sha256 is None
                or effect_contexts(item.record.value) == {query.context_sha256}
            )
            and (
                not query.primitive_ids
                or set(query.primitive_ids) <= effect_primitives(item.record.value)
            )
        )
        return self._page(query, values)

    def impacts(self, query: ImpactQuery = ImpactQuery()) -> KnowledgePage:
        """Return impact assessments matching exact qualitative labels."""
        index = self._index()

        def related(
            assessment: ImpactAssessment,
        ) -> tuple[EffectEstimate, ImpactPolicy]:
            """Resolve the effect and policy used by one assessment."""
            effect = self._value(index, assessment.effect)
            policy = self._value(index, assessment.policy)
            if not isinstance(effect, EffectEstimate) or not isinstance(
                policy, ImpactPolicy
            ):
                raise ValueError("impact references the wrong knowledge records")
            return effect, policy

        values = tuple(
            item
            for item in self._records()
            if isinstance(item.record.value, ImpactAssessment)
            and (not query.impacts or item.record.value.impact in query.impacts)
            and (
                not query.metric_ids
                or related(item.record.value)[0].metric_id in query.metric_ids
            )
            and (
                not query.policy_ids
                or related(item.record.value)[1].policy_id in query.policy_ids
            )
            and (
                query.context_sha256 is None
                or related(item.record.value)[1].context_sha256
                == query.context_sha256
            )
        )
        return self._page(query, values)

    def diagnostics(self, query: DiagnosticQuery = DiagnosticQuery()) -> KnowledgePage:
        """Return diagnostic signatures matching exact run and metric fields."""
        values = tuple(
            item
            for item in self._records()
            if isinstance(item.record.value, DiagnosticSignature)
            and (not query.runs or item.record.value.run in query.runs)
            and (not query.stage_ids or item.record.value.stage_id in query.stage_ids)
            and (
                not query.metric_ids
                or set(query.metric_ids)
                <= {part.metric_id for part in item.record.value.components}
            )
        )
        return self._page(query, values)

    def assertions(self, query: AssertionQuery = AssertionQuery()) -> KnowledgePage:
        """Return journal assertions matching exact review and evidence fields."""
        index = self._index()

        def primitives(assertion: JournalAssertion) -> set[str]:
            """Resolve primitive IDs from cited assignment evidence."""
            identifiers: set[str] = set()
            for evidence in assertion.evidence:
                if evidence.kind != "assignment":
                    continue
                assignment = self._value(index, evidence.reference)
                if isinstance(
                    assignment,
                    (
                        DeclaredPrimitiveAssignment,
                        InferredPrimitiveAssignment,
                        ReviewedPrimitiveAssignment,
                    ),
                ):
                    identifiers.add(str(assignment.primitive.primitive_id))
            return identifiers

        values = tuple(
            item
            for item in self._records()
            if isinstance(item.record.value, JournalAssertion)
            and (not query.kinds or item.record.value.kind in query.kinds)
            and (not query.statuses or item.record.value.status in query.statuses)
            and (
                not query.evidence_kinds
                or set(query.evidence_kinds)
                <= {evidence.kind for evidence in item.record.value.evidence}
            )
            and (
                not query.primitive_ids
                or set(query.primitive_ids) <= primitives(item.record.value)
            )
        )
        return self._page(query, values)

    def retrieval_judgments(
        self,
        query: RetrievalJudgmentQuery = RetrievalJudgmentQuery(),
    ) -> KnowledgePage:
        """Return reviewed vector judgments matching exact review fields."""
        index = self._index()
        values: list[CatalogKnowledgeRecord] = []
        for item in self._records():
            judgment = item.record.value
            if not isinstance(judgment, RetrievalJudgment):
                continue
            vector = index.get(_reference_key(judgment.query_vector))
            if vector is None or not isinstance(vector.record.value, KnowledgeVector):
                continue
            if (
                query.view_ids
                and vector.record.value.view.view_id not in query.view_ids
            ):
                continue
            if query.aspects and not set(query.aspects) <= set(judgment.aspects):
                continue
            if (
                query.minimum_relevance is not None
                and judgment.relevance < query.minimum_relevance
            ):
                continue
            if query.reviewers and judgment.reviewed_by not in query.reviewers:
                continue
            values.append(item)
        return self._page(query, tuple(values))

    def similar(self, query: SimilarityQuery) -> SimilarityPage:
        """Rank vectors by exact cosine distance inside one declared view."""
        index = self._index()
        matches: list[SimilarityMatch] = []
        query_norm = math.sqrt(sum(value * value for value in query.values))
        if query_norm == 0:
            raise ValueError("similarity query vector cannot be zero")
        for item in self._records():
            vector = item.record.value
            if not isinstance(vector, KnowledgeVector):
                continue
            if (
                vector.view.view_id != query.view_id
                or vector.view.version != query.view_version
            ):
                continue
            if len(vector.values) != len(query.values):
                raise ValueError("similarity query width differs from its view")
            source = index.get(_reference_key(vector.source))
            if source is None:
                raise ValueError("knowledge vector source is absent from the catalog")
            source_value = source.record.value
            if query.primitive_ids and not (
                isinstance(
                    source_value,
                    (
                        DeclaredPrimitiveAssignment,
                        InferredPrimitiveAssignment,
                        ReviewedPrimitiveAssignment,
                    ),
                )
                and source_value.primitive.primitive_id in query.primitive_ids
            ):
                continue
            if query.metric_ids and not (
                isinstance(source_value, DiagnosticSignature)
                and set(query.metric_ids)
                <= {part.metric_id for part in source_value.components}
            ):
                continue
            if query.assertion_statuses and not (
                isinstance(source_value, JournalAssertion)
                and source_value.status in query.assertion_statuses
            ):
                continue
            vector_norm = math.sqrt(sum(value * value for value in vector.values))
            if vector_norm == 0:
                raise ValueError("stored knowledge vector cannot be zero")
            similarity = sum(
                left * right for left, right in zip(query.values, vector.values)
            ) / (query_norm * vector_norm)
            distance = max(0.0, 1.0 - similarity)
            matches.append(
                SimilarityMatch(
                    source=source,
                    vector=item.reference,
                    distance=distance,
                )
            )
        matches.sort(key=lambda item: (item.distance, _reference_key(item.vector)))
        return SimilarityPage(items=tuple(matches[: query.limit]))


def catalog(*, root: Path | None = None) -> Catalog:
    """Open the derived catalog beneath one project root."""
    return Catalog(Path.cwd() if root is None else root)


__all__ = [
    "ArtifactPage",
    "ArtifactQuery",
    "BenchmarkPage",
    "BenchmarkQuery",
    "Catalog",
    "CatalogArtifact",
    "CatalogBenchmark",
    "CatalogBenchmarkSource",
    "CatalogEdge",
    "CatalogFile",
    "CatalogMeasurement",
    "CatalogRefreshResult",
    "CatalogRun",
    "CatalogRunSource",
    "KnowledgeCatalog",
    "MeasurementPage",
    "MeasurementQuery",
    "RunPage",
    "RunQuery",
    "catalog",
]
