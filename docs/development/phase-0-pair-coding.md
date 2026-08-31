# Phase 0 Pair-Coding Reference

This document contains the exact bounded edits scheduled by Phase 0 of the
[master execution checklist](master-execution-checklist.md).
The checklist decides order. Each `PairBlock` below supplies the code, target,
focused test, and completion gate for one checkbox.

## 1. PairBlock contract

Each checklist checkbox owns exactly one `PairBlock`. A block may change
several targets when splitting the edit leaves the code unable to compile.
Every dependency names an earlier block. The documentation
validator rejects duplicate ownership, missing blocks, unknown requirements,
unknown targets, dependency cycles, placeholders, and invalid Python.

```text
ContractRequirement
        |
        v
Phase 0 checkbox -> PairBlock -> exact source target
                         |              |
                         v              v
                   focused test -> completion gate
```

The implementation uses five ordinary data-structure operations:

1. Dictionaries join stable requirement, block, path, symbol, test, and gate
   identifiers.
2. A directed graph records `depends_on` edges between blocks.
3. A topological sort proves that every producer precedes its consumer.
4. Reverse adjacency traversal later finds the tests and contract surfaces
   affected by a changed source node.
5. Canonical JSON plus SHA-256 identifies one reviewed graph and permits exact
   set difference between revisions.

This workflow compares Phase 0 nodes through their stable identities. Graph
isomorphism applies later when two normalized experiment graphs lack shared IDs
and the question concerns structural equivalence. Exact revision identity uses
stable IDs and set difference.

### Audit boundary

Phase 0 uses two audit layers.

The deterministic layer parses markers, manifests, Python syntax, live imports,
model fields, dependencies, targets, tests, and gates. It reports exact
mismatches. The worked-example check now preserves one rejected fixture that
imports the retired `RuleImplementation` model and supplies the retired
`ContractRequirement.phase` field. The test must continue to reject both.

The semantic layer asks whether a surviving name, edge, or guarantee means the
same thing as the contract. A reviewer still owns that judgment until the
system graph can derive the affected-file closure. Every semantic defect found
during review must become a rejected fixture and a deterministic validator
before its review cycle closes. This rule turns a one-time inference into a
repeatable regression check.

## 2. Contract traceability

<!-- pair-block-definition: P0-CRT-01 -->
```toml pair-block
id = "P0-CRT-01"
requirements = ["CRT-01"]
targets = ["src/viper/_contract_traceability.py:_parse_requirement_markers", "src/viper/_contract_traceability.py:_parse_verifier_rules"]
tests = ["tests/test_documentation.py:test_contract_rules_map_to_owners_and_tests"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_rules_map_to_owners_and_tests -q"
depends_on = []
```

Add the imports, error, private row type, patterns, and both complete parsers
after `ContractTraceabilityGraph`.

```python pair-edit
import re
from dataclasses import dataclass
from pathlib import Path


class ContractTraceabilityError(ValueError):
    """Report an invalid or incomplete traceability declaration."""


@dataclass(frozen=True)
class _RequirementMarker:
    requirement: ContractRequirement
    phase: int
    test_path: str


_REQUIREMENT_ROW = re.compile(
    r"^\| (?P<label>[A-Z]{3}-\d{2}) "
    r"<!-- contract-requirement: (?P<requirement>[A-Z]{3}-\d{2}) "
    r"phase=(?P<phase>\d+) test=(?P<test>tests/[a-z0-9_/]+\.py) -->",
    re.MULTILINE,
)
_VERIFIER_RULE_ROW = re.compile(
    r"^\| `(?P<label>[a-z][a-z0-9_.]+)` "
    r"<!-- verifier-rule: (?P<rule>[a-z][a-z0-9_.]+) "
    r"requirement=(?P<requirement>[A-Z]{3}-\d{2}) --> "
    r"\| (?P<statement>.+?) \|$",
    re.MULTILINE,
)


def _duplicates(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(value for value in set(values) if values.count(value) > 1))


def _parse_requirement_markers(
    root: Path,
    contract: Path,
) -> tuple[_RequirementMarker, ...]:
    contract_path = contract.relative_to(root).as_posix()
    markers: list[_RequirementMarker] = []
    for match in _REQUIREMENT_ROW.finditer(contract.read_text(encoding="utf-8")):
        label = match.group("label")
        requirement_id = match.group("requirement")
        if label != requirement_id:
            raise ContractTraceabilityError(
                f"requirement label {label} does not match {requirement_id}"
            )
        markers.append(
            _RequirementMarker(
                requirement=ContractRequirement(
                    requirement_id=requirement_id,
                    contract=contract_path,
                ),
                phase=int(match.group("phase")),
                test_path=match.group("test"),
            )
        )
    if not markers:
        raise ContractTraceabilityError(
            f"{contract_path} declares no contract requirements"
        )
    duplicate_ids = _duplicates(
        [marker.requirement.requirement_id for marker in markers]
    )
    if duplicate_ids:
        raise ContractTraceabilityError(
            f"duplicate requirements in {contract_path}: {duplicate_ids}"
        )
    return tuple(sorted(markers, key=lambda item: item.requirement.requirement_id))


def _parse_verifier_rules(
    root: Path,
    contract: Path,
    requirements: tuple[_RequirementMarker, ...],
) -> tuple[VerifierRule, ...]:
    contract_path = contract.relative_to(root).as_posix()
    requirement_ids = {
        marker.requirement.requirement_id for marker in requirements
    }
    rules: list[VerifierRule] = []
    for match in _VERIFIER_RULE_ROW.finditer(contract.read_text(encoding="utf-8")):
        label = match.group("label")
        rule_id = match.group("rule")
        requirement_id = match.group("requirement")
        if label != rule_id:
            raise ContractTraceabilityError(
                f"verifier-rule label {label} does not match {rule_id}"
            )
        if requirement_id not in requirement_ids:
            raise ContractTraceabilityError(
                f"{rule_id} names unknown requirement {requirement_id}"
            )
        rules.append(
            VerifierRule(
                rule_id=rule_id,
                requirement_id=requirement_id,
                contract=contract_path,
                statement=match.group("statement"),
            )
        )
    duplicate_ids = _duplicates([rule.rule_id for rule in rules])
    if duplicate_ids:
        raise ContractTraceabilityError(
            f"duplicate verifier rules in {contract_path}: {duplicate_ids}"
        )
    uncovered = requirement_ids - {rule.requirement_id for rule in rules}
    if uncovered:
        raise ContractTraceabilityError(
            f"requirements without verifier rules in {contract_path}: {sorted(uncovered)}"
        )
    return tuple(sorted(rules, key=lambda item: item.rule_id))
```

<!-- pair-block-definition: P0-CRT-02 -->
```toml pair-block
id = "P0-CRT-02"
requirements = ["CRT-02"]
targets = ["src/viper/_contract_traceability.py:_parse_rule_edges"]
tests = ["tests/test_documentation.py:test_contract_rules_map_to_owners_and_tests"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_rules_map_to_owners_and_tests -q"
depends_on = ["P0-CRT-01"]
```

Add the checklist edge parser after the declaration parsers.

```python pair-edit
import ast


_PHASE_HEADING = re.compile(r"^## \d+\. Phase (?P<phase>\d+)\b", re.MULTILINE)
_RULE_EDGE = re.compile(
    r"<!-- contract-(?P<kind>implementation|verification): "
    r"requirement=(?P<requirement>[A-Z]{3}-\d{2}) "
    r"rule=(?P<rule>[a-z][a-z0-9_.]+) "
    r"state=(?P<state>planned|implemented) "
    r"(?P<label>owner|test)=(?P<target>[^ ]+) -->"
)


def _parse_repo_symbol(value: str) -> RepoSymbolRef:
    path, separator, symbol = value.partition(":")
    if not separator or not path or not symbol:
        raise ContractTraceabilityError(
            f"source reference must use path:symbol: {value}"
        )
    return RepoSymbolRef(path=path, symbol=symbol)


def _python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(f"{node.name}.{member.name}")
    return symbols


def _require_python_symbol(root: Path, target: RepoSymbolRef) -> None:
    path = root / target.path
    if not path.is_file():
        raise ContractTraceabilityError(f"source file is missing: {target.path}")
    if target.symbol not in _python_symbols(path):
        raise ContractTraceabilityError(
            f"source symbol is missing: {target.path}:{target.symbol}"
        )


def _parse_rule_edges(
    root: Path,
    checklist: Path,
    requirements: tuple[_RequirementMarker, ...],
    rules: tuple[VerifierRule, ...],
) -> tuple[RuleEdge, ...]:
    text = checklist.read_text(encoding="utf-8")
    phases = tuple(_PHASE_HEADING.finditer(text))
    requirement_by_id = {
        item.requirement.requirement_id: item for item in requirements
    }
    rule_by_id = {rule.rule_id: rule for rule in rules}
    edges: list[RuleEdge] = []
    for index, phase_match in enumerate(phases):
        phase = int(phase_match.group("phase"))
        end = phases[index + 1].start() if index + 1 < len(phases) else len(text)
        section = text[phase_match.end():end]
        for match in _RULE_EDGE.finditer(section):
            requirement_id = match.group("requirement")
            rule_id = match.group("rule")
            kind = match.group("kind")
            expected_label = "owner" if kind == "implementation" else "test"
            if match.group("label") != expected_label:
                raise ContractTraceabilityError(
                    f"{kind} edge requires {expected_label}= target"
                )
            requirement = requirement_by_id.get(requirement_id)
            rule = rule_by_id.get(rule_id)
            if requirement is None or rule is None:
                raise ContractTraceabilityError(
                    f"unknown requirement-rule edge: {requirement_id}:{rule_id}"
                )
            if rule.requirement_id != requirement_id:
                raise ContractTraceabilityError(
                    f"{rule_id} does not belong to {requirement_id}"
                )
            if requirement.phase != phase:
                raise ContractTraceabilityError(
                    f"{requirement_id} belongs to phase {requirement.phase}, not {phase}"
                )
            target = _parse_repo_symbol(match.group("target"))
            state = match.group("state")
            if state == "implemented":
                _require_python_symbol(root, target)
            edges.append(
                RuleEdge(
                    kind=kind,
                    rule_id=rule_id,
                    phase=phase,
                    checklist_line=text.count("\n", 0, phase_match.end() + match.start()) + 1,
                    state=state,
                    target=target,
                )
            )
    keys = [(edge.kind, edge.rule_id, edge.target) for edge in edges]
    if len(keys) != len(set(keys)):
        raise ContractTraceabilityError("duplicate rule edge")
    for rule_id in rule_by_id:
        kinds = {edge.kind for edge in edges if edge.rule_id == rule_id}
        if kinds != {"implementation", "verification"}:
            raise ContractTraceabilityError(
                f"{rule_id} requires implementation and verification edges"
            )
    order = {"implementation": 0, "verification": 1}
    return tuple(
        sorted(
            edges,
            key=lambda edge: (
                edge.rule_id,
                order[edge.kind],
                edge.target.path,
                edge.target.symbol,
            ),
        )
    )
```

<!-- pair-block-definition: P0-CRT-03 -->
```toml pair-block
id = "P0-CRT-03"
requirements = ["CRT-03"]
targets = ["src/viper/_contract_traceability.py:parse_contract_traces", "src/viper/_contract_traceability.py:validate_contract_example"]
tests = ["tests/test_documentation.py:test_contract_traces_are_populated", "tests/test_documentation.py:test_phase_zero_contracts_show_three_dags_and_instantiate_models"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k 'contract_traces_are_populated or phase_zero_contracts_show_three_dags' -q"
depends_on = ["P0-CRT-02"]
```

Move the existing trace-fence, model-construction, and Mermaid checks from the
documentation oracle into these production operations. Keep the oracle until
parity passes.

```python pair-edit
import tomllib
from collections.abc import Mapping


_TRACE_FENCE = re.compile(
    r"`{3,4}toml contract-trace\n(?P<body>.*?)\n`{3,4}",
    re.DOTALL,
)
_PLACEHOLDER = re.compile(r"(?:\.\.\.|\bTBD\b|\bTODO\b|<[^>]+>)")


def _trace_mapping(raw: Mapping[str, object]) -> dict[str, object]:
    value = dict(raw)
    value["implementation"] = _parse_repo_symbol(str(value["implementation"]))
    value["test"] = _parse_repo_symbol(str(value["test"]))
    outcome = dict(value["outcome"])
    if outcome.get("kind") == "rejected":
        outcome["rejected_at"] = _parse_repo_symbol(str(outcome["rejected_at"]))
    value["outcome"] = outcome
    return value


def parse_contract_traces(root: Path, contract: Path) -> tuple[ContractTrace, ...]:
    text = contract.read_text(encoding="utf-8")
    traces: list[ContractTrace] = []
    for match in _TRACE_FENCE.finditer(text):
        body = match.group("body")
        if _PLACEHOLDER.search(body):
            raise ContractTraceabilityError(
                f"trace contains a placeholder: {contract.relative_to(root)}"
            )
        traces.append(ContractTrace.model_validate(_trace_mapping(tomllib.loads(body))))
    trace_ids = [trace.trace_id for trace in traces]
    if _duplicates(trace_ids):
        raise ContractTraceabilityError("duplicate trace IDs")
    kinds = {trace.outcome.kind for trace in traces}
    if kinds != {"accepted", "rejected"}:
        raise ContractTraceabilityError(
            f"{contract.relative_to(root)} requires accepted and rejected traces"
        )
    return tuple(sorted(traces, key=lambda item: item.trace_id))


def validate_contract_example(contract: Path, model_names: tuple[str, ...]) -> None:
    text = contract.read_text(encoding="utf-8")
    section_three = text.split("## 3.", 1)[1].split("## 4.", 1)[0]
    diagrams = re.findall(r"```mermaid\n(.*?)\n```", section_three, re.DOTALL)
    if len(diagrams) != 3 or any("-->" not in diagram for diagram in diagrams):
        raise ContractTraceabilityError(
            f"{contract.name} requires current, proposed-change, and integrated DAGs"
        )
    example_match = re.search(
        r"<!-- contract-worked-example: start -->(.*?)"
        r"<!-- contract-worked-example: end -->",
        text,
        re.DOTALL,
    )
    if example_match is None:
        raise ContractTraceabilityError(
            f"{contract.name} requires one marked worked example"
        )
    example = example_match.group(1)
    for model_name in model_names:
        if re.search(rf"\b{re.escape(model_name)}\s*\(", example) is None:
            raise ContractTraceabilityError(
                f"worked example does not instantiate {model_name}"
            )
```

<!-- pair-block-definition: P0-CRT-04 -->
```toml pair-block
id = "P0-CRT-04"
requirements = ["CRT-03"]
targets = ["tests/test_documentation.py:CONTRACTS_WITH_COMPLETE_EXAMPLES"]
tests = ["tests/test_documentation.py:test_phase_zero_contracts_show_three_dags_and_instantiate_models"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k phase_zero_contracts_show_three_dags_and_instantiate_models -q"
depends_on = ["P0-CRT-03"]
```

Expand the validated contract set only after every contract has the required
three diagrams and complete worked example.

```python pair-edit
CONTRACTS_WITH_COMPLETE_EXAMPLES = IMPLEMENTATION_CONTRACTS
```

<!-- pair-block-definition: P0-CRT-05 -->
```toml pair-block
id = "P0-CRT-05"
requirements = ["CRT-04"]
targets = ["src/viper/_contract_traceability.py:compile_contract_traceability", "src/viper/_contract_traceability.py:serialize_contract_traceability"]
tests = ["tests/test_documentation.py:test_contract_traceability_graph_is_canonical"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_traceability_graph_is_canonical -q"
depends_on = ["P0-CRT-03", "P0-CRT-04"]
```

Compile the joined records and serialize their canonical representation.

```python pair-edit
import json


def serialize_contract_traceability(graph: ContractTraceabilityGraph) -> bytes:
    return json.dumps(
        graph.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compile_contract_traceability(
    root: Path,
    checklist: Path,
    contracts: tuple[Path, ...],
) -> ContractTraceabilityGraph:
    markers = tuple(
        marker
        for contract in contracts
        for marker in _parse_requirement_markers(root, contract)
    )
    requirements = tuple(marker.requirement for marker in markers)
    if _duplicates([item.requirement_id for item in requirements]):
        raise ContractTraceabilityError("requirement ID belongs to several contracts")
    rules = tuple(
        rule
        for contract in contracts
        for rule in _parse_verifier_rules(
            root,
            contract,
            tuple(
                marker
                for marker in markers
                if marker.requirement.contract == contract.relative_to(root).as_posix()
            ),
        )
    )
    if _duplicates([item.rule_id for item in rules]):
        raise ContractTraceabilityError("verifier-rule ID belongs to several contracts")
    traces = tuple(
        trace for contract in contracts for trace in parse_contract_traces(root, contract)
    )
    graph = ContractTraceabilityGraph(
        requirements=tuple(sorted(requirements, key=lambda item: item.requirement_id)),
        rules=tuple(sorted(rules, key=lambda item: item.rule_id)),
        edges=_parse_rule_edges(root, checklist, markers, rules),
        traces=tuple(sorted(traces, key=lambda item: item.trace_id)),
    )
    serialize_contract_traceability(graph)
    return graph
```

## 3. Project root

<!-- pair-block-definition: P0-PDR-01 -->
```toml pair-block
id = "P0-PDR-01"
requirements = ["PDR-01"]
targets = ["src/viper/project.py:ProjectSettings", "src/viper/project.py:find_project_root", "src/viper/project.py:resolve_project_root"]
tests = ["tests/test_project_init.py:test_init_project_establishes_discoverable_root"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py -k establishes_discoverable_root -q"
depends_on = ["P0-CRT-05"]
```

Create `src/viper/project.py` with the root marker model and resolver.

```python pair-edit
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1


class ProjectRootError(ValueError):
    """Report a missing, invalid, or incompatible project root."""


def find_project_root(start: Path) -> Path:
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "viper.toml").is_file():
            return directory
    raise ProjectRootError(f"no viper.toml found from {start}")


def _require_git_work_tree(root: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProjectRootError(f"project root is not in a Git work tree: {root}")
    if Path(completed.stdout.strip()).resolve() != root:
        raise ProjectRootError(f"viper.toml must be at the Git work-tree root: {root}")


def resolve_project_root(root: Path | None = None) -> Path:
    resolved = find_project_root(root if root is not None else Path.cwd())
    marker = resolved / "viper.toml"
    try:
        settings = ProjectSettings.model_validate(
            tomllib.loads(marker.read_text(encoding="utf-8")).get("project", {})
        )
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        raise ProjectRootError(f"invalid project marker: {marker}") from error
    if settings.schema_version != 1:
        raise ProjectRootError(
            f"unsupported project schema version: {settings.schema_version}"
        )
    _require_git_work_tree(resolved)
    return resolved
```

<!-- pair-block-definition: P0-PDR-02 -->
```toml pair-block
id = "P0-PDR-02"
requirements = ["PDR-01"]
targets = ["src/viper/project_init.py:add_project_root_files"]
tests = ["tests/test_project_init.py:test_init_project_establishes_discoverable_root"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py -k establishes_discoverable_root -q"
depends_on = ["P0-PDR-01"]
```

Add these exact entries to the mapping returned by `_project_files()`.

```python pair-edit
PROJECT_ROOT_FILES = {
    "viper.toml": "[project]\nschema_version = 1\n",
    "inputs/.gitkeep": "",
    "benchmarks/README.md": "# Benchmarks\n",
    "experiments/README.md": "# Experiments\n",
}


def add_project_root_files(files: dict[str, str]) -> dict[str, str]:
    overlap = files.keys() & PROJECT_ROOT_FILES.keys()
    if overlap:
        raise ProjectInitializationError(
            f"project scaffold duplicates reserved paths: {sorted(overlap)}"
        )
    return {**files, **PROJECT_ROOT_FILES}
```

Call `add_project_root_files(files)` immediately before `_project_files()`
returns.

<!-- pair-block-definition: P0-PDR-03 -->
```toml pair-block
id = "P0-PDR-03"
requirements = ["PDR-02"]
targets = ["src/viper/api.py:_resolve_operation_root", "src/viper/_api/handlers.py:handle_freeze"]
tests = ["tests/test_storage.py:test_store_uses_selected_project_root"]
gate = "conda run -n mantra python -m pytest tests/test_storage.py -k uses_selected_project_root -q"
depends_on = ["P0-PDR-01"]
```

Resolve the public input once. Internal handlers receive the canonical path.

```python pair-edit
from viper.project import resolve_project_root


def _resolve_operation_root(root: Path | None) -> Path:
    return resolve_project_root(root)


def handle_freeze(request: FreezeRunPlanRequest) -> ViperResult:
    root = _resolve_operation_root(request.root)
    draft = load_run_plan_draft(root, request.draft)
    return freeze_run_plan(root, draft)
```

Apply the same `root = _resolve_operation_root(request.root)` boundary to each
public filesystem operation. Internal helpers receive that one resolved value.

<!-- pair-block-definition: P0-PDR-04 -->
```toml pair-block
id = "P0-PDR-04"
requirements = ["PDR-04"]
targets = ["src/viper/cli.py:add_root_argument", "src/viper/api.py:RunRequest"]
tests = ["tests/test_documentation.py:test_project_root_vocabulary"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k project_root_vocabulary -q"
depends_on = ["P0-PDR-03"]
```

Use `root` at public boundaries and `project_root` for the resolved internal
value.

```python pair-edit
class RunRequest(APIModel):
    root: Path | None = None


def add_root_argument(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="VIPER project root; defaults to discovery from the current directory",
    )
```

Delete `--repository-root`, `repository_root`, `left_repository_root`, and
`right_repository_root` from public request and CLI surfaces. Comparison
operations use `left_root` and `right_root`.

<!-- pair-block-definition: P0-PDR-05 -->
```toml pair-block
id = "P0-PDR-05"
requirements = ["PDR-02"]
targets = ["src/viper/storage.py:LocalArtifactStore.__init__"]
tests = ["tests/test_storage.py:test_store_uses_selected_project_root"]
gate = "conda run -n mantra python -m pytest tests/test_storage.py -k uses_selected_project_root -q"
depends_on = ["P0-PDR-01", "P0-PDR-03"]
```

Replace the constructor with the shared project-root boundary.

```python pair-edit
from .project import resolve_project_path


class LocalArtifactStore:
    def __init__(self, project_root: Path, store: RepoRelPath = ".viper/store"):
        self.project_root = project_root
        self.store = store
        self.store_root = resolve_project_path(
            project_root,
            store,
            operation="write",
            allow_missing=True,
        )
```

Rename internal `repository_root` attributes to `project_root`. Preserve the
persisted `LocalFileRef.store` value `.viper/store`.

<!-- pair-block-definition: P0-PDR-06 -->
```toml pair-block
id = "P0-PDR-06"
requirements = ["PDR-03"]
targets = ["src/viper/project.py:resolve_project_path"]
tests = ["tests/test_validation_architecture.py:test_project_paths_reject_symlinks"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k project_paths_reject_symlinks -q"
depends_on = ["P0-PDR-01"]
```

Add the path resolver to `src/viper/project.py`.

```python pair-edit
from typing import Literal

from viper._schema import RepoRelPath


PathOperation = Literal["read", "write"]


def resolve_project_path(
    project_root: Path,
    path: RepoRelPath,
    *,
    operation: PathOperation,
    allow_missing: bool = False,
) -> Path:
    root = project_root.resolve(strict=True)
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProjectRootError(f"project path escapes ROOT: {path}")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ProjectRootError(f"project path contains a symlink: {path}")
        if not current.exists():
            break
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ProjectRootError(f"resolved project path escapes ROOT: {path}")
    if operation == "read" and not allow_missing and not resolved.is_file():
        raise ProjectRootError(f"project file is missing: {path}")
    if operation == "write" and not allow_missing and not resolved.parent.is_dir():
        raise ProjectRootError(f"project parent is missing: {path}")
    return resolved
```

## 4. System graph

<!-- pair-block-definition: P0-SIG-01 -->
```toml pair-block
id = "P0-SIG-01"
requirements = ["SIG-01"]
targets = ["src/viper/system_graph.py:PairBlock", "src/viper/system_graph.py:SystemGraph", "src/viper/system_graph.py:SystemCondensationDAG", "src/viper/system_graph.py:SystemGraphDelta", "src/viper/system_graph.py:ImpactReport"]
tests = ["tests/test_documentation.py:test_phase_zero_system_models_match_contract", "tests/test_validation_architecture.py:test_system_graph_inventory_and_edges_are_auditable"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py tests/test_validation_architecture.py -k 'phase_zero_system_models_match_contract or system_graph_inventory_and_edges_are_auditable' -q"
depends_on = ["P0-CRT-05", "P0-PDR-01"]
```

Create `src/viper/system_graph.py` with this complete model slice and canonical
serialization boundary.

```python pair-edit
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Self

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from ._contract_traceability import RequirementId, RepoSymbolRef, RuleEdge
from ._schema import GitCommit, NonEmptyStr, ProtocolModel, RepoRelPath, SHA256
from .references import ResolvedFileRef


SystemNodeId = Annotated[str, StringConstraints(min_length=1)]
SystemComponentId = SHA256
PairBlockId = Annotated[
    str,
    StringConstraints(pattern=r"^P0-[A-Z]+-[0-9]{2}$"),
]
SystemNodeKind = Literal["file", "span", "external"]
SystemNodeRole = Literal[
    "python_module",
    "python_symbol",
    "python_field",
    "public_export",
    "configuration",
    "fixture",
    "generated_source",
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
    "implementation_block",
    "completion_gate",
    "acceptance_test",
    "installed_package",
    "context_variable",
    "context_file",
    "context_command",
]
SystemEdgeKind = Literal[
    "defines",
    "defined_in",
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
    "enforces",
    "implements",
    "tests",
    "documents",
    "resolves",
    "launches",
    "changes",
    "depends_on",
    "gates_on",
]
ResolutionKind = Literal[
    "dynamic_import",
    "decorator_registration",
    "registry_entry",
    "reflection_target",
    "subprocess_entrypoint",
]
EdgeOrigin = Literal["declared", "static", "observed"]
FileAnalysisStatus = Literal["parsed", "opaque", "excluded"]
PropagationAction = Literal["change", "remove", "retain"]


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


class SystemSource(ProtocolModel):
    repository: HttpUrl
    commit: GitCommit


class RepositoryFile(ProtocolModel):
    path: RepoRelPath
    sha256: SHA256
    bytes: int = Field(ge=0)


class FileAnalysisReceipt(ProtocolModel):
    path: RepoRelPath
    file_sha256: SHA256
    analyzer: NonEmptyStr
    status: FileAnalysisStatus
    emitted_nodes: tuple[SystemNodeId, ...]
    emitted_edges: tuple[SHA256, ...]
    reason: NonEmptyStr | None = None


class PairBlock(ProtocolModel):
    block_id: PairBlockId
    document: RepoRelPath
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    sha256: SHA256
    requirements: tuple[RequirementId, ...] = Field(min_length=1)
    targets: tuple[RepoSymbolRef, ...] = Field(min_length=1)
    tests: tuple[RepoSymbolRef, ...] = Field(min_length=1)
    gate: NonEmptyStr
    depends_on: tuple[PairBlockId, ...]


class SystemNode(ProtocolModel):
    node_id: SystemNodeId
    kind: SystemNodeKind
    roles: tuple[SystemNodeRole, ...] = Field(min_length=1)
    path: RepoRelPath | None = None
    symbol: NonEmptyStr | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    sha256: SHA256 | None = None

    @model_validator(mode="after")
    def validate_source_identity(self) -> Self:
        if self.kind == "file":
            if self.path is None or self.sha256 is None:
                raise ValueError("file node requires path and sha256")
            if any(
                value is not None
                for value in (self.symbol, self.start_line, self.end_line)
            ):
                raise ValueError("file node omits symbol and line fields")
        elif self.kind == "span":
            required = (
                self.path,
                self.symbol,
                self.start_line,
                self.end_line,
                self.sha256,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "span node requires path, symbol, lines, and sha256"
                )
            if self.start_line > self.end_line:
                raise ValueError("span node starts after it ends")
        elif self.kind == "external":
            if self.symbol is None:
                raise ValueError("external node requires symbol")
            if any(
                value is not None
                for value in (
                    self.path,
                    self.start_line,
                    self.end_line,
                    self.sha256,
                )
            ):
                raise ValueError(
                    "external node omits repository source fields"
                )
        return self


class SourceEvidence(ProtocolModel):
    kind: Literal["source"] = "source"
    path: RepoRelPath
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    expression: NonEmptyStr


class ResolutionEvidence(ProtocolModel):
    kind: Literal["resolution"] = "resolution"
    resolution_id: SHA256


EdgeEvidence = Annotated[
    SourceEvidence | ResolutionEvidence,
    Field(discriminator="kind"),
]


class SystemEdge(ProtocolModel):
    edge_id: SHA256
    source: SystemNodeId
    target: SystemNodeId
    kind: SystemEdgeKind
    origin: EdgeOrigin
    evidence: EdgeEvidence


class ResolutionAttempt(ProtocolModel):
    resolution_id: SHA256
    kind: ResolutionKind
    source: SystemNodeId
    expression: NonEmptyStr


class ResolutionObservation(ProtocolModel):
    attempt: ResolutionAttempt
    target: SystemNodeId
    edge: SystemEdge


class UnresolvedDependency(ProtocolModel):
    attempt: ResolutionAttempt
    reason: NonEmptyStr


class SystemGraph(ProtocolModel):
    schema_version: Literal[1] = 1
    source: SystemSource
    context_sha256: SHA256
    contract_traceability_sha256: SHA256
    inventory: tuple[RepositoryFile, ...] = Field(min_length=1)
    analyses: tuple[FileAnalysisReceipt, ...] = Field(min_length=1)
    nodes: tuple[SystemNode, ...] = Field(min_length=1)
    edges: tuple[SystemEdge, ...]
    observations: tuple[ResolutionObservation, ...]
    unresolved: tuple[UnresolvedDependency, ...]


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
    affected_requirements: tuple[RequirementId, ...]
    affected_implementations: tuple[RuleEdge, ...]
    observing_tests: tuple[RuleEdge, ...]
    unresolved: tuple[UnresolvedDependency, ...]
    complete: bool


class PropagationDisposition(ProtocolModel):
    path: RepoRelPath
    action: PropagationAction
    affected_nodes: tuple[SystemNodeId, ...] = Field(min_length=1)
    statement: NonEmptyStr


class PlannedAddition(ProtocolModel):
    path: RepoRelPath
    purpose: NonEmptyStr
    requirements: tuple[RequirementId, ...] = Field(min_length=1)


class PropagationPlan(ProtocolModel):
    schema_version: Literal[1] = 1
    impact: ResolvedFileRef
    dispositions: tuple[PropagationDisposition, ...] = Field(min_length=1)
    planned_additions: tuple[PlannedAddition, ...]


def canonical_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
```

Every persisted model field receives the exact role description stated in the
contract before this block closes.

<!-- pair-block-definition: P0-SIG-02 -->
```toml pair-block
id = "P0-SIG-02"
requirements = ["SIG-01"]
targets = ["src/viper/system_graph.py:inventory_source"]
tests = ["tests/test_validation_architecture.py:test_system_graph_inventory_and_edges_are_auditable"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_inventory_and_edges_are_auditable -q"
depends_on = ["P0-SIG-01"]
```

Use the selected commit's Git tree objects as the finite source inventory.

```python pair-edit
import subprocess
from pathlib import Path


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def inventory_source(root: Path, commit: str) -> tuple[RepositoryFile, ...]:
    paths = tuple(
        path
        for path in _git(root, "ls-tree", "-r", "--name-only", "-z", commit)
        .decode("utf-8")
        .split("\0")
        if path
    )
    inventory: list[RepositoryFile] = []
    for path in paths:
        raw = _git(root, "show", f"{commit}:{path}")
        inventory.append(
            RepositoryFile(
                path=path,
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
            )
        )
    return tuple(sorted(inventory, key=lambda item: item.path))


def file_node(item: RepositoryFile) -> SystemNode:
    return SystemNode(
        node_id=f"file:{item.path}",
        kind="file",
        roles=("generated_source",),
        path=item.path,
        sha256=item.sha256,
    )
```

The analyzer replaces the provisional `generated_source` role with the sorted
roles derived from the file kind before graph publication.

<!-- pair-block-definition: P0-SIG-03 -->
```toml pair-block
id = "P0-SIG-03"
requirements = ["SIG-01"]
targets = ["src/viper/system_graph.py:analyze_python"]
tests = ["tests/test_validation_architecture.py:test_system_graph_inventory_and_edges_are_auditable"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_inventory_and_edges_are_auditable -q"
depends_on = ["P0-SIG-02"]
```

Start semantic extraction with exact Python definition spans. Add the Markdown,
TOML, pytest, `__all__`, and checklist analyzers through the same return type.

```python pair-edit
import ast


def _source_span(raw: bytes, start_line: int, end_line: int) -> bytes:
    lines = raw.splitlines(keepends=True)
    return b"".join(lines[start_line - 1:end_line])


def analyze_python(item: RepositoryFile, raw: bytes) -> tuple[tuple[SystemNode, ...], tuple[SystemEdge, ...]]:
    tree = ast.parse(raw, filename=item.path)
    nodes: list[SystemNode] = []
    edges: list[SystemEdge] = []
    file_id = f"file:{item.path}"
    for declaration in ast.walk(tree):
        if not isinstance(declaration, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        symbol = declaration.name
        node_id = f"span:{item.path}:{symbol}"
        end_line = declaration.end_lineno or declaration.lineno
        node = SystemNode(
            node_id=node_id,
            kind="span",
            roles=("python_symbol",),
            path=item.path,
            symbol=symbol,
            start_line=declaration.lineno,
            end_line=end_line,
            sha256=hashlib.sha256(
                _source_span(raw, declaration.lineno, end_line)
            ).hexdigest(),
        )
        evidence = SourceEvidence(
            path=item.path,
            start_line=declaration.lineno,
            end_line=end_line,
            expression=symbol,
        )
        edge_payload = {
            "source": node_id,
            "target": file_id,
            "kind": "defined_in",
            "origin": "static",
            "evidence": evidence.model_dump(mode="json"),
        }
        nodes.append(node)
        edges.append(SystemEdge(edge_id=canonical_sha256(edge_payload), **edge_payload))
    return (
        tuple(sorted(nodes, key=lambda node: node.node_id)),
        tuple(sorted(edges, key=lambda edge: edge.edge_id)),
    )
```

Each additional analyzer must emit one `FileAnalysisReceipt` whose
`emitted_nodes` and `emitted_edges` exactly equal its returned IDs.

<!-- pair-block-definition: P0-SIG-04 -->
```toml pair-block
id = "P0-SIG-04"
requirements = ["SIG-04"]
targets = ["src/viper/system_graph.py:compile_pair_blocks", "src/viper/system_graph.py:topological_pair_blocks", "src/viper/system_graph.py:ingest_contract_traceability", "src/viper/system_graph.py:ingest_pair_blocks"]
tests = ["tests/test_documentation.py:test_system_graph_preserves_contract_traceability", "tests/test_documentation.py:test_phase_zero_checkboxes_have_complete_ordered_pair_blocks"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k system_graph_preserves_contract_traceability -q"
depends_on = ["P0-CRT-05", "P0-SIG-03"]
```

Preserve the exact requirement, rule, implementation, and verification joins.

```python pair-edit
def ingest_contract_traceability(
    traceability: ContractTraceabilityGraph,
) -> tuple[tuple[SystemNode, ...], tuple[SystemEdge, ...]]:
    nodes: dict[str, SystemNode] = {}
    edges: list[SystemEdge] = []
    for requirement in traceability.requirements:
        node_id = f"span:{requirement.contract}:requirement:{requirement.requirement_id}"
        nodes[node_id] = SystemNode(
            node_id=node_id,
            kind="span",
            roles=("contract_requirement",),
            path=requirement.contract,
            symbol=requirement.requirement_id,
            start_line=1,
            end_line=1,
            sha256=canonical_sha256(requirement),
        )
    for rule in traceability.rules:
        rule_id = f"span:{rule.contract}:rule:{rule.rule_id}"
        requirement = next(
            item for item in traceability.requirements
            if item.requirement_id == rule.requirement_id
        )
        requirement_id = (
            f"span:{requirement.contract}:requirement:{requirement.requirement_id}"
        )
        nodes[rule_id] = SystemNode(
            node_id=rule_id,
            kind="span",
            roles=("verifier_rule",),
            path=rule.contract,
            symbol=rule.rule_id,
            start_line=1,
            end_line=1,
            sha256=canonical_sha256(rule),
        )
        payload = {
            "source": rule_id,
            "target": requirement_id,
            "kind": "enforces",
            "origin": "declared",
            "evidence": SourceEvidence(
                path=rule.contract,
                start_line=1,
                end_line=1,
                expression=rule.rule_id,
            ).model_dump(mode="json"),
        }
        edges.append(SystemEdge(edge_id=canonical_sha256(payload), **payload))
    for link in traceability.edges:
        target_id = f"span:{link.target.path}:{link.target.symbol}"
        rule = next(item for item in traceability.rules if item.rule_id == link.rule_id)
        rule_id = f"span:{rule.contract}:rule:{rule.rule_id}"
        relation = "implements" if link.kind == "implementation" else "tests"
        payload = {
            "source": target_id,
            "target": rule_id,
            "kind": relation,
            "origin": "declared",
            "evidence": SourceEvidence(
                path=link.target.path,
                start_line=link.checklist_line,
                end_line=link.checklist_line,
                expression=link.target.symbol,
            ).model_dump(mode="json"),
        }
        edges.append(SystemEdge(edge_id=canonical_sha256(payload), **payload))
    return (
        tuple(sorted(nodes.values(), key=lambda node: node.node_id)),
        tuple(sorted(edges, key=lambda edge: edge.edge_id)),
    )


def compile_pair_blocks(
    root: Path,
    checklist: Path,
    reference: Path,
) -> tuple[PairBlock, ...]:
    checklist_text = checklist.read_text(encoding="utf-8")
    reference_text = reference.read_text(encoding="utf-8")
    checklist_ids = tuple(_PAIR_BLOCK_MARKER.findall(checklist_text))
    blocks: list[PairBlock] = []
    for match in _PAIR_BLOCK_DEFINITION.finditer(reference_text):
        manifest = tomllib.loads(match.group("manifest"))
        start_line = reference_text.count("\n", 0, match.start()) + 1
        end_line = reference_text.count("\n", 0, match.end()) + 1
        raw = match.group(0).encode("utf-8")
        blocks.append(
            PairBlock(
                block_id=manifest["id"],
                document=reference.relative_to(root).as_posix(),
                start_line=start_line,
                end_line=end_line,
                sha256=hashlib.sha256(raw).hexdigest(),
                requirements=tuple(manifest["requirements"]),
                targets=tuple(_parse_repo_symbol(value) for value in manifest["targets"]),
                tests=tuple(_parse_repo_symbol(value) for value in manifest["tests"]),
                gate=manifest["gate"],
                depends_on=tuple(manifest["depends_on"]),
            )
        )
    if set(checklist_ids) != {block.block_id for block in blocks}:
        raise SystemGraphError("checklist and PairBlock IDs differ")
    return topological_pair_blocks(tuple(blocks))


def topological_pair_blocks(blocks: tuple[PairBlock, ...]) -> tuple[PairBlock, ...]:
    by_id = {block.block_id: block for block in blocks}
    incoming = {block.block_id: set(block.depends_on) for block in blocks}
    for block_id, dependencies in incoming.items():
        unknown = dependencies - by_id.keys()
        if unknown:
            raise SystemGraphError(f"{block_id} has unknown dependencies {sorted(unknown)}")
    ready = sorted(block_id for block_id, dependencies in incoming.items() if not dependencies)
    ordered: list[PairBlock] = []
    while ready:
        block_id = ready.pop(0)
        ordered.append(by_id[block_id])
        for dependent in sorted(incoming):
            if block_id in incoming[dependent]:
                incoming[dependent].remove(block_id)
                if not incoming[dependent] and by_id[dependent] not in ordered:
                    ready.append(dependent)
                    ready.sort()
    if len(ordered) != len(blocks):
        raise SystemGraphError("PairBlock dependency graph contains a cycle")
    return tuple(ordered)


def ingest_pair_blocks(
    tasks: tuple[PairBlock, ...],
    traceability: ContractTraceabilityGraph,
) -> tuple[tuple[SystemNode, ...], tuple[SystemEdge, ...]]:
    requirements = {
        item.requirement_id: item for item in traceability.requirements
    }
    nodes: list[SystemNode] = []
    edges: list[SystemEdge] = []

    def add_edge(source: str, target: str, kind: SystemEdgeKind, task: PairBlock) -> None:
        evidence = SourceEvidence(
            path=task.document,
            start_line=task.start_line,
            end_line=task.end_line,
            expression=task.block_id,
        )
        payload = {
            "source": source,
            "target": target,
            "kind": kind,
            "origin": "declared",
            "evidence": evidence.model_dump(mode="json"),
        }
        edges.append(SystemEdge(edge_id=canonical_sha256(payload), **payload))

    for task in topological_pair_blocks(tasks):
        block_id = f"span:{task.document}:pair-block:{task.block_id}"
        gate_id = f"span:{task.document}:gate:{task.block_id}"
        nodes.extend(
            (
                SystemNode(
                    node_id=block_id,
                    kind="span",
                    roles=("implementation_block",),
                    path=task.document,
                    symbol=task.block_id,
                    start_line=task.start_line,
                    end_line=task.end_line,
                    sha256=task.sha256,
                ),
                SystemNode(
                    node_id=gate_id,
                    kind="span",
                    roles=("completion_gate",),
                    path=task.document,
                    symbol=f"gate:{task.block_id}",
                    start_line=task.start_line,
                    end_line=task.end_line,
                    sha256=canonical_sha256(task.gate),
                ),
            )
        )
        for requirement_id in task.requirements:
            requirement = requirements[requirement_id]
            add_edge(
                block_id,
                f"span:{requirement.contract}:requirement:{requirement_id}",
                "implements",
                task,
            )
        for target in task.targets:
            add_edge(block_id, f"span:{target.path}:{target.symbol}", "changes", task)
        for test in task.tests:
            add_edge(block_id, f"span:{test.path}:{test.symbol}", "depends_on", task)
        for dependency in task.depends_on:
            add_edge(
                block_id,
                f"span:{task.document}:pair-block:{dependency}",
                "depends_on",
                task,
            )
        add_edge(block_id, gate_id, "gates_on", task)
    return (
        tuple(sorted(nodes, key=lambda node: node.node_id)),
        tuple(sorted(edges, key=lambda edge: edge.edge_id)),
    )
```

The source-span analyzer replaces the provisional line and digest values with
the exact marker spans before publication.

<!-- pair-block-definition: P0-SIG-05 -->
```toml pair-block
id = "P0-SIG-05"
requirements = ["SIG-04"]
targets = ["tests/test_documentation.py:test_system_impact_dags_preserve_semantic_topology"]
tests = ["tests/test_documentation.py:test_system_impact_dags_preserve_semantic_topology"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k system_impact_dags_preserve_semantic_topology -q"
depends_on = ["P0-SIG-01"]
```

This block is implemented. Preserve the exact edge sets, role assignments,
palette, and neutral link style already asserted by the named test.

```python pair-edit
SYSTEM_IMPACT_DAG_COUNT = 3
SYSTEM_IMPACT_LINK_STYLE = "linkStyle default stroke:#94a3b8,stroke-width:2px"
```

<!-- pair-block-definition: P0-SIG-06 -->
```toml pair-block
id = "P0-SIG-06"
requirements = ["SIG-02"]
targets = ["src/viper/system_graph.py:record_resolution"]
tests = ["tests/test_validation_architecture.py:test_system_graph_resolution_is_total_and_strict"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_resolution_is_total_and_strict -q"
depends_on = ["P0-SIG-03"]
```

Represent each dynamic lookup as one attempt with one outcome.

```python pair-edit
def make_resolution_attempt(
    kind: ResolutionKind,
    source: SystemNodeId,
    expression: str,
) -> ResolutionAttempt:
    payload = {"kind": kind, "source": source, "expression": expression}
    return ResolutionAttempt(resolution_id=canonical_sha256(payload), **payload)


def record_resolution(
    attempt: ResolutionAttempt,
    target: SystemNodeId | None,
    reason: str | None,
) -> ResolutionObservation | UnresolvedDependency:
    if (target is None) == (reason is None):
        raise ValueError("resolution requires exactly one target or reason")
    if target is None:
        return UnresolvedDependency(attempt=attempt, reason=reason)
    evidence = ResolutionEvidence(resolution_id=attempt.resolution_id)
    payload = {
        "source": attempt.source,
        "target": target,
        "kind": "resolves",
        "origin": "observed",
        "evidence": evidence.model_dump(mode="json"),
    }
    edge = SystemEdge(edge_id=canonical_sha256(payload), **payload)
    return ResolutionObservation(attempt=attempt, target=target, edge=edge)
```

<!-- pair-block-definition: P0-SIG-07 -->
```toml pair-block
id = "P0-SIG-07"
requirements = ["SIG-02"]
targets = ["src/viper/system_graph.py:require_strict_graph"]
tests = ["tests/test_validation_architecture.py:test_system_graph_resolution_is_total_and_strict"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_resolution_is_total_and_strict -q"
depends_on = ["P0-SIG-06"]
```

```python pair-edit
class SystemGraphError(ValueError):
    """Report an incomplete or internally inconsistent system graph."""


def require_strict_graph(graph: SystemGraph) -> SystemGraph:
    if graph.unresolved:
        identities = tuple(
            item.attempt.resolution_id for item in graph.unresolved
        )
        raise SystemGraphError(f"unresolved dependencies: {identities}")
    return graph
```

<!-- pair-block-definition: P0-SIG-08 -->
```toml pair-block
id = "P0-SIG-08"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:condense_system_graph"]
tests = ["tests/test_inspection.py:test_system_impact_reaches_local_store_consumers"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k system_impact_reaches_local_store_consumers -q"
depends_on = ["P0-SIG-07"]
```

Use Tarjan's depth-first search to collapse cycles, then retain all relation
kinds crossing each component pair.

```python pair-edit
def strongly_connected_components(graph: SystemGraph) -> tuple[tuple[str, ...], ...]:
    adjacency = {node.node_id: [] for node in graph.nodes}
    for edge in graph.edges:
        adjacency[edge.source].append(edge.target)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in sorted(adjacency[node_id]):
            if target not in indices:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] == indices[node_id]:
            members: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                members.append(member)
                if member == node_id:
                    break
            components.append(tuple(sorted(members)))

    for node_id in sorted(adjacency):
        if node_id not in indices:
            visit(node_id)
    return tuple(sorted(components))


def condense_system_graph(
    graph: SystemGraph,
    graph_ref: ResolvedFileRef,
) -> SystemCondensationDAG:
    member_groups = strongly_connected_components(graph)
    components = tuple(
        SystemComponent(component_id=canonical_sha256(group), members=group)
        for group in member_groups
    )
    component_by_node = {
        member: component.component_id
        for component in components
        for member in component.members
    }
    relations: dict[tuple[str, str], set[str]] = {}
    for edge in graph.edges:
        source = component_by_node[edge.source]
        target = component_by_node[edge.target]
        if source != target:
            relations.setdefault((source, target), set()).add(edge.kind)
    edges = tuple(
        SystemComponentEdge(
            source=source,
            target=target,
            relations=tuple(sorted(kinds)),
        )
        for (source, target), kinds in sorted(relations.items())
    )
    return SystemCondensationDAG(graph=graph_ref, components=components, edges=edges)
```

<!-- pair-block-definition: P0-SIG-09 -->
```toml pair-block
id = "P0-SIG-09"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:diff_system_graphs", "src/viper/system_graph.py:compute_impact"]
tests = ["tests/test_inspection.py:test_system_impact_reaches_local_store_consumers", "tests/test_inspection.py:test_system_impact_replays_skill_manifest_rename"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k system_impact -q"
depends_on = ["P0-SIG-08"]
```

Use stable node and edge IDs for exact set difference. Reverse traversal starts
at every changed node and both endpoints of every changed edge.

```python pair-edit
def diff_system_graphs(
    baseline: SystemGraph,
    candidate: SystemGraph,
    baseline_ref: ResolvedFileRef,
    candidate_ref: ResolvedFileRef,
) -> SystemGraphDelta:
    if baseline.context_sha256 != candidate.context_sha256:
        raise SystemGraphError("system graph contexts differ")
    baseline_nodes = {node.node_id: node for node in baseline.nodes}
    candidate_nodes = {node.node_id: node for node in candidate.nodes}
    shared = baseline_nodes.keys() & candidate_nodes.keys()
    changed = tuple(
        ChangedNode(
            node_id=node_id,
            baseline=baseline_nodes[node_id],
            candidate=candidate_nodes[node_id],
        )
        for node_id in sorted(shared)
        if baseline_nodes[node_id] != candidate_nodes[node_id]
    )
    baseline_edges = {edge.edge_id: edge for edge in baseline.edges}
    candidate_edges = {edge.edge_id: edge for edge in candidate.edges}
    return SystemGraphDelta(
        baseline=baseline_ref,
        candidate=candidate_ref,
        context_sha256=baseline.context_sha256,
        added_nodes=tuple(candidate_nodes[key] for key in sorted(candidate_nodes.keys() - baseline_nodes.keys())),
        removed_nodes=tuple(baseline_nodes[key] for key in sorted(baseline_nodes.keys() - candidate_nodes.keys())),
        changed_nodes=changed,
        added_edges=tuple(candidate_edges[key] for key in sorted(candidate_edges.keys() - baseline_edges.keys())),
        removed_edges=tuple(baseline_edges[key] for key in sorted(baseline_edges.keys() - candidate_edges.keys())),
    )


def reverse_closure(graph: SystemGraph, seeds: set[str]) -> tuple[str, ...]:
    reverse = {node.node_id: set() for node in graph.nodes}
    for edge in graph.edges:
        reverse[edge.target].add(edge.source)
    reached = set(seeds)
    pending = list(sorted(seeds, reverse=True))
    while pending:
        target = pending.pop()
        for dependent in sorted(reverse.get(target, ())):
            if dependent not in reached:
                reached.add(dependent)
                pending.append(dependent)
    return tuple(sorted(reached))


def compute_impact(
    delta: SystemGraphDelta,
    candidate: SystemGraph,
    delta_ref: ResolvedFileRef,
    traceability: ContractTraceabilityGraph,
) -> ImpactReport:
    seeds = {node.node_id for node in delta.added_nodes + delta.removed_nodes}
    seeds.update(node.node_id for node in delta.changed_nodes)
    for edge in delta.added_edges + delta.removed_edges:
        seeds.update((edge.source, edge.target))
    affected_nodes = reverse_closure(candidate, seeds)
    affected_set = set(affected_nodes)
    affected_requirements = tuple(
        sorted(
            requirement.requirement_id
            for requirement in traceability.requirements
            if any(
                requirement.requirement_id == node.symbol
                and node.node_id in affected_set
                for node in candidate.nodes
            )
        )
    )
    implementations = tuple(
        edge
        for edge in traceability.edges
        if edge.kind == "implementation"
        and f"span:{edge.target.path}:{edge.target.symbol}" in affected_set
    )
    verifications = tuple(
        edge
        for edge in traceability.edges
        if edge.kind == "verification"
        and f"span:{edge.target.path}:{edge.target.symbol}" in affected_set
    )
    return ImpactReport(
        delta=delta_ref,
        affected_nodes=affected_nodes,
        affected_requirements=affected_requirements,
        affected_implementations=implementations,
        observing_tests=verifications,
        unresolved=candidate.unresolved,
        complete=not candidate.unresolved,
    )
```

<!-- pair-block-definition: P0-SIG-10 -->
```toml pair-block
id = "P0-SIG-10"
requirements = ["SIG-03"]
targets = ["src/viper/system_graph.py:verify_propagation"]
tests = ["tests/test_inspection.py:test_system_impact_reaches_local_store_consumers"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k system_impact_reaches_local_store_consumers -q"
depends_on = ["P0-SIG-09"]
```

```python pair-edit
def verify_propagation(
    impact: ImpactReport,
    plan: PropagationPlan,
    delta: SystemGraphDelta,
) -> None:
    covered = [
        node_id
        for disposition in plan.dispositions
        for node_id in disposition.affected_nodes
    ]
    if len(covered) != len(set(covered)):
        raise SystemGraphError("affected node has several dispositions")
    if set(covered) != set(impact.affected_nodes):
        raise SystemGraphError("propagation plan does not cover the impact report")
    planned = {item.path for item in plan.planned_additions}
    realized = {
        node.path
        for node in delta.added_nodes
        if node.kind == "file" and node.path is not None
    }
    if planned != realized:
        raise SystemGraphError(
            f"planned additions {sorted(planned)} differ from added files {sorted(realized)}"
        )
```

<!-- pair-block-definition: P0-SIG-11 -->
```toml pair-block
id = "P0-SIG-11"
requirements = ["SIG-02"]
targets = ["src/viper/system_graph.py:validate_system_graph", "src/viper/system_graph.py:serialize_system_graph"]
tests = ["tests/test_validation_architecture.py:test_system_graph_resolution_is_total_and_strict"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph_resolution_is_total_and_strict -q"
depends_on = ["P0-SIG-06", "P0-SIG-07"]
```

```python pair-edit
def validate_system_graph(graph: SystemGraph) -> None:
    node_ids = {node.node_id for node in graph.nodes}
    inventory = {item.path: item for item in graph.inventory}
    analyses = {item.path: item for item in graph.analyses}
    if inventory.keys() != analyses.keys():
        raise SystemGraphError("inventory and analysis paths differ")
    for path, item in inventory.items():
        if analyses[path].file_sha256 != item.sha256:
            raise SystemGraphError(f"analysis digest differs for {path}")
    for edge in graph.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            raise SystemGraphError(f"edge endpoint is absent: {edge.edge_id}")
    outcomes = [item.attempt.resolution_id for item in graph.observations]
    outcomes.extend(item.attempt.resolution_id for item in graph.unresolved)
    if len(outcomes) != len(set(outcomes)):
        raise SystemGraphError("resolution attempt has several outcomes")


def serialize_system_graph(graph: SystemGraph) -> bytes:
    validate_system_graph(graph)
    return canonical_bytes(graph)
```

## 5. Focused proof

These blocks add the tests named by the checklist. Imports belong at the top
of each target test module.

<!-- pair-block-definition: P0-PROOF-01 -->
```toml pair-block
id = "P0-PROOF-01"
requirements = ["CRT-01"]
targets = ["tests/test_documentation.py:test_contract_rules_map_to_owners_and_tests"]
tests = ["tests/test_documentation.py:test_contract_rules_map_to_owners_and_tests"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_rules_map_to_owners_and_tests -q"
depends_on = ["P0-CRT-01"]
```

```python pair-edit
def test_contract_rules_map_to_owners_and_tests() -> None:
    graph = compile_contract_traceability(
        ROOT,
        MASTER_EXECUTION_CHECKLIST,
        PHASE_ZERO_CONTRACTS,
    )
    requirement_ids = [item.requirement_id for item in graph.requirements]
    rule_ids = [item.rule_id for item in graph.rules]
    assert len(requirement_ids) == len(set(requirement_ids))
    assert len(rule_ids) == len(set(rule_ids))
    for requirement_id in requirement_ids:
        assert any(
            rule.requirement_id == requirement_id for rule in graph.rules
        )
```

<!-- pair-block-definition: P0-PROOF-02 -->
```toml pair-block
id = "P0-PROOF-02"
requirements = ["CRT-02"]
targets = ["tests/test_documentation.py:test_contract_traceability_rejects_missing_symbols"]
tests = ["tests/test_documentation.py:test_contract_traceability_rejects_missing_symbols"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_traceability_rejects_missing_symbols -q"
depends_on = ["P0-CRT-02"]
```

```python pair-edit
def test_contract_traceability_rejects_missing_symbols(tmp_path: Path) -> None:
    source = tmp_path / "owner.py"
    source.write_text("def present():\n    return None\n", encoding="utf-8")
    with pytest.raises(
        ContractTraceabilityError,
        match="source symbol is missing",
    ):
        _require_python_symbol(
            tmp_path,
            RepoSymbolRef(path="owner.py", symbol="absent"),
        )
```

<!-- pair-block-definition: P0-PROOF-03 -->
```toml pair-block
id = "P0-PROOF-03"
requirements = ["CRT-03"]
targets = ["tests/test_documentation.py:test_contract_traces_are_populated", "tests/test_documentation.py:test_phase_zero_contracts_show_three_dags_and_instantiate_models"]
tests = ["tests/test_documentation.py:test_contract_traces_are_populated", "tests/test_documentation.py:test_phase_zero_contracts_show_three_dags_and_instantiate_models"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k 'contract_traces_are_populated or phase_zero_contracts_show_three_dags' -q"
depends_on = ["P0-CRT-03"]
```

```python pair-edit
def test_contract_traces_are_populated() -> None:
    for contract in PHASE_ZERO_CONTRACTS:
        traces = parse_contract_traces(ROOT, contract)
        assert {trace.outcome.kind for trace in traces} == {"accepted", "rejected"}
        assert all(trace.scenario and trace.setup and trace.input for trace in traces)
        assert all(trace.invocation for trace in traces)


def test_phase_zero_contracts_show_three_dags_and_instantiate_models() -> None:
    model_names = tuple(model.__name__ for model in TRACEABILITY_MODELS)
    for contract in PHASE_ZERO_CONTRACTS:
        validate_contract_example(contract, model_names)
```

<!-- pair-block-definition: P0-PROOF-04 -->
```toml pair-block
id = "P0-PROOF-04"
requirements = ["CRT-04"]
targets = ["tests/test_documentation.py:test_contract_traceability_graph_is_canonical"]
tests = ["tests/test_documentation.py:test_contract_traceability_graph_is_canonical"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k contract_traceability_graph_is_canonical -q"
depends_on = ["P0-CRT-05"]
```

```python pair-edit
def test_contract_traceability_graph_is_canonical() -> None:
    left = compile_contract_traceability(
        ROOT,
        MASTER_EXECUTION_CHECKLIST,
        PHASE_ZERO_CONTRACTS,
    )
    right = compile_contract_traceability(
        ROOT,
        MASTER_EXECUTION_CHECKLIST,
        PHASE_ZERO_CONTRACTS,
    )
    assert left == right
    assert serialize_contract_traceability(left) == serialize_contract_traceability(right)
    for rule in left.rules:
        links = tuple(edge for edge in left.edges if edge.rule_id == rule.rule_id)
        assert {link.kind for link in links} == {"implementation", "verification"}
```

<!-- pair-block-definition: P0-PROOF-05 -->
```toml pair-block
id = "P0-PROOF-05"
requirements = ["PDR-01"]
targets = ["tests/test_project_init.py:test_init_project_establishes_discoverable_root"]
tests = ["tests/test_project_init.py:test_init_project_establishes_discoverable_root"]
gate = "conda run -n mantra python -m pytest tests/test_project_init.py -k establishes_discoverable_root -q"
depends_on = ["P0-PDR-01", "P0-PDR-02"]
```

```python pair-edit
def test_init_project_establishes_discoverable_root(tmp_path: Path) -> None:
    target = tmp_path / "outside" / "starter"
    initialize_project(target, "sample_project")
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    child = target / "src" / "sample_project"
    assert find_project_root(child) == target.resolve()
    assert resolve_project_root(child) == target.resolve()
    required = {
        "viper.toml",
        "inputs",
        "benchmarks",
        "experiments",
        ".gitignore",
        "pyproject.toml",
    }
    assert required <= {path.name for path in target.iterdir()}
```

<!-- pair-block-definition: P0-PROOF-06 -->
```toml pair-block
id = "P0-PROOF-06"
requirements = ["PDR-02"]
targets = ["tests/test_storage.py:test_store_uses_selected_project_root"]
tests = ["tests/test_storage.py:test_store_uses_selected_project_root"]
gate = "conda run -n mantra python -m pytest tests/test_storage.py -k uses_selected_project_root -q"
depends_on = ["P0-PDR-05"]
```

```python pair-edit
def test_store_uses_selected_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "artifacts" / "model.bin"
    source.parent.mkdir()
    source.write_bytes(b"original")
    store = LocalArtifactStore(root)
    reference = store.resolved_files({"artifacts/model.bin": source.read_bytes()})[0]
    source.write_bytes(b"changed")
    assert store.store_root == root / ".viper" / "store"
    assert store.fetch(reference.stored_at) == b"original"
    with pytest.raises((LocalStoreError, ProjectRootError)):
        LocalArtifactStore(root, "../escape")
```

<!-- pair-block-definition: P0-PROOF-07 -->
```toml pair-block
id = "P0-PROOF-07"
requirements = ["PDR-03"]
targets = ["tests/test_validation_architecture.py:test_project_paths_reject_symlinks"]
tests = ["tests/test_validation_architecture.py:test_project_paths_reject_symlinks"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k project_paths_reject_symlinks -q"
depends_on = ["P0-PDR-06"]
```

```python pair-edit
def test_project_paths_reject_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n", encoding="utf-8")
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "link.csv").symlink_to(outside)
    with pytest.raises(ProjectRootError, match="symlink"):
        resolve_project_path(root, "inputs/link.csv", operation="read")
    with pytest.raises(ProjectRootError, match="escapes"):
        resolve_project_path(root, "../outside.csv", operation="read")
```

<!-- pair-block-definition: P0-PROOF-08 -->
```toml pair-block
id = "P0-PROOF-08"
requirements = ["PDR-04"]
targets = ["tests/test_documentation.py:test_project_root_vocabulary"]
tests = ["tests/test_documentation.py:test_project_root_vocabulary"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k project_root_vocabulary -q"
depends_on = ["P0-PDR-04"]
```

```python pair-edit
def test_project_root_vocabulary() -> None:
    retired = re.compile(r"\brepository_root\b|--repository-root")
    surfaces = (
        ROOT / "src/viper/api.py",
        ROOT / "src/viper/cli.py",
        ROOT / "src/viper/_api/handlers.py",
        ROOT / "docs/reference/protocol.md",
        ROOT / "docs/reference/api.md",
    )
    violations = {
        path.relative_to(ROOT).as_posix(): retired.findall(path.read_text())
        for path in surfaces
        if retired.search(path.read_text())
    }
    assert violations == {}
```

<!-- pair-block-definition: P0-PROOF-09 -->
```toml pair-block
id = "P0-PROOF-09"
requirements = ["SIG-01", "SIG-02"]
targets = ["tests/test_validation_architecture.py:test_system_graph_inventory_and_edges_are_auditable", "tests/test_validation_architecture.py:test_system_graph_resolution_is_total_and_strict"]
tests = ["tests/test_validation_architecture.py:test_system_graph_inventory_and_edges_are_auditable", "tests/test_validation_architecture.py:test_system_graph_resolution_is_total_and_strict"]
gate = "conda run -n mantra python -m pytest tests/test_validation_architecture.py -k system_graph -q"
depends_on = ["P0-SIG-02", "P0-SIG-03", "P0-SIG-06", "P0-SIG-07", "P0-SIG-11"]
```

```python pair-edit
def test_system_graph_inventory_and_edges_are_auditable(system_graph: SystemGraph) -> None:
    assert {item.path for item in system_graph.inventory} == {
        item.path for item in system_graph.analyses
    }
    assert {f"file:{item.path}" for item in system_graph.inventory} <= {
        node.node_id for node in system_graph.nodes
    }
    validate_system_graph(system_graph)


def test_system_graph_resolution_is_total_and_strict(system_graph: SystemGraph) -> None:
    assert serialize_system_graph(system_graph) == serialize_system_graph(system_graph)
    attempts = [item.attempt.resolution_id for item in system_graph.observations]
    attempts.extend(item.attempt.resolution_id for item in system_graph.unresolved)
    assert len(attempts) == len(set(attempts))
    if system_graph.unresolved:
        with pytest.raises(SystemGraphError, match="unresolved dependencies"):
            require_strict_graph(system_graph)
```

<!-- pair-block-definition: P0-PROOF-10 -->
```toml pair-block
id = "P0-PROOF-10"
requirements = ["SIG-03"]
targets = ["tests/test_inspection.py:test_system_impact_reaches_local_store_consumers", "tests/test_inspection.py:test_system_impact_replays_skill_manifest_rename"]
tests = ["tests/test_inspection.py:test_system_impact_reaches_local_store_consumers", "tests/test_inspection.py:test_system_impact_replays_skill_manifest_rename"]
gate = "conda run -n mantra python -m pytest tests/test_inspection.py -k system_impact -q"
depends_on = ["P0-SIG-08", "P0-SIG-09", "P0-SIG-10"]
```

```python pair-edit
def assert_exact_impact(
    report: ImpactReport,
    expected_nodes: set[str],
    expected_tests: set[str],
) -> None:
    assert set(report.affected_nodes) == expected_nodes
    assert {edge.target.symbol for edge in report.observing_tests} == expected_tests
    assert report.complete is True


def test_system_impact_reaches_local_store_consumers(
    local_store_change: tuple[
        SystemGraph,
        SystemGraph,
        ResolvedFileRef,
        ResolvedFileRef,
        ResolvedFileRef,
        ContractTraceabilityGraph,
        set[str],
        set[str],
    ],
) -> None:
    (
        baseline,
        candidate,
        baseline_ref,
        candidate_ref,
        delta_ref,
        traceability,
        expected_nodes,
        expected_tests,
    ) = local_store_change
    delta = diff_system_graphs(baseline, candidate, baseline_ref, candidate_ref)
    report = compute_impact(delta, candidate, delta_ref, traceability)
    assert_exact_impact(report, expected_nodes, expected_tests)


def test_system_impact_replays_skill_manifest_rename(
    skill_manifest_rename: tuple[SystemGraph, SystemGraph, ResolvedFileRef, ResolvedFileRef],
) -> None:
    baseline, candidate, baseline_ref, candidate_ref = skill_manifest_rename
    delta = diff_system_graphs(baseline, candidate, baseline_ref, candidate_ref)
    seeds = {node.node_id for node in delta.added_nodes + delta.removed_nodes}
    seeds.update(node.node_id for node in delta.changed_nodes)
    for edge in delta.added_edges + delta.removed_edges:
        seeds.update((edge.source, edge.target))
    assert reverse_closure(candidate, seeds)
```

<!-- pair-block-definition: P0-PROOF-11 -->
```toml pair-block
id = "P0-PROOF-11"
requirements = ["SIG-04"]
targets = ["tests/test_documentation.py:test_system_graph_preserves_contract_traceability", "tests/test_documentation.py:test_phase_zero_checkboxes_have_complete_ordered_pair_blocks"]
tests = ["tests/test_documentation.py:test_system_graph_preserves_contract_traceability", "tests/test_documentation.py:test_phase_zero_checkboxes_have_complete_ordered_pair_blocks"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k system_graph_preserves_contract_traceability -q"
depends_on = ["P0-SIG-04"]
```

```python pair-edit
def test_system_graph_preserves_contract_traceability() -> None:
    traceability = compile_contract_traceability(
        ROOT,
        MASTER_EXECUTION_CHECKLIST,
        PHASE_ZERO_CONTRACTS,
    )
    nodes, edges = ingest_contract_traceability(traceability)
    node_ids = {node.node_id for node in nodes}
    for requirement in traceability.requirements:
        assert any(requirement.requirement_id in node_id for node_id in node_ids)
    for rule in traceability.rules:
        assert any(rule.rule_id in node_id for node_id in node_ids)
        relations = {edge.kind for edge in edges if rule.rule_id in edge.target}
        assert {"implements", "tests"} <= relations


def test_phase_zero_checkboxes_have_complete_ordered_pair_blocks() -> None:
    blocks = compile_pair_blocks(
        ROOT,
        MASTER_EXECUTION_CHECKLIST,
        PHASE_ZERO_PAIR_CODING,
    )
    assert len(blocks) == 34
    assert {block.block_id for block in blocks} == PHASE_ZERO_PAIR_BLOCK_IDS
    assert topological_pair_blocks(blocks) == blocks
```

<!-- pair-block-definition: P0-PROOF-12 -->
```toml pair-block
id = "P0-PROOF-12"
requirements = ["SIG-04"]
targets = ["tests/test_documentation.py:test_system_impact_dags_preserve_semantic_topology"]
tests = ["tests/test_documentation.py:test_system_impact_dags_preserve_semantic_topology"]
gate = "conda run -n mantra python -m pytest tests/test_documentation.py -k system_impact_dags_preserve_semantic_topology -q"
depends_on = ["P0-SIG-05"]
```

```python pair-edit
def test_phase_zero_keeps_three_system_impact_dags() -> None:
    diagrams = _MERMAID_FENCE.findall(SYSTEM_IMPACT_GRAPH.read_text())
    assert len(diagrams) >= 3
    assert all(SYSTEM_IMPACT_LINK_STYLE in diagram for diagram in diagrams[:3])
```

## 6. Phase 0 gates

Run the focused test after each block. Run this phase gate after every Phase 0
block has passed:

```bash
conda run -n mantra python -m pytest \
  tests/test_project_init.py \
  tests/test_storage.py \
  tests/test_validation_architecture.py \
  tests/test_inspection.py \
  tests/test_documentation.py -q
```

Close each review cycle only after the focused gate passes, the diff contains
the intended block, and the local and upstream commits are equal.

## 7. Design basis

The local `PairBlock` format is a VIPER design. Its primitives come from
established systems:

- Ferrante, Ottenstein, and Warren model control and data dependencies as
  explicit graph edges in the program dependence graph.
- Horwitz, Reps, and Binkley extend dependency traversal across procedure
  boundaries through the system dependence graph.
- Tarjan's depth-first algorithm computes strongly connected components in
  linear time. VIPER collapses those components before topological ordering.
- Git assigns immutable object IDs from object type and contents, stores file
  contents as blobs, and stores path structure in trees. VIPER inventories one
  selected commit. The working tree remains outside source identity.
- GitHub's stack graphs build file-incremental name-binding graphs and resolve a
  reference by graph search. VIPER extends that file-anchored principle across
  contract, runtime, and verification relationships.
- NASA's software traceability guidance links requirements through
  implementation and verification evidence. `PairBlock` makes that link
  executable at the checklist-task boundary.
- W3C PROV separates entities, activities, and typed provenance relations.
  VIPER retains node roles, relation kinds, and edge evidence.

Primary sources:

1. Ferrante, Ottenstein, and Warren, [The Program Dependence Graph and Its Use
   in Optimization](https://doi.org/10.1145/24039.24041), 1987.
2. Horwitz, Reps, and Binkley, [Interprocedural Slicing Using Dependence
   Graphs](https://doi.org/10.1145/77606.77608), 1990.
3. Tarjan, [Depth-First Search and Linear Graph
   Algorithms](https://doi.org/10.1137/0201010), 1972.
4. Git, [Core data model](https://git-scm.com/docs/gitdatamodel.html) and
   [`git diff-tree`](https://git-scm.com/docs/git-diff-tree.html).
5. Creager and van Antwerpen, [Stack Graphs: Name Resolution at
   Scale](https://arxiv.org/abs/2211.01224), 2022.
6. NASA, [Bidirectional Traceability](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695427/SWE-052%2B-%2BBidirectional%2BTraceability).
7. W3C, [PROV-O](https://www.w3.org/TR/prov-o/).
