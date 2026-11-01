"""Тесты `actions/setup/verify_release.py`: сверка wheel и `--installation` с release.json.

Скрипт запускается отдельным процессом (`python -I`), как в composite action: он живёт
вне пакета, использует только stdlib и не должен зависеть от PYTHONPATH репозитория.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests._verification_test_support import install_verification

KIT = Path(__file__).resolve().parents[2]
SCRIPT = KIT / "actions" / "setup" / "verify_release.py"
VERSION = tomllib.loads((KIT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VerifyRelease(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_verify(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})

    def wheel(self, name: str = "witnessbox-0.5.2-py3-none-any.whl") -> Path:
        path = self.root / name
        path.write_bytes(b"test wheel bytes")
        return path

    def release(self, wheel_path: Path, **overrides) -> Path:
        data = {
            "version": "0.5.2",
            "result": "PASS",
            "wheel": {"file": wheel_path.name, "sha256": sha256(wheel_path)},
            "installation": {
                "distribution": "witnessbox",
                "version": "0.5.2",
                "gate_sha256": "a" * 64,
                "checker_sha256": "b" * 64,
            },
        }
        data.update(overrides)
        path = self.root / "release.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def installation(self, **overrides) -> Path:
        data = {
            "distribution": "witnessbox",
            "version": "0.5.2",
            "gate_sha256": "a" * 64,
            "checker_sha256": "b" * 64,
        }
        data.update(overrides)
        path = self.root / "installation.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_wheel_matches_release(self):
        wheel = self.wheel()
        p = self.run_verify("wheel", self.release(wheel), wheel)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_wheel_sha_mismatch_fails(self):
        wheel = self.wheel()
        expected = sha256(wheel)
        release = self.release(wheel, wheel={"file": wheel.name, "sha256": "0" * 64})
        p = self.run_verify("wheel", release, wheel)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(expected, p.stderr)
        self.assertIn("0" * 64, p.stderr)

    def test_release_not_pass_fails(self):
        wheel = self.wheel()
        p = self.run_verify("wheel", self.release(wheel, result="FAIL"), wheel)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("FAIL", p.stderr)

    def test_version_mismatch_fails(self):
        wheel = self.wheel("witnessbox-0.6.0-py3-none-any.whl")
        p = self.run_verify("wheel", self.release(wheel, version="0.5.2"), wheel)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("0.6.0", p.stderr)
        self.assertIn("0.5.2", p.stderr)

    def test_installation_matches(self):
        p = self.run_verify("installation", self.release(self.wheel()), self.installation())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_installation_checker_sha_mismatch_fails(self):
        p = self.run_verify("installation", self.release(self.wheel()),
                            self.installation(checker_sha256="c" * 64))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("checker_sha256", p.stderr)


class InstalledRelease(unittest.TestCase):
    """Настоящий wheel: release.json собирается из `--installation` и SHA файла."""

    @classmethod
    def setUpClass(cls):
        cls.install_tmp, cls.bin, cls.wheel, cls.sdist = install_verification()
        cls.addClassCleanup(cls.install_tmp.cleanup)

    def test_installation_of_real_wheel_matches_release_check(self):
        env = {**os.environ, "PYTHONPATH": ""}
        installation = json.loads(subprocess.check_output(
            [str(self.bin / "ebt-gate"), "--installation"], text=True, env=env))
        release = {
            "version": VERSION,
            "result": "PASS",
            "wheel": {"file": self.wheel.name, "sha256": sha256(self.wheel)},
            "installation": {k: installation[k] for k in
                             ("distribution", "version", "gate_sha256", "checker_sha256")},
        }
        release_path = Path(self.install_tmp.name) / "release.json"
        release_path.write_text(json.dumps(release), encoding="utf-8")
        installation_path = Path(self.install_tmp.name) / "installation.json"
        installation_path.write_text(json.dumps(installation), encoding="utf-8")

        for args in (("wheel", release_path, self.wheel),
                     ("installation", release_path, installation_path)):
            with self.subTest(command=args[0]):
                p = subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

        self.assertEqual(release["version"], VERSION)
        self.assertEqual(self.wheel.name, f"witnessbox-{VERSION}-py3-none-any.whl")


if __name__ == "__main__":
    unittest.main()
