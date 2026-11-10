"""Tests of the example checker from the scaffold. Replace together with checks.py and spec.toml.

The package is installed in the tool environment (`uv tool install`), not in the system
python3, so the tests are run by the distribution command from the project root:

    witnessbox test-checks ebt

It runs unittest with the installation interpreter and treats a zero-test run
as a failure, not a success.

Checked: valid evidence of each input partition, a rule violation and
a malformed shape. For each witness field there must be a case where its corruption is caught
(or WitnessError), otherwise the checker does not check that field.
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
        self.assertIn("expected 6", verdict.reason)

    def test_missing_field(self):
        with self.assertRaises(WitnessError):
            checks.example_rule({"value": 1}, {})

    def test_bool_is_not_an_integer(self):
        with self.assertRaises(WitnessError):
            self.rule(True, 2)


if __name__ == "__main__":
    unittest.main()
