# Гейт в GitHub Actions

[English](ci.md) · **Русский**

В CI локальная модель угроз D26/D34 не работает: `test.sh` исполняется с правами гейта и может подменить вердикт, а согласованную подмену свидетельств и `gate.json` после вердикта нельзя заметить по хешу. Поэтому проверка разделена на две стадии (D45): недоверенную и доверенную.

```text
pull_request ──► ebt-tests (недоверенная стадия)
                    │  witnessbox gate как обычно
                    │  artifact witnessbox-evidence: out/*.jsonl + gate.json
                    ▼
workflow_run ◄──────┘
     │
     ▼
ebt-verify (workflow из основной ветки)
  checkout head_sha; ebt/ из BASE; prepare.sh удалён; test.sh → replay.sh
  настоящий witnessbox gate; код проекта не исполняется
  attest gate.json; gate.md в summary; commit status witnessbox/gate
```

- `ebt-tests` запускается на `pull_request` и недоверенна. Её вердикт — только сведения.
- `ebt-verify` запускается на `workflow_run`. GitHub всегда берёт этот workflow из основной ветки, поэтому ветка задачи не может его изменить. `ebt/` и `checks.py` берутся из `BASE`, `prepare.sh` удаляется, вместо `test.sh` ставится replay-скрипт. Код проекта во второй стадии не исполняется.
- `actions/setup` ставит witnessbox из PyPI, сверяет SHA-256 wheel и JSON `--installation` с `release.json` выпуска.
- `actions/verify` перепроверяет свидетельства настоящей командой `witnessbox gate`, подписывает `gate.json` аттестацией GitHub и ставит commit status `witnessbox/gate`: `success` — PASS, `failure` — FAIL, `error` — ERROR или отказ до гейта.

Логика лежит в composite actions [setup](../actions/setup/action.yml) и [verify](../actions/verify/action.yml); их скрипты проверяются локально в [test_verify.py](../tests/actions/test_verify.py). Перед первой стадией нужен выпуск witnessbox с `release.json` в GitHub Release: в примерах ниже используется `0.8.0`.

## Шаблон `.github/workflows/ebt-tests.yml`

```yaml
name: ebt-tests

on:
  pull_request:

permissions:
  contents: read

concurrency:
  group: ebt-tests-${{ github.ref }}
  cancel-in-progress: true

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - name: Получить исходники
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          # Именно head PR, а не merge-коммит: вторая стадия чекаутит workflow_run.head_sha.
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0

      - name: Установить witnessbox
        # SHA коммита WitnessBox с actions/setup и actions/verify (D45).
        # Полный SHA коммита тега выпуска; не используйте main или имя тега.
        uses: kaufd/WitnessBox/actions/setup@2455f3c96f0b677967884f10d13a6ad4c6304bf4 # v0.8.0
        with:
          version: "0.8.0"

      - name: Запустить гейт
        env:
          BASE: ${{ github.event.pull_request.base.sha }}
        run: |
          set +e
          witnessbox gate ebt . "$RUNNER_TEMP/run"
          rc=$?
          echo "witnessbox gate завершился с кодом $rc; вердикт этой стадии не доверенный"
          exit 0

      - name: Выгрузить свидетельства и gate.json
        if: always()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: witnessbox-evidence
          path: |
            ${{ runner.temp }}/run/out/*.jsonl
            ${{ runner.temp }}/run/gate.json
          if-no-files-found: error
```

`fetch-depth: 0` нужен гейту: он сравнивает `BASE` и `HEAD` и проверяет защищённые пути `ebt/` и `tool/ebt_check`. `|| true`/`exit 0` не скрывает вердикт: `gate.json` всё равно выгружается, а вторая стадия решает заново.

## Шаблон `.github/workflows/ebt-verify.yml`

```yaml
name: ebt-verify

on:
  workflow_run:
    workflows: [ebt-tests]
    types: [completed]

permissions: {}

jobs:
  verify:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
      statuses: write
      id-token: write
      attestations: write
    steps:
      - name: Установить witnessbox
        uses: kaufd/WitnessBox/actions/setup@2455f3c96f0b677967884f10d13a6ad4c6304bf4 # v0.8.0
        with:
          version: "0.8.0"

      - name: Перепроверить и подписать
        # Если setup упал, verify всё равно должен поставить status error.
        if: always()
        uses: kaufd/WitnessBox/actions/verify@2455f3c96f0b677967884f10d13a6ad4c6304bf4 # v0.8.0
        with:
          github-token: ${{ github.token }}
```

Оба workflow должны быть влиты в основную ветку. `workflow_run` срабатывает только для workflow-файла из основной ветки; PR, меняющий `ebt-verify.yml`, не влияет на проверку этого PR. В примерах закреплён полный 40-символьный SHA коммита тега `v0.8.0`, а не `main` и не имя тега: тег можно переставить, коммит — нет.

`actions/verify` требует, чтобы `actions/setup` уже выполнился в этом job: composite action не вызывает setup сам, иначе пришлось бы ссылаться на SHA того же коммита изнутри него. Если `witnessbox` нет на `PATH`, `actions/verify` ставит `error`, а не молчит.

## Обязательная проверка

1. Включите branch protection для основной ветки.
2. Включите **Require status checks to pass before merging**.
3. Добавьте `witnessbox/gate` в обязательные проверки. После первого запуска статус появится в списке; до этого его можно указать вручную.
4. Не делайте вердикт `ebt-tests` условием слияния: он недоверенный. Обязательной должна быть только проверка `witnessbox/gate`.

Статус ставится на `github.event.workflow_run.head_sha` — коммит PR, а не на merge-коммит. `pending` блокирует слияние, `failure` и `error` тоже; `success` разрешает.

Права job `verify` минимальны:

| Право | Зачем |
|---|---|
| `contents: read` | checkout коммита PR и чтение репозитория |
| `actions: read` | скачать `witnessbox-evidence` из запуска `ebt-tests` |
| `statuses: write` | commit status `witnessbox/gate` |
| `id-token: write` | OIDC-токен для аттестации |
| `attestations: write` | `actions/attest-build-provenance` |

Права `ebt-tests` — только `contents: read`. Токен первой стадии не даёт писать статусы и не должен давать.

## Проверка вердикта третьим лицом

Скачайте артефакт второй стадии и проверьте подпись:

```bash
gh run download <run-id> --repo <owner>/<repo> --name witnessbox-verdict
gh attestation verify gate.json \
  --repo <owner>/<repo> \
  --signer-workflow <owner>/<repo>/.github/workflows/ebt-verify.yml \
  --source-ref refs/heads/main
```

`--signer-workflow` — workflow потребителя, который вызвал composite action; `--source-ref refs/heads/main` привязывает подпись к основной ветке. Для приватного репозитория аттестации требуют тарифа GitHub с поддержкой artifact attestations; без неё шаг подписи не выполнится, а `witnessbox/gate` получит `error`.

При желании перепроверьте свидетельства установленным `witnessbox check`:

```bash
witnessbox check --spec ebt/spec.toml --evidence out/*.jsonl --json recheck.json
```

Если в проекте есть `ebt/checks.py`, добавьте `--checkers ebt/checks.py`; при использовании `known.toml`, `baseline.jsonl` или `EBT_INV` добавьте соответствующие `--known`, `--baseline`, `--scope`. `gate.json` содержит `evidence` — имена и SHA-256 файлов `out/*.jsonl`, которые читал чекер; сверьте их с скачанными файлами. Согласованную подмену самих свидетельств и `gate.json` до вердикта это не ловит: свидетельства пишет код под проверкой, а `tests_exit_code` первой стадии — его заявление (D45).

## Ограничения

- **PR из форка и push без PR не поддерживаются.** У `workflow_run` для них обычно нет `pull_requests[].base.sha`; вторая стадия ставит `error` с текстом «no BASE: a PR from a fork or a push without a PR is not supported». Если `BASE` есть, но `head_repository` — форк, ставится `error` «a PR from a fork is not supported». Это не `success`.
- **Нет артефакта — `error`.** Если первая стадия отменена или упала до выгрузки, вторая стадия ставит `error` «no witnessbox-evidence artifact», а не молчит.
- **`ebt/` должен быть в основной ветке.** Если его там нет, вторая стадия даёт `error` «no ebt/ in BASE: first merge ebt/ into the main branch». Проверку нельзя ввести тем же PR, который её запускает.
- **Правка `ebt/` в PR — FAIL.** `spec.toml` и `checks.py` берутся из `BASE`; изменение `ebt/` или `tool/ebt_check/` даёт `protected_paths_changed`, а не PASS по spec ветки.
- **Свидетельства пишет код под проверкой.** Action меняет то, кто выносит и подписывает вердикт, но не то, кто пишет свидетельства. Намеренный обход в первой стадии (фоновый процесс, `PATH`, `~/.gitconfig`) не ловится — это та же граница D26.
- **Артефакт недоверенный.** replay копирует только обычные файлы `out/*.jsonl`; symlink, подкаталог или не-`.jsonl` не читаются, а `tests_exit_code` принимается только как целое `0` или `1`. Остальное — `error`.
- **`workflow_run` не запускается для PR, пока `ebt-verify.yml` не в основной ветке.** Сначала влейте оба workflow.

## Приёмка в демонстрационном репозитории

Сквозной сценарий нельзя проверить в PR самого Witnessbox: `workflow_run` срабатывает только для workflow из основной ветки. Приёмка идёт в отдельном публичном репозитории (например, `kaufd/witnessbox-ci-demo`).

1. Создать репозиторий и влить в `main`: `witnessbox scaffold ts ebt` с утверждённой `spec.toml` из примера, оба workflow из шаблонов выше с одним и тем же SHA actions и branch protection с обязательной проверкой `witnessbox/gate`.
2. PR с корректным изменением: `witnessbox/gate` — `success`; `gh attestation verify gate.json ...` проходит.
3. PR, нарушающий правило: `failure`; `gate.md` в summary второй стадии.
4. PR, меняющий `ebt/spec.toml`: `failure` с `protected_paths_changed`, даже если spec ветки делает проверку зелёной.
5. PR, меняющий `.github/workflows/ebt-verify.yml` на `exit 0`: статус ставит версия из `main`; PR-версия workflow не исполняется.
6. PR, где код нарушает правило, а фоновый процесс из тестового файла вне `ebt/` после гейта первой стадии переписывает её `gate.json` на `PASS`: вторая стадия — `failure` с `checker_failed` и без `protected_paths_changed`. Сценарий не должен менять `ebt/`: иначе FAIL объясняется защищёнными путями, а не перепроверкой. Вторая стадия берёт из артефакта только свидетельства и `tests_exit_code`; их подмену она не обнаружит — это ограничение D45.
7. Ссылки на запуски и результаты записать отдельным абзацем D45 с датой.

Приёмка требует существующего демо-репозитория и не входит в локальные `make test`; после прогона её результаты фиксируются в журнале решений.

## Диагностика

| Сообщение | Что значит |
|---|---|
| `no BASE: a PR from a fork or a push without a PR is not supported` | `workflow_run.pull_requests` пуст; форки в первой версии не поддержаны |
| `a PR from a fork is not supported` | `BASE` есть, но `head_repository` не совпадает с репозиторием workflow |
| `no witnessbox-evidence artifact` | первая стадия упала/отменена до upload или артефакт переименован |
| `witnessbox not found on PATH: run actions/setup first` | в job нет шага `actions/setup` или он упал |
| `no ebt/ in BASE: first merge ebt/ into the main branch` | в основной ветке ещё нет каталога проверки |
| `symlink in the evidence` / `not a regular file in the evidence` / `tests_exit_code` | артефакт первой стадии повреждён или подменён |
| `gate.json` отсутствует | гейт не смог записать итог; вторая стадия ставит `error` |
