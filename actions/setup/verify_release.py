#!/usr/bin/env python3
"""Сверка установки witnessbox с выпуском.

`wheel` проверяет release.json (result PASS, версия, SHA-256 wheel) и сам файл wheel.
`installation` сверяет JSON `witnessbox --installation` с `release["installation"]`.

Код 0 — совпало, 1 — расхождение или непригодный вход. Скрипт использует только stdlib
и запускается до установки, поэтому он не импортирует witnessbox.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: не удалось прочитать JSON: {error}") from error


def sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"{path}: не удалось прочитать файл: {error}") from error


def wheel_version(path: Path) -> str:
    """Версия из имени wheel: <distribution>-<version>-<python>-<abi>-<platform>.whl."""
    name = path.name
    if not name.endswith(".whl"):
        raise ValueError(f"{path}: ожидался файл .whl")
    parts = name[:-len(".whl")].split("-")
    if len(parts) < 5:
        raise ValueError(f"{path}: имя wheel не соответствует формату distribution-version-python-abi-platform.whl")
    return parts[1]


def verify_wheel(release_path: Path, wheel_path: Path) -> int:
    try:
        release = load_json(release_path)
        if not isinstance(release, dict):
            raise ValueError(f"{release_path}: ожидался JSON-объект")
        result = release.get("result")
        if result != "PASS":
            return fail(f"{release_path}: result={result!r}, ожидался PASS")
        expected_version = release.get("version")
        if not isinstance(expected_version, str) or not expected_version:
            return fail(f"{release_path}: нет строкового version")
        actual_version = wheel_version(wheel_path)
        if actual_version != expected_version:
            return fail(f"wheel: версия {actual_version} не совпадает с release.json: {expected_version}")
        wheel = release.get("wheel")
        expected_sha = wheel.get("sha256") if isinstance(wheel, dict) else None
        if not isinstance(expected_sha, str) or not expected_sha:
            return fail(f"{release_path}: нет wheel.sha256")
        actual_sha = sha256(wheel_path)
    except ValueError as error:
        return fail(str(error))
    if actual_sha != expected_sha:
        return fail(f"wheel: SHA-256 не совпадает: ожидалось {expected_sha}, получено {actual_sha}")
    print(f"wheel {wheel_path.name}: PASS (версия {actual_version}, sha256 {actual_sha})")
    return 0


def verify_installation(release_path: Path, installation_path: Path) -> int:
    try:
        release = load_json(release_path)
        installation = load_json(installation_path)
    except ValueError as error:
        return fail(str(error))
    if not isinstance(release, dict) or not isinstance(release.get("installation"), dict):
        return fail(f"{release_path}: нет объекта installation")
    if not isinstance(installation, dict):
        return fail(f"{installation_path}: ожидался JSON-объект")
    expected = release["installation"]
    differences = []
    for field in ("distribution", "version", "gate_sha256", "checker_sha256"):
        expected_value = expected.get(field)
        actual_value = installation.get(field)
        if not isinstance(expected_value, str) or not expected_value:
            differences.append(f"{field}: нет в release.json")
        elif expected_value != actual_value:
            differences.append(f"{field}: ожидалось {expected_value!r}, получено {actual_value!r}")
    if differences:
        print("installation: расхождения с release.json:", file=sys.stderr)
        for difference in differences:
            print(f"  {difference}", file=sys.stderr)
        return 1
    print("installation: PASS")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Сверка witnessbox с release.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    wheel = subparsers.add_parser("wheel", help="сверить wheel с release.json")
    wheel.add_argument("release", type=Path)
    wheel.add_argument("wheel", type=Path)
    installation = subparsers.add_parser("installation", help="сверить --installation с release.json")
    installation.add_argument("release", type=Path)
    installation.add_argument("installation", type=Path)
    args = parser.parse_args(argv)
    if args.command == "wheel":
        return verify_wheel(args.release, args.wheel)
    return verify_installation(args.release, args.installation)


if __name__ == "__main__":
    sys.exit(main())
