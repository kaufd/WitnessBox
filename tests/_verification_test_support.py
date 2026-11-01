"""Сборка поставки и установка wheel для интеграционных тестов гейта."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

KIT = Path(__file__).resolve().parents[1]


def install_verification():
    """sdist → wheel из sdist → установка в чистый venv.

    Wheel собирается только из извлечённого sdist: устаревший build/lib рабочего
    дерева в него не попадает, а проверка видит ровно то, что поставляется архивом.
    Возвращает (временный каталог, bin venv, wheel, sdist).
    """
    tmp = tempfile.TemporaryDirectory(prefix="witnessbox-installed-test-")
    root = Path(tmp.name)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    uv = shutil.which("uv")
    if not uv:
        tmp.cleanup()
        raise RuntimeError("Для проверки установки нужен uv (сборка wheel и изолированный venv)")
    dist = root / "dist"
    commands = [
        [uv, "build", "--sdist", str(KIT), "--out-dir", str(dist)],
        [uv, "venv", "--python", sys.executable, str(root / "venv")],
    ]
    for cmd in commands:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if p.returncode:
            tmp.cleanup()
            raise RuntimeError(f"{cmd}:\n{p.stdout}\n{p.stderr}")
    sdist = next(dist.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        archive.extractall(root / "sdist", filter="data")
    tree = next((root / "sdist").iterdir())
    p = subprocess.run([uv, "build", "--wheel", str(tree), "--out-dir", str(dist)],
                       env=env, capture_output=True, text=True)
    if p.returncode:
        tmp.cleanup()
        raise RuntimeError(f"wheel из sdist:\n{p.stdout}\n{p.stderr}")
    wheel = next(dist.glob("*.whl"))
    p = subprocess.run([uv, "pip", "install", "--python", str(root / "venv/bin/python"),
                        "--no-index", str(wheel)], env=env, capture_output=True, text=True)
    if p.returncode:
        tmp.cleanup()
        raise RuntimeError(p.stdout + p.stderr)
    return tmp, root / "venv/bin", wheel, sdist
