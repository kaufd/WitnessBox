"""Independent EBT checkers.

Each checker is a separate implementation of a rule from the requirement (ebt/spec.toml),
written NOT by whoever wrote the application code. The checker:
  * receives only the witness (the record data field) and the invariant description;
  * never looks at the ok field, which is merely a claim by the code;
  * returns its own verdict, reason and input partitions,
    to which the record belongs; the coverage report is built from them.

The checker is deliberately written in a different language than the application:
reusing application code is physically impossible, so a mistake
in understanding the requirement cannot get into both sides "consistently".
"""

from __future__ import annotations

import sys
from typing import Any



from witnessbox.api import CheckFn, PartitionsFn, Verdict, WitnessError


def _int(v: Any, name: str) -> int:
    # bool is a subclass of int in Python, but in the evidence it is a type error.
    if isinstance(v, bool) or not isinstance(v, int):
        raise WitnessError(f"{name}: expected an integer, got {v!r}")
    return v


def _flag(v: Any, name: str) -> bool:
    if not isinstance(v, bool):
        raise WitnessError(f"{name}: expected true/false, got {v!r}")
    return v


def _list(v: Any, name: str) -> list:
    if not isinstance(v, list):
        raise WitnessError(f"{name}: expected a list, got {type(v).__name__}")
    return v


# ── REQ-CART-1 ────────────────────────────────────────────────────────


def cart_total(w: dict, inv: dict) -> Verdict:
    lines = _list(w["lines"], "lines")
    subtotal = 0
    for i, line in enumerate(lines):
        pair = _list(line, f"lines[{i}]")
        if len(pair) != 2:
            raise WitnessError(f"lines[{i}]: expected [price, qty]")
        price, qty = _int(pair[0], f"lines[{i}].price"), _int(pair[1], f"lines[{i}].qty")
        if price < 0 or qty < 1:
            return Verdict(False, f"lines[{i}]: invalid price={price}, qty={qty}")
        subtotal += price * qty

    d = w["discount"]
    if not isinstance(d, dict) or "type" not in d or "value" not in d:
        raise WitnessError("discount: expected {type, value}")
    dtype, dval = d["type"], _int(d["value"], "discount.value")

    parts: set[str] = set()
    if not lines:
        parts.add("empty_cart")

    if dtype == "none":
        if dval != 0:
            return Verdict(False, f"discount none with non-zero value={dval}", parts)
        expected_off = 0
        parts.add("no_discount")
    elif dtype == "percent":
        if not 0 <= dval <= 100:
            return Verdict(False, f"percent outside 0..100: {dval}", parts)
        expected_off = subtotal * dval // 100  # rounding down to the minor unit
        parts.add("percent")
        if subtotal * dval % 100:
            parts.add("percent_rounding")
    elif dtype == "fixed":
        if dval < 0:
            return Verdict(False, f"negative fixed discount {dval}", parts)
        expected_off = min(dval, subtotal)
        parts.add("fixed")
        if dval > subtotal:
            parts.add("fixed_exceeds_subtotal")
    else:
        raise WitnessError(f"discount.type: unknown type {dtype!r}")

    expected_result = subtotal - expected_off
    got_sub = _int(w["subtotal"], "subtotal")
    got_off = _int(w["off"], "off")
    got_res = _int(w["result"], "result")

    if got_sub != subtotal:
        return Verdict(False, f"subtotal={got_sub}, recomputing from lines gives {subtotal}", parts)
    if got_off != expected_off:
        return Verdict(False, f"off={got_off}, by the discount rule {dtype}:{dval} it must be {expected_off}", parts)
    if got_res != expected_result:
        return Verdict(False, f"result={got_res}, must be {expected_result}", parts)
    if got_res < 0:
        return Verdict(False, f"negative result {got_res}", parts)
    return Verdict(True, "", parts)


# ── State machines ──────────────────────────────────────────────────


def _transition_key(t: list) -> str:
    return f"{t[0]} --{t[1]}--> {t[2]}"


def transition(w: dict, inv: dict) -> Verdict:
    table = [list(t) for t in inv.get("transitions", [])]
    t = [w["from"], w["event"], w["to"]]
    for i, v in enumerate(t):
        if not isinstance(v, str):
            raise WitnessError(f"{['from', 'event', 'to'][i]}: expected a string")
    if t in table:
        return Verdict(True, "", {_transition_key(t)})
    states = {s for row in table for s in (row[0], row[2])}
    if t[0] not in states:
        return Verdict(False, f"unknown state from={t[0]!r}")
    allowed = [f"{r[1]}→{r[2]}" for r in table if r[0] == t[0]]
    return Verdict(False, f"transition {_transition_key(t)} is not allowed; from {t[0]!r} one can go to: {', '.join(allowed) or 'nowhere'}")


def transition_partitions(inv: dict) -> list[str]:
    return [_transition_key(list(t)) for t in inv.get("transitions", [])]


# ── REQ-SYNC-1 ────────────────────────────────────────────────────────


def _records(v: Any, name: str, width: int) -> list[tuple]:
    out = []
    for i, row in enumerate(_list(v, name)):
        row = _list(row, f"{name}[{i}]")
        if len(row) != width:
            raise WitnessError(f"{name}[{i}]: expected {width} fields")
        out.append(tuple(row))
    return out


def sync_merge(w: dict, inv: dict) -> Verdict:
    local = _records(w["local"], "local", 3)    # [id, version, deleted]
    remote = _records(w["remote"], "remote", 3)
    out = _records(w["out"], "out", 2)          # [id, version]

    for name, rows in (("local", local), ("remote", remote)):
        ids = [r[0] for r in rows]
        if len(ids) != len(set(ids)):
            raise WitnessError(f"{name}: duplicate ids in the input")

    loc = {r[0]: (_int(r[1], "local.version"), _flag(r[2], "local.deleted")) for r in local}
    rem = {r[0]: (_int(r[1], "remote.version"), _flag(r[2], "remote.deleted")) for r in remote}

    parts: set[str] = set()
    expected: dict[Any, int] = {}
    for key in loc.keys() | rem.keys():
        if key in loc and key in rem:
            (lv, ld), (rv, rd) = loc[key], rem[key]
            if lv > rv:
                ver, deleted = lv, ld
                parts.add("conflict_local_wins")
            elif rv > lv:
                ver, deleted = rv, rd
                parts.add("conflict_remote_wins")
            else:
                ver, deleted = rv, rd  # on a tie, the server one
                parts.add("conflict_tie")
        elif key in loc:
            ver, deleted = loc[key]
            parts.add("local_only")
        else:
            ver, deleted = rem[key]
            parts.add("remote_only")
        if deleted:
            parts.add("tombstone")
        else:
            expected[key] = ver

    out_ids = [r[0] for r in out]
    dups = sorted({i for i in out_ids if out_ids.count(i) > 1}, key=str)
    if dups:
        return Verdict(False, f"duplicate ids in the result: {dups[:5]}", parts)
    got = {r[0]: _int(r[1], "out.version") for r in out}

    missing = sorted(expected.keys() - got.keys(), key=str)
    extra = sorted(got.keys() - expected.keys(), key=str)
    wrong = sorted((k for k in expected.keys() & got.keys() if expected[k] != got[k]), key=str)
    if missing or extra or wrong:
        msg = []
        if missing:
            msg.append(f"lost {missing[:5]}")
        if extra:
            msg.append(f"extra/deleted {extra[:5]}")
        if wrong:
            msg.append("wrong version " + ", ".join(f"{k}: {got[k]}≠{expected[k]}" for k in wrong[:5]))
        return Verdict(False, "; ".join(msg), parts)
    return Verdict(True, "", parts)


# ── Registry ────────────────────────────────────────────────────────────

CHECKERS: dict[str, CheckFn] = {
    "cart_total": cart_total,
    "transition": transition,
    "sync_merge": sync_merge,
}

# Checkers whose coverage partitions are derived from the spec rather than given as a list.
DERIVED_PARTITIONS: dict[str, PartitionsFn] = {
    "transition": transition_partitions,
}

# The legacy and canonical import paths use one registry.
_canonical = "witnessbox.checker.checkers"
_current = sys.modules[__name__]
if _canonical in sys.modules:
    sys.modules[__name__] = sys.modules[_canonical]
else:
    sys.modules[_canonical] = _current
sys.modules.setdefault("checkers", sys.modules[_canonical])
