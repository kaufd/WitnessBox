# План: CI репозитория, усиленный self-test, `ebt-gate --sync-pinned`

> **Для исполнителя-агента:** обязательный sub-skill — superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** первый этап развития после 0.5.2. Тесты репозитория идут в CI на каждый PR. Self-test ловит чекер, который смотрит только на часть списка. SDK-копии из `pinned.txt` обновляются одной командой. Результат — версия `0.6.0`, не опубликованная.

**Архитектура:** CI — отдельный workflow без сборки выпуска. Self-test остаётся в `checker/engine.py`: мутации и учёт ведутся по пути внутри поля (`lines[1].qty`), а не только по полю верхнего уровня. `--sync-pinned` — новая ветка `cli.py` рядом с `--scaffold`; формат `pinned.txt` разбирается так же, как в `gate.sh`.

**Стек:** Python 3.11+ (только stdlib), bash, GitHub Actions, uv.

**Источник требований:** обсуждение в сессии 2026-11-01 (пункты «CI для тестов», 2 и 9), [CLAUDE.md](../../../CLAUDE.md), [decisions.md](../../decisions.md) D15, D16, D25, D26, D33.

## Глобальные ограничения

- Runtime не получает сторонних зависимостей; только stdlib Python 3.11+.
- Чекер не импортирует приложение или SDK и не полагается на `ok`.
- Документация, сообщения и отчёты — на русском; идентификаторы и код — на английском.
- Решения append-only: новые записи D43, D44 с датой, причиной и статусом; старые записи не трогаются.
- После изменения чекера — `make test` и `make example`; демонстрация по-прежнему находит все четыре дефекта.
- Шаблоны заготовки рассчитаны на macOS `/bin/bash` 3.2.
- Новые поля JSON — совместимое изменение; смысл существующих полей не меняется.
- Изменение `cli.py` и `engine.py` меняет `gate_sha256`/`checker_sha256` — это ожидаемо, значения записываются при выпуске, а не в этом плане.
- Новый Runner API, UI и runtime-зависимости не вводятся.

## Фокус ревью

1. Поле-список в witness пустое или длиной в сотни элементов: self-test не взрывается по времени, пустой список не даёт ложной слабости.
2. Список, который чекер законно сравнивает как множество: self-test не должен объявлять его слабым только из-за порядка (поэтому оператора перестановки нет).
3. Поле, которое законно не влияет на вердикт, внутри элементов списка: `not_in_verdict = ["lines[*].note"]` снимает FAIL.
4. `pinned.txt` с CRLF, комментариями, пустыми строками и строкой из одного токена: `--sync-pinned` разбирает его так же, как гейт, и после синхронизации гейт не даёт `pinned_drift`.
5. Путь назначения в `pinned.txt` абсолютный, с `..` или через symlink за пределы проекта: `--sync-pinned` отказывает (код 2) и ничего не пишет, даже если предыдущие строки корректны.

---

### Задача 1: CI для тестов репозитория

**Файлы:**
- Создать: `.github/workflows/test.yml`
- Изменить: `docs/development.md` (раздел о проверках — одна фраза про CI)

**Интерфейсы:** не потребляет и не производит кода.

- [ ] **Шаг 1: Убедиться, что `make example` детерминирован**

Run: `make example && git status --porcelain examples/`
Expected: пустой вывод. Если `examples/basic/*` меняются при повторном запуске, CI-проверку `git diff --exit-code examples/` не включать, а записать причину в PR.

- [ ] **Шаг 2: Написать `.github/workflows/test.yml`**

- `on: push` в `main`, `pull_request`; `permissions: contents: read`; `concurrency` по ref с отменой прежнего запуска.
- Job `python`: матрица `os: [ubuntu-latest, macos-latest]`, `python: ["3.11", "3.13"]`; шаги — checkout, setup-python, setup-uv, `make test example PY=python`, затем `git diff --exit-code examples/` (если шаг 1 прошёл).
- Job `sdk` на `ubuntu-latest`: setup-java (Temurin 17), setup-bun, setup-dart; `make test-sdk`.
- Каждое `uses:` закреплено полным SHA коммита с комментарием версии, как в `publish.yml`. SHA берутся командой `gh api repos/<owner>/<action>/git/ref/tags/<tag> --jq .object.sha` (для annotated-тега — разыменовать до коммита).
- Комментарий в начале файла на русском: что проверяет workflow и почему он ничего не публикует.

- [ ] **Шаг 3: Проверить синтаксис локально**

Run: `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/test.yml`
Expected: `ok -- validation done`.

- [ ] **Шаг 4: Дописать в `docs/development.md`** одну фразу: `make test example` на Linux и macOS (Python 3.11 и 3.13) и `make test-sdk` выполняются workflow `test.yml` на каждый PR; `make test-linux` и `make release-check` остаются локальными.

- [ ] **Шаг 5: Коммит, PR, зелёный CI**

```bash
git switch -c ci/tests
git add .github/workflows/test.yml docs/development.md
git commit -m "CI: тесты чекера, гейта, примера и SDK на каждый PR"
```

Expected: в PR все задания зелёные. Тест `sandbox-exec` на Linux пропускается — это известно (D33).

---

### Задача 2: Self-test по каждому элементу списка

**Файлы:**
- Изменить: `src/witnessbox/checker/engine.py:266-349` (`_mutate`, `self_test`) и `:381-388` (`weak_required`)
- Изменить: `src/witnessbox/checker/rendering.py:102-113`
- Тест: `tests/checker/test_checker.py` (класс `Classification`, рядом с `test_self_test_finds_ignored_field`)
- Документы: `docs/security.md` (новая строка таблицы), `docs/extensions.md` (абзац о self-test и `not_in_verdict`), `docs/decisions.md` (D43)

**Интерфейсы:**
- Производит: `_mutants(v: Any) -> list[tuple[str, Any]]` — список `(суффикс пути, испорченное значение)`; `""` — само значение, `"[i]"` — элемент списка, `".key"` — ключ словаря, с рекурсией.
- Производит: `MAX_INDEX = 8` — элементы с индексом `>= MAX_INDEX` не портятся по отдельности.
- Производит: в `self_test()[inv_id]` новый ключ `weak_paths: list[str]` (отсортирован); `weak_fields` теперь — отсортированные уникальные поля верхнего уровня из `weak_paths`.
- Производит: `_allowed(path: str, allowed: set[str]) -> bool` — путь покрыт `not_in_verdict`.
- Производит: `Report.weak_required[inv_id]` — список **путей**; для скалярного поля путь равен имени поля, поэтому прежние отчёты не меняются.

- [ ] **Шаг 1: Тесты `_mutants`**

```python
def test_mutants_cover_every_list_element_within_cap(self):
    self.assertEqual(ec._mutants(5), [("", 6), ("", 4)])
    self.assertEqual(ec._mutants(True), [("", False)])
    self.assertEqual(ec._mutants("2 employees"), [("", "3 employees")])
    self.assertEqual(ec._mutants(None), [])
    self.assertEqual(ec._mutants({}), [])
    self.assertEqual(ec._mutants([]), [("", [0])])
    paths = {p for p, _ in ec._mutants([{"q": 1}, {"q": 2}])}
    self.assertEqual(paths, {"[0]", "[0].q", "[1]", "[1].q"})
    self.assertFalse(any(p.startswith("[8]") for p, _ in ec._mutants(list(range(20)))))
```

`"[0]"` в ожидании — удаление элемента 0; `"[0].q"` — порча `q` в элементе 0.

- [ ] **Шаг 2: Тест чекера, который читает только первую строку корзины**

```python
def test_self_test_finds_checker_reading_only_first_list_element(self):
    original = checkers.CHECKERS["cart_total"]
    w = cart([(333, 3), (100, 2)], "percent", 15)  # помощник cart() из того же файла
    def first_only(m, inv):  # хвост списка всегда берётся из неиспорченного образца
        return original({**m, "lines": m["lines"][:1] + w["lines"][1:]}, inv)
    ec.CHECKERS["cart_total"] = first_only
    try:
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, w)], self_test=True)
        weak = r.self_test["INV-CART-3"]["weak_paths"]
        self.assertTrue(weak and all(p.startswith("lines[1]") for p in weak), weak)
        self.assertEqual(r.self_test["INV-CART-3"]["weak_fields"], ["lines"])
        self.assertEqual(r.weak_required["INV-CART-3"], weak)
        self.spec["inv"]["INV-CART-3"]["not_in_verdict"] = ["lines[*]"]
        r = self.report([rec(1, "INV-CART-3", "REQ-CART-1", True, w)], self_test=True)
        self.assertEqual(r.weak_required, {})
    finally:
        ec.CHECKERS["cart_total"] = original
```

`cart()` сам считает `subtotal`, `off` и `result`; строки корзины — пары `[цена, количество]`, поэтому слабые пути имеют вид `lines[1]`, `lines[1][0]`, `lines[1][1]`.

- [ ] **Шаг 3: Запустить и убедиться, что тесты падают**

Run: `PYTHONPATH=src python3 -m unittest tests.checker.test_checker.Classification -k mutants -k first_list -v`
Expected: FAIL/ERROR — `_mutants` не определена, `weak_paths` нет.

- [ ] **Шаг 4: Реализовать `_mutants` и учёт по путям**

- `_mutants`: bool → `not v`; int → `v + 1`, `v - 1`; float и str — через существующий `_mutate` (поведение D16 сохраняется); список пуст → `[("", [0])]`; иначе для `i < MAX_INDEX` — удаление элемента (`f"[{i}]"`) и мутанты элемента с префиксом `f"[{i}]"`; словарь — мутанты значений с префиксом `f".{key}"`. Перестановки элементов нет: чекер законно сравнивает некоторые списки как множество.
- Комментарий у `MAX_INDEX`: `# simplicity: портятся первые 8 элементов; чекер, читающий только первые 8, не пойман — поднять предел или выбирать индексы по образцам.`
- В `self_test` счётчики `tried/killed/errors` ведутся по полному пути `f"{k}{suffix}"`; путь слабый, если `tried and killed == 0 and not errors`. `fields[k]` суммирует счётчики своих путей (формат `fields` для потребителей прежний). `crashing_fields` — по полю, как сейчас.
- `_allowed`: путь нормализуется `re.sub(r"\[\d+\]", "[*]", path)`; покрыт, если нормализованный путь равен элементу `allowed` или начинается с `элемент + "."` или `элемент + "["`. Имя поля верхнего уровня покрывает все его подпути.
- `rendering.py`: строка о слабых полях перечисляет `weak_paths`.

- [ ] **Шаг 5: Прогнать тесты чекера и пример**

Run: `make test-checker && make example && git diff --stat examples/`
Expected: все тесты зелёные, включая прежние `test_self_test_finds_ignored_field` и `test_string_mutation_changes_a_digit_or_the_whole_value`. `make example` завершается успешно (внутри ожидаемый код 1), в `report.md` по-прежнему четыре дефекта. Если self-test нашёл слабые пути у встроенных чекеров (`cart_total`, `sync_merge`), это дефект чекера: исправить чекер с отдельным целевым тестом, а не ослаблять self-test.

- [ ] **Шаг 6: Документы**

- `docs/security.md`: строка «Чекер проверяет только часть списка | `weak_paths` из self-test, путь `поле[i]…` | ссылка на `test_self_test_finds_checker_reading_only_first_list_element`».
- `docs/extensions.md`: self-test портит каждое поле и первые 8 элементов списков; `not_in_verdict` принимает имя поля или путь с `[*]` (`lines[*].note`).
- `docs/decisions.md`, D43 «Self-test по элементам списков»: причина — одного убийства на поле хватало, чекер, читающий `items[0]`, проходил; что меняется — пути, `weak_paths`, `[*]` в `not_in_verdict`; последствие — проект может получить новый FAIL `weak_required` на поле-списке и снимает его исправлением чекера или `not_in_verdict` после утверждения человеком (D4); версия `0.6.0`. Статус: принято.

- [ ] **Шаг 7: Коммит**

```bash
git add src/witnessbox/checker/engine.py src/witnessbox/checker/rendering.py tests/checker/test_checker.py examples/basic docs/security.md docs/extensions.md docs/decisions.md
git commit -m "Self-test портит каждый элемент списка и сообщает слабые пути (D43)"
```

---

### Задача 3: Отказ формы отдельно от убийства логикой, подстановка из соседнего образца

**Файлы:**
- Изменить: `src/witnessbox/checker/engine.py` (`self_test`)
- Изменить: `src/witnessbox/checker/rendering.py` (раздел самопроверки)
- Тест: `tests/checker/test_checker.py` (`Classification`)
- Документы: `docs/decisions.md` — абзац в D43 (задачи 2 и 3 идут одним PR; если раздельно, задача 3 получает свою запись, а `--sync-pinned` — следующий номер)

**Интерфейсы:**
- Потребляет: учёт по путям из задачи 2.
- Производит: в `fields[k]` и в счётчиках пути новое поле `rejected: int` — сколько мутантов дали `WitnessError`. `killed` сохраняет прежний смысл (вердикт не ok **или** `WitnessError`), поэтому `rejected <= killed`.
- Производит: `self_test()[inv_id]["shape_only_paths"]: list[str]` — пути, где `killed > 0 and killed == rejected`. Это только сведения: в `weak_required` они не попадают и вердикт не меняют.
- Производит: подстановку из соседнего образца — для поля верхнего уровня `k` и образца `w` берётся значение `k` из первого другого образца того же инварианта, где оно отличается; путь мутанта — `k`.

- [ ] **Шаг 1: Тест «ловится только формой»**

```python
def test_self_test_reports_shape_only_rejection_without_failing(self):
    original = checkers.CHECKERS["transition"]
    states = {"cart", "confirmed"}
    def shape_only(w, inv):  # проверяет, что to — известное состояние, но не сверяет переход
        if w["to"] not in states:
            raise WitnessError("to: неизвестное состояние")
        match = [t[2] for t in inv["transitions"] if t[0] == w["from"] and t[1] == w["event"]]
        return original({**w, "to": match[0] if match else w["to"]}, inv)
    ec.CHECKERS["transition"] = shape_only
    try:
        w = {"from": "cart", "event": "confirm", "to": "confirmed"}
        r = self.report([rec(1, "SM-CHECKOUT", "REQ-CHECKOUT-2", True, w)], self_test=True)
        s = r.self_test["SM-CHECKOUT"]
        self.assertEqual(s["shape_only_paths"], ["to"])
        self.assertEqual(s["fields"]["to"]["rejected"], s["fields"]["to"]["killed"])
        self.assertEqual(r.weak_required, {})
    finally:
        ec.CHECKERS["transition"] = original
```

- [ ] **Шаг 2: Тест подстановки**

`test_cross_sample_substitution_kills_by_logic`: два корректных свидетельства `SM-CHECKOUT` с разными `to` (второй переход взять из `self.spec["inv"]["SM-CHECKOUT"]["transitions"]`), штатный чекер. Ожидание: `fields["to"]["killed"] > fields["to"]["rejected"]` и `"to" not in shape_only_paths`.

- [ ] **Шаг 3: Запустить — FAIL** (`rejected`/`shape_only_paths` нет).

Run: `PYTHONPATH=src python3 -m unittest tests.checker.test_checker.Classification -k shape_only -k substitution -v`

- [ ] **Шаг 4: Реализовать** счётчик `rejected` в ветке `except WitnessError`, подстановку (детерминированно: образцы в порядке записей) и `shape_only_paths`. В `rendering.py` — строка «порча пути … ловится только проверкой формы: подставьте в тест другое допустимое значение или проверьте, что чекер сверяет его с правилом».

- [ ] **Шаг 5: `make test-checker && make example`** — зелёные тесты, четыре дефекта, обновлённый `examples/basic/report.*`.

- [ ] **Шаг 6: Коммит**

```bash
git add src/witnessbox/checker tests/checker examples/basic docs/decisions.md
git commit -m "Self-test: отказ формы учитывается отдельно, подстановка значения из соседнего образца (D43)"
```

---

### Задача 4: `ebt-gate --sync-pinned`

**Файлы:**
- Изменить: `src/witnessbox/cli.py` (новая функция и ветка в `main`, текст подсказки `scaffold` на строке 186)
- Изменить: `src/witnessbox/resources/scaffold/README.md`, `docs/scaffold.md` (шаг 3 «Скопировать SDK»), `docs/usage.md` (таблица поддерживаемого интерфейса), `docs/decisions.md` (D44)
- Тест: `tests/gate/test_gate.py` (класс `Gate`, рядом с `test_pinned_uses_installed_resource_and_detects_drift`)

**Интерфейсы:**
- Производит: команду `ebt-gate --sync-pinned <ebt-dir> [<project-root>]`; `<project-root>` по умолчанию — текущий каталог. Коды: `0` — все копии совпадают с оригиналами после выполнения; `2` — ошибка, ничего не записано.
- Производит: `sync_pinned(argv: list[str]) -> int` в `cli.py`.
- Разбор строки — как в `gate.sh:107-108`: пустая строка и строка, начинающаяся с `#`, пропускаются; первый токен — оригинал (`kit:<путь>` → `<package>/resources/<путь>`, абсолютный — как есть, иначе относительно `<ebt-dir>`), второй — путь в проекте.
- Вывод: по строке на копию — `обновлён <dest>` или `без изменений <dest>`.

- [ ] **Шаг 1: Тест синхронизации и согласия с гейтом**

```python
def test_sync_pinned_copies_originals_and_gate_sees_no_drift(self):
    (self.ebt / "obs").mkdir()
    (self.ebt / "obs/helper.ts").write_text("export const h = 1;\n")
    (self.ebt / "pinned.txt").write_text(
        "# SDK\nkit:lib/ebt/Ebt.java  sdk/Ebt.java\n\nobs/helper.ts  src/obs/helper.ts\n")
    p = self.sync_pinned(self.ebt, cwd=self.clone)
    self.assertEqual(p.returncode, 0, p.stderr)
    self.assertIn("обновлён sdk/Ebt.java", p.stdout)
    sdk = Path(self.installation()["resources"]) / "lib/ebt/Ebt.java"
    self.assertEqual((self.clone / "sdk/Ebt.java").read_bytes(), sdk.read_bytes())
    self.assertIn("без изменений", self.sync_pinned(self.ebt, cwd=self.clone).stdout)
    <commit всех файлов клона, как в test_pinned_uses_installed_resource_and_detects_drift>
    self.assertEqual(self.gate(self.write_to('"$OUT_DIR"')).returncode, 0)
```

`self.sync_pinned(ebt, root=None, cwd=None)` — новый помощник класса: `subprocess.run([self.bin / "ebt-gate", "--sync-pinned", str(ebt), *([str(root)] if root else [])], cwd=cwd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})`.

- [ ] **Шаг 2: Тест отказов без частичной записи**

`test_sync_pinned_refuses_escape_missing_original_and_crlf` — для каждого `pinned.txt` код `2`, а `sdk/Ebt.java` (первая корректная строка) **не создан**:
- `kit:lib/ebt/Ebt.java  sdk/Ebt.java\nkit:lib/ebt/Ebt.java  ../outside.java\n`
- `kit:lib/ebt/Ebt.java  sdk/Ebt.java\nkit:lib/ebt/Ebt.java  /tmp/abs.java\n`
- `kit:lib/ebt/Ebt.java  sdk/Ebt.java\nkit:lib/ebt/Nope.java  x.java\n`
- `kit:lib/ebt/Ebt.java  sdk/Ebt.java\nkit:lib/ebt/Ebt.java\n` (нет пути назначения)
- `kit:lib/ebt/Ebt.java  sdk/Ebt.java\r\n` (CRLF: гейт прочтёт `sdk/Ebt.java\r`, и синхронизация не должна молча писать в другой путь)
- symlink `link → <tmp вне клона>` в клоне и строка `kit:lib/ebt/Ebt.java  link/Ebt.java`.

Плюс `ebt-gate --sync-pinned` без аргументов и с каталогом без `pinned.txt` — код `2` и строка `usage:` / «нет pinned.txt» в stderr.

Каждый отказ дополнительно проверяет префикс `ebt-gate --sync-pinned:` в stderr: без этого тест прошёл бы и до реализации, потому что неизвестный аргумент уходит в `gate.sh` и тоже даёт код `2`.

- [ ] **Шаг 3: Запустить — FAIL**

Run: `PYTHONPATH=src python3 -m unittest tests.gate.test_gate.Gate -k sync_pinned -v`
Expected: оба теста падают — первый на коде `2` вместо `0`, второй на отсутствии префикса в stderr.

- [ ] **Шаг 4: Реализовать `sync_pinned`**

Два прохода. Первый проверяет все строки и строит список `(src, dest)`, второй копирует только изменившиеся (`shutil.copyfile` после `mkdir(parents=True, exist_ok=True)`). Сравнение байтов перед копированием. Путь назначения — `(root / dest).resolve()` должен лежать внутри `root.resolve()`; абсолютный `dest` — отказ. Символ `\r` в строке — отказ с подсказкой сохранить файл с LF. Сообщения об ошибках — с префиксом `ebt-gate --sync-pinned:` на stderr, как у `--scaffold`. В `main` ветка ставится до `installation()`, как `--scaffold`; путь к `resources` — `Path(__file__).resolve().parent / "resources"`.

- [ ] **Шаг 5: `make test`** — все тесты гейта зелёные.

- [ ] **Шаг 6: Документы**

- Подсказка `scaffold` (`cli.py:186`) и `scaffold/README.md`: шаг «скопируйте SDK» → `ebt-gate --sync-pinned ebt` из корня проекта.
- `docs/scaffold.md`, шаг 3: та же команда; после обновления поставки она же убирает `pinned_drift`.
- `docs/usage.md`: команда в левом столбце таблицы поддерживаемого интерфейса.
- `docs/decisions.md`, D44 «`--sync-pinned`»: причина — ручное копирование SDK после каждой смены байтов (D27, D36) давало `pinned_drift`; команда только копирует оригиналы по `pinned.txt` и не меняет проверку гейта; запись вне корня проекта запрещена. Статус: принято.

- [ ] **Шаг 7: Коммит**

```bash
git add src/witnessbox/cli.py src/witnessbox/resources/scaffold/README.md tests/gate/test_gate.py docs
git commit -m "ebt-gate --sync-pinned: копии SDK и помощников по pinned.txt (D44)"
```

---

### Задача 5: Версия 0.6.0 и полная проверка (без публикации)

**Файлы:** `pyproject.toml` (`version = "0.6.0"`), `docs/usage.md` и `docs/development.md` (упоминания `0.5.2` в командах установки из wheel — заменить на `0.6.0` только там, где речь о сборке из клона), `docs/decisions.md` (раздел «Текущий статус»: D43, D44 в работе, `0.6.0` не выпущена).

- [ ] **Шаг 1:** поднять версию, обновить тексты.
- [ ] **Шаг 2:** `make test example && make test-sdk` — зелёные, четыре дефекта.
- [ ] **Шаг 3:** `make test-linux` (нужен docker или `DOCKER_CONTEXT=colima`) — зелёный, один ожидаемый пропуск `sandbox-exec`.
- [ ] **Шаг 4:** `make release-check` — `build/release/0.6.0/release.json` с `"result": "PASS"`. Тег, GitHub Release и публикация — отдельным решением владельца.
- [ ] **Шаг 5:** коммит `Witnessbox 0.6.0: self-test по путям и --sync-pinned`, PR, зелёный CI из задачи 1.

---

## Дальнейшие этапы (отдельные планы)

Каждый этап требует своей записи D до кода.

1. **Гейт вне досягаемости агента.** GitHub Action (`action.yml` в репозитории): ставит закреплённую версию, сверяет `--installation` с `release.json` выпуска, запускает гейт, публикует `gate.md` в summary, подписывает `gate.json` через `actions/attest-build-provenance`. Закрывает «не ловится» из D26 и D34 при условии, что workflow защищён от правки веткой (CODEOWNERS / required workflow). В `security.md` — новые строки таблицы.
2. **Проверка выпуска машиной.** Документ и шаг Action: `pypi-attestations verify` для wheel из PyPI, сверка SHA с `release.json`.
3. **Совместимость SDK для новых языков.** `ebt-check --conformance <out.jsonl>`: golden и набор отрицательных случаев (дробь, `NaN`, нестроковый ключ), который реализация должна отклонить. Конкретный SDK (вероятно, Python) — под первый реальный проект.
4. **Стек `generic` в заготовке.** `test.sh`, где команда тестов и каталог свидетельств задаются переменными; рецепты для npm/pnpm/jest, Maven, pytest в `docs/scaffold.md`.
5. **Сквозные примеры TS и JVM в CI.** Путь установка → `--scaffold` → `--sync-pinned` → PASS → внесённый дефект → FAIL (отложено в D19).
6. **Предварительная проверка** `ebt-gate --check-only <ebt-dir> <clone>`: spec, `checks.py`, исполняемость `test.sh`, `pinned.txt`, чистота клона — без запуска тестов.
7. **Тесты `checks.py` штатной командой** вместо заклинания с `python` из `--installation` (D32).
8. README: явно указать, что на Windows гейт работает только через WSL.
9. Язык документации для PyPI-аудитории — решение владельца, CLAUDE.md сейчас требует русский.
