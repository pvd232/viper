# System Impact Check

This contract verifies an existing implementation plan. Contract Traceability
owns requirements, rules, exact source targets, PairBlocks, tests, gates, and
dependency order. The System Impact Check uses CodeQL to inspect the source
before and after those PairBlocks run.

The check has one bounded job:

```text
validated ContractTraceabilityGraph
+ CodeQL baseline source graph
+ CodeQL candidate source graph
-> impact report
-> one check per declared target
-> reject unplanned source changes
```


`ContractTraceabilityGraph` supplies the plan and selected PairBlocks. Each
PairBlock gate remains the behavioral acceptance boundary. The pre-pairing
command also records the policy-selected direct neighborhood in both source
graphs and rejects a candidate that fails Pyright.

## 1. Status

**Contract status:** complete.

| ID | Implementation obligation |
| --- | --- |
| SIG-01 <!-- contract-requirement: SIG-01 phase=0 test=tests/test_system_impact.py --> | Run one pinned CodeQL query pack over an immutable source snapshot and return a canonical `SourceGraph` whose nodes retain exact UTF-8 byte spans and declaration digests. |
| SIG-02 <!-- contract-requirement: SIG-02 phase=0 test=tests/test_system_impact.py --> | Resolve every `ContractTarget` against the baseline `SourceGraph`, classify its planned declaration change, reject an impossible action, and report every direct baseline dependent connected through an `EdgeKind` selected by impact-policy version 1. |
| SIG-03 <!-- contract-requirement: SIG-03 phase=0 test=tests/test_system_impact.py --> | Freeze the selected PairBlocks and candidate source once; verify their plan digest, dependencies, gates, target actions, and exact declarations; reject unplanned source changes; and bind a passing check to the commit containing the checked source and selected plan. |
| SIG-04 <!-- contract-requirement: SIG-04 phase=0 test=tests/test_system_impact.py --> | Replay the check over the committed `model_support` to `models` migration and one completed VIPER PairBlock, then compare its result with the exact Git diff. |
| SIG-05 <!-- contract-requirement: SIG-05 phase=0 test=tests/test_system_impact.py --> | Persist the CodeQL command, version, query-pack digest, source-snapshot digest, optional commit, exit status, and decoded-result digest for both source graphs; reject identity or receipt drift. |
| SIG-06 <!-- contract-requirement: SIG-06 phase=0 test=tests/test_system_impact.py --> | Emit `writes` edges for direct name and attribute assignments whose writing declaration and assignment target both resolve to `SourceNode` records, retaining the assignment location as edge evidence. |
| SIG-07 <!-- contract-requirement: SIG-07 phase=0 test=tests/test_system_impact.py --> | Derive the policy-selected one-hop node and edge delta from the baseline graph and the CodeQL translation of the materialized PairBlocks, reject every changed declaration absent from those blocks, and reject the materialized candidate when Pyright finds a static interface error. |

## 2. Required claim

Given a validated `ContractTraceabilityGraph` $Q$, baseline snapshot $R_0$,
frozen candidate snapshot $R^*$, and one pinned CodeQL identity $K$, VIPER can
answer:

```text
Did every planned add, update, or removal occur?
Did the realized declaration equal the declaration required by the plan?
Did implementation change any source declaration absent from the plan?
Which direct source declarations depend on each planned target before or after the change?
Did both observations use the same CodeQL identity?
```

CodeQL produces the baseline graph:

$$
G_0=\operatorname{Analyze}_{K}(R_0).
$$

For selected PairBlocks $B_P$, the CTG supplies plan $P$, target set $T_P$,
dependency order $\prec_P$, and the authored source delta $\Delta_P$:

$$
P=(B_P,T_P,\prec_P),
\qquad
\Delta_P(t)\in\{\operatorname{add}(h),\operatorname{update}(h),
\operatorname{remove}\},
$$

where $t$ is one repository declaration and $h$ is the SHA-256 digest of its
authored declaration bytes. The scheduler constructs candidate source $R^*$,
and CodeQL observes candidate graph $G^*$:

$$
R^*=\operatorname{Materialize}(R_0,\Delta_P,\prec_P),
\qquad
G^*=\operatorname{Analyze}_{K}(R^*).
$$

Let $\eta_G(t)$ be declaration $t$'s digest in graph $G$, or $\bot$ when the
declaration is absent. The observed declaration delta is:

$$
\Delta(G_0,G^*)=
\{t\mid\eta_{G_0}(t)\ne\eta_{G^*}(t)\}.
$$

System Impact computes $C=\operatorname{CheckPlan}(P,G_0,G^*)$:

$$
\begin{aligned}
C.\mathrm{passed}\iff{}&
\operatorname{TargetsMatch}(\Delta_P,G_0,G^*)
\land \Delta(G_0,G^*)\subseteq\operatorname{Owned}(T_P) \\
&\land \operatorname{DependenciesSatisfied}(P,G_0)
\land \operatorname{GatesPass}(B_P) \\
&\land \operatorname{PlanDigestValid}(P)
\land \operatorname{SourceDigestsValid}(R_0,R^*) \\
&\land \operatorname{ReceiptsValid}_{K}(G_0,G^*)
\land \operatorname{OneHopValid}(P,G_0,G^*).
\end{aligned}
$$

The pre-pairing command returns result $V$ after constructing $R^*$ and calling
System Impact:

$$
\begin{aligned}
V.\mathrm{passed}\iff{}&
\operatorname{Clean}(R_0)
\land \operatorname{Defined}(R^*)
\land \operatorname{Pyright}(R^*)=0 \\
&\land C.\mathrm{passed}
\land \operatorname{PrivateOwnersConsumed}(G^*).
\end{aligned}
$$

The following rules expand $C.\mathrm{passed}$. For the `ContractTarget`
records owned by `PlanCheck.blocks`,
`PlanCheck.passed` is true exactly when:

1. every `add` target is absent from $G_0$ and present in $G^*$;
2. every `update` target is present in both graphs and its realized declaration
   equals the declared target value;
3. every `remove` target is present in $G_0$ and absent from $G^*$;
4. every changed source declaration belongs to a `ContractTarget` whose
   `block_id` appears in `PlanCheck.blocks`;
5. VIPER runs every frozen selected `PairBlock.gate` once and every command
   exits with code `0`;
6. every omitted PairBlock dependency already has all of its declared target
   states in $G_0$;
7. `plan_sha256` equals the digest recomputed from the frozen selected blocks,
   targets, dependencies, tests, gates, and supporting-asset bytes; and
8. both graphs have valid receipts for the same $K$.

The check applies only to the selected PairBlocks. A selected block may omit a
dependency when every `ContractTarget` owned by that dependency already matches
the baseline graph. `PlanCheck.baseline_dependencies` records those satisfied
dependencies. `PlanCheck.unsatisfied_dependencies` records the rest and makes
the check fail. The source graph decides whether an omitted dependency is
satisfied; checklist status supplies no evidence for this decision.

`PlanCheck` evaluates the frozen candidate before commit. After commit,
`accept()` recomputes the source digest and selected-plan digest from the
committed tree. Both values must equal `PlanCheck.realized.source_sha256` and
`PlanCheck.plan_sha256`. The plan digest also binds each selected
`PairBlock.assets` path and its exact bytes. Equality produces an `Acceptance`;
either mismatch rejects the commit. The accepted commit becomes the baseline
for the next block or contract.

The impact report identifies direct source declarations that may need
attention. `classify_target_change()` compares each baseline declaration with
its authored replacement. Impact-policy version 1 selects the `SourceEdge.kind`
values that can carry that kind of change. The report is complete only over
the direct edges present in the pinned baseline `SourceGraph`. Runtime
dependency coverage remains outside this guarantee. A `ContractTarget`
identifies each dependent declaration that must change.
The realized-delta check supplies the enforceable boundary: if implementation
does change a dependent, that declaration must already be a `ContractTarget`.

Let $S_\Delta$ contain the selected target nodes present in either source
graph. For the edge-kind policy $K_1$ already defined by
`IMPACT_EDGE_KINDS_V1`, the checked direct edges are:

$$
E_0^{(1)}=\{(u,v,k)\in E_0\mid v\in S_\Delta\land k\in K_1(v)\},
$$

$$
E_*^{(1)}=\{(u,v,k)\in E_*\mid v\in S_\Delta\land k\in K_1(v)\}.
$$

The direct neighborhood is:

$$
B^{(1)}=S_\Delta\cup
\{u\mid\exists v\in S_\Delta:(u,v,k)\in E_0^{(1)}\cup E_*^{(1)}\}.
$$

`OneHop` is the exact CodeQL edge delta induced by the materialized contract
source:

$$
\begin{aligned}
\mathrm{before} &= \operatorname{ids}(E_0^{(1)}), \\
\mathrm{after} &= \operatorname{ids}(E_*^{(1)}), \\
\mathrm{removed} &= \mathrm{before}\setminus\mathrm{after}, \\
\mathrm{added} &= \mathrm{after}\setminus\mathrm{before}.
\end{aligned}
$$

`SourceGraph` construction rejects duplicate nodes, duplicate edges, unknown
edge endpoints, and invalid CodeQL receipts. `OneHop` construction rejects any
`removed` or `added` value that differs from those set differences. Therefore:

$$
\operatorname{OneHopValid}(P,G_0,G^*)\iff
\begin{cases}
\operatorname{ValidGraph}(G_0),\\
\operatorname{ValidGraph}(G^*),\\
\mathrm{before}=\operatorname{ids}(E_0^{(1)}),\\
\mathrm{after}=\operatorname{ids}(E_*^{(1)}),\\
\mathrm{removed}=\mathrm{before}\setminus\mathrm{after},\\
\mathrm{added}=\mathrm{after}\setminus\mathrm{before}.
\end{cases}
$$

The exact `ContractTarget` payload is the sole source of the expected edge
changes. It produces $R^*$, and the pinned analyzer translates $R^*$ into $G^*$
and its one-hop edge delta. The realized-delta rule separately requires every
changed declaration to belong to the selected plan:

$$
\Delta(G_0,G^*)\subseteq\operatorname{Owned}(T_P).
$$

After implementation, `accept()` requires the committed source digest to equal
the checked $R^*$ digest. For the same pinned analyzer $K$, identical source
bytes reproduce $G^*$ and the same one-hop delta. One CodeQL pass over those
bytes therefore establishes the committed graph.

The four checks are complementary:

| Check | Establishes |
| --- | --- |
| AST declaration extraction | Exact target identity and declaration bytes |
| CodeQL | Represented dependency structure and the direct neighborhood |
| Pyright | Static compatibility of the fully materialized production source |
| PairBlock gates | Runtime behavior selected by the contract |

CodeQL establishes represented source dependencies. Pyright runs over the
entire source tree selected by the materialized candidate's
`pyrightconfig.json`, covering the one-hop neighborhood and every other
configured module. It checks that typed callers satisfy the interfaces they
use. PairBlock gates establish the selected runtime behavior. The one-hop
guarantee covers the edges emitted by the pinned CodeQL query pack. The CodeQL
graph defines that scope.

## 3. Current gap

### Current DAG

The input boundary before this contract contains a closed CTG plan and source
files, but no operation joins declared targets to independently observed source
facts.

```mermaid
flowchart LR
    Contract["Contract requirements and rules"]
    Edges["RuleEdge owners and tests"]
    Blocks["PairBlocks in CTG"]
    Source["Repository source"]
    Gap["Unsupported comparison<br/>plan versus realized source"]

    Contract -->|"requirement_id"| Edges
    Blocks -->|"ordered execution"| Source
    Edges -->|"no source-graph join"| Gap
    Source -->|"no source observation"| Gap

    class Contract current
    class Edges,Blocks,Source evidence
    class Gap gap
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef evidence fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Proposed-change DAG

The replacement introduces source observation, dependency reporting, plan
conformance, and one post-commit acceptance record.

```mermaid
flowchart TB
    Plan["Selected ContractTargets and PairBlocks"]
    Freeze["Freeze plan and candidate source"]
    Identity["CodeQLIdentity"]
    Baseline["SourceGraph G0"]
    Impact["Impact"]
    Realized["SourceGraph G*"]
    Resolved["ResolvedContractTarget"]
    Target["TargetCheck"]
    Gates["Run frozen PairBlock gates"]
    Dependencies["Baseline-satisfied dependencies"]
    Check["PlanCheck"]
    Commit["Commit checked source"]
    Acceptance["Acceptance"]

    Plan -->|"selected plan"| Freeze
    Plan -->|"recompute plan digest"| Check
    Identity -->|"analyze R0"| Baseline
    Baseline -->|"typed direct dependents"| Impact
    Freeze -->|"authored declaration"| Resolved
    Freeze -->|"immutable candidate"| Realized
    Identity -->|"analyze candidate"| Realized
    Baseline -->|"before facts"| Resolved
    Resolved -->|"ChangeKind"| Impact
    Resolved -->|"expected digest"| Target
    Realized -->|"after facts"| Target
    Impact -->|"review evidence"| Check
    Target -->|"ordered checks"| Check
    Plan -->|"gate commands"| Gates
    Gates -->|"exit code 0"| Check
    Baseline -->|"dependency target states"| Dependencies
    Dependencies -->|"omitted dependency evidence"| Check
    Freeze -->|"checked source and plan bytes"| Commit
    Check -->|"passed check"| Commit
    Commit -->|"revision, source, and plan bytes"| Acceptance
    Check -->|"check digest"| Acceptance

    class Plan,Freeze,Identity,Baseline,Impact,Realized,Resolved,Target,Gates,Dependencies,Check,Commit,Acceptance proposed
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Integrated DAG

`CRT-06` closes the plan first. System Impact then observes the baseline,
implementation runs the existing PairBlocks, and the same CodeQL identity
observes the result.

```mermaid
flowchart TB
    Requirement["ContractRequirement"]
    Target["ContractTarget<br/>action · target · declaration"]
    Rule["VerifierRule and RuleEdges"]
    Block["PairBlock<br/>targets · tests · gate"]
    CTG["ContractTraceabilityGraph"]
    CodeQL["CodeQLIdentity"]
    G0["SourceGraph G0"]
    Impact["Impact<br/>typed direct dependents"]
    Execute["Execute existing PairBlocks"]
    Freeze["Freeze selected plan<br/>and candidate source"]
    Gs["SourceGraph G*"]
    Resolved["ResolvedContractTarget<br/>digest and ChangeKind"]
    Check["PlanCheck"]
    Gates["Run frozen PairBlock gates"]
    Dependencies["Baseline-satisfied dependencies"]
    Commit["Commit checked source"]
    Acceptance["Acceptance"]

    Requirement -->|"requirements"| Target
    Requirement -->|"requirement_id"| Rule
    Target -->|"block_id"| Block
    Rule -->|"block_id"| Block
    Requirement -->|"record"| CTG
    Target -->|"record"| CTG
    Rule -->|"record"| CTG
    Block -->|"record"| CTG
    CodeQL -->|"analyze R0"| G0
    CTG -->|"resolve targets"| G0
    G0 -->|"one-hop policy selection"| Impact
    Block -->|"ordered work"| Execute
    Execute -->|"candidate edits"| Freeze
    CTG -->|"selected blocks"| Freeze
    Freeze -->|"immutable source snapshot"| Gs
    Freeze -->|"resolve authored declarations"| Resolved
    CodeQL -->|"analyze candidate"| Gs
    Resolved -->|"ChangeKind"| Impact
    CTG -->|"expected actions"| Check
    Resolved -->|"expected digests"| Check
    G0 -->|"before facts"| Check
    Gs -->|"after facts"| Check
    Impact -->|"review evidence"| Check
    Block -->|"gate command"| Gates
    Gates -->|"exit code 0"| Check
    G0 -->|"dependency target states"| Dependencies
    Dependencies -->|"omitted dependency evidence"| Check
    Freeze -->|"plan digest"| Check
    Freeze -->|"checked source and plan bytes"| Commit
    Check -->|"passed check"| Commit
    Commit -->|"revision, source, and plan bytes"| Acceptance
    Check -->|"check digest"| Acceptance

    class Requirement,Target,Rule,CTG contract
    class Block checklist
    class CodeQL,G0,Gs,Impact evidence
    class Execute,Freeze,Gates,Commit implementation
    class Resolved,Dependencies,Check,Acceptance output
    classDef contract fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef checklist fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px
    classDef evidence fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef implementation fill:#312e81,stroke:#a5b4fc,color:#ffffff,stroke-width:2px
    classDef output fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

The diagrams use the contract-wide semantic palette: blue for authored
contract data, amber for checklist scheduling, teal for observed evidence,
purple for proposed or generated records, and red for an unsupported gap.

## 4. Models

<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-01 action=add target=src/viper/system_impact/models.py:CodeQLIdentity -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-01 action=add target=src/viper/system_impact/models.py:SourceSnapshot -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-01 action=add target=src/viper/system_impact/models.py:CodeQLReceipt -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-01 action=add target=src/viper/system_impact/models.py:SourceNode -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-01 action=add target=src/viper/system_impact/models.py:SourceEdge -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-01 action=add target=src/viper/system_impact/models.py:SourceGraph -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=update target=src/viper/system_impact/models.py:CodeQLReceipt -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/system_impact/models.py:SourceNodeKind -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=update target=src/viper/system_impact/models.py:SourceNode -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=update target=src/viper/system_impact/models.py:SourceGraph -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/models.py:ChangeKind -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/models.py:Impact -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/models.py:ResolvedContractTarget -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/models.py:PlanInspection -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/models.py:CheckState -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/models.py:TargetCheck -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/models.py:GateCheck -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/models.py:PlanCheck -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/models.py:Acceptance -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=update target=src/viper/system_impact/models.py:__all__ -->

```python contract-target
"""Define public records for System Impact checks."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .._contract_traceability import (
    ContractTarget,
    PairBlockId,
    RepoSymbolRef,
)
from .._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath

CommitId = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
NodeId = NonEmptyStr
EdgeKind = Literal["imports", "calls", "constructs", "inherits", "reads", "writes"]
SourceNodeKind = Literal["function", "method", "class", "assignment", "import"]
ChangeKind = Literal[
    "satisfied",
    "added",
    "removed",
    "callable_interface_changed",
    "type_interface_changed",
    "implementation_changed",
    "unclassified",
]
CheckState = Literal["passed", "failed"]


class CodeQLIdentity(ProtocolModel):
    """Fix the analyzer and query pack used for both source snapshots."""

    version: NonEmptyStr = Field(description="Required CodeQL CLI version.")
    platform: NonEmptyStr = Field(description="CodeQL bundle platform identifier.")
    executable_sha256: SHA256 = Field(
        description="Digest of the exact CodeQL launcher executable."
    )
    pack: NonEmptyStr = Field(description="Name and version of the VIPER query pack.")
    pack_sha256: SHA256 = Field(description="Digest of the exact query-pack bytes.")


class SourceSnapshot(ProtocolModel):
    """Identify one immutable repository source tree."""

    base_revision: CommitId = Field(
        description="Committed baseline from which this source was derived."
    )
    source_sha256: SHA256 = Field(
        description="Digest of the complete analyzed source-file set and bytes."
    )
    revision: CommitId | None = Field(
        description="Exact commit when the snapshot is committed; otherwise absent."
    )


class CodeQLReceipt(ProtocolModel):
    """Record one completed source-analysis invocation."""

    snapshot: SourceSnapshot = Field(
        description="Immutable source snapshot analyzed by CodeQL."
    )
    identity: CodeQLIdentity = Field(
        description="Exact CodeQL and query-pack identity used by every command."
    )
    commands: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1,
        description="Ordered argument vectors executed for this analysis.",
    )
    exit_code: int = Field(description="Terminal process exit code.")
    database_sha256: SHA256 = Field(
        description="Digest of the CodeQL database's relative paths and file bytes."
    )
    result_sha256: SHA256 = Field(description="Digest of the decoded canonical rows.")
    stderr_sha256: SHA256 = Field(
        description=(
            "Digest of the ordered query labels and captured standard error bytes."
        )
    )


class SourceNode(ProtocolModel):
    """Identify one Python declaration observed in one source snapshot."""

    node_id: NodeId = Field(
        description="Stable path-and-symbol key assigned after uniqueness is proved."
    )
    path: RepoRelPath = Field(description="Repository-relative Python source path.")
    symbol: NonEmptyStr = Field(description="Qualified Python symbol name.")
    kind: SourceNodeKind = Field(description="Observed Python declaration kind.")
    binding_start_line: int = Field(
        ge=1,
        description="First line of the AST occurrence located by CodeQL.",
    )
    binding_start_col: int = Field(
        ge=0,
        description="UTF-8 byte offset of that occurrence on its first line.",
    )
    binding_end_line: int = Field(
        ge=1,
        description="Final line of the located AST occurrence.",
    )
    binding_end_col: int = Field(
        ge=0,
        description="UTF-8 byte offset after the located AST occurrence.",
    )
    start_line: int = Field(
        ge=1,
        description="First source line of the declaration.",
    )
    start_col: int = Field(
        ge=0,
        description="UTF-8 byte offset on the first line.",
    )
    end_line: int = Field(
        ge=1,
        description="Final source line of the declaration.",
    )
    end_col: int = Field(
        ge=0,
        description="UTF-8 byte offset after the declaration.",
    )
    sha256: SHA256 = Field(description="Digest of the exact declaration bytes.")

    @model_validator(mode="after")
    def validate_spans(self) -> SourceNode:
        """Require a nonempty binding inside its declaration."""
        binding_start = (self.binding_start_line, self.binding_start_col)
        binding_end = (self.binding_end_line, self.binding_end_col)
        declaration_start = (self.start_line, self.start_col)
        declaration_end = (self.end_line, self.end_col)

        if not (declaration_start <= binding_start < binding_end <= declaration_end):
            raise ValueError("SourceNode binding must lie inside its declaration")

        return self


class SourceEdge(ProtocolModel):
    """Record one source declaration's dependency on another declaration."""

    edge_id: SHA256 = Field(description="Digest of the complete edge identity.")
    source: NodeId = Field(description="Declaration that depends on the target.")
    target: NodeId = Field(description="Declaration consumed by the source.")
    kind: EdgeKind = Field(description="Observed dependency operation.")
    query: NonEmptyStr = Field(description="CodeQL query that emitted the edge.")
    path: NonEmptyStr = Field(
        description="Repository-relative path containing the use."
    )
    line: int = Field(
        ge=1,
        description="One-based source line containing the use.",
    )


class SourceGraph(ProtocolModel):
    """Store one canonical CodeQL observation of a source snapshot."""

    schema_version: Literal[2] = Field(
        default=2,
        description="Source-graph format version.",
    )
    snapshot: SourceSnapshot = Field(
        description="Immutable source snapshot represented by the graph."
    )
    identity: CodeQLIdentity = Field(
        description="Analyzer identity used for this graph."
    )
    nodes: tuple[SourceNode, ...] = Field(
        description="Nodes sorted by stable identifier."
    )
    edges: tuple[SourceEdge, ...] = Field(
        description="Edges sorted by stable identifier."
    )
    receipt: CodeQLReceipt = Field(
        description="Evidence for the completed analysis run."
    )

    @field_validator("nodes")
    @classmethod
    def order_nodes(cls, nodes: tuple[SourceNode, ...]) -> tuple[SourceNode, ...]:
        """Order nodes by their stable identifiers before serialization."""
        return tuple(sorted(nodes, key=lambda node: node.node_id))

    @field_validator("edges")
    @classmethod
    def order_edges(cls, edges: tuple[SourceEdge, ...]) -> tuple[SourceEdge, ...]:
        """Order edges by their stable identifiers before serialization."""
        return tuple(sorted(edges, key=lambda edge: edge.edge_id))

    @model_validator(mode="after")
    def validate_graph(self) -> SourceGraph:
        """Reject duplicate identities, dangling edges, and receipt drift."""
        node_ids = tuple(node.node_id for node in self.nodes)
        target_keys = tuple((node.path, node.symbol) for node in self.nodes)
        occurrences = tuple(
            (
                node.path,
                node.binding_start_line,
                node.binding_start_col,
                node.binding_end_line,
                node.binding_end_col,
            )
            for node in self.nodes
        )
        edge_ids = tuple(edge.edge_id for edge in self.edges)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("SourceGraph contains duplicate node IDs")
        if len(target_keys) != len(set(target_keys)):
            raise ValueError("SourceGraph contains an ambiguous source target")
        if len(occurrences) != len(set(occurrences)):
            raise ValueError("SourceGraph contains a duplicate binding occurrence")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("SourceGraph contains duplicate edge IDs")
        known = set(node_ids)
        if any(
            edge.source not in known or edge.target not in known for edge in self.edges
        ):
            raise ValueError("SourceGraph contains an edge with an unknown endpoint")
        if self.receipt.snapshot != self.snapshot:
            raise ValueError("CodeQLReceipt snapshot differs from SourceGraph snapshot")
        if self.receipt.identity != self.identity:
            raise ValueError("CodeQLReceipt identity differs from SourceGraph identity")
        result_payload = json.dumps(
            {
                "nodes": [node.model_dump(mode="json") for node in self.nodes],
                "edges": [edge.model_dump(mode="json") for edge in self.edges],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if hashlib.sha256(result_payload).hexdigest() != self.receipt.result_sha256:
            raise ValueError(
                "CodeQLReceipt result digest differs from SourceGraph rows"
            )
        return self


class Impact(ProtocolModel):
    """Report direct baseline dependents selected by policy version 1."""

    policy_version: Literal[1] = Field(
        default=1,
        description="Change-kind-to-edge-kind policy version used for this report.",
    )
    baseline: SourceSnapshot = Field(
        description="Baseline source snapshot whose direct edges were inspected."
    )
    targets: tuple[NodeId, ...] = Field(
        description="Existing baseline nodes resolved from the selected targets."
    )
    affected: tuple[NodeId, ...] = Field(
        description="Unique direct dependents selected by the impact policy."
    )
    edges: tuple[SHA256, ...] = Field(
        description="SourceEdge identifiers that support the affected-node report."
    )


class ResolvedContractTarget(ProtocolModel):
    """Bind one authored target to baseline and expected declaration bytes."""

    target: ContractTarget = Field(description="Selected CTG target being resolved.")
    baseline_node: NodeId | None = Field(
        description="Resolved baseline node identifier, or absent for an addition."
    )
    baseline_sha256: SHA256 | None = Field(
        description="Baseline declaration digest, or absent for an addition."
    )
    expected_sha256: SHA256 | None = Field(
        description="Authored declaration digest, or absent for a removal."
    )
    change_kind: ChangeKind = Field(
        description="Planned transition used to select direct dependency edges."
    )


class TargetCheck(ProtocolModel):
    """Record whether one realized declaration matches its authored target."""

    resolved: ResolvedContractTarget = Field(
        description="Authored target resolved against the baseline source graph."
    )
    after_sha256: SHA256 | None = Field(
        description=(
            "Realized declaration digest, or absent when no declaration remains."
        )
    )
    state: CheckState = Field(
        description="Whether the realized declaration has the required target state."
    )
    message: NonEmptyStr = Field(description="Specific reason for the target result.")


class GateCheck(ProtocolModel):
    """Record one selected PairBlock gate invocation."""

    block_id: PairBlockId = Field(
        description="Selected PairBlock whose frozen gate was executed."
    )
    command: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="Exact argument vector executed without a command shell.",
    )
    exit_code: int = Field(description="Terminal process exit code.")
    stdout_sha256: SHA256 = Field(
        description="Digest of the gate's captured standard output bytes."
    )
    stderr_sha256: SHA256 = Field(
        description="Digest of the gate's captured standard error bytes."
    )


class PlanCheck(ProtocolModel):
    """Record the complete result of checking selected PairBlocks."""

    schema_version: Literal[1] = Field(
        default=1,
        description="Plan-check record format version.",
    )
    baseline: SourceSnapshot = Field(
        description="Source state inspected before the selected PairBlocks ran."
    )
    realized: SourceSnapshot = Field(
        description=(
            "Candidate source state inspected after the selected PairBlocks ran."
        )
    )
    blocks: tuple[PairBlockId, ...] = Field(
        min_length=1,
        description="Selected PairBlocks covered by this check.",
    )
    contracts: tuple[RepoRelPath, ...] = Field(
        min_length=1,
        description="Contract files needed to reconstruct the selected plan.",
    )
    baseline_dependencies: tuple[PairBlockId, ...] = Field(
        default=(),
        description=(
            "Omitted dependencies whose target state already exists in the baseline."
        ),
    )
    unsatisfied_dependencies: tuple[PairBlockId, ...] = Field(
        default=(),
        description=(
            "Omitted dependencies whose target state is absent from the baseline."
        ),
    )
    plan_sha256: SHA256 = Field(
        description=(
            "Digest of the selected PairBlock and ContractTarget records plus "
            "the selected asset paths and bytes."
        )
    )
    impact: Impact = Field(
        description="Direct advisory dependency report for the selected targets."
    )
    targets: tuple[TargetCheck, ...] = Field(
        description="One realized result for every selected ContractTarget."
    )
    unexpected: tuple[RepoSymbolRef, ...] = Field(
        description="Changed declarations that no selected ContractTarget owns."
    )
    gates: tuple[GateCheck, ...] = Field(
        description="One gate result for every selected PairBlock."
    )
    receipts_valid: bool = Field(
        description=(
            "Whether both graphs have successful receipts with one analyzer identity."
        )
    )
    plan_valid: bool = Field(
        description=(
            "Whether the post-gate contract files retain the checked plan digest."
        )
    )
    source_valid: bool = Field(
        description="Whether both source roots retain their checked source digests."
    )
    passed: bool = Field(
        description=(
            "Whether every target, dependency, gate, source, plan, and receipt check "
            "passed."
        )
    )


class Acceptance(ProtocolModel):
    """Bind a passing plan check to its exact committed source and plan."""

    check: SHA256 = Field(
        description="Digest of the exact passing PlanCheck accepted for reuse."
    )
    revision: CommitId = Field(
        description="Commit whose Python source and selected plan match the PlanCheck."
    )


class PlanInspection(ProtocolModel):
    """Return resolved selected targets and their direct advisory impact."""

    targets: tuple[ResolvedContractTarget, ...] = Field(
        description="Selected targets resolved against their baseline declarations."
    )
    impact: Impact = Field(
        description="Direct advisory impact derived from the resolved targets."
    )


__all__ = [
    "Acceptance",
    "CodeQLIdentity",
    "CodeQLReceipt",
    "ChangeKind",
    "CheckState",
    "CommitId",
    "EdgeKind",
    "GateCheck",
    "Impact",
    "NodeId",
    "PlanCheck",
    "PlanInspection",
    "ResolvedContractTarget",
    "SourceEdge",
    "SourceGraph",
    "SourceNode",
    "SourceNodeKind",
    "SourceSnapshot",
    "TargetCheck",
]
```

Baseline and expected digests are optional because additions have no baseline
declaration and removals have no expected or realized declaration.

### Illustrative worked example

The example checks the completed manifest migration that renamed
`model_support` to `models` in the global skills repository.

<!-- contract-worked-example: start -->

```python
baseline_id: CommitId = "6eb74b8e8bba2ddf2f2f9fa3822e11c5d9a3d06b"
realized_id: CommitId = "18083057eeb92c755ead031122afd48e8a77d653"
identity = CodeQLIdentity(
    version="2.26.4",
    platform="osx64",
    executable_sha256="1" * 64,
    pack="viper/python-impact@1.1.0",
    pack_sha256="2" * 64,
)
baseline_snapshot = SourceSnapshot(
    base_revision=baseline_id,
    source_sha256="a" * 64,
    revision=baseline_id,
)
realized_snapshot = SourceSnapshot(
    base_revision=baseline_id,
    source_sha256="b" * 64,
    revision=realized_id,
)
empty_result_sha256 = hashlib.sha256(b'{"edges":[],"nodes":[]}').hexdigest()
baseline_receipt = CodeQLReceipt(
    snapshot=baseline_snapshot,
    identity=identity,
    commands=(("codeql", "query", "run"),),
    exit_code=0,
    database_sha256="3" * 64,
    result_sha256=empty_result_sha256,
    stderr_sha256="4" * 64,
)
realized_receipt = CodeQLReceipt(
    snapshot=realized_snapshot,
    identity=identity,
    commands=(("codeql", "query", "run"),),
    exit_code=0,
    database_sha256="5" * 64,
    result_sha256=empty_result_sha256,
    stderr_sha256="4" * 64,
)
baseline = SourceGraph(
    snapshot=baseline_snapshot,
    identity=identity,
    nodes=(),
    edges=(),
    receipt=baseline_receipt,
)
realized = SourceGraph(
    snapshot=realized_snapshot,
    identity=identity,
    nodes=(),
    edges=(),
    receipt=realized_receipt,
)
declaration = DeclarationRef(
    path="docs/development/example.md",
    start_line=1,
    end_line=3,
    sha256="6" * 64,
)
planned = ContractTarget(
    requirements=("SKE-01",),
    block_id="P0-SKE-01",
    action="remove",
    target=RepoSymbolRef(
        path="scripts/validate-skill-contract.py",
        symbol="compile_manifest",
    ),
    declaration=declaration,
)
resolved = ResolvedContractTarget(
    target=planned,
    baseline_node="scripts/validate-skill-contract.py:compile_manifest",
    baseline_sha256="7" * 64,
    expected_sha256=None,
    change_kind="removed",
)
target = TargetCheck(
    resolved=resolved,
    after_sha256=None,
    state="passed",
    message="target declaration is absent",
)
gate = GateCheck(
    block_id="P0-SKE-01",
    command=("python", "-m", "pytest"),
    exit_code=0,
    stdout_sha256="8" * 64,
    stderr_sha256="9" * 64,
)
result = PlanCheck(
    baseline=baseline.snapshot,
    realized=realized.snapshot,
    blocks=(planned.block_id,),
    contracts=("docs/development/example.md",),
    baseline_dependencies=(),
    unsatisfied_dependencies=(),
    plan_sha256="c" * 64,
    impact=Impact(
        baseline=baseline.snapshot,
        targets=(resolved.baseline_node,),
        affected=(),
        edges=(),
    ),
    targets=(target,),
    unexpected=(),
    gates=(gate,),
    receipts_valid=True,
    plan_valid=True,
    source_valid=True,
    passed=True,
)
acceptance = Acceptance(check="f" * 64, revision=realized_id)

assert baseline.identity == realized.identity
assert result.targets[0].state == "passed"
assert result.unsatisfied_dependencies == ()
assert result.passed
assert acceptance.revision == result.realized.revision
```

<!-- contract-worked-example: end -->

## 5. Execution

```text
compile_contract_traceability() -> closed CTG plan
analyze_source(R0, K) -> G0 + receipt
inspect_plan(CTG, G0) -> action checks + typed one-hop impact report
execute the selected PairBlocks and their focused tests -> candidate source
freeze selected plan + candidate source -> plan_sha256 + R*
analyze_source(R*, K) -> G* + receipt
check_plan(selected CTG, G0, G*) -> PlanCheck
commit the exact frozen R* source -> revision
accept(repository root, PlanCheck, revision) -> Acceptance
```

CodeQL emits declaration nodes and dependency edges. VIPER canonicalizes those
rows, hashes each declaration span, classifies each planned change, selects
its direct dependency edges, and performs equality checks.
CodeQL never authors requirements, targets, or PairBlocks.

`analyze_source()` receives an exact `snapshot_root`, `SourceSnapshot`,
`CodeQLIdentity`, CodeQL executable path, query-pack path, cache root, and
artifact root. It verifies the source manifest, query-pack tree, CLI version,
and launcher digest before analysis. An exact source-and-identity cache key may
reuse a database only when its recorded content digest still matches the cached
database. A missing or altered cache manifest or database forces a full
rebuild. The receipt records every executed argument vector, the analyzed
database digest, and the canonical result digest.

`CodeQLIdentity` does not hash every file in the installed CodeQL distribution.
Phase 0 binds the reported CLI version, launcher bytes, and query-pack bytes,
and trusts the verified distribution installed behind that identity.

Query-pack version `1.1.0` emits `calls`, `constructs`, `inherits`, `imports`,
`reads`, and `writes`. A `writes` edge is emitted only when the writing scope
and the canonical module or class assignment both resolve to `SourceNode`
records. Local variables and attributes without an existing assignment node
remain outside the Phase 0 graph.

CodeQL identifies repository declarations and dependency evidence. Python's
AST selects the exact original byte span for each CodeQL declaration row and
each declaration inside a Markdown `contract-target` fence. This local AST pass
does not resolve repository dependencies or replace CodeQL identity.

### Node and edge identity

CodeQL locates a binding by file, line, and column. Python's AST verifies that
location and supplies the complete declaration span and exact bytes. CodeQL
locations count lines and columns from one; Python AST lines count from one and
its columns are UTF-8 byte offsets. The adapter converts the CodeQL column before
joining the two records. These coordinate rules come from the
[CodeQL location contract](https://codeql.github.com/docs/writing-codeql-queries/providing-locations-in-codeql-queries/)
and [Python AST contract](https://docs.python.org/3/library/ast.html#ast.AST).

Let $V$ be the source nodes and let a contract target $t$ contain `path` and
`symbol`. The target must identify one node:

$$
\forall t,\quad
\left|\left\{v\in V : v.path=t.path \land v.symbol=t.symbol\right\}\right|=1.
$$

For one node, let $B$ be its binding span and $D$ its complete declaration
span. Both spans are half-open after conversion to AST coordinates:

$$
D_{\mathrm{start}} \le B_{\mathrm{start}}
< B_{\mathrm{end}} \le D_{\mathrm{end}}.
$$

Every dependency edge must resolve both endpoints exactly:

$$
\forall e\in E,\quad
|\operatorname{Source}(e)|=1
\land |\operatorname{Target}(e)|=1.
$$

The query pack and AST loader enforce these as joins, not guesses. Zero or
multiple matches reject the graph. There is no line-range fallback.

For example:

```python
from x import A, B as C
```

The statement creates two nodes. Both nodes hash the same declaration bytes,
but their binding spans differ:

```text
SourceNode A
├── binding:    [14, 15)
└── declaration:[0, 23)

SourceNode C
├── binding:    [17, 23)
└── declaration:[0, 23)
```

An edge row at the second binding resolves to `C`. A row that supplies only the
line, or a column that matches neither binding, fails. The path-and-symbol node
ID is assigned only after the uniqueness rule above passes.

`check_plan()` recomputes `plan_sha256`, verifies omitted dependencies against
their declared baseline target states, and runs every frozen selected
`PairBlock.gate`. A gate passes when its process exits with code `0`.
`accept()` requires `PlanCheck.passed`, rebuilds the canonical source manifest
and selected plan, including supporting-asset bytes, from `revision`. It
compares both digests with
`PlanCheck.realized.source_sha256` and `PlanCheck.plan_sha256` before returning
`Acceptance`.

### Declaration

One operation computes both planned and observed declaration digests:

```python
def extract_declaration_bytes(
    source: bytes,
    qualified_symbol: str,
) -> bytes:
    """Return one declaration exactly as encoded in UTF-8 source."""
```

The operation decodes UTF-8, parses the module, and resolves exactly one AST
declaration for `qualified_symbol`. A decorated function or class starts at
the `@` token of its first decorator. The declaration ends at the AST node's
`end_lineno` and `end_col_offset`. The extractor converts those UTF-8 byte
offsets back into one slice of the original `source` bytes. It never reformats
code or normalizes newlines. Zero matches, several matches, invalid UTF-8, or
a missing end position fail the check.

For an `add` or `update`, the extractor runs once on the PairBlock's authored
fence and once on the candidate source file. A fence may contain several
declarations; the qualified symbol selects one. For a `remove`, the planned
digest is absent and the candidate graph must omit the baseline symbol.

### Change-sensitive direct impact

One internal operation classifies the planned transition before PairBlock
execution:

```python
def classify_target_change(
    *,
    action: Literal["add", "update", "remove"],
    baseline: bytes | None,
    expected: bytes | None,
) -> ChangeKind:
    """Classify one planned declaration transition."""
```

`add` returns `added`, and `remove` returns `removed`. An `update` already
present in the baseline returns `satisfied`. Otherwise, the operation parses
the baseline and expected declarations and applies these rules in order:

1. A function or method whose synchronous or asynchronous form, decorators,
   type parameters, parameters, or return annotation changed returns
   `callable_interface_changed`.
2. A class whose decorators, type parameters, bases, keywords, directly
   declared field names or annotations, or directly declared method headers
   changed returns `type_interface_changed`.
3. An assignment whose target or annotation changed returns
   `type_interface_changed`.
4. A supported declaration with the same interface and different body returns
   `implementation_changed`.
5. An unsupported, ambiguous, or kind-changing comparison returns
   `unclassified`.

Interface changes take precedence when the same declaration also changes its
body. Impact-policy version 1 maps each `ChangeKind` to the existing
`EdgeKind` vocabulary:

```python
IMPACT_EDGE_KINDS_V1: dict[ChangeKind, frozenset[EdgeKind]] = {
    "satisfied": frozenset(),
    "added": frozenset(),
    "removed": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
    "callable_interface_changed": frozenset({"calls", "constructs"}),
    "type_interface_changed": frozenset(
        {"constructs", "inherits", "reads", "writes"}
    ),
    "implementation_changed": frozenset({"calls", "reads"}),
    "unclassified": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
}
```

For each `ResolvedContractTarget` $r$ with a baseline node,
`inspect_plan()` selects exactly these incoming baseline edges:

```python
{
    edge
    for edge in baseline.edges
    if edge.target == r.baseline_node
    and edge.kind in IMPACT_EDGE_KINDS_V1[r.change_kind]
}
```

`Impact.edges` stores the selected edge identifiers. `Impact.affected` stores
their unique `source` node identifiers. The operation stops after this direct
step. If review adds one reported dependent as another `ContractTarget`, that
target receives its own classification and direct-impact report.

The [CodeQL impact observations](codeql-impact-observations.md) ledger records
whether this report supplies a direct dependent absent from the pre-report
plan, whether that dependent changes source or tests, and which relevant
dependencies later prove absent from the report. The ledger evaluates the
report's practical value while preserving this contract's acceptance claim.

This work is linear in the bytes of each selected fence and source file. Cache
the parsed declaration index by file digest, so several targets in one file
pay the parse cost once. In practice, CodeQL analysis and pytest dominate this
small local AST pass.

`SourceSnapshot.source_sha256` hashes a canonical manifest of every `.py` file
beneath `snapshot_root`, except files beneath the explicit cache and environment
directories in `IGNORED_PARTS`. Each row contains the repository-relative path
and raw-file digest. `analyze_source()` rejects a root whose current manifest
differs from the snapshot. The caller may provide an immutable copy or a stable
working tree; the digest check establishes the same input boundary.

Phase 0 does not represent `.pyi` declarations. A plan that changes a stub file
cannot pass System Impact until a source-fact provider emits nodes for that
file type.

### Guided work and strict closure

The default guided boundary is one contract session. At the start, the
developer synchronizes the repository, records baseline commit
$R_0$, compiles the starting contract and PairBlocks, and selects the contract's
remaining blocks. PairBlocks retain the edit order inside the session.

During guided work, the developer may revise any selected PairBlock and its
source while running focused tests and reviewing Git diffs. AST extraction and
CodeQL run during strict closure. Intermediate commits preserve review
checkpoints while each PairBlock and the contract remain planned.

After pair coding, the agent reconciles the complete difference from $R_0$ to
the candidate. Every changed declaration receives one result:

1. An existing `ContractTarget` already describes the change.
2. An intentional discovery requires an updated `ContractTarget` and explicit
   user approval.
3. An accidental or unrelated change leaves this candidate or enters a
   separately approved plan.

The reconciliation updates PairBlocks, targets, dependencies, tests, and gates
before acceptance. An observed source change enters the approved plan only
after explicit user approval.

Strict closure then runs once for the reconciled contract:

```text
fix baseline R0
-> select the contract's remaining PairBlocks
-> edit PairBlocks and source
-> run focused tests
-> reconcile every changed declaration with the selected plan
-> freeze selected PairBlock bytes and candidate source bytes
-> compute plan_sha256
-> extract exact planned and candidate declarations
-> analyze R0 and frozen R* with one CodeQLIdentity
-> check_plan()
-> commit the exact checked candidate bytes
-> accept() the commit only when its source and selected-plan digests match the check
-> publish the acceptance, contracts, and CodeQL outputs
```

Changing a selected PairBlock, target declaration, dependency, gate, test, or
candidate source file after the freeze changes its digest and invalidates the
`PlanCheck`. A change made between `check_plan()` and commit causes `accept()`
to reject the committed revision. The next strict attempt reuses $R_0$, freezes
the revised plan and candidate once, and reruns the closing checks. Strict
closure supplies the completion evidence. Guided work reduces iteration cost
while preserving that final guarantee.
The developer may request a narrower PairBlock-level strict close when one
block needs independent acceptance before the rest of the contract continues.

### Autonomous work

Autonomous work freezes the selected PairBlocks before implementation. The
agent stays within those targets, tests, dependencies, and gates. A necessary
plan change starts a new freeze against the same baseline $R_0$ before work
continues. The final `check_plan()`, commit, `accept()`, and publication
operations are identical to guided work.

Guided and autonomous work therefore differ only during implementation:

```text
guided: start check -> flexible pair coding -> final check -> commit -> accept -> publish
autonomous: freeze plan -> constrained execution -> final check -> commit -> accept -> publish
```

## 6. Serializable evidence

The implemented records serialize into this logical bundle:

```text
.viper/system/<check-id>/
├── plan.json
├── baseline.json
├── baseline-receipt.json
├── impact.json
├── realized.json
├── realized-receipt.json
├── plan-check.json
└── acceptance.json
```

Each model uses sorted, compact JSON and repository-relative paths.
`plan_sha256` binds the selected `PairBlock` and `ContractTarget` records plus
the exact bytes of every selected `PairBlock.assets` path. `accept()` returns
`Acceptance` only after it reconstructs those values from the committed tree.
`python -m tools.plan.publish` uploads the compact bundle to a private Hugging
Face dataset repository after `accept()` succeeds. It stores `result.json`,
`acceptance.json`, the raw and decoded CodeQL query outputs, and the selected
contracts read from the accepted commit. It excludes the generated candidate
tree and reusable CodeQL database cache.

The upload contains one `manifest.json` whose rows name every uploaded path,
SHA-256 digest, and byte count. The command writes `publication.json` locally
as a `ResolvedFileRef`. Its `HuggingFaceFileRef` identifies the manifest at the
exact dataset commit returned by Hugging Face. A mismatched `Acceptance.check`
is rejected before any upload begins.

## 7. Verification

| Rule | Executable requirement |
| --- | --- |
| `system.source.canonical` <!-- verifier-rule: system.source.canonical requirement=SIG-01 --> | Repeated analysis of one immutable source snapshot with one identity produces byte-identical `SourceGraph` JSON; each declaration span includes exact UTF-8 byte columns and hashes the original bytes. |
| `system.plan.resolved` <!-- verifier-rule: system.plan.resolved requirement=SIG-02 --> | Every CTG target has a baseline state compatible with its action and one `ChangeKind`; `Impact` contains exactly the direct incoming baseline edges permitted by impact-policy version 1 and their source nodes. |
| `system.plan.realized` <!-- verifier-rule: system.plan.realized requirement=SIG-03 --> | Every selected target has the required after-state and exact declaration digest. |
| `system.plan.closed` <!-- verifier-rule: system.plan.closed requirement=SIG-03 --> | `check_plan()` recomputes `plan_sha256`, requires every selected PairBlock gate to exit with code `0`, and accepts an omitted dependency only when all of its target states exist in the baseline; `accept()` then requires the committed source, selected-plan, and supporting-asset bytes to equal the checked values. |
| `system.fixture.replayed` <!-- verifier-rule: system.fixture.replayed requirement=SIG-04 --> | Both committed fixtures reproduce their reviewed changed-path sets and target results. |
| `system.codeql.identity` <!-- verifier-rule: system.codeql.identity requirement=SIG-05 --> | Baseline and candidate receipts contain the same pinned CodeQL identity and their exact source-snapshot and result digests. |
| `system.source.writes` <!-- verifier-rule: system.source.writes requirement=SIG-06 --> | The checked-in CodeQL pack emits `writes` edges for a function writing a declared module variable and a method writing a declared class attribute; every emitted edge retains the assignment location. |
| `system.one_hop.recorded` <!-- verifier-rule: system.one_hop.recorded requirement=SIG-07 --> | `check_plan()` derives the exact added and removed policy-selected one-hop edges from the valid baseline and materialized source graphs; the realized-delta check rejects changed declarations outside the selected PairBlocks. |
| `system.candidate.typed` <!-- verifier-rule: system.candidate.typed requirement=SIG-07 --> | `tools/plan/check.py:validate` runs Pyright against the fully materialized production source and stops before candidate CodeQL analysis or PairBlock gates when static interfaces are incompatible. PairBlock gates own test behavior. |

## 8. Propagation

| Surface | Required change |
| --- | --- |
| `src/viper/system_impact/models.py` | Define the public System Impact records. |
| `src/viper/system_impact/plan.py` | Resolve contract targets against the baseline graph. |
| `src/viper/system_impact/check.py` | Check the realized plan and bind it to its commit. |
| `src/viper/_system_impact/codeql.py` | Create and query CodeQL databases and return validated canonical rows. |
| `src/viper/_system_impact/source.py` | Resolve qualified Python symbols, extract exact UTF-8 declaration bytes including decorators, and implement `classify_target_change()`. |
| `tools/plan/check.py` | Run Pyright against the materialized candidate before candidate CodeQL analysis and restore the caller's `PYTHONPATH` after the check. |
| `tools/plan/publish.py` | Upload one accepted compact evidence bundle and return an immutable `ResolvedFileRef` for its manifest. |
| `tests/test_release_tools.py` | Prove publication uses a private dataset repository, exact check-owned paths, and one immutable Hugging Face commit. |
| `tests/test_system_impact.py` | Cover exact declaration extraction, change classification, typed one-hop impact selection, action transitions, unexpected changes, plan-digest validation, gate execution, accepted dependencies, committed source-and-plan binding, identity drift, and both committed fixtures. |
| `docs/development/contract-traceability.md` | Make `CRT-06` the sole owner of targets, PairBlocks, rule-block joins, and plan closure. |
| `docs/development/master-execution-checklist.md` | Replace the old graph-transformation blocks with the six bounded blocks below. |

### Removed design

This replacement removes `ContractChange`, `ContractDelta`,
`TargetSpecification`, generated PairBlocks, total propagation dispositions,
SCC condensation, coverage.py blast certification, observed dynamic-resolution
manifests, and the research program from Master Phase 0. Appendix A retains the
cross-contract scheduling extension and the evidence required to reconsider it.

## 9. Acceptance case

### Success

Two committed fixtures define the initial boundary:

| Fixture | Baseline | Realized | Expected changed Python declarations |
| --- | --- | --- | --- |
| `.agents` manifest-key migration | `6eb74b8e8bba2ddf2f2f9fa3822e11c5d9a3d06b` | `18083057eeb92c755ead031122afd48e8a77d653` | `run-skill-evaluations.py:main`; `validate-skill-contract.py:compile_manifest`; `validate-skill-evaluation-run.py:validate_run`; the changed runner-test class and setup; the changed skill-contract test class and new rejection test |
| VIPER `P0-PROOF-05` | `1e33d9a7bd12327702397c0e7aaf96e490dec46e` | `5c78ff5d33bdfa9c7b92b7bb9ff5c0fefdc7eef8` | `test_documentation.py:_CHECKBOX_BLOCK`; `test_documentation.py:test_contract_requirements_map_to_plan_tasks_and_tests`; imports of `find_project_root`, `resolve_project_root`, and `initialize_project`; `test_project_init.py:test_init_project_establishes_discoverable_root` |

The fixture plan must name every declaration in its expected set. Every target
transition must match, every selected PairBlock gate must exit with code `0`,
every dependency must be selected or already match its baseline target state, and
the Git diff must expose no additional changed Python declaration.
`PlanCheck.passed` is then true.
`accept()` binds that result to the fixture's realized commit.

### Rejection

A focused fixture changes one additional function outside the selected target
set.
`check_plan()` places that function in `PlanCheck.unexpected` and returns
`passed=False`. Separate tests cover a stale baseline action, wrong declaration
digest, missing target, failed gate, invalid plan digest, unsatisfied
dependency, CodeQL identity drift, and a commit whose source or selected plan
differs from the checked candidate.

The focused impact fixtures use `A -> B -> C` with `C` as the planned target.
Policy-selected direct impact contains `B` and excludes `A`. Separate fixtures
require a callable-interface update to select `calls`, a removal to select all
six represented edge kinds, and an `unclassified` update to use the same
conservative direct-edge fallback.

The one-hop fixture adds a baseline caller and a candidate adapter around one
selected function. `OneHop.before` and `OneHop.after` retain the exact incoming
edge IDs, and `OneHop.neighbors` contains both direct dependents. A separate
fixture changes a function parameter but leaves its caller unchanged. Pyright
rejects that materialized candidate before candidate CodeQL analysis or any
PairBlock gate runs.

## 10. Implementation order

<!-- pair-block-definition: P0-SIG-01 -->
```toml pair-block
id = "P0-SIG-01"
requirements = ["SIG-01", "SIG-05"]
targets = ["src/viper/system_impact/models.py:CodeQLIdentity", "src/viper/system_impact/models.py:SourceSnapshot", "src/viper/system_impact/models.py:CodeQLReceipt", "src/viper/system_impact/models.py:SourceNode", "src/viper/system_impact/models.py:SourceEdge", "src/viper/system_impact/models.py:SourceGraph"]
tests = ["tests/test_system_impact.py:test_source_graph_is_canonical"]
gate = "python -m pytest tests/test_system_impact.py -k source_graph_is_canonical -q"
depends_on = ["P0-CRT-07"]
```

<!-- pair-block-definition: P0-SIG-02 -->
```toml pair-block
id = "P0-SIG-02"
requirements = ["SIG-01", "SIG-05"]
targets = ["src/viper/_system_impact/codeql.py:IGNORED_PARTS", "src/viper/_system_impact/codeql.py:CodeQLAnalysisError", "src/viper/_system_impact/codeql.py:_Declaration", "src/viper/_system_impact/codeql.py:_Anchor", "src/viper/_system_impact/codeql.py:_qualified_declarations", "src/viper/_system_impact/codeql.py:_node_span", "src/viper/_system_impact/codeql.py:_binding_span", "src/viper/_system_impact/codeql.py:_codeql_byte_col", "src/viper/_system_impact/codeql.py:_source_node_id", "src/viper/_system_impact/codeql.py:_load_nodes", "src/viper/_system_impact/codeql.py:_edge_node", "src/viper/_system_impact/codeql.py:_load_edges", "src/viper/_system_impact/codeql.py:source_digest", "src/viper/_system_impact/codeql.py:analyze_source", "src/viper/system_impact/models.py:CodeQLReceipt", "src/viper/system_impact/models.py:SourceNodeKind", "src/viper/system_impact/models.py:SourceNode", "src/viper/system_impact/models.py:SourceGraph", "tests/test_system_impact.py:test_source_digest_ignores_viper_worktrees", "tests/test_system_impact.py:test_node_span_keeps_trailing_inline_directive", "tests/test_system_impact.py:test_load_nodes_uses_binding_occurrences_and_rejects_ambiguous_targets", "tests/test_system_impact.py:test_load_edges_uses_exact_binding_locations"]
assets = ["tools/codeql/viper-python-impact/qlpack.yml", "tools/codeql/viper-python-impact/codeql-pack.lock.yml", "tools/codeql/viper-python-impact/source-facts.qls", "tools/codeql/viper-python-impact/Nodes.qll", "tools/codeql/viper-python-impact/Declarations.ql", "tools/codeql/viper-python-impact/Dependencies.ql"]
tests = ["tests/test_system_impact.py:test_analyze_source_binds_digests_identity_and_database_reuse", "tests/test_system_impact.py:test_analyze_source_rebuilds_tampered_cache_manifest", "tests/test_system_impact.py:test_analyze_source_rejects_source_pack_and_cli_identity_drift", "tests/test_system_impact.py:test_checked_in_codeql_pack_analyzes_tiny_repository", "tests/test_system_impact.py:test_source_digest_ignores_viper_worktrees", "tests/test_system_impact.py:test_node_span_keeps_trailing_inline_directive", "tests/test_system_impact.py:test_load_nodes_uses_binding_occurrences_and_rejects_ambiguous_targets", "tests/test_system_impact.py:test_load_edges_uses_exact_binding_locations"]
gate = "python -m pytest tests/test_system_impact.py -k 'analyze_source or checked_in_codeql_pack or node_span or load_nodes or load_edges' -q"
depends_on = ["P0-SIG-01"]
```

<!-- pair-block-definition: P0-SIG-03 -->
```toml pair-block
id = "P0-SIG-03"
requirements = ["SIG-01", "SIG-02"]
targets = ["src/viper/_system_impact/source.py:SourceDeclarationError", "src/viper/_system_impact/source.py:extract_declaration_bytes", "src/viper/_system_impact/source.py:classify_target_change", "src/viper/system_impact/plan.py:IMPACT_EDGE_KINDS_V1", "src/viper/system_impact/plan.py:PlanInspectionError", "src/viper/system_impact/plan.py:inspect_plan", "src/viper/system_impact/models.py:ChangeKind", "src/viper/system_impact/models.py:Impact", "src/viper/system_impact/models.py:ResolvedContractTarget", "src/viper/system_impact/models.py:PlanInspection"]
tests = ["tests/test_system_impact.py:test_declaration_extraction_preserves_exact_decorated_bytes", "tests/test_system_impact.py:test_change_classifier_distinguishes_interface_and_body_updates", "tests/test_system_impact.py:test_plan_reports_only_policy_selected_one_hop_dependents", "tests/test_system_impact.py:test_removed_target_reports_all_represented_direct_dependents", "tests/test_system_impact.py:test_unclassified_change_uses_conservative_one_hop_edges"]
gate = "python -m pytest tests/test_system_impact.py -k 'declaration_extraction or change_classifier or policy_selected_one_hop or removed_target or unclassified_change' -q"
depends_on = ["P0-SIG-02"]
```

<!-- pair-block-definition: P0-SIG-04 -->
```toml pair-block
id = "P0-SIG-04"
requirements = ["SIG-03"]
targets = ["src/viper/_contract_traceability.py:compile_contract_plan", "src/viper/system_impact/check.py:SystemImpactCheckError", "src/viper/system_impact/check.py:check_plan", "src/viper/system_impact/check.py:accept", "src/viper/system_impact/models.py:CheckState", "src/viper/system_impact/models.py:TargetCheck", "src/viper/system_impact/models.py:GateCheck", "src/viper/system_impact/models.py:PlanCheck", "src/viper/system_impact/models.py:Acceptance", "src/viper/system_impact/models.py:__all__"]
tests = ["tests/test_system_impact.py:test_plan_check_rejects_unplanned_source_change", "tests/test_system_impact.py:test_plan_check_rejects_wrong_target_and_receipt_identity", "tests/test_system_impact.py:test_plan_check_runs_gates_and_validates_dependencies", "tests/test_system_impact.py:test_plan_check_rejects_asset_changed_by_gate", "tests/test_system_impact.py:test_acceptance_binds_commit_to_checked_source_and_plan"]
gate = "python -m pytest tests/test_system_impact.py -k 'plan_check or acceptance' -q"
depends_on = ["P0-SIG-03"]
```

<!-- pair-block-definition: P0-SIG-05 -->
```toml pair-block
id = "P0-SIG-05"
requirements = ["SIG-04"]
targets = ["tests/test_system_impact.py:test_committed_manifest_rename", "tests/test_system_impact.py:test_completed_viper_pair_block"]
assets = ["tests/data/system_impact/agents_manifest_migration/metadata.json", "tests/data/system_impact/agents_manifest_migration/baseline/scripts/run-skill-evaluations.py.source", "tests/data/system_impact/agents_manifest_migration/baseline/scripts/validate-skill-contract.py.source", "tests/data/system_impact/agents_manifest_migration/baseline/scripts/validate-skill-evaluation-run.py.source", "tests/data/system_impact/agents_manifest_migration/baseline/tests/test_run_skill_evaluations.py.source", "tests/data/system_impact/agents_manifest_migration/baseline/tests/test_skill_contract.py.source", "tests/data/system_impact/agents_manifest_migration/realized/scripts/run-skill-evaluations.py.source", "tests/data/system_impact/agents_manifest_migration/realized/scripts/validate-skill-contract.py.source", "tests/data/system_impact/agents_manifest_migration/realized/scripts/validate-skill-evaluation-run.py.source", "tests/data/system_impact/agents_manifest_migration/realized/tests/test_run_skill_evaluations.py.source", "tests/data/system_impact/agents_manifest_migration/realized/tests/test_skill_contract.py.source", "tests/data/system_impact/viper_p0_proof_05/metadata.json", "tests/data/system_impact/viper_p0_proof_05/baseline/tests/test_documentation.py.source", "tests/data/system_impact/viper_p0_proof_05/baseline/tests/test_project_init.py.source", "tests/data/system_impact/viper_p0_proof_05/realized/tests/test_documentation.py.source", "tests/data/system_impact/viper_p0_proof_05/realized/tests/test_project_init.py.source"]
tests = ["tests/test_system_impact.py:test_committed_manifest_rename", "tests/test_system_impact.py:test_completed_viper_pair_block"]
gate = "python -m pytest tests/test_system_impact.py -k 'committed_manifest_rename or completed_viper_pair_block' -q"
depends_on = ["P0-SIG-04"]
```


<!-- pair-block-definition: P0-SIG-06 -->
```toml pair-block
id = "P0-SIG-06"
requirements = ["SIG-06"]
targets = ["tests/test_system_impact.py:test_checked_in_codeql_pack_analyzes_tiny_repository"]
assets = ["tools/codeql/viper-python-impact/Nodes.qll", "tools/codeql/viper-python-impact/Declarations.ql", "tools/codeql/viper-python-impact/Dependencies.ql"]
tests = ["tests/test_system_impact.py:test_checked_in_codeql_pack_analyzes_tiny_repository"]
gate = "VIPER_RUN_CODEQL_TESTS=1 python -m pytest tests/test_system_impact.py::test_checked_in_codeql_pack_analyzes_tiny_repository -q"
depends_on = ["P0-SIG-05"]
```

<!-- pair-block-definition: P0-SIG-07 -->
```toml pair-block
id = "P0-SIG-07"
requirements = ["SIG-07"]
targets = ["src/viper/system_impact/models.py:OneHop", "src/viper/system_impact/models.py:PlanCheck", "src/viper/system_impact/models.py:__all__", "src/viper/_system_impact/source.py:ImportBinding", "src/viper/_system_impact/source.py:import_binding", "src/viper/_system_impact/source.py:_import_names", "src/viper/_system_impact/source.py:_resolve_declaration", "src/viper/system_impact/check.py:ast", "src/viper/system_impact/check.py:Acceptance", "src/viper/system_impact/check.py:CommitId", "src/viper/system_impact/check.py:GateCheck", "src/viper/system_impact/check.py:IMPACT_EDGE_KINDS_V1", "src/viper/system_impact/check.py:OneHop", "src/viper/system_impact/check.py:PlanCheck", "src/viper/system_impact/check.py:ResolvedContractTarget", "src/viper/system_impact/check.py:SourceGraph", "src/viper/system_impact/check.py:SourceNode", "src/viper/system_impact/check.py:TargetCheck", "src/viper/system_impact/check.py:inspect_plan", "src/viper/system_impact/check.py:extract_declaration_bytes", "src/viper/system_impact/check.py:import_binding", "src/viper/system_impact/check.py:_target_is_satisfied", "src/viper/system_impact/check.py:_target_checks", "src/viper/system_impact/check.py:_unexpected_changes", "src/viper/system_impact/check.py:_one_hop", "src/viper/system_impact/check.py:check_plan", "tests/test_system_impact.py:import_binding", "tests/test_system_impact.py:test_class_target_owns_nested_declaration_changes", "tests/test_system_impact.py:test_import_target_owns_names_in_the_same_statement", "tests/test_system_impact.py:test_formatting_only_change_is_not_unexpected", "tests/test_system_impact.py:test_one_hop_records_baseline_and_candidate_neighbors", "tests/test_system_impact.py:test_pre_pairing_pyright_rejects_stale_caller"]
tests = ["tests/test_system_impact.py:test_class_target_owns_nested_declaration_changes", "tests/test_system_impact.py:test_import_target_owns_names_in_the_same_statement", "tests/test_system_impact.py:test_formatting_only_change_is_not_unexpected", "tests/test_system_impact.py:test_one_hop_records_baseline_and_candidate_neighbors", "tests/test_system_impact.py:test_pre_pairing_pyright_rejects_stale_caller"]
gate = "python -m pytest tests/test_system_impact.py -k 'class_target_owns or import_target_owns or formatting_only or one_hop_records or pre_pairing_pyright' -q"
depends_on = ["P0-SIG-06"]
```

The implementation closes after all seven focused gates pass, the complete test
module passes, and the review-cycle commit is synchronized with its upstream.

## 11. ContractTarget

These declarations are the exact implementation values owned by the PairBlocks.
Later update targets supersede the earlier declaration for the same symbol.

### CodeQL adapter

<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:IGNORED_PARTS -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:CodeQLAnalysisError -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:_Declaration -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:_Anchor -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=update target=src/viper/_system_impact/codeql.py:_qualified_declarations -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=update target=src/viper/_system_impact/codeql.py:_node_span -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:_binding_span -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:_codeql_byte_col -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:_source_node_id -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=update target=src/viper/_system_impact/codeql.py:_load_nodes -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:_edge_node -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-02 action=update target=src/viper/_system_impact/codeql.py:_load_edges -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:source_digest -->
<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=src/viper/_system_impact/codeql.py:analyze_source -->

```python contract-target
IGNORED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".viper",
        "node_modules",
    }
)

class CodeQLAnalysisError(RuntimeError):
    """Report a failed or internally inconsistent CodeQL analysis."""

@dataclass(frozen=True)
class _Declaration:
    """Keep one symbol's AST binding and full statement together."""

    symbol: str
    kind: SourceNodeKind
    declaration: ast.stmt
    binding: ast.AST

_Anchor = tuple[str, SourceNodeKind, int, int]

def _qualified_declarations(
    tree: ast.Module,
) -> tuple[_Declaration, ...]:
    """Collect the declarations represented in the source graph."""
    declarations: list[_Declaration] = []

    def visit(body: Sequence[ast.stmt], prefix: str = "") -> None:
        """Collect declarations from one module or class body."""
        for node in body:
            bindings: tuple[tuple[str, ast.AST], ...] = ()
            kind: SourceNodeKind | None = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bindings = ((node.name, node),)
                kind = "method" if prefix else "function"
            elif isinstance(node, ast.ClassDef):
                bindings = ((node.name, node),)
                kind = "class"
            elif isinstance(node, ast.Assign):
                bindings = tuple(
                    (target.id, target)
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )
                kind = "assignment"
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                bindings = ((node.target.id, node.target),)
                kind = "assignment"
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings = tuple(
                    (
                        alias.asname or alias.name,
                        alias,
                    )
                    for alias in node.names
                    if alias.name != "*"
                )
                kind = "import"

            if kind is None:
                continue

            # One statement can bind several names, so keep each binding separate.
            for name, binding in bindings:
                declarations.append(
                    _Declaration(
                        symbol=f"{prefix}{name}",
                        kind=kind,
                        declaration=node,
                        binding=binding,
                    )
                )

            # Class members need the class prefix; function locals are not graph nodes.
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")

    visit(tree.body)
    return tuple(declarations)

def source_digest(root: Path) -> str:
    rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in _python_files(root)
    ]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

def analyze_source(
    snapshot_root: Path,
    *,
    snapshot: SourceSnapshot,
    identity: CodeQLIdentity,
    codeql_executable: Path,
    query_pack: Path,
    cache_root: Path,
    artifact_root: Path,
) -> SourceGraph:
    """Analyze one exact Python source tree with a pinned CodeQL query pack."""
    root = snapshot_root.resolve()
    if source_digest(root) != snapshot.source_sha256:
        raise CodeQLAnalysisError(
            "SourceSnapshot.source_sha256 does not match source bytes"
        )
    if _tree_digest(query_pack.resolve()) != identity.pack_sha256:
        raise CodeQLAnalysisError(
            "CodeQLIdentity.pack_sha256 does not match query-pack bytes"
        )

    version_stdout, version_stderr = _run(
        (str(codeql_executable), "version", "--format=json"), cwd=root
    )
    version_payload = json.loads(version_stdout)
    if version_payload.get("version") != identity.version:
        raise CodeQLAnalysisError(
            "CodeQL executable version does not match CodeQLIdentity"
        )
    if hashlib.sha256(codeql_executable.read_bytes()).hexdigest() != (
        identity.executable_sha256
    ):
        raise CodeQLAnalysisError(
            "CodeQL executable digest does not match CodeQLIdentity"
        )

    key = _hash_parts(
        (
            snapshot.source_sha256.encode(),
            identity.version.encode(),
            identity.executable_sha256.encode(),
            identity.pack_sha256.encode(),
        )
    )
    database = cache_root.resolve() / key / "database"
    manifest = database.parent / "viper-database.json"
    commands: list[tuple[str, ...]] = [
        (str(codeql_executable), "version", "--format=json")
    ]
    stderr_parts: list[bytes] = [b"version", version_stderr]
    if not _database_is_reusable(
        database,
        manifest,
        key=key,
        source_sha256=snapshot.source_sha256,
    ):
        if database.parent.exists():
            shutil.rmtree(database.parent)
        database.parent.mkdir(parents=True)
        command = (
            str(codeql_executable),
            "database",
            "create",
            str(database),
            "--language=python",
            f"--source-root={root}",
            "--overwrite",
        )
        _, stderr = _run(command, cwd=root)
        commands.append(command)
        stderr_parts.extend((b"database-create", stderr))
    artifact_root.mkdir(parents=True, exist_ok=True)
    decoded: dict[str, list[list[Any]]] = {}
    for query_name in _QUERY_FILES:
        query = query_pack / query_name
        bqrs = artifact_root / f"{query.stem}.bqrs"
        decoded_path = artifact_root / f"{query.stem}.json"
        run_command = (
            str(codeql_executable),
            "query",
            "run",
            str(query),
            f"--database={database}",
            f"--output={bqrs}",
        )
        _, stderr = _run(run_command, cwd=root)
        commands.append(run_command)
        stderr_parts.extend((query_name.encode(), stderr))
        decode_command = (
            str(codeql_executable),
            "bqrs",
            "decode",
            str(bqrs),
            "--format=json",
            f"--output={decoded_path}",
        )
        _, stderr = _run(decode_command, cwd=root)
        commands.append(decode_command)
        stderr_parts.extend((f"decode:{query_name}".encode(), stderr))
        rows = _table_rows(json.loads(decoded_path.read_text(encoding="utf-8")))
        rows.sort(
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"))
        )
        decoded[query.stem] = rows

    nodes = _load_nodes(root, decoded["Declarations"])
    edges = _load_edges(root, decoded["Dependencies"], nodes)
    result_payload = json.dumps(
        {
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": [edge.model_dump(mode="json") for edge in edges],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    database_sha256 = _tree_digest(database)
    manifest.write_text(
        json.dumps(
            {
                "key": key,
                "source_sha256": snapshot.source_sha256,
                "database_sha256": database_sha256,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt = CodeQLReceipt(
        snapshot=snapshot,
        identity=identity,
        commands=tuple(commands),
        exit_code=0,
        database_sha256=database_sha256,
        result_sha256=hashlib.sha256(result_payload).hexdigest(),
        stderr_sha256=_hash_parts(stderr_parts),
    )
    return SourceGraph(
        snapshot=snapshot,
        identity=identity,
        nodes=nodes,
        edges=edges,
        receipt=receipt,
    )

def _node_span(node: ast.stmt, source: bytes) -> tuple[int, int, int, int, bytes]:
    """Slice the complete statement from the original source bytes."""
    if node.end_lineno is None or node.end_col_offset is None:
        raise CodeQLAnalysisError("Python declaration has no complete source span")
    lines, offsets = _byte_offsets(source)
    start_line = node.lineno
    start_col = node.col_offset

    # Decorators belong to the declaration even though AST starts at def or class.
    if (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.decorator_list
    ):
        decorator = node.decorator_list[0]
        start_line = decorator.lineno
        start_col = lines[start_line - 1].rfind(b"@", 0, decorator.col_offset + 1)
        if start_col < 0:
            raise CodeQLAnalysisError("decorated declaration has no leading at-sign")
    start = offsets[start_line - 1] + start_col
    end_line = lines[node.end_lineno - 1]
    end_col = node.end_col_offset
    suffix = end_line[end_col:]

    # Keep a line-end directive with the statement it controls.
    if suffix.lstrip().startswith(b"#"):
        end_col = len(end_line.rstrip(b"\r\n"))
    end = offsets[node.end_lineno - 1] + end_col
    return (
        start_line,
        start_col,
        node.end_lineno,
        end_col,
        source[start:end],
    )

def _binding_span(node: ast.AST, source: bytes) -> tuple[int, int, int, int]:
    """Read the AST coordinates used to match a CodeQL anchor."""
    start_line = getattr(node, "lineno", None)
    start_col = getattr(node, "col_offset", None)
    end_line = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if (
        not isinstance(start_line, int)
        or not isinstance(start_col, int)
        or not isinstance(end_line, int)
        or not isinstance(end_col, int)
    ):
        raise CodeQLAnalysisError("Python binding has no complete source span")
    lines, offsets = _byte_offsets(source)

    # AST columns count UTF-8 bytes, so validate them against the original source.
    try:
        start = offsets[start_line - 1] + start_col
        end = offsets[end_line - 1] + end_col
    except (IndexError, TypeError) as error:
        raise CodeQLAnalysisError(
            "Python binding has an invalid source span"
        ) from error
    if start < 0 or end < start or end > len(source):
        raise CodeQLAnalysisError("Python binding has an invalid source span")
    return start_line, start_col, end_line, end_col

def _codeql_byte_col(source: bytes, line: int, column: int) -> int:
    """Convert CodeQL's character column to the byte column used by AST."""
    lines = source.splitlines(keepends=True)
    if line < 1 or line > len(lines) or column < 1:
        raise CodeQLAnalysisError("CodeQL emitted an invalid binding location")
    try:
        text = lines[line - 1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise CodeQLAnalysisError("Python source is not valid UTF-8") from error
    prefix = text[: column - 1]
    if len(prefix) != column - 1:
        raise CodeQLAnalysisError("CodeQL emitted an invalid binding column")

    # A non-ASCII character can occupy more than one UTF-8 byte.
    return len(prefix.encode("utf-8"))

def _source_node_id(path: str, symbol: str) -> str:
    """Return the stable target key after uniqueness has been proved."""
    return f"{path}:{symbol}"

def _load_nodes(root: Path, rows: list[list[Any]]) -> tuple[SourceNode, ...]:
    """Join every CodeQL anchor to one AST declaration or reject the graph."""
    nodes: dict[str, SourceNode] = {}
    files: dict[str, tuple[bytes, dict[_Anchor, _Declaration]]] = {}

    for row in rows:
        if len(row) != 5:
            raise CodeQLAnalysisError("CodeQL emitted a malformed declaration row")

        path = str(row[0])
        if any(part in IGNORED_PARTS for part in Path(path).parts):
            continue

        # CodeQL emits one row per declaration, so parse each file only once.
        if path not in files:
            source_path = root / path
            if not source_path.is_file() or source_path.suffix != ".py":
                raise CodeQLAnalysisError(f"CodeQL declaration path is absent: {path}")

            source = source_path.read_bytes()
            try:
                tree = ast.parse(
                    source.decode("utf-8"),
                    type_comments=True,
                )
            except (SyntaxError, UnicodeDecodeError) as error:
                raise CodeQLAnalysisError(
                    f"cannot resolve CodeQL declarations in {path}"
                ) from error

            index: dict[_Anchor, _Declaration] = {}

            for declaration in _qualified_declarations(tree):
                line, column, _, _ = _binding_span(
                    declaration.binding,
                    source,
                )
                key = (
                    declaration.symbol,
                    declaration.kind,
                    line,
                    column,
                )

                if key in index:
                    raise CodeQLAnalysisError(
                        f"duplicate AST declaration anchor in {path}: {key}"
                    )

                index[key] = declaration

            files[path] = source, index

        source, index = files[path]
        symbol = str(row[1])
        kind = cast(SourceNodeKind, str(row[2]))
        line = int(row[3])
        column = _codeql_byte_col(source, line, int(row[4]))
        key = symbol, kind, line, column

        try:
            declaration = index[key]
        except KeyError as error:
            raise CodeQLAnalysisError(
                "CodeQL anchor has no matching AST declaration: "
                f"{path}:{symbol} at {line}:{column}"
            ) from error

        (
            binding_start_line,
            binding_start_col,
            binding_end_line,
            binding_end_col,
        ) = _binding_span(declaration.binding, source)

        start_line, start_col, end_line, end_col, exact = _node_span(
            declaration.declaration,
            source,
        )

        node_id = _source_node_id(path, symbol)

        # Contract targets omit location, so a second occurrence is ambiguous.
        if node_id in nodes:
            raise CodeQLAnalysisError(
                f"source target does not identify one declaration: {path}:{symbol}"
            )

        nodes[node_id] = SourceNode(
            node_id=node_id,
            path=path,
            symbol=symbol,
            kind=kind,
            binding_start_line=binding_start_line,
            binding_start_col=binding_start_col,
            binding_end_line=binding_end_line,
            binding_end_col=binding_end_col,
            start_line=start_line,
            start_col=start_col,
            end_line=end_line,
            end_col=end_col,
            sha256=hashlib.sha256(exact).hexdigest(),
        )

    return tuple(sorted(nodes.values(), key=lambda node: node.node_id))

def _edge_node(
    root: Path,
    nodes: dict[tuple[str, int, int], SourceNode],
    sources: dict[str, bytes],
    path: str,
    line: int,
    column: int,
) -> SourceNode:
    """Resolve one CodeQL edge endpoint by its exact binding location."""
    if path not in sources:
        source_path = root / path
        if not source_path.is_file() or source_path.suffix != ".py":
            raise CodeQLAnalysisError(f"CodeQL edge path is absent: {path}")
        sources[path] = source_path.read_bytes()

    byte_column = _codeql_byte_col(sources[path], line, column)
    try:
        return nodes[path, line, byte_column]
    except KeyError as error:
        raise CodeQLAnalysisError(
            f"CodeQL edge endpoint has no source node: {path} at {line}:{byte_column}"
        ) from error

def _load_edges(
    root: Path,
    rows: list[list[Any]],
    nodes: tuple[SourceNode, ...],
) -> tuple[SourceEdge, ...]:
    """Join each CodeQL dependency to two exact source nodes."""
    index: dict[tuple[str, int, int], SourceNode] = {}
    for node in nodes:
        key = (node.path, node.binding_start_line, node.binding_start_col)
        if key in index:
            raise CodeQLAnalysisError(f"duplicate source-node anchor: {key}")
        index[key] = node

    sources: dict[str, bytes] = {}
    edges: dict[str, SourceEdge] = {}
    for row in rows:
        if len(row) != 9:
            raise CodeQLAnalysisError("CodeQL emitted a malformed dependency row")

        source_path = str(row[0])
        target_path = str(row[3])
        if any(
            part in IGNORED_PARTS
            for path in (source_path, target_path)
            for part in Path(path).parts
        ):
            continue

        source = _edge_node(
            root,
            index,
            sources,
            source_path,
            int(row[1]),
            int(row[2]),
        )
        target = _edge_node(
            root,
            index,
            sources,
            target_path,
            int(row[4]),
            int(row[5]),
        )
        if source.node_id == target.node_id:
            continue

        kind = str(row[6])
        if kind not in _EDGE_KINDS:
            raise CodeQLAnalysisError(f"CodeQL emitted an unknown edge kind: {kind}")
        payload = json.dumps(
            [source.node_id, kind, target.node_id, str(row[7]), int(row[8])],
            separators=(",", ":"),
        ).encode()
        edge_id = hashlib.sha256(payload).hexdigest()
        edges[edge_id] = SourceEdge(
            edge_id=edge_id,
            source=source.node_id,
            target=target.node_id,
            kind=cast(EdgeKind, kind),
            query="viper/python-impact/dependencies",
            path=str(row[7]),
            line=int(row[8]),
        )
    return tuple(sorted(edges.values(), key=lambda edge: edge.edge_id))
```

<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=tests/test_system_impact.py:test_load_nodes_uses_binding_occurrences_and_rejects_ambiguous_targets -->
```python contract-target
def test_load_nodes_uses_binding_occurrences_and_rejects_ambiguous_targets(
    tmp_path: Path,
) -> None:
    """Resolve each CodeQL location once and reject repeated target names."""
    source = tmp_path / "imports.py"
    source.write_text("from x import A, B as C\n", encoding="utf-8")
    rows = [
        ["imports.py", "A", "import", 1, 15],
        ["imports.py", "C", "import", 1, 18],
    ]

    nodes = _load_nodes(tmp_path, rows)

    assert tuple(node.node_id for node in nodes) == (
        "imports.py:A",
        "imports.py:C",
    )
    assert tuple(
        (
            node.binding_start_line,
            node.binding_start_col,
            node.binding_end_line,
            node.binding_end_col,
        )
        for node in nodes
    ) == ((1, 14, 1, 15), (1, 17, 1, 23))
    assert nodes[0].sha256 == nodes[1].sha256

    source.write_text("VALUE = 1\nVALUE = 2\n", encoding="utf-8")
    duplicate_rows = [
        ["imports.py", "VALUE", "assignment", 1, 1],
        ["imports.py", "VALUE", "assignment", 2, 1],
    ]
    with pytest.raises(CodeQLAnalysisError, match="does not identify one declaration"):
        _load_nodes(tmp_path, duplicate_rows)
```

<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=tests/test_system_impact.py:test_load_edges_uses_exact_binding_locations -->
```python contract-target
def test_load_edges_uses_exact_binding_locations(tmp_path: Path) -> None:
    """Attach a same-line dependency to the binding named by CodeQL."""
    source = tmp_path / "imports.py"
    source.write_text("from x import A, B as C\n", encoding="utf-8")
    nodes = _load_nodes(
        tmp_path,
        [
            ["imports.py", "A", "import", 1, 15],
            ["imports.py", "C", "import", 1, 18],
        ],
    )
    rows = [["imports.py", 1, 15, "imports.py", 1, 18, "reads", "use.py", 4]]

    edges = _load_edges(tmp_path, rows, nodes)

    assert len(edges) == 1
    assert edges[0].source == "imports.py:A"
    assert edges[0].target == "imports.py:C"

    rows[0][5] = 16
    with pytest.raises(CodeQLAnalysisError, match="has no source node"):
        _load_edges(tmp_path, rows, nodes)
```

<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=tests/test_system_impact.py:test_node_span_keeps_trailing_inline_directive -->
```python contract-target
def test_node_span_keeps_trailing_inline_directive() -> None:
    """Keep a line-end type directive with the declaration it qualifies."""
    source = (
        b"class Item:\n    value: int  # pyright: ignore[reportGeneralTypeIssues]\n"
    )
    declaration = ast.parse(source).body[0]

    assert _node_span(declaration, source)[-1] == source.rstrip(b"\n")
```

### Declaration resolution and impact

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/_system_impact/source.py:ImportBinding -->
```python contract-target
ImportBinding: TypeAlias = tuple[str, int, str | None, str, str | None]
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/_system_impact/source.py:import_binding -->
```python contract-target
def import_binding(source: bytes, symbol: str) -> ImportBinding:
    """Return the import that creates one local name."""
    matches: list[ImportBinding] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if local == symbol:
                    matches.append(("import", 0, None, alias.name, alias.asname))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                if local == symbol:
                    matches.append(
                        ("from", node.level, node.module, alias.name, alias.asname)
                    )
    if len(matches) != 1:
        raise SourceDeclarationError(
            f"expected one import binding for {symbol!r}; found {len(matches)}"
        )
    return matches[0]
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/_system_impact/source.py:_import_names -->
```python contract-target
def _import_names(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    """Return the names created by one import statement."""
    names: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            continue
        names.append(alias.asname or alias.name)
    return tuple(names)
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/_system_impact/source.py:_resolve_declaration -->
```python contract-target
def _resolve_declaration(tree: ast.Module, qualified_symbol: str) -> ast.stmt:
    """Find the one declaration named by a contract target."""
    parts = qualified_symbol.split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        raise SourceDeclarationError(
            f"invalid qualified Python symbol: {qualified_symbol!r}"
        )

    direct = [
        node for node in tree.body if qualified_symbol in _declaration_names(node)
    ]
    if len(direct) == 1:
        return direct[0]
    if len(direct) > 1:
        raise SourceDeclarationError(
            f"Python declaration is ambiguous: {qualified_symbol}"
        )

    body: Sequence[ast.stmt] = tree.body
    for index, part in enumerate(parts):
        matches = [node for node in body if part in _declaration_names(node)]
        if not matches:
            raise SourceDeclarationError(
                f"Python declaration is absent: {qualified_symbol}"
            )
        if len(matches) > 1:
            raise SourceDeclarationError(
                f"Python declaration is ambiguous: {qualified_symbol}"
            )

        match = matches[0]
        if index == len(parts) - 1:
            return match
        if not isinstance(match, ast.ClassDef):
            raise SourceDeclarationError(
                f"qualified symbol parent is not a class: {qualified_symbol}"
            )
        body = match.body

    raise AssertionError("qualified symbol resolution exhausted without a result")
```

<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/_system_impact/source.py:SourceDeclarationError -->
<!-- contract-target: requirements=SIG-01 block=P0-SIG-03 action=add target=src/viper/_system_impact/source.py:extract_declaration_bytes -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/_system_impact/source.py:classify_target_change -->

```python contract-target
class SourceDeclarationError(ValueError):
    """Report an absent, ambiguous, malformed, or impossible declaration change."""

def extract_declaration_bytes(
    source: bytes,
    qualified_symbol: str,
) -> bytes:
    """Return one declaration exactly as encoded in UTF-8 source.

    Module declarations and class members may be functions, classes,
    assignments, annotated assignments, or import statements. The operation
    raises ``SourceDeclarationError`` when the source or symbol cannot identify
    one exact declaration.
    """
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceDeclarationError("Python source is not valid UTF-8") from error

    try:
        tree = ast.parse(text, type_comments=True)
    except SyntaxError as error:
        raise SourceDeclarationError("Python source cannot be parsed") from error

    node = _resolve_declaration(tree, qualified_symbol)
    if (
        getattr(node, "lineno", None) is None
        or getattr(node, "col_offset", None) is None
        or node.end_lineno is None
        or node.end_col_offset is None
    ):
        raise SourceDeclarationError(
            f"Python declaration lacks a complete source span: {qualified_symbol}"
        )

    lines, offsets = _line_offsets(source)
    try:
        start_line, start_column = _declaration_start(node, lines)
        start = offsets[start_line - 1] + start_column
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        # Keep an inline directive with the declaration it qualifies.
        end_line = lines[node.end_lineno - 1]
        suffix = end_line[node.end_col_offset :]
        if suffix.lstrip().startswith(b"#"):
            end = offsets[node.end_lineno - 1] + len(end_line.rstrip(b"\r\n"))
    except (IndexError, ValueError) as error:
        raise SourceDeclarationError(
            f"Python declaration has an invalid source span: {qualified_symbol}"
        ) from error

    if start < 0 or end < start or end > len(source):
        raise SourceDeclarationError(
            f"Python declaration has an invalid source span: {qualified_symbol}"
        )
    return source[start:end]

def classify_target_change(
    *,
    action: TargetAction,
    baseline: bytes | None,
    expected: bytes | None,
) -> ChangeKind:
    """Classify one valid planned declaration transition.

    The operation raises ``SourceDeclarationError`` when the declared action
    contradicts declaration presence.
    """
    if action == "add":
        if baseline is not None or expected is None:
            raise SourceDeclarationError(
                "add requires an absent baseline and a present expected declaration"
            )
        _parse_single_declaration(expected, "expected")
        return "added"

    if action == "remove":
        if baseline is None or expected is not None:
            raise SourceDeclarationError(
                "remove requires a present baseline and no expected declaration"
            )
        _parse_single_declaration(baseline, "baseline")
        return "removed"

    if action != "update":
        raise SourceDeclarationError(f"unsupported target action: {action!r}")
    if baseline is None or expected is None:
        raise SourceDeclarationError(
            "update requires baseline and expected declarations"
        )
    if baseline == expected:
        return "satisfied"

    before = _parse_single_declaration(baseline, "baseline")
    after = _parse_single_declaration(expected, "expected")
    if type(before) is not type(after):
        return "unclassified"

    if isinstance(before, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(
        after, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        if _callable_interface(before) != _callable_interface(after):
            return "callable_interface_changed"
        return "implementation_changed"

    if isinstance(before, ast.ClassDef) and isinstance(after, ast.ClassDef):
        if _class_interface(before) != _class_interface(after):
            return "type_interface_changed"
        return "implementation_changed"

    if isinstance(before, (ast.Assign, ast.AnnAssign)) and isinstance(
        after, (ast.Assign, ast.AnnAssign)
    ):
        if _assignment_interface(before) != _assignment_interface(after):
            return "type_interface_changed"
        return "implementation_changed"

    if not isinstance(before, _SupportedDeclaration) or not isinstance(
        after, _SupportedDeclaration
    ):
        return "unclassified"
    return "unclassified"
```

<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/plan.py:IMPACT_EDGE_KINDS_V1 -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/plan.py:PlanInspectionError -->
<!-- contract-target: requirements=SIG-02 block=P0-SIG-03 action=add target=src/viper/system_impact/plan.py:inspect_plan -->

```python contract-target
IMPACT_EDGE_KINDS_V1: dict[str, frozenset[EdgeKind]] = {
    "satisfied": frozenset(),
    "added": frozenset(),
    "removed": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
    "callable_interface_changed": frozenset({"calls", "constructs"}),
    "type_interface_changed": frozenset({"constructs", "inherits", "reads", "writes"}),
    "implementation_changed": frozenset({"calls", "reads"}),
    "unclassified": frozenset(
        {"imports", "calls", "constructs", "inherits", "reads", "writes"}
    ),
}

class PlanInspectionError(ValueError):
    """Report an absent, duplicate, stale, or impossible selected target."""

def inspect_plan(
    *,
    plan_root: Path,
    baseline_root: Path,
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
    baseline: SourceGraph,
) -> PlanInspection:
    """Resolve selected targets and return policy-selected incoming edges."""
    if not block_ids or len(block_ids) != len(set(block_ids)):
        raise PlanInspectionError("block_ids must contain unique selected PairBlocks")
    known_blocks = {block.block_id for block in traceability.blocks}
    missing = sorted(set(block_ids) - known_blocks)
    if missing:
        raise PlanInspectionError(f"selected PairBlocks are absent: {missing}")

    selected = set(block_ids)
    targets = tuple(
        sorted(
            (target for target in traceability.targets if target.block_id in selected),
            key=lambda item: (item.block_id, item.target.path, item.target.symbol),
        )
    )
    nodes = _node_index(baseline)
    resolved: list[ResolvedContractTarget] = []
    impacted_edges = {}
    target_ids: set[str] = set()
    for target in targets:
        key = (target.target.path, target.target.symbol)
        baseline_node = nodes.get(key)
        before = None
        if baseline_node is not None:
            source = (baseline_root / baseline_node.path).read_bytes()
            before = extract_declaration_bytes(source, baseline_node.symbol)
            if hashlib.sha256(before).hexdigest() != baseline_node.sha256:
                raise PlanInspectionError(f"baseline digest is stale for {key!r}")
        expected = _payload(plan_root, target)
        change_kind = classify_target_change(
            action=target.action,
            baseline=before,
            expected=expected,
        )
        item = ResolvedContractTarget(
            target=target,
            baseline_node=None if baseline_node is None else baseline_node.node_id,
            baseline_sha256=None if baseline_node is None else baseline_node.sha256,
            expected_sha256=None
            if expected is None
            else hashlib.sha256(expected).hexdigest(),
            change_kind=change_kind,
        )
        resolved.append(item)
        if baseline_node is None:
            continue
        target_ids.add(baseline_node.node_id)
        permitted = IMPACT_EDGE_KINDS_V1[change_kind]
        for edge in baseline.edges:
            if edge.target == baseline_node.node_id and edge.kind in permitted:
                impacted_edges[edge.edge_id] = edge

    edges = tuple(sorted(impacted_edges.values(), key=lambda edge: edge.edge_id))
    return PlanInspection(
        targets=tuple(resolved),
        impact=Impact(
            baseline=baseline.snapshot,
            targets=tuple(sorted(target_ids)),
            affected=tuple(sorted({edge.source for edge in edges})),
            edges=tuple(edge.edge_id for edge in edges),
        ),
    )
```

### Plan reconstruction

<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/_contract_traceability.py:compile_contract_plan -->

```python contract-target
def compile_contract_plan(
    root: Path,
    contracts: tuple[Path, ...],
) -> tuple[tuple[PairBlock, ...], tuple[ContractTarget, ...]]:
    """Compile the PairBlocks and ContractTargets declared by exact contracts."""
    return _parse_pair_blocks(root, contracts), _parse_contract_targets(root, contracts)
```

### Plan checking and acceptance

<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/check.py:SystemImpactCheckError -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/check.py:check_plan -->
<!-- contract-target: requirements=SIG-03 block=P0-SIG-04 action=add target=src/viper/system_impact/check.py:accept -->

```python contract-target
class SystemImpactCheckError(ValueError):
    """Report malformed check inputs or a failed acceptance binding."""

def check_plan(
    *,
    root: Path,
    baseline_root: Path,
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
    baseline: SourceGraph,
    realized: SourceGraph,
    gate_timeout_seconds: float = 900.0,
) -> PlanCheck:
    """Check selected PairBlocks against independently observed source graphs."""
    root = root.resolve()
    baseline_root = baseline_root.resolve()
    if gate_timeout_seconds <= 0:
        raise SystemImpactCheckError("gate timeout must be greater than zero")

    blocks, targets = _selected_records(traceability, block_ids)
    baseline_nodes = _node_index(baseline)
    realized_nodes = _node_index(realized)
    inspection = inspect_plan(
        plan_root=root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=tuple(block.block_id for block in blocks),
        baseline=baseline,
    )
    target_checks = _target_checks(
        root=root,
        resolved_targets=inspection.targets,
        realized_nodes=realized_nodes,
    )
    unexpected = _unexpected_changes(
        baseline_root=baseline_root,
        realized_root=root,
        baseline_nodes=baseline_nodes,
        realized_nodes=realized_nodes,
        targets=targets,
    )
    baseline_dependencies, unsatisfied_dependencies = _dependency_results(
        root=root,
        traceability=traceability,
        blocks=blocks,
        selected={block.block_id for block in blocks},
        baseline_nodes=baseline_nodes,
    )
    plan_sha256 = _plan_sha256(
        blocks,
        targets,
        _asset_manifest_sha256(root=root, blocks=blocks),
    )
    contracts = tuple(sorted({item.declaration.path for item in (*blocks, *targets)}))
    gates = tuple(
        _run_gate(
            root=root,
            block=block,
            timeout_seconds=gate_timeout_seconds,
        )
        for block in blocks
    )
    receipt_valid = _receipt_pair_is_valid(baseline, realized)
    try:
        plan_valid = (
            _current_plan_sha256(
                root=root,
                contracts=contracts,
                block_ids=tuple(block.block_id for block in blocks),
            )
            == plan_sha256
        )
    except SystemImpactCheckError:
        plan_valid = False
    source_valid = (
        source_digest(baseline_root) == baseline.snapshot.source_sha256
        and source_digest(root) == realized.snapshot.source_sha256
    )
    passed = (
        receipt_valid
        and plan_valid
        and source_valid
        and all(target.state == "passed" for target in target_checks)
        and not unexpected
        and not unsatisfied_dependencies
        and all(gate.exit_code == 0 for gate in gates)
    )
    return PlanCheck(
        baseline=baseline.snapshot,
        realized=realized.snapshot,
        blocks=tuple(block.block_id for block in blocks),
        contracts=contracts,
        baseline_dependencies=baseline_dependencies,
        unsatisfied_dependencies=unsatisfied_dependencies,
        plan_sha256=plan_sha256,
        impact=inspection.impact,
        targets=target_checks,
        unexpected=unexpected,
        gates=gates,
        receipts_valid=receipt_valid,
        plan_valid=plan_valid,
        source_valid=source_valid,
        passed=passed,
    )

def accept(
    *,
    root: Path,
    check: PlanCheck,
    revision: CommitId,
) -> Acceptance:
    """Bind one passing check to identical committed source and plan bytes."""
    root = root.resolve()
    check_is_passing = (
        check.passed
        and check.receipts_valid
        and check.plan_valid
        and check.source_valid
        and all(target.state == "passed" for target in check.targets)
        and not check.unexpected
        and not check.unsatisfied_dependencies
        and all(gate.exit_code == 0 for gate in check.gates)
        and tuple(sorted(gate.block_id for gate in check.gates)) == check.blocks
    )
    if not check_is_passing:
        raise SystemImpactCheckError("cannot accept a failed PlanCheck")
    if check.realized.revision is not None and check.realized.revision != revision:
        raise SystemImpactCheckError(
            "accepted commit differs from the committed realized snapshot"
        )
    resolved_revision = (
        _git(
            root,
            ("rev-parse", "--verify", f"{revision}^{{commit}}"),
        )
        .decode("ascii")
        .strip()
    )
    if resolved_revision != revision:
        raise SystemImpactCheckError("accept requires one exact full commit ID")
    ancestry = subprocess.run(
        (
            "git",
            "merge-base",
            "--is-ancestor",
            check.baseline.revision or check.baseline.base_revision,
            revision,
        ),
        cwd=root,
        check=False,
        capture_output=True,
        shell=False,
    )
    if ancestry.returncode != 0:
        raise SystemImpactCheckError(
            "accepted commit does not descend from the checked baseline"
        )

    source_sha256 = _snapshot_source_sha256(root, revision)
    if source_sha256 != check.realized.source_sha256:
        raise SystemImpactCheckError(
            "accepted commit source differs from the checked candidate"
        )
    plan_sha256, committed_targets = _committed_plan(
        root=root,
        revision=revision,
        contracts=check.contracts,
        block_ids=check.blocks,
    )
    if plan_sha256 != check.plan_sha256:
        raise SystemImpactCheckError(
            "accepted commit plan differs from the checked PairBlocks"
        )
    checked_targets = tuple(
        sorted(
            (
                target.resolved.target.block_id,
                target.resolved.target.target.path,
                target.resolved.target.target.symbol,
            )
            for target in check.targets
        )
    )
    expected_targets = tuple(
        sorted(
            (target.block_id, target.target.path, target.target.symbol)
            for target in committed_targets
        )
    )
    if checked_targets != expected_targets:
        raise SystemImpactCheckError(
            "accepted PlanCheck does not cover every committed ContractTarget"
        )

    check_sha256 = _sha256(_canonical_json(check.model_dump(mode="json")))
    return Acceptance(check=check_sha256, revision=revision)
```

### Historical replay tests

<!-- contract-target: requirements=SIG-04 block=P0-SIG-05 action=add target=tests/test_system_impact.py:test_committed_manifest_rename -->
<!-- contract-target: requirements=SIG-04 block=P0-SIG-05 action=add target=tests/test_system_impact.py:test_completed_viper_pair_block -->

```python contract-target
def test_committed_manifest_rename(tmp_path: Path) -> None:
    """Replay the global skills manifest-field migration fixture."""
    _assert_historical_fixture(
        "agents_manifest_migration",
        "6eb74b8e8bba2ddf2f2f9fa3822e11c5d9a3d06b",
        "18083057eeb92c755ead031122afd48e8a77d653",
        tmp_path,
    )

def test_completed_viper_pair_block(tmp_path: Path) -> None:
    """Replay the accepted VIPER P0-PROOF-05 fixture."""
    _assert_historical_fixture(
        "viper_p0_proof_05",
        "1e33d9a7bd12327702397c0e7aaf96e490dec46e",
        "5c78ff5d33bdfa9c7b92b7bb9ff5c0fefdc7eef8",
        tmp_path,
    )
```

### CodeQL write-edge integration test

<!-- contract-target: requirements=SIG-06 block=P0-SIG-06 action=update target=tests/test_system_impact.py:test_checked_in_codeql_pack_analyzes_tiny_repository -->

```python contract-target
@pytest.mark.integration
def test_checked_in_codeql_pack_analyzes_tiny_repository(tmp_path: Path) -> None:
    """Compile the checked-in QL pack and verify exact dependency edges."""
    if os.environ.get("VIPER_RUN_CODEQL_TESTS") != "1":
        pytest.skip("set VIPER_RUN_CODEQL_TESTS=1 to run the real CodeQL check")

    configured = os.environ.get("VIPER_CODEQL")
    executable_value = configured or shutil.which("codeql")
    assert executable_value is not None, "CodeQL is unavailable"
    executable = Path(executable_value).resolve()

    checked_in_pack = Path(__file__).parents[1] / "tools/codeql/viper-python-impact"
    query_pack = tmp_path / "query-pack"
    shutil.copytree(checked_in_pack, query_pack)

    installed = run_subprocess(
        (str(executable), "pack", "install", str(query_pack)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    version = run_subprocess(
        (str(executable), "version", "--format=json"),
        check=True,
        capture_output=True,
        text=True,
    )

    root = tmp_path / "source"
    _sig02_source_fixture(root)
    (root / "src/writes.py").write_text(
        "state = 0\n"
        "\n"
        "def read_state() -> int:\n"
        "    return state\n"
        "\n"
        "def update_state(value: int) -> None:\n"
        "    global state\n"
        "    state = value\n"
        "\n"
        "class Counter:\n"
        "    value = 0\n"
        "\n"
        "    def update(self, value: int) -> None:\n"
        "        self.value = value\n",
        encoding="utf-8",
    )
    (root / "src/consumer.py").write_text(
        "from writes import state\n",
        encoding="utf-8",
    )

    snapshot = SourceSnapshot(
        base_revision=_REVISION,
        source_sha256=source_digest(root),
        revision=None,
    )
    identity = CodeQLIdentity(
        version=json.loads(version.stdout)["version"],
        platform=sys.platform,
        executable_sha256=_sha256(executable.read_bytes()),
        pack="viper/python-impact@1.1.0",
        pack_sha256=_tree_digest(query_pack),
    )

    graph = analyze_source(
        root,
        snapshot=snapshot,
        identity=identity,
        codeql_executable=executable,
        query_pack=query_pack,
        cache_root=tmp_path / "cache",
        artifact_root=tmp_path / "artifacts",
    )

    assert {node.symbol for node in graph.nodes} >= {
        "dependency",
        "dependent",
        "state",
        "update_state",
        "Counter",
        "Counter.value",
        "Counter.update",
    }
    assert any(
        edge.source == "src/example.py:dependent"
        and edge.target == "src/example.py:dependency"
        and edge.kind == "calls"
        for edge in graph.edges
    )

    write_edges = {
        (edge.source, edge.target): (edge.path, edge.line)
        for edge in graph.edges
        if edge.kind == "writes"
    }
    assert write_edges[("src/writes.py:update_state", "src/writes.py:state")] == (
        "src/writes.py",
        8,
    )
    assert write_edges[
        ("src/writes.py:Counter.update", "src/writes.py:Counter.value")
    ] == ("src/writes.py", 14)

    assert any(
        edge.source == "src/writes.py:read_state"
        and edge.target == "src/writes.py:state"
        and edge.kind == "reads"
        for edge in graph.edges
    )
    assert any(
        edge.source == "src/consumer.py:state"
        and edge.target == "src/writes.py:state"
        and edge.kind == "imports"
        for edge in graph.edges
    )
```

### One-hop pre-pairing check

**File: `src/viper/system_impact/models.py`**

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/models.py:OneHop -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/models.py:PlanCheck -->

```python contract-target
class OneHop(ProtocolModel):
    """Store the CodeQL edge delta around the selected targets."""

    targets: tuple[NodeId, ...] = Field(
        description="Selected target nodes present in either graph."
    )
    neighbors: tuple[NodeId, ...] = Field(
        description="Direct dependents found before or after the planned change."
    )
    changed: tuple[NodeId, ...] = Field(
        description="Direct dependents whose declaration state changed."
    )
    before: tuple[SHA256, ...] = Field(
        description="Policy-selected incoming edge IDs in the baseline graph."
    )
    after: tuple[SHA256, ...] = Field(
        description="Incoming edge IDs derived from the materialized PairBlocks."
    )
    removed: tuple[SHA256, ...] = Field(
        description="Baseline edge IDs absent after materialization."
    )
    added: tuple[SHA256, ...] = Field(
        description="Materialized edge IDs absent from the baseline."
    )

    @model_validator(mode="after")
    def validate_delta(self) -> OneHop:
        """Require added and removed edges to equal the graph difference."""
        before = set(self.before)
        after = set(self.after)
        if self.removed != tuple(sorted(before - after)):
            raise ValueError("OneHop.removed differs from before - after")
        if self.added != tuple(sorted(after - before)):
            raise ValueError("OneHop.added differs from after - before")
        return self


class PlanCheck(ProtocolModel):
    """Record the complete result of checking selected PairBlocks."""

    schema_version: Literal[3] = Field(
        default=3,
        description="Plan-check record format version.",
    )
    baseline: SourceSnapshot = Field(
        description="Source state inspected before the selected PairBlocks ran."
    )
    realized: SourceSnapshot = Field(
        description=(
            "Candidate source state inspected after the selected PairBlocks ran."
        )
    )
    blocks: tuple[PairBlockId, ...] = Field(
        min_length=1,
        description="Selected PairBlocks covered by this check.",
    )
    contracts: tuple[RepoRelPath, ...] = Field(
        min_length=1,
        description="Contract files needed to reconstruct the selected plan.",
    )
    baseline_dependencies: tuple[PairBlockId, ...] = Field(
        default=(),
        description=(
            "Omitted dependencies whose target state already exists in the baseline."
        ),
    )
    unsatisfied_dependencies: tuple[PairBlockId, ...] = Field(
        default=(),
        description=(
            "Omitted dependencies whose target state is absent from the baseline."
        ),
    )
    plan_sha256: SHA256 = Field(
        description=(
            "Digest of the selected PairBlock and ContractTarget records plus "
            "the selected asset paths and bytes."
        )
    )
    impact: Impact = Field(
        description="Direct advisory dependency report for the selected targets."
    )
    one_hop: OneHop = Field(
        description="CodeQL edge delta derived from the baseline and planned source."
    )
    targets: tuple[TargetCheck, ...] = Field(
        description="One realized result for every selected ContractTarget."
    )
    unexpected: tuple[RepoSymbolRef, ...] = Field(
        description="Changed declarations that no selected ContractTarget owns."
    )
    gates: tuple[GateCheck, ...] = Field(
        description="One gate result for every selected PairBlock."
    )
    receipts_valid: bool = Field(
        description=(
            "Whether both graphs have successful receipts with one analyzer identity."
        )
    )
    plan_valid: bool = Field(
        description=(
            "Whether the post-gate contract files retain the checked plan digest."
        )
    )
    source_valid: bool = Field(
        description="Whether both source roots retain their checked source digests."
    )
    passed: bool = Field(
        description=(
            "Whether every target, dependency, gate, source, plan, and receipt check "
            "passed."
        )
    )
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/models.py:__all__ -->

```python contract-target
__all__ = [
    "Acceptance",
    "CodeQLIdentity",
    "CodeQLReceipt",
    "ChangeKind",
    "CheckState",
    "CommitId",
    "EdgeKind",
    "GateCheck",
    "Impact",
    "NodeId",
    "OneHop",
    "PlanCheck",
    "PlanInspection",
    "ResolvedContractTarget",
    "SourceEdge",
    "SourceGraph",
    "SourceNode",
    "SourceNodeKind",
    "SourceSnapshot",
    "TargetCheck",
]
```

**File: `src/viper/system_impact/check.py`**

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:ast -->
```python contract-target
import ast
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:Acceptance -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:CommitId -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:GateCheck -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:IMPACT_EDGE_KINDS_V1 -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:OneHop -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:PlanCheck -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:ResolvedContractTarget -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:SourceGraph -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:SourceNode -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:TargetCheck -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:inspect_plan -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:extract_declaration_bytes -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:import_binding -->

```python contract-target
from .models import (
    Acceptance,
    CommitId,
    GateCheck,
    OneHop,
    PlanCheck,
    ResolvedContractTarget,
    SourceGraph,
    SourceNode,
    TargetCheck,
)
from .plan import IMPACT_EDGE_KINDS_V1, inspect_plan
from .._system_impact.source import extract_declaration_bytes, import_binding
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:_target_is_satisfied -->
```python contract-target
def _target_is_satisfied(
    *,
    root: Path,
    target: ContractTarget,
    nodes: dict[tuple[str, str], SourceNode],
) -> bool:
    node = nodes.get(_target_key(target))
    if target.action == "remove":
        return node is None
    expected = _declaration_payload(root, target)
    assert expected is not None
    if node is not None and node.kind == "import":
        realized = (root / target.target.path).read_bytes()
        return import_binding(expected, target.target.symbol) == import_binding(
            realized,
            target.target.symbol,
        )
    return node is not None and node.sha256 == _sha256(expected)
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:_target_checks -->
```python contract-target
def _target_checks(
    *,
    root: Path,
    resolved_targets: tuple[ResolvedContractTarget, ...],
    realized_nodes: dict[tuple[str, str], SourceNode],
) -> tuple[TargetCheck, ...]:
    checks: list[TargetCheck] = []
    for resolved in resolved_targets:
        target = resolved.target
        after = realized_nodes.get(_target_key(target))
        if target.action == "remove":
            passed = after is None
            message = (
                "target declaration is absent"
                if passed
                else "removed target declaration remains present"
            )
        else:
            expected = _declaration_payload(root, target)
            if after is not None and after.kind == "import" and expected is not None:
                realized = (root / target.target.path).read_bytes()
                passed = import_binding(
                    expected,
                    target.target.symbol,
                ) == import_binding(realized, target.target.symbol)
            else:
                passed = after is not None and after.sha256 == resolved.expected_sha256
            if after is None:
                message = "required target declaration is absent"
            elif passed:
                message = (
                    "target import matches the authored binding"
                    if after.kind == "import"
                    else "target declaration matches the authored bytes"
                )
            else:
                message = "target declaration differs from the authored bytes"
        checks.append(
            TargetCheck(
                resolved=resolved,
                after_sha256=None if after is None else after.sha256,
                state="passed" if passed else "failed",
                message=message,
            )
        )
    return tuple(checks)
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:_unexpected_changes -->
```python contract-target
def _unexpected_changes(
    *,
    baseline_root: Path,
    realized_root: Path,
    baseline_nodes: dict[tuple[str, str], SourceNode],
    realized_nodes: dict[tuple[str, str], SourceNode],
    targets: tuple[ContractTarget, ...],
) -> tuple[RepoSymbolRef, ...]:
    changed: set[tuple[str, str]] = set()
    for key in baseline_nodes.keys() | realized_nodes.keys():
        before = baseline_nodes.get(key)
        after = realized_nodes.get(key)
        if before is None or after is None:
            changed.add(key)
            continue
        if before.sha256 == after.sha256:
            continue
        if before.kind == after.kind == "import":
            baseline_source = (baseline_root / before.path).read_bytes()
            realized_source = (realized_root / after.path).read_bytes()
            if import_binding(baseline_source, before.symbol) == import_binding(
                realized_source,
                after.symbol,
            ):
                continue
        try:
            baseline_declaration = extract_declaration_bytes(
                (baseline_root / before.path).read_bytes(),
                before.symbol,
            )
            realized_declaration = extract_declaration_bytes(
                (realized_root / after.path).read_bytes(),
                after.symbol,
            )
            baseline_tree = ast.parse(baseline_declaration, type_comments=True)
            realized_tree = ast.parse(realized_declaration, type_comments=True)
            if ast.dump(baseline_tree, include_attributes=False) == ast.dump(
                realized_tree,
                include_attributes=False,
            ):
                continue
        except (OSError, SyntaxError, SourceDeclarationError):
            pass
        changed.add(key)
    all_nodes = {**baseline_nodes, **realized_nodes}
    planned: set[tuple[str, str]] = set()
    import_spans: set[tuple[str, int, int, int, int]] = set()
    for target in targets:
        target_key = _target_key(target)
        planned.add(target_key)
        target_node = all_nodes.get(target_key)
        for node in (baseline_nodes.get(target_key), realized_nodes.get(target_key)):
            if node is not None and node.kind == "import":
                import_spans.add(
                    (
                        node.path,
                        node.start_line,
                        node.start_col,
                        node.end_line,
                        node.end_col,
                    )
                )
        for key, node in all_nodes.items():
            if key[0] != target_key[0]:
                continue
            target_contains_node = (
                target_node is not None
                and target_node.kind == "class"
                and node.symbol.startswith(f"{target_key[1]}.")
            )
            node_contains_target = node.kind == "class" and target_key[1].startswith(
                f"{node.symbol}."
            )
            if target_contains_node or node_contains_target:
                planned.add(key)
    for key, node in all_nodes.items():
        span = (
            node.path,
            node.start_line,
            node.start_col,
            node.end_line,
            node.end_col,
        )
        if node.kind == "import" and span in import_spans:
            # One import target owns the whole statement; Ruff may regroup its names.
            planned.add(key)
    return tuple(
        RepoSymbolRef(path=path, symbol=symbol)
        for path, symbol in sorted(changed - planned)
    )
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=src/viper/system_impact/check.py:_one_hop -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=src/viper/system_impact/check.py:check_plan -->

```python contract-target
def _one_hop(
    *,
    targets: tuple[ResolvedContractTarget, ...],
    baseline: SourceGraph,
    realized: SourceGraph,
) -> OneHop:
    """Record direct dependents selected by the existing impact policy."""
    baseline_nodes = {node.node_id: node for node in baseline.nodes}
    realized_nodes = {node.node_id: node for node in realized.nodes}
    indexes = (_node_index(baseline), _node_index(realized))
    node_kinds: dict[str, set[str]] = {}
    for target in targets:
        key = _target_key(target.target)
        kinds = IMPACT_EDGE_KINDS_V1[target.change_kind]

        # Adds exist only afterward and removals only beforehand, so each target
        # must be resolved in both graphs.
        for index in indexes:
            node = index.get(key)
            if node is not None:
                node_kinds.setdefault(node.node_id, set()).update(kinds)

    before = tuple(
        sorted(
            edge.edge_id
            for edge in baseline.edges
            if edge.target in node_kinds and edge.kind in node_kinds[edge.target]
        )
    )
    after = tuple(
        sorted(
            edge.edge_id
            for edge in realized.edges
            if edge.target in node_kinds and edge.kind in node_kinds[edge.target]
        )
    )
    before_ids = set(before)
    after_ids = set(after)
    selected_ids = before_ids | after_ids
    selected_edges = tuple(
        edge
        for edge in (*baseline.edges, *realized.edges)
        if edge.edge_id in selected_ids
    )
    neighbors = tuple(sorted({edge.source for edge in selected_edges}))
    changed = tuple(
        node_id
        for node_id in neighbors
        if baseline_nodes.get(node_id) is None
        or realized_nodes.get(node_id) is None
        or baseline_nodes[node_id].sha256 != realized_nodes[node_id].sha256
    )
    return OneHop(
        targets=tuple(sorted(node_kinds)),
        neighbors=neighbors,
        changed=changed,
        before=before,
        after=after,
        removed=tuple(sorted(before_ids - after_ids)),
        added=tuple(sorted(after_ids - before_ids)),
    )


def check_plan(
    *,
    root: Path,
    baseline_root: Path,
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
    baseline: SourceGraph,
    realized: SourceGraph,
    gate_timeout_seconds: float = 900.0,
) -> PlanCheck:
    """Check selected PairBlocks against independently observed source graphs."""
    root = root.resolve()
    baseline_root = baseline_root.resolve()
    if gate_timeout_seconds <= 0:
        raise SystemImpactCheckError("gate timeout must be greater than zero")

    blocks, targets = _selected_records(traceability, block_ids)
    baseline_nodes = _node_index(baseline)
    realized_nodes = _node_index(realized)
    inspection = inspect_plan(
        plan_root=root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=tuple(block.block_id for block in blocks),
        baseline=baseline,
    )
    target_checks = _target_checks(
        root=root,
        resolved_targets=inspection.targets,
        realized_nodes=realized_nodes,
    )
    one_hop = _one_hop(
        targets=inspection.targets,
        baseline=baseline,
        realized=realized,
    )
    unexpected = _unexpected_changes(
        baseline_root=baseline_root,
        realized_root=root,
        baseline_nodes=baseline_nodes,
        realized_nodes=realized_nodes,
        targets=targets,
    )
    baseline_dependencies, unsatisfied_dependencies = _dependency_results(
        root=root,
        traceability=traceability,
        blocks=blocks,
        selected={block.block_id for block in blocks},
        baseline_nodes=baseline_nodes,
    )
    plan_sha256 = _plan_sha256(
        blocks,
        targets,
        _asset_manifest_sha256(root=root, blocks=blocks),
    )
    contracts = tuple(sorted({item.declaration.path for item in (*blocks, *targets)}))
    gates = tuple(
        _run_gate(
            root=root,
            block=block,
            timeout_seconds=gate_timeout_seconds,
        )
        for block in blocks
    )
    receipt_valid = _receipt_pair_is_valid(baseline, realized)
    try:
        plan_valid = (
            _current_plan_sha256(
                root=root,
                contracts=contracts,
                block_ids=tuple(block.block_id for block in blocks),
            )
            == plan_sha256
        )
    except SystemImpactCheckError:
        plan_valid = False
    source_valid = (
        source_digest(baseline_root) == baseline.snapshot.source_sha256
        and source_digest(root) == realized.snapshot.source_sha256
    )
    passed = (
        receipt_valid
        and plan_valid
        and source_valid
        and all(target.state == "passed" for target in target_checks)
        and not unexpected
        and not unsatisfied_dependencies
        and all(gate.exit_code == 0 for gate in gates)
    )
    return PlanCheck(
        baseline=baseline.snapshot,
        realized=realized.snapshot,
        blocks=tuple(block.block_id for block in blocks),
        contracts=contracts,
        baseline_dependencies=baseline_dependencies,
        unsatisfied_dependencies=unsatisfied_dependencies,
        plan_sha256=plan_sha256,
        impact=inspection.impact,
        one_hop=one_hop,
        targets=target_checks,
        unexpected=unexpected,
        gates=gates,
        receipts_valid=receipt_valid,
        plan_valid=plan_valid,
        source_valid=source_valid,
        passed=passed,
    )
```

**File: `tests/test_system_impact.py`**

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=tests/test_system_impact.py:import_binding -->
```python contract-target
from viper._system_impact.source import import_binding
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=update target=tests/test_system_impact.py:test_class_target_owns_nested_declaration_changes -->
```python contract-target
def test_class_target_owns_nested_declaration_changes(tmp_path: Path) -> None:
    """Treat class-container and nested declaration digests as one planned edit."""
    path = "src/example.py"
    baseline_class = _node(
        path=path,
        symbol="Example",
        kind="class",
        declaration=b"class Example:\n    value = 1",
    )
    baseline_field = _node(
        path=path,
        symbol="Example.value",
        kind="assignment",
        declaration=b"value = 1",
    )
    realized_class = baseline_class.model_copy(
        update={"sha256": _sha256(b"class Example:\n    value = 2")}
    )
    realized_field = baseline_field.model_copy(update={"sha256": _sha256(b"value = 2")})
    target = ContractTarget(
        requirements=(_REQUIREMENT_ID,),
        block_id=_BLOCK_ID,
        action="update",
        target=RepoSymbolRef(path=path, symbol="Example"),
        declaration=_declaration_ref(),
    )

    unexpected = _unexpected_changes(
        baseline_root=tmp_path,
        realized_root=tmp_path,
        baseline_nodes={
            (path, "Example"): baseline_class,
            (path, "Example.value"): baseline_field,
        },
        realized_nodes={
            (path, "Example"): realized_class,
            (path, "Example.value"): realized_field,
        },
        targets=(target,),
    )

    assert unexpected == ()
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=tests/test_system_impact.py:test_import_target_owns_names_in_the_same_statement -->
```python contract-target
def test_import_target_owns_names_in_the_same_statement(tmp_path: Path) -> None:
    """Compare one import by binding when Ruff regroups its statement."""
    path = "src/example.py"
    baseline_name = _node(
        path=path,
        symbol="Existing",
        kind="import",
        declaration=b"from .models import Existing",
    )
    realized_name = _node(
        path=path,
        symbol="Existing",
        kind="import",
        declaration=b"from .models import Existing, New",
    )
    realized_new = _node(
        path=path,
        symbol="New",
        kind="import",
        declaration=b"from .models import Existing, New",
    )
    target = ContractTarget(
        requirements=(_REQUIREMENT_ID,),
        block_id=_BLOCK_ID,
        action="add",
        target=RepoSymbolRef(path=path, symbol="New"),
        declaration=_declaration_ref(),
    )
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    baseline_path = baseline_root / path
    realized_path = realized_root / path
    baseline_path.parent.mkdir(parents=True)
    realized_path.parent.mkdir(parents=True)
    baseline_path.write_text("from .models import Existing\n")
    realized_path.write_text("from .models import Existing, New\n")

    unexpected = _unexpected_changes(
        baseline_root=baseline_root,
        realized_root=realized_root,
        baseline_nodes={(path, "Existing"): baseline_name},
        realized_nodes={
            (path, "Existing"): realized_name,
            (path, "New"): realized_new,
        },
        targets=(target,),
    )

    assert import_binding(b"from .models import New\n", "New") == import_binding(
        b"from .models import Existing, New\n",
        "New",
    )
    assert (
        extract_declaration_bytes(
            b"import urllib.parse\n",
            "urllib.parse",
        )
        == b"import urllib.parse"
    )
    assert unexpected == ()
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=tests/test_system_impact.py:test_formatting_only_change_is_not_unexpected -->
```python contract-target
def test_formatting_only_change_is_not_unexpected(tmp_path: Path) -> None:
    """Ignore Ruff layout changes that preserve the same Python tree."""
    path = "src/example.py"
    before = b"def value():\n    return (\n        1\n    )\n"
    after = b"def value():\n    return 1\n"
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    baseline_path = baseline_root / path
    realized_path = realized_root / path
    baseline_path.parent.mkdir(parents=True)
    realized_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(before)
    realized_path.write_bytes(after)

    unexpected = _unexpected_changes(
        baseline_root=baseline_root,
        realized_root=realized_root,
        baseline_nodes={
            (path, "value"): _node(
                path=path,
                symbol="value",
                kind="function",
                declaration=before.rstrip(),
            )
        },
        realized_nodes={
            (path, "value"): _node(
                path=path,
                symbol="value",
                kind="function",
                declaration=after.rstrip(),
            )
        },
        targets=(),
    )

    assert unexpected == ()
```

<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=tests/test_system_impact.py:test_one_hop_records_baseline_and_candidate_neighbors -->
<!-- contract-target: requirements=SIG-07 block=P0-SIG-07 action=add target=tests/test_system_impact.py:test_pre_pairing_pyright_rejects_stale_caller -->

```python contract-target
def test_one_hop_records_baseline_and_candidate_neighbors(tmp_path: Path) -> None:
    """Record direct dependents found before and after a selected update."""
    baseline_root = tmp_path / "baseline"
    realized_root = tmp_path / "realized"
    _write_check_source(baseline_root, target_increment=0)
    _write_check_source(realized_root, target_increment=1)
    traceability = _write_check_contract(
        realized_root,
        gate=f"{sys.executable} -c pass",
    )
    baseline_target = _node(
        path="src/example.py",
        symbol="target",
        kind="function",
        declaration=b"def target(value: int) -> int:\n    return value + 0",
    )
    realized_target = _node(
        path="src/example.py",
        symbol="target",
        kind="function",
        declaration=b"def target(value: int) -> int:\n    return value + 1",
    )
    caller = _node(path="src/caller.py", symbol="caller", kind="function")
    adapter = _node(path="src/adapter.py", symbol="adapter", kind="function")
    before = _edge(index=21, source=caller, target=baseline_target, kind="calls")
    after = _edge(index=22, source=adapter, target=realized_target, kind="calls")

    result = check_plan(
        root=realized_root,
        baseline_root=baseline_root,
        traceability=traceability,
        block_ids=("P0-SIG-04",),
        baseline=_source_graph(
            nodes=(baseline_target, caller),
            edges=(before,),
            source_sha256=source_digest(baseline_root),
        ),
        realized=_source_graph(
            nodes=(realized_target, adapter),
            edges=(after,),
            source_sha256=source_digest(realized_root),
            revision=None,
        ),
    )

    assert result.one_hop.targets == (baseline_target.node_id,)
    assert result.one_hop.neighbors == (adapter.node_id, caller.node_id)
    assert result.one_hop.changed == (adapter.node_id, caller.node_id)
    assert result.one_hop.before == (before.edge_id,)
    assert result.one_hop.after == (after.edge_id,)
    assert result.one_hop.removed == (before.edge_id,)
    assert result.one_hop.added == (after.edge_id,)


def test_pre_pairing_pyright_rejects_stale_caller(tmp_path: Path) -> None:
    """Reject a caller that omits a new required parameter."""
    root = tmp_path / "candidate"
    source = root / "src/example.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def save(path: str, overwrite: bool) -> None:\n"
        "    pass\n"
        "\n"
        "def publish() -> None:\n"
        "    save('artifact')\n",
        encoding="utf-8",
    )
    (root / "pyrightconfig.json").write_text(
        json.dumps({"include": ["src"], "typeCheckingMode": "standard"}),
        encoding="utf-8",
    )

    checked = run_subprocess(
        (
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(root / "pyrightconfig.json"),
            "--pythonpath",
            sys.executable,
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert checked.returncode != 0
    assert "overwrite" in checked.stdout
```


## Appendix A. PairBlock scheduling

Cross-contract scheduling now has its own governing contract:
[PairBlock scheduling](pair-block-scheduling.md). That contract owns planned
source materialization, dependency projection, write-conflict ordering, SCC
condensation, deterministic execution waves, and their focused acceptance
tests.

## Appendix B. Deferred plan resolution

This non-normative extension may be reconsidered after the one-hop preflight
has been used on real contracts. `add`, `update`, and `remove` bound the action
type; a finite rewrite library or bounded LLM proposal step must supply the
candidate payloads. Intersecting dependency paths are candidate resolution
points, not automatically safe stopping points.

```text
resolve(seed, baseline, budget):
    frontier = obligations(seed, Analyze(baseline))
    candidates = deterministic_rewrites(frontier)
    if candidates is empty:
        candidates = bounded_llm_proposals(frontier, budget)

    valid = []
    for candidate in deduplicate(candidates):
        source = materialize(baseline, candidate)
        graph = Analyze(source)
        if pyright(source) == 0 and gates(source) == 0:
            valid.append((candidate, outward_obligations(graph)))

    return min(valid, key=(unresolved_obligations, changed_nodes, changed_edges))
```

An implementation must define the finite candidate source, budget, cost order,
and failure result before this procedure can become a verifier rule or
PairBlock.

## Sources

- GitHub, [About CodeQL](https://codeql.github.com/docs/codeql-overview/about-codeql/),
  defines CodeQL databases as relational representations of source code that
  queries can inspect.
- GitHub, [CodeQL library for Python](https://codeql.github.com/codeql-standard-libraries/python/),
  documents Python declarations, calls, imports, and data-flow relations.
- Python Software Foundation,
  [Abstract Syntax Trees](https://docs.python.org/3.14/library/ast.html#ast.AST),
  defines AST line positions and UTF-8 byte offsets. VIPER widens decorated
  function and class spans to the first decorator before slicing source bytes.
- Git,
  [`merge-base --is-ancestor`](https://git-scm.com/docs/git-merge-base#Documentation/git-merge-base.txt---is-ancestor),
  provides the ancestry check used by `accept()` to require the candidate
  commit to descend from the checked baseline.
- Ramakrishna Bairi et al.,
  [CodePlan: Repository-level Coding using LLMs and Planning](https://arxiv.org/abs/2309.12499),
  provides the change-classification and dependency-relation selection pattern.
  VIPER uses a deterministic one-hop advisory policy. Adaptive plan generation
  remains outside Master Phase 0.
- Sergey Mechtaev, Jooyong Yi, and Abhik Roychoudhury,
  [DirectFix: Looking for Simple Program Repairs](https://mechtaev.com/files/icse15.pdf),
  supports choosing a valid repair that preserves as much of the original
  program as possible.
- Yuan Yuan and Wolfgang Banzhaf,
  [ARJA: Automated Repair of Java Programs via Multi-Objective Genetic Programming](https://arxiv.org/abs/1712.07804),
  separates edit locations, operation types, and candidate code while reducing
  the search space and preferring smaller test-adequate patches.
- Susmit Jha and Sanjit Seshia,
  [Are There Good Mistakes? A Theoretical Analysis of CEGIS](https://doi.org/10.4204/EPTCS.157.10),
  establishes why a finite candidate space matters for termination.
- Gregg Rothermel and Mary Jean Harrold,
  [A Safe, Efficient Regression Test Selection Technique](https://doi.org/10.1145/248233.248262),
  provides the dependency-based regression-selection framing. VIPER uses the
  typed direct-impact set as review evidence. Safe test selection under that
  paper's proof conditions remains outside this contract.
- Robert Tarjan,
  [Depth-First Search and Linear Graph Algorithms](https://doi.org/10.1137/0201010),
  gives the linear-time strongly connected component algorithm used by the
  proposed condensation step.
- George Karypis and Vipin Kumar,
  [Multilevel k-way Partitioning Scheme for Irregular Graphs](https://www.maths.tcd.ie/~eoin/index/karypis.kumar_metis96.html),
  supplies the workload-balancing and edge-cut foundation for the proposed
  partitioning objective.
- Grzegorz Malewicz et al.,
  [Pregel: A System for Large-Scale Graph Processing](https://research.google/pubs/pregel-a-system-for-large-scale-graph-processing/),
  provides a distributed graph-execution precedent based on partitioned graph
  state and coordinated iterations. VIPER requires separate evidence for
  multi-agent coding correctness.
- Xu Yang et al.,
  [When Parallelism Pays Off: Cohesion-Aware Task Partitioning for Multi-Agent Coding](https://arxiv.org/abs/2606.00953),
  models repository-level multi-agent coding as a weighted dependency-graph
  partitioning problem. The 2026 result is a preprint and supplies motivation
  for VIPER's proposed comparison. VIPER must measure its own gains.

## 13. Generated-candidate exclusion

<!-- contract-target: requirements=SIG-01,SIG-05 block=P0-SIG-02 action=add target=tests/test_system_impact.py:test_source_digest_ignores_viper_worktrees -->
```python contract-target
def test_source_digest_ignores_viper_worktrees(tmp_path: Path) -> None:
    """Keep generated plan candidates outside the reusable source identity."""
    source = tmp_path / "src/example.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    expected = source_digest(tmp_path)

    generated = tmp_path / ".viper/checks/candidate/example.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("VALUE = 2\n")

    assert source_digest(tmp_path) == expected
```
