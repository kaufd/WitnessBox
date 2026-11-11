PY      ?= python3
CHECK   := PYTHONPATH=src $(PY) -m witnessbox.checker.ebt_check
SPEC    ?= examples/basic/spec.toml
EVIDENCE ?= build/ebt/evidence.jsonl
BASELINE ?= examples/basic/baseline.jsonl
LINUX_IMAGE ?= ghcr.io/astral-sh/uv:python3.12-bookworm
STACK ?= ts
E2E_EXAMPLE = $(if $(filter generic,$(STACK)),examples/e2e/ts,examples/e2e/$(STACK))

.PHONY: help test test-linux release-check test-checker test-gate test-actions test-ts test-java test-dart format-dart test-sdk example e2e check baseline clean

help:
	@echo "make test         — tests of the source checker, the installed gate and actions"
	@echo "make test-linux   — make test and make example for the committed HEAD in a Linux container (needs docker)"
	@echo "make release-check — wheel+sdist, tests from the sdist, build/release/<version>/release.json"
	@echo "make test-checker — tests of the source checker"
	@echo "make test-gate    — tests of the installed wheel gate"
	@echo "make test-actions — tests of the composite action scripts for CI"
	@echo "make test-ts      — tests of the canonical TypeScript SDK (needs bun)"
	@echo "make test-java    — tests of the canonical Java SDK (needs JDK 17+)"
	@echo "make test-dart    — tests of the canonical Dart SDK with and without assert (needs dart)"
	@echo "make format-dart  — dart format leaves ebt.dart unchanged: style 3.6 and current, width 80/100/120"
	@echo "make test-sdk     — all SDK tests and format-dart"
	@echo "make example      — rebuild examples/basic/ and the report (expected to find errors)"
	@echo "make e2e STACK=ts|jvm|generic|dart — end-to-end example: scaffold → PASS → defect → FAIL (needs bun/gradle/flutter)"
	@echo "make check        — check $(EVIDENCE) against $(SPEC) with baseline $(BASELINE)"
	@echo "make baseline     — accept the current $(EVIDENCE) as the new baseline"

test: test-checker test-gate test-actions

# A clean clone of HEAD, an ordinary user: uncommitted changes do not get here.
test-linux:
	docker run --rm -v "$(CURDIR)":/src:ro $(LINUX_IMAGE) bash -c '\
	  set -e; useradd -m t; \
	  su t -c "git -c safe.directory=\"*\" clone -q /src /home/t/repo && cd /home/t/repo && make test example"'

release-check:
	$(PY) tests/release_check.py

test-checker:
	PYTHONPATH=src $(PY) -m unittest discover -s tests/checker -p 'test_checker.py'

test-gate:
	PYTHONPATH=src $(PY) -m unittest discover -s tests/gate -p 'test_gate.py'

test-actions:
	PYTHONPATH= $(PY) -m unittest discover -s tests/actions -p 'test_*.py'

test-ts:
	MODE=test bun test tests/sdk/ts

test-java:
	mkdir -p build/java
	javac -d build/java src/witnessbox/resources/lib/ebt/Ebt.java tests/sdk/java/EbtTest.java && java -ea -cp build/java ebt.EbtTest

test-dart:
	dart run --enable-asserts tests/sdk/dart/ebt_test.dart && dart run tests/sdk/dart/ebt_test.dart

# ebt.dart is copied into projects byte for byte (pinned.txt), and their CI may run dart format.
# The file is changed neither by the short style (3.6) nor by the tall style of current Dart at width 80–120.
# The second check runs without `// dart format off`: a line wrap in the code is visible even when the safeguard hides it.
DART_SDK := src/witnessbox/resources/lib/ebt/ebt.dart
format-dart:
	@set -e; for v in 3.6 latest; do for w in 80 100 120; do \
	  echo "dart format --language-version $$v --line-length $$w"; \
	  dart format -o none --set-exit-if-changed --language-version $$v --line-length $$w $(DART_SDK); \
	  grep -vx '// dart format off' $(DART_SDK) | dart format -o none --set-exit-if-changed \
	    --language-version $$v --line-length $$w --stdin-name ebt.dart; \
	done; done

test-sdk: test-java test-ts test-dart format-dart

# The example deliberately contains defects, so exit code 1 is normal here.
example:
	$(PY) examples/basic/make_example.py
	@set +e; $(CHECK) --spec $(SPEC) --evidence examples/basic/evidence.jsonl \
	  --baseline examples/basic/baseline.jsonl \
	  --md examples/basic/report.md --json examples/basic/report.json --self-test; rc=$$?; \
	  test $$rc -eq 1
	@echo "→ examples/basic/report.md"

# End-to-end path: scaffold → sync-pinned → PASS → defect → FAIL checker_failed.
# Needs the installed witnessbox command, bun (ts/generic), gradle with JDK 17 (jvm) or flutter (dart); network.
e2e:
	examples/e2e/run.sh $(STACK) $(E2E_EXAMPLE)

check:
	$(CHECK) --spec $(SPEC) --evidence $(EVIDENCE) --baseline $(BASELINE) \
	  --md build/ebt/report.md --json build/ebt/report.json --self-test

baseline:
	cp $(EVIDENCE) $(BASELINE)
	@echo "baseline updated: commit $(BASELINE) with an explanation in the PR"

clean:
	rm -rf build
