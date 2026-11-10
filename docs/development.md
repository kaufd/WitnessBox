# Development

**English** · [Русский](development.ru.md)

You need Python 3.11+ and `uv` to install and build the wheel and sdist. The runtime uses the standard library. The SDK tests require JDK 17+ and Bun.

From the repository root:

```bash
make test        # source checker, installed wheel gate, ebt/ scaffold and actions scripts
make test-actions  # only the actions/setup and actions/verify scripts
make test-sdk    # Java, TypeScript and Dart SDKs
make format-dart  # dart format does not change ebt.dart (part of test-sdk)
make example     # rebuild the demonstration with four intentional defects
make e2e STACK=ts|jvm|generic  # end-to-end example: scaffold → PASS → defect → FAIL
make test-linux  # make test and make example for the committed HEAD in a Linux container
make release-check  # release check: sdist → wheel, tests from the sdist, wheel comparison
```

`make test` and `make example` work without a network and without Bun/Gradle. `make e2e`
builds a temporary git repository, applies the scaffold and the example, runs the
installed `witnessbox gate` command twice and checks for `checker_failed`; it needs `witnessbox` from the
wheel, Bun (for `ts` and `generic`), Gradle with JDK 17 (for `jvm`) and a network for
dependencies. The generated Gradle wrapper and `node_modules` are not
committed to the repository.

The [test](../.github/workflows/test.yml) workflow runs `make test example` on Linux and macOS (Python 3.11 and 3.13), `make test-sdk` and `make e2e` for `ts`, `generic` and `jvm` on every PR; `make test-linux` and `make release-check` stay local.

Standalone artifacts are built and checked separately:

```bash
uv build
uv tool install --force dist/witnessbox-0.8.0-py3-none-any.whl
```

The gate integration tests install the wheel into a temporary isolated environment; they check the distribution without an editable install and without `PYTHONPATH`. The source-checker tests use `PYTHONPATH=src` locally as development-tree tests. Project extensions do not need this trick: installed checkers import the types through `witnessbox.api`.

`make release-check` builds the sdist and a wheel from it, runs `make test example` and `make test-sdk` (if bun, javac and dart are present) from the extracted sdist, compares the wheel from the sdist with the release one, and installs the release wheel into a clean venv without an index, checking the version and the installation fingerprints. The result, the version and the SHA-256 of the artifacts are in `build/release/<version>/release.json`. `uv build` builds the sdist, and the wheel from it. `uv build --wheel` builds directly from the working tree and reuses a stale `build/lib`: modules deleted from the sources may end up in the wheel, so only the build through the sdist is used for releases and checks.

`make test-linux` needs a working docker; the image is set by `LINUX_IMAGE`. On Linux, only the gate check without access to the sources is skipped: it uses macOS `sandbox-exec`.

`make example` is expected to get FAIL, because the example contains four defects. It also runs the self-test. When you change the checker or the classification, add targeted cases of correct evidence and of each changed error class, then run `make test` and `make example`. SDK changes require the corresponding tests (`make test-sdk`). The detailed rules for changes are listed in the root [CLAUDE.md](../CLAUDE.md).

## Release

Exactly the files that `make release-check` verified are published: the [publish](../.github/workflows/publish.yml) workflow builds nothing, but downloads the wheel, sdist and `release.json` from the GitHub Release of the tag, checks the SHA-256 against `release.json` and uploads the files through Trusted Publishing (D40).

1. Bump `version` in `pyproject.toml`, commit, and run `make release-check`: the result is PASS in `build/release/<version>/release.json`.
2. Tag that commit and push the tag: `git tag -a v<version> -m ...`, `git push origin v<version>`.
3. Create a prerelease with the verified files: `gh release create v<version> --prerelease build/release/<version>/dist/* build/release/<version>/release.json`.
4. Optional, a trial release (needs a pending publisher on test.pypi.org with the `testpypi` environment): `gh workflow run publish.yml -f tag=v<version> -f index=testpypi`, then install into a clean environment: `uv tool run --default-index https://test.pypi.org/simple/ --from witnessbox==<version> witnessbox --installation` and `witnessbox scaffold` into a temporary directory.
5. Release: `gh workflow run publish.yml -f tag=v<version> -f index=pypi`; compare the SHA-256 of the files on PyPI with `release.json`, check `uvx --from witnessbox==<version> witnessbox --installation` and `--scaffold`, then `gh release edit v<version> --prerelease=false --latest`.
6. In the next commit, add the release entry with the SHA-256 to the decision log.

PyPI does not allow uploading a file again with the same version, so an error after step 5 can be fixed only with a new version.

## Import compatibility

The library imports `from checkers import Verdict, WitnessError` and `from ebt_verification.api import Verdict, WitnessError` stay compatible for the installed distribution: both return objects from `witnessbox.api`. The internal modules of the old package (`ebt_verification.checker.*`, `ebt_verification.cli`) are not re-exported: they are not a supported interface, and after the rename their paths are `witnessbox.checker.*` and `witnessbox.cli`. The preferred public import is `from witnessbox.api import Verdict, WitnessError`; the new scaffold templates use it. The current source tree has neither a `tool/ebt_check` directory shim nor a `lib/ebt` symlink.
