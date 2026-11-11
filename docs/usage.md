# Installation and usage

**English** · [Русский](usage.ru.md)

Witnessbox is a self-contained distribution of the gate, the checker and the Java, Dart and TypeScript SDKs. The runtime needs Python 3.11+ and uses only the standard library. Installing and building need [uv](https://docs.astral.sh/uv/).

## Installation

The distribution is published on PyPI:

```bash
uv tool install witnessbox
uv tool update-shell
```

Without uv, use `pipx install witnessbox` or `pip install witnessbox` in a venv. A specific version is given as `witnessbox==0.5.2`. The same files are attached to the GitHub Release of the tag; the SHA-256 of the files and the release `gate_sha256`/`checker_sha256` are recorded in the [decision log](decisions.md).

From a clone of the repository, build an sdist and a wheel from it and install the wheel:

```bash
uv build
uv tool install dist/witnessbox-0.8.0-py3-none-any.whl
uv tool update-shell
```

`uv build` without `--wheel` first builds the sdist, and the wheel from it. `uv build --wheel` builds directly from the working tree and reuses a stale `build/lib`: the old runtime can end up in the distribution. If `build/` is left over from earlier builds, it is enough to delete it before such a check. From a tag without a clone: `uv tool install git+https://github.com/kaufd/WitnessBox@v0.8.0`.

The distribution adds one command, `witnessbox`, with the subcommands `gate`, `check`, `scaffold`, `sync-pinned`, `test-checks` and `spec`; the repository sources are not needed after installation. A built wheel can be transferred to the target machine and installed with the same `uv tool install dist/witnessbox-0.8.0-py3-none-any.whl`. `witnessbox --installation` shows the distribution, the version, the installation paths and the SHA-256 of the gate and checker code, as well as the path to the SDK resources. For calibration runs, run the project replay after an update.

## Moving from the old distribution

Before `0.4.0` the distribution was called `ebt-verification`; from `0.4.0` it is called `witnessbox`, and from `0.5.0` the package is also called `witnessbox`. Before `0.7.0` the distribution provided the commands `ebt-gate` and `ebt-check`; in `0.7.0` they were removed without aliases, and one command, `witnessbox`, remains (D51). Both distributions contain the file `ebt_verification/api.py`, so they do not coexist in one environment. First the old one is removed, then the new one is installed:

```bash
uv tool uninstall ebt-verification   # if the old distribution is still installed
uv tool install witnessbox
uv tool update-shell
```

For an installation in a venv, instead of `uv tool` use `pip uninstall ebt-verification`, then `pip install witnessbox`. The order matters: `uv tool install` refuses to install a command that already belongs to another tool, and `pip uninstall ebt-verification` after installing `witnessbox` would delete the shared file `ebt_verification/api.py` and break the compatible import. The distributions cannot be combined in one environment.

When updating from `0.6.0`, the command `uv tool upgrade witnessbox` replaces the old commands with the new ones. If the old version was also installed through `pipx`, the second installation must be removed by hand (`pipx uninstall witnessbox`): otherwise its old commands stay on `PATH`.

What to change in a project when moving from `0.6.0`: command calls in `test.sh`, CI and helper scripts, following the D51 table. These do not change: the `ebt/` and `build/ebt/` directories, the `EBT_*` variables, the SDK names (`Ebt`, `ev()`, `traced()`), `spec.toml`, `pinned.txt` with the `kit:` prefix, the formats of the evidence and of the JSON reports. The SDK bytes did not change, so pinned copies do not give `pinned_drift`. Project checkers with the old import `from ebt_verification.api import ...` or `from checkers import ...` keep working; new code imports `from witnessbox.api import ...`. Imports of internal modules (`ebt_verification.checker.checkers`, `ebt_verification.checker.ebt_check`, `ebt_verification.cli`) are not preserved: this is not a supported interface, after 0.5.0 the same modules are `witnessbox.checker.*` and `witnessbox.cli`, and such a `checks.py` must be fixed once. To update the installed version, use `uv tool install --force <source>`.

## Scaffold for a new project

The installed distribution creates a check directory from templates:

```bash
witnessbox scaffold <dart|ts|jvm|generic> [<directory>]
```

`<directory>` defaults to `ebt` in the current directory; `.` fills the current empty directory. The command does not overwrite an existing non-empty directory. The stack chooses `test.sh` and `pinned.txt`; `generic` runs the command from `EBT_TEST_CMD`, and the spec and the example checker are shared. The files, the `test.sh` contract, `pinned.txt` and the order of actions are in the [scaffold](scaffold.md) page. The path to the first PASS is the [quick start](quickstart.md), and writing a spec is the [authoring guide](authoring.md). The scaffold `spec.toml` is an example, not an approved spec: a human approves the requirement (D4).

The files pinned in `pinned.txt` are copied into the project by the command `witnessbox sync-pinned <ebt directory>`, run from the project root; it parses `pinned.txt` the same way as the gate and does not write outside the project (D44).

## Running the gate and the checker

The check directory must contain a `spec.toml` approved by a human; `checks.py` is needed only for project rules. `known.toml`, `baseline.jsonl`, `prepare.sh`, `test.sh` and `pinned.txt` are used additionally. In `pinned.txt` you can pin an SDK copy, for example `kit:lib/ebt/Ebt.java  app/src/test/java/ebt/Ebt.java`; the source `kit:lib/ebt/` is taken from the resources of the installed package.

The gate takes the check directory, a clean checkout of the project and a results directory:

```bash
witnessbox gate /path/to/project/ebt /path/to/clean-checkout /path/to/results
```

The optional variables `BASE`, `EBT_INV` and `EBT_TESTS` set the base commit, the chosen invariants and the test filter. To recheck ready evidence use `witnessbox check --spec ... --checkers ... --evidence ...`; the full form is in `--help`.

In GitHub Actions the gate can run in two stages: untrusted tests on `pull_request` and a trusted recheck on `workflow_run` with a signed `gate.json` and the status `witnessbox/gate`: the [CI mode](ci.md) (D45).

Gate exit codes: `0` is PASS, `1` is FAIL, `2` is ERROR. Execution errors take priority over the check result; missing evidence counts as ERROR. The gate writes the same result to `gate.json` in the results directory, including on early refusals if the directory is available. The fields of format `1`:

| Field | Meaning |
|---|---|
| `format` | the format version, currently `1` |
| `result`, `exit_code` | `PASS`/`FAIL`/`ERROR` and the matching code `0`/`1`/`2` |
| `reasons` | all observed reasons: `checker_failed`, `checker_error`, `tests_failed`, `tests_error`, `protected_paths_changed`, `pinned_drift`, `gate_error`; empty on PASS |
| `message` | the text of the gate's refusal on `gate_error`, otherwise `null` |
| `commit` | the checked commit, `null` before the checkout is checked |
| `tests_exit_code`, `checker_exit_code` | the stage codes; `null` if the stage did not run |
| `spec_sha256`, `verifier`, `checker` | the spec hash, the distribution (`distribution`, `version`, `gate_sha256`) and the checker (`command`, `sha256`) |
| `evidence` | the evidence files the checker read: `{file, sha256}` per `out/*.jsonl`, by name; `null` if the checker did not run |
| `files` | the names of existing results in the results directory: `gate.md`, `report.json`, `evidence.jsonl`, `out`, `inputs` (the inputs the checker read), `spec.html` (the review page of the checked spec), etc. | The results directory is reused, with the outputs of the previous attempt cleared, so do not run parallel attempts into one checkout or results directory. |

`test.sh` runs from the checkout: the words from `EBT_TESTS` are passed to it as arguments, and the absolute empty `OUT_DIR` as an environment variable. The script writes separate `OUT_DIR/*.jsonl` files, each with its own seq: code `0` means the tests succeeded, `1` means the tests that ran ended unsuccessfully, other codes mean an execution error. The gate checks the available evidence on a non-zero test code too. If the script created no evidence, the gate may pick up fresh `build/ebt/*.jsonl`; the directory is cleared before the run.

The presence of an executable `test.sh` enables the strict interface; `EBT_RUNNER=test.sh` sets it explicitly, and `EBT_RUNNER=flutter` is an explicit Flutter run, only when there is no `test.sh`. If `EBT_RUNNER` is not set and `test.sh` is missing, the compatibility mode with `flutter test --no-pub ${EBT_TESTS:-test/ebt}` and a warning is kept. `prepare.sh`, if given, prepares the dependencies of the clean checkout. `test.sh` runs with the gate's rights, and `OUT_DIR` is not a sandbox. The checker reads a copy of `spec.toml`, `checks.py`, `known.toml` and `baseline.jsonl` taken into `inputs/` of the results directory before `prepare.sh`; if the originals or the distribution code changed during the run, the result is ERROR. This does not protect against a deliberate bypass ([decisions](decisions.md), D26).

## Checking the connection and the checker tests

Before a full run, connection errors are found by a command run from the project root:

```bash
witnessbox gate --check-only ebt .
```

It checks `spec.toml`, the loading of `checks.py` and the registration of all checkers
of the spec, `known.toml`, `baseline.jsonl`, the runner choice, `pinned.txt`, the cleanliness of the
clone and hidden edits (`skip-worktree`/`assume-unchanged`), and, with `BASE`,
changes to the protected paths. `prepare.sh` and `test.sh` are not run and files are not
changed; `checks.py` is imported the same way as in the checker. When `EBT_CHECK` is set,
`--check-only` does not parse `spec.toml`, `checks.py`, `known.toml` and `baseline.jsonl`
locally: understanding them belongs to the external checker. It checks the presence of `EBT_CHECK`,
the runner, `pinned.txt`, the clone and `BASE`. Codes: `0` no problems,
`1` problems found, `2` usage error. This is a hint, not a verdict:
the only guarantee is that each problem found would give the gate a non-PASS on the same input;
the command does not check the tests or the evidence. Without `BASE` the output says
outright that the protected paths were not checked.

The tests of a project checker are run with the distribution's interpreter:

```bash
witnessbox test-checks ebt
```

`<ebt-dir>` defaults to `ebt`. A zero-test run (no `test_*.py` in the directory) gives
code `1`, not success.

The review page of a spec, for a human who approves it:

```bash
witnessbox spec ebt/spec.toml spec.html
```

The command validates the spec as the checker does and writes a self-contained HTML page with no
scripts and no network loads: requirements with `source`, invariants with `witness`, `partitions` or
transitions, the requirements without `source` or without invariants, and the `sha256` of the file.
The full `sha256` is also printed to stdout. Codes: `0` the page is written, `2` the spec does not
parse or the arguments are wrong. The gate writes the same page for the checked copy of the spec to
`spec.html` in the results directory and links it from `gate.md`.

## Imports in project checkers

Installed project checkers import the public types from `witnessbox.api`; `PYTHONPATH` and an editable install are not required. The compatible `ebt_verification.api` re-exports the same objects and contains no second implementation, and `from checkers import ...` remains a historical import. A developer's tests may separately import the sources from the development tree.

## Supported interface and compatibility

An external consumer may rely on the left column; the right one changes without notice.

| Supported interface | Internal implementation |
|---|---|
| the subcommands `witnessbox gate` (including `--check-only`), `witnessbox check`, `witnessbox scaffold`, `witnessbox sync-pinned`, `witnessbox test-checks`, `witnessbox spec`, `witnessbox --version`, `witnessbox --installation`, their arguments and exit codes | the organization of the package's Python modules; the internal `ebt_verification.checker.*`/`ebt_verification.cli` are not re-exported |
| `witnessbox.api`, the compatible `ebt_verification.api` and `from checkers import ...` | the functions of `checker/engine.py` and `checker/input.py` |
| the formats of the JSONL evidence, `report.json` and `gate.json` | the structure of the checker registry |
| the `test.sh`/`prepare.sh` contract, `OUT_DIR`, the variables `BASE`, `EBT_INV`, `EBT_TESTS`, `EBT_RUNNER`, `EBT_CHECK` | the gate's bash functions |
| the SDKs from the `resources` field of the `witnessbox --installation` command, their format and allowed values ([sdk](sdk.md)) | the physical location of the sources |

`gate.md`, `report.md` and `spec.html` are meant for humans; their text is not parsed by programs. New JSON fields and new `reasons` values are a compatible change, and a consumer ignores what it does not know. Removing or renaming a field, or changing the meaning of an exit code or of the `test.sh` contract, is incompatible: before version 1.0 such changes raise the minor version, are recorded in the [decisions](decisions.md) and change the `format` of the affected JSON. Adding the public import `witnessbox.api` while keeping the old `ebt_verification.api` is a compatible change, hence version `0.5.0` and not a patch. Fixes without an interface change raise the patch version. The boundaries are pinned by tests of the installed wheel in `tests/gate/test_gate.py`.
