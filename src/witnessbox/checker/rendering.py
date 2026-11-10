"""Markdown rendering of the independent EBT report."""
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
        "# EBT: independent verification report",
        "",
        f"**Result: {'❌ not proven' if failed else '✅ proven on this run'}**",
        "",
        f"Spec `{r.spec_version}` (sha {r.spec_sha}) · records: {r.records} · scopes: {r.scopes}"
        + (f" · coverage required for: {', '.join(r.coverage_scope)}" if r.coverage_scope is not None else ""),
        "",
    ]
    if r.records == 0:
        L += ["**The log has no records: there is no proof.**", ""]
    for inv_id, weak in r.weak_required.items():
        L += [f"**Checker `{inv_id}` does not catch corruption of paths {', '.join(f'`{w}`' for w in weak)} — "
              "proof by this checker is not accepted (see \"Checker self-test\").**", ""]
    L += [
        "| Category | Count |",
        "|---|---|",
    ]
    for kind in CRITICAL:
        L.append(f"| {TITLES[kind]} | {r.count(kind)} |")
    L.append(f"| Requirements without invariants | {len(r.req_without_inv)} |")
    L.append(f"| Invariants without records | {len(r.inv_never_fired)} |")
    L.append(f"| Invariants with uncovered partitions | {len(r.uncovered_partitions)} |")
    if r.known_findings or r.known_unused:
        L.append(f"| Known findings (do not fail) | {len(r.known_findings)} |")

    crit = [f for f in r.findings if f.kind in CRITICAL]
    if crit:
        L += ["", "## Critical findings", ""]
        order = {k: i for i, k in enumerate(CRITICAL)}
        for f in sorted(crit, key=lambda f: (order[f.kind], f.line))[:limit]:
            L.append(f"### {TITLES[f.kind]} — `{f.inv or '?'}`")
            where = f"line {f.line}" if f.line else "spec.toml (checker not registered)"
            L.append(f"- Where: {where}, scope `{f.scope or '-'}`, seq {f.seq}")
            inv = spec["inv"].get(f.inv or "")
            if inv:
                req_text = " ".join(spec["req"][inv["req"]].get("text", "").split())
                L.append(f"- Requirement {inv['req']}: {req_text}")
                if inv.get("statement"):
                    L.append(f"- Invariant: {inv['statement']}")
            if f.verdict is not None:
                L.append(f"- Code claimed ok={f.claim}; checker: {'ok' if f.verdict else 'violation'}")
            elif f.claim is not None:
                L.append(f"- Code claimed ok={f.claim}; checker: could not verify")
            if f.reason:
                L.append(f"- Reason: {f.reason}")
            if f.witness is not None:
                L.append(f"- Evidence: `{_short(f.witness)}`")
            L.append("")
        if len(crit) > limit:
            L.append(f"_…and {len(crit) - limit} more; the full list is in the JSON report._")

    if r.has_coverage_gaps:
        L += ["", "## Coverage", ""]
        for req in r.req_without_inv:
            L.append(f"- **{req}** is not formalized by any invariant")
        for inv in r.inv_never_fired:
            L.append(f"- **{inv}** never fired: there is no proof for it")
        for inv, parts in r.uncovered_partitions.items():
            L.append(f"- **{inv}**: partitions not encountered: {', '.join(f'`{p}`' for p in parts)}")

    if r.known_findings or r.known_unused:
        L += ["", "## Known findings", "",
              "Accepted by a human in known.toml and do not fail the build.", ""]
        for f in r.known_findings[:limit]:
            L.append(f"- {TITLES.get(f.kind, f.kind)} — `{f.inv}`: {f.reason} · `{_short(f.witness, 200)}`")
        if len(r.known_findings) > limit:
            L.append(f"- …and {len(r.known_findings) - limit} more")
        for e in r.known_unused:
            L.append(f"- no longer occurs, can be removed from known.toml: `{e['inv']}` {_short(e['match'], 200)}")

    if r.baseline is not None:
        b = r.baseline
        L += ["", "## Changes since the previous run", ""]
        if not (b["appeared"] or b["vanished"] or b["count_changed"] or b["changed_total"]):
            L.append("Evidence matches the baseline.")
        for k in b["vanished"]:
            L.append(f"- `{k}` disappeared: the invariant stopped firing in the scope")
        for k in b["appeared"]:
            L.append(f"- `{k}` appeared")
        for c in b["count_changed"]:
            L.append(f"- `{c['key']}`: records were {c['before']}, now {c['after']}")
        for c in b["changed"]:
            L.append(f"- `{c['key']}`, record #{c['index'] + 1}: " + "; ".join(c["diff"]))
        if b["changed_total"] > len(b["changed"]):
            L.append(f"- …and {b['changed_total'] - len(b['changed'])} more changed records")

    if r.self_test is not None:
        L += ["", "## Checker self-test", "",
              "Each evidence field and the first elements of its lists are corrupted, "
              "and the checker is verified to notice it.", ""]
        for inv, s in r.self_test.items():
            if s["crashing_fields"]:
                L.append(f"- ⚠️ **{inv}**: the checker crashes on corrupted fields "
                         f"{', '.join(f'`{w}`' for w in s['crashing_fields'])} — it must answer with a verdict, not an exception")
            if s["weak_paths"]:
                L.append(f"- ⚠️ **{inv}**: corruption of paths {', '.join(f'`{w}`' for w in s['weak_paths'])} "
                         f"was never caught: the checker does not check them or they are superfluous in the witness")
            if s["shape_only_paths"]:
                L.append(f"- ℹ️ **{inv}**: corruption of path {', '.join(f'`{w}`' for w in s['shape_only_paths'])} "
                         "is caught only by the shape check: substitute another valid value in the test "
                         "or check that the checker compares it with the rule")
            if not (s["weak_paths"] or s["crashing_fields"] or s["shape_only_paths"]):
                L.append(f"- **{inv}**: corruption of any field is caught (samples: {s['samples']})")
    return "\n".join(L) + "\n"


