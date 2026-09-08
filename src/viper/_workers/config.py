"""Validate workspace config in a dedicated worker process."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .._config.validation import (
    ConfigValidationContext,
    config_type_path,
    validate_config,
)
from ..serialization import load_stage_spec
from ..stages import ParameterizedSpec


def main() -> int:
    """Validate frozen stage config and write its effective JSON mapping."""
    context_path = os.environ.get("VIPER_CONTEXT_PATH")
    if context_path is None:
        raise ValueError("VIPER_CONTEXT_PATH is required")
    context = ConfigValidationContext.model_validate_json(
        Path(context_path).read_text(encoding="utf-8")
    )
    stage = load_stage_spec(context.stage_spec_path)
    if not isinstance(stage, ParameterizedSpec):
        raise ValueError("config validation requires a parameterized stage")
    reference = stage.config_type
    validated = validate_config(
        config_type_path(Path.cwd(), reference),
        reference,
        stage.config,
        type(stage.config),
    )
    context.result_path.write_text(
        json.dumps(validated, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
