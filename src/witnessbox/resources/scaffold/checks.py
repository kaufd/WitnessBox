"""Independent project checkers for witnessbox check (--checkers).

The rule is recomputed here from the requirement text in spec.toml, not from the
application code: importing the application, its SDK or runtime is forbidden. The checker receives
only the witness (record data) and the invariant description; it does not read the application ok field.

The `example_rule` example is part of the scaffold: replace it with your own rule together with
[inv.INV-EXAMPLE-1] in spec.toml and the tests in test_checks.py.

Registration is through CHECKERS. Names must not clash with core checkers
(cart_total, transition, sync_merge). For derived input partitions use
DERIVED_PARTITIONS, as described in the Witnessbox documentation (docs/extensions.md).

Python standard library only. An evidence shape error is WitnessError;
a requirement violation is Verdict(ok=False, reason=..., parts=...).
"""

from __future__ import annotations

from witnessbox.api import Verdict, WitnessError


def _int(witness: dict, name: str) -> int:
    if name not in witness:
        raise WitnessError(f"{name}: field is required")
    value = witness[name]
    # bool is a subclass of int in Python, but in the evidence it is a type error.
    if isinstance(value, bool) or not isinstance(value, int):
        raise WitnessError(f"{name}: expected an integer, got {value!r}")
    return value


def example_rule(witness: dict, inv: dict) -> Verdict:
    """INV-EXAMPLE-1: result == value × 2; partitions zero/positive/negative."""
    value = _int(witness, "value")
    result = _int(witness, "result")

    parts = {"zero"} if value == 0 else {"positive"} if value > 0 else {"negative"}
    expected = value * 2
    if result != expected:
        return Verdict(False, f"result={result}, by the rule value × 2 expected {expected}", parts)
    return Verdict(True, "", parts)


CHECKERS = {
    "example_rule": example_rule,
}
