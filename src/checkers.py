"""Совместимый публичный модуль общих чекеров."""
import sys
from witnessbox.checker import checkers as _impl

sys.modules[__name__] = _impl
