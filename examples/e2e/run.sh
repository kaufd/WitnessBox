#!/bin/bash
# Сквозной пример EBT: заготовка → sync-pinned → PASS → дефект → FAIL checker_failed.
#
#   examples/e2e/run.sh <ts|jvm|generic> <example-dir>
#
# Собирает временный git-репозиторий, накладывает заготовку и пример, прогоняет
# установленную команду witnessbox gate дважды. Каталог результатов печатается
# при отказе и удаляется при успехе. Коды: 0 — оба ожидания выполнены; 1 — ожидание
# не выполнено; 2 — ошибка окружения (нет git, witnessbox, bun, gradle, python3).
set -uo pipefail

GRADLE_VERSION=9.8.2

usage() {
  echo "usage: $0 <ts|jvm|generic> <example-dir>" >&2
  exit 2
}

[ $# -eq 2 ] || usage
stack=$1
example_arg=$2
case $stack in
  ts|jvm|generic) ;;
  *) usage ;;
esac

example=$(cd "$example_arg" 2>/dev/null && pwd) || {
  echo "e2e: нет каталога примера $example_arg" >&2
  exit 2
}

root=""
cleanup() {
  rc=$?
  [ -n "$root" ] || return 0
  if [ "$rc" -eq 0 ]; then
    rm -rf "$root"
  else
    echo "e2e $stack: каталог результатов сохранён: $root" >&2
  fi
}
trap cleanup EXIT

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "e2e: не найден $1: $2" >&2
    exit 2
  }
}
need git "нужен git"
need witnessbox "установите witnessbox (uv tool install dist/witnessbox-*.whl)"
need python3 "нужен python3 для разбора gate.json"
case $stack in
  ts|generic) need bun "примеру TypeScript нужен Bun" ;;
  jvm) need gradle "нужен Gradle для генерации wrapper"; need java "нужен JDK 17" ;;
esac

root=$(mktemp -d "${TMPDIR:-/tmp}/witnessbox-e2e-${stack}.XXXXXX") || {
  echo "e2e: не удалось создать временный каталог" >&2
  exit 2
}
work="$root/repo"
logs="$root/logs"
mkdir -p "$work" "$logs" || exit 2

# Пример копируется без defect/ и ebt/: заготовка создаётся командой, ebt/ — наложение.
for entry in "$example"/*; do
  [ -e "$entry" ] || continue
  name=$(basename "$entry")
  [ "$name" = defect ] && continue
  [ "$name" = ebt ] && continue
  cp -R "$entry" "$work/" || { echo "e2e: не удалось скопировать $name" >&2; exit 2; }
done

# Сгенерированные зависимости и отчёты не должны делать клон грязным для второго прогона.
cat > "$work/.gitignore" <<'EOF'
build/
node_modules/
.gradle/
EOF

(cd "$work" && witnessbox scaffold "$stack" ebt) >"$logs/scaffold.log" 2>&1 || {
  cat "$logs/scaffold.log" >&2
  echo "e2e: scaffold $stack упал" >&2
  exit 2
}
cp -R "$example/ebt/." "$work/ebt/" || {
  echo "e2e: не удалось наложить $example/ebt" >&2
  exit 2
}
[ ! -f "$work/ebt/prepare.sh" ] || chmod 755 "$work/ebt/prepare.sh"

if [ "$stack" = jvm ]; then
  (cd "$work" && gradle wrapper --gradle-version "$GRADLE_VERSION" --distribution-type bin) \
    >"$logs/wrapper.log" 2>&1 || {
    cat "$logs/wrapper.log" >&2
    echo "e2e: не удалось сгенерировать Gradle wrapper $GRADLE_VERSION" >&2
    exit 2
  }
fi

(cd "$work" && witnessbox sync-pinned ebt) >"$logs/sync-pinned.log" 2>&1 || {
  cat "$logs/sync-pinned.log" >&2
  echo "e2e: sync-pinned не прошёл" >&2
  exit 1
}

git -C "$work" init -q || exit 2
git -C "$work" config user.name "witnessbox-e2e" || exit 2
git -C "$work" config user.email "witnessbox-e2e@example.invalid" || exit 2
git -C "$work" add -A || exit 2
git -C "$work" commit -qm "e2e: заготовка, SDK и пример" || exit 2
base=$(git -C "$work" rev-parse HEAD) || exit 2

(cd "$work" && witnessbox test-checks ebt) >"$logs/test-checks.log" 2>&1 || {
  cat "$logs/test-checks.log" >&2
  echo "e2e: test-checks не прошёл" >&2
  exit 1
}
(cd "$work" && BASE="$base" witnessbox gate --check-only ebt .) >"$logs/check-only.log" 2>&1 || {
  cat "$logs/check-only.log" >&2
  echo "e2e: gate --check-only нашёл проблему" >&2
  exit 1
}

# generic запускает тот же TS-пример: команда тестов задаётся переменной.
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
  echo "e2e: первый прогон не дал PASS" >&2
  exit 1
fi
python3 -I - "$logs/run1/gate.json" <<'PY' || exit 1
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
if data.get("result") != "PASS":
    sys.exit(f"e2e: первый прогон {data.get('result')}, ожидался PASS")
PY

cp -R "$example/defect/." "$work/" || { echo "e2e: не удалось наложить дефект" >&2; exit 2; }
git -C "$work" add -A || exit 2
git -C "$work" commit --allow-empty -qm "e2e: дефект" || exit 2

run_gate "$logs/run2" "$logs/run2.log"
rc=$?
if [ "$rc" -ne 1 ]; then
  cat "$logs/run2.log" >&2
  echo "e2e: дефект не обнаружен — второй прогон вернул $rc, ожидался 1 (FAIL)" >&2
  exit 1
fi
python3 -I - "$logs/run2/gate.json" <<'PY' || exit 1
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
reasons = data.get("reasons") or []
if data.get("result") != "FAIL":
    sys.exit(f"e2e: второй прогон {data.get('result')}, ожидался FAIL")
if "checker_failed" not in reasons:
    sys.exit(f"e2e: в reasons нет checker_failed: {reasons}")
if "protected_paths_changed" in reasons:
    sys.exit(f"e2e: дефект задел защищённые пути: {reasons}")
PY

echo "e2e $stack: заготовка → sync-pinned → PASS → дефект → FAIL (checker_failed)"
exit 0
