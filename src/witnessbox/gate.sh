#!/bin/bash
# witnessbox gate <ebt-dir> <clone> <run-dir>; public entry point is cli.py of this distribution.
# test.sh gets an empty absolute OUT_DIR; the old build/ebt/*.jsonl go through a bridge.
# Codes: 0 PASS, 1 FAIL, 2 ERROR; the same result is in <run-dir>/gate.json (format 1).
# BASE, EBT_TESTS, EBT_INV, EBT_CHECK are preserved.
set -uo pipefail

[ $# -eq 3 ] || { echo "usage: witnessbox gate <ebt-dir> <clone> <run-dir>" >&2; exit 2; }
mkdir -p "$3" && run=$(cd "$3" && pwd) || exit 2
# The result of a previous attempt in the same folder must not survive an early exit of this one.
out="$run/out"
rm -rf "$out" "$run/inputs" && rm -f "$run"/{gate.md,gate.json,report.md,report.json,evidence.jsonl,test.log,prepare.log,ebt-check.err,installation.json,spec.html} \
  || { echo "could not clear the results of the previous attempt in $run" >&2; exit 2; }
py=${EBT_VERIFICATION_PYTHON:-}
[ -n "$py" ] || { echo "run the installed command witnessbox gate" >&2; exit 2; }

# gate.json is written for any outcome, as soon as the results directory is known.
summary() {
  "$py" -I -c 'import sys; from witnessbox.cli import write_summary; write_summary(*sys.argv[1:])' \
    "$run" "$1" "$2" "${3:-}" "${head:-}" "${test_rc:-}" "${check_rc:-}" \
    "${checker_command:-}" "${checker_hash:-}" "${spec_file:-}"
}
# Stages share the context of one run; any infrastructure failure is ERROR.
fail() {
  error_message="$*"
  echo "$*" >&2
  summary 2 gate_error "$*" || rm -f "$run/gate.json"
  exit 2
}

ebt=$(cd "$1" && pwd) || fail "no checks directory $1"
spec_file="$ebt/spec.toml"
clone=$(cd "$2" && pwd) || fail "no clone $2"
tests=${EBT_TESTS:-}
package=$(cd "$(dirname "$0")" && pwd) || fail "distribution directory not found"
kit="$package/resources"
check="$package/checker/ebt_check.py"
[ -f "$ebt/spec.toml" ] || fail "no $ebt/spec.toml"

installation=$("$py" -I -m witnessbox.cli --installation) || fail "could not determine the installation"
printf '%s\n' "$installation" > "$run/installation.json" || fail "could not write installation.json"
supply_name=$("$py" -I -c 'from witnessbox.cli import installation; i=installation(); print(i["distribution"], i["version"], "in", i["package"], "; gate sha256", i["gate_sha256"])') \
  || fail "could not determine the distribution"
if [ -n "${EBT_CHECK:-}" ]; then
  checker_path=$(command -v "$EBT_CHECK") || fail "EBT_CHECK=$EBT_CHECK: command not found"
  case $checker_path in /*) ;; *) checker_path="$PWD/$checker_path" ;; esac
  [ -x "$checker_path" ] || fail "EBT_CHECK=$EBT_CHECK: not an executable file $checker_path"
  checker=("$checker_path")
  checker_command=$checker_path
  version=$("${checker[@]}" --version 2>&1) || fail "EBT_CHECK=$EBT_CHECK: --version failed"
  checker_hash=$(shasum -a 256 "$checker_path") || fail "could not hash $checker_path"
  checker_hash=${checker_hash%% *}
  checker_name="EBT_CHECK=$EBT_CHECK ($checker_path), $version; sha256 $checker_hash"
else
  checker=("$py" -I -m witnessbox.checker.ebt_check)
  checker_command=$check
  version=$("${checker[@]}" --version) || fail "witnessbox check --version failed"
  checker_hash=$("$py" -I -c 'from witnessbox.cli import installation; print(installation()["checker_sha256"])') \
    || fail "could not determine the checker sha256"
  checker_name="$version; $check; sha256 $checker_hash"
fi

select_runner() {
  case ${EBT_RUNNER:-} in
    ''|test.sh|flutter) ;;
    *) fail "EBT_RUNNER=$EBT_RUNNER: unknown runner (test.sh or flutter)" ;;
  esac
  if [ -e "$ebt/test.sh" ] || [ -L "$ebt/test.sh" ]; then
    [ -f "$ebt/test.sh" ] && [ -x "$ebt/test.sh" ] || fail "test.sh exists but is not an executable file: $ebt/test.sh"
    [ "${EBT_RUNNER:-}" != flutter ] || fail "EBT_RUNNER=flutter: the package contains test.sh; use EBT_RUNNER=test.sh"
    runner_kind=test.sh
    runner="test.sh${tests:+ $tests}"
    runner_command=("$ebt/test.sh")
  else
    [ "${EBT_RUNNER:-}" != test.sh ] || fail "no $ebt/test.sh: add an executable test.sh or choose EBT_RUNNER=flutter"
    if [ -z "${EBT_RUNNER:-}" ]; then
      echo "Compatibility: without test.sh the legacy Flutter adapter is selected; add test.sh or set EBT_RUNNER=flutter explicitly" >&2
    fi
    # The concrete command and Flutter details belong only to the legacy adapter.
    source "$package/runners/flutter.sh" || fail "could not load the legacy Flutter adapter"
    select_legacy_flutter
  fi
}

preflight_git() {
  cd "$clone" || fail "could not open the clone $clone"
  # HEAD before status: in a repository without commits all files are untracked, and a "dirty tree" would hide the cause.
  if ! head=$(git rev-parse -q --verify HEAD); then
    git rev-parse --git-dir >/dev/null 2>&1 && fail "the repository has no commits: the gate checks only committed files"
    fail "git rev-parse HEAD failed"
  fi
  status=$(git status --porcelain) || fail "git status failed: clone cleanliness not checked"
  if [ -n "$status" ]; then
    echo "$status" >&2
    fail "the clone tree is not clean: the gate checks only committed files"
  fi
  # Do not hide a git failure behind a successful grep or an empty substitution.
  tracked=$(git ls-files -v) || fail "git ls-files failed: hidden changes not checked"
  hidden=$(printf '%s\n' "$tracked" | sed -n '/^[a-zS] /p') || fail "could not check git flags"
  if [ -n "$hidden" ]; then
    echo "$hidden" >&2
    fail "the clone has skip-worktree/assume-unchanged: tests may run on uncommitted code"
  fi
  protected=""
  if [ -n "${BASE:-}" ]; then
    git rev-parse -q --verify "$BASE^{commit}" >/dev/null || fail "BASE=$BASE: no such commit"
    protected=$(git diff --name-only "$BASE" HEAD -- ebt tool/ebt_check) || fail "git diff from BASE failed"
  fi
  drifted=""
  if [ -f "$ebt/pinned.txt" ]; then
    while read -r src dest _ || [ -n "$src" ]; do
      case $src in ''|'#'*) continue ;; kit:*) src="$kit/${src#kit:}" ;; /*) ;; *) src="$ebt/$src" ;; esac
      [ -f "$src" ] || fail "pinned.txt: no original $src"
      cmp -s "$src" "$dest"
      cmp_rc=$?
      case $cmp_rc in
        0) ;;
        1) drifted="$drifted $dest" ;;
        *) [ -e "$dest" ] && fail "pinned.txt: could not compare $src and $dest"
           drifted="$drifted $dest" ;;
      esac
    done < "$ebt/pinned.txt" || fail "could not read pinned.txt"
  fi
}

stash_changes() {
  git -C "$clone" stash push -q -m "witnessbox gate: changes from run $head" >/dev/null 2>&1
}
cleanup_exit() {
  exit_rc=$?
  trap - EXIT
  if ! stash_changes; then
    rm -f "$run/gate.md"
    echo "could not save the run changes in git stash" >&2
    summary 2 gate_error "${error_message:+$error_message; }could not save the run changes in git stash" \
      || rm -f "$run/gate.json"
    exit_rc=2
  fi
  exit "$exit_rc"
}

# Project code (prepare.sh, test.sh) runs with the gate privileges: the checker reads a copy of the inputs
# taken before it, and editing the originals or the distribution during the run is an error. This is detection, not a sandbox.
inputs_list="spec.toml checks.py known.toml baseline.jsonl"
snapshot_inputs() {
  inputs="$run/inputs"
  mkdir "$inputs" || fail "could not create $inputs"
  for name in $inputs_list; do
    [ -f "$ebt/$name" ] || continue
    cp "$ebt/$name" "$inputs/$name" || fail "could not copy $ebt/$name to $inputs"
  done
  spec_file="$inputs/spec.toml"
}

verify_inputs() {
  changed=""
  for name in $inputs_list; do
    if [ -f "$inputs/$name" ]; then
      cmp -s "$inputs/$name" "$ebt/$name" || changed="$changed $name"
    elif [ -e "$ebt/$name" ] || [ -L "$ebt/$name" ]; then
      changed="$changed $name"
    fi
  done
  [ -z "$changed" ] || fail "check inputs in $ebt changed during the run:$changed"
  now=$("$py" -I -m witnessbox.cli --installation) || fail "could not re-determine the installation"
  [ "$now" = "$installation" ] || fail "distribution code changed during the run, see $run/installation.json"
  if [ -n "${EBT_CHECK:-}" ]; then
    now=$(shasum -a 256 "$checker_path") || fail "could not re-hash $checker_path"
    [ "${now%% *}" = "$checker_hash" ] || fail "EBT_CHECK=$EBT_CHECK: checker changed during the run"
  fi
}

run_tests() {
  if [ -x "$ebt/prepare.sh" ]; then
    exec 3> "$run/prepare.log" || fail "could not open prepare.log"
    "$ebt/prepare.sh" >&3 2>&1
    prepare_rc=$?
    exec 3>&-
    [ $prepare_rc -eq 0 ] || fail "prepare.sh failed, see $run/prepare.log"
  fi
  rm -f build/ebt/*.jsonl || fail "could not remove evidence of the previous run in build/ebt/"
  mkdir -p "$out" || fail "could not create $out"
  exec 3> "$run/test.log" || fail "could not open test.log"
  OUT_DIR="$out" "${runner_command[@]}" $tests >&3 2>&1
  test_rc=$?
  exec 3>&-
  runner_error=""
  [ $test_rc -gt 1 ] && runner_error=1
  current_head=$(git rev-parse --verify HEAD) || fail "git rev-parse HEAD after the tests failed"
  [ "$current_head" = "$head" ] || fail "clone HEAD changed during the run"
}

collect_evidence() {
  shopt -s nullglob
  logs=("$out"/*.jsonl)
  if [ ${#logs[@]} -eq 0 ]; then
    bridge=(build/ebt/*.jsonl)
    if [ ${#bridge[@]} -gt 0 ]; then
      cp "${bridge[@]}" "$out"/ || fail "copying build/ebt to $out failed"
    fi
    logs=("$out"/*.jsonl)
  fi
  if [ ${#logs[@]} -eq 0 ]; then
    [ -n "$drifted" ] && echo "pinned copies differ from the original or are missing (pinned.txt):$drifted" >&2
    fail "no evidence in $out (OUT_DIR) or in build/ebt/ (tests: code $test_rc${runner_error:+, execution error}), see $run/test.log"
  fi
  # awk 1 appends a newline; the checker gets the original files with separate seq.
  awk 1 "${logs[@]}" > "$run/evidence.jsonl" || fail "concatenating the evidence failed"
}

check_evidence() {
  args=(--spec "$inputs/spec.toml" --evidence "${logs[@]}" --self-test
        --md "$run/report.md" --json "$run/report.json")
  [ -f "$inputs/checks.py" ] && args+=(--checkers "$inputs/checks.py")
  [ -f "$inputs/known.toml" ] && args+=(--known "$inputs/known.toml")
  [ -f "$inputs/baseline.jsonl" ] && args+=(--baseline "$inputs/baseline.jsonl")
  [ -n "${EBT_INV:-}" ] && args+=(--scope "$EBT_INV")
  exec 3> "$run/ebt-check.err" || fail "could not open ebt-check.err"
  "${checker[@]}" "${args[@]}" 2>&3
  check_rc=$?
  exec 3>&-
}

decide() {
  # All observed reasons, not only the one that set the exit code; empty items are dropped by gate.json.
  reasons=""
  case $check_rc in 0) ;; 1) reasons+=",checker_failed" ;; *) reasons+=",checker_error" ;; esac
  case $test_rc in 0) ;; 1) reasons+=",tests_failed" ;; *) reasons+=",tests_error" ;; esac
  [ -n "$protected" ] && reasons+=",protected_paths_changed"
  [ -n "$drifted" ] && reasons+=",pinned_drift"
  rc=$check_rc
  case $rc in 0|1|2) ;; *) rc=2 ;; esac
  [ $test_rc -ne 0 ] && [ $rc -eq 0 ] && rc=1
  [ -n "$protected" ] && [ $rc -eq 0 ] && rc=1
  [ -n "$drifted" ] && [ $rc -eq 0 ] && rc=1
  [ -n "$runner_error" ] && rc=2
  case $rc in 0) verdict="green" ;; 1) verdict="red" ;; *) verdict="gate error" ;; esac
}

write_report() {
  spec_hash=$(shasum -a 256 "$spec_file") || fail "could not hash spec.toml"
  python_version=$("$py" --version) || fail "could not determine the Python version"
  # The review page of the checked spec copy (D58). A spec that does not parse is already
  # a checker error, so a missing page does not change the verdict; gate.md says it is missing.
  spec_page="[spec.html](spec.html)"
  "$py" -I -c 'import sys; from witnessbox.spec_page import write_page; write_page(*sys.argv[1:])' \
    "$spec_file" "$run/spec.html" "$ebt/spec.toml" 2>/dev/null \
    || { rm -f "$run/spec.html"; spec_page="not built: spec.toml does not parse"; }
  if [ "$runner_kind" = test.sh ]; then
    runner_hash=$(shasum -a 256 "$ebt/test.sh") || fail "could not hash test.sh"
    runner_environment="test.sh sha256 ${runner_hash:0:12}"
  else
    legacy_flutter_environment || fail "could not determine the legacy Flutter adapter environment"
  fi
  # First build the text completely, then check the single write.
  report=$(cat <<EOF
# EBT gate: $verdict

- Commit: \`$head\` in \`$clone\`
- Spec: \`$ebt\`, spec.toml sha256 ${spec_hash:0:12} · page: $spec_page
- \`$runner\` tests: code $test_rc · ebt_check: code $check_rc · logs merged: ${#logs[@]}
- Distribution: $supply_name
- Checker: $checker_name
- Coverage required for: ${EBT_INV:-all spec invariants}
- Environment: $runner_environment; $python_version
- Report: [report.md](report.md)
EOF
) || fail "could not build gate.md"
  [ -n "$runner_error" ] && report+=$'\n'"- **Test execution error:** code $test_rc (contract: 0 passed, 1 failed), see test.log"
  [ -n "${BASE:-}" ] || report+=$'\n'"- Protected paths were not checked: BASE is not set"
  [ -n "$protected" ] && report+=$'\n'"- **ebt/ or tool/ebt_check/ changed in the application branch:** $protected"
  [ -n "$drifted" ] && report+=$'\n'"- **Pinned copies differ from the original or are missing (pinned.txt):**$drifted"
  printf '%s\n' "$report" > "$run/gate.md" || { rm -f "$run/gate.md"; fail "could not write gate.md"; }
  summary "$rc" "$reasons" || { rm -f "$run/gate.md"; fail "could not write gate.json"; }
  cat "$run/gate.md" || { rm -f "$run/gate.md"; fail "could not read gate.md"; }
}

select_runner
preflight_git
snapshot_inputs
# Changes from preparation/tests are saved even on an early failure.
trap cleanup_exit EXIT
run_tests
verify_inputs
collect_evidence
check_evidence
decide
# Check the stash before publishing PASS; on failure EXIT retries saving.
stash_changes || fail "could not save the run changes in git stash"
trap - EXIT
write_report
exit "$rc"
