# The `ebt/` scaffold for a new project

**English** · [Русский](scaffold.ru.md)

The installed distribution can create the check directory of a new project:

```bash
witnessbox scaffold <dart|ts|jvm|generic> [<directory>]
```

`<directory>` defaults to `ebt` in the current directory; `.` fills the current
empty directory. The command does not touch an existing non-empty directory: it refuses
to write over an approved `spec.toml` and returns code `2`. The templates are part of the wheel and sdist (`witnessbox/resources/scaffold/`);
the repository sources are not needed after installation.

There are four stacks; they differ in `test.sh` and a line of `pinned.txt`:

| Stack | Project | Default `test.sh` | SDK |
|---|---|---|---|
| `dart` | Dart/Flutter | `flutter test --no-pub test/ebt` | `lib/ebt/ebt.dart` |
| `ts` | TypeScript/Vite/Vitest | `bunx vitest run .ebt.test` | `src/lib/ebt/ebt.ts` |
| `jvm` | Java/Kotlin on Gradle | `./gradlew test --tests '*EbtTest'` | `src/test/java/ebt/Ebt.java` |
| `generic` | any tool | `$EBT_TEST_CMD` | by language |

The path from an empty scaffold to the first PASS on the ready TypeScript example is the [quick start](quickstart.md); how to turn a requirement into `spec.toml`, a checker and evidence tests is the [authoring guide](authoring.md). Connecting through a coding agent is covered in the [agent instructions](agent.md).

## What is created

| File | Purpose |
|---|---|
| `spec.toml` | an example `[req]`/`[inv]` with comments; replaced by the approved requirement |
| `checks.py` | an example independent checker and the `CHECKERS` registry; does not import the application or the SDK |
| `test_checks.py` | tests of the example checker: a correct case, each input class, a violation, a shape error |
| `test.sh` | runs the tests of the chosen stack and collects the evidence into `OUT_DIR` |
| `pinned.txt` | pins the SDK copy (and, if needed, the observation helpers) |
| `README.md` | the same instructions for a human, inside the project directory |

`spec.toml`, `checks.py` and `test_checks.py` are the same for all stacks. `test.sh` and
`pinned.txt` are taken from the stack's directory.

## After creation

1. **Approve the requirement.** Replace `REQ-EXAMPLE-1` and `INV-EXAMPLE-1` in
   `spec.toml` with the approved requirement and set `source`. In the connecting project
   a human approves the spec (D4); the agent that writes the application code does not
   change it. `witness` is the minimal set of inputs and outputs for recomputation,
   `partitions` are the real input classes from the requirement, not a list of tests.
2. **Implement the checker.** `checks.py` recomputes the result from `witness` and
   returns a `Verdict`; a malformed evidence shape is a `WitnessError`.
   The sensitivity check is `witnessbox check --self-test`. The distribution command runs the checker tests
   from the project root: a package from `uv tool install` is not visible to the system
   `python3`.

   ```bash
   witnessbox test-checks ebt
   ```

   A zero-test run (no `test_*.py` in the directory) gives code `1`, not success.
3. **Copy the SDK.** From the project root run `witnessbox sync-pinned ebt`
   (substitute the directory name if it differs): the command parses `pinned.txt` the same way
   the gate does, takes the `kit:` files from the resources of the installed distribution and copies
   the originals into the project. The copy must match byte for byte, otherwise the gate gives
   `pinned_drift`; after the distribution is updated the same command refreshes the changed
   copies. The command rejects absolute destination paths and escapes from the project root (including via
   `..` or a symlink).
4. **Write the evidence tests.** They drive the real code across the input classes and
   write JSONL to `build/ebt/<feature>.jsonl` (the format is in the [SDK](sdk.md)).
5. **Add `prepare.sh` if dependencies are needed.** For a clean clone this is
   `flutter pub get`, `bun install --frozen-lockfile`, or nothing for Gradle.
   The gate runs `prepare.sh` before `test.sh`; the `test.sh` template assumes the
   dependencies are already installed.
6. **Check the connection.** From the project root run
   `witnessbox gate --check-only ebt .`: the command checks `spec.toml`, `checks.py` and the
   registration of checkers, `known.toml`, `baseline.jsonl`, the runner choice, `pinned.txt`,
   the cleanliness of the clone and hidden edits, and, with `BASE`, the protected paths. It does not
   run the tests; code `0` means no problems. This is a hint, not a verdict: the verdict
   is issued by the gate.
7. **Run the gate** with the task's `BASE` and `EBT_INV`. While there is no evidence, the gate
   ends with code `2` (ERROR): that is the absence of a check, not PASS. The `ebt/`
   directory is committed to the project repository before the task: with `BASE`, a change to `ebt/`
   in the task branch is counted by the gate as a violation of the protected paths.

## The `test.sh` contract

- The working directory is the root of a clean clone; the gate does not copy the project.
- `OUT_DIR` is an empty absolute results directory; evidence is written to
  `OUT_DIR/*.jsonl`, and different files may start `seq` at 1.
- The `EBT_TESTS` words are passed as arguments; without them the template runs only the evidence
  tests.
- Code `0` means the tests passed, `1` means the tests ran and failed, other codes mean an execution
  error. Evidence is checked on code `1` too, so the template copies it
  on any outcome.
- `test.sh` runs with the gate's rights; `OUT_DIR` is not a sandbox.

The templates target macOS `/bin/bash` 3.2: no `${var,,}`, no empty arrays under
`set -u`, no Bash 4 constructs. For Android in the `jvm` template set
`EBT_GRADLE_TASK=:app:testDebugUnitTest`, `EBT_GRADLE_RESULTS=app/build/test-results/testDebugUnitTest`
and `EBT_EVIDENCE_DIR=app/build/ebt`. A tool outside `dart`, `ts` and `jvm`
is connected with the `generic` stack; see below.

## The `generic` stack

`generic` does not choose a tool: `test.sh` runs the command from `EBT_TEST_CMD` and
copies the evidence from `EBT_EVIDENCE_DIR` (default `build/ebt`). The `EBT_TESTS`
words are passed to the command as separate arguments, without `eval`. Code `0` means the tests
passed; a code from `EBT_TEST_FAIL_CODES` (default `1`) means the tests ran and failed;
other codes mean an execution error.

| Tool | Variables | `pinned.txt` line |
|---|---|---|
| npm + Jest | `EBT_TEST_CMD="npx jest --testPathPattern ebt"` | `kit:lib/ebt/ebt.ts  src/lib/ebt/ebt.ts` |
| pnpm + Vitest | `EBT_TEST_CMD="pnpm exec vitest run .ebt.test"` | `kit:lib/ebt/ebt.ts  src/lib/ebt/ebt.ts` |
| Maven | `EBT_TEST_CMD="mvn -q test -Dtest='*EbtTest'"`, `EBT_EVIDENCE_DIR=target/ebt` | `kit:lib/ebt/Ebt.java  src/test/java/ebt/Ebt.java` |
| `dart test` | `EBT_TEST_CMD="dart test test/ebt"` | `kit:lib/ebt/ebt.dart  lib/ebt/ebt.dart` |

`EBT_TEST_CMD` is a simple command: it runs as `bash -c`, and the `EBT_TESTS` words
are appended to its end as separate arguments. Trailing newlines and spaces
are dropped. Put several commands, a pipeline, a comment or your own `"$@"`
into a separate script: `EBT_TEST_CMD` calls it, and the script parses the
arguments itself.

The TypeScript SDK enables recording on `import.meta.env.MODE === 'test'`. Jest does not set this
value, and without `import.meta.env` the module cannot be imported: with Jest you need
Vite/Vitest or your own `MODE=test` substitution in the Jest configuration; see the [SDK](sdk.md).

Maven returns code `1` both for failed tests and for a broken build, so
`EBT_TEST_FAIL_CODES` does not tell them apart. For precision, as in `jvm/test.sh`,
parse `target/surefire-reports/*.xml` in your own `test.sh`.

There is no pytest recipe: no Python SDK is shipped. Connecting a Python project
awaits a decision on a Python SDK (the plan `2026-11-02-sdk-conformance.md`).

## `pinned.txt`

A line is `<original>  <path in the clone>`:

- `kit:lib/ebt/…` is a file from the resources of the installed distribution; this is how the SDK is pinned;
- `obs/<feature>…` is a file next to `ebt/`; this is how observation helpers are pinned (D29);
- an absolute path is an external file.

The copy must match the original. A difference or a missing file is the reason
`pinned_drift` and a FAIL of the gate. The destination path in the template is an example; set the one
where the project keeps the SDK.

## Limits

The scaffold is an example, not an approved spec and not proof of behavior.
It does not create `known.toml`, `baseline.jsonl` and `prepare.sh`: they appear as the
project needs them. The gate checks only what was recorded; a decision made in code without
evidence stays outside the check.
