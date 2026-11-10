#!/usr/bin/env python3
"""Verification of a witnessbox installation against a release.

`wheel` checks release.json (result PASS, version, wheel SHA-256) and the wheel file itself.
`installation` compares the JSON of `witnessbox --installation` with `release["installation"]`.

Code 0 means a match, 1 a mismatch or an unusable input. The script uses only the stdlib
and runs before installation, so it does not import witnessbox.
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
        raise ValueError(f"{path}: could not read JSON: {error}") from error


def sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"{path}: could not read the file: {error}") from error


def wheel_version(path: Path) -> str:
    """Version from the wheel name: <distribution>-<version>-<python>-<abi>-<platform>.whl."""
    name = path.name
    if not name.endswith(".whl"):
        raise ValueError(f"{path}: expected a .whl file")
    parts = name[:-len(".whl")].split("-")
    if len(parts) < 5:
        raise ValueError(f"{path}: the wheel name does not match the format distribution-version-python-abi-platform.whl")
    return parts[1]


def verify_wheel(release_path: Path, wheel_path: Path) -> int:
    try:
        release = load_json(release_path)
        if not isinstance(release, dict):
            raise ValueError(f"{release_path}: expected a JSON object")
        result = release.get("result")
        if result != "PASS":
            return fail(f"{release_path}: result={result!r}, expected PASS")
        expected_version = release.get("version")
        if not isinstance(expected_version, str) or not expected_version:
            return fail(f"{release_path}: no string version")
        actual_version = wheel_version(wheel_path)
        if actual_version != expected_version:
            return fail(f"wheel: version {actual_version} does not match release.json: {expected_version}")
        wheel = release.get("wheel")
        expected_sha = wheel.get("sha256") if isinstance(wheel, dict) else None
        if not isinstance(expected_sha, str) or not expected_sha:
            return fail(f"{release_path}: no wheel.sha256")
        actual_sha = sha256(wheel_path)
    except ValueError as error:
        return fail(str(error))
    if actual_sha != expected_sha:
        return fail(f"wheel: SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")
    print(f"wheel {wheel_path.name}: PASS (version {actual_version}, sha256 {actual_sha})")
    return 0


def verify_installation(release_path: Path, installation_path: Path) -> int:
    try:
        release = load_json(release_path)
        installation = load_json(installation_path)
    except ValueError as error:
        return fail(str(error))
    if not isinstance(release, dict) or not isinstance(release.get("installation"), dict):
        return fail(f"{release_path}: no installation object")
    if not isinstance(installation, dict):
        return fail(f"{installation_path}: expected a JSON object")
    expected = release["installation"]
    differences = []
    for field in ("distribution", "version", "gate_sha256", "checker_sha256"):
        expected_value = expected.get(field)
        actual_value = installation.get(field)
        if not isinstance(expected_value, str) or not expected_value:
            differences.append(f"{field}: not in release.json")
        elif expected_value != actual_value:
            differences.append(f"{field}: expected {expected_value!r}, got {actual_value!r}")
    if differences:
        print("installation: differences from release.json:", file=sys.stderr)
        for difference in differences:
            print(f"  {difference}", file=sys.stderr)
        return 1
    print("installation: PASS")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify witnessbox against release.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    wheel = subparsers.add_parser("wheel", help="verify the wheel against release.json")
    wheel.add_argument("release", type=Path)
    wheel.add_argument("wheel", type=Path)
    installation = subparsers.add_parser("installation", help="verify --installation against release.json")
    installation.add_argument("release", type=Path)
    installation.add_argument("installation", type=Path)
    args = parser.parse_args(argv)
    if args.command == "wheel":
        return verify_wheel(args.release, args.wheel)
    return verify_installation(args.release, args.installation)


if __name__ == "__main__":
    sys.exit(main())
