"""Extract and classify exact Python declarations for System Impact checks."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterator, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypeAlias, cast

from .._contract_traceability import ContractTarget, TargetAction

ChangeKind: TypeAlias = Literal[
    "satisfied",
    "added",
    "removed",
    "callable_interface_changed",
    "type_interface_changed",
    "implementation_changed",
    "unclassified",
]
ImportBinding: TypeAlias = tuple[str, int, str | None, str, str | None]

_CallableDeclaration: TypeAlias = ast.FunctionDef | ast.AsyncFunctionDef
_SupportedDeclaration: TypeAlias = (
    _CallableDeclaration
    | ast.ClassDef
    | ast.Assign
    | ast.AnnAssign
    | ast.Import
    | ast.ImportFrom
)


class SourceDeclarationError(ValueError):
    """Report an absent, ambiguous, malformed, or impossible declaration change."""


def declaration_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield declarations from module or class control-flow blocks."""
    for node in body:
        yield node

        # Classes get their own qualified scope; functions are intentionally local.
        if isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            yield from declaration_statements(node.body)
            yield from declaration_statements(node.orelse)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from declaration_statements(node.body)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            yield from declaration_statements(node.body)
            for handler in node.handlers:
                yield from declaration_statements(handler.body)
            yield from declaration_statements(node.orelse)
            yield from declaration_statements(node.finalbody)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                yield from declaration_statements(case.body)


def import_binding(source: bytes, symbol: str) -> ImportBinding:
    """Return the import that creates one local name."""
    matches: list[ImportBinding] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.asname or alias.name
                if target == symbol:
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


@lru_cache(maxsize=64)
def _contract_target_payloads(source: bytes) -> dict[tuple[int, int, str], bytes]:
    """Index each contract-target fence once for the current file bytes."""
    opening = b"```python contract-target\n"
    closing = b"\n```"
    payloads: dict[tuple[int, int, str], bytes] = {}
    position = 0
    while True:
        start = source.find(opening, position)
        if start < 0:
            break
        end = source.find(closing, start + len(opening))
        if end < 0:
            break
        declaration_end = end + len(closing)
        declaration = source[start:declaration_end]
        key = (
            source.count(b"\n", 0, start) + 1,
            source.count(b"\n", 0, declaration_end) + 1,
            hashlib.sha256(declaration).hexdigest(),
        )
        payloads[key] = source[start + len(opening) : end]
        position = declaration_end
    return payloads


def declaration_payload(root: Path, target: ContractTarget) -> bytes | None:
    """Read the exact declaration owned by one ContractTarget."""
    if target.action == "remove":
        return None

    path = root / target.declaration.path
    try:
        source = path.read_bytes()
    except OSError as error:
        raise SourceDeclarationError(
            f"cannot read ContractTarget declaration: {target.declaration.path}"
        ) from error

    key = (
        target.declaration.start_line,
        target.declaration.end_line,
        target.declaration.sha256,
    )
    payload = _contract_target_payloads(source).get(key)
    if payload is None:
        raise SourceDeclarationError(
            "ContractTarget declaration cannot be reconstructed exactly: "
            f"{target.block_id} {target.target.path}:{target.target.symbol}"
        )
    try:
        return extract_declaration_bytes(payload, target.target.symbol)
    except SourceDeclarationError as error:
        raise SourceDeclarationError(
            "ContractTarget payload does not resolve its declared symbol: "
            f"{target.target.path}:{target.target.symbol}"
        ) from error


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    targets: Sequence[ast.expr]
    if isinstance(node, ast.Assign):
        targets = node.targets
    else:
        targets = (node.target,)
    return tuple(target.id for target in targets if isinstance(target, ast.Name))


def _import_names(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    """Return the names created by one import statement."""
    names: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            continue
        names.append(alias.asname or alias.name)
    return tuple(names)


def _declaration_names(node: ast.stmt) -> tuple[str, ...]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return _assignment_names(node)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _import_names(node)
    return ()


def _resolve_declaration(tree: ast.Module, qualified_symbol: str) -> ast.stmt:
    """Find the one declaration named by a contract target."""
    parts = qualified_symbol.split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        raise SourceDeclarationError(
            f"invalid qualified Python symbol: {qualified_symbol!r}"
        )

    direct = [
        node
        for node in declaration_statements(tree.body)
        if qualified_symbol in _declaration_names(node)
    ]
    if len(direct) == 1:
        return direct[0]
    if len(direct) > 1:
        raise SourceDeclarationError(
            f"Python declaration is ambiguous: {qualified_symbol}"
        )

    body: Sequence[ast.stmt] = tree.body
    for index, part in enumerate(parts):
        matches = [
            node
            for node in declaration_statements(body)
            if part in _declaration_names(node)
        ]
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


@lru_cache(maxsize=256)
def _line_offsets(source: bytes) -> tuple[tuple[bytes, ...], tuple[int, ...]]:
    lines = tuple(source.splitlines(keepends=True))
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    return lines, tuple(offsets)


def _declaration_start(
    node: ast.stmt,
    lines: tuple[bytes, ...],
) -> tuple[int, int]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if node.decorator_list:
            first = node.decorator_list[0]
            line = lines[first.lineno - 1]
            expression_column = first.col_offset
            marker_column = line.rfind(b"@", 0, expression_column + 1)
            if marker_column < 0:
                raise SourceDeclarationError(
                    "decorated declaration lacks its leading @ token"
                )
            return first.lineno, marker_column
    return node.lineno, node.col_offset


@lru_cache(maxsize=256)
def _parse_python(source: bytes) -> ast.Module:
    """Parse identical source bytes once across target lookups."""
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceDeclarationError("Python source is not valid UTF-8") from error
    try:
        return ast.parse(text, type_comments=True)
    except SyntaxError as error:
        raise SourceDeclarationError("Python source cannot be parsed") from error


@lru_cache(maxsize=1024)
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
    tree = _parse_python(source)
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


def _parse_single_declaration(source: bytes, label: str) -> ast.stmt:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceDeclarationError(
            f"{label} declaration is not valid UTF-8"
        ) from error
    try:
        tree = ast.parse(text, type_comments=True)
    except SyntaxError as error:
        raise SourceDeclarationError(f"{label} declaration cannot be parsed") from error
    if len(tree.body) != 1:
        raise SourceDeclarationError(
            f"{label} bytes must contain exactly one Python declaration"
        )
    return tree.body[0]


def _ast_key(value: ast.AST | None) -> str | None:
    if value is None:
        return None
    return ast.dump(value, include_attributes=False)


def _ast_keys(values: Sequence[ast.AST]) -> tuple[str, ...]:
    return tuple(ast.dump(value, include_attributes=False) for value in values)


def _type_parameter_keys(node: ast.AST) -> tuple[str, ...]:
    return _ast_keys(cast(Sequence[ast.AST], getattr(node, "type_params", ())))


def _callable_interface(node: _CallableDeclaration) -> tuple[object, ...]:
    return (
        type(node),
        node.name,
        _ast_keys(node.decorator_list),
        _type_parameter_keys(node),
        _ast_key(node.args),
        _ast_key(node.returns),
        node.type_comment,
    )


def _direct_field_interface(
    node: ast.Assign | ast.AnnAssign,
) -> tuple[tuple[str, str | None], ...]:
    annotation = (
        _ast_key(node.annotation)
        if isinstance(node, ast.AnnAssign)
        else node.type_comment
    )
    return tuple((name, annotation) for name in _assignment_names(node))


def _class_interface(node: ast.ClassDef) -> tuple[object, ...]:
    fields = tuple(
        field
        for member in node.body
        if isinstance(member, (ast.Assign, ast.AnnAssign))
        for field in _direct_field_interface(member)
    )
    methods = tuple(
        _callable_interface(member)
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return (
        node.name,
        _ast_keys(node.decorator_list),
        _type_parameter_keys(node),
        _ast_keys(node.bases),
        _ast_keys(node.keywords),
        fields,
        methods,
    )


def _assignment_interface(
    node: ast.Assign | ast.AnnAssign,
) -> tuple[object, ...]:
    if isinstance(node, ast.Assign):
        targets: Sequence[ast.expr] = node.targets
        annotation = node.type_comment
    else:
        targets = (node.target,)
        annotation = _ast_key(node.annotation)
    return (type(node), _ast_keys(targets), annotation)


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
