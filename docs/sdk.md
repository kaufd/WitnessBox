# The evidence-recording SDK

**English** · [Русский](sdk.ru.md)

The Java, TypeScript and Dart SDKs write JSONL lines of one format: `{"seq","scope"?,"req","inv","ok","data"}`. The path to the sources is given by the `resources` field of the `witnessbox --installation` command, under `lib/ebt/`. The SDKs only record evidence; the checker verifies the rule.

## Common format

- `seq` starts at 1 and grows with each record; `reset()` zeroes `seq`, `scope` and the records.
- `scope` is written only if it is set.
- `data` is snapshotted at the moment of the call: changing the passed objects after the call does not change the record.
- The order of the `data` fields is set by the SDK input; the checker ignores order.

The scenario [tests/sdk/golden.jsonl](../tests/sdk/golden.jsonl) is recorded byte for byte identically by Java, TypeScript and Dart (`make test-sdk`). The field order in it is fixed only for comparing this example; it does not require sorting the fields of other evidence.

The contract common to all languages is `ev()`, this format, the allowed values below and the golden file. A new language is connected by implementing them and passing the golden file. `traced()` is an optional convenience of the TypeScript SDK only; Java and Dart do not have it (D25).

## Allowed `data` values

| Value | Java | TypeScript | Dart |
|---|---|---|---|
| `null` | `null` | `null` | `null` |
| boolean | `Boolean` | `boolean` | `bool` |
| string | `String` | `string` | `String` |
| integer | `Integer`, `Long`, `Short`, `Byte`: the whole `long` range | a safe integer: `Number.isSafeInteger` | `int`: on the VM the whole 64-bit range |
| list | `Collection` | an array without holes | `List` |
| object | `Map` with string keys | a plain object: prototype `Object.prototype` or `null` | `Map` with string keys |

Anything else is an error with the field path (`data.v[0].x`); the record does not reach the log and `seq` does not grow. In Java this is `IllegalArgumentException`: fractional numbers, `BigDecimal`, `char`, a non-string key, an arbitrary object. In TypeScript this is `TypeError`: a fraction, `NaN`, `±Infinity`, an integer outside ±(2⁵³−1), `undefined`, a hole in an array, `bigint`, a function, `Date`, `Map` and other objects that are not plain. In Dart this is `ArgumentError` (D27): any `double`, including `1.0` on the VM, `DateTime`, an enum, `Set` and other `Iterable`s that are not a `List`, a non-string key, an arbitrary object. Pass an enum as `.name`, time as a string or an integer, and a fraction as a string or as integer minimal units.

Equivalence caveats:

- Java writes a `long` outside ±(2⁵³−1) exactly, and the Python checker reads it exactly, but JS tools will read such a number with loss. For identical behavior across SDKs, keep integers in the safe range.
- Dart on the VM (`flutter test`, `dart run`) writes an `int` exactly across the whole 64-bit range, with the same caveat as Java for `long`. On the web `int` and `double` are one JS number: an integer is exact only within ±(2⁵³−1), the SDK does not reject values outside it (precision was lost before the call), and `1.0` there is indistinguishable from `1` and is written as `1`; a fraction is rejected on the web too.
- Java accepts any `Collection`, including `Set`; Dart accepts only `List`.
- The control characters `\b` and `\f` are encoded by TypeScript as `\b`/`\f`, and by Java as `\u0008`/`\u000c`. The value is the same, the bytes differ; the golden file has no such characters.
- A lone UTF-16 surrogate is escaped by TypeScript (`\ud800`); Java writes it as is, and when the file is written in UTF-8 it is replaced with `?`.

## Fractions, time and concurrency

The format does not introduce separate types for them (D28). The application encodes the value explicitly, and the checker parses and recomputes it.

- **Money.** By default, integer minimal units and a currency: `{"amount": 1250, "cur": "RUB"}`. Rates, exchange rates, percentages and sums beyond ±(2⁵³−1) are passed as a decimal string without an exponent: `{"rate": "0.155"}`, in Java `BigDecimal.toPlainString()`. The checker parses it with `decimal.Decimal` and compares values, not strings. The rounding mode and step (`HALF_EVEN`, `HALF_UP`, to the kopeck) are named by the requirement, and the checker applies them through `Decimal.quantize`. Add an input class for exactly half a step, otherwise the rounding boundary stays unproven.
- **Non-money fractions** (metrics, coordinates) are a string that the checker parses with `float()` and compares with a tolerance from the spec. Comparing as strings is not allowed: Java writes `100.0` and `1.0E10`, JavaScript writes `100` and `10000000000`.
- **Time.** An instant is integer milliseconds from the epoch or ISO-8601 with a mandatory offset (`2026-11-01T10:00:00+03:00`). A date is `YYYY-MM-DD`, a duration is integer milliseconds, a time zone is an IANA name (`Europe/Moscow`). If the decision depends on the current time, the application records the `now` it used in `data`: the checker does not read the clock, otherwise the recomputation is not reproducible. The checker parses time with `datetime.fromisoformat` and `zoneinfo`. `zoneinfo` takes the zone database from the system: it exists on macOS and Linux, on Windows it is absent without the `tzdata` package, and the runtime adds no dependencies. Input classes worth requiring: the daylight saving switch, the end of a month, 29 February, midnight in another zone.
- **Concurrency.** The checker checks each record separately, so a concurrent scenario is written by the test as one piece of evidence after all operations finish: `{"initial": {...}, "ops": [{"op": "debit", "amount": 500, "result": "ok"}, ...], "final": {...}}`. The checker looks for a sequential order of `ops` that gives exactly these outcomes and this `final`; for a small number of operations, trying permutations is enough. The input classes are whether there was a conflict and which side won.

## Visibility of write errors

`ev()` throws an error at the call site. `traced()` throws it from a synchronous call, and for a `Promise` returns a derived `Promise` that rejects with this error; a rejected original `Promise` is not recorded. If the application code itself catches all exceptions around the call, the error does not reach the test; then there is no evidence, and the checker sees it as an uncovered invariant.

## Disabling recording

The guarantees differ; each holds only under its own condition.

| SDK | How recording is disabled | Condition | What is not guaranteed |
|---|---|---|---|
| Dart | `ev()` is called only inside `assert(...)`; in a release and profile build `assert` does not execute: neither the call nor the evaluation of the arguments happens | every call is inside `assert`; the SDK and the gate do not check this | the removal of identifiers and data from the binary was not checked |
| TypeScript | when `import.meta.env.MODE !== 'test'`, `ev()` returns at once and `traced()` returns the original function | the bundler sets `import.meta.env.MODE` (Vite, Vitest); without `import.meta.env` the module fails on import | the removal of calls and arguments from the bundle depends on the bundler and was not checked; a `data` object passed as a literal is evaluated at the call site: pass a function `() => ({ ... })` |
| Java | there is no switch: every call writes a record into the process memory | `Ebt.java` lies only in the test source set (`src/test/java`); `pinned.txt` verifies the content of the copy but not its place | if the file gets into the main source set, records will accumulate in the running application |

## Formatter in a Dart project

The copy of `ebt.dart` is compared with `pinned.txt` byte for byte, and a project's CI may run `dart format --set-exit-if-changed`. So each SDK statement takes one line shorter than 80 characters: neither the short style (language version before 3.6) nor the tall style (3.7+) at a width of 80 to 120 has anything to join or wrap. `// dart format off` at the start of the file is insurance for the tall style; the short style does not read it. `make format-dart` (part of `make test-sdk`, and so of CI and `make release-check`) checks all six combinations of `--language-version` 3.6 and the current version with a width of 80, 100 and 120, and also the same file without `// dart format off`. A wrap added to the SDK, or a new formatter style, will show up at the distribution release, not in the project's CI.

## A project's own SDK

The shipped SDK may not fit the project: for example, `ebt.ts` needs TypeScript 4.5+ (`Awaited`, `structuredClone`) and Vite (`import.meta.env.MODE`), while the project builds with an older compiler, another bundler or runs tests in a browser (Karma). The copy cannot be fixed in place: the gate compares it with the original byte for byte. Then the project keeps its own SDK in `ebt/` and pins it with a line without `kit:`:

```text
lib/ebt.ts  src/testing/ebt/ebt.ts
```

`witnessbox sync-pinned ebt` copies it into the product, and the gate compares the copy with the original in `ebt/` as with the shipped one. `ebt/` is a protected path: the own SDK and its edits are a separate change that a human approves, not part of a task branch.

Start from the shipped SDK of the closest language and change only what the project needs: types the compiler lacks, the recording switch, the way records leave the test. Keep the contract: `ev()`, the [common format](#common-format), the [allowed values](#allowed-data-values) and the golden file; check it by repeating the `tests/sdk` scenario in the project's test runner and comparing the output with `tests/sdk/golden.jsonl`. The recording switch must stay off outside tests; write down its condition as in [Disabling recording](#disabling-recording).

If the tests cannot write files (a browser runner such as Karma), print each record with a marker on its own line, for example `EBT<TAB><feature><TAB><json>`, and let the project's own `ebt/test.sh` cut these lines into `$OUT_DIR/<feature>.jsonl` for any test outcome. Exclude the copy from the project's linters and formatters (`.prettierignore`, `tslint.json`/`eslint` ignores, `dart format` exclusions): a reformatted copy is `pinned_drift`.
