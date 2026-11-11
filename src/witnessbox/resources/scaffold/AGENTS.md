# Rules for coding agents: Witnessbox in this project

This project checks its code decisions with Witnessbox (evidence-based testing, EBT). Tests record
each decision with `ev()`; an independent checker in `ebt/checks.py` recomputes it against the
human-approved specification `ebt/spec.toml`; the gate gives PASS, FAIL or ERROR. The rules below
apply to every agent that changes this repository, not only inside `ebt/`.

## Hard rules

1. **A human approves the specification.** Do not change `ebt/spec.toml` without explicit human
   approval of the requirement, `witness`, `partitions` and, for `-OBS`, the observation contract.
   The approval covers the exact file: `witnessbox spec ebt/spec.toml build/spec.html` prints its
   `sha256`; any later edit needs a new approval. If a rule looks wrong or ambiguous, stop and ask.
2. **Do not edit `ebt/` or the pinned SDK copies in a task branch.** The gate fails such a branch
   with `protected_paths_changed` or `pinned_drift`. The SDK copies listed in `ebt/pinned.txt` are
   refreshed only by `witnessbox sync-pinned ebt`. Changes to `ebt/` are a separate change that a
   human approves.
3. **Do not weaken the check to get PASS.** Do not remove classes from `partitions` or fields from
   `witness`, do not add `not_in_verdict`, `known.toml` or `--allow-uncovered`, do not delete,
   skip or loosen evidence tests, and do not remove `ev()` calls.
4. **Evidence is what the application did.** The `data` of an `ev()` record holds what the code
   actually used and returned, not what the test recomputed. When you change code around an
   `ev()` call, keep the call and keep its `data` equal to the `witness` fields.
5. **The checker is independent.** `ebt/checks.py` does not import the application, its SDK or
   third-party packages, does not read `ok`, and takes the rule's constants from the requirement
   text, not from the application code.
6. **A red gate is a finding, not an obstacle.** FAIL with `checker_failed` means a defect in the
   code or an error in the specification; the human decides which. Report the invariant and the
   finding from `report.md`; fix the code only if the task asks for it, and never fix the
   specification yourself. No evidence is ERROR, not success.
7. **Dart:** call `ev()` only inside `assert`, express money as whole minor units, and do not
   claim the code is verified until `flutter analyze` and the tests pass.

## Commands

Run from the project root; `BASE` is the commit the task branch starts from.

```bash
witnessbox test-checks ebt                                  # checker tests, 0 is success
BASE=<base commit> witnessbox gate --check-only ebt .       # setup hints, not a verdict
BASE=<base commit> witnessbox gate ebt . ../ebt-results     # 0 PASS, 1 FAIL, 2 ERROR
```

The results directory is outside the clone. Reasons are in `gate.json`, findings in `report.md`.
What each result means and what to do is in the agent instructions, stage 6:
https://github.com/kaufd/WitnessBox/blob/main/docs/agent.md
