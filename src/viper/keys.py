"""Define canonical input and output names for built-in stage roles."""

from typing import Final

from .ids import InputName, OutputName


class Train:
    """Canonical input and output names used by training stages."""

    MODEL: Final[OutputName] = "model"
    RESUME_STATE: Final[OutputName] = "resume_state"


class Eval:
    """Canonical input and output names used by evaluation stages."""

    MODEL: Final[InputName] = "model"
    TEST: Final[InputName] = "test"
    PREDICTIONS: Final[OutputName] = "predictions"


__all__ = ["Eval", "Train"]
