#!/bin/bash
# test.sh of the ebt/ scaffold for Java/Kotlin on Gradle (witnessbox scaffold jvm).
#
# Gate contract: the working directory is the root of a clean clone; OUT_DIR is an empty absolute
# directory of run results. Arguments are the words from EBT_TESTS; each becomes
# a separate Gradle --tests filter. Codes: 0 tests passed, 1 tests ran
# and failed, 2 execution error. Evidence is collected in OUT_DIR for any outcome.
#
# Project settings are environment variables (the defaults are for a JVM module):
#   EBT_GRADLE_TASK     test task; Android: :app:testDebugUnitTest
#   EBT_GRADLE_RESULTS  XML report directory; Android: app/build/test-results/testDebugUnitTest
#   EBT_EVIDENCE_DIR    directory of JSONL from the tests; Android: app/build/ebt
#   EBT_TESTS           class filters; *EbtTest by default
# The tests write JSONL to build/ebt/<feature>.jsonl (see docs/sdk.md); for Android this
# may be app/build/ebt, in which case set EBT_EVIDENCE_DIR.
set -uo pipefail

[ -n "${OUT_DIR:-}" ] || { echo "test.sh: OUT_DIR is required (run through witnessbox gate)" >&2; exit 2; }

task=${EBT_GRADLE_TASK:-test}
results=${EBT_GRADLE_RESULTS:-build/test-results/test}
evidence_dir=${EBT_EVIDENCE_DIR:-build/ebt}

[ -x ./gradlew ] || { echo "test.sh: no executable ./gradlew in the clone root" >&2; exit 2; }

filters=("$@")
if [ ${#filters[@]} -eq 0 ]; then
  filters=('*EbtTest')
fi
gradle_args=()
for pattern in "${filters[@]}"; do
  gradle_args+=(--tests "$pattern")
done

# Evidence and reports from the previous run must not survive the current one.
rm -rf "$evidence_dir" "$results" || exit 2
log=$(mktemp) || exit 2
trap 'rm -f "$log"' EXIT

./gradlew -q "$task" "${gradle_args[@]}" --rerun 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}

# Evidence is copied for any outcome: a red run is also checked by the checker.
mkdir -p "$OUT_DIR" || exit 2
shopt -s nullglob
evidence=("$evidence_dir"/*.jsonl)
if [ ${#evidence[@]} -gt 0 ]; then
  cp "${evidence[@]}" "$OUT_DIR"/ || exit 2
fi

[ "$rc" -eq 0 ] && exit 0
# Gradle returns 1 both for failed tests and for a broken build. Code 1 only if
# the only failure cause is "There were failing tests" and the fresh XML has failures;
# everything else, including ambiguous output, is 2 ("no check was run").
#
# Checking that the XML exists is mandatory: with nullglob and no matches grep would have no
# file names and would read stdin, i.e. could hang instead of returning code 2.
reports=("$results"/TEST-*.xml)
if [ ${#reports[@]} -eq 0 ]; then
  exit 2
fi
if grep -q "There were failing tests" "$log" && ! grep -q "Build completed with" "$log" \
   && grep -lqE '<testsuite [^>]*(failures="[1-9]|errors="[1-9])' "${reports[@]}" 2>/dev/null; then
  exit 1
fi
exit 2
