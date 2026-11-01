"""Тесты примера чекера из заготовки. Замените вместе с checks.py и spec.toml.

Запуск из каталога ebt/. Пакет установлен в окружение инструмента (`uv tool
install`), а не в системный python3, поэтому интерпретатор берём у поставки:

    python=$(ebt-gate --installation | python3 -c 'import json, sys; print(json.load(sys.stdin)["python"])')
    "$python" -m unittest discover -s . -p 'test_checks.py'

Здесь системный python3 только читает JSON; witnessbox он не импортирует.

Проверяются: корректное свидетельство каждого класса входов, нарушение правила и
некорректная форма. Для каждого поля witness нужен случай, где его порча ловится
(или WitnessError), иначе чекер это поле не проверяет.
"""

from __future__ import annotations

import unittest

import checks
from witnessbox.api import WitnessError


class ExampleRule(unittest.TestCase):
    def rule(self, value, result):
        return checks.example_rule({"value": value, "result": result}, {})

    def test_registered(self):
        self.assertIs(checks.CHECKERS["example_rule"], checks.example_rule)

    def test_positive(self):
        verdict = self.rule(3, 6)
        self.assertTrue(verdict.ok, verdict.reason)
        self.assertEqual(verdict.parts, {"positive"})

    def test_zero(self):
        verdict = self.rule(0, 0)
        self.assertTrue(verdict.ok, verdict.reason)
        self.assertEqual(verdict.parts, {"zero"})

    def test_negative(self):
        verdict = self.rule(-4, -8)
        self.assertTrue(verdict.ok, verdict.reason)
        self.assertEqual(verdict.parts, {"negative"})

    def test_wrong_result_is_a_violation(self):
        verdict = self.rule(3, 7)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.parts, {"positive"})
        self.assertIn("ожидалось 6", verdict.reason)

    def test_missing_field(self):
        with self.assertRaises(WitnessError):
            checks.example_rule({"value": 1}, {})

    def test_bool_is_not_an_integer(self):
        with self.assertRaises(WitnessError):
            self.rule(True, 2)


if __name__ == "__main__":
    unittest.main()
