"""Publish accepted plan evidence to an immutable Hugging Face revision."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

import viper._subprocess as subprocess
from viper.references import HuggingFaceFileRef, ResolvedFileRef
from viper.system_impact.models import Acceptance, PlanCheck

ROOT = Path(__file__).parents[2]
CODEQL_FILES = (
    "Declarations.bqrs",
    "Declarations.json",
    "Dependencies.bqrs",
    "Dependencies.json",
)


class PublicationError(ValueError):
    """Report evidence that cannot be bound to one accepted plan."""


def _sha256(value: bytes) -> str:
    """Hash bytes for the manifest and returned file reference."""
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    """Serialize one stable JSON value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _git_file(root: Path, revision: str, relative: str) -> bytes:
    """Read a contract from the accepted commit."""
    completed = subprocess.run(
        ("git", "show", f"{revision}:{relative}"),
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise PublicationError(f"accepted commit does not contain {relative}")
    return completed.stdout


def _files(
    *,
    root: Path,
    results: Path,
    check: PlanCheck,
    acceptance: Acceptance,
) -> dict[str, bytes]:
    """Collect the compact evidence needed to inspect the accepted plan."""
    files = {
        "result.json": (results / "result.json").read_bytes(),
        "acceptance.json": (results / "acceptance.json").read_bytes(),
    }
    for graph in ("baseline-codeql", "planned-codeql"):
        for name in CODEQL_FILES:
            source = results / graph / name
            if not source.is_file():
                raise PublicationError(f"missing plan evidence: {graph}/{name}")
            content = source.read_bytes()
            published_name = name
            if source.suffix == ".bqrs":
                content = base64.b64encode(content) + b"\n"
                published_name = f"{name}.base64"
            files[f"codeql/{graph.removesuffix('-codeql')}/{published_name}"] = content
    for contract in check.contracts:
        files[f"contracts/{contract}"] = _git_file(
            root,
            acceptance.revision,
            str(contract),
        )
    return files


def _manifest(
    *,
    repository: str,
    acceptance: Acceptance,
    files: Mapping[str, bytes],
) -> bytes:
    """Bind the accepted check to every uploaded path and digest."""
    return (
        _canonical_json(
            {
                "schema_version": 1,
                "repository": repository,
                "acceptance": acceptance.model_dump(mode="json"),
                "files": [
                    {
                        "path": name,
                        "sha256": _sha256(content),
                        "bytes": len(content),
                    }
                    for name, content in sorted(files.items())
                ],
            }
        )
        + b"\n"
    )


def publish(
    *,
    root: Path,
    results: Path,
    repository: str,
    check: PlanCheck,
    acceptance: Acceptance,
) -> ResolvedFileRef:
    """Upload one accepted plan and return its immutable manifest reference."""
    check_bytes = _canonical_json(check.model_dump(mode="json"))
    if _sha256(check_bytes) != acceptance.check:
        raise PublicationError("acceptance does not identify the supplied PlanCheck")

    files = _files(
        root=root.resolve(),
        results=results.resolve(),
        check=check,
        acceptance=acceptance,
    )
    manifest = _manifest(
        repository=repository,
        acceptance=acceptance,
        files=files,
    )
    prefix = f"checks/{acceptance.check}"
    uploads = {
        **files,
        "manifest.json": manifest,
    }
    api = HfApi()
    api.create_repo(
        repo_id=repository,
        repo_type="dataset",
        private=True,
        exist_ok=True,
    )
    committed = api.create_commit(
        repo_id=repository,
        repo_type="dataset",
        commit_message=f"Publish plan evidence {acceptance.check[:12]}",
        operations=(
            CommitOperationAdd(
                path_in_repo=f"{prefix}/{name}",
                path_or_fileobj=content,
            )
            for name, content in sorted(uploads.items())
        ),
    )
    return ResolvedFileRef(
        sha256=_sha256(manifest),
        bytes=len(manifest),
        stored_at=HuggingFaceFileRef(
            repository=repository,
            commit=committed.oid,
            path=f"{prefix}/manifest.json",
            repo_type="dataset",
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Publish one saved result and its acceptance record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    results = args.results.resolve()
    result = json.loads((results / "result.json").read_text(encoding="utf-8"))
    if not result.get("passed"):
        raise PublicationError("cannot publish a failed plan result")
    check = PlanCheck.model_validate(result["check"])
    acceptance = Acceptance.model_validate_json(
        (results / "acceptance.json").read_text(encoding="utf-8")
    )
    reference = publish(
        root=args.root,
        results=results,
        repository=args.repository,
        check=check,
        acceptance=acceptance,
    )
    output = (
        args.output.resolve()
        if args.output is not None
        else results / "publication.json"
    )
    output.write_text(reference.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"published {reference.stored_at.commit}; saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
