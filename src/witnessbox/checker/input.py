"""Загрузка и проверка внешних спецификаций, свидетельств и расширений."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 и старше: pip install tomli
    import tomli as tomllib

from .checkers import CHECKERS, DERIVED_PARTITIONS
from .engine import Finding, MALFORMED_LINE, TITLES


def _string(value, label: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label}: ожидалась строка")


def _strings(value, label: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{label}: ожидался список строк")
    for item in value:
        _string(item, label)


def load_spec(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    spec = tomllib.loads(raw.decode("utf-8"))
    for section in ("req", "inv", "meta"):
        spec.setdefault(section, {})
        if not isinstance(spec[section], dict):
            raise ValueError(f"{section}: ожидалась таблица")
    if not spec["inv"]:
        raise ValueError("в спецификации нет ни одного инварианта [inv.*]")
    for req_id, req in spec["req"].items():
        _string(req_id, "req ID")
        if not isinstance(req, dict):
            raise ValueError(f"{req_id}: ожидалась таблица требования")
        if "text" in req:
            _string(req["text"], f"{req_id}.text")
    for inv_id, inv in spec["inv"].items():
        _string(inv_id, "inv ID")
        if not isinstance(inv, dict):
            raise ValueError(f"{inv_id}: ожидалась таблица инварианта")
        for key in ("req", "checker", "witness"):
            if key not in inv:
                raise ValueError(f"{inv_id}: в спецификации нет поля {key!r}")
        for key in ("req", "checker"):
            _string(inv[key], f"{inv_id}.{key}")
        if inv["req"] not in spec["req"]:
            raise ValueError(f"{inv_id}: ссылается на неизвестное требование {inv['req']}")
        _strings(inv["witness"], f"{inv_id}.witness")
        for key in ("partitions", "not_in_verdict"):
            if key in inv:
                _strings(inv[key], f"{inv_id}.{key}")
        if "statement" in inv and not isinstance(inv["statement"], str):
            raise ValueError(f"{inv_id}.statement: ожидалась строка")
        if inv["checker"] == "transition" and "transitions" in inv:
            rows = inv["transitions"]
            if not isinstance(rows, list) or any(
                    not isinstance(row, list) or len(row) != 3
                    or any(not isinstance(cell, str) for cell in row) for row in rows):
                raise ValueError(f"{inv_id}.transitions: ожидался список троек строк [from, event, to]")
    return spec, hashlib.sha256(raw).hexdigest()[:12]


def load_jsonl(path: Path, offset: int = 0) -> tuple[list[tuple[int, dict]], list[Finding]]:
    """offset — сколько строк было в предыдущих файлах: номера строк сквозные, как в склейке."""
    records, bad = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=offset + 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError("ожидался объект")
            for key in ("inv", "req", "scope"):
                if rec.get(key) is not None and not isinstance(rec[key], str):
                    raise ValueError(f"{key} должен быть строкой, получено {rec[key]!r}")
            records.append((n, rec))
        except (ValueError, RecursionError) as e:
            # Слишком глубокая вложенность: на 3.11 json.loads бросает RecursionError,
            # на 3.12+ разбирает или отвергает как объект неправильного вида. Это битая
            # строка, а не ошибка запуска и не падение чекера (D34).
            bad.append(Finding(MALFORMED_LINE, n, reason=str(e)))
    return records, bad


def _registry(value, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label}: ожидался словарь")
    for name, fn in value.items():
        _string(name, f"{label}: имя чекера")
        if not callable(fn):
            raise ValueError(f"{label}[{name!r}]: ожидалась вызываемая функция")


def load_checkers(path: Path) -> None:
    """Проверяет расширение целиком, затем добавляет его в общий реестр."""
    try:
        spec = importlib.util.spec_from_file_location("ebt_project_checks", path)
        if spec is None or spec.loader is None:
            raise ValueError("не удалось загрузить Python-модуль")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except SystemExit as e:
        raise ValueError(f"{path}: SystemExit: {e.code}") from e
    except Exception as e:  # noqa: BLE001 — ошибка импорта проектного кода = ошибка запуска
        raise ValueError(f"{path}: {type(e).__name__}: {e}") from e
    checks = getattr(mod, "CHECKERS", None)
    if not isinstance(checks, dict):
        raise ValueError(f"{path}: нет словаря CHECKERS")
    derived = getattr(mod, "DERIVED_PARTITIONS", {})
    _registry(checks, f"{path}: CHECKERS")
    _registry(derived, f"{path}: DERIVED_PARTITIONS")
    taken = sorted(CHECKERS.keys() & checks.keys() | DERIVED_PARTITIONS.keys() & derived.keys())
    if taken:
        raise ValueError(f"{path}: чекер {', '.join(taken)} уже есть в ядре — дайте проектному другое имя")
    unknown = sorted(derived.keys() - (CHECKERS.keys() | checks.keys()))
    if unknown:
        raise ValueError(f"{path}: DERIVED_PARTITIONS: неизвестные чекеры: {', '.join(unknown)}")
    CHECKERS.update(checks)
    DERIVED_PARTITIONS.update(derived)


def load_known(path: Path) -> list[dict]:
    """Известные находки: [[known]] с inv, kind, match (поля witness), reason, accepted.

    Пустой match запрещён: он прятал бы и новые нарушения того же инварианта.
    kind обязателен: без него одна запись прятала бы на том же входе любой вид находки (D15).
    """
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("known", [])
    _known_entries(entries, path.name)
    return entries


def _known_entries(entries, label: str = "known") -> None:
    if not isinstance(entries, list):
        raise ValueError(f"{label}: ожидался список [[known]]")
    for i, entry in enumerate(entries, start=1):
        where = f"{label}: запись {i}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: ожидалась таблица")
        for key in ("inv", "kind", "match", "reason", "accepted"):
            if not entry.get(key):
                raise ValueError(f"{where}: нет поля {key!r}")
        for key in ("inv", "kind", "reason", "accepted"):
            _string(entry[key], f"{where}.{key}")
        if not isinstance(entry["match"], dict):
            raise ValueError(f"{where}: match должен быть таблицей полей witness")
        try:
            json.dumps(entry["match"])
        except (TypeError, ValueError) as e:
            raise ValueError(f"{where}: match должен содержать JSON-значения: {e}") from e


def validate_known(known: list[dict], spec: dict) -> None:
    """Ключи match — только поля witness инварианта: иначе код мог бы дописать в data
    придуманный ключ и спрятать за ним любое нарушение (D15)."""
    _known_entries(known)
    for i, e in enumerate(known, start=1):
        inv = spec["inv"].get(e["inv"])
        if inv is None:
            raise ValueError(f"known: запись {i}: инварианта {e['inv']} нет в spec")
        extra = sorted(set(e["match"]) - set(inv["witness"]))
        if extra:
            raise ValueError(f"known: запись {i}: в match поля не из witness {e['inv']}: {', '.join(extra)}")
        if e["kind"] not in TITLES:
            raise ValueError(f"known: запись {i}: неизвестный kind {e['kind']!r}")


