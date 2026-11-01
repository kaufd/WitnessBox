# Гейт в GitHub Actions

В CI локальная модель угроз D26/D34 не работает: `test.sh` исполняется с правами гейта и может подменить вердикт, а согласованную подмену свидетельств и `gate.json` после вердикта нельзя заметить по хешу. Поэтому проверка разделена на две стадии (D45): недоверенную и доверенную.

```text
pull_request ──► ebt-tests (недоверенная стадия)
                    │  ebt-gate как обычно
                    │  artifact witnessbox-evidence: out/*.jsonl + gate.json
                    ▼
workflow_run ◄──────┘
     │
     ▼
ebt-verify (workflow из основной ветки)
  checkout head_sha; ebt/ из BASE; prepare.sh удалён; test.sh → replay.sh
  настоящий ebt-gate; код проекта не исполняется
  attest gate.json; gate.md в summary; commit status witnessbox/gate
```

- `ebt-tests` запускается на `pull_request` и недоверенна. Её вердикт — только сведения.
- `ebt-verify` запускается на `workflow_run`. GitHub всегда берёт этот workflow из основной ветки, поэтому ветка задачи не может его изменить. `ebt/` и `checks.py` берутся из `BASE`, `prepare.sh` удаляется, вместо `test.sh` ставится replay-скрипт. Код проекта во второй стадии не исполняется.
- `actions/setup` ставит witnessbox из PyPI, сверяет SHA-256 wheel и JSON `--installation` с `release.json` выпуска.
- `actions/verify` перепроверяет свидетельства настоящим `ebt-gate`, подписывает `gate.json` аттестацией GitHub и ставит commit status `witnessbox/gate`: `success` — PASS, `failure` — FAIL, `error` — ERROR или отказ до гейта.

Логика лежит в composite actions [setup](../actions/setup/action.yml) и [verify](../actions/verify/action.yml); их скрипты проверяются локально в [test_verify.py](../tests/actions/test_verify.py). Перед первой стадией нужен выпуск witnessbox с `release.json` в GitHub Release: в примерах ниже используется `0.5.2`, для проверки `0.6.0` замените версию после выпуска.

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
        # При выпуске замените на SHA тега; не используйте main.
        uses: kaufd/WitnessBox/actions/setup@ae496d3ea939e3c966733ddb77ece60baf70ca6b # коммит D45
        with:
          version: "0.5.2"

      - name: Запустить гейт
        env:
          BASE: ${{ github.event.pull_request.base.sha }}
        run: |
          set +e
          ebt-gate ebt . "$RUNNER_TEMP/run"
          rc=$?
          echo "ebt-gate завершился с кодом $rc; вердикт этой стадии не доверенный"
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
        uses: kaufd/WitnessBox/actions/setup@ae496d3ea939e3c966733ddb77ece60baf70ca6b # коммит D45
        with:
          version: "0.5.2"

      - name: Перепроверить и подписать
        # Если setup упал, verify всё равно должен поставить status error.
        if: always()
        uses: kaufd/WitnessBox/actions/verify@ae496d3ea939e3c966733ddb77ece60baf70ca6b # коммит D45
        with:
          github-token: ${{ github.token }}
```

Оба workflow должны быть влиты в основную ветку. `workflow_run` срабатывает только для workflow-файла из основной ветки; PR, меняющий `ebt-verify.yml`, не влияет на проверку этого PR. В примерах закреплён SHA коммита ветки с actions; при выпуске замените его на SHA тега (полный 40-символьный SHA, не `main` и не `v0.6.0`).

`actions/verify` требует, чтобы `actions/setup` уже выполнился в этом job: composite action не вызывает setup сам, иначе пришлось бы ссылаться на SHA того же коммита изнутри него. Если `ebt-gate` нет на `PATH`, `actions/verify` ставит `error`, а не молчит.

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

При желании перепроверьте свидетельства установленным `ebt-check`:

```bash
ebt-check --spec ebt/spec.toml --evidence out/*.jsonl --json recheck.json
```

Если в проекте есть `ebt/checks.py`, добавьте `--checkers ebt/checks.py`; при использовании `known.toml`, `baseline.jsonl` или `EBT_INV` добавьте соответствующие `--known`, `--baseline`, `--scope`. `gate.json` содержит `evidence` — имена и SHA-256 файлов `out/*.jsonl`, которые читал чекер; сверьте их с скачанными файлами. Согласованную подмену самих свидетельств и `gate.json` до вердикта это не ловит: свидетельства пишет код под проверкой, а `tests_exit_code` первой стадии — его заявление (D45).

## Ограничения

- **PR из форка и push без PR не поддерживаются.** У `workflow_run` для них обычно нет `pull_requests[].base.sha`; вторая стадия ставит `error` с текстом «нет BASE: PR из форка или push без PR не поддерживается». Если `BASE` есть, но `head_repository` — форк, ставится `error` «PR из форка не поддерживается». Это не `success`.
- **Нет артефакта — `error`.** Если первая стадия отменена или упала до выгрузки, вторая стадия ставит `error` «нет артефакта witnessbox-evidence», а не молчит.
- **`ebt/` должен быть в основной ветке.** Если его там нет, вторая стадия даёт `error` «ebt/ нет в BASE — сначала влейте ebt/ в основную ветку». Проверку нельзя ввести тем же PR, который её запускает.
- **Правка `ebt/` в PR — FAIL.** `spec.toml` и `checks.py` берутся из `BASE`; изменение `ebt/` или `tool/ebt_check/` даёт `protected_paths_changed`, а не PASS по spec ветки.
- **Свидетельства пишет код под проверкой.** Action меняет то, кто выносит и подписывает вердикт, но не то, кто пишет свидетельства. Намеренный обход в первой стадии (фоновый процесс, `PATH`, `~/.gitconfig`) не ловится — это та же граница D26.
- **Артефакт недоверенный.** replay копирует только обычные файлы `out/*.jsonl`; symlink, подкаталог или не-`.jsonl` не читаются, а `tests_exit_code` принимается только как целое `0` или `1`. Остальное — `error`.
- **`workflow_run` не запускается для PR, пока `ebt-verify.yml` не в основной ветке.** Сначала влейте оба workflow.

## Диагностика

| Сообщение | Что значит |
|---|---|
| `нет BASE: PR из форка или push без PR не поддерживается` | `workflow_run.pull_requests` пуст; форки в первой версии не поддержаны |
| `PR из форка не поддерживается` | `BASE` есть, но `head_repository` не совпадает с репозиторием workflow |
| `нет артефакта witnessbox-evidence` | первая стадия упала/отменена до upload или артефакт переименован |
| `ebt-gate не найден на PATH: сначала выполните actions/setup` | в job нет шага `actions/setup` или он упал |
| `ebt/ нет в BASE — сначала влейте ebt/ в основную ветку` | в основной ветке ещё нет каталога проверки |
| `symlink в свидетельствах` / `не обычный файл` / `tests_exit_code` | артефакт первой стадии повреждён или подменён |
| `gate.json` отсутствует | гейт не смог записать итог; вторая стадия ставит `error` |
