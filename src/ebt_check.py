"""Совместимое имя модуля чекера для `import ebt_check`."""
import sys
from witnessbox.checker import ebt_check as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
