#!/usr/bin/env python3
"""ebt_check: independent re-verification of the EBT proof log (level 2).

What it does:
  1. Re-verifies every record with its own checker, ignoring the ok field.
  2. Looks for false proofs (the code said ok, the checker disagrees),
     incomplete evidence, unregistered invariants, lost records.
  3. Builds coverage: REQ without INV, INV without records, uncovered partitions.
  4. Compares with the previous run (baseline): regression.
  5. Checker self-test: corrupts evidence fields and checks that the checker
     notices. A field whose corruption is never caught is not checked by the checker.
  6. Known findings (--known, approved by a human) are shown separately
     and do not fail the build: on existing code only new findings fail it.
  7. --scope INV,…: completeness of coverage (the invariant fired, all partitions) is required
     only for the task invariants. Records of other invariants are checked as usual:
     a regression in another rule still fails, while an invariant whose test is not in this branch does not.

Project checkers (--checkers file.py) are added to the checkers from the neighboring checkers.py
(a name clash with a core checker is a startup error, D18):
the file defines CHECKERS and optionally DERIVED_PARTITIONS, and takes Verdict and WitnessError
from witnessbox.api (the compatible imports ebt_verification.api and from checkers are also supported).

Standard library only, Python 3.11+ (on 3.10 with the tomli package).

  python tool/ebt_check/ebt_check.py \
      --spec ebt/spec.toml --evidence build/ebt/evidence.jsonl \
      --baseline build/ebt/baseline.jsonl \
      --md build/ebt/report.md --json build/ebt/report.json --self-test

Exit code: 0 everything proven; 1 critical findings or coverage gaps;
2 startup error (missing file, broken spec).
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
    p = argparse.ArgumentParser(prog="witnessbox check", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"witnessbox check {__version__}")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--evidence", required=True, type=Path, nargs="+",
                   help="JSONL log(s); several files mean several runs, seq restarts in each")
    p.add_argument("--baseline", type=Path, help="log of the previous run for the diff")
    p.add_argument("--known", type=Path, help="known findings (known.toml) that do not fail the build")
    p.add_argument("--checkers", type=Path, help="project checkers (.py with CHECKERS)")
    p.add_argument("--scope", help="comma-separated task invariants: coverage is required only for them")
    p.add_argument("--md", type=Path, help="where to write the markdown report (otherwise stdout)")
    p.add_argument("--json", type=Path, help="where to write the JSON report")
    p.add_argument("--self-test", action="store_true", help="check checker sensitivity")
    p.add_argument("--allow-uncovered", action="store_true", help="coverage gaps do not fail the build")
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
                    raise ValueError(f"baseline {a.baseline}: broken lines {len(baseline_bad)}, first: {baseline_bad[0].line}")
            else:
                print(f"baseline {a.baseline} not found: diff skipped", file=sys.stderr)
        known = load_known(a.known) if a.known else None
        if known:
            validate_known(known, spec)
        scope = [i.strip() for i in a.scope.split(",") if i.strip()] if a.scope else None
        unknown = [i for i in scope or [] if i not in spec["inv"]]
        if scope is not None and (not scope or unknown):
            raise ValueError(f"--scope: not in spec: {', '.join(unknown) or '(empty)'}")
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


