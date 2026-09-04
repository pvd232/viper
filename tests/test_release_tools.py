"""Tests for package metadata and deterministic index verification."""

import hashlib
import json
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.release_index import (
    distribution_hashes,
    fetch_published_hashes,
    published_hashes,
    require_identical_files,
)
from tools.plan import publish as publication
from viper.system_impact.models import Acceptance, PlanCheck


def test_release_metadata_matches_the_approved_public_identity() -> None:
    """Freeze the package identity and supported installation contract."""
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "viper-provenance"
    assert project["version"] == "0.1.0a2"
    assert project["description"] == (
        "Run and verify reproducible ML experiments with machine-readable "
        "guardrails for agents."
    )
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert project["authors"] == [
        {"name": "Peter Driscoll", "email": "peterdriscoll27@gmail.com"}
    ]
    assert project["maintainers"] == project["authors"]
    assert project["urls"] == {
        "Repository": "https://github.com/pvd232/viper",
        "Documentation": "https://github.com/pvd232/viper/tree/main/docs",
        "Issues": "https://github.com/pvd232/viper/issues",
    }
    assert project["scripts"] == {"viper": "viper.cli:main"}
    assert project["dependencies"] == [
        "huggingface_hub>=1,<2",
        "httpx>=0.28,<1",
        "numpy>=2,<3",
        "pydantic>=2.12,<3",
        "PyYAML>=6,<7",
        "torch>=2.6,<3",
        "torchdata==0.11.0",
    ]


def test_distribution_hashes_binds_each_release_filename(tmp_path: Path) -> None:
    """Hash every release file and preserve its exact filename."""
    (tmp_path / "viper.whl").write_bytes(b"wheel")
    (tmp_path / "viper.tar.gz").write_bytes(b"source")

    assert distribution_hashes(tmp_path) == {
        "viper.tar.gz": (
            "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d"
        ),
        "viper.whl": (
            "ba59926159d2aa256eb8739b8da7e2b574b960e1202c6d624cbe981cef996c91"
        ),
    }


def test_published_hashes_requires_complete_file_identity() -> None:
    """Extract complete index identities and reject an incomplete entry."""
    assert published_hashes(
        {
            "urls": [
                {
                    "filename": "viper.whl",
                    "digests": {"sha256": "a" * 64},
                }
            ]
        }
    ) == {"viper.whl": "a" * 64}

    with pytest.raises(ValueError, match="filename or SHA-256"):
        published_hashes({"urls": [{"filename": "viper.whl"}]})


def test_release_file_comparison_rejects_any_index_difference() -> None:
    """Require identical filenames and digests across the release boundary."""
    release = {"viper.whl": "a" * 64}
    require_identical_files(release, release)

    with pytest.raises(ValueError, match="differ from local distributions"):
        require_identical_files(release, {"viper.whl": "b" * 64})


def test_package_index_requires_https() -> None:
    """Reject a package-index endpoint that lacks transport authentication."""
    with pytest.raises(ValueError, match="absolute HTTPS URL"):
        fetch_published_hashes("http://example.com", "viper", "1.0")


def test_publish_binds_compact_evidence_to_one_hugging_face_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish accepted contracts and CodeQL rows under the check digest."""
    root = tmp_path / "repository"
    contract = root / "docs/plan.md"
    contract.parent.mkdir(parents=True)
    contract.write_text("# Plan\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    subprocess.run(("git", "-C", str(root), "add", "docs/plan.md"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=VIPER Test",
            "-c",
            "user.email=viper@example.invalid",
            "commit",
            "-qm",
            "plan",
        ),
        check=True,
    )
    revision = subprocess.run(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    check = PlanCheck.model_construct(contracts=("docs/plan.md",))
    check_payload = check.model_dump(mode="json")
    acceptance = Acceptance(
        check=hashlib.sha256(
            json.dumps(
                check_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        revision=revision,
    )
    results = tmp_path / "results"
    for graph in ("baseline-codeql", "planned-codeql"):
        directory = results / graph
        directory.mkdir(parents=True)
        for name in publication.CODEQL_FILES:
            (directory / name).write_bytes(f"{graph}/{name}".encode())
    (results / "result.json").write_text(
        json.dumps({"passed": True, "check": check_payload}),
        encoding="utf-8",
    )
    (results / "acceptance.json").write_text(
        acceptance.model_dump_json(),
        encoding="utf-8",
    )

    calls: dict[str, object] = {}

    class FakeApi:
        def create_repo(self, **kwargs) -> None:
            calls["repo"] = kwargs

        def create_commit(self, **kwargs):
            calls["operations"] = tuple(kwargs["operations"])
            return SimpleNamespace(oid="a" * 40)

    monkeypatch.setattr(publication, "HfApi", FakeApi)

    reference = publication.publish(
        root=root,
        results=results,
        repository="pvd232/viper-plan-evidence",
        check=check,
        acceptance=acceptance,
    )

    assert calls["repo"] == {
        "repo_id": "pvd232/viper-plan-evidence",
        "repo_type": "dataset",
        "private": True,
        "exist_ok": True,
    }
    operations = calls["operations"]
    paths = {operation.path_in_repo for operation in operations}
    prefix = f"checks/{acceptance.check}"
    assert f"{prefix}/manifest.json" in paths
    assert f"{prefix}/contracts/docs/plan.md" in paths
    assert f"{prefix}/codeql/baseline/Declarations.json" in paths
    assert f"{prefix}/codeql/planned/Dependencies.bqrs" in paths
    assert reference.stored_at.repository == "pvd232/viper-plan-evidence"
    assert reference.stored_at.commit == "a" * 40
    assert reference.stored_at.path == f"{prefix}/manifest.json"

    with pytest.raises(publication.PublicationError, match="does not identify"):
        publication.publish(
            root=root,
            results=results,
            repository="pvd232/viper-plan-evidence",
            check=check,
            acceptance=acceptance.model_copy(update={"check": "f" * 64}),
        )
