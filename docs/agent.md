# Agent instructions: connecting Witnessbox to a project

**English** · [Русский](agent.ru.md)

This document is addressed to a coding agent (Claude Code, Codex, Cursor and the like) that a human has asked to connect Witnessbox to their project. The human only needs to give the agent one line:

```
Connect Witnessbox to this project following the instructions at https://github.com/kaufd/WitnessBox/blob/main/docs/agent.md
```

For a human the same path is described in the [quick start](quickstart.md) and the [authoring guide](authoring.md); below is its version with rules and stop points for an agent.

---

## Role and the main rule

You connect to the project an independent check of the code's decisions (EBT). In tests the code records evidence of a decision through `ev()`, and a separate checker recomputes the rule against the spec approved by a human and issues a verdict.

**You do not approve the spec.** You prepare a draft of `ebt/spec.toml`, show it to the human and wait for explicit approval. If the rule is written and fitted to the code by the same one who writes the code, the check loses its meaning (decision D4). Everything else is your work: the scaffold, the SDK, the checker, the tests, running the gate.

## Hard prohibitions

1. Do not commit `ebt/spec.toml` and do not run the gate "to get green" until the human has approved the requirement, `witness`, `partitions` and, for `-OBS`, the observation contract.
2. After approval, do not change `spec.toml` on your own initiative. If it turns out the rule cannot be implemented or is ambiguous, stop and ask.
3. Do not edit `ebt/` or the pinned SDK copy in the task branch that the gate checks: that gives `protected_paths_changed` and `pinned_drift`. Only `witnessbox sync-pinned` updates the SDK copy.
4. `checks.py` does not import the application, its SDK or third-party packages and does not read the `ok` field. The rule's constants come from the requirement text, not from the application code.
5. `data` of the evidence holds what the application actually used and returned, not what the test recomputed itself.
6. Do not weaken the check to get PASS: do not remove classes from `partitions` or fields from `witness`, and do not add `not_in_verdict`, `known.toml` or `--allow-uncovered` without the human's decision. A red gate on project code is a finding; you report it, you do not hide it.
7. Do not change application code, except inserting `ev()` at the decision point if the human allowed it. You describe a defect the gate found, and fix it only when told to.
8. Missing evidence is ERROR, not success. Do not call the connection working until you have PASS on sound code and FAIL on an introduced defect (stage 7).
9. For Dart, do not claim the code is checked until it has passed `flutter analyze` and the tests; in Dart `ev()` is called only inside `assert`, and money is in integer minimal units.

## Stop points

Stop and ask the human, do not guess, when:

- **the requirement is missing or ambiguous**: the boundary (`>=` or `>`), units, rounding, what happens on an empty input;
- **the spec draft is ready**: a mandatory stop (stage 2);
- **the stack fits neither** `dart`, `ts`, `jvm`, nor the `generic` recipes, or the project is in Python (no Python SDK is shipped);
- **`ev()` needs a change to application code**;
- **the gate is red on code the human considers sound**: either a code defect or a spec error; the human decides;
- a command ended with code `2` and the cause is not fixed by configuring the environment.

## Stage 0. Environment

```bash
witnessbox --installation || uv tool install --force witnessbox   # or pipx install --force witnessbox
witnessbox --installation
```

You need Python 3.11+, `git`, bash (macOS or Linux; not Windows). The `witnessbox` command exists from version 0.7.0; earlier versions gave `ebt-gate` and `ebt-check`. This is why the installation in stage 0 uses `--force`: without it `uv tool install` keeps an old version that is already installed. The release SHA-256 of the gate and the checker are in the [decision log](decisions.md); if the human requires verification, compare `gate_sha256` and `checker_sha256` from `--installation`.

## Stage 1. Reconnaissance of the project

Determine the stack and the test tool without changing files:

| Sign | `--scaffold` stack | Default tests | SDK in the project |
|---|---|---|---|
| `pubspec.yaml` | `dart` | `flutter test --no-pub test/ebt` | `lib/ebt/ebt.dart` |
| `package.json` + Vitest and Bun | `ts` | `bunx vitest run .ebt.test` | `src/lib/ebt/ebt.ts` |
| `build.gradle(.kts)` | `jvm` | `./gradlew test --tests '*EbtTest'` | `src/test/java/ebt/Ebt.java` |
| npm/pnpm + Jest or Vitest, Maven, `dart test` | `generic` | `$EBT_TEST_CMD` | by language |

The `generic` recipes and caveats (Jest without `import.meta.env`, Maven returning code `1` on a broken build) are in the [scaffold](scaffold.md#the-generic-stack). Find out whether an `ebt/` directory already exists: `--scaffold` does not overwrite a non-empty directory, and that is right, since an approved spec may be there.

Find the **decision point** for the requirement in the code: the function where the result is computed. Determine whether the outcome is visible or persisted (a screen, a notification, a write to storage, a call to an external system): then, besides the decision level, you need the observation level `<INV>-OBS` ([guide, section 7](authoring.md#7-observation-level-inv-obs)).

## Stage 2. Spec draft and approval

```bash
witnessbox scaffold <stack> ebt
```

Replace the example `REQ-EXAMPLE-1`/`INV-EXAMPLE-1` in `ebt/spec.toml` with a draft following the [guide](authoring.md#2-spectoml):

- `[req.*]` is the requirement text in the owner's words and `source` (a ticket, a dated decision);
- `[inv.*]` is `statement`, `checker`, `witness` (the minimum fields for recomputation) and `partitions` (the input classes from the requirement, including boundaries, not test names);
- for a visible or persisted outcome, a twin `<INV>-OBS` and the text of the observation contract (the observation boundary, required and forbidden transitions, the completion moment and next session steps, forbidden side effects, reading the log after the action).

**Stop.** Show the human the draft in this form:

```
Requirement: <text> (source: <source>)
Invariant: <statement>
witness: <fields> — why each is needed for recomputation
partitions: <classes> — which input values each covers; boundary: <value>
OBS: <needed/not needed and why>; contract: <five points>
Questions: <everything you could not derive from the requirement>
```

Build the review page of the draft and show it together with the text above:

```bash
witnessbox spec ebt/spec.toml build/spec.html
```

The page lists the requirements with `source`, the invariants with `witness`, `partitions` or transitions, marks a requirement without `source` or without invariants and prints the `sha256` of the file. If you can publish a page for the human (an artifact, a preview), publish it; otherwise give the path to the file. Ask the human to approve the hash printed on the page: the approval names exactly that file, and any later edit needs a new approval.

Continue only after an explicit "approved" (or edits the human approved). Carry the human's edits over verbatim.

## Stage 3. Checker

Write the rule function in `ebt/checks.py` and register it in `CHECKERS` ([sample](authoring.md#3-checkspy)): `Verdict(ok, reason, parts)` for a well-formed record, `WitnessError` for a missing field or a wrong type; `parts` are returned on a violation too; the name does not match core checkers (`cart_total`, `transition`, `sync_merge`). In `ebt/test_checks.py`: a case for each class, a violation at the boundary, a shape error, registration.

```bash
witnessbox test-checks ebt
```

Expected is code `0`. A zero-test run (no `test_*.py`) gives code `1`.

## Stage 4. SDK and evidence tests

```bash
witnessbox sync-pinned ebt
```

If the project keeps the SDK somewhere other than where the template line of `ebt/pinned.txt` points, first fix the destination path in `pinned.txt`, then repeat the command. Do not edit the SDK file afterwards.

An evidence test drives the real code across each class from `partitions` and writes JSONL to `build/ebt/<feature>.jsonl` (for `generic`, to `EBT_EVIDENCE_DIR`). A TypeScript sample is in the [quick start, step 4](quickstart.md#4-the-evidence-test); the format and the allowed values of `data` are in the [SDK](sdk.md). The evidence is recorded at the decision point or around the call; `Ebt.scope` is the class or scenario name; `data` is exactly the `witness` fields.

If a clean clone needs dependencies, add an executable `ebt/prepare.sh` (`bun install --frozen-lockfile`, `flutter pub get`; nothing for Gradle). The lock file must be committed.

For `-OBS`: the test acts through the observation boundary from the contract, reads the observed value (with an appearance log or a log of fake calls if the contract has them; the log is read after the action completes) and writes `ev("<INV>-OBS", ...)`. Observation helpers are pinned in `pinned.txt` with a line `obs/<feature>…  <path>`.

## Stage 5. Checking the connection

Commit the connection in one commit (the spec is already approved): `ebt/`, the SDK copy, the evidence tests, the lock file. `build/` goes in `.gitignore`.

```bash
BASE=$(git rev-parse HEAD) witnessbox gate --check-only ebt .
```

Every line must be `ok`; fix any `problem …` and repeat. This is a hint, not a verdict.

## Stage 6. The gate on sound code

```bash
BASE=$(git rev-parse HEAD) witnessbox gate ebt . ../ebt-results
echo $?
```

The results directory is outside the clone. Codes: `0` PASS, `1` FAIL, `2` ERROR. The reasons are `reasons` in `../ebt-results/gate.json`, the findings are in `report.md`:

| Result | What to do |
|---|---|
| ERROR, `no evidence` | the test did not write the file to the right directory, or `test.sh` did not find the tests: check the path and the filter |
| ERROR, `gate_error` of another kind | read `message`, `prepare.log`, `test.log`; most often a dirty clone or missing dependencies |
| FAIL, `checker_failed`, "partitions not encountered" | the tests did not reach a class: add a scenario; do not remove classes from `partitions` |
| FAIL, `checker_failed`, a violation or a false proof | a possible code defect or a spec error: **stop**, show the finding to the human |
| FAIL, `tests_failed` | the tests themselves failed, see `test.log` |
| FAIL, `pinned_drift` | the SDK copy differs: `witnessbox sync-pinned ebt`, commit |
| FAIL, `protected_paths_changed` | `ebt/` changed after `BASE`: check which commit was passed as `BASE` |
| `report.md`: "corruption of paths … was never caught" | the checker does not look at the field: either check it in the checker, or ask the human whether it is superfluous in `witness` |

## Stage 7. Sensitivity check on a defect

PASS alone does not prove the check works. Introduce a defect in a separate worktree so as not to touch the human's tree:

```bash
git worktree add ../ebt-defect-check HEAD
# in ../ebt-defect-check break the rule's boundary in the application code (for example, >= → >)
git -C ../ebt-defect-check commit -am "temporary defect to check EBT"
BASE=$(git rev-parse HEAD) witnessbox gate ../ebt-defect-check/ebt ../ebt-defect-check ../ebt-results-defect
echo $?
git worktree remove --force ../ebt-defect-check
```

Expected is code `1` and `checker_failed` in `reasons` without `protected_paths_changed`. If the gate stayed green, the rule is not sensitive to this error: check `partitions` (is there a boundary class) and `witness`, and tell the human. The temporary commit is created on the worktree's detached HEAD and does not reach the human's branches.

## Stage 8. Report to the human

```
Stack: <stack>, test command: <...>
Spec: <INV-...> — approved <by whom/when>
Connection: commit <sha>; files: ebt/..., <SDK>, <tests>
Gate on sound code: PASS (code 0), classes: <all from partitions>
Gate on the defect <which>: FAIL, reasons=[...]
Found in project code: <violations or "none">
Not covered: <decisions without evidence, requirements without OBS, what stayed outside the check>
Next: CI — docs/ci.md (the two-stage gate for GitHub Actions)
```

List explicitly what the gate does **not** check in this connection: decisions without `ev()`, outcomes without `-OBS`, classes that are not in `partitions`. The limits of the guarantees are in the [threat model](security.md); do not promise more.
