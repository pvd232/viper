"""Compose contract targets into an isolated planned source tree."""

from __future__ import annotations

import ast
import hashlib
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from ._contract_traceability import (
    ContractTarget,
    ContractTraceabilityGraph,
    PairBlockId,
    TargetAction,
)
from ._schema import SHA256, NonEmptyStr, ProtocolModel
from ._system_impact.source import declaration_payload as _declaration_payload
from .system_impact import SourceGraph

ScheduleEdgeKind = Literal["declared", "source", "write_conflict"]


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
