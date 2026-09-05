"""Validate project parameters in a dedicated worker process."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .._parameter.validation import (
    ParameterValidationContext,
    parameter_model_path,
    validate_parameters,
)
from ..serialization import load_stage_spec
from ..stages import ParameterizedSpec


def main() -> int:
    """Validate frozen stage parameters and write their effective JSON mapping."""
    context_path = os.environ.get("VIPER_CONTEXT_PATH")
    if context_path is None:
        raise ValueError("VIPER_CONTEXT_PATH is required")
    context = ParameterValidationContext.model_validate_json(
        Path(context_path).read_text(encoding="utf-8")
    )
    stage = load_stage_spec(context.stage_spec_path)
    if not isinstance(stage, ParameterizedSpec):
        raise ValueError("parameter validation requires a parameterized stage")
    reference = stage.parameter_model
    validated = validate_parameters(
        parameter_model_path(Path.cwd(), reference),
        reference,
        stage.params,
        type(stage.params),
    )
    context.result_path.write_text(
        json.dumps(validated, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
