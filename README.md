# Witnessbox

Evidence-based testing (EBT) of application behaviour: during tests the code records which decision it made and on what data, and an independent checker re-verifies every decision against a human-approved specification. The kit consists of a run gate, a checker and SDKs for Java, Dart and TypeScript. The runtime requires Python 3.11+ and has no third-party dependencies. The gate is a bash script tested on macOS and Linux; native Windows is not supported, and running it under WSL is not covered by tests.

## Quick start

```bash
uv tool install witnessbox          # or: pipx install witnessbox
witnessbox scaffold ts ebt          # ebt/ scaffold for the dart, ts, jvm or generic stack
witnessbox sync-pinned ebt          # copy the SDK pinned in ebt/pinned.txt into the project
# write an evidence test and ebt/prepare.sh, then commit ebt/ and the project
witnessbox test-checks ebt          # unit tests of the project checker
witnessbox gate --check-only ebt .  # wiring check; runs no tests
BASE=$(git rev-parse HEAD) witnessbox gate ebt . ../results   # gate: PASS, exit code 0
```

The scaffold contains an example `spec.toml`, `checks.py` and a stack-specific `test.sh`. A human approves the specification before the first run, and `test.sh` wires in the project's tests. The gate on a bare scaffold, before any evidence test exists, ends in ERROR (exit code `2`): no evidence is not a pass. The [quick start tutorial](https://github.com/kaufd/WitnessBox/blob/main/docs/quickstart.md) walks the whole path on a small TypeScript project: scaffold, evidence test, PASS, an injected defect, FAIL with `checker_failed`, and how to read `gate.md` and `gate.json`. To write your own specification, see [authoring a specification](https://github.com/kaufd/WitnessBox/blob/main/docs/authoring.md); the scaffold files are described in [new project](https://github.com/kaufd/WitnessBox/blob/main/docs/scaffold.md). `witnessbox gate --check-only` and `witnessbox test-checks` need 0.7.0 or later. To have a coding agent wire up the project, give it the [agent instructions](https://github.com/kaufd/WitnessBox/blob/main/docs/agent.md): it drafts the specification and stops until a human approves it. The installation provides one command, `witnessbox`, with the `gate`, `check`, `scaffold`, `sync-pinned` and `test-checks` subcommands; `witnessbox --help` lists them. The two separate commands from 0.6.0 are removed in 0.7.0. Gate exit codes: `0` PASS, `1` FAIL, `2` ERROR. The machine-readable result for CI is `gate.json` in the results directory.

`witnessbox --installation` prints the version and the SHA-256 of the gate and checker code; compare them with the release values in the [decision log](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.md). Building from source, moving from the previous distribution and migration are covered in [usage](https://github.com/kaufd/WitnessBox/blob/main/docs/usage.md).

The documentation is written in Russian.

## Guarantees and limits

The gate checks what was recorded and re-verifies the rule, but it is not a sandbox: the code under test and the gate run as the same OS user, so the guarantee is detection, not a privilege boundary ([D26](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.md)).

- A decision that was made but not recorded, with consequences not visible outside observation-level (OBS) scenarios, is not caught; mutation audit is a research tool, not part of the gate (D29).
- An installation tampered with before the run is not caught: the caller compares `gate_sha256` and `checker_sha256` with the release values (D33); in CI, `actions/setup` checks the wheel and `--installation` against the release (D45).
- A deliberate bypass from `test.sh` by the same user — a background process, `~/.gitconfig`, `PATH` — is not caught (D26).
- A coordinated substitution of evidence and `gate.json` before the verdict is not caught; in CI the trusted stage re-checks the evidence and signs the result, but the evidence is still produced by the code under test (D34, D45).
- In CI, a verdict from the untrusted `pull_request` stage is not trusted: a `workflow_run` stage re-verifies the evidence against `ebt/` from the base branch, signs `gate.json` and sets the `witnessbox/gate` commit status (D45, [CI mode](https://github.com/kaufd/WitnessBox/blob/main/docs/ci.md)).

A human approves the specification (D4). The full "attack → how it is caught → what is not" table is in the [threat model](https://github.com/kaufd/WitnessBox/blob/main/docs/security.md).

## Documents

- [Quick start](https://github.com/kaufd/WitnessBox/blob/main/docs/quickstart.md) — a tutorial from installation to the first PASS and a caught defect.
- [Authoring a specification](https://github.com/kaufd/WitnessBox/blob/main/docs/authoring.md) — from a requirement to `spec.toml`, a checker and evidence tests; the observation level (`<INV>-OBS`) and its contract.
- [Instructions for a coding agent](https://github.com/kaufd/WitnessBox/blob/main/docs/agent.md) — the same path for an AI agent: rules, stop points for human approval, commands and the final report.
- [How it works](https://github.com/kaufd/WitnessBox/blob/main/docs/example.md) — one example from requirement to verdict, for a first look.
- [Threat model](https://github.com/kaufd/WitnessBox/blob/main/docs/security.md) — what the gate detects and what it does not promise.
- [CI mode](https://github.com/kaufd/WitnessBox/blob/main/docs/ci.md) — two-stage GitHub Actions gate with a signed verdict and the `witnessbox/gate` status.
- [New project](https://github.com/kaufd/WitnessBox/blob/main/docs/scaffold.md) — the `ebt/` scaffold: specification, stack-specific `test.sh` and `pinned.txt`.
- [Architecture](https://github.com/kaufd/WitnessBox/blob/main/docs/architecture.md) — the actual modules and the verification flow.
- [Extensions](https://github.com/kaufd/WitnessBox/blob/main/docs/extensions.md) — public types and the contract for project checkers.
- [Development](https://github.com/kaufd/WitnessBox/blob/main/docs/development.md) — test commands, SDKs and the standalone build.
- [Decisions](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.md) — current status and the append-only decision log.

## License

[MIT](https://github.com/kaufd/WitnessBox/blob/main/LICENSE). The SDK files (`Ebt.java`, `ebt.ts`, `ebt.dart`) are copied into application code unchanged and carry the line `SPDX-License-Identifier: MIT`.
