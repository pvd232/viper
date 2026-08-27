"""Tests for deterministic package-index release verification."""

from pathlib import Path

import pytest

from tests.release_index import (
    distribution_hashes,
    fetch_published_hashes,
    published_hashes,
    require_identical_files,
)


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
