# PairBlock scheduling contract

## 1. Status

**Contract status:** Complete.

| ID | Implementation obligation |
| --- | --- |
| SCH-01 <!-- contract-requirement: SCH-01 phase=4 test=tests/test_system_impact.py --> | Compose dependency-ordered `ContractTarget` records into one terminal planned source tree so the existing CodeQL adapter can analyze the plan before implementation. |
| SCH-02 <!-- contract-requirement: SCH-02 phase=4 test=tests/test_system_impact.py --> | Project explicit PairBlock dependencies, planned source dependencies, and overlapping target files into one deterministic block graph. |
| SCH-03 <!-- contract-requirement: SCH-03 phase=4 test=tests/test_system_impact.py --> | Condense strongly connected blocks and return deterministic execution waves whose groups may run concurrently. |

## 2. Required claim

Given one closed `ContractTraceabilityGraph`, one baseline `SourceGraph`, and
the CodeQL `SourceGraph` produced from the selected target declarations, VIPER
returns a deterministic sequence of execution waves. Blocks in one wave have
no unresolved dependency or write conflict between groups. Every selected
block appears exactly once.

The first version schedules work. It does not estimate duration, token use, or
agent quality, and it does not merge candidate commits automatically.

## 3. Current gap

### Inspected path

The current stack already supplies:

```text
contract Markdown
-> compile_contract_traceability()
-> ContractTarget + PairBlock records

repository source
-> analyze_source()
-> SourceGraph

implemented candidate
-> check_plan()
-> accept()
```

The fixed example selects four blocks. `P-A` adds `parse()`. `P-B` changes
`load()` to call `parse()`. `P-C` and `P-D` edit different declarations in one
file. The scheduler must place `P-A` before `P-B` and serialize `P-C` before
`P-D` to avoid concurrent writes to the same file.

### Current DAG

```mermaid
flowchart LR
    Contract["ContractTarget + PairBlock"] --> CTG["ContractTraceabilityGraph"]
    Source["baseline source"] --> CodeQL["analyze_source()"]
    CodeQL --> G0["SourceGraph G0"]
    CTG --> Gap["no block projection"]
    G0 --> Gap
    Gap --> Manual["manual execution order"]

    class Contract,Source current
    class CTG,CodeQL,G0 implementation
    class Gap gap
    class Manual checklist
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef gap fill:#7f1d1d,stroke:#fca5a5,color:#ffffff,stroke-width:2px
    classDef checklist fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Missing connector

VIPER does not compose repeated changes to one declaration, materialize the
terminal planned source before implementation, project source dependencies
onto their owning PairBlocks, or condense the result into a dependency-safe
execution order.

### Proposed-change DAG

```mermaid
flowchart TB
    Order["order_blocks()"] --> Final["final_targets()"]
    Final --> Overlay["materialize_plan()"]
    Overlay --> Gp["planned SourceGraph"]
    Gp --> Project["build_block_graph()"]
    Project --> Blocks["BlockGraph"]
    Blocks --> SCC["strong_components()"]
    SCC --> Waves["schedule_blocks()"]
    Waves --> Schedule["BlockSchedule"]

    class Order,Final,Overlay,Gp,Project,Blocks,SCC,Waves,Schedule proposed
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

### Integrated DAG

```mermaid
flowchart TB
    Contract["approved contract"] --> CTG["ContractTraceabilityGraph"]
    Base["baseline source"] --> G0["CodeQL SourceGraph G0"]
    CTG --> Order["order_blocks()"]
    Order --> Final["final_targets()"]
    Final --> Overlay["materialize_plan()"]
    Base --> Overlay
    Overlay --> Analyze["analyze_source()"]
    Analyze --> Gp["planned SourceGraph Gp"]
    CTG --> Project["build_block_graph()"]
    G0 --> Project
    Gp --> Project
    Project --> SCC["SCC condensation"]
    SCC --> Schedule["BlockSchedule waves"]
    Schedule --> Checklist["reviewed master-checklist order"]
    Checklist --> Work["isolated PairBlock worktrees"]
    Work --> Check["check_plan() + accept()"]

    class Contract,Base current
    class CTG,G0,Analyze,Check implementation
    class Overlay,Gp,Project,SCC,Schedule proposed
    class Checklist checklist
    class Work output
    classDef current fill:#1e3a8a,stroke:#60a5fa,color:#ffffff,stroke-width:2px
    classDef implementation fill:#115e59,stroke:#5eead4,color:#ffffff,stroke-width:2px
    classDef proposed fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    classDef checklist fill:#713f12,stroke:#fbbf24,color:#ffffff,stroke-width:2px
    classDef output fill:#581c87,stroke:#d8b4fe,color:#ffffff,stroke-width:2px
    linkStyle default stroke:#94a3b8,stroke-width:2px
```

## 4. Models

| Object | Role |
| --- | --- |
| `ScheduleEdge` | One prerequisite-to-consumer relation and its evidence. |
| `BlockGraph` | Selected blocks plus explicit, source-derived, and file-conflict edges. |
| `WorkGroup` | One SCC that must remain one execution unit. |
| `WorkWave` | Groups whose predecessor groups have already completed. |
| `BlockSchedule` | Complete deterministic assignment of selected blocks to waves. |

The executable declarations appear once, under Accepted `ContractTarget`
declarations.

## 5. Execution

`order_blocks()` orders the selected dependency closure. `final_targets()`
then composes repeated changes to one symbol. Repeated writers must already be
ordered by `PairBlock.depends_on`; otherwise the plan is ambiguous and fails.
The final target is an `add`, `update`, or `remove` relative to the baseline,
regardless of how many intermediate declarations the PairBlocks specify.

`materialize_plan()` copies the baseline Python tree and applies declarations
in PairBlock order. It replaces or removes existing declarations by their
exact `SourceGraph` spans, places a new declaration before the next existing
target, and keeps new imports in the module import block. Version 1 rejects
nested additions because `ContractTarget` does not yet carry a class-body
insertion point.

The existing `analyze_source()` operation analyzes that materialized tree with
the same pinned `CodeQLIdentity` used for the baseline. `build_block_graph()`
then adds three edge classes:

1. `PairBlock.depends_on`: the dependency block precedes its consumer.
2. `SourceEdge`: the block owning the depended-on declaration precedes the
   block owning the dependent declaration.
3. Same-file writes: an existing dependency determines their direction;
   otherwise the lower PairBlock ID runs first.

`schedule_blocks()` computes SCCs, replaces each SCC with one group, and uses
the zero-indegree frontier of the condensation DAG as one execution wave.

## 6. Persisted evidence

The scheduler returns canonical protocol records. The existing CodeQL receipts
bind both source graphs to their snapshots and analyzer identity. The master
checklist remains the reviewed scheduling authority; `BlockSchedule` is the
evidence used to update it, not an automatic checklist mutation.

## 7. Verification

| Rule | Executable condition |
| --- | --- |
| `schedule.plan.materialized` <!-- verifier-rule: schedule.plan.materialized requirement=SCH-01 --> | Dependency-ordered additions, updates, and removals compose into the exact terminal planned source without changing the baseline tree; unordered repeat writers fail. |
| `schedule.graph.closed` <!-- verifier-rule: schedule.graph.closed requirement=SCH-02 --> | Every graph endpoint is selected; explicit and planned source dependencies point prerequisite-first; blocks writing one file receive one deterministic serial order. |
| `schedule.waves.complete` <!-- verifier-rule: schedule.waves.complete requirement=SCH-03 --> | Every selected block occurs in exactly one SCC group and one wave; every predecessor group occurs in an earlier wave. |

## 8. Propagation

| Surface | Required change |
| --- | --- |
| `system-impact-compiler.md` | Replace the exploratory scheduler appendix with a link to this governing contract. |
| Master checklist | Add the scheduler blocks after the existing System Impact blocks; retain human approval of the generated order. |
| Contract execution | Use a schedule only after all selected contracts compile into one CTG and both source graphs share one CodeQL identity. |
| Parallel worktrees | Give one group exclusive ownership of its PairBlock targets; integrate accepted commits sequentially. |

## 9. Acceptance case

### Success

For the four-block fixture, the first wave contains `(P-A,)` and `(P-C,)`.
The second wave contains `(P-B,)` and `(P-D,)`. Repeating the operation returns
byte-identical JSON.

<!-- contract-worked-example: start -->
```python
traceability, baseline, planned = _schedule_fixture()
graph = build_block_graph(
    traceability,
    ("P0-TST-02", "P0-TST-03", "P0-TST-04"),
    baseline,
    planned,
)
result = schedule_blocks(graph)
groups = {group.group_id: group.blocks for group in result.groups}
waves = tuple(
    tuple(groups[group_id] for group_id in wave.groups)
    for wave in result.waves
)
assert set(waves[0]) == {("P0-TST-01",), ("P0-TST-03",)}
assert set(waves[1]) == {("P0-TST-02",), ("P0-TST-04",)}
```
<!-- contract-worked-example: end -->

### Rejection

Materialization rejects a nested added target, an impossible action sequence,
and repeat writers without an explicit dependency path. Graph construction
rejects an unknown block or a source edge whose selected endpoint cannot be
resolved uniquely.

## 10. Implementation order

1. Order selected blocks, compose their final declarations, and analyze the
   planned tree.
2. Project explicit, source, and same-file relationships onto PairBlocks.
3. Condense SCCs and emit deterministic execution waves.
4. Replay the four-block fixture and one completed contract slice before using
   the schedule to revise checklist order.

## 11. Contract-owned PairBlocks

<!-- pair-block-definition: P4-SCH-01 -->
```toml pair-block
id = "P4-SCH-01"
requirements = ["SCH-01"]
targets = [
    "src/viper/scheduling.py:annotations",
    "src/viper/scheduling.py:ast",
    "src/viper/scheduling.py:shutil",
    "src/viper/scheduling.py:defaultdict",
    "src/viper/scheduling.py:Path",
    "src/viper/scheduling.py:ContractTarget",
    "src/viper/scheduling.py:ContractTraceabilityGraph",
    "src/viper/scheduling.py:PairBlockId",
    "src/viper/scheduling.py:TargetAction",
    "src/viper/scheduling.py:_declaration_payload",
    "src/viper/scheduling.py:SourceGraph",
    "src/viper/scheduling.py:_import_parts",
    "src/viper/scheduling.py:ScheduleError",
    "src/viper/scheduling.py:select_blocks",
    "src/viper/scheduling.py:order_blocks",
    "src/viper/scheduling.py:_precedes",
    "src/viper/scheduling.py:final_targets",
    "src/viper/scheduling.py:materialize_plan",
    "src/viper/scheduling.py:__all__",
    "tests/test_system_impact.py:scheduling",
    "tests/test_system_impact.py:test_final_targets_compose_ordered_revisions",
    "tests/test_system_impact.py:test_materialize_plan_applies_exact_declarations",
    "tests/test_system_impact.py:test_materialize_plan_coalesces_one_shared_declaration_removal",
    "tests/test_system_impact.py:test_materialize_plan_composes_one_import_across_targets",
    "tests/test_system_impact.py:test_pre_pairing_modules_document_every_operation",
    "tests/test_system_impact.py:test_pre_pairing_command_loads",
    "tools/check_plan.py:annotations",
    "tools/check_plan.py:argparse",
    "tools/check_plan.py:hashlib",
    "tools/check_plan.py:json",
    "tools/check_plan.py:os",
    "tools/check_plan.py:platform",
    "tools/check_plan.py:shutil",
    "tools/check_plan.py:sys",
    "tools/check_plan.py:Sequence",
    "tools/check_plan.py:Path",
    "tools/check_plan.py:Any",
    "tools/check_plan.py:ROOT",
    "tools/check_plan.py:impact",
    "tools/check_plan.py:subprocess",
    "tools/check_plan.py:ContractTraceabilityGraph",
    "tools/check_plan.py:PairBlockId",
    "tools/check_plan.py:_implemented_pair_blocks",
    "tools/check_plan.py:compile_contract_plan",
    "tools/check_plan.py:compile_contract_traceability",
    "tools/check_plan.py:_tree_digest",
    "tools/check_plan.py:analyze_source",
    "tools/check_plan.py:source_digest",
    "tools/check_plan.py:ScheduleError",
    "tools/check_plan.py:materialize_plan",
    "tools/check_plan.py:select_blocks",
    "tools/check_plan.py:PlanValidationError",
    "tools/check_plan.py:_run",
    "tools/check_plan.py:_git_revision",
    "tools/check_plan.py:_contracts",
    "tools/check_plan.py:_identity",
    "tools/check_plan.py:_analyze",
    "tools/check_plan.py:_unconsumed_private_owners",
    "tools/check_plan.py:validate",
    "tools/check_plan.py:main",
]
tests = [
    "tests/test_system_impact.py:test_final_targets_compose_ordered_revisions",
    "tests/test_system_impact.py:test_materialize_plan_applies_exact_declarations",
    "tests/test_system_impact.py:test_materialize_plan_coalesces_one_shared_declaration_removal",
    "tests/test_system_impact.py:test_materialize_plan_composes_one_import_across_targets",
    "tests/test_system_impact.py:test_pre_pairing_modules_document_every_operation",
    "tests/test_system_impact.py:test_pre_pairing_command_loads",
]
gate = "python -m pytest tests/test_system_impact.py -k 'materialize_plan or pre_pairing_modules' -q"
depends_on = ["P0-SIG-06"]
```

**Context:** System Impact can inspect approved declaration bytes and analyze
an implemented candidate, but it cannot compose several planned revisions of
one symbol or analyze the terminal planned code before implementation. This
block orders those revisions and creates one isolated planned source tree.

<!-- pair-block-definition: P4-SCH-02 -->
```toml pair-block
id = "P4-SCH-02"
requirements = ["SCH-02"]
targets = [
    "src/viper/scheduling.py:Literal",
    "src/viper/scheduling.py:Self",
    "src/viper/scheduling.py:Field",
    "src/viper/scheduling.py:model_validator",
    "src/viper/scheduling.py:NonEmptyStr",
    "src/viper/scheduling.py:ProtocolModel",
    "src/viper/scheduling.py:ScheduleEdgeKind",
    "src/viper/scheduling.py:ScheduleEdge",
    "src/viper/scheduling.py:BlockGraph",
    "src/viper/scheduling.py:build_block_graph",
    "src/viper/scheduling.py:__all__",
    "tests/test_system_impact.py:_schedule_fixture",
    "tests/test_system_impact.py:test_block_graph_combines_dependencies_and_write_conflicts",
    "tests/test_system_impact.py:test_block_graph_rejects_unselected_endpoint",
]
tests = [
    "tests/test_system_impact.py:test_block_graph_combines_dependencies_and_write_conflicts",
    "tests/test_system_impact.py:test_block_graph_rejects_unselected_endpoint",
]
gate = "python -m pytest tests/test_system_impact.py -k block_graph -q"
depends_on = ["P4-SCH-01"]
```

**Context:** PairBlock dependencies and CodeQL source edges currently remain
separate records. This block projects both relations onto selected blocks and
orders blocks that would write the same file.

<!-- pair-block-definition: P4-SCH-03 -->
```toml pair-block
id = "P4-SCH-03"
requirements = ["SCH-03"]
targets = [
    "src/viper/scheduling.py:hashlib",
    "src/viper/scheduling.py:SHA256",
    "src/viper/scheduling.py:NonEmptyStr",
    "src/viper/scheduling.py:ProtocolModel",
    "src/viper/scheduling.py:WorkGroup",
    "src/viper/scheduling.py:WorkWave",
    "src/viper/scheduling.py:BlockSchedule",
    "src/viper/scheduling.py:strong_components",
    "src/viper/scheduling.py:schedule_blocks",
    "src/viper/scheduling.py:__all__",
    "tests/test_system_impact.py:test_schedule_blocks_returns_dependency_safe_waves",
    "tests/test_system_impact.py:test_schedule_blocks_keeps_cycle_in_one_group",
]
tests = [
    "tests/test_system_impact.py:test_schedule_blocks_returns_dependency_safe_waves",
    "tests/test_system_impact.py:test_schedule_blocks_keeps_cycle_in_one_group",
]
gate = "python -m pytest tests/test_system_impact.py -k schedule_blocks -q"
depends_on = ["P4-SCH-02"]
```

**Context:** A directed block graph states precedence and coupling but does not
assign executable work. This block condenses cycles and returns the maximal
deterministic frontier available at each step.

## 12. ContractTarget

### P4-SCH-01 — planned source

**File: `src/viper/scheduling.py`**

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:annotations -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:ast -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:shutil -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:defaultdict -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:Path -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:ContractTarget -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:ContractTraceabilityGraph -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:PairBlockId -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:TargetAction -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:_declaration_payload -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:SourceGraph -->
```python contract-target
from __future__ import annotations

import ast
import shutil
from collections import defaultdict
from pathlib import Path

from ._contract_traceability import (
    ContractTarget,
    ContractTraceabilityGraph,
    PairBlockId,
    TargetAction,
)
from ._system_impact.source import declaration_payload as _declaration_payload
from .system_impact import SourceGraph
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:ScheduleError -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:_import_parts -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:select_blocks -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:order_blocks -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:_precedes -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:final_targets -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:materialize_plan -->
```python contract-target
def _import_parts(
    payload: bytes,
) -> tuple[tuple[int, str | None], frozenset[str]] | None:
    """Return the module and imported names for one import statement."""
    try:
        tree = ast.parse(payload)
    except SyntaxError:
        return None
    if len(tree.body) != 1:
        return None
    statement = tree.body[0]
    if isinstance(statement, ast.ImportFrom):
        owner = (statement.level, statement.module)
    elif isinstance(statement, ast.Import) and len(statement.names) == 1:
        owner = (0, statement.names[0].name)
    else:
        return None
    names = frozenset(alias.asname or alias.name for alias in statement.names)
    return owner, names


class ScheduleError(ValueError):
    """Report an invalid planned source or block schedule."""


def select_blocks(
    traceability: ContractTraceabilityGraph,
    requested: tuple[PairBlockId, ...],
    *,
    completed: frozenset[PairBlockId] = frozenset(),
) -> tuple[PairBlockId, ...]:
    """Select requested blocks and their unfinished dependencies."""
    blocks = {block.block_id: block for block in traceability.blocks}
    selected: set[PairBlockId] = set()

    def include(block_id: PairBlockId) -> None:
        """Add this block and its unfinished dependencies."""
        if block_id in completed or block_id in selected:
            return
        block = blocks.get(block_id)
        if block is None:
            raise ScheduleError(f"unknown PairBlock: {block_id}")
        selected.add(block_id)
        for dependency in block.depends_on:
            include(dependency)

    for block_id in requested:
        include(block_id)
    return tuple(sorted(selected))


def order_blocks(
    traceability: ContractTraceabilityGraph,
    selected: tuple[PairBlockId, ...],
) -> tuple[PairBlockId, ...]:
    """Order blocks by dependency, then by ID."""
    blocks = {block.block_id: block for block in traceability.blocks}
    known = set(selected)
    if len(known) != len(selected) or any(block not in blocks for block in known):
        raise ScheduleError("selected PairBlocks must be unique and known")
    successors = {block: set() for block in known}
    indegree = {block: 0 for block in known}
    for block in known:
        for dependency in blocks[block].depends_on:
            if dependency not in known:
                continue
            successors[dependency].add(block)
            indegree[block] += 1

    ordered: list[PairBlockId] = []
    while len(ordered) < len(known):
        ready = sorted(block for block in known - set(ordered) if indegree[block] == 0)
        if not ready:
            raise ScheduleError("selected PairBlocks contain a dependency cycle")
        for block in ready:
            ordered.append(block)
            for consumer in successors[block]:
                indegree[consumer] -= 1
    return tuple(ordered)


def _precedes(
    traceability: ContractTraceabilityGraph,
    prerequisite: PairBlockId,
    consumer: PairBlockId,
) -> bool:
    """Return whether the consumer depends on the prerequisite."""
    blocks = {block.block_id: block for block in traceability.blocks}
    pending = list(blocks[consumer].depends_on)
    visited: set[PairBlockId] = set()
    while pending:
        block = pending.pop()
        if block == prerequisite:
            return True
        if block in visited or block not in blocks:
            continue
        visited.add(block)
        pending.extend(blocks[block].depends_on)
    return False


def final_targets(
    traceability: ContractTraceabilityGraph,
    ordered: tuple[PairBlockId, ...],
    baseline: SourceGraph,
) -> tuple[ContractTarget, ...]:
    """Reduce ordered edits for each target to one change from the baseline."""
    positions = {block: index for index, block in enumerate(ordered)}
    target_positions = {
        block.block_id: {target: index for index, target in enumerate(block.targets)}
        for block in traceability.blocks
        if block.block_id in positions
    }
    # Group every edit to the same target.
    chains: dict[tuple[str, str], list[ContractTarget]] = defaultdict(list)
    for target in traceability.targets:
        if target.block_id in positions:
            chains[(target.target.path, target.target.symbol)].append(target)
    baseline_targets = {(node.path, node.symbol) for node in baseline.nodes}
    resolved: list[ContractTarget] = []
    for identity, chain in sorted(chains.items()):
        chain.sort(key=lambda target: positions[target.block_id])
        # Several blocks may edit one target only when depends_on orders them.
        for earlier, later in zip(chain, chain[1:], strict=False):
            if not _precedes(traceability, earlier.block_id, later.block_id):
                raise ScheduleError(
                    "repeat target writers require an explicit dependency path: "
                    f"{identity[0]}:{identity[1]}"
                )

        initially_present = identity in baseline_targets
        present = initially_present
        for target in chain:
            if target.action == "add":
                if present:
                    raise ScheduleError(f"added target already exists: {target.target}")
                present = True
            elif target.action == "update":
                if not present:
                    raise ScheduleError(f"updated target is absent: {target.target}")
            else:
                if not present:
                    raise ScheduleError(f"removed target is absent: {target.target}")
                present = False

        # Reduce the chain to one change from the baseline to the final state.
        if not initially_present and not present:
            continue
        last = chain[-1]
        action: TargetAction
        if present:
            action = "update" if initially_present else "add"
        else:
            action = "remove"
        resolved.append(last.model_copy(update={"action": action}))
    return tuple(
        sorted(
            resolved,
            key=lambda target: (
                positions[target.block_id],
                target_positions[target.block_id][target.target],
            ),
        )
    )


def materialize_plan(
    baseline_root: Path,
    plan_root: Path,
    traceability: ContractTraceabilityGraph,
    block_ids: tuple[PairBlockId, ...],
    baseline: SourceGraph,
    destination: Path,
    *,
    completed: frozenset[PairBlockId] = frozenset(),
) -> None:
    """Copy the baseline and apply selected edits to a new tree."""
    if destination.exists():
        raise ScheduleError("planned source destination already exists")
    shutil.copytree(
        baseline_root,
        destination,
        ignore=shutil.ignore_patterns(".git", ".venv", ".viper", "__pycache__"),
    )
    selected = select_blocks(traceability, block_ids, completed=completed)
    ordered = order_blocks(traceability, selected)
    targets = final_targets(traceability, ordered, baseline)
    if not targets:
        raise ScheduleError("selected PairBlocks contain no ContractTargets")
    nodes = {(node.path, node.symbol): node for node in baseline.nodes}
    by_path: dict[str, list[ContractTarget]] = defaultdict(list)
    for target in targets:
        by_path[target.target.path].append(target)

    for relative_path, file_targets in sorted(by_path.items()):
        output = destination / relative_path
        source = output.read_bytes() if output.exists() else b""
        lines = source.splitlines(keepends=True)
        starts = [0]
        for line in lines:
            starts.append(starts[-1] + len(line))
        replacements: dict[tuple[int, int], bytes] = {}
        additions: list[tuple[int, bytes]] = []
        for index, target in enumerate(file_targets):
            node = nodes.get((target.target.path, target.target.symbol))
            if target.action == "add":
                if node is not None:
                    raise ScheduleError(f"added target already exists: {target.target}")
                if "." in target.target.symbol:
                    raise ScheduleError("version 1 cannot place a nested added target")
                payload = _declaration_payload(plan_root, target)
                assert payload is not None
                additions.append((index, payload))
                continue
            if node is None:
                raise ScheduleError(f"baseline target is absent: {target.target}")
            # Convert CodeQL positions to byte offsets in the baseline file.
            start = starts[node.start_line - 1] + node.start_col
            end = starts[node.end_line - 1] + node.end_col
            payload = (
                b""
                if target.action == "remove"
                else _declaration_payload(plan_root, target)
            )
            assert payload is not None or target.action == "remove"
            span = (start, end)
            replacement = b"" if payload is None else payload
            # Removing one name and updating the shared statement are one edit.
            if span in replacements and replacements[span] != replacement:
                previous = replacements[span]
                if not previous:
                    replacements[span] = replacement
                elif replacement:
                    raise ScheduleError("one declaration has conflicting replacements")
                continue
            replacements[span] = replacement

        ordered_replacements = sorted(
            (start, end, payload) for (start, end), payload in replacements.items()
        )
        if any(
            current[0] < previous[1]
            for previous, current in zip(
                ordered_replacements,
                ordered_replacements[1:],
                strict=False,
            )
        ):
            raise ScheduleError("planned declaration replacements overlap")

        replacement_payloads = set(replacements.values())
        replacement_imports = {
            span: parts
            for span, payload in replacements.items()
            if (parts := _import_parts(payload)) is not None
        }
        unique_additions: dict[bytes, tuple[int, bytes]] = {}
        for index, payload in additions:
            if payload in replacement_payloads:
                continue
            parts = _import_parts(payload)
            if parts is not None:
                owner, names = parts
                replaced = next(
                    (
                        span
                        for span, (
                            current_owner,
                            current_names,
                        ) in replacement_imports.items()
                        if current_owner == owner and current_names < names
                    ),
                    None,
                )
                if replaced is not None:
                    replacements[replaced] = payload
                    replacement_imports[replaced] = parts
                    replacement_payloads.add(payload)
                    continue
                prior = next(
                    (
                        existing
                        for existing in unique_additions
                        if (
                            (existing_parts := _import_parts(existing)) is not None
                            and existing_parts[0] == owner
                            and existing_parts[1] <= names
                        )
                    ),
                    None,
                )
                if prior is not None:
                    unique_additions.pop(prior)
            unique_additions.setdefault(payload, (index, payload))
        additions = sorted(unique_additions.values(), key=lambda addition: addition[0])
        insertions: dict[int, list[bytes]] = defaultdict(list)
        for index, payload in additions:
            next_node = next(
                (
                    nodes.get(
                        (
                            later.target.path,
                            later.target.symbol,
                        )
                    )
                    for later in file_targets[index + 1 :]
                    if (
                        nodes.get((later.target.path, later.target.symbol)) is not None
                        and nodes[(later.target.path, later.target.symbol)].kind
                        != "import"
                    )
                ),
                None,
            )
            if payload.startswith((b"import ", b"from ")):
                imports = tuple(
                    node
                    for node in nodes.values()
                    if node.path == relative_path and node.kind == "import"
                )
                if imports:
                    last = max(
                        imports,
                        key=lambda node: (node.end_line, node.end_col),
                    )
                    offset = starts[last.end_line - 1] + last.end_col
                    if source[offset : offset + 2] == b"\r\n":
                        offset += 2
                    elif source[offset : offset + 1] == b"\n":
                        offset += 1
                else:
                    first = min(
                        (node for node in nodes.values() if node.path == relative_path),
                        key=lambda node: (node.start_line, node.start_col),
                        default=None,
                    )
                    offset = (
                        0
                        if first is None
                        else starts[first.start_line - 1] + first.start_col
                    )
            elif next_node is not None:
                offset = starts[next_node.start_line - 1] + next_node.start_col
            else:
                offset = len(source)
            if payload not in insertions[offset]:
                insertions[offset].append(payload)

        replacements_by_start = {
            start: (end, payload) for (start, end), payload in replacements.items()
        }
        edit_offsets = sorted(
            replacements_by_start.keys() | insertions.keys(),
            reverse=True,
        )
        # Apply edits from the end so baseline offsets stay valid.
        for start in edit_offsets:
            end, replacement = replacements_by_start.get(start, (start, b""))
            inserted = b"\n\n".join(insertions.get(start, ()))
            if inserted:
                if start > 0 and source[start - 1 : start] not in (b"\n", b"\r"):
                    inserted = b"\n" + inserted
                if replacement or source[start:]:
                    inserted += b"\n\n"
                elif not inserted.endswith(b"\n"):
                    inserted += b"\n"
            source = source[:start] + inserted + replacement + source[end:]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source)

```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=src/viper/scheduling.py:__all__ -->
```python contract-target
__all__ = [
    "ScheduleError",
    "final_targets",
    "materialize_plan",
    "order_blocks",
    "select_blocks",
]
```

**File: `tests/test_system_impact.py`**

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:scheduling -->
```python contract-target
import viper.scheduling as scheduling
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:test_final_targets_compose_ordered_revisions -->
```python contract-target
def test_final_targets_compose_ordered_revisions() -> None:
    """Use the last explicitly ordered declaration as the terminal target."""
    first = "P0-TST-01"
    second = "P0-TST-02"
    declaration = _declaration_ref()
    final_declaration = declaration.model_copy(update={"sha256": "1" * 64})
    target = RepoSymbolRef(path="module.py", symbol="load")
    targets = (
        ContractTarget.model_construct(
            requirements=("SCH-01",),
            block_id=first,
            action="update",
            target=target,
            declaration=declaration,
        ),
        ContractTarget.model_construct(
            requirements=("SCH-01",),
            block_id=second,
            action="update",
            target=target,
            declaration=final_declaration,
        ),
    )
    blocks = (
        PairBlock.model_construct(
            block_id=first,
            requirements=("SCH-01",),
            targets=(target,),
            assets=(),
            tests=(),
            gate="true",
            depends_on=(),
            declaration=declaration,
        ),
        PairBlock.model_construct(
            block_id=second,
            requirements=("SCH-01",),
            targets=(target,),
            assets=(),
            tests=(),
            gate="true",
            depends_on=(first,),
            declaration=declaration,
        ),
    )
    traceability = ContractTraceabilityGraph.model_construct(
        requirements=(),
        rules=(),
        edges=(),
        targets=targets,
        blocks=blocks,
    )
    baseline = _source_graph(
        nodes=(_node(path="module.py", symbol="load", kind="function"),)
    )

    resolved = scheduling.final_targets(traceability, (first, second), baseline)

    assert len(resolved) == 1
    assert resolved[0].block_id == second
    assert resolved[0].action == "update"
    assert resolved[0].declaration == final_declaration

    unordered = traceability.model_copy(
        update={
            "blocks": (
                blocks[0],
                blocks[1].model_copy(update={"depends_on": ()}),
            )
        }
    )
    with pytest.raises(scheduling.ScheduleError, match="explicit dependency path"):
        scheduling.final_targets(unordered, (first, second), baseline)
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:test_materialize_plan_applies_exact_declarations -->
```python contract-target
def test_materialize_plan_applies_exact_declarations(tmp_path: Path) -> None:
    """Apply one update, removal, and top-level addition to an isolated tree."""
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    source = b"def old():\n    return 1\n\ndef removed():\n    return 2\n"
    (baseline_root / "module.py").write_bytes(source)
    plan_root = tmp_path / "plan"
    updated = b"def old():\n    return 3"
    added = b"def added():\n    return old()"
    update_ref = _write_target_fence(plan_root, updated + b"\n\n" + added)
    remove_ref = DeclarationRef(
        path="contract.md",
        start_line=1,
        end_line=1,
        sha256=hashlib.sha256(b"<!-- contract-remove -->").hexdigest(),
    )
    graph = _source_graph(
        nodes=(
            SourceNode(
                node_id="module.py:old",
                path="module.py",
                symbol="old",
                kind="function",
                start_line=1,
                start_col=0,
                end_line=2,
                end_col=12,
                sha256=hashlib.sha256(b"def old():\n    return 1").hexdigest(),
            ),
            SourceNode(
                node_id="module.py:removed",
                path="module.py",
                symbol="removed",
                kind="function",
                start_line=4,
                start_col=0,
                end_line=5,
                end_col=12,
                sha256=hashlib.sha256(b"def removed():\n    return 2").hexdigest(),
            ),
        ),
    )
    traceability = _traceability(
        targets=(
            _target(
                action="add",
                path="module.py",
                symbol="added",
                declaration=update_ref,
            ),
            _target(
                action="update",
                path="module.py",
                symbol="old",
                declaration=update_ref,
            ),
            _target(
                action="remove",
                path="module.py",
                symbol="removed",
                declaration=remove_ref,
            ),
        ),
    )

    destination = tmp_path / "planned"
    scheduling.materialize_plan(
        baseline_root,
        plan_root,
        traceability,
        (_BLOCK_ID,),
        graph,
        destination,
    )

    assert (destination / "module.py").read_text() == (
        "def added():\n    return old()\n\ndef old():\n    return 3\n\n\n"
    )
    assert (baseline_root / "module.py").read_bytes() == source
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:test_materialize_plan_coalesces_one_shared_declaration_removal -->
```python contract-target
def test_materialize_plan_coalesces_one_shared_declaration_removal(
    tmp_path: Path,
) -> None:
    """Remove one import declaration named by several ContractTargets once."""
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    source = b"from package import First, Second\n"
    (baseline_root / "module.py").write_bytes(source)
    plan_root = tmp_path / "plan"
    remove_ref = DeclarationRef(
        path="contract.md",
        start_line=1,
        end_line=1,
        sha256=hashlib.sha256(b"<!-- contract-remove -->").hexdigest(),
    )
    declaration_end = len(source.rstrip(b"\n"))
    graph = _source_graph(
        nodes=tuple(
            SourceNode(
                node_id=f"module.py:{symbol}",
                path="module.py",
                symbol=symbol,
                kind="import",
                start_line=1,
                start_col=0,
                end_line=1,
                end_col=declaration_end,
                sha256=hashlib.sha256(source.rstrip(b"\n")).hexdigest(),
            )
            for symbol in ("First", "Second")
        ),
    )
    traceability = _traceability(
        targets=tuple(
            _target(
                action="remove",
                path="module.py",
                symbol=symbol,
                declaration=remove_ref,
            )
            for symbol in ("First", "Second")
        )
    )

    destination = tmp_path / "planned"
    scheduling.materialize_plan(
        baseline_root,
        plan_root,
        traceability,
        (_BLOCK_ID,),
        graph,
        destination,
    )

    assert (destination / "module.py").read_bytes() == b"\n"
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:test_materialize_plan_composes_one_import_across_targets -->
```python contract-target
def test_materialize_plan_composes_one_import_across_targets(tmp_path: Path) -> None:
    """Let a later import payload replace the earlier form of that import."""
    baseline_root = tmp_path / "baseline"
    baseline_root.mkdir()
    source = b"from package import First\n\nVALUE = First\n"
    (baseline_root / "module.py").write_bytes(source)

    plan_root = tmp_path / "plan"
    fence = b"`" * 3
    old_payload = fence + b"python contract-target\nfrom package import First\n" + fence
    new_payload = (
        fence + b"python contract-target\nfrom package import First, Second\n" + fence
    )
    old_path = plan_root / "docs/old.md"
    new_path = plan_root / "docs/new.md"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(old_payload + b"\n")
    new_path.write_bytes(new_payload + b"\n")
    old_ref = _declaration_ref(
        path="docs/old.md",
        start_line=1,
        end_line=3,
        sha256=_sha256(old_payload),
    )
    new_ref = _declaration_ref(
        path="docs/new.md",
        start_line=1,
        end_line=3,
        sha256=_sha256(new_payload),
    )
    declaration_end = len(b"from package import First")
    graph = _source_graph(
        nodes=(
            SourceNode(
                node_id="module.py:First",
                path="module.py",
                symbol="First",
                kind="import",
                start_line=1,
                start_col=0,
                end_line=1,
                end_col=declaration_end,
                sha256=_sha256(b"from package import First"),
            ),
        ),
    )
    traceability = _traceability(
        targets=(
            _target(
                action="update",
                path="module.py",
                symbol="First",
                declaration=old_ref,
            ),
            _target(
                action="add",
                path="module.py",
                symbol="Second",
                declaration=new_ref,
            ),
        )
    )

    destination = tmp_path / "planned"
    scheduling.materialize_plan(
        baseline_root,
        plan_root,
        traceability,
        (_BLOCK_ID,),
        graph,
        destination,
    )

    assert (destination / "module.py").read_bytes() == (
        b"from package import First, Second\n\nVALUE = First\n"
    )
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:test_pre_pairing_modules_document_every_operation -->
```python contract-target
def test_pre_pairing_modules_document_every_operation() -> None:
    """Require docstrings on public, private, and nested pre-pairing operations."""
    missing: list[str] = []
    for relative_path in ("src/viper/scheduling.py", "tools/check_plan.py"):
        tree = ast.parse(Path(relative_path).read_text(), filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node) is None:
                    missing.append(f"{relative_path}:{node.name}")

    assert missing == []
```

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tests/test_system_impact.py:test_pre_pairing_command_loads -->
```python contract-target
def test_pre_pairing_command_loads() -> None:
    """Load the pre-pairing command without relying on prior package imports."""
    checked = run_subprocess(
        (sys.executable, "tools/check_plan.py", "--help"),
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert checked.returncode == 0, checked.stderr
```

**File: `tools/check_plan.py`**

<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:annotations -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:argparse -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:hashlib -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:json -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:os -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:platform -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:shutil -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:sys -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:Sequence -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:Path -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:Any -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:ROOT -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:impact -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:subprocess -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:ContractTraceabilityGraph -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:PairBlockId -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_implemented_pair_blocks -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:compile_contract_plan -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:compile_contract_traceability -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_tree_digest -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:analyze_source -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:source_digest -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:ScheduleError -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:materialize_plan -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:select_blocks -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:PlanValidationError -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_run -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_git_revision -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_contracts -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_identity -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_analyze -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:_unconsumed_private_owners -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:validate -->
<!-- contract-target: requirements=SCH-01 block=P4-SCH-01 action=add target=tools/check_plan.py:main -->
```python contract-target
"""Check selected PairBlocks before editing source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The private CodeQL adapter imports the public models while loading.
import viper.system_impact as impact  # noqa: E402

from viper import _subprocess as subprocess  # noqa: E402
from viper._contract_traceability import (  # noqa: E402
    ContractTraceabilityGraph,
    PairBlockId,
    _implemented_pair_blocks,
    compile_contract_plan,
    compile_contract_traceability,
)
from viper._system_impact.codeql import (  # noqa: E402
    _tree_digest,
    analyze_source,
    source_digest,
)
from viper.scheduling import (  # noqa: E402
    ScheduleError,
    materialize_plan,
    select_blocks,
)


class PlanValidationError(RuntimeError):
    """Report a failed pre-pairing plan check."""


def _run(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one command without a shell."""
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed


def _git_revision(root: Path) -> str:
    """Return the current commit after requiring a clean checkout."""
    status = _run(("git", "status", "--porcelain"), cwd=root)
    if status.returncode != 0:
        raise PlanValidationError(status.stderr.strip() or "git status failed")
    if status.stdout:
        raise PlanValidationError("pre-pairing validation requires a clean baseline")
    revision = _run(("git", "rev-parse", "HEAD"), cwd=root)
    if revision.returncode != 0:
        raise PlanValidationError(revision.stderr.strip() or "git rev-parse failed")
    return revision.stdout.strip()


def _contracts(root: Path) -> tuple[Path, ...]:
    """Return the contracts in the baseline manifest."""
    manifest = json.loads(
        (root / "docs/development/contract-baselines.json").read_text()
    )
    return tuple(root / record["path"] for record in manifest["contracts"])


def _identity(executable: Path, query_pack: Path) -> impact.CodeQLIdentity:
    """Identify the CodeQL executable and query pack."""
    version = _run((str(executable), "version", "--format=json"), cwd=ROOT)
    if version.returncode != 0:
        raise PlanValidationError(version.stderr.strip() or "CodeQL version failed")
    payload = json.loads(version.stdout)
    pack_result = _run(
        (
            sys.executable,
            "-c",
            (
                "import json,yaml,pathlib; "
                "p=yaml.safe_load(pathlib.Path('qlpack.yml').read_text()); "
                "print(json.dumps(p))"
            ),
        ),
        cwd=query_pack,
    )
    if pack_result.returncode != 0:
        raise PlanValidationError(
            pack_result.stderr.strip() or "CodeQL pack inspection failed"
        )
    pack = json.loads(pack_result.stdout)
    return impact.CodeQLIdentity(
        version=payload["version"],
        platform=f"{platform.system().lower()}-{platform.machine()}",
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        pack=f"{pack['name']}@{pack['version']}",
        pack_sha256=_tree_digest(query_pack),
    )


def _analyze(
    root: Path,
    *,
    revision: str,
    committed: bool,
    identity: impact.CodeQLIdentity,
    executable: Path,
    query_pack: Path,
    cache: Path,
    artifacts: Path,
) -> impact.SourceGraph:
    """Build a source graph and its receipt."""
    snapshot = impact.SourceSnapshot(
        base_revision=revision,
        source_sha256=source_digest(root),
        revision=revision if committed else None,
    )
    return analyze_source(
        root,
        snapshot=snapshot,
        identity=identity,
        codeql_executable=executable,
        query_pack=query_pack,
        cache_root=cache,
        artifact_root=artifacts,
    )


def _unconsumed_private_owners(
    traceability: ContractTraceabilityGraph,
    selected: frozenset[PairBlockId],
    graph: impact.SourceGraph,
) -> tuple[str, ...]:
    """Find new private owners that nothing uses."""
    targets = {
        (target.block_id, target.target): target
        for target in traceability.targets
        if target.block_id in selected
    }
    nodes = {(node.path, node.symbol): node for node in graph.nodes}
    incoming = {edge.target for edge in graph.edges}
    missing: list[str] = []
    for edge in traceability.edges:
        if edge.kind != "implementation" or edge.block_id not in selected:
            continue
        target = targets.get((edge.block_id, edge.target))
        if target is None or target.action != "add":
            continue
        if not edge.target.symbol.rsplit(".", maxsplit=1)[-1].startswith("_"):
            continue
        node = nodes.get((edge.target.path, edge.target.symbol))
        if node is not None and node.node_id not in incoming:
            missing.append(f"{edge.target.path}:{edge.target.symbol}")
    return tuple(sorted(missing))


def validate(
    *,
    root: Path,
    blocks: tuple[PairBlockId, ...],
    codeql: Path,
    python: Path,
    cache: Path,
    results: Path,
) -> dict[str, Any]:
    """Build the selected plan, check it, and save the result."""
    revision = _git_revision(root)
    contracts = _contracts(root)
    # Select blocks first; their requirements determine the full CTG.
    raw_blocks, raw_targets = compile_contract_plan(root, contracts)
    completed = _implemented_pair_blocks(
        root / "docs/development/master-execution-checklist.md"
    )
    plan = ContractTraceabilityGraph.model_construct(
        requirements=(),
        rules=(),
        edges=(),
        targets=raw_targets,
        blocks=raw_blocks,
    )
    selected = select_blocks(plan, blocks, completed=completed)
    if not selected:
        raise PlanValidationError("selected PairBlocks are already implemented")
    selected_ids = set(selected)
    requirement_ids = tuple(
        sorted(
            {
                requirement
                for block in raw_blocks
                if block.block_id in selected_ids
                for requirement in block.requirements
            }
        )
    )
    traceability = compile_contract_traceability(
        root,
        root / "docs/development/master-execution-checklist.md",
        contracts,
        requirement_ids=requirement_ids,
    )
    identity = _identity(codeql, root / "tools/codeql/viper-python-impact")
    results.mkdir(parents=True, exist_ok=False)
    # Every planned edit starts from the clean commit.
    baseline = _analyze(
        root,
        revision=revision,
        committed=True,
        identity=identity,
        executable=codeql,
        query_pack=root / "tools/codeql/viper-python-impact",
        cache=cache,
        artifacts=results / "baseline-codeql",
    )

    candidate = results / "candidate"
    try:
        materialize_plan(
            root,
            root,
            traceability,
            selected,
            baseline,
            candidate,
            completed=completed,
        )
    except ScheduleError as error:
        result = {
            "passed": False,
            "stage": "materialize",
            "revision": revision,
            "blocks": selected,
            "error": str(error),
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result

    python_targets = tuple(
        sorted(
            {
                str(target.target.path)
                for target in traceability.targets
                if target.block_id in selected_ids
                and Path(target.target.path).suffix in {".py", ".pyi"}
            }
        )
    )
    checks = (
        (
            "ruff-format",
            (str(python), "-m", "ruff", "format", *python_targets),
        ),
        (
            "ruff-imports",
            (
                str(python),
                "-m",
                "ruff",
                "check",
                "--fix",
                "--select",
                "I001",
                *python_targets,
            ),
        ),
        (
            "ruff",
            (str(python), "-m", "ruff", "check", "--ignore", "D100", *python_targets),
        ),
    )
    for stage, command in checks:
        completed = _run(command, cwd=candidate)
        if completed.returncode != 0:
            result = {
                "passed": False,
                "stage": stage,
                "revision": revision,
                "blocks": selected,
                "command": tuple(completed.args),
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            (results / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n"
            )
            return result

    # Make Pyright import the candidate instead of the baseline.
    original_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(candidate / "src")
    pyright = _run(
        (
            str(python),
            "-m",
            "pyright",
            str(candidate / "src"),
            "--project",
            str(candidate / "pyrightconfig.json"),
            "--pythonpath",
            str(python),
        ),
        cwd=candidate,
    )
    if pyright.returncode != 0:
        result = {
            "passed": False,
            "stage": "pyright",
            "revision": revision,
            "blocks": selected,
            "command": tuple(pyright.args),
            "stdout": pyright.stdout,
            "stderr": pyright.stderr,
        }
        (results / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        if original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = original_pythonpath
        return result

    # Pyright checks types first; CodeQL then observes G*.
    planned = _analyze(
        candidate,
        revision=revision,
        committed=False,
        identity=identity,
        executable=codeql,
        query_pack=root / "tools/codeql/viper-python-impact",
        cache=cache,
        artifacts=results / "planned-codeql",
    )
    unconsumed = _unconsumed_private_owners(
        traceability,
        frozenset(selected),
        planned,
    )
    checked = impact.check_plan(
        root=candidate,
        baseline_root=root,
        traceability=traceability,
        block_ids=selected,
        baseline=baseline,
        realized=planned,
    )
    result = {
        "passed": checked.passed and not unconsumed,
        "stage": "complete",
        "revision": revision,
        "blocks": selected,
        "pyright": {
            "command": tuple(pyright.args),
            "stdout": pyright.stdout,
            "stderr": pyright.stderr,
        },
        "unconsumed_private_owners": unconsumed,
        "check": checked.model_dump(mode="json"),
    }
    (results / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    if original_pythonpath is None:
        os.environ.pop("PYTHONPATH", None)
    else:
        os.environ["PYTHONPATH"] = original_pythonpath
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pre-pairing check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", action="append", required=True)
    codeql = shutil.which("codeql")
    parser.add_argument(
        "--codeql",
        type=Path,
        default=None if codeql is None else Path(codeql),
    )
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / ".viper/codeql-cache")
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.codeql is None:
        parser.error("codeql is unavailable on PATH; install or expose CodeQL first")
    if args.java_home is not None:
        os.environ["CODEQL_JAVA_HOME"] = str(args.java_home.resolve())
    result = validate(
        root=ROOT,
        blocks=tuple(args.block),
        codeql=args.codeql.resolve(),
        python=args.python.resolve(),
        cache=args.cache.resolve(),
        results=args.results.resolve(),
    )
    if result["passed"]:
        print(f"planned source passed: {', '.join(result['blocks'])}")
        return 0
    print(f"planned source failed during {result['stage']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### P4-SCH-02 — block graph

**File: `src/viper/scheduling.py`**

<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:Literal -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:Self -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:Field -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:model_validator -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:NonEmptyStr -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:ProtocolModel -->
```python contract-target
from typing import Literal, Self

from pydantic import Field, model_validator

from ._schema import NonEmptyStr, ProtocolModel
```

<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:ScheduleEdgeKind -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:ScheduleEdge -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:BlockGraph -->
<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=src/viper/scheduling.py:build_block_graph -->
```python contract-target
ScheduleEdgeKind = Literal["declared", "source", "write_conflict"]


class ScheduleEdge(ProtocolModel):
    """Require one PairBlock to precede or remain coupled to another."""

    prerequisite: PairBlockId = Field(description="Block that must run first.")
    consumer: PairBlockId = Field(description="Block that must run afterward.")
    kind: ScheduleEdgeKind = Field(description="Reason the order is required.")
    evidence: NonEmptyStr = Field(description="Record that establishes the order.")


class BlockGraph(ProtocolModel):
    """Store the complete dependency graph for selected PairBlocks."""

    blocks: tuple[PairBlockId, ...] = Field(
        min_length=1,
        description="Selected blocks in canonical order.",
    )
    edges: tuple[ScheduleEdge, ...] = Field(
        description="Required ordering relationships in canonical order."
    )

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        """Require unique blocks, known endpoints, and canonical order."""
        if self.blocks != tuple(sorted(set(self.blocks))):
            raise ValueError("blocks must be unique and sorted")
        known = set(self.blocks)
        if any(
            edge.prerequisite not in known or edge.consumer not in known
            for edge in self.edges
        ):
            raise ValueError("schedule edge names an unselected PairBlock")
        ordered = tuple(
            sorted(
                self.edges,
                key=lambda edge: (
                    edge.prerequisite,
                    edge.consumer,
                    edge.kind,
                    edge.evidence,
                ),
            )
        )
        identities = tuple(
            (edge.prerequisite, edge.consumer, edge.kind, edge.evidence)
            for edge in self.edges
        )
        if self.edges != ordered or len(identities) != len(set(identities)):
            raise ValueError("schedule edges must be unique and sorted")
        return self


def build_block_graph(
    traceability: ContractTraceabilityGraph,
    requested: tuple[PairBlockId, ...],
    baseline: SourceGraph,
    planned: SourceGraph,
    *,
    completed: frozenset[PairBlockId] = frozenset(),
) -> BlockGraph:
    """Project plan, source, and write-conflict edges onto selected blocks."""
    blocks = {block.block_id: block for block in traceability.blocks}
    selected = set(select_blocks(traceability, requested, completed=completed))

    ordered = order_blocks(traceability, tuple(sorted(selected)))
    positions = {block: index for index, block in enumerate(ordered)}
    targets = tuple(
        target for target in traceability.targets if target.block_id in selected
    )
    writers: dict[tuple[str, str], list[PairBlockId]] = defaultdict(list)
    for target in targets:
        writers[(target.target.path, target.target.symbol)].append(target.block_id)
    for blocks_for_target in writers.values():
        blocks_for_target.sort(key=positions.__getitem__)
    baseline_owners = {identity: values[0] for identity, values in writers.items()}
    planned_owners = {identity: values[-1] for identity, values in writers.items()}
    nodes = {
        node.node_id: (node.path, node.symbol)
        for graph in (baseline, planned)
        for node in graph.nodes
    }
    edges: set[tuple[PairBlockId, PairBlockId, ScheduleEdgeKind, str]] = set()
    for block_id in selected:
        for dependency in blocks[block_id].depends_on:
            if dependency in selected:
                edges.add((dependency, block_id, "declared", dependency))
    for graph, owners in (
        (baseline, baseline_owners),
        (planned, planned_owners),
    ):
        for edge in graph.edges:
            consumer = owners.get(nodes.get(edge.source, ("", "")))
            prerequisite = owners.get(nodes.get(edge.target, ("", "")))
            if prerequisite is not None and consumer is not None:
                if prerequisite != consumer:
                    edges.add((prerequisite, consumer, "source", edge.edge_id))

    paths: dict[str, set[PairBlockId]] = defaultdict(set)
    for target in targets:
        paths[target.target.path].add(target.block_id)
    for path, path_writers in paths.items():
        ordered_writers = sorted(path_writers)
        for left_index, left in enumerate(ordered_writers):
            for right in ordered_writers[left_index + 1 :]:
                if _precedes(traceability, left, right):
                    prerequisite, consumer = left, right
                elif _precedes(traceability, right, left):
                    prerequisite, consumer = right, left
                else:
                    prerequisite, consumer = left, right
                edges.add((prerequisite, consumer, "write_conflict", path))

    records = tuple(
        ScheduleEdge(
            prerequisite=prerequisite,
            consumer=consumer,
            kind=kind,
            evidence=evidence,
        )
        for prerequisite, consumer, kind, evidence in sorted(edges)
    )
    return BlockGraph(blocks=tuple(sorted(selected)), edges=records)
```

<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=update target=src/viper/scheduling.py:__all__ -->
```python contract-target
__all__ = [
    "BlockGraph",
    "ScheduleError",
    "ScheduleEdge",
    "ScheduleEdgeKind",
    "build_block_graph",
    "final_targets",
    "materialize_plan",
    "order_blocks",
    "select_blocks",
]
```

**File: `tests/test_system_impact.py`**

<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=tests/test_system_impact.py:_schedule_fixture -->
```python contract-target
def _schedule_fixture() -> tuple[ContractTraceabilityGraph, SourceGraph, SourceGraph]:
    """Build four blocks with one dependency and one shared-file conflict."""
    declaration = _declaration_ref()
    definitions = (
        ("P0-TST-01", "src/parse.py", "parse", ()),
        ("P0-TST-02", "src/load.py", "load", ("P0-TST-01",)),
        ("P0-TST-03", "src/shared.py", "left", ()),
        ("P0-TST-04", "src/shared.py", "right", ()),
    )
    targets = tuple(
        ContractTarget.model_construct(
            requirements=("SCH-02",),
            block_id=block_id,
            action="update",
            target=RepoSymbolRef(path=path, symbol=symbol),
            declaration=declaration,
        )
        for block_id, path, symbol, _dependencies in definitions
    )
    blocks = tuple(
        PairBlock.model_construct(
            block_id=block_id,
            requirements=("SCH-02",),
            targets=(RepoSymbolRef(path=path, symbol=symbol),),
            assets=(),
            tests=(
                RepoSymbolRef(
                    path="tests/test_system_impact.py",
                    symbol="test_schedule_blocks_returns_dependency_safe_waves",
                ),
            ),
            gate="python -m pytest tests/test_system_impact.py",
            depends_on=dependencies,
            declaration=declaration,
        )
        for block_id, path, symbol, dependencies in definitions
    )
    traceability = ContractTraceabilityGraph.model_construct(
        requirements=(),
        rules=(),
        edges=(),
        targets=targets,
        blocks=blocks,
    )
    parse = _node(path="src/parse.py", symbol="parse", kind="function")
    load = _node(path="src/load.py", symbol="load", kind="function")
    left = _node(path="src/shared.py", symbol="left", kind="function")
    right = _node(path="src/shared.py", symbol="right", kind="function")
    baseline = _source_graph(nodes=(parse, load, left, right))
    planned = _source_graph(
        nodes=(parse, load, left, right),
        edges=(_edge(index=1, source=load, target=parse, kind="calls"),),
        source_sha256="8" * 64,
        revision=None,
    )
    return traceability, baseline, planned
```

<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=tests/test_system_impact.py:test_block_graph_combines_dependencies_and_write_conflicts -->
```python contract-target
def test_block_graph_combines_dependencies_and_write_conflicts() -> None:
    """Project explicit, source, and same-file relations onto PairBlocks."""
    traceability, baseline, planned = _schedule_fixture()

    graph = scheduling.build_block_graph(
        traceability,
        ("P0-TST-02", "P0-TST-03", "P0-TST-04"),
        baseline,
        planned,
    )

    relations = {(edge.prerequisite, edge.consumer, edge.kind) for edge in graph.edges}
    assert ("P0-TST-01", "P0-TST-02", "declared") in relations
    assert ("P0-TST-01", "P0-TST-02", "source") in relations
    assert ("P0-TST-03", "P0-TST-04", "write_conflict") in relations
    assert ("P0-TST-04", "P0-TST-03", "write_conflict") not in relations
```

<!-- contract-target: requirements=SCH-02 block=P4-SCH-02 action=add target=tests/test_system_impact.py:test_block_graph_rejects_unselected_endpoint -->
```python contract-target
def test_block_graph_rejects_unselected_endpoint() -> None:
    """Reject an edge whose consumer is absent from the selected blocks."""
    with pytest.raises(ValueError, match="unselected PairBlock"):
        scheduling.BlockGraph(
            blocks=("P0-TST-01",),
            edges=(
                scheduling.ScheduleEdge(
                    prerequisite="P0-TST-01",
                    consumer="P0-TST-02",
                    kind="declared",
                    evidence="P0-TST-01",
                ),
            ),
        )
```

### P4-SCH-03 — execution waves

**File: `src/viper/scheduling.py`**

<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:hashlib -->
```python contract-target
import hashlib
```

<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:SHA256 -->
<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=update target=src/viper/scheduling.py:NonEmptyStr -->
<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=update target=src/viper/scheduling.py:ProtocolModel -->
```python contract-target
from ._schema import SHA256, NonEmptyStr, ProtocolModel
```

<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:WorkGroup -->
<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:WorkWave -->
<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:BlockSchedule -->
<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:strong_components -->
<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=src/viper/scheduling.py:schedule_blocks -->
```python contract-target
class WorkGroup(ProtocolModel):
    """Keep one strongly connected set of PairBlocks together."""

    group_id: SHA256 = Field(description="Digest identifying this exact block set.")
    blocks: tuple[PairBlockId, ...] = Field(
        min_length=1,
        description="Blocks that must remain in one execution unit.",
    )


class WorkWave(ProtocolModel):
    """List groups eligible after all earlier waves complete."""

    index: int = Field(ge=0, description="Zero-based execution order.")
    groups: tuple[SHA256, ...] = Field(
        min_length=1,
        description="Groups eligible to run in this wave.",
    )


class BlockSchedule(ProtocolModel):
    """Assign every selected PairBlock to one ordered execution wave."""

    graph: BlockGraph = Field(description="Block graph used to derive the schedule.")
    groups: tuple[WorkGroup, ...] = Field(
        min_length=1,
        description="Strongly connected block groups.",
    )
    waves: tuple[WorkWave, ...] = Field(
        min_length=1,
        description="Dependency-safe execution waves.",
    )


def strong_components(graph: BlockGraph) -> tuple[WorkGroup, ...]:
    """Return Tarjan strongly connected components in canonical order."""
    adjacent = {block: [] for block in graph.blocks}
    for edge in graph.edges:
        adjacent[edge.prerequisite].append(edge.consumer)
    for values in adjacent.values():
        values.sort()

    index = 0
    indices: dict[PairBlockId, int] = {}
    lowlinks: dict[PairBlockId, int] = {}
    stack: list[PairBlockId] = []
    active: set[PairBlockId] = set()
    components: list[tuple[PairBlockId, ...]] = []

    def visit(block: PairBlockId) -> None:
        """Place one block in its strongly connected component."""
        nonlocal index
        indices[block] = index
        lowlinks[block] = index
        index += 1
        stack.append(block)
        active.add(block)
        for consumer in adjacent[block]:
            if consumer not in indices:
                visit(consumer)
                lowlinks[block] = min(lowlinks[block], lowlinks[consumer])
            elif consumer in active:
                lowlinks[block] = min(lowlinks[block], indices[consumer])
        if lowlinks[block] != indices[block]:
            return
        component: list[PairBlockId] = []
        while True:
            member = stack.pop()
            active.remove(member)
            component.append(member)
            if member == block:
                break
        components.append(tuple(sorted(component)))

    for block in graph.blocks:
        if block not in indices:
            visit(block)

    return tuple(
        WorkGroup(
            group_id=hashlib.sha256("\0".join(blocks).encode()).hexdigest(),
            blocks=blocks,
        )
        for blocks in sorted(components)
    )


def schedule_blocks(graph: BlockGraph) -> BlockSchedule:
    """Condense block cycles and return deterministic zero-indegree waves."""
    groups = strong_components(graph)
    owner = {block: group.group_id for group in groups for block in group.blocks}
    successors = {group.group_id: set() for group in groups}
    indegree = {group.group_id: 0 for group in groups}
    for edge in graph.edges:
        prerequisite = owner[edge.prerequisite]
        consumer = owner[edge.consumer]
        if prerequisite == consumer or consumer in successors[prerequisite]:
            continue
        successors[prerequisite].add(consumer)
        indegree[consumer] += 1

    waves: list[WorkWave] = []
    remaining = set(indegree)
    while remaining:
        ready = tuple(sorted(group for group in remaining if indegree[group] == 0))
        if not ready:
            raise ScheduleError("condensed block graph contains a cycle")
        waves.append(WorkWave(index=len(waves), groups=ready))
        for group in ready:
            remaining.remove(group)
            for consumer in successors[group]:
                indegree[consumer] -= 1
    return BlockSchedule(graph=graph, groups=groups, waves=tuple(waves))
```

<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=update target=src/viper/scheduling.py:__all__ -->
```python contract-target
__all__ = [
    "BlockGraph",
    "BlockSchedule",
    "ScheduleError",
    "ScheduleEdge",
    "ScheduleEdgeKind",
    "WorkGroup",
    "WorkWave",
    "build_block_graph",
    "final_targets",
    "materialize_plan",
    "order_blocks",
    "schedule_blocks",
    "select_blocks",
    "strong_components",
]
```

**File: `tests/test_system_impact.py`**

<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=tests/test_system_impact.py:test_schedule_blocks_returns_dependency_safe_waves -->
```python contract-target
def test_schedule_blocks_returns_dependency_safe_waves() -> None:
    """Place independent groups together and their consumer in the next wave."""
    traceability, baseline, planned = _schedule_fixture()
    graph = scheduling.build_block_graph(
        traceability,
        ("P0-TST-02", "P0-TST-03", "P0-TST-04"),
        baseline,
        planned,
    )

    schedule = scheduling.schedule_blocks(graph)
    groups = {group.group_id: group.blocks for group in schedule.groups}
    waves = tuple(
        tuple(groups[group_id] for group_id in wave.groups) for wave in schedule.waves
    )

    assert set(waves[0]) == {("P0-TST-01",), ("P0-TST-03",)}
    assert set(waves[1]) == {("P0-TST-02",), ("P0-TST-04",)}
```

<!-- contract-target: requirements=SCH-03 block=P4-SCH-03 action=add target=tests/test_system_impact.py:test_schedule_blocks_keeps_cycle_in_one_group -->
```python contract-target
def test_schedule_blocks_keeps_cycle_in_one_group() -> None:
    """Keep mutually dependent blocks together in one execution group."""
    graph = scheduling.BlockGraph(
        blocks=("P0-TST-01", "P0-TST-02"),
        edges=(
            scheduling.ScheduleEdge(
                prerequisite="P0-TST-01",
                consumer="P0-TST-02",
                kind="source",
                evidence="edge-1",
            ),
            scheduling.ScheduleEdge(
                prerequisite="P0-TST-02",
                consumer="P0-TST-01",
                kind="source",
                evidence="edge-2",
            ),
        ),
    )

    schedule = scheduling.schedule_blocks(graph)

    assert tuple(group.blocks for group in schedule.groups) == (
        ("P0-TST-01", "P0-TST-02"),
    )
    assert len(schedule.waves) == 1
```

## Sources

- GitHub, [Functions in Python](https://codeql.github.com/docs/codeql-language-guides/functions-in-python/), documents CodeQL's Python declaration and call representations.
- Robert Tarjan, [Depth-First Search and Linear Graph Algorithms](https://doi.org/10.1137/0201010), supplies the linear-time SCC algorithm used here.
- Arthur Kahn, [Topological Sorting of Large Networks](https://doi.org/10.1145/368996.369025), supplies the zero-indegree ordering used for execution waves.
- Andrey Mokhov, Neil Mitchell, and Simon Peyton Jones, [Build Systems à la Carte](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/03/build-systems.pdf), separates dependency-respecting scheduling from rebuild decisions and motivates executing independent tasks concurrently.
