# Witnessbox

[English](README.md) · **Русский**

Тестирование поведения приложения на основе свидетельств (evidence-based testing, EBT): во время тестов код записывает, какое решение он принял и на каких данных, а независимый чекер заново проверяет каждое решение по утверждённой человеком спецификации. Комплект состоит из гейта прогона, чекера и SDK для Java, Dart и TypeScript. Runtime требует Python 3.11+ и не имеет сторонних зависимостей. Гейт — bash-скрипт, проверенный на macOS и Linux; на Windows тесты чекера, гейта и примера идут в CI под WSL 2 (Ubuntu 24.04), а нативный Windows не поддерживается.

## Быстрый старт

```bash
uv tool install witnessbox          # or: pipx install witnessbox
witnessbox scaffold ts ebt          # ebt/ scaffold for the dart, ts, jvm or generic stack
witnessbox sync-pinned ebt          # copy the SDK pinned in ebt/pinned.txt into the project
# write an evidence test and ebt/prepare.sh, then commit ebt/ and the project
witnessbox test-checks ebt          # unit tests of the project checker
witnessbox gate --check-only ebt .  # wiring check; runs no tests
BASE=$(git rev-parse HEAD) witnessbox gate ebt . ../results   # gate: PASS, exit code 0
```

Заготовка содержит пример `spec.toml`, `checks.py` и `test.sh` для выбранного стека. Человек утверждает спецификацию до первого прогона, а `test.sh` подключает тесты проекта. Гейт на голой заготовке, пока нет ни одного теста свидетельств, завершается ERROR (код `2`): отсутствие свидетельств — не успех. [Учебник «Быстрый старт»](https://github.com/kaufd/WitnessBox/blob/main/docs/quickstart.ru.md) проходит весь путь на небольшом TypeScript-проекте: заготовка, тест свидетельств, PASS, внесённый дефект, FAIL с `checker_failed` и чтение `gate.md` и `gate.json`. Чтобы написать собственную спецификацию, см. [составление спецификации](https://github.com/kaufd/WitnessBox/blob/main/docs/authoring.ru.md); файлы заготовки описаны в [новом проекте](https://github.com/kaufd/WitnessBox/blob/main/docs/scaffold.ru.md). Команде `witnessbox` нужна версия 0.7.0 или новее; раннюю установку обновите через `uv tool upgrade witnessbox`. Чтобы подключить проект силами агента-кодировщика, дайте ему [инструкцию для агента](https://github.com/kaufd/WitnessBox/blob/main/docs/agent.ru.md): он составит черновик спецификации и остановится до утверждения человеком. Установка даёт одну команду, `witnessbox`, с подкомандами `gate`, `check`, `scaffold`, `sync-pinned`, `test-checks` и `spec`; их перечисляет `witnessbox --help`. Две отдельные команды из 0.6.0 удалены в 0.7.0. Коды возврата гейта: `0` — PASS, `1` — FAIL, `2` — ERROR. Машиночитаемый результат для CI — `gate.json` в каталоге результатов.

`witnessbox --installation` печатает версию и SHA-256 кода гейта и чекера; сверьте их с выпускными значениями в [журнале решений](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.ru.md). Сборка из исходников, переход с прежней поставки и миграция описаны в [использовании](https://github.com/kaufd/WitnessBox/blob/main/docs/usage.ru.md).

Документация доступна на английском и русском языках.

## Гарантии и границы

Гейт проверяет записанное и заново проверяет правило, но не является песочницей: код под проверкой и гейт работают от одного пользователя ОС, поэтому гарантия — обнаружение, а не граница прав ([D26](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.ru.md)).

- Решение, которое принято, но не записано, с последствиями, не видимыми вне сценариев уровня наблюдения (OBS), не ловится; мутационный аудит — исследовательский инструмент, а не часть гейта (D29).
- Установка, подменённая до прогона, не ловится: вызывающий сверяет `gate_sha256` и `checker_sha256` с выпускными значениями (D33); в CI `actions/setup` сверяет wheel и `--installation` с выпуском (D45).
- Намеренный обход из `test.sh` тем же пользователем — фоновый процесс, `~/.gitconfig`, `PATH` — не ловится (D26).
- Согласованная подмена свидетельств и `gate.json` до вердикта не ловится; в CI доверенная стадия перепроверяет свидетельства и подписывает результат, но свидетельства по-прежнему создаёт код под проверкой (D34, D45).
- В CI вердикту из недоверенной стадии `pull_request` не доверяют: стадия `workflow_run` перепроверяет свидетельства по `ebt/` из основной ветки, подписывает `gate.json` и выставляет статус коммита `witnessbox/gate` (D45, [режим CI](https://github.com/kaufd/WitnessBox/blob/main/docs/ci.ru.md)).

Спецификацию утверждает человек (D4). Полная таблица «атака → чем ловится → что не ловится» — в [модели угроз](https://github.com/kaufd/WitnessBox/blob/main/docs/security.ru.md).

## Документы

- [Быстрый старт](https://github.com/kaufd/WitnessBox/blob/main/docs/quickstart.ru.md) — учебник от установки до первого PASS и пойманного дефекта.
- [Составление спецификации](https://github.com/kaufd/WitnessBox/blob/main/docs/authoring.ru.md) — от требования до `spec.toml`, чекера и тестов свидетельств; уровень наблюдения (`<INV>-OBS`) и его контракт.
- [Инструкция для агента-кодировщика](https://github.com/kaufd/WitnessBox/blob/main/docs/agent.ru.md) — тот же путь для ИИ-агента: правила, точки остановки для утверждения человеком, команды и итоговый отчёт.
- [Как это работает](https://github.com/kaufd/WitnessBox/blob/main/docs/example.ru.md) — один пример от требования до вердикта, для первого знакомства.
- [Модель угроз](https://github.com/kaufd/WitnessBox/blob/main/docs/security.ru.md) — что гейт обнаруживает и что он не обещает.
- [Режим CI](https://github.com/kaufd/WitnessBox/blob/main/docs/ci.ru.md) — двухстадийный гейт GitHub Actions с подписанным вердиктом и статусом `witnessbox/gate`.
- [Новый проект](https://github.com/kaufd/WitnessBox/blob/main/docs/scaffold.ru.md) — заготовка `ebt/`: спецификация, `test.sh` для стека и `pinned.txt`.
- [Архитектура](https://github.com/kaufd/WitnessBox/blob/main/docs/architecture.ru.md) — реальные модули и схема проверки.
- [Расширения](https://github.com/kaufd/WitnessBox/blob/main/docs/extensions.ru.md) — публичные типы и контракт проектных чекеров.
- [Разработка](https://github.com/kaufd/WitnessBox/blob/main/docs/development.ru.md) — команды тестов, SDK и standalone-сборка.
- [Решения](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.ru.md) — текущий статус и журнал решений, в который записи только добавляются.

## Лицензия

[MIT](https://github.com/kaufd/WitnessBox/blob/main/LICENSE). Файлы SDK (`Ebt.java`, `ebt.ts`, `ebt.dart`) копируются в код приложения без изменений и содержат строку `SPDX-License-Identifier: MIT`.
