"""Public entry point of the witnessbox command; all runtime paths belong to this installation."""

import hashlib
import json
import os
from importlib.metadata import distribution
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def _installed_entries(package: Path, dist):
    """(root, paths) of the shipped code: RECORD, or a tree walk for editable installs.

    RECORD is relative to dist.locate_file(""), not package.parent. In an editable
    install and when running from src via PYTHONPATH, RECORD lists only .pth and
    finder files, not the package sources: such a RECORD is unusable, and then
    the fingerprint is built by walking the tree.
    """
    files = dist.files or ()
    root = Path(dist.locate_file("")).resolve()
    # RECORD is usable only if it describes the package being run. With PYTHONPATH=src
    # next to an installed wheel the metadata exists, but the package lies outside its root.
    if package == root / package.name and any(
            Path(entry).parts[:1] == (package.name,) for entry in files):
        return root, [Path(dist.locate_file(entry)).resolve() for entry in files]
    root = package.parent
    paths = [root / "checkers.py", root / "ebt_check.py",
             *package.rglob("*.py"), *package.rglob("*.sh")]
    compat = root / "ebt_verification"
    if compat.is_dir():
        paths += list(compat.rglob("*.py"))
    return root, paths


def _code_hash(root: Path, paths):
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: p.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        # Lengths make file boundaries unambiguous, including rename/empty-file changes.
        for part in (name, data):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def installation():
    package = Path(__file__).resolve().parent
    dist = distribution("witnessbox")
    root, installed = _installed_entries(package, dist)
    # scaffold is data for a new project, not checking code: editing it does not change
    # the identity of the installed gate. So the directory is excluded from the fingerprint.
    code = [path for path in installed
            if path.suffix in (".py", ".sh") and "scaffold" not in path.parts]
    cli = Path(__file__).resolve()
    modules = [path for path in code if path.suffix == ".py" and path.resolve() != cli]
    shell_files = [path for path in code if path.suffix == ".sh"]
    if not modules or not shell_files:
        # An empty or incomplete file set would give a constant SHA of empty input:
        # a silent "identity" that identifies nothing.
        raise RuntimeError(
            "installation: empty witnessbox code fingerprint "
            f"(python={len(modules)}, shell={len(shell_files)}); check the package installation")
    return {
        "distribution": dist.metadata["Name"],
        "version": dist.version,
        "package": str(package),
        "resources": str(package / "resources"),
        "python": sys.executable,
        "checker": str(package / "checker" / "ebt_check.py"),
        "checker_sha256": _code_hash(root, modules),
        "gate_sha256": _code_hash(root, [*shell_files, cli]),
    }


GATE_FILES = ("gate.md", "report.md", "report.json", "evidence.jsonl", "out",
              "test.log", "prepare.log", "ebt-check.err", "installation.json", "inputs")


def write_summary(run, exit_code, reasons, message, commit, tests_rc, check_rc,
                  checker, checker_sha256, spec):
    """gate.json is the machine-readable result of a gate attempt, format 1; the write is atomic."""
    run, spec, exit_code = Path(run), Path(spec), int(exit_code)
    info = installation()
    evidence = None
    if check_rc:
        # simplicity: the hash is taken when the result is written, not when the checker reads it; editing the file
        # in between is not seen (D26 boundary). More precise: hash in load_jsonl.
        evidence = [
            {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted((run / "out").glob("*.jsonl"))
            if path.is_file()
        ]
    summary = {
        "format": 1,
        "result": {0: "PASS", 1: "FAIL"}.get(exit_code, "ERROR"),
        "exit_code": exit_code,
        "reasons": [r for r in reasons.split(",") if r],
        "message": message or None,
        "commit": commit or None,
        "tests_exit_code": int(tests_rc) if tests_rc else None,
        "checker_exit_code": int(check_rc) if check_rc else None,
        "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest() if spec.is_file() else None,
        "verifier": {k: info[k] for k in ("distribution", "version", "gate_sha256")},
        "checker": {"command": checker or None, "sha256": checker_sha256 or None},
        "evidence": evidence,
        "files": [name for name in GATE_FILES if (run / name).exists()],
    }
    tmp = run / "gate.json.tmp"
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(run / "gate.json")


SCAFFOLD_STACKS = ("dart", "ts", "jvm", "generic")
SCAFFOLD_FILES = ("spec.toml", "checks.py", "test_checks.py", "README.md")


def _copy_scaffold(sources, target):
    """Copy templates into an empty directory; on error remove the files already created."""
    copied = []
    try:
        for name, source in sources.items():
            # Remember the name before copying: a failed write may leave part of a file.
            copied.append(name)
            shutil.copyfile(source, target / name)
        (target / "test.sh").chmod(0o755)
    except OSError:
        for name in copied:
            (target / name).unlink(missing_ok=True)
        raise


def scaffold(argv):
    """Scaffold of ebt/: spec, checks.py, the chosen stack's test.sh templates and pinned.txt."""
    usage = "usage: witnessbox scaffold <dart|ts|jvm|generic> [<ebt-dir>]"
    if len(argv) not in (1, 2) or argv[0] not in SCAFFOLD_STACKS:
        print(usage, file=sys.stderr)
        return 2
    stack = argv[0]
    target = Path(argv[1] if len(argv) == 2 else "ebt").expanduser()
    root = Path(__file__).resolve().parent / "resources" / "scaffold"
    sources = {name: root / name for name in SCAFFOLD_FILES}
    sources["test.sh"] = root / stack / "test.sh"
    sources["pinned.txt"] = root / stack / "pinned.txt"

    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        print("witnessbox scaffold: the distribution has no template files: " + ", ".join(missing), file=sys.stderr)
        return 2
    # The scaffold does not overwrite an approved spec or foreign files (D4).
    existing = target.exists() or target.is_symlink()
    if existing and (target.is_symlink() or not target.is_dir() or any(target.iterdir())):
        print(f"witnessbox scaffold: {target} already exists and is not empty; files not overwritten", file=sys.stderr)
        return 2
    # Normalize before creating the temp directory: `--scaffold ts .` is the current
    # directory, not a temp directory inside it.
    target = target.resolve()

    if existing:
        # An existing empty directory (including `.`) is filled in place; it must not be removed.
        try:
            _copy_scaffold(sources, target)
        except OSError as error:
            print(f"witnessbox scaffold: could not create {target}: {error}", file=sys.stderr)
            return 2
    else:
        temp = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix=".ebt-scaffold-", dir=target.parent))
            _copy_scaffold(sources, temp)
            temp.chmod(0o755)
            temp.rename(target)
        except OSError as error:
            if temp is not None:
                shutil.rmtree(temp, ignore_errors=True)
            print(f"witnessbox scaffold: could not create {target}: {error}", file=sys.stderr)
            return 2

    print(f"Created ebt/ scaffold ({stack}) in {target}:")
    for name in sources:
        print(f"  {name}")
    print("Next:")
    print("  replace the example REQ-EXAMPLE-1/INV-EXAMPLE-1 with an approved requirement (may stay for a trial);")
    print("  run the checker tests: witnessbox test-checks ebt;")
    print("  copy the SDK and helpers: witnessbox sync-pinned ebt;")
    print("  write an evidence test (it writes build/ebt/*.jsonl) and, if needed, ebt/prepare.sh;")
    print("  commit the project and check the setup: witnessbox gate --check-only ebt .;")
    print("  run the gate: witnessbox gate ebt . <result dir>.")
    print("Details are in the directory README.md.")
    return 0


PinnedCopy = tuple[int, Path, str, Path | None]


def _printable(value: object) -> str:
    """Text without surrogates: a cp1251 path is shown as \\xNN, but printing does not crash."""
    return str(value).encode("utf-8", "backslashreplace").decode("utf-8")


def _gate_read_pinned(ebt: Path, root: Path) -> tuple[list[PinnedCopy], str | None]:
    """Parse pinned.txt by gate.sh rules, without the strictness of --sync-pinned.

    The gate skips comment lines (including those with \r or non-UTF-8), accepts
    an absolute dest, `../` and a repeated path; it checks only that the original exists and
    that the copy matches. These are the rules --check-only needs, otherwise it would find
    a problem where the gate gives PASS (D47).
    """
    pinned = ebt / "pinned.txt"
    if not pinned.is_file():
        return [], f"no pinned.txt: {pinned}"
    try:
        raw = pinned.read_bytes()
    except OSError as error:
        return [], f"could not read {pinned}: {error}"
    resources = Path(__file__).resolve().parent / "resources"
    copies: list[PinnedCopy] = []
    # Bash read splits only on spaces and tabs; \r stays in the last field.
    for number, line in enumerate(raw.split(b"\n"), start=1):
        fields = [field for field in re.split(rb"[ \t]+", line.strip(b" \t")) if field]
        if not fields or fields[0].startswith(b"#"):
            continue
        source = fields[0]
        dest = fields[1] if len(fields) > 1 else b""
        source_text = os.fsdecode(source)
        if source_text.startswith("kit:"):
            src = resources / source_text[len("kit:"):].lstrip("/")
        elif os.path.isabs(source_text):
            src = Path(source_text)
        else:
            src = ebt / source_text
        if not src.is_file():
            return [], f"pinned.txt:{number}: no original {_printable(src)}"
        if not dest:
            destination = None
        else:
            dest_text = os.fsdecode(dest)
            destination = Path(dest_text) if os.path.isabs(dest_text) else root / dest_text
        copies.append((number, src, _printable(os.fsdecode(dest)), destination))
    return copies, None


def read_pinned(ebt: Path, root: Path, gate_rules: bool = False) -> tuple[list[PinnedCopy], str | None]:
    """Parse pinned.txt: (copies, first error). The error is text without the command prefix.

    The first pass writes nothing: a failure before the first write leaves no half-made copies.
    Same format as the gate: empty lines and `#` lines are skipped, the first token is
    the original (`kit:` means resources of this distribution, absolute as is, otherwise next to ebt/),
    the second is the path in the project. Returns (line number, original, dest, resolved path).

    gate_rules=True: the lenient gate.sh rules for --check-only: comments are not
    checked for \r/UTF-8; an absolute dest, escaping the root and repeats are allowed.
    """
    if gate_rules:
        return _gate_read_pinned(ebt, root)
    pinned = ebt / "pinned.txt"
    if not pinned.is_file():
        return [], f"no pinned.txt: {pinned}"
    # Read bytes, not text with universal newlines: otherwise CRLF vanishes,
    # and the command would silently write the copy where the gate does not look (`sdk/Ebt.java\r`).
    try:
        text = pinned.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return [], f"could not read {pinned}: {error}"

    resources = Path(__file__).resolve().parent / "resources"
    copies: list[PinnedCopy] = []
    seen: dict[Path, int] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if "\r" in line:
            return [], f"pinned.txt:{number}: \\r character in the line; save the file with LF line endings"
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if len(tokens) < 2:
            return [], f"pinned.txt:{number}: no destination path"
        source, dest = tokens[0], tokens[1]
        if source.startswith("kit:"):
            # As in gate.sh: a kit: line is joined with the resources directory, not the file system.
            src = resources / source[len("kit:"):].lstrip("/")
        elif Path(source).is_absolute():
            src = Path(source)
        else:
            src = ebt / source
        if not src.is_file():
            return [], f"pinned.txt:{number}: no original {src}"
        if Path(dest).is_absolute():
            return [], f"pinned.txt:{number}: absolute destination path is not allowed: {dest}"
        destination = (root / dest).resolve()
        if not destination.is_relative_to(root):
            return [], f"pinned.txt:{number}: destination path is outside the project: {dest}"
        if destination.is_dir():
            return [], f"pinned.txt:{number}: destination path is a directory: {dest}"
        if destination in seen:
            return [], (f"pinned.txt:{number}: destination path is already taken by line "
                        f"{seen[destination]}: {dest}")
        seen[destination] = number
        copies.append((number, src, dest, destination))
    return copies, None


def sync_pinned(argv):
    """Copy the originals from pinned.txt into the project; kit: means resources of this distribution."""
    usage = "usage: witnessbox sync-pinned <ebt-dir> [<project-root>]"
    if len(argv) not in (1, 2):
        print(usage, file=sys.stderr)
        return 2

    def fail(message):
        print(f"witnessbox sync-pinned: {message}", file=sys.stderr)
        return 2

    ebt = Path(argv[0]).expanduser().resolve()
    root = Path(argv[1] if len(argv) == 2 else ".").expanduser().resolve()
    copies, error = read_pinned(ebt, root)
    if error:
        return fail(error)

    # The first pass checked all lines: a failure before the first write leaves no half-made copies.
    for number, src, dest, destination in copies:
        try:
            same = destination.is_file() and destination.read_bytes() == src.read_bytes()
        except OSError as error:
            return fail(f"pinned.txt:{number}: could not compare {dest}: {error}")
        if same:
            print(f"unchanged {dest}")
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, destination)
        except OSError as error:
            return fail(f"pinned.txt:{number}: could not write {dest}: {error}")
        print(f"updated {dest}")
    return 0


def check_only(argv):
    """Check the setup before running tests; the gate still issues the verdict.

    Executes and changes nothing: prepare.sh and test.sh are not run. checks.py
    is imported as in the checker (it is trusted project code, docs/extensions.md).
    Codes: 0 no problems, 1 problems (the gate would not give PASS on this input), 2 usage error.
    """
    usage = "usage: witnessbox gate --check-only <ebt-dir> <clone>"
    if len(argv) != 2:
        print(usage, file=sys.stderr)
        return 2
    ebt = Path(argv[0]).expanduser().resolve()
    clone = Path(argv[1]).expanduser().resolve()
    for path, label in ((ebt, "checks"), (clone, "clone")):
        if not path.is_dir():
            print(f"witnessbox gate --check-only: no {label} directory {path}", file=sys.stderr)
            return 2

    # Importing the project checks.py must not leave __pycache__ in the checks directory:
    # the command promises not to change project files.
    sys.dont_write_bytecode = True
    from .checker.engine import missing_checkers
    from .checker.input import load_checkers, load_jsonl, load_known, load_spec, validate_known

    problems = 0

    def ok(name, note=""):
        print(f"ok {name}" + (f": {note}" if note else ""))

    def skip(name, reason):
        print(f"skipped {name}: {reason}")

    def problem(name, text):
        nonlocal problems
        problems += 1
        print(f"problem {name}: {' '.join(_printable(text).split())}")

    def git(*args):
        return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)

    # An external EBT_CHECK parses spec, checks.py, known and baseline itself: a local
    # check of their contents would report a problem the gate with it does not share.
    ebt_check = os.environ.get("EBT_CHECK", "")
    external = bool(ebt_check)
    external_ok = external and shutil.which(ebt_check) is not None

    # 1. spec: the file exists and (for the standard checker) its load_spec parses it.
    spec = None
    scope = None
    spec_path = ebt / "spec.toml"
    if not spec_path.is_file():
        problem("spec", f"no {spec_path}")
    elif external:
        skip("spec", f"EBT_CHECK={ebt_check}: the external checker verifies the contents")
    else:
        try:
            loaded, _ = load_spec(spec_path)
            raw_scope = os.environ.get("EBT_INV", "")
            if raw_scope:
                scope = [item.strip() for item in raw_scope.split(",") if item.strip()]
                unknown = [item for item in scope if item not in loaded["inv"]]
                if not scope or unknown:
                    raise ValueError(f"EBT_INV: not in spec: {', '.join(unknown) or '(empty)'}")
        except (OSError, ValueError) as error:
            problem("spec", error)
        else:
            spec = loaded
            ok("spec")

    # 2. checks: the extension loads, every checker in scope is registered.
    if external:
        if external_ok:
            skip("checks", f"EBT_CHECK={ebt_check}: the external checker verifies checks.py and registration")
        else:
            problem("checks", f"EBT_CHECK={ebt_check}: command not found")
    elif spec is None:
        skip("checks", "no spec loaded")
    else:
        checks_loaded = True
        checks_path = ebt / "checks.py"
        if checks_path.is_file():
            try:
                load_checkers(checks_path)
            except (OSError, ValueError) as error:
                problem("checks", error)
                checks_loaded = False
        if checks_loaded:
            missing = missing_checkers(spec, scope)
            if missing:
                details = ", ".join(f"{inv_id}: {spec['inv'][inv_id]['checker']}" for inv_id in missing)
                problem("checks", "checker is registered neither in the core nor in checks.py: " + details)
            else:
                ok("checks")

    # 3. known: the same parsing and the same check against witness as when the checker runs.
    known_path = ebt / "known.toml"
    if external:
        skip("known", f"EBT_CHECK={ebt_check}: the external checker verifies known.toml")
    elif not known_path.is_file():
        ok("known", "no known.toml")
    elif spec is None:
        skip("known", "no spec loaded")
    else:
        try:
            known = load_known(known_path)
            validate_known(known, spec)
        except (OSError, ValueError) as error:
            problem("known", error)
        else:
            ok("known")

    # 4. baseline: a broken baseline line is an error for the checker too, not a silent skip.
    baseline_path = ebt / "baseline.jsonl"
    if external:
        skip("baseline", f"EBT_CHECK={ebt_check}: the external checker verifies baseline.jsonl")
    elif not baseline_path.is_file():
        ok("baseline", "no baseline.jsonl")
    else:
        try:
            _, bad = load_jsonl(baseline_path)
        except (OSError, ValueError) as error:
            problem("baseline", error)
        else:
            if bad:
                problem("baseline", f"broken lines: {len(bad)}, first: {bad[0].line}")
            else:
                ok("baseline")

    # 5. runner: selection rules from gate.sh, without running the runner itself.
    runner = os.environ.get("EBT_RUNNER", "")
    test_sh = ebt / "test.sh"
    if runner not in ("", "test.sh", "flutter"):
        problem("runner", f"EBT_RUNNER={runner}: unknown runner (test.sh or flutter)")
    elif test_sh.exists() or test_sh.is_symlink():
        if not test_sh.is_file() or not os.access(test_sh, os.X_OK):
            problem("runner", f"test.sh exists but is not an executable file: {test_sh}")
        elif runner == "flutter":
            problem("runner", "EBT_RUNNER=flutter: the package contains test.sh; use EBT_RUNNER=test.sh")
        else:
            ok("runner")
    elif runner == "test.sh":
        problem("runner", f"no {test_sh}: add an executable test.sh or choose EBT_RUNNER=flutter")
    elif runner == "flutter":
        ok("runner")
    else:
        ok("runner", "legacy Flutter adapter")

    # 6. pinned: parsed by the gate rules (not the strict --sync-pinned rules),
    # comparison as cmp in preflight: a missing copy is drift, a read failure is a problem.
    pinned_path = ebt / "pinned.txt"
    if not pinned_path.is_file():
        ok("pinned", "no pinned.txt")
    else:
        copies, error = read_pinned(ebt, clone, gate_rules=True)
        if error:
            problem("pinned", error)
        else:
            drifted = []
            failed = False
            for number, src, dest, destination in copies:
                if destination is None:
                    drifted.append("(empty destination path)")
                    continue
                if not destination.exists() and not destination.is_symlink():
                    drifted.append(dest)
                    continue
                try:
                    if not destination.is_file() or destination.read_bytes() != src.read_bytes():
                        drifted.append(dest)
                except OSError as error:
                    problem("pinned", f"pinned.txt:{number}: could not compare {dest}: {error}")
                    failed = True
                    break
            if not failed:
                if drifted:
                    problem("pinned", "pinned copies differ from the original: " + ", ".join(drifted))
                else:
                    ok("pinned")

    # 7. clone: has a commit, clean tree and no hidden changes, as in preflight_git.
    # HEAD before status: without commits all files are untracked, and a "dirty tree" would hide the cause.
    def clone_problem() -> str | None:
        head = git("rev-parse", "-q", "--verify", "HEAD")
        if head.returncode:
            if git("rev-parse", "--git-dir").returncode == 0:
                return "the repository has no commits: the gate checks only committed files"
            return "git rev-parse HEAD failed: " + head.stderr.strip()
        status = git("status", "--porcelain")
        if status.returncode:
            return f"git status failed: {status.stderr.strip() or status.stdout.strip()}"
        if status.stdout.strip():
            return "the clone tree is not clean: " + status.stdout.splitlines()[0]
        tracked = git("ls-files", "-v")
        if tracked.returncode:
            return f"git ls-files failed: {tracked.stderr.strip() or tracked.stdout.strip()}"
        hidden = [line for line in tracked.stdout.splitlines()
                  if len(line) > 1 and line[1] == " " and (line[0] in "S" or line[0].islower())]
        if hidden:
            return "the clone has skip-worktree/assume-unchanged: " + hidden[0]
        return None

    try:
        message = clone_problem()
    except OSError as error:
        message = f"git failed: {error}"
    if message:
        problem("clone", message)
    else:
        ok("clone")

    # 8. base: without BASE protected paths are not checked, and the output says so explicitly.
    base = os.environ.get("BASE", "")
    if not base:
        skip("base", "BASE is not set: protected paths are not checked")
    else:
        try:
            commit = git("rev-parse", "-q", "--verify", f"{base}^{{commit}}")
            head = git("rev-parse", "-q", "--verify", "HEAD")
        except OSError as error:
            problem("base", f"git rev-parse failed: {error}")
        else:
            if commit.returncode:
                problem("base", f"BASE={base}: no such commit")
            elif head.returncode:
                problem("base", f"git rev-parse HEAD failed: {head.stderr.strip()}")
            else:
                try:
                    diff = git("diff", "--name-only", base, "HEAD", "--", "ebt", "tool/ebt_check")
                except OSError as error:
                    problem("base", f"git diff failed: {error}")
                else:
                    changed = [line for line in diff.stdout.splitlines() if line]
                    if diff.returncode:
                        problem("base", f"git diff from BASE failed: {diff.stderr.strip()}")
                    elif changed:
                        problem("base", "protected paths changed in the branch: " + ", ".join(changed))
                    else:
                        ok("base")

    return 1 if problems else 0


def test_checks(argv):
    """Run the test_*.py files of the checks directory with this distribution's interpreter."""
    usage = "usage: witnessbox test-checks [<ebt-dir>]"
    if len(argv) > 1:
        print(usage, file=sys.stderr)
        return 2
    ebt = Path(argv[0] if argv else "ebt").expanduser().resolve()
    if not ebt.is_dir():
        print(f"witnessbox test-checks: no directory {ebt}", file=sys.stderr)
        return 2
    command = [sys.executable, "-I", "-B", "-m", "unittest", "discover",
               "-s", str(ebt), "-t", str(ebt), "-p", "test_*.py", "-v"]
    p = subprocess.run(command, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    output = p.stdout + p.stderr
    match = re.search(r"^Ran (\d+) tests?\b", output, re.MULTILINE)
    if match is None or int(match.group(1)) == 0:
        print("witnessbox test-checks: no checker tests found; a zero-test run does not count as success",
              file=sys.stderr)
        return 1
    return p.returncode


USAGE = """usage: witnessbox <command> [<arguments>]

  gate <ebt-dir> <clone> <run-dir>              gate: project tests and evidence recomputation
  gate --check-only <ebt-dir> <clone>           setup check without running tests
  check --spec <spec.toml> --evidence <jsonl>…  checker (witnessbox check -h)
  scaffold <dart|ts|jvm|generic> [<ebt-dir>]    scaffold of ebt/
  sync-pinned <ebt-dir> [<project-root>]        copies from pinned.txt
  test-checks [<ebt-dir>]                       project checker tests
  --version | --installation"""

COMMANDS = {"scaffold": scaffold, "sync-pinned": sync_pinned, "test-checks": test_checks}


def main():
    command, argv = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else (None, [])
    if command == "check":
        # The checker argparse handles its help and argument parsing.
        from witnessbox.checker.cli import main as check
        return check(argv)
    if command in ("-h", "--help") or (command in (*COMMANDS, "gate") and argv[:1] in (["-h"], ["--help"])):
        print(USAGE)
        return 0
    if command in COMMANDS:
        return COMMANDS[command](argv)
    if command == "gate" and argv[:1] == ["--check-only"]:
        return check_only(argv[1:])
    if command in ("--version", "--installation"):
        if argv:
            print(f"usage: witnessbox {command}", file=sys.stderr)
            return 2
    elif command != "gate":
        if command is not None:
            print(f"witnessbox: unknown command {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    try:
        info = installation()
    except RuntimeError as error:
        print(f"witnessbox: {error}", file=sys.stderr)
        return 2
    if command == "--version":
        print(f"witnessbox {info['version']}")
        return 0
    if command == "--installation":
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    env = os.environ | {"EBT_VERIFICATION_PYTHON": sys.executable}
    os.execve("/bin/bash", ["bash", str(Path(info["package"]) / "gate.sh"), *argv], env)


if __name__ == "__main__":
    sys.exit(main())
