#!/usr/bin/env python3
"""ebt_check — независимая перепроверка лога доказательств EBT (уровень 2).

Что делает:
  1. Перепроверяет каждую запись своим чекером, игнорируя поле ok.
  2. Ищет ложные доказательства (код сказал ok, чекер не согласен),
     неполные свидетельства, незарегистрированные инварианты, потерянные записи.
  3. Строит покрытие: REQ без INV, INV без записей, непройденные классы входов.
  4. Сравнивает с прошлым прогоном (baseline) — регрессия.
  5. Самопроверка чекеров: портит поля свидетельств и проверяет, что чекер
     это замечает. Поле, порча которого ни разу не поймана, — чекер его не проверяет.
  6. Известные находки (--known, утверждает человек) показывает отдельно
     и не валит по ним сборку: на существующем коде валит только новое.
  7. --scope INV,…: полноту покрытия (инвариант сработал, все классы входов) требует
     только у инвариантов задачи. Записи остальных инвариантов проверяются как обычно —
     регрессия в чужом правиле по-прежнему валит, а инвариант, чей тест не в этой ветке, — нет.

Чекеры проекта (--checkers файл.py) добавляются к чекерам из checkers.py рядом
(совпадение имени с чекером ядра — ошибка запуска, D18):
файл задаёт CHECKERS и, по желанию, DERIVED_PARTITIONS, а Verdict и WitnessError
берёт из witnessbox.api (совместимые импорты ebt_verification.api и из checkers тоже поддерживаются).

Только стандартная библиотека, Python 3.11+ (на 3.10 — с пакетом tomli).

  python tool/ebt_check/ebt_check.py \
      --spec ebt/spec.toml --evidence build/ebt/evidence.jsonl \
      --baseline build/ebt/baseline.jsonl \
      --md build/ebt/report.md --json build/ebt/report.json --self-test

Код выхода: 0 — всё доказано; 1 — есть критичные находки или дыры в покрытии;
2 — ошибка запуска (нет файла, битая спецификация).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .engine import ExtensionError, build_report
from .input import load_checkers, load_jsonl, load_known, load_spec, validate_known
from .rendering import render_md

__version__ = "0.1.0"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"ebt-check {__version__}")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--evidence", required=True, type=Path, nargs="+",
                   help="лог(и) JSONL; несколько файлов — несколько прогонов, seq в каждом с начала")
    p.add_argument("--baseline", type=Path, help="лог прошлого прогона для диффа")
    p.add_argument("--known", type=Path, help="известные находки (known.toml), которые не валят сборку")
    p.add_argument("--checkers", type=Path, help="чекеры проекта (.py с CHECKERS)")
    p.add_argument("--scope", help="инварианты задачи через запятую: покрытие требуется только у них")
    p.add_argument("--md", type=Path, help="куда записать markdown-отчёт (иначе в stdout)")
    p.add_argument("--json", type=Path, help="куда записать JSON-отчёт")
    p.add_argument("--self-test", action="store_true", help="проверить чувствительность чекеров")
    p.add_argument("--allow-uncovered", action="store_true", help="дыры в покрытии не валят сборку")
    p.add_argument("--max-items", type=int, default=30)
    a = p.parse_args(argv)

    try:
        if a.checkers:
            load_checkers(a.checkers)
        spec, sha = load_spec(a.spec)
        records, bad, file_starts, offset = [], [], set(), 0
        for path in a.evidence:
            recs, bd = load_jsonl(path, offset)
            records += recs
            bad += bd
            if recs:
                file_starts.add(recs[0][0])
            offset += len(path.read_text(encoding="utf-8").splitlines())
        baseline = None
        if a.baseline:
            if a.baseline.exists():
                baseline, baseline_bad = load_jsonl(a.baseline)
                if baseline_bad:
                    raise ValueError(f"baseline {a.baseline}: битых строк {len(baseline_bad)}, первая — {baseline_bad[0].line}")
            else:
                print(f"baseline {a.baseline} не найден — дифф пропущен", file=sys.stderr)
        known = load_known(a.known) if a.known else None
        if known:
            validate_known(known, spec)
        scope = [i.strip() for i in a.scope.split(",") if i.strip()] if a.scope else None
        unknown = [i for i in scope or [] if i not in spec["inv"]]
        if scope is not None and (not scope or unknown):
            raise ValueError(f"--scope: нет в spec: {', '.join(unknown) or '(пусто)'}")
    except (OSError, ValueError) as e:
        print(f"ebt_check: {e}", file=sys.stderr)
        return 2

    try:
        r = build_report(spec, sha, records, bad, baseline, a.max_items, a.self_test, known, scope, file_starts)
    except ExtensionError as e:
        print(f"ebt_check: {e}", file=sys.stderr)
        return 2
    md = render_md(r, spec, a.max_items, a.allow_uncovered)
    try:
        if a.md:
            a.md.parent.mkdir(parents=True, exist_ok=True)
            a.md.write_text(md, encoding="utf-8")
        else:
            sys.stdout.write(md)
        if a.json:
            a.json.parent.mkdir(parents=True, exist_ok=True)
            a.json.write_text(json.dumps(asdict(r), ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, UnicodeError) as e:
        print(f"ebt_check: {e}", file=sys.stderr)
        return 2

    return 1 if r.failed(a.allow_uncovered) else 0


