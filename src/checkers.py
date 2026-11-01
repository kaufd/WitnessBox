"""Совместимый публичный модуль общих чекеров."""
import sys
from ebt_verification.checker import checkers as _impl

sys.modules[__name__] = _impl
