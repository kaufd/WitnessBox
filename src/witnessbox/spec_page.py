"""A self-contained HTML page of spec.toml for a human to review and approve (D58).

The page shows the requirements, their invariants and the sha256 of the exact file, so an approval
names one version of the spec. It is a view only: the gate and the checker do not read it.
"""

import hashlib
from html import escape
from pathlib import Path

from witnessbox.checker.input import load_spec

CSS = """
/* Layout: one reading column; each requirement is a section, its invariants are bordered panels inside it. */
:root {
  --paper: #f6f7f9;
  --surface: #ffffff;
  --ink: #18202b;
  --muted: #5b6676;
  --rule: #d9dee6;
  --accent: #1f4fb8;
  --accent-soft: #e7eefc;
  --warn: #8a5300;
  --warn-soft: #fbf0dc;
  --font-body: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --paper: #11161d; --surface: #18202a; --ink: #e4e9f0; --muted: #98a3b3;
    --rule: #2b3542; --accent: #8fb0ff; --accent-soft: #1e2b45;
    --warn: #f0b860; --warn-soft: #3a2c14;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #11161d; --surface: #18202a; --ink: #e4e9f0; --muted: #98a3b3;
  --rule: #2b3542; --accent: #8fb0ff; --accent-soft: #1e2b45;
  --warn: #f0b860; --warn-soft: #3a2c14;
}
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 15px/1.6 var(--font-body);
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
}
.page { max-width: 860px; margin: 0 auto; padding-block: 40px 64px; display: grid; gap: 40px; }
h1, h2, h3 { text-wrap: balance; margin: 0; line-height: 1.2; font-weight: 650; }
h1 { font-size: 32px; letter-spacing: -0.01em; }
h2 { font-size: 21px; }
h3 { font-size: 16px; }
code, .mono { font-family: var(--font-mono); font-size: 0.92em; }
.label { font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }

header { display: grid; gap: 20px; }
.file { color: var(--muted); font-family: var(--font-mono); font-size: 13px; overflow-wrap: anywhere; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
  background: var(--rule); border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; }
.fact { background: var(--surface); padding: 12px 14px; display: grid; gap: 2px; }
.fact .value { font-family: var(--font-mono); font-size: 15px; font-variant-numeric: tabular-nums; }
.hash { display: grid; gap: 4px; padding: 12px 14px; border: 1px dashed var(--accent);
  border-radius: 6px; background: var(--accent-soft); }
.hash .value { font-family: var(--font-mono); font-size: 13px; overflow-wrap: anywhere; }
.hash .value b { color: var(--accent); font-weight: 650; }

nav ol { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
nav a { display: inline-block; padding: 4px 10px; border: 1px solid var(--rule); border-radius: 4px;
  color: var(--ink); text-decoration: none; font-family: var(--font-mono); font-size: 13px; background: var(--surface); }
nav a:hover, nav a:focus-visible { border-color: var(--accent); color: var(--accent); }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.req { display: grid; gap: 16px; padding-top: 24px; border-top: 2px solid var(--ink); scroll-margin-top: 16px; }
.req-head, .inv-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 16px; }
.req-text, .statement { margin: 0; max-width: 65ch; }
.source { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; font-size: 14px; color: var(--muted); }
.flag { display: inline-block; padding: 1px 8px; border-radius: 3px; font-size: 12px; font-weight: 600;
  color: var(--warn); background: var(--warn-soft); }

.inv { background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 16px 18px;
  display: grid; gap: 14px; scroll-margin-top: 16px; }
.rows { display: grid; grid-template-columns: max-content 1fr; gap: 10px 16px; align-items: baseline; margin: 0; }
.rows dt, .rows dd { margin: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; list-style: none; margin: 0; padding: 0; }
.chips li { font-family: var(--font-mono); font-size: 13px; padding: 1px 8px; border-radius: 3px;
  border: 1px solid var(--rule); background: var(--paper); }
.chips.witness li { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.note { font-size: 13px; color: var(--muted); }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-family: var(--font-mono); font-size: 13px; }
th, td { text-align: left; padding: 4px 16px 4px 0; border-bottom: 1px solid var(--rule); }
th { font-family: var(--font-body); font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--muted); }
td.arrow { color: var(--muted); padding-right: 8px; }

footer { font-size: 13px; color: var(--muted); border-top: 1px solid var(--rule); padding-top: 16px; }

@media (max-width: 520px) {
  h1 { font-size: 26px; }
  .rows { grid-template-columns: 1fr; gap: 4px; }
  .rows dd { margin-bottom: 8px; }
}
"""


def _chips(items: list[str], cls: str = "") -> str:
    return f'<ul class="chips {cls}">' + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def _flag(text: str) -> str:
    return f'<span class="flag">{escape(text)}</span>'


def _invariant(inv_id: str, inv: dict) -> str:
    rows = [("Checker", f'<code>{escape(inv["checker"])}</code>'),
            ("Witness", _chips(inv["witness"], "witness"))]
    if inv.get("transitions"):
        body = "".join(f'<tr><td>{escape(a)}</td><td>{escape(e)}</td><td class="arrow">→</td><td>{escape(b)}</td></tr>'
                       for a, e, b in inv["transitions"])
        rows.append(("Transitions",
                     '<div class="table-wrap"><table><thead><tr><th>From</th><th>Event</th><th></th><th>To</th>'
                     f'</tr></thead><tbody>{body}</tbody></table></div>'
                     f'<p class="note">One coverage partition per transition: {len(inv["transitions"])}.</p>'))
    elif inv.get("partitions"):
        rows.append(("Partitions", _chips(inv["partitions"])))
    else:
        rows.append(("Partitions", _flag("none")))
    if inv.get("not_in_verdict"):
        rows.append(("Not in verdict", _chips(inv["not_in_verdict"])))
    statement = inv.get("statement")
    statement_html = f'<p class="statement">{escape(statement)}</p>' if statement else f"<p>{_flag('no statement')}</p>"
    rows_html = "".join(f'<dt class="label">{k}</dt><dd>{v}</dd>' for k, v in rows)
    return (f'<article class="inv" id="{escape(inv_id)}"><div class="inv-head">'
            f'<h3 class="mono">{escape(inv_id)}</h3><span class="label">Invariant</span></div>'
            f'{statement_html}<dl class="rows">{rows_html}</dl></article>')


def render(spec: dict, raw: bytes, shown_path: str) -> str:
    """The page for a spec already validated by load_spec; raw is the file bytes the hash is taken from."""
    sha = hashlib.sha256(raw).hexdigest()
    reqs, invs = spec["req"], spec["inv"]
    by_req: dict[str, list[str]] = {req_id: [] for req_id in reqs}
    for inv_id, inv in invs.items():
        by_req[inv["req"]].append(inv_id)
    uncovered = sum(1 for ids in by_req.values() if not ids)
    no_source = sum(1 for req in reqs.values() if not req.get("source"))
    facts = [("Version", spec["meta"].get("version", "—")), ("Requirements", len(reqs)),
             ("Invariants", len(invs)), ("Without invariants", uncovered), ("Without source", no_source)]
    facts_html = "".join(f'<div class="fact"><span class="label">{k}</span>'
                         f'<span class="value">{escape(str(v))}</span></div>' for k, v in facts)
    nav = "".join(f'<li><a href="#{escape(r)}">{escape(r)}</a></li>' for r in reqs)

    sections = []
    for req_id, req in reqs.items():
        source = req.get("source")
        source_html = escape(" ".join(str(source).split())) if source else _flag("not given")
        invariants = "".join(_invariant(i, invs[i]) for i in by_req[req_id]) or (
            f'<p>{_flag("no invariants")} <span class="note">The gate does not check this requirement.</span></p>')
        sections.append(
            f'<section class="req" id="{escape(req_id)}"><div class="req-head">'
            f'<h2 class="mono">{escape(req_id)}</h2><span class="label">Requirement</span></div>'
            f'<p class="req-text">{escape(" ".join(str(req.get("text", "")).split()))}</p>'
            f'<div class="source"><span class="label">Source</span><span>{source_html}</span></div>'
            f"{invariants}</section>")

    path = Path(shown_path)
    project = path.parent.parent.name if path.parent.name == "ebt" else path.parent.name
    title = f"{project} EBT spec" if project else "EBT spec"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="claude:viewport-fit-sides" content="cover">
<title>{escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
<header>
  <div class="file">{escape(shown_path)}</div>
  <h1>{escape(title)}</h1>
  <div class="facts">{facts_html}</div>
  <div class="hash"><span class="label">spec.toml sha256 · an approval names exactly this file</span>
    <span class="value"><b>{sha[:12]}</b>{sha[12:]}</span></div>
  <nav aria-label="Requirements"><ol>{nav}</ol></nav>
</header>
{"".join(sections)}
<footer>Built from {escape(shown_path)}. The gate and the checker report print the first 12 characters
of this hash. Any edit of the file changes the hash, and the spec has to be approved again.</footer>
</div>
</body>
</html>
"""


def write_page(spec_path, out_path, shown_path=None) -> str:
    """Validates spec_path as the checker does, writes the page to out_path, returns the full sha256."""
    spec_path, out_path = Path(spec_path), Path(out_path)
    spec, _ = load_spec(spec_path)
    raw = spec_path.read_bytes()
    out_path.write_text(render(spec, raw, str(shown_path or spec_path)), encoding="utf-8")
    return hashlib.sha256(raw).hexdigest()
