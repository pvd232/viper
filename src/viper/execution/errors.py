"""Define errors raised by run and benchmark execution."""

from __future__ import annotations

from .results import RunResult


class RunError(RuntimeError):
    """Report a run failure and retain its terminal result when available."""

    def __init__(self, message: str, *, result: RunResult | None = None) -> None:
        """Attach the failed terminal result without suppressing the exception."""
        super().__init__(message)
        self.result = result


class RunPromotionError(RuntimeError):
    """Report a local run graph that cannot be promoted without execution."""


class BenchmarkExecutionError(RuntimeError):
    """Report a benchmark request, execution, or publication failure."""


class RunExportError(RuntimeError):
    """Report invalid, incomplete, or unsafe run-bundle operations."""


class RestoreError(RuntimeError):
    """Report an invalid restore reference, selection, or destination."""


__all__ = [
    "BenchmarkExecutionError",
    "RestoreError",
    "RunError",
    "RunExportError",
    "RunPromotionError",
]
