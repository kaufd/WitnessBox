"""Публичный контракт независимых проектных чекеров EBT.

Проектные расширения импортируют типы отсюда; прежний импорт из ``checkers``
возвращает те же объекты.
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
    """Свидетельство есть, но оно некорректно по форме (типы, структура)."""


CheckFn = Callable[[dict, dict], Verdict]
PartitionsFn = Callable[[dict], list[str]]
