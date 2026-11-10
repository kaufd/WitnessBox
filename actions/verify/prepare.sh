#!/bin/bash
# prepare.sh <clone> <base-sha> <target-dir> — a trusted copy of ebt/ for the second CI stage.
#
# ebt/ is taken from BASE (a commit of the main branch), not from the branch under check. prepare.sh
# is removed from the copy, replay.sh replaces test.sh: project code is not executed here.
# Codes: 0 the copy is ready; 2 no ebt/ in BASE or a git/tar error.
set -uo pipefail

fail() {
  echo "prepare.sh: $*" >&2
  exit 2
}

[ $# -eq 3 ] || fail "usage: $0 <clone> <base-sha> <target-dir>"
clone=$1
base=$2
target=$3
[ -n "$clone" ] && [ -n "$base" ] && [ -n "$target" ] || fail "empty argument"
[ "$target" != "/" ] || fail "target-dir cannot be /"
[ -d "$clone" ] || fail "no clone $clone"
[ ! -L "$target" ] || fail "target-dir must not be a symlink: $target"

base=$(git -C "$clone" rev-parse -q --verify "$base^{commit}") \
  || fail "BASE=$2: no such commit in $clone"
if [ "$(git -C "$clone" cat-file -t "$base:ebt" 2>/dev/null)" != tree ]; then
  fail "no ebt/ in BASE: first merge ebt/ into the main branch"
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || fail "actions/verify directory not found"
[ -f "$script_dir/replay.sh" ] || fail "no $script_dir/replay.sh"

rm -rf "$target" || fail "could not clear $target"
mkdir -p "$target" || fail "could not create $target"
# target-dir is the checks directory itself (ebt/), not its parent: witnessbox gate gets the same one.
if ! git -C "$clone" archive "$base" ebt | tar -x -C "$target" --strip-components=1; then
  rm -rf "$target"
  fail "could not extract ebt/ from BASE $base"
fi
[ -d "$target" ] || fail "no ebt/ directory in BASE $base"
# prepare.sh from BASE must not remain: the second stage does not run project preparation.
rm -rf "$target/prepare.sh" || fail "could not remove prepare.sh from the copy"
rm -rf "$target/test.sh" || fail "could not replace test.sh in the copy"
cp "$script_dir/replay.sh" "$target/test.sh" || fail "could not copy replay.sh"
chmod 755 "$target/test.sh" || fail "could not make test.sh executable"
printf 'prepare.sh: ebt/ from BASE %s prepared in %s\n' "$base" "$target"
