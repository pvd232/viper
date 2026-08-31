# VIPER System-Impact Compiler
## Formal Specification, Phase 0 Implementation Baseline, and Research Program

**Status.** Research specification with an immediately implementable Phase 0 baseline.

**Purpose.** VIPER is intended to compile declarative software-change intent against a source-evidenced repository model, derive a complete set of represented implementation obligations before coding begins, decompose those obligations into bounded work units, and independently verify the resulting repository after implementation. Phase 0 establishes the smallest complete end-to-end system capable of testing that proposition. Later phases improve the formal model, semantic representation, decomposition objective, repair search, and selection policy without changing the core protocol.

---

## 1. Motivation and research objective

Repository-scale software changes fail differently from isolated coding tasks. A seemingly local request such as renaming `viper.file_artifact` to `viper.artifact` can propagate through implementation code, public exports, type references, tests, documentation, contract examples, serialization schemas, runtime registries, and downstream constructors. In a conventional agentic workflow, one agent is asked to discover these effects, decide what should change, perform the edits, run tests, and then decide whether the work is complete. This places impact discovery, planning, implementation, and completion judgment inside a single probabilistic reasoning loop.

VIPER separates those responsibilities. The system should transform a current repository and one or more explicit proposed changes into a complete, executable map of implementation obligations before implementation begins. Coding agents should receive bounded obligations rather than being asked to rediscover the global task from source. After implementation, the repository should be recompiled independently into the same structural representation and checked against the pre-implementation obligations.

At the highest level, the intended research protocol is

$$
R_0 \xrightarrow{\mathcal C} G_0
\xrightarrow{\{\Delta_i\}} B
\xrightarrow{P} T^*
\xrightarrow{\text{decompose / select}} \mathcal W
\xrightarrow{\text{implement}} R_1
\xrightarrow{\mathcal C} G_1
\xrightarrow{\text{verify}} \{\text{accept},\text{reject}\}.
$$

Here, $R_0$ is the current repository, $G_0$ is its compiled system graph, $\{\Delta_i\}$ is the set of proposed contract-owned changes, $B$ is the conservative represented impact closure, $P$ is a total disposition map over $B$, $T^*$ is an executable target specification, $\mathcal W$ is the bounded implementation work, $R_1$ is the implemented repository, and $G_1$ is the independently reconstructed post-implementation graph.

The core hypothesis is deliberately narrower than the full research program. A proposed change should be expanded into a conservative represented impact set, and every entity in that set should receive exactly one explicit disposition before coding begins:

$$
B = \operatorname{ImpactClosure}(G_0,\Delta),
$$

$$
P:B\rightarrow\{\mathrm{CHANGE},\mathrm{REMOVE},\mathrm{RETAIN}\},
$$

$$
\boxed{\operatorname{dom}(P)=B.}
$$

No affected represented entity may disappear from planning silently. Everything downstream is justified only if this first mechanism proves useful in practice.

---

## 2. Conceptual derivation

### 2.1 From “DAG 1 versus DAG 2” to a pre-implementation change compiler

The original intuition was to compare a graph of the current implemented system with a graph of the intended system and derive the implementation work from their difference. The important temporal constraint is that the intended representation must exist before implementation. A graph extracted from an already implemented candidate repository is useful for verification, but it cannot serve as the implementation plan that precedes the implementation.

Accordingly, the current repository must first be compiled into a system graph:

$$
R_0 \xrightarrow{\mathcal C} G_0.
$$

The proposed change is represented explicitly as one or more deltas $\Delta_1,\ldots,\Delta_k$. Their identities and provenance are preserved even when their effects overlap.

### 2.2 Why a delta does not generally determine a unique future graph

An early formulation assumed that the proposed delta could be applied directly to the baseline graph to obtain a single future graph:

$$
G^* = \operatorname{Apply}(G_0,\Delta).
$$

That is generally too strong. A contract can determine a required local semantic transformation without determining every downstream implementation choice. If `LocalArtifactStore.load(...) -> bytes` becomes `LocalArtifactStore.load(...) -> LoadedArtifact`, for example, a downstream `Runner.verify` may either propagate `LoadedArtifact` or unwrap `LoadedArtifact.data` and preserve its existing `bytes` interface. Both may satisfy the original change intent.

The logically prior object is therefore a target specification $T^*$ whose models are the admissible future graphs:

$$
\mathcal A(T^*) = \{G \mid G\models T^*\}.
$$

A singleton future graph is only the special case

$$
|\mathcal A(T^*)|=1.
$$

In general, implementation freedom should be preserved wherever the specification does not require a particular structural choice. Later phases may select a specific planned realization $G^*\in\mathcal A(T^*)$ when deterministic bounded execution requires one.

### 2.3 Four distinct jobs

The full system separates four jobs that should not be conflated:

$$
\textbf{Completeness:}\qquad \{\Delta_i\}\rightarrow B\rightarrow P,
$$

$$
\textbf{Decomposition:}\qquad P\rightarrow \operatorname{SCC}\rightarrow \Pi^*,
$$

$$
\textbf{Choice:}\qquad \Pi^*\rightarrow\{\mathcal R_i\}\rightarrow\{U_i^*\},
$$

$$
\textbf{Verification:}\qquad G^*\rightarrow R_1\rightarrow G_1.
$$

Phase 0 implements a deliberately simple version of all four jobs so that the end-to-end proposition can be tested before the research program expands.

---

# Phase 0 — Complete Change Planning and End-to-End Verification

Phase 0 is the implementation baseline and first kill gate. It is a complete executable protocol, not a collection of partial V0 subsections embedded across later research phases. Its purpose is to determine whether conservative impact closure, total disposition, bounded agent execution, and independent structural verification materially improve real repository changes. Learned embeddings, formal repair enumeration, and globally optimized partitioning are explicitly deferred.

## 3. Phase 0 success criterion

Given a current repository $R_0$ and an explicit proposed change $\Delta$, Phase 0 must:

1. compile $R_0$ into a deterministic baseline graph $G_0$;
2. derive a conservative represented affected set $B$;
3. assign exactly one explicit disposition to every member of $B$;
4. attach simple repository-aware context and coarse operation estimates;
5. condense dependency cycles into atomic scheduling units;
6. partition the work with a deterministic baseline heuristic;
7. resolve residual implementation choices within bounded candidate sets;
8. compile the selected work into PairBlocks;
9. execute those PairBlocks with coding agents;
10. reconstruct the implemented repository independently as $G_1$; and
11. reject a structurally incomplete implementation even when ordinary tests would otherwise pass.

The centerpiece is

$$
B=\operatorname{ImpactClosure}(G_0,\Delta),
$$

$$
P:B\rightarrow\{\mathrm{CHANGE},\mathrm{REMOVE},\mathrm{RETAIN}\},
$$

$$
\boxed{\operatorname{dom}(P)=B.}
$$

Phase 0 is successful if this protocol detects meaningful omissions or structural divergences that an ordinary strong coding-agent workflow misses often enough to justify further investment.

## 4. Baseline repository graph

Phase 0 should support only graph facts that can be extracted reliably. Let

$$
G_0=(V_0,E_0).
$$

The initial node classes are `File`, `Class`, `Function`, `Method`, `PublicSymbol`, `Test`, and `ContractRequirement`; `Field` may be included where extraction is straightforward. The initial typed relationships are `contains`, `imports`, `calls`, `constructs`, `typed_by`, `tests`, and `constrained_by`.

Every relationship must retain source evidence. Stable identities should be canonical and source-addressable, for example:

```text
file:src/viper/artifacts.py
class:src/viper/artifacts.py:ArtifactDraft
function:src/viper/api.py:artifact
test:tests/test_public_api.py:test_artifact_constructor
```

Stable identity is required for impact analysis, provenance, graph comparison, and post-implementation reconciliation. Dynamic relationships must not be guessed. Any unresolved runtime, reflective, registry, or dynamic-import relationship that matters to the graph should be represented explicitly as an `UnresolvedDependency` record. The Phase 0 proof is therefore conditional on the dependency relation actually represented by $G_0$.

## 5. Explicit Phase 0 change input

Phase 0 should not begin by building a natural-language contract compiler. The authoritative contract or specification is translated manually into a structured graph-facing delta:

```python
Delta(
    id="artifact-api",
    add=(...),
    remove=(...),
    update=(...),
    require=(...),
    forbid=(...),
)
```

For several simultaneous proposed changes, define the direct seed set

$$
S_{\Delta}=\bigcup_{i=1}^{k}S_{\Delta_i},
$$

while retaining per-entity provenance

$$
\operatorname{prov}(v)=\{\Delta_i\mid\Delta_i\leadsto v\}.
$$

The delta identifies graph nodes, relationships, or predicates whose semantics are intentionally changed. Contract-to-delta compilation is a later compiler stage and must not block Phase 0.

## 6. Conservative impact closure

Edges are oriented from dependent to dependency. Thus

$$
A\rightarrow B
$$

means that $A$ depends on $B$. A change to $B$ therefore causes $A$ to enter the reverse-reachable impact set. Define

$$
B=\operatorname{PredClosure}_{G_0}(S_{\Delta}).
$$

The closure should preserve both change provenance and witness paths. A representative record is:

```python
Impact(
    node_id="...",
    caused_by=("artifact-api",),
    paths=(...),
)
```

The reachability computation itself is deterministic.

### 6.1 Conditional soundness

Assume the represented dependency relation is conservative in the following sense: whenever changing represented entity $y$ can require reconsidering represented entity $x$, the graph contains a path

$$
x\rightarrow^* y.
$$

Under this assumption,

$$
\operatorname{Affected}(\Delta)\subseteq B.
$$

If an affected entity $x$ were not in $B$, conservativeness would imply a path $x\rightarrow^*s$ to some changed seed $s\in S_{\Delta}$. But membership in $B$ is defined exactly by the existence of such a path, yielding a contradiction. This theorem does not prove completeness of arbitrary Python dependency extraction; it states precisely what follows from a conservative represented relation.

### 6.2 Minimality of consideration

$B$ is the least predecessor-closed set containing $S_{\Delta}$. For every predecessor-closed set $B'$ satisfying

$$
S_{\Delta}\subseteq B',
$$

we have

$$
B\subseteq B'.
$$

This is minimality of the set that must be considered, not a claim that every member of $B$ must be edited.

## 7. Total disposition

The key distinction is

$$
\mathrm{affected}\neq\mathrm{must\ edit}.
$$

Every entity in the impact closure receives exactly one disposition:

$$
P:B\rightarrow\{\mathrm{CHANGE},\mathrm{REMOVE},\mathrm{RETAIN}\}.
$$

The accepted plan must satisfy

$$
\boxed{\forall v\in B,\ \exists!\,P(v)}
$$

or equivalently

$$
\boxed{\operatorname{dom}(P)=B.}
$$

An impacted test may legitimately be retained if its behavioral obligation remains correct. A compatibility alias may be removed. A constructor may change. The guarantee is not that the entire blast radius is edited; it is that no represented affected surface is omitted from planning.

### 7.1 Agent-assisted disposition generation

For each $v\in B$, the planning agent receives the original proposed change, the affected source span, nearby dependencies and dependents, relevant tests, relevant contracts, and sufficient source-backed context to understand the entity. It must return structured output:

```python
Disposition(
    node_id="...",
    action="change",  # change | remove | retain
    reason="...",
    required_postconditions=(...),
    forbidden_postconditions=(...),
    affected_tests=(...),
    confidence=...,
)
```

Coverage is checked independently of the agent:

```python
set(dispositions.keys()) == set(B)
```

and the planner rejects duplicate or contradictory dispositions. If $|B|=37$, the accepted plan contains exactly one disposition for all 37 represented affected entities. An omission is therefore a pre-implementation planning failure rather than a post-hoc implementation surprise.

## 8. Executable target specification

The baseline graph, delta, and total disposition map compile into an executable target specification:

$$
T^*=\operatorname{CompileTarget}(G_0,\{\Delta_i\},P).
$$

$T^*$ should express requirements such as `REQUIRE public symbol viper.artifact`, `FORBID public symbol viper.file_artifact`, preservation of artifact bundle behavior, required documentation relationships, and preservation predicates attached to `RETAIN` decisions. It defines the admissible future graph family

$$
\mathcal A=\{G\mid G\models T^*\}.
$$

Phase 0 does not assume that $\mathcal A$ is a singleton.

## 9. Simple repository-aware semantic context

Phase 0 needs repository-local semantic information, but it does not need a learned embedding system. For every $v\in B$, construct a structured context object from deterministic repository evidence and one concise agent-generated role summary:

```python
NodeContext(
    node_id="...",
    kind="method",
    language="python",
    public_api=False,
    native_code=False,
    cuda=False,
    generated=False,
    loc=42,
    fan_in=7,
    fan_out=3,
    test_count=4,
    contract_count=1,
    scc_id=None,  # populated after condensation when applicable
    role_summary="Internal artifact decoding helper.",
)
```

Everything other than `role_summary` should be derived from repository evidence whenever possible. The role summary should be generated from source, callers, dependencies, tests, and contracts. No vector database, custom embedding model, or learned graph encoder is required. Conceptually, this structured object is Phase 0's approximation to a repository-conditioned representation $e(v)$.

## 10. Coarse operation-conditioned estimates

Engineering cost attaches to an operation, not merely to a node. The relevant distinction is between, for example, `(CUDA kernel, RETAIN)` and `(CUDA kernel, CHANGE)`. For each planned operation $(v,P(v))$, Phase 0 records coarse ordinal estimates:

```python
OperationEstimate(
    effort=1,        # 1..5 for active work; 0 permitted for no implementation work
    risk=1,          # 1..5; 0 permitted when no mutation risk is introduced
    verification=1,  # 1..5
    rationale="...",
)
```

Representative values might be:

```text
custom CUDA kernel + CHANGE:
    effort        5
    risk          5
    verification  5

internal Python utility + CHANGE:
    effort        1
    risk          1
    verification  1

custom CUDA kernel + RETAIN:
    effort        0
    risk          0
    verification  1
```

These are agent estimates used as Phase 0 policy inputs, not formal truths. Their rationales and eventual observed outcomes must be logged so later stages can test and calibrate them.

## 11. SCC condensation

The affected graph may contain cycles. Compute its strongly connected components and condensation DAG:

$$
D_B=\operatorname{Condensation}(B).
$$

Each SCC is atomic for Phase 0 scheduling. Members of the same SCC must not be assigned to independent agents as though no cyclic coordination exists. Standard deterministic algorithms such as Tarjan's or Kosaraju's algorithm should be used, with stable component identifiers.

This is an execution property of the current work graph, not a requirement that future graphs preserve the same SCC structure. A later repair may legitimately break an existing dependency cycle.

## 12. Deterministic greedy partition baseline

Phase 0 does not solve the global graph-partitioning problem. Each SCC receives an approximate workload

$$
w(C)=\sum_{v\in C}\operatorname{effort}(v,P(v)).
$$

Dependency types receive fixed baseline communication weights, for example:

```text
public API / schema / type-contract edge    5
call / construction edge                    4
typed dependency                            3
import                                      2
test / documentation observation            1
```

These are explicitly heuristic constants. A deterministic greedy partitioner should keep high-cost edges internal where practical, approximately balance total effort, preserve SCC atomicity, respect the condensation-DAG execution order, and produce a small number of useful work groups. Its output is denoted

$$
\Pi_0=\{C_1,\ldots,C_m\},
$$

not $\Pi^*$, because no claim of global optimality is made in Phase 0.

## 13. Bounded implementation-choice resolution

A total disposition can still leave several valid implementations. Phase 0 should not enumerate the entire graph-repair universe. Instead, an implementation-planning agent generates a small candidate set inside each work component:

```text
candidate A
candidate B
candidate C
```

Each candidate must satisfy the hard obligations compiled from $P$ and $T^*$. Candidate reduction proceeds in a fixed order.

### 13.1 Hard validity

Reject any candidate that violates a delta, required postcondition, forbidden relationship, public invariant, test obligation, or contract obligation.

### 13.2 Least-change dominance

If candidate $U_a$ satisfies every hard obligation while making a strict subset of the changes made by candidate $U_b$, eliminate $U_b$.

### 13.3 Simple semantic preference

For surviving candidates, compare the affected operations using `NodeContext` and the coarse operation estimates. A candidate that rewrites a specialized CUDA kernel should not be preferred merely because it changes fewer graph nodes than an alternative confined to low-risk utility code. Phase 0 should not introduce a universal weighted objective for effort, risk, and verification burden.

### 13.4 Final selector agent

If multiple candidates remain, a final selector agent receives the original $\Delta$, all relevant `NodeContext` records, surviving candidate transformations, dependency consequences, operation estimates, tests and contracts, and the reasons earlier candidates were eliminated. Its task is narrow:

> Among these already-valid, non-dominated implementations, which is the best repository-local engineering choice?

The result must be structured:

```python
Selection(
    candidate_id="B",
    rationale=(...),
    decisive_factors=(...),
    confidence=...,
    unresolved_tradeoffs=(...),
)
```

The selector is not permitted to omit a member of $B$, override $\Delta$, waive a hard constraint, or silently invent additional affected surfaces. The formal layer determines what is complete and valid; the agent layer determines what is preferred among the admitted alternatives.

## 14. PairBlocks and bounded execution

Each selected partition is compiled into one or more executable `PairBlock`s containing owned obligations, source targets, originating deltas, required and forbidden postconditions, execution dependencies, tests, verification requirements, and expected effort:

```python
PairBlock(
    id="artifact-api",
    owned_nodes=(...),
    dispositions=(...),
    source_targets=(...),
    originating_deltas=(...),
    required_postconditions=(...),
    forbidden_postconditions=(...),
    depends_on=(...),
    tests=(...),
    estimated_effort=...,
)
```

PairBlocks are derived from the obligation graph rather than manually grouped by file name. Coding agents receive one PairBlock, the relevant source slice, and project instructions. Their job is to realize already-compiled obligations rather than rediscover the global task.

Execution follows the condensation and partition dependencies. If $A$ and $B$ feed $C$ while $D$ is independent, $A$, $B$, and $D$ may execute concurrently and $C$ begins when its predecessors complete. Phase 0 uses the graph as a scheduling constraint, not as a mandate to maximize raw concurrency.

## 15. Independent reconstruction and verification

After implementation, let $R_1$ denote the resulting repository. The observed graph must be reconstructed independently from the repository itself:

$$
R_1\xrightarrow{\mathcal C}G_1.
$$

$G_1$ must not be synthesized from agent reports or by mutating $G_0$ according to the plan. Independent reconstruction is required for meaningful conformance checking.

At minimum, Phase 0 acceptance requires

$$
G_1\models T^*.
$$

The verifier checks that required additions exist, required removals are absent, forbidden structures do not remain, required relationships exist, every `RETAIN` obligation still satisfies its preservation predicate, PairBlock gates pass, and required behavioral checks succeed. Structural verification and behavioral verification are distinct:

$$
G_1\models T^*\not\Rightarrow\text{arbitrary behavioral correctness},
$$

and

$$
\text{tests pass}\not\Rightarrow G_1\models T^*.
$$

A canonical Phase 0 failure case is a requested retirement of `viper.file_artifact` where an implementation correctly adds `viper.artifact` but leaves `file_artifact = artifact` as a compatibility alias. Ordinary tests may pass, but if $T^*$ requires that the retired public symbol not exist, then

$$
G_1\not\models T^*,
$$

and the implementation must be rejected.

## 16. Required telemetry

Phase 0 should record the data needed both for evaluation and for later learned models. For each run and obligation, record at least:

```text
Delta identity and source
impact-set size B
impact provenance / witness paths
NodeContext
disposition
predicted effort
predicted risk
predicted verification burden
selected candidate and selection rationale
actual changed files
actual changed symbols
actual changed LOC
agent tokens
wall-clock time
repair iterations
test failures
verification failures
cross-agent messages / tokens
verification time
final success or failure
```

This produces a future dataset of operation-conditioned repository observations rather than requiring a separate data-collection project before the semantic research can begin.

## 17. Phase 0 acceptance test

The first end-to-end acceptance test should use one real cross-cutting VIPER API change, such as retiring a public constructor and introducing its replacement. The test must:

1. compile $G_0$ from the baseline repository;
2. construct an explicit $\Delta$;
3. derive $B$;
4. generate exactly one disposition for every $v\in B$;
5. assert $\operatorname{dom}(P)=B$;
6. derive `NodeContext` for every affected entity;
7. assign coarse effort, risk, and verification estimates;
8. compute SCCs and the condensation DAG;
9. build deterministic work partitions;
10. select among at least two plausible implementation alternatives where the task naturally permits more than one;
11. compile PairBlocks;
12. execute the implementation;
13. independently compile $G_1$;
14. run behavioral gates; and
15. verify structural conformance.

The test should then deliberately leave one stale retired symbol or reference in an otherwise passing implementation. The structural verifier must reject it. This is the Phase 0 proof of value.

## 18. Phase 0 implementation order

Build the baseline in this order:

```text
1. Repository graph
2. Explicit Delta
3. Reverse impact closure
4. Total dispositions
5. NodeContext
6. Coarse operation estimates
7. SCC condensation
8. Deterministic greedy partition
9. Candidate implementation generation
10. Hard / least-change / simple semantic filtering
11. Final semantic selector agent
12. PairBlocks
13. Bounded implementation
14. Independent recompile
15. Conformance verifier
16. Telemetry
```

The ordering is intentional. Learned embeddings, graph-repair synthesis, and exact partition optimization should not precede an end-to-end working baseline.

## 19. Phase 0 non-goals

Phase 0 does not require custom repository embeddings, GNNs, learned effort models, learned risk models, learned edge-coupling models, exhaustive graph-repair enumeration, exact Pareto-front computation over all future graphs, global optimal partitioning, counterfactual future-change simulation, sophisticated multi-agent tournaments, or a unique singleton $G^*$.

These are research upgrades, not prerequisites for testing the central mechanism.

## 20. Kill gate and definition of Phase 0 success

Before investing in learned representations or formal repair synthesis, compare Phase 0 against a strong ordinary coding agent. Measure missed propagation surfaces, stale structures, unnecessary edits, test success, structural conformance, repair rounds, token cost, wall-clock time, and coordination overhead.

If

$$
\text{impact closure}
+
\text{total disposition}
+
\text{bounded work}
+
\text{independent verification}
$$

does not materially improve real repository changes, stop or substantially narrow the research program.

Phase 0 succeeds if it demonstrates that a local software-change specification can be expanded into a complete represented impact set, every affected represented surface can be dispositioned before coding, bounded agents can implement the resulting plan, and an independent verifier can detect an omitted propagation that ordinary test execution does not detect.

---

# Phase I — Formal Completeness and Richer Repository Semantics

Phase I generalizes the Phase 0 graph and turns its conditional guarantees into an explicit proof boundary. It does not change the total-disposition protocol; it improves the repository representation and the strength of the assumptions under which completeness is claimed.

## 21. Research repository graph

Let the research graph be

$$
G=(V,E,X),
$$

where $V$ contains represented repository entities, $E$ contains typed dependency or evidence relations, and $X$ contains source-evidenced semantic state attached to nodes and edges. The complete graph may include files, modules, classes, functions, methods, fields, parameters, public symbols, schemas, serialization surfaces, tests, assertions, contract requirements, documentation examples, runtime registrations, build targets, generated artifacts, external interfaces, and PairBlock obligations.

Possible relationship types include imports, calls, reads, writes, construction, typing, implementation, exposure, serialization, observation, testing, documentation, contract constraints, registration, dynamic resolution, generation, and general dependency. Each relationship must retain provenance sufficient to explain why it exists. Runtime-dependent relationships should be represented through explicit resolution attempts and observations rather than silently inferred.

The central limitation remains visible: no graph algorithm can recover a dependency the repository compiler fails to represent. Analysis receipts, unresolved dependencies, runtime-resolution observations, and source provenance therefore belong to the proof boundary rather than being treated as incidental metadata.

## 22. Multi-delta semantics

For $\Delta_1,\ldots,\Delta_k$, the compiler should distinguish disjoint, commuting, reinforcing, overlapping, and conflicting changes. The combined seed set may collapse cleanly for impact analysis,

$$
S_{\Delta}=\bigcup_i S_{\Delta_i},
$$

but provenance must remain attached to every affected obligation. Conflicting postconditions must be detected before repair synthesis or execution.

## 23. Formal target semantics

The combination of $G_0$, $\{\Delta_i\}$, and the complete disposition map $P$ compiles into

$$
T^*=\operatorname{CompileTarget}(G_0,\{\Delta_i\},P).
$$

$T^*$ is the authoritative set of structural constraints for the future repository. Its model set is

$$
\mathcal A(T^*)=\{G\mid G\models T^*\}.
$$

The target is intentionally constraint-based. A unique future graph is not required unless later selection policies or additional requirements reduce the admissible set to one member.

## 24. Proof obligations for completeness

### Theorem 1 — Impact soundness

Under conservative dependency extraction,

$$
\operatorname{Affected}(\Delta)\subseteq B.
$$

### Theorem 2 — Impact minimality

$B$ is the least predecessor-closed set containing $S_{\Delta}$.

### Theorem 3 — Plan completeness

For every accepted plan,

$$
\operatorname{dom}(P)=B
$$

and

$$
\forall v\in B,\ \exists!\,P(v).
$$

These theorems formalize the first research claim: all represented potentially affected entities are considered, and none can disappear from the plan silently.

---

# Phase II — Repository-Conditioned Semantic Representation and Calibrated Projections

Phase II replaces the crude Phase 0 context and ordinal estimates with a reusable repository-conditioned representation and separately calibrated operation-conditioned projections. The semantic layer remains downstream of formal completeness: it may influence decomposition and choice, but it cannot redefine the impact closure or waive a hard target constraint.

## 25. Persistent semantic state

For each node $v$, collect a source-evidenced bundle $X(v)$ containing source or signature information, comments and docstrings, node type, language, file role, public/private status, callers, callees, tests, contracts, graph neighborhood, native/CUDA/generated status, complexity features, SCC membership, fan-in, fan-out, and provenance. Construct

$$
e(v)=\operatorname{Encode}(X(v)).
$$

The representation may be a pretrained code embedding, a structured feature vector, an agent-generated semantic summary, or a hybrid. The representation is not itself an engineering cost and should not replace explicit hard facts such as `cuda=True`, `public_api=True`, or `native_boundary=True`.

## 26. Operation-conditioned representation

Let $q(\Delta)$ represent change intent. For an operation $\delta_v$ proposed on node $v$, define

$$
z(v,\delta_v)=\operatorname{Condition}\bigl(e(v),q(\Delta),\delta_v,\text{typed graph context}\bigr).
$$

This distinction matters because a node can be expensive to rewrite but nearly free to retain.

## 27. Separate semantic projections

Do not collapse engineering consequence into one universal scalar. Derive separate projections:

$$
w(v,\delta_v)=\mathbb E[\text{implementation effort}\mid z(v,\delta_v)],
$$

$$
r(v,\delta_v)=\mathbb E[\text{mutation or regression risk}\mid z(v,\delta_v)],
$$

$$
h(v,\delta_v)=\mathbb E[\text{verification burden}\mid z(v,\delta_v)],
$$

and, for edge $u\rightarrow v$,

$$
c(u,v,\delta_u,\delta_v)=\mathbb E[\text{coordination burden}\mid z_u,z_v,\operatorname{type}(u,v)].
$$

Effort primarily informs scheduling, coordination cost informs partition boundaries, risk informs repair selection, and verification burden informs acceptance planning.

## 28. Representation roadmap

The progression should be empirical rather than aspirational. Phase 0 uses explicit static features plus an agent role summary and coarse estimates. The first research upgrade adds a pretrained code embedding while retaining the explicit features. The next stage learns small prediction heads for $w$, $r$, $h$, and $c$ from execution traces. Only if those additions demonstrate value should VIPER learn typed repository-neighborhood aggregation or a joint repository/change representation.

The intended progression is

$$
\text{explicit features + role summary}
\rightarrow
\text{pretrained code representation}
\rightarrow
\text{learned task-specific projections}
\rightarrow
\text{typed repository-aware aggregation}.
$$

The telemetry emitted by Phase 0 supplies the initial supervision: actual implementation time, token use, changed symbols and LOC, repair iterations, test failures, verification cost, cross-agent communication, and final outcomes.

---

# Phase III — Optimized SCC-Safe Decomposition

Phase III replaces the Phase 0 greedy partition with a principled optimization over SCC-condensed work. The purpose is execution decomposition, not final architecture selection.

## 29. SCC-safe work graph

For the complete impact graph, compute

$$
D_B=\operatorname{Condensation}(B).
$$

The SCCs remain atomic scheduling units. Candidate future graphs are not required to preserve the same SCC structure; breaking a large cycle may itself be a desirable repair.

## 30. Research partition objective

Let

$$
\Pi=\{C_1,\ldots,C_m\}
$$

be a partition of the SCC-condensed work graph. Following the communication-to-computation formulation established in distributed scheduling and applied to multi-agent coding by Co-Coder, define $W(\Pi;w)$ as predicted critical-path implementation cost and $C(\Pi;c)$ as predicted cross-partition coordination cost. The research objective is

$$
\Pi^*=\arg\min_{\Pi}\left[W(\Pi;w)+\alpha C(\Pi;c)\right].
$$

VIPER's contribution is not this objective itself. The intended extension is to derive its node and edge weights from operation-conditioned repository semantics over a richer typed dependency graph. If $\alpha$ cannot be calibrated to actual communication/computation costs, $W$ and $C$ should remain a multiobjective/Pareto problem rather than being combined through an arbitrary aesthetic weight.

## 31. Structural diagnostics

Useful graph statistics include $|V|$, $|E|$, edge density, SCC count, mean and maximum SCC size, condensation-DAG depth, fan-in and fan-out distributions, cut weight, component-size distribution, and workload imbalance. These are diagnostics rather than automatic objectives. Maximizing connected components can reward pathological fragmentation, and minimizing density can be gamed by adding irrelevant structure.

A more directly meaningful architecture statistic is change-propagation geometry. For each node $v$, define

$$
b(v)=|\operatorname{Pred}^*(v)|.
$$

Under future-change distribution $p(v)$,

$$
\mathbb E[\operatorname{BlastRadius}]
=\sum_v p(v)b(v).
$$

If no prior is known, the uniform distribution provides a topology-derived baseline. Worst-case blast radius and the concentration or variance of $b(v)$ summarize dependency hubs without generating explicit counterfactual changes.

---

# Phase IV — Formal Repair Spaces and Repository-Local Selection

Phase IV addresses the implementation freedom left after completeness and decomposition. It treats each work component as a constrained repair problem, removes formally inferior alternatives, and uses repository-aware semantic judgment only for the residual choices that formal information does not order.

## 32. Component repair spaces

For partition component $C_i$, define

$$
\mathcal R_i=
\left\{
U\mid \operatorname{Apply}(C_i,U)\models T_i^*
\right\}.
$$

Three cases are possible:

$$
|\mathcal R_i|=0
$$

indicates an inconsistent or unsatisfied specification,

$$
|\mathcal R_i|=1
$$

indicates a unique local repair, and

$$
|\mathcal R_i|>1
$$

indicates genuine implementation underdetermination. The design should reuse established graph-repair formalisms where possible rather than inventing a new repair semantics merely for VIPER.

## 33. Formal filtering hierarchy

Candidate reduction should remain ordered. Hard validity first removes every repair that violates $T_i^*$. Least-change dominance then removes any repair that has a strict valid sub-update. Structural Pareto dominance can compare interface disturbance, dependency disturbance, SCC effects, blast-radius geometry, cross-component coupling, critical-path consequences, and verification obligations without prematurely forcing these dimensions into one scalar objective.

The local repair validity and minimality obligations are:

$$
U\in\mathcal R_i\Rightarrow \operatorname{Apply}(C_i,U)\models T_i^*,
$$

and for every retained least-changing repair $U$ there exists no strict valid sub-update $U'\subset U$ satisfying the same local constraints.

## 34. Semantic repair selection

Topology and cardinality cannot fully order engineering choices. A repair that changes one custom CUDA kernel may be less desirable than one that changes three ordinary Python utilities, even when the first touches fewer graph entities. For every surviving repair, aggregate the operation-conditioned risk, verification burden, architectural sensitivity, performance sensitivity, and any other evidence-supported semantic consequences.

The semantic system may eliminate candidates that are clearly dominated under these repository-local measures, but it must not override hard validity or impact completeness.

## 35. Residual agent comparator

If several formally admissible and non-dominated candidates remain, the final selector agent receives the current repository evidence, original specification, candidate transformations, structural summaries, semantic projections, relevant tests and contracts, and the evidence supporting prior eliminations. Pairwise or small-set comparison is preferred to asking the model for an uncalibrated universal architecture score.

A final selection should record whether it was logically forced, least-change dominant, structurally dominant, semantically dominant, chosen by contextual agent preference, supported by empirical realization evidence, or selected only by a canonical tie-break. Canonical selection provides reproducibility, not a claim of semantic optimality.

## 36. Composition of local repairs

For selected repairs $U_1^*,\ldots,U_m^*$, propose

$$
U^*=\bigoplus_i U_i^*,
$$

and

$$
G^*=\operatorname{Apply}(G_0,U^*).
$$

Local validity does not imply global validity automatically. Composition must verify interface compatibility, conflict freedom, shared-resource constraints, contract provenance, cross-component dependencies, and global target satisfaction. Under explicit compatibility conditions, the desired composition theorem is

$$
G^*\models T^*.
$$

---

# Phase V — Realization, Independent Reconstruction, and Conformance

Phase V generalizes the Phase 0 verifier to the richer target and selected repair structure. It preserves the critical independence boundary: the observed implementation graph is reconstructed from repository evidence, not from the plan.

## 37. Planned target and selected realization

Maintain both concepts:

$$
T^*=\text{complete executable target constraints},
$$

and

$$
G^*=\text{one selected planned structural realization when selection is required}.
$$

The relation

$$
G^*\in\mathcal A(T^*)
$$

must hold. Exact singleton selection is not necessary when the implementation can be accepted against $T^*$ alone, but freezing selected structural choices into $G^*$ can be useful for deterministic bounded execution.

## 38. Independent realization

After implementation,

$$
R_1\xrightarrow{\mathcal C}G_1.
$$

The same source-evidenced compiler should be used wherever practical. The graph is reconstructed from the implemented repository, not from implementation reports.

## 39. Conformance theorem

Under sound post-implementation extraction,

$$
G_1\models T^*
$$

establishes structural realization of all represented target obligations. If $G^*$ fixed additional structural choices, those choices must also be checked. Exact equality

$$
G_1=G^*
$$

should be required only for properties the plan actually intended to determine. Structural conformance remains distinct from behavioral correctness, so builds, tests, runtime checks, and benchmarks remain separate acceptance evidence.

---

## 40. Full research architecture

The complete research architecture is

$$
\{\Delta_i\}
\rightarrow B
\rightarrow P
\rightarrow \text{semantic obligation enrichment}
\rightarrow \operatorname{SCC}(B)
\rightarrow \Pi^*
\rightarrow \{\mathcal R_i\}
\rightarrow \{U_i^*\}
\rightarrow G^*
\rightarrow R_1
\rightarrow G_1.
$$

Expanded operationally:

```text
contract-owned changes
    ↓
source-evidenced baseline repository graph
    ↓
conservative impact closure
    ↓
total disposition map
    ↓
repository-conditioned obligation representation
    ↓
operation-conditioned effort / risk / verification / coordination estimates
    ↓
SCC condensation
    ↓
cohesion-aware optimized partition
    ↓
component repair spaces
    ↓
hard validity
    ↓
least-change filtering
    ↓
structural Pareto filtering
    ↓
semantic filtering
    ↓
residual repository-aware agent selection
    ↓
selected local repairs
    ↓
global composition
    ↓
planned structural realization
    ↓
PairBlocks and bounded implementation
    ↓
independent repository reconstruction
    ↓
structural + behavioral conformance
```

The formal system determines what must be considered and what is admissible. The semantic system estimates what is difficult, risky, or costly to coordinate. Agents resolve only the remaining underdetermined engineering choices. The verifier independently determines whether the realized repository satisfies the frozen obligations.

---

## 41. Determinism and reproducibility

The system distinguishes mathematical determinism, policy determinism, and model reproducibility. Graph extraction, stable identifiers, reachability, SCC computation, canonicalization, and constraint checking should be mathematically deterministic. Partitioning, repair selection, and tie-breaking are deterministic only relative to a fixed policy. Semantic summaries, embeddings, effort estimates, and agent judgments require model and context freezing if reproducibility is claimed.

A run should record the repository snapshot, graph-compiler version, model identity, prompt or context-builder version, decoding configuration where applicable, semantic extractor version, selection policy, and canonical tie-breaking rules. A stochastic semantic judgment must not be presented as a theorem.

Future selected repairs should carry a selection receipt such as:

```text
FORCED_BY_CONSTRAINT
LEAST_CHANGE_DOMINANCE
STRUCTURAL_DOMINANCE
SEMANTIC_COST_DOMINANCE
AGENT_CONTEXTUAL_PREFERENCE
EMPIRICAL_REALIZATION_EVIDENCE
CANONICAL_TIE_BREAK
```

This distinguishes mathematically necessary decisions from engineering preferences and reproducibility-only choices.

---

## 42. Prior-art boundary and contribution hypothesis

The architecture intentionally composes established ideas rather than renaming them. Dependency-based impact analysis and slicing are established in the program-dependence literature. Delta modeling formalizes explicit modifications applied to a core model. Algebraic graph transformation provides formal semantics for graph updates, applicability, and composition. Graph-repair research provides formal repair spaces, least-changing repairs, and the fact that multiple minimal repairs may remain. Software reflexion models provide intended-versus-observed structural comparison. CodePlan combines repository dependency analysis, change-impact propagation, planning, and LLM repository editing. Archbird provides a close deterministic repository `Map -> Plan -> isolated Act -> fresh Map/Verify -> Apply` workflow. Co-Coder formalizes repository-level multi-agent coding as a graph-partitioning problem balancing critical-path computation against cross-agent communication.

Accordingly, VIPER should not claim novelty for dependency graphs, reverse-reachability impact analysis, delta modeling, graph transformation, graph repair, repair planning, graph partitioning, multi-agent scheduling, intended-versus-observed architecture comparison, deterministic repository IR, or closed plan/verify loops.

The current candidate contribution is narrower. First, VIPER proposes the explicit pre-implementation invariant

$$
B=\operatorname{ConservativeImpactClosure}(G_0,\Delta),
$$

$$
P:B\rightarrow\{\mathrm{CHANGE},\mathrm{REMOVE},\mathrm{RETAIN}\},
$$

$$
\operatorname{dom}(P)=B,
$$

so that no conservatively affected represented repository entity may be omitted silently from planning. Second, it maintains a strict formal/agentic boundary: formal machinery determines completeness and admissibility, repository-aware semantic machinery estimates engineering consequences, agents resolve only residual underdetermined choices, and the verifier independently checks realization. Third, the research system proposes a persistent semantic representation $e(v)$ that is reused to derive operation-conditioned effort, risk, verification burden, and coordination cost rather than introducing a single isolated LLM ranking step after planning.

These remain contribution hypotheses, not established novelty claims. Novelty should be treated as a hypothesis to falsify continuously against prior work.

---

## 43. Principal prior work and sources

The following sources provide the principal theoretical and systems foundations for the specification.

1. **Horwitz, Susan; Reps, Thomas; Binkley, David.** “Interprocedural Slicing Using Dependence Graphs.” *ACM Transactions on Programming Languages and Systems*, 12(1), 1990. DOI: 10.1145/77606.77608. This work provides the dependence-graph and slicing foundation for conservative impact reasoning.
2. **Clarke, Dave; Helvensteijn, Michiel; Schaefer, Ina.** “Abstract Delta Modeling.” *GPCE*, 2010. DOI: 10.1145/1868294.1868298. This work formalizes a core model plus explicit deltas and addresses composition and ambiguity.
3. **Ehrig et al. and the algebraic graph-transformation literature.** The double-pushout tradition provides a formal basis for graph rewriting, preservation, applicability conditions, dangling conditions, confluence, and composition.
4. **Murphy, Gail C.; Notkin, David; Sullivan, Kevin.** “Software Reflexion Models: Bridging the Gap between Design and Implementation.” *FSE*, 1995; later expanded in *IEEE Transactions on Software Engineering*. This line of work provides the intended-versus-observed structural comparison primitive.
5. **Dam, Hoa Khanh; Winikoff, Michael.** “Generation of Repair Plans for Change Propagation.” This work establishes automated repair-plan generation for consistency-preserving change propagation.
6. **Logic-based graph-repair literature.** Modern graph-repair work establishes sound and complete repair generation under graph constraints, least-changing repair notions, delta-preserving repairs, and the possibility of multiple incomparable minimal repairs.
7. **Bairi et al.** “CodePlan: Repository-level Coding using LLMs and Planning.” arXiv:2309.12499. CodePlan provides a close repository-level precedent for dependency analysis, may-impact propagation, planning, and LLM editing.
8. **Archbird.** Public system documentation, 2026. Archbird provides a close contemporary systems comparator for deterministic repository mapping, planning, isolated candidate realization, fresh remapping, and verification.
9. **Yang, Xu; Nie, Lunyiu; Chandra, Ethan; Gannutin, Stanislav; Lin, Fangru; Chaudhuri, Swarat.** “When Parallelism Pays Off: Cohesion-Aware Task Partitioning for Multi-Agent Coding.” arXiv:2606.00953, 2026. Co-Coder formalizes repository-level task partitioning as a communication-to-computation tradeoff and supplies the immediate baseline for VIPER's decomposition layer.
10. **Code-representation and repository-graph representation literature.** GraphCodeBERT, UniXcoder, CodeT5+, RepoGraph, and recent code-graph models establish practical baselines for combining code semantics with structural context. VIPER should reuse pretrained representations before considering custom model training.

---

## 44. Empirical validation program

The research program should be evaluated by ablation rather than by implementing the entire architecture at once. Comparisons should include a strong sequential coding agent, simple file-parallel agents, impact analysis without total disposition, impact analysis with total disposition, SCC-safe partitioning, Co-Coder-style structural partitioning, topology plus semantic effort estimates, and the full semantic repair-selection system.

Primary completeness metrics are missed affected surfaces, stale structures, and omitted contract obligations. Minimality metrics include unnecessary files or symbols changed and dependency churn. Quality metrics include test and build success, structural conformance, regressions, and benchmark behavior where relevant. Agent-efficiency metrics include token use, wall-clock time, repair iterations, context size, and cross-agent communication. Partition metrics include critical path, workload balance, cut weight, and SCC violations. Semantic-model quality should be assessed by the relationship between predicted and observed implementation effort, token use, verification cost, repair iterations, regressions, performance sensitivity, and coordination burden.

The ablation sequence is itself a scope-control mechanism. If total disposition does not improve the Phase 0 baseline, downstream semantic sophistication is not justified. If explicit static semantic metadata performs as well as learned embeddings, the learned representation should not be built. If bounded agent candidate generation performs as well as formal repair-space enumeration, exhaustive synthesis should remain out of scope.

---

## 45. Remaining research and engineering work

The immediate engineering work is the Phase 0 implementation order defined above. The broader research agenda should proceed only after Phase 0 clears its kill gate. Remaining tasks include:

1. defining the complete heterogeneous repository graph schema and exact evidence boundary;
2. strengthening dynamic-resolution coverage and unresolved-dependency semantics;
3. formalizing multi-delta conflict, compatibility, and provenance semantics;
4. completing the soundness, minimality, and total-disposition proofs against the implemented graph model;
5. defining precise semantics and evidence requirements for `CHANGE`, `REMOVE`, and especially `RETAIN`;
6. testing whether prior work already states the exact global total-disposition invariant over a conservative repository impact closure;
7. defining and evaluating persistent repository-context representations $e(v)$;
8. calibrating operation-conditioned effort $w$, risk $r$, verification burden $h$, and coordination cost $c$ from collected traces;
9. replacing the greedy partition baseline with an SCC-safe optimized or Pareto decomposition based on measured computation and coordination costs;
10. defining component repair spaces using established graph-repair theory where practical;
11. determining tractable repair-search strategies without assuming that all admissible graphs can be enumerated;
12. defining structural Pareto metrics and the ordering in which they should be applied;
13. designing the residual pairwise agent-comparison protocol and handling preference cycles or low-confidence decisions;
14. defining when isolated candidate implementation should be used to obtain empirical selection evidence;
15. proving local-repair composition conditions and global target satisfaction;
16. defining selection receipts and exact policy-determinism requirements;
17. completing post-implementation conformance semantics and the boundary between $T^*$ satisfaction and exact $G^*$ conformance;
18. expanding the canonical worked example to include multiple deltas, a dependency cycle, multiple valid repairs, a specialized high-risk component, and the full derivation from $R_0$ to $G_1$; and
19. continuing novelty falsification against change-impact analysis, graph repair, bidirectional transformations, architecture repair, model synchronization, repository planning, CodePlan, Archbird, and adjacent agentic software-engineering systems.

---

## 46. Canonical research statement

VIPER is intended to function as a software-change compiler. Given a current repository and declarative proposed changes, it derives a conservative represented impact closure, assigns exactly one explicit disposition to every affected represented entity, enriches the resulting obligations with repository-local semantic context, decomposes the complete work into dependency-safe implementation units, permits agents to resolve only those engineering choices left underdetermined by formal constraints, and independently reconstructs the implemented repository to verify structural and behavioral conformance.

Phase 0 is the non-negotiable baseline. It tests whether the simple protocol

$$
\Delta
\rightarrow B
\rightarrow P
\rightarrow \text{simple semantic context}
\rightarrow \text{bounded choice}
\rightarrow \text{implementation}
\rightarrow \text{independent verification}
$$

is useful before the project invests in learned representations, optimized partitioning, or formal repair synthesis.

The formal system determines what must be considered and what is admissible. The semantic system estimates what is difficult, risky, or costly to coordinate. The implementation agent determines how to realize bounded admissible obligations. The verifier determines whether the resulting repository actually satisfies them.

The first research bet is not that graph transformation, change-impact analysis, repair planning, or multi-agent partitioning is new. It is that a source-evidenced change compiler with a total-disposition invariant can make repository-scale agentic software changes more complete, auditable, and independently verifiable than an agent that must infer, execute, and self-audit the entire task in one loop.
