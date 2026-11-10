#!/bin/bash
# replay.sh is the test.sh of the trusted stage: it supplies the evidence from the first-stage artifact
# and runs nothing. The artifact is untrusted: symlinks and non-regular files are rejected.
#
# EBT_REPLAY_DIR is the absolute directory of the unpacked artifact (out/*.jsonl, gate.json).
# OUT_DIR is the usual test.sh contract: an empty absolute results directory.
# The exit code is tests_exit_code from gate.json (only the integers 0 or 1), otherwise 2.
set -u

fail() {
  echo "replay.sh: $*" >&2
  exit 2
}

artifact=${EBT_REPLAY_DIR:-}
[ -n "$artifact" ] || fail "EBT_REPLAY_DIR is not set"
case $artifact in
  /*) ;;
  *) fail "EBT_REPLAY_DIR must be an absolute directory: $artifact" ;;
esac
[ -d "$artifact" ] || fail "no artifact directory: $artifact"

out=${OUT_DIR:-}
[ -n "$out" ] || fail "OUT_DIR is not set"
case $out in
  /*) ;;
  *) fail "OUT_DIR must be an absolute directory: $out" ;;
esac
[ -d "$out" ] || fail "no OUT_DIR directory: $out"

gate_json="$artifact/gate.json"
[ -f "$gate_json" ] && [ ! -L "$gate_json" ] \
  || fail "no regular file $gate_json"

tests_exit_code=$(python3 -I - "$gate_json" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        summary = json.load(stream)
except (OSError, UnicodeError, ValueError) as error:
    print(f"gate.json: could not read: {error}", file=sys.stderr)
    sys.exit(2)
code = summary.get("tests_exit_code") if isinstance(summary, dict) else None
if type(code) is not int or code not in (0, 1):
    print(f"gate.json: tests_exit_code must be the integer 0 or 1, got {code!r}", file=sys.stderr)
    sys.exit(2)
print(code)
PY
) || fail "could not parse tests_exit_code"

[ -L "$artifact/out" ] && fail "out/ in the artifact is a symlink"
[ -d "$artifact/out" ] || fail "no out/ directory in the artifact"

count=0
for evidence in "$artifact"/out/*.jsonl; do
  # Without nullglob: an unmatched pattern stays a string with '*' and is discarded here.
  [ -e "$evidence" ] || [ -L "$evidence" ] || continue
  [ -L "$evidence" ] && fail "symlink in the evidence: $evidence"
  [ -f "$evidence" ] || fail "not a regular file in the evidence: $evidence"
  cp "$evidence" "$out/" || fail "could not copy $evidence"
  count=$((count + 1))
done
[ "$count" -gt 0 ] || fail "the artifact has no regular out/*.jsonl files"

exit "$tests_exit_code"
