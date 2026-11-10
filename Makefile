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
	@echo "make test         — тесты исходного чекера, установленного гейта и actions"
	@echo "make test-linux   — make test и make example для закоммиченного HEAD в Linux-контейнере (нужен docker)"
	@echo "make release-check — wheel+sdist, тесты из sdist, build/release/<версия>/release.json"
	@echo "make test-checker — тесты исходного чекера"
	@echo "make test-gate    — тесты установленного wheel-гейта"
	@echo "make test-actions — тесты скриптов composite actions для CI"
	@echo "make test-ts      — тесты канонического TypeScript SDK (нужен bun)"
	@echo "make test-java    — тесты канонического Java SDK (нужен JDK 17+)"
	@echo "make test-dart    — тесты канонического Dart SDK с assert и без (нужен dart)"
	@echo "make format-dart  — dart format не меняет ebt.dart: стиль 3.6 и текущий, ширина 80/100/120"
	@echo "make test-sdk     — все SDK тесты и format-dart"
	@echo "make example      — пересобрать examples/basic/ и отчёт (ожидаемо находит ошибки)"
	@echo "make e2e STACK=ts|jvm|generic — сквозной пример: заготовка → PASS → дефект → FAIL (нужны bun/gradle)"
	@echo "make check        — проверить $(EVIDENCE) по $(SPEC) с baseline $(BASELINE)"
	@echo "make baseline     — принять текущий $(EVIDENCE) как новый baseline"

test: test-checker test-gate test-actions

# Чистый клон HEAD, обычный пользователь: незакоммиченные правки сюда не попадают.
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

# ebt.dart копируется в проекты байт в байт (pinned.txt), а их CI может гонять dart format.
# Файл не меняется ни коротким стилем (3.6), ни tall-стилем текущего Dart при ширине 80–120.
# Вторая проверка — без `// dart format off`: перенос в коде виден, даже когда страховка его скрывает.
DART_SDK := src/witnessbox/resources/lib/ebt/ebt.dart
format-dart:
	@set -e; for v in 3.6 latest; do for w in 80 100 120; do \
	  echo "dart format --language-version $$v --line-length $$w"; \
	  dart format -o none --set-exit-if-changed --language-version $$v --line-length $$w $(DART_SDK); \
	  grep -vx '// dart format off' $(DART_SDK) | dart format -o none --set-exit-if-changed \
	    --language-version $$v --line-length $$w --stdin-name ebt.dart; \
	done; done

test-sdk: test-java test-ts test-dart format-dart

# Пример специально содержит дефекты, поэтому код выхода 1 здесь — норма.
example:
	$(PY) examples/basic/make_example.py
	@set +e; $(CHECK) --spec $(SPEC) --evidence examples/basic/evidence.jsonl \
	  --baseline examples/basic/baseline.jsonl \
	  --md examples/basic/report.md --json examples/basic/report.json --self-test; rc=$$?; \
	  test $$rc -eq 1
	@echo "→ examples/basic/report.md"

# Сквозной путь: заготовка → sync-pinned → PASS → дефект → FAIL checker_failed.
# Нужна установленная команда witnessbox, bun (ts/generic) и gradle с JDK 17 (jvm); сеть.
e2e:
	examples/e2e/run.sh $(STACK) $(E2E_EXAMPLE)

check:
	$(CHECK) --spec $(SPEC) --evidence $(EVIDENCE) --baseline $(BASELINE) \
	  --md build/ebt/report.md --json build/ebt/report.json --self-test

baseline:
	cp $(EVIDENCE) $(BASELINE)
	@echo "baseline обновлён — закоммитьте $(BASELINE) с объяснением в PR"

clean:
	rm -rf build
