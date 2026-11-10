#!/bin/bash
# test.sh of the ebt/ scaffold for any test tool (witnessbox scaffold generic).
#
# Gate contract: the working directory is the root of a clean clone; OUT_DIR is an empty absolute
# directory of run results. Arguments are the words from EBT_TESTS; they are passed
# to the command as separate words, without eval. Codes: 0 tests passed, 1 tests
# ran and failed, 2 execution error. Evidence is collected in OUT_DIR
# for any test outcome.
#
# The test command is set by an environment variable:
#   EBT_TEST_CMD        required simple command; run as bash -c, the EBT_TESTS words
#                       are appended to its end as separate argv. A complex
#                       scenario (several commands, a pipeline) needs its own script;
#   EBT_EVIDENCE_DIR    directory of JSONL from the tests, build/ebt by default;
#   EBT_TEST_FAIL_CODES command codes meaning "tests ran and failed",
#                       space-separated, 1 by default.
#
# Code mapping: 0 → 0; a code from EBT_TEST_FAIL_CODES → 1; everything else → 2.
# Tools like Maven and Gradle return 1 both for failed tests and for a broken
# build: if it matters, parse the reports in your own test.sh or set the exact
# set of codes in EBT_TEST_FAIL_CODES (docs/scaffold.md).
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: OUT_DIR is required (run through witnessbox gate)" >&2; exit 2; }

[ -n "${EBT_TEST_CMD:-}" ] || {
  echo "test.sh: set EBT_TEST_CMD to the project test command (docs/scaffold.md, generic stack)" >&2
  exit 2
}

evidence_dir=${EBT_EVIDENCE_DIR:-build/ebt}
fail_codes=${EBT_TEST_FAIL_CODES:-1}

# Evidence from the previous run must not survive the current one, even if the tests failed.
rm -rf "$evidence_dir" || exit 2

# A trailing newline (a `|` block in YAML) would turn the appended arguments
# into a separate command.
cmd=${EBT_TEST_CMD%"${EBT_TEST_CMD##*[![:space:]]}"}
[ -n "$cmd" ] || { echo "test.sh: EBT_TEST_CMD is empty" >&2; exit 2; }

# The EBT_TESTS words are separate argv at the end of the command, without eval or re-parsing.
bash -c "$cmd"' "$@"' _ "$@"
rc=$?

# Evidence is copied for any outcome: a red run is also checked by the checker.
mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=("$evidence_dir"/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
for code in $fail_codes; do
  [ "$rc" = "$code" ] && exit 1
done
exit 2
