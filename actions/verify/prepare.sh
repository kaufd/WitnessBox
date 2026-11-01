#!/bin/bash
# prepare.sh <clone> <base-sha> <target-dir> — доверенная копия ebt/ для второй стадии CI.
#
# ebt/ берётся из BASE (коммит основной ветки), а не из проверяемой ветки. prepare.sh
# в копии удаляется, вместо test.sh ставится replay.sh: код проекта здесь не исполняется.
# Коды: 0 — копия готова; 2 — нет ebt/ в BASE или ошибка git/tar.
set -uo pipefail

fail() {
  echo "prepare.sh: $*" >&2
  exit 2
}

[ $# -eq 3 ] || fail "usage: $0 <clone> <base-sha> <target-dir>"
clone=$1
base=$2
target=$3
[ -n "$clone" ] && [ -n "$base" ] && [ -n "$target" ] || fail "пустой аргумент"
[ "$target" != "/" ] || fail "target-dir не может быть /"
[ -d "$clone" ] || fail "нет клона $clone"
[ ! -L "$target" ] || fail "target-dir не должен быть symlink: $target"

base=$(git -C "$clone" rev-parse -q --verify "$base^{commit}") \
  || fail "BASE=$2: такого коммита нет в $clone"
if [ "$(git -C "$clone" cat-file -t "$base:ebt" 2>/dev/null)" != tree ]; then
  fail "ebt/ нет в BASE — сначала влейте ebt/ в основную ветку"
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || fail "не найден каталог actions/verify"
[ -f "$script_dir/replay.sh" ] || fail "нет $script_dir/replay.sh"

rm -rf "$target" || fail "не удалось очистить $target"
mkdir -p "$target" || fail "не удалось создать $target"
# target-dir — сам каталог проверки (ebt/), а не его родитель: ebt-gate получает его же.
if ! git -C "$clone" archive "$base" ebt | tar -x -C "$target" --strip-components=1; then
  rm -rf "$target"
  fail "не удалось извлечь ebt/ из BASE $base"
fi
[ -d "$target" ] || fail "в BASE $base нет каталога ebt/"
# prepare.sh из BASE не должен остаться: вторая стадия не исполняет подготовку проекта.
rm -rf "$target/prepare.sh" || fail "не удалось удалить prepare.sh из копии"
rm -rf "$target/test.sh" || fail "не удалось заменить test.sh в копии"
cp "$script_dir/replay.sh" "$target/test.sh" || fail "не удалось скопировать replay.sh"
chmod 755 "$target/test.sh" || fail "не удалось сделать test.sh исполняемым"
printf 'prepare.sh: ebt/ из BASE %s подготовлен в %s\n' "$base" "$target"
