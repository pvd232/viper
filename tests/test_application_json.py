"""Golden tests for the stable application JSON result families."""

from pathlib import Path

import pytest
from pydantic import HttpUrl

from viper.application import (
    CapabilitiesRequest,
    FailureOrigin,
    ViperFailure,
    get_capabilities,
    result_json_bytes,
)

GOLDEN_ROOT = Path(__file__).parent / "golden/application"


def test_success_json_matches_golden_document() -> None:
    """Freeze the canonical encoding shared by every success model."""
    result = get_capabilities(CapabilitiesRequest())

    assert result_json_bytes(result) == (GOLDEN_ROOT / "success.json").read_bytes()


@pytest.mark.parametrize(
    ("origin", "operation", "code"),
    (
        ("request", "run", "invalid_request"),
        ("application", "run", "execution_failed"),
        ("cli", None, "invalid_request"),
        ("internal", "run", "internal_error"),
    ),
)
def test_failure_json_matches_origin_golden_document(
    origin: FailureOrigin,
    operation: str | None,
    code: str,
) -> None:
    """Freeze one canonical public failure document for each producing layer."""
    failure = ViperFailure.model_validate(
        {
            "operation": operation,
            "origin": origin,
            "code": code,
            "message": f"{origin} failure",
        }
    )

    assert (
        result_json_bytes(failure)
        == (GOLDEN_ROOT / f"failure.{origin}.json").read_bytes()
    )


def test_public_json_serializes_validated_urls_as_strings() -> None:
    """Represent a protocol URL through its canonical text form."""
    failure = ViperFailure(
        operation="run",
        origin="application",
        code="retrieval_failed",
        message="retrieval failed",
        details={
            "repository": HttpUrl("https://github.com/example/project"),
        },
    )

    assert b'"repository":"https://github.com/example/project"' in (
        result_json_bytes(failure)
    )
