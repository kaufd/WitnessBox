"""Модель отчёта и независимая перепроверка доказательств EBT."""
from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .checkers import CHECKERS, DERIVED_PARTITIONS, Verdict, WitnessError

# Категории находок. Все, кроме INFO-уровня, валят сборку.
FALSE_PROOF = "FALSE_PROOF"                  # код: ok, чекер: нарушение — самое опасное
CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"  # код и чекер согласны: нарушение
CHECKER_DISAGREES = "CHECKER_DISAGREES"      # код: нарушение, чекер: ok — кто-то из них неправ
WITNESS_INCOMPLETE = "WITNESS_INCOMPLETE"    # не хватает полей — перепроверить нельзя
WITNESS_MALFORMED = "WITNESS_MALFORMED"      # поля есть, но форма/типы неверны
UNKNOWN_INV = "UNKNOWN_INV"                  # инварианта нет в реестре
REQ_MISMATCH = "REQ_MISMATCH"                # запись ссылается не на то требование
NO_CHECKER = "NO_CHECKER"                    # в реестре указан чекер, которого нет
CHECKER_ERROR = "CHECKER_ERROR"              # чекер упал — ошибка в самом чекере
LOG_GAP = "LOG_GAP"                          # пропуск seq — записи потеряны
MALFORMED_LINE = "MALFORMED_LINE"            # строка лога не JSON

CRITICAL = [FALSE_PROOF, CONFIRMED_VIOLATION, CHECKER_DISAGREES, WITNESS_INCOMPLETE,
            WITNESS_MALFORMED, UNKNOWN_INV, REQ_MISMATCH, NO_CHECKER, CHECKER_ERROR, LOG_GAP,
            MALFORMED_LINE]

TITLES = {
    FALSE_PROOF: "Ложное доказательство (код: ok, чекер: нарушение)",
    CONFIRMED_VIOLATION: "Подтверждённое нарушение",
    CHECKER_DISAGREES: "Код сообщил о нарушении, чекер не согласен",
    WITNESS_INCOMPLETE: "Неполное свидетельство",
    WITNESS_MALFORMED: "Некорректное свидетельство",
    UNKNOWN_INV: "Инвариант не зарегистрирован",
    REQ_MISMATCH: "Не то требование",
    NO_CHECKER: "Нет чекера",
    CHECKER_ERROR: "Ошибка в чекере",
    LOG_GAP: "Потерянные записи",
    MALFORMED_LINE: "Битая строка лога",
}


@dataclass
class Finding:
    kind: str
    line: int
    scope: str | None = None
    seq: int | None = None
    inv: str | None = None
    req: str | None = None
    claim: bool | None = None
    verdict: bool | None = None
    reason: str = ""
    witness: Any = None


@dataclass
class Report:
    spec_version: str = ""
    spec_sha: str = ""
    records: int = 0
    scopes: int = 0
    findings: list[Finding] = field(default_factory=list)
    req_without_inv: list[str] = field(default_factory=list)
    inv_never_fired: list[str] = field(default_factory=list)
    uncovered_partitions: dict[str, list[str]] = field(default_factory=dict)
    baseline: dict | None = None
    self_test: dict | None = None
    known_findings: list[Finding] = field(default_factory=list)
    coverage_scope: list[str] | None = None
    known_unused: list[dict] = field(default_factory=list)
    # Пути слабых мест чекера (`поле`, `поле[i]`, `поле.ключ`); для скалярного поля путь
    # равен имени поля (D43).
    weak_required: dict[str, list[str]] = field(default_factory=dict)

    def count(self, kind: str) -> int:
        return sum(1 for f in self.findings if f.kind == kind)

    @property
    def has_critical(self) -> bool:
        return any(f.kind in CRITICAL for f in self.findings)

    @property
    def has_coverage_gaps(self) -> bool:
        # Ключ — «сценарий / инвариант»; при --scope чужие инварианты могут не срабатывать (D13).
        vanished = any(self.coverage_scope is None or k.rsplit(" / ", 1)[1] in self.coverage_scope
                       for k in (self.baseline or {}).get("vanished", []))
        return bool(self.req_without_inv or self.inv_never_fired or self.uncovered_partitions or vanished)

    def failed(self, allow_uncovered: bool) -> bool:
        # Пустой лог — не «неполное покрытие», а отсутствие доказательства: --allow-uncovered его не прощает.
        # Слабый чекер (порча поля не ловится) не доказывает ничего, сколько бы записей ни было.
        return (self.has_critical or self.records == 0 or bool(self.weak_required)
                or (self.has_coverage_gaps and not allow_uncovered))


def _known_match(f: Finding, e: dict) -> bool:
    if f.inv != e["inv"] or e["kind"] != f.kind or not isinstance(f.witness, dict):
        return False
    # Тип тоже сравнивается: 1 и 1.0 в свидетельстве — разные входы.
    return all(k in f.witness and f.witness[k] == v and type(f.witness[k]) is type(v)
               for k, v in e["match"].items())


def apply_known(r: Report, known: list[dict], seen: set[str]) -> None:
    used: set[int] = set()
    rest = []
    for f in r.findings:
        hit = next((i for i, e in enumerate(known) if _known_match(f, e)), None)
        if hit is None:
            rest.append(f)
        else:
            used.add(hit)
            r.known_findings.append(f)
    r.findings = rest
    # «Можно удалить» — только если инвариант встречался в логе: иначе запись просто не проверялась.
    r.known_unused = [e for i, e in enumerate(known) if i not in used and e["inv"] in seen]


class ExtensionError(ValueError):
    """Некорректное расширение или его параметры в спецификации."""


def declared_partitions(inv: dict) -> list[str]:
    derive = DERIVED_PARTITIONS.get(inv["checker"])
    try:
        parts = derive(inv) if derive is not None else list(inv.get("partitions", []))
    except SystemExit as e:
        raise ExtensionError(f"{inv['checker']}: DERIVED_PARTITIONS: SystemExit: {e.code}") from e
    except Exception as e:  # noqa: BLE001 — граница проектного расширения
        raise ExtensionError(f"{inv['checker']}: DERIVED_PARTITIONS: {type(e).__name__}: {e}") from e
    if not isinstance(parts, list) or any(not isinstance(p, str) for p in parts):
        raise ExtensionError(f"{inv['checker']}: DERIVED_PARTITIONS должен возвращать список строк")
    return parts


# ── Проверка одной записи ─────────────────────────────────────────────


def run_checker(inv: dict, witness: dict) -> Verdict:
    verdict = CHECKERS[inv["checker"]](witness, inv)
    if not isinstance(verdict, Verdict):
        raise TypeError(f"{inv['checker']}: чекер должен возвращать Verdict, получен {type(verdict).__name__}")
    if (not isinstance(verdict.ok, bool) or not isinstance(verdict.reason, str)
            or not isinstance(verdict.parts, set)
            or any(not isinstance(part, str) for part in verdict.parts)):
        raise TypeError(f"{inv['checker']}: некорректный Verdict: нужны ok bool, reason str, parts set[str]")
    return verdict


def check_record(n: int, rec: dict, spec: dict, hits: dict[str, set[str]],
                 seen: set[str]) -> Finding | None:
    """hits — классы входов по записям, которые доказывают инвариант: запись с находкой
    (в том числе известной из known.toml) покрытия не даёт (D11, D15)."""
    inv_id, scope, seq = rec.get("inv"), rec.get("scope"), rec.get("seq")
    base = dict(line=n, scope=scope, seq=seq, inv=inv_id, req=rec.get("req"),
                claim=rec.get("ok"), witness=rec.get("data"))

    inv = spec["inv"].get(inv_id)
    if inv is None:
        return Finding(UNKNOWN_INV, reason="нет в ebt/spec.toml — новый инвариант должен пройти утверждение", **base)
    seen.add(inv_id)
    if rec.get("req") != inv["req"]:
        return Finding(REQ_MISMATCH, reason=f"в реестре {inv_id} формализует {inv['req']}", **base)
    if inv["checker"] not in CHECKERS:
        return Finding(NO_CHECKER, reason=f"чекер {inv['checker']!r} не реализован", **base)

    w = rec.get("data")
    if not isinstance(w, dict):
        return Finding(WITNESS_INCOMPLETE, reason="нет поля data", **base)
    missing = [k for k in inv["witness"] if w.get(k) is None]
    if missing:
        return Finding(WITNESS_INCOMPLETE, reason=f"нет полей: {', '.join(missing)}", **base)

    try:
        v = run_checker(inv, w)
    except WitnessError as e:
        return Finding(WITNESS_MALFORMED, reason=str(e), **base)
    except SystemExit as e:
        return Finding(CHECKER_ERROR, reason=f"SystemExit: {e.code}", **base)
    except Exception as e:  # noqa: BLE001 — упавший чекер не должен ронять весь отчёт
        return Finding(CHECKER_ERROR, reason=f"{type(e).__name__}: {e}", **base)

    claim = rec.get("ok")
    if claim is True and v.ok:
        hits.setdefault(inv_id, set()).update(v.parts)
        return None
    if claim is True and not v.ok:
        return Finding(FALSE_PROOF, verdict=False, reason=v.reason, **base)
    if claim is False and not v.ok:
        return Finding(CONFIRMED_VIOLATION, verdict=False, reason=v.reason, **base)
    return Finding(CHECKER_DISAGREES, verdict=True,
                   reason="чекер считает свидетельство корректным — проверьте условие ok в коде или сам чекер", **base)


def check_integrity(records: list[tuple[int, dict]], file_starts: set[int] = frozenset()) -> list[Finding]:
    """seq растёт на 1 внутри прогона и сбрасывается в 1 при Ebt.reset().
    file_starts — номера первых записей каждого файла лога: новый файл — новый прогон."""
    out, prev = [], None
    for n, rec in records:
        if n in file_starts:
            prev = None
        seq = rec.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            out.append(Finding(LOG_GAP, n, rec.get("scope"), None, rec.get("inv"), reason="нет seq"))
            prev = None
            continue
        if seq == 1:
            prev = 1
            continue
        if prev is None:
            out.append(Finding(LOG_GAP, n, rec.get("scope"), seq, rec.get("inv"),
                               reason=f"прогон начинается с seq={seq}: потеряно {seq - 1} первых записей (переполнен буфер?)"))
        elif seq != prev + 1:
            out.append(Finding(LOG_GAP, n, rec.get("scope"), seq, rec.get("inv"),
                               reason=f"после seq={prev} идёт seq={seq}"))
        prev = seq
    return out


# ── Регрессия относительно baseline ───────────────────────────────────


def group(records: list[tuple[int, dict]]) -> dict[tuple[str, str], list[dict]]:
    g: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for _, rec in records:
        g[(rec.get("scope") or "-", rec.get("inv") or "?")].append({"ok": rec.get("ok"), "data": rec.get("data")})
    return g


def field_diff(a: Any, b: Any) -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(a.keys() | b.keys())
        return [f"{k}: {json.dumps(a.get(k), ensure_ascii=False)} → {json.dumps(b.get(k), ensure_ascii=False)}"
                for k in keys if a.get(k) != b.get(k)]
    return [f"{json.dumps(a, ensure_ascii=False)} → {json.dumps(b, ensure_ascii=False)}"] if a != b else []


def compare_baseline(cur: list[tuple[int, dict]], base: list[tuple[int, dict]], limit: int) -> dict:
    gc, gb = group(cur), group(base)
    appeared = sorted(f"{s} / {i}" for s, i in gc.keys() - gb.keys())
    vanished = sorted(f"{s} / {i}" for s, i in gb.keys() - gc.keys())
    count_changed, changed = [], []
    for key in sorted(gc.keys() & gb.keys()):
        a, b = gb[key], gc[key]
        if len(a) != len(b):
            count_changed.append({"key": f"{key[0]} / {key[1]}", "before": len(a), "after": len(b)})
        for idx, (ra, rb) in enumerate(zip(a, b)):
            diff = field_diff(ra["data"], rb["data"])
            if ra["ok"] != rb["ok"]:
                diff.insert(0, f"ok: {ra['ok']} → {rb['ok']}")
            if diff:
                changed.append({"key": f"{key[0]} / {key[1]}", "index": idx, "diff": diff})
    return {
        "appeared": appeared,
        "vanished": vanished,
        "count_changed": count_changed,
        "changed_total": len(changed),
        "changed": changed[:limit],
    }


# ── Самопроверка чекеров ──────────────────────────────────────────────


def _mutate(v: Any) -> tuple[bool, Any]:
    """Мутирует первое скалярное значение внутри v. Возвращает (удалось, новое)."""
    if isinstance(v, bool):
        return True, not v
    if isinstance(v, int):
        return True, v + 1
    if isinstance(v, float):
        return True, v + 1.0
    if isinstance(v, str):
        # Не суффикс (D16): чекер законно смотрит только на часть строки — число и единицу
        # в «1 day available» — и хвоста не заметит. Есть цифра — меняется первая цифра
        # (число в тексте — то, что чекеры текста проверяют, а слово вместо числа бывает законным);
        # нет — строка заменяется целиком.
        m = re.search(r"\d", v)
        if m:
            return True, v[:m.start()] + str((int(m.group()) + 1) % 10) + v[m.end():]
        return True, "_mut" if v != "_mut" else "_mut2"
    if isinstance(v, list):
        if not v:
            return True, [0]  # пустой список — добавляем элемент
        for i, x in enumerate(v):
            ok, nx = _mutate(x)
            if ok:
                return True, v[:i] + [nx] + v[i + 1:]
        return False, v
    if isinstance(v, dict):
        for k in v:
            ok, nx = _mutate(v[k])
            if ok:
                return True, {**v, k: nx}
    return False, v


MAX_INDEX = 8
# simplicity: портятся первые 8 элементов; чекер, читающий только первые 8, не пойман —
# поднять предел или выбирать индексы по образцам.


def _mutants(v: Any) -> list[tuple[str, Any]]:
    """Мутанты значения: (суффикс пути, значение с внесённой порчей).

    `""` — само значение, `"[i]"` — элемент списка, `".key"` — ключ словаря,
    с рекурсией. У непустого списка портятся удаление и содержимое первых
    MAX_INDEX элементов; перестановки нет — чекер законно сравнивает некоторые
    списки как множество.
    """
    if isinstance(v, bool):
        return [("", not v)]
    if isinstance(v, int):
        return [("", v + 1), ("", v - 1)]
    if isinstance(v, (float, str)):
        ok, mutated = _mutate(v)
        return [("", mutated)] if ok else []
    if isinstance(v, list):
        if not v:
            return [("", [0])]  # пустой список — добавляем элемент
        out: list[tuple[str, Any]] = []
        for i in range(min(len(v), MAX_INDEX)):
            out.append((f"[{i}]", v[:i] + v[i + 1:]))
            out.extend((f"[{i}]{suffix}", v[:i] + [mutated] + v[i + 1:])
                       for suffix, mutated in _mutants(v[i]))
        return out
    if isinstance(v, dict):
        return [(f".{key}{suffix}", {**v, key: mutated})
                for key in v for suffix, mutated in _mutants(v[key])]
    return []


def self_test(records: list[tuple[int, dict]], spec: dict, per_inv: int) -> dict:
    """Для каждого поля свидетельства: ловит ли чекер порчу этого поля или его элементов."""
    samples: dict[str, list[dict]] = defaultdict(list)
    for _, rec in records:
        inv = spec["inv"].get(rec.get("inv"))
        w = rec.get("data")
        if inv is None or inv["checker"] not in CHECKERS or not isinstance(w, dict):
            continue
        if any(w.get(k) is None for k in inv["witness"]) or len(samples[rec["inv"]]) >= per_inv:
            continue
        try:
            if run_checker(inv, w).ok:
                samples[rec["inv"]].append(w)
        except SystemExit:
            # check_record already records the extension failure; self-test must not exit the CLI.
            pass
        except Exception:  # noqa: BLE001 — такие записи уже попали в находки
            pass

    result = {}
    for inv_id, ws in sorted(samples.items()):
        inv = spec["inv"][inv_id]
        fields = {}
        weak_paths: list[str] = []
        shape_only_paths: list[str] = []
        for k in inv["witness"]:
            attempts: list[tuple[str, dict, Any]] = []
            for w in ws:
                attempts.extend((f"{k}{suffix}", w, mutated) for suffix, mutated in _mutants(w[k]))
                # Подстановка значения из соседнего образца: форма та же, но другое
                # допустимое значение — так проверяется, сверяет ли чекер его с правилом (D43).
                other = next((o for o in ws if o[k] != w[k]), None)
                if other is not None:
                    attempts.append((k, w, other[k]))
            counts: dict[str, dict[str, int]] = {}
            for path, w, mutated in attempts:
                s = counts.setdefault(path, {"tried": 0, "killed": 0, "errors": 0, "rejected": 0})
                s["tried"] += 1
                m = copy.deepcopy(w)
                m[k] = mutated
                try:
                    if not run_checker(inv, m).ok:
                        s["killed"] += 1
                except WitnessError:
                    s["killed"] += 1
                    s["rejected"] += 1  # сломалась форма, а не логика правила
                except SystemExit:
                    s["errors"] += 1
                except Exception:  # noqa: BLE001
                    s["errors"] += 1    # чекер упал на испорченных данных — тоже его дефект
            fields[k] = {key: sum(s[key] for s in counts.values())
                         for key in ("tried", "killed", "errors", "rejected")}
            weak_paths.extend(p for p, s in counts.items()
                              if s["tried"] and s["killed"] == 0 and not s["errors"])
            shape_only_paths.extend(p for p, s in counts.items()
                                    if s["killed"] and s["killed"] == s["rejected"])
        weak_paths.sort()
        shape_only_paths.sort()
        weak_fields = sorted({_top_field(p) for p in weak_paths})
        crashing = [k for k, s in fields.items() if s["errors"]]
        result[inv_id] = {"samples": len(ws), "fields": fields, "weak_fields": weak_fields,
                          "weak_paths": weak_paths, "crashing_fields": crashing,
                          "shape_only_paths": shape_only_paths}
    return result


def _top_field(path: str) -> str:
    """Имя поля верхнего уровня из пути `поле[i]…` или `поле.ключ`."""
    return re.split(r"[.\[]", path, maxsplit=1)[0]


def _allowed(path: str, allowed: set[str]) -> bool:
    """Путь покрыт not_in_verdict; имя поля верхнего уровня покрывает его подпути."""
    normalized = re.sub(r"\[\d+\]", "[*]", path)
    return any(normalized == entry or normalized.startswith(entry + ".")
               or normalized.startswith(entry + "[") for entry in allowed)


# ── Сборка отчёта ─────────────────────────────────────────────────────


def build_report(spec: dict, sha: str, records, bad_lines, baseline, limit: int, do_self_test: bool,
                 known: list[dict] | None = None, scope: list[str] | None = None,
                 file_starts: set[int] = frozenset()) -> Report:
    r = Report(spec_version=str(spec.get("meta", {}).get("version", "")), spec_sha=sha,
               records=len(records), scopes=len({rec.get("scope") for _, rec in records}))
    r.findings.extend(bad_lines)
    r.findings.extend(check_integrity(records, file_starts))

    hits: dict[str, set[str]] = {}
    seen: set[str] = set()
    for n, rec in records:
        f = check_record(n, rec, spec, hits, seen)
        if f:
            r.findings.append(f)
    if known is not None:
        apply_known(r, known, seen)
    fired = set(hits)

    reqs_with_inv = {inv["req"] for inv in spec["inv"].values()}
    r.req_without_inv = sorted(set(spec["req"]) - reqs_with_inv)
    required = set(scope) if scope is not None else set(spec["inv"])
    r.coverage_scope = sorted(scope) if scope is not None else None
    r.inv_never_fired = sorted(required - fired)
    for inv_id in sorted(fired & required):
        missing = [p for p in declared_partitions(spec["inv"][inv_id]) if p not in hits[inv_id]]
        if missing:
            r.uncovered_partitions[inv_id] = missing

    if baseline is not None:
        r.baseline = compare_baseline(records, baseline, limit)
    if do_self_test:
        r.self_test = self_test(records, spec, per_inv=25)
        # Поле или путь, которые законно не влияют на вердикт, владелец перечисляет
        # в not_in_verdict: имя поля или путь с [*], например "lines" или "lines[*].note" (D15, D43).
        for inv_id in sorted(required & r.self_test.keys()):
            allowed = set(spec["inv"][inv_id].get("not_in_verdict", []))
            weak = [p for p in r.self_test[inv_id]["weak_paths"] if not _allowed(p, allowed)]
            if weak:
                r.weak_required[inv_id] = weak
    return r


