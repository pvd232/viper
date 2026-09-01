# Research memory roadmap

VIPER's long-term research memory should begin with verified experiments, add
versioned scientific labels, and derive comparisons within explicit contexts.
The deterministic foundation now belongs to the active contract migration.
Learned representations, literature ingestion, outcome models, and continual
learning remain later research work.

## 1. Status

**Status:** active foundation with deferred learned layers.

The current migration supplies three prerequisites:

```text
immutable run evidence
-> searchable provenance catalog
-> MCP access to exact queries and operations
```

[`system-impact-compiler.md`](system-impact-compiler.md) supports development of
those layers. It compares VIPER source revisions and reports affected code,
contracts, and tests. A separate experiment graph represents a user's frozen
plans.

[`experiment-knowledge-primitives.md`](experiment-knowledge-primitives.md)
adds the fourth layer in Phases 16 and 17:

```text
versioned ontology and assignments
-> controlled modulations and paired effects
-> diagnostic signatures and evidence-backed journal assertions
-> exact graph filters and optional vector indexes
```

The learned work in Sections 8 and 9 begins after these four layers pass their
acceptance tests and produce reviewed training and evaluation records.

## 2. Intended use

The system should help an agent answer questions such as:

- Which tried architectures duplicate an earlier experiment?
- Which loss families helped this task under comparable data and compute?
- Which embedding topologies failed repeatedly for this domain?
- Which untested combinations remain plausible?
- Which recent papers introduce a relevant method or contradict a stored
  assumption?

The system should return the experiments, measurements, and papers behind each
answer. Every label and generated summary remains attached to those sources.

## 3. Evidence layers

The knowledge graph should preserve five separate layers:

| Layer | Contents | Authority |
| --- | --- | --- |
| Protocol evidence | Runs, stages, inputs, artifacts, parameters, metrics, benchmarks, environments, and seeds | Immutable VIPER records |
| Catalog facts | Searchable normalized rows and lineage edges | Rebuildable projection of protocol evidence |
| Declared scientific labels | Functional families, topology labels, loss terms, data transformations, and experiment modulations supplied by the researcher | Versioned controlled vocabulary plus authored assignments |
| Derived findings | Effect estimates, uncertainty, comparable groups, failures, and exclusions | Recomputable analysis over catalog facts and labels |
| Literature evidence | Papers, claims, methods, datasets, metrics, code links, and publication relationships | Versioned primary-source records |

An agent can combine the layers in an answer. Storage and verification keep
their authority separate.

## 4. Experiment structure graph

VIPER should derive a canonical graph from each frozen experiment protocol.
The compiler reads `RunSpec`, every referenced stage specification, artifact
declarations, input references, metric definitions, environment identity, and
reproducibility settings. The frozen protocol supplies the graph input.

The graph needs typed nodes and edges:

```text
run
├── contains -> stage
├── selects -> variant and replicate
└── uses -> environment and reproducibility settings

stage
├── consumes -> input root or prior artifact
├── produces -> artifact
├── measures -> metric
└── optimizes -> objective
```

Comparison occurs in three steps:

1. Exact protocol identity detects identical frozen plans.
2. Typed, labeled graph isomorphism detects plans with the same structure after
   irrelevant identifier renaming.
3. A deterministic graph edit script lists added, removed, and changed nodes,
   edges, fields, and byte-addressed definitions for plans that differ.

The initial edit cost is unweighted. Each added, removed, or changed typed item
counts once. The report keeps the complete edit list beside the count. The
count measures structural distance. Controlled outcomes and diagnostics
measure scientific impact.

The graph edit becomes the observed change attached to a controlled
modulation:

```text
baseline frozen graph + candidate frozen graph
-> canonical correspondence
-> exact graph edit
-> matched diagnostic and objective changes
-> primitive assignments that explain the scientific meaning
```

This adds evidence beneath the primitive ontology. The graph proves which
protocol structure changed. Primitive assignments label that change as a model
family, embedding topology, loss family, optimizer family, or another
scientific concept. Diagnostic and outcome records show what happened after
the change.

The experiment graph requires a separate contract before implementation. That
contract must define its exact node, edge, correspondence, edit, and verifier
models. It must also define which identifier changes count as irrelevant and
which fields remain part of experiment identity.

## 5. Experiment primitives

The first ontology should use a small set of versioned primitives. Each label
needs a stable ID, definition, version, parent relationships, and examples.

Candidate dimensions include:

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

The active primitive contract defines the exact ontology, target, and
assignment models. Assignments distinguish three origins:

```text
declared
-> the researcher or authoring program assigned the label

inferred
-> a classifier assigned the label with model, version, and confidence

reviewed
-> a person accepted or corrected an inferred assignment
```

This separation lets the system improve its classifiers while preserving the
historical experiment record.

## 6. Experiment modulations and impact

An experiment modulation changes one or more primitives between comparable
runs. The active primitive contract stores the changed fields, comparison
context, paired measurements, numeric effect, uncertainty, and versioned
impact policy.

`high`, `medium`, and `low` require a stated context. An impact classification
needs these inputs:

```text
changed primitive
baseline and candidate runs
objective metric and direction
dataset and split identities
model scale
compute budget
replicate distribution
effect estimate
uncertainty interval
impact thresholds and their version
```

The system derives the categorical impact from the numeric estimate and one
versioned threshold policy. Another task, dataset, scale, or objective can
produce a different impact classification for the same modulation.

Negative and null results remain first-class evidence. They support duplicate
avoidance and bound search regions that already performed poorly.

## 7. Non-duplicative search

Search should reject an experiment as a duplicate only when its complete
execution identity matches a prior verified run or when an explicit
equivalence rule says the difference is irrelevant to the active question.

The search system can use three filters in order:

1. Exact protocol identity removes byte-for-byte duplicate plans and stage
   reuse candidates.
2. Ontology identity removes experiments with the same declared primitive
   configuration under the same data and evaluation conditions.
3. Similarity retrieval ranks nearby experiments for agent review.

The third filter suggests candidates for review. An exact identity or explicit
equivalence rule performs rejection.

The active primitive contract implements this order through exact catalog
fields, graph edges, and one optional HNSW index per vector view.

An architecture becomes clearly unpromising only after a versioned exclusion
rule evaluates enough comparable evidence. The rule must state its minimum
replicate count, effect threshold, uncertainty limit, data scope, compute
scope, and expiration or review condition.

## 8. Literature ingestion

Literature records should preserve:

```text
paper identity and version
authors and publication venue
retrieval time
primary-source URL
code and dataset links
method primitives
reported metrics and conditions
claim text or normalized claim
supporting table, figure, or section
citations and follow-up relationships
```

Paper claims and VIPER observations remain separate node types. A paper can
motivate a run. A verified run can support or contradict a paper claim under
its own conditions.

The ingestion pipeline should poll primary sources, deduplicate versions, run
label classifiers, and queue uncertain assignments for review. A retrieval
index can expose the paper text and graph neighborhood to an agent.

## 9. Retrieval and continual learning

The first agent memory should use retrieval over the catalog, ontology graph,
derived findings, and literature records. Retrieval preserves citations and
lets a user inspect the evidence before acting.

Continual learning should consume curated, versioned training examples derived
from verified agent decisions and experiment outcomes. Reviewed examples
replace an unreviewed stream of generated notes. Each training example needs
its source evidence, target behavior, acceptance result, and ontology version.

This ordering keeps the objective tractable:

```text
retrieve exact relevant evidence
-> propose one bounded experiment
-> execute and verify it
-> update derived findings
-> review successful decision traces
-> train a domain-specific policy or classifier
```

## 10. Planned interfaces

Phases 16 and 17 add graph and semantic queries through the same Python, CLI,
and MCP surfaces:

```text
find experiments by primitive labels
compare one modulation across matched runs
retrieve negative results in one search region
return evidence for one proposed experiment
record reviewed labels and finding policies
```

Knowledge publication uses execute access. Search uses read access. Literature
queries begin after the literature records have their own contract.

## 11. Build sequence

### Active in the current migration

1. Finish an experiment-structure graph contract and add it to the master
   checklist before implementation.
2. Compile frozen plans into canonical typed graphs and deterministic edit
   scripts.
3. Define the versioned primitive ontology and exact assignment records.
4. Define controlled `Modulation`, paired `EffectEstimate`, `ImpactPolicy`, and
   `ImpactAssessment` records.
5. Extract deterministic `DiagnosticSignature` records.
6. Add typed `JournalAssertion` records with immutable evidence links.
7. Build exact filters and graph traversal.
8. Keep diagnostic vectors and journal-text vectors in separate views.
9. Add one optional HNSW index per vector view.
10. Record reviewed retrieval judgments against exact query and candidate
   vectors.
11. Expose publication and search through Python, typed API, CLI, and MCP.

### Deferred until reviewed evidence exists

1. Train and evaluate primitive classifiers from reviewed assignments.
2. Train aspect-aware and multi-view representations against held-out retrieval
   judgments.
3. Add primary-source literature and claim records.
4. Train context-conditioned outcome models on controlled comparison records.
5. Evaluate experiment acquisition against duplicate rejection, proposal
   quality, cost, and verified outcome improvement.
6. Train domain-specific policies from reviewed decision traces.

Each deferred step starts only after its contract names the immutable training
set, held-out evaluation set, metric, baseline, and acceptance threshold.

## 12. Remaining platform work

The following platform capabilities also remain outside the current migration:

- Coordinator recovery from the last sealed stage after process or host loss.
- Typed run and stage events, event cursors, cancellation, and heartbeats.
- Filesystem, network, secret, CPU, GPU, memory, and time permissions for
  unattended agents.
- Reachability-based retention and garbage collection.
- Local and cloud archive compression with verified restore.
- Cross-provider storage migration and mirroring.
- Adaptive search, Bayesian optimization, and distributed scheduling.
- Learned primitive classifiers, vector representations, outcome models,
  acquisition policies, and continual-learning policies.

These capabilities can consume the immutable records, catalog, and MCP layer.
They preserve the evidence model defined by the current contracts.

## 13. Research basis

The [CoALA framework](https://arxiv.org/abs/2309.02427) separates agent memory
into working, episodic, semantic, and procedural forms. VIPER's verified runs
fit episodic evidence; the ontology and derived findings fit semantic memory;
reviewed execution strategies fit procedural memory.

[Agent Workflow Memory](https://proceedings.mlr.press/v267/wang25bx.html)
extracts reusable workflows from prior trajectories. VIPER can supply verified
trajectories and results alongside conversational context.

[ResearchGym](https://arxiv.org/abs/2602.15112) treats research agents as
systems that should be evaluated on complete research tasks. VIPER's proposed
catalog and experiment graph can provide controlled tasks, exact evidence, and
measurable outcomes for that evaluation.

These papers motivate the memory and evaluation layers. Controlled experiments
after implementation must measure whether the proposed ontology or
continual-learning system improves a given domain.
