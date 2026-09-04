"""Acceptance checks for immutable metric execution and verification evidence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import Field

import viper._verification.metrics as metric_verification
import viper.artifacts as artifacts
import viper.execution._metric as metric_execution
import viper.metrics as metrics
import viper.references as references
from tests.test_verification_acceptance import (
    POLICY,
    build_complete_fixture,
    fetch_attempt,
    replace_run_attempts,
    sha256,
    yaml_bytes,
)
from viper import parameters
from viper.metrics import (
    MeasurementSink,
    MetricContext,
    MetricHandle,
    MetricVerificationReceipt,
    invoke_metric,
)
from viper.verification import verify_run_result
from viper.verification.models import VerificationError


def test_recomputed_metric_requires_one_verification_receipt() -> None:
    """Reject a successful attempt that omits recomputation evidence."""
    resolved_run, store, _ = build_complete_fixture()
    attempt = fetch_attempt(store, resolved_run.attempts[0]).model_copy(
        update={"metric_verification_files": ()}
    )
    invalid_run = replace_run_attempts(store, resolved_run, (attempt,))

    with pytest.raises(VerificationError, match="one immutable verification receipt"):
        verify_run_result(invalid_run, policy=POLICY, fetcher=store.fetch)


def test_metric_receipt_rejects_a_different_recomputed_value() -> None:
    """Reject recomputation evidence whose value fails the frozen comparator."""
    resolved_run, store, _ = build_complete_fixture()
    attempt = fetch_attempt(store, resolved_run.attempts[0])
    reference = attempt.metric_verification_files[0]
    receipt = MetricVerificationReceipt.model_validate(
        yaml.safe_load(store.fetch(reference.stored_at))
    )
    tampered_receipt = receipt.model_copy(
        update={
            "recomputation": receipt.recomputation.model_copy(update={"value": 0.5})
        }
    )
    raw = yaml_bytes(tampered_receipt)
    store.put(reference.stored_at, raw)
    tampered_reference = reference.model_copy(
        update={"sha256": sha256(raw), "bytes": len(raw)}
    )
    invalid_attempt = attempt.model_copy(
        update={"metric_verification_files": (tampered_reference,)}
    )
    invalid_run = replace_run_attempts(store, resolved_run, (invalid_attempt,))

    with pytest.raises(VerificationError, match="does not match its measurement"):
        verify_run_result(invalid_run, policy=POLICY, fetcher=store.fetch)


def test_metric_receipt_rejects_worker_ownership_tampering() -> None:
    """Reject a recomputation receipt assigned to another run attempt."""
    resolved_run, store, _ = build_complete_fixture()
    attempt = fetch_attempt(store, resolved_run.attempts[0])
    reference = attempt.metric_verification_files[0]
    receipt = MetricVerificationReceipt.model_validate(
        yaml.safe_load(store.fetch(reference.stored_at))
    )
    tampered_receipt = receipt.model_copy(
        update={
            "recomputation": receipt.recomputation.model_copy(update={"attempt_id": 2})
        }
    )
    raw = yaml_bytes(tampered_receipt)
    store.put(reference.stored_at, raw)
    tampered_reference = reference.model_copy(
        update={"sha256": sha256(raw), "bytes": len(raw)}
    )
    invalid_attempt = attempt.model_copy(
        update={"metric_verification_files": (tampered_reference,)}
    )
    invalid_run = replace_run_attempts(store, resolved_run, (invalid_attempt,))

    with pytest.raises(VerificationError, match="receipt is invalid"):
        verify_run_result(invalid_run, policy=POLICY, fetcher=store.fetch)


def test_metric_params_reach_live_and_recomputed_execution(tmp_path: Path) -> None:
    """Pass one custom parameter instance through both metric invocation paths."""

    class Scale(parameters.Metric):
        factor: float = Field(gt=0)

    received: list[Scale] = []

    def scaled(context: MetricContext[Scale], value: float) -> float:
        received.append(context.params)
        return value * context.params.factor

    params = Scale(factor=2.0)
    context = MetricContext(params=params)
    sink = MeasurementSink(
        tmp_path / "scaled.jsonl",
        run_id="01JABCDEFGHJKMNPQRSTVWXYZ0",
        attempt_id=1,
        stage_id="train",
        metric_id="scaled",
    )

    assert MetricHandle(scaled, sink, context).record(3.0).value == 6.0
    assert invoke_metric(scaled, context, 4.0) == 8.0
    assert received == [params, params]


def test_metric_dependencies_reuse_snapshot_references() -> None:
    """Derive a metric artifact reference from its enclosing stage snapshot."""
    file = references.SnapshotFileRef(
        path="artifacts/predictions.bin", sha256="a" * 64, bytes=4
    )
    stage_ref = references.ResolvedStageRef(
        stage_id="eval",
        snapshot=references.LocalStageResultSnapshotRef(commit="b" * 64),
        resolved_spec=references.SnapshotFileRef(
            path="stages/eval/resolved.yaml",
            sha256="c" * 64,
            bytes=10,
        ),
    )
    dependency = metrics.MetricDependency(
        source="artifact",
        name="predictions",
        required_data_role="evaluation",
    )
    resolved = metric_execution._resolve_metric_dependencies(
        SimpleNamespace(inputs={}),
        SimpleNamespace(
            inputs={},
            artifacts={"predictions": artifacts.ResolvedSingleFileArtifact(file=file)},
        ),
        stage_ref,
        {},
        SimpleNamespace(dependencies=(dependency,)),
        {},
    )

    assert resolved[0].files[0].stored_at == references.LocalFileRef(
        commit="b" * 64,
        path=file.path,
    )


def test_metric_dependency_rejects_republished_payload() -> None:
    """Treat equal bytes at another immutable revision as a different reference."""
    expected = references.ResolvedFileRef(
        sha256="a" * 64,
        bytes=4,
        stored_at=references.LocalFileRef(commit="b" * 64, path="predictions.bin"),
    )
    republished = expected.model_copy(
        update={
            "stored_at": references.LocalFileRef(
                commit="c" * 64,
                path="predictions.bin",
            )
        }
    )

    dependency = metrics.MetricDependency(
        source="artifact",
        name="predictions",
        required_data_role="evaluation",
    )
    with pytest.raises(VerificationError, match="dependency references differ"):
        metric_verification.verify_metric_dependency_references(
            metrics.ResolvedMetricDependency(
                dependency=dependency,
                files=(republished,),
            ),
            metrics.ResolvedMetricDependency(
                dependency=dependency,
                files=(expected,),
            ),
            "accuracy",
        )
