"""Acceptance tests for portable terminal-run evidence bundles."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.git_repository import REPOSITORY
from tests.test_run_execution import _freeze_retry_plan
from viper.execution import export_run, retry, verify_run_bundle
from viper.execution._attempt import execute_attempt
from viper.execution.errors import RunError, RunExportError


def test_export_run_verifies_offline(tmp_path: Path) -> None:
    """Verify failed and successful bundles after removing their source workspace."""
    root = tmp_path / "project"
    frozen = _freeze_retry_plan(root)
    with pytest.raises(RunError) as caught:
        execute_attempt(root, frozen.files[-1], plan=frozen.reference)
    failed = caught.value.result
    assert failed is not None

    failed_bundle = tmp_path / "failed-bundle"
    failed_export = export_run(
        root,
        failed.path,
        failed_bundle,
        trusted_source_repositories=frozenset({REPOSITORY}),
    )
    first_duplicate = tmp_path / "failed-bundle-copy"
    export_run(
        root,
        failed.path,
        first_duplicate,
        trusted_source_repositories=frozenset({REPOSITORY}),
    )
    assert (failed_bundle / "manifest.json").read_bytes() == (
        first_duplicate / "manifest.json"
    ).read_bytes()

    succeeded = retry(root, frozen.files[-1])
    succeeded_bundle = tmp_path / "succeeded-bundle"
    succeeded_export = export_run(
        root,
        succeeded.path,
        succeeded_bundle,
        trusted_source_repositories=frozenset({REPOSITORY}),
    )
    root.rename(tmp_path / "source-workspace-removed")

    verified_failed = verify_run_bundle(
        failed_bundle,
        trusted_source_repositories=frozenset({REPOSITORY}),
        expected_manifest_sha256=failed_export.manifest_sha256,
    )
    verified_succeeded = verify_run_bundle(
        succeeded_bundle,
        trusted_source_repositories=frozenset({REPOSITORY}),
        expected_manifest_sha256=succeeded_export.manifest_sha256,
    )
    assert verified_failed.file_count > 1
    assert verified_succeeded.file_count >= verified_failed.file_count


def test_export_verifier_rejects_missing_or_changed_file(tmp_path: Path) -> None:
    """Reject absent and altered payloads without consulting their source store."""
    root = tmp_path / "project"
    frozen = _freeze_retry_plan(root)
    with pytest.raises(RunError) as caught:
        execute_attempt(root, frozen.files[-1], plan=frozen.reference)
    failed = caught.value.result
    assert failed is not None
    bundle = tmp_path / "bundle"
    export_run(
        root,
        failed.path,
        bundle,
        trusted_source_repositories=frozenset({REPOSITORY}),
    )
    payload = next(
        path
        for path in sorted(bundle.rglob("*"))
        if path.name != "manifest.json" and path.is_file()
    )
    raw = payload.read_bytes()
    payload.unlink()
    with pytest.raises(RunExportError, match="files differ"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )
    payload.write_bytes(raw + b"changed")
    with pytest.raises(RunExportError, match="byte count differs"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )
