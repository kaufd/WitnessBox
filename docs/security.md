# Witnessbox threat model

**English** · [Русский](security.ru.md)

The gate and the checker answer the question "what was recorded and does the record agree with the rule", not "what was executed". The adversary is the code under test and its author, including a coding agent; it runs as the same OS user as the gate. The guarantee is **detection** of a mismatch, not a privilege boundary: the gate is not a sandbox and not a proof that there is no bypass (D26).

| Attack or error | How it is caught | Reference |
|---|---|---|
| The code writes `ok: true` on a wrong decision | the checker recomputes the rule from `data`; `ok` has no effect; `FALSE_PROOF` | [test_ok_field_is_ignored_for_verdict](../tests/checker/test_checker.py), [test_false_proof](../tests/checker/test_checker.py) |
| A record is lost inside a file | `LOG_GAP` by `seq` | [test_log_gap](../tests/checker/test_checker.py), [test_gap_at_file_boundary](../tests/checker/test_checker.py) |
| A scenario vanished relative to the baseline | a coverage gap | [test_vanished_scenario_is_a_gap](../tests/checker/test_checker.py) |
| Incomplete evidence or evidence of the wrong type | `WITNESS_INCOMPLETE`, `WITNESS_MALFORMED`, `MALFORMED_LINE` | [test_wrong_types_are_malformed](../tests/checker/test_checker.py), [test_non_string_ids_are_malformed_lines](../tests/checker/test_checker.py) |
| The checker does not look at a field | `--self-test` | [test_self_test_finds_ignored_field](../tests/checker/test_checker.py) |
| The checker verifies only part of a list | `weak_paths` from the self-test, path `field[i]…` | [test_self_test_finds_checker_reading_only_first_list_element](../tests/checker/test_checker.py) |
| A partition is not covered | `uncovered_partitions`, FAIL without `--allow-uncovered` | [test_coverage](../tests/checker/test_checker.py) |
| The tests failed while the checker is green | `tests_failed`, FAIL | [D19](decisions.md) |
| A branch edits `ebt/` or `tool/ebt_check/` | `protected_paths_changed`; `BASE` is required | [gate.sh](../src/witnessbox/gate.sh) |
| A branch edits the pinned SDK copy | `pinned_drift` | `pinned.txt`, [D25](decisions.md) |
| The verification inputs changed during the run | the `inputs/` snapshot, ERROR `gate_error` | [D26](decisions.md) |
| The gate or checker code changed during the run | the `--installation` comparison, ERROR | [D26](decisions.md) |
| There is no evidence | ERROR | [docs/usage.md](usage.md) |
| The evidence was replaced after the verdict | `evidence` in `gate.json`, re-check with `witnessbox check` | [D34](decisions.md) |
| The verdict or `gate.json` was changed by project code (CI mode) | re-check in `workflow_run`, `gate.json` signed with an attestation | [test_verify.py](../tests/actions/test_verify.py), [D45](decisions.md) |
| The spec was changed in a PR (CI mode) | `ebt/` and `checks.py` from `BASE`; `protected_paths_changed` | [test_prepare_uses_base_spec_and_drops_prepare](../tests/actions/test_verify.py), [D45](decisions.md) |
| A PR branch edits `ebt-verify.yml` | GitHub takes the workflow from the base branch; the PR version does not run | [D45](decisions.md) |
| Hostile input breaks the checker | exit code 0/1/2 without a traceback | [HostileEvidence](../tests/checker/test_checker.py) |
| A stale PASS in the results directory | cleanup before the run, atomic writes, removal on failure | [D19](decisions.md) |

A coordinated substitution of the evidence and `gate.json` after the verdict is not caught in a local run or in the first CI stage: `evidence` is a hash, not a signature, and the same user can rewrite both files (D34). The hash detects a mismatch with the files the checker read; it does not prove they are authentic. In CI mode the second stage re-checks the evidence and signs `gate.json` with an attestation (D45), so a substitution after the verdict is detected when the signature is verified.

## Not caught

- A decision was made but not recorded, and its consequences are not visible in OBS scenarios: [D29](decisions.md). Mutation audit remains research, not a gate.
- An installation tampered with before the run: the caller compares `gate_sha256` and `checker_sha256` with the release values ([D33](decisions.md)); in CI, `actions/setup` compares the wheel and `--installation` with `release.json` ([D45](decisions.md)).
- A deliberate bypass from `test.sh` by the same user: a background process, `~/.gitconfig`, `PATH` ([D26](decisions.md)); in CI this applies to the first stage, `ebt-tests`, and the second stage does not execute project code.
- A coordinated substitution of the evidence and `gate.json` before the verdict: the evidence is written by the code under test, and the first stage's `tests_exit_code` is a claim of that code ([D45](decisions.md)). The second stage's signature detects a substitution after the verdict, but does not prove that the evidence reflects the real execution.
- A PR from a fork or a push without a PR: `workflow_run` usually has no `BASE`, and an explicit fork is rejected by `head_repository`; the status is `error`, not `success` ([D45](decisions.md)).
- An edit to the evidence file between the checker's read and the writing of the result ([D34](decisions.md)).
- A wrong specification: a human approves it ([D4](decisions.md)).

Every "caught" row references a test or a decision. A new class of attacks is added to the table together with a test; a row without such a reference should be moved to "Not caught".
