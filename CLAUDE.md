# Witnessbox development rules

## Structure and independence

- `src/witnessbox/` is the only runtime and the installed package; the public command is `witnessbox` with the subcommands `gate`, `check`, `scaffold`, `sync-pinned`, `test-checks` and `spec`.
- `src/witnessbox/checker/` is an independent implementation of the rules. The checker and project extensions do not import the application or the SDK and do not rely on the application's `ok`.
- `src/witnessbox/api.py` holds the public extension types. New code imports `Verdict` and `WitnessError` from `witnessbox.api`; `src/ebt_verification/api.py` re-exports the same objects for existing projects, and compatibility with `from checkers import ...` is kept.
- `src/witnessbox/resources/lib/ebt/` holds the shipped SDKs; `tests/` holds the tests of the checker, the installed wheel gate and the SDKs; `examples/` is the demonstration.
- `src/witnessbox/resources/scaffold/` holds the templates of a new project: `spec.toml`, `checks.py`, `test_checks.py`, `test.sh` for the Dart, TypeScript and JVM stacks, and `pinned.txt`. The template `spec.toml` is an example, not an approved specification. `test.sh` and `pinned.txt` are part of the shipped scaffold interface; the gate contract in them may change only together with `docs/scaffold.md`, `docs/scaffold.ru.md` and the tests.

## Specification and decisions

In a connected project a human approves the EBT specification. An agent does not change the project's `spec.toml` without human approval of the requirement (decision D4). Do not introduce a new Runner API, UI or runtime dependencies without a separate decision.

Decisions are append-only: when something changes, add an entry with the reason and the status; do not rewrite earlier entries. The current list and the decision log are in [docs/decisions.md](docs/decisions.md) and [docs/decisions.ru.md](docs/decisions.ru.md).

## Changes and verification

When changing the checker or the classification, add targeted cases for correct evidence and for every changed error class. For a new checker, check its registration in `CHECKERS`, `witness`/`partitions` and sensitivity via `--self-test`. After changes to the checker or the specification, run `make test` and `make example`; the demonstration must find all four planted defects. Verify changes to the Java, TypeScript or Dart SDK with the corresponding SDK tests.

All code — identifiers, comments, CLI, gate and checker messages, reports, SDKs, scaffold templates (including its README), workflows and tests — this file, commit messages and pull request descriptions are written in English (D54, D56). The documentation is bilingual (D55): the English version is `docs/<name>.md` and `README.md`, the Russian version is `docs/<name>.ru.md` and `README.ru.md`, and the first line after the title is the language switcher. Make every documentation change in both versions in one change; links inside the Russian version point to `.ru.md`, inside the English version to `.md`; a new decision log entry is added to both files. Working plans (`docs/plans/`, `docs/superpowers/`) are not tracked in git (D56). In Dart, express money as whole minor units, and call `ev()` only inside `assert`. Do not claim that Dart code is verified or works until it has passed `flutter analyze` and the tests.

The runtime must not acquire third-party dependencies. When changing the runtime, keep in mind that the installation fingerprint is built from the distribution files (RECORD): `checker_sha256` covers all shipped Python code of `src/witnessbox/`, the py-modules and the compatibility `src/ebt_verification/`; `gate_sha256` covers the shell files and `cli.py`; `scaffold` is excluded. For an editable install and `PYTHONPATH=src`, where RECORD does not contain the sources or describes another installation, the fingerprint is built by walking the tree; an empty fingerprint is an error, not a constant SHA. Integration checks of the installed wheel must stay independent of the checkout and `PYTHONPATH`; source tests of the development tree may import `src` separately.
