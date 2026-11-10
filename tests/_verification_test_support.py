"""Building the distribution and installing the wheel for the gate integration tests."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

KIT = Path(__file__).resolve().parents[1]


def install_verification():
    """sdist → wheel from the sdist → installation into a clean venv.

    `uv build` without flags builds the sdist, and the wheel from it, so a stale
    build/lib of the working tree does not get into the distribution. Returns (temp directory,
    bin venv, wheel, sdist).
    """
    tmp = tempfile.TemporaryDirectory(prefix="witnessbox-installed-test-")
    root = Path(tmp.name)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    uv = shutil.which("uv")
    if not uv:
        tmp.cleanup()
        raise RuntimeError("uv is required to check the installation (wheel build and an isolated venv)")
    dist = root / "dist"
    commands = [
        [uv, "build", str(KIT), "--out-dir", str(dist)],
        [uv, "venv", "--python", sys.executable, str(root / "venv")],
    ]
    for cmd in commands:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if p.returncode:
            tmp.cleanup()
            raise RuntimeError(f"{cmd}:\n{p.stdout}\n{p.stderr}")
    wheel, sdist = next(dist.glob("*.whl")), next(dist.glob("*.tar.gz"))
    p = subprocess.run([uv, "pip", "install", "--python", str(root / "venv/bin/python"),
                        "--no-index", str(wheel)], env=env, capture_output=True, text=True)
    if p.returncode:
        tmp.cleanup()
        raise RuntimeError(p.stdout + p.stderr)
    return tmp, root / "venv/bin", wheel, sdist
