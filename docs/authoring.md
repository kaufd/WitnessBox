# How to write a spec: from requirement to evidence tests

**English** · [Русский](authoring.ru.md)

This guide is for whoever connects Witnessbox to a project and writes `spec.toml`, `checks.py` and the evidence tests. Commands and the scaffold are in the [quick start](quickstart.md) and the [scaffold](scaffold.md) page; the record format is in the [SDK](sdk.md); the extension contract is in [extensions](extensions.md).

The chain is:

```
requirement  →  invariant in spec.toml  →  checker in checks.py  →  evidence tests
  (human)        witness + partitions       recomputation by witness   ev() per partition
```

A human approves the spec, not the one who writes the code (D4). Otherwise the rule under test gets fitted to the implementation. The checker does not import the application and does not read its `ok`. The whole point of the method is a rule written apart from the code and recomputed independently.

The examples below use an invented requirement about a shipping fee. Its spec, checker and evidence were run through the real `witnessbox check` version 0.7.0. The fragments about the observation level (OBS) describe the method and were not run against an application in this repository (see [limits](#limits-of-this-guide)).

## 1. Requirement

The source requirement is the text of a ticket or an owner's decision, not a summary of the code:

> Shipping costs 300 kopecks. If the sum of the goods is at least 5000 kopecks, shipping is free.

Before formalizing, write down:

- **what is decided**: the result that must be correct (`fee`);
- **what it depends on**: the inputs of the decision (`subtotal`);
- **where the boundaries are**: the values at which the rule changes (exactly `5000`);
- **how values are encoded**: money as integer minimal units, time, fractions: the [SDK conventions](sdk.md#fractions-time-and-concurrency). Units and the rounding mode come from the requirement, not from the code.

If the requirement does not say this (what happens at exactly 5000? kopecks or rubles?), the question goes back to the owner. An analyst's guess in `spec.toml` is the same defect the gate is meant to catch.

## 2. `spec.toml`

```toml
[meta]
version = "2026-11-02"   # date of human approval

[req.REQ-SHIP-1]
text = """Shipping costs 300 kopecks. If the sum of the goods is at least 5000 kopecks,
shipping is free."""
source = """ticket: SHIP-12"""

[inv.INV-SHIP-1]
req = "REQ-SHIP-1"
statement = "fee == 0 when subtotal >= 5000, otherwise fee == 300"
checker = "shipping_fee"
witness = ["subtotal", "fee"]
partitions = ["below_threshold", "at_threshold", "above_threshold"]
```

- `[req.*]` is the requirement in the words of the domain, plus `source`: where it comes from (a ticket, a dated decision, a reference `path:line`).
- `[inv.*]` is the verifiable formulation. One requirement can have several invariants. `checker` is a name from `CHECKERS` in `checks.py` or a core checker.

The full list of fields and an example of a state machine are in the comments of the scaffold `spec.toml`.

### `witness`: the minimum for recomputation

`witness` lists the `data` fields without which the result **cannot be recomputed** independently of the application. The criterion: the checker receives only `data` and the requirement text. Everything the rule needs must be in the record; anything extra must not.

| What to record | What not to record |
|---|---|
| the inputs of the decision (`subtotal`) | internal intermediate values the checker can compute itself |
| the result the application returned (`fee`) | flags and state that do not affect the rule |
| what the application "knew" and the checker cannot know: the `now` it used, an exchange rate, the chosen tariff | identifiers and texts "for debugging" |

The rule is recomputed from the inputs. If it cannot be obtained without an intermediate value (for example, a discount depends on a list of items), the list goes into `witness`, not the total. The shorter the `witness`, the fewer fields where the checker and the application can disagree, and the cheaper the maintenance. `--self-test` ([below](#5---self-test)) shows a field the checker does not use.

### `partitions`: input classes, not a list of tests

`partitions` are the classes of inputs of the **requirement**, and each must appear in the evidence. If no record falls into a class, the gate reports "partitions not encountered": the rule is not proven on it.

Classes are derived from the requirement, not from which tests already exist:

- For `fee` there are three classes: below the threshold, exactly at the threshold, above. The boundary class (`at_threshold`) is needed separately: the `>=`/`>` error lives there.
- For rounding, a separate class "exactly half a step" (`sdk.md` advises adding it).
- For time: the daylight saving switch, the end of a month, 29 February.
- For empty inputs: an empty cart, zero, a negative value.

Bad: `partitions = ["test_shipping_1", "test_shipping_2"]`. These are test names. They do not say which input values are covered, and the "exactly at the threshold" class is easy to miss. Good: class names describe input values, not scenarios.

The **checker** assigns classes: it returns `parts` in `Verdict` for each record from its data (`value == 0` → `zero`). So a test only picks inputs, and the checker credits the class. A rule violation does not count as coverage: a record with a wrong result produces a finding and does not close the class.

For a state machine, instead of `partitions` set `checker = "transition"` and `transitions = [[from, event, to], ...]`: one class is derived per transition (an example is in the scaffold `spec.toml`). Derived classes for your own checker are `DERIVED_PARTITIONS`, see [extensions](extensions.md).

## 3. `checks.py`

```python
from __future__ import annotations

from witnessbox.api import Verdict, WitnessError

FREE_FROM = 5000
FEE = 300


def _int(witness: dict, name: str) -> int:
    if name not in witness:
        raise WitnessError(f"{name}: field is required")
    value = witness[name]
    # bool is a subclass of int in Python, but in evidence it is a type error.
    if isinstance(value, bool) or not isinstance(value, int):
        raise WitnessError(f"{name}: expected an integer, got {value!r}")
    return value


def shipping_fee(witness: dict, inv: dict) -> Verdict:
    """INV-SHIP-1: fee == 0 when subtotal >= 5000, otherwise 300."""
    subtotal = _int(witness, "subtotal")
    fee = _int(witness, "fee")
    if subtotal < 0:
        raise WitnessError(f"subtotal: the sum cannot be negative: {subtotal}")

    if subtotal < FREE_FROM:
        parts, expected = {"below_threshold"}, FEE
    elif subtotal == FREE_FROM:
        parts, expected = {"at_threshold"}, 0
    else:
        parts, expected = {"above_threshold"}, 0
    if fee != expected:
        return Verdict(False, f"fee={fee}, the rule expected {expected}", parts)
    return Verdict(True, "", parts)


CHECKERS = {"shipping_fee": shipping_fee}
```

What makes a checker good:

- **Recomputation, not repetition.** The rule is written anew from the requirement text. The constants `5000` and `300` come from the requirement and are not imported from the application: a shared constant turns an error in both places into "agreement".
- **Two kinds of refusal.** `Verdict(False, reason, parts)` means the evidence is well-formed but the rule is violated (a "Confirmed violation" finding). `WitnessError` means the evidence is not fit for checking: a missing field, the wrong type, an impossible value (a "Malformed evidence" finding). Do not stay silent on shape: a checker that "lets through" the unknown counts garbage as proof.
- **Always `parts`.** Classes are returned on a violation too: the report shows on which class the rule fails.
- **Do not read the application's `ok`** and do not import the application, its SDK or runtime. Standard library only. Import the types with `from witnessbox.api import Verdict, WitnessError`.
- **The name** of the checker must not match core names (`cart_total`, `transition`, `sync_merge`).
- **A checker is trusted code:** it runs inside the `witnessbox check` process ([limits](extensions.md#limits-of-applicability)).

### Checker tests

`ebt/test_checks.py` tests the checker itself, not the application. Each input class needs a correct case, a violation needs a case with `ok=False`, and the shape needs a `WitnessError`:

```python
import unittest

import checks
from witnessbox.api import WitnessError


class ShippingFee(unittest.TestCase):
    def rule(self, subtotal, fee):
        return checks.shipping_fee({"subtotal": subtotal, "fee": fee}, {})

    def test_registered(self):
        self.assertIs(checks.CHECKERS["shipping_fee"], checks.shipping_fee)

    def test_boundary_is_free(self):
        verdict = self.rule(5000, 0)
        self.assertTrue(verdict.ok, verdict.reason)
        self.assertEqual(verdict.parts, {"at_threshold"})

    def test_boundary_charged_is_a_violation(self):
        verdict = self.rule(5000, 300)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.parts, {"at_threshold"})

    def test_missing_field(self):
        with self.assertRaises(WitnessError):
            checks.shipping_fee({"subtotal": 1}, {})
```

Run `witnessbox test-checks ebt` from the project root. An empty test set gives code `1`, not success. The scaffold `test_checks.py` is a ready template.

## 4. Evidence tests

A test drives the **real** code across the input classes and records evidence. There are two places for `ev()`: in the application code at the decision point ([the discount example](example.md)) or in a test around the call ([quick start](quickstart.md#4-the-evidence-test)). In both cases `data` holds what the application actually used and returned, not what the test recomputed itself. Otherwise the test is checked, not the application.

- One scenario per input class; `Ebt.scope` is the class or scenario name.
- `data` takes only allowed values ([table](sdk.md#allowed-data-values)); fractions and time are encoded explicitly.
- A recording error is visible at the `ev()` call. If the application catches all exceptions around it, there will be no evidence, and the checker will report an invariant without records ([visibility](sdk.md#visibility-of-write-errors)).
- In Dart, `ev()` is called only inside `assert`, and money is in integer minimal units.

## 5. `--self-test`

The self-test checks the sensitivity of the checker: it corrupts each evidence field and the first list elements and sees whether the checker notices.

```bash
witnessbox check --spec ebt/spec.toml --checkers ebt/checks.py \
          --evidence build/ebt/evidence.jsonl --self-test
```

(The gate runs the self-test itself; the command is for developing a checker.) For a sound checker the report says:

```
- **INV-SHIP-1**: corruption of any field is caught (samples: 3)
```

Add to `witness` and to the evidence a field `note` that the rule does not use:

```
**Checker `INV-SHIP-1` does not catch corruption of paths `note` — proof by this checker is not accepted …
- ⚠️ **INV-SHIP-1**: corruption of paths `note` was never caught: the checker does not check them or they are superfluous in the witness
```

This is one of two questions: either the checker should check this field, or the field is superfluous and must be removed from `witness` (see above). If a field legitimately does not affect the verdict, the owner lists it in `not_in_verdict`. A human decides on the exclusion, not the checker's author ([extensions](extensions.md)).

## 6. Order of work

1. Write down the requirement and its boundaries (section 1); questions go to the owner.
2. Write `[req]`/`[inv]` with `witness` and `partitions`; get human approval.
3. Write `checks.py` and `test_checks.py`; `witnessbox test-checks ebt`.
4. Write evidence tests per input class; `witnessbox sync-pinned ebt`, `witnessbox gate --check-only ebt .`.
5. Commit `ebt/`, then run the gate.
6. Check that the rule is not silent: introduce a defect at the boundary (`>=` → `>`) and make sure the gate is red, not green. For the scaffold example these are steps 8–9 of the [quick start](quickstart.md#8-inject-a-defect).

On the defect from step 6, in our example the checker would find a false proof: the application recorded `ok=true`, while the evidence `{"subtotal": 5000, "fee": 300}` violates the rule.

## 7. Observation level: `<INV>-OBS`

### Why it is needed

The decision level (everything above) checks what the code **recorded**. If a decision is made in two places and the record is in one, the records of the first place close the coverage and the gate stays silent. A decision can be recorded correctly and then not applied, or applied through a second path without a record, or the state can be wrong for a few moments. The observation level checks not the record of the decision but its **observable consequences**: what the user saw or what was saved.

It is needed for requirements with a visible or persisted outcome: a screen, a window, a notification, a write to storage, a call to an external system. For pure computations (a rate, rounding, a total) the decision level is enough. The decision level also stays for boundaries and as an integrity check of the record (D29).

What is known about the benefit, without rounding in favor of the method (D29, a pilot on a TypeScript project, one pilot, not statistics): of five injected defects (a second path, a change after `ev()`, a decision not applied, an extra write, a flickering window) the decision level found none, OBS without a log found four, and OBS with an appearance log found all five. Nine order-boundary mutants were found only by the decision level, so OBS does not replace it but complements it. Other projects will give other numbers.

### How `<INV>-OBS` works

In `spec.toml`, next to `INV-SHIP-1`, add a twin:

```toml
[inv.INV-SHIP-1-OBS]
req = "REQ-SHIP-1"
statement = "In the order's total line, as the buyer sees it, fee == 0 when subtotal >= 5000, otherwise fee == 300"
checker = "shipping_fee"
witness = ["subtotal", "fee"]
partitions = ["below_threshold", "at_threshold"]
```

The same `checker` and the same `witness`, but its own `partitions`: the observation scenarios cover those classes that actually pass through the interface. The twin's records are made by an **observation test**: it performs the action through the boundary a human uses (a screen, an API, storage), reads what appeared there, and writes `ev("INV-SHIP-1-OBS", ...)` with the observed value. The checker is the same, so the recomputation is still independent. A twin with such `partitions` and observation records is accepted by `witnessbox check` and passes `--self-test`.

### Observation contract

For each `-OBS` the analyst writes an "Observation contract" and has it approved together with the spec (D4, D29). `spec.toml` has no separate field for it and the checker does not read it. It is more practical to keep the text as a comment above the invariant, or next to it in a document that a human approves. The contract answers five questions.

1. **Observation boundary.** What exactly the test reads and where: a field on a screen, an API response, a row in storage, a window in the widget tree. The boundary is what the user or consumer sees, not an internal object of the application.
2. **Required and forbidden transitions.** Which states must appear and which must not appear at all. If a wrong state can appear and disappear before the test reads it, an **appearance log** is needed: a helper keeps a list of all states of the boundary during the scenario, not only the last one. A window that flashed for one frame is not visible in an "after" snapshot, but is visible in the appearance log.
3. **Completion moment and the next steps of the session.** When the action counts as finished (a state change, a response, a quiet interval with no events) and what the same session does next. Choose the moment explicitly: a change scheduled after it is not observed. A wrong state may come back not at once but at the next step of the same session; if the scenario ends earlier, it will not see it. So the contract includes the next steps of the session, not only the action itself.
4. **Forbidden side effects.** What must not happen in any scenario: a call to an external system, a write, a send. If the effect does not return into the observable state, a **log of fake calls** is needed: a stand-in for the external system records every call.
5. **Reading the log after the action completes.** The log is read after the action completes, not only before it (D30). In the pilot, the window-close log was read before the close, and a window that flashed during or after the close got into neither the evidence nor the check. After reading the log after the action, the defect "the window flashes after closing from the feed" was found in 4 of 4 such closes (without this reading it was missed), and after any close it was visible in 15 of 15 close records. If the state before the action matters too, the log is read twice. A limitation remains: a change after the quiet interval is not visible.

Contract template:

```
Observation contract: INV-SHIP-1-OBS
1. Boundary: the "Shipping" row in the totals block of the payment screen.
2. Transitions: required — "300" for a sum below the threshold, "0" at the threshold and above;
   forbidden — any appearance of "300" after the sum crosses the threshold
   (appearance log of the row since the moment the sum changed).
3. Completion: after the server's response to the cart change and 50 ms of quiet;
   next session step — go to payment and back to the cart.
4. Side effects: the order does not go to payment with the wrong shipping
   (log of calls to a fake of the payment gateway).
5. The log is read after the action completes and after the next session step.
```

(This illustrates the form of a contract. It is not an example that was run: there is no ready application with OBS in the repository.)

### Observation helpers

The appearance log and the log of fake calls are **project** helpers in the project's test code: the SDK, the evidence format, the core checker and the runtime do not contain them (D29). Pin them in `pinned.txt` with a line `obs/<feature>…  <path in the project>`. Then the gate verifies the copy, as it does the SDK. The scaffold `pinned.txt` has a commented-out line for this.

### What OBS gives and what it does not

OBS checks observable consequences in the given scenarios (D29). It does not prove that a decision is correct on all inputs. A defect that is not visible at the chosen boundary, beyond the completion moment, or in an unforeseen session step will stay unnoticed. "Mutant killed" in an exploratory mutation audit means sensitivity to this corruption in these scenarios, not proof; the audit itself is not part of the gate. The threat model records this in [security](security.md): the gate checks what was recorded, and a decision with no evidence and no observable consequence is outside the check.

## Limits of this guide

- The shipping example was checked by the real `witnessbox check`, but was not run with an application and a test on any stack. The end-to-end run with a stack is the [quick start](quickstart.md).
- The OBS section follows the decisions [D29 and D30](decisions.md). The repository has no example application with an OBS test and an observation helper. The first such example is a separate task.
- No document replaces human approval of the spec.
