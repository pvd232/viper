"""Define the error raised when complete run execution fails."""


class RunError(RuntimeError):
    """Report a local plan, source, materialization, or execution failure."""


class BenchmarkExecutionError(RuntimeError):
    """Report a benchmark request, execution, or publication failure."""


__all__ = ["BenchmarkExecutionError", "RunError"]
