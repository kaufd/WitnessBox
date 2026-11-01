"""Совместимое имя модуля CLI ebt-check."""
import sys
from ebt_verification.checker import ebt_check as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
