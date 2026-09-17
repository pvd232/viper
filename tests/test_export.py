"""Acceptance tests for portable terminal-run evidence bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.git_repository import REPOSITORY
from tests.test_run_execution import _freeze_retry_plan
from viper.execution import export_run, retry, verify_run_bundle
from viper.execution._attempt import execute_attempt
from viper.execution.errors import RunError, RunExportError


def test_export_run_verifies_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failed and successful bundles after removing their source workspace."""
    extra_repository = next(
        candidate
        for index in range(100)
        if next(
            iter(
                frozenset(
                    {
                        REPOSITORY,
                        (candidate := f"https://example.test/extra-{index}"),
                    }
                )
            )
        )
        != REPOSITORY
    )
    trusted_repositories = frozenset({REPOSITORY, extra_repository})

    def reject_external_fetch(*_args, **_kwargs):
        raise AssertionError("local run source was treated as external")

    monkeypatch.setattr(
        "viper.execution._source.fetch_git_file_bytes",
        reject_external_fetch,
    )
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
        trusted_source_repositories=trusted_repositories,
    )
    first_duplicate = tmp_path / "failed-bundle-copy"
    export_run(
        root,
        failed.path,
        first_duplicate,
        trusted_source_repositories=trusted_repositories,
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
        trusted_source_repositories=trusted_repositories,
    )
    root.rename(tmp_path / "source-workspace-removed")

    verified_failed = verify_run_bundle(
        failed_bundle,
        trusted_source_repositories=trusted_repositories,
        expected_manifest_sha256=failed_export.manifest_sha256,
    )
    verified_succeeded = verify_run_bundle(
        succeeded_bundle,
        trusted_source_repositories=trusted_repositories,
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


def test_export_verifier_consumes_every_manifest_payload(tmp_path: Path) -> None:
    """Reject changed framework source and otherwise valid orphan payloads."""
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
    manifest_path = bundle / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    source_entry = next(
        entry
        for entry in manifest["entries"]
        if entry["source"].get("kind") == "viper_source"
    )
    source_path = bundle / source_entry["path"]
    original_source = source_path.read_bytes()
    changed_source = b"not the declared VIPER source\n"
    source_path.write_bytes(changed_source)
    source_entry["bytes"] = len(changed_source)
    source_entry["sha256"] = hashlib.sha256(changed_source).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(RunExportError, match="evidence graph is invalid"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )

    source_path.write_bytes(original_source)
    manifest_path.write_bytes(original_manifest)
    manifest = json.loads(original_manifest)
    orphan_source = {
        "kind": "executable",
        "command": "unused",
        "executable_id": "unused",
    }
    source_raw = (
        json.dumps(orphan_source, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    source_digest = hashlib.sha256(source_raw).hexdigest()
    orphan_path = f"objects/{source_digest[:2]}/{source_digest}"
    orphan_raw = b"unused executable"
    target = bundle / orphan_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(orphan_raw)
    manifest["entries"].append(
        {
            "path": orphan_path,
            "bytes": len(orphan_raw),
            "sha256": hashlib.sha256(orphan_raw).hexdigest(),
            "source": orphan_source,
        }
    )
    manifest["entries"].sort(key=lambda entry: entry["path"])
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(RunExportError, match="evidence graph is invalid"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )


def test_export_verifier_wraps_missing_manifest(tmp_path: Path) -> None:
    """Report an incomplete bundle through the public export error type."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    with pytest.raises(RunExportError, match="manifest is unavailable"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )
