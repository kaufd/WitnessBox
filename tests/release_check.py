"""Проверка выпуска поставки: make release-check.

1. Собирает sdist и wheel из него (не из рабочего дерева).
2. Из извлечённого sdist запускает make test и make example (и make test-sdk, если есть
   bun, javac и dart): sdist самодостаточен и проходит тесты.
3. Собирает wheel из sdist и сравнивает его содержимое с выпускным.
4. Ставит выпускной wheel в чистый venv без индекса и PYTHONPATH, сверяет дистрибутив,
   версию и совместимый импорт установки.
5. Пишет build/release/<version>/release.json с версией, SHA-256 артефактов и итогами.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}


def run(cmd, cwd=None):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, env=ENV, check=True)


def single(paths):
    found = list(paths)
    if len(found) != 1:
        raise SystemExit(f"ожидался один файл, найдено: {found}")
    return found[0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(wheel: Path) -> dict:
    """Файлы пакета без .dist-info: метаданные сборки могут отличаться, код — нет."""
    with zipfile.ZipFile(wheel) as z:
        return {name: z.read(name) for name in z.namelist() if ".dist-info/" not in name}


def main() -> int:
    uv = shutil.which("uv") or sys.exit("нужен uv")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    out = ROOT / "build/release" / version
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    # Без --wheel uv собирает wheel из sdist: устаревший build/lib рабочего дерева в него не попадёт.
    run([uv, "build", "--out-dir", out / "dist", ROOT])
    wheel, sdist = single((out / "dist").glob("*.whl")), single((out / "dist").glob("*.tar.gz"))

    with tarfile.open(sdist) as archive:
        # filter= появился в 3.11.4; на 3.11.0–3.11.3 распаковываем свой же sdist без него.
        if hasattr(tarfile, "data_filter"):
            archive.extractall(out / "sdist", filter="data")
        else:
            archive.extractall(out / "sdist")
    tree = single((out / "sdist").iterdir())
    run(["make", "test", "example"], cwd=tree)
    sdk = bool(shutil.which("bun") and shutil.which("javac") and shutil.which("dart"))
    if sdk:
        run(["make", "test-sdk"], cwd=tree)
    run([uv, "build", "--wheel", "--out-dir", out / "rebuilt", tree])
    payload_identical = payload(wheel) == payload(single((out / "rebuilt").glob("*.whl")))

    venv = out / "venv"
    run([uv, "venv", "--python", sys.executable, venv])
    run([uv, "pip", "install", "--python", venv / "bin/python", "--no-index", wheel])
    installation = json.loads(subprocess.check_output([str(venv / "bin/ebt-gate"), "--installation"], env=ENV))
    identity = subprocess.run(
        [str(venv / "bin/python"), "-I", "-c",
         "from witnessbox.api import Verdict; "
         "from ebt_verification.api import Verdict as Compatible; "
         "assert Compatible is Verdict"],
        env=ENV, capture_output=True, text=True)
    if identity.returncode:
        # Без этого при FAIL виден только флаг: причина остаётся в захваченном выводе.
        sys.stderr.write(identity.stdout + identity.stderr)
        sys.stderr.flush()

    ok = (payload_identical and identity.returncode == 0
          and installation["distribution"] == "witnessbox" and installation["version"] == version)
    release = {
        "version": version,
        "result": "PASS" if ok else "FAIL",
        "wheel": {"file": wheel.name, "sha256": sha256(wheel)},
        "sdist": {"file": sdist.name, "sha256": sha256(sdist)},
        "installation": {k: installation[k] for k in ("distribution", "version", "gate_sha256", "checker_sha256")},
        "compat_import": identity.returncode == 0,
        "sdist_tests": "make test example" + (" test-sdk" if sdk else "; test-sdk пропущен: нет bun или javac"),
        "sdist_wheel_payload_identical": payload_identical,
    }
    if identity.returncode:
        release["compat_import_error"] = (identity.stdout + identity.stderr).strip() or f"exit {identity.returncode}"
    (out / "release.json").write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wheel из sdist совпал с выпускным: {payload_identical}")
    print(f"\nrelease-check {version}: {release['result']} → {out / 'release.json'}")
    print(f"wheel {release['wheel']['sha256']}\nsdist {release['sdist']['sha256']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
