"""Compile and check exact source rename obligations."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from viper._contract_traceability import RepoSymbolRef
from viper._schema import SHA256, NonEmptyStr, ProtocolModel, RepoRelPath
from viper._system_impact.codeql import source_digest

from .models import (
    CodeQLExtractionSpec,
    CodeQLQuerySpec,
    SourceGraph,
    SourceGraphFormat,
    SourceNode,
    SourceSnapshot,
)

RenameTransitionStatus = Literal[
    "satisfied",
    "still_uses_old_target",
    "replacement_missing",
    "occurrence_mismatch",
    "analysis_unresolved",
]
ReferenceKind = Literal["imports", "calls", "reads", "writes"]
_SUPPORTED_EDGE_KINDS = frozenset({"imports", "calls", "reads", "writes"})
_MODULE_IMPORTS_SYMBOL = "<module imports>"


class RenameAnalysisError(ValueError):
    """Report an input that cannot support an exact rename decision."""


class RenameSpec(ProtocolModel):
    """Declare one repository symbol rename and its governed edge kinds."""

    old_target: RepoSymbolRef = Field(description="Declaration being renamed.")
    new_target: RepoSymbolRef = Field(description="Required replacement declaration.")
    edge_kinds: tuple[ReferenceKind, ...] = Field(
        min_length=1,
        description="Dependency operations that every governed caller must replace.",
    )

    @field_validator("edge_kinds")
    @classmethod
    def order_edge_kinds(
        cls, edge_kinds: tuple[ReferenceKind, ...]
    ) -> tuple[ReferenceKind, ...]:
        """Store each selected kind once in deterministic order."""
        if len(edge_kinds) != len(set(edge_kinds)):
            raise ValueError("RenameSpec.edge_kinds contains duplicates")
        return tuple(sorted(edge_kinds))

    @model_validator(mode="after")
    def validate_targets(self) -> RenameSpec:
        """Require two distinct top-level Python declarations."""
        if self.old_target == self.new_target:
            raise ValueError("RenameSpec targets must differ")
        if "." in self.old_target.symbol or "." in self.new_target.symbol:
            raise ValueError("RenameSpec supports top-level declarations")
        return self


class ReferenceSite(ProtocolModel):
    """Identify one binding-aware reference to a rename target."""

    dependent: RepoSymbolRef = Field(
        description="Declaration containing the reference."
    )
    kind: ReferenceKind = Field(description="Operation performed at the reference.")
    path: RepoRelPath = Field(description="Source file containing the reference.")
    line: int = Field(ge=1, description="One-based source line.")
    column: int = Field(ge=0, description="Zero-based UTF-8 source column.")


class RenameObligation(ProtocolModel):
    """Require one dependent to replace all baseline target references."""

    dependent: RepoSymbolRef = Field(description="Governed dependent declaration.")
    kind: ReferenceKind = Field(description="Governed dependency operation.")
    baseline_sites: tuple[ReferenceSite, ...] = Field(
        min_length=1,
        description="Exact baseline references that require replacements.",
    )

    @field_validator("baseline_sites")
    @classmethod
    def order_sites(cls, sites: tuple[ReferenceSite, ...]) -> tuple[ReferenceSite, ...]:
        """Store exact sites in source order."""
        return tuple(
            sorted(sites, key=lambda site: (site.path, site.line, site.column))
        )

    @model_validator(mode="after")
    def validate_sites(self) -> RenameObligation:
        """Require every site to belong to this obligation."""
        if any(
            site.dependent != self.dependent or site.kind != self.kind
            for site in self.baseline_sites
        ):
            raise ValueError("RenameObligation contains a foreign reference site")
        return self


class RenameObligationSet(ProtocolModel):
    """Bind compiled obligations to one baseline graph and checker."""

    spec: RenameSpec = Field(description="Rename whose references are governed.")
    baseline: SourceSnapshot = Field(description="Source snapshot scanned for duties.")
    baseline_graph_sha256: SHA256 = Field(
        description="Digest of the baseline SourceGraph rows."
    )
    extraction: CodeQLExtractionSpec = Field(
        description="CodeQL extraction identity used for the baseline graph."
    )
    query: CodeQLQuerySpec = Field(
        description="CodeQL query identity used for the baseline graph."
    )
    format: SourceGraphFormat = Field(
        description="SourceGraph lowering identity used for the baseline graph."
    )
    checker_sha256: SHA256 = Field(
        description="Digest of the loaded binding-aware checker implementation."
    )
    obligations: tuple[RenameObligation, ...] = Field(
        min_length=1,
        description="Mandatory dependency replacements in stable order.",
    )


class DependencyTransition(ProtocolModel):
    """Compare one baseline obligation with candidate old and new sites."""

    obligation: RenameObligation = Field(description="Baseline duty being checked.")
    candidate_old_sites: tuple[ReferenceSite, ...] = Field(
        description="Candidate references that still select the old target."
    )
    candidate_new_sites: tuple[ReferenceSite, ...] = Field(
        description="Candidate references that select the replacement target."
    )
    status: RenameTransitionStatus = Field(
        description="Exact outcome for this dependent and edge kind."
    )
    message: NonEmptyStr = Field(description="Reason for the transition outcome.")


class RenameCheck(ProtocolModel):
    """Record the complete decision for one candidate rename."""

    schema_version: Literal[1] = Field(default=1, description="Record format version.")
    obligations: RenameObligationSet = Field(
        description="Baseline duties and analysis identities."
    )
    candidate: SourceSnapshot = Field(description="Candidate source snapshot checked.")
    candidate_graph_sha256: SHA256 = Field(
        description="Digest of the candidate SourceGraph rows."
    )
    transitions: tuple[DependencyTransition, ...] = Field(
        description="One result for every baseline obligation."
    )
    unresolved: tuple[NonEmptyStr, ...] = Field(
        description="Analysis sites whose binding could not be decided."
    )
    passed: bool = Field(description="Whether the exact rename contract is satisfied.")

    @model_validator(mode="after")
    def validate_decision(self) -> RenameCheck:
        """Derive acceptance from complete, satisfied transition coverage."""
        expected = {
            (item.dependent.path, item.dependent.symbol, item.kind)
            for item in self.obligations.obligations
        }
        actual = {
            (
                item.obligation.dependent.path,
                item.obligation.dependent.symbol,
                item.obligation.kind,
            )
            for item in self.transitions
        }
        if actual != expected or len(actual) != len(self.transitions):
            raise ValueError(
                "RenameCheck transitions do not cover each obligation once"
            )
        accepted = not self.unresolved and all(
            item.status == "satisfied" for item in self.transitions
        )
        if self.passed != accepted:
            raise ValueError("RenameCheck.passed differs from its transition results")
        return self


def rename_checker_digest() -> str:
    """Hash the loaded implementation that compiles and checks obligations."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _module_name(path: str) -> str:
    """Convert one repository Python path into its importable module name."""
    pure = PurePosixPath(path)
    parts = list(pure.parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if not parts or not parts[-1].endswith(".py"):
        raise RenameAnalysisError(f"rename target is not a Python file: {path}")
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    if not parts:
        raise RenameAnalysisError(f"rename target has no importable module: {path}")
    return ".".join(parts)


def _node_index(graph: SourceGraph) -> dict[str, SourceNode]:
    """Index graph declarations by stable node identifier."""
    return {node.node_id: node for node in graph.nodes}


def _target_node(graph: SourceGraph, target: RepoSymbolRef) -> SourceNode | None:
    """Resolve one path-and-symbol target in a graph."""
    return next(
        (
            node
            for node in graph.nodes
            if node.path == target.path and node.symbol == target.symbol
        ),
        None,
    )


def _validate_graph_root(root: Path, graph: SourceGraph) -> None:
    """Require the scanned source bytes to equal the graph snapshot."""
    if source_digest(root) != graph.snapshot.source_sha256:
        raise RenameAnalysisError("SourceGraph snapshot differs from scanned source")


def compile_rename_obligations(
    *, root: Path, graph: SourceGraph, spec: RenameSpec
) -> RenameObligationSet:
    """Compile baseline incoming edges into exact, binding-aware obligations."""
    root = root.resolve()
    _validate_graph_root(root, graph)
    old_node = _target_node(graph, spec.old_target)
    if old_node is None:
        raise RenameAnalysisError("baseline graph does not contain the old target")
    nodes = _node_index(graph)
    selected: dict[
        tuple[RepoSymbolRef, ReferenceKind],
        dict[tuple[str, int, int], ReferenceSite],
    ] = {}

    def add_site(
        dependent: RepoSymbolRef, kind: ReferenceKind, site: ReferenceSite
    ) -> None:
        """Add one exact occurrence without duplicating overlapping queries."""
        selected.setdefault((dependent, kind), {})[
            (str(site.path), site.line, site.column)
        ] = site

    for edge in graph.edges:
        if edge.target != old_node.node_id or edge.kind not in spec.edge_kinds:
            continue
        if edge.kind not in _SUPPORTED_EDGE_KINDS:
            raise RenameAnalysisError(f"unsupported rename edge kind: {edge.kind}")
        owner = nodes[edge.source]
        reference_kind = edge.kind
        dependent = (
            RepoSymbolRef(path=edge.path, symbol=_MODULE_IMPORTS_SYMBOL)
            if reference_kind == "imports"
            else RepoSymbolRef(path=owner.path, symbol=owner.symbol)
        )
        site = ReferenceSite(
            dependent=dependent,
            kind=reference_kind,
            path=edge.path,
            line=edge.line,
            column=edge.column,
        )
        add_site(dependent, reference_kind, site)
    old_module = _module_name(str(spec.old_target.path))
    unresolved = [
        item
        for item in graph.references
        if item.resolution == "unresolved" and item.target_module == old_module
    ]
    if unresolved:
        rendered = "; ".join(
            f"{item.path}:{item.line}: {item.binding_form}" for item in unresolved
        )
        raise RenameAnalysisError(
            f"baseline binding analysis is unresolved: {rendered}"
        )
    for reference in graph.references:
        if (
            reference.resolution != "resolved"
            or reference.target_module != old_module
            or reference.target_symbol != spec.old_target.symbol
            or reference.kind not in spec.edge_kinds
            or reference.kind not in _SUPPORTED_EDGE_KINDS
        ):
            continue
        owner = nodes[reference.source]
        kind = reference.kind
        dependent = (
            RepoSymbolRef(path=reference.path, symbol=_MODULE_IMPORTS_SYMBOL)
            if kind == "imports"
            else RepoSymbolRef(path=owner.path, symbol=owner.symbol)
        )
        add_site(
            dependent,
            kind,
            ReferenceSite(
                dependent=dependent,
                kind=kind,
                path=reference.path,
                line=reference.line,
                column=reference.column,
            ),
        )
    if not selected:
        raise RenameAnalysisError("baseline graph contains no governed references")

    obligations: list[RenameObligation] = []
    for (dependent, kind), sites in sorted(
        selected.items(),
        key=lambda item: (
            item[0][0].path,
            item[0][0].symbol,
            item[0][1],
        ),
    ):
        obligations.append(
            RenameObligation(
                dependent=dependent,
                kind=kind,
                baseline_sites=tuple(sites.values()),
            )
        )
    receipt = graph.receipt
    return RenameObligationSet(
        spec=spec,
        baseline=graph.snapshot,
        baseline_graph_sha256=receipt.graph.sha256,
        extraction=receipt.database.extraction,
        query=receipt.query.query,
        format=receipt.graph.format,
        checker_sha256=rename_checker_digest(),
        obligations=tuple(obligations),
    )


def _transition(
    obligation: RenameObligation,
    *,
    old_sites: tuple[ReferenceSite, ...],
    new_sites: tuple[ReferenceSite, ...],
    unresolved: bool,
) -> DependencyTransition:
    """Classify one exact candidate dependency transition."""
    if unresolved:
        status: RenameTransitionStatus = "analysis_unresolved"
        message = "candidate binding analysis is unresolved"
    elif old_sites:
        status = "still_uses_old_target"
        message = f"candidate retains {len(old_sites)} old-target reference(s)"
    elif len(new_sites) < len(obligation.baseline_sites):
        status = "replacement_missing"
        message = (
            f"candidate has {len(new_sites)} replacement(s); "
            f"baseline requires {len(obligation.baseline_sites)}"
        )
    else:
        status = "satisfied"
        message = (
            f"candidate has {len(new_sites)} replacement(s) for "
            f"{len(obligation.baseline_sites)} governed reference(s)"
        )
    return DependencyTransition(
        obligation=obligation,
        candidate_old_sites=old_sites,
        candidate_new_sites=new_sites,
        status=status,
        message=message,
    )


def check_rename_obligations(
    *, root: Path, graph: SourceGraph, obligations: RenameObligationSet
) -> RenameCheck:
    """Verify that one candidate removes and replaces every baseline reference."""
    root = root.resolve()
    _validate_graph_root(root, graph)
    if obligations.checker_sha256 != rename_checker_digest():
        raise RenameAnalysisError("rename checker differs from compiled obligations")
    receipt = graph.receipt
    if (
        receipt.database.extraction != obligations.extraction
        or receipt.query.query != obligations.query
        or receipt.graph.format != obligations.format
    ):
        raise RenameAnalysisError("candidate graph uses a different analysis identity")
    if _target_node(graph, obligations.spec.old_target) is not None:
        raise RenameAnalysisError("candidate graph still contains the old declaration")
    if _target_node(graph, obligations.spec.new_target) is None:
        raise RenameAnalysisError(
            "candidate graph does not contain the new declaration"
        )

    nodes = {(node.path, node.symbol): node for node in graph.nodes}
    old_module = _module_name(str(obligations.spec.old_target.path))
    new_module = _module_name(str(obligations.spec.new_target.path))
    all_unresolved: list[str] = []
    transitions: list[DependencyTransition] = []
    for obligation in obligations.obligations:
        module_imports = obligation.dependent.symbol == _MODULE_IMPORTS_SYMBOL
        owner = nodes.get((obligation.dependent.path, obligation.dependent.symbol))
        if owner is None and not module_imports:
            transitions.append(
                _transition(
                    obligation,
                    old_sites=(),
                    new_sites=(),
                    unresolved=False,
                )
            )
            continue
        relevant = [
            item
            for item in graph.references
            if (
                item.path == obligation.dependent.path
                if module_imports
                else owner is not None and item.source == owner.node_id
            )
        ]
        failures = tuple(
            sorted(
                {
                    f"{item.path}:{item.line}: {item.binding_form}"
                    for item in relevant
                    if item.resolution == "unresolved"
                    and item.target_module in {old_module, new_module}
                }
            )
        )
        old_sites = tuple(
            ReferenceSite(
                dependent=obligation.dependent,
                kind=obligation.kind,
                path=item.path,
                line=item.line,
                column=item.column,
            )
            for item in relevant
            if item.resolution == "resolved"
            and item.target_module == old_module
            and item.target_symbol == obligations.spec.old_target.symbol
            and item.kind == obligation.kind
        )
        new_sites = tuple(
            ReferenceSite(
                dependent=obligation.dependent,
                kind=obligation.kind,
                path=item.path,
                line=item.line,
                column=item.column,
            )
            for item in relevant
            if item.resolution == "resolved"
            and item.target_module == new_module
            and item.target_symbol == obligations.spec.new_target.symbol
            and item.kind == obligation.kind
        )
        all_unresolved.extend(failures)
        transitions.append(
            _transition(
                obligation,
                old_sites=old_sites,
                new_sites=new_sites,
                unresolved=bool(failures),
            )
        )
    unresolved = tuple(sorted(set(all_unresolved)))
    return RenameCheck(
        obligations=obligations,
        candidate=graph.snapshot,
        candidate_graph_sha256=receipt.graph.sha256,
        transitions=tuple(transitions),
        unresolved=unresolved,
        passed=not unresolved
        and all(item.status == "satisfied" for item in transitions),
    )


def render_rename_check(check: RenameCheck) -> str:
    """Render a compact source-linked report for an agent or CLI."""
    total = sum(
        len(transition.obligation.baseline_sites) for transition in check.transitions
    )
    satisfied = sum(
        len(transition.obligation.baseline_sites)
        for transition in check.transitions
        if transition.status == "satisfied"
    )
    spec = check.obligations.spec
    lines = [
        (
            f"Rename: {spec.old_target.path}:{spec.old_target.symbol} -> "
            f"{spec.new_target.path}:{spec.new_target.symbol}"
        ),
        f"Satisfied: {satisfied}/{total} references",
    ]
    failures = [
        transition
        for transition in check.transitions
        if transition.status != "satisfied"
    ]
    lines.append(f"Unresolved: {len(failures) + len(check.unresolved)}")
    for index, transition in enumerate(failures, start=1):
        dependent = transition.obligation.dependent
        first = transition.obligation.baseline_sites[0]
        lines.extend(
            (
                "",
                f"{index}. {dependent.path}:{first.line} {dependent.symbol}",
                f"   {transition.status}: {transition.message}",
            )
        )
    lines.append("")
    lines.append(f"Completion: {'accepted' if check.passed else 'rejected'}")
    return "\n".join(lines)


__all__ = [
    "DependencyTransition",
    "ReferenceSite",
    "RenameAnalysisError",
    "RenameCheck",
    "RenameObligation",
    "RenameObligationSet",
    "RenameSpec",
    "check_rename_obligations",
    "compile_rename_obligations",
    "render_rename_check",
    "rename_checker_digest",
]
