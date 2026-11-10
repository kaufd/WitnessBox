"""Public contract of independent EBT project checkers.

Project extensions import the types from here; the legacy import from ``checkers``
returns the same objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

__all__ = ["Verdict", "WitnessError", "CheckFn", "PartitionsFn"]


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    parts: set[str] = field(default_factory=set)


class WitnessError(Exception):
    """The evidence exists but is malformed (types, structure)."""


CheckFn = Callable[[dict, dict], Verdict]
PartitionsFn = Callable[[dict], list[str]]
