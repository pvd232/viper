# Experiment knowledge primitives

VIPER records exact runs. This contract adds the scientific labels and
comparisons needed to search those runs as experiments. It preserves the run
records as evidence. The new records state what a run tested, what changed,
what happened, and which evidence supports a written conclusion.

## 1. Status

**Contract status:** complete; Master Phases 16 and 17 implemented.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| EKP-01 <!-- contract-requirement: EKP-01 phase=16 test=tests/test_protocol.py --> | Define a versioned primitive ontology and declared, inferred, and reviewed assignment records. |
| EKP-02 <!-- contract-requirement: EKP-02 phase=16 test=tests/test_verification_acceptance.py --> | Record controlled modulations, paired effects, impact assessments, diagnostic signatures, and evidence-backed journal assertions as immutable files. |
| EKP-03 <!-- contract-requirement: EKP-03 phase=17 test=tests/test_inspection.py --> | Add vector views, vectors, retrieval judgments, exact graph and filter indexes, and one optional HNSW index for each declared vector view. |
| EKP-04 <!-- contract-requirement: EKP-04 phase=17 test=tests/test_api.py --> | Expose the same knowledge publication and search operations through Python, typed API, CLI, and MCP. |

## 2. Required claim

VIPER can answer a scientific query only when it can return the immutable runs,
measurements, assignments, comparisons, or journal records behind the answer.

The first implementation supports this path:

```text
verified runs and benchmark results
-> versioned primitive assignments
-> controlled run pairs
-> recomputed effect estimates and diagnostic signatures
-> reviewed journal assertions
-> exact graph and field filters
-> optional similarity ranking inside one named vector view
```

Exact run identity and explicit equivalence rules decide whether two
experiments duplicate each other. Similarity search only ranks candidates for
review.

## 3. Current gap

The provenance catalog can find runs by exact fields. The missing records must
represent these claims:

```text
this model uses a gated recurrent functional family
this run changed only the regularization family
this change improved test loss across four matched replicates
this diagnostic pattern preceded divergence
this journal conclusion is supported by these measurements
```

Free text supplies prose while leaving versioned terms, typed evidence links,
and deterministic recomputation unresolved. A vector index supplies a ranking.
Identity, provenance, and experimental effects require exact records.

### Current DAG

```mermaid
flowchart LR
    Runs["verified experiments"] --> Text["journal prose"]
    Runs --> Metrics["metrics + diagnostics"]
    Text --> Vector["semantic vector"]
    Metrics --> Gap["no shared primitive or modulation identity"]
    Vector --> Gap
    class Runs,Text,Metrics,Vector current
    class Gap gap
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Proposed-change DAG

```mermaid
flowchart LR
    Ontology["versioned primitives"] --> Assignment["PrimitiveAssignment"]
    Runs["matched runs"] --> Modulation["Modulation"]
    Assignment --> Modulation
    Modulation --> Effect["EffectEstimate"]
    Runs --> Diagnostic["DiagnosticSignature"]
    Runs --> Journal["JournalAssertion"]
    class Ontology,Assignment,Runs,Modulation,Effect,Diagnostic,Journal proposed
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Integrated DAG

```mermaid
flowchart LR
    Evidence["verified VIPER evidence"] --> Knowledge["typed knowledge records"]
    Knowledge --> Exact["ontology + graph filters"]
    Knowledge --> Views["journal, diagnostic, effect vectors"]
    Exact --> Rank["evidence-aware ranking"]
    Views --> Rank
    Rank --> Result["source-linked research memory"]
    class Evidence contract
    class Knowledge,Exact,Views,Rank implementation
    class Result output
    classDef contract fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef output fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

## 4. Stable identifiers and targets

The ontology defines the allowed scientific terms. A knowledge target identifies
the exact VIPER evidence being labeled.

```python
PrimitiveId = Annotated[str, StringConstraints(min_length=1)]
OntologyId = Annotated[str, StringConstraints(min_length=1)]
OntologyVersion = Annotated[str, StringConstraints(min_length=1)]
AssertionId = Annotated[str, StringConstraints(min_length=1)]
VectorViewId = Annotated[str, StringConstraints(min_length=1)]


class PrimitiveRef(ProtocolModel):
    ontology_id: OntologyId
    ontology_version: OntologyVersion
    primitive_id: PrimitiveId


class RunKnowledgeTarget(ProtocolModel):
    kind: Literal["run"] = "run"
    run: ResolvedRunRef


class StageKnowledgeTarget(ProtocolModel):
    kind: Literal["stage"] = "stage"
    run: ResolvedRunRef
    stage_id: StageId


class ArtifactKnowledgeTarget(ProtocolModel):
    kind: Literal["artifact"] = "artifact"
    run: ResolvedRunRef
    stage_id: StageId
    artifact_name: ArtifactName
    sha256: SHA256


class MeasurementKnowledgeTarget(ProtocolModel):
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
```

Every target contains an immutable reference. A stage, artifact, or measurement
target also contains the key needed to find that entity inside the verified
run.

## 5. Versioned ontology

```python
class PrimitiveSpec(ProtocolModel):
    primitive_id: PrimitiveId
    dimension: NonEmptyStr
    label: NonEmptyStr
    definition: NonEmptyStr
    parents: tuple[PrimitiveId, ...] = ()
    examples: tuple[NonEmptyStr, ...] = ()


class OntologySpec(ProtocolModel):
    schema_version: Literal[1] = 1
    ontology_id: OntologyId
    version: OntologyVersion
    primitives: tuple[PrimitiveSpec, ...] = Field(min_length=1)
    created_at: AwareDatetime
```

Primitive IDs are unique within one ontology version. Every parent must exist
in that same version. The parent graph must be acyclic. A published ontology
version is immutable. A correction creates another version.

The first vocabulary covers these dimensions:

```text
model functional family
embedding topology
attention or recurrence topology
loss-term functional family
optimizer family
regularization family
data transformation family
sampling strategy
training schedule
parameter initialization
inference strategy
compute and precision regime
```

New ontology versions can add terms while retaining the protocol schema.

## 6. Primitive assignments

The assignment union keeps authored facts, classifier output, and human review
separate.

```python
class DeclaredPrimitiveAssignment(ProtocolModel):
    origin: Literal["declared"] = "declared"
    target: KnowledgeTarget
    primitive: PrimitiveRef
    assigned_by: NonEmptyStr
    assigned_at: AwareDatetime


class InferredPrimitiveAssignment(ProtocolModel):
    origin: Literal["inferred"] = "inferred"
    target: KnowledgeTarget
    primitive: PrimitiveRef
    classifier: ResolvedArtifactPointerRef
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    assigned_at: AwareDatetime


class ReviewedPrimitiveAssignment(ProtocolModel):
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
```

A reviewed correction keeps the original inferred assignment. Queries can ask
for declared, inferred, reviewed, or effective labels. An effective label uses
the newest valid review when one exists, then a declared assignment, then an
inferred assignment. Equal timestamps break ties by immutable reference.

## 7. Controlled modulation and paired effects

A modulation compares two verified runs and names every scientific primitive
that changed.

```python
class PrimitiveChange(ProtocolModel):
    dimension: NonEmptyStr
    baseline_assignment: ResolvedFileRef | None = None
    candidate_assignment: ResolvedFileRef | None = None


ComparisonField = Literal[
    "inputs",
    "split",
    "eval_spec",
    "env",
    "reproducibility",
    "compute",
]


class RunComparisonIdentity(ProtocolModel):
    input_sha256: tuple[SHA256, ...] = Field(min_length=1)
    split_sha256: SHA256
    eval_spec_sha256: SHA256
    env_sha256: SHA256
    reproducibility_sha256: SHA256
    compute_sha256: SHA256


class ComparisonContext(ProtocolModel):
    baseline: RunComparisonIdentity
    candidate: RunComparisonIdentity
    matched: tuple[ComparisonField, ...] = Field(min_length=1)


class Modulation(ProtocolModel):
    schema_version: Literal[1] = 1
    baseline_run: ResolvedRunRef
    candidate_run: ResolvedRunRef
    changes: tuple[PrimitiveChange, ...] = Field(min_length=1)
    context: ComparisonContext
    created_at: AwareDatetime


class PairedEffect(ProtocolModel):
    modulation: ResolvedFileRef
    baseline_measurement: ResolvedFileRef
    candidate_measurement: ResolvedFileRef
    baseline_value: float = Field(allow_inf_nan=False)
    candidate_value: float = Field(allow_inf_nan=False)
    improvement: float = Field(allow_inf_nan=False)


class EffectEstimate(ProtocolModel):
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
```

`PrimitiveChange` requires at least one assignment and rejects equal assignment
references. The verifier loads each assignment, checks its ontology dimension,
and requires its target to belong to the corresponding baseline or candidate
run. This preserves the exact assignment history used to define the change.
Changes sort by dimension.

`ComparisonContext.matched` names the fields held constant. The verifier
requires equal baseline and candidate values for each one. A compute-regime
modulation can omit `"compute"` from `matched` and preserve the two compute
identities. Every run pair in one estimate must use the same primitive changes
and matched-field set. The effect query groups pairs by the exact values in the
fields selected as controls.

VIPER orients each pair so a positive number means improvement. For pair
`i`, let `b_i` be the baseline measurement and `c_i` the candidate
measurement. Let `s=1` for a metric that should increase and `s=-1` for a
metric that should decrease.

```math
d_i = s(c_i - b_i)
```

For `n` pairs, the reported mean is:

```math
\bar d = \frac{1}{n}\sum_{i=1}^{n} d_i
```

For `n >= 2`, VIPER records the sample standard error and a two-sided normal
interval:

```math
SE(\bar d) = \sqrt{\frac{1}{n(n-1)}\sum_{i=1}^{n}(d_i-\bar d)^2}
```

```math
[\bar d-z_{1-\alpha/2}SE(\bar d),\ \bar d+z_{1-\alpha/2}SE(\bar d)]
```

Here, `alpha = 1 - confidence`, and `z` is the standard-normal quantile. One
pair stores `None` for its standard error and interval. This record is a
descriptive paired estimate. A causal claim requires a separate identification
argument.

### Qualitative impact

High, medium, and low labels come from a published policy for one metric and
comparison scope.

```python
class ImpactPolicy(ProtocolModel):
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


class ImpactAssessment(ProtocolModel):
    schema_version: Literal[1] = 1
    effect: ResolvedFileRef
    policy: ResolvedFileRef
    impact: Literal["negative", "none", "low", "medium", "high"]
    assessed_at: AwareDatetime
```

`context_sha256` covers the ordered matched-field names and their shared
values. Thresholds must satisfy `low < medium < high`. The verifier loads the
effect and policy, checks the context digest, pair count, and interval width,
and recomputes the label:

```text
interval_high < 0
-> negative

interval contains zero or mean_improvement < low_threshold
-> none

low_threshold <= mean_improvement < medium_threshold
-> low

medium_threshold <= mean_improvement < high_threshold
-> medium

mean_improvement >= high_threshold
-> high
```

An estimate must have an interval. It must meet the policy's pair count and
maximum interval width before VIPER publishes an assessment.

## 8. Diagnostic signatures

A diagnostic signature is a deterministic ordered view of measurements from
one stage.

```python
class DiagnosticComponent(ProtocolModel):
    metric_id: MetricId
    measurement: ResolvedFileRef
    value: float = Field(allow_inf_nan=False)


class DiagnosticSignature(ProtocolModel):
    schema_version: Literal[1] = 1
    run: ResolvedRunRef
    stage_id: StageId
    components: tuple[DiagnosticComponent, ...] = Field(min_length=1)
    component_sha256: SHA256
    created_at: AwareDatetime
```

Components sort by metric ID and immutable measurement reference. The digest
covers the canonical component tuple. Verification loads each `Measurement`,
checks its run, stage, metric ID, and value, then recomputes the digest.

## 9. Journal assertions

A journal entry states one bounded claim and cites the evidence that supports
it.

```python
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
    kind: JournalEvidenceKind
    reference: ResolvedFileRef


class JournalAssertion(ProtocolModel):
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
```

`status="reviewed"` and `status="rejected"` require both review fields.
`status="proposed"` rejects them. An exclusion assertion must cite at least one
effect estimate or impact assessment. Verification loads every evidence
reference and checks that its stored record matches `kind`.

The journal text remains separate from its embedding. A new embedding model
creates a new vector while preserving the assertion and its review status.

## 10. Vector views and derived indexes

Each vector belongs to one declared view. Diagnostic values and journal text
use separate views.

```python
class DiagnosticVectorView(ProtocolModel):
    kind: Literal["diagnostic"] = "diagnostic"
    view_id: VectorViewId
    version: NonEmptyStr
    metric_ids: tuple[MetricId, ...] = Field(min_length=1)
    dimensions: int = Field(ge=1)
    distance: Literal["cosine"] = "cosine"


class JournalVectorView(ProtocolModel):
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
    schema_version: Literal[1] = 1
    view: VectorViewSpec
    source: ResolvedFileRef
    values: tuple[float, ...] = Field(min_length=1)
    created_at: AwareDatetime


RetrievalAspect = Literal["primitive", "diagnostic", "journal", "outcome"]


class RetrievalJudgment(ProtocolModel):
    schema_version: Literal[1] = 1
    query_vector: ResolvedFileRef
    candidate_vector: ResolvedFileRef
    aspects: tuple[RetrievalAspect, ...] = Field(min_length=1)
    relevance: int = Field(ge=0, le=3)
    reviewed_by: NonEmptyStr
    reviewed_at: AwareDatetime
```

Master Phase 17 defines `VectorViewSpec` and `KnowledgeVector` before it defines
`RetrievalJudgment`. The judgment consumes two published vector references, so
its verifier can load both vectors and compare their view identity.

`values` must contain exactly `view.dimensions` finite values. A diagnostic
view requires the same ordered metric IDs as its source signature. A journal
view requires a `JournalAssertion` source and records the exact embedder in the
view.

`RetrievalJudgment` loads both `KnowledgeVector` records and requires the same
view ID, version, and digest. Relevance uses a four-point reviewed scale:

```text
0 -> irrelevant
1 -> related but unhelpful
2 -> useful supporting context
3 -> directly answers the retrieval need
```

The aspects state which view of the experiment justified that score. These
records supply held-out retrieval judgments before any learned representation
enters the framework.

The catalog stores exact fields and graph edges in SQLite. It stores an
optional HNSW index for each `(view_id, version, view digest)` under:

```text
.viper/knowledge/<view-sha256>/hnsw.bin
```

These files are derived. The verified `KnowledgeVector` records retain the
evidence needed to rebuild them after deletion.

Similarity search follows this order:

```text
exact experiment, ontology, context, and review-status filters
-> select one vector view
-> HNSW candidate search when that view has an index
-> exact distance calculation over returned candidates
-> stable distance and immutable-reference ordering
```

Small filtered sets use exhaustive distance calculation. HNSW accelerates
larger sets as an approximate nearest-neighbor index. Exact duplicate rejection
uses run identity, primitive identity, or a reviewed equivalence rule. HNSW
distance only ranks candidates.

### Exact query models

```python
class PrimitiveQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology_id: OntologyId | None = None
    ontology_versions: tuple[OntologyVersion, ...] = ()
    dimensions: tuple[NonEmptyStr, ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    labels: tuple[NonEmptyStr, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class AssignmentQuery(BaseModel):
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
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_runs: tuple[ResolvedRunRef, ...] = ()
    candidate_runs: tuple[ResolvedRunRef, ...] = ()
    dimensions: tuple[NonEmptyStr, ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    context_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class EffectQuery(BaseModel):
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
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_ids: tuple[MetricId, ...] = ()
    impacts: tuple[Literal["negative", "none", "low", "medium", "high"], ...] = ()
    policy_ids: tuple[NonEmptyStr, ...] = ()
    context_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class DiagnosticQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: tuple[ResolvedRunRef, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class AssertionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kinds: tuple[Literal["observation", "hypothesis", "decision", "exclusion"], ...] = ()
    statuses: tuple[Literal["proposed", "reviewed", "rejected"], ...] = ()
    evidence_kinds: tuple[JournalEvidenceKind, ...] = ()
    primitive_ids: tuple[PrimitiveId, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class RetrievalJudgmentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    view_ids: tuple[VectorViewId, ...] = ()
    aspects: tuple[RetrievalAspect, ...] = ()
    minimum_relevance: int | None = Field(default=None, ge=0, le=3)
    reviewers: tuple[NonEmptyStr, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class SimilarityQuery(BaseModel):
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


class CatalogPrimitive(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology: ResolvedFileRef
    primitive: PrimitiveRef
    dimension: NonEmptyStr
    label: NonEmptyStr


class CatalogKnowledgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: ResolvedFileRef
    record: KnowledgeRecordEnvelope


class SimilarityMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: CatalogKnowledgeRecord
    vector: ResolvedFileRef
    distance: float = Field(ge=0.0, allow_inf_nan=False)


class PrimitivePage(BaseModel):
    items: tuple[CatalogPrimitive, ...]
    next_cursor: str | None = None


class KnowledgePage(BaseModel):
    items: tuple[CatalogKnowledgeRecord, ...]
    next_cursor: str | None = None


class SimilarityPage(BaseModel):
    items: tuple[SimilarityMatch, ...]
```

Every exact page sorts by its complete typed key, then immutable reference.
Its opaque cursor binds the query and final sort key. `SimilarityPage` returns
one bounded result and omits pagination.

```python
class KnowledgeCatalog:
    def primitives(self, query: PrimitiveQuery = PrimitiveQuery()) -> PrimitivePage: ...
    def assignments(self, query: AssignmentQuery = AssignmentQuery()) -> KnowledgePage: ...
    def modulations(self, query: ModulationQuery = ModulationQuery()) -> KnowledgePage: ...
    def effects(self, query: EffectQuery = EffectQuery()) -> KnowledgePage: ...
    def impacts(self, query: ImpactQuery = ImpactQuery()) -> KnowledgePage: ...
    def diagnostics(self, query: DiagnosticQuery = DiagnosticQuery()) -> KnowledgePage: ...
    def assertions(self, query: AssertionQuery = AssertionQuery()) -> KnowledgePage: ...
    def retrieval_judgments(
        self,
        query: RetrievalJudgmentQuery = RetrievalJudgmentQuery(),
    ) -> KnowledgePage: ...
    def similar(self, query: SimilarityQuery) -> SimilarityPage: ...


# Phase 16 extends the existing Catalog.refresh() method with knowledge heads.
def refresh(
    self,
    *,
    runs: tuple[CatalogRunSource, ...] = (),
    benchmarks: tuple[CatalogBenchmarkSource, ...] = (),
    knowledge: tuple[ResolvedFileRef, ...] = (),
) -> CatalogRefreshResult: ...


# Phase 17 adds this property to Catalog.
@property
def knowledge(self) -> KnowledgeCatalog: ...
```

## 11. Publication, verification, and authority

| Rule | Executable condition |
| --- | --- |
| `knowledge.ontology.complete` <!-- verifier-rule: knowledge.ontology.complete requirement=EKP-01 --> | Ontology versions and declared, inferred, and reviewed primitive assignments preserve exact provenance. |
| `knowledge.evidence.complete` <!-- verifier-rule: knowledge.evidence.complete requirement=EKP-02 --> | Modulations, effects, impact assessments, diagnostic signatures, and journal assertions publish as immutable evidence. |
| `knowledge.retrieval.complete` <!-- verifier-rule: knowledge.retrieval.complete requirement=EKP-03 --> | Exact filters and graph indexes remain authoritative while each vector view uses its declared optional HNSW index. |
| `knowledge.public.complete` <!-- verifier-rule: knowledge.public.complete requirement=EKP-04 --> | Python, typed API, CLI, and MCP expose the same knowledge publication and search operations. |

Knowledge records are standalone immutable files. They use the destination
already bound for the current project:

```text
protocol model
-> canonical JSON bytes
-> publish_resolved_files()
-> ResolvedFileRef
-> catalog refresh
-> exact rows, graph edges, and optional vector index
```

The local catalog and HNSW files remain rebuildable projections. Evidence
references point to immutable protocol records.

```python
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
    | PrimitiveAssignment
    | Modulation
    | EffectEstimate
    | ImpactPolicy
    | ImpactAssessment
    | DiagnosticSignature
    | JournalAssertion
    | KnowledgeVector
    | RetrievalJudgment
)


class KnowledgeRecordEnvelope(ProtocolModel):
    schema_version: Literal[1] = 1
    record_kind: KnowledgeRecordKind
    value: KnowledgeRecord


class KnowledgeManifest(ProtocolModel):
    schema_version: Literal[1] = 1
    record: ResolvedFileRef
    previous: ResolvedFileRef | None = None
    published_at: AwareDatetime


class KnowledgePublicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedFileRef
    manifest: ResolvedFileRef


class KnowledgeStore:
    def publish_ontology(self, value: OntologySpec) -> KnowledgePublicationResult: ...
    def publish_assignment(self, value: PrimitiveAssignment) -> KnowledgePublicationResult: ...
    def publish_modulation(self, value: Modulation) -> KnowledgePublicationResult: ...
    def publish_effect(self, value: EffectEstimate) -> KnowledgePublicationResult: ...
    def publish_impact_policy(self, value: ImpactPolicy) -> KnowledgePublicationResult: ...
    def publish_impact(self, value: ImpactAssessment) -> KnowledgePublicationResult: ...
    def publish_signature(self, value: DiagnosticSignature) -> KnowledgePublicationResult: ...
    def publish_assertion(self, value: JournalAssertion) -> KnowledgePublicationResult: ...
    def publish_vector(self, value: KnowledgeVector) -> KnowledgePublicationResult: ...
    def publish_retrieval_judgment(
        self,
        value: RetrievalJudgment,
    ) -> KnowledgePublicationResult: ...


def knowledge(
    *,
    root: Path | None = None,
    destination: StorageDestination | None = None,
) -> KnowledgeStore: ...
```

Master Phase 16 first implements `KnowledgeRecordKind`, `KnowledgeRecord`, and
`KnowledgeStore` through `JournalAssertion`. Master Phase 17 extends those three
owners with `KnowledgeVector`, `RetrievalJudgment`, `publish_vector()`, and
`publish_retrieval_judgment()` after both vector models exist. The code above
shows the complete target API after both phases.

`destination=None` loads the repository's current `StorageSettings`. An
explicit destination overrides that setting for this store. Every published
reference contains its own local or cloud location, so a later configuration
change leaves old records retrievable. Cross-run knowledge records use the
store destination independently because they belong to several runs.

Every successful publication writes the record, then writes one immutable
`KnowledgeManifest` whose `previous` field points to the prior manifest. The
record bytes contain `KnowledgeRecordEnvelope`; its validator requires the
declared `record_kind` to match the concrete `value` type. VIPER
atomically replaces this local discovery pointer after both writes succeed:

```text
.viper/knowledge/head.json
```

The head file contains the newest manifest's `ResolvedFileRef`. A repository
lock serializes head updates. A crash before the head replacement can leave an
unreachable immutable file. Readers keep the prior complete head. A later
garbage collector may remove the unreachable file after its grace period.

`KnowledgePublicationResult.record` is the reference used by assignments,
modulations, effects, and journals. `manifest` is the portable starting point
for catalog discovery. Every publish method validates referenced records
before writing. Failed validation publishes nothing.

The Phase 16 `Catalog.refresh(knowledge=...)` extension follows the local head
and any supplied manifest heads.

Refresh walks each manifest chain to its first record, rejects a cycle or an
invalid envelope, and deduplicates records by immutable reference. Catalog
results include the validated envelope beside its reference. A remote user can
pass the manifest returned by
`KnowledgePublicationResult` even when this checkout lacks the original local
head.

Python reads use `KnowledgeCatalog` and the exact query models above. The typed
API and CLI expose matching publication and search operations.

MCP read mode adds these tools in name order:

```text
search_assertions
search_assignments
search_diagnostics
search_effects
search_impacts
search_modulations
search_primitives
search_retrieval_judgments
search_similar
```

MCP execute mode adds:

```text
knowledge_refresh
publish_assertion
publish_assignment
publish_diagnostic
publish_effect
publish_impact
publish_impact_policy
publish_modulation
publish_ontology
publish_retrieval_judgment
publish_vector
```

## 12. Acceptance cases
<!-- contract-worked-example: start -->

```python
from datetime import UTC, datetime


created_at = datetime.now(UTC)
primitive = PrimitiveSpec(
    primitive_id="loss.focal",
    dimension="loss-term functional family",
    label="Focal loss",
    definition="Cross-entropy weighted toward hard examples.",
    parents=("loss.classification",),
    examples=("gamma=2",),
)
ontology = OntologySpec(
    ontology_id="viper.ml",
    version="1",
    primitives=(classification_loss, primitive),
    created_at=created_at,
)
primitive_ref = PrimitiveRef(
    ontology_id=ontology.ontology_id,
    ontology_version=ontology.version,
    primitive_id=primitive.primitive_id,
)
target = RunKnowledgeTarget(run=verified_candidate_run)
assignment = DeclaredPrimitiveAssignment(
    target=target,
    primitive=primitive_ref,
    assigned_by="experiment-author",
    assigned_at=created_at,
)

assert assignment.primitive.primitive_id == "loss.focal"
assert assignment.target.run == verified_candidate_run
```

### Ontology and assignment history

Publish two ontology versions, one inferred assignment, and one reviewed
correction. Effective-label search returns the correction. Historical search
returns all records with their original immutable references. A missing parent,
parent cycle, unknown primitive, or review of the wrong record type fails.

### Paired effect verification

Four matched run pairs produce four measurements. VIPER rebuilds every
oriented improvement, mean, standard error, and interval. Changing one
measurement reference, value, direction, context, or stored estimate causes
verification failure.

### Qualitative impact

One effect passes a published policy's pair-count and interval-width rules.
VIPER recomputes its impact label. A threshold-order error, context mismatch,
insufficient pair count, wide interval, or changed label fails.

### Diagnostic signature

The same verified measurements in different input order produce the same
component order and digest. A measurement from another stage or a changed
component value fails verification.

### Journal evidence

A reviewed observation cites one effect and one diagnostic signature. Search
returns the assertion and both source records. A missing reference, wrong
evidence kind, review-field mismatch, or unsupported exclusion fails.

### Manifest discovery and recovery

Two processes publish under the repository lock. The second manifest points to
the first. Catalog refresh from the local head finds both records. Refresh from
the second manifest supplied explicitly returns the same records after the
local head is removed. A cycle, missing prior manifest, non-knowledge record,
or interrupted publication before head replacement fails closed. The prior
head remains readable.

### Exact and vector search

Exact filters run before similarity search. Two HNSW rebuilds over the same
fixture return the same exact filtered set. Final candidates sort by exact
distance and immutable reference. The test records recall against exhaustive
search for the fixed fixture. That measurement applies to the fixture and
declared index settings.

### Reviewed retrieval judgment

One reviewer scores four candidates against a query vector. The verifier
requires one vector view and valid references. Exact search returns the scores
in candidate-reference order. A mixed view, changed score, unknown vector, or
duplicate aspect fails.

### Surface equality

Python, typed API, CLI, and MCP calls return the same ordered references for
one exact query and one vector query. Read-only MCP omits publication and
refresh tools. Execute mode routes them through the same typed handlers.

<!-- contract-worked-example: end -->

## 13. Propagation

| Surface | Required change |
| --- | --- |
| `src/viper/knowledge.py` | Add every ontology, assignment, modulation, effect, impact, diagnostic, journal, vector, retrieval-judgment, and publication model. |
| `src/viper/catalog.py` | Add verified knowledge rows, graph edges, exact queries, vector-view metadata, and HNSW rebuilds. |
| `src/viper/verification/__init__.py` | Dispatch ontology, assignment, comparison, impact, signature, assertion, vector, and retrieval-judgment verification. |
| `src/viper/api.py` | Add typed publication and search request and success models. |
| `src/viper/api.py` | Route knowledge operations through `KnowledgeStore` and `Catalog`. |
| `src/viper/cli.py` | Add `knowledge publish`, `knowledge search`, and `knowledge refresh` commands. |
| `src/viper/mcp.py` | Add read searches and execute-only publication and refresh tools from the typed operation registry. |
| `src/viper/__init__.py` | Export `knowledge` and the public protocol and query models. |
| `pyproject.toml` | Add a compatible optional HNSW dependency group; retain exact search in the base installation. |
| `tests/test_protocol.py` | Cover exact fields, unions, validators, canonical ordering, and JSON round trips. |
| `tests/test_verification_acceptance.py` | Sever every immutable reference and recomputed relationship. |
| `tests/test_inspection.py` | Cover graph extraction, exact filters, rebuild equality, vector views, ordering, and fixed-fixture recall. |
| `tests/test_api.py` | Compare Python, typed API, CLI, and MCP request and result schemas. |
| Public documentation | Explain the evidence layers, controlled comparison limits, and exact-versus-similarity boundary. |

## 14. Legacy cleanup

[`research-memory-roadmap.md`](research-memory-roadmap.md) stops describing the
whole research-memory system as deferred. It points to this contract for the
active deterministic foundation.

Current protocol records remain. The implementation removes any new code that
stores scientific labels only in catalog rows or journals only as untyped text.
Every vector carries its source record and view identity.

## 15. Implementation order

1. Add ontology, targets, and assignment models.
2. Add modulation, paired effect, impact, diagnostic, and journal models.
3. Add canonical publication and verification through `JournalAssertion`.
4. Extend catalog refresh with exact non-vector rows and graph edges.
5. Add vector views and `KnowledgeVector`, then extend publication and
   verification for vectors.
6. Add `RetrievalJudgment` after `KnowledgeVector`, then extend publication,
   verification, and exact retrieval-judgment queries.
7. Add exhaustive exact-distance search.
8. Add one optional HNSW index per view and fixed-fixture recall tests.
9. Add Python, typed API, CLI, and MCP publication and search surfaces.
10. Run the terminal generated-project and full-system gate.

## 16. Research boundary

This contract produces the reviewed scientific labels, effects, diagnostics,
assertions, vectors, and retrieval judgments consumed by
[`Research Memory and Agent Learning`](research-memory-roadmap.md). That
contract owns the decision episode, training dataset, learning update,
evaluation, promotion, and rollback records for:

- primitive classifiers;
- aspect-aware or multi-view representations;
- context-conditioned outcome models;
- experiment-acquisition policies; or
- continual-learning policies from agent traces.

Each model must name its immutable `LearningDatasetManifest`, ontology version,
frozen `AgentEvaluationPlan`, acceptance metrics, retention suite, and review
policy. A reviewed `JournalAssertion` can label an episode, but it does not
substitute for the complete `ResearchEpisode` or `LearningExample` records.

## 17. Research basis

[HNSW](https://arxiv.org/abs/1603.09320) supplies the approximate vector-index
structure. VIPER keeps it behind exact filters and exact final distance
calculation because the index is a search aid.

[USearch](https://pypi.org/project/usearch/) supplies maintained Python wheels
for the optional HNSW accelerator. Exact search remains the base installation.

[Agent Workflow Memory](https://proceedings.mlr.press/v267/wang25bx.html)
shows how reusable procedures can be extracted from prior trajectories. VIPER
adds immutable run and measurement references to each reviewed assertion.

[ResearchGym](https://arxiv.org/abs/2602.15112) evaluates agents on executable
research tasks with objective outcomes. Its broad reliability gap supports
building reviewed evidence records before training a research policy.

[PerTurboAgent](https://proceedings.mlr.press/v311/hao25b.html) provides a
narrow example of iterative experiment selection informed by analysis and
retrieved knowledge. VIPER first records the controlled comparisons and
reviewed decisions needed to evaluate such selection in another domain.

## 18. Phase 16 executable plan

<!-- pair-block-definition: P16-EKP-01 -->
```toml pair-block
id = "P16-EKP-01"
requirements = ["EKP-01", "EKP-02"]
targets = [
    "src/viper/knowledge.py:annotations",
    "src/viper/knowledge.py:hashlib",
    "src/viper/knowledge.py:json",
    "src/viper/knowledge.py:os",
    "src/viper/knowledge.py:tempfile",
    "src/viper/knowledge.py:Iterator",
    "src/viper/knowledge.py:contextmanager",
    "src/viper/knowledge.py:Path",
    "src/viper/knowledge.py:Annotated",
    "src/viper/knowledge.py:Literal",
    "src/viper/knowledge.py:Self",
    "src/viper/knowledge.py:AwareDatetime",
    "src/viper/knowledge.py:BaseModel",
    "src/viper/knowledge.py:ConfigDict",
    "src/viper/knowledge.py:Field",
    "src/viper/knowledge.py:StringConstraints",
    "src/viper/knowledge.py:TypeAdapter",
    "src/viper/knowledge.py:model_validator",
    "src/viper/knowledge.py:SHA256",
    "src/viper/knowledge.py:ArtifactName",
    "src/viper/knowledge.py:NonEmptyStr",
    "src/viper/knowledge.py:ProtocolModel",
    "src/viper/knowledge.py:MetricId",
    "src/viper/knowledge.py:StageId",
    "src/viper/knowledge.py:ResolvedArtifactPointerRef",
    "src/viper/knowledge.py:ResolvedFileRef",
    "src/viper/knowledge.py:ResolvedRunRef",
    "src/viper/knowledge.py:serialize_document",
    "src/viper/knowledge.py:StorageDestination",
    "src/viper/knowledge.py:load_storage_settings",
    "src/viper/knowledge.py:publish_resolved_files",
    "src/viper/knowledge.py:PrimitiveId",
    "src/viper/knowledge.py:OntologyId",
    "src/viper/knowledge.py:OntologyVersion",
    "src/viper/knowledge.py:AssertionId",
    "src/viper/knowledge.py:PrimitiveRef",
    "src/viper/knowledge.py:RunKnowledgeTarget",
    "src/viper/knowledge.py:StageKnowledgeTarget",
    "src/viper/knowledge.py:ArtifactKnowledgeTarget",
    "src/viper/knowledge.py:MeasurementKnowledgeTarget",
    "src/viper/knowledge.py:KnowledgeTarget",
    "src/viper/knowledge.py:PrimitiveSpec",
    "src/viper/knowledge.py:OntologySpec",
    "src/viper/knowledge.py:DeclaredPrimitiveAssignment",
    "src/viper/knowledge.py:InferredPrimitiveAssignment",
    "src/viper/knowledge.py:ReviewedPrimitiveAssignment",
    "src/viper/knowledge.py:PrimitiveAssignment",
    "src/viper/knowledge.py:PrimitiveChange",
    "src/viper/knowledge.py:ComparisonField",
    "src/viper/knowledge.py:RunComparisonIdentity",
    "src/viper/knowledge.py:ComparisonContext",
    "src/viper/knowledge.py:Modulation",
    "src/viper/knowledge.py:PairedEffect",
    "src/viper/knowledge.py:EffectEstimate",
    "src/viper/knowledge.py:ImpactPolicy",
    "src/viper/knowledge.py:ImpactAssessment",
    "src/viper/knowledge.py:DiagnosticComponent",
    "src/viper/knowledge.py:diagnostic_component_sha256",
    "src/viper/knowledge.py:DiagnosticSignature",
    "src/viper/knowledge.py:JournalEvidenceKind",
    "src/viper/knowledge.py:JournalEvidence",
    "src/viper/knowledge.py:JournalAssertion",
    "src/viper/knowledge.py:KnowledgeRecordKind",
    "src/viper/knowledge.py:KnowledgeRecord",
    "src/viper/knowledge.py:_RECORD_TYPES",
    "src/viper/knowledge.py:KnowledgeRecordEnvelope",
    "src/viper/knowledge.py:KnowledgeManifest",
    "src/viper/knowledge.py:KnowledgePublicationResult",
    "src/viper/knowledge.py:_repository_lock",
    "src/viper/knowledge.py:KnowledgeStore",
    "src/viper/knowledge.py:knowledge",
    "src/viper/knowledge.py:__all__",
    "tests/test_protocol.py:UTC",
    "tests/test_protocol.py:datetime",
    "tests/test_protocol.py:DeclaredPrimitiveAssignment",
    "tests/test_protocol.py:OntologySpec",
    "tests/test_protocol.py:PrimitiveRef",
    "tests/test_protocol.py:PrimitiveSpec",
    "tests/test_protocol.py:RunKnowledgeTarget",
    "tests/test_protocol.py:LocalFileRef",
    "tests/test_protocol.py:ResolvedRunRef",
    "tests/test_protocol.py:SnapshotFileRef",
    "tests/test_protocol.py:test_knowledge_ontology_preserves_assignment_provenance",
    "tests/test_verification_acceptance.py:DeclaredPrimitiveAssignment",
    "tests/test_verification_acceptance.py:KnowledgeManifest",
    "tests/test_verification_acceptance.py:KnowledgeRecordEnvelope",
    "tests/test_verification_acceptance.py:OntologySpec",
    "tests/test_verification_acceptance.py:PrimitiveRef",
    "tests/test_verification_acceptance.py:PrimitiveSpec",
    "tests/test_verification_acceptance.py:RunKnowledgeTarget",
    "tests/test_verification_acceptance.py:knowledge",
    "tests/test_verification_acceptance.py:document_digest",
    "tests/test_verification_acceptance.py:parse_yaml_bytes",
    "tests/test_verification_acceptance.py:LocalArtifactStore",
    "tests/test_verification_acceptance.py:test_knowledge_records_preserve_immutable_evidence",
]
tests = [
    "tests/test_protocol.py:test_knowledge_ontology_preserves_assignment_provenance",
    "tests/test_verification_acceptance.py:test_knowledge_records_preserve_immutable_evidence",
]
gate = "python -m pytest tests/test_protocol.py::test_knowledge_ontology_preserves_assignment_provenance tests/test_verification_acceptance.py::test_knowledge_records_preserve_immutable_evidence -q"
depends_on = ["P15-PCM-01"]
```

**Context:** Phase 16 defines the immutable scientific evidence records and one
repository-bound publication chain. The block keeps ontology assignments tied
to exact run references and advances the local knowledge head only after both
the record and its manifest have been published.

## 19. Phase 16 ContractTargets

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:annotations -->
```python contract-target
from __future__ import annotations
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:hashlib -->
```python contract-target
import hashlib
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:json -->
```python contract-target
import json
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:os -->
```python contract-target
import os
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:tempfile -->
```python contract-target
import tempfile
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Iterator -->
```python contract-target
from collections.abc import Iterator
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:contextmanager -->
```python contract-target
from contextlib import contextmanager
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Path -->
```python contract-target
from pathlib import Path
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Annotated -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Literal -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Self -->
```python contract-target
from typing import Annotated, Literal, Self
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:AwareDatetime -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:BaseModel -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ConfigDict -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Field -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:StringConstraints -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:TypeAdapter -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:model_validator -->
```python contract-target
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:SHA256 -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ArtifactName -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:NonEmptyStr -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ProtocolModel -->
```python contract-target
from ._schema import SHA256, ArtifactName, NonEmptyStr, ProtocolModel
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:MetricId -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:StageId -->
```python contract-target
from .ids import MetricId, StageId
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ResolvedArtifactPointerRef -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ResolvedFileRef -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ResolvedRunRef -->
```python contract-target
from .references import (
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedRunRef,
)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:serialize_document -->
```python contract-target
from .serialization import serialize_document
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:StorageDestination -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:load_storage_settings -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:publish_resolved_files -->
```python contract-target
from .storage import (
    StorageDestination,
    load_storage_settings,
    publish_resolved_files,
)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:PrimitiveId -->
```python contract-target
PrimitiveId = Annotated[str, StringConstraints(min_length=1)]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:OntologyId -->
```python contract-target
OntologyId = Annotated[str, StringConstraints(min_length=1)]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:OntologyVersion -->
```python contract-target
OntologyVersion = Annotated[str, StringConstraints(min_length=1)]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:AssertionId -->
```python contract-target
AssertionId = Annotated[str, StringConstraints(min_length=1)]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:PrimitiveRef -->
```python contract-target
class PrimitiveRef(ProtocolModel):
    """Select one term from an exact ontology version."""

    ontology_id: OntologyId
    ontology_version: OntologyVersion
    primitive_id: PrimitiveId
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:RunKnowledgeTarget -->
```python contract-target
class RunKnowledgeTarget(ProtocolModel):
    """Identify one immutable run."""

    kind: Literal["run"] = "run"
    run: ResolvedRunRef
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:StageKnowledgeTarget -->
```python contract-target
class StageKnowledgeTarget(ProtocolModel):
    """Identify one stage inside an immutable run."""

    kind: Literal["stage"] = "stage"
    run: ResolvedRunRef
    stage_id: StageId
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ArtifactKnowledgeTarget -->
```python contract-target
class ArtifactKnowledgeTarget(ProtocolModel):
    """Identify one artifact inside an immutable run."""

    kind: Literal["artifact"] = "artifact"
    run: ResolvedRunRef
    stage_id: StageId
    artifact_name: ArtifactName
    sha256: SHA256
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:MeasurementKnowledgeTarget -->
```python contract-target
class MeasurementKnowledgeTarget(ProtocolModel):
    """Identify one immutable measurement."""

    kind: Literal["measurement"] = "measurement"
    run: ResolvedRunRef
    stage_id: StageId
    metric_id: MetricId
    measurement: ResolvedFileRef
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeTarget -->
```python contract-target
KnowledgeTarget = Annotated[
    RunKnowledgeTarget
    | StageKnowledgeTarget
    | ArtifactKnowledgeTarget
    | MeasurementKnowledgeTarget,
    Field(discriminator="kind"),
]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:PrimitiveSpec -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:OntologySpec -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:DeclaredPrimitiveAssignment -->
```python contract-target
class DeclaredPrimitiveAssignment(ProtocolModel):
    """Record a primitive assigned by an identified author."""

    origin: Literal["declared"] = "declared"
    target: KnowledgeTarget
    primitive: PrimitiveRef
    assigned_by: NonEmptyStr
    assigned_at: AwareDatetime
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:InferredPrimitiveAssignment -->
```python contract-target
class InferredPrimitiveAssignment(ProtocolModel):
    """Record a primitive assigned by an immutable classifier."""

    origin: Literal["inferred"] = "inferred"
    target: KnowledgeTarget
    primitive: PrimitiveRef
    classifier: ResolvedArtifactPointerRef
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    assigned_at: AwareDatetime
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ReviewedPrimitiveAssignment -->
```python contract-target
class ReviewedPrimitiveAssignment(ProtocolModel):
    """Record a human decision about an earlier assignment."""

    origin: Literal["reviewed"] = "reviewed"
    source_assignment: ResolvedFileRef
    target: KnowledgeTarget
    primitive: PrimitiveRef
    decision: Literal["accepted", "corrected"]
    reviewed_by: NonEmptyStr
    reviewed_at: AwareDatetime
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:PrimitiveAssignment -->
```python contract-target
PrimitiveAssignment = Annotated[
    DeclaredPrimitiveAssignment
    | InferredPrimitiveAssignment
    | ReviewedPrimitiveAssignment,
    Field(discriminator="origin"),
]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:PrimitiveChange -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ComparisonField -->
```python contract-target
ComparisonField = Literal[
    "inputs",
    "split",
    "eval_spec",
    "env",
    "reproducibility",
    "compute",
]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:RunComparisonIdentity -->
```python contract-target
class RunComparisonIdentity(ProtocolModel):
    """Store the exact fields that can be held constant between runs."""

    input_sha256: tuple[SHA256, ...] = Field(min_length=1)
    split_sha256: SHA256
    eval_spec_sha256: SHA256
    env_sha256: SHA256
    reproducibility_sha256: SHA256
    compute_sha256: SHA256
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ComparisonContext -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:Modulation -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:PairedEffect -->
```python contract-target
class PairedEffect(ProtocolModel):
    """Store one oriented measurement difference for a run pair."""

    modulation: ResolvedFileRef
    baseline_measurement: ResolvedFileRef
    candidate_measurement: ResolvedFileRef
    baseline_value: float = Field(allow_inf_nan=False)
    candidate_value: float = Field(allow_inf_nan=False)
    improvement: float = Field(allow_inf_nan=False)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:EffectEstimate -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ImpactPolicy -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:ImpactAssessment -->
```python contract-target
class ImpactAssessment(ProtocolModel):
    """Apply one immutable policy to one immutable effect estimate."""

    schema_version: Literal[1] = 1
    effect: ResolvedFileRef
    policy: ResolvedFileRef
    impact: Literal["negative", "none", "low", "medium", "high"]
    assessed_at: AwareDatetime
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:DiagnosticComponent -->
```python contract-target
class DiagnosticComponent(ProtocolModel):
    """Bind one metric value to its immutable measurement."""

    metric_id: MetricId
    measurement: ResolvedFileRef
    value: float = Field(allow_inf_nan=False)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:diagnostic_component_sha256 -->
```python contract-target
def diagnostic_component_sha256(components: tuple[DiagnosticComponent, ...]) -> str:
    """Hash one ordered diagnostic component tuple."""
    payload = [component.model_dump(mode="json") for component in components]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:DiagnosticSignature -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:JournalEvidenceKind -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:JournalEvidence -->
```python contract-target
class JournalEvidence(ProtocolModel):
    """Cite one immutable record supporting a journal assertion."""

    kind: JournalEvidenceKind
    reference: ResolvedFileRef
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:JournalAssertion -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeRecordKind -->
```python contract-target
KnowledgeRecordKind = Literal[
    "ontology",
    "assignment",
    "modulation",
    "effect",
    "impact_policy",
    "impact",
    "diagnostic",
    "assertion",
]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeRecord -->
```python contract-target
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
)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:_RECORD_TYPES -->
```python contract-target
_RECORD_TYPES: dict[KnowledgeRecordKind, type[ProtocolModel]] = {
    "ontology": OntologySpec,
    "assignment": DeclaredPrimitiveAssignment,
    "modulation": Modulation,
    "effect": EffectEstimate,
    "impact_policy": ImpactPolicy,
    "impact": ImpactAssessment,
    "diagnostic": DiagnosticSignature,
    "assertion": JournalAssertion,
}
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeRecordEnvelope -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeManifest -->
```python contract-target
class KnowledgeManifest(ProtocolModel):
    """Link one published record to the preceding knowledge manifest."""

    schema_version: Literal[1] = 1
    record: ResolvedFileRef
    previous: ResolvedFileRef | None = None
    published_at: AwareDatetime
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgePublicationResult -->
```python contract-target
class KnowledgePublicationResult(BaseModel):
    """Return the immutable record and manifest references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ResolvedFileRef
    manifest: ResolvedFileRef
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:_repository_lock -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeStore -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:knowledge -->
```python contract-target
def knowledge(
    *,
    root: Path | None = None,
    destination: StorageDestination | None = None,
) -> KnowledgeStore:
    """Open the knowledge store for one repository."""
    project_root = Path.cwd().resolve() if root is None else root.resolve(strict=True)
    selected = destination or load_storage_settings(project_root).destination
    return KnowledgeStore(project_root, selected)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=src/viper/knowledge.py:__all__ -->
```python contract-target
__all__ = [
    "ArtifactKnowledgeTarget",
    "AssertionId",
    "ComparisonContext",
    "ComparisonField",
    "DeclaredPrimitiveAssignment",
    "DiagnosticComponent",
    "DiagnosticSignature",
    "EffectEstimate",
    "ImpactAssessment",
    "ImpactPolicy",
    "InferredPrimitiveAssignment",
    "JournalAssertion",
    "JournalEvidence",
    "JournalEvidenceKind",
    "KnowledgeManifest",
    "KnowledgePublicationResult",
    "KnowledgeRecord",
    "KnowledgeRecordEnvelope",
    "KnowledgeRecordKind",
    "KnowledgeStore",
    "KnowledgeTarget",
    "MeasurementKnowledgeTarget",
    "Modulation",
    "OntologyId",
    "OntologySpec",
    "OntologyVersion",
    "PairedEffect",
    "PrimitiveAssignment",
    "PrimitiveChange",
    "PrimitiveId",
    "PrimitiveRef",
    "PrimitiveSpec",
    "ReviewedPrimitiveAssignment",
    "RunComparisonIdentity",
    "RunKnowledgeTarget",
    "StageKnowledgeTarget",
    "diagnostic_component_sha256",
    "knowledge",
]
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:UTC -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:datetime -->
```python contract-target
from datetime import UTC, datetime
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:DeclaredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:OntologySpec -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:PrimitiveRef -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:PrimitiveSpec -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:RunKnowledgeTarget -->
```python contract-target
from viper.knowledge import (
    DeclaredPrimitiveAssignment,
    OntologySpec,
    PrimitiveRef,
    PrimitiveSpec,
    RunKnowledgeTarget,
)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:LocalFileRef -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:ResolvedRunRef -->
```python contract-target
from viper.references import LocalFileRef, ResolvedRunRef, SnapshotFileRef
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=update target=tests/test_protocol.py:SnapshotFileRef -->
```python contract-target
from viper.references import LocalFileRef, ResolvedRunRef, SnapshotFileRef
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_protocol.py:test_knowledge_ontology_preserves_assignment_provenance -->
```python contract-target
def test_knowledge_ontology_preserves_assignment_provenance() -> None:
    """Keep each assignment bound to one ontology version and immutable run."""
    ontology = OntologySpec(
        ontology_id="viper-core",
        version="1",
        primitives=(
            PrimitiveSpec(
                primitive_id="gated-recurrence",
                dimension="model-family",
                label="Gated recurrence",
                definition="A recurrent state transition with learned gates.",
            ),
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    run = ResolvedRunRef(
        sha256=SHA_A,
        bytes=10,
        stored_at=LocalFileRef(commit=SHA_B, path="runs/final.yaml"),
    )
    assignment = DeclaredPrimitiveAssignment(
        target=RunKnowledgeTarget(run=run),
        primitive=PrimitiveRef(
            ontology_id=ontology.ontology_id,
            ontology_version=ontology.version,
            primitive_id=ontology.primitives[0].primitive_id,
        ),
        assigned_by="researcher",
        assigned_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    restored = DeclaredPrimitiveAssignment.model_validate_json(
        assignment.model_dump_json()
    )
    assert restored == assignment
    assert restored.target.run == run
    assert restored.primitive.ontology_version == ontology.version

    with pytest.raises(ValueError, match="parent is undefined"):
        OntologySpec(
            ontology_id="viper-core",
            version="broken",
            primitives=(
                PrimitiveSpec(
                    primitive_id="child",
                    dimension="model-family",
                    label="Child",
                    definition="Broken parent reference.",
                    parents=("missing",),
                ),
            ),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:DeclaredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:KnowledgeManifest -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:KnowledgeRecordEnvelope -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:OntologySpec -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:PrimitiveRef -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:PrimitiveSpec -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:RunKnowledgeTarget -->
<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:knowledge -->
```python contract-target
from viper.knowledge import (
    DeclaredPrimitiveAssignment,
    KnowledgeManifest,
    KnowledgeRecordEnvelope,
    OntologySpec,
    PrimitiveRef,
    PrimitiveSpec,
    RunKnowledgeTarget,
    knowledge,
)
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=update target=tests/test_verification_acceptance.py:document_digest -->
```python contract-target
from viper.serialization import document_digest, parse_yaml_bytes
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:parse_yaml_bytes -->
```python contract-target
from viper.serialization import document_digest, parse_yaml_bytes
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:LocalArtifactStore -->
```python contract-target
from viper.storage import LocalArtifactStore
```

<!-- contract-target: requirements=EKP-01,EKP-02 block=P16-EKP-01 action=add target=tests/test_verification_acceptance.py:test_knowledge_records_preserve_immutable_evidence -->
```python contract-target
def test_knowledge_records_preserve_immutable_evidence(tmp_path: Path) -> None:
    """Publish records and an immutable manifest chain before advancing the head."""
    (tmp_path / "viper.toml").write_text("[project]\nschema_version = 1\n")
    store = knowledge(root=tmp_path)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    ontology = OntologySpec(
        ontology_id="viper-core",
        version="1",
        primitives=(
            PrimitiveSpec(
                primitive_id="gated-recurrence",
                dimension="model-family",
                label="Gated recurrence",
                definition="A recurrent state transition with learned gates.",
            ),
        ),
        created_at=created,
    )
    first = store.publish_ontology(ontology)
    run = ResolvedRunRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=LocalFileRef(commit="b" * 64, path="runs/final.yaml"),
    )
    assignment = DeclaredPrimitiveAssignment(
        target=RunKnowledgeTarget(run=run),
        primitive=PrimitiveRef(
            ontology_id=ontology.ontology_id,
            ontology_version=ontology.version,
            primitive_id=ontology.primitives[0].primitive_id,
        ),
        assigned_by="researcher",
        assigned_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    second = store.publish_assignment(assignment)

    local = LocalArtifactStore(tmp_path)
    first_record = KnowledgeRecordEnvelope.model_validate(
        parse_yaml_bytes(local.fetch(first.record.stored_at))
    )
    second_manifest = KnowledgeManifest.model_validate(
        parse_yaml_bytes(local.fetch(second.manifest.stored_at))
    )
    assert first_record.record_kind == "ontology"
    assert first_record.value == ontology
    assert second_manifest.record == second.record
    assert second_manifest.previous == first.manifest
    stored_head = ResolvedFileRef.model_validate_json(store.head.read_bytes())
    assert stored_head == second.manifest

    with pytest.raises(ValueError, match="kind differs"):
        KnowledgeRecordEnvelope(record_kind="impact", value=ontology)
```

## 20. Phase 17 executable plan

<!-- pair-block-definition: P17-EKP-01 -->
```toml pair-block
id = "P17-EKP-01"
requirements = ["EKP-03", "EKP-04"]
targets = [
    "src/viper/knowledge.py:math",
    "src/viper/knowledge.py:LocalFileRef",
    "src/viper/knowledge.py:ResolvedArtifactPointerRef",
    "src/viper/knowledge.py:ResolvedFileRef",
    "src/viper/knowledge.py:ResolvedRunRef",
    "src/viper/knowledge.py:parse_yaml_bytes",
    "src/viper/knowledge.py:serialize_document",
    "src/viper/knowledge.py:LocalArtifactStore",
    "src/viper/knowledge.py:StorageDestination",
    "src/viper/knowledge.py:load_storage_settings",
    "src/viper/knowledge.py:publish_resolved_files",
    "src/viper/knowledge.py:VectorViewId",
    "src/viper/knowledge.py:DiagnosticVectorView",
    "src/viper/knowledge.py:JournalVectorView",
    "src/viper/knowledge.py:VectorViewSpec",
    "src/viper/knowledge.py:KnowledgeVector",
    "src/viper/knowledge.py:RetrievalAspect",
    "src/viper/knowledge.py:RetrievalJudgment",
    "src/viper/knowledge.py:KnowledgeRecordKind",
    "src/viper/knowledge.py:KnowledgeRecord",
    "src/viper/knowledge.py:_RECORD_TYPES",
    "src/viper/knowledge.py:PrimitiveQuery",
    "src/viper/knowledge.py:AssignmentQuery",
    "src/viper/knowledge.py:ModulationQuery",
    "src/viper/knowledge.py:EffectQuery",
    "src/viper/knowledge.py:ImpactQuery",
    "src/viper/knowledge.py:DiagnosticQuery",
    "src/viper/knowledge.py:AssertionQuery",
    "src/viper/knowledge.py:RetrievalJudgmentQuery",
    "src/viper/knowledge.py:SimilarityQuery",
    "src/viper/knowledge.py:CatalogPrimitive",
    "src/viper/knowledge.py:CatalogKnowledgeRecord",
    "src/viper/knowledge.py:SimilarityMatch",
    "src/viper/knowledge.py:PrimitivePage",
    "src/viper/knowledge.py:KnowledgePage",
    "src/viper/knowledge.py:SimilarityPage",
    "src/viper/knowledge.py:KnowledgeStore",
    "src/viper/knowledge.py:__all__",
    "src/viper/catalog.py:math",
    "src/viper/catalog.py:AwareDatetime",
    "src/viper/catalog.py:BaseModel",
    "src/viper/catalog.py:ConfigDict",
    "src/viper/catalog.py:Field",
    "src/viper/catalog.py:TypeAdapter",
    "src/viper/catalog.py:AssertionQuery",
    "src/viper/catalog.py:AssignmentQuery",
    "src/viper/catalog.py:CatalogKnowledgeRecord",
    "src/viper/catalog.py:CatalogPrimitive",
    "src/viper/catalog.py:DeclaredPrimitiveAssignment",
    "src/viper/catalog.py:DiagnosticQuery",
    "src/viper/catalog.py:DiagnosticSignature",
    "src/viper/catalog.py:EffectEstimate",
    "src/viper/catalog.py:EffectQuery",
    "src/viper/catalog.py:ImpactAssessment",
    "src/viper/catalog.py:ImpactPolicy",
    "src/viper/catalog.py:ImpactQuery",
    "src/viper/catalog.py:InferredPrimitiveAssignment",
    "src/viper/catalog.py:JournalAssertion",
    "src/viper/catalog.py:KnowledgeManifest",
    "src/viper/catalog.py:KnowledgePage",
    "src/viper/catalog.py:KnowledgeRecordEnvelope",
    "src/viper/catalog.py:KnowledgeVector",
    "src/viper/catalog.py:Modulation",
    "src/viper/catalog.py:ModulationQuery",
    "src/viper/catalog.py:OntologySpec",
    "src/viper/catalog.py:PrimitivePage",
    "src/viper/catalog.py:PrimitiveQuery",
    "src/viper/catalog.py:PrimitiveRef",
    "src/viper/catalog.py:RetrievalJudgment",
    "src/viper/catalog.py:RetrievalJudgmentQuery",
    "src/viper/catalog.py:ReviewedPrimitiveAssignment",
    "src/viper/catalog.py:SimilarityMatch",
    "src/viper/catalog.py:SimilarityPage",
    "src/viper/catalog.py:SimilarityQuery",
    "src/viper/catalog.py:LocalFileRef",
    "src/viper/catalog.py:ResolvedBenchmarkResultRef",
    "src/viper/catalog.py:ResolvedFileRef",
    "src/viper/catalog.py:ResolvedRunRef",
    "src/viper/catalog.py:SnapshotFileRef",
    "src/viper/catalog.py:StageResultSnapshot",
    "src/viper/catalog.py:document_digest",
    "src/viper/catalog.py:parse_yaml_bytes",
    "src/viper/catalog.py:serialize_document",
    "src/viper/catalog.py:LocalArtifactStore",
    "src/viper/catalog.py:_SCHEMA",
    "src/viper/catalog.py:_knowledge_bytes",
    "src/viper/catalog.py:_knowledge_chain",
    "src/viper/catalog.py:Catalog",
    "src/viper/catalog.py:KnowledgeCatalog",
    "src/viper/catalog.py:__all__",
    "src/viper/api.py:AssertionQuery",
    "src/viper/api.py:AssignmentQuery",
    "src/viper/api.py:DeclaredPrimitiveAssignment",
    "src/viper/api.py:DiagnosticQuery",
    "src/viper/api.py:DiagnosticSignature",
    "src/viper/api.py:EffectEstimate",
    "src/viper/api.py:EffectQuery",
    "src/viper/api.py:ImpactAssessment",
    "src/viper/api.py:ImpactPolicy",
    "src/viper/api.py:ImpactQuery",
    "src/viper/api.py:InferredPrimitiveAssignment",
    "src/viper/api.py:JournalAssertion",
    "src/viper/api.py:KnowledgePage",
    "src/viper/api.py:KnowledgePublicationResult",
    "src/viper/api.py:KnowledgeRecordEnvelope",
    "src/viper/api.py:KnowledgeVector",
    "src/viper/api.py:Modulation",
    "src/viper/api.py:ModulationQuery",
    "src/viper/api.py:OntologySpec",
    "src/viper/api.py:PrimitivePage",
    "src/viper/api.py:PrimitiveQuery",
    "src/viper/api.py:RetrievalJudgment",
    "src/viper/api.py:RetrievalJudgmentQuery",
    "src/viper/api.py:ReviewedPrimitiveAssignment",
    "src/viper/api.py:SimilarityPage",
    "src/viper/api.py:SimilarityQuery",
    "src/viper/api.py:open_knowledge",
    "src/viper/api.py:LocalFileRef",
    "src/viper/api.py:ResolvedFileRef",
    "src/viper/api.py:ResolvedRunRef",
    "src/viper/api.py:OperationName",
    "src/viper/api.py:KnowledgeRefreshRequest",
    "src/viper/api.py:KnowledgeRefreshSuccess",
    "src/viper/api.py:KnowledgeSearchRequest",
    "src/viper/api.py:KnowledgeSearchSuccess",
    "src/viper/api.py:PublishKnowledgeRequest",
    "src/viper/api.py:PublishKnowledgeSuccess",
    "src/viper/api.py:SCHEMA_REGISTRY",
    "src/viper/api.py:OPERATIONS",
    "src/viper/api.py:knowledge_refresh",
    "src/viper/api.py:search_primitives",
    "src/viper/api.py:search_assignments",
    "src/viper/api.py:search_modulations",
    "src/viper/api.py:search_effects",
    "src/viper/api.py:search_impacts",
    "src/viper/api.py:search_diagnostics",
    "src/viper/api.py:search_assertions",
    "src/viper/api.py:search_retrieval_judgments",
    "src/viper/api.py:search_similar",
    "src/viper/api.py:_publish_knowledge",
    "src/viper/api.py:publish_ontology",
    "src/viper/api.py:publish_assignment",
    "src/viper/api.py:publish_modulation",
    "src/viper/api.py:publish_effect",
    "src/viper/api.py:publish_impact_policy",
    "src/viper/api.py:publish_impact",
    "src/viper/api.py:publish_diagnostic",
    "src/viper/api.py:publish_assertion",
    "src/viper/api.py:publish_vector",
    "src/viper/api.py:publish_retrieval_judgment",
    "src/viper/api.py:REQUEST_REGISTRY",
    "src/viper/api.py:HANDLER_REGISTRY",
    "src/viper/api.py:__all__",
    "src/viper/cli.py:build_parser",
    "src/viper/cli.py:_operation_and_payload",
    "src/viper/cli.py:_human_success",
    "src/viper/mcp.py:READ_OPERATIONS",
    "src/viper/mcp.py:EXECUTION_OPERATIONS",
    "tests/test_protocol.py:DeclaredPrimitiveAssignment",
    "tests/test_protocol.py:DiagnosticVectorView",
    "tests/test_protocol.py:KnowledgeVector",
    "tests/test_protocol.py:OntologySpec",
    "tests/test_protocol.py:PrimitiveRef",
    "tests/test_protocol.py:PrimitiveSpec",
    "tests/test_protocol.py:RetrievalJudgment",
    "tests/test_protocol.py:RunKnowledgeTarget",
    "tests/test_protocol.py:LocalFileRef",
    "tests/test_protocol.py:ResolvedFileRef",
    "tests/test_protocol.py:ResolvedRunRef",
    "tests/test_protocol.py:SnapshotFileRef",
    "tests/test_protocol.py:test_knowledge_vectors_preserve_view_identity",
    "tests/test_inspection.py:AssignmentQuery",
    "tests/test_inspection.py:DeclaredPrimitiveAssignment",
    "tests/test_inspection.py:DiagnosticComponent",
    "tests/test_inspection.py:DiagnosticSignature",
    "tests/test_inspection.py:DiagnosticVectorView",
    "tests/test_inspection.py:KnowledgeVector",
    "tests/test_inspection.py:OntologySpec",
    "tests/test_inspection.py:PrimitiveQuery",
    "tests/test_inspection.py:PrimitiveRef",
    "tests/test_inspection.py:PrimitiveSpec",
    "tests/test_inspection.py:RetrievalJudgment",
    "tests/test_inspection.py:RetrievalJudgmentQuery",
    "tests/test_inspection.py:RunKnowledgeTarget",
    "tests/test_inspection.py:SimilarityQuery",
    "tests/test_inspection.py:diagnostic_component_sha256",
    "tests/test_inspection.py:knowledge",
    "tests/test_inspection.py:GitFileRef",
    "tests/test_inspection.py:LocalFileRef",
    "tests/test_inspection.py:LocalStageResultSnapshotRef",
    "tests/test_inspection.py:ResolvedFileRef",
    "tests/test_inspection.py:ResolvedRunRef",
    "tests/test_inspection.py:ResolvedRunSpecRef",
    "tests/test_inspection.py:ResolvedStageRef",
    "tests/test_inspection.py:SnapshotFileRef",
    "tests/test_inspection.py:test_knowledge_retrieval_keeps_exact_indexes_authoritative",
    "tests/test_api.py:HANDLER_REGISTRY",
    "tests/test_api.py:REQUEST_REGISTRY",
    "tests/test_api.py:CapabilitiesRequest",
    "tests/test_api.py:CatalogRefreshRequest",
    "tests/test_api.py:KnowledgeRefreshRequest",
    "tests/test_api.py:KnowledgeSearchRequest",
    "tests/test_api.py:LocalRunPath",
    "tests/test_api.py:OperationName",
    "tests/test_api.py:PublishKnowledgeRequest",
    "tests/test_api.py:RestoreRequest",
    "tests/test_api.py:RunManyRequest",
    "tests/test_api.py:SchemaRequest",
    "tests/test_api.py:SearchRunsRequest",
    "tests/test_api.py:StatusRequest",
    "tests/test_api.py:SuccessModel",
    "tests/test_api.py:ValidateStageRequest",
    "tests/test_api.py:ViperFailure",
    "tests/test_api.py:catalog_refresh",
    "tests/test_api.py:dispatch",
    "tests/test_api.py:get_capabilities",
    "tests/test_api.py:get_schema",
    "tests/test_api.py:knowledge_refresh",
    "tests/test_api.py:publish_ontology",
    "tests/test_api.py:restore_artifacts",
    "tests/test_api.py:result_json_bytes",
    "tests/test_api.py:run_many",
    "tests/test_api.py:search_primitives",
    "tests/test_api.py:search_runs",
    "tests/test_api.py:status",
    "tests/test_api.py:validate_stage",
    "tests/test_api.py:KnowledgeRecordEnvelope",
    "tests/test_api.py:OntologySpec",
    "tests/test_api.py:PrimitiveSpec",
    "tests/test_api.py:test_knowledge_operations_match_python_cli_and_mcp",
]
assets = ["pyproject.toml"]
tests = [
    "tests/test_protocol.py:test_knowledge_vectors_preserve_view_identity",
    "tests/test_inspection.py:test_knowledge_retrieval_keeps_exact_indexes_authoritative",
    "tests/test_api.py:test_mcp_tool_schemas_match_typed_operations",
    "tests/test_api.py:test_knowledge_operations_match_python_cli_and_mcp",
]
gate = "python -m pytest tests/test_protocol.py::test_knowledge_vectors_preserve_view_identity tests/test_inspection.py::test_knowledge_retrieval_keeps_exact_indexes_authoritative tests/test_api.py::test_mcp_tool_schemas_match_typed_operations tests/test_api.py::test_knowledge_operations_match_python_cli_and_mcp -q"
depends_on = ["P16-EKP-01"]
```

**Context:** Phase 17 extends immutable knowledge with fixed vector views,
exact catalog filters, stable exhaustive similarity ranking, and one typed
operation registry shared by Python, CLI, and MCP. Exact filters remain
authoritative; optional HNSW indexes may accelerate candidate selection only.

## 21. Phase 17 ContractTargets

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:math -->
```python contract-target
import math
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:LocalFileRef -->
```python contract-target
from .references import (
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedRunRef,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:ResolvedArtifactPointerRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:ResolvedFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:ResolvedRunRef -->
```python contract-target
from .references import (
    LocalFileRef,
    ResolvedArtifactPointerRef,
    ResolvedFileRef,
    ResolvedRunRef,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:parse_yaml_bytes -->
```python contract-target
from .serialization import parse_yaml_bytes, serialize_document
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:serialize_document -->
```python contract-target
from .serialization import parse_yaml_bytes, serialize_document
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:LocalArtifactStore -->
```python contract-target
from .storage import (
    LocalArtifactStore,
    StorageDestination,
    load_storage_settings,
    publish_resolved_files,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:StorageDestination -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:load_storage_settings -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:publish_resolved_files -->
```python contract-target
from .storage import (
    LocalArtifactStore,
    StorageDestination,
    load_storage_settings,
    publish_resolved_files,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:VectorViewId -->
```python contract-target
VectorViewId = Annotated[str, StringConstraints(min_length=1)]
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:DiagnosticVectorView -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:JournalVectorView -->
```python contract-target
class JournalVectorView(ProtocolModel):
    """Define one journal embedding space and its immutable embedder."""

    kind: Literal["journal"] = "journal"
    view_id: VectorViewId
    version: NonEmptyStr
    embedder: ResolvedArtifactPointerRef
    dimensions: int = Field(ge=1)
    distance: Literal["cosine"] = "cosine"
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:VectorViewSpec -->
```python contract-target
VectorViewSpec = Annotated[
    DiagnosticVectorView | JournalVectorView,
    Field(discriminator="kind"),
]
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:KnowledgeVector -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:RetrievalAspect -->
```python contract-target
RetrievalAspect = Literal["primitive", "diagnostic", "journal", "outcome"]
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:RetrievalJudgment -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:KnowledgeRecordKind -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:KnowledgeRecord -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:_RECORD_TYPES -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:PrimitiveQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:AssignmentQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:ModulationQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:EffectQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:ImpactQuery -->
```python contract-target
class ImpactQuery(BaseModel):
    """Filter qualitative impact assessments by exact fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_ids: tuple[MetricId, ...] = ()
    impacts: tuple[Literal["negative", "none", "low", "medium", "high"], ...] = ()
    policy_ids: tuple[NonEmptyStr, ...] = ()
    context_sha256: SHA256 | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:DiagnosticQuery -->
```python contract-target
class DiagnosticQuery(BaseModel):
    """Filter diagnostic signatures by run, stage, or metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: tuple[ResolvedRunRef, ...] = ()
    stage_ids: tuple[StageId, ...] = ()
    metric_ids: tuple[MetricId, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:AssertionQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:RetrievalJudgmentQuery -->
```python contract-target
class RetrievalJudgmentQuery(BaseModel):
    """Filter reviewed retrieval judgments by exact review fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    view_ids: tuple[VectorViewId, ...] = ()
    aspects: tuple[RetrievalAspect, ...] = ()
    minimum_relevance: int | None = Field(default=None, ge=0, le=3)
    reviewers: tuple[NonEmptyStr, ...] = ()
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:SimilarityQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:CatalogPrimitive -->
```python contract-target
class CatalogPrimitive(BaseModel):
    """Return one primitive with its immutable ontology reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology: ResolvedFileRef
    primitive: PrimitiveRef
    dimension: NonEmptyStr
    label: NonEmptyStr
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:CatalogKnowledgeRecord -->
```python contract-target
class CatalogKnowledgeRecord(BaseModel):
    """Return one immutable reference and its parsed knowledge record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: ResolvedFileRef
    record: KnowledgeRecordEnvelope
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:SimilarityMatch -->
```python contract-target
class SimilarityMatch(BaseModel):
    """Return one exact-distance vector match and its source record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: CatalogKnowledgeRecord
    vector: ResolvedFileRef
    distance: float = Field(ge=0.0, allow_inf_nan=False)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:PrimitivePage -->
```python contract-target
class PrimitivePage(BaseModel):
    """Return one deterministic page of ontology primitives."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[CatalogPrimitive, ...]
    next_cursor: str | None = None
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:KnowledgePage -->
```python contract-target
class KnowledgePage(BaseModel):
    """Return one deterministic page of knowledge records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[CatalogKnowledgeRecord, ...]
    next_cursor: str | None = None
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/knowledge.py:SimilarityPage -->
```python contract-target
class SimilarityPage(BaseModel):
    """Return one bounded exact-distance result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[SimilarityMatch, ...]
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:KnowledgeStore -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/knowledge.py:__all__ -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:math -->
```python contract-target
import math
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:AwareDatetime -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:BaseModel -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:ConfigDict -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:Field -->
```python contract-target
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:TypeAdapter -->
```python contract-target
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:AssertionQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:AssignmentQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:CatalogKnowledgeRecord -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:CatalogPrimitive -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:DeclaredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:DiagnosticQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:DiagnosticSignature -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:EffectEstimate -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:EffectQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:ImpactAssessment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:ImpactPolicy -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:ImpactQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:InferredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:JournalAssertion -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:KnowledgeManifest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:KnowledgePage -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:KnowledgeRecordEnvelope -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:KnowledgeVector -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:Modulation -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:ModulationQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:OntologySpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:PrimitivePage -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:PrimitiveQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:PrimitiveRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:RetrievalJudgment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:RetrievalJudgmentQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:ReviewedPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:SimilarityMatch -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:SimilarityPage -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:SimilarityQuery -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:LocalFileRef -->
```python contract-target
from .references import (
    LocalFileRef,
    ResolvedBenchmarkResultRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshot,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:ResolvedBenchmarkResultRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:ResolvedFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:ResolvedRunRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:SnapshotFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:StageResultSnapshot -->
```python contract-target
from .references import (
    LocalFileRef,
    ResolvedBenchmarkResultRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
    StageResultSnapshot,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:document_digest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:serialize_document -->
```python contract-target
from .serialization import document_digest, parse_yaml_bytes, serialize_document
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:parse_yaml_bytes -->
```python contract-target
from .serialization import document_digest, parse_yaml_bytes, serialize_document
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:LocalArtifactStore -->
```python contract-target
from .storage import LocalArtifactStore
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:_SCHEMA -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:_knowledge_bytes -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:_knowledge_chain -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:Catalog -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/catalog.py:KnowledgeCatalog -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/catalog.py:__all__ -->
```python contract-target
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
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:AssertionQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:AssignmentQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:DeclaredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:DiagnosticQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:DiagnosticSignature -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:EffectEstimate -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:EffectQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:ImpactAssessment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:ImpactPolicy -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:ImpactQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:InferredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:JournalAssertion -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgePage -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgePublicationResult -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgeRecordEnvelope -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgeVector -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:Modulation -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:ModulationQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:OntologySpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:PrimitivePage -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:PrimitiveQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:RetrievalJudgment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:RetrievalJudgmentQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:ReviewedPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:SimilarityPage -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:SimilarityQuery -->
```python contract-target
from .knowledge import (
    AssertionQuery,
    AssignmentQuery,
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
    KnowledgePage,
    KnowledgePublicationResult,
    KnowledgeRecordEnvelope,
    KnowledgeVector,
    Modulation,
    ModulationQuery,
    OntologySpec,
    PrimitivePage,
    PrimitiveQuery,
    RetrievalJudgment,
    RetrievalJudgmentQuery,
    ReviewedPrimitiveAssignment,
    SimilarityPage,
    SimilarityQuery,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:open_knowledge -->
```python contract-target
from .knowledge import knowledge as open_knowledge
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:LocalFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:ResolvedRunRef -->
```python contract-target
from .references import LocalFileRef, ResolvedFileRef, ResolvedRunRef
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:ResolvedFileRef -->
```python contract-target
from .references import LocalFileRef, ResolvedFileRef, ResolvedRunRef
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:OperationName -->
```python contract-target
OperationName = Literal[
    "validate_stage",
    "validate_resolved_stage",
    "validate_run_spec",
    "freeze_run",
    "preflight",
    "execute_stage",
    "run",
    "run_many",
    "retry",
    "execute_benchmark",
    "restore",
    "plan_diff",
    "lineage",
    "status",
    "compare_runs",
    "verify_run",
    "verify_benchmark",
    "verify_pointer",
    "get_schema",
    "get_capabilities",
    "init_project",
    "explain_impact",
    "analyze_impact",
    "catalog_refresh",
    "search_runs",
    "search_artifacts",
    "search_measurements",
    "search_benchmarks",
    "knowledge_refresh",
    "search_primitives",
    "search_assignments",
    "search_modulations",
    "search_effects",
    "search_impacts",
    "search_diagnostics",
    "search_assertions",
    "search_retrieval_judgments",
    "search_similar",
    "publish_ontology",
    "publish_assignment",
    "publish_modulation",
    "publish_effect",
    "publish_impact_policy",
    "publish_impact",
    "publish_diagnostic",
    "publish_assertion",
    "publish_vector",
    "publish_retrieval_judgment",
]
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgeRefreshRequest -->
```python contract-target
class KnowledgeRefreshRequest(APIModel):
    """Select manifest heads for one complete knowledge projection."""

    root: Path
    heads: tuple[ResolvedFileRef, ...] = ()
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgeRefreshSuccess -->
```python contract-target
class KnowledgeRefreshSuccess(SuccessModel):
    """Return the rebuilt catalog identity and source counts."""

    operation: Literal["knowledge_refresh"] = "knowledge_refresh"  # pyright: ignore[reportIncompatibleVariableOverride]
    result: CatalogRefreshResult
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgeSearchRequest -->
```python contract-target
class KnowledgeSearchRequest(APIModel):
    """Select one project and one exact knowledge query payload."""

    root: Path
    query: dict[str, Any] = Field(default_factory=dict)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:KnowledgeSearchSuccess -->
```python contract-target
class KnowledgeSearchSuccess(SuccessModel):
    """Return one typed exact or similarity-search result."""

    page: PrimitivePage | KnowledgePage | SimilarityPage
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:PublishKnowledgeRequest -->
```python contract-target
class PublishKnowledgeRequest(APIModel):
    """Select one project and one typed knowledge record."""

    root: Path
    record: KnowledgeRecordEnvelope
    published_at: datetime | None = None
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:PublishKnowledgeSuccess -->
```python contract-target
class PublishKnowledgeSuccess(SuccessModel):
    """Return immutable record and manifest references."""

    publication: KnowledgePublicationResult
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:SCHEMA_REGISTRY -->
```python contract-target
SCHEMA_REGISTRY: dict[str, Any] = {
    "ArtifactPointer": ArtifactPointer,
    "BenchmarkResult": BenchmarkResult,
    "CapabilitiesRequest": CapabilitiesRequest,
    "CapabilitiesSuccess": CapabilitiesSuccess,
    "CatalogRefreshRequest": CatalogRefreshRequest,
    "CatalogRefreshSuccess": CatalogRefreshSuccess,
    "KnowledgeRefreshRequest": KnowledgeRefreshRequest,
    "KnowledgeRefreshSuccess": KnowledgeRefreshSuccess,
    "KnowledgeSearchRequest": KnowledgeSearchRequest,
    "KnowledgeSearchSuccess": KnowledgeSearchSuccess,
    "PublishKnowledgeRequest": PublishKnowledgeRequest,
    "PublishKnowledgeSuccess": PublishKnowledgeSuccess,
    "ExecuteStageRequest": ExecuteStageRequest,
    "ExecuteStageSuccess": ExecuteStageSuccess,
    "ExecuteBenchmarkRequest": ExecuteBenchmarkRequest,
    "ExecuteBenchmarkSuccess": ExecuteBenchmarkSuccess,
    "RestoreRequest": RestoreRequest,
    "RestoreSuccess": RestoreSuccess,
    "ExplainImpactRequest": ExplainImpactRequest,
    "ExplainImpactSuccess": ExplainImpactSuccess,
    "AnalyzeImpactRequest": AnalyzeImpactRequest,
    "AnalyzeImpactSuccess": AnalyzeImpactSuccess,
    "FreezeRunRequest": FreezeRunRequest,
    "FreezeRunSuccess": FreezeRunSuccess,
    "InitProjectRequest": InitProjectRequest,
    "InitProjectSuccess": InitProjectSuccess,
    "LineageRequest": LineageRequest,
    "LineageSuccess": LineageSuccess,
    "CompareRunsRequest": CompareRunsRequest,
    "CompareRunsSuccess": CompareRunsSuccess,
    "PlanDiffRequest": PlanDiffRequest,
    "PlanDiffSuccess": PlanDiffSuccess,
    "StatusRequest": StatusRequest,
    "StatusSuccess": StatusSuccess,
    "PreflightRequest": PreflightRequest,
    "PreflightSuccess": PreflightSuccess,
    "ResolvedRun": ResolvedRun,
    "RunRequest": RunRequest,
    "RunSuccess": RunSuccess,
    "RunManyRequest": RunManyRequest,
    "RunManySuccess": RunManySuccess,
    "RetryRequest": RetryRequest,
    "RetrySuccess": RetrySuccess,
    "RunSpec": RunSpec,
    "SchemaRequest": SchemaRequest,
    "SchemaSuccess": SchemaSuccess,
    "SearchArtifactsRequest": SearchArtifactsRequest,
    "SearchArtifactsSuccess": SearchArtifactsSuccess,
    "SearchBenchmarksRequest": SearchBenchmarksRequest,
    "SearchBenchmarksSuccess": SearchBenchmarksSuccess,
    "SearchMeasurementsRequest": SearchMeasurementsRequest,
    "SearchMeasurementsSuccess": SearchMeasurementsSuccess,
    "SearchRunsRequest": SearchRunsRequest,
    "SearchRunsSuccess": SearchRunsSuccess,
    "Spec": Spec,
    "ValidateResolvedStageRequest": ValidateResolvedStageRequest,
    "ValidateResolvedStageSuccess": ValidateResolvedStageSuccess,
    "ValidateRunSpecRequest": ValidateRunSpecRequest,
    "ValidateRunSpecSuccess": ValidateRunSpecSuccess,
    "ValidateStageRequest": ValidateStageRequest,
    "ValidateStageSuccess": ValidateStageSuccess,
    "VerifyBenchmarkRequest": VerifyBenchmarkRequest,
    "VerifyBenchmarkSuccess": VerifyBenchmarkSuccess,
    "VerifyPointerRequest": VerifyPointerRequest,
    "VerifyPointerSuccess": VerifyPointerSuccess,
    "VerifyRunRequest": VerifyRunRequest,
    "VerifyRunSuccess": VerifyRunSuccess,
    "ViperFailure": ViperFailure,
}
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:OPERATIONS -->
```python contract-target
OPERATIONS: tuple[OperationName, ...] = (
    "validate_stage",
    "validate_resolved_stage",
    "validate_run_spec",
    "freeze_run",
    "preflight",
    "execute_stage",
    "run",
    "run_many",
    "retry",
    "execute_benchmark",
    "restore",
    "plan_diff",
    "lineage",
    "status",
    "compare_runs",
    "verify_run",
    "verify_benchmark",
    "verify_pointer",
    "get_schema",
    "get_capabilities",
    "init_project",
    "explain_impact",
    "analyze_impact",
    "catalog_refresh",
    "search_runs",
    "search_artifacts",
    "search_measurements",
    "search_benchmarks",
    "knowledge_refresh",
    "search_primitives",
    "search_assignments",
    "search_modulations",
    "search_effects",
    "search_impacts",
    "search_diagnostics",
    "search_assertions",
    "search_retrieval_judgments",
    "search_similar",
    "publish_ontology",
    "publish_assignment",
    "publish_modulation",
    "publish_effect",
    "publish_impact_policy",
    "publish_impact",
    "publish_diagnostic",
    "publish_assertion",
    "publish_vector",
    "publish_retrieval_judgment",
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:knowledge_refresh -->
```python contract-target
def knowledge_refresh(request: KnowledgeRefreshRequest) -> KnowledgeRefreshSuccess:
    """Rebuild the knowledge projection from local and supplied manifest heads."""
    project_root = _root(request.root, "knowledge_refresh")
    result = catalog(root=project_root).refresh(knowledge=request.heads)
    return KnowledgeRefreshSuccess(result=result)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_primitives -->
```python contract-target
def search_primitives(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return ontology primitives matching one exact query."""
    project_root = _root(request.root, "search_primitives")
    query = PrimitiveQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.primitives(query)
    return KnowledgeSearchSuccess(operation="search_primitives", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_assignments -->
```python contract-target
def search_assignments(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return primitive assignments matching one exact query."""
    project_root = _root(request.root, "search_assignments")
    query = AssignmentQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.assignments(query)
    return KnowledgeSearchSuccess(operation="search_assignments", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_modulations -->
```python contract-target
def search_modulations(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return controlled modulations matching one exact query."""
    project_root = _root(request.root, "search_modulations")
    query = ModulationQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.modulations(query)
    return KnowledgeSearchSuccess(operation="search_modulations", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_effects -->
```python contract-target
def search_effects(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return effect estimates matching one exact query."""
    project_root = _root(request.root, "search_effects")
    query = EffectQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.effects(query)
    return KnowledgeSearchSuccess(operation="search_effects", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_impacts -->
```python contract-target
def search_impacts(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return impact assessments matching one exact query."""
    project_root = _root(request.root, "search_impacts")
    query = ImpactQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.impacts(query)
    return KnowledgeSearchSuccess(operation="search_impacts", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_diagnostics -->
```python contract-target
def search_diagnostics(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return diagnostic signatures matching one exact query."""
    project_root = _root(request.root, "search_diagnostics")
    query = DiagnosticQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.diagnostics(query)
    return KnowledgeSearchSuccess(operation="search_diagnostics", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_assertions -->
```python contract-target
def search_assertions(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Return journal assertions matching one exact query."""
    project_root = _root(request.root, "search_assertions")
    query = AssertionQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.assertions(query)
    return KnowledgeSearchSuccess(operation="search_assertions", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_retrieval_judgments -->
```python contract-target
def search_retrieval_judgments(
    request: KnowledgeSearchRequest,
) -> KnowledgeSearchSuccess:
    """Return retrieval judgments matching one exact query."""
    project_root = _root(request.root, "search_retrieval_judgments")
    query = RetrievalJudgmentQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.retrieval_judgments(query)
    return KnowledgeSearchSuccess(
        operation="search_retrieval_judgments",
        page=page,
    )
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:search_similar -->
```python contract-target
def search_similar(request: KnowledgeSearchRequest) -> KnowledgeSearchSuccess:
    """Rank vectors inside one exact view."""
    project_root = _root(request.root, "search_similar")
    query = SimilarityQuery.model_validate(request.query)
    page = catalog(root=project_root).knowledge.similar(query)
    return KnowledgeSearchSuccess(operation="search_similar", page=page)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:_publish_knowledge -->
```python contract-target
def _publish_knowledge(
    operation: OperationName,
    request: PublishKnowledgeRequest,
) -> PublishKnowledgeSuccess:
    """Route one typed envelope through its matching store method."""
    project_root = _root(request.root, operation)
    store = open_knowledge(root=project_root)
    value = request.record.value
    if operation == "publish_ontology" and isinstance(value, OntologySpec):
        result = store.publish_ontology(value)
    elif operation == "publish_assignment" and isinstance(
        value,
        (
            DeclaredPrimitiveAssignment,
            InferredPrimitiveAssignment,
            ReviewedPrimitiveAssignment,
        ),
    ):
        result = store.publish_assignment(value)
    elif operation == "publish_modulation" and isinstance(value, Modulation):
        result = store.publish_modulation(value)
    elif operation == "publish_effect" and isinstance(value, EffectEstimate):
        result = store.publish_effect(value)
    elif operation == "publish_impact_policy" and isinstance(value, ImpactPolicy):
        if request.published_at is None:
            raise ValueError("impact policy publication requires published_at")
        result = store.publish_impact_policy(value, published_at=request.published_at)
    elif operation == "publish_impact" and isinstance(value, ImpactAssessment):
        result = store.publish_impact(value)
    elif operation == "publish_diagnostic" and isinstance(
        value, DiagnosticSignature
    ):
        result = store.publish_signature(value)
    elif operation == "publish_assertion" and isinstance(value, JournalAssertion):
        result = store.publish_assertion(value)
    elif operation == "publish_vector" and isinstance(value, KnowledgeVector):
        result = store.publish_vector(value)
    elif operation == "publish_retrieval_judgment" and isinstance(
        value, RetrievalJudgment
    ):
        result = store.publish_retrieval_judgment(value)
    else:
        raise ValueError("knowledge record kind differs from the operation")
    return PublishKnowledgeSuccess(operation=operation, publication=result)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_ontology -->
```python contract-target
def publish_ontology(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one ontology record."""
    return _publish_knowledge("publish_ontology", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_assignment -->
```python contract-target
def publish_assignment(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one primitive assignment record."""
    return _publish_knowledge("publish_assignment", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_modulation -->
```python contract-target
def publish_modulation(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one controlled modulation record."""
    return _publish_knowledge("publish_modulation", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_effect -->
```python contract-target
def publish_effect(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one effect estimate record."""
    return _publish_knowledge("publish_effect", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_impact_policy -->
```python contract-target
def publish_impact_policy(
    request: PublishKnowledgeRequest,
) -> PublishKnowledgeSuccess:
    """Publish one impact policy record."""
    return _publish_knowledge("publish_impact_policy", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_impact -->
```python contract-target
def publish_impact(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one impact assessment record."""
    return _publish_knowledge("publish_impact", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_diagnostic -->
```python contract-target
def publish_diagnostic(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one diagnostic signature record."""
    return _publish_knowledge("publish_diagnostic", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_assertion -->
```python contract-target
def publish_assertion(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one journal assertion record."""
    return _publish_knowledge("publish_assertion", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_vector -->
```python contract-target
def publish_vector(request: PublishKnowledgeRequest) -> PublishKnowledgeSuccess:
    """Publish one knowledge vector record."""
    return _publish_knowledge("publish_vector", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=src/viper/api.py:publish_retrieval_judgment -->
```python contract-target
def publish_retrieval_judgment(
    request: PublishKnowledgeRequest,
) -> PublishKnowledgeSuccess:
    """Publish one reviewed retrieval judgment record."""
    return _publish_knowledge("publish_retrieval_judgment", request)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:REQUEST_REGISTRY -->
```python contract-target
REQUEST_REGISTRY: dict[OperationName, RequestType] = {
    "validate_stage": ValidateStageRequest,
    "validate_resolved_stage": ValidateResolvedStageRequest,
    "validate_run_spec": ValidateRunSpecRequest,
    "freeze_run": FreezeRunRequest,
    "preflight": PreflightRequest,
    "execute_stage": ExecuteStageRequest,
    "run": RunRequest,
    "run_many": RunManyRequest,
    "retry": RetryRequest,
    "execute_benchmark": ExecuteBenchmarkRequest,
    "restore": RestoreRequest,
    "plan_diff": PlanDiffRequest,
    "lineage": LineageRequest,
    "status": StatusRequest,
    "compare_runs": CompareRunsRequest,
    "verify_run": VerifyRunRequest,
    "verify_benchmark": VerifyBenchmarkRequest,
    "verify_pointer": VerifyPointerRequest,
    "get_schema": SchemaRequest,
    "get_capabilities": CapabilitiesRequest,
    "init_project": InitProjectRequest,
    "explain_impact": ExplainImpactRequest,
    "analyze_impact": AnalyzeImpactRequest,
    "catalog_refresh": CatalogRefreshRequest,
    "search_runs": SearchRunsRequest,
    "search_artifacts": SearchArtifactsRequest,
    "search_measurements": SearchMeasurementsRequest,
    "search_benchmarks": SearchBenchmarksRequest,
    "knowledge_refresh": KnowledgeRefreshRequest,
    "search_primitives": KnowledgeSearchRequest,
    "search_assignments": KnowledgeSearchRequest,
    "search_modulations": KnowledgeSearchRequest,
    "search_effects": KnowledgeSearchRequest,
    "search_impacts": KnowledgeSearchRequest,
    "search_diagnostics": KnowledgeSearchRequest,
    "search_assertions": KnowledgeSearchRequest,
    "search_retrieval_judgments": KnowledgeSearchRequest,
    "search_similar": KnowledgeSearchRequest,
    "publish_ontology": PublishKnowledgeRequest,
    "publish_assignment": PublishKnowledgeRequest,
    "publish_modulation": PublishKnowledgeRequest,
    "publish_effect": PublishKnowledgeRequest,
    "publish_impact_policy": PublishKnowledgeRequest,
    "publish_impact": PublishKnowledgeRequest,
    "publish_diagnostic": PublishKnowledgeRequest,
    "publish_assertion": PublishKnowledgeRequest,
    "publish_vector": PublishKnowledgeRequest,
    "publish_retrieval_judgment": PublishKnowledgeRequest,
}
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:HANDLER_REGISTRY -->
```python contract-target
HANDLER_REGISTRY: dict[OperationName, Handler] = {
    "validate_stage": validate_stage,
    "validate_resolved_stage": validate_resolved_stage,
    "validate_run_spec": validate_run_spec,
    "freeze_run": freeze_run,
    "preflight": preflight,
    "execute_stage": execute_stage,
    "run": run_request,
    "run_many": run_many,
    "retry": retry_request,
    "execute_benchmark": execute_benchmark,
    "restore": restore_artifacts,
    "plan_diff": plan_diff,
    "lineage": lineage,
    "status": status,
    "compare_runs": compare_runs,
    "verify_run": verify_run,
    "verify_benchmark": verify_benchmark,
    "verify_pointer": verify_pointer,
    "get_schema": get_schema,
    "get_capabilities": get_capabilities,
    "init_project": init_project,
    "explain_impact": explain_impact,
    "analyze_impact": analyze_impact,
    "catalog_refresh": catalog_refresh,
    "search_runs": search_runs,
    "search_artifacts": search_artifacts,
    "search_measurements": search_measurements,
    "search_benchmarks": search_benchmarks,
    "knowledge_refresh": knowledge_refresh,
    "search_primitives": search_primitives,
    "search_assignments": search_assignments,
    "search_modulations": search_modulations,
    "search_effects": search_effects,
    "search_impacts": search_impacts,
    "search_diagnostics": search_diagnostics,
    "search_assertions": search_assertions,
    "search_retrieval_judgments": search_retrieval_judgments,
    "search_similar": search_similar,
    "publish_ontology": publish_ontology,
    "publish_assignment": publish_assignment,
    "publish_modulation": publish_modulation,
    "publish_effect": publish_effect,
    "publish_impact_policy": publish_impact_policy,
    "publish_impact": publish_impact,
    "publish_diagnostic": publish_diagnostic,
    "publish_assertion": publish_assertion,
    "publish_vector": publish_vector,
    "publish_retrieval_judgment": publish_retrieval_judgment,
}
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/api.py:__all__ -->
```python contract-target
__all__ = [
    "APIModel",
    "AnalyzeImpactRequest",
    "AnalyzeImpactSuccess",
    "CapabilitiesRequest",
    "CapabilitiesSuccess",
    "CatalogRefreshRequest",
    "CatalogRefreshSuccess",
    "CompareRunsRequest",
    "CompareRunsSuccess",
    "ExecuteStageRequest",
    "ExecuteStageSuccess",
    "ExecuteBenchmarkRequest",
    "ExecuteBenchmarkSuccess",
    "ExplainImpactRequest",
    "ExplainImpactSuccess",
    "ErrorCode",
    "FailureOrigin",
    "FreezeRunRequest",
    "FreezeRunSuccess",
    "InitProjectRequest",
    "InitProjectSuccess",
    "LineageRequest",
    "LineageSuccess",
    "KnowledgeRefreshRequest",
    "KnowledgeRefreshSuccess",
    "KnowledgeSearchRequest",
    "KnowledgeSearchSuccess",
    "OperationName",
    "PythonRunError",
    "PlanDiffRequest",
    "PlanDiffSuccess",
    "PreflightRequest",
    "PreflightSuccess",
    "PublishKnowledgeRequest",
    "PublishKnowledgeSuccess",
    "RunRequest",
    "RunSuccess",
    "RunManyRequest",
    "RunManySuccess",
    "RetryRequest",
    "RetrySuccess",
    "RestoreRequest",
    "RestoreRequestReference",
    "RestoreSuccess",
    "LocalRunPath",
    "ViperCloudRunReference",
    "SchemaRequest",
    "SchemaSuccess",
    "SearchArtifactsRequest",
    "SearchArtifactsSuccess",
    "SearchBenchmarksRequest",
    "SearchBenchmarksSuccess",
    "SearchMeasurementsRequest",
    "SearchMeasurementsSuccess",
    "SearchRunsRequest",
    "SearchRunsSuccess",
    "StatusRequest",
    "StatusSuccess",
    "SuccessModel",
    "ValidateResolvedStageRequest",
    "ValidateResolvedStageSuccess",
    "ValidateRunSpecRequest",
    "ValidateRunSpecSuccess",
    "ValidateStageRequest",
    "ValidateStageSuccess",
    "VerifyBenchmarkRequest",
    "VerifyBenchmarkSuccess",
    "VerifyPointerRequest",
    "VerifyPointerSuccess",
    "VerifyRunRequest",
    "VerifyRunSuccess",
    "ViperError",
    "ViperFailure",
    "analyze_impact",
    "catalog_refresh",
    "compare_runs",
    "dispatch",
    "execute_stage",
    "execute_benchmark",
    "explain_impact",
    "restore_artifacts",
    "freeze_run",
    "get_capabilities",
    "init_project",
    "get_schema",
    "knowledge_refresh",
    "lineage",
    "plan_diff",
    "preflight",
    "publish_assertion",
    "publish_assignment",
    "publish_diagnostic",
    "publish_effect",
    "publish_impact",
    "publish_modulation",
    "publish_ontology",
    "publish_retrieval_judgment",
    "publish_vector",
    "result_json_bytes",
    "retry",
    "run",
    "run_many",
    "search_artifacts",
    "search_assertions",
    "search_assignments",
    "search_benchmarks",
    "search_diagnostics",
    "search_effects",
    "search_impacts",
    "search_measurements",
    "search_modulations",
    "search_primitives",
    "search_retrieval_judgments",
    "search_runs",
    "search_similar",
    "status",
    "validate_resolved_stage",
    "validate_run_spec",
    "validate_stage",
    "verify_benchmark",
    "verify_pointer",
    "verify_run",
]
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/cli.py:build_parser -->
```python contract-target
def build_parser() -> ArgumentParser:
    """Build the VIPER command parser and its API subcommands."""
    parser = ViperArgumentParser(prog="viper")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit one machine-readable result document",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("validate-stage", "validate one authored stage specification"),
        ("validate-resolved-stage", "validate one resolved stage specification"),
        ("validate-run", "validate one frozen run specification"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("path", type=Path)

    freeze = commands.add_parser(
        "freeze-run",
        help="write canonical stage specs and a hash-bound RunSpec",
    )
    freeze.add_argument("draft", type=Path)
    add_root(freeze)

    preflight = commands.add_parser(
        "preflight",
        help="inspect every applicable check before local execution",
    )
    preflight.add_argument("run_spec", type=Path)
    add_root(preflight)

    execute = commands.add_parser(
        "execute-stage",
        help="run one stage from a frozen local run plan",
    )
    execute.add_argument("run_spec", type=Path)
    execute.add_argument("stage_id")
    add_root(execute)
    execute.add_argument("--timeout-seconds", type=float)

    run_command = commands.add_parser(
        "run",
        help="execute and verify one complete run on this host",
    )
    run_command.add_argument("run_spec", type=Path)
    add_root(run_command)
    run_command.add_argument("--timeout-seconds", type=float)

    run_many = commands.add_parser(
        "run-many",
        help="execute several frozen run plans with bounded concurrency",
    )
    run_many.add_argument("run_specs", nargs="+", type=Path)
    add_root(run_many)
    run_many.add_argument("--max-concurrency", type=int, default=1)
    run_many.add_argument("--timeout-seconds", type=float)
    run_many.add_argument("--stop-on-failure", action="store_true")

    catalog_refresh = commands.add_parser(
        "catalog-refresh",
        help="verify terminal runs and rebuild the local catalog",
    )
    catalog_refresh.add_argument("run_paths", nargs="+", type=Path)
    add_root(catalog_refresh)
    catalog_refresh.add_argument(
        "--trust-source",
        action="append",
        required=True,
        help="source repository URL approved to supply executable loaders",
    )

    for name, help_text in (
        ("search-runs", "query verified runs"),
        ("search-artifacts", "query verified artifacts"),
        ("search-measurements", "query verified measurements"),
        ("search-benchmarks", "query verified benchmark results"),
    ):
        search = commands.add_parser(name, help=help_text)
        add_root(search)
        search.add_argument(
            "--query",
            type=parse_query,
            default={},
            help="exact query model as one JSON object",
        )

    knowledge = commands.add_parser(
        "knowledge",
        help="publish and search experiment knowledge",
    )
    knowledge_commands = knowledge.add_subparsers(
        dest="knowledge_command",
        required=True,
    )
    knowledge_refresh = knowledge_commands.add_parser(
        "refresh",
        help="rebuild the local knowledge projection",
    )
    add_root(knowledge_refresh)
    knowledge_refresh.add_argument(
        "--head",
        action="append",
        type=parse_query,
        default=[],
        help="immutable knowledge manifest reference as JSON",
    )
    knowledge_search = knowledge_commands.add_parser(
        "search",
        help="run one exact knowledge query",
    )
    add_root(knowledge_search)
    knowledge_search.add_argument(
        "kind",
        choices=(
            "search_assertions",
            "search_assignments",
            "search_diagnostics",
            "search_effects",
            "search_impacts",
            "search_modulations",
            "search_primitives",
            "search_retrieval_judgments",
            "search_similar",
        ),
    )
    knowledge_search.add_argument("--query", type=parse_query, default={})
    knowledge_publish = knowledge_commands.add_parser(
        "publish",
        help="publish one typed knowledge record",
    )
    add_root(knowledge_publish)
    knowledge_publish.add_argument(
        "kind",
        choices=(
            "publish_assertion",
            "publish_assignment",
            "publish_diagnostic",
            "publish_effect",
            "publish_impact",
            "publish_impact_policy",
            "publish_modulation",
            "publish_ontology",
            "publish_retrieval_judgment",
            "publish_vector",
        ),
    )
    knowledge_publish.add_argument("record", type=parse_query)
    knowledge_publish.add_argument("--published-at")

    mcp = commands.add_parser(
        "mcp",
        help="serve the typed VIPER API over local MCP stdio",
    )
    add_root(mcp)
    mcp.add_argument("--access", choices=("read", "execute"), default="read")

    retry_command = commands.add_parser(
        "retry",
        help="append one attempt to a failed frozen run",
    )
    retry_command.add_argument("run_spec", type=Path)
    add_root(retry_command)
    retry_command.add_argument("--timeout-seconds", type=float)

    benchmark_command = commands.add_parser(
        "execute-benchmark",
        help="execute and verify one independent benchmark confirmation",
    )
    benchmark_command.add_argument("resolved_run", type=Path)
    benchmark_command.add_argument("benchmark_spec", type=Path)
    add_root(benchmark_command)
    benchmark_command.add_argument("--timeout-seconds", type=float)

    restore = commands.add_parser(
        "restore",
        help="restore verified artifacts from one successful run",
    )
    restore.add_argument("run_reference")
    add_root(restore)
    restore.add_argument(
        "--artifacts",
        nargs="+",
        default=[],
        type=parse_artifact_selector,
        metavar="STAGE.ARTIFACT",
    )
    restore.add_argument("--output", type=Path)

    plan_diff = commands.add_parser(
        "plan-diff",
        help="compare two complete frozen run plans",
    )
    plan_diff.add_argument("left_run_spec", type=Path)
    plan_diff.add_argument("right_run_spec", type=Path)
    add_root(plan_diff, "left_root")
    add_root(plan_diff, "right_root")

    status = commands.add_parser(
        "status",
        help="read the latest durable state of one local attempt",
    )
    status.add_argument("path", type=Path)

    compare_runs = commands.add_parser(
        "compare-runs",
        help="compare all connected evidence from two verified runs",
    )
    compare_runs.add_argument("left_path", type=Path)
    compare_runs.add_argument("right_path", type=Path)
    add_root(compare_runs, "left_root")
    add_root(compare_runs, "right_root")
    compare_runs.add_argument(
        "--trust-source",
        action="append",
        required=True,
        help="source repository URL approved to supply executable loaders",
    )

    for name, help_text in (
        ("verify-run", "verify one terminal resolved run"),
        ("verify-benchmark", "verify one benchmark result"),
        ("verify-pointer", "verify one promoted artifact pointer"),
        ("lineage", "return the verified upstream lineage of one run"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("path", type=Path)
        add_root(command)
        command.add_argument(
            "--trust-source",
            action="append",
            required=True,
            help="source repository URL approved to supply executable loaders",
        )

    schema = commands.add_parser("schema", help="return one public JSON Schema")
    schema.add_argument("name")
    commands.add_parser("capabilities", help="list installed VIPER capabilities")
    initialize = commands.add_parser(
        "init",
        help="create a five-stage starter project",
    )
    initialize.add_argument("path", type=Path)
    initialize.add_argument("--package", required=True)
    impact = commands.add_parser(
        "impact",
        help="inspect verified source-impact evidence",
    )
    impact_commands = impact.add_subparsers(dest="impact_command", required=True)
    explain = impact_commands.add_parser(
        "explain",
        help="join one PlanCheck one-hop result to source locations",
    )
    explain.add_argument("--check", type=Path, required=True)
    explain.add_argument("--baseline-graph", type=Path, required=True)
    explain.add_argument("--realized-graph", type=Path, required=True)
    explain.add_argument(
        "--target",
        action="append",
        dest="targets",
        default=[],
        help="limit evidence to one PATH:SYMBOL target; repeat for several targets",
    )
    analyze = impact_commands.add_parser(
        "analyze",
        help="compile direct impact from one Git baseline to the working tree",
    )
    add_root(analyze)
    analyze.add_argument(
        "--base",
        default="HEAD",
        help="baseline Git revision; defaults to HEAD",
    )
    analyze.add_argument(
        "--target",
        action="append",
        dest="targets",
        required=True,
        help="analyze one PATH:SYMBOL target; repeat for several targets",
    )
    analyze.add_argument("--artifact-root", type=Path)
    analyze.add_argument("--cache-root", type=Path)
    analyze.add_argument("--codeql-executable", type=Path)
    analyze.add_argument("--query-pack", type=Path)
    return parser
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/cli.py:_operation_and_payload -->
```python contract-target
def _operation_and_payload(
    arguments: argparse.Namespace,
) -> tuple[OperationName, dict[str, Any]]:
    """Map parsed command arguments onto one API operation."""
    values = vars(arguments).copy()
    command = values.pop("command")
    values.pop("json_output")
    if command == "impact":
        command = f"impact-{values.pop('impact_command')}"
    if command == "knowledge":
        knowledge_command = values.pop("knowledge_command")
        if knowledge_command == "refresh":
            values["heads"] = values.pop("head")
            command = "knowledge-refresh"
        else:
            command = values.pop("kind").replace("_", "-")
    mapping: dict[str, OperationName] = {
        "validate-stage": "validate_stage",
        "validate-resolved-stage": "validate_resolved_stage",
        "validate-run": "validate_run_spec",
        "freeze-run": "freeze_run",
        "preflight": "preflight",
        "execute-stage": "execute_stage",
        "run": "run",
        "run-many": "run_many",
        "catalog-refresh": "catalog_refresh",
        "search-runs": "search_runs",
        "search-artifacts": "search_artifacts",
        "search-measurements": "search_measurements",
        "search-benchmarks": "search_benchmarks",
        "knowledge-refresh": "knowledge_refresh",
        "search-primitives": "search_primitives",
        "search-assignments": "search_assignments",
        "search-modulations": "search_modulations",
        "search-effects": "search_effects",
        "search-impacts": "search_impacts",
        "search-diagnostics": "search_diagnostics",
        "search-assertions": "search_assertions",
        "search-retrieval-judgments": "search_retrieval_judgments",
        "search-similar": "search_similar",
        "publish-ontology": "publish_ontology",
        "publish-assignment": "publish_assignment",
        "publish-modulation": "publish_modulation",
        "publish-effect": "publish_effect",
        "publish-impact-policy": "publish_impact_policy",
        "publish-impact": "publish_impact",
        "publish-diagnostic": "publish_diagnostic",
        "publish-assertion": "publish_assertion",
        "publish-vector": "publish_vector",
        "publish-retrieval-judgment": "publish_retrieval_judgment",
        "retry": "retry",
        "execute-benchmark": "execute_benchmark",
        "restore": "restore",
        "plan-diff": "plan_diff",
        "lineage": "lineage",
        "status": "status",
        "compare-runs": "compare_runs",
        "verify-run": "verify_run",
        "verify-benchmark": "verify_benchmark",
        "verify-pointer": "verify_pointer",
        "schema": "get_schema",
        "capabilities": "get_capabilities",
        "init": "init_project",
        "impact-explain": "explain_impact",
        "impact-analyze": "analyze_impact",
    }
    operation = mapping[command]
    if operation == "restore":
        reference = values.pop("run_reference")
        values["run_reference"] = (
            {"kind": "viper_cloud_uri", "uri": reference}
            if reference.startswith("viper://")
            else {"kind": "local_path", "path": reference}
        )
        selectors = []
        for stage_id, artifact_name in values.pop("artifacts"):
            selectors.append({"stage_id": stage_id, "artifact_name": artifact_name})
        values["artifacts"] = selectors
        values["repository_root"] = values.pop("root")
    trusted = values.pop("trust_source", None)
    if trusted is not None:
        values["trusted_source_repositories"] = trusted
    return operation, values
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/cli.py:_human_success -->
```python contract-target
def _human_success(result: SuccessModel) -> str:
    """Render one concise human result for an API success."""
    if result.operation == "validate_stage":
        return f"valid {getattr(result, 'stage_kind')} stage"
    if result.operation == "validate_resolved_stage":
        return f"valid resolved {getattr(result, 'stage_kind')} stage"
    if result.operation == "validate_run_spec":
        return "valid run plan"
    if result.operation == "freeze_run":
        files = getattr(result, "files")
        return f"froze run {getattr(result, 'run_id')} in {len(files)} files"
    if result.operation == "preflight":
        checks = getattr(result, "checks")
        failures = sum(check.status == "failure" for check in checks)
        return (
            "preflight ready"
            if failures == 0
            else f"preflight found {failures} failures"
        )
    if result.operation == "execute_stage":
        artifacts = getattr(result, "artifacts")
        count = sum(
            1 if artifact.kind == "file" else len(artifact.members)
            for artifact in artifacts.values()
        )
        return (
            f"executed stage {getattr(result, 'stage_id')} and identified {count} files"
        )
    if result.operation == "run":
        return f"completed and verified run {getattr(result, 'run_id')}"
    if result.operation == "run_many":
        runs = getattr(result, "result").runs
        failures = sum(run.status == "failed" for run in runs)
        return f"completed {len(runs)} runs with {failures} failures"
    if result.operation == "catalog_refresh":
        refreshed = getattr(result, "result")
        return f"cataloged {refreshed.accepted} sources; rejected {refreshed.rejected}"
    if result.operation == "knowledge_refresh":
        refreshed = getattr(result, "result")
        return f"cataloged {refreshed.accepted} knowledge records"
    if result.operation.startswith("search_"):
        page = getattr(result, "page")
        return f"returned {len(page.items)} catalog results"
    if result.operation.startswith("publish_"):
        publication = getattr(result, "publication")
        return f"published knowledge record {publication.record.sha256}"
    if result.operation == "retry":
        return (
            f"completed attempt {getattr(result, 'attempt_id')} for run "
            f"{getattr(result, 'run_id')}"
        )
    if result.operation == "execute_benchmark":
        benchmark = getattr(result, "result")
        return (
            f"benchmark {benchmark.status}: confirmation attempt "
            f"{benchmark.confirmation.stored_at.path}"
        )
    if result.operation == "restore":
        restored = getattr(result, "result")
        file_count = sum(len(artifact.files) for artifact in restored.artifacts)
        return f"restored {file_count} verified files"
    if result.operation == "plan_diff":
        changes = getattr(result, "changes")
        if not changes:
            return "plans are identical"
        return "\n".join(f"{change.kind}: {change.path}" for change in changes)
    if result.operation == "lineage":
        return (
            f"verified lineage with {len(getattr(result, 'nodes'))} nodes and "
            f"{len(getattr(result, 'edges'))} edges"
        )
    if result.operation == "status":
        state = getattr(result, "state")
        entries = getattr(result, "entry_count")
        return f"attempt state {state or 'empty'} after {entries} journal entries"
    if result.operation == "compare_runs":
        changes = getattr(result, "changes")
        if not changes:
            return "verified runs are identical"
        return "\n".join(f"{change.kind}: {change.path}" for change in changes)
    if result.operation == "verify_run":
        return f"verified run {getattr(result, 'run_id')}"
    if result.operation == "verify_benchmark":
        return f"verified benchmark result {getattr(result, 'benchmark_status')}"
    if result.operation == "verify_pointer":
        return f"verified artifact with {getattr(result, 'file_count')} files"
    if result.operation == "get_schema":
        return result.model_dump_json(indent=2)
    if result.operation == "init_project":
        return f"created project at {getattr(result, 'project_root')}"
    if result.operation == "explain_impact":
        evidence = getattr(result, "evidence")
        if not evidence:
            return "no direct dependency evidence"
        return "\n".join(
            f"{item.state} {item.kind}: "
            f"{item.dependent.path}:{item.dependent.symbol} -> "
            f"{item.target.path}:{item.target.symbol} "
            f"at {item.use_path}:{item.use_line}"
            for item in evidence
        )
    if result.operation == "analyze_impact":
        evidence = getattr(result, "evidence")
        if not evidence:
            return "no direct dependency evidence"
        return "\n".join(
            f"{item.state} {item.kind}: "
            f"{item.dependent.path}:{item.dependent.symbol} -> "
            f"{item.target.path}:{item.target.symbol} "
            f"at {item.use_path}:{item.use_line}"
            for item in evidence
        )
    capabilities = getattr(result, "operations")
    return "\n".join(capabilities)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/mcp.py:READ_OPERATIONS -->
```python contract-target
READ_OPERATIONS: tuple[OperationName, ...] = (
    "compare_runs",
    "get_capabilities",
    "get_schema",
    "lineage",
    "plan_diff",
    "search_artifacts",
    "search_assertions",
    "search_assignments",
    "search_benchmarks",
    "search_diagnostics",
    "search_effects",
    "search_impacts",
    "search_measurements",
    "search_modulations",
    "search_primitives",
    "search_retrieval_judgments",
    "search_runs",
    "search_similar",
    "status",
    "verify_benchmark",
    "verify_pointer",
    "verify_run",
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=src/viper/mcp.py:EXECUTION_OPERATIONS -->
```python contract-target
EXECUTION_OPERATIONS: tuple[OperationName, ...] = (
    "catalog_refresh",
    "execute_benchmark",
    "preflight",
    "knowledge_refresh",
    "publish_assertion",
    "publish_assignment",
    "publish_diagnostic",
    "publish_effect",
    "publish_impact",
    "publish_impact_policy",
    "publish_modulation",
    "publish_ontology",
    "publish_retrieval_judgment",
    "publish_vector",
    "restore",
    "retry",
    "run",
    "run_many",
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:DeclaredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:OntologySpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:PrimitiveRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:PrimitiveSpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:RunKnowledgeTarget -->
```python contract-target
from viper.knowledge import (
    DeclaredPrimitiveAssignment,
    DiagnosticVectorView,
    KnowledgeVector,
    OntologySpec,
    PrimitiveRef,
    PrimitiveSpec,
    RetrievalJudgment,
    RunKnowledgeTarget,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_protocol.py:DiagnosticVectorView -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_protocol.py:KnowledgeVector -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_protocol.py:RetrievalJudgment -->
```python contract-target
from viper.knowledge import (
    DeclaredPrimitiveAssignment,
    DiagnosticVectorView,
    KnowledgeVector,
    OntologySpec,
    PrimitiveRef,
    PrimitiveSpec,
    RetrievalJudgment,
    RunKnowledgeTarget,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:LocalFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:ResolvedRunRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_protocol.py:SnapshotFileRef -->
```python contract-target
from viper.references import (
    LocalFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_protocol.py:ResolvedFileRef -->
```python contract-target
from viper.references import (
    LocalFileRef,
    ResolvedFileRef,
    ResolvedRunRef,
    SnapshotFileRef,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_protocol.py:test_knowledge_vectors_preserve_view_identity -->
```python contract-target
def test_knowledge_vectors_preserve_view_identity() -> None:
    """Round-trip one fixed-width vector and reviewed relevance judgment."""
    created = datetime(2026, 1, 1, tzinfo=UTC)
    view = DiagnosticVectorView(
        view_id="diagnostic-v1",
        version="1",
        metric_ids=("loss",),
        dimensions=1,
    )
    source = ResolvedFileRef(
        sha256=SHA_A,
        bytes=10,
        stored_at=LocalFileRef(commit=SHA_B, path="knowledge/signature.yaml"),
    )
    vector = KnowledgeVector(
        view=view,
        source=source,
        values=(0.5,),
        created_at=created,
    )
    first = ResolvedFileRef(
        sha256="c" * 64,
        bytes=10,
        stored_at=LocalFileRef(commit="d" * 64, path="knowledge/vector-1.yaml"),
    )
    second = ResolvedFileRef(
        sha256="e" * 64,
        bytes=10,
        stored_at=LocalFileRef(commit="f" * 64, path="knowledge/vector-2.yaml"),
    )
    judgment = RetrievalJudgment(
        query_vector=first,
        candidate_vector=second,
        aspects=("diagnostic",),
        relevance=3,
        reviewed_by="reviewer",
        reviewed_at=created,
    )

    assert KnowledgeVector.model_validate_json(vector.model_dump_json()) == vector
    assert RetrievalJudgment.model_validate_json(
        judgment.model_dump_json()
    ) == judgment

    with pytest.raises(ValueError, match="width differs"):
        KnowledgeVector(
            view=view,
            source=source,
            values=(0.5, 0.6),
            created_at=created,
        )
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:AssignmentQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:DeclaredPrimitiveAssignment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:DiagnosticComponent -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:DiagnosticSignature -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:DiagnosticVectorView -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:KnowledgeVector -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:OntologySpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:PrimitiveQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:PrimitiveRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:PrimitiveSpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:RetrievalJudgment -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:RetrievalJudgmentQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:RunKnowledgeTarget -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:SimilarityQuery -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:diagnostic_component_sha256 -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:knowledge -->
```python contract-target
from viper.knowledge import (
    AssignmentQuery,
    DeclaredPrimitiveAssignment,
    DiagnosticComponent,
    DiagnosticSignature,
    DiagnosticVectorView,
    KnowledgeVector,
    OntologySpec,
    PrimitiveQuery,
    PrimitiveRef,
    PrimitiveSpec,
    RetrievalJudgment,
    RetrievalJudgmentQuery,
    RunKnowledgeTarget,
    SimilarityQuery,
    diagnostic_component_sha256,
    knowledge,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:GitFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:LocalFileRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:LocalStageResultSnapshotRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:ResolvedRunRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:ResolvedRunSpecRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:ResolvedStageRef -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_inspection.py:SnapshotFileRef -->
```python contract-target
from viper.references import (
    GitFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageRef,
    SnapshotFileRef,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:ResolvedFileRef -->
```python contract-target
from viper.references import (
    GitFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    ResolvedFileRef,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedStageRef,
    SnapshotFileRef,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_inspection.py:test_knowledge_retrieval_keeps_exact_indexes_authoritative -->
```python contract-target
def test_knowledge_retrieval_keeps_exact_indexes_authoritative(
    tmp_path: Path,
) -> None:
    """Filter exact records before ranking vectors inside one declared view."""
    (tmp_path / "viper.toml").write_text("[project]\nschema_version = 1\n")
    store = knowledge(root=tmp_path)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    ontology = OntologySpec(
        ontology_id="viper-core",
        version="1",
        primitives=(
            PrimitiveSpec(
                primitive_id="gated-recurrence",
                dimension="model-family",
                label="Gated recurrence",
                definition="A recurrent state transition with learned gates.",
            ),
        ),
        created_at=created,
    )
    store.publish_ontology(ontology)
    run = ResolvedRunRef(
        sha256="a" * 64,
        bytes=10,
        stored_at=LocalFileRef(commit="b" * 64, path="runs/final.yaml"),
    )
    assignment = DeclaredPrimitiveAssignment(
        target=RunKnowledgeTarget(run=run),
        primitive=PrimitiveRef(
            ontology_id=ontology.ontology_id,
            ontology_version=ontology.version,
            primitive_id=ontology.primitives[0].primitive_id,
        ),
        assigned_by="researcher",
        assigned_at=created,
    )
    store.publish_assignment(assignment)
    first_components = (
        DiagnosticComponent(
            metric_id="loss",
            measurement=ResolvedFileRef(
                sha256="c" * 64,
                bytes=10,
                stored_at=LocalFileRef(
                    commit="d" * 64,
                    path="measurements/first.json",
                ),
            ),
            value=1.0,
        ),
    )
    second_components = (
        DiagnosticComponent(
            metric_id="loss",
            measurement=ResolvedFileRef(
                sha256="e" * 64,
                bytes=10,
                stored_at=LocalFileRef(
                    commit="f" * 64,
                    path="measurements/second.json",
                ),
            ),
            value=2.0,
        ),
    )
    first_signature = store.publish_signature(
        DiagnosticSignature(
            run=run,
            stage_id="train",
            components=first_components,
            component_sha256=diagnostic_component_sha256(first_components),
            created_at=created,
        )
    )
    second_signature = store.publish_signature(
        DiagnosticSignature(
            run=run,
            stage_id="eval",
            components=second_components,
            component_sha256=diagnostic_component_sha256(second_components),
            created_at=created,
        )
    )
    view = DiagnosticVectorView(
        view_id="diagnostic-v1",
        version="1",
        metric_ids=("loss",),
        dimensions=1,
    )
    first = store.publish_vector(
        KnowledgeVector(
            view=view,
            source=first_signature.record,
            values=(1.0,),
            created_at=created,
        )
    )
    second = store.publish_vector(
        KnowledgeVector(
            view=view,
            source=second_signature.record,
            values=(-1.0,),
            created_at=created,
        )
    )
    store.publish_retrieval_judgment(
        RetrievalJudgment(
            query_vector=first.record,
            candidate_vector=second.record,
            aspects=("diagnostic",),
            relevance=2,
            reviewed_by="reviewer",
            reviewed_at=created,
        )
    )

    catalog = Catalog(tmp_path)
    catalog.refresh()
    records = catalog.knowledge
    primitive_page = records.primitives(
        PrimitiveQuery(primitive_ids=("gated-recurrence",))
    )
    assert tuple(item.label for item in primitive_page.items) == (
        "Gated recurrence",
    )
    assert records.assignments(
        AssignmentQuery(origins=("declared",))
    ).items[0].record.value == assignment

    similar = records.similar(
        SimilarityQuery(
            view_id=view.view_id,
            view_version=view.version,
            values=(1.0,),
        )
    )
    assert similar.items[0].vector == first.record
    assert similar.items[0].distance == 0.0
    judgments = records.retrieval_judgments(
        RetrievalJudgmentQuery(
            view_ids=(view.view_id,),
            minimum_relevance=2,
        )
    )
    assert len(judgments.items) == 1
    assert records.similar(
        SimilarityQuery(
            view_id="another-view",
            view_version="1",
            values=(1.0,),
        )
    ).items == ()
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:HANDLER_REGISTRY -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:REQUEST_REGISTRY -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:CapabilitiesRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:CatalogRefreshRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:LocalRunPath -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:OperationName -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:RestoreRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:RunManyRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:SchemaRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:SearchRunsRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:StatusRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:SuccessModel -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:ValidateStageRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:ViperFailure -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:catalog_refresh -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:dispatch -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:get_capabilities -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:get_schema -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:restore_artifacts -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:result_json_bytes -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:run_many -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:search_runs -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:status -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=update target=tests/test_api.py:validate_stage -->
```python contract-target
from viper.api import (
    HANDLER_REGISTRY,
    REQUEST_REGISTRY,
    CapabilitiesRequest,
    CatalogRefreshRequest,
    KnowledgeRefreshRequest,
    KnowledgeSearchRequest,
    LocalRunPath,
    OperationName,
    PublishKnowledgeRequest,
    RestoreRequest,
    RunManyRequest,
    SchemaRequest,
    SearchRunsRequest,
    StatusRequest,
    SuccessModel,
    ValidateStageRequest,
    ViperFailure,
    catalog_refresh,
    dispatch,
    get_capabilities,
    get_schema,
    knowledge_refresh,
    publish_ontology,
    restore_artifacts,
    result_json_bytes,
    run_many,
    search_primitives,
    search_runs,
    status,
    validate_stage,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:KnowledgeRefreshRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:KnowledgeSearchRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:PublishKnowledgeRequest -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:knowledge_refresh -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:publish_ontology -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:search_primitives -->
```python contract-target
from viper.api import (
    HANDLER_REGISTRY,
    REQUEST_REGISTRY,
    CapabilitiesRequest,
    CatalogRefreshRequest,
    KnowledgeRefreshRequest,
    KnowledgeSearchRequest,
    LocalRunPath,
    OperationName,
    PublishKnowledgeRequest,
    RestoreRequest,
    RunManyRequest,
    SchemaRequest,
    SearchRunsRequest,
    StatusRequest,
    SuccessModel,
    ValidateStageRequest,
    ViperFailure,
    catalog_refresh,
    dispatch,
    get_capabilities,
    get_schema,
    knowledge_refresh,
    publish_ontology,
    restore_artifacts,
    result_json_bytes,
    run_many,
    search_primitives,
    search_runs,
    status,
    validate_stage,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:KnowledgeRecordEnvelope -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:OntologySpec -->
<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:PrimitiveSpec -->
```python contract-target
from viper.knowledge import (
    KnowledgeRecordEnvelope,
    OntologySpec,
    PrimitiveSpec,
)
```

<!-- contract-target: requirements=EKP-03,EKP-04 block=P17-EKP-01 action=add target=tests/test_api.py:test_knowledge_operations_match_python_cli_and_mcp -->
```python contract-target
def test_knowledge_operations_match_python_cli_and_mcp(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route one exact knowledge query through every public surface."""
    monkeypatch.setattr("viper.api.resolve_root", lambda root: root.resolve())
    (tmp_path / "viper.toml").write_text("[project]\nschema_version = 1\n")
    ontology = OntologySpec(
        ontology_id="viper-core",
        version="1",
        primitives=(
            PrimitiveSpec(
                primitive_id="gated-recurrence",
                dimension="model-family",
                label="Gated recurrence",
                definition="A recurrent state transition with learned gates.",
            ),
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    published = publish_ontology(
        PublishKnowledgeRequest(
            root=tmp_path,
            record=KnowledgeRecordEnvelope(
                record_kind="ontology",
                value=ontology,
            ),
        )
    )
    knowledge_refresh(KnowledgeRefreshRequest(root=tmp_path))
    query = {"primitive_ids": ["gated-recurrence"]}
    python_result = search_primitives(
        KnowledgeSearchRequest(root=tmp_path, query=query)
    )

    assert main(
        [
            "--json",
            "knowledge",
            "search",
            "search_primitives",
            "--root",
            str(tmp_path),
            "--query",
            json.dumps(query),
        ]
    ) == 0
    cli_result = json.loads(capsys.readouterr().out)
    mcp_result = call_tool(
        tmp_path,
        "read",
        "search_primitives",
        {"query": query},
    )

    assert published.publication.record.sha256
    assert cli_result["page"] == python_result.page.model_dump(mode="json")
    assert mcp_result.structured_content["page"] == cli_result["page"]
    read_tools = {tool.name for tool in tool_registry("read")}
    execute_tools = {tool.name for tool in tool_registry("execute")}
    assert "search_primitives" in read_tools
    assert "publish_ontology" not in read_tools
    assert "publish_ontology" in execute_tools
```
