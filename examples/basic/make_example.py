#!/usr/bin/env python3
"""Generates example proof logs to demonstrate ebt_check.

  baseline.jsonl — the "correct" run;
  evidence.jsonl — the same run with deliberate defects:
    1. a percent discount rounded up (150 instead of 149)      → FALSE_PROOF
    2. on equal versions the local record won                   → FALSE_PROOF
    3. evidence made of the result only {"result": ...}        → WITNESS_INCOMPLETE
    4. an invented invariant INV-CART-9                        → UNKNOWN_INV

The record format matches what lib/ebt/ebt.dart writes.

  python3 examples/basic/make_example.py   # writes files next to itself
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cart(lines, dtype, dval, off_override=None):
    sub = sum(p * q for p, q in lines)
    off = {"none": 0, "percent": sub * dval // 100, "fixed": min(dval, sub)}[dtype]
    if off_override is not None:
        off = off_override
    return {"lines": [list(x) for x in lines], "discount": {"type": dtype, "value": dval},
            "subtotal": sub, "off": off, "result": sub - off}


def build(regressed: bool):
    runs = []

    r = [
        ("SM-CHECKOUT", "REQ-CHECKOUT-2", True, {"from": "cart", "event": "confirm", "to": "confirmed"}),
        ("INV-CART-3", "REQ-CART-1", True, cart([(49900, 1), (1990, 3)], "none", 0)),
        # 999 × 15% = 149.85 → 149 by the requirement; defect: 150
        ("INV-CART-3", "REQ-CART-1", True,
         cart([(333, 3)], "percent", 15, off_override=150 if regressed else None)),
        ("INV-CART-3", "REQ-CART-1", True, cart([(120000, 1)], "fixed", 50000)),
        ("SM-CHECKOUT", "REQ-CHECKOUT-2", True, {"from": "confirmed", "event": "pay", "to": "paying"}),
        ("SM-CHECKOUT", "REQ-CHECKOUT-2", True, {"from": "paying", "event": "failed", "to": "confirmed"}),
        ("SM-CHECKOUT", "REQ-CHECKOUT-2", True, {"from": "confirmed", "event": "pay", "to": "paying"}),
        ("SM-CHECKOUT", "REQ-CHECKOUT-2", True, {"from": "paying", "event": "paid", "to": "done"}),
    ]
    if regressed:
        r.append(("INV-CART-3", "REQ-CART-1", True, {"result": 8490}))
        r.append(("INV-CART-9", "REQ-CART-1", True, {"items": 2}))
    runs.append(("checkout_discount", r))

    r = [
        ("INV-SYNC-1", "REQ-SYNC-1", True, {
            "local": [["a", 3, False], ["b", 1, False], ["c", 2, True]],
            "remote": [["a", 2, False], ["d", 1, False], ["c", 1, False]],
            "out": [["a", 3], ["b", 1], ["d", 1]],
        }),
        # Valid equal versions (the server wins, tombstone) and two server records:
        # deleting any remote row changes the result, so the self-test sees that
        # the checker reads more than the first row of the list.
        ("INV-SYNC-1", "REQ-SYNC-1", True, {
            "local": [["e", 5, False], ["f", 2, True]],
            "remote": [["e", 5, True], ["g", 1, False], ["h", 3, False]],
            "out": [["g", 1], ["h", 3]],
        }),
        # equal versions: the server wins (deleted=True → no record in out)
        ("INV-SYNC-1", "REQ-SYNC-1", True, {
            "local": [["e", 5, False]],
            "remote": [["e", 5, True]],
            "out": [["e", 5]] if regressed else [],
        }),
    ]
    runs.append(("sync_offline", r))
    return runs


def write(path: Path, regressed: bool) -> None:
    with path.open("w", encoding="utf-8") as f:
        for scope, recs in build(regressed):
            for seq, (inv, req, ok, data) in enumerate(recs, start=1):
                f.write(json.dumps({"seq": seq, "scope": scope, "req": req, "inv": inv,
                                    "ok": ok, "data": data}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    write(HERE / "evidence.jsonl", regressed=True)
    write(HERE / "baseline.jsonl", regressed=False)
    print(f"written: {HERE / 'evidence.jsonl'}, {HERE / 'baseline.jsonl'}")
