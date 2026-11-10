"""Loading and validation of external specs, evidence and extensions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older: pip install tomli
    import tomli as tomllib

from .checkers import CHECKERS, DERIVED_PARTITIONS
from .engine import Finding, MALFORMED_LINE, TITLES


def _string(value, label: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label}: expected a string")


def _strings(value, label: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected a list of strings")
    for item in value:
        _string(item, label)


def load_spec(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    spec = tomllib.loads(raw.decode("utf-8"))
    for section in ("req", "inv", "meta"):
        spec.setdefault(section, {})
        if not isinstance(spec[section], dict):
            raise ValueError(f"{section}: expected a table")
    if not spec["inv"]:
        raise ValueError("the spec has no invariants [inv.*]")
    for req_id, req in spec["req"].items():
        _string(req_id, "req ID")
        if not isinstance(req, dict):
            raise ValueError(f"{req_id}: expected a requirement table")
        if "text" in req:
            _string(req["text"], f"{req_id}.text")
    for inv_id, inv in spec["inv"].items():
        _string(inv_id, "inv ID")
        if not isinstance(inv, dict):
            raise ValueError(f"{inv_id}: expected an invariant table")
        for key in ("req", "checker", "witness"):
            if key not in inv:
                raise ValueError(f"{inv_id}: the spec has no field {key!r}")
        for key in ("req", "checker"):
            _string(inv[key], f"{inv_id}.{key}")
        if inv["req"] not in spec["req"]:
            raise ValueError(f"{inv_id}: refers to unknown requirement {inv['req']}")
        _strings(inv["witness"], f"{inv_id}.witness")
        for key in ("partitions", "not_in_verdict"):
            if key in inv:
                _strings(inv[key], f"{inv_id}.{key}")
        if "statement" in inv and not isinstance(inv["statement"], str):
            raise ValueError(f"{inv_id}.statement: expected a string")
        if inv["checker"] == "transition" and "transitions" in inv:
            rows = inv["transitions"]
            if not isinstance(rows, list) or any(
                    not isinstance(row, list) or len(row) != 3
                    or any(not isinstance(cell, str) for cell in row) for row in rows):
                raise ValueError(f"{inv_id}.transitions: expected a list of string triples [from, event, to]")
    return spec, hashlib.sha256(raw).hexdigest()[:12]


def load_jsonl(path: Path, offset: int = 0) -> tuple[list[tuple[int, dict]], list[Finding]]:
    """offset: how many lines were in the previous files; line numbers are continuous, as in the concatenation."""
    records, bad = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=offset + 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError("expected an object")
            for key in ("inv", "req", "scope"):
                if rec.get(key) is not None and not isinstance(rec[key], str):
                    raise ValueError(f"{key} must be a string, got {rec[key]!r}")
            records.append((n, rec))
        except (ValueError, RecursionError) as e:
            # Nesting that is too deep: on 3.11 json.loads raises RecursionError,
            # on 3.12+ it parses or rejects it as an object of the wrong shape. This is a broken
            # line, not a startup error and not a checker crash (D34).
            bad.append(Finding(MALFORMED_LINE, n, reason=str(e)))
    return records, bad


def _registry(value, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected a dict")
    for name, fn in value.items():
        _string(name, f"{label}: checker name")
        if not callable(fn):
            raise ValueError(f"{label}[{name!r}]: expected a callable")


def load_checkers(path: Path) -> None:
    """Validates the whole extension, then adds it to the shared registry."""
    try:
        spec = importlib.util.spec_from_file_location("ebt_project_checks", path)
        if spec is None or spec.loader is None:
            raise ValueError("could not load the Python module")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except SystemExit as e:
        raise ValueError(f"{path}: SystemExit: {e.code}") from e
    except Exception as e:  # noqa: BLE001 — an import error in project code is a startup error
        raise ValueError(f"{path}: {type(e).__name__}: {e}") from e
    checks = getattr(mod, "CHECKERS", None)
    if not isinstance(checks, dict):
        raise ValueError(f"{path}: no CHECKERS dict")
    derived = getattr(mod, "DERIVED_PARTITIONS", {})
    _registry(checks, f"{path}: CHECKERS")
    _registry(derived, f"{path}: DERIVED_PARTITIONS")
    taken = sorted(CHECKERS.keys() & checks.keys() | DERIVED_PARTITIONS.keys() & derived.keys())
    if taken:
        raise ValueError(f"{path}: checker {', '.join(taken)} already exists in the core; give the project checker another name")
    unknown = sorted(derived.keys() - (CHECKERS.keys() | checks.keys()))
    if unknown:
        raise ValueError(f"{path}: DERIVED_PARTITIONS: unknown checkers: {', '.join(unknown)}")
    CHECKERS.update(checks)
    DERIVED_PARTITIONS.update(derived)


def load_known(path: Path) -> list[dict]:
    """Known findings: [[known]] with inv, kind, match (witness fields), reason, accepted.

    An empty match is forbidden: it would also hide new violations of the same invariant.
    kind is required: without it one entry would hide any kind of finding on the same input (D15).
    """
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("known", [])
    _known_entries(entries, path.name)
    return entries


def _known_entries(entries, label: str = "known") -> None:
    if not isinstance(entries, list):
        raise ValueError(f"{label}: expected a [[known]] list")
    for i, entry in enumerate(entries, start=1):
        where = f"{label}: entry {i}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: expected a table")
        for key in ("inv", "kind", "match", "reason", "accepted"):
            if not entry.get(key):
                raise ValueError(f"{where}: no field {key!r}")
        for key in ("inv", "kind", "reason", "accepted"):
            _string(entry[key], f"{where}.{key}")
        if not isinstance(entry["match"], dict):
            raise ValueError(f"{where}: match must be a table of witness fields")
        try:
            json.dumps(entry["match"])
        except (TypeError, ValueError) as e:
            raise ValueError(f"{where}: match must contain JSON values: {e}") from e


def validate_known(known: list[dict], spec: dict) -> None:
    """match keys are only the invariant's witness fields: otherwise code could add to data
    an invented key and hide any violation behind it (D15)."""
    _known_entries(known)
    for i, e in enumerate(known, start=1):
        inv = spec["inv"].get(e["inv"])
        if inv is None:
            raise ValueError(f"known: entry {i}: invariant {e['inv']} is not in the spec")
        extra = sorted(set(e["match"]) - set(inv["witness"]))
        if extra:
            raise ValueError(f"known: entry {i}: match has fields not from the witness of {e['inv']}: {', '.join(extra)}")
        if e["kind"] not in TITLES:
            raise ValueError(f"known: entry {i}: unknown kind {e['kind']!r}")


