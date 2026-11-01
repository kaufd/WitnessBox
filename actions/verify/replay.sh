#!/bin/bash
# replay.sh — test.sh доверенной стадии: отдаёт свидетельства из артефакта первой стадии
# и ничего не запускает. Артефакт недоверенный: symlink и не обычные файлы отвергаются.
#
# EBT_REPLAY_DIR — абсолютный каталог распакованного артефакта (out/*.jsonl, gate.json).
# OUT_DIR — обычный контракт test.sh: пустой абсолютный каталог результатов.
# Код выхода — tests_exit_code из gate.json (только целые 0 или 1), иначе 2.
set -u

fail() {
  echo "replay.sh: $*" >&2
  exit 2
}

artifact=${EBT_REPLAY_DIR:-}
[ -n "$artifact" ] || fail "EBT_REPLAY_DIR не задана"
case $artifact in
  /*) ;;
  *) fail "EBT_REPLAY_DIR должна быть абсолютным каталогом: $artifact" ;;
esac
[ -d "$artifact" ] || fail "нет каталога артефакта: $artifact"

out=${OUT_DIR:-}
[ -n "$out" ] || fail "OUT_DIR не задан"
case $out in
  /*) ;;
  *) fail "OUT_DIR должен быть абсолютным каталогом: $out" ;;
esac
[ -d "$out" ] || fail "нет каталога OUT_DIR: $out"

gate_json="$artifact/gate.json"
[ -f "$gate_json" ] && [ ! -L "$gate_json" ] \
  || fail "нет обычного файла $gate_json"

tests_exit_code=$(python3 -I - "$gate_json" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        summary = json.load(stream)
except (OSError, UnicodeError, ValueError) as error:
    print(f"gate.json: не удалось прочитать: {error}", file=sys.stderr)
    sys.exit(2)
code = summary.get("tests_exit_code") if isinstance(summary, dict) else None
if type(code) is not int or code not in (0, 1):
    print(f"gate.json: tests_exit_code должен быть целым 0 или 1, получено {code!r}", file=sys.stderr)
    sys.exit(2)
print(code)
PY
) || fail "не удалось разобрать tests_exit_code"

[ -L "$artifact/out" ] && fail "out/ в артефакте — symlink"
[ -d "$artifact/out" ] || fail "нет каталога out/ в артефакте"

count=0
for evidence in "$artifact"/out/*.jsonl; do
  # Без nullglob: несовпавший шаблон остаётся строкой с '*' и отбрасывается здесь.
  [ -e "$evidence" ] || [ -L "$evidence" ] || continue
  [ -L "$evidence" ] && fail "symlink в свидетельствах: $evidence"
  [ -f "$evidence" ] || fail "не обычный файл в свидетельствах: $evidence"
  cp "$evidence" "$out/" || fail "не удалось скопировать $evidence"
  count=$((count + 1))
done
[ "$count" -gt 0 ] || fail "в артефакте нет обычных файлов out/*.jsonl"

exit "$tests_exit_code"
