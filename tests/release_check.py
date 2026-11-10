"""Distribution release check: make release-check.

1. Builds the sdist and a wheel from it (not from the working tree).
2. From the extracted sdist runs make test and make example (and make test-sdk, if
   bun, javac and dart are present): the sdist is self-contained and passes the tests.
3. Builds a wheel from the sdist and compares its contents with the release one.
4. Installs the release wheel into a clean venv without an index and PYTHONPATH, checks the distribution,
   the version and the compatible import of the installation.
5. Writes build/release/<version>/release.json with the version, artifact SHA-256 and results.
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
        raise SystemExit(f"expected one file, found: {found}")
    return found[0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(wheel: Path) -> dict:
    """Package files without .dist-info: build metadata may differ, the code may not."""
    with zipfile.ZipFile(wheel) as z:
        return {name: z.read(name) for name in z.namelist() if ".dist-info/" not in name}


def main() -> int:
    uv = shutil.which("uv") or sys.exit("uv is required")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    out = ROOT / "build/release" / version
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    # Without --wheel uv builds the wheel from the sdist: a stale build/lib of the working tree will not get into it.
    run([uv, "build", "--out-dir", out / "dist", ROOT])
    wheel, sdist = single((out / "dist").glob("*.whl")), single((out / "dist").glob("*.tar.gz"))

    with tarfile.open(sdist) as archive:
        # filter= appeared in 3.11.4; on 3.11.0–3.11.3 we unpack our own sdist without it.
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
    installation = json.loads(subprocess.check_output([str(venv / "bin/witnessbox"), "--installation"], env=ENV))
    identity = subprocess.run(
        [str(venv / "bin/python"), "-I", "-c",
         "from witnessbox.api import Verdict; "
         "from ebt_verification.api import Verdict as Compatible; "
         "assert Compatible is Verdict"],
        env=ENV, capture_output=True, text=True)
    if identity.returncode:
        # Without this, on FAIL only the flag is visible: the cause stays in the captured output.
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
        "sdist_tests": "make test example" + (" test-sdk" if sdk else "; test-sdk skipped: no bun or javac"),
        "sdist_wheel_payload_identical": payload_identical,
    }
    if identity.returncode:
        release["compat_import_error"] = (identity.stdout + identity.stderr).strip() or f"exit {identity.returncode}"
    (out / "release.json").write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wheel from the sdist matched the release one: {payload_identical}")
    print(f"\nrelease-check {version}: {release['result']} → {out / 'release.json'}")
    print(f"wheel {release['wheel']['sha256']}\nsdist {release['sdist']['sha256']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
