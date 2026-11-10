"""Compatibility public module of the shared checkers."""
import sys
from witnessbox.checker import checkers as _impl

sys.modules[__name__] = _impl
