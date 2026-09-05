"""Print baseline rename relationships unresolved in the current candidate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

_VIRTUAL_ENV = os.environ.get("VIRTUAL_ENV")
if _VIRTUAL_ENV is not None:
    _VIRTUAL_PYTHON = Path(_VIRTUAL_ENV) / "bin" / "python"
    if _VIRTUAL_PYTHON.is_file() and Path(sys.executable) != _VIRTUAL_PYTHON:
        os.execv(
            os.fspath(_VIRTUAL_PYTHON),
            (os.fspath(_VIRTUAL_PYTHON), *sys.argv),
        )

from viper._system_impact.codeql import analyze_overlay_source, source_digest
from viper.system_impact.models import SourceGraph, SourceSnapshot
from viper.system_impact.rename import (
    RenameAnalysisError,
    RenameObligationSet,
    check_rename_obligations,
)


def _extract_head(root: Path, destination: Path) -> None:
    """Materialize committed source for the overlay baseline."""
    archive = destination.parent / "baseline.tar"
    subprocess.run(
        ("git", "archive", "--format=tar", f"--output={archive}", "HEAD"),
        cwd=root,
        check=True,
    )
    destination.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")


def unresolved(root: Path, evidence: Path) -> dict[str, object]:
    """Evaluate one candidate graph and return its obligation anti-join."""
    baseline_graph = SourceGraph.model_validate_json(
        (evidence / "baseline-source-graph.json").read_bytes()
    )
    obligations = tuple(
        RenameObligationSet.model_validate_json(path.read_bytes())
        for path in sorted((evidence / "obligations").glob("*.json"))
    )
    if not obligations:
        raise ValueError("no frozen obligations were supplied")
    codeql_value = shutil.which("codeql")
    if codeql_value is None:
        raise RuntimeError("CodeQL is unavailable")
    first = obligations[0]
    cache = root / ".viper" / "cache"
    with tempfile.TemporaryDirectory(prefix="viper-unresolved-") as directory:
        baseline_root = Path(directory) / "baseline"
        _extract_head(root, baseline_root)
        graph = analyze_overlay_source(
            root,
            baseline_root=baseline_root,
            baseline_graph=baseline_graph,
            snapshot=SourceSnapshot(
                base_revision=baseline_graph.snapshot.base_revision,
                source_sha256=source_digest(root),
                revision=None,
            ),
            extraction=first.extraction,
            query=first.query,
            format=first.format,
            codeql_executable=Path(codeql_value).resolve(),
            query_pack=evidence / "query-pack",
            cache_root=cache,
        )
    rows: list[dict[str, object]] = []
    for frozen in obligations:
        try:
            check = check_rename_obligations(
                root=root,
                graph=graph,
                obligations=frozen,
            )
        except RenameAnalysisError as error:
            rows.extend(
                {
                    "old_target": frozen.spec.old_target.model_dump(mode="json"),
                    "new_target": frozen.spec.new_target.model_dump(mode="json"),
                    "dependent": obligation.dependent.model_dump(mode="json"),
                    "kind": obligation.kind,
                    "sites": [
                        site.model_dump(mode="json")
                        for site in obligation.baseline_sites
                    ],
                    "status": "unresolved",
                    "reason": str(error),
                }
                for obligation in frozen.obligations
            )
            continue
        rows.extend(
            {
                "old_target": frozen.spec.old_target.model_dump(mode="json"),
                "new_target": frozen.spec.new_target.model_dump(mode="json"),
                "dependent": transition.obligation.dependent.model_dump(mode="json"),
                "kind": transition.obligation.kind,
                "sites": [
                    site.model_dump(mode="json")
                    for site in transition.obligation.baseline_sites
                ],
                "status": transition.status,
                "reason": transition.message,
            }
            for transition in check.transitions
            if transition.status != "satisfied"
        )
    return {
        "schema_version": 1,
        "candidate_graph_sha256": graph.receipt.graph.sha256,
        "unresolved_count": len(rows),
        "unresolved": rows,
    }


def main() -> int:
    """Run against the repository containing this copied tool."""
    tool = Path(__file__).resolve()
    root = tool.parents[1]
    result = unresolved(root, tool.parent / "evidence")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
