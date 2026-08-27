"""Run one project-owned artifact loader and write its validation result."""

from __future__ import annotations

import os
from pathlib import Path

from .artifact_loaders import (
    ArtifactLoaderError,
    ArtifactLoaderWorkerContext,
    ArtifactLoaderWorkerResult,
    validate_artifact_context,
)


def main() -> int:
    """Validate one materialized artifact and preserve the exact outcome."""
    context_path = os.environ.get("VIPER_CONTEXT_PATH")
    if context_path is None:
        raise ValueError("VIPER_CONTEXT_PATH is required")
    context = ArtifactLoaderWorkerContext.model_validate_json(
        Path(context_path).read_text(encoding="utf-8")
    )
    context.result_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = ArtifactLoaderWorkerResult(
            validation=validate_artifact_context(context)
        )
    except ArtifactLoaderError as exc:
        result = ArtifactLoaderWorkerResult(error=str(exc))
    except Exception as exc:
        result = ArtifactLoaderWorkerResult(error=f"unexpected worker error: {exc}")
    context.result_path.write_text(result.model_dump_json(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
