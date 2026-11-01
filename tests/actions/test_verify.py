"""Тесты доверенной стадии: `prepare.sh` берёт `ebt/` из BASE, `replay.sh` отдаёт
свидетельства из артефакта и является обычным `test.sh` по договору (`OUT_DIR`, коды).

Артефакт первой стадии — недоверенный вход: symlink, не обычный файл и неверный
`tests_exit_code` обязаны давать код 2, а не читаться и не исполняться.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests._verification_test_support import install_verification

KIT = Path(__file__).resolve().parents[2]
PREPARE = KIT / "actions" / "verify" / "prepare.sh"
REPLAY = KIT / "actions" / "verify" / "replay.sh"
FIXTURE = KIT / "src/witnessbox/checker/fixtures/record.jsonl"

SPEC = """[req.REQ-CART-1]
text = "Итог корзины = сумма позиций минус скидка."

[inv.INV-CART-3]
req = "REQ-CART-1"
checker = "cart_total"
witness = ["lines", "discount", "subtotal", "off", "result"]
partitions = ["no_discount"]
"""


class Verify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install_tmp, cls.bin, cls.wheel, cls.sdist = install_verification()
        cls.addClassCleanup(cls.install_tmp.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clone = self.root / "clone"
        self.clone.mkdir()
        (self.clone / ".gitignore").write_text("build/\n", encoding="utf-8")
        self.base = self.git_init()

    # ── построение прогона ────────────────────────────────────────────────

    def git(self, *args, check=True):
        return subprocess.run(
            ["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=check, capture_output=True, text=True)

    def git_init(self) -> str:
        self.git("init", "-q")
        return self.commit("init")

    def commit(self, message: str) -> str:
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write_ebt(self, spec: str = SPEC, prepare: str = "#!/bin/bash\nexit 0\n",
                  test_sh: str = "#!/bin/bash\nexit 0\n") -> None:
        ebt = self.clone / "ebt"
        ebt.mkdir(exist_ok=True)
        (ebt / "spec.toml").write_text(spec, encoding="utf-8")
        for name, body in (("prepare.sh", prepare), ("test.sh", test_sh)):
            path = ebt / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def artifact(self, tests_exit_code=0, evidence: bool = True) -> Path:
        artifact = self.root / "artifact"
        (artifact / "out").mkdir(parents=True, exist_ok=True)
        (artifact / "gate.json").write_text(
            json.dumps({"format": 1, "result": "PASS", "tests_exit_code": tests_exit_code}),
            encoding="utf-8")
        if evidence:
            (artifact / "out" / "a.jsonl").write_text(FIXTURE.read_text(encoding="utf-8"),
                                                       encoding="utf-8")
        return artifact

    def prepare(self, base: str, target: Path | None = None) -> subprocess.CompletedProcess:
        target = target or self.root / "target"
        return subprocess.run([str(PREPARE), str(self.clone), base, str(target)],
                              capture_output=True, text=True, env=self.env())

    def prepare_ok(self, base: str) -> Path:
        target = self.root / "target"
        p = self.prepare(base, target)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return target

    def gate(self, base: str, artifact: Path, target: Path) -> subprocess.CompletedProcess:
        run = self.root / "run"
        return subprocess.run(
            [str(self.bin / "ebt-gate"), str(target), str(self.clone), str(run)],
            capture_output=True, text=True,
            env={**self.env(), "BASE": base, "EBT_RUNNER": "test.sh",
                 "EBT_REPLAY_DIR": str(artifact), "EBT_TESTS": "", "EBT_CHECK": ""})

    def gate_json(self) -> dict:
        return json.loads((self.root / "run" / "gate.json").read_text(encoding="utf-8"))

    def replay(self, artifact: Path, out: Path | None = None, **env) -> subprocess.CompletedProcess:
        out = out or self.root / "out"
        out.mkdir(exist_ok=True)
        environment = {**self.env(), "EBT_REPLAY_DIR": str(artifact), "OUT_DIR": str(out)}
        environment.update(env)
        return subprocess.run([str(REPLAY)], cwd=self.clone, capture_output=True, text=True,
                              env=environment)

    @staticmethod
    def env() -> dict:
        environment = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        environment["PYTHONPATH"] = ""
        return environment

    # ── prepare.sh ────────────────────────────────────────────────────────

    def test_prepare_uses_base_spec_and_drops_prepare(self):
        self.write_ebt()
        base = self.commit("base ebt")
        # Ветка задачи меняет spec и prepare.sh; вторая стадия обязана взять копию из BASE
        # и не исполнять prepare.sh ветки.
        (self.clone / "ebt" / "spec.toml").write_text("broken = [\n", encoding="utf-8")
        (self.clone / "ebt" / "prepare.sh").write_text("#!/bin/bash\ntouch branch-prepare-ran\n",
                                                       encoding="utf-8")
        (self.clone / "ebt" / "prepare.sh").chmod(0o755)
        self.commit("branch edits ebt")

        target = self.prepare_ok(base)
        expected_spec = self.git("show", f"{base}:ebt/spec.toml").stdout
        self.assertEqual((target / "spec.toml").read_text(encoding="utf-8"), expected_spec)
        self.assertFalse((target / "prepare.sh").exists())
        self.assertEqual((target / "test.sh").read_bytes(), REPLAY.read_bytes())
        self.assertTrue(os.access(target / "test.sh", os.X_OK), "test.sh не исполняемый")

        artifact = self.artifact()
        p = self.gate(base, artifact, target)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        summary = self.gate_json()
        self.assertEqual(summary["result"], "FAIL")
        self.assertIn("protected_paths_changed", summary["reasons"])
        self.assertFalse((self.clone / "branch-prepare-ran").exists(),
                         "prepare.sh ветки не должен исполняться")

    def test_prepare_without_ebt_in_base_is_error(self):
        # BASE без ebt/: проверку вводят тем же PR — это ERROR, а не проверка пустой ветки.
        base = self.git("rev-parse", "HEAD").stdout.strip()
        p = self.prepare(base)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("ebt/", p.stderr)
        self.assertIn("BASE", p.stderr)
        self.assertFalse((self.root / "target").exists())

    # ── replay.sh: обычный PASS/FAIL по договору test.sh ──────────────────

    def test_replay_pass_from_artifact(self):
        self.write_ebt()
        base = self.commit("base ebt")
        target = self.prepare_ok(base)
        artifact = self.artifact(tests_exit_code=0)

        p = self.gate(base, artifact, target)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        summary = self.gate_json()
        self.assertEqual(summary["result"], "PASS")
        self.assertEqual(summary["tests_exit_code"], 0)
        self.assertEqual([item["file"] for item in summary["evidence"]], ["a.jsonl"])

    def test_replay_failed_tests_is_fail(self):
        self.write_ebt()
        base = self.commit("base ebt")
        target = self.prepare_ok(base)
        artifact = self.artifact(tests_exit_code=1)

        p = self.gate(base, artifact, target)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        summary = self.gate_json()
        self.assertEqual(summary["result"], "FAIL")
        self.assertIn("tests_failed", summary["reasons"])

    # ── replay.sh: недоверенный артефакт ─────────────────────────────────

    def test_replay_rejects_bad_exit_code(self):
        for value in ("0", None, True, 2, -1):
            with self.subTest(tests_exit_code=value):
                artifact = self.artifact(tests_exit_code=value)
                p = self.replay(artifact)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertEqual(list((self.root / "out").iterdir()), [])

    def test_replay_rejects_symlink_evidence(self):
        artifact = self.artifact(evidence=False)
        (artifact / "out" / "a.jsonl").symlink_to("/etc/passwd")
        p = self.replay(artifact)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(list((self.root / "out").iterdir()), [])

    def test_replay_without_evidence_is_error(self):
        artifact = self.artifact(evidence=False)
        p = self.replay(artifact)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(list((self.root / "out").iterdir()), [])

    def test_replay_copies_only_regular_jsonl(self):
        artifact = self.artifact()
        (artifact / "out" / "notes.txt").write_text("not evidence", encoding="utf-8")
        (artifact / "out" / "nested").mkdir()
        (artifact / "out" / "nested" / "b.jsonl").write_text(FIXTURE.read_text(encoding="utf-8"),
                                                             encoding="utf-8")
        p = self.replay(artifact)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sorted(path.name for path in (self.root / "out").iterdir()), ["a.jsonl"])

    def test_replay_rejects_symlinked_gate_json(self):
        artifact = self.artifact()
        other = self.root / "other-gate.json"
        other.write_text(json.dumps({"tests_exit_code": 0}), encoding="utf-8")
        (artifact / "gate.json").unlink()
        (artifact / "gate.json").symlink_to(other)
        p = self.replay(artifact)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_replay_requires_absolute_replay_dir_and_out_dir(self):
        artifact = self.artifact()
        p = self.replay(artifact, EBT_REPLAY_DIR="artifact")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        out = self.root / "relative-out"
        out.mkdir()
        p = subprocess.run([str(REPLAY)], cwd=self.clone, capture_output=True, text=True,
                           env={**self.env(), "EBT_REPLAY_DIR": str(artifact), "OUT_DIR": "relative-out"})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p = subprocess.run([str(REPLAY)], cwd=self.clone, capture_output=True, text=True,
                           env={**self.env(), "EBT_REPLAY_DIR": str(artifact)})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
