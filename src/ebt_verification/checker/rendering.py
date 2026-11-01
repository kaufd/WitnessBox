"""Markdown-представление независимого отчёта EBT."""
from __future__ import annotations

import json
from typing import Any

from .engine import CRITICAL, TITLES, Report

def _short(v: Any, n: int = 400) -> str:
    s = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return s if len(s) <= n else s[: n - 1] + "…"


def render_md(r: Report, spec: dict, limit: int, allow_uncovered: bool) -> str:
    failed = r.failed(allow_uncovered)
    L = [
        "# EBT: отчёт независимой проверки",
        "",
        f"**Итог: {'❌ не доказано' if failed else '✅ доказано на этом прогоне'}**",
        "",
        f"Спецификация `{r.spec_version}` (sha {r.spec_sha}) · записей: {r.records} · сценариев: {r.scopes}"
        + (f" · покрытие требуется для: {', '.join(r.coverage_scope)}" if r.coverage_scope is not None else ""),
        "",
    ]
    if r.records == 0:
        L += ["**В логе нет ни одной записи — доказательства нет.**", ""]
    for inv_id, weak in r.weak_required.items():
        L += [f"**Чекер `{inv_id}` не ловит порчу полей {', '.join(f'`{w}`' for w in weak)} — "
              "доказательство этим чекером не принимается (см. «Самопроверка чекеров»).**", ""]
    L += [
        "| Категория | Кол-во |",
        "|---|---|",
    ]
    for kind in CRITICAL:
        L.append(f"| {TITLES[kind]} | {r.count(kind)} |")
    L.append(f"| Требования без инвариантов | {len(r.req_without_inv)} |")
    L.append(f"| Инварианты без записей | {len(r.inv_never_fired)} |")
    L.append(f"| Инварианты с непройденными классами входов | {len(r.uncovered_partitions)} |")
    if r.known_findings or r.known_unused:
        L.append(f"| Известные находки (не валят) | {len(r.known_findings)} |")

    crit = [f for f in r.findings if f.kind in CRITICAL]
    if crit:
        L += ["", "## Критичные находки", ""]
        order = {k: i for i, k in enumerate(CRITICAL)}
        for f in sorted(crit, key=lambda f: (order[f.kind], f.line))[:limit]:
            L.append(f"### {TITLES[f.kind]} — `{f.inv or '?'}`")
            L.append(f"- Где: строка {f.line}, scope `{f.scope or '-'}`, seq {f.seq}")
            inv = spec["inv"].get(f.inv or "")
            if inv:
                req_text = " ".join(spec["req"][inv["req"]].get("text", "").split())
                L.append(f"- Требование {inv['req']}: {req_text}")
                if inv.get("statement"):
                    L.append(f"- Инвариант: {inv['statement']}")
            if f.verdict is not None:
                L.append(f"- Код заявил ok={f.claim}; чекер: {'ok' if f.verdict else 'нарушение'}")
            elif f.claim is not None:
                L.append(f"- Код заявил ok={f.claim}; чекер: не смог проверить")
            if f.reason:
                L.append(f"- Причина: {f.reason}")
            if f.witness is not None:
                L.append(f"- Свидетельство: `{_short(f.witness)}`")
            L.append("")
        if len(crit) > limit:
            L.append(f"_…и ещё {len(crit) - limit}; полный список в JSON-отчёте._")

    if r.has_coverage_gaps:
        L += ["", "## Покрытие", ""]
        for req in r.req_without_inv:
            L.append(f"- **{req}** не формализовано ни одним инвариантом")
        for inv in r.inv_never_fired:
            L.append(f"- **{inv}** ни разу не сработал — по нему нет ни одного доказательства")
        for inv, parts in r.uncovered_partitions.items():
            L.append(f"- **{inv}**: не встретились классы входов: {', '.join(f'`{p}`' for p in parts)}")

    if r.known_findings or r.known_unused:
        L += ["", "## Известные находки", "",
              "Приняты человеком в known.toml и сборку не валят.", ""]
        for f in r.known_findings[:limit]:
            L.append(f"- {TITLES.get(f.kind, f.kind)} — `{f.inv}`: {f.reason} · `{_short(f.witness, 200)}`")
        if len(r.known_findings) > limit:
            L.append(f"- …и ещё {len(r.known_findings) - limit}")
        for e in r.known_unused:
            L.append(f"- больше не встречается — можно удалить из known.toml: `{e['inv']}` {_short(e['match'], 200)}")

    if r.baseline is not None:
        b = r.baseline
        L += ["", "## Изменения относительно прошлого прогона", ""]
        if not (b["appeared"] or b["vanished"] or b["count_changed"] or b["changed_total"]):
            L.append("Свидетельства совпадают с baseline.")
        for k in b["vanished"]:
            L.append(f"- исчез `{k}` — инвариант перестал срабатывать в сценарии")
        for k in b["appeared"]:
            L.append(f"- появился `{k}`")
        for c in b["count_changed"]:
            L.append(f"- `{c['key']}`: записей было {c['before']}, стало {c['after']}")
        for c in b["changed"]:
            L.append(f"- `{c['key']}`, запись №{c['index'] + 1}: " + "; ".join(c["diff"]))
        if b["changed_total"] > len(b["changed"]):
            L.append(f"- …и ещё {b['changed_total'] - len(b['changed'])} изменённых записей")

    if r.self_test is not None:
        L += ["", "## Самопроверка чекеров", "",
              "Каждое поле свидетельства портится, и проверяется, что чекер это замечает.", ""]
        for inv, s in r.self_test.items():
            if s["crashing_fields"]:
                L.append(f"- ⚠️ **{inv}**: чекер падает на испорченных полях "
                         f"{', '.join(f'`{w}`' for w in s['crashing_fields'])} — он должен отвечать вердиктом, а не исключением")
            if s["weak_fields"]:
                L.append(f"- ⚠️ **{inv}**: порча полей {', '.join(f'`{w}`' for w in s['weak_fields'])} "
                         f"ни разу не поймана — чекер их не проверяет или они лишние в witness")
            if not (s["weak_fields"] or s["crashing_fields"]):
                L.append(f"- **{inv}**: порча любого поля ловится (образцов: {s['samples']})")
    return "\n".join(L) + "\n"


