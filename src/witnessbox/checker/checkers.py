"""Независимые чекеры EBT.

Каждый чекер — отдельная реализация правила из требования (ebt/spec.toml),
написанная НЕ тем, кто писал код приложения. Чекер:
  * получает только witness (поле data записи) и описание инварианта;
  * никогда не смотрит на поле ok — это всего лишь заявление кода;
  * возвращает свой вердикт, причину и классы входов (partitions),
    к которым относится запись, — из них строится отчёт покрытия.

Чекер написан на другом языке, чем приложение, намеренно:
переиспользовать код приложения физически невозможно, поэтому ошибка
в понимании требования не может «согласованно» попасть в обе стороны.
"""

from __future__ import annotations

import sys
from typing import Any



from witnessbox.api import CheckFn, PartitionsFn, Verdict, WitnessError


def _int(v: Any, name: str) -> int:
    # bool — подкласс int в Python, но в свидетельстве это ошибка типа.
    if isinstance(v, bool) or not isinstance(v, int):
        raise WitnessError(f"{name}: ожидалось целое, получено {v!r}")
    return v


def _flag(v: Any, name: str) -> bool:
    if not isinstance(v, bool):
        raise WitnessError(f"{name}: ожидалось true/false, получено {v!r}")
    return v


def _list(v: Any, name: str) -> list:
    if not isinstance(v, list):
        raise WitnessError(f"{name}: ожидался список, получено {type(v).__name__}")
    return v


# ── REQ-CART-1 ────────────────────────────────────────────────────────


def cart_total(w: dict, inv: dict) -> Verdict:
    lines = _list(w["lines"], "lines")
    subtotal = 0
    for i, line in enumerate(lines):
        pair = _list(line, f"lines[{i}]")
        if len(pair) != 2:
            raise WitnessError(f"lines[{i}]: ожидалось [price, qty]")
        price, qty = _int(pair[0], f"lines[{i}].price"), _int(pair[1], f"lines[{i}].qty")
        if price < 0 or qty < 1:
            return Verdict(False, f"lines[{i}]: недопустимые price={price}, qty={qty}")
        subtotal += price * qty

    d = w["discount"]
    if not isinstance(d, dict) or "type" not in d or "value" not in d:
        raise WitnessError("discount: ожидалось {type, value}")
    dtype, dval = d["type"], _int(d["value"], "discount.value")

    parts: set[str] = set()
    if not lines:
        parts.add("empty_cart")

    if dtype == "none":
        if dval != 0:
            return Verdict(False, f"discount none с ненулевым value={dval}", parts)
        expected_off = 0
        parts.add("no_discount")
    elif dtype == "percent":
        if not 0 <= dval <= 100:
            return Verdict(False, f"процент вне 0..100: {dval}", parts)
        expected_off = subtotal * dval // 100  # округление вниз до копейки
        parts.add("percent")
        if subtotal * dval % 100:
            parts.add("percent_rounding")
    elif dtype == "fixed":
        if dval < 0:
            return Verdict(False, f"отрицательная фиксированная скидка {dval}", parts)
        expected_off = min(dval, subtotal)
        parts.add("fixed")
        if dval > subtotal:
            parts.add("fixed_exceeds_subtotal")
    else:
        raise WitnessError(f"discount.type: неизвестный тип {dtype!r}")

    expected_result = subtotal - expected_off
    got_sub = _int(w["subtotal"], "subtotal")
    got_off = _int(w["off"], "off")
    got_res = _int(w["result"], "result")

    if got_sub != subtotal:
        return Verdict(False, f"subtotal={got_sub}, пересчёт по lines даёт {subtotal}", parts)
    if got_off != expected_off:
        return Verdict(False, f"off={got_off}, по правилу скидки {dtype}:{dval} должно быть {expected_off}", parts)
    if got_res != expected_result:
        return Verdict(False, f"result={got_res}, должно быть {expected_result}", parts)
    if got_res < 0:
        return Verdict(False, f"отрицательный итог {got_res}", parts)
    return Verdict(True, "", parts)


# ── Машины состояний ──────────────────────────────────────────────────


def _transition_key(t: list) -> str:
    return f"{t[0]} --{t[1]}--> {t[2]}"


def transition(w: dict, inv: dict) -> Verdict:
    table = [list(t) for t in inv.get("transitions", [])]
    t = [w["from"], w["event"], w["to"]]
    for i, v in enumerate(t):
        if not isinstance(v, str):
            raise WitnessError(f"{['from', 'event', 'to'][i]}: ожидалась строка")
    if t in table:
        return Verdict(True, "", {_transition_key(t)})
    states = {s for row in table for s in (row[0], row[2])}
    if t[0] not in states:
        return Verdict(False, f"неизвестное состояние from={t[0]!r}")
    allowed = [f"{r[1]}→{r[2]}" for r in table if r[0] == t[0]]
    return Verdict(False, f"переход {_transition_key(t)} не разрешён; из {t[0]!r} можно: {', '.join(allowed) or 'никуда'}")


def transition_partitions(inv: dict) -> list[str]:
    return [_transition_key(list(t)) for t in inv.get("transitions", [])]


# ── REQ-SYNC-1 ────────────────────────────────────────────────────────


def _records(v: Any, name: str, width: int) -> list[tuple]:
    out = []
    for i, row in enumerate(_list(v, name)):
        row = _list(row, f"{name}[{i}]")
        if len(row) != width:
            raise WitnessError(f"{name}[{i}]: ожидалось {width} поля")
        out.append(tuple(row))
    return out


def sync_merge(w: dict, inv: dict) -> Verdict:
    local = _records(w["local"], "local", 3)    # [id, version, deleted]
    remote = _records(w["remote"], "remote", 3)
    out = _records(w["out"], "out", 2)          # [id, version]

    for name, rows in (("local", local), ("remote", remote)):
        ids = [r[0] for r in rows]
        if len(ids) != len(set(ids)):
            raise WitnessError(f"{name}: дубли id во входе")

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
                ver, deleted = rv, rd  # при равенстве — серверная
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
        return Verdict(False, f"дубли id в результате: {dups[:5]}", parts)
    got = {r[0]: _int(r[1], "out.version") for r in out}

    missing = sorted(expected.keys() - got.keys(), key=str)
    extra = sorted(got.keys() - expected.keys(), key=str)
    wrong = sorted((k for k in expected.keys() & got.keys() if expected[k] != got[k]), key=str)
    if missing or extra or wrong:
        msg = []
        if missing:
            msg.append(f"потеряны {missing[:5]}")
        if extra:
            msg.append(f"лишние/удалённые {extra[:5]}")
        if wrong:
            msg.append("не та версия " + ", ".join(f"{k}: {got[k]}≠{expected[k]}" for k in wrong[:5]))
        return Verdict(False, "; ".join(msg), parts)
    return Verdict(True, "", parts)


# ── Реестр ────────────────────────────────────────────────────────────

CHECKERS: dict[str, CheckFn] = {
    "cart_total": cart_total,
    "transition": transition,
    "sync_merge": sync_merge,
}

# Чекеры, у которых классы покрытия выводятся из спецификации, а не задаются списком.
DERIVED_PARTITIONS: dict[str, PartitionsFn] = {
    "transition": transition_partitions,
}

# Прежний и канонический пути импорта используют один реестр.
_canonical = "witnessbox.checker.checkers"
_current = sys.modules[__name__]
if _canonical in sys.modules:
    sys.modules[__name__] = sys.modules[_canonical]
else:
    sys.modules[_canonical] = _current
sys.modules.setdefault("checkers", sys.modules[_canonical])
