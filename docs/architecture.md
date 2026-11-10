# Architecture

**English** · [Русский](architecture.ru.md)

The distribution installs one entry point from `pyproject.toml`: `witnessbox` leads to `witnessbox.cli:main`. `main()` parses the first argv position and calls `scaffold`, `sync_pinned`, `check_only` or `test_checks`, passes the rest to `witnessbox.checker.cli.main` for the `check` subcommand, or executes the packaged `gate.sh` for `gate`; the checker is imported lazily, only in the `check` branch. The runtime lives in `src/witnessbox/`; the `src/ebt_verification/` package is only a compatible re-export of `witnessbox.api` for existing project checkers.

## Verification flow

![Verification flow: checkout, test.sh, witnessbox check, result PASS, FAIL or ERROR](verification-flow.svg)

A run gets FAIL if at least one of these conditions holds.

| Condition | Class in the report |
|---|---|
| Recomputation found a violation or did not confirm what the code claimed | `FALSE_PROOF` (code claimed ok), `CONFIRMED_VIOLATION`, `CHECKER_DISAGREES` |
| The evidence cannot be checked | `WITNESS_INCOMPLETE`, `WITNESS_MALFORMED`, `MALFORMED_LINE` |
| A record does not match the spec, the checker did not run, or there is no implementation in scope | `UNKNOWN_INV`, `REQ_MISMATCH`, `NO_CHECKER`, `CHECKER_ERROR` |
| Records are lost or missing | `LOG_GAP`, empty log |
| A coverage gap (taking `EBT_INV` into account) | REQ without INV, INV without records, an uncovered partition, a scenario/invariant pair that vanished from the baseline |
| The checker is not sensitive to field corruption | `weak_required` from the self-test |
| The tests failed | `test.sh` returned 1 |
| Verification paths or copies changed | `ebt/` or `tool/ebt_check/` changed relative to `BASE`; a copy from `pinned.txt` differs or is missing |

An unregistered invariant checker in scope is a `NO_CHECKER` finding (FAIL), even if there are no records; outside scope it does not fail the run until there is a record with that invariant. `--check-only` reports it only for invariants in scope, so its problem still means the gate is not PASS.

Findings that match `known.toml` do not fail the run. Changed `data` and record counts relative to the baseline are shown in the report for review, but they do not change the verdict.

ERROR means that no verification result was obtained: there is no verification directory or `spec.toml`, the clone is dirty or has hidden changes, git or I/O failed, `prepare.sh` failed, `test.sh` returned a code greater than 1, there is no evidence, the checker returned a code other than 0 and 1 (including malformed spec, known or extensions), the run changes could not be saved to a git stash, or the verification inputs or the distribution code changed during the run. ERROR takes priority over FAIL. The `reasons` field in `gate.json` lists all observed reasons.

## Gate flow

`cli.py` parses the arguments and hands control to the packaged `gate.sh`. The shell gate checks the checkout, prepares the environment, runs the project `test.sh` or the chosen runner, collects the JSONL evidence, calls the checker from the same installation and builds the reports. The Flutter runner is in `runners/flutter.sh`. The project's EBT directory sets the trusted inputs: `spec.toml`, `checks.py` and the optional `known.toml`, `baseline.jsonl`, `prepare.sh`, `test.sh`, `pinned.txt`.

The checker in `checker/` reads the specification and the evidence, checks the base rules and the project extensions, applies the scope/baseline/known context and renders Markdown/JSON. It implements the rules independently and does not import the application or the SDK.

## Extensions and resources

`api.py` defines the types of the public extension API; `ebt_verification/api.py` re-exports them without a second implementation and is included in `checker_sha256` together with the checker code: the project checker executes the compatible import. The standard rules and the engine are in `checker/checkers.py` and `checker/engine.py`; input validation and reports are split between `input.py` and `rendering.py`. The practical extension contract is described in [extensions](extensions.md).

The Java, Dart and TypeScript SDKs are shipped as package resources in `resources/lib/ebt/`. The format, the allowed values and the guarantees of disabling recording are described in [sdk](sdk.md). Their tests are in `tests/sdk/`. The installation needs no Python dependencies beyond the standard library. The build, the standalone wheel check and the SDK commands are described in [development](development.md).

The new-project templates are in `resources/scaffold/`: `spec.toml`, an example `checks.py` and `test_checks.py`, and `test.sh` and `pinned.txt` for Dart, TypeScript and JVM. `witnessbox scaffold` copies them into a new `ebt/` without overwriting a non-empty directory. The templates are data, not verification code: editing them is not part of `gate_sha256`. The instructions are in [scaffold](scaffold.md).

## Boundaries

The gate runs the project's `prepare.sh` and `test.sh` with its own privileges, without a sandbox. The checker reads the copy of the verification inputs in `inputs/`, taken before them, and a change to the inputs or to the distribution code during the run gives ERROR. This detects accidental or naive corruption; it is not protection against deliberate bypass (D26). `OUT_DIR` is for results, not for input data. For parallel test scenarios the project is responsible for ordering and data isolation. The gate does not introduce a standalone Runner API or UI.
