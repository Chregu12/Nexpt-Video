"""Apple Motion automation bridge for Nexpt-Video."""

from .core import MotionError
from .spec import SpecError, normalize_spec, validate_spec

__all__ = ["MotionError", "SpecError", "normalize_spec", "validate_spec"]
