"""Tests of gate.sh, the witnessbox command and the ebt/ scaffold: the contract with the project test.sh
(OUT_DIR, codes), evidence freshness, the attempt result, the spec/test.sh/pinned.txt templates
and `scaffold`.

python3 -m unittest discover -s tests
"""

import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from tests._verification_test_support import install_verification
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
FIXTURE = KIT / "src/witnessbox/checker/fixtures/record.jsonl"
VERSION = tomllib.loads((KIT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

SPEC = """[req.REQ-CART-1]
text = "Cart total = sum of lines minus the discount."

[inv.INV-CART-3]
req = "REQ-CART-1"
checker = "cart_total"
witness = ["lines", "discount", "subtotal", "off", "result"]
partitions = ["no_discount"]
"""


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install_tmp, cls.bin, cls.wheel, cls.sdist = install_verification()
        cls.addClassCleanup(cls.install_tmp.cleanup)

    def setUp(self):
        self.new_project()

    def new_project(self):
        """A fresh project: a separate clone and checks directory for an independent case."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.clone, self.ebt, self.run_dir = root / "clone", root / "ebt", root / "run"
        self.clone.mkdir()
        self.ebt.mkdir()
        (self.ebt / "spec.toml").write_text(SPEC, encoding="utf-8")
        (self.clone / ".gitignore").write_text("build/\n")
        # commit runs `git maintenance run --auto --detach` in the background: its maintenance.lock
        # races with the clone rmtree in the problem_cases cases and fails the test (macOS CI).
        git = ["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
               "-c", "maintenance.auto=false"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        self.record = FIXTURE.read_text(encoding="utf-8")

    def gate(self, test_sh: str | None, env: dict | None = None) -> subprocess.CompletedProcess:
        script = self.ebt / "test.sh"
        if test_sh is not None:
            script.write_text("#!/bin/bash\nset -u\n" + test_sh, encoding="utf-8")
            script.chmod(0o755)
        return subprocess.run([str(self.bin / "witnessbox"), "gate", str(self.ebt), str(self.clone), str(self.run_dir)],
                              capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "", "BASE": "", "EBT_RUNNER": "", "EBT_CHECK": "", "EBT_INV": "", **(env or {})})

    def write_to(self, target: str) -> str:
        return f"mkdir -p {target}\ncat > {target}/a.jsonl <<'JSONL'\n{self.record}\nJSONL\n"

    def gate_md(self) -> str:
        path = self.run_dir / "gate.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def gate_json(self) -> dict:
        import json
        return json.loads((self.run_dir / "gate.json").read_text(encoding="utf-8"))

    def sync_pinned(self, ebt: Path, root: Path | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.bin / "witnessbox"), "sync-pinned", str(ebt), *([str(root)] if root else [])],
            cwd=cwd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})

    def fake_checker(self, rc: int) -> Path:
        """A fake checker on PATH: always answers with code rc."""
        bin_dir = self.run_dir.parent / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "fake-check"
        fake.write_text(f"#!/bin/bash\necho 'fake-check 9.9.9'\nexit {rc}\n", encoding="utf-8")
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

    def check_only(self, env: dict | None = None, *paths: str) -> subprocess.CompletedProcess:
        argv = [str(self.bin / "witnessbox"), "gate", "--check-only", *(paths or (str(self.ebt), str(self.clone)))]
        base = {**os.environ, "PYTHONPATH": "", "BASE": "", "EBT_RUNNER": "",
                "EBT_CHECK": "", "EBT_INV": ""}
        return subprocess.run(argv, capture_output=True, text=True, env={**base, **(env or {})})

    def run_test_checks(self, *paths, cwd: Path | None = None,
                    env: dict | None = None) -> subprocess.CompletedProcess:
        argv = [str(self.bin / "witnessbox"), "test-checks", *map(str, paths)]
        base = {**os.environ, "PYTHONPATH": "", "PATH": os.environ["PATH"]}
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env={**base, **(env or {})})

    def commit_clone(self, message: str) -> str:
        subprocess.run(["git", "-C", str(self.clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", message], check=True)
        return subprocess.check_output(["git", "-C", str(self.clone), "rev-parse", "HEAD"], text=True).strip()

    def case_unknown_checker(self) -> dict:
        (self.ebt / "spec.toml").write_text(SPEC.replace('"cart_total"', '"missing_rule"'), encoding="utf-8")
        return {}

    def case_broken_checks(self) -> dict:
        (self.ebt / "checks.py").write_text('raise RuntimeError("boom")\n', encoding="utf-8")
        return {}

    def case_core_checker(self) -> dict:
        (self.ebt / "checks.py").write_text(
            "from witnessbox.checker.checkers import cart_total\nCHECKERS = {'cart_total': cart_total}\n",
            encoding="utf-8")
        return {}

    def case_non_executable_test_sh(self) -> dict:
        script = self.ebt / "test.sh"
        script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o644)
        return {}

    def case_pinned_drift(self) -> dict:
        (self.clone / "Ebt.java").write_text("drift", encoding="utf-8")
        (self.ebt / "pinned.txt").write_text("kit:lib/ebt/Ebt.java  Ebt.java\n", encoding="utf-8")
        self.commit_clone("pinned copy")
        return {}

    def case_dirty_clone(self) -> dict:
        (self.clone / "untracked").write_text("dirty", encoding="utf-8")
        return {}

    def case_hidden_edit(self) -> dict:
        subprocess.run(["git", "-C", str(self.clone), "update-index", "--skip-worktree", ".gitignore"],
                       check=True)
        return {}

    def case_base_changed(self) -> dict:
        (self.clone / "ebt").mkdir()
        marker = self.clone / "ebt/marker"
        marker.write_text("before BASE", encoding="utf-8")
        base = self.commit_clone("ebt/marker in BASE")
        marker.write_text("after BASE", encoding="utf-8")
        self.commit_clone("change of the protected ebt/")
        return {"BASE": base}

    def case_unknown_checker_out_of_scope(self) -> dict:
        extra = ('\n[inv.INV-OUT]\nreq = "REQ-CART-1"\nchecker = "missing_rule"\n'
                 'witness = ["a"]\n')
        (self.ebt / "spec.toml").write_text(SPEC + extra, encoding="utf-8")
        return {"EBT_INV": "INV-CART-3"}

    def case_missing_ebt_check(self) -> dict:
        return {"EBT_CHECK": "no-such-checker"}

    def case_unknown_ebt_inv(self) -> dict:
        return {"EBT_INV": "INV-NOPE"}

    def case_no_commits(self) -> dict:
        shutil.rmtree(self.clone)
        self.clone.mkdir()
        subprocess.run(["git", "-C", str(self.clone), "init", "-q"], check=True)
        # An untracked file, as in a fresh project: the cause is the absence of commits, not a dirty tree.
        (self.clone / ".gitignore").write_text("build/\n")
        return {}

    def problem_cases(self):
        return {
            "checks: unknown checker": (self.case_unknown_checker, "checks"),
            "checks: EBT_CHECK not found": (self.case_missing_ebt_check, "checks"),
            "checks: checks.py crashes": (self.case_broken_checks, "checks"),
            "checks: core checker name": (self.case_core_checker, "checks"),
            "spec: unknown EBT_INV": (self.case_unknown_ebt_inv, "spec"),
            "runner: test.sh is not executable": (self.case_non_executable_test_sh, "runner"),
            "pinned: drift": (self.case_pinned_drift, "pinned"),
            "clone: dirty tree": (self.case_dirty_clone, "clone"),
            "clone: skip-worktree": (self.case_hidden_edit, "clone"),
            "clone: repository without commits": (self.case_no_commits, "clone"),
            "base: ebt/ changed": (self.case_base_changed, "base"),
        }

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
                self.assertEqual("Compatibility:" in p.stderr, not selection)

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
        # The build/ebt bridge is copied to out/: evidence lists what the checker read.
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
        self.assertIn("the package contains test.sh", p.stderr)

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
        self.assertIn("after the tests", p.stderr)

    def test_output_io_failures_never_pass(self):
        for filename in ("gate.md", "gate.json", "evidence.jsonl", "ebt-check.err", "report.md", "report.json"):
            with self.subTest(filename=filename):
                # Created during execution: initial cleanup cannot detect this failure.
                script = self.write_to('"$OUT_DIR"') + f'mkdir "$(dirname "$OUT_DIR")/{filename}"\n'
                p = self.gate(script)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertNotIn("green", self.gate_md() if (self.run_dir / "gate.md").is_file() else "")
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
        self.assertIn("could not open test.log", p.stderr)

    def test_tracked_runner_changes_are_stashed(self):
        p = self.gate(self.write_to('"$OUT_DIR"') + 'echo changed > .gitignore\n')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((self.clone / ".gitignore").read_text(), "build/\n")
        stash = subprocess.check_output(["git", "-C", str(self.clone), "stash", "list"], text=True)
        self.assertIn("witnessbox gate: changes from run", stash)

    def test_stash_failure_cannot_publish_pass(self):
        import shutil
        real_git = shutil.which("git")
        git = self.fake_command("git", f'case " $* " in *" stash push "*) exit 37;; esac\nexec "{real_git}" "$@"\n')
        p = self.gate(self.write_to('"$OUT_DIR"'), self.command_env(git))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertNotIn("green", p.stdout)
        self.assertFalse((self.run_dir / "gate.md").exists())
        self.assertEqual(self.gate_json()["result"], "ERROR")
        self.assertIn("git stash", self.gate_json()["message"])

    def test_gate_json_and_report_json_contract(self):
        """Supported machine-readable results: gate.json of the gate and report.json of the checker."""
        import json
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        s = self.gate_json()
        self.assertEqual((s["format"], s["result"], s["exit_code"], s["reasons"]), (1, "PASS", 0, []))
        self.assertEqual((s["tests_exit_code"], s["checker_exit_code"], s["message"]), (0, 0, None))
        head = subprocess.check_output(["git", "-C", str(self.clone), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(s["commit"], head)
        self.assertEqual((s["verifier"]["distribution"], s["verifier"]["version"]), ("witnessbox", VERSION))
        self.assertRegex(s["verifier"]["gate_sha256"], "^[0-9a-f]{64}$")
        self.assertRegex(s["checker"]["sha256"], "^[0-9a-f]{64}$")
        self.assertRegex(s["spec_sha256"], "^[0-9a-f]{64}$")
        self.assertLessEqual({"gate.md", "report.md", "report.json", "evidence.jsonl", "out",
                              "test.log", "installation.json", "inputs", "spec.html"}, set(s["files"]))
        # The review page of the checked spec copy carries the same sha256 as gate.json (D58).
        self.assertIn(s["spec_sha256"][12:], (self.run_dir / "spec.html").read_text(encoding="utf-8"))
        self.assertIn("page: [spec.html](spec.html)", self.gate_md())
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

    def test_gate_without_spec_page_when_spec_does_not_parse(self):
        """A spec the checker rejects has no page; the gate stays ERROR and gate.md says the page is missing."""
        (self.ebt / "spec.toml").write_text(SPEC.replace('req = "REQ-CART-1"', 'req = "REQ-NONE"'),
                                            encoding="utf-8")
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(self.gate_json()["reasons"], ["checker_error"])
        self.assertFalse((self.run_dir / "spec.html").exists())
        self.assertNotIn("spec.html", self.gate_json()["files"])
        self.assertIn("page: not built: spec.toml does not parse", self.gate_md())

    def test_gate_json_evidence_lists_regular_files_sorted(self):
        """evidence lists the regular out/*.jsonl files by name."""
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
        # macOS awk skips the directory, and the checker fails on reading (evidence is listed);
        # mawk on Debian may fail at the concatenation before the checker (evidence is null).
        # The main thing is that the result does not vanish.
        self.assertTrue(s["evidence"] is None
                        or [e["file"] for e in s["evidence"]] == ["a.jsonl", "b.jsonl"])

    def test_installation_identity_covers_shipped_code_and_gate_helpers(self):
        """The fingerprint covers all shipped .py/.sh; scaffold is data, cli.py is the gate."""
        info = self.installation()
        package = Path(info["package"])
        compat = package.parent / "ebt_verification"
        before = info
        for target in (package / "__init__.py",
                       package / "checker" / "checkers.py",
                       package / "api.py",
                       package.parent / "checkers.py",
                       package.parent / "ebt_check.py",
                       compat / "__init__.py",
                       compat / "api.py"):
            with self.subTest(file=target.relative_to(package.parent).as_posix()):
                original = target.read_bytes()
                try:
                    target.write_bytes(original + b"# identity change\n")
                    changed = self.installation()
                    self.assertNotEqual(before["checker_sha256"], changed["checker_sha256"])
                    self.assertEqual(before["gate_sha256"], changed["gate_sha256"])
                finally:
                    target.write_bytes(original)
        self.assertEqual(before["checker_sha256"], self.installation()["checker_sha256"])
        # cli.py is gate code, not checker code: it goes only into gate_sha256.
        cli = package / "cli.py"
        original = cli.read_bytes()
        try:
            cli.write_bytes(original + b"# identity change\n")
            changed = self.installation()
            self.assertEqual(before["checker_sha256"], changed["checker_sha256"])
            self.assertNotEqual(before["gate_sha256"], changed["gate_sha256"])
        finally:
            cli.write_bytes(original)
        self.assertEqual(before["gate_sha256"], self.installation()["gate_sha256"])
        # The scaffold is data for a new project, not checking code: editing it must not
        # change the identity of the installed gate.
        scaffold_spec = package / "resources" / "scaffold" / "spec.toml"
        original = scaffold_spec.read_bytes()
        try:
            scaffold_spec.write_bytes(original + b"\n# data change\n")
            changed = self.installation()
            self.assertEqual(before["gate_sha256"], changed["gate_sha256"])
            self.assertEqual(before["checker_sha256"], changed["checker_sha256"])
        finally:
            scaffold_spec.write_bytes(original)
        helper = package / "runners" / "flutter.sh"
        original = helper.read_bytes()
        try:
            helper.write_bytes(original + b"\n# identity change\n")
            changed = self.installation()
            self.assertNotEqual(before["gate_sha256"], changed["gate_sha256"])
            self.assertEqual(before["checker_sha256"], changed["checker_sha256"])
        finally:
            helper.write_bytes(original)

    def test_installation_falls_back_when_record_lacks_package_files(self):
        """Editable/PYTHONPATH: RECORD without witnessbox/ means the fingerprint is built by a tree walk."""
        import hashlib
        import json
        import shutil
        import sys
        root = self.clone.parent / "source-install"
        tree = root / "src"
        shutil.copytree(KIT / "src", tree,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
        site = root / "site-packages"
        dist_info = site / f"witnessbox-{VERSION}.dist-info"
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: witnessbox\nVersion: {VERSION}\n", encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": f"{site}{os.pathsep}{tree}"}
        env.pop("PYTHONHOME", None)

        def installation():
            p = subprocess.run([sys.executable, "-m", "witnessbox.cli", "--installation"], cwd=root,
                               capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            return json.loads(p.stdout)

        empty = hashlib.sha256(b"").hexdigest()
        for record in ("", f"__editable__.witnessbox.pth,,\n"):
            with self.subTest(record=record or "empty"):
                (dist_info / "RECORD").write_text(record, encoding="utf-8")
                info = installation()
                self.assertEqual((info["distribution"], info["version"]), ("witnessbox", VERSION))
                self.assertEqual(Path(info["package"]), (tree / "witnessbox").resolve())
                self.assertNotEqual(info["checker_sha256"], empty)
                self.assertNotEqual(info["gate_sha256"], empty)
                # The tree walk covers exactly the same as the RECORD of an installed wheel.
                installed_info = self.installation()
                self.assertEqual(info["checker_sha256"], installed_info["checker_sha256"])
                self.assertEqual(info["gate_sha256"], installed_info["gate_sha256"])

                checker = tree / "witnessbox" / "checker" / "checkers.py"
                original = checker.read_bytes()
                try:
                    checker.write_bytes(original + b"# source change\n")
                    changed = installation()
                    self.assertNotEqual(info["checker_sha256"], changed["checker_sha256"])
                    self.assertEqual(info["gate_sha256"], changed["gate_sha256"])
                finally:
                    checker.write_bytes(original)

                gate = tree / "witnessbox" / "gate.sh"
                original = gate.read_bytes()
                try:
                    gate.write_bytes(original + b"\n# source change\n")
                    changed = installation()
                    self.assertNotEqual(info["gate_sha256"], changed["gate_sha256"])
                    self.assertEqual(info["checker_sha256"], changed["checker_sha256"])
                finally:
                    gate.write_bytes(original)

    def test_installation_falls_back_when_metadata_describes_another_install(self):
        """PYTHONPATH=src without egg-info next to a wheel: RECORD describes another installation."""
        import hashlib
        import json
        import shutil
        root = self.clone.parent / "shadowed-install"
        tree = root / "src"
        shutil.copytree(KIT / "src", tree,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
        env = {**os.environ, "PYTHONPATH": str(tree)}
        env.pop("PYTHONHOME", None)
        p = subprocess.run([str(self.bin / "python"), "-m", "witnessbox.cli", "--installation"],
                           cwd=root, capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        info = json.loads(p.stdout)
        self.assertEqual(Path(info["package"]), (tree / "witnessbox").resolve())
        self.assertNotEqual(info["checker_sha256"], hashlib.sha256(b"").hexdigest())
        self.assertNotEqual(info["gate_sha256"], hashlib.sha256(b"").hexdigest())
        # The code in src is the same as in the wheel: the fingerprints must match.
        installed_info = self.installation()
        self.assertEqual(info["checker_sha256"], installed_info["checker_sha256"])
        self.assertEqual(info["gate_sha256"], installed_info["gate_sha256"])

    def test_installation_refuses_empty_fingerprint(self):
        """An empty file set is an installation error, not a constant SHA of empty input."""
        code = (
            "import witnessbox.cli as cli\n"
            "cli._installed_entries = lambda package, dist: (package.parent, [])\n"
            "try:\n"
            "    cli.installation()\n"
            "except RuntimeError as error:\n"
            "    print(error)\n"
        )
        p = subprocess.run([str(self.bin / "python"), "-I", "-c", code],
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("empty witnessbox code fingerprint", p.stdout)

    def installation(self) -> dict:
        import json
        return json.loads(subprocess.check_output(
            [str(self.bin / "witnessbox"), "--installation"], text=True,
            env={**os.environ, "PYTHONPATH": ""}))

    def test_installation_reports_witnessbox_and_existing_paths(self):
        """--installation describes the installed witnessbox, and its paths exist."""
        info = self.installation()
        self.assertEqual((info["distribution"], info["version"]), ("witnessbox", VERSION))
        for key in ("package", "resources", "python", "checker"):
            self.assertTrue(Path(info[key]).exists(), f"{key}: {info[key]}")
        self.assertEqual(Path(info["python"]).resolve(), (self.bin / "python").resolve())
        self.assertEqual(Path(info["package"]).name, "witnessbox")
        self.assertTrue((Path(info["resources"]) / "lib/ebt/Ebt.java").is_file())
        self.assertTrue((Path(info["package"]) / "gate.sh").is_file())
        self.assertRegex(info["gate_sha256"], "^[0-9a-f]{64}$")
        self.assertRegex(info["checker_sha256"], "^[0-9a-f]{64}$")
        import zipfile
        with zipfile.ZipFile(self.wheel) as wheel:
            metadata = next(wheel.read(name) for name in wheel.namelist()
                            if name.endswith(".dist-info/METADATA"))
        self.assertIn(f"Name: {info['distribution']}\n".encode(), metadata)
        self.assertIn(f"Version: {info['version']}\n".encode(), metadata)

    def test_old_commands_are_not_installed(self):
        for name in ("ebt-gate", "ebt-check"):
            self.assertFalse((self.bin / name).exists(), name)

    def witnessbox(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.bin / "witnessbox"), *args], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": ""})

    def test_usage_without_command(self):
        p = self.witnessbox()
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage: witnessbox <command>", p.stderr)

    def test_help_lists_commands(self):
        p = self.witnessbox("--help")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for command in ("gate", "--check-only", "check", "scaffold", "sync-pinned", "test-checks", "spec"):
            self.assertIn(command, p.stdout)

    def test_subcommand_help_prints_usage(self):
        for command in ("gate", "scaffold", "sync-pinned", "test-checks", "spec"):
            for flag in ("-h", "--help"):
                with self.subTest(command=command, flag=flag):
                    p = self.witnessbox(command, flag)
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    self.assertIn(f"  {command} ", p.stdout)
                    self.assertEqual(p.stderr, "")

    def test_unknown_command_and_old_flags(self):
        for arg in ("frobnicate", "--scaffold", "--check-only"):
            with self.subTest(arg=arg):
                p = self.witnessbox(arg, "ts")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn(f"witnessbox: unknown command {arg}", p.stderr)
                self.assertIn("usage: witnessbox <command>", p.stderr)

    def test_version_and_installation_take_no_arguments(self):
        for flag in ("--version", "--installation"):
            with self.subTest(flag=flag):
                p = self.witnessbox(flag, "extra")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn(f"usage: witnessbox {flag}", p.stderr)
                self.assertNotIn("unknown command", p.stderr)

    def test_spec_page_shows_spec_hash_gaps_and_escapes_text(self):
        """witnessbox spec: the page names the exact file by sha256, marks gaps and escapes the spec text."""
        import hashlib
        spec = self.ebt / "spec.toml"
        spec.write_text(SPEC.replace("minus the discount.", "minus the discount <script>x</script>.")
                        + '\n[req.REQ-PROFILE-1]\ntext = "Name is cut to 64 characters."\n'
                        + 'source = "ticket: PROF-7"\n', encoding="utf-8")
        page = self.run_dir.parent / "spec.html"
        p = self.witnessbox("spec", str(spec), str(page))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        sha = hashlib.sha256(spec.read_bytes()).hexdigest()
        self.assertIn(f"spec.toml sha256 {sha}", p.stdout)
        html = page.read_text(encoding="utf-8")
        self.assertIn(f"<b>{sha[:12]}</b>{sha[12:]}", html)
        for text in ('id="REQ-CART-1"', 'id="INV-CART-3"', "cart_total", "no_discount", "ticket: PROF-7"):
            self.assertIn(text, html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        # REQ-CART-1 has no source, REQ-PROFILE-1 has no invariants.
        self.assertIn('<span class="flag">not given</span>', html)
        self.assertIn('<span class="flag">no invariants</span>', html)

    def test_spec_page_refuses_bad_input(self):
        page = self.run_dir.parent / "spec.html"
        (self.ebt / "bad.toml").write_text("[inv.X]\nreq = 'REQ-NONE'\nchecker = 'c'\nwitness = []\n",
                                           encoding="utf-8")
        cases = {
            "no file": (str(self.ebt / "none.toml"), str(page)),
            "unknown requirement": (str(self.ebt / "bad.toml"), str(page)),
            "one argument": (str(self.ebt / "spec.toml"),),
        }
        for name, args in cases.items():
            with self.subTest(name):
                p = self.witnessbox("spec", *args)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("spec", p.stderr)
                self.assertFalse(page.exists())

    def test_gate_without_args_names_command(self):
        p = self.witnessbox("gate")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage: witnessbox gate <ebt-dir> <clone> <run-dir>", p.stderr)

    def test_check_bad_args_uses_prog(self):
        p = self.witnessbox("check")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage: witnessbox check", p.stderr)

    def test_installed_public_imports_are_identical_without_checkout(self):
        """The distribution works without a checkout and PYTHONPATH; the new and compatible imports are one class."""
        code = (
            "import sys\n"
            "import witnessbox\n"
            "from witnessbox.api import Verdict, WitnessError\n"
            "from ebt_verification.api import Verdict as CompatVerdict\n"
            "from ebt_verification.api import WitnessError as CompatWitnessError\n"
            "from checkers import Verdict as LegacyVerdict\n"
            "assert CompatVerdict is Verdict is LegacyVerdict\n"
            "assert CompatWitnessError is WitnessError\n"
            "assert Verdict.__module__ == 'witnessbox.api'\n"
            "assert 'site-packages' in witnessbox.__file__, witnessbox.__file__\n"
            f"assert {str(KIT / 'src')!r} not in sys.path, sys.path\n"
            "print('ok')\n"
        )
        p = subprocess.run([str(self.bin / "python"), "-I", "-c", code], cwd=self.clone.parent,
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(p.stdout.strip(), "ok")

    def test_checker_cli_runs_from_distribution(self):
        p = subprocess.run([str(self.bin / "witnessbox"), "check", "--version"], capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout.strip(), r"^witnessbox check \d+\.\d+\.\d+$")

    def test_scaffold_creates_ebt_for_each_stack(self):
        expected = {
            "dart": ("lib/ebt/ebt.dart", "lib/ebt/ebt.dart"),
            "ts": ("lib/ebt/ebt.ts", "src/lib/ebt/ebt.ts"),
            "jvm": ("lib/ebt/Ebt.java", "src/test/java/ebt/Ebt.java"),
            # generic does not choose a language: the lines of all three SDKs in pinned.txt are comments.
            "generic": None,
        }
        env = {**os.environ, "PYTHONPATH": ""}
        files = {"spec.toml", "checks.py", "test_checks.py", "README.md", "test.sh", "pinned.txt"}
        for stack, pin in expected.items():
            with self.subTest(stack=stack):
                target = self.clone.parent / f"scaffold-{stack}"
                p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", stack, str(target)],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual({path.name for path in target.iterdir()}, files)
                self.assertTrue(os.access(target / "test.sh", os.X_OK), "test.sh is not executable")
                self.assertEqual(subprocess.run(["/bin/bash", "-n", str(target / "test.sh")],
                                                capture_output=True).returncode, 0)

                spec = tomllib.loads((target / "spec.toml").read_text(encoding="utf-8"))
                self.assertIn("REQ-EXAMPLE-1", spec["req"])
                self.assertEqual(spec["inv"]["INV-EXAMPLE-1"]["checker"], "example_rule")
                self.assertIn("example_rule", (target / "checks.py").read_text(encoding="utf-8"))
                pinned = (target / "pinned.txt").read_text(encoding="utf-8")
                if pin:
                    sdk, destination = pin
                    self.assertIn(f"kit:{sdk}  {destination}", pinned)
                else:
                    # The gate accepts an empty set of lines: all lines are comments.
                    self.assertEqual([line for line in pinned.splitlines()
                                      if line.strip() and not line.startswith("#")], [])
                    for sdk in ("lib/ebt/Ebt.java", "lib/ebt/ebt.ts", "lib/ebt/ebt.dart"):
                        self.assertIn(f"kit:{sdk}", pinned)
                    p = self.sync_pinned(target, cwd=self.clone)
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    self.assertEqual(p.stdout.strip(), "")
                # The new templates import the public witnessbox.api, the legacy import is for compatibility only.
                for name in ("checks.py", "test_checks.py"):
                    template = (target / name).read_text(encoding="utf-8")
                    self.assertIn("from witnessbox.api import", template)
                    self.assertNotIn("from ebt_verification.api import", template)

                # The test.sh contract: without OUT_DIR it is an execution error, not "tests failed".
                p = subprocess.run([str(target / "test.sh")], cwd=target, capture_output=True, text=True,
                                   env={k: v for k, v in os.environ.items() if k != "OUT_DIR"})
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

                # The example checker and its tests are working code, not comments. The instruction
                # must run the tests with the distribution interpreter: the system python3
                # does not see the witnessbox package.
                for name in ("test_checks.py", "README.md"):
                    self.assertIn("witnessbox test-checks", (target / name).read_text(encoding="utf-8"))
                p = subprocess.run([str(self.bin / "witnessbox"), "test-checks", target.name],
                                   cwd=target.parent, capture_output=True, text=True,
                                   env={**env, "PATH": f"{self.bin}:{os.environ['PATH']}"})
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

                # The scaffold is self-consistent: spec, checks.py and the self-test give PASS.
                evidence = target / "evidence.jsonl"
                evidence.write_text(
                    '{"seq":1,"req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,'
                    '"data":{"value":5,"result":10}}\n'
                    '{"seq":2,"req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,'
                    '"data":{"value":0,"result":0}}\n'
                    '{"seq":3,"req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,'
                    '"data":{"value":-3,"result":-6}}\n', encoding="utf-8")
                p = subprocess.run([str(self.bin / "witnessbox"), "check", "--spec", str(target / "spec.toml"),
                                    "--checkers", str(target / "checks.py"), "--evidence", str(evidence),
                                    "--self-test"], capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_scaffold_refuses_existing_files_and_unknown_stack(self):
        env = {**os.environ, "PYTHONPATH": ""}
        target = self.clone.parent / "scaffold-existing"
        target.mkdir()
        approved = target / "spec.toml"
        approved.write_text("# approved spec\n", encoding="utf-8")
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "ts", str(target)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("not empty", p.stderr)
        self.assertEqual(approved.read_text(encoding="utf-8"), "# approved spec\n")

        missing = self.clone.parent / "scaffold-unknown"
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "ruby", str(missing)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage:", p.stderr)
        self.assertFalse(missing.exists())

        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

        # The default directory is ebt in the current directory.
        default = self.clone.parent / "scaffold-default"
        default.mkdir()
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "ts"], cwd=default,
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((default / "ebt" / "spec.toml").is_file())

    def test_scaffold_accepts_current_directory(self):
        """`.` is the current empty directory for each stack; before, it was removed as a temporary one and failed."""
        env = {**os.environ, "PYTHONPATH": ""}
        for stack in ("dart", "ts", "jvm", "generic"):
            with self.subTest(stack=stack):
                dot = self.clone.parent / f"scaffold-dot-{stack}"
                dot.mkdir()
                p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", stack, "."], cwd=dot,
                                   capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue((dot / "spec.toml").is_file())
                self.assertTrue((dot / "test.sh").is_file())
                self.assertTrue((dot / "pinned.txt").is_file())
                self.assertFalse((dot / "ebt").exists())

    def test_scaffold_test_scripts_follow_gate_contract(self):
        """The test.sh template: EBT_TESTS arguments, OUT_DIR, codes 0/1/2 and evidence for any outcome."""
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("EBT_") and k != "OUT_DIR"}
        env["PYTHONPATH"] = ""
        fake_body = """#!/bin/bash
mkdir -p build/ebt
printf '%s\\n' "$*" > command.args
printf '%s\\n' '{"seq":1}' > build/ebt/a.jsonl
exit "${FAKE_RC:-0}"
"""
        cases = (("dart", "flutter", {}), ("ts", "bunx", {}),
                 ("generic", "fake-tests", {"EBT_TEST_CMD": "fake-tests"}))
        for stack, command, extra in cases:
            with self.subTest(stack=stack):
                project = self.clone.parent / f"run-{stack}"
                target = project / "ebt"
                p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", stack, str(target)],
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
                                          env={**path_env, "OUT_DIR": str(out), "FAKE_RC": str(rc),
                                               **extra}), out

                p, out = run_tests(0, "out")
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue((out / "a.jsonl").is_file())
                args = (project / "command.args").read_text(encoding="utf-8").strip()
                self.assertIn("one two", args)
                if stack == "dart":
                    self.assertIn("--no-pub", args)
                elif stack == "ts":
                    self.assertIn("run", args)
                else:
                    # The EBT_TESTS words are passed to the command as separate arguments, without eval.
                    self.assertEqual(args, "one two")

                p, out = run_tests(1, "out-failed")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertTrue((out / "a.jsonl").is_file())

                p, _ = run_tests(2, "out-error")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

                p, out = run_tests(7, "out-ambiguous")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                # Evidence is copied even on an "execution error": code 7 is not in EBT_TEST_FAIL_CODES.
                self.assertTrue((out / "a.jsonl").is_file())

        project = self.clone.parent / "run-jvm"
        target = project / "ebt"
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "jvm", str(target)],
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

        # No XML: the old grep without files read stdin and could hang. Keep stdin
        # open and wait: the template must return 2 without waiting for stdin to close.
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
            self.fail("test.sh hung: grep read stdin without XML reports")
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 2, stdout + stderr)

    def test_generic_test_script_settings(self):
        """generic: required EBT_TEST_CMD, EBT_EVIDENCE_DIR, EBT_TEST_FAIL_CODES and arguments."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("EBT_") and k != "OUT_DIR"}
        env["PYTHONPATH"] = ""
        project = self.clone.parent / "run-generic-settings"
        target = project / "ebt"
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "generic", str(target)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        bin_dir = project / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "fake-tests"
        fake.write_text("""#!/bin/bash
mkdir -p "${FAKE_EVIDENCE:-build/ebt}"
printf '%s\\n' "$#" > "$FAKE_ARGS"
printf '%s\\n' "$@" >> "$FAKE_ARGS"
printf '%s\\n' '{"seq":1}' > "${FAKE_EVIDENCE:-build/ebt}/a.jsonl"
exit "${FAKE_RC:-0}"
""", encoding="utf-8")
        fake.chmod(0o755)
        path_env = {**env, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

        # 1. Without EBT_TEST_CMD: code 2 with a hint, not running an empty command.
        out = project / "out-no-command"
        out.mkdir()
        p = subprocess.run([str(target / "test.sh")], cwd=project, capture_output=True, text=True,
                           env={**path_env, "OUT_DIR": str(out)})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("EBT_TEST_CMD", p.stderr)

        def run(name, **overrides):
            out = project / name
            out.mkdir()
            return subprocess.run([str(target / "test.sh"), "a b"], cwd=project,
                                  capture_output=True, text=True,
                                  env={**path_env, "OUT_DIR": str(out), "EBT_TEST_CMD": "fake-tests",
                                       "FAKE_ARGS": str(project / "command.args"),
                                       "FAKE_RC": "0", **overrides}), out

        # 2. Evidence is taken from EBT_EVIDENCE_DIR, an old file there does not survive the run.
        evidence_dir = project / "out/ev"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "old.jsonl").write_text('{"seq":1}\n', encoding="utf-8")
        p, out = run("out-evidence", EBT_EVIDENCE_DIR="out/ev", FAKE_EVIDENCE=str(evidence_dir))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sorted(path.name for path in out.iterdir()), ["a.jsonl"])
        self.assertFalse((evidence_dir / "old.jsonl").exists())

        # 3. A code from EBT_TEST_FAIL_CODES means "tests failed" (1), other codes are an error (2).
        p, out = run("out-fail-code", EBT_TEST_FAIL_CODES="1 4", FAKE_RC="4")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertTrue((out / "a.jsonl").is_file())
        p, _ = run("out-other-code", EBT_TEST_FAIL_CODES="1 4", FAKE_RC="5")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

        # 4. An argument with a space reaches the command as one word: the EBT_TESTS words are not re-parsed.
        p, _ = run("out-args")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((project / "command.args").read_text(encoding="utf-8").splitlines(),
                         ["1", "a b"])

        # 5. A trailing newline from a YAML block does not turn an argument into a new command.
        p, _ = run("out-newline", EBT_TEST_CMD="fake-tests\n")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual((project / "command.args").read_text(encoding="utf-8").splitlines(),
                         ["1", "a b"])

    def test_matching_checker_by_default_even_if_other_on_path(self):
        fake = self.fake_checker(0)
        self.record = self.record.replace('"result":55870', '"result":1')  # a rule violation
        env = {"PATH": f"{fake.parent}:{os.environ['PATH']}"}
        p = self.gate(self.write_to('"$OUT_DIR"'), env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"witnessbox {VERSION}", self.gate_md())
        self.assertIn(str(self.bin.parent), self.gate_md())

    def test_project_cannot_shadow_bundled_checker_package(self):
        for name in ("witnessbox", "ebt_verification"):
            poison = self.clone / name
            poison.mkdir()
            (poison / "__init__.py").write_text("raise RuntimeError('wrong checker from project cwd')")
        subprocess.run(["git", "-C", str(self.clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "name collision"], check=True)
        self.record = self.record.replace('"result":55870', '"result":1')
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("False proof", (self.run_dir / "report.md").read_text())

    def test_installed_checker_only_on_request(self):
        fake = self.fake_checker(0)
        self.record = self.record.replace('"result":55870', '"result":1')
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("fake-check 9.9.9", self.gate_md())

    def test_relative_explicit_checker_is_resolved_before_chdir(self):
        fake = self.fake_checker(0)
        self.record = self.record.replace('"result":55870', '"result":1')
        relative = os.path.relpath(fake, Path.cwd())
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": relative})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("fake-check 9.9.9", self.gate_md())

    def test_out_dir_evidence_passes(self):
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("green", self.gate_md())
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
        self.assertIn("red", self.gate_md())

    def test_runner_error_with_evidence_is_error(self):
        # Evidence through the build/ebt bridge: this is how the case is checked on a gate without OUT_DIR too.
        p = self.gate(self.write_to("build/ebt") + "exit 2\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertNotIn("green", self.gate_md())

    def test_runner_error_without_evidence_is_error(self):
        p = self.gate("exit 2\n")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_rerun_does_not_keep_old_green(self):
        first = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.gate("exit 0\n")
        self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
        self.assertNotIn("green", self.gate_md())
        self.assertFalse((self.run_dir / "report.md").exists())

    def test_checker_crash_is_normalized_to_error(self):
        fake = self.fake_checker(0)
        fake.write_text('#!/bin/bash\nif [ "$1" = --version ]; then echo crash-checker; exit 0; fi\nexit 17\n')
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_seq_boundaries_are_preserved(self):
        # Two files with seq=1 are valid; a concatenation as input would give LOG_GAP.
        script = self.write_to('"$OUT_DIR"') + 'cp "$OUT_DIR/a.jsonl" "$OUT_DIR/b.jsonl"\n'
        p = self.gate(script)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("logs merged: 2", self.gate_md())

    def test_missing_bundle_clears_old_green(self):
        self.assertEqual(self.gate(self.write_to('"$OUT_DIR"')).returncode, 0)
        p = subprocess.run([str(self.bin / "witnessbox"), "gate", str(self.ebt / "missing"),
                            str(self.clone), str(self.run_dir)], capture_output=True)
        self.assertEqual(p.returncode, 2)
        self.assertFalse((self.run_dir / "report.md").exists())
        self.assertFalse((self.run_dir / "gate.md").exists())

    def test_pinned_uses_installed_resource_and_detects_drift(self):
        info = self.installation()
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
        self.assertIn("Pinned copies differ", self.gate_md())

    def test_sync_pinned_copies_originals_and_gate_sees_no_drift(self):
        (self.ebt / "obs").mkdir()
        (self.ebt / "obs/helper.ts").write_text("export const h = 1;\n")
        (self.ebt / "pinned.txt").write_text(
            "# SDK\nkit:lib/ebt/Ebt.java  sdk/Ebt.java\n\nobs/helper.ts  src/obs/helper.ts\n")
        p = self.sync_pinned(self.ebt, cwd=self.clone)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("updated sdk/Ebt.java", p.stdout)
        sdk = Path(self.installation()["resources"]) / "lib/ebt/Ebt.java"
        self.assertEqual((self.clone / "sdk/Ebt.java").read_bytes(), sdk.read_bytes())
        self.assertIn("unchanged", self.sync_pinned(self.ebt, cwd=self.clone).stdout)
        subprocess.run(["git", "-C", str(self.clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.clone), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "pin"], check=True)
        self.assertEqual(self.gate(self.write_to('"$OUT_DIR"')).returncode, 0)

    def test_sync_pinned_refuses_escape_missing_original_and_crlf(self):
        valid = "kit:lib/ebt/Ebt.java  sdk/Ebt.java\n"
        (self.clone.parent / "outside").mkdir()
        os.symlink(self.clone.parent / "outside", self.clone / "link")
        cases = {
            "escape": valid + "kit:lib/ebt/Ebt.java  ../outside.java\n",
            "absolute": valid + "kit:lib/ebt/Ebt.java  /tmp/abs.java\n",
            "missing original": valid + "kit:lib/ebt/Nope.java  x.java\n",
            "no destination": valid + "kit:lib/ebt/Ebt.java\n",
            "crlf": valid + "kit:lib/ebt/Ebt.java  sdk/Ebt.java\r\n",
            "symlink outside": valid + "kit:lib/ebt/Ebt.java  link/Ebt.java\n",
            "duplicate destination": valid + "kit:lib/ebt/Ebt.java  sdk/Ebt.java\n",
        }
        for name, pinned in cases.items():
            with self.subTest(name=name):
                (self.clone / "sdk/Ebt.java").unlink(missing_ok=True)
                (self.ebt / "pinned.txt").write_text(pinned, encoding="utf-8")
                p = self.sync_pinned(self.ebt, cwd=self.clone)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("witnessbox sync-pinned:", p.stderr)
                self.assertFalse((self.clone / "sdk/Ebt.java").exists())

        # The strict --sync-pinned mode does not accept a non-UTF-8 comment, even if
        # --check-only by the gate rules lets it through.
        (self.ebt / "pinned.txt").write_bytes(b"# \xcf\xf0\xe8\xec\xe5\xf0 cp1251\n")
        p = self.sync_pinned(self.ebt, cwd=self.clone)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("could not read", p.stderr)

        p = subprocess.run([str(self.bin / "witnessbox"), "sync-pinned"],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage:", p.stderr)

        empty = self.clone.parent / "ebt-empty"
        empty.mkdir()
        p = self.sync_pinned(empty, cwd=self.clone)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("witnessbox sync-pinned:", p.stderr)
        self.assertIn("no pinned.txt", p.stderr)

    def test_check_only_clean_project_is_ok(self):
        p = self.check_only()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        lines = p.stdout.splitlines()
        self.assertTrue(lines, "no output for the checks")
        self.assertEqual([line for line in lines if line.startswith("skipped")],
                         ["skipped base: BASE is not set: protected paths are not checked"])
        for line in lines:
            if not line.startswith("skipped"):
                self.assertTrue(line.startswith("ok "), line)
        for name in ("spec", "checks", "known", "baseline", "runner", "pinned", "clone"):
            self.assertTrue(any(line.startswith(f"ok {name}") for line in lines), name)

    def test_check_only_does_not_execute_project_scripts(self):
        # checks.py is imported, but __pycache__ must not remain in the checks directory.
        (self.ebt / "checks.py").write_text("CHECKERS = {}\n", encoding="utf-8")
        markers = []
        for name in ("prepare.sh", "test.sh"):
            marker = self.clone.parent / f"ran-{name}"
            markers.append(marker)
            script = self.ebt / name
            script.write_text(f"#!/bin/bash\ntouch {marker}\n", encoding="utf-8")
            script.chmod(0o755)
        p = self.check_only()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([marker.name for marker in markers if marker.exists()], [])
        self.assertFalse((self.ebt / "__pycache__").exists(), "check-only left __pycache__")

    def test_check_only_unknown_checker_out_of_scope_is_not_problem(self):
        """An approved spec may run ahead of the code: outside EBT_INV an unfinished checker does not interfere."""
        env = self.case_unknown_checker_out_of_scope()
        p = self.check_only(env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = self.gate(self.write_to('"$OUT_DIR"'), env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_check_only_unknown_checker_in_scope_fails_gate(self):
        """A check-only problem in scope must be a gate FAIL, not ERROR and not PASS."""
        self.case_unknown_checker()
        p = self.check_only()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        p = self.gate(self.write_to('"$OUT_DIR"'))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.gate_json()["reasons"], ["checker_failed"])
        self.assertIn("No checker", (self.run_dir / "report.md").read_text(encoding="utf-8"))

    def test_check_only_does_not_judge_external_checker_registry(self):
        """EBT_CHECK may know its own checker: a local registration check would report a false problem."""
        fake = self.fake_checker(0)
        (self.ebt / "spec.toml").write_text(
            SPEC.replace('"cart_total"', '"missing_rule"'), encoding="utf-8")
        p = self.check_only({"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("skipped checks", p.stdout)

    def test_check_only_does_not_judge_external_checker_files(self):
        """With an external checker, a local parse of spec/checks/known/baseline would report a false problem."""
        fake = self.fake_checker(0)
        (self.ebt / "spec.toml").write_text("this is not TOML\n", encoding="utf-8")
        (self.ebt / "checks.py").write_text('raise RuntimeError("boom")\n', encoding="utf-8")
        (self.ebt / "known.toml").write_text("[[known]]\n", encoding="utf-8")
        (self.ebt / "baseline.jsonl").write_text("{not json\n", encoding="utf-8")
        p = self.check_only({"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for name in ("spec", "checks", "known", "baseline"):
            self.assertIn(f"skipped {name}", p.stdout)
        # The gate with the same external checker on these files is PASS too: the guarantee is intact.
        p = self.gate(self.write_to('"$OUT_DIR"'), {"EBT_CHECK": str(fake)})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_check_only_pinned_uses_gate_rules(self):
        """The strictness of --sync-pinned gives no problem where the gate on the same input is PASS."""
        sdk = Path(self.installation()["resources"]) / "lib/ebt/Ebt.java"

        def pin_in_clone():
            (self.clone / "Ebt.java").write_bytes(sdk.read_bytes())
            self.commit_clone("pinned copy")

        def cr_comment():
            pin_in_clone()
            (self.ebt / "pinned.txt").write_bytes(b"# comment\r\nkit:lib/ebt/Ebt.java  Ebt.java\n")

        def cp1251_comment():
            (self.ebt / "pinned.txt").write_bytes(b"# \xcf\xf0\xe8\xec\xe5\xf0 cp1251\n")

        def outside_relative():
            (self.clone.parent / "Ebt.java").write_bytes(sdk.read_bytes())
            (self.ebt / "pinned.txt").write_text("kit:lib/ebt/Ebt.java  ../Ebt.java\n", encoding="utf-8")

        def duplicate_destination():
            pin_in_clone()
            (self.ebt / "pinned.txt").write_text(
                "kit:lib/ebt/Ebt.java  Ebt.java\nkit:lib/ebt/Ebt.java  ./Ebt.java\n",
                encoding="utf-8")

        def absolute_destination():
            target = self.clone.parent / "abs.java"
            target.write_bytes(sdk.read_bytes())
            (self.ebt / "pinned.txt").write_text(
                f"kit:lib/ebt/Ebt.java  {target}\n", encoding="utf-8")

        for name, prepare in {
            "CR only in a comment": cr_comment,
            "non-UTF-8 comment": cp1251_comment,
            "dest outside the clone": outside_relative,
            "repeated dest": duplicate_destination,
            "absolute dest": absolute_destination,
        }.items():
            with self.subTest(name=name):
                self.new_project()
                sdk = Path(self.installation()["resources"]) / "lib/ebt/Ebt.java"
                prepare()
                p = self.check_only()
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                p = self.gate(self.write_to('"$OUT_DIR"'))
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_check_only_reports_each_problem(self):
        for name, (prepare, check) in self.problem_cases().items():
            with self.subTest(name=name):
                self.new_project()
                env = prepare()
                p = self.check_only(env)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(f"problem {check}:", p.stdout)
                self.assertNotIn("Traceback", p.stderr)

    def test_no_commits_is_named_before_dirty_tree(self):
        for name, run in (("check-only", self.check_only), ("gate", lambda env: self.gate(self.write_to('"$OUT_DIR"'), env))):
            with self.subTest(name=name):
                self.new_project()
                p = run(self.case_no_commits())
                self.assertIn("the repository has no commits", p.stdout + p.stderr)
                self.assertNotIn("not clean", p.stdout + p.stderr)

    def test_check_only_problems_are_not_gate_pass(self):
        """Every --check-only problem on the same input gives the gate a non-PASS (D47 boundary)."""
        for name, (prepare, _) in self.problem_cases().items():
            with self.subTest(name=name):
                self.new_project()
                env = prepare()
                # A non-executable test.sh is checked by the gate as is, without substituting the script.
                test_sh = None if name.startswith("runner") else self.write_to('"$OUT_DIR"')
                p = self.gate(test_sh, env)
                self.assertIn(p.returncode, (1, 2), p.stdout + p.stderr)

    def test_check_only_usage_errors(self):
        env = {**os.environ, "PYTHONPATH": ""}
        for args in ([], [str(self.ebt)], [str(self.ebt), str(self.clone), "extra"]):
            with self.subTest(args=args):
                p = subprocess.run([str(self.bin / "witnessbox"), "gate", "--check-only", *args],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("usage:", p.stderr)
        p = self.check_only({}, str(self.ebt / "missing"), str(self.clone))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("no checks directory", p.stderr)

    def test_test_checks_runs_scaffold_tests(self):
        target = self.clone.parent / "test-checks-ts"
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "ts", str(target)],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = self.run_test_checks(target, cwd=self.clone.parent)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("OK", p.stdout + p.stderr)
        self.assertFalse((target / "__pycache__").exists(), "--test-checks left __pycache__")

    def test_test_checks_fails_on_broken_checker(self):
        target = self.clone.parent / "test-checks-broken"
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "ts", str(target)],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        checks = target / "checks.py"
        text = checks.read_text(encoding="utf-8")
        self.assertIn("expected = value * 2", text)
        checks.write_text(text.replace("expected = value * 2", "expected = value * 3"), encoding="utf-8")
        p = self.run_test_checks(target, cwd=self.clone.parent)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)

    def test_test_checks_without_tests_is_not_green(self):
        target = self.clone.parent / "test-checks-none"
        p = subprocess.run([str(self.bin / "witnessbox"), "scaffold", "ts", str(target)],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        (target / "test_checks.py").unlink()
        p = self.run_test_checks(target, cwd=self.clone.parent)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("no checker tests found", p.stderr)

    def test_test_checks_usage_errors(self):
        env = {**os.environ, "PYTHONPATH": ""}
        p = subprocess.run([str(self.bin / "witnessbox"), "test-checks", "a", "b"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("usage:", p.stderr)
        p = subprocess.run([str(self.bin / "witnessbox"), "test-checks", str(self.ebt / "missing")],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("no directory", p.stderr)

    def test_wheel_from_sdist_ships_sdk_templates_and_compat_module(self):
        """The wheel is built from the sdist: the SDK and all templates ship in the distribution, compatibility has no second copy."""
        import zipfile
        with zipfile.ZipFile(self.wheel) as wheel:
            names = wheel.namelist()
        for name in ("Ebt.java", "ebt.dart", "ebt.ts"):
            self.assertIn(f"witnessbox/resources/lib/ebt/{name}", names)
        for name in ("README.md", "spec.toml", "checks.py", "test_checks.py",
                     "dart/test.sh", "dart/pinned.txt", "ts/test.sh", "ts/pinned.txt",
                     "jvm/test.sh", "jvm/pinned.txt", "generic/test.sh", "generic/pinned.txt"):
            self.assertIn(f"witnessbox/resources/scaffold/{name}", names)
        self.assertIn("witnessbox/checker/fixtures/record.jsonl", names)
        self.assertIn("witnessbox/api.py", names)
        # The old import is a thin forward through ebt_verification/api.py, not a second runtime.
        self.assertIn("ebt_verification/api.py", names)
        self.assertNotIn("ebt_verification/checker/checkers.py", names)
        self.assertFalse(any("prompts/" in p or p.endswith(("roles.toml", "run_role.py")) for p in names))

    def test_sdist_ships_sdk_templates_and_compat_module(self):
        import tarfile
        with tarfile.open(self.sdist) as archive:
            names = archive.getnames()
        for relative in ("src/witnessbox/resources/lib/ebt/Ebt.java",
                         "src/witnessbox/resources/lib/ebt/ebt.dart",
                         "src/witnessbox/resources/lib/ebt/ebt.ts",
                         "src/witnessbox/resources/scaffold/test_checks.py",
                         "src/witnessbox/resources/scaffold/dart/test.sh",
                         "src/witnessbox/resources/scaffold/generic/test.sh",
                         "src/witnessbox/resources/scaffold/generic/pinned.txt",
                         "src/witnessbox/checker/fixtures/record.jsonl",
                         "src/witnessbox/api.py",
                         "src/ebt_verification/api.py"):
            self.assertTrue(any(name.endswith(relative) for name in names), relative)
        self.assertFalse(any(name.endswith("src/ebt_verification/checker/checkers.py") for name in names))

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
        self.assertIn("changed in the application branch", self.gate_md())

    def test_runner_cannot_change_verification_inputs(self):
        """Project code runs with the gate privileges: editing inputs during the run is ERROR, the checker reads a snapshot."""
        cases = {"spec.toml": 'echo "# changed" >> "$(dirname "$0")/spec.toml"\n',
                 "checks.py": 'echo "CHECKERS = {}" > "$(dirname "$0")/checks.py"\n'}
        for name, edit in cases.items():
            with self.subTest(name=name):
                p = self.gate(self.write_to('"$OUT_DIR"') + edit)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                s = self.gate_json()
                self.assertEqual((s["result"], s["reasons"]), ("ERROR", ["gate_error"]))
                self.assertIn(f"changed during the run: {name}", s["message"])
                self.assertEqual((self.run_dir / "inputs/spec.toml").read_text(encoding="utf-8"), SPEC)
                (self.ebt / "spec.toml").write_text(SPEC, encoding="utf-8")
                (self.ebt / "checks.py").unlink(missing_ok=True)

    def test_runner_cannot_change_installed_verifier(self):
        import json
        env = {**os.environ, "PYTHONPATH": ""}  # make test-gate sets PYTHONPATH=src: the installed package is needed
        info = json.loads(subprocess.check_output([str(self.bin / "witnessbox"), "--installation"], env=env))
        self.assertIn("site-packages", info["package"])
        package = Path(info["package"])
        # The compatible package is executed by project checkers, so editing it is
        # the same distribution tampering as editing witnessbox/checker/.
        for target in (package / "checker" / "checkers.py",
                       package / "__init__.py",
                       package.parent / "ebt_verification" / "api.py",
                       package.parent / "checkers.py"):
            with self.subTest(verifier=target.name):
                original = target.read_bytes()
                try:
                    p = self.gate(self.write_to('"$OUT_DIR"') + f'echo "# changed" >> "{target}"\n')
                    self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                    self.assertEqual(self.gate_json()["result"], "ERROR")
                    self.assertIn("distribution code changed during the run", self.gate_json()["message"])
                finally:
                    target.write_bytes(original)

    def test_installed_gate_without_source_access(self):
        import sys
        if sys.platform != "darwin":
            self.skipTest("The sandbox-exec check requires macOS; use a container on other OSes")
        source = KIT
        policy = f'(version 1)(allow default)(deny file-read* (subpath "{source}"))'
        prefix = ["/usr/bin/sandbox-exec", "-p", policy]
        probe = subprocess.run(prefix + ["/bin/cat", str(source / "README.md")],
                               capture_output=True, text=True, cwd=self.clone.parent)
        if "sandbox_apply" in probe.stderr:
            self.skipTest("The system sandbox is unavailable inside the external process sandbox")
        self.assertNotEqual(probe.returncode, 0, "The repository sources are accessible")
        self.assertIn("Operation not permitted", probe.stderr)
        (self.ebt / "spec.toml").write_text(SPEC.replace('"cart_total"', '"project_cart"'))
        (self.ebt / "checks.py").write_text(
            'from checkers import Verdict, WitnessError\n'
            'from witnessbox.checker.checkers import cart_total, Verdict as InstalledVerdict\n'
            'from ebt_verification.api import Verdict as CompatVerdict\n'
            'assert Verdict is InstalledVerdict is CompatVerdict\n'
            'CHECKERS = {"project_cart": cart_total}\n')
        self.gate(self.write_to('"$OUT_DIR"'))  # Save the project inputs before the sources are forbidden.
        env = {**os.environ, "PYTHONPATH": "", "BASE": "", "EBT_CHECK": ""}
        p = subprocess.run(prefix + [str(self.bin / "witnessbox"), "gate", str(self.ebt), str(self.clone),
                                     str(self.run_dir)], capture_output=True, text=True,
                           cwd=self.clone.parent, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"witnessbox {VERSION}", self.gate_md())


if __name__ == "__main__":
    unittest.main()
