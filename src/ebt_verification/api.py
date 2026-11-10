"""Compatibility import of the public Witnessbox types.

Legacy project checkers import ``Verdict`` and ``WitnessError`` from here;
the same objects as from :mod:`witnessbox.api` are returned. There is no second implementation.
"""
from __future__ import annotations

from witnessbox.api import CheckFn, PartitionsFn, Verdict, WitnessError

__all__ = ["Verdict", "WitnessError", "CheckFn", "PartitionsFn"]
