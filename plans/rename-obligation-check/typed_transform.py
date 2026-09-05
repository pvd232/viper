"""Apply one digest-bound rename plus a keyword contract to resolved calls."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Any


class TransformError(ValueError):
    """Report an invalid or stale typed transformation."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TransformError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise TransformError(f"{path} does not contain a JSON object")
    return value


def _worklist(path: Path) -> dict[str, Any]:
    document = _object(path)
    if (
        document.get("schema_version") != 2
        or document.get("coordinate_system")
        != "line_one_based_column_utf8_zero_based"
    ):
        raise TransformError("unsupported rename worklist")
    obligations_file = document.get("obligations_file")
    expected_digest = document.get("obligations_sha256")
    if not isinstance(obligations_file, str) or not isinstance(expected_digest, str):
        raise TransformError("worklist provenance is incomplete")
    obligations_path = path.parent / obligations_file
    actual_digest = hashlib.sha256(obligations_path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise TransformError("worklist obligations digest differs")
    return document


def _line_starts(source: bytes) -> list[int]:
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def _byte_position(lines: list[str], starts: list[int], row: int, column: int) -> int:
    return starts[row - 1] + len(lines[row - 1][:column].encode())


def _definition_insertion(
    source: bytes,
    symbol: str,
    *,
    keyword: str,
    annotation: str,
    value: str,
) -> tuple[int, bytes]:
    text = source.decode()
    tree = ast.parse(text)
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
    ]
    if len(definitions) != 1:
        raise TransformError(f"target definition is not unique: {symbol}")
    definition = definitions[0]
    if keyword in {
        argument.arg
        for argument in (
            *definition.args.posonlyargs,
            *definition.args.args,
            *definition.args.kwonlyargs,
        )
    }:
        raise TransformError(f"target definition already has parameter: {keyword}")
    lines = text.splitlines(keepends=True)
    starts = _line_starts(source)
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    opening: tokenize.TokenInfo | None = None
    closing: tokenize.TokenInfo | None = None
    saw_definition = False
    saw_name = False
    depth = 0
    for token in tokens:
        if token.type == tokenize.NAME and token.string == "def":
            saw_definition = True
            saw_name = False
            continue
        if saw_definition and token.type == tokenize.NAME:
            saw_name = token.string == symbol
            saw_definition = False
            continue
        if saw_name and opening is None and token.type == tokenize.OP:
            if token.string != "(":
                continue
            opening = token
            depth = 1
            continue
        if opening is None or token.type != tokenize.OP:
            continue
        if token.string == "(":
            depth += 1
        elif token.string == ")":
            depth -= 1
            if depth == 0:
                closing = token
                break
    if opening is None or closing is None:
        raise TransformError(f"cannot locate signature boundary: {symbol}")
    opening_end = _byte_position(lines, starts, *opening.end)
    closing_start = _byte_position(lines, starts, *closing.start)
    has_parameters = bool(source[opening_end:closing_start].strip())
    has_keyword_boundary = definition.args.vararg is not None or bool(
        definition.args.kwonlyargs
    )
    if not has_parameters:
        prefix = ""
    elif has_keyword_boundary:
        prefix = ", "
    else:
        prefix = ", *, "
    payload = f"{prefix}{keyword}: {annotation} = {json.dumps(value)}".encode()
    return closing_start, payload


def _call_insertions(
    source: bytes,
    sites: list[dict[str, Any]],
    *,
    keyword: str,
    value: str,
) -> list[tuple[int, bytes]]:
    tree = ast.parse(source.decode())
    starts = _line_starts(source)
    calls: dict[tuple[int, int], ast.Call] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            calls[(node.func.lineno, node.func.col_offset)] = node
    insertions: list[tuple[int, bytes]] = []
    for site in sites:
        line = site.get("line")
        column = site.get("column")
        if not isinstance(line, int) or not isinstance(column, int):
            raise TransformError("call-site coordinates are invalid")
        call = calls.get((line, column))
        if call is None or call.end_lineno is None or call.end_col_offset is None:
            raise TransformError(f"resolved call is absent at {line}:{column}")
        if any(item.arg == keyword for item in call.keywords):
            raise TransformError(f"call already has keyword at {line}:{column}")
        end = starts[call.end_lineno - 1] + call.end_col_offset
        if source[end - 1 : end] != b")":
            raise TransformError(f"call boundary is invalid at {line}:{column}")
        prefix = ", " if call.args or call.keywords else ""
        insertions.append(
            (end - 1, f"{prefix}{keyword}={json.dumps(value)}".encode())
        )
    return insertions


def _atomic_bytes(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def apply_transform(
    root: Path,
    worklist_path: Path,
    *,
    keyword: str,
    annotation: str,
    value: str,
) -> tuple[int, int, int]:
    """Apply verified symbol edits, one parameter, and all resolved call arguments."""
    document = _worklist(worklist_path)
    batches = document.get("batches")
    sites = document.get("sites")
    old_target = document.get("old_target")
    if (
        not isinstance(batches, list)
        or not batches
        or not isinstance(sites, list)
        or not isinstance(old_target, dict)
        or not isinstance(old_target.get("path"), str)
        or not isinstance(old_target.get("symbol"), str)
    ):
        raise TransformError("worklist transformation fields are incomplete")
    sites_by_path: dict[str, list[dict[str, Any]]] = {}
    for site in sites:
        if not isinstance(site, dict):
            raise TransformError("worklist site is not an object")
        if site.get("kind") != "calls":
            continue
        path = site.get("path")
        if not isinstance(path, str):
            raise TransformError("worklist call path is invalid")
        sites_by_path.setdefault(path, []).append(site)
    outputs: dict[Path, bytes] = {}
    symbol_edits = 0
    call_edits = 0
    definition_path = old_target["path"]
    for batch in batches:
        if not isinstance(batch, dict):
            raise TransformError("worklist batch is not an object")
        relative = batch.get("path")
        edits = batch.get("edits")
        if not isinstance(relative, str) or not isinstance(edits, list) or not edits:
            raise TransformError("worklist batch fields are invalid")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise TransformError(
                f"worklist path escapes the root: {relative}"
            ) from error
        source = path.read_bytes()
        starts = _line_starts(source)
        replacements: list[tuple[int, int, bytes]] = []
        for edit in edits:
            if not isinstance(edit, dict):
                raise TransformError("worklist edit is not an object")
            line = edit.get("line")
            column = edit.get("column")
            end_column = edit.get("end_column")
            old_text = edit.get("old_text")
            new_text = edit.get("new_text")
            if (
                not isinstance(line, int)
                or not 1 <= line < len(starts)
                or not isinstance(column, int)
                or not isinstance(end_column, int)
                or not isinstance(old_text, str)
                or not isinstance(new_text, str)
            ):
                raise TransformError(f"worklist edit is invalid for {relative}")
            start = starts[line - 1] + column
            end = starts[line - 1] + end_column
            if source[start:end] != old_text.encode():
                raise TransformError(
                    f"stale symbol edit at {relative}:{line}:{column}"
                )
            replacements.append((start, end, new_text.encode()))
            symbol_edits += 1
        for position, payload in _call_insertions(
            source,
            sites_by_path.get(relative, []),
            keyword=keyword,
            value=value,
        ):
            replacements.append((position, position, payload))
            call_edits += 1
        if relative == definition_path:
            position, payload = _definition_insertion(
                source,
                old_target["symbol"],
                keyword=keyword,
                annotation=annotation,
                value=value,
            )
            replacements.append((position, position, payload))
        for start, end, payload in sorted(replacements, reverse=True):
            source = source[:start] + payload + source[end:]
        outputs[path] = source
    for path, payload in outputs.items():
        _atomic_bytes(path, payload)
    return len(outputs), symbol_edits, call_edits


def main(argv: list[str] | None = None) -> int:
    """Apply one complete typed transformation without scheduling the agent."""
    parser = argparse.ArgumentParser(prog="typed-transform")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--annotation", required=True)
    parser.add_argument("--value", required=True)
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    worklist = arguments.worklist
    if not worklist.is_absolute():
        worklist = root / worklist
    try:
        files, symbols, calls = apply_transform(
            root,
            worklist.resolve(),
            keyword=arguments.keyword,
            annotation=arguments.annotation,
            value=arguments.value,
        )
    except (OSError, TransformError, SyntaxError, UnicodeDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        f"Applied transformation: {symbols} symbol edits and {calls} call edits "
        f"in {files} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
