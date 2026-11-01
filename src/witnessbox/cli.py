"""Публичный вход гейта; все runtime-пути принадлежат этой установке."""

import hashlib
import json
import os
from importlib.metadata import distribution
from pathlib import Path
import shutil
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
    print("скопируйте SDK из ebt-gate --installation (resources/lib/ebt/) по путям pinned.txt")
    print("и напишите тесты свидетельств в build/ebt/. Подробности — в README.md каталога.")
    return 0


def main():
    if sys.argv[1:2] == ["--scaffold"]:
        return scaffold(sys.argv[2:])
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
