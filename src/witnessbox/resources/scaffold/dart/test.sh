#!/bin/bash
# test.sh of the ebt/ scaffold for Dart/Flutter (witnessbox scaffold dart).
#
# Gate contract: the working directory is the root of a clean clone; OUT_DIR is an empty absolute
# directory of run results. Arguments are the words from EBT_TESTS (a test filter).
# Codes: 0 tests passed, 1 tests ran and failed, 2 execution error.
# Evidence is collected in OUT_DIR/*.jsonl for any test outcome.
#
# The tests write JSONL to build/ebt/<feature>.jsonl (see docs/sdk.md), so the script
# copies them to OUT_DIR. If your test/ebt is not created yet, the gate ends with ERROR
# "no evidence", which is the expected scaffold state, not PASS.
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: OUT_DIR is required (run through witnessbox gate)" >&2; exit 2; }

command -v flutter >/dev/null 2>&1 || { echo "test.sh: flutter not found; the Flutter SDK is required" >&2; exit 2; }

# Evidence from the previous run must not survive the current one, even if the tests failed.
rm -rf build/ebt || exit 2

tests=("$@")
if [ ${#tests[@]} -eq 0 ]; then
  # By default only the evidence tests: the gate does not need the whole suite if EBT_TESTS is not set.
  tests=(test/ebt)
fi

# --no-pub: dependencies are prepared by the project prepare.sh (flutter pub get), not this script.
flutter test --no-pub "${tests[@]}"
rc=$?

mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=(build/ebt/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
# Flutter returns 1 both for failed tests and for some build errors. If the project
# distinguishes them differently, refine here: 2 means "no check was run".
[ "$rc" -eq 1 ] && exit 1
exit 2
