# Quick start: from zero to the first PASS

**English** · [Русский](quickstart.ru.md)

The tutorial walks the whole path on a tiny TypeScript project: installation, the `ebt/` scaffold, an evidence test, a green gate, then an injected defect and a red gate with the reason `checker_failed`. It is the same scenario as [examples/e2e/ts](../examples/e2e/ts) (D48), and `make e2e STACK=ts` runs it. For a ready example with a store discount, see [how it works](example.md); to write your own specification, see the [authoring guide](authoring.md).

What the tutorial does not teach: it takes the template requirement "`result = value × 2`" as is. In a real project a human approves the specification (D4), not the person who writes the code; the example is only here to show the working cycle.

## What you need

- Python 3.11+ and [uv](https://docs.astral.sh/uv/) (or `pipx`);
- [Bun](https://bun.sh/), which runs the Vitest tests in the `ts` stack;
- `git`: the gate checks a committed, clean clone.

The `witnessbox` command appeared in 0.7.0; earlier releases provided `ebt-gate` and `ebt-check`, and the steps below do not work with them. Upgrade an earlier installation with `uv tool upgrade witnessbox`. The output below was captured from the 0.7.0 wheel built from this tree (`uv build`); paths in it are shortened.

## 1. Installation

```bash
uv tool install witnessbox
```

This installs one command, `witnessbox`, with the `gate`, `check`, `scaffold`, `sync-pinned` and `test-checks` subcommands; `witnessbox --help` lists them. `witnessbox --installation` prints the version and the fingerprints of the distribution.

## 2. The project and the `ebt/` scaffold

Create a project with one function:

```bash
mkdir double-demo && cd double-demo
git init
mkdir src
```

`package.json`:

```json
{
  "name": "double-demo",
  "private": true,
  "type": "module",
  "devDependencies": {
    "vitest": "5.0.5"
  }
}
```

`vitest.config.ts`: Vitest looks only for evidence tests.

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["*.ebt.test.ts"],
  },
});
```

`tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "skipLibCheck": true,
    "types": ["vitest/globals"]
  },
  "include": ["src", "*.ts"]
}
```

`src/double.ts`:

```ts
export function double(value: number): number {
  return value * 2;
}
```

`.gitignore`:

```
node_modules/
build/
```

Install the dependencies and create the scaffold:

```bash
bun install
witnessbox scaffold ts ebt
```

`bun install` creates `bun.lock`. Commit it, because the gate installs dependencies in a clean clone with `bun install --frozen-lockfile`. The scaffold prints the list of created files:

```
Created ebt/ scaffold (ts) in …/double-demo/ebt:
  spec.toml
  checks.py
  test_checks.py
  README.md
  test.sh
  pinned.txt
Next:
  replace the example REQ-EXAMPLE-1/INV-EXAMPLE-1 with an approved requirement (may stay for a trial);
  run the checker tests: witnessbox test-checks ebt;
  copy the SDK and helpers: witnessbox sync-pinned ebt;
  write an evidence test (it writes build/ebt/*.jsonl) and, if needed, ebt/prepare.sh;
  commit the project and check the setup: witnessbox gate --check-only ebt .;
  run the gate: witnessbox gate ebt . <result dir>.
Details are in the directory README.md.
```

The "Next" hint is the order for your own project, as in `ebt/README.md`. The tutorial keeps the template specification, so it first copies the SDK and writes the test, and runs the checker tests before the commit.

What matters in it right now:

- `ebt/spec.toml` has the example requirement `REQ-EXAMPLE-1` and the invariant `INV-EXAMPLE-1`: `result == value × 2`, `witness = ["value", "result"]`, partitions `zero`, `positive`, `negative`;
- `ebt/checks.py` has the independent checker `example_rule`: it recomputes `value × 2` itself and does not import the application;
- `ebt/test.sh` runs `bunx vitest run .ebt.test` and copies `build/ebt/*.jsonl` to `OUT_DIR`; you do not need to touch it.

Here we leave the template specification as it is. For your own requirement, replace it following the [authoring guide](authoring.md).

## 3. The SDK copy

```bash
witnessbox sync-pinned ebt
```

```
updated src/lib/ebt/ebt.ts
```

The command read `ebt/pinned.txt` (the line `kit:lib/ebt/ebt.ts  src/lib/ebt/ebt.ts`) and put the SDK from the installed distribution into the project. The gate compares the copy with the original byte for byte; editing the copy by hand gives `pinned_drift`.

## 4. The evidence test

`double.ebt.test.ts` in the project root: the test drives the code through the partitions and writes one piece of evidence per partition.

```ts
import { afterAll, describe, expect, it } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";

import { Ebt, ev } from "./src/lib/ebt/ebt";
import { double } from "./src/double";

// Evidence is written after all cases: partitions are zero/positive/negative.
afterAll(() => {
  mkdirSync("build/ebt", { recursive: true });
  writeFileSync("build/ebt/double.jsonl", Ebt.toJsonl() + "\n");
});

describe("double", () => {
  const cases = [
    ["zero", 0],
    ["positive", 21],
    ["negative", -4],
  ] as const;

  for (const [name, value] of cases) {
    it(name, () => {
      Ebt.scope = name;
      const result = double(value);
      ev("INV-EXAMPLE-1", "REQ-EXAMPLE-1", result === value * 2, { value, result });
      expect(result).toBe(value * 2);
    });
  }
});
```

What happens here:

- `Ebt.scope = name` is the name of the partition; it goes into the record and separates scenarios from each other;
- `ev(inv, req, ok, data)` is the record: which invariant, which requirement, what the code decided (`ok`) and the **decision data** (`data`), exactly the `witness` fields from `spec.toml`;
- `afterAll` writes the file `build/ebt/double.jsonl`; `test.sh` copies it to `OUT_DIR`;
- `expect` is an ordinary test assertion. It does not replace the evidence: the gate trusts the checker's recomputation, not the assertion.

The record format and the allowed `data` values are in the [SDK](sdk.md).

## 5. `prepare.sh`

A clean clone has no `node_modules`. The gate runs `ebt/prepare.sh` before `test.sh`, so it installs the dependencies:

```bash
cat > ebt/prepare.sh <<'EOF'
#!/bin/bash
set -euo pipefail

bun install --frozen-lockfile
EOF
chmod 755 ebt/prepare.sh
```

## 6. Check the checker and the wiring before a full run

The scaffold's checker tests:

```bash
witnessbox test-checks ebt
```

```
test_bool_is_not_an_integer (test_checks.ExampleRule.test_bool_is_not_an_integer) ... ok
test_missing_field (test_checks.ExampleRule.test_missing_field) ... ok
test_negative (test_checks.ExampleRule.test_negative) ... ok
test_positive (test_checks.ExampleRule.test_positive) ... ok
test_registered (test_checks.ExampleRule.test_registered) ... ok
test_wrong_result_is_a_violation (test_checks.ExampleRule.test_wrong_result_is_a_violation) ... ok
test_zero (test_checks.ExampleRule.test_zero) ... ok

Ran 7 tests in 0.000s

OK
```

Now commit everything, including `ebt/`: the gate checks the clone, and it treats a change to `ebt/` inside the branch under test as a protected-path violation.

```bash
git add -A
git commit -m "Project with the ebt scaffold"
```

The wiring check (it runs neither `prepare.sh` nor `test.sh`):

```bash
BASE=$(git rev-parse HEAD) witnessbox gate --check-only ebt .
```

```
ok spec
ok checks
ok known: no known.toml
ok baseline: no baseline.jsonl
ok runner
ok pinned
ok clone
ok base
```

Before the first commit, the same command would have found a problem: `problem clone: the repository has no commits: the gate checks only committed files`, exit code `1`; with uncommitted changes after it, the line is `problem clone: the clone tree is not clean`. Without `BASE`, the `base` line reads `skipped`: protected paths were not checked. `--check-only` is a hint, not a verdict.

## 7. The gate: PASS

```bash
BASE=$(git rev-parse HEAD) witnessbox gate ebt . ../results
echo $?
```

The three arguments are the `ebt/` directory, the project clone and the results directory (the gate creates and clears it itself; keep it outside the clone). `BASE` is the commit against which the gate looks for changes to protected paths; here it is the same as the commit under test.

The exit code is `0`. The gate prints `gate.md` to the terminal; its first line is `# EBT gate: green`. The "Checker" line shows the version of the checker itself (`witnessbox check 0.1.0`): it is maintained separately from the distribution version, and the distribution and the checker are identified unambiguously by their sha256. In `gate.json`:

```json
{
  "format": 1,
  "result": "PASS",
  "exit_code": 0,
  "reasons": [],
  "tests_exit_code": 0,
  "checker_exit_code": 0,
  "evidence": [{"file": "double.jsonl", "sha256": "…"}]
}
```

(Not all fields are shown.) The evidence is in `../results/evidence.jsonl`, three lines, one per partition:

```
{"seq":1,"scope":"zero","req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,"data":{"value":0,"result":0}}
{"seq":2,"scope":"positive","req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,"data":{"value":21,"result":42}}
{"seq":3,"scope":"negative","req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,"data":{"value":-4,"result":-8}}
```

`report.md` says "Result: ✅ proven on this run", all finding categories equal zero, and the checker self-test says "corruption of any field is caught".

What the gate did: it installed the dependencies (`prepare.sh`), ran `test.sh`, collected the evidence, recomputed every record with the `example_rule` checker, checked that all partitions were encountered and wrote the result. PASS means that on the recorded scenarios the rule holds. It does not mean the code is correct outside those scenarios; the limits of the guarantees are in the [threat model](security.md).

If there is no evidence at all (for example, the test file is missing), the gate gives ERROR, not PASS: exit code `2`, reason `gate_error`, and `gate.json` has `"message": "no evidence in …"`. A missing check is not counted as success.

## 8. Inject a defect

Replace `src/double.ts`:

```ts
export function double(value: number): number {
  return value * 3;
}
```

```bash
git commit -am "double: multiply by 3"
BASE=$(git rev-parse HEAD~1) witnessbox gate ebt . ../results-defect
echo $?
```

The exit code is `1`. The scaffold and the test did not change, `BASE` is the commit before the defect, and the protected paths are untouched.

## 9. How to read the result

`gate.md` starts with the line `# EBT gate: red`, followed by versions, hashes and stage codes: `test.sh tests: code 1 · ebt_check: code 1`. The reasons are in `gate.json`:

```json
{ "result": "FAIL", "exit_code": 1, "reasons": ["checker_failed", "tests_failed"] }
```

- `checker_failed`: the checker found a violation or a coverage gap; see `report.md`;
- `tests_failed`: the tests themselves failed (`expect(result).toBe(value * 2)`); details are in `test.log`. There are two reasons here because both the test and the checker see the defect. The full list of reasons is in [usage](usage.md#running-the-gate-and-the-checker).

The main thing is `report.md`:

```
**Result: ❌ not proven**

| Confirmed violation | 2 |
| Invariants with uncovered partitions | 1 |

### Confirmed violation — `INV-EXAMPLE-1`
- Where: line 2, scope `positive`, seq 2
- Invariant: result == value × 2
- Code claimed ok=False; checker: violation
- Reason: result=63, by the rule value × 2 expected 42
- Evidence: `{"value":21,"result":63}`
…
## Coverage

- **INV-EXAMPLE-1**: partitions not encountered: `positive`, `negative`
```

Read it like this: "Where" gives the line and `scope` of the evidence, "Reason" is what the checker recomputed, "Evidence" is the recorded data. The "Code claimed ok=…" line shows what the application decided; the checker does not use it. If the application records `ok=true` on wrong data, that is a separate category, "False proof (code: ok, checker: violation)": the checker finds the violation anyway. A violated record does not count its partition as covered, which is why the `positive` and `negative` partitions are listed as not passed.

The results directory:

| File | Contents |
|---|---|
| `gate.json` | the result for CI: `result`, `reasons`, stage codes, hashes of the spec, the distribution and the evidence |
| `gate.md` | the same in short, for a human |
| `report.md`, `report.json` | checker findings, coverage, self-test |
| `evidence.jsonl`, `out/` | the evidence the checker read |
| `test.log`, `prepare.log` | the output of `test.sh` and `prepare.sh` |
| `inputs/` | a copy of `spec.toml` and `checks.py`, taken before `prepare.sh` |

## Automatic check of the tutorial

`make e2e STACK=ts` builds a temporary repository from the scaffold and `examples/e2e/ts`, runs the gate on the healthy code (expects PASS), applies `examples/e2e/ts/defect/` and expects FAIL with `checker_failed` and without `protected_paths_changed`. The analogues are `STACK=jvm` and `STACK=generic`. It needs the installed `witnessbox` command and `bun` (for `jvm`, `gradle` and JDK 17).

## Next

- Your own requirement: [from a requirement to evidence tests](authoring.md).
- Other stacks and the `test.sh` contract: [scaffold](scaffold.md).
- CI: [two-stage gate](ci.md).
- What the gate does not guarantee: [threat model](security.md).
