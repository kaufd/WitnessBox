# План: гейт в GitHub Actions с подписанным вердиктом

> **Для исполнителя-агента:** обязательный sub-skill — superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** закрыть в CI две дыры модели угроз. Первая (D26): код под проверкой работает от того же пользователя, что и гейт, и может подменить вердикт. Вторая (D34): согласованную подмену свидетельств и `gate.json` после вердикта нельзя обнаружить. Вердикт выдаёт стадия, где код проекта не исполняется. `gate.json` подписан аттестацией GitHub. Установка witnessbox сверяется с выпуском.

**Архитектура:** две стадии в репозитории потребителя.
1. `ebt-tests` (`on: pull_request`, недоверенная): ставит проверенную поставку, запускает `ebt-gate` как обычно, выгружает `out/*.jsonl` и `gate.json` артефактом. Её вердикт — только сведения.
2. `ebt-verify` (`on: workflow_run`, доверенная): GitHub всегда берёт этот workflow из основной ветки, поэтому ветка задачи не может его изменить. Он не исполняет код проекта. Чекаутит коммит PR, берёт `ebt/` из `BASE`, заменяет в копии `test.sh` на replay-runner, который отдаёт свидетельства из артефакта, и запускает настоящий `ebt-gate`. Затем подписывает `gate.json` (`attest-build-provenance`), публикует `gate.md` в summary и ставит commit status `witnessbox/gate` на коммит PR.

Логика лежит в двух composite actions репозитория WitnessBox (`actions/setup`, `actions/verify`), а их скрипты тестируются локально. YAML потребителя — шаблоны в `docs/ci.md`.

**Стек:** GitHub Actions (composite), bash 3.2-совместимый shell, Python stdlib, `gh`, uv.

**Источник требований:** обсуждение 2026-11-01 (пункты 1, 4 и 10 списка развития); [security.md](../../security.md); D26, D33, D34, D40 в [decisions.md](../../decisions.md).

**Предусловие:** выпущена версия witnessbox на PyPI с `release.json` в GitHub Release (0.6.0 или 0.5.2 для отладки).

## Глобальные ограничения

- Runtime-пакет `src/witnessbox/` не меняется: `gate_sha256`/`checker_sha256` прежние, новых зависимостей нет. Actions живут вне пакета (`actions/`) и вне fingerprint установки.
- Новый Runner API не вводится: replay-runner — обычный `test.sh` по существующему договору (`OUT_DIR`, коды 0/1/2).
- Стадия `ebt-verify` не исполняет файлы из checkout проекта и из артефакта: `prepare.sh` удаляется, `test.sh` заменяется, `checks.py` берётся из `BASE`.
- Артефакт первой стадии — недоверенные данные: копируются только обычные файлы `out/*.jsonl` (не symlink), `tests_exit_code` принимается только как целое 0 или 1.
- Каталог проверки — только `ebt` в корне репозитория: защита путей в `gate.sh` (`git diff BASE HEAD -- ebt tool/ebt_check`) знает только его.
- Все `uses:` закреплены полным SHA с комментарием версии; права задаются минимально в каждом job.
- Документация и сообщения — на русском; README — на английском (D41).
- PR из форков не поддерживаются в первой версии: у `workflow_run` для них нет `pull_requests[].base.sha`. Статус в этом случае — `error` с объяснением, а не `success`.
- Решение D45 записывается до кода (append-only).

## Фокус ревью

1. PR из форка или push без PR (`pull_requests` пуст): commit status `error` с текстом «нет BASE: PR из форка или push без PR не поддерживается», вердикт не `success`.
2. Первая стадия отменена или упала до выгрузки артефакта: вторая стадия ставит `error` «нет артефакта witnessbox-evidence», а не молчит.
3. Артефакт содержит symlink `out/a.jsonl → /etc/passwd`, файл не `.jsonl` или подкаталог: replay копирует только обычные `*.jsonl`. Symlink даёт ERROR, а не чтение чужого файла.
4. В `BASE` нет `ebt/` (проверку вводят тем же PR): ERROR «ebt/ нет в BASE — сначала влейте ebt/ в основную ветку», как в шаге 6 `docs/scaffold.md`.
5. PR меняет `ebt/spec.toml`: вторая стадия проверяет по spec из `BASE` и даёт FAIL `protected_paths_changed`, а не PASS по spec ветки.

---

### Задача 1: Решение D45

**Файлы:** изменить `docs/decisions.md` (новая запись в конце, строка в «Текущем статусе»).

**Интерфейсы:** не производит кода. Фиксирует имена, на которые опираются задачи 2–5: `actions/setup`, `actions/verify`, артефакт `witnessbox-evidence`, артефакт `witnessbox-verdict`, commit status `witnessbox/gate`, переменная `EBT_REPLAY_DIR`.

- [ ] **Шаг 1: Записать D45 «Гейт в GitHub Actions: недоверенные тесты и доверенная перепроверка».** Содержание:
  - причина — D26 и D34;
  - две стадии и почему `workflow_run`: workflow из основной ветки не правится веткой задачи, `pull_request_target` с исполнением кода PR отвергнут;
  - что закрывается — вердикт и `gate.json` не изменяются кодом проекта; подпись привязывает `gate.json` к workflow основной ветки;
  - что не закрывается — свидетельства по-прежнему пишет код под проверкой, а `tests_exit_code` первой стадии — заявление этого кода, как и сейчас;
  - форки не поддерживаются; аттестации в приватных репозиториях требуют тарифа GitHub с поддержкой artifact attestations;
  - actions закрепляются по SHA коммита WitnessBox; runtime и Runner API не меняются.

  Статус: принято.
- [ ] **Шаг 2: Коммит** `Решение D45: гейт в GitHub Actions с подписанным вердиктом`.

---

### Задача 2: `actions/setup` — установка, сверенная с выпуском

**Файлы:**
- Создать: `actions/setup/action.yml`, `actions/setup/verify_release.py`
- Создать: `tests/actions/__init__.py`, `tests/actions/test_setup.py`
- Изменить: `Makefile` (цель `test-actions` и включение её в `test`)

**Интерфейсы:**
- Производит: action `kaufd/WitnessBox/actions/setup@<sha>` со входом `version` (обязательный, ровно `X.Y.Z`). После выполнения `ebt-gate` и `ebt-check` на `PATH`; выход `installation` — путь к JSON `--installation`.
- Производит: `verify_release.py wheel <release.json> <wheel>` — код 0, если `release["result"] == "PASS"`, `release["version"]` равна версии из имени wheel и SHA-256 файла равен `release["wheel"]["sha256"]`; иначе код 1 и сообщение с ожидаемым и фактическим значением.
- Производит: `verify_release.py installation <release.json> <installation.json>` — код 0, если `distribution`, `version`, `gate_sha256`, `checker_sha256` совпадают с `release["installation"]`; иначе код 1 с перечнем расхождений.

- [ ] **Шаг 1: Тесты `verify_release.py`** (`tests/actions/test_setup.py`, запуск скрипта через `subprocess` с `sys.executable -I`):
  - `test_wheel_matches_release` — временный файл, `release.json` с его SHA и `"result": "PASS"` → код 0;
  - `test_wheel_sha_mismatch_fails` → код 1, в stderr оба SHA;
  - `test_release_not_pass_fails` (`"result": "FAIL"`) → код 1;
  - `test_version_mismatch_fails` (wheel `witnessbox-0.6.0-…`, `release["version"] == "0.5.2"`) → код 1;
  - `test_installation_matches` и `test_installation_checker_sha_mismatch_fails` — расхождение `checker_sha256` → код 1, в stderr `checker_sha256`;
  - `test_installation_of_real_wheel_matches_release_check` — установить wheel через `tests/_verification_test_support.install_verification()`, собрать `release.json` из `--installation` этого venv и SHA wheel → оба подкоманды дают 0.
- [ ] **Шаг 2: Запуск — FAIL** (`python3 -m unittest discover -s tests/actions -p 'test_setup.py'`: скрипта нет).
- [ ] **Шаг 3: Реализовать `verify_release.py`** — stdlib, `argparse` с двумя подкомандами, Python 3.11+.
- [ ] **Шаг 4: Написать `action.yml`** (composite, `shell: bash` у каждого шага):
  1. проверить `version` по `^[0-9]+\.[0-9]+\.[0-9]+$`;
  2. `actions/setup-python` (3.12) и `astral-sh/setup-uv`, оба по SHA;
  3. `gh release download v$VERSION --repo kaufd/WitnessBox --pattern release.json` (`GH_TOKEN: ${{ github.token }}`);
  4. `python -m pip download --no-deps --only-binary=:all: --dest "$RUNNER_TEMP/witnessbox" witnessbox==$VERSION`;
  5. `verify_release.py wheel …`;
  6. `uv tool install <этот wheel-файл>` — ставится именно проверенный файл, а не повторная загрузка из индекса;
  7. `ebt-gate --installation > installation.json`, затем `verify_release.py installation …`;
  8. записать выход `installation`.
- [ ] **Шаг 5: Make и проверка синтаксиса.** Цель `test-actions: PYTHONPATH= $(PY) -m unittest discover -s tests/actions -p 'test_*.py'`, `test: test-checker test-gate test-actions`. Проверка: `make test-actions` зелёный; `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-actions actions/setup/action.yml` → `ok`.
- [ ] **Шаг 6: Коммит** `actions/setup: установка witnessbox, сверенная с release.json (D45)`.

---

### Задача 3: Replay-runner и копия `ebt/` из `BASE`

**Файлы:**
- Создать: `actions/verify/prepare.sh`, `actions/verify/replay.sh`
- Тест: `tests/actions/test_verify.py`

**Интерфейсы:**
- Производит: `prepare.sh <clone> <base-sha> <target-dir>`. Извлекает `ebt/` из `<base-sha>` (`git -C <clone> archive <base-sha> ebt | tar -x`) в `<target-dir>`, удаляет `prepare.sh`, кладёт исполняемую копию `replay.sh` как `test.sh`. Коды: 0 — готово; 2 — `ebt/` нет в `BASE` (сообщение из «Фокуса ревью», п. 4) или ошибка git/tar.
- Производит: `replay.sh` — договор `test.sh`. Читает `EBT_REPLAY_DIR` (обязательна, абсолютный каталог распакованного артефакта):
  - `tests_exit_code` из `$EBT_REPLAY_DIR/gate.json` разбирается через `python3 -c` (`json`). Принимаются только целые 0 и 1, иначе выход 2.
  - Каждый `$EBT_REPLAY_DIR/out/*.jsonl` проверяется: symlink или не обычный файл → выход 2. Затем файл копируется в `$OUT_DIR`.
  - Если `.jsonl` нет, выход 2. Иначе выход — `tests_exit_code`.
  - Скрипт совместим с bash 3.2, `set -u`, без пустых массивов.

- [ ] **Шаг 1: Тесты** (`tests/actions/test_verify.py`). Используют установленный wheel (`install_verification()`), git-репозиторий во временном каталоге с коммитом `BASE` (содержит `ebt/spec.toml`, `ebt/prepare.sh`, `ebt/test.sh`) и записью `src/witnessbox/checker/fixtures/record.jsonl`, как в `tests/gate/test_gate.py`:
  - `test_replay_pass_from_artifact` — артефакт с `out/a.jsonl` и `gate.json` (`tests_exit_code: 0`), `prepare.sh` + `ebt-gate <target> <clone> <run>` с `BASE` и `EBT_REPLAY_DIR` → код 0, `gate.json.result == "PASS"`;
  - `test_replay_failed_tests_is_fail` — `tests_exit_code: 1` → код 1, `"tests_failed"` в `reasons`;
  - `test_replay_rejects_bad_exit_code` — `tests_exit_code: "0"` и `null` → код 2;
  - `test_replay_rejects_symlink_evidence` — `out/a.jsonl` — symlink → код 2;
  - `test_replay_without_evidence_is_error` → код 2;
  - `test_prepare_uses_base_spec_and_drops_prepare` — HEAD меняет `ebt/spec.toml` и `ebt/prepare.sh`. Копия совпадает с `BASE`, `prepare.sh` в ней нет, `test.sh` равен `replay.sh`. Гейт даёт код 1 с `protected_paths_changed`.
  - `test_prepare_without_ebt_in_base_is_error` → код 2 и сообщение про `BASE`.
- [ ] **Шаг 2: Запуск — FAIL** (`make test-actions`: скриптов нет).
- [ ] **Шаг 3: Реализовать `prepare.sh` и `replay.sh`.**
- [ ] **Шаг 4: `make test-actions && bash -n actions/verify/*.sh`** — зелёные.
- [ ] **Шаг 5: Коммит** `actions/verify: replay-runner и ebt/ из BASE (D45)`.

---

### Задача 4: `actions/verify/action.yml` — перепроверка, подпись, статус

**Файлы:** создать `actions/verify/action.yml`.

**Интерфейсы:**
- Потребляет: `actions/setup` (задача 2); `prepare.sh`, `replay.sh` (задача 3).
- Производит: action `kaufd/WitnessBox/actions/verify@<sha>`, вход `github-token` (по умолчанию `${{ github.token }}`). Запускается только в job на `workflow_run`. Требуемые права job: `contents: read`, `actions: read`, `statuses: write`, `id-token: write`, `attestations: write`.
- Производит: commit status `witnessbox/gate` на `github.event.workflow_run.head_sha`:
  - `success` — PASS;
  - `failure` — FAIL;
  - `error` — ERROR или любой отказ до гейта.

  Описание статуса — `result` и `reasons` из `gate.json`; `target_url` — URL запуска.
- Производит: артефакт `witnessbox-verdict` с каталогом результатов гейта и аттестацию `gate.json`.

- [ ] **Шаг 1: Написать шаги.** Первым шагом ставится статус `pending`. Отказ любого шага до гейта переводится в `error` финальным шагом `if: always()`.
  1. Проверить `github.event_name == 'workflow_run'`. `BASE` — `github.event.workflow_run.pull_requests[0].base.sha`; если пусто, `error` из «Фокуса ревью», п. 1.
  2. Проверить, что `ebt-gate` уже на `PATH`: workflow потребителя вызывает `actions/setup` отдельным шагом перед `actions/verify`. Иначе — `error` «сначала actions/setup». Вызывать setup изнутри verify нельзя: `uses: ./…` в composite указывает на репозиторий потребителя, а SHA того же коммита WitnessBox в самом коммите не записать.
  3. `actions/checkout` — `repository: github.event.workflow_run.head_repository.full_name`, `ref: head_sha`, `fetch-depth: 0`, `persist-credentials: false`, в `$RUNNER_TEMP/clone`.
  4. `actions/download-artifact` — `name: witnessbox-evidence`, `run-id: github.event.workflow_run.id`, `github-token`, в `$RUNNER_TEMP/evidence`. Если артефакта нет, `error` из п. 2.
  5. `prepare.sh "$RUNNER_TEMP/clone" "$BASE" "$RUNNER_TEMP/ebt"`.
  6. `BASE=… EBT_RUNNER=test.sh EBT_REPLAY_DIR=… ebt-gate "$RUNNER_TEMP/ebt" "$RUNNER_TEMP/clone" "$RUNNER_TEMP/run"`. Код сохранить и шаг не валить.
  7. `cat gate.md >> "$GITHUB_STEP_SUMMARY"`.
  8. `actions/attest-build-provenance` с `subject-path: $RUNNER_TEMP/run/gate.json`, если `gate.json` есть.
  9. `actions/upload-artifact` `witnessbox-verdict`.
  10. Финальный статус через `gh api repos/{owner}/{repo}/statuses/{sha}` по коду гейта: 0 → `success`, 1 → `failure`, иначе `error`.

  Ни один шаг не запускает файлы из `$RUNNER_TEMP/clone` или `$RUNNER_TEMP/evidence`.
- [ ] **Шаг 2: Синтаксис.** `check-jsonschema --builtin-schema vendor.github-actions actions/verify/action.yml` → `ok`. Также `grep -n 'clone/\|evidence/' actions/verify/action.yml`: пути встречаются только как аргументы `prepare.sh`, `ebt-gate`, checkout и download.
- [ ] **Шаг 3: Коммит** `actions/verify: перепроверка свидетельств, аттестация gate.json и commit status (D45)`.

---

### Задача 5: Шаблоны потребителя и документы

**Файлы:**
- Создать: `docs/ci.md`
- Изменить: `docs/security.md` (таблица и «Не ловится»), `README.md` (раздел Guarantees and limits и список Documents), `docs/usage.md` (ссылка на `docs/ci.md` в разделе запуска)

**Интерфейсы:** потребляет имена из задач 1–4.

- [ ] **Шаг 1: `docs/ci.md`**:
  - Схема двух стадий.
  - Шаблон `.github/workflows/ebt-tests.yml`. Триггер `on: pull_request`, права `contents: read`, `fetch-depth: 0`. Шаги: `actions/setup`, `BASE=${{ github.event.pull_request.base.sha }} ebt-gate ebt . "$RUNNER_TEMP/run" || true`, `upload-artifact` с именем `witnessbox-evidence` и файлами `run/out/*.jsonl`, `run/gate.json`, `if: always()`.
  - Шаблон `.github/workflows/ebt-verify.yml`. Триггер `on: workflow_run` (`workflows: [ebt-tests]`, `types: [completed]`), права из задачи 4, шаги `actions/setup` и затем `actions/verify` с одним и тем же SHA.
  - Как сделать `witnessbox/gate` обязательной проверкой в branch protection.
  - Проверка вердикта третьим лицом: `gh attestation verify gate.json --repo <owner>/<repo> --signer-workflow <owner>/<repo>/.github/workflows/ebt-verify.yml --source-ref refs/heads/<основная ветка>`, затем при желании `ebt-check` по `witnessbox-verdict`.
  - Ограничения из D45: форки, приватные репозитории, `tests_exit_code` — заявление кода.
- [ ] **Шаг 2: `docs/security.md`.** Новые строки таблицы со ссылками на тесты задачи 3 и D45:
  - «Вердикт или `gate.json` изменены кодом проекта (CI-режим)» → «перепроверка в `workflow_run`, аттестация»;
  - «Spec изменена в PR (CI-режим)» → «spec из `BASE`».

  В «Не ловится» уточнить: строки D26/D34 относятся к локальному запуску и к первой стадии.
- [ ] **Шаг 3: README** — одно предложение в Guarantees and limits о CI-режиме со ссылкой на `docs/ci.md`; строка в Documents.
- [ ] **Шаг 4: `make test`** зелёный (документы не ломают тестов на ссылки `security.md`, если такие есть).
- [ ] **Шаг 5: Коммит** `Документы CI-режима: шаблоны workflow и модель угроз (D45)`.

---

### Задача 6: Приёмка на демонстрационном репозитории (с владельцем)

Workflow на `workflow_run` срабатывает только из основной ветки, поэтому сквозной сценарий не проверить ни в PR WitnessBox, ни локально.

- [ ] **Шаг 1:** владелец создаёт публичный репозиторий (например, `kaufd/witnessbox-ci-demo`). В нём заготовка `ebt-gate --scaffold ts ebt`, утверждённая spec из примера, шаблоны из `docs/ci.md` с actions на SHA ветки задачи. Всё влито в `main`; `witnessbox/gate` — обязательная проверка.
- [ ] **Шаг 2:** PR с корректным изменением → `witnessbox/gate: success`, `gh attestation verify` проходит.
- [ ] **Шаг 3:** PR, где код нарушает правило → `failure`, `gate.md` в summary.
- [ ] **Шаг 4:** PR, меняющий `ebt/spec.toml` → `failure` с `protected_paths_changed`.
- [ ] **Шаг 5:** PR, меняющий `.github/workflows/ebt-verify.yml` на `exit 0` → статус по-прежнему ставит версия из `main`.
- [ ] **Шаг 6:** PR, чей `test.sh` оставляет фоновый процесс, переписывающий `gate.json` → вердикт второй стадии от этого не зависит.
- [ ] **Шаг 7:** результаты каждого сценария (ссылки на запуски) записать в D45 отдельным абзацем с датой.

---

## Что не входит

- Защита свидетельств от их автора: свидетельства по-прежнему пишет код под проверкой, Action меняет только то, кто выносит и подписывает вердикт.
- Изоляция `test.sh` первой стадии (контейнер, отдельный пользователь) — не нужна: её результат не доверенный.
- GitLab CI и другие системы — по запросу проекта.
- Публикация actions в GitHub Marketplace — после приёмки.
