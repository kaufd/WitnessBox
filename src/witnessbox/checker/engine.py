"""Report model and independent re-verification of EBT proofs."""
from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .checkers import CHECKERS, DERIVED_PARTITIONS, Verdict, WitnessError

# Finding categories. All except the INFO level fail the build.
FALSE_PROOF = "FALSE_PROOF"                  # code: ok, checker: violation (the most dangerous)
CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"  # code and checker agree: violation
CHECKER_DISAGREES = "CHECKER_DISAGREES"      # code: violation, checker: ok (one of them is wrong)
WITNESS_INCOMPLETE = "WITNESS_INCOMPLETE"    # fields missing, cannot re-verify
WITNESS_MALFORMED = "WITNESS_MALFORMED"      # fields present, but shape/types are wrong
UNKNOWN_INV = "UNKNOWN_INV"                  # invariant is not in the registry
REQ_MISMATCH = "REQ_MISMATCH"                # the record refers to the wrong requirement
NO_CHECKER = "NO_CHECKER"                    # the registry names a checker that does not exist
CHECKER_ERROR = "CHECKER_ERROR"              # the checker crashed: a bug in the checker itself
LOG_GAP = "LOG_GAP"                          # seq gap: records lost
MALFORMED_LINE = "MALFORMED_LINE"            # log line is not JSON

CRITICAL = [FALSE_PROOF, CONFIRMED_VIOLATION, CHECKER_DISAGREES, WITNESS_INCOMPLETE,
            WITNESS_MALFORMED, UNKNOWN_INV, REQ_MISMATCH, NO_CHECKER, CHECKER_ERROR, LOG_GAP,
            MALFORMED_LINE]

TITLES = {
    FALSE_PROOF: "False proof (code: ok, checker: violation)",
    CONFIRMED_VIOLATION: "Confirmed violation",
    CHECKER_DISAGREES: "Code reported a violation, checker disagrees",
    WITNESS_INCOMPLETE: "Incomplete evidence",
    WITNESS_MALFORMED: "Malformed evidence",
    UNKNOWN_INV: "Invariant not registered",
    REQ_MISMATCH: "Wrong requirement",
    NO_CHECKER: "No checker",
    CHECKER_ERROR: "Checker error",
    LOG_GAP: "Lost records",
    MALFORMED_LINE: "Broken log line",
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
    # Paths of checker weak spots (`field`, `field[i]`, `field.key`); for a scalar field the path
    # equals the field name (D43).
    weak_required: dict[str, list[str]] = field(default_factory=dict)

    def count(self, kind: str) -> int:
        return sum(1 for f in self.findings if f.kind == kind)

    @property
    def has_critical(self) -> bool:
        return any(f.kind in CRITICAL for f in self.findings)

    @property
    def has_coverage_gaps(self) -> bool:
        # The key is "scenario / invariant"; with --scope other invariants may not fire (D13).
        vanished = any(self.coverage_scope is None or k.rsplit(" / ", 1)[1] in self.coverage_scope
                       for k in (self.baseline or {}).get("vanished", []))
        return bool(self.req_without_inv or self.inv_never_fired or self.uncovered_partitions or vanished)

    def failed(self, allow_uncovered: bool) -> bool:
        # An empty log is not "incomplete coverage" but no proof at all: --allow-uncovered does not forgive it.
        # A weak checker (field corruption not caught) proves nothing, however many records there are.
        return (self.has_critical or self.records == 0 or bool(self.weak_required)
                or (self.has_coverage_gaps and not allow_uncovered))


def _known_match(f: Finding, e: dict) -> bool:
    if f.inv != e["inv"] or e["kind"] != f.kind or not isinstance(f.witness, dict):
        return False
    # The type is compared too: 1 and 1.0 in the evidence are different inputs.
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
    # "Can be removed" only if the invariant appeared in the log: otherwise the entry was simply not checked.
    r.known_unused = [e for i, e in enumerate(known) if i not in used and e["inv"] in seen]


class ExtensionError(ValueError):
    """Invalid extension or its parameters in the spec."""


def declared_partitions(inv: dict) -> list[str]:
    derive = DERIVED_PARTITIONS.get(inv["checker"])
    try:
        parts = derive(inv) if derive is not None else list(inv.get("partitions", []))
    except SystemExit as e:
        raise ExtensionError(f"{inv['checker']}: DERIVED_PARTITIONS: SystemExit: {e.code}") from e
    except Exception as e:  # noqa: BLE001 — project extension boundary
        raise ExtensionError(f"{inv['checker']}: DERIVED_PARTITIONS: {type(e).__name__}: {e}") from e
    if not isinstance(parts, list) or any(not isinstance(p, str) for p in parts):
        raise ExtensionError(f"{inv['checker']}: DERIVED_PARTITIONS must return a list of strings")
    return parts


# ── Checking a single record ─────────────────────────────────────────────


def run_checker(inv: dict, witness: dict) -> Verdict:
    verdict = CHECKERS[inv["checker"]](witness, inv)
    if not isinstance(verdict, Verdict):
        raise TypeError(f"{inv['checker']}: checker must return Verdict, got {type(verdict).__name__}")
    if (not isinstance(verdict.ok, bool) or not isinstance(verdict.reason, str)
            or not isinstance(verdict.parts, set)
            or any(not isinstance(part, str) for part in verdict.parts)):
        raise TypeError(f"{inv['checker']}: invalid Verdict: need ok bool, reason str, parts set[str]")
    return verdict


def check_record(n: int, rec: dict, spec: dict, hits: dict[str, set[str]],
                 seen: set[str]) -> Finding | None:
    """hits: partitions by records that prove the invariant: a record with a finding
    (including one known from known.toml) gives no coverage (D11, D15)."""
    inv_id, scope, seq = rec.get("inv"), rec.get("scope"), rec.get("seq")
    base = dict(line=n, scope=scope, seq=seq, inv=inv_id, req=rec.get("req"),
                claim=rec.get("ok"), witness=rec.get("data"))

    inv = spec["inv"].get(inv_id)
    if inv is None:
        return Finding(UNKNOWN_INV, reason="not in ebt/spec.toml: a new invariant must be approved", **base)
    seen.add(inv_id)
    if rec.get("req") != inv["req"]:
        return Finding(REQ_MISMATCH, reason=f"in the registry {inv_id} formalizes {inv['req']}", **base)
    if inv["checker"] not in CHECKERS:
        return Finding(NO_CHECKER, reason=f"checker {inv['checker']!r} is not implemented", **base)

    w = rec.get("data")
    if not isinstance(w, dict):
        return Finding(WITNESS_INCOMPLETE, reason="no data field", **base)
    missing = [k for k in inv["witness"] if w.get(k) is None]
    if missing:
        return Finding(WITNESS_INCOMPLETE, reason=f"missing fields: {', '.join(missing)}", **base)

    try:
        v = run_checker(inv, w)
    except WitnessError as e:
        return Finding(WITNESS_MALFORMED, reason=str(e), **base)
    except SystemExit as e:
        return Finding(CHECKER_ERROR, reason=f"SystemExit: {e.code}", **base)
    except Exception as e:  # noqa: BLE001 — a crashed checker must not bring down the whole report
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
                   reason="the checker considers the evidence valid: check the ok condition in the code or the checker itself", **base)


def check_integrity(records: list[tuple[int, dict]], file_starts: set[int] = frozenset()) -> list[Finding]:
    """seq grows by 1 within a run and resets to 1 on Ebt.reset().
    file_starts: numbers of the first records of each log file: a new file is a new run."""
    out, prev = [], None
    for n, rec in records:
        if n in file_starts:
            prev = None
        seq = rec.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            out.append(Finding(LOG_GAP, n, rec.get("scope"), None, rec.get("inv"), reason="no seq"))
            prev = None
            continue
        if seq == 1:
            prev = 1
            continue
        if prev is None:
            out.append(Finding(LOG_GAP, n, rec.get("scope"), seq, rec.get("inv"),
                               reason=f"run starts with seq={seq}: the first {seq - 1} records were lost (buffer overflow?)"))
        elif seq != prev + 1:
            out.append(Finding(LOG_GAP, n, rec.get("scope"), seq, rec.get("inv"),
                               reason=f"seq={seq} follows seq={prev}"))
        prev = seq
    return out


# ── Regression against baseline ───────────────────────────────────


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


# ── Checker self-test ──────────────────────────────────────────────


def _mutate(v: Any) -> tuple[bool, Any]:
    """Mutates the first scalar value inside v. Returns (succeeded, new)."""
    if isinstance(v, bool):
        return True, not v
    if isinstance(v, int):
        return True, v + 1
    if isinstance(v, float):
        return True, v + 1.0
    if isinstance(v, str):
        # Not a suffix (D16): a checker may legitimately look at only part of a string, the number and unit
        # in "1 day available", and miss the tail. If there is a digit, the first digit is changed
        # (a number in the text is what text checkers verify, while a word in place of a number may be legitimate);
        # if none, the whole string is replaced.
        m = re.search(r"\d", v)
        if m:
            return True, v[:m.start()] + str((int(m.group()) + 1) % 10) + v[m.end():]
        return True, "_mut" if v != "_mut" else "_mut2"
    if isinstance(v, list):
        if not v:
            return True, [0]  # empty list: add an element
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
# simplicity: the first 8 elements are corrupted at each nesting level; a checker reading
# only the first 8 is not caught: raise the limit or choose indexes by samples.
# Mutants grow roughly as 8^depth per field (depth 4 is about 100 thousand checker
# runs), so the self-test slows down on deeply nested evidence.


def _mutants(v: Any) -> list[tuple[str, Any]]:
    """Value mutants: (path suffix, value with injected corruption).

    `""` is the value itself, `"[i]"` a list element, `".key"` a dict key,
    recursively. For a non-empty list, deletion and the contents of the first
    MAX_INDEX elements are corrupted; there is no reordering, as a checker may legitimately compare some
    lists as a set.
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
            return [("", [0])]  # empty list: add an element
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
    """For each evidence field: whether the checker catches corruption of this field or its elements."""
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
        except Exception:  # noqa: BLE001 — such records are already in the findings
            pass

    result = {}
    for inv_id, ws in sorted(samples.items()):
        inv = spec["inv"][inv_id]
        fields = {}
        weak_paths: list[str] = []
        shape_only_paths: list[str] = []
        for k in inv["witness"]:
            attempts: list[tuple[str, dict, Any, bool]] = []
            for w in ws:
                attempts.extend((f"{k}{suffix}", w, mutated, False)
                                for suffix, mutated in _mutants(w[k]))
                # Substituting a value from a neighboring sample: same shape, but a different
                # valid value, which checks whether the checker compares it with the rule (D43).
                other = next((o for o in ws if o[k] != w[k]), None)
                if other is not None:
                    attempts.append((k, w, other[k], True))
            counts: dict[str, dict[str, int]] = {}
            for path, w, mutated, substituted in attempts:
                s = counts.setdefault(path, {"tried": 0, "substituted": 0, "killed": 0,
                                             "errors": 0, "rejected": 0})
                s["tried"] += 1
                if substituted:
                    s["substituted"] += 1
                m = copy.deepcopy(w)
                m[k] = mutated
                try:
                    if not run_checker(inv, m).ok:
                        s["killed"] += 1
                except WitnessError:
                    s["killed"] += 1
                    s["rejected"] += 1  # the shape broke, not the rule logic
                except SystemExit:
                    s["errors"] += 1
                except Exception:  # noqa: BLE001
                    s["errors"] += 1    # the checker crashed on corrupted data, also its defect
            fields[k] = {key: sum(s[key] for s in counts.values())
                         for key in ("tried", "killed", "errors", "rejected", "substituted")}
            # Substitution does not create weakness by itself: a container field at the top-level path
            # has no other mutants, and two valid samples with a difference that does not affect the verdict
            # would give a false FAIL. A path is weak only if it had
            # ordinary mutants (tried > substituted); substitution affects killed and shape_only.
            weak_paths.extend(p for p, s in counts.items()
                              if (s["tried"] > s["substituted"] and s["killed"] == 0
                                  and not s["errors"]))
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
    """Top-level field name from the path `field[i]…` or `field.key`."""
    return re.split(r"[.\[]", path, maxsplit=1)[0]


def _allowed(path: str, allowed: set[str]) -> bool:
    """The path is covered by not_in_verdict; a top-level field name covers its subpaths."""
    normalized = re.sub(r"\[\d+\]", "[*]", path)
    return any(normalized == entry or normalized.startswith(entry + ".")
               or normalized.startswith(entry + "[") for entry in allowed)


# ── Report assembly ─────────────────────────────────────────────────────


def missing_checkers(spec: dict, scope: list[str] | None = None) -> list[str]:
    """Invariants in scope that have no registered checker."""
    required = set(scope) if scope is not None else set(spec["inv"])
    return sorted(inv_id for inv_id in required
                  if inv_id in spec["inv"] and spec["inv"][inv_id]["checker"] not in CHECKERS)


def build_report(spec: dict, sha: str, records, bad_lines, baseline, limit: int, do_self_test: bool,
                 known: list[dict] | None = None, scope: list[str] | None = None,
                 file_starts: set[int] = frozenset()) -> Report:
    r = Report(spec_version=str(spec.get("meta", {}).get("version", "")), spec_sha=sha,
               records=len(records), scopes=len({rec.get("scope") for _, rec in records}))
    r.findings.extend(bad_lines)
    r.findings.extend(check_integrity(records, file_starts))
    # An invariant in scope with an unknown checker cannot be checked even without records.
    # If there is a record for it, NO_CHECKER comes from check_record; do not duplicate.
    recorded_invs = {rec.get("inv") for _, rec in records}
    for inv_id in missing_checkers(spec, scope):
        if inv_id in recorded_invs:
            continue
        inv = spec["inv"][inv_id]
        r.findings.append(Finding(NO_CHECKER, line=0, inv=inv_id, req=inv["req"],
                                  reason=f"checker {inv['checker']!r} is not implemented"))

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
        # A field or path that legitimately does not affect the verdict is listed by the owner
        # in not_in_verdict: a field name or a path with [*], e.g. "lines" or "lines[*].note" (D15, D43).
        for inv_id in sorted(required & r.self_test.keys()):
            allowed = set(spec["inv"][inv_id].get("not_in_verdict", []))
            weak = [p for p in r.self_test[inv_id]["weak_paths"] if not _allowed(p, allowed)]
            if weak:
                r.weak_required[inv_id] = weak
    return r


