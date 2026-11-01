# План: `ebt-gate --check-only` и `ebt-gate --test-checks`

> **Для исполнителя-агента:** обязательный sub-skill — superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** ошибки подключения находятся до прогона тестов, а тесты проектного чекера запускаются одной командой. Сейчас неверная `spec.toml`, неисполняемый `test.sh` или `pinned_drift` выясняются только после полного прогона. Тесты `checks.py` запускаются обходным рецептом с `python` из `--installation` (D32).

**Архитектура:** две новые ветки `cli.py` рядом с `--scaffold` и `--sync-pinned`.
- `--check-only` повторяет предварительные проверки гейта без запуска `prepare.sh`, `test.sh` и чекера по свидетельствам. Разбор `pinned.txt` общий с `--sync-pinned`. Проверки spec и расширений вызывают те же функции чекера, что и `ebt-check`.
- `--test-checks` запускает `unittest` интерпретатором установки.

**Стек:** Python 3.11+ stdlib, git.

**Источник требований:** обсуждение 2026-11-02 (пункты 11 и 12 списка развития); D32, D44; [gate.sh](../../../src/witnessbox/gate.sh) — предварительные проверки; [input.py](../../../src/witnessbox/checker/input.py) — `load_spec`, `load_checkers`, `load_known`, `validate_known`.

## Глобальные ограничения

- Runtime без сторонних зависимостей; Python 3.11+.
- Гейт (`gate.sh`) не меняется: `--check-only` — подсказка до прогона, вердикт по-прежнему выносит только гейт.
- `--check-only` не исполняет `prepare.sh` и `test.sh` и не меняет файлы. Исключение — `checks.py`: он импортируется так же, как в чекере, это доверенный проектный код (docs/extensions.md).
- Каждая проблема, которую находит `--check-only`, на том же входе даёт гейту не-PASS. Обратное не обещается: тесты и свидетельства команда не проверяет.
- Сообщения — на русском, идентификаторы — на английском.
- Новые команды — совместимое изменение интерфейса: версия `0.7.0`, запись D47 (append-only).
- `cli.py` входит в `gate_sha256`: новый отпечаток записывается при выпуске.

## Фокус ревью

1. Клон с `skip-worktree` или `assume-unchanged` при чистом `git status`: `--check-only` сообщает о скрытых правках, как гейт.
2. `spec.toml` ссылается на чекер, которого нет ни в ядре, ни в `checks.py`: проблема «чекер … не зарегистрирован», а не молчание до `NO_CHECKER` в отчёте.
3. `checks.py` падает при импорте или регистрирует имя чекера ядра: проблема с текстом ошибки, без traceback и без кода 2.
4. `--test-checks` в каталоге без `test_*.py`: `unittest` находит 0 тестов. Нулевой прогон — код 1 с сообщением, а не зелёный 0.
5. `--check-only` без `BASE`: защищённые пути не проверяются. Вывод говорит об этом явно, а не пишет «ок».

---

### Задача 1: Общий разбор `pinned.txt`

**Файлы:**
- Изменить: `src/witnessbox/cli.py` (`sync_pinned`)
- Тест: `tests/gate/test_gate.py` — существующие тесты `--sync-pinned` должны остаться зелёными без правок

**Интерфейсы:**
- Производит: `read_pinned(ebt: Path, root: Path) -> tuple[list[PinnedCopy], str | None]` в `cli.py`. Второй элемент — текст первой ошибки с номером строки, тот же, что сейчас печатает `--sync-pinned` после префикса.
- Производит: `PinnedCopy = tuple[int, Path, str, Path]` — `(номер строки, оригинал, dest как в файле, разрешённый путь назначения)`.
- `sync_pinned` вызывает `read_pinned` и сохраняет прежний вывод и коды.

- [ ] **Шаг 1:** вынести первый проход `sync_pinned` (чтение байтов, `\r`, комментарии, `kit:`/абсолютный/относительный оригинал, отсутствие оригинала, абсолютный dest, выход за корень, каталог, повтор пути) в `read_pinned`.
- [ ] **Шаг 2:** `PYTHONPATH=src python3 -m unittest tests.gate.test_gate.Gate -k sync_pinned` — зелёный, тексты ошибок прежние.
- [ ] **Шаг 3: Коммит** `cli: общий разбор pinned.txt для --sync-pinned и --check-only`.

---

### Задача 2: `ebt-gate --check-only <ebt-dir> <clone>`

**Файлы:**
- Изменить: `src/witnessbox/cli.py` (новая функция `check_only`, ветка в `main` до `installation()`)
- Тест: `tests/gate/test_gate.py`, новый класс-миксин не нужен — методы в `Gate`, помощник `self.check_only(env=None) -> CompletedProcess`, запускающий установленный `ebt-gate --check-only <self.ebt> <self.clone>` с `PYTHONPATH=""`

**Интерфейсы:**
- Потребляет: `read_pinned` (задача 1); `load_spec`, `load_checkers`, `load_known`, `validate_known`, `load_jsonl` из `witnessbox.checker.input`; `CHECKERS` из `witnessbox.checker.checkers`.
- Производит: `check_only(argv: list[str]) -> int`. Коды:
  - `0` — проблем нет;
  - `1` — найдены проблемы, гейт на этом входе не даст PASS;
  - `2` — ошибка вызова: неверные аргументы или нет каталога.
- Вывод — по строке на проверку: `ок <проверка>`, `проблема <проверка>: <текст>` или `пропущено <проверка>: <причина>`. Проверки по порядку:
  1. `spec` — `ebt/spec.toml` есть и проходит `load_spec`.
  2. `checks` — если есть `checks.py`, проходит `load_checkers`. Каждый `inv.checker` из spec есть в `CHECKERS` после загрузки.
  3. `known` — если есть `known.toml`, проходит `load_known` и `validate_known`.
  4. `baseline` — если есть `baseline.jsonl`, `load_jsonl` без битых строк.
  5. `runner` — правила `select_runner` из `gate.sh`: `test.sh` — исполняемый обычный файл; `EBT_RUNNER` — `''`, `test.sh` или `flutter`; без `test.sh` и без `EBT_RUNNER` — `ок` с пометкой «legacy Flutter adapter».
  6. `pinned` — `read_pinned` без ошибки, каждая копия совпадает с оригиналом байт в байт. Расхождение — проблема со списком путей.
  7. `clone` — `git status --porcelain` пуст; в `git ls-files -v` нет строк с флагом `[a-zS]`, как в `gate.sh:93`.
  8. `base` — если задан `BASE`, коммит существует и `git diff --name-only BASE HEAD -- ebt tool/ebt_check` пуст; без `BASE` — `пропущено`.

- [ ] **Шаг 1: Тесты.** Исходное состояние `setUp` класса `Gate`: spec без `checks.py` и чистый клон. Тестовый `test.sh` создаётся через `self.gate(...)` или явной записью исполняемого файла.
  - `test_check_only_clean_project_is_ok` → код 0, все строки `ок`, кроме `пропущено base`.
  - `test_check_only_reports_each_problem` — по подтесту на каждый пункт фокуса ревью 1–3:
    - неизвестный `inv.checker`;
    - `checks.py` с `raise RuntimeError("boom")`;
    - `checks.py`, регистрирующий `cart_total`;
    - неисполняемый `test.sh`;
    - `pinned.txt` с расхождением;
    - грязный клон;
    - `git update-index --skip-worktree` на закоммиченном файле;
    - `BASE` при изменённом `ebt/` в клоне. В `Gate` каталог проверки `self.ebt` лежит вне клона, поэтому подтест коммитит `ebt/marker` в клон, берёт этот коммит как `BASE` и меняет `ebt/marker` следующим коммитом.

    Ожидание в каждом подтесте: код 1, строка `проблема <проверка>`, в stderr нет `Traceback`.
  - `test_check_only_problems_are_not_gate_pass` — для тех же подтестов `self.gate(self.write_to('"$OUT_DIR"'))` возвращает не 0 (FAIL или ERROR). Так закреплено ограничение «каждая проблема — не-PASS гейта».
  - `test_check_only_usage_errors` — без аргументов и с несуществующим каталогом → код 2, `usage:` или «нет каталога» в stderr.
- [ ] **Шаг 2: Запуск — FAIL** (`PYTHONPATH=src python3 -m unittest tests.gate.test_gate.Gate -k check_only`): аргумент уходит в `gate.sh`, коды и вывод не совпадают.
- [ ] **Шаг 3: Реализовать `check_only`.** Функции чекера импортируются внутри функции, чтобы `--scaffold` и `--version` не тянули модули чекера. `ValueError`/`OSError` из них превращаются в строку `проблема`. Git вызывается через `subprocess.run([...], cwd=clone, capture_output=True, text=True)`. Отказ git — `проблема clone: git … упал`.
- [ ] **Шаг 4:** `make test-gate` — зелёный.
- [ ] **Шаг 5: Коммит** `ebt-gate --check-only: проверки подключения до прогона (D47)`.

---

### Задача 3: `ebt-gate --test-checks [<ebt-dir>]`

**Файлы:**
- Изменить: `src/witnessbox/cli.py` (функция `test_checks`, ветка в `main`)
- Изменить: `src/witnessbox/resources/scaffold/test_checks.py` (docstring), `src/witnessbox/resources/scaffold/README.md` (шаг 2), `docs/scaffold.md` (шаг 2)
- Тест: `tests/gate/test_gate.py`

**Интерфейсы:**
- Производит: `test_checks(argv: list[str]) -> int`. `<ebt-dir>` по умолчанию `ebt`. Запускает `[sys.executable, "-I", "-m", "unittest", "discover", "-s", <ebt-dir>, "-t", <ebt-dir>, "-p", "test_*.py", "-v"]` и возвращает его код. Если `unittest` сообщил `Ran 0 tests`, возвращает 1 и пишет «тестов чекера не найдено» (п. 4 фокуса ревью).

- [ ] **Шаг 1: Тесты.**
  - `test_test_checks_runs_scaffold_tests` — `--scaffold ts <dir>`, затем `--test-checks <dir>` установленной командой из чужого cwd с системным `PATH` → код 0, в выводе `OK`.
  - `test_test_checks_fails_on_broken_checker` — в `checks.py` заготовки `expected = value * 2` заменено на `value * 3` → код 1.
  - `test_test_checks_without_tests_is_not_green` — каталог только с `checks.py` → код 1 и сообщение.
- [ ] **Шаг 2: Запуск — FAIL.**
- [ ] **Шаг 3: Реализовать.** Подсчёт тестов — по строке `Ran N tests` в объединённом выводе `unittest`, который сначала печатается пользователю как есть.
- [ ] **Шаг 4: Обновить инструкции.** В docstring `test_checks.py`, README заготовки и `docs/scaffold.md` рецепт из D32 (`python=$(ebt-gate --installation | …)`) заменяется на `ebt-gate --test-checks ebt`. Тест D32 `test_scaffold_*`, запускающий пример ровно по инструкции, переводится на новую команду.
- [ ] **Шаг 5:** `make test` — зелёный.
- [ ] **Шаг 6: Коммит** `ebt-gate --test-checks: тесты проектного чекера интерпретатором поставки (D47)`.

---

### Задача 4: Документы и решение D47

**Файлы:** `docs/usage.md` (таблица поддерживаемого интерфейса, раздел запуска), `docs/scaffold.md` (шаг 6 — `--check-only` перед первым запуском гейта), `docs/decisions.md` (D47, «Текущий статус»), `cli.py` — текст подсказки `scaffold` (порядок «test-checks → sync-pinned → check-only → гейт»).

- [ ] **Шаг 1:** D47 «`--check-only` и `--test-checks`». Содержание:
  - причины — поздние ошибки подключения и рецепт D32;
  - `--check-only` — подсказка, а не вердикт; гарантирована только связь «проблема → не-PASS»;
  - `checks.py` импортируется; `prepare.sh` и `test.sh` не запускаются;
  - нулевой прогон тестов чекера — не успех;
  - версия `0.7.0`.

  Статус: принято.
- [ ] **Шаг 2:** `make test example` — зелёный, четыре дефекта.
- [ ] **Шаг 3: Коммит** `Документы: --check-only и --test-checks (D47)`.

## Что не входит

- Запуск тестов проекта, проверка свидетельств и self-test — это делает гейт.
- Предсказание `tests_failed`, `uncovered_partitions` и `weak_required`.
- Изменение `gate.sh` и формата `gate.json`.
