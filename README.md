# Witnessbox

Проверка поведения приложения по свидетельствам (метод EBT, evidence-based testing): код во время тестов записывает, какое решение принял и на каких данных, а независимый чекер перепроверяет каждое решение по спецификации, утверждённой человеком. Комплект — гейт запуска, чекер и SDK для Java, Dart и TypeScript. Runtime требует Python 3.11+ и не имеет сторонних зависимостей.

## Быстрый старт

```bash
uv tool install witnessbox          # или: pipx install witnessbox
ebt-gate --scaffold ts ebt          # заготовка ebt/ для стека dart, ts или jvm
ebt-gate ebt /path/to/clean-checkout /path/to/results
```

Заготовка содержит пример `spec.toml`, `checks.py` и `test.sh` под стек; спецификацию перед первым запуском утверждает человек, а `test.sh` подключает тесты проекта ([новый проект](https://github.com/kaufd/WitnessBox/blob/main/docs/scaffold.md)). Установка предоставляет `ebt-gate` и `ebt-check`; отдельной команды `witnessbox` нет. Коды гейта: `0` PASS, `1` FAIL, `2` ERROR. Итог для CI — `gate.json` в каталоге результатов.

`ebt-gate --installation` показывает версию и SHA-256 кода гейта и чекера; их сверяют с выпускными значениями в [журнале решений](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.md). Сборка из исходников, переход с прежнего дистрибутива и миграция — [использование](https://github.com/kaufd/WitnessBox/blob/main/docs/usage.md).

## Границы гарантий

Гейт проверяет записанное и перепроверяет правило, но не является песочницей: код под проверкой и гейт работают от одного пользователя ОС, поэтому гарантия — обнаружение, а не граница прав ([D26](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.md)).

- Решение принято, но не записано, и его последствия вне сценариев OBS не видны; мутационный аудит — исследование, а не гейт (D29).
- Подменённая до прогона установка не ловится: вызывающий сверяет `gate_sha256` и `checker_sha256` с выпускными значениями (D33).
- Намеренный обход из `test.sh` тем же пользователем — фоновый процесс, `~/.gitconfig`, `PATH` — не ловится (D26).
- Правка свидетельств после вердикта видна при перепроверке по `gate.json`; согласованная подмена файлов и итога не ловится (D34).

Спецификацию утверждает человек (D4). Полная таблица «атака → чем ловится → чего нет» — в [модели угроз](https://github.com/kaufd/WitnessBox/blob/main/docs/security.md).

## Документы

- [Как это работает](https://github.com/kaufd/WitnessBox/blob/main/docs/example.md) — один пример от требования до вердикта, для первого знакомства.
- [Модель угроз](https://github.com/kaufd/WitnessBox/blob/main/docs/security.md) — что гейт обнаруживает и чего не обещает.
- [Новый проект](https://github.com/kaufd/WitnessBox/blob/main/docs/scaffold.md) — заготовка `ebt/`: спецификация, `test.sh` под стек и `pinned.txt`.
- [Архитектура](https://github.com/kaufd/WitnessBox/blob/main/docs/architecture.md) — реальные модули и поток проверки.
- [Расширения](https://github.com/kaufd/WitnessBox/blob/main/docs/extensions.md) — публичные типы и контракт проектных чекеров.
- [Разработка](https://github.com/kaufd/WitnessBox/blob/main/docs/development.md) — команды тестов, SDK и standalone-сборка.
- [Решения](https://github.com/kaufd/WitnessBox/blob/main/docs/decisions.md) — текущий статус и append-only журнал решений.

## Лицензия

[MIT](https://github.com/kaufd/WitnessBox/blob/main/LICENSE). SDK-файлы (`Ebt.java`, `ebt.ts`, `ebt.dart`) копируются в код приложения без изменений и несут строку `SPDX-License-Identifier: MIT`.
