"""Публичный вход гейта; все runtime-пути принадлежат этой установке."""

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
    """(root, paths) поставляемого кода: RECORD, а для editable — обход дерева.

    RECORD задан относительно dist.locate_file(""), а не package.parent. В editable
    установке и при запуске из src через PYTHONPATH в RECORD лежат только .pth и
    finder-файлы, а исходников пакета там нет: такой RECORD непригоден, и тогда
    отпечаток строится обходом дерева.
    """
    files = dist.files or ()
    root = Path(dist.locate_file("")).resolve()
    # RECORD пригоден, только если он описывает исполняемый пакет. При PYTHONPATH=src
    # рядом с установленным wheel метаданные есть, но package лежит вне их корня.
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
    # scaffold — данные для нового проекта, а не код проверки: его правка не меняет
    # удостоверение установленного гейта. Поэтому каталог исключён из fingerprint.
    code = [path for path in installed
            if path.suffix in (".py", ".sh") and "scaffold" not in path.parts]
    cli = Path(__file__).resolve()
    modules = [path for path in code if path.suffix == ".py" and path.resolve() != cli]
    shell_files = [path for path in code if path.suffix == ".sh"]
    if not modules or not shell_files:
        # Пустой или неполный набор файлов дал бы постоянный SHA пустого ввода:
        # молчаливое «удостоверение», которое ничего не удостоверяет.
        raise RuntimeError(
            "installation: пустой отпечаток кода witnessbox "
            f"(python={len(modules)}, shell={len(shell_files)}); проверьте установку пакета")
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
    """gate.json — машиночитаемый итог попытки гейта, формат 1; запись атомарная."""
    run, spec, exit_code = Path(run), Path(spec), int(exit_code)
    info = installation()
    evidence = None
    if check_rc:
        # simplicity: хеш снят при записи итога, а не при чтении чекером; правка файла
        # между ними не видна (граница D26). Точнее — хешировать в load_jsonl.
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


SCAFFOLD_STACKS = ("dart", "ts", "jvm")
SCAFFOLD_FILES = ("spec.toml", "checks.py", "test_checks.py", "README.md")


def _copy_scaffold(sources, target):
    """Скопировать шаблоны в пустой каталог; при ошибке убрать уже созданные файлы."""
    copied = []
    try:
        for name, source in sources.items():
            # Имя запоминаем до копирования: неудачная запись могла оставить часть файла.
            copied.append(name)
            shutil.copyfile(source, target / name)
        (target / "test.sh").chmod(0o755)
    except OSError:
        for name in copied:
            (target / name).unlink(missing_ok=True)
        raise


def scaffold(argv):
    """Заготовка ebt/: шаблоны spec, checks.py, test.sh выбранного стека и pinned.txt."""
    usage = "usage: ebt-gate --scaffold <dart|ts|jvm> [<ebt-dir>]"
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
        print("ebt-gate --scaffold: в поставке нет файлов шаблона: " + ", ".join(missing), file=sys.stderr)
        return 2
    # Утверждённую спецификацию и чужие файлы заготовка не перезаписывает (D4).
    existing = target.exists() or target.is_symlink()
    if existing and (target.is_symlink() or not target.is_dir() or any(target.iterdir())):
        print(f"ebt-gate --scaffold: {target} уже существует и не пуст; файлы не перезаписаны", file=sys.stderr)
        return 2
    # Нормализуем до создания временного каталога: `--scaffold ts .` — это текущий
    # каталог, а не временный каталог внутри него.
    target = target.resolve()

    if existing:
        # Существующий пустой каталог (в том числе `.`) заполняем на месте; удалять его нельзя.
        try:
            _copy_scaffold(sources, target)
        except OSError as error:
            print(f"ebt-gate --scaffold: не удалось создать {target}: {error}", file=sys.stderr)
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
            print(f"ebt-gate --scaffold: не удалось создать {target}: {error}", file=sys.stderr)
            return 2

    print(f"Создана заготовка ebt/ ({stack}) в {target}:")
    for name in sources:
        print(f"  {name}")
    print("Дальше: замените пример REQ-EXAMPLE-1/INV-EXAMPLE-1 утверждённым требованием,")
    print("скопируйте SDK и помощников по pinned.txt командой ebt-gate --sync-pinned ebt")
    print("из корня проекта и напишите тесты свидетельств в build/ebt/.")
    print("Подробности — в README.md каталога.")
    return 0


PinnedCopy = tuple[int, Path, str, Path]


def read_pinned(ebt: Path, root: Path) -> tuple[list[PinnedCopy], str | None]:
    """Разобрать pinned.txt: (копии, первая ошибка). Ошибка — текст без префикса команды.

    Первый проход ничего не пишет: отказ до первой записи не оставит половину копий.
    Формат тот же, что у гейта: пустые строки и строки с `#` пропускаются, первый токен —
    оригинал (`kit:` — ресурсы этой поставки, абсолютный — как есть, иначе рядом с ebt/),
    второй — путь в проекте. Возвращает (номер строки, оригинал, dest, разрешённый путь).
    """
    pinned = ebt / "pinned.txt"
    if not pinned.is_file():
        return [], f"нет pinned.txt: {pinned}"
    # Читаем байты, а не текст с универсальными переводами строк: CRLF иначе исчезнет,
    # и команда молча запишет копию не туда, куда её ищет гейт (`sdk/Ebt.java\r`).
    try:
        text = pinned.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return [], f"не удалось прочитать {pinned}: {error}"

    resources = Path(__file__).resolve().parent / "resources"
    copies: list[PinnedCopy] = []
    seen: dict[Path, int] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if "\r" in line:
            return [], f"pinned.txt:{number}: символ \\r в строке; сохраните файл с переводами строк LF"
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if len(tokens) < 2:
            return [], f"pinned.txt:{number}: нет пути назначения"
        source, dest = tokens[0], tokens[1]
        if source.startswith("kit:"):
            # Как в gate.sh: строка kit: склеивается с каталогом ресурсов, а не с файловой системой.
            src = resources / source[len("kit:"):].lstrip("/")
        elif Path(source).is_absolute():
            src = Path(source)
        else:
            src = ebt / source
        if not src.is_file():
            return [], f"pinned.txt:{number}: нет оригинала {src}"
        if Path(dest).is_absolute():
            return [], f"pinned.txt:{number}: абсолютный путь назначения не разрешён: {dest}"
        destination = (root / dest).resolve()
        if not destination.is_relative_to(root):
            return [], f"pinned.txt:{number}: путь назначения вне проекта: {dest}"
        if destination.is_dir():
            return [], f"pinned.txt:{number}: путь назначения — каталог: {dest}"
        if destination in seen:
            return [], (f"pinned.txt:{number}: путь назначения уже занят строкой "
                        f"{seen[destination]}: {dest}")
        seen[destination] = number
        copies.append((number, src, dest, destination))
    return copies, None


def sync_pinned(argv):
    """Скопировать в проект оригиналы из pinned.txt; kit: — ресурсы этой поставки."""
    usage = "usage: ebt-gate --sync-pinned <ebt-dir> [<project-root>]"
    if len(argv) not in (1, 2):
        print(usage, file=sys.stderr)
        return 2

    def fail(message):
        print(f"ebt-gate --sync-pinned: {message}", file=sys.stderr)
        return 2

    ebt = Path(argv[0]).expanduser().resolve()
    root = Path(argv[1] if len(argv) == 2 else ".").expanduser().resolve()
    copies, error = read_pinned(ebt, root)
    if error:
        return fail(error)

    # Первый проход проверил все строки: отказ до первой записи не оставит половину копий.
    for number, src, dest, destination in copies:
        try:
            same = destination.is_file() and destination.read_bytes() == src.read_bytes()
        except OSError as error:
            return fail(f"pinned.txt:{number}: не удалось сравнить {dest}: {error}")
        if same:
            print(f"без изменений {dest}")
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, destination)
        except OSError as error:
            return fail(f"pinned.txt:{number}: не удалось записать {dest}: {error}")
        print(f"обновлён {dest}")
    return 0


def check_only(argv):
    """Проверить подключение до прогона тестов; вердикт всё равно выносит гейт.

    Ничего не исполняет и не меняет: prepare.sh и test.sh не запускаются. checks.py
    импортируется так же, как в чекере (это доверенный проектный код, docs/extensions.md).
    Коды: 0 — проблем нет, 1 — проблемы (гейт на этом входе не даст PASS), 2 — ошибка вызова.
    """
    usage = "usage: ebt-gate --check-only <ebt-dir> <clone>"
    if len(argv) != 2:
        print(usage, file=sys.stderr)
        return 2
    ebt = Path(argv[0]).expanduser().resolve()
    clone = Path(argv[1]).expanduser().resolve()
    for path, label in ((ebt, "проверки"), (clone, "клона")):
        if not path.is_dir():
            print(f"ebt-gate --check-only: нет каталога {label} {path}", file=sys.stderr)
            return 2

    from .checker.checkers import CHECKERS
    from .checker.input import load_checkers, load_jsonl, load_known, load_spec, validate_known

    problems = 0

    def ok(name, note=""):
        print(f"ок {name}" + (f": {note}" if note else ""))

    def skip(name, reason):
        print(f"пропущено {name}: {reason}")

    def problem(name, text):
        nonlocal problems
        problems += 1
        print(f"проблема {name}: {' '.join(str(text).split())}")

    def git(*args):
        return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)

    # 1. spec: файл есть и разбирается теми же load_spec, что у чекера.
    spec = None
    spec_path = ebt / "spec.toml"
    if not spec_path.is_file():
        problem("spec", f"нет {spec_path}")
    else:
        try:
            spec, _ = load_spec(spec_path)
        except (OSError, ValueError) as error:
            problem("spec", error)
        else:
            ok("spec")

    # 2. checks: расширение загружается, каждый checker из spec зарегистрирован.
    if spec is None:
        skip("checks", "нет загруженной спецификации")
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
            missing = sorted({inv["checker"] for inv in spec["inv"].values()} - set(CHECKERS))
            if missing:
                problem("checks", "чекер не зарегистрирован ни в ядре, ни в checks.py: "
                        + ", ".join(missing))
            else:
                ok("checks")

    # 3. known: тот же разбор и та же сверка с witness, что при запуске чекера.
    known_path = ebt / "known.toml"
    if not known_path.is_file():
        ok("known", "нет known.toml")
    elif spec is None:
        skip("known", "нет загруженной спецификации")
    else:
        try:
            known = load_known(known_path)
            validate_known(known, spec)
        except (OSError, ValueError) as error:
            problem("known", error)
        else:
            ok("known")

    # 4. baseline: битая строка в baseline — ошибка и у чекера, а не тихий пропуск.
    baseline_path = ebt / "baseline.jsonl"
    if not baseline_path.is_file():
        ok("baseline", "нет baseline.jsonl")
    else:
        try:
            _, bad = load_jsonl(baseline_path)
        except (OSError, ValueError) as error:
            problem("baseline", error)
        else:
            if bad:
                problem("baseline", f"битых строк: {len(bad)}, первая — {bad[0].line}")
            else:
                ok("baseline")

    # 5. runner: правила выбора из gate.sh, без запуска самого runner.
    runner = os.environ.get("EBT_RUNNER", "")
    test_sh = ebt / "test.sh"
    if runner not in ("", "test.sh", "flutter"):
        problem("runner", f"EBT_RUNNER={runner}: неизвестный runner (test.sh или flutter)")
    elif test_sh.exists() or test_sh.is_symlink():
        if not test_sh.is_file() or not os.access(test_sh, os.X_OK):
            problem("runner", f"test.sh существует, но не является исполняемым файлом: {test_sh}")
        elif runner == "flutter":
            problem("runner", "EBT_RUNNER=flutter: пакет содержит test.sh; используйте EBT_RUNNER=test.sh")
        else:
            ok("runner")
    elif runner == "test.sh":
        problem("runner", f"нет {test_sh}: добавьте исполняемый test.sh или выберите EBT_RUNNER=flutter")
    elif runner == "flutter":
        ok("runner")
    else:
        ok("runner", "legacy Flutter adapter")

    # 6. pinned: разбор общий с --sync-pinned, сравнение — как в preflight гейта.
    pinned_path = ebt / "pinned.txt"
    if not pinned_path.is_file():
        ok("pinned", "нет pinned.txt")
    else:
        copies, error = read_pinned(ebt, clone)
        if error:
            problem("pinned", error)
        else:
            drifted = []
            try:
                for _, src, dest, destination in copies:
                    if not destination.is_file() or destination.read_bytes() != src.read_bytes():
                        drifted.append(dest)
            except OSError as error:
                problem("pinned", error)
            else:
                if drifted:
                    problem("pinned", "закреплённые копии отличаются от оригинала: " + ", ".join(drifted))
                else:
                    ok("pinned")

    # 7. clone: чистое дерево и отсутствие скрытых правок — как в preflight_git.
    try:
        status = git("status", "--porcelain")
    except OSError as error:
        problem("clone", f"git status упал: {error}")
    else:
        if status.returncode:
            problem("clone", f"git status упал: {status.stderr.strip() or status.stdout.strip()}")
        elif status.stdout.strip():
            problem("clone", "дерево клона не чистое: " + status.stdout.splitlines()[0])
        else:
            try:
                tracked = git("ls-files", "-v")
            except OSError as error:
                problem("clone", f"git ls-files упал: {error}")
            else:
                hidden = [line for line in tracked.stdout.splitlines()
                          if len(line) > 1 and line[1] == " " and (line[0] in "S" or line[0].islower())]
                if tracked.returncode:
                    problem("clone", f"git ls-files упал: {tracked.stderr.strip() or tracked.stdout.strip()}")
                elif hidden:
                    problem("clone", "в клоне есть skip-worktree/assume-unchanged: " + hidden[0])
                else:
                    ok("clone")

    # 8. base: без BASE защищённые пути не проверяются, и вывод говорит об этом явно.
    base = os.environ.get("BASE", "")
    if not base:
        skip("base", "BASE не задан — защищённые пути не проверяются")
    else:
        try:
            commit = git("rev-parse", "-q", "--verify", f"{base}^{{commit}}")
            head = git("rev-parse", "-q", "--verify", "HEAD")
        except OSError as error:
            problem("base", f"git rev-parse упал: {error}")
        else:
            if commit.returncode:
                problem("base", f"BASE={base}: такого коммита нет")
            elif head.returncode:
                problem("base", f"git rev-parse HEAD упал: {head.stderr.strip()}")
            else:
                try:
                    diff = git("diff", "--name-only", base, "HEAD", "--", "ebt", "tool/ebt_check")
                except OSError as error:
                    problem("base", f"git diff упал: {error}")
                else:
                    changed = [line for line in diff.stdout.splitlines() if line]
                    if diff.returncode:
                        problem("base", f"git diff от BASE упал: {diff.stderr.strip()}")
                    elif changed:
                        problem("base", "в ветке изменены защищённые пути: " + ", ".join(changed))
                    else:
                        ok("base")

    return 1 if problems else 0


def test_checks(argv):
    """Запустить test_*.py каталога проверки интерпретатором этой поставки."""
    usage = "usage: ebt-gate --test-checks [<ebt-dir>]"
    if len(argv) > 1:
        print(usage, file=sys.stderr)
        return 2
    ebt = Path(argv[0] if argv else "ebt").expanduser().resolve()
    if not ebt.is_dir():
        print(f"ebt-gate --test-checks: нет каталога {ebt}", file=sys.stderr)
        return 2
    command = [sys.executable, "-I", "-m", "unittest", "discover",
               "-s", str(ebt), "-t", str(ebt), "-p", "test_*.py", "-v"]
    p = subprocess.run(command, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    output = p.stdout + p.stderr
    match = re.search(r"^Ran (\d+) tests?\b", output, re.MULTILINE)
    if match is None or int(match.group(1)) == 0:
        print("ebt-gate --test-checks: тестов чекера не найдено — нулевой прогон не считается успехом",
              file=sys.stderr)
        return 1
    return p.returncode


def main():
    if sys.argv[1:2] == ["--scaffold"]:
        return scaffold(sys.argv[2:])
    if sys.argv[1:2] == ["--sync-pinned"]:
        return sync_pinned(sys.argv[2:])
    if sys.argv[1:2] == ["--check-only"]:
        return check_only(sys.argv[2:])
    if sys.argv[1:2] == ["--test-checks"]:
        return test_checks(sys.argv[2:])
    try:
        info = installation()
    except RuntimeError as error:
        print(f"ebt-gate: {error}", file=sys.stderr)
        return 2
    if sys.argv[1:] == ["--version"]:
        print(f"witnessbox {info['version']}")
        return 0
    if sys.argv[1:] == ["--installation"]:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    env = os.environ | {"EBT_VERIFICATION_PYTHON": sys.executable}
    os.execve("/bin/bash", ["bash", str(Path(info["package"]) / "gate.sh"), *sys.argv[1:]], env)


if __name__ == "__main__":
    sys.exit(main())
