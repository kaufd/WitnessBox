"""Build and install the package wheel for installed-gate integration tests."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

KIT = Path(__file__).resolve().parents[1]


def install_verification():
    tmp = tempfile.TemporaryDirectory(prefix="ebt-installed-test-")
    root = Path(tmp.name)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    uv = shutil.which("uv")
    if not uv:
        tmp.cleanup()
        raise RuntimeError("Для проверки установки нужен uv (сборка wheel и изолированный venv)")
    commands = [
        # sdist → wheel: устаревший build/lib дерева разработки в wheel не попадёт.
        [uv, "build", str(KIT), "--out-dir", str(root / "dist")],
        [uv, "venv", "--python", sys.executable, str(root / "venv")],
    ]
    for cmd in commands:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if p.returncode:
            tmp.cleanup()
            raise RuntimeError(f"{cmd}:\n{p.stdout}\n{p.stderr}")
    wheel = next((root / "dist").glob("*.whl"))
    p = subprocess.run([uv, "pip", "install", "--python", str(root / "venv/bin/python"),
                        "--no-index", str(wheel)], env=env, capture_output=True, text=True)
    if p.returncode:
        tmp.cleanup()
        raise RuntimeError(p.stdout + p.stderr)
    return tmp, root / "venv/bin", wheel
