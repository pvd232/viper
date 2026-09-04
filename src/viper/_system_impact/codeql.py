"""Compile one Python source snapshot into a canonical source graph."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import viper._subprocess as subprocess

from ..system_impact import (
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
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
)
_QUERY_FILES = ("Declarations.ql", "Dependencies.ql")
_EDGE_KINDS = frozenset(
    {"imports", "calls", "constructs", "inherits", "reads", "writes"}
)


class CodeQLAnalysisError(RuntimeError):
    """Report a failed or internally inconsistent CodeQL analysis."""


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
    completed = subprocess.run(  # noqa: S603 - executable is an explicit input.
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
) -> tuple[tuple[str, ast.stmt, SourceNodeKind], ...]:
    declarations: list[tuple[str, ast.stmt, SourceNodeKind]] = []

    def visit(body: Sequence[ast.stmt], prefix: str = "") -> None:
        for node in body:
            names: tuple[str, ...] = ()
            kind: SourceNodeKind | None = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = (node.name,)
                kind = "method" if prefix else "function"
            elif isinstance(node, ast.ClassDef):
                names = (node.name,)
                kind = "class"
            elif isinstance(node, ast.Assign):
                names = tuple(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
                kind = "assignment"
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = (node.target.id,)
                kind = "assignment"
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = tuple(
                    alias.asname
                    or (
                        alias.name.split(".", maxsplit=1)[0]
                        if isinstance(node, ast.Import)
                        else alias.name
                    )
                    for alias in node.names
                    if alias.name != "*"
                )
                kind = "import"

            if kind is None:
                continue
            for name in names:
                declarations.append((f"{prefix}{name}", node, kind))
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")

    visit(tree.body)
    return tuple(declarations)


def _byte_offsets(source: bytes) -> tuple[tuple[bytes, ...], tuple[int, ...]]:
    lines = tuple(source.splitlines(keepends=True))
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    return lines, tuple(offsets)


def _node_span(node: ast.stmt, source: bytes) -> tuple[int, int, int, int, bytes]:
    if node.end_lineno is None or node.end_col_offset is None:
        raise CodeQLAnalysisError("Python declaration has no complete source span")
    lines, offsets = _byte_offsets(source)
    start_line = node.lineno
    start_col = node.col_offset
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
    end = offsets[node.end_lineno - 1] + node.end_col_offset
    return (
        start_line,
        start_col,
        node.end_lineno,
        node.end_col_offset,
        source[start:end],
    )


def _table_rows(payload: Any) -> list[list[Any]]:
    if not isinstance(payload, dict) or len(payload) != 1:
        raise CodeQLAnalysisError("decoded BQRS result has no unique result set")
    result = next(iter(payload.values()))
    if not isinstance(result, dict) or not isinstance(result.get("tuples"), list):
        raise CodeQLAnalysisError("decoded BQRS result has no tuple table")
    return cast(list[list[Any]], result["tuples"])


def _load_nodes(root: Path, rows: list[list[Any]]) -> tuple[SourceNode, ...]:
    observed_lines: set[tuple[str, int]] = set()
    for row in rows:
        path = str(row[0])
        if any(part in IGNORED_PARTS for part in Path(path).parts):
            continue
        observed_lines.add((path, int(row[3])))
    nodes: dict[str, SourceNode] = {}
    for path in sorted({path for path, _ in observed_lines}):
        source_path = root / path
        if not source_path.is_file() or source_path.suffix != ".py":
            continue
        source = source_path.read_bytes()
        try:
            tree = ast.parse(source.decode("utf-8"), type_comments=True)
        except (SyntaxError, UnicodeDecodeError) as error:
            raise CodeQLAnalysisError(
                f"cannot normalize CodeQL declarations in {path}"
            ) from error
        for symbol, declaration, kind in _qualified_declarations(tree):
            codeql_lines = {declaration.lineno}
            if isinstance(
                declaration, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                codeql_lines.add(
                    declaration.decorator_list[0].lineno
                    if declaration.decorator_list
                    else declaration.lineno
                )
            if not any((path, line) in observed_lines for line in codeql_lines):
                continue
            start_line, start_col, end_line, end_col, exact = _node_span(
                declaration, source
            )
            node_id = f"{path}:{symbol}"
            nodes[node_id] = SourceNode(
                node_id=node_id,
                path=path,
                symbol=symbol,
                kind=kind,
                start_line=start_line,
                start_col=start_col,
                end_line=end_line,
                end_col=end_col,
                sha256=hashlib.sha256(exact).hexdigest(),
            )
    return tuple(sorted(nodes.values(), key=lambda node: node.node_id))


def _node_at(
    by_line: dict[tuple[str, int], tuple[SourceNode, ...]],
    by_path: dict[str, tuple[SourceNode, ...]],
    path: str,
    line: int,
) -> SourceNode | None:
    exact = by_line.get((path, line), ())
    if len(exact) == 1:
        return exact[0]
    candidates = tuple(
        node
        for node in by_path.get(path, ())
        if node.start_line <= line <= node.end_line
    )
    if not candidates:
        return None
    return min(
        candidates, key=lambda node: (node.end_line - node.start_line, node.node_id)
    )


def _load_edges(
    rows: list[list[Any]], nodes: tuple[SourceNode, ...]
) -> tuple[SourceEdge, ...]:
    by_line: dict[tuple[str, int], list[SourceNode]] = {}
    nodes_by_path: dict[str, list[SourceNode]] = {}
    for node in nodes:
        by_line.setdefault((node.path, node.start_line), []).append(node)
        nodes_by_path.setdefault(node.path, []).append(node)
    line_index = {key: tuple(value) for key, value in by_line.items()}
    path_index = {key: tuple(value) for key, value in nodes_by_path.items()}
    edges: dict[str, SourceEdge] = {}
    for row in rows:
        source = _node_at(line_index, path_index, str(row[0]), int(row[1]))
        target = _node_at(line_index, path_index, str(row[3]), int(row[4]))
        if source is None or target is None or source.node_id == target.node_id:
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
    edges = _load_edges(decoded["Dependencies"], nodes)
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
