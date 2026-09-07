"""Tests for package metadata and deterministic index verification."""

import tomllib
from pathlib import Path

import pytest

from tests.release_index import (
    distribution_hashes,
    fetch_published_hashes,
    published_hashes,
    require_identical_files,
)


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
