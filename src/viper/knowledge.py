"""Define and publish evidence-backed experiment knowledge records."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ._schema import SHA256, ArtifactName, NonEmptyStr, ProtocolModel
from .ids import MetricId, StageId
from .references import (
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedRunRef,
)
from .serialization import parse_yaml_bytes, serialize_document
from .storage import (
    LocalArtifactStore,
    StorageDestination,
    load_storage_settings,
    publish_resolved_files,
)

PrimitiveId = Annotated[str, StringConstraints(min_length=1)]
OntologyId = Annotated[str, StringConstraints(min_length=1)]
OntologyVersion = Annotated[str, StringConstraints(min_length=1)]
AssertionId = Annotated[str, StringConstraints(min_length=1)]
VectorViewId = Annotated[str, StringConstraints(min_length=1)]


class PrimitiveRef(ProtocolModel):
    """Select one term from an exact ontology version."""

    ontology_id: OntologyId
    ontology_version: OntologyVersion
    primitive_id: PrimitiveId


class RunKnowledgeTarget(ProtocolModel):
    """Identify one immutable run."""

    kind: Literal["run"] = "run"
    run: ResolvedRunRef


class StageKnowledgeTarget(ProtocolModel):
    """Identify one stage inside an immutable run."""

    kind: Literal["stage"] = "stage"
    run: ResolvedRunRef
    stage_id: StageId


class ArtifactKnowledgeTarget(ProtocolModel):
    """Identify one artifact inside an immutable run."""

    kind: Literal["artifact"] = "artifact"
    run: ResolvedRunRef
    stage_id: StageId
    artifact_name: ArtifactName
    sha256: SHA256


class MeasurementKnowledgeTarget(ProtocolModel):
    """Identify one immutable measurement."""

    kind: Literal["measurement"] = "measurement"
    run: ResolvedRunRef
    stage_id: StageId
    metric_id: MetricId
    measurement: ResolvedFileRef


KnowledgeTarget = Annotated[
    RunKnowledgeTarget
    | StageKnowledgeTarget
    | ArtifactKnowledgeTarget
    | MeasurementKnowledgeTarget,
    Field(discriminator="kind"),
]


class PrimitiveSpec(ProtocolModel):
    """Define one term and its place in the ontology graph."""

    primitive_id: PrimitiveId
    dimension: NonEmptyStr
    label: NonEmptyStr
    definition: NonEmptyStr
    parents: tuple[PrimitiveId, ...] = ()
    examples: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        """Require stable parent and example order without duplicates."""
        if self.parents != tuple(sorted(set(self.parents))):
            raise ValueError("primitive parents must be unique and sorted")
        if self.examples != tuple(sorted(set(self.examples))):
            raise ValueError("primitive examples must be unique and sorted")
        return self


class OntologySpec(ProtocolModel):
    """Publish one complete acyclic ontology version."""

    schema_version: Literal[1] = 1
    ontology_id: OntologyId
    version: OntologyVersion
    primitives: tuple[PrimitiveSpec, ...] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        """Require one sorted definition per term and an acyclic parent graph."""
        identifiers = tuple(item.primitive_id for item in self.primitives)
        if identifiers != tuple(sorted(set(identifiers))):
            raise ValueError("ontology primitives must be unique and sorted")
        known = set(identifiers)
        if any(
            parent not in known for item in self.primitives for parent in item.parents
        ):
            raise ValueError("ontology parent is undefined")
        parents = {item.primitive_id: item.parents for item in self.primitives}

        def visit(node: PrimitiveId, path: frozenset[PrimitiveId]) -> None:
            if node in path:
                raise ValueError("ontology parents contain a cycle")
            for parent in parents[node]:
                visit(parent, path | {node})

        for identifier in identifiers:
            visit(identifier, frozenset())
        return self


class DeclaredPrimitiveAssignment(ProtocolModel):
    """Record a primitive assigned by an identified author."""

    origin: Literal["declared"] = "declared"
    target: KnowledgeTarget
    primitive: PrimitiveRef
    assigned_by: NonEmptyStr
    assigned_at: AwareDatetime


class InferredPrimitiveAssignment(ProtocolModel):
    """Record a primitive assigned by an immutable classifier."""

    origin: Literal["inferred"] = "inferred"
    target: KnowledgeTarget
    primitive: PrimitiveRef
    classifier: ResolvedArtifactPointerRef
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    assigned_at: AwareDatetime


class ReviewedPrimitiveAssignment(ProtocolModel):
    """Record a human decision about an earlier assignment."""

    origin: Literal["reviewed"] = "reviewed"
    source_assignment: ResolvedFileRef
    target: KnowledgeTarget
    primitive: PrimitiveRef
    decision: Literal["accepted", "corrected"]
    reviewed_by: NonEmptyStr
    reviewed_at: AwareDatetime


PrimitiveAssignment = Annotated[
    DeclaredPrimitiveAssignment
    | InferredPrimitiveAssignment
    | ReviewedPrimitiveAssignment,
    Field(discriminator="origin"),
]


class PrimitiveChange(ProtocolModel):
    """Identify the assignment transition in one ontology dimension."""

    dimension: NonEmptyStr
    baseline_assignment: ResolvedFileRef | None = None
    candidate_assignment: ResolvedFileRef | None = None

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        """Require an actual assignment addition, removal, or replacement."""
        if self.baseline_assignment is None and self.candidate_assignment is None:
            raise ValueError("primitive change requires an assignment")
        if self.baseline_assignment == self.candidate_assignment:
            raise ValueError("primitive change assignments must differ")
        return self


ComparisonField = Literal[
    "inputs",
    "split",
    "eval_spec",
    "env",
    "reproducibility",
    "compute",
]


class RunComparisonIdentity(ProtocolModel):
    """Store the exact fields that can be held constant between runs."""

    input_sha256: tuple[SHA256, ...] = Field(min_length=1)
    split_sha256: SHA256
    eval_spec_sha256: SHA256
    env_sha256: SHA256
    reproducibility_sha256: SHA256
    compute_sha256: SHA256


class ComparisonContext(ProtocolModel):
    """Declare which run identities a modulation holds constant."""

    baseline: RunComparisonIdentity
    candidate: RunComparisonIdentity
    matched: tuple[ComparisonField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_matches(self) -> Self:
        """Require every declared control to have the same exact value."""
        if self.matched != tuple(sorted(set(self.matched))):
            raise ValueError("matched fields must be unique and sorted")
        field_names = {
            "inputs": "input_sha256",
            "split": "split_sha256",
            "eval_spec": "eval_spec_sha256",
            "env": "env_sha256",
            "reproducibility": "reproducibility_sha256",
            "compute": "compute_sha256",
        }
        for field in self.matched:
            name = field_names[field]
            if getattr(self.baseline, name) != getattr(self.candidate, name):
                raise ValueError(f"matched comparison field differs: {field}")
        return self


class Modulation(ProtocolModel):
    """Compare two runs and enumerate their scientific changes."""

    schema_version: Literal[1] = 1
    baseline_run: ResolvedRunRef
    candidate_run: ResolvedRunRef
    changes: tuple[PrimitiveChange, ...] = Field(min_length=1)
    context: ComparisonContext
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        """Require one change per dimension in stable order."""
        dimensions = tuple(item.dimension for item in self.changes)
        if dimensions != tuple(sorted(set(dimensions))):
            raise ValueError("modulation changes must be unique and sorted")
        if self.baseline_run == self.candidate_run:
            raise ValueError("modulation runs must differ")
        return self


class PairedEffect(ProtocolModel):
    """Store one oriented measurement difference for a run pair."""

    modulation: ResolvedFileRef
    baseline_measurement: ResolvedFileRef
    candidate_measurement: ResolvedFileRef
    baseline_value: float = Field(allow_inf_nan=False)
    candidate_value: float = Field(allow_inf_nan=False)
    improvement: float = Field(allow_inf_nan=False)


class EffectEstimate(ProtocolModel):
    """Store a descriptive estimate across matched run pairs."""

    schema_version: Literal[1] = 1
    metric_id: MetricId
    direction: Literal["min", "max"]
    pairs: tuple[PairedEffect, ...] = Field(min_length=1)
    mean_improvement: float = Field(allow_inf_nan=False)
    standard_error: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0)
    interval_low: float | None = Field(default=None, allow_inf_nan=False)
    interval_high: float | None = Field(default=None, allow_inf_nan=False)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        """Require stored improvements and their mean to match the pair values."""
        sign = 1.0 if self.direction == "max" else -1.0
        expected = tuple(
            sign * (pair.candidate_value - pair.baseline_value) for pair in self.pairs
        )
        if any(
            abs(pair.improvement - value) > 1e-12
            for pair, value in zip(self.pairs, expected)
        ):
            raise ValueError("paired improvement does not match its measurements")
        if abs(self.mean_improvement - sum(expected) / len(expected)) > 1e-12:
            raise ValueError("mean improvement does not match its pairs")
        interval = (self.interval_low, self.interval_high)
        if len(self.pairs) == 1 and (
            self.standard_error is not None or interval != (None, None)
        ):
            raise ValueError("one pair cannot report an interval")
        if len(self.pairs) > 1 and (self.standard_error is None or None in interval):
            raise ValueError("several pairs require an interval")
        return self


class ImpactPolicy(ProtocolModel):
    """Define reproducible thresholds for one qualitative impact label."""

    schema_version: Literal[1] = 1
    policy_id: NonEmptyStr
    version: NonEmptyStr
    metric_id: MetricId
    context_sha256: SHA256
    minimum_pairs: int = Field(ge=2)
    maximum_interval_width: float = Field(gt=0.0, allow_inf_nan=False)
    low_threshold: float = Field(gt=0.0, allow_inf_nan=False)
    medium_threshold: float = Field(gt=0.0, allow_inf_nan=False)
    high_threshold: float = Field(gt=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        """Require increasing low, medium, and high thresholds."""
        if not self.low_threshold < self.medium_threshold < self.high_threshold:
            raise ValueError("impact thresholds must increase")
        return self


class ImpactAssessment(ProtocolModel):
    """Apply one immutable policy to one immutable effect estimate."""

    schema_version: Literal[1] = 1
    effect: ResolvedFileRef
    policy: ResolvedFileRef
    impact: Literal["negative", "none", "low", "medium", "high"]
    assessed_at: AwareDatetime


class DiagnosticComponent(ProtocolModel):
    """Bind one metric value to its immutable measurement."""

    metric_id: MetricId
    measurement: ResolvedFileRef
    value: float = Field(allow_inf_nan=False)


def diagnostic_component_sha256(components: tuple[DiagnosticComponent, ...]) -> str:
    """Hash one ordered diagnostic component tuple."""
    payload = [component.model_dump(mode="json") for component in components]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class DiagnosticSignature(ProtocolModel):
    """Store a deterministic metric signature for one stage."""

    schema_version: Literal[1] = 1
    run: ResolvedRunRef
    stage_id: StageId
    components: tuple[DiagnosticComponent, ...] = Field(min_length=1)
    component_sha256: SHA256
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_components(self) -> Self:
        """Require stable component order and the exact component digest."""
        keys = tuple(
            (str(item.metric_id), item.measurement.sha256) for item in self.components
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("diagnostic components must be unique and sorted")
        if self.component_sha256 != diagnostic_component_sha256(self.components):
            raise ValueError("diagnostic component digest differs")
        return self


JournalEvidenceKind = Literal[
    "run",
    "artifact",
    "measurement",
    "benchmark",
    "assignment",
    "modulation",
    "effect",
    "impact",
    "diagnostic",
    "retrieval_judgment",
]


class JournalEvidence(ProtocolModel):
    """Cite one immutable record supporting a journal assertion."""

    kind: JournalEvidenceKind
    reference: ResolvedFileRef


class JournalAssertion(ProtocolModel):
    """State one bounded claim and its immutable evidence."""

    schema_version: Literal[1] = 1
    assertion_id: AssertionId
    kind: Literal["observation", "hypothesis", "decision", "exclusion"]
    text: NonEmptyStr
    evidence: tuple[JournalEvidence, ...] = Field(min_length=1)
    status: Literal["proposed", "reviewed", "rejected"]
    authored_by: NonEmptyStr
    created_at: AwareDatetime
    reviewed_by: NonEmptyStr | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        """Keep review identity and exclusion evidence consistent with status."""
        reviewed = self.reviewed_by is not None and self.reviewed_at is not None
        if (self.reviewed_by is None) != (self.reviewed_at is None):
            raise ValueError("journal review fields must appear together")
        if self.status == "proposed" and reviewed:
            raise ValueError("proposed journal assertion cannot be reviewed")
        if self.status != "proposed" and not reviewed:
            raise ValueError("terminal journal assertion requires a reviewer")
        if self.kind == "exclusion" and not any(
            item.kind in {"effect", "impact"} for item in self.evidence
        ):
            raise ValueError("exclusion requires effect or impact evidence")
        return self


class DiagnosticVectorView(ProtocolModel):
    """Define one ordered diagnostic vector space."""

    kind: Literal["diagnostic"] = "diagnostic"
    view_id: VectorViewId
    version: NonEmptyStr
    metric_ids: tuple[MetricId, ...] = Field(min_length=1)
    dimensions: int = Field(ge=1)
    distance: Literal["cosine"] = "cosine"

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        """Require one stable metric order matching the vector width."""
        if self.metric_ids != tuple(sorted(set(self.metric_ids))):
            raise ValueError("diagnostic metrics must be unique and sorted")
        if len(self.metric_ids) != self.dimensions:
            raise ValueError("diagnostic metric count differs from dimensions")
        return self


class JournalVectorView(ProtocolModel):
    """Define one journal embedding space and its immutable embedder."""

    kind: Literal["journal"] = "journal"
    view_id: VectorViewId
    version: NonEmptyStr
    embedder: ResolvedArtifactPointerRef
    dimensions: int = Field(ge=1)
    distance: Literal["cosine"] = "cosine"


VectorViewSpec = Annotated[
    DiagnosticVectorView | JournalVectorView,
    Field(discriminator="kind"),
]


class KnowledgeVector(ProtocolModel):
    """Bind finite values to one source record and vector view."""

    schema_version: Literal[1] = 1
    view: VectorViewSpec
    source: ResolvedFileRef
    values: tuple[float, ...] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """Require the exact declared width and finite values."""
        if len(self.values) != self.view.dimensions:
            raise ValueError("vector width differs from its view")
        if not all(math.isfinite(value) for value in self.values):
            raise ValueError("vector values must be finite")
        return self


RetrievalAspect = Literal["primitive", "diagnostic", "journal", "outcome"]


class RetrievalJudgment(ProtocolModel):
    """Store one reviewed relevance judgment between two vectors."""

    schema_version: Literal[1] = 1
    query_vector: ResolvedFileRef
    candidate_vector: ResolvedFileRef
    aspects: tuple[RetrievalAspect, ...] = Field(min_length=1)
    relevance: int = Field(ge=0, le=3)
    reviewed_by: NonEmptyStr
    reviewed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_judgment(self) -> Self:
        """Reject self-comparisons and unstable aspect order."""
        if self.query_vector == self.candidate_vector:
            raise ValueError("retrieval judgment vectors must differ")
        if self.aspects != tuple(sorted(set(self.aspects))):
            raise ValueError("retrieval aspects must be unique and sorted")
        return self


KnowledgeRecordKind = Literal[
    "ontology",
    "assignment",
    "modulation",
    "effect",
    "impact_policy",
    "impact",
    "diagnostic",
    "assertion",
    "vector",
    "retrieval_judgment",
]
KnowledgeRecord = (
    OntologySpec
    | DeclaredPrimitiveAssignment
    | InferredPrimitiveAssignment
    | ReviewedPrimitiveAssignment
    | Modulation
    | EffectEstimate
    | ImpactPolicy
    | ImpactAssessment
    | DiagnosticSignature
    | JournalAssertion
    | KnowledgeVector
    | RetrievalJudgment
)

_RECORD_TYPES: dict[KnowledgeRecordKind, type[ProtocolModel]] = {
    "ontology": OntologySpec,
    "assignment": DeclaredPrimitiveAssignment,
    "modulation": Modulation,
    "effect": EffectEstimate,
    "impact_policy": ImpactPolicy,
    "impact": ImpactAssessment,
    "diagnostic": DiagnosticSignature,
    "assertion": JournalAssertion,
    "vector": KnowledgeVector,
    "retrieval_judgment": RetrievalJudgment,
}


class KnowledgeRecordEnvelope(ProtocolModel):
    """Pair each record with the discriminator stored on disk."""

    schema_version: Literal[1] = 1
    record_kind: KnowledgeRecordKind
    value: KnowledgeRecord

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        """Require the discriminator to name the concrete record type."""
        if self.record_kind == "assignment":
            valid = isinstance(
                self.value,
                (
                    DeclaredPrimitiveAssignment,
                    InferredPrimitiveAssignment,
                    ReviewedPrimitiveAssignment,
                ),
            )
        else:
            valid = isinstance(self.value, _RECORD_TYPES[self.record_kind])
        if not valid:
            raise ValueError("knowledge record kind differs from its value")
        return self


class KnowledgeManifest(ProtocolModel):
    """Link one published record to the preceding knowledge manifest."""

    schema_version: Literal[1] = 1
    record: ResolvedFileRef
    previous: ResolvedFileRef | None = None
    published_at: AwareDatetime


class KnowledgePublicationResult(BaseModel):
    """Return the immutable record and manifest references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedFileRef
    manifest: ResolvedFileRef


class PrimitiveQuery(BaseModel):
    """Filter ontology primitives by exact fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology_id: OntologyId | None = None
    ontology_versions: tuple[OntologyVersion, ...] = ()
    dimensions: tuple[NonEmptyStr, ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    labels: tuple[NonEmptyStr, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class AssignmentQuery(BaseModel):
    """Filter primitive assignments by exact provenance fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: ResolvedRunRef | None = None
    stage_ids: tuple[StageId, ...] = ()
    origins: tuple[Literal["declared", "inferred", "reviewed"], ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    decisions: tuple[Literal["accepted", "corrected"], ...] = ()
    effective_only: bool = False
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class ModulationQuery(BaseModel):
    """Filter controlled run comparisons by exact identities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_runs: tuple[ResolvedRunRef, ...] = ()
    candidate_runs: tuple[ResolvedRunRef, ...] = ()
    dimensions: tuple[NonEmptyStr, ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    context_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class EffectQuery(BaseModel):
    """Filter paired effect estimates by exact metric and context fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_ids: tuple[MetricId, ...] = ()
    directions: tuple[Literal["min", "max"], ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    context_sha256: SHA256 | None = None
    minimum_improvement: float | None = Field(default=None, allow_inf_nan=False)
    maximum_improvement: float | None = Field(default=None, allow_inf_nan=False)
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class ImpactQuery(BaseModel):
    """Filter qualitative impact assessments by exact fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_ids: tuple[MetricId, ...] = ()
    impacts: tuple[Literal["negative", "none", "low", "medium", "high"], ...] = ()
    policy_ids: tuple[NonEmptyStr, ...] = ()
    context_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class DiagnosticQuery(BaseModel):
    """Filter diagnostic signatures by run, stage, or metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: tuple[ResolvedRunRef, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class AssertionQuery(BaseModel):
    """Filter journal assertions by review and evidence fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kinds: tuple[
        Literal["observation", "hypothesis", "decision", "exclusion"], ...
    ] = ()
    statuses: tuple[Literal["proposed", "reviewed", "rejected"], ...] = ()
    evidence_kinds: tuple[JournalEvidenceKind, ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class RetrievalJudgmentQuery(BaseModel):
    """Filter reviewed retrieval judgments by exact review fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    view_ids: tuple[VectorViewId, ...] = ()
    aspects: tuple[RetrievalAspect, ...] = ()
    minimum_relevance: int | None = Field(default=None, ge=0, le=3)
    reviewers: tuple[NonEmptyStr, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class SimilarityQuery(BaseModel):
    """Rank vectors inside one exact view after exact filters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    view_id: VectorViewId
    view_version: NonEmptyStr
    values: tuple[float, ...] = Field(min_length=1)
    primitive_ids: tuple[PrimitiveId, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    assertion_statuses: tuple[
        Literal["proposed", "reviewed", "rejected"], ...
    ] = ()
    limit: int = Field(default=20, ge=1, le=500)

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """Reject non-finite query vectors."""
        if not all(math.isfinite(value) for value in self.values):
            raise ValueError("similarity values must be finite")
        return self


class CatalogPrimitive(BaseModel):
    """Return one primitive with its immutable ontology reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology: ResolvedFileRef
    primitive: PrimitiveRef
    dimension: NonEmptyStr
    label: NonEmptyStr


class CatalogKnowledgeRecord(BaseModel):
    """Return one immutable reference and its parsed knowledge record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: ResolvedFileRef
    record: KnowledgeRecordEnvelope


class SimilarityMatch(BaseModel):
    """Return one exact-distance vector match and its source record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: CatalogKnowledgeRecord
    vector: ResolvedFileRef
    distance: float = Field(ge=0.0, allow_inf_nan=False)


class PrimitivePage(BaseModel):
    """Return one deterministic page of ontology primitives."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[CatalogPrimitive, ...]
    next_cursor: str | None = None


class KnowledgePage(BaseModel):
    """Return one deterministic page of knowledge records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[CatalogKnowledgeRecord, ...]
    next_cursor: str | None = None


class SimilarityPage(BaseModel):
    """Return one bounded exact-distance result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[SimilarityMatch, ...]


@contextmanager
def _repository_lock(root: Path) -> Iterator[None]:
    """Reject concurrent knowledge-head writers with one exclusive lock file."""
    path = root / ".viper/knowledge/head.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise RuntimeError("knowledge head is locked by another publisher") from error
    os.close(descriptor)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


class KnowledgeStore:
    """Publish knowledge records and one immutable manifest chain."""

    def __init__(self, root: Path, destination: StorageDestination):
        """Bind publication to one root and storage destination."""
        self.root = root.resolve(strict=True)
        self.destination = destination
        self.head = self.root / ".viper/knowledge/head.json"

    def _previous(self) -> ResolvedFileRef | None:
        """Load the current manifest reference when a head exists."""
        if not self.head.is_file():
            return None
        return TypeAdapter(ResolvedFileRef).validate_json(self.head.read_bytes())

    def _record(self, reference: ResolvedFileRef) -> KnowledgeRecordEnvelope:
        """Load and verify one locally published knowledge record."""
        if not isinstance(reference.stored_at, LocalFileRef):
            raise ValueError("knowledge verification currently requires local files")
        raw = LocalArtifactStore(self.root, reference.stored_at.store).fetch(
            reference.stored_at
        )
        if len(raw) != reference.bytes:
            raise ValueError("knowledge record byte count differs")
        if hashlib.sha256(raw).hexdigest() != reference.sha256:
            raise ValueError("knowledge record digest differs")
        return KnowledgeRecordEnvelope.model_validate(parse_yaml_bytes(raw))

    def _replace_head(self, reference: ResolvedFileRef) -> None:
        """Atomically replace the local discovery pointer."""
        self.head.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            dir=self.head.parent,
            prefix=".head.",
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(reference.model_dump_json().encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.head)
        finally:
            temporary.unlink(missing_ok=True)

    def _publish(
        self,
        kind: KnowledgeRecordKind,
        value: KnowledgeRecord,
        published_at: AwareDatetime,
    ) -> KnowledgePublicationResult:
        """Publish one record, append its manifest, and advance the head."""
        envelope = KnowledgeRecordEnvelope(record_kind=kind, value=value)
        raw = serialize_document(envelope)
        record_path = f"knowledge/records/{hashlib.sha256(raw).hexdigest()}.yaml"
        with _repository_lock(self.root):
            record = publish_resolved_files(
                self.root,
                self.destination,
                {record_path: raw},
            )[record_path]
            manifest = KnowledgeManifest(
                record=record,
                previous=self._previous(),
                published_at=published_at,
            )
            manifest_raw = serialize_document(manifest)
            manifest_path = (
                f"knowledge/manifests/{hashlib.sha256(manifest_raw).hexdigest()}.yaml"
            )
            manifest_ref = publish_resolved_files(
                self.root,
                self.destination,
                {manifest_path: manifest_raw},
            )[manifest_path]
            self._replace_head(manifest_ref)
        return KnowledgePublicationResult(record=record, manifest=manifest_ref)

    def publish_ontology(self, value: OntologySpec) -> KnowledgePublicationResult:
        """Publish one ontology version."""
        return self._publish("ontology", value, value.created_at)

    def publish_assignment(
        self, value: PrimitiveAssignment
    ) -> KnowledgePublicationResult:
        """Publish one declared, inferred, or reviewed assignment."""
        timestamp = (
            value.reviewed_at
            if isinstance(value, ReviewedPrimitiveAssignment)
            else value.assigned_at
        )
        return self._publish("assignment", value, timestamp)

    def publish_modulation(self, value: Modulation) -> KnowledgePublicationResult:
        """Publish one controlled run comparison."""
        return self._publish("modulation", value, value.created_at)

    def publish_effect(self, value: EffectEstimate) -> KnowledgePublicationResult:
        """Publish one paired effect estimate."""
        return self._publish("effect", value, value.created_at)

    def publish_impact_policy(
        self, value: ImpactPolicy, *, published_at: AwareDatetime
    ) -> KnowledgePublicationResult:
        """Publish one qualitative impact policy."""
        return self._publish("impact_policy", value, published_at)

    def publish_impact(self, value: ImpactAssessment) -> KnowledgePublicationResult:
        """Publish one policy-backed impact assessment."""
        return self._publish("impact", value, value.assessed_at)

    def publish_signature(
        self, value: DiagnosticSignature
    ) -> KnowledgePublicationResult:
        """Publish one deterministic diagnostic signature."""
        return self._publish("diagnostic", value, value.created_at)

    def publish_assertion(self, value: JournalAssertion) -> KnowledgePublicationResult:
        """Publish one evidence-backed journal assertion."""
        return self._publish("assertion", value, value.created_at)

    def publish_vector(self, value: KnowledgeVector) -> KnowledgePublicationResult:
        """Publish one vector without changing its source record."""
        source = self._record(value.source).value
        expected = (
            DiagnosticSignature
            if isinstance(value.view, DiagnosticVectorView)
            else JournalAssertion
        )
        if not isinstance(source, expected):
            raise ValueError("knowledge vector source differs from its view")
        return self._publish("vector", value, value.created_at)

    def publish_retrieval_judgment(
        self,
        value: RetrievalJudgment,
    ) -> KnowledgePublicationResult:
        """Publish one reviewed retrieval judgment."""
        query = self._record(value.query_vector).value
        candidate = self._record(value.candidate_vector).value
        if not isinstance(query, KnowledgeVector) or not isinstance(
            candidate, KnowledgeVector
        ):
            raise ValueError("retrieval judgment requires vector records")
        if query.view != candidate.view:
            raise ValueError("retrieval judgment vector views differ")
        return self._publish("retrieval_judgment", value, value.reviewed_at)


def knowledge(
    *,
    root: Path | None = None,
    destination: StorageDestination | None = None,
) -> KnowledgeStore:
    """Open the knowledge store for one repository."""
    project_root = Path.cwd().resolve() if root is None else root.resolve(strict=True)
    selected = destination or load_storage_settings(project_root).destination
    return KnowledgeStore(project_root, selected)


__all__ = [
    "ArtifactKnowledgeTarget",
    "AssertionQuery",
    "AssertionId",
    "AssignmentQuery",
    "CatalogKnowledgeRecord",
    "CatalogPrimitive",
    "ComparisonContext",
    "ComparisonField",
    "DeclaredPrimitiveAssignment",
    "DiagnosticComponent",
    "DiagnosticQuery",
    "DiagnosticSignature",
    "DiagnosticVectorView",
    "EffectQuery",
    "EffectEstimate",
    "ImpactAssessment",
    "ImpactQuery",
    "ImpactPolicy",
    "InferredPrimitiveAssignment",
    "JournalAssertion",
    "JournalEvidence",
    "JournalEvidenceKind",
    "JournalVectorView",
    "KnowledgeManifest",
    "KnowledgePage",
    "KnowledgePublicationResult",
    "KnowledgeRecord",
    "KnowledgeRecordEnvelope",
    "KnowledgeRecordKind",
    "KnowledgeStore",
    "KnowledgeTarget",
    "KnowledgeVector",
    "MeasurementKnowledgeTarget",
    "Modulation",
    "ModulationQuery",
    "OntologyId",
    "OntologySpec",
    "OntologyVersion",
    "PairedEffect",
    "PrimitiveAssignment",
    "PrimitiveChange",
    "PrimitiveId",
    "PrimitivePage",
    "PrimitiveQuery",
    "PrimitiveRef",
    "PrimitiveSpec",
    "RetrievalAspect",
    "RetrievalJudgment",
    "RetrievalJudgmentQuery",
    "ReviewedPrimitiveAssignment",
    "RunComparisonIdentity",
    "RunKnowledgeTarget",
    "SimilarityMatch",
    "SimilarityPage",
    "SimilarityQuery",
    "StageKnowledgeTarget",
    "VectorViewId",
    "VectorViewSpec",
    "diagnostic_component_sha256",
    "knowledge",
]
