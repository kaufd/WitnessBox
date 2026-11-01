"""Совместимый импорт публичных типов Witnessbox.

Прежние проектные чекеры импортируют ``Verdict`` и ``WitnessError`` отсюда;
возвращаются те же объекты, что и из :mod:`witnessbox.api`. Второй реализации нет.
"""
from __future__ import annotations

from witnessbox.api import CheckFn, PartitionsFn, Verdict, WitnessError

__all__ = ["Verdict", "WitnessError", "CheckFn", "PartitionsFn"]
