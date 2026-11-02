# Команда `witnessbox` вместо `ebt-gate` и `ebt-check` — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** поставка `0.7.0` устанавливает одну команду `witnessbox` с подкомандами; `ebt-gate` и `ebt-check` удаляются без алиасов.

**Architecture:** единственный entry point `witnessbox = "witnessbox.cli:main"`. `main()` в `cli.py` разбирает первую позицию argv и передаёт остаток существующим функциям (`scaffold`, `sync_pinned`, `check_only`, `test_checks`, exec `gate.sh`) или `witnessbox.checker.cli.main(argv)`. Диспетчер живёт в `cli.py`, поэтому меняется `gate_sha256`; `checker_sha256` меняется только из-за `prog`/`--version` чекера.

**Tech Stack:** Python stdlib, bash, unittest, composite GitHub Actions.

**Spec:** решение пользователя в чате 2026-11-02: «потребителей всё равно обновлять, и они мои; старые команды держать смысла нет». Оформляется записью D50 (Task 3).

## Global Constraints

- Runtime без сторонних зависимостей; `argparse` для диспетчера не нужен — разбор по `argv[0]`, как сейчас.
- Чекер не импортирует `cli.py`; импорт идёт только в сторону `cli.py → witnessbox.checker.cli`, лениво внутри ветки `check`.
- Сообщения, документация и отчёты — на русском; `README.md` и `description` в `pyproject.toml` — на английском (D41).
- Журнал решений append-only: прежние записи D1–D49 не правятся; правятся только сводка в начале `docs/decisions.md` и новая запись D50.
- Не меняются: аргументы и коды выхода каждой подкоманды, `EBT_*`, `BASE`, каталоги `ebt/` и `build/ebt/`, формат свидетельств, JSON `--installation`, `gate.json`/`report.json`, имя файла `ebt-check.err` в каталоге итога, совместимые модули `ebt_check`, `checkers`, `ebt_verification`.
- `docs/superpowers/`, `.claude/`, `.delta/` не трогать.

## Таблица соответствия

| было | стало |
|---|---|
| `ebt-gate <ebt> <clone> <run>` | `witnessbox gate <ebt> <clone> <run>` |
| `ebt-gate --check-only <ebt> <clone>` | `witnessbox gate --check-only <ebt> <clone>` |
| `ebt-gate --scaffold <stack> [<dir>]` | `witnessbox scaffold <stack> [<dir>]` |
| `ebt-gate --sync-pinned <ebt> [<root>]` | `witnessbox sync-pinned <ebt> [<root>]` |
| `ebt-gate --test-checks [<ebt>]` | `witnessbox test-checks [<ebt>]` |
| `ebt-gate --version` → `witnessbox X` | `witnessbox --version` → `witnessbox X` |
| `ebt-gate --installation` | `witnessbox --installation` |
| `ebt-check …`, `--version` → `ebt-check 0.1.0` | `witnessbox check …`, `--version` → `witnessbox check 0.1.0` |

`--check-only` остаётся флагом `gate`, а не подкомандой `check-only`: рядом с `check` (чекер) имя `check-only` читалось бы как режим чекера.

## Review Focus

- Старый `ebt-gate` 0.6.0 остался на PATH (вторая установка через pipx) — новый wheel его не ставит: тест «старых команд в `bin/` нет» (Task 1).
- Workflow потребителя на `actions/verify@v0.7.0` без `actions/setup` — сообщение должно называть `witnessbox`, а не `ebt-gate` (Task 1, `tests/actions`).
- `witnessbox` без аргументов, с `-h` и с неизвестной подкомандой (включая старый флаг `witnessbox --scaffold`) — usage и код `2`/`0`, без exec `gate.sh` (Task 1).
- `witnessbox check` с ошибкой аргументов — argparse с `prog="witnessbox check"`, код `2` (Task 1).
- `witnessbox gate` без аргументов — usage `gate.sh` называет `witnessbox gate`, а не путь к скрипту (Task 1).

---

### Task 1: Диспетчер, entry point и все исполняемые проверки

**Files:**
- Modify: `pyproject.toml:29-31` — в `[project.scripts]` одна строка `witnessbox = "witnessbox.cli:main"`.
- Modify: `src/witnessbox/cli.py` — `main()` (стр. 608–629) и префиксы сообщений (стр. 139–190, 307–355, 586–620).
- Modify: `src/witnessbox/gate.sh` — стр. 2, 8, 15, 57, 123.
- Modify: `src/witnessbox/checker/cli.py:50-51` — `ArgumentParser(prog="witnessbox check", …)`, `version=f"witnessbox check {__version__}"`.
- Modify: `src/ebt_check.py:1` — docstring «Совместимое имя модуля чекера для `import ebt_check`».
- Modify: `actions/setup/action.yml:89-91`, `actions/setup/verify_release.py:5`, `actions/verify/action.yml:55-56,117`, `actions/verify/prepare.sh:34`.
- Test: `tests/gate/test_gate.py`, `tests/checker/test_checker.py:596`, `tests/actions/test_setup.py:122`, `tests/actions/test_verify.py:99`, `tests/release_check.py:76`.

**Interfaces:**
- Produces: CLI по таблице соответствия; usage верхнего уровня (stdout при `-h`/`--help`, stderr при пустом argv):

```
usage: witnessbox <команда> [<аргументы>]

  gate <ebt-dir> <clone> <run-dir>              гейт: тесты проекта и пересчёт свидетельств
  gate --check-only <ebt-dir> <clone>           проверка подключения без запуска тестов
  check --spec <spec.toml> --evidence <jsonl>…  чекер (witnessbox check -h)
  scaffold <dart|ts|jvm|generic> [<ebt-dir>]    заготовка ebt/
  sync-pinned <ebt-dir> [<project-root>]        копии из pinned.txt
  test-checks [<ebt-dir>]                       тесты чекеров проекта
  --version | --installation
```

- Неизвестная подкоманда: stderr `witnessbox: неизвестная команда <arg>` + usage, код `2`.
- Префиксы ошибок: `witnessbox scaffold:`, `witnessbox sync-pinned:`, `witnessbox gate --check-only:`, `witnessbox test-checks:`, `witnessbox:`; usage-строки подкоманд — `usage: witnessbox <подкоманда> …`. Подсказки после `scaffold` (стр. 188–190) — новыми командами.
- `gate.sh`: usage `usage: witnessbox gate <ebt-dir> <clone> <run-dir>`; `запускайте установленную команду witnessbox gate`; `witnessbox check --version упал`; stash `witnessbox gate: изменения за прогон $head`.
- `actions/setup` проверяет `witnessbox --version`, `witnessbox check --version`, пишет `witnessbox --installation`; `actions/verify` — `command -v witnessbox`, ошибка `witnessbox не найден на PATH: сначала выполните actions/setup`, запуск `witnessbox gate …`.

- [ ] **Step 1: Перевести тесты на новые команды.** В `tests/gate/test_gate.py` все `self.bin / "ebt-gate"` → `self.bin / "witnessbox"` с подкомандой по таблице; `"--scaffold"` → `"scaffold"` и т. д.; прогон гейта — `[witnessbox, "gate", ebt, clone, run]`; `--check-only` — `[witnessbox, "gate", "--check-only", …]`; ожидания префиксов (`"ebt-gate --sync-pinned:"` → `"witnessbox sync-pinned:"`, стр. 1035, 1054), stash (стр. 297), подсказка в шаблонах (стр. 630: `"witnessbox test-checks"`), версия чекера (стр. 575: `r"^witnessbox check \d+\.\d+\.\d+$"`). Подставной чекер для `EBT_CHECK` (стр. 82–86) переименовать в `fake-check`, его вывод `fake-check 9.9.9` (и ожидания стр. 907, 915). В `tests/checker/test_checker.py:596` — `f"witnessbox check {ec.__version__}"`. В `tests/actions/*` и `tests/release_check.py` — `witnessbox`, `witnessbox --installation`, `witnessbox gate`.

- [ ] **Step 2: Добавить новые тесты в `tests/gate/test_gate.py`** (класс установленного wheel, рядом с тестом `--installation` на стр. 527):

```python
def test_old_commands_are_not_installed(self):
    for name in ("ebt-gate", "ebt-check"):
        self.assertFalse((self.bin / name).exists(), name)

def test_usage_without_command(self):
    p = subprocess.run([str(self.bin / "witnessbox")], capture_output=True, text=True, env=env)
    self.assertEqual(p.returncode, 2)
    self.assertIn("usage: witnessbox <команда>", p.stderr)

def test_help_lists_commands(self):
    p = subprocess.run([str(self.bin / "witnessbox"), "--help"], capture_output=True, text=True, env=env)
    self.assertEqual(p.returncode, 0)
    for command in ("gate", "--check-only", "check", "scaffold", "sync-pinned", "test-checks"):
        self.assertIn(command, p.stdout)

def test_unknown_command_and_old_flags(self):
    for arg in ("frobnicate", "--scaffold", "--check-only"):
        p = subprocess.run([str(self.bin / "witnessbox"), arg, "ts"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2, arg)
        self.assertIn(f"witnessbox: неизвестная команда {arg}", p.stderr)

def test_gate_without_args_names_command(self):
    p = subprocess.run([str(self.bin / "witnessbox"), "gate"], capture_output=True, text=True, env=env)
    self.assertEqual(p.returncode, 2)
    self.assertIn("usage: witnessbox gate <ebt-dir> <clone> <run-dir>", p.stderr)

def test_check_bad_args_uses_prog(self):
    p = subprocess.run([str(self.bin / "witnessbox"), "check"], capture_output=True, text=True, env=env)
    self.assertEqual(p.returncode, 2)
    self.assertIn("usage: witnessbox check", p.stderr)
```

`env` — то же окружение, что в соседних тестах класса. В `tests/actions/test_verify.py` — ожидание сообщения `witnessbox не найден на PATH`, если там есть тест на отсутствие setup; иначе добавить его по образцу соседних тестов.

- [ ] **Step 3: Убедиться, что тесты падают.** Run: `make test` — Expected: FAIL (`bin/witnessbox` не существует).

- [ ] **Step 4: Реализовать.** `pyproject.toml`, затем `main()`:

```python
COMMANDS = {"scaffold": scaffold, "sync-pinned": sync_pinned, "test-checks": test_checks}

def main():
    command, argv = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else (None, [])
    if command in ("-h", "--help"):
        print(USAGE)
        return 0
    if command in COMMANDS:
        return COMMANDS[command](argv)
    if command == "check":
        from witnessbox.checker.cli import main as check
        return check(argv)
    if command == "gate" and argv[:1] == ["--check-only"]:
        return check_only(argv[1:])
    if command != "gate" and not (command in ("--version", "--installation") and not argv):
        if command is not None:
            print(f"witnessbox: неизвестная команда {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    # далее без изменений: installation(), --version, --installation,
    # для gate — execve gate.sh с argv (без слова "gate")
```

Остальные файлы — по блоку Interfaces.

- [ ] **Step 5: Тесты проходят.** Run: `make test` — Expected: OK, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src actions tests
git commit -m "CLI: одна команда witnessbox вместо ebt-gate и ebt-check"
```

### Task 2: Заготовка и сквозной пример

**Files:**
- Modify: `src/witnessbox/resources/scaffold/{README.md,checks.py,test_checks.py}`, `scaffold/{dart,ts,jvm,generic}/test.sh` (комментарий стр. 2 и `нужен OUT_DIR (запуск через witnessbox gate)`), `scaffold/*/pinned.txt` (комментарии).
- Modify: `examples/e2e/run.sh`, `examples/e2e/{ts,jvm}/ebt/pinned.txt`, `Makefile:70`.

**Interfaces:**
- Consumes: CLI из Task 1.

- [ ] **Step 1: Заменить команды в файлах заготовки по таблице.** Договор `test.sh` и формат `pinned.txt` не меняются — только комментарии и текст сообщения об `OUT_DIR`.
- [ ] **Step 2: `examples/e2e/run.sh`.** `need witnessbox "установите witnessbox (uv tool install dist/witnessbox-*.whl)"`; удалить `check_only_available`, `test_checks_available` и ветки `else … пропущено` (стр. 59–70, 129–145): если `witnessbox` есть, все подкоманды есть. Вызовы — по таблице. Комментарии стр. 7–9 — `witnessbox gate`.
- [ ] **Step 3: Проверить.** Run: `uv tool install --force dist/witnessbox-*.whl` (после `make release-check` или `uv build`), затем `make e2e STACK=generic` и `make e2e STACK=ts` (нужен bun), `make e2e STACK=jvm` при наличии gradle — Expected: PASS на исправном коде, FAIL `checker_failed` на дефекте, код `0`. Стек без инструмента не запускать и назвать в отчёте как непроверенный.
- [ ] **Step 4: Commit** — `git commit -m "Заготовка и e2e: команда witnessbox"`.

### Task 3: Документация и решение D50

**Files:**
- Modify: `README.md`, `CLAUDE.md:5`, `docs/{quickstart,usage,scaffold,agent,authoring,architecture,ci,example,sdk,security,development}.md`, `docs/verification-flow.svg` (`<desc>` и подпись «3. witnessbox check: пересчёт»).
- Modify: `docs/decisions.md` — сводка стр. 10 и 15; новая запись в конце.

- [ ] **Step 1: Заменить команды по таблице во всех файлах выше.** `docs/quickstart.md:21` и `docs/usage.md:26`: «Появится команда `witnessbox`», фраза «отдельной команды `witnessbox` нет» удаляется. `docs/usage.md:126` (таблица публичного интерфейса) — подкоманды `witnessbox`. В `docs/usage.md` рядом с историей переименований (стр. 30) — абзац: с `0.7.0` команды `ebt-gate`/`ebt-check` удалены; `uv tool upgrade witnessbox` убирает их, но вторую установку через pipx нужно удалить вручную.
- [ ] **Step 2: Запись D50** в конец `docs/decisions.md`: «### D50. Одна команда `witnessbox`». Причина: у `ebt-gate` четыре флага-подкоманды, имя пакета не совпадает с командой, а довод D36/D38 (правки у потребителей) снят — потребители обновляются вместе с выпуском. Решение — таблица соответствия, `--check-only` остаётся флагом `gate`, без алиасов; что не меняется — список из Global Constraints; меняются `gate_sha256` и `checker_sha256`, выходит в `0.7.0`. Статус: принято. Сводку стр. 10 и 15 переписать на новые команды со ссылкой на D50.
- [ ] **Step 3: Проверить, что старых имён не осталось.** Run:

```bash
grep -rnE "ebt-gate|ebt-check([^.]|$)" --exclude-dir=.git --exclude-dir=build --exclude-dir=.claude --exclude-dir=.delta --exclude-dir=superpowers --exclude=decisions.md .
```

Expected: пусто (`ebt-check.err` отфильтрован шаблоном). В `docs/decisions.md` совпадения только в D1–D49 и в тексте D50.
- [ ] **Step 4: Commit** — `git commit -m "Документация: команда witnessbox (D50)"`.

### Task 4: Итоговая проверка

- [ ] **Step 1:** `make test` и `make example` — Expected: OK; пример находит все четыре заложенных дефекта.
- [ ] **Step 2:** `make release-check` — Expected: wheel и sdist собраны, тесты из sdist проходят, `build/release/0.7.0/release.json` записан; в `bin/` тестового venv только `witnessbox`.
- [ ] **Step 3:** `make test-linux` при наличии docker — Expected: OK. Без docker — указать в отчёте.
