PY      ?= python3
CHECK   := PYTHONPATH=src $(PY) -m witnessbox.checker.ebt_check
SPEC    ?= examples/basic/spec.toml
EVIDENCE ?= build/ebt/evidence.jsonl
BASELINE ?= examples/basic/baseline.jsonl
LINUX_IMAGE ?= ghcr.io/astral-sh/uv:python3.12-bookworm

.PHONY: help test test-linux release-check test-checker test-gate test-actions test-ts test-java test-dart test-sdk example check baseline clean

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
	@echo "make test-sdk     — все SDK тесты"
	@echo "make example      — пересобрать examples/basic/ и отчёт (ожидаемо находит ошибки)"
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

test-sdk: test-java test-ts test-dart

# Пример специально содержит дефекты, поэтому код выхода 1 здесь — норма.
example:
	$(PY) examples/basic/make_example.py
	@set +e; $(CHECK) --spec $(SPEC) --evidence examples/basic/evidence.jsonl \
	  --baseline examples/basic/baseline.jsonl \
	  --md examples/basic/report.md --json examples/basic/report.json --self-test; rc=$$?; \
	  test $$rc -eq 1
	@echo "→ examples/basic/report.md"

check:
	$(CHECK) --spec $(SPEC) --evidence $(EVIDENCE) --baseline $(BASELINE) \
	  --md build/ebt/report.md --json build/ebt/report.json --self-test

baseline:
	cp $(EVIDENCE) $(BASELINE)
	@echo "baseline обновлён — закоммитьте $(BASELINE) с объяснением в PR"

clean:
	rm -rf build
