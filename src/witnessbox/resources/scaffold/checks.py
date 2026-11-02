"""Независимые чекеры проекта для witnessbox check (--checkers).

Правило пересчитывается здесь по тексту требования из spec.toml, а не по коду
приложения: импортировать приложение, его SDK или runtime нельзя. Чекер получает
только witness (data записи) и описание инварианта; поле ok приложения он не читает.

Пример `example_rule` — часть заготовки: замените его своим правилом вместе с
[inv.INV-EXAMPLE-1] в spec.toml и тестами в test_checks.py.

Регистрация — через CHECKERS. Имена не должны совпадать с чекерами ядра
(cart_total, transition, sync_merge). Для производных классов входов используйте
DERIVED_PARTITIONS, как описано в документации Witnessbox (docs/extensions.md).

Только стандартная библиотека Python. Ошибка формы свидетельства — WitnessError;
несоблюдение требования — Verdict(ok=False, reason=..., parts=...).
"""

from __future__ import annotations

from witnessbox.api import Verdict, WitnessError


def _int(witness: dict, name: str) -> int:
    if name not in witness:
        raise WitnessError(f"{name}: поле обязательно")
    value = witness[name]
    # bool — подкласс int в Python, но в свидетельстве это ошибка типа.
    if isinstance(value, bool) or not isinstance(value, int):
        raise WitnessError(f"{name}: ожидалось целое, получено {value!r}")
    return value


def example_rule(witness: dict, inv: dict) -> Verdict:
    """INV-EXAMPLE-1: result == value × 2; классы zero/positive/negative."""
    value = _int(witness, "value")
    result = _int(witness, "result")

    parts = {"zero"} if value == 0 else {"positive"} if value > 0 else {"negative"}
    expected = value * 2
    if result != expected:
        return Verdict(False, f"result={result}, по правилу value × 2 ожидалось {expected}", parts)
    return Verdict(True, "", parts)


CHECKERS = {
    "example_rule": example_rule,
}
