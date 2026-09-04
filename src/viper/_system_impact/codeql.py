"""Compile one Python source snapshot into a canonical source graph."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import viper._subprocess as subprocess

from ..system_impact.models import (
    CodeQLIdentity,
    CodeQLReceipt,
    EdgeKind,
    SourceEdge,
    SourceGraph,
    SourceNode,
    SourceNodeKind,
    SourceSnapshot,
)

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
_QUERY_FILES = ("Declarations.ql", "Dependencies.ql")
_EDGE_KINDS = frozenset(
    {"imports", "calls", "constructs", "inherits", "reads", "writes"}
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


# CodeQL and AST use this key to identify the same declaration within one file.
_Anchor = tuple[str, SourceNodeKind, int, int]


def _hash_parts(parts: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in root.rglob("*.py")
                if not any(
                    part in IGNORED_PARTS for part in path.relative_to(root).parts
                )
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


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


def _tree_digest(root: Path) -> str:
    parts: list[bytes] = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        parts.extend((path.relative_to(root).as_posix().encode(), path.read_bytes()))
    return _hash_parts(parts)


def _database_is_reusable(
    database: Path,
    manifest: Path,
    *,
    key: str,
    source_sha256: str,
) -> bool:
    if not database.is_dir() or not manifest.is_file():
        return False
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected = {
        "key": key,
        "source_sha256": source_sha256,
        "database_sha256": _tree_digest(database),
    }
    return recorded == expected


def _run(command: Sequence[str], *, cwd: Path) -> tuple[bytes, bytes]:
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        rendered = " ".join(command)
        detail = completed.stderr.decode("utf-8", errors="replace")
        raise CodeQLAnalysisError(f"CodeQL command failed ({rendered}): {detail}")
    return completed.stdout, completed.stderr


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


def _byte_offsets(source: bytes) -> tuple[tuple[bytes, ...], tuple[int, ...]]:
    """Map each source line to its starting byte."""
    lines = tuple(source.splitlines(keepends=True))
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    return lines, tuple(offsets)


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


def _table_rows(payload: Any) -> list[list[Any]]:
    if not isinstance(payload, dict) or len(payload) != 1:
        raise CodeQLAnalysisError("decoded BQRS result has no unique result set")
    result = next(iter(payload.values()))
    if not isinstance(result, dict) or not isinstance(result.get("tuples"), list):
        raise CodeQLAnalysisError("decoded BQRS result has no tuple table")
    return cast(list[list[Any]], result["tuples"])


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

            # Map each CodeQL location to the AST declaration at that location.
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


__all__ = ["CodeQLAnalysisError", "IGNORED_PARTS", "analyze_source", "source_digest"]
