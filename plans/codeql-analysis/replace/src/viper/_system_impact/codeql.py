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

import yaml

import viper._subprocess as subprocess

from ..system_impact.models import (
    CodeQLAnalysisReceipt,
    CodeQLExtractionSpec,
    CodeQLQuerySpec,
    DatabaseReceipt,
    EdgeKind,
    GraphReceipt,
    QueryReceipt,
    SourceEdge,
    SourceGraph,
    SourceGraphFormat,
    SourceNode,
    SourceNodeKind,
    SourceSnapshot,
    stage_key,
)
from .source import declaration_statements

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
_EDGE_KINDS = frozenset(
    {"imports", "calls", "constructs", "inherits", "reads", "writes"}
)
_LOWERING_ASSETS = (
    ("src/viper/_system_impact/codeql.py", Path(__file__)),
    ("src/viper/_system_impact/source.py", Path(__file__).with_name("source.py")),
    (
        "src/viper/system_impact/models.py",
        Path(__file__).parents[1] / "system_impact/models.py",
    ),
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


@dataclass(frozen=True)
class _DatabaseStage:
    """Keep a verified database path with its receipt."""

    path: Path
    receipt: DatabaseReceipt


@dataclass(frozen=True)
class _QueryStage:
    """Keep verified BQRS paths with their receipt."""

    database: Path
    results: tuple[Path, ...]
    receipt: QueryReceipt


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
    """Hash every analyzed Python path and its bytes."""
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


def lowering_digest() -> str:
    """Hash the explicit files that convert CodeQL rows into a SourceGraph."""
    parts: list[bytes] = []
    for relative, path in _LOWERING_ASSETS:
        try:
            source = path.read_bytes()
        except OSError as error:
            raise CodeQLAnalysisError(
                f"lowering asset is absent: {relative}"
            ) from error
        parts.extend((relative.encode(), source))
    return _hash_parts(parts)


def _database_digest(database: Path) -> str:
    """Hash extracted facts while ignoring query caches and logs."""
    files: list[Path] = []
    facts = database / "db-python"
    if facts.is_dir():
        files.extend(
            path
            for path in facts.rglob("*")
            if path.is_file() and "cache" not in path.relative_to(facts).parts
        )
    source = database / "src.zip"
    if source.is_file():
        files.append(source)
    if not files:
        raise CodeQLAnalysisError("CodeQL database contains no extracted facts")
    parts: list[bytes] = []
    for path in sorted(files, key=lambda item: item.relative_to(database).as_posix()):
        parts.extend(
            (path.relative_to(database).as_posix().encode(), path.read_bytes())
        )
    return _hash_parts(parts)


def _result_files(database: Path) -> tuple[Path, ...]:
    """Return the BQRS files selected by the authoritative query suite."""
    results = tuple(sorted((database / "results").rglob("*.bqrs")))
    if not results:
        raise CodeQLAnalysisError("CodeQL query suite produced no BQRS results")
    stems = tuple(path.stem for path in results)
    if len(stems) != len(set(stems)):
        raise CodeQLAnalysisError("CodeQL query suite produced duplicate result names")
    return results


def _result_digest(database: Path, results: tuple[Path, ...]) -> str:
    """Hash every suite result by path and bytes."""
    parts: list[bytes] = []
    for path in results:
        parts.extend(
            (path.relative_to(database).as_posix().encode(), path.read_bytes())
        )
    return _hash_parts(parts)


def _write_receipt(path: Path, receipt: object) -> None:
    """Write one canonical stage receipt."""
    model_dump = getattr(receipt, "model_dump")
    path.write_text(
        json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _load_database_receipt(path: Path) -> DatabaseReceipt | None:
    """Load a database receipt or treat invalid bytes as a cache miss."""
    try:
        return DatabaseReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _load_query_receipt(path: Path) -> QueryReceipt | None:
    """Load a query receipt or treat invalid bytes as a cache miss."""
    try:
        return QueryReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


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
        for node in declaration_statements(body):
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


def _check_extraction(
    root: Path,
    executable: Path,
    extraction: CodeQLExtractionSpec,
) -> tuple[tuple[tuple[str, ...], ...], tuple[bytes, ...]]:
    """Confirm that the executable and selected Python extractor match the plan."""
    version_command = (str(executable), "version", "--format=json")
    version_stdout, version_stderr = _run(version_command, cwd=root)
    version = json.loads(version_stdout).get("version")
    if version != extraction.version:
        raise CodeQLAnalysisError(
            "CodeQL executable version differs from CodeQLExtractionSpec"
        )
    if hashlib.sha256(executable.read_bytes()).hexdigest() != (
        extraction.executable_sha256
    ):
        raise CodeQLAnalysisError(
            "CodeQL executable digest differs from CodeQLExtractionSpec"
        )

    languages_command = (str(executable), "resolve", "languages", "--format=json")
    languages_stdout, languages_stderr = _run(languages_command, cwd=root)
    candidates = json.loads(languages_stdout).get(extraction.language)
    if not isinstance(candidates, list) or not candidates:
        raise CodeQLAnalysisError("CodeQL has no Python extractor")
    extractor = Path(candidates[0]).resolve()
    if _tree_digest(extractor) != extraction.extractor_sha256:
        raise CodeQLAnalysisError(
            "Python extractor digest differs from CodeQLExtractionSpec"
        )
    return (
        (version_command, languages_command),
        (b"version", version_stderr, b"languages", languages_stderr),
    )


def _check_query_pack(query_pack: Path, query: CodeQLQuerySpec) -> Path:
    """Confirm the query pack and suite selected by the plan."""
    pack_root = query_pack.resolve()
    if _tree_digest(pack_root) != query.pack_sha256:
        raise CodeQLAnalysisError("query-pack digest differs from CodeQLQuerySpec")
    try:
        metadata = yaml.safe_load(
            (pack_root / "qlpack.yml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise CodeQLAnalysisError("cannot read query-pack metadata") from error
    if not isinstance(metadata, dict):
        raise CodeQLAnalysisError("query-pack metadata is not a mapping")
    if f"{metadata.get('name')}@{metadata.get('version')}" != query.pack:
        raise CodeQLAnalysisError("query-pack identity differs from CodeQLQuerySpec")
    suite = pack_root / query.suite
    if not suite.is_file():
        raise CodeQLAnalysisError("CodeQLQuerySpec suite is absent from the query pack")
    return suite


def _extract_database(
    root: Path,
    *,
    snapshot: SourceSnapshot,
    extraction: CodeQLExtractionSpec,
    executable: Path,
    cache_root: Path,
) -> _DatabaseStage:
    """Create or reuse the database selected by the source and extraction spec."""
    commands, stderr_parts = _check_extraction(root, executable, extraction)
    key = stage_key(snapshot, extraction)
    stage_root = cache_root / "databases" / key
    database = stage_root / "database"
    receipt_path = stage_root / "receipt.json"
    receipt = _load_database_receipt(receipt_path)
    cached_sha256 = None
    if database.is_dir():
        try:
            cached_sha256 = _database_digest(database)
        except CodeQLAnalysisError:
            pass
    if (
        receipt is not None
        and receipt.snapshot == snapshot
        and receipt.extraction == extraction
        and receipt.key == key
        and receipt.exit_code == 0
        and receipt.sha256 == cached_sha256
    ):
        return _DatabaseStage(path=database, receipt=receipt)

    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True)
    create_command = (
        str(executable),
        "database",
        "create",
        str(database),
        f"--language={extraction.language}",
        f"--build-mode={extraction.build_mode}",
        f"--source-root={root}",
        "--overwrite",
    )
    _, create_stderr = _run(create_command, cwd=root)
    receipt = DatabaseReceipt(
        snapshot=snapshot,
        extraction=extraction,
        key=key,
        sha256=_database_digest(database),
        commands=(*commands, create_command),
        exit_code=0,
        stderr_sha256=_hash_parts((*stderr_parts, b"database-create", create_stderr)),
    )
    _write_receipt(receipt_path, receipt)
    return _DatabaseStage(path=database, receipt=receipt)


def _run_query_suite(
    root: Path,
    *,
    database: _DatabaseStage,
    query: CodeQLQuerySpec,
    suite: Path,
    executable: Path,
    cache_root: Path,
) -> _QueryStage:
    """Run or reuse the authoritative suite without mutating the base database."""
    key = stage_key(database.receipt.key, database.receipt.sha256, query)
    stage_root = cache_root / "queries" / key
    query_database = stage_root / "database"
    receipt_path = stage_root / "receipt.json"
    receipt = _load_query_receipt(receipt_path)
    results: tuple[Path, ...] = ()
    if receipt is not None and query_database.is_dir():
        try:
            results = _result_files(query_database)
            database_sha256 = _database_digest(query_database)
        except CodeQLAnalysisError:
            database_sha256 = None
        if (
            results
            and receipt.database_key == database.receipt.key
            and receipt.database_sha256 == database.receipt.sha256
            and receipt.query == query
            and receipt.key == key
            and receipt.exit_code == 0
            and receipt.sha256 == _result_digest(query_database, results)
            and database_sha256 == database.receipt.sha256
        ):
            return _QueryStage(
                database=query_database,
                results=results,
                receipt=receipt,
            )

    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True)
    shutil.copytree(database.path, query_database)
    command = (
        str(executable),
        "database",
        "run-queries",
        "--",
        str(query_database),
        str(suite),
    )
    _, stderr = _run(command, cwd=root)
    if _database_digest(query_database) != database.receipt.sha256:
        raise CodeQLAnalysisError(
            "query execution changed the extracted database facts"
        )
    results = _result_files(query_database)
    receipt = QueryReceipt(
        database_key=database.receipt.key,
        database_sha256=database.receipt.sha256,
        query=query,
        key=key,
        sha256=_result_digest(query_database, results),
        commands=(command,),
        exit_code=0,
        stderr_sha256=_hash_parts((b"database-run-queries", stderr)),
    )
    _write_receipt(receipt_path, receipt)
    return _QueryStage(database=query_database, results=results, receipt=receipt)


def _lower_graph(
    root: Path,
    *,
    snapshot: SourceSnapshot,
    extraction: CodeQLExtractionSpec,
    query: CodeQLQuerySpec,
    format: SourceGraphFormat,
    database: DatabaseReceipt,
    results: _QueryStage,
    executable: Path,
    cache_root: Path,
    artifact_root: Path,
) -> SourceGraph:
    """Decode one query result set and convert it into a canonical graph."""
    key = stage_key(results.receipt.key, results.receipt.sha256, format)
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_results: list[Path] = []
    for result in results.results:
        artifact = artifact_root / result.name
        shutil.copy2(result, artifact)
        artifact_results.append(artifact)
    graph_root = cache_root / "graphs" / key
    graph_path = graph_root / "source-graph.json"

    decoded: dict[str, list[list[Any]]] = {}
    commands: list[tuple[str, ...]] = []
    stderr_parts: list[bytes] = []
    for result in artifact_results:
        decoded_path = artifact_root / f"{result.stem}.json"
        command = (
            str(executable),
            "bqrs",
            "decode",
            str(result),
            "--format=json",
            f"--output={decoded_path}",
        )
        _, stderr = _run(command, cwd=root)
        commands.append(command)
        stderr_parts.extend((result.stem.encode(), stderr))
        rows = _table_rows(json.loads(decoded_path.read_text(encoding="utf-8")))
        rows.sort(
            key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"))
        )
        decoded[result.stem] = rows
    if graph_path.is_file():
        try:
            graph = SourceGraph.model_validate_json(
                graph_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, ValueError):
            graph = None
        if (
            graph is not None
            and graph.receipt.database == database
            and graph.receipt.query == results.receipt
            and graph.receipt.graph.key == key
            and graph.receipt.graph.format == format
        ):
            return graph

    try:
        declaration_rows = decoded["Declarations"]
        dependency_rows = decoded["Dependencies"]
    except KeyError as error:
        raise CodeQLAnalysisError(
            "query suite must produce Declarations and Dependencies results"
        ) from error

    nodes = _load_nodes(root, declaration_rows)
    edges = _load_edges(root, dependency_rows, nodes)
    graph_sha256 = hashlib.sha256(
        json.dumps(
            {
                "nodes": [node.model_dump(mode="json") for node in nodes],
                "edges": [edge.model_dump(mode="json") for edge in edges],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    receipt = GraphReceipt(
        query_key=results.receipt.key,
        query_sha256=results.receipt.sha256,
        format=format,
        key=key,
        sha256=graph_sha256,
        commands=tuple(commands),
        exit_code=0,
        stderr_sha256=_hash_parts(stderr_parts),
    )
    graph = SourceGraph(
        snapshot=snapshot,
        nodes=nodes,
        edges=edges,
        receipt=CodeQLAnalysisReceipt(
            database=database,
            query=results.receipt,
            graph=receipt,
        ),
    )
    if graph_root.exists():
        shutil.rmtree(graph_root)
    graph_root.mkdir(parents=True)
    graph_path.write_text(graph.model_dump_json(), encoding="utf-8")
    return graph


def analyze_source(
    snapshot_root: Path,
    *,
    snapshot: SourceSnapshot,
    extraction: CodeQLExtractionSpec,
    query: CodeQLQuerySpec,
    format: SourceGraphFormat,
    codeql_executable: Path,
    query_pack: Path,
    cache_root: Path,
    artifact_root: Path,
) -> SourceGraph:
    """Extract, query, and lower one exact Python source tree."""
    root = snapshot_root.resolve()
    if source_digest(root) != snapshot.source_sha256:
        raise CodeQLAnalysisError(
            "SourceSnapshot.source_sha256 does not match source bytes"
        )
    if format.lowering_sha256 != lowering_digest():
        raise CodeQLAnalysisError(
            "SourceGraphFormat lowering digest differs from loaded assets"
        )
    suite = _check_query_pack(query_pack, query)
    database = _extract_database(
        root,
        snapshot=snapshot,
        extraction=extraction,
        executable=codeql_executable,
        cache_root=cache_root.resolve(),
    )
    results = _run_query_suite(
        root,
        database=database,
        query=query,
        suite=suite,
        executable=codeql_executable,
        cache_root=cache_root.resolve(),
    )
    return _lower_graph(
        root,
        snapshot=snapshot,
        extraction=extraction,
        query=query,
        format=format,
        database=database.receipt,
        results=results,
        executable=codeql_executable,
        cache_root=cache_root.resolve(),
        artifact_root=artifact_root.resolve(),
    )


__all__ = [
    "CodeQLAnalysisError",
    "IGNORED_PARTS",
    "analyze_source",
    "lowering_digest",
    "source_digest",
]
