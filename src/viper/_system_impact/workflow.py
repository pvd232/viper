"""Analyze one committed baseline against the current Python working tree."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import viper._subprocess as subprocess
from viper._contract_traceability import RepoSymbolRef
from viper.system_impact.explain import (
    DependencyEvidence,
    ImpactPathSearch,
    explain_source_comparison,
    rank_impact_paths,
)
from viper.system_impact.models import SourceGraph, SourceSnapshot
from viper.system_impact.rename import (
    ReferenceKind,
    RenameAnalysisError,
    RenameCheck,
    RenameObligationSet,
    RenameSpec,
    check_rename_obligations,
    compile_rename_obligations,
    render_rename_check,
)

from .codeql import (
    IGNORED_PARTS,
    CodeQLAnalysisError,
    analyze_source,
    resolve_analysis_specs,
    source_digest,
)


class WorkingTreeImpactError(RuntimeError):
    """Report a repository, baseline, or analysis orchestration failure."""


@dataclass(frozen=True)
class WorkingTreeImpact:
    """Return explained evidence and its persisted graph artifacts."""

    repository_root: Path
    base_revision: str
    artifact_root: Path
    baseline_graph: Path
    realized_graph: Path
    evidence: tuple[DependencyEvidence, ...]
    path_search: ImpactPathSearch


@dataclass(frozen=True)
class WorkingTreeRenameCheck:
    """Return an exact rename decision and its persisted evidence."""

    repository_root: Path
    base_revision: str
    artifact_root: Path
    baseline_graph: Path
    realized_graph: Path
    obligations_path: Path
    check_path: Path
    report: str
    check: RenameCheck


def _git(root: Path, *arguments: str) -> bytes:
    """Run one bounded Git read and return its standard output."""
    try:
        completed = subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise WorkingTreeImpactError("cannot execute Git") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise WorkingTreeImpactError(f"Git command failed: {detail}")
    return completed.stdout


def _repository_root(root: Path) -> Path:
    """Resolve and validate the repository that owns the working tree."""
    requested = root.resolve()
    resolved = Path(
        _git(requested, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    if resolved != requested:
        raise WorkingTreeImpactError(
            f"repository root must be the Git top level: {resolved}"
        )
    return resolved


def _commit(root: Path, revision: str) -> str:
    """Resolve one revision expression to a complete commit identifier."""
    value = (
        _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
        .decode("ascii")
        .strip()
    )
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise WorkingTreeImpactError("Git returned an invalid commit identifier")
    return value


def _materialize_revision(root: Path, revision: str, destination: Path) -> None:
    """Export one committed tree without changing the caller's Git worktree."""
    archive_path = destination.parent / "baseline.tar"
    _git(
        root,
        "archive",
        "--format=tar",
        f"--output={archive_path}",
        revision,
    )
    destination.mkdir()
    try:
        with tarfile.open(archive_path, mode="r") as archive:
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise WorkingTreeImpactError(
                        "Git archive contains a path outside its source root"
                    )
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise WorkingTreeImpactError(
                        f"Git archive contains an unsupported entry: {member.name}"
                    )
                source = archive.extractfile(member)
                if source is None:
                    raise WorkingTreeImpactError(
                        f"cannot read Git archive entry: {member.name}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read())
    except (OSError, tarfile.TarError) as error:
        raise WorkingTreeImpactError(
            "cannot materialize the baseline revision"
        ) from error


def _materialize_working_tree(root: Path, destination: Path) -> str:
    """Capture one stable copy of the Python files in the working tree."""
    for _attempt in range(2):
        before = source_digest(root)
        if destination.exists():
            shutil.rmtree(destination)
        for source in root.rglob("*.py"):
            relative = source.relative_to(root)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        after = source_digest(root)
        captured = source_digest(destination)
        if before == after == captured:
            return captured
    raise WorkingTreeImpactError("Python working tree changed while it was captured")


def _write_graph(path: Path, graph: SourceGraph) -> None:
    """Atomically persist one canonical source graph."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(graph.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


def _write_model(path: Path, value: RenameObligationSet | RenameCheck) -> None:
    """Atomically persist one canonical rename protocol record."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(value.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


def analyze_working_tree_impact(
    root: Path,
    *,
    base: str,
    targets: tuple[str, ...],
    artifact_root: Path | None = None,
    cache_root: Path | None = None,
    codeql_executable: Path | None = None,
    query_pack: Path | None = None,
    path_depth: int = 3,
    path_limit: int = 12,
    path_expansion_budget: int = 500,
) -> WorkingTreeImpact:
    """Compile direct dependencies and ranked paths around source targets."""
    repository = _repository_root(root)
    revision = _commit(repository, base)
    executable_value = (
        str(codeql_executable)
        if codeql_executable is not None
        else shutil.which("codeql")
    )
    if executable_value is None:
        raise WorkingTreeImpactError("CodeQL executable is unavailable")
    executable = Path(executable_value).resolve()
    pack = (
        query_pack.resolve()
        if query_pack is not None
        else Path(__file__).parents[3] / "tools/codeql/viper-python-impact"
    )
    cache = (
        cache_root.resolve()
        if cache_root is not None
        else repository / ".viper/cache/codeql-source-analysis"
    )
    try:
        extraction, query, graph_format = resolve_analysis_specs(
            repository,
            codeql_executable=executable,
            query_pack=pack,
        )
        with tempfile.TemporaryDirectory(prefix="viper-impact-analysis.") as directory:
            temporary_root = Path(directory)
            baseline_root = temporary_root / "baseline"
            realized_root = temporary_root / "realized"
            _materialize_revision(repository, revision, baseline_root)
            candidate_sha256 = _materialize_working_tree(
                repository,
                realized_root,
            )
            output = (
                artifact_root.resolve()
                if artifact_root is not None
                else repository
                / ".viper/system-impact/analysis"
                / f"{revision[:12]}-{candidate_sha256[:12]}"
            )
            output.mkdir(parents=True, exist_ok=True)
            baseline_snapshot = SourceSnapshot(
                base_revision=revision,
                source_sha256=source_digest(baseline_root),
                revision=revision,
            )
            realized_snapshot = SourceSnapshot(
                base_revision=revision,
                source_sha256=candidate_sha256,
                revision=None,
            )
            common = {
                "extraction": extraction,
                "query": query,
                "format": graph_format,
                "codeql_executable": executable,
                "query_pack": pack,
                "cache_root": cache,
            }
            baseline = analyze_source(
                baseline_root,
                snapshot=baseline_snapshot,
                artifact_root=output / "baseline",
                **common,
            )
            realized = analyze_source(
                realized_root,
                snapshot=realized_snapshot,
                artifact_root=output / "realized",
                **common,
            )
    except CodeQLAnalysisError as error:
        raise WorkingTreeImpactError(str(error)) from error

    baseline_path = output / "baseline-source-graph.json"
    realized_path = output / "realized-source-graph.json"
    _write_graph(baseline_path, baseline)
    _write_graph(realized_path, realized)
    try:
        evidence = explain_source_comparison(
            baseline=baseline,
            realized=realized,
            targets=targets,
        )
        path_search = rank_impact_paths(
            graph=baseline,
            targets=targets,
            max_depth=path_depth,
            limit=path_limit,
            expansion_budget=path_expansion_budget,
        )
    except ValueError as error:
        raise WorkingTreeImpactError(str(error)) from error
    (output / "dependency-evidence.json").write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in evidence],
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (output / "impact-paths.json").write_text(
        path_search.model_dump_json(),
        encoding="utf-8",
    )
    return WorkingTreeImpact(
        repository_root=repository,
        base_revision=revision,
        artifact_root=output,
        baseline_graph=baseline_path,
        realized_graph=realized_path,
        evidence=evidence,
        path_search=path_search,
    )


def analyze_working_tree_rename(
    root: Path,
    *,
    base: str,
    old_target: RepoSymbolRef,
    new_target: RepoSymbolRef,
    edge_kinds: tuple[ReferenceKind, ...],
    artifact_root: Path | None = None,
    cache_root: Path | None = None,
    codeql_executable: Path | None = None,
    query_pack: Path | None = None,
) -> WorkingTreeRenameCheck:
    """Verify one exact rename from a Git baseline to the working tree."""
    repository = _repository_root(root)
    revision = _commit(repository, base)
    executable_value = (
        str(codeql_executable)
        if codeql_executable is not None
        else shutil.which("codeql")
    )
    if executable_value is None:
        raise WorkingTreeImpactError("CodeQL executable is unavailable")
    executable = Path(executable_value).resolve()
    pack = (
        query_pack.resolve()
        if query_pack is not None
        else Path(__file__).parents[3] / "tools/codeql/viper-python-impact"
    )
    cache = (
        cache_root.resolve()
        if cache_root is not None
        else repository / ".viper/cache/codeql-source-analysis"
    )
    try:
        spec = RenameSpec(
            old_target=old_target,
            new_target=new_target,
            edge_kinds=edge_kinds,
        )
        extraction, query, graph_format = resolve_analysis_specs(
            repository,
            codeql_executable=executable,
            query_pack=pack,
        )
        with tempfile.TemporaryDirectory(prefix="viper-rename-analysis.") as directory:
            temporary_root = Path(directory)
            baseline_root = temporary_root / "baseline"
            realized_root = temporary_root / "realized"
            _materialize_revision(repository, revision, baseline_root)
            candidate_sha256 = _materialize_working_tree(repository, realized_root)
            output = (
                artifact_root.resolve()
                if artifact_root is not None
                else repository
                / ".viper/system-impact/rename"
                / f"{revision[:12]}-{candidate_sha256[:12]}"
            )
            output.mkdir(parents=True, exist_ok=True)
            common = {
                "extraction": extraction,
                "query": query,
                "format": graph_format,
                "codeql_executable": executable,
                "query_pack": pack,
                "cache_root": cache,
            }
            baseline = analyze_source(
                baseline_root,
                snapshot=SourceSnapshot(
                    base_revision=revision,
                    source_sha256=source_digest(baseline_root),
                    revision=revision,
                ),
                artifact_root=output / "baseline",
                **common,
            )
            realized = analyze_source(
                realized_root,
                snapshot=SourceSnapshot(
                    base_revision=revision,
                    source_sha256=candidate_sha256,
                    revision=None,
                ),
                artifact_root=output / "realized",
                **common,
            )
            obligations = compile_rename_obligations(
                root=baseline_root,
                graph=baseline,
                spec=spec,
            )
            decision = check_rename_obligations(
                root=realized_root,
                graph=realized,
                obligations=obligations,
            )
    except (CodeQLAnalysisError, RenameAnalysisError, OSError, ValueError) as error:
        raise WorkingTreeImpactError(str(error)) from error

    baseline_path = output / "baseline-source-graph.json"
    realized_path = output / "realized-source-graph.json"
    obligations_path = output / "rename-obligations.json"
    check_path = output / "rename-check.json"
    report = render_rename_check(decision)
    _write_graph(baseline_path, baseline)
    _write_graph(realized_path, realized)
    _write_model(obligations_path, obligations)
    _write_model(check_path, decision)
    (output / "rename-report.txt").write_text(report + "\n", encoding="utf-8")
    return WorkingTreeRenameCheck(
        repository_root=repository,
        base_revision=revision,
        artifact_root=output,
        baseline_graph=baseline_path,
        realized_graph=realized_path,
        obligations_path=obligations_path,
        check_path=check_path,
        report=report,
        check=decision,
    )


__all__ = [
    "WorkingTreeImpact",
    "WorkingTreeImpactError",
    "WorkingTreeRenameCheck",
    "analyze_working_tree_impact",
    "analyze_working_tree_rename",
]
