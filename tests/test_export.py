"""Acceptance tests for portable terminal-run evidence bundles."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from tests.git_repository import REPOSITORY
from tests.test_run_execution import _freeze_retry_plan
from tests.test_verification_acceptance import POLICY, build_complete_fixture
from viper.artifacts import ArtifactPointer
from viper.config import Config, ConfigTypeRef
from viper.execution import export_run, retry, verify_run_bundle
from viper.execution._attempt import execute_attempt
from viper.execution._export import _RecordingFetcher
from viper.execution.errors import RunError, RunExportError
from viper.http import ExternalExecutableSpec, ResolvedExternalExecutable
from viper.references import (
    GitFileRef,
    HuggingFaceStageResultSnapshotRef,
    LocalStageResultSnapshotRef,
    StorageModel,
)
from viper.serialization import parse_yaml_bytes
from viper.verification import verify_run_result


def test_export_traversal_reads_benchmark_pointers_before_root_attempt() -> None:
    """Retain benchmark pointer dependencies even before evaluation is inspected."""
    resolved_run, store, _ = build_complete_fixture(benchmark_enabled=True)

    class RecordingPlanFetcher:
        """Record plan reads while serving one in-memory provenance fixture."""

        def __init__(self) -> None:
            self.paths: list[str] = []

        def __call__(self, location: StorageModel) -> bytes:
            self.paths.append(str(location.path))
            return store.fetch(location)

        def read_plan_source(self, location: GitFileRef) -> bytes:
            return self(location)

        def read_viper_source(self, reference: ConfigTypeRef) -> bytes:
            return (
                Path(inspect.getfile(Config)).resolve().parent / reference.path
            ).read_bytes()

        def list_snapshot_files(
            self,
            snapshot: HuggingFaceStageResultSnapshotRef | LocalStageResultSnapshotRef,
        ) -> tuple[str, ...]:
            return store.list_snapshot_files(snapshot)

    fetcher = RecordingPlanFetcher()
    verified = verify_run_result(resolved_run, policy=POLICY, fetcher=fetcher)
    assert verified.plan.benchmark is not None
    references = (
        verified.plan.benchmark.test,
        *verified.plan.benchmark.splits.values(),
    )
    pointer_paths = {str(reference.stored_at.path) for reference in references}
    pointers = tuple(
        ArtifactPointer.model_validate(
            parse_yaml_bytes(store.fetch(reference.stored_at))
        )
        for reference in references
    )
    root_attempt_path = str(resolved_run.attempts[0].stored_at.path)
    root_attempt_index = fetcher.paths.index(root_attempt_path)

    assert pointer_paths
    assert all(fetcher.paths.index(path) < root_attempt_index for path in pointer_paths)
    assert all(
        fetcher.paths.index(str(pointer.run.stored_at.path)) < root_attempt_index
        for pointer in pointers
    )
    assert all(
        any(
            f"/artifacts/{pointer.artifact.stage_id}/"
            f"{pointer.artifact.artifact_name}/" in path
            for path in fetcher.paths[:root_attempt_index]
        )
        for pointer in pointers
    )


def test_export_run_verifies_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failed and successful bundles after removing their source workspace."""
    trusted_repositories = frozenset(
        {REPOSITORY, "https://example.test/extra-repository"}
    )

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
    failed_manifest = json.loads((failed_bundle / "manifest.json").read_bytes())
    assert failed_manifest["snapshots"]
    assert all(item["members"] for item in failed_manifest["snapshots"])
    assert any(
        entry["source"].get("path") == "environment.yml"
        for entry in failed_manifest["entries"]
    )

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
    manifest["snapshots"][0]["members"] = []
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(RunExportError, match="manifest is invalid"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )

    manifest_path.write_bytes(original_manifest)
    manifest = json.loads(original_manifest)
    foreign_source = {
        "kind": "git",
        "repository": "https://attacker.invalid/repository",
        "commit": "a" * 40,
        "path": "foreign.bin",
    }
    foreign_source_raw = (
        json.dumps(foreign_source, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    foreign_digest = hashlib.sha256(foreign_source_raw).hexdigest()
    foreign_path = f"objects/{foreign_digest[:2]}/{foreign_digest}"
    foreign_raw = b"foreign snapshot payload"
    foreign_target = bundle / foreign_path
    foreign_target.parent.mkdir(parents=True, exist_ok=True)
    foreign_target.write_bytes(foreign_raw)
    manifest["entries"].append(
        {
            "path": foreign_path,
            "bytes": len(foreign_raw),
            "sha256": hashlib.sha256(foreign_raw).hexdigest(),
            "source": foreign_source,
        }
    )
    manifest["entries"].sort(key=lambda entry: entry["path"])
    manifest["snapshots"][0]["members"].append(foreign_path)
    manifest["snapshots"][0]["members"].sort()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    with pytest.raises(RunExportError, match="evidence graph is invalid"):
        verify_run_bundle(
            bundle,
            trusted_source_repositories=frozenset({REPOSITORY}),
        )

    foreign_target.unlink()
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


def test_export_retains_distinct_executable_versions(tmp_path: Path) -> None:
    """Keep two versions of one named executable as distinct bundle payloads."""
    first_raw = b"first executable"
    second_raw = b"second executable"
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.write_bytes(first_raw)
    second_path.write_bytes(second_raw)
    recording = _RecordingFetcher(None)  # type: ignore[arg-type]

    for path, raw in ((first_path, first_raw), (second_path, second_raw)):
        recording.read_external_executable(
            ResolvedExternalExecutable(
                spec=ExternalExecutableSpec(
                    executable_id="transfer",
                    command="transfer",
                    sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),
                ),
                path=path,
            )
        )

    assert len(recording.payloads) == 2
    assert {raw for _, raw in recording.payloads.values()} == {first_raw, second_raw}
