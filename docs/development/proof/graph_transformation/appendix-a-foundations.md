# Appendix A: Graph-transformation foundations

This appendix defines the graph-transformation claim that VIPER must establish
before implementing planned-system compilation. A contract delta identifies
the mandatory mutations. Reverse dependency closure identifies every graph
entity that must receive a disposition. A propagation plan supplies the
decisions that the contract delta leaves open. The baseline graph, delta, and
plan compile into executable target constraints:

```math
T^*=\operatorname{CompileTarget}(G_0,\Delta,P).
```

The model set $\mathcal A(T^*)=\{G\mid G\models T^*\}$ may contain several
valid future graphs. When bounded implementation requires one structural
realization, repair selection chooses graph operations $U^*$ satisfying
$\operatorname{Apply}(G_0,U^*)\models T^*$ and thereby fixes an optional
planned graph $G^*$. Selected work compiles into ordered `PairBlock` records
only after that choice.

This document is a starter proof. Its definitions and propositions are local
design proposals that leave the active contracts unchanged. The contract
delta $\Delta$ below is a normative input that describes required future
mutations. It is distinct from an observed difference between two compiled
source revisions.

## A.1 Proof contract

The proof has four targets:

1. **Soundness:** the blast radius contains every entity that the contract
   change can affect, subject to a conservative dependency-extraction
   assumption.
2. **Minimality:** reverse reachability returns the least
   predecessor-closed set that contains the delta-induced initial vertices.
3. **Target determinism:** fixed, valid inputs produce one canonical target
   constraint set; a concrete planned graph is deterministic only after repair
   selection fixes every required structural choice.
4. **Conformance:** the observed graph satisfies the target constraints;
   planned-versus-observed fact comparison applies when selection fixed a
   concrete planned graph.

The domain contains finite repository states, finite typed attributed graphs,
finite graph-operation sequences, and finite propagation plans. Finiteness
ensures that graph compilation, closure, plan ordering, and operation
application terminate. The theorems remain conditional on the compiler's
declared analysis boundary.

The proof dependency structure is:

```text
conservative blast-radius theorem
├── dependency orientation
├── impact overlay
├── delta-induced initial vertex set
└── dependency-conservativeness assumption

minimal-closure theorem
├── reverse-reachability definition
└── predecessor-closed-set definition

target-determinism theorem
├── total propagation plan
├── canonical target-constraint compilation
└── optional deterministic repair selection

post-implementation conformance
├── common compiler and context
├── target-constraint satisfaction
└── optional canonical represented-fact projection
```

The resulting lifecycle preserves the decomposition developed before this
appendix:

```text
1. Repository compilation       R0 -> G0
2. Contract transformation      Delta defines mandatory operations
3. Conservative impact          (G0, Delta) -> B
4. Total propagation planning   (Delta, B) -> P
5. Target compilation           (G0, Delta, P) -> T*
6. Decomposition and selection  T* -> Pi -> U* -> optional G*
7. Execution compilation        (T*, Pi, U*) -> PairBlocks
8. Implementation               PairBlocks -> R1
9. Repository recompilation     R1 -> G1
10. Conformance                 G1 models T*
```

Stages 3 and 4 are separate obligations. Impact analysis discovers what must
be considered. The propagation plan decides what each affected surface should
become.

## A.2 Repository states and compiled graphs

Let $\mathcal P$ be the set of repository-relative paths and $\mathbb B^*$ the
set of finite byte strings.

**Definition A.1 (repository state).** A repository state is a finite partial
map

```math
R : \mathcal P \rightharpoonup \mathbb B^*.
```

The baseline repository is $R_0$. The implemented repository is $R_1$.
Repository identity also includes the selected Git revision, because two maps
with equal current files and different committed histories may identify
different review inputs.

Let $\mathcal I$ be a universe of stable entity identifiers, $\mathcal K_V$ a
finite set of node kinds, $\mathcal K_E$ a finite set of dependency kinds, and
$\mathcal A$ a set of canonical attribute maps.

**Definition A.2 (system graph).** A system graph is a finite typed attributed
directed graph

```math
G=(V,E,\tau_V,\alpha_V,\alpha_E),
```

with:

- $V\subseteq\mathcal I$, a finite set of node identifiers;
- $E\subseteq V\times\mathcal K_E\times V$, a finite set of typed dependency
  edges;
- $\tau_V:V\rightarrow\mathcal K_V$, the node type function; and
- $\alpha_V:V\rightarrow\mathcal A$ and
  $\alpha_E:E\rightarrow\mathcal A$, the canonical attribute functions.

An edge $(u,k,v)\in E$ means that $u$ depends on $v$ through dependency kind
$k$. Edge attributes retain the evidence and provenance supporting that
relationship. Stable node identifiers preserve exact revision comparison.

Define the untyped dependency projection used for reachability:

```math
D_G
=
\left\{
(u,v)\in V\times V
\;\middle|\;
\exists k\in\mathcal K_E:\;(u,k,v)\in E
\right\}.
```

Every member of $E$ contributes to $D_G$. Repository evidence that does not
assert dependency belongs in a separate evidence relation rather than being
inserted into $E$ and filtered during reachability.

Let $X$ be one fixed `SystemContextManifest`. Let $C_X$ be the repository
compiler under that context.

**Definition A.3 (baseline and observed graphs).** When strict compilation
succeeds,

```math
G_0=C_X(R_0)
\qquad\text{and}\qquad
G_1=C_X(R_1).
```

The compilation result must include the analyzed inventory, coverage evidence,
dependency evidence, resolution observations, and an unresolved set. The
strict proof boundary requires the unresolved set to be empty. Equal inputs
must produce equal canonical graphs; target determinism otherwise fails before
transformation begins.

### Dependency orientation

**Definition A.4 (dependency relation).** For vertices $x,y\in V$, write
$x\rightarrow_G y$ exactly when $(x,y)\in D_G$. The source $x$ is the
dependent and the target $y$ is the dependency. Every compiler adapter must
normalize its source-level relation into this orientation before emitting an
edge in $E$.

Let $\rightarrow_G^*$ denote the reflexive transitive closure of
$\rightarrow_G$.

## A.3 Contract delta and initial vertices

Let $\mathcal O$ contain these primitive operations over stable anchors:

```text
AddNode(id, kind, attributes)
RemoveNode(id, expected-kind, expected-attributes)
SetNodeAttributes(id, expected, replacement)
AddEdge(source, kind, target, attributes)
RemoveEdge(source, kind, target, expected-attributes)
SetEdgeAttributes(source, kind, target, expected, replacement)
```

The algebraic interpretation compiles each primitive operation or compatible
operation group into a double-pushout (DPO) rule

```math
q=\left(L\xleftarrow{\ell}K\xrightarrow{r}R,\mathsf{ac}_q\right).
```

Here $L$ is the pre-change fragment, $K$ is the preserved fragment, $R$ is the
replacement fragment, and $\mathsf{ac}_q$ is the application condition. A
match $m:L\rightarrow G$ may apply when it satisfies $\mathsf{ac}_q$ and the
pushout complement exists. The DPO gluing conditions include the dangling
condition: deleting a node requires the rule to delete each incident edge that
would otherwise become endpointless. The first pushout removes
$L\setminus\ell(K)$ while preserving $K$; the second adds
$R\setminus r(K)$. Typed attributed rules carry node, edge, and attribute
constraints through the same construction
([Ehrig et al. 2006](https://doi.org/10.1007/3-540-31188-2), Chapters 2–4).

The stable-anchor operation list is VIPER's authoring syntax. DPO rules supply
the semantics of `Apply`. This separation permits concise contract deltas while
retaining explicit match, preservation, deletion, addition, application, and
dangling conditions.

Every destructive or updating operation carries an expected old value. That
precondition prevents the operation from silently applying to a different
baseline fact.

**Definition A.5 (contract delta).** A contract delta is a finite partially
ordered family

```math
\Delta=(O_\Delta,\prec_\Delta),
```

where $O_\Delta\subseteq\mathcal O$ states the mandatory graph operations and
$\prec_\Delta$ states every required application order. The delta is valid for
$G_0$ when every anchor resolves uniquely, every operation precondition holds,
and at least one linear extension of $\prec_\Delta$ can execute while
preserving the graph constraints.

**Definition A.6 (delta-induced initial vertex set).** The vertex support of an
operation is the set of node anchors that it creates, removes, reads, updates,
or names as an edge endpoint. The initial vertex set is

```math
S_\Delta
=
\bigcup_{o\in O_\Delta}\operatorname{support}_V(o).
```

An edge edit contributes both endpoints. A removal retains its old anchor and
old incident dependencies during impact analysis so the overlay still
represents the structure being disrupted.

### Impact overlay

Let $V_\Delta^+$ be the nodes added by $\Delta$, and let
$D_\Delta^+$ be the dependency pairs introduced by added or updated edges in
$\Delta$ after removing their dependency-kind component.

**Definition A.7 (impact overlay).** The impact overlay
$H_\Delta=(V_H,D_H)$ is the dependency graph with

```math
V_H=V_0\cup V_\Delta^+,
\qquad
D_H=D_{G_0}\cup D_\Delta^+.
```

The union retains baseline edges that $\Delta$ removes and adds new contract
relationships. The overlay serves impact analysis only. Section A.7 defines
target compilation and optional planned-graph selection.

## A.4 Blast radius

**Definition A.8 (blast radius).** The blast radius of $\Delta$ relative to
$G_0$ and $X$ is

```math
B(G_0,\Delta,X)
=
\left\{
x\in V_H
\;\middle|\;
\exists s\in S_\Delta:\;x\rightarrow_{H_\Delta}^*s
\right\}.
```

Write $B$ when the inputs are fixed. Membership in $B$ requires the plan to
consider the entity. The plan may assign `retain` after that review.

Let $D_X^{\mathrm{sem}}\subseteq V_H\times V_H$ be the semantic dependency
relation under context $X$. A pair $(x,y)\in D_X^{\mathrm{sem}}$ means that a
contract-relevant change to $y$ may require changing or checking $x$. Write
$x\rightarrow_{\mathrm{sem}}y$ for membership in this relation and
$\rightarrow_{\mathrm{sem}}^*$ for its reflexive transitive closure.

**Definition A.9 (potentially affected entity).** The semantic affected set is

```math
A_\Delta
=
\left\{
x\in V_H
\;\middle|\;
\exists s\in S_\Delta:\;x\rightarrow_{\mathrm{sem}}^*s
\right\}.
```

The relation includes possible changes to existence, type, represented
attributes, and represented relationships. It is a semantic proof primitive;
the algorithm computes $B$ from extracted graph dependencies.

**Assumption A.1 (dependency conservativeness).** The impact overlay contains
every semantic dependency edge:

```math
D_X^{\mathrm{sem}}\subseteq D_H.
```

Per-input analysis receipts, resolution attempts, and explicit unresolved
records establish the evidence boundary for this assumption. Empty unresolved
output establishes total resolution for the compiler's declared analyzers and
fixed context. Completeness over arbitrary Python semantics requires the
analyzer set to model every relevant dependency.

### Theorem A.1: conservative blast radius

Under Assumption A.1,

```math
A_\Delta\subseteq B.
```

**Proof.** Let $x\in A_\Delta$. Definition A.9 supplies a semantic path
$x=v_0\rightarrow_{\mathrm{sem}}v_1\rightarrow_{\mathrm{sem}}\cdots
\rightarrow_{\mathrm{sem}}v_n=s$ with $s\in S_\Delta$. Assumption A.1 places
every edge of that path in $D_H$, so the same vertex sequence is an
$H_\Delta$ path from $x$ to $s$. Definition A.8 gives $x\in B$. Since $x$
was arbitrary, $A_\Delta\subseteq B$. $\square$

Reverse reachability is exact for the extracted dependency relation. Missing
reflection targets, registry edges, subprocess entrypoints, generated
artifacts, contract links, or other semantic dependencies can invalidate
Assumption A.1.

### Theorem A.2: minimal predecessor-closed set

**Definition A.10 (predecessor closed).** A set $Q\subseteq V_H$ is
predecessor closed when

```math
\forall(x,y)\in D_H:\;y\in Q\Longrightarrow x\in Q.
```

The blast radius $B$ is the unique least predecessor-closed subset of
$V_H$ that contains $S_\Delta$.

**Proof.** Reflexivity of $\rightarrow^*$ gives $S_\Delta\subseteq B$. If
$y\in B$ and $(x,y)\in D_H$, then $y\rightarrow^*s$ for some
$s\in S_\Delta$.
Prepending $(x,y)$ gives $x\rightarrow^*s$, so $x\in B$. Thus $B$ is
predecessor closed.

Let $Q$ be any predecessor-closed set with $S_\Delta\subseteq Q$. For any
$x\in B$, choose a path
$x=v_0\rightarrow v_1\rightarrow\cdots\rightarrow v_n=s$ with
$s\in S_\Delta$. Since $s\in Q$, predecessor closure applied backward along
the finite path gives $v_{n-1},\ldots,v_0=x\in Q$. Hence $B\subseteq Q$.
Every admissible $Q$ contains $B$, so $B$ is a least element under set
inclusion. If $L$ were another least element, then $B\subseteq L$ and
$L\subseteq B$, hence $B=L$ by set extensionality. $\square$

Minimality is relative to $H_\Delta$. Adding a conservative dependency edge
can enlarge $B$. Removing a real dependency edge can make the computed set
unsound even though it remains minimal for the defective overlay.

## A.5 Propagation plan and PairBlocks

Let $\mathcal D$ be the set of admissible disposition records. A disposition
record contains:

```text
vertex
decision in {add, change, remove, retain}
required postconditions
forbidden postconditions
preservation predicates
rationale
```

The record states the required treatment of one affected vertex. It does not
specify agent ownership or execution order.

**Definition A.11 (propagation plan and total disposition).** A candidate
propagation plan is a finite partial function

```math
P:V_H\rightharpoonup\mathcal D.
```

The plan is accepted exactly when

```math
\operatorname{dom}(P)=B
```

and each record $P(v)$ identifies $v$ as its subject. The equality requires a
plan entry for every affected vertex and excludes disposition keys outside the
computed blast radius. A disposition may still require additional target
structure through its postconditions.

**Proposition A.3 (total-disposition property).** Every vertex in $B$ receives
exactly one disposition in an accepted plan.

**Proof.** Domain equality gives existence: for every $b\in B$, $P(b)$ is
defined. A function has at most one value for each input, which gives
uniqueness. $\square$

Total disposition establishes planning coverage. It does not establish that
the selected decisions are mutually consistent, that their postconditions are
satisfiable, or that every vertex requires a source edit. Target compilation
checks consistency and satisfiability; a `retain` disposition can discharge an
affected vertex through a preservation predicate.

PairBlocks appear after target compilation, decomposition, and repair
selection. Section A.7 defines that execution connector.

## A.6 Why the contract delta is insufficient

The following five-file repository supplies one counterexample to the claim
that $\Delta$ alone always determines $G^*$.

```text
repo/
├── models.py
├── storage.py
├── runner.py
├── api.py
└── tests/
    └── test_api.py
```

`models.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactRef:
    path: Path
```

`storage.py`:

```python
from models import ArtifactRef


class LocalArtifactStore:
    def load(self, ref: ArtifactRef) -> bytes:
        return ref.path.read_bytes()
```

`runner.py`:

```python
from models import ArtifactRef
from storage import LocalArtifactStore


class Runner:
    def __init__(self, store: LocalArtifactStore):
        self.store = store

    def verify(self, ref: ArtifactRef) -> bytes:
        return self.store.load(ref)
```

`api.py`:

```python
from pathlib import Path

from models import ArtifactRef
from runner import Runner
from storage import LocalArtifactStore


def verify(path: Path) -> bytes:
    ref = ArtifactRef(path=path)
    return Runner(LocalArtifactStore()).verify(ref)
```

`tests/test_api.py`:

```python
from api import verify


def test_verify(tmp_path):
    path = tmp_path / "model.bin"
    path.write_bytes(b"abc")

    assert verify(path) == b"abc"
```

With dependency direction `dependent -> dependency`, the relevant part of
$G_0$ is:

```text
test_verify
    |
    v
api.verify
    |---------------------> ArtifactRef.path
    v
Runner.verify
    |
    v
LocalArtifactStore.load
    |
    v
ArtifactRef.path
```

Suppose the contract replaces `ArtifactRef.path: Path` with
`ArtifactRef.source: LocalSource` and changes
`LocalArtifactStore.load(...) -> bytes` into
`LocalArtifactStore.load(...) -> LoadedArtifact`, where:

```python
@dataclass(frozen=True)
class LoadedArtifact:
    data: bytes
    sha256: str
```

The mandatory delta contains operations equivalent to:

```text
REMOVE  ArtifactRef.path

ADD     LocalSource
ADD     ArtifactRef.source
ADD     ArtifactRef.source --typed_by--> LocalSource

ADD     LoadedArtifact
UPDATE  LocalArtifactStore.load.return_type:
            bytes -> LoadedArtifact

REMOVE  LocalArtifactStore.load --reads--> ArtifactRef.path
ADD     LocalArtifactStore.load --reads--> ArtifactRef.source
```

The impact overlay retains the old `reads` relationship while adding the new
relationships. Reverse traversal from $S_\Delta$ reaches:

```text
ArtifactRef.path
      ^
      |-- LocalArtifactStore.load
      |          ^
      |          |
      |      Runner.verify
      |          ^
      |          |
      |       api.verify
      |          ^
      |          |
      |      test_verify
      |
      `-- api.verify
```

The delta-induced initial vertices are approximately:

```text
ArtifactRef.path
ArtifactRef.source
LocalSource
LocalArtifactStore.load.return_type
LoadedArtifact
```

The resulting blast radius includes the changed model fields and types,
`LocalArtifactStore.load`, `Runner.verify`, `api.verify`, and `test_verify`.
Every member needs a disposition, and the delta leaves at least two valid
propagation choices.

Plan $P_A$ propagates the new return type:

```python
def verify(self, ref: ArtifactRef) -> LoadedArtifact:
    return self.store.load(ref)
```

The public `api.verify` then also returns `LoadedArtifact`.

Plan $P_B$ contains the new return type inside `Runner`:

```python
def verify(self, ref: ArtifactRef) -> bytes:
    loaded = self.store.load(ref)
    return loaded.data
```

The public `api.verify(path) -> bytes` and its existing test can remain valid.
Both plans satisfy the stated mandatory delta, while their planned graph facts
for `Runner.verify` and `api.verify` differ. Therefore

```math
\operatorname{Apply}(G_0,\Delta)
```

fails to define a total single-valued target derivation for this example. The
complete definition requires $P_A$ or $P_B$.

The constructor has the same ambiguity. The delta requires `api.verify` to stop
constructing `ArtifactRef(path=path)` and leaves the choice among
`ArtifactRef(source=LocalSource(path))`, changing the public API to accept a
`LocalSource`, or another contract-compatible boundary. The propagation plan
must state the target obligation, and repair selection must choose a concrete
construction when bounded execution requires one.

## A.7 Target compilation, decomposition, and repair selection

Let $\mathcal F$ be the finite Phase 0 graph-fact universe induced by node
identities, node roles, typed edges, and normalized Python signatures. For
$f\in\mathcal F$, define three atomic predicates over a candidate graph $G$:

```math
\begin{aligned}
\operatorname{Present}(f)(G)
&\iff f\in\mathcal F(G),\\
\operatorname{Absent}(f)(G)
&\iff f\notin\mathcal F(G),\\
\operatorname{Preserved}_{G_0}(f)(G)
&\iff f\in\mathcal F(G_0)\cap\mathcal F(G),
\end{aligned}
```

where $\mathcal F(G)$ is the canonical fact projection of $G$.

**Definition A.12 (target specification).** Target compilation translates the
canonical baseline graph, valid delta, and accepted propagation plan into a
finite canonical conjunction of the three atomic predicates:

```math
T^*=\operatorname{CompileTarget}(G_0,\Delta,P).
```

Node and edge additions produce presence predicates. Removals produce absence
predicates. An edge update produces absence of the baseline edge and presence
of the replacement edge. Each propagation disposition supplies typed required,
forbidden, and preserved facts. Define the admissible future graph family

```math
\mathcal A(T^*)=\left\{G\;\middle|\;G\models T^*\right\}.
```

Target consistency requires $\mathcal A(T^*)\neq\varnothing$.

The atomic predicate names are VIPER conventions. Graph-constraint
satisfaction is the imported mathematical mechanism; the three-kind normal
form is the local Phase 0 design. It is complete for the stated target language
because every accepted input record translates to a finite conjunction of
presence, absence, and baseline-preservation predicates over $\mathcal F$.

### Theorem A.4: deterministic target-constraint derivation

Fixed inputs $(G_0,\Delta,P)$ determine one canonical $T^*$ when all of these
conditions hold:

1. $C_X$ is deterministic and $G_0$ is canonical.
2. Every node and typed-edge anchor referenced by $\Delta$ or $P$ either
   resolves uniquely against $G_0$ or is declared fresh under a canonical
   identifier.
3. $\Delta$ is valid for $G_0$ and every operation precondition is explicit.
4. $P$ satisfies $\operatorname{dom}(P)=B$.
5. Every delta operation and typed disposition fact has the total translation
   stated in Definition A.12.
6. Target normalization rejects contradictory predicates and applies a fixed
   canonical ordering.

**Proof.** Conditions 1 and 2 fix the baseline facts and every referenced
entity. Conditions 3 and 4 fix the accepted delta and plan inputs. Condition 5
maps each input record to a unique finite predicate multiset. Condition 6
merges equal predicates with their origins, rejects the simultaneous presence
and absence of one fact, and gives every consistent predicate set one canonical
representation. `CompileTarget` therefore returns the same $T^*$ for equal
inputs. $\square$

The theorem establishes deterministic constraint derivation. It does not
assert that $\mathcal A(T^*)$ contains one graph.

**Definition A.13 (affected work graph and partition).** Restrict the impact
overlay to the blast radius:

```math
H_\Delta[B]
=
\left(B,D_H\cap(B\times B)\right).
```

Compute its strongly connected components and condensation DAG:

```math
D_B=\operatorname{Condensation}\!\left(H_\Delta[B]\right).
```

A work partition $\Pi=\{C_1,\ldots,C_m\}$ partitions the vertices of $D_B$.
Each vertex of $D_B$ represents one SCC and remains atomic for scheduling.
The partition selects agent ownership and execution boundaries; it does not
select the future repository structure.

Let $\lambda(c)\subseteq B$ be the original vertices represented by
condensation vertex $c$. Lift each work component back to repository vertices:

```math
W_i
=
\bigcup_{c\in C_i}\lambda(c).
```

The sets $W_1,\ldots,W_m$ partition $B$. Let $\Gamma_i\subseteq V_H\setminus
W_i$ contain every boundary vertex named by a crossing dependency or by a
target predicate owned by component $i$.

An ownership function $\omega:T^*\rightarrow\{1,\ldots,m\}$ assigns every
target predicate to one component, and

```math
T_i^*=\{t\in T^*\mid\omega(t)=i\}.
```

Let $N_i$ be the fresh vertex anchors introduced by predicates in $T_i^*$
that were not already present in $V_H$. Target compilation requires the
$N_i$ sets to be pairwise disjoint. Define the writable ownership set

```math
\widehat W_i=W_i\cup N_i.
```

The boundary $\Gamma_i$ remains read-only.

For an operation sequence $U$, $\operatorname{write}_V(U)$ contains every
vertex anchor it creates, removes, or updates, including endpoints of changed
edges. The set $\operatorname{read}_V(U)$ contains every additional vertex
anchor used by a match, precondition, or postcondition.

**Definition A.14 (component repair space).** The admissible repair space for
component $i$ is

```math
\mathcal R_i
=
\left\{
U\;\middle|\;
\begin{array}{l}
\operatorname{write}_V(U)\subseteq\widehat W_i,\\
\operatorname{read}_V(U)\subseteq\widehat W_i\cup\Gamma_i,\\
\operatorname{Apply}(G_0,U)\text{ exists, and}\\
\operatorname{Apply}(G_0,U)\models T_i^*
\end{array}
\right\}.
```

Hard validity removes every $U\notin\mathcal R_i$. Least-change and structural
dominance may remove formally inferior survivors. If several admissible,
non-dominated candidates remain, a bounded selector $\sigma_i$ chooses one
repair using repository evidence, operation estimates, tests, contracts, and
recorded tradeoffs:

```math
U_i^*=\sigma_i(\mathcal R_i,T_i^*,X).
```

An agent may generate candidates and compare the surviving alternatives. The
hard-validity layer determines membership in $\mathcal R_i$ and remains
authoritative.

When selected local repairs are conflict-free and interface-compatible, define

```math
U^*=\bigoplus_{i=1}^{m}U_i^*
```

and, when the selected repairs fix a complete structural realization,

```math
G^*=\operatorname{Apply}(G_0,U^*).
```

Selection must verify $G^*\models T^*$. A canonical $G^*$ additionally
requires unique anchors, satisfied DPO application and gluing conditions,
termination, deterministic conflict resolution or confluence, and canonical
serialization. Without complete structural selection, $T^*$ remains the
authoritative target and no singleton $G^*$ is asserted.

### Execution compilation

The Phase 0 master checklist already uses a parseable
[`PairBlock` contract](../../phase-0-pair-coding.md#1-pairblock-contract) to bind
each checklist item to its requirements, dependencies, source targets, tests,
and completion gate. This appendix keeps that established execution unit and
defines the additional information required when graph-derived repair
selection produces its contents.

Let $\mathcal Q$ be the ordered PairBlocks produced from the target,
partition, and selected repairs:

```math
\mathcal Q
=
\operatorname{CompileWork}(T^*,\Pi,\{U_i^*\}_{i=1}^{m}).
```

Each PairBlock records owned dispositions, selected repair operations, source
targets, originating deltas, required and forbidden postconditions, execution
dependencies, tests, verification requirements, and effort estimates. The
owned repair-operation sets must partition the operations in $U^*$, and the
PairBlocks must collectively carry every hard obligation in $T^*.

PairBlock dependency order constrains execution scheduling. It does not prove
repair confluence or select the architecture.

## A.8 Implemented repository and observed graph

Implementation applies the selected PairBlocks to $R_0$ and produces $R_1$.
Strict recompilation under the same context gives $G_1=C_X(R_1)$.

**Definition A.15 (target conformance).** The observed graph conforms to the
authoritative target specification exactly when

```math
G_1\models T^*.
```

This judgment evaluates every required, forbidden, and preservation predicate
in $T^*$ against facts reconstructed from $R_1$. It remains defined when
$\mathcal A(T^*)$ contains several graphs and no concrete $G^*$ was selected.

**Proposition A.5 (represented target conformance).** Assume that $C_X$
soundly extracts every graph fact referenced by $T^*$ and that the target
predicate evaluator implements the semantics assigned by `CompileTarget`.
Then $G_1\models T^*$ establishes that every represented target obligation is
realized in $R_1$.

**Proof.** Each member of $T^*$ is an executable predicate over represented
graph facts. By the definition of satisfaction, $G_1\models T^*$ holds exactly
when every predicate evaluates to true on $G_1$. Sound extraction maps those
true graph predicates to the corresponding represented facts in $R_1$.
$\square$

Target conformance does not require one fully selected planned graph. When
repair selection fixed a concrete $G^*$, VIPER may additionally compare the
planned and observed represented facts that selection intended to freeze.

Let $\Sigma$ be the declared conformance scope, and let
$\mathcal F_\Sigma(G)$ be the canonical set of represented facts inside that
scope. A fact records one of these forms:

```text
node(id, kind, canonical attributes)
edge(dependent, kind, dependency, canonical attributes)
```

The scope excludes evidence fields whose values may legitimately differ
between planned and observed compilation, such as source line numbers, while
retaining every field that the plan claims as a postcondition.

**Definition A.16 (optional planned-versus-observed partition).** When $G^*$
exists, let

```math
F^*=\mathcal F_\Sigma(G^*)
\qquad\text{and}\qquad
F_1=\mathcal F_\Sigma(G_1).
```

Then define:

```math
\operatorname{Conv}=F^*\cap F_1,
```

```math
\operatorname{Abs}=F^*\setminus F_1,
```

```math
\operatorname{Div}=F_1\setminus F^*.
```

Convergences are frozen planned facts observed after implementation. Absences
are frozen planned facts missing from the implementation. Divergences are
observed facts outside the frozen planned projection.

**Proposition A.6 (scoped planned-graph equality).** The observed graph equals
the selected planned graph in scope $\Sigma$ exactly when

```math
\operatorname{Abs}=\varnothing
\qquad\text{and}\qquad
\operatorname{Div}=\varnothing.
```

**Proof.** Both differences are empty exactly when $F^*\subseteq F_1$ and
$F_1\subseteq F^*$. By set extensionality, those inclusions hold exactly when
$F^*=F_1$. $\square$

Phase 0 uses stable identities and exact set difference. A comparison without
shared identities requires an explicit correspondence map or a normalized
graph isomorphism before computing the partition.

### Limits of the comparison

Target satisfaction and optional planned-graph comparison cover only facts
emitted by $C_X$ and predicates implemented by the verifier. Arbitrary
functional correctness, program termination, numerical correctness, security,
and behavior under an undeclared context remain outside those results. A
compiler omission leaves the corresponding implementation defect
unobservable.

The same compiler and context must produce $G_0$ and $G_1$. A compiler-version
change or context change introduces another independent delta and makes a raw
set comparison ambiguous.

Absence and divergence also require an explicit comparison policy. Some
observed implementation facts may be intentionally unconstrained by the
selected plan. They are failures only when $\Sigma$ declares them frozen.
Every claimed selected-graph postcondition must remain inside $\Sigma$.
Behavioral acceptance continues through builds, tests, runtime checks, and
benchmarks outside structural conformance.

## A.9 Relationship to prior work

The proof imports one primitive from each source family:

| Source | Imported primitive | VIPER proof role |
| --- | --- | --- |
| [Clarke, Helvensteijn, and Schaefer 2010](https://doi.org/10.1145/1868294.1868298) | Explicit deltas, composition, conflict resolution, and unambiguous derivation | Definition of $\Delta$ and target-determinism Conditions 3, 5, and 6 |
| [Ehrig et al. 2006](https://doi.org/10.1007/3-540-31188-2) | DPO rule application, application and gluing conditions, preservation, constraints, confluence, and termination | Semantics of applying $\Delta$ and selected repair operations $U^*$ |
| [Ehrig, Ehrig, Habel, and Pennemann 2006](https://doi.org/10.3233/FUN-2006-74107) | Graph constraints, application conditions, and their translations in adhesive high-level replacement systems | Satisfaction semantics for the target specification $T^*$ |
| [Horwitz, Reps, and Binkley 1990](https://doi.org/10.1145/77606.77608) | Dependence-graph representation and interprocedural slicing | Dependency relation, reverse closure, and blast-radius argument |
| [Murphy, Notkin, and Sullivan 2001](https://doi.org/10.1109/32.917525) | Intended-versus-extracted structural comparison | Optional convergence, absence, and divergence for selected $G^*$ versus observed $G_1$ |

Delta modeling supplies the core-plus-modifications structure. Clarke,
Helvensteijn, and Schaefer define deltas as modifications applied incrementally
to a core product and study conflict-resolving deltas and conditions for
unambiguous product generation. VIPER borrows that separation while using one
reviewed repository as the core and one contract change plus propagation plan
as the modification family
([Clarke, Helvensteijn, and Schaefer 2010](https://doi.org/10.1145/1868294.1868298),
Sections 1–4).

Algebraic graph transformation supplies the DPO rule span, application and
gluing conditions, graph constraints, local confluence, and termination. This
appendix compiles stable-anchor operations into that rule form. A later
contract must define the exact typed attributed graph category and the
operation-to-rule compiler before VIPER can claim a complete DPO instantiation
([Ehrig et al. 2006](https://doi.org/10.1007/3-540-31188-2), Chapters 2–4).

Graph constraints state conditions satisfied by graphs, while application
conditions state conditions for applying transformations. VIPER uses graph
constraints for $T^*$ and application conditions for delta and repair
applicability. Presence and absence are the Phase 0 atomic fragment;
preservation compares a projected baseline fact with the observed fact
([Ehrig, Ehrig, Habel, and Pennemann 2006](https://doi.org/10.3233/FUN-2006-74107)).

Horwitz, Reps, and Binkley introduced the system dependence graph to represent
interprocedural dependencies and compute slices across procedure boundaries.
VIPER generalizes the dependency-closure pattern to heterogeneous repository
entities, including code, tests, contracts, checklist tasks, and external
resolution evidence. The conservative theorem in this appendix is a local
result under VIPER's declared dependency policy, distinct from the paper's
interprocedural slicing algorithm
([Horwitz, Reps, and Binkley 1990](https://doi.org/10.1145/77606.77608),
Sections 2–4).

Software reflexion models compare an expected high-level model with an
extracted source model and classify relations as convergence, absence, or
divergence. VIPER applies that comparison vocabulary when repair selection
freezes a planned graph projection. The authoritative general comparison is
$G_1\models T^*$; planned-versus-observed equality remains limited to the
represented scope
([Murphy, Notkin, and Sullivan 2001](https://doi.org/10.1109/32.917525),
Sections 2–3).

These sources establish separate primitives. The complete VIPER construction
is a local synthesis whose composition this appendix must prove:

```math
\begin{aligned}
R_0&\longrightarrow G_0, \\
(G_0,\Delta)&\longrightarrow(H_\Delta,S_\Delta)\longrightarrow B, \\
(\Delta,B)&\longrightarrow P, \\
(G_0,\Delta,P)&\longrightarrow T^*, \\
H_\Delta[B]&\longrightarrow D_B\longrightarrow\Pi
\longrightarrow\{\mathcal R_i\}\longrightarrow\{U_i^*\}, \\
(T^*,\Pi,\{U_i^*\})&\longrightarrow\mathcal Q
\longrightarrow R_1\longrightarrow G_1, \\
G_1&\models T^*.
\end{aligned}
```

When selection freezes all structural choices, the additional branch is

```math
\{U_i^*\}\longrightarrow U^*\longrightarrow G^*,
\qquad
G^*\models T^*,
\qquad
\mathcal F_\Sigma(G_1)=\mathcal F_\Sigma(G^*).
```

## A.10 Required next formal connectors

These definitions are sufficient to state soundness, graph-relative
minimality, target determinism, and represented conformance. Implementation
still requires five explicit connectors:

1. Compiler adapters must normalize every typed dependency edge into
   `dependent -> dependency` orientation and store non-dependency evidence
   outside $E$.
2. The contract-delta schema must represent mandatory operations separately
   from the observed revision-difference `SystemGraphDelta`.
3. `CompileTarget` must translate delta operations and total dispositions into
   canonical predicates and reject inconsistent target specifications.
4. The decomposition, repair-selection, and `CompileWork` connectors must
   preserve every target obligation, selected repair operation, and execution
   dependency in the generated PairBlocks.
5. The conformance contract must define target-predicate evaluation and, when
   a concrete $G^*$ exists, declare $\mathcal F_\Sigma$, including which
   evidence fields are compared and which are intentionally ignored.

These connectors should be added after the foundation receives review. That
sequence keeps proof review separate from contract-repair review.

## Works cited

Clarke, Dave, Michiel Helvensteijn, and Ina Schaefer. “Abstract Delta
Modeling.” In *Proceedings of the Ninth International Conference on Generative
Programming and Component Engineering (GPCE 2010)*, 13–22. ACM, 2010.
[https://doi.org/10.1145/1868294.1868298](https://doi.org/10.1145/1868294.1868298).

Ehrig, Hartmut, Karsten Ehrig, Ulrike Prange, and Gabriele Taentzer.
*Fundamentals of Algebraic Graph Transformation*. Berlin: Springer, 2006.
[https://doi.org/10.1007/3-540-31188-2](https://doi.org/10.1007/3-540-31188-2).

Horwitz, Susan, Thomas Reps, and David Binkley. “Interprocedural Slicing Using
Dependence Graphs.” *ACM Transactions on Programming Languages and Systems*
12, issue 1 (1990): 26–60.
[https://doi.org/10.1145/77606.77608](https://doi.org/10.1145/77606.77608).

Murphy, Gail C., David Notkin, and Kevin J. Sullivan. “Software Reflexion
Models: Bridging the Gap between Design and Implementation.” *IEEE
Transactions on Software Engineering* 27, issue 4 (2001): 364–380.
[https://doi.org/10.1109/32.917525](https://doi.org/10.1109/32.917525).
