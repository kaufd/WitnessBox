# План: стек `generic` в заготовке и сквозные примеры в CI

> **Для исполнителя-агента:** обязательный sub-skill — superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** подключение проекта, чей инструмент тестов не совпадает с тремя шаблонами, перестаёт требовать переписывания `test.sh`. Путь «установка → заготовка → `--sync-pinned` → PASS → дефект → FAIL» проверяется в CI самого WitnessBox для TS, JVM и `generic`. Сейчас шаблоны проверяются только подменой команд и `bash -n`, а сквозной путь проходил лишь вручную в демо-репозитории.

**Архитектура:**
- Новый каталог стека `resources/scaffold/generic/` (`test.sh`, `pinned.txt`): команда тестов и каталог свидетельств задаются переменными, договор гейта прежний.
- Примеры `examples/e2e/ts/` и `examples/e2e/jvm/` — минимальные проекты, реализующие правило шаблонной spec (`REQ-EXAMPLE-1`, `value × 2`). Поэтому `spec.toml`, `checks.py` и `test_checks.py` берутся из заготовки без изменений.
- Драйвер `examples/e2e/run.sh` собирает временный git-репозиторий, накладывает заготовку и прогоняет гейт дважды. CI-задача `e2e` запускает его для `ts`, `generic` (тот же TS-проект) и `jvm`.

**Стек:** bash 3.2-совместимый shell, Bun + Vitest, Gradle + JUnit 5, GitHub Actions.

**Источник требований:** обсуждение 2026-11-02 (пункты 6 и 7 списка развития); D19 (отложенный пример полного подключения), D31/D32 (договор заготовки), [docs/scaffold.md](../../scaffold.md).

**Зависимость:** если план `2026-11-02-check-only-test-checks.md` уже выполнен, драйвер вызывает `ebt-gate --check-only` и `--test-checks` (задача 3, шаг 3). Если нет — эти два вызова пропускаются, остальное не меняется.

## Глобальные ограничения

- Договор `test.sh` (`OUT_DIR`, аргументы из `EBT_TESTS`, коды 0/1/2, свидетельства при любом исходе) и формат `pinned.txt` не меняются; меняется только набор стеков `--scaffold`.
- Шаблоны совместимы с macOS `/bin/bash` 3.2: без `${var,,}`, без пустых массивов под `set -u`.
- Шаблонная spec — пример, а не утверждённая спецификация (D4); примеры e2e используют её только как фиксированный тестовый вход.
- Runtime без новых зависимостей. Bun, Gradle и JUnit нужны только примерам и CI, не поставке.
- В репозиторий не коммитятся бинарники: Gradle wrapper генерируется драйвером во временном репозитории командой `gradle wrapper`.
- Версии инструментов в CI и примерах закрепляются точно и не моложе двух недель: Gradle, JUnit, Vitest (через `bun.lock`), actions по SHA.
- `make test` остаётся без сети и без Bun/Gradle; e2e — отдельная цель `make e2e`.
- Изменение заготовки — вместе с `docs/scaffold.md` и тестами (CLAUDE.md); запись D48, версия `0.7.0`.

## Фокус ревью

1. `EBT_TEST_CMD` не задана: `generic/test.sh` даёт код 2 с подсказкой, а не запускает пустую команду.
2. Команда тестов вернула 1 при сломанной сборке (Maven, Gradle без разбора XML): по умолчанию `generic` отдаёт 1. В `docs/scaffold.md` явно сказано, что различение «упали тесты / не собралось» — забота проекта, и показан `EBT_TEST_FAIL_CODES`.
3. Аргументы `EBT_TESTS` с пробелами и спецсимволами в команде: передаются отдельными словами через `"$@"`, без `eval`.
4. Стали свидетельства прошлого прогона в каталоге свидетельств: `generic/test.sh` очищает его до запуска команды, как шаблоны `ts` и `jvm`.
5. Драйвер e2e не должен зеленеть, если гейт PASS-ит дефект: второй прогон обязан дать код 1 и `checker_failed` в `gate.json.reasons`. Иное — провал задачи CI.

---

### Задача 1: Стек `generic`

**Файлы:**
- Создать: `src/witnessbox/resources/scaffold/generic/test.sh`, `src/witnessbox/resources/scaffold/generic/pinned.txt`
- Изменить: `src/witnessbox/cli.py` (`SCAFFOLD_STACKS = ("dart", "ts", "jvm", "generic")`, текст `usage`)
- Тест: `tests/gate/test_gate.py` (`test_scaffold_creates_ebt_for_each_stack` — `generic` в списке; `test_scaffold_test_scripts_follow_gate_contract` — подтест `generic`; новый `test_generic_test_script_settings`)

**Интерфейсы:**
- Производит: переменные `generic/test.sh`:
  - `EBT_TEST_CMD` — обязательная строка команды, исполняется как `bash -c "$EBT_TEST_CMD"' "$@"' _ "$@"`;
  - `EBT_EVIDENCE_DIR` — по умолчанию `build/ebt`;
  - `EBT_TEST_FAIL_CODES` — коды команды, означающие «тесты выполнились и упали», через пробел, по умолчанию `1`.

  Отображение кодов: 0 → 0; код из `EBT_TEST_FAIL_CODES` → 1; всё остальное → 2.
- Производит: `generic/pinned.txt` — только комментарии с форматом строки и примерами для всех трёх SDK. Пустой набор строк гейт уже принимает.

- [x] **Шаг 1: Тесты.**
  - В `test_scaffold_creates_ebt_for_each_stack` добавить `generic`.
  - В `test_scaffold_test_scripts_follow_gate_contract` — подтест `generic` с `EBT_TEST_CMD=<fake-команда>`. Проверяются те же ожидания, что для `ts`: аргументы `EBT_TESTS`, свидетельства в `OUT_DIR` при кодах 0, 1 и 7, итоговые коды 0, 1 и 2.
  - `test_generic_test_script_settings` проверяет:
    - без `EBT_TEST_CMD` → код 2 и `EBT_TEST_CMD` в stderr;
    - `EBT_EVIDENCE_DIR=out/ev` → берутся файлы оттуда;
    - `EBT_TEST_FAIL_CODES="1 4"` и код команды 4 → 1;
    - аргумент `"a b"` приходит одним словом;
    - старый файл в каталоге свидетельств не попадает в `OUT_DIR`.
- [x] **Шаг 2: Запуск — FAIL** (`make test-gate`: стека нет).
- [x] **Шаг 3: Реализовать шаблоны.** Заголовок `test.sh` устроен как у `jvm`: договор, затем переменные с умолчаниями. `bash -n` проходит.
- [x] **Шаг 4:** `make test-gate` — зелёный.
- [x] **Шаг 5: Коммит** `Заготовка: стек generic с командой тестов из EBT_TEST_CMD (D48)`.

---

### Задача 2: Рецепты в `docs/scaffold.md`

**Файлы:** `docs/scaffold.md` (таблица стеков, новый раздел «Стек generic»), `src/witnessbox/resources/scaffold/README.md` (одна строка о `generic`).

- [x] **Шаг 1:** строка `generic` в таблице стеков: «любой инструмент», `test.sh` — `$EBT_TEST_CMD`, SDK — по языку.
- [x] **Шаг 2:** раздел с рецептами. Значения переменных и строка `pinned.txt` для каждого:
  - npm + Jest: `EBT_TEST_CMD="npx jest --testPathPattern ebt"`; с TS SDK — оговорка из `docs/sdk.md` о `import.meta.env`: Jest его не задаёт, нужен Vite/Vitest или своя подстановка.
  - pnpm + Vitest: `EBT_TEST_CMD="pnpm exec vitest run .ebt.test"`.
  - Maven: `EBT_TEST_CMD="mvn -q test -Dtest='*EbtTest'"`, `EBT_EVIDENCE_DIR=target/ebt`. Предупреждение из фокуса ревью п. 2: Maven возвращает 1 и на сломанную сборку; для точности перейдите на разбор отчётов, как в `jvm/test.sh`.
  - `dart test` без Flutter: `EBT_TEST_CMD="dart test test/ebt"`.
- [x] **Шаг 3:** абзац «pytest»: SDK для Python не поставляется. Подключение Python-проекта ждёт решения о Python SDK (см. план `2026-11-02-sdk-conformance.md`), поэтому рецепта нет.
- [x] **Шаг 4: Коммит** `docs/scaffold: рецепты стека generic (D48)`.

---

### Задача 3: Сквозные примеры и драйвер

**Файлы:**
- Создать: `examples/e2e/run.sh`
- Создать: `examples/e2e/ts/` —
  - проект: `package.json`, `bun.lock`, `tsconfig.json`, `vitest.config.ts`;
  - код и тест: `src/double.ts`, `double.ebt.test.ts`;
  - наложение на заготовку: `ebt/prepare.sh` (`bun install --frozen-lockfile`), `ebt/pinned.txt`;
  - дефект: `defect/src/double.ts`.
- Создать: `examples/e2e/jvm/` —
  - проект: `settings.gradle`, `build.gradle` (Java 17, JUnit 5);
  - код и тест: `src/main/java/example/Doubler.java`, `src/test/java/example/DoublerEbtTest.java`;
  - наложение на заготовку: `ebt/pinned.txt`;
  - дефект: `defect/src/main/java/example/Doubler.java`.
- Изменить: `Makefile` (цель `e2e`, `STACK ?= ts`), `docs/development.md`
- Изменить: `.gitignore`, если нужно для `node_modules`/`build` внутри примеров

**Интерфейсы:**
- Производит: `examples/e2e/run.sh <stack> <example-dir>`, где `<stack>` — `ts`, `jvm` или `generic`. Использует `ebt-gate` с `PATH`. Коды: 0 — оба ожидания выполнены; 1 — ожидание не выполнено (сообщение говорит какое); 2 — ошибка окружения (нет `bun`/`gradle`/`git`).
- Тесты примеров пишут свидетельства в `build/ebt/double.jsonl` через SDK по пути из `ebt/pinned.txt`. Свидетельство — `{"value", "result"}` для классов `zero`, `positive`, `negative`, как требует шаблонная spec.
- Make: `make e2e STACK=ts|jvm|generic` вызывает `examples/e2e/run.sh $(STACK) examples/e2e/<ts для generic, иначе STACK>`.

- [x] **Шаг 1: Драйвер `run.sh`.** Шаги:
  1. Временный каталог, `git init`, копирование примера без `defect/`.
  2. `ebt-gate --scaffold <stack> ebt`, затем копирование `example/ebt/*` поверх заготовки.
  3. Для `jvm` — `gradle wrapper --gradle-version <закреплённая>`.
  4. `ebt-gate --sync-pinned ebt`.
  5. Если доступны — `ebt-gate --test-checks ebt` и `ebt-gate --check-only ebt .`, оба с кодом 0.
  6. Коммит; `BASE` = этот коммит.
  7. Прогон 1: `ebt-gate ebt . <run1>` → код 0.
  8. Наложение `defect/` поверх проекта и коммит.
  9. Прогон 2: `ebt-gate ebt . <run2>` → код 1. В `gate.json.reasons` есть `checker_failed`, нет `protected_paths_changed`. Разбор — через `python3 -I -c` с `json`.
  10. Для `generic` экспортируется `EBT_TEST_CMD="bunx vitest run .ebt.test"`.

  Каталог результатов печатается при отказе, временный каталог удаляется при успехе.
- [x] **Шаг 2: Пример TS.** Повторяет проверенный демо-проект D45 без CI-файлов: `double(value)`, тест с тремя классами и `ev("INV-EXAMPLE-1", "REQ-EXAMPLE-1", …)`. `bun.lock` закоммичен, Vitest — точная версия.
- [x] **Шаг 3: Пример JVM.** `Doubler.twice(int)`, JUnit-тест `DoublerEbtTest` с тремя классами и `Ebt.ev(...)`; запись `Ebt.toJsonl()` в `build/ebt/double.jsonl` в `@AfterAll`. Путь SDK — `src/test/java/ebt/Ebt.java` (из шаблонного `jvm/pinned.txt`).
- [x] **Шаг 4: Локальная проверка.**
  1. Собрать и поставить wheel: `uv build && uv tool install --force dist/witnessbox-*.whl`.
  2. `make e2e STACK=ts` → 0.
  3. `make e2e STACK=generic` → 0.
  4. `make e2e STACK=jvm` → 0, если есть `gradle` и JDK 17; иначе проверка JVM — только в CI, это записать в PR.
  5. Контроль чувствительности: временно сделать дефект корректным кодом → драйвер даёт код 1 «дефект не обнаружен». Затем вернуть.
- [x] **Шаг 5: Коммит** `Сквозные примеры TS и JVM и драйвер e2e (D48)`.

---

### Задача 4: CI-задача `e2e`

**Файлы:** `.github/workflows/test.yml` (новый job), `docs/development.md`.

- [x] **Шаг 1:** job `e2e` на `ubuntu-latest`, матрица `stack: [ts, generic, jvm]`, `fail-fast: false`, права `contents: read`. Шаги:
  - `actions/checkout`, `astral-sh/setup-uv`;
  - сборка и установка wheel из checkout (`uv build`, `uv tool install dist/witnessbox-*.whl`);
  - для `ts`/`generic` — `oven-sh/setup-bun`;
  - для `jvm` — `actions/setup-java` (Temurin 17) и `gradle/actions/setup-gradle` с `gradle-version`;
  - `make e2e STACK=${{ matrix.stack }}`.

  Все `uses:` закреплены SHA (сверка — `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`).
- [x] **Шаг 2:** `check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/test.yml` → `ok`.
- [x] **Шаг 3:** в `docs/development.md` — что делает `make e2e` и какие инструменты нужны.
- [ ] **Шаг 4:** PR и зелёный CI во всех трёх `e2e` и прежних заданиях.
- [x] **Шаг 5: Коммит** `CI: сквозные примеры ts, generic и jvm (D48)`.

---

### Задача 5: Решение D48

**Файлы:** `docs/decisions.md` (D48, «Текущий статус»), `docs/usage.md` (`--scaffold <dart|ts|jvm|generic>`), `README.md` (Quick start — `generic` в перечне стеков).

- [x] **Шаг 1:** D48 «Стек `generic` и сквозные примеры в CI». Содержание:
  - причины — переписывание `test.sh` под инструмент и отсутствие сквозной проверки (D19);
  - устройство `generic`: переменные, отображение кодов и его граница для Maven/Gradle;
  - примеры используют шаблонную spec как фиксированный вход, а не как утверждённую;
  - Gradle wrapper генерируется, бинарники не коммитятся;
  - Python-рецепта нет до решения о Python SDK;
  - демо-репозиторий D45 этими примерами заменён;
  - версия `0.7.0`.

  Статус: принято.
- [x] **Шаг 2:** `make test example` — зелёный.
- [x] **Шаг 3: Коммит** `Решение D48: стек generic и сквозные примеры`.

## Что не входит

- Python SDK и рецепт pytest (отдельное решение).
- Пример Dart/Flutter в CI: Flutter SDK тяжёл для каждого PR. Dart SDK уже проверяется `make test-sdk`, Flutter-шаблон — подменой команды.
- Изменение шаблонов `ts`, `jvm`, `dart`.
