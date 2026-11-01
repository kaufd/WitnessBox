"""Тесты ebt-gate.sh и заготовки ebt/: договор с test.sh проекта (OUT_DIR, коды), свежесть
свидетельств, итог попытки, шаблоны spec/test.sh/pinned.txt и `--scaffold`.

python3 -m unittest discover -s tests
"""

import os
import subprocess
import tempfile
import tomllib
import unittest

from tests._verification_test_support import install_verification
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
FIXTURE = KIT / "src/ebt_verification/checker/fixtures/record.jsonl"

SPEC = """[req.REQ-CART-1]
text = "Итог корзины = сумма позиций минус скидка."

[inv.INV-CART-3]
req = "REQ-CART-1"
checker = "cart_total"
witness = ["lines", "discount", "subtotal", "off", "result"]
partitions = ["no_discount"]
"""


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install_tmp, cls.bin, cls.wheel = install_verification()
        cls.addClassCleanup(cls.install_tmp.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.clone, self.ebt, self.run_dir = root / "clone", root / "ebt", root / "run"
        self.clone.mkdir()
        self.ebt.mkdir()
        (self.ebt / "spec.toml").write_text(SPEC, encoding="utf-8")
        (self.clone / ".gitignore").write_text("build/\n")
        git = ["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        self.record = FIXTURE.read_text(encoding="utf-8")

    def gate(self, test_sh: str | None, env: dict | None = None) -> subprocess.CompletedProcess:
        script = self.ebt / "test.sh"
        if test_sh is not None:
            script.write_text("#!/bin/bash\nset -u\n" + test_sh, encoding="utf-8")
            script.chmod(0o755)
        return subprocess.run([str(self.bin / "ebt-gate"), str(self.ebt), str(self.clone), str(self.run_dir)],
                              capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "", "BASE": "", "EBT_RUNNER": "", **(env or {})})

    def write_to(self, target: str) -> str:
        return f"mkdir -p {target}\ncat > {target}/a.jsonl <<'JSONL'\n{self.record}\nJSONL\n"

    def gate_md(self) -> str:
        path = self.run_dir / "gate.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def gate_json(self) -> dict:
        import json
        return json.loads((self.run_dir / "gate.json").read_text(encoding="utf-8"))

    def fake_checker(self, rc: int) -> Path:
        """Подставной ebt-check на PATH: всегда отвечает кодом rc."""
        bin_dir = self.run_dir.parent / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "ebt-check"
        fake.write_text(f"#!/bin/bash\necho 'ebt-check 9.9.9'\nexit {rc}\n", encoding="utf-8")
        fake.chmod(0o755)
        return fake

    def fake_command(self, name: str, body: str) -> Path:
        directory = self.run_dir.parent / "commands"
        directory.mkdir(exist_ok=True)
        command = directory / name
        command.write_text("#!/bin/bash\n" + body, encoding="utf-8")
        command.chmod(0o755)
        return command

    def command_env(self, command: Path, **env) -> dict:
        return {"PATH": f"{command.parent}:{os.environ['PATH']}", **env}

    def test_strict_runner_requires_test_script(self):
        p = self.gate(None, {"EBT_RUNNER": "test.sh"})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("EBT_RUNNER=flutter", p.stderr)

    def test_legacy_flutter_adapter_explicit_and_implicit(self):
        flutter = self.fake_command("flutter", 'if [ "$1" = --version ]; then echo "Flutter test-double"; exit 0; fi\n'
                                    + self.write_to("build/ebt"))
        for selection in ("flutter", ""):
            with self.subTest(selection=selection):
                p = self.gate(None, self.command_env(flutter, EBT_RUNNER=selection))
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn("flutter test --no-pub test/ebt", self.gate_md())
                self.assertIn("Flutter test-double", self.gate_md())
                self.assertEqual("Совместимость:" in p.stderr, not selection)

    def test_runner_filters_and_out_dir_contract_are_preserved(self):
        script = ('[ "$#" -eq 2 ] && [ "$1" = one ] && [ "$2" = two ] || exit 2\n'
                  '[ "${OUT_DIR:0:1}" = / ] && [ -z "$(ls -A "$OUT_DIR")" ] || exit 2\n'
                  + self.write_to('"$OUT_DIR"'))
        p = self.gate(script, {"EBT_RUNNER": "test.sh", "EBT_TESTS": "one two"})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        (self.ebt / "test.sh").unlink()
        flutter = self.fake_command("flutter", 'if [ "$1" = --version ]; then echo "Flutter test-double"; exit 0; fi\n'
                                    '[ "$*" = "test --no-pub one two" ] || exit 2\n'
                                    + self.write_to("build/ebt"))
        p = self.gate(None, self.command_env(flutter, EBT_RUNNER="flutter", EBT_TESTS="one two"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        # Мост build/ebt копируется в out/: evidence перечисляет то, что читал чекер.
        self.assertEqual([e["file"] for e in self.gate_json()["evidence"]], ["a.jsonl"])

    def test_runner_choice_errors_do_not_fall_back_to_flutter(self):
        flutter = self.fake_command("flutter", 'echo unexpected-flutter >&2\nexit 0\n')
        script = self.ebt / "test.sh"
        script.write_text("#!/bin/bash\nexit 0\n")
        script.chmod(0o644)
        for selection in ("", "flutter", "unsupported"):
            with self.subTest(selection=selection):
                p = self.gate(None, self.command_env(flutter, EBT_RUNNER=selection))
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertNotIn("unexpected-flutter", p.stderr)
                self.assertFalse((self.run_dir / "gate.md").exists())

    def test_explicit_flutter_does_not_bypass_existing_test_script(self):
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_RUNNER": "flutter"})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("пакет содержит test.sh", p.stderr)

    def test_preflight_git_failures_are_errors(self):
        import shutil
        real_git = shutil.which("git")
        for operation in ("status", "ls-files", "rev-parse"):
            with self.subTest(operation=operation):
                git = self.fake_command("git", f'if [ "$1" = {operation} ]; then exit 37; fi\nexec "{real_git}" "$@"\n')
                p = self.gate(self.write_to('"$OUT_DIR"'), self.command_env(git))
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("git " + operation, p.stderr)
                self.assertFalse((self.run_dir / "gate.md").exists())

    def test_non_git_directory_is_not_a_clean_checkout(self):
        import shutil
        shutil.rmtree(self.clone / ".git")
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse((self.run_dir / "gate.md").exists())

    def test_git_failure_after_tests_is_error(self):
        import shutil
        real_git = shutil.which("git")
        marker = self.clone.parent / "after-tests"
        git = self.fake_command("git", f'if [ "$1" = rev-parse ] && [ -f "{marker}" ]; then exit 37; fi\nexec "{real_git}" "$@"\n')
        p = self.gate(self.write_to('"$OUT_DIR"') + f'touch "{marker}"\n', self.command_env(git))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("после тестов", p.stderr)

    def test_output_io_failures_never_pass(self):
        for filename in ("gate.md", "gate.json", "evidence.jsonl", "ebt-check.err", "report.md", "report.json"):
            with self.subTest(filename=filename):
                # Created during execution: initial cleanup cannot detect this failure.
                script = self.write_to('"$OUT_DIR"') + f'mkdir "$(dirname "$OUT_DIR")/{filename}"\n'
                p = self.gate(script)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertNotIn("зелёный", self.gate_md() if (self.run_dir / "gate.md").is_file() else "")
                if (self.run_dir / "gate.json").is_file():
                    self.assertEqual(self.gate_json()["result"], "ERROR")
                target = self.run_dir / filename
                if target.is_dir():
                    target.rmdir()

    def test_log_open_failure_is_error(self):
        (self.ebt / "prepare.sh").write_text('#!/bin/bash\nmkdir "' + str(self.run_dir / "test.log") + '"\n')
        (self.ebt / "prepare.sh").chmod(0o755)
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("не удалось открыть test.log", p.stderr)

    def test_tracked_runner_changes_are_stashed(self):
        p = self.gate(self.write_to('"$OUT_DIR"') + 'echo changed > .gitignore\n')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((self.clone / ".gitignore").read_text(), "build/\n")
        stash = subprocess.check_output(["git", "-C", str(self.clone), "stash", "list"], text=True)
        self.assertIn("ebt-gate: изменения за прогон", stash)

    def test_stash_failure_cannot_publish_pass(self):
        import shutil
        real_git = shutil.which("git")
        git = self.fake_command("git", f'case " $* " in *" stash push "*) exit 37;; esac\nexec "{real_git}" "$@"\n')
        p = self.gate(self.write_to('"$OUT_DIR"'), self.command_env(git))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertNotIn("зелёный", p.stdout)
        self.assertFalse((self.run_dir / "gate.md").exists())
        self.assertEqual(self.gate_json()["result"], "ERROR")
        self.assertIn("git stash", self.gate_json()["message"])

    def test_gate_json_and_report_json_contract(self):
        """Поддерживаемые машиночитаемые итоги: gate.json гейта и report.json чекера."""
        import json
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        s = self.gate_json()
        self.assertEqual((s["format"], s["result"], s["exit_code"], s["reasons"]), (1, "PASS", 0, []))
        self.assertEqual((s["tests_exit_code"], s["checker_exit_code"], s["message"]), (0, 0, None))
        head = subprocess.check_output(["git", "-C", str(self.clone), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(s["commit"], head)
        self.assertEqual(s["verifier"]["version"], "0.3.1")
        self.assertRegex(s["verifier"]["gate_sha256"], "^[0-9a-f]{64}$")
        self.assertRegex(s["checker"]["sha256"], "^[0-9a-f]{64}$")
        self.assertRegex(s["spec_sha256"], "^[0-9a-f]{64}$")
        self.assertLessEqual({"gate.md", "report.md", "report.json", "evidence.jsonl", "out",
                              "test.log", "installation.json", "inputs"}, set(s["files"]))
        import hashlib
        out = self.run_dir / "out"
        self.assertEqual(s["evidence"], [{"file": "a.jsonl",
                                          "sha256": hashlib.sha256((out / "a.jsonl").read_bytes()).hexdigest()}])
        report = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        self.assertLessEqual({"spec_sha", "records", "findings", "req_without_inv", "inv_never_fired",
                              "uncovered_partitions", "baseline", "self_test"}, report.keys())

        p = self.gate(self.write_to('"$OUT_DIR"') + "exit 1\n")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        s = self.gate_json()
        self.assertEqual((s["result"], s["reasons"], s["tests_exit_code"], s["checker_exit_code"]),
                         ("FAIL", ["tests_failed"], 1, 0))
        self.assertEqual([e["file"] for e in s["evidence"]], ["a.jsonl"])

        (self.ebt / "spec.toml").unlink()
        p = self.gate("exit 0\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        s = self.gate_json()
        self.assertEqual((s["result"], s["exit_code"], s["reasons"]), ("ERROR", 2, ["gate_error"]))
        self.assertIn("spec.toml", s["message"])
        self.assertEqual((s["commit"], s["tests_exit_code"], s["spec_sha256"]), (None, None, None))
        self.assertIsNone(s["evidence"])
        self.assertNotIn("gate.md", s["files"])

    def test_gate_json_evidence_lists_regular_files_sorted(self):
        """evidence перечисляет обычные файлы out/*.jsonl по имени."""
        def two_files(target: str) -> str:
            return (f"mkdir -p {target}\n"
                    f"cat > {target}/b.jsonl <<'JSONL'\n{self.record}\nJSONL\n"
                    f"cat > {target}/a.jsonl <<'JSONL'\n{self.record}\nJSONL\n")

        p = self.gate(two_files('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([e["file"] for e in self.gate_json()["evidence"]], ["a.jsonl", "b.jsonl"])

        p = self.gate(two_files('"$OUT_DIR"') + 'mkdir -p "$OUT_DIR/x.jsonl"\n')
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        s = self.gate_json()
        self.assertEqual(s["result"], "ERROR")
        # macOS awk пропускает каталог, и чекер падает на чтении (evidence перечислен);
        # mawk в Debian может упасть на склейке до чекера (evidence — null).
        # Главное — итог не пропадает.
        self.assertTrue(s["evidence"] is None
                        or [e["file"] for e in s["evidence"]] == ["a.jsonl", "b.jsonl"])

    def test_installation_identity_covers_runtime_modules_and_gate_helpers(self):
        import json
        import shutil
        info = json.loads(subprocess.check_output([str(self.bin / "ebt-gate"), "--installation"]))
        package = self.clone.parent / "identity-package"
        shutil.copytree(info["package"], package)
        code = ("import importlib.util,json,sys; "
                "s=importlib.util.spec_from_file_location('identity_cli',sys.argv[1]); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "print(json.dumps(m.installation()))")
        def identity():
            return json.loads(subprocess.check_output([str(self.bin / "python"), "-I", "-c", code,
                                                       str(package / "cli.py")]))
        before = identity()
        module = package / "checker" / "new_runtime.py"
        module.write_text("VALUE = 1\n")
        after = identity()
        self.assertNotEqual(before["checker_sha256"], after["checker_sha256"])
        module.rename(module.with_name("renamed_runtime.py"))
        self.assertNotEqual(after["checker_sha256"], identity()["checker_sha256"])
        module.with_name("renamed_runtime.py").unlink()
        (package / "api.py").write_text("PUBLIC_VALUE = 1\n")
        self.assertNotEqual(before["checker_sha256"], identity()["checker_sha256"])
        (package / "checker" / "test_ignored.py").write_text("not runtime\n")
        stable = identity()
        (package / "checker" / "test_ignored.py").write_text("still not runtime\n")
        self.assertEqual(stable["checker_sha256"], identity()["checker_sha256"])
        # Заготовка — данные для нового проекта, а не код проверки: её правка не должна
        # менять удостоверение установленного гейта.
        scaffold_spec = package / "resources" / "scaffold" / "spec.toml"
        scaffold_spec.write_text(scaffold_spec.read_text(encoding="utf-8") + "\n# data change\n",
                                 encoding="utf-8")
        self.assertEqual(before["gate_sha256"], identity()["gate_sha256"])
        self.assertEqual(stable["checker_sha256"], identity()["checker_sha256"])
        helper = package / "runners" / "flutter.sh"
        helper.write_text(helper.read_text() + "\n# identity change\n")
        self.assertNotEqual(before["gate_sha256"], identity()["gate_sha256"])
        self.assertEqual(stable["checker_sha256"], identity()["checker_sha256"])

    def test_scaffold_creates_ebt_for_each_stack(self):
        expected = {
            "dart": ("lib/ebt/ebt.dart", "lib/ebt/ebt.dart"),
            "ts": ("lib/ebt/ebt.ts", "src/lib/ebt/ebt.ts"),
            "jvm": ("lib/ebt/Ebt.java", "src/test/java/ebt/Ebt.java"),
        }
        env = {**os.environ, "PYTHONPATH": ""}
        files = {"spec.toml", "checks.py", "test_checks.py", "README.md", "test.sh", "pinned.txt"}
        for stack, (sdk, destination) in expected.items():
            with self.subTest(stack=stack):
                target = self.clone.parent / f"scaffold-{stack}"
                p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", stack, str(target)],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual({path.name for path in target.iterdir()}, files)
                self.assertTrue(os.access(target / "test.sh", os.X_OK), "test.sh не исполняемый")
                self.assertEqual(subprocess.run(["/bin/bash", "-n", str(target / "test.sh")],
                                                capture_output=True).returncode, 0)

                spec = tomllib.loads((target / "spec.toml").read_text(encoding="utf-8"))
                self.assertIn("REQ-EXAMPLE-1", spec["req"])
                self.assertEqual(spec["inv"]["INV-EXAMPLE-1"]["checker"], "example_rule")
                self.assertIn("example_rule", (target / "checks.py").read_text(encoding="utf-8"))
                self.assertIn(f"kit:{sdk}  {destination}", (target / "pinned.txt").read_text(encoding="utf-8"))

                # Договор test.sh: без OUT_DIR — ошибка исполнения, а не «тесты упали».
                p = subprocess.run([str(target / "test.sh")], cwd=target, capture_output=True, text=True,
                                   env={k: v for k, v in os.environ.items() if k != "OUT_DIR"})
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

                # Пример чекера и его тесты — рабочие, а не комментарии. Инструкция
                # должна запускать интерпретатор поставки: системный python3 пакет
                # ebt_verification не видит.
                for name in ("test_checks.py", "README.md"):
                    self.assertIn("ebt-gate --installation", (target / name).read_text(encoding="utf-8"))
                shell = """
python=$(ebt-gate --installation | python3 -c 'import json, sys; print(json.load(sys.stdin)["python"])')
"$python" -m unittest discover -s . -p 'test_checks.py'
"""
                p = subprocess.run(["/bin/bash", "-c", shell], cwd=target, capture_output=True, text=True,
                                   env={**env, "PATH": f"{self.bin}:{os.environ['PATH']}"})
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

                # Заготовка самосогласована: spec, checks.py и self-test дают PASS.
                evidence = target / "evidence.jsonl"
                evidence.write_text(
                    '{"seq":1,"req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,'
                    '"data":{"value":5,"result":10}}\n'
                    '{"seq":2,"req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,'
                    '"data":{"value":0,"result":0}}\n'
                    '{"seq":3,"req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,'
                    '"data":{"value":-3,"result":-6}}\n', encoding="utf-8")
                p = subprocess.run([str(self.bin / "ebt-check"), "--spec", str(target / "spec.toml"),
                                    "--checkers", str(target / "checks.py"), "--evidence", str(evidence),
                                    "--self-test"], capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_scaffold_refuses_existing_files_and_unknown_stack(self):
        env = {**os.environ, "PYTHONPATH": ""}
        target = self.clone.parent / "scaffold-existing"
        target.mkdir()
        approved = target / "spec.toml"
        approved.write_text("# утверждённая спецификация\n", encoding="utf-8")
        p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", "ts", str(target)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("не пуст", p.stderr)
        self.assertEqual(approved.read_text(encoding="utf-8"), "# утверждённая спецификация\n")

        missing = self.clone.parent / "scaffold-unknown"
        p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", "ruby", str(missing)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage:", p.stderr)
        self.assertFalse(missing.exists())

        p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

        # Каталог по умолчанию — ebt в текущем каталоге.
        default = self.clone.parent / "scaffold-default"
        default.mkdir()
        p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", "ts"], cwd=default,
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((default / "ebt" / "spec.toml").is_file())

    def test_scaffold_accepts_current_directory(self):
        """`.` — текущий пустой каталог; раньше он удалялся как временный и падал."""
        env = {**os.environ, "PYTHONPATH": ""}
        dot = self.clone.parent / "scaffold-dot"
        dot.mkdir()
        p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", "ts", "."], cwd=dot,
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((dot / "spec.toml").is_file())
        self.assertTrue((dot / "test.sh").is_file())
        self.assertFalse((dot / "ebt").exists())

    def test_scaffold_test_scripts_follow_gate_contract(self):
        """Шаблон test.sh: аргументы EBT_TESTS, OUT_DIR, коды 0/1/2 и свидетельства при любом исходе."""
        env = {**os.environ, "PYTHONPATH": ""}
        fake_body = """#!/bin/bash
mkdir -p build/ebt
printf '%s\\n' "$*" > command.args
printf '%s\\n' '{"seq":1}' > build/ebt/a.jsonl
exit "${FAKE_RC:-0}"
"""
        for stack, command in (("dart", "flutter"), ("ts", "bunx")):
            with self.subTest(stack=stack):
                project = self.clone.parent / f"run-{stack}"
                target = project / "ebt"
                p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", stack, str(target)],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                bin_dir = project / "bin"
                bin_dir.mkdir()
                fake = bin_dir / command
                fake.write_text(fake_body, encoding="utf-8")
                fake.chmod(0o755)
                path_env = {**env, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

                def run_tests(rc, name):
                    out = project / name
                    out.mkdir()
                    return subprocess.run([str(target / "test.sh"), "one", "two"], cwd=project,
                                          capture_output=True, text=True,
                                          env={**path_env, "OUT_DIR": str(out), "FAKE_RC": str(rc)}), out

                p, out = run_tests(0, "out")
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue((out / "a.jsonl").is_file())
                args = (project / "command.args").read_text(encoding="utf-8").strip()
                self.assertIn("one two", args)
                self.assertIn("--no-pub" if stack == "dart" else "run", args)

                p, out = run_tests(1, "out-failed")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertTrue((out / "a.jsonl").is_file())

                p, _ = run_tests(2, "out-error")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

        project = self.clone.parent / "run-jvm"
        target = project / "ebt"
        p = subprocess.run([str(self.bin / "ebt-gate"), "--scaffold", "jvm", str(target)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        gradlew = project / "gradlew"
        gradlew.write_text("""#!/bin/bash
mkdir -p build/ebt build/test-results/test
printf '%s\\n' "$*" > command.args
printf '%s\\n' '{"seq":1}' > build/ebt/a.jsonl
if [ "${FAKE_XML:-1}" = 1 ]; then
  printf '%s\\n' '<testsuite failures="1" errors="0"></testsuite>' > build/test-results/test/TEST-a.xml
fi
case ${FAKE_RC:-0} in
  1) echo "There were failing tests"; exit 1 ;;
  2) echo "Build completed with"; exit 1 ;;
  3) exit 1 ;;
esac
exit 0
""", encoding="utf-8")
        gradlew.chmod(0o755)

        def run_gradle(rc, name, xml=True):
            out = project / name
            out.mkdir()
            return subprocess.run([str(target / "test.sh")], cwd=project, capture_output=True, text=True,
                                  env={**env, "OUT_DIR": str(out), "FAKE_RC": str(rc),
                                       "FAKE_XML": "1" if xml else "0"}), out

        p, out = run_gradle(0, "out")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((out / "a.jsonl").is_file())
        self.assertIn("--tests *EbtTest", (project / "command.args").read_text(encoding="utf-8"))
        p, out = run_gradle(1, "out-failed")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertTrue((out / "a.jsonl").is_file())
        p, _ = run_gradle(2, "out-compile-error")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p, _ = run_gradle(3, "out-ambiguous")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

        # Нет XML: старый grep без файлов читал stdin и мог зависнуть. Держим stdin
        # открытым и ждём: шаблон обязан вернуть 2, не дожидаясь закрытия stdin.
        out = project / "out-no-xml"
        out.mkdir()
        process = subprocess.Popen([str(target / "test.sh")], cwd=project,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env={**env, "OUT_DIR": str(out), "FAKE_RC": "1",
                                                   "FAKE_XML": "0"})
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            self.fail("test.sh завис: grep читал stdin при отсутствии XML-отчётов")
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 2, stdout + stderr)

    def test_matching_checker_by_default_even_if_other_on_path(self):
        fake = self.fake_checker(0)
        self.record = self.record.replace('"result":55870', '"result":1')  # нарушение правила
        env = {"PATH": f"{fake.parent}:{os.environ['PATH']}"}
        p = self.gate(self.write_to('"$OUT_DIR"'), env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("ebt-verification 0.3.1", self.gate_md())
        self.assertIn(str(self.bin.parent), self.gate_md())

    def test_project_cannot_shadow_bundled_checker_package(self):
        poison = self.clone / "ebt_verification"
        poison.mkdir()
        (poison / "__init__.py").write_text("raise RuntimeError('wrong checker from project cwd')")
        subprocess.run(["git", "-C", str(self.clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "name collision"], check=True)
        self.record = self.record.replace('"result":55870', '"result":1')
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("Ложное доказательство", (self.run_dir / "report.md").read_text())

    def test_installed_checker_only_on_request(self):
        fake = self.fake_checker(0)
        self.record = self.record.replace('"result":55870', '"result":1')
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ebt-check 9.9.9", self.gate_md())

    def test_relative_explicit_checker_is_resolved_before_chdir(self):
        fake = self.fake_checker(0)
        self.record = self.record.replace('"result":55870', '"result":1')
        relative = os.path.relpath(fake, Path.cwd())
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": relative})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ebt-check 9.9.9", self.gate_md())

    def test_out_dir_evidence_passes(self):
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("зелёный", self.gate_md())
        self.assertTrue((self.run_dir / "out" / "a.jsonl").exists())

    def test_legacy_build_ebt_bridge_passes(self):
        p = self.gate(self.write_to("build/ebt"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_stale_build_ebt_is_not_evidence(self):
        (self.clone / "build" / "ebt").mkdir(parents=True)
        (self.clone / "build" / "ebt" / "old.jsonl").write_text(self.record, encoding="utf-8")
        p = self.gate("exit 0\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_stale_out_dir_is_not_evidence(self):
        (self.run_dir / "out").mkdir(parents=True)
        (self.run_dir / "out" / "old.jsonl").write_text(self.record, encoding="utf-8")
        p = self.gate("exit 0\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_failed_tests_with_evidence_are_red(self):
        p = self.gate(self.write_to('"$OUT_DIR"') + "exit 1\n")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("красный", self.gate_md())

    def test_runner_error_with_evidence_is_error(self):
        # Свидетельства через мост build/ebt: так случай проверяется и на гейте без OUT_DIR.
        p = self.gate(self.write_to("build/ebt") + "exit 2\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertNotIn("зелёный", self.gate_md())

    def test_runner_error_without_evidence_is_error(self):
        p = self.gate("exit 2\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_rerun_does_not_keep_old_green(self):
        first = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.gate("exit 0\n")
        self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
        self.assertNotIn("зелёный", self.gate_md())
        self.assertFalse((self.run_dir / "report.md").exists())

    def test_checker_crash_is_normalized_to_error(self):
        fake = self.fake_checker(0)
        fake.write_text('#!/bin/bash\nif [ "$1" = --version ]; then echo crash-checker; exit 0; fi\nexit 17\n')
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_seq_boundaries_are_preserved(self):
        # Два файла с seq=1 корректны; склейка как вход дала бы LOG_GAP.
        script = self.write_to('"$OUT_DIR"') + 'cp "$OUT_DIR/a.jsonl" "$OUT_DIR/b.jsonl"\n'
        p = self.gate(script)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("логов склеено: 2", self.gate_md())

    def test_missing_bundle_clears_old_green(self):
        self.assertEqual(self.gate(self.write_to('"$OUT_DIR"')).returncode, 0)
        p = subprocess.run([str(self.bin / "ebt-gate"), str(self.ebt / "missing"),
                            str(self.clone), str(self.run_dir)], capture_output=True)
        self.assertEqual(p.returncode, 2)
        self.assertFalse((self.run_dir / "report.md").exists())
        self.assertFalse((self.run_dir / "gate.md").exists())

    def test_pinned_uses_installed_resource_and_detects_drift(self):
        import json
        info = json.loads(subprocess.check_output([str(self.bin / "ebt-gate"), "--installation"]))
        original = Path(info["resources"]) / "lib/ebt/Ebt.java"
        (self.clone / "Ebt.java").write_bytes(original.read_bytes())
        (self.ebt / "pinned.txt").write_text("kit:lib/ebt/Ebt.java Ebt.java")
        subprocess.run(["git", "-C", str(self.clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "pin"], check=True)
        self.assertEqual(self.gate(self.write_to('"$OUT_DIR"')).returncode, 0)
        (self.clone / "Ebt.java").write_text("drift")
        subprocess.run(["git", "-C", str(self.clone), "commit", "-qam", "drift",
                        "--author=t <t@t>"], check=True,
                       env={**os.environ, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("Закреплённые копии отличаются", self.gate_md())

    def test_artifact_has_sdk_fixture_and_no_role_prompts(self):
        import zipfile
        with zipfile.ZipFile(self.wheel) as wheel:
            names = wheel.namelist()
        for name in ("Ebt.java", "ebt.dart", "ebt.ts"):
            self.assertIn(f"ebt_verification/resources/lib/ebt/{name}", names)
        for name in ("README.md", "spec.toml", "checks.py", "test_checks.py",
                     "dart/test.sh", "dart/pinned.txt", "ts/test.sh", "ts/pinned.txt",
                     "jvm/test.sh", "jvm/pinned.txt"):
            self.assertIn(f"ebt_verification/resources/scaffold/{name}", names)
        self.assertIn("ebt_verification/checker/fixtures/record.jsonl", names)
        self.assertFalse(any("prompts/" in p or p.endswith(("roles.toml", "run_role.py")) for p in names))

    def test_dirty_checkout_and_hidden_edits_are_errors(self):
        (self.clone / "untracked").write_text("dirty")
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        (self.clone / "untracked").unlink()
        subprocess.run(["git", "-C", str(self.clone), "update-index", "--assume-unchanged", ".gitignore"], check=True)
        (self.clone / ".gitignore").write_text("hidden edit")
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("assume-unchanged", p.stderr)

    def test_base_protects_project_verification_paths(self):
        base = subprocess.check_output(["git", "-C", str(self.clone), "rev-parse", "HEAD"], text=True).strip()
        (self.clone / "ebt").mkdir()
        (self.clone / "ebt/changed").write_text("protected")
        subprocess.run(["git", "-C", str(self.clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "protected edit"], check=True)
        p = self.gate(self.write_to('"$OUT_DIR"'), {"BASE": base})
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("В ветке приложения изменены", self.gate_md())

    def test_runner_cannot_change_verification_inputs(self):
        """Код проекта исполняется с правами гейта: правка входов за прогон — ERROR, чекер читает снимок."""
        cases = {"spec.toml": 'echo "# changed" >> "$(dirname "$0")/spec.toml"\n',
                 "checks.py": 'echo "CHECKERS = {}" > "$(dirname "$0")/checks.py"\n'}
        for name, edit in cases.items():
            with self.subTest(name=name):
                p = self.gate(self.write_to('"$OUT_DIR"') + edit)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                s = self.gate_json()
                self.assertEqual((s["result"], s["reasons"]), ("ERROR", ["gate_error"]))
                self.assertIn(f"изменены во время прогона: {name}", s["message"])
                self.assertEqual((self.run_dir / "inputs/spec.toml").read_text(encoding="utf-8"), SPEC)
                (self.ebt / "spec.toml").write_text(SPEC, encoding="utf-8")
                (self.ebt / "checks.py").unlink(missing_ok=True)

    def test_runner_cannot_change_installed_verifier(self):
        import json
        env = {**os.environ, "PYTHONPATH": ""}  # make test-gate задаёт PYTHONPATH=src: нужен установленный пакет
        info = json.loads(subprocess.check_output([str(self.bin / "ebt-gate"), "--installation"], env=env))
        self.assertIn("site-packages", info["package"])
        target = Path(info["package"]) / "checker" / "checkers.py"
        self.addCleanup(target.write_bytes, target.read_bytes())
        p = self.gate(self.write_to('"$OUT_DIR"') + f'echo "# changed" >> "{target}"\n')
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(self.gate_json()["result"], "ERROR")
        self.assertIn("код поставки изменён во время прогона", self.gate_json()["message"])

    def test_installed_gate_without_source_access(self):
        import sys
        if sys.platform != "darwin":
            self.skipTest("Проверка sandbox-exec требует macOS; используйте контейнер на других ОС")
        source = KIT
        policy = f'(version 1)(allow default)(deny file-read* (subpath "{source}"))'
        prefix = ["/usr/bin/sandbox-exec", "-p", policy]
        probe = subprocess.run(prefix + ["/bin/cat", str(source / "README.md")],
                               capture_output=True, text=True, cwd=self.clone.parent)
        if "sandbox_apply" in probe.stderr:
            self.skipTest("Системная песочница недоступна внутри внешней песочницы процесса")
        self.assertNotEqual(probe.returncode, 0, "Исходники репозитория доступны")
        self.assertIn("Operation not permitted", probe.stderr)
        (self.ebt / "spec.toml").write_text(SPEC.replace('"cart_total"', '"project_cart"'))
        (self.ebt / "checks.py").write_text(
            'from checkers import Verdict, WitnessError\n'
            'from ebt_verification.checker.checkers import cart_total, Verdict as InstalledVerdict\n'
            'assert Verdict is InstalledVerdict\n'
            'CHECKERS = {"project_cart": cart_total}\n')
        self.gate(self.write_to('"$OUT_DIR"'))  # Сохранить проектные входы до запрета исходников.
        env = {**os.environ, "PYTHONPATH": "", "BASE": "", "EBT_CHECK": ""}
        p = subprocess.run(prefix + [str(self.bin / "ebt-gate"), str(self.ebt), str(self.clone),
                                     str(self.run_dir)], capture_output=True, text=True,
                           cwd=self.clone.parent, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ebt-verification 0.3.1", self.gate_md())


if __name__ == "__main__":
    unittest.main()
