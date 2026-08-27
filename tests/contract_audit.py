#!/usr/bin/env python3
"""Audit VIPER contract models against the formal protocol and checklist."""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel

PYTHON_FENCE = re.compile(r"```python\s*\n(?P<code>.*?)```", re.DOTALL)
RULE_CELL = re.compile(r"\|\s*`(?P<rule>[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)`\s*\|")


@dataclass(frozen=True)
class FieldShape:
    """Represent one annotated field shown in a specification class."""

    annotation: str
    default: str | None


@dataclass(frozen=True)
class ClassShape:
    """Represent the comparable structure of one displayed class."""

    decorators: tuple[str, ...]
    bases: tuple[str, ...]
    fields: dict[str, FieldShape]


@dataclass(frozen=True)
class AuditFinding:
    """Describe one deterministic contract-audit failure."""

    code: str
    location: str
    message: str


@dataclass(frozen=True)
class AuditResult:
    """Contain the complete deterministic audit result."""

    contract_count: int
    python_fence_count: int
    compared_class_count: int
    compared_alias_count: int
    implemented_model_count: int
    verifier_rule_count: int
    findings: tuple[AuditFinding, ...]

    @property
    def passed(self) -> bool:
        """Return whether the deterministic audit found no failures."""
        return not self.findings


def _expression(node: ast.AST) -> str:
    """Return one stable source representation for an AST expression."""
    return ast.unparse(node)


def _class_shape(node: ast.ClassDef) -> ClassShape:
    """Extract bases and annotated fields from one class definition."""
    fields: dict[str, FieldShape] = {}
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name):
            continue
        fields[statement.target.id] = FieldShape(
            annotation=_expression(statement.annotation),
            default=_expression(statement.value) if statement.value else None,
        )
    return ClassShape(
        decorators=tuple(_expression(decorator) for decorator in node.decorator_list),
        bases=tuple(_expression(base) for base in node.bases),
        fields=fields,
    )


def _document_classes(
    path: Path,
) -> tuple[dict[str, ClassShape], dict[str, str], int, list[AuditFinding]]:
    """Parse Python fences and collect class shapes from one Markdown file."""
    text = path.read_text(encoding="utf-8")
    classes: dict[str, ClassShape] = {}
    aliases: dict[str, str] = {}
    findings: list[AuditFinding] = []
    fence_count = 0

    for fence_count, match in enumerate(PYTHON_FENCE.finditer(text), start=1):
        code = match.group("code")
        try:
            module = ast.parse(code)
        except SyntaxError as error:
            findings.append(
                AuditFinding(
                    code="schema.syntax",
                    location=f"{path}:{fence_count}",
                    message=f"Python fence does not parse: {error.msg}",
                )
            )
            continue

        for node in module.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    aliases[target.id] = _expression(node.value)
                continue
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    aliases[node.target.id] = _expression(node.value)
                continue
            if not isinstance(node, ast.ClassDef):
                continue
            shape = _class_shape(node)
            earlier = classes.get(node.name)
            if earlier is not None and earlier != shape:
                findings.append(
                    AuditFinding(
                        code="schema.duplicate",
                        location=str(path),
                        message=(
                            f"{node.name} has conflicting definitions in one document"
                        ),
                    )
                )
                continue
            classes[node.name] = shape

    return classes, aliases, fence_count, findings


def _compare_shapes(
    *,
    class_name: str,
    contract_path: Path,
    contract: ClassShape,
    protocol: ClassShape,
) -> list[AuditFinding]:
    """Compare one contract class with its formal-protocol definition."""
    findings: list[AuditFinding] = []
    if contract.decorators != protocol.decorators:
        findings.append(
            AuditFinding(
                code="schema.decorators",
                location=str(contract_path),
                message=(
                    f"{class_name} decorators differ: "
                    f"contract={contract.decorators}, protocol={protocol.decorators}"
                ),
            )
        )
    if contract.bases != protocol.bases:
        findings.append(
            AuditFinding(
                code="schema.bases",
                location=str(contract_path),
                message=(
                    f"{class_name} bases differ: contract={contract.bases}, "
                    f"protocol={protocol.bases}"
                ),
            )
        )
    if contract.fields != protocol.fields:
        findings.append(
            AuditFinding(
                code="schema.fields",
                location=str(contract_path),
                message=(
                    f"{class_name} fields differ: "
                    f"contract={asdict(contract)['fields']}, "
                    f"protocol={asdict(protocol)['fields']}"
                ),
            )
        )
    return findings


def _implemented_schema_findings(root: Path) -> tuple[int, list[AuditFinding]]:
    """Generate schemas for every implemented persisted or extension model."""
    sys.path.insert(0, str(root / "src"))
    try:
        from viper import (
            artifacts,
            benchmark,
            experiments,
            http,
            metrics,
            parameters,
            references,
            resume,
            runs,
            runtime,
            stages,
        )
    finally:
        sys.path.pop(0)

    findings: list[AuditFinding] = []
    count = 0
    modules = (
        artifacts,
        benchmark,
        experiments,
        http,
        metrics,
        parameters,
        references,
        resume,
        runs,
        runtime,
        stages,
    )
    for module in modules:
        for name, value in inspect.getmembers(module, inspect.isclass):
            if value.__module__ != module.__name__:
                continue
            if not issubclass(value, BaseModel):
                continue
            count += 1
            try:
                value.model_json_schema()
            except Exception as error:  # noqa: BLE001 - report every schema failure.
                findings.append(
                    AuditFinding(
                        code="schema.construct",
                        location=f"{module.__name__}.{name}",
                        message=f"Pydantic schema generation failed: {error}",
                    )
                )
    return count, findings


def audit_repository(root: Path) -> AuditResult:
    """Run deterministic contract checks for one VIPER repository root."""
    contracts_dir = root / "docs" / "contracts"
    protocol_path = root / "docs" / "reference" / "protocol.md"
    checklist_path = root / "docs" / "PUBLICATION_TODO.md"
    contract_paths = sorted(
        path
        for path in contracts_dir.glob("*.md")
        if path.name not in {"README.md", "AUDIT.md"}
    )

    (
        protocol_classes,
        protocol_aliases,
        protocol_fences,
        findings,
    ) = _document_classes(protocol_path)
    python_fence_count = protocol_fences
    compared_class_count = 0
    compared_alias_count = 0
    all_contract_text = ""

    for path in contract_paths:
        (
            contract_classes,
            contract_aliases,
            fence_count,
            document_findings,
        ) = _document_classes(path)
        python_fence_count += fence_count
        findings.extend(document_findings)
        all_contract_text += path.read_text(encoding="utf-8") + "\n"
        for class_name, contract_shape in contract_classes.items():
            protocol_shape = protocol_classes.get(class_name)
            if protocol_shape is None:
                continue
            compared_class_count += 1
            findings.extend(
                _compare_shapes(
                    class_name=class_name,
                    contract_path=path,
                    contract=contract_shape,
                    protocol=protocol_shape,
                )
            )
        for alias_name, contract_alias in contract_aliases.items():
            protocol_alias = protocol_aliases.get(alias_name)
            if protocol_alias is None:
                continue
            compared_alias_count += 1
            if contract_alias != protocol_alias:
                findings.append(
                    AuditFinding(
                        code="schema.alias",
                        location=str(path),
                        message=(
                            f"{alias_name} differs: contract={contract_alias}, "
                            f"protocol={protocol_alias}"
                        ),
                    )
                )

    checklist = checklist_path.read_text(encoding="utf-8")
    verifier_rules = sorted(set(RULE_CELL.findall(all_contract_text)))
    for rule in verifier_rules:
        if f"`{rule}`" not in checklist:
            findings.append(
                AuditFinding(
                    code="traceability.checklist",
                    location=str(checklist_path),
                    message=f"Named verifier rule is absent from the checklist: {rule}",
                )
            )

    implemented_model_count, model_findings = _implemented_schema_findings(root)
    findings.extend(model_findings)

    return AuditResult(
        contract_count=len(contract_paths),
        python_fence_count=python_fence_count,
        compared_class_count=compared_class_count,
        compared_alias_count=compared_alias_count,
        implemented_model_count=implemented_model_count,
        verifier_rule_count=len(verifier_rules),
        findings=tuple(findings),
    )


def _format_text(result: AuditResult) -> str:
    """Render one audit result for a terminal."""
    lines = [
        f"Contracts: {result.contract_count}",
        f"Python fences parsed: {result.python_fence_count}",
        f"Repeated classes compared: {result.compared_class_count}",
        f"Repeated aliases compared: {result.compared_alias_count}",
        f"Implemented Pydantic schemas generated: {result.implemented_model_count}",
        f"Named verifier rules traced: {result.verifier_rule_count}",
    ]
    if result.passed:
        lines.append("Audit: PASS")
        return "\n".join(lines)
    lines.append(f"Audit: FAIL ({len(result.findings)} findings)")
    lines.extend(
        f"- [{finding.code}] {finding.location}: {finding.message}"
        for finding in result.findings
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse command arguments, run the audit, and emit text or JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="VIPER repository root",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    result = audit_repository(args.root.resolve())
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(_format_text(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
