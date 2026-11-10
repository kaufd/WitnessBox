#!/bin/bash
# test.sh of the ebt/ scaffold for TypeScript/Vite/Vitest (witnessbox scaffold ts).
#
# Gate contract: the working directory is the root of a clean clone; OUT_DIR is an empty absolute
# directory of run results. Arguments are the words from EBT_TESTS (a vitest filter).
# Codes: 0 tests passed, 1 tests ran and failed, 2 execution error.
# Evidence is collected in OUT_DIR/*.jsonl for any test outcome.
#
# The tests write JSONL to build/ebt/<feature>.jsonl (see docs/sdk.md), so the script
# copies them to OUT_DIR. Dependencies are prepared by prepare.sh (bun install), not this
# script; without node_modules vitest will fail, and the code is returned below.
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: OUT_DIR is required (run through witnessbox gate)" >&2; exit 2; }

command -v bunx >/dev/null 2>&1 || { echo "test.sh: bunx not found; Bun is required" >&2; exit 2; }

# Evidence from the previous run must not survive the current one, even if the tests failed.
rm -rf build/ebt || exit 2

tests=("$@")
if [ ${#tests[@]} -eq 0 ]; then
  # By default only the evidence tests (*.ebt.test.ts): the gate does not need the rest of the suite.
  tests=(.ebt.test)
fi

bunx vitest run "${tests[@]}"
rc=$?

mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=(build/ebt/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
# Vitest returns 1 both for failed tests and for some configuration loading errors.
# If the project distinguishes them differently, refine here: 2 means "no check was run".
[ "$rc" -eq 1 ] && exit 1
exit 2
