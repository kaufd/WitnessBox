# The gate in GitHub Actions

**English** · [Русский](ci.ru.md)

In CI the local threat model D26/D34 does not hold: `test.sh` runs with the gate's rights and can forge the verdict, and a coordinated forgery of the evidence and `gate.json` after the verdict cannot be noticed by a hash. So the check is split into two stages (D45): an untrusted one and a trusted one.

```text
pull_request ──► ebt-tests (untrusted stage)
                    │  witnessbox gate as usual
                    │  artifact witnessbox-evidence: out/*.jsonl + gate.json
                    ▼
workflow_run ◄──────┘
     │
     ▼
ebt-verify (workflow from the main branch)
  checkout head_sha; ebt/ from BASE; prepare.sh removed; test.sh → replay.sh
  the real witnessbox gate; project code is not executed
  attest gate.json; gate.md in the summary; commit status witnessbox/gate
```

- `ebt-tests` runs on `pull_request` and is untrusted. Its verdict is information only.
- `ebt-verify` runs on `workflow_run`. GitHub always takes this workflow from the main branch, so the task branch cannot change it. `ebt/` and `checks.py` are taken from `BASE`, `prepare.sh` is removed, and a replay script is put in place of `test.sh`. Project code is not executed in the second stage.
- `actions/setup` installs witnessbox from PyPI and checks the SHA-256 of the wheel and the `--installation` JSON against the release's `release.json`.
- `actions/verify` rechecks the evidence with the real `witnessbox gate` command, signs `gate.json` with a GitHub attestation and sets the commit status `witnessbox/gate`: `success` is PASS, `failure` is FAIL, `error` is ERROR or a refusal before the gate.

The logic lives in the composite actions [setup](../actions/setup/action.yml) and [verify](../actions/verify/action.yml); their scripts are tested locally in [test_verify.py](../tests/actions/test_verify.py). Before the first stage you need a witnessbox release with `release.json` in a GitHub Release: the examples below use `0.9.0`.

## Template `.github/workflows/ebt-tests.yml`

```yaml
name: ebt-tests

on:
  pull_request:

permissions:
  contents: read

concurrency:
  group: ebt-tests-${{ github.ref }}
  cancel-in-progress: true

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - name: Check out the sources
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          # The PR head, not the merge commit: the second stage checks out workflow_run.head_sha.
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0

      - name: Install witnessbox
        # The SHA of the WitnessBox commit with actions/setup and actions/verify (D45).
        # The full SHA of the release tag's commit; do not use main or a tag name.
        uses: kaufd/WitnessBox/actions/setup@45c564b6ddd65c92e8d9ae1c6f79bc764ca1127f # v0.9.0
        with:
          version: "0.9.0"

      - name: Run the gate
        env:
          BASE: ${{ github.event.pull_request.base.sha }}
        run: |
          set +e
          witnessbox gate ebt . "$RUNNER_TEMP/run"
          rc=$?
          echo "witnessbox gate exited with code $rc; the verdict of this stage is not trusted"
          exit 0

      - name: Upload the evidence and gate.json
        if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: witnessbox-evidence
          path: |
            ${{ runner.temp }}/run/out/*.jsonl
            ${{ runner.temp }}/run/gate.json
          if-no-files-found: error
```

`fetch-depth: 0` is needed by the gate: it compares `BASE` and `HEAD` and checks the protected paths `ebt/` and `tool/ebt_check`. `|| true`/`exit 0` does not hide the verdict: `gate.json` is still uploaded, and the second stage decides again.

## Template `.github/workflows/ebt-verify.yml`

```yaml
name: ebt-verify

on:
  workflow_run:
    workflows: [ebt-tests]
    types: [completed]

permissions: {}

jobs:
  verify:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
      statuses: write
      id-token: write
      attestations: write
    steps:
      - name: Install witnessbox
        uses: kaufd/WitnessBox/actions/setup@45c564b6ddd65c92e8d9ae1c6f79bc764ca1127f # v0.9.0
        with:
          version: "0.9.0"

      - name: Recheck and sign
        # If setup failed, verify must still set the status to error.
        if: always()
        uses: kaufd/WitnessBox/actions/verify@45c564b6ddd65c92e8d9ae1c6f79bc764ca1127f # v0.9.0
        with:
          github-token: ${{ github.token }}
```

Both workflows must be merged into the main branch. `workflow_run` fires only for a workflow file from the main branch; a PR that changes `ebt-verify.yml` does not affect the check of that PR. The examples pin the full 40-character SHA of the `v0.9.0` tag's commit, not `main` and not the tag name: a tag can be moved, a commit cannot.

`actions/verify` requires that `actions/setup` has already run in this job: a composite action does not call setup itself, as it would have to reference the SHA of the same commit from inside it. If `witnessbox` is not on `PATH`, `actions/verify` sets `error` and does not stay silent.

## Required check

1. Enable branch protection for the main branch.
2. Enable **Require status checks to pass before merging**.
3. Add `witnessbox/gate` to the required checks. After the first run the status appears in the list; before that you can enter it by hand.
4. Do not make the `ebt-tests` verdict a merge condition: it is untrusted. Only the `witnessbox/gate` check must be required.

The status is set on `github.event.workflow_run.head_sha`, the PR commit, not the merge commit. `pending` blocks the merge, and so do `failure` and `error`; `success` allows it.

The rights of the `verify` job are minimal:

| Right | Why |
|---|---|
| `contents: read` | check out the PR commit and read the repository |
| `actions: read` | download `witnessbox-evidence` from the `ebt-tests` run |
| `statuses: write` | the commit status `witnessbox/gate` |
| `id-token: write` | an OIDC token for the attestation |
| `attestations: write` | `actions/attest-build-provenance` |

The rights of `ebt-tests` are only `contents: read`. The token of the first stage does not allow writing statuses and must not.

## Verifying the verdict by a third party

Download the artifact of the second stage and verify the signature:

```bash
gh run download <run-id> --repo <owner>/<repo> --name witnessbox-verdict
gh attestation verify gate.json \
  --repo <owner>/<repo> \
  --signer-workflow <owner>/<repo>/.github/workflows/ebt-verify.yml \
  --source-ref refs/heads/main
```

`--signer-workflow` is the consumer's workflow that called the composite action; `--source-ref refs/heads/main` binds the signature to the main branch. For a private repository, attestations require a GitHub plan that supports artifact attestations; without one the signing step fails and `witnessbox/gate` gets `error`.

If you wish, recheck the evidence with the installed `witnessbox check`:

```bash
witnessbox check --spec ebt/spec.toml --evidence out/*.jsonl --json recheck.json
```

If the project has `ebt/checks.py`, add `--checkers ebt/checks.py`; if you use `known.toml`, `baseline.jsonl` or `EBT_INV`, add the matching `--known`, `--baseline`, `--scope`. `gate.json` holds `evidence`: the names and SHA-256 of the `out/*.jsonl` files the checker read; compare them with the downloaded files. This does not catch a coordinated forgery of the evidence itself and of `gate.json` before the verdict: the evidence is written by the code under test, and the first stage's `tests_exit_code` is its claim (D45).

## Limitations

- **PRs from forks and pushes without a PR are not supported.** For them `workflow_run` usually has no `pull_requests[].base.sha`; the second stage sets `error` with the text "no BASE: a PR from a fork or a push without a PR is not supported". If `BASE` exists but `head_repository` is a fork, it sets `error` "a PR from a fork is not supported". This is not `success`.
- **No artifact means `error`.** If the first stage was cancelled or failed before the upload, the second stage sets `error` "no witnessbox-evidence artifact" and does not stay silent.
- **`ebt/` must be in the main branch.** If it is not there, the second stage gives `error` "no ebt/ in BASE: first merge ebt/ into the main branch". The check cannot be introduced by the same PR that runs it.
- **Changing `ebt/` in a PR is FAIL.** `spec.toml` and `checks.py` are taken from `BASE`; a change to `ebt/` or `tool/ebt_check/` gives `protected_paths_changed`, not PASS by the branch's spec.
- **The evidence is written by the code under test.** The action changes who issues and signs the verdict, but not who writes the evidence. A deliberate bypass in the first stage (a background process, `PATH`, `~/.gitconfig`) is not caught: this is the same D26 boundary.
- **The artifact is untrusted.** The replay copies only regular files `out/*.jsonl`; a symlink, a subdirectory or a non-`.jsonl` file is not read, and `tests_exit_code` is accepted only as the integer `0` or `1`. Anything else is `error`.
- **`workflow_run` does not fire for a PR until `ebt-verify.yml` is in the main branch.** Merge both workflows first.

## Acceptance in the demo repository

The end-to-end scenario cannot be checked in a PR of Witnessbox itself: `workflow_run` fires only for a workflow from the main branch. Acceptance runs in a separate public repository (for example, `kaufd/witnessbox-ci-demo`).

1. Create the repository and merge into `main`: `witnessbox scaffold ts ebt` with the approved `spec.toml` from the example, both workflows from the templates above with the same actions SHA, and branch protection with the required check `witnessbox/gate`.
2. A PR with a correct change: `witnessbox/gate` is `success`; `gh attestation verify gate.json ...` passes.
3. A PR that violates the rule: `failure`; `gate.md` in the summary of the second stage.
4. A PR that changes `ebt/spec.toml`: `failure` with `protected_paths_changed`, even if the branch's spec makes the check green.
5. A PR that changes `.github/workflows/ebt-verify.yml` to `exit 0`: the status is set by the version from `main`; the PR's version of the workflow is not executed.
6. A PR where the code violates the rule, and a background process from a test file outside `ebt/` rewrites the first stage's `gate.json` to `PASS` after its gate: the second stage is `failure` with `checker_failed` and without `protected_paths_changed`. The scenario must not change `ebt/`: otherwise the FAIL is explained by the protected paths and not by the recheck. The second stage takes only the evidence and `tests_exit_code` from the artifact; it will not detect their forgery. This is a D45 limitation.
7. Record the links to the runs and the results in a separate D45 paragraph with a date.

Acceptance requires an existing demo repository and is not part of the local `make test`; after the run its results are recorded in the decision log.

## Diagnostics

| Message | What it means |
|---|---|
| `no BASE: a PR from a fork or a push without a PR is not supported` | `workflow_run.pull_requests` is empty; forks are not supported in the first version |
| `a PR from a fork is not supported` | `BASE` exists, but `head_repository` does not match the workflow's repository |
| `no witnessbox-evidence artifact` | the first stage failed or was cancelled before the upload, or the artifact was renamed |
| `witnessbox not found on PATH: run actions/setup first` | the job has no `actions/setup` step, or it failed |
| `no ebt/ in BASE: first merge ebt/ into the main branch` | the main branch has no checks directory yet |
| `symlink in the evidence` / `not a regular file in the evidence` / `tests_exit_code` | the first stage's artifact is corrupted or forged |
| `gate.json` is missing | the gate could not write the result; the second stage sets `error` |
