#!/usr/bin/env python3
"""Совместимый фасад CLI и прежних импортов независимого чекера EBT."""
from __future__ import annotations

import sys

from .checkers import CHECKERS, DERIVED_PARTITIONS, Verdict, WitnessError
from .engine import *  # noqa: F403 — совместимость экспортированных функций и категорий.
from .engine import _known_match, _mutate
from .input import load_checkers, load_jsonl, load_known, load_spec, validate_known
from .rendering import _short, render_md
from .cli import __version__, main
from .cli import __doc__ as __doc__

if __name__ == "__main__":
    sys.exit(main())
