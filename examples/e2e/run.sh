#!/bin/bash
# EBT end-to-end example: scaffold → sync-pinned → PASS → defect → FAIL checker_failed.
#
#   examples/e2e/run.sh <ts|jvm|generic|dart> <example-dir>
#
# Builds a temporary git repository, overlays the scaffold and the example, runs
# the installed witnessbox gate command twice. The results directory is printed
# on failure and removed on success. Codes: 0 both expectations met; 1 an expectation
# not met; 2 environment error (no git, witnessbox, bun, gradle, flutter, python3).
set -uo pipefail

GRADLE_VERSION=9.8.2

usage() {
  echo "usage: $0 <ts|jvm|generic|dart> <example-dir>" >&2
  exit 2
}

[ $# -eq 2 ] || usage
stack=$1
example_arg=$2
case $stack in
  ts|jvm|generic|dart) ;;
  *) usage ;;
esac

example=$(cd "$example_arg" 2>/dev/null && pwd) || {
  echo "e2e: no example directory $example_arg" >&2
  exit 2
}

root=""
cleanup() {
  rc=$?
  [ -n "$root" ] || return 0
  if [ "$rc" -eq 0 ]; then
    rm -rf "$root"
  else
    echo "e2e $stack: results directory kept: $root" >&2
  fi
}
trap cleanup EXIT

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "e2e: $1 not found: $2" >&2
    exit 2
  }
}
need git "git is required"
need witnessbox "install witnessbox (uv tool install dist/witnessbox-*.whl)"
need python3 "python3 is required to parse gate.json"
case $stack in
  ts|generic) need bun "the TypeScript example needs Bun" ;;
  jvm) need gradle "Gradle is required to generate the wrapper"; need java "JDK 17 is required" ;;
  dart) need flutter "the Dart example needs the Flutter SDK" ;;
esac

root=$(mktemp -d "${TMPDIR:-/tmp}/witnessbox-e2e-${stack}.XXXXXX") || {
  echo "e2e: could not create a temporary directory" >&2
  exit 2
}
work="$root/repo"
logs="$root/logs"
mkdir -p "$work" "$logs" || exit 2

# The example is copied without defect/ and ebt/: the scaffold is created by the command, ebt/ is an overlay.
for entry in "$example"/*; do
  [ -e "$entry" ] || continue
  name=$(basename "$entry")
  [ "$name" = defect ] && continue
  [ "$name" = ebt ] && continue
  cp -R "$entry" "$work/" || { echo "e2e: could not copy $name" >&2; exit 2; }
done

# Generated dependencies and reports must not make the clone dirty for the second run.
cat > "$work/.gitignore" <<'EOF'
build/
node_modules/
.gradle/
.dart_tool/
pubspec.lock
EOF

(cd "$work" && witnessbox scaffold "$stack" ebt) >"$logs/scaffold.log" 2>&1 || {
  cat "$logs/scaffold.log" >&2
  echo "e2e: scaffold $stack failed" >&2
  exit 2
}
cp -R "$example/ebt/." "$work/ebt/" || {
  echo "e2e: could not overlay $example/ebt" >&2
  exit 2
}
[ ! -f "$work/ebt/prepare.sh" ] || chmod 755 "$work/ebt/prepare.sh"

if [ "$stack" = jvm ]; then
  (cd "$work" && gradle wrapper --gradle-version "$GRADLE_VERSION" --distribution-type bin) \
    >"$logs/wrapper.log" 2>&1 || {
    cat "$logs/wrapper.log" >&2
    echo "e2e: could not generate the Gradle wrapper $GRADLE_VERSION" >&2
    exit 2
  }
fi

(cd "$work" && witnessbox sync-pinned ebt) >"$logs/sync-pinned.log" 2>&1 || {
  cat "$logs/sync-pinned.log" >&2
  echo "e2e: sync-pinned failed" >&2
  exit 1
}

git -C "$work" init -q || exit 2
git -C "$work" config user.name "witnessbox-e2e" || exit 2
git -C "$work" config user.email "witnessbox-e2e@example.invalid" || exit 2
git -C "$work" add -A || exit 2
git -C "$work" commit -qm "e2e: scaffold, SDK and example" || exit 2
base=$(git -C "$work" rev-parse HEAD) || exit 2

(cd "$work" && witnessbox test-checks ebt) >"$logs/test-checks.log" 2>&1 || {
  cat "$logs/test-checks.log" >&2
  echo "e2e: test-checks failed" >&2
  exit 1
}
(cd "$work" && BASE="$base" witnessbox gate --check-only ebt .) >"$logs/check-only.log" 2>&1 || {
  cat "$logs/check-only.log" >&2
  echo "e2e: gate --check-only found a problem" >&2
  exit 1
}

# generic runs the same TS example: the test command is set by a variable.
if [ "$stack" = generic ]; then
  export EBT_TEST_CMD="bunx vitest run .ebt.test"
fi
unset EBT_RUNNER EBT_TESTS EBT_CHECK EBT_INV

run_gate() {
  run_dir=$1
  log=$2
  (cd "$work" && BASE="$base" witnessbox gate ebt . "$run_dir") >"$log" 2>&1
}

if ! run_gate "$logs/run1" "$logs/run1.log"; then
  cat "$logs/run1.log" >&2
  echo "e2e: the first run did not give PASS" >&2
  exit 1
fi
python3 -I - "$logs/run1/gate.json" <<'PY' || exit 1
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
if data.get("result") != "PASS":
    sys.exit(f"e2e: first run {data.get('result')}, expected PASS")
PY

cp -R "$example/defect/." "$work/" || { echo "e2e: could not overlay the defect" >&2; exit 2; }
git -C "$work" add -A || exit 2
git -C "$work" commit --allow-empty -qm "e2e: defect" || exit 2

run_gate "$logs/run2" "$logs/run2.log"
rc=$?
if [ "$rc" -ne 1 ]; then
  cat "$logs/run2.log" >&2
  echo "e2e: defect not detected: the second run returned $rc, expected 1 (FAIL)" >&2
  exit 1
fi
python3 -I - "$logs/run2/gate.json" <<'PY' || exit 1
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
reasons = data.get("reasons") or []
if data.get("result") != "FAIL":
    sys.exit(f"e2e: second run {data.get('result')}, expected FAIL")
if "checker_failed" not in reasons:
    sys.exit(f"e2e: no checker_failed in reasons: {reasons}")
if "protected_paths_changed" in reasons:
    sys.exit(f"e2e: the defect touched protected paths: {reasons}")
PY

echo "e2e $stack: scaffold → sync-pinned → PASS → defect → FAIL (checker_failed)"
exit 0
