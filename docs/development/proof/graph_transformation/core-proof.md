# Core proof of the System Impact Compiler

This document states the complete proof argument for VIPER's System Impact
Compiler. The [formal appendix](appendix-a-foundations.md) supplies the typed
graph-transformation definitions and detailed theorem statements. The
[compiler design](../../system-impact-compiler.md) maps the proof objects to
implementation phases.

The proof separates four claims. Conservative soundness uses one explicit
compiler-soundness assumption. Graph-relative minimality follows from the
reachability definition. Target determinism uses the compiler conditions in
Section 11. Conformance uses independent reconstruction under the same frozen
context.

## 1. Complete pipeline

```text
G0 + Delta
   |
   v
impact closure B
   |
   v
total dispositions P
   |
   v
target constraints T*
   |
   +---------------- completeness ends here
   |
   v
SCC condensation of H_Delta[B] and work partition Pi
   |
   v
candidate repairs {U1, U2, ...}
   |
   v
hard-validity filtering: Apply(G0, U) models T*
   |
   v
least-change / structural / semantic filtering
   |
   v
selector agent chooses U*
   |
   v
optional selected graph G* = Apply(G0, U*)
   |
   v
PairBlocks
   |
   v
R1 -> independently compiled G1
   |
   v
G1 models T* and, when G* is frozen, G1 conforms to G*
```

The repository-level proof trace is:

```text
R0
 | compile under frozen context X
 v
G0
 | combine baseline dependencies with direct additions from Delta
 v
H_Delta + initial vertex set S_Delta
 | reverse reachability
 v
B
 | assign one decision to every member
 v
P
 | compile Delta and P into requirements
 v
T*
 | decompose, select, and compile work
 v
PairBlocks
 | implement
 v
R1
 | independently recompile under X
 v
G1
 | check G1 models T*
 v
accept or reject
```

In everyday terms, VIPER first finds every represented repository entity that
may need attention. A plan assigns one required treatment to each entity. VIPER
then chooses work that satisfies those requirements, applies that work, and
rebuilds the graph from the changed repository to check the result. The
diagrams specify that protocol; each connector retains its documented
implementation status.

## 2. Compile the baseline repository

Let $R_0$ be the repository before the proposed change. The repository compiler
runs under one frozen context $X$:

```math
\mathcal C_X:\mathcal R\rightarrow\mathcal G.
```

The compiler produces:

```math
G_0=\mathcal C_X(R_0).
```

The reachability proof uses these concrete data types:

```python
VertexId = str
EdgeKind = str
TypedEdge = tuple[VertexId, EdgeKind, VertexId]

V_0: set[VertexId]
E_0: set[TypedEdge]
```

Let $\mathcal K_E$ be the finite set of allowed dependency kinds. The
reachability portion of the baseline graph is:

```math
G_0=(V_0,E_0),
\qquad
E_0\subseteq V_0\times\mathcal K_E\times V_0.
```

Here $V_0$ is a finite set of vertex identifiers. Every edge
$(u,k,v)\in E_0$ means that vertex $u$ depends on vertex $v$
through relationship kind $k$. The direction is always
`dependent -> dependency`. For example:

```python
("api.verify", "calls", "Runner.verify")
```

means that `api.verify` depends on `Runner.verify` through a call.

Reachability uses the untyped dependency projection:

```math
D_{G_0}
=
\left\{
(u,v)\in V_0\times V_0
\;\middle|\;
\exists k\in\mathcal K_E:\;(u,k,v)\in E_0
\right\}.
```

Mechanically:

```python
D_0 = {
    (source, target)
    for source, kind, target in E_0
}
```

Every typed dependency edge contributes. The type remains in $E_0$ so exact
verification can distinguish removal of an import from removal of a call.

### 2.1 Place CRT and delta compilation in the proof pipeline

Let $Q_0$ be the canonical contract-traceability graph compiled from the
baseline repository:

```math
Q_0=\operatorname{CompileTraceability}(R_0).
```

The repository compiler lowers the requirements, verifier rules, owners, and
tests in $Q_0$ into source-evidenced vertices and typed dependencies while
constructing $G_0$. A separate bootstrap-PairBlock parser contributes current
scheduling traceability to the same baseline graph. Both are internal compiler
stages; the public proof equation remains $G_0=\mathcal C_X(R_0)$.

Let $d_\Delta$ be the separately authored normative-change declaration. The
delta compiler runs after $G_0$ exists:

```math
\Delta
=
\operatorname{CompileContractDelta}(d_\Delta,G_0).
```

The two stages are:

```text
R0 -> CompileTraceability -> Q0 -> lower into G0

(d_Delta, G0) -> CompileContractDelta -> Delta
```

$Q_0$ supplies baseline traceability facts. $d_\Delta$ supplies the normative
change operations. `CompileContractDelta` validates $d_\Delta$ against $G_0$.
Bootstrap PairBlocks contribute scheduling traceability only to $G_0$; every
delta operation, member of $S_\Delta$, and introduced edge in $H_\Delta$ comes
from the explicit delta declaration.

## 3. Five-file baseline trace

The complete toy repository contains `models.py`, `storage.py`, `runner.py`,
`api.py`, and `tests/test_api.py`. At symbol granularity, the relevant baseline
dependencies are:

```text
test_verify
    |
    v
api.verify
    +----------------> ArtifactRef.path
    |
    v
Runner.verify
    |
    v
LocalArtifactStore.load
    |
    v
ArtifactRef.path
```

Therefore $D_{G_0}$ contains at least:

```python
D_0 = {
    ("test_verify", "api.verify"),
    ("api.verify", "Runner.verify"),
    ("api.verify", "ArtifactRef.path"),
    ("Runner.verify", "LocalArtifactStore.load"),
    ("LocalArtifactStore.load", "ArtifactRef.path"),
}
```

The [formal appendix](appendix-a-foundations.md#a6-why-the-contract-delta-is-insufficient)
contains all five source files and the typed dependency trace.

## 4. Represent the direct contract change

A contract delta is a finite family of explicit graph operations with a partial
order that records required application precedence:

```math
\Delta=(O_\Delta,\prec_\Delta).
```

The toy delta contains these direct requirements:

```text
REMOVE ArtifactRef.path
ADD ArtifactRef.source
ADD LocalSource
CHANGE LocalArtifactStore.load return type
ADD LoadedArtifact
```

The closed primitive operation set adds, removes, or updates nodes and typed
edges. The formal appendix defines the preconditions and DPO application
semantics for each operation.

The delta leaves the adaptations of `Runner.verify`, `api.verify`, and
`test_verify` open for propagation planning.

For each operation $o\in O_\Delta$, the vertex support
$\operatorname{support}_V(o)$ contains every vertex identifier that the
operation creates, removes, reads, updates, or names as an edge endpoint. The
delta-induced initial vertex set is:

```math
S_\Delta
=
\bigcup_{o\in O_\Delta}\operatorname{support}_V(o).
```

$S_\Delta$ contains the direct operation anchors. Reverse reachability expands
those anchors into the complete represented affected set $B$.

## 5. Construct the impact-analysis overlay

Let $V_\Delta^+$ contain the vertices directly added by $\Delta$. Let
$D_\Delta^+$ contain the untyped dependency pairs directly added or introduced
by updated edges in $\Delta$. Define:

```math
H_\Delta=(V_{H_\Delta},D_{H_\Delta}),
```

where:

```math
V_{H_\Delta}=V_0\cup V_\Delta^+,
\qquad
D_{H_\Delta}=D_{G_0}\cup D_\Delta^+.
```

$H_\Delta$ serves impact analysis. Target compilation occurs later. The overlay
retains baseline dependencies that the delta removes and adds dependencies that
the delta directly introduces. Traversal therefore covers both the old
structure being disrupted and the new structure being introduced.

Let $D_\Delta^-$ contain the baseline dependency pairs directly removed or
replaced by $\Delta$. Applying only the direct removals and additions would
yield:

```math
D_{\mathrm{direct}}
=
(D_{G_0}\setminus D_\Delta^-)\cup D_\Delta^+.
```

$D_{\mathrm{direct}}$ still omits the propagation changes selected later by
$P$ and can remove an old path before impact analysis has considered its
dependents.

## 6. Compute the blast radius

Write $x\leadsto_{H_\Delta}s$ when $x$ reaches $s$ through zero or more edges
in $D_{H_\Delta}$. A zero-edge path lets every initial vertex reach itself.

Define the blast radius:

```math
B
=
\left\{
x\in V_{H_\Delta}
\;\middle|\;
\exists s\in S_\Delta:\;x\leadsto_{H_\Delta}s
\right\}.
```

In the toy repository, the changed fields and types pull in their represented
dependents:

```text
changed fields and types
        ^
        |
LocalArtifactStore.load
        ^
        |
Runner.verify
        ^
        |
api.verify
        ^
        |
test_verify
```

$B$ therefore contains the directly changed vertices, `Runner.verify`,
`api.verify`, and `test_verify`.

## 7. Prove graph-relative minimality

A set $C\subseteq V_{H_\Delta}$ is an admissible predecessor-closed set when:

```math
S_\Delta\subseteq C,
```

and:

```math
(u,v)\in D_{H_\Delta}
\text{ and }v\in C
\quad\Longrightarrow\quad
u\in C.
```

Let $\mathfrak C$ contain every such set:

```math
\mathfrak C
=
\left\{
C\subseteq V_{H_\Delta}
\;\middle|\;
S_\Delta\subseteq C
\text{ and }C\text{ is predecessor-closed}
\right\}.
```

The requirement $S_\Delta\subseteq C$ matters: every admissible comparison set
must contain the vertices named directly by the delta. The full set
$V_{H_\Delta}$ is admissible, so $\mathfrak C$ is nonempty.

First, $B\in\mathfrak C$. Every $s\in S_\Delta$ reaches itself, so
$S_\Delta\subseteq B$. If $(u,v)\in D_{H_\Delta}$ and $v\in B$, then a path
$v\leadsto_{H_\Delta}s$ exists for some $s\in S_\Delta$. Prefixing that path
with $u\rightarrow v$ gives $u\leadsto_{H_\Delta}s$, so $u\in B$.

Second, choose any $C\in\mathfrak C$ and any $x\in B$. By the definition of
$B$, a path exists:

```math
x=v_0\rightarrow v_1\rightarrow\cdots\rightarrow v_n=s,
\qquad
s\in S_\Delta.
```

Because $S_\Delta\subseteq C$, the final vertex $v_n=s$ belongs to $C$.
Predecessor closure then forces $v_{n-1}\in C$, followed by $v_{n-2}\in C$,
and continuing backward until $v_0=x\in C$. Hence:

```math
\forall C\in\mathfrak C,\qquad B\subseteq C.
```

Since $B\in\mathfrak C$ and $B$ is contained in every member of
$\mathfrak C$:

```math
B=\bigcap_{C\in\mathfrak C}C.
```

Therefore $B$ is the unique least predecessor-closed superset of $S_\Delta$
under set inclusion. This theorem proves minimality relative to
$H_\Delta$. Section 8 states the separate assumption that connects
$H_\Delta$ to real semantic dependencies.

## 8. Prove conservative soundness

Let $D_X^{\mathrm{sem}}\subseteq
V_{H_\Delta}\times V_{H_\Delta}$ be the semantic dependency relation under
context $X$. A pair $(u,v)\in D_X^{\mathrm{sem}}$ means that a
contract-relevant change to $v$ may require changing or checking $u$.

Define the semantically affected set:

```math
A_\Delta
=
\left\{
x\in V_{H_\Delta}
\;\middle|\;
\exists s\in S_\Delta:\;x\leadsto_{\mathrm{sem}}s
\right\}.
```

The proof assumes that the compiler conservatively represents every semantic
dependency relevant to the contract:

```math
D_X^{\mathrm{sem}}\subseteq D_{H_\Delta}.
```

Take any $x\in A_\Delta$. A semantic path exists from $x$ to some
$s\in S_\Delta$. The edge-inclusion assumption places every edge in that
vertex sequence in $D_{H_\Delta}$. The same sequence is therefore an impact
path, so $x\in B$. Hence:

```math
A_\Delta\subseteq B.
```

This is the conservative blast-radius theorem. Extra represented edges can make
$B$ larger than $A_\Delta$. Omitting a semantic edge invalidates the
edge-inclusion assumption. An alternate represented path can still preserve
reachability for a particular vertex. The theorem-level guarantee fails once
the edge-inclusion assumption fails.

## 9. Assign a total propagation plan

$B$ determines which vertices require decisions. $P$ supplies those decisions.

A proof-level disposition contains the selected decision and the facts that the
future implementation must require, forbid, or preserve:

```python
Disposition = (
    decision,
    required_postconditions,
    forbidden_postconditions,
    preservation_predicates,
    rationale,
)
```

Let $\mathcal D$ be the set of admissible dispositions. A propagation plan is
a function:

```math
P:B\rightarrow\mathcal D.
```

The total-disposition validation rule is:

```math
\operatorname{dom}(P)=B.
```

Mechanically:

```python
set(P.keys()) == B
```

Because $P$ is a function, every affected vertex has exactly one disposition:

```math
\forall v\in B,\quad
\exists!d\in\mathcal D:\;P(v)=d.
```

The protocol validator enforces this property. The definition of $B$ alone
establishes only which vertices need dispositions.

The toy delta permits at least two different propagation plans:

```text
Plan A:
propagate LoadedArtifact through
LocalArtifactStore.load -> Runner.verify -> api.verify

Plan B:
LocalArtifactStore.load returns LoadedArtifact,
but Runner.verify extracts and returns bytes
```

The direct delta permits both plans. Selecting $P_A$ or $P_B$ determines how
the represented dependents must be treated.

## 10. Compile target constraints

The target compiler consumes the baseline graph, direct delta, and accepted
propagation plan:

```math
T^*=\operatorname{CompileTarget}(G_0,\Delta,P).
```

For the toy change, $T^*$ may contain:

```text
REQUIRE ArtifactRef.source
FORBID ArtifactRef.path
REQUIRE LocalSource
REQUIRE LoadedArtifact
REQUIRE LocalArtifactStore.load returns LoadedArtifact

REQUIRE the selected Runner.verify propagation behavior
REQUIRE the selected api.verify propagation behavior
REQUIRE the selected test_verify obligation
```

The central correction is:

```math
(G_0,\Delta)
\text{ generally does not determine one complete }G^*.
```

$\Delta$ defines the direct contract change. $P$ defines the required treatment
of the represented consequences. Even fixed $(G_0,\Delta,P)$ may permit several
implementation structures. Define:

```math
\mathcal A(T^*)
=
\left\{
G\;\middle|\;G\models T^*
\right\}.
```

A helper function and direct construction can produce different graphs while
both satisfy the same constraints. Therefore $T^*$ is authoritative unless
repair selection explicitly freezes one planned graph $G^*$.

## 11. Establish deterministic target derivation

The same $(G_0,\Delta,P)$ produces the same $T^*$ when all of these protocol
conditions hold:

1. $G_0$ has a canonical representation.
2. Compiler context $X$ is frozen.
3. Every node and edge anchor resolves uniquely.
4. $\Delta$ has explicit operations, preconditions, application order, and
   conflict handling.
5. $P$ is total and single-valued over $B$.
6. `CompileTarget` uses a fixed translation and canonical ordering.
7. Every unordered operation pair either commutes or has a deterministic
   conflict rule.

These conditions establish deterministic constraint derivation:

```math
(G_0,\Delta,P)\longmapsto T^*.
```

These conditions determine $T^*$ only. A unique $G^*$ requires a selector that
freezes every relevant structural alternative, deterministic graph-rewrite
application, and canonical graph serialization.

## 12. Decompose, select, and compile PairBlocks

Completeness is fixed once $T^*$ contains every hard obligation induced by the
total plan. The later stages choose and schedule an implementation that
satisfies those obligations.

First, condense the strongly connected components of the affected graph
$H_\Delta[B]$ and partition the resulting acyclic component graph into work
units $\Pi$. Candidate generation produces repair operation sets
$\{U_1,U_2,\ldots\}$. Every surviving candidate must satisfy:

```math
\operatorname{Apply}(G_0,U)\models T^*.
```

Least-change, structural, semantic, cost, and risk filters may reduce the
hard-valid candidate set. A selector agent may choose $U^*$ only among the
remaining candidates. If the protocol freezes that selection, it defines:

```math
G^*=\operatorname{Apply}(G_0,U^*).
```

Selection succeeds only when the hard-valid candidate set is nonempty. An
empty candidate set rejects the plan. Repair determinism requires fixed filter
objectives, canonical tie handling, and a deterministic selector.
Target determinism establishes the same $T^*$ for the same inputs; it leaves
repair selection as a separate obligation.

The selected work compiles into PairBlocks containing:

```text
owned dispositions
source targets
originating deltas
required postconditions
forbidden postconditions
execution dependencies
tests
verification requirements
```

The artifact roles are distinct:

```text
P
-> defines the required treatment of every member of B

T*
-> compiles those decisions into authoritative target constraints

PairBlocks
-> assign the selected implementation work to bounded executions
```

Executing the PairBlocks transforms the repository:

```math
R_0\xrightarrow{\text{PairBlocks}}R_1.
```

The work compiler must assign every hard obligation in $T^*$ to at least one
generated PairBlock and reject contradictory ownership. This coverage theorem
is a remaining implementation proof obligation. The blast-radius, minimality,
and target-determinism results establish its inputs.

## 13. Independently reconstruct and verify the result

After implementation, the same frozen repository compiler independently
reconstructs the observed graph:

```math
G_1=\mathcal C_X(R_1).
```

The compiler inspects $R_1$ directly. Independent reconstruction keeps the
verification evidence separate from agent reports and from the plan that the
verifier checks.

The authoritative structural acceptance condition is:

```math
G_1\models T^*.
```

General acceptance requires $G_1\models T^*$. When repair selection freezes one
$G^*$, the protocol may also require equality over a declared comparison scope.

When a planned graph is frozen, let $\Sigma$ be the declared comparison scope
and let $\mathcal F_\Sigma(G)$ extract the represented facts inside that scope.
Compare:

```math
\mathcal F_\Sigma(G_1)
\quad\text{with}\quad
\mathcal F_\Sigma(G^*).
```

The comparison identifies:

```math
\operatorname{missing}
=
\mathcal F_\Sigma(G^*)\setminus\mathcal F_\Sigma(G_1),
```

```math
\operatorname{unexpected}
=
\mathcal F_\Sigma(G_1)\setminus\mathcal F_\Sigma(G^*),
```

and:

```math
\operatorname{convergent}
=
\mathcal F_\Sigma(G_1)\cap\mathcal F_\Sigma(G^*).
```

This comparison proves only represented structural conformance inside $\Sigma$.
Behavioral correctness, security, and performance require separate evidence.
Properties outside the observation boundary of $\mathcal C_X$ remain outside
the structural proof. Behavioral tests supply a separate acceptance layer.

## 14. Complete claim

Under the dependency-conservativeness assumption:

```math
A_\Delta\subseteq B.
```

By graph construction:

```math
B
=
\text{the unique least predecessor-closed superset of }S_\Delta.
```

By plan validation:

```math
\operatorname{dom}(P)=B.
```

By deterministic target compilation:

```math
T^*=\operatorname{CompileTarget}(G_0,\Delta,P).
```

By implementation and independent reconstruction:

```math
R_1\xrightarrow{\mathcal C_X}G_1.
```

Acceptance requires:

```math
G_1\models T^*.
```

Conditional on successful repair selection and work compilation, the complete
VIPER synthesis is:

```math
\begin{aligned}
R_0&\longrightarrow G_0, \\
(G_0,\Delta)&\longrightarrow(H_\Delta,S_\Delta)\longrightarrow B, \\
(\Delta,B)&\longrightarrow P, \\
(G_0,\Delta,P)&\longrightarrow T^*, \\
H_\Delta[B]&\longrightarrow D_B\longrightarrow\Pi, \\
(T^*,\Pi)&\longrightarrow\{U_i\}\longrightarrow U^*, \\
U^*&\longrightarrow G^*\ \text{ when selection is frozen}, \\
(T^*,\Pi,U^*)&\longrightarrow\text{PairBlocks}\longrightarrow R_1, \\
R_1&\xrightarrow{\mathcal C_X}G_1, \\
G_1&\models T^*.
\end{aligned}
```

Clarke, Helvensteijn, and Schaefer supply the
[explicit-delta foundation](https://doi.org/10.1145/1868294.1868298). Ehrig
and the algebraic graph-transformation literature supply
[rewrite application conditions](https://doi.org/10.1007/3-540-31188-2).
Horwitz, Reps, and Binkley supply
[dependence-graph slicing](https://doi.org/10.1145/77606.77608). Murphy,
Notkin, and Sullivan supply
[intended-versus-observed structural comparison](https://doi.org/10.1109/32.917525).
The
[formal appendix](appendix-a-foundations.md#a9-relationship-to-prior-work) maps each
cited primitive to this VIPER-specific composition.
