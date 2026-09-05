"""Define the error raised when complete run execution fails."""


class RunError(RuntimeError):
    """Report a local plan, source, materialization, or execution failure."""


class BenchmarkExecutionError(RuntimeError):
    """Report a benchmark request, execution, or publication failure."""


class RestoreError(RuntimeError):
    """Report an invalid restore reference, selection, or destination."""


__all__ = ["BenchmarkExecutionError", "RestoreError", "RunError"]
