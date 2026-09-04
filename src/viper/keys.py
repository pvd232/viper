from typing import Final

from ._schema import ArtifactName
from .ids import InputName


class Train:
    """Canonical artifact and input names used by training stages."""

    MODEL: Final[ArtifactName] = "model"
    STATE: Final[ArtifactName] = "state"


class Eval:
    """Canonical input and artifact names used by evaluation stages."""

    MODEL: Final[InputName] = "model"
    TEST: Final[InputName] = "test"
    PREDS: Final[ArtifactName] = "preds"


__all__ = ["Eval", "Train"]
