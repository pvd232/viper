# Appendix A: Graph-transformation foundations

This appendix defines the graph-transformation claim that VIPER must establish
before implementing planned-system compilation. A contract delta identifies
the mandatory mutations. Reverse dependency closure identifies every graph
entity that must receive a disposition. A propagation plan, carried by ordered
`PairBlock` records, supplies the decisions that the contract delta leaves
open. The planned graph therefore has the form

```math
G^* = \operatorname{Apply}(G_0,\Delta \oplus \Theta(P)),
```

where $\Theta(P)$ compiles the propagation plan into graph operations. A
complete $G^*$ generally depends on both $\Delta$ and $P$.

This document is a starter proof. Its definitions and propositions are local
design proposals that leave the active contracts unchanged. The existing
[`SystemGraphDelta`](../../system-impact-graph.md#graph-delta-and-impact-report)
is an observed difference between two compiled source revisions. The
contract delta $\Delta$ below is a normative input that describes required
future mutations. A later contract revision must keep those two objects
distinct.

## A.1 Proof contract

The proof has four targets:

1. **Soundness:** the blast radius contains every entity that the contract
   change can affect, subject to a conservative dependency-extraction
   assumption.
2. **Minimality:** reverse reachability returns the smallest
   predecessor-closed set that contains the directly changed seeds.
3. **Target determinism:** a valid contract delta plus a complete propagation
   plan produces one planned graph.
4. **Conformance:** the post-implementation comparison classifies every
   represented fact as convergence, absence, or divergence.

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
├── direct seed set
└── dependency-conservativeness assumption

minimal-closure theorem
├── reverse-reachability definition
└── predecessor-closed-set definition

target-determinism theorem
├── total propagation plan
├── PairBlock dependency order
├── plan-to-operation compilation
├── unique anchors and satisfied preconditions
└── ordered or confluent conflicting operations

post-implementation conformance
├── common compiler and context
├── canonical represented-fact projection
└── stable identity or an explicit correspondence map
```

The resulting lifecycle preserves the decomposition developed before this
appendix:

```text
1. Repository compilation       R0 -> G0
2. Contract transformation      Delta defines mandatory mutation seeds
3. Conservative impact          (G0, Delta) -> B
4. Total propagation planning   (Delta, B) -> P
5. Planned-system compilation   (G0, Delta, P) -> G*
6. Implementation               P -> R1
7. Repository recompilation     R1 -> G1
8. Conformance                  G1 <-> G*
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
finite set of node kinds, $\mathcal K_E$ a finite set of edge kinds, and
$\mathcal A$ a set of canonical attribute maps.

**Definition A.2 (system graph).** A system graph is a finite typed attributed
directed multigraph

```math
G=(V,E,s,t,\tau_V,\tau_E,\alpha_V,\alpha_E),
```

with:

- $V\subseteq\mathcal I$, a finite set of node identifiers;
- $E\subseteq\mathcal I$, a finite set of edge identifiers disjoint from $V$;
- $s,t:E\rightarrow V$, the source and target functions;
- $\tau_V:V\rightarrow\mathcal K_V$ and
  $\tau_E:E\rightarrow\mathcal K_E$, the node and edge type functions; and
- $\alpha_V:V\rightarrow\mathcal A$ and
  $\alpha_E:E\rightarrow\mathcal A$, the canonical attribute functions.

Edge identifiers permit two edges with equal endpoints and different kinds or
evidence. Stable node identifiers preserve exact revision comparison. The
existing [system-impact contract](../../system-impact-graph.md#identifiers-and-kinds)
already distinguishes file, span, and external nodes and records typed edge
evidence.

Let $X$ be one fixed `SystemContextManifest`. Let $C_X$ be the repository
compiler under that context.

**Definition A.3 (baseline and observed graphs).** When strict compilation
succeeds,

```math
G_0=C_X(R_0)
\qquad\text{and}\qquad
G_1=C_X(R_1).
```

The compilation result includes the inventory, one analysis receipt per
tracked file, edge evidence, resolution observations, and the unresolved set.
The strict proof boundary requires the unresolved set to be empty. Equal
inputs must produce equal canonical graphs; target determinism otherwise fails
before transformation begins.

### Dependency orientation

`SystemEdgeKind` contains relations with different surface directions. A
`defines` edge and a `calls` edge require relation-specific traversal rules.

**Definition A.4 (dependency interpretation).** A dependency policy is a
partial function

```math
\rho_X : \mathcal K_E \times V \times V
\rightharpoonup V\times V.
```

For an edge $e$, if
$\rho_X(\tau_E(e),s(e),t(e))=(x,y)$, then $x$ is the dependent and $y$ is the
dependency. Write $x\rightarrow_G y$. An edge kind outside the domain of
$\rho_X$ carries evidence only. Each included edge kind declares its
orientation in the contract, and the proof uses that declaration.

Let $\rightarrow_G^*$ denote the reflexive transitive closure of
$\rightarrow_G$. Reflexivity makes every seed a member of its own blast
radius.

## A.3 Contract delta and direct seeds

Let $\mathcal O$ contain these primitive operations over stable anchors:

```text
AddNode(id, kind, attributes)
RemoveNode(id, expected-kind, expected-attributes)
SetNodeAttributes(id, expected, replacement)
AddEdge(id, source, target, kind, attributes)
RemoveEdge(id, source, target, kind, expected-attributes)
SetEdgeAttributes(id, expected, replacement)
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

**Definition A.6 (direct seed set).** The support of an operation is the set of
node anchors that it creates, removes, reads, updates, or names as an edge
endpoint. The direct seed set is

```math
S_\Delta
=
\bigcup_{o\in O_\Delta}\operatorname{support}(o).
```

An edge edit therefore seeds both endpoints. A removal retains its old anchor
and old incident dependencies during impact analysis; otherwise deletion would
erase the evidence needed to find existing dependents.

### Impact overlay

Let $V_\Delta^+$ be the nodes added by $\Delta$, and let
$D_\Delta^+$ be the dependency pairs introduced by added or updated edges in
$\Delta$ after applying $\rho_X$.

**Definition A.7 (impact overlay).** The impact overlay
$H_\Delta=(V_H,D_H)$ is the dependency graph with

```math
V_H=V_0\cup V_\Delta^+,
\qquad
D_H=D_{G_0}\cup D_\Delta^+.
```

The union deliberately retains baseline edges that $\Delta$ removes and adds
new contract relationships. The overlay serves impact analysis only. Definition
A.13 constructs the planned target graph.

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

Take $\rightsquigarrow_X$ as the semantic may-affect relation under context
$X$: $x\rightsquigarrow_X y$ means that changing the represented obligation
of $y$ can require reconsidering the represented obligation of $x$.

**Definition A.9 (potentially affected entity).** The semantic affected set is

```math
A_\Delta
=
\left\{
x\in V_H
\;\middle|\;
\exists s\in S_\Delta:\;x\rightsquigarrow_X s
\right\}.
```

The relation includes possible changes to existence, type, represented
attributes, and represented relationships. It is a semantic proof primitive;
the algorithm computes $B$ from extracted graph dependencies.

**Assumption A.1 (dependency conservativeness).** For every
$x\in A_\Delta$, the impact overlay contains a path from $x$ to a direct seed:

```math
\forall x\in A_\Delta\;\exists s\in S_\Delta:
x\rightarrow_{H_\Delta}^*s.
```

The `FileAnalysisReceipt`, `ResolutionAttempt`, and
`UnresolvedDependency` records establish the evidence boundary for this
assumption. Empty unresolved output establishes total resolution for the
compiler's declared analyzers and fixed context. Completeness over arbitrary
Python semantics requires the analyzer set to model every relevant dependency.

### Theorem A.1: conservative blast radius

Under Assumption A.1,

```math
A_\Delta\subseteq B.
```

**Proof.** Let $x\in A_\Delta$. Assumption A.1 supplies
$s\in S_\Delta$ such that $x\rightarrow_{H_\Delta}^*s$. Definition A.8 then
gives $x\in B$. Since $x$ was arbitrary, $A_\Delta\subseteq B$. $\square$

This theorem locates the guarantee. Reverse reachability is exact for the
extracted dependency relation. Missing reflection targets, registry edges,
subprocess entrypoints, generated artifacts, contract links, or other
relationships invalidate Assumption A.1 for the omitted entities.

### Theorem A.2: minimal predecessor-closed set

**Definition A.10 (predecessor closed).** A set $Q\subseteq V_H$ is
predecessor closed when

```math
\forall(x,y)\in D_H:\;y\in Q\Longrightarrow x\in Q.
```

The blast radius $B$ is the unique smallest predecessor-closed subset of
$V_H$ that contains $S_\Delta$.

**Proof.** Reflexivity of $\rightarrow^*$ gives $S_\Delta\subseteq B$. If
$y\in B$ and $(x,y)\in D_H$, then $y\rightarrow^*s$ for some seed $s$.
Prepending $(x,y)$ gives $x\rightarrow^*s$, so $x\in B$. Thus $B$ is
predecessor closed.

Let $Q$ be any predecessor-closed set with $S_\Delta\subseteq Q$. For any
$x\in B$, choose a path
$x=v_0\rightarrow v_1\rightarrow\cdots\rightarrow v_n=s$ with
$s\in S_\Delta$. Since $s\in Q$, predecessor closure applied backward along
the finite path gives $v_{n-1},\ldots,v_0=x\in Q$. Hence $B\subseteq Q$.
Every admissible $Q$ contains $B$, so $B$ is the unique smallest one.
$\square$

Minimality is relative to $H_\Delta$. Adding a conservative dependency edge
can enlarge $B$. Removing a real dependency edge can make the computed set
unsound even though it remains minimal for the defective overlay.

## A.5 Propagation plan and PairBlocks

The active [propagation-plan contract](../../system-impact-graph.md#graph-delta-and-impact-report)
groups affected nodes by repository path. Let
$D_1,\ldots,D_m$ be its `PropagationDisposition` records, and let
$N_1,\ldots,N_k$ be its `PlannedAddition` records.

Partition the blast radius into existing and introduced entities:

```math
B_0=B\cap V_0,
\qquad
B_+=B\setminus V_0.
```

**Definition A.11 (total disposition).** A propagation plan is disposition
total over $B_0$ when the affected-node sets form a partition of $B_0$:

```math
\bigcup_{i=1}^{m}\operatorname{nodes}(D_i)=B_0
```

and

```math
i\neq j
\Longrightarrow
\operatorname{nodes}(D_i)\cap\operatorname{nodes}(D_j)=\varnothing.
```

Each existing path has one action in
$\{\mathrm{change},\mathrm{remove},\mathrm{retain}\}$. Every retained path
states why its represented obligation remains satisfied. Planned additions
cover newly introduced paths, and their represented node sets partition $B_+$.

The path-level records induce a node-level function

```math
p_P:B_0\rightarrow
\{\mathrm{change},\mathrm{remove},\mathrm{retain}\},
```

where $p_P(b)$ is the action of the unique disposition containing $b$. With
planned additions included, the extended function

```math
\overline p_P:B\rightarrow
\{\mathrm{add},\mathrm{change},\mathrm{remove},\mathrm{retain}\}
```

is total. This is the well-typed form of the earlier shorthand
$P:B\rightarrow\{\mathrm{change},\mathrm{remove},\mathrm{retain}\}$.

**Proposition A.3 (total-disposition property).** If Definition A.11 holds,
then every existing entity in $B_0$ receives exactly one implementation
disposition. If planned additions partition $B_+$, every entity in $B$ receives
exactly one extended action.

**Proof.** Union equality gives existence: every $b\in B_0$ belongs to at least
one disposition. Pairwise disjointness gives uniqueness because membership in
two dispositions would place $b$ in their empty intersection. The same
argument applies to the planned-addition partition of $B_+$. $\square$

The [Phase 0 PairBlock contract](../../phase-0-pair-coding.md#1-pairblock-contract)
provides the concrete plan carrier. Each checklist task owns one `PairBlock`
with stable requirements, exact source targets, exact tests, one gate, and
dependencies on earlier blocks. Let $\mathcal Q_P$ be the finite set of blocks
selected by plan $P$, and let $\prec_P$ be the transitive closure of their
`depends_on` edges.

For planned-system compilation, a PairBlock must also have a deterministic
interpretation as graph postconditions or primitive graph operations. Define

```math
\Theta(P)
=
\operatorname{compile\_plan}(\mathcal Q_P,\prec_P).
```

The complete marked PairBlock supplies the exact bounded code edit in addition
to target spans, tests, gates, and order. PairBlocks therefore carry the
planned-propagation component developed in the prior derivation. Target
derivation requires `compile_plan` to give that marked content a deterministic
graph interpretation: either extract the resulting graph postconditions from
the complete code edit or record those postconditions explicitly. This
appendix defines that formal connector while leaving the existing contract
unchanged.

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

The direct seeds are approximately:

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
`LocalSource`, or another contract-compatible boundary. A PairBlock must record
that propagation decision before planned-system compilation.

## A.7 Planned graph and deterministic target derivation

**Definition A.12 (combined operation family).** Let

```math
\Omega(\Delta,P)
=
\operatorname{normalize}(O_\Delta\cup\Theta(P),
\prec_\Delta\cup\prec_P\cup\prec_{\mathrm{cross}}),
```

where $\prec_{\mathrm{cross}}$ orders plan operations whose preconditions
depend on contract operations. Normalization rejects duplicate operation IDs,
incompatible postconditions, and unsatisfied references.

**Definition A.13 (planned graph).** If the normalized operation family has a
valid derivation from $G_0$, then

```math
G^*=\operatorname{Apply}(G_0,\Omega(\Delta,P)).
```

Nodes and edges outside the operation support are inherited from $G_0$.

### Theorem A.4: deterministic target derivation

The inputs $(G_0,\Delta,P)$ determine one canonical $G^*$ when all of these
conditions hold:

1. $C_X$ is deterministic and $G_0$ is canonical.
2. Every referenced node and edge anchor resolves uniquely.
3. $P$ is disposition total over $B_0$, its planned additions partition $B_+$,
   and each plan action compiles to explicit graph postconditions through
   $\Theta$.
4. The combined dependency order is acyclic and therefore has a linear
   extension.
5. Every operation precondition holds at its application point.
6. Every DPO match satisfies its application and gluing conditions, including
   the dangling condition for deletions.
7. Every pair of operations unordered by the dependency order either commutes
   or has a specified conflict-resolving operation that gives the same normal
   form.
8. Every derivation terminates and preserves the declared graph constraints.
9. Canonical serialization erases irrelevant execution-order differences.

**Proof.** Conditions 1 and 2 fix the initial graph and the denotation of every
anchor. Conditions 3 and 4 produce a finite executable operation family.
Condition 5 makes each anchored operation eligible. Condition 6 makes each DPO
rewrite defined. Condition 7 makes every permitted ordering produce the same
graph before canonicalization. Condition 8 ensures that each derivation reaches
a valid terminal graph. Condition 9 gives that terminal
graph one serialized identity. Hence every valid derivation of
$\Omega(\Delta,P)$ from $G_0$ yields the same canonical $G^*$. $\square$

Condition 7 may be established by a fixed total order, by pairwise commutation,
or by a confluence argument with conflict-resolution rules. An acyclic
PairBlock dependency graph establishes Condition 4 alone. Operation
commutation or confluence requires separate evidence.

## A.8 Implemented repository and observed graph

Implementation applies the selected PairBlocks to $R_0$ and produces $R_1$.
Strict recompilation under the same context gives $G_1=C_X(R_1)$.

Let $\Sigma$ be the declared conformance scope, and let
$\mathcal F_\Sigma(G)$ be the canonical set of represented facts inside that
scope. A fact records one of these forms:

```text
node(id, kind, canonical attributes)
edge(id, dependent, dependency, kind, canonical attributes)
```

The scope excludes evidence fields whose values may legitimately differ
between planned and observed compilation, such as source line numbers, while
retaining every field that the plan claims as a postcondition.

**Definition A.14 (conformance partition).** Let

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

Convergences are planned facts observed after implementation. Absences are
planned facts missing from the implementation. Divergences are observed facts
outside the plan.

**Proposition A.5 (represented structural conformance).** The observed graph
conforms to the planned graph in scope $\Sigma$ exactly when

```math
\operatorname{Abs}=\varnothing
\qquad\text{and}\qquad
\operatorname{Div}=\varnothing.
```

**Proof.** Both differences are empty exactly when $F^*\subseteq F_1$ and
$F_1\subseteq F^*$. By set extensionality, those inclusions hold exactly when
$F^*=F_1$. $\square$

Phase 0 uses stable identities and exact set difference. If a future comparison
lacks shared identities, the comparison must first provide an explicit
correspondence map or a normalized graph isomorphism. The conformance theorem
therefore requires more than an implicit name match.

### Limits of the comparison

The comparison proves equality only for facts emitted by $C_X$ and retained by
$\mathcal F_\Sigma$. Arbitrary functional correctness, program termination,
numerical correctness, security, and behavior under an undeclared context
remain outside that result. A compiler omission leaves the corresponding
implementation defect unobservable.

The same compiler and context must produce $G_0$ and $G_1$. A compiler-version
change or context change introduces another independent delta and makes a raw
set comparison ambiguous.

Absence and divergence also require policy. Some observed implementation facts
may be intentionally unconstrained by the plan; the comparison scope must
exclude them before the partition is interpreted as failure. Conversely, every
claimed target postcondition must remain inside the scope.

## A.9 Relationship to prior work

The proof imports one primitive from each source family:

| Source | Imported primitive | VIPER proof role |
| --- | --- | --- |
| [Clarke, Helvensteijn, and Schaefer 2010](https://doi.org/10.1145/1868294.1868298) | Explicit deltas, composition, conflict resolution, and unambiguous derivation | Definition of $\Delta$ and target-determinism Condition 7 |
| [Ehrig et al. 2006](https://doi.org/10.1007/3-540-31188-2) | DPO rule application, application and gluing conditions, preservation, constraints, confluence, and termination | Semantics of $\operatorname{Apply}(G_0,\Delta\oplus\Theta(P))$ |
| [Horwitz, Reps, and Binkley 1990](https://doi.org/10.1145/77606.77608) | Dependence-graph representation and interprocedural slicing | Dependency relation, reverse closure, and blast-radius argument |
| [Murphy, Notkin, and Sullivan 2001](https://doi.org/10.1109/32.917525) | Intended-versus-extracted structural comparison | Convergence, absence, and divergence for $G^*$ versus $G_1$ |

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
divergence. VIPER applies that comparison vocabulary to canonical planned and
observed graph facts. The equality claim remains limited to the represented
scope ([Murphy, Notkin, and Sullivan 2001](https://doi.org/10.1109/32.917525),
Sections 2–3).

These sources establish separate primitives. The complete VIPER construction
is a local synthesis whose composition this appendix must prove:

```math
\begin{aligned}
R_0&\longrightarrow G_0,
& (G_0,\Delta)&\longrightarrow B,
& (\Delta,B)&\longrightarrow P, \\
(G_0,\Delta,P)&\longrightarrow G^*,
& R_1&\longrightarrow G_1,
& G_1&\longleftrightarrow G^*.
\end{aligned}
```

## A.10 Required next formal connectors

These definitions are sufficient to state soundness, graph-relative
minimality, target determinism, and represented conformance. Implementation
still requires four explicit connectors:

1. The system-impact contract must assign every propagating `SystemEdgeKind`
   one dependency orientation through $\rho_X$.
2. The contract-delta schema must represent mandatory operations separately
   from the observed revision-difference `SystemGraphDelta`.
3. `PropagationPlan` and its ordered PairBlocks must compile into explicit
   graph postconditions through $\Theta$.
4. The conformance contract must declare $\mathcal F_\Sigma$, including which
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
