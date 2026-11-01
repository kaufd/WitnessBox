#!/usr/bin/env python3
"""Генерирует пример логов доказательств для демонстрации ebt_check.

  baseline.jsonl — «правильный» прогон;
  evidence.jsonl — тот же прогон с намеренными дефектами:
    1. процентная скидка округлена вверх (150 вместо 149)      → FALSE_PROOF
    2. при равных версиях победила локальная запись            → FALSE_PROOF
    3. свидетельство только из результата {"result": ...}      → WITNESS_INCOMPLETE
    4. выдуманный инвариант INV-CART-9                         → UNKNOWN_INV

Формат записи совпадает с тем, что пишет lib/ebt/ebt.dart.

  python3 examples/basic/make_example.py   # пишет файлы рядом с собой
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
        # 999 × 15% = 149.85 → по требованию 149; дефект: 150
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
        # равные версии: побеждает сервер (deleted=True → записи в out нет)
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
