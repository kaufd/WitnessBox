# The `ebt/` scaffold for a new project

A command of the installed distribution creates the EBT check directory from templates:

```bash
witnessbox scaffold <dart|ts|jvm|generic> [<directory>]
```

`<directory>` defaults to `ebt` in the current directory. The command refuses to write into an
existing non-empty directory: it will not overwrite an approved `spec.toml`. There are
four stacks; they differ in `test.sh` and a line of `pinned.txt`; `spec.toml`, `checks.py` and
`test_checks.py` are the same for all of them.

| Stack | Project | Default `test.sh` | SDK |
|---|---|---|---|
| `dart` | Dart/Flutter | `flutter test --no-pub test/ebt` | `lib/ebt/ebt.dart` |
| `ts` | TypeScript/Vite/Vitest | `bunx vitest run .ebt.test` | `src/lib/ebt/ebt.ts` |
| `jvm` | Java/Kotlin on Gradle | `./gradlew test --tests '*EbtTest'` | `src/test/java/ebt/Ebt.java` |
| `generic` | any tool | `$EBT_TEST_CMD` | by language |

More in the Witnessbox documentation: the [quick start](https://github.com/kaufd/witnessbox/blob/main/docs/quickstart.md) leads from the scaffold to the first PASS on an example, and the [authoring guide](https://github.com/kaufd/witnessbox/blob/main/docs/authoring.md) explains how to write `spec.toml`, the checker and the evidence tests, including the observation level `<INV>-OBS`. If a coding agent does the connecting, give it the [agent instructions](https://github.com/kaufd/witnessbox/blob/main/docs/agent.md). This file is a reference for the scaffold; the `test.sh` contract is described below.

## What is created

- `spec.toml` is an **example** requirement and invariant. Replace `REQ-EXAMPLE-1` and
  `INV-EXAMPLE-1` with an approved requirement. In the connecting project a human
  approves the spec (D4); the agent that writes the application code does not change it.
- `checks.py` is an example independent project checker `example_rule` and the
  `CHECKERS` registry. Replace the rule together with the spec.
- `test_checks.py` holds the tests of the example checker. Run them from the project root with
  the distribution command (it picks the installation's interpreter itself):

  ```bash
  witnessbox test-checks ebt
  ```

  A zero-test run gives code `1`, not success.
- `test.sh` runs the tests of the chosen stack per the gate contract and collects the evidence
  into `OUT_DIR`. It is an executable file.
- `pinned.txt` pins the SDK copy (and, if needed, the observation helpers) with a
  byte-for-byte check.
- `AGENTS.md` holds the rules for coding agents that change this project: do not change the
  spec without a human, do not edit `ebt/` in a task branch, do not weaken the check. Point the
  project's own agent instructions (`AGENTS.md`, `CLAUDE.md` or similar at the project root) to
  it, so that every agent reads it, not only the one that did the connecting.
- `README.md` is this file.

## After creation

1. **Approve the requirement.** Replace the example in `spec.toml` with the text from a ticket or
   an owner's decision and set `source`. Check that `witness` is the minimal set of
   inputs and outputs, and `partitions` are the real boundaries of the requirement.
2. **Implement the checker.** `checks.py` recomputes the result from `witness` and does not
   import the application or the SDK. A shape error is `WitnessError`, a violation is
   `Verdict(ok=False, ...)`. Add cases to `test_checks.py` and run
   `witnessbox check --self-test`.
3. **Copy the SDK.** From the project root run `witnessbox sync-pinned ebt`
   (substitute your directory name if it differs): the command parses `pinned.txt`
   and copies `kit:lib/ebt/...` from the resources of the installed distribution into the project. The copy
   must match byte for byte; otherwise the gate gives `pinned_drift`. After the
   distribution is updated, repeat the same command: it refreshes the changed copies.
4. **Write the evidence tests.** They drive the real code across the input classes and
   write JSONL to `build/ebt/<feature>.jsonl` (see `docs/sdk.md`). `test.sh`
   copies these files into `OUT_DIR`.
5. **Prepare the dependencies.** For a clean clone add `prepare.sh`
   (`flutter pub get`, `bun install --frozen-lockfile`, or nothing for Gradle):
   the gate runs it before `test.sh`, and `test.sh` assumes the dependencies are
   installed. `prepare.sh` and `test.sh` run with the gate's rights, and `OUT_DIR`
   is not a sandbox.
6. **Run the gate:**
   `BASE=<base> EBT_INV=<task invariants> witnessbox gate <ebt directory> <clone> <result>`.
   While there is no evidence, the gate ends with ERROR: that is not PASS but the absence of a check.
   Commit `ebt/` to the project repository before the task: with `BASE`, a change to `ebt/`
   in the task branch is counted by the gate as a violation of the protected paths.

## The `test.sh` contract

- The working directory is the root of a clean clone; the gate does not copy the project.
- `OUT_DIR` is an empty absolute results directory; evidence is written to
  `OUT_DIR/*.jsonl` (different files may start `seq` at 1).
- The gate passes the `EBT_TESTS` words as arguments; without them the template runs only the
  evidence tests.
- Code `0` means the tests passed, `1` means the tests ran and failed, other codes mean an execution
  error. The gate checks the evidence on code `1` too.
- Evidence is copied on any outcome of the tests, otherwise a red run cannot be
  checked by the checker.

The templates target macOS `/bin/bash` 3.2: no `${var,,}`, no empty arrays under
`set -u`, and no Bash 4. For another tool take the `generic` stack: it runs
`EBT_TEST_CMD`, collects the evidence from `EBT_EVIDENCE_DIR` and tells the codes of
`EBT_TEST_FAIL_CODES` apart, keeping the gate contract.

## `pinned.txt`

A line is `<original>  <path in the clone>`:

- `kit:lib/ebt/…` is a file from the resources of the installed distribution; this is how the SDK is pinned;
- `obs/<feature>…` is a file next to `ebt/`; this is how observation helpers are pinned;
- an absolute path is an external file.

The copy must match the original. A difference or a missing file is the reason
`pinned_drift` and a FAIL of the gate. The destination path in the template is an example: set the one
where the project keeps the SDK.

## Limits

The scaffold is not an approved spec and does not prove behavior. It
does not create `known.toml`, `baseline.jsonl` and `prepare.sh`: they appear as the
project needs them. The gate checks only what was recorded: if a decision is made
in code without recording evidence, it stays outside the check.
