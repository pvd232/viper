# Deterministic system impact graph

VIPER needs a repeatable way to identify which implementation, protocol,
verifier, test, contract, and checklist surfaces a proposed change can affect.
This contract compiles the codebase and specification stack into one typed
directed graph under a fixed execution context. It then condenses dependency
cycles into a DAG and computes the exact graph delta between two source
revisions.

## 1. Status

**Contract status:** draft after change-impact review; owner review pending.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| SIG-01 <!-- contract-requirement: SIG-01 phase=0 test=tests/test_validation_architecture.py --> | Compile canonical typed nodes and edges from Python source, public registries, protocol records, contracts, checklist markers, and tests. |
| SIG-02 <!-- contract-requirement: SIG-02 phase=0 test=tests/test_validation_architecture.py --> | Hold declared external inputs fixed, observe dynamic resolution under each source revision, and fail closed on unresolved dependencies in strict mode. |
| SIG-03 <!-- contract-requirement: SIG-03 phase=0 test=tests/test_inspection.py --> | Condense dependency cycles into a DAG and compute a canonical typed delta plus reverse impact closure. |
| SIG-04 <!-- contract-requirement: SIG-04 phase=0 test=tests/test_documentation.py --> | Require every contract obligation to connect to one implementation owner and one observing test through the compiled graph. |

## 2. Required claim

Given two source revisions and one fixed context manifest, VIPER produces the
same canonical dependency graphs, graph delta, and affected-surface report on
every conforming execution.

Let `C0` and `C1` identify the baseline and candidate source revisions. Let `X`
identify the fixed context manifest. The compiler constructs:

```math
G_0 = \operatorname{compile}(C_0 \mid X)
```

```math
G_1 = \operatorname{compile}(C_1 \mid X)
```

The comparator returns:

```math
\Delta G = \operatorname{diff}(G_0, G_1)
```

and the reverse dependency closure of every changed node and edge.

The guarantee is conditional on `X`. It identifies impact under the declared
Python runtime, dependencies, environment variables, fixture files, command
inputs, and external responses.

## 3. Current gap

### Inspected path

The repository has several deterministic checks with separate, hard-coded
views:

```text
tests/test_validation_architecture.py
-> parses Python imports for privacy rules

tests/test_documentation.py
-> parses contract requirements, checklist markers, schemas, links, and examples

inspection.plan_diff()
-> compares frozen plan JSON leaves

inspection.lineage()
-> constructs one verified run graph
```

These checks establish separate local relationships. The system lacks one graph
that connects a changed protocol field to its constructor, runtime consumer,
persisted record, verifier, contract requirement, checklist task, and test.

### Missing connector

The missing path is:

```text
source revision + fixed context
-> canonical typed SystemGraph
-> strongly connected components
-> SystemCondensationDAG
-> graph delta
-> reverse dependency closure
-> affected contracts, checklist tasks, and tests
-> explicit unresolved boundary
```

## 4. Contract models

### Identifiers and kinds

```python
SystemNodeId = Annotated[str, StringConstraints(min_length=1)]
SystemComponentId = SHA256

SystemNodeKind = Literal[
    "module",
    "symbol",
    "public_export",
    "protocol_model",
    "protocol_field",
    "api_operation",
    "cli_command",
    "runtime_operation",
    "persisted_document",
    "verifier_rule",
    "contract",
    "contract_requirement",
    "checklist_task",
    "test",
    "external_input",
    "unresolved_target",
]

SystemEdgeKind = Literal[
    "defines",
    "contains",
    "imports",
    "calls",
    "registers",
    "exports",
    "constructs",
    "reads",
    "writes",
    "serializes",
    "retrieves",
    "verifies",
    "implements",
    "tests",
    "documents",
    "resolves",
    "launches",
]

ResolutionKind = Literal[
    "dynamic_import",
    "decorator_registration",
    "registry_entry",
    "reflection_target",
    "subprocess_entrypoint",
]
```

### Fixed context

`SystemContextManifest` contains external values held equal across the two
compilations. Every collection uses canonical lexical ordering.

```python
class ContextPackage(ProtocolModel):
    name: NonEmptyStr
    version: NonEmptyStr


class ContextVariable(ProtocolModel):
    name: NonEmptyStr
    value: str


class ContextFile(ProtocolModel):
    path: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class ContextCommand(ProtocolModel):
    command_id: NonEmptyStr
    executable: NonEmptyStr
    argv: tuple[str, ...]
    stdin_sha256: SHA256 | None = None
    response: ContextFile | None = None


class SystemContextManifest(ProtocolModel):
    schema_version: Literal[1] = 1
    python_version: NonEmptyStr
    platform: NonEmptyStr
    packages: tuple[ContextPackage, ...]
    variables: tuple[ContextVariable, ...]
    files: tuple[ContextFile, ...]
    commands: tuple[ContextCommand, ...]
```

The manifest contains serializable values and excludes process handles and
secrets. A test or review that needs a credential supplies a deterministic
fixture value with zero external authority.

The manifest fixes exogenous inputs. The compiler observes dynamic outcomes
produced by the source revision: decorator registrations, registry contents,
reflection targets, resolved imports, and subprocess entrypoints.

### Source identity

```python
class SystemSource(ProtocolModel):
    repository: HttpUrl
    commit: GitCommit
```

The baseline and candidate graphs may use different `SystemSource.commit`
values. Both graphs must use the same context-manifest digest.

### Nodes, edges, and observations

```python
class SystemNode(ProtocolModel):
    node_id: SystemNodeId
    kind: SystemNodeKind
    path: RepoRelPath | None = None
    symbol: NonEmptyStr | None = None
    line: int | None = Field(default=None, ge=1)
    sha256: SHA256 | None = None


class SystemEdge(ProtocolModel):
    source: SystemNodeId
    target: SystemNodeId
    kind: SystemEdgeKind


class ResolutionObservation(ProtocolModel):
    kind: ResolutionKind
    source: SystemNodeId
    target: SystemNodeId
```

`SystemNode` applies these field rules:

- A source-backed node requires `path` and `sha256`.
- A symbol, protocol field, operation, command, rule, requirement, or task
  requires `symbol`.
- `external_input` and `unresolved_target` carry `path=None`, `symbol=None`, and
  `sha256=None` when their source lies outside the repository.

Every `SystemEdge.source` and `SystemEdge.target` must name a node in the same
graph. Duplicate `(source, target, kind)` tuples fail validation.

### Complete system graph

```python
class UnresolvedDependency(ProtocolModel):
    source: SystemNodeId
    kind: ResolutionKind
    expression: NonEmptyStr
    reason: NonEmptyStr


class SystemGraph(ProtocolModel):
    schema_version: Literal[1] = 1
    source: SystemSource
    context_sha256: SHA256
    nodes: tuple[SystemNode, ...] = Field(min_length=1)
    edges: tuple[SystemEdge, ...]
    observations: tuple[ResolutionObservation, ...]
    unresolved: tuple[UnresolvedDependency, ...]
```

Nodes sort by `node_id`. Edges sort by `(source, target, kind)`. Observations
sort by `(kind, source, target)`. Unresolved dependencies sort by
`(source, kind, expression)`.

The graph digest is the SHA-256 digest of canonical JSON bytes. The stored graph
uses `ResolvedFileRef` as its immutable reference.

### Condensation DAG

Python imports and calls may contain cycles. The compiler collapses each
strongly connected component into one component node:

```python
class SystemComponent(ProtocolModel):
    component_id: SystemComponentId
    members: tuple[SystemNodeId, ...] = Field(min_length=1)


class SystemComponentEdge(ProtocolModel):
    source: SystemComponentId
    target: SystemComponentId
    relations: tuple[SystemEdgeKind, ...] = Field(min_length=1)


class SystemCondensationDAG(ProtocolModel):
    schema_version: Literal[1] = 1
    graph: ResolvedFileRef
    components: tuple[SystemComponent, ...] = Field(min_length=1)
    edges: tuple[SystemComponentEdge, ...]
```

`component_id` hashes the ordered member IDs. The component graph must be
acyclic. An edge retains every relationship kind crossing the same component
pair. The DAG remains unweighted.

### Graph delta and impact report

```python
class ChangedNode(ProtocolModel):
    node_id: SystemNodeId
    baseline: SystemNode
    candidate: SystemNode


class SystemGraphDelta(ProtocolModel):
    schema_version: Literal[1] = 1
    baseline: ResolvedFileRef
    candidate: ResolvedFileRef
    context_sha256: SHA256
    added_nodes: tuple[SystemNode, ...]
    removed_nodes: tuple[SystemNode, ...]
    changed_nodes: tuple[ChangedNode, ...]
    added_edges: tuple[SystemEdge, ...]
    removed_edges: tuple[SystemEdge, ...]


class ImpactReport(ProtocolModel):
    schema_version: Literal[1] = 1
    delta: ResolvedFileRef
    affected_nodes: tuple[SystemNodeId, ...]
    affected_requirements: tuple[NonEmptyStr, ...]
    observing_tests: tuple[RepoRelPath, ...]
    unresolved: tuple[UnresolvedDependency, ...]
    complete: bool
```

`complete` is `True` only when both source graphs have empty `unresolved`
collections. Strict compilation rejects an incomplete graph before publishing
an `ImpactReport`.

## 5. Compilation

### Static pass

The compiler parses repository files and emits directly supported nodes and
edges:

```text
Python AST
-> modules, symbols, imports, calls, decorators, and literal registrations

public __all__ and package imports
-> public-export edges

Pydantic declarations
-> protocol-model and protocol-field nodes

typed operation and CLI registries
-> API-operation and CLI-command edges

contract requirement comments
-> contract-to-requirement edges

checklist implementation and verification comments
-> requirement-to-task and requirement-to-test edges
```

The first implementation supports direct names, attributes, literal
collections, and repository-owned helper calls evaluated solely from declared
repository inputs.

### Observed pass

The compiler then runs discovery under the fixed context:

```text
source revision + SystemContextManifest
-> isolated discovery process
-> import modules and inspect declared registries
-> record decorator registrations
-> resolve configured reflection targets
-> intercept declared subprocess launches
-> emit ResolutionObservation values
```

The source revision determines the observed outcomes. The context manifest
supplies equal external inputs to both revisions.

### Unresolved boundary

When discovery reaches an input absent from the context manifest, it emits
`UnresolvedDependency`. Examples include an undeclared environment variable, a
network response omitted from the fixtures, or an executable omitted from the
declared command identities.

```text
strict=True
-> reject before graph publication

strict=False
-> publish graph with unresolved nodes
-> ImpactReport.complete = False
```

The specification-system review gate requires strict mode.

## 6. Persisted evidence

One review stores these files:

```text
.viper/system/<context-sha256>/<source-commit>/graph.json
.viper/system/<context-sha256>/<source-commit>/dag.json
.viper/system/<context-sha256>/<baseline>..<candidate>/delta.json
.viper/system/<context-sha256>/<baseline>..<candidate>/impact.json
```

Each file publishes through `publish_resolved_files()` and receives one
`ResolvedFileRef`. The path is a discovery aid. The reference and content
digest provide identity.

The context manifest is published once. Both graphs store its digest. The
delta verifier loads both graphs and requires equal context digests.

## 7. Verification

The implementation adds these checks:

| Rule | Executable requirement |
| --- | --- |
| `system.context.identity` | Recompute the canonical manifest digest. |
| `system.graph.canonical` | Recompile the source revision and require identical ordered nodes, edges, observations, and unresolved dependencies. |
| `system.graph.references` | Require every edge and observation endpoint to exist. |
| `system.graph.strict` | Reject unresolved dependencies in the specification-system review path. |
| `system.dag.components` | Recompute strongly connected components and component IDs. |
| `system.dag.acyclic` | Require topological ordering to visit every component once. |
| `system.delta.context` | Require the baseline and candidate graphs to use the same context digest. |
| `system.delta.identity` | Recompute every added, removed, and changed node and edge. |
| `system.impact.closure` | Recompute reverse reachability from every changed node and edge endpoint. |
| `system.requirement.coverage` | Require each contract requirement to reach exactly one implementation task and at least one observing test. |

## 8. Propagation

| Surface | Required statement |
| --- | --- |
| `src/viper/system_graph.py` | Add every graph model, canonical serializer, static compiler, observed discovery pass, SCC condensation, graph comparator, and impact closure. |
| `src/viper/inspection.py` | Add `compile_system()`, `system_diff()`, and `system_impact()` inspection functions. |
| `src/viper/api.py` | Add typed compile, diff, and impact request and success models for developer tooling. |
| `src/viper/_api/handlers.py` | Route developer operations through the same compiler and serializers. |
| `src/viper/cli.py` | Add `viper system compile`, `viper system diff`, and `viper system impact` with deterministic JSON output. |
| `src/viper/storage.py` | Publish manifests, graphs, DAGs, deltas, and reports through the independent-file publisher. |
| `tests/test_validation_architecture.py` | Cover static extraction, observed registries, fixed context, unresolved targets, canonical ordering, SCC condensation, and strict failure. |
| `tests/test_inspection.py` | Cover graph delta, reverse closure, stable impact ordering, and one changed protocol-field path. |
| `tests/test_documentation.py` | Replace the separate contract-marker audit with graph-backed coverage and compare both results during migration. |
| `docs/development/master-execution-checklist.md` | Produce the compiler in Phase 0 and require its strict impact report before every later phase. |
| `docs/development/testing.md` | Define the fixed review context and the strict system-impact gate. |
| `pyproject.toml` | Register the new tests and any optional graph implementation dependency; the base implementation uses the standard library. |

### Legacy cleanup

| Current occurrence | Disposition |
| --- | --- |
| Independent import-privacy AST scan | Retain as a focused assertion until graph parity passes, then implement it as a query over `SystemGraph`. |
| Independent contract requirement and checklist parser | Retain as an oracle until graph parity passes, then query `implements` and `tests` edges. |
| `plan_diff()` | Retain; it compares user experiment plans and belongs to the later experiment-graph contract. |
| `lineage()` | Retain; it compiles verified user-run provenance, while `SystemGraph` compiles VIPER source dependencies. |
| Manual change-impact prose | Retain for semantic judgment; require its stated scope to match the generated `ImpactReport`. |

## 9. Acceptance case

### Success

1. Compile the current source revision under fixture context `X` twice.
2. Require identical graph bytes, DAG bytes, digests, and empty unresolved
   collections.
3. Change `LocalFileRef.store` in a candidate fixture revision.
4. Compile the candidate under the same `X`.
5. Require the delta to include the protocol field.
6. Require the reverse closure to include local storage construction, retrieval,
   storage verification, protocol documentation, storage tests, and the owning
   contract requirement.

### Rejection

A candidate reads `VIPER_BACKEND` during decorator registration. The context
manifest omits that variable. Strict compilation emits
`UnresolvedDependency(kind="registry_entry")` and rejects the impact report
through `system.graph.strict`.

### Dynamic-change case

The baseline decorator registers operation `run`. The candidate removes the
decorator while the context remains equal. The observed candidate registry
omits `run`. The graph delta removes the `registers` edge and reaches the API,
CLI, MCP, documentation, and test consumers. The test proves that registry
contents belong to observed outcomes and stay outside the fixed context values.

## 10. Implementation order

1. Add context, node, edge, graph, DAG, delta, and impact models.
2. Compile static Python, protocol, registry, contract, checklist, and test
   relationships.
3. Add the observed discovery process and strict unresolved-input handling.
4. Add SCC condensation and canonical DAG serialization.
5. Add typed graph comparison and reverse impact closure.
6. Compare graph-backed contract coverage with the existing documentation-test
   oracle.
7. Add Python, typed API, and CLI developer operations.
8. Require one strict impact report before each later checklist phase closes.

**Commit boundary:** `Compile deterministic system impact graphs`
