"""Acceptance checks for immutable metric execution and verification evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import Field

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
