# Быстрый старт: от нуля до первого PASS

[English](quickstart.md) · **Русский**

Учебник проходит весь путь на крошечном TypeScript-проекте: установка, заготовка `ebt/`, тест свидетельств, зелёный гейт, затем внесённый дефект и красный гейт с причиной `checker_failed`. Это тот же сценарий, что в [examples/e2e/ts](../examples/e2e/ts) (D48); его же прогоняет `make e2e STACK=ts`. Для готового примера на скидке в магазине см. [как это работает](example.ru.md), для написания собственной спецификации — [руководство](authoring.ru.md).

Чему учебник не учит: он берёт шаблонное требование «`result = value × 2`» как есть. В реальном проекте спецификацию утверждает человек (D4), а не тот, кто пишет код; пример нужен, чтобы увидеть работающий цикл.

## Что понадобится

- Python 3.11+ и [uv](https://docs.astral.sh/uv/) (или `pipx`);
- [Bun](https://bun.sh/) — запускает тесты Vitest в стеке `ts`;
- `git`: гейт проверяет закоммиченный чистый клон.

Команда `witnessbox` появилась в 0.7.0; более ранние выпуски давали `ebt-gate` и `ebt-check`, и шаги ниже на них не работают. Установленную раньше версию обновите: `uv tool upgrade witnessbox`. Вывод ниже снят с wheel 0.8.0, собранного из этого дерева (`uv build`); пути в нём сокращены.

## 1. Установка

```bash
uv tool install witnessbox
```

Появится одна команда `witnessbox` с подкомандами `gate`, `check`, `scaffold`, `sync-pinned`, `test-checks` и `spec`; список выводит `witnessbox --help`. Версию и отпечатки поставки показывает `witnessbox --installation`.

## 2. Проект и заготовка `ebt/`

Создайте проект с одной функцией:

```bash
mkdir double-demo && cd double-demo
git init
mkdir src
```

`package.json`:

```json
{
  "name": "double-demo",
  "private": true,
  "type": "module",
  "devDependencies": {
    "vitest": "5.0.5"
  }
}
```

`vitest.config.ts` — Vitest ищет только тесты свидетельств:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["*.ebt.test.ts"],
  },
});
```

`tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "skipLibCheck": true,
    "types": ["vitest/globals"]
  },
  "include": ["src", "*.ts"]
}
```

`src/double.ts`:

```ts
export function double(value: number): number {
  return value * 2;
}
```

`.gitignore`:

```
node_modules/
build/
```

Установите зависимости и создайте заготовку:

```bash
bun install
witnessbox scaffold ts ebt
```

`bun install` создаст `bun.lock`: его нужно закоммитить, потому что гейт ставит зависимости в чистом клоне командой `bun install --frozen-lockfile`. Заготовка печатает список созданного:

```
Created ebt/ scaffold (ts) in …/double-demo/ebt:
  spec.toml
  checks.py
  test_checks.py
  README.md
  test.sh
  pinned.txt
Next:
  replace the example REQ-EXAMPLE-1/INV-EXAMPLE-1 with an approved requirement (may stay for a trial);
  run the checker tests: witnessbox test-checks ebt;
  copy the SDK and helpers: witnessbox sync-pinned ebt;
  write an evidence test (it writes build/ebt/*.jsonl) and, if needed, ebt/prepare.sh;
  commit the project and check the setup: witnessbox gate --check-only ebt .;
  run the gate: witnessbox gate ebt . <result dir>.
Details are in the directory README.md.
```

Подсказка `Next` — порядок для своего проекта, как в `ebt/README.md`. Учебник оставляет шаблонную спецификацию, поэтому сначала копирует SDK и пишет тест, а тесты чекера запускает перед коммитом.

Что в ней важно сейчас:

- `ebt/spec.toml` — пример требования `REQ-EXAMPLE-1` и инварианта `INV-EXAMPLE-1`: `result == value × 2`, `witness = ["value", "result"]`, классы входов `zero`, `positive`, `negative`;
- `ebt/checks.py` — независимый чекер `example_rule`: он пересчитывает `value × 2` сам и не импортирует приложение;
- `ebt/test.sh` — запуск `bunx vitest run .ebt.test` и копирование `build/ebt/*.jsonl` в `OUT_DIR`; его трогать не нужно.

Здесь шаблонную спецификацию мы оставляем как есть. Для своего требования её заменяют по [руководству](authoring.ru.md).

## 3. Копия SDK

```bash
witnessbox sync-pinned ebt
```

```
updated src/lib/ebt/ebt.ts
```

Команда прочитала `ebt/pinned.txt` (строка `kit:lib/ebt/ebt.ts  src/lib/ebt/ebt.ts`) и положила SDK из установленной поставки в проект. Гейт сверяет копию с оригиналом байт в байт; правка копии вручную даст `pinned_drift`.

## 4. Тест свидетельств

`double.ebt.test.ts` в корне проекта: тест водит код по классам входов и записывает по одному свидетельству на класс.

```ts
import { afterAll, describe, expect, it } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";

import { Ebt, ev } from "./src/lib/ebt/ebt";
import { double } from "./src/double";

// Evidence is written after all cases: partitions are zero/positive/negative.
afterAll(() => {
  mkdirSync("build/ebt", { recursive: true });
  writeFileSync("build/ebt/double.jsonl", Ebt.toJsonl() + "\n");
});

describe("double", () => {
  const cases = [
    ["zero", 0],
    ["positive", 21],
    ["negative", -4],
  ] as const;

  for (const [name, value] of cases) {
    it(name, () => {
      Ebt.scope = name;
      const result = double(value);
      ev("INV-EXAMPLE-1", "REQ-EXAMPLE-1", result === value * 2, { value, result });
      expect(result).toBe(value * 2);
    });
  }
});
```

Что здесь происходит:

- `Ebt.scope = name` — имя класса входов; оно попадает в запись и отделяет сценарии друг от друга;
- `ev(inv, req, ok, data)` — запись: какой инвариант, какое требование, что решил код (`ok`) и **данные решения** (`data`) — ровно поля `witness` из `spec.toml`;
- `afterAll` — запись файла `build/ebt/double.jsonl`; `test.sh` скопирует его в `OUT_DIR`;
- `expect` — обычная проверка теста. Она не заменяет свидетельство: гейт верит не ей, а пересчёту чекера.

Формат записи и допустимые значения `data` — в [SDK](sdk.ru.md).

## 5. `prepare.sh`

В чистом клоне нет `node_modules`. Гейт запускает `ebt/prepare.sh` до `test.sh`, поэтому зависимости ставит он:

```bash
cat > ebt/prepare.sh <<'EOF'
#!/bin/bash
set -euo pipefail

bun install --frozen-lockfile
EOF
chmod 755 ebt/prepare.sh
```

## 6. Проверка чекера и подключения до полного прогона

Тесты чекера из заготовки:

```bash
witnessbox test-checks ebt
```

```
test_bool_is_not_an_integer (test_checks.ExampleRule.test_bool_is_not_an_integer) ... ok
test_missing_field (test_checks.ExampleRule.test_missing_field) ... ok
test_negative (test_checks.ExampleRule.test_negative) ... ok
test_positive (test_checks.ExampleRule.test_positive) ... ok
test_registered (test_checks.ExampleRule.test_registered) ... ok
test_wrong_result_is_a_violation (test_checks.ExampleRule.test_wrong_result_is_a_violation) ... ok
test_zero (test_checks.ExampleRule.test_zero) ... ok

Ran 7 tests in 0.000s

OK
```

Теперь закоммитьте всё, включая `ebt/`: гейт проверяет клон, а изменение `ebt/` внутри проверяемой ветки считает нарушением защищённых путей.

```bash
git add -A
git commit -m "Проект с заготовкой ebt"
```

Проверка подключения (`prepare.sh` и `test.sh` она не запускает):

```bash
BASE=$(git rev-parse HEAD) witnessbox gate --check-only ebt .
```

```
ok spec
ok checks
ok known: no known.toml
ok baseline: no baseline.jsonl
ok runner
ok pinned
ok clone
ok base
```

До первого коммита та же команда нашла бы проблему: `problem clone: the repository has no commits: the gate checks only committed files`, код `1`; с незакоммиченными правками после него — `problem clone: the clone tree is not clean`. Без `BASE` строка `base` будет `skipped`: защищённые пути не проверялись. `--check-only` — подсказка, а не вердикт.

## 7. Гейт: PASS

```bash
BASE=$(git rev-parse HEAD) witnessbox gate ebt . ../results
echo $?
```

Три аргумента — каталог `ebt/`, клон проекта и каталог результатов (его гейт создаёт и очищает сам; держите его вне клона). `BASE` — коммит, относительно которого гейт ищет изменения защищённых путей; здесь он совпадает с проверяемым коммитом.

Код возврата `0`. Гейт печатает `gate.md` в терминал; его первая строка — `# EBT gate: green`. Строка `Checker` показывает версию самого чекера (`witnessbox check 0.1.0`): она ведётся отдельно от версии поставки, а поставку и чекер однозначно задают sha256. В `gate.json`:

```json
{
  "format": 1,
  "result": "PASS",
  "exit_code": 0,
  "reasons": [],
  "tests_exit_code": 0,
  "checker_exit_code": 0,
  "evidence": [{"file": "double.jsonl", "sha256": "…"}]
}
```

(Показаны не все поля.) Свидетельства — `../results/evidence.jsonl`, три строки, по одной на класс:

```
{"seq":1,"scope":"zero","req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,"data":{"value":0,"result":0}}
{"seq":2,"scope":"positive","req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,"data":{"value":21,"result":42}}
{"seq":3,"scope":"negative","req":"REQ-EXAMPLE-1","inv":"INV-EXAMPLE-1","ok":true,"data":{"value":-4,"result":-8}}
```

В `report.md` — «Result: ✅ proven on this run», все категории находок равны нулю, а в самопроверке чекера: «corruption of any field is caught».

Что гейт сделал: поставил зависимости (`prepare.sh`), запустил `test.sh`, собрал свидетельства, пересчитал каждую запись чекером `example_rule`, проверил, что встретились все классы входов, и записал итог. PASS означает: на записанных сценариях правило выполнено. Он не означает, что код верен вне этих сценариев; границы гарантий — в [модели угроз](security.ru.md).

Если свидетельств нет вовсе (например, нет файла теста), гейт даёт не PASS, а ERROR: код `2`, причина `gate_error`, в `gate.json` — `"message": "no evidence in …"`. Отсутствие проверки не считается успехом.

## 8. Внесите дефект

Замените `src/double.ts`:

```ts
export function double(value: number): number {
  return value * 3;
}
```

```bash
git commit -am "double: умножение на 3"
BASE=$(git rev-parse HEAD~1) witnessbox gate ebt . ../results-defect
echo $?
```

Код возврата `1`. Заготовка и тест не менялись, `BASE` — коммит до дефекта; защищённые пути не тронуты.

## 9. Как читать результат

`gate.md` начинается строкой `# EBT gate: red`, затем идут версии, хеши и коды стадий: `test.sh tests: code 1 · ebt_check: code 1`. Причины — в `gate.json`:

```json
{ "result": "FAIL", "exit_code": 1, "reasons": ["checker_failed", "tests_failed"] }
```

- `checker_failed` — чекер нашёл нарушение или дыру в покрытии: смотрите `report.md`;
- `tests_failed` — упали сами тесты (`expect(result).toBe(value * 2)`); подробности — в `test.log`. Здесь причин две, потому что дефект виден и тесту, и чекеру. Полный список причин — в [usage](usage.ru.md#запуск-гейта-и-чекера).

Главное — `report.md`:

```
**Result: ❌ not proven**

| Confirmed violation | 2 |
| Invariants with uncovered partitions | 1 |

### Confirmed violation — `INV-EXAMPLE-1`
- Where: line 2, scope `positive`, seq 2
- Invariant: result == value × 2
- Code claimed ok=False; checker: violation
- Reason: result=63, by the rule value × 2 expected 42
- Evidence: `{"value":21,"result":63}`
…
## Coverage

- **INV-EXAMPLE-1**: partitions not encountered: `positive`, `negative`
```

Читать его надо так: `Where` указывает строку и `scope` свидетельства, `Reason` — что пересчитал чекер, `Evidence` — записанные данные. Строка `Code claimed ok=…` показывает, что решило приложение; чекер её не использует. Если приложение запишет `ok=true` на неверных данных, это отдельная категория — «False proof (code: ok, checker: violation)»: чекер нарушение всё равно найдёт. Нарушенное свидетельство не засчитывает класс входов: поэтому классы `positive` и `negative` числятся непройденными.

Каталог результатов:

| Файл | Что внутри |
|---|---|
| `gate.json` | итог для CI: `result`, `reasons`, коды стадий, хеши спецификации, поставки и свидетельств |
| `gate.md` | то же коротко для человека |
| `report.md`, `report.json` | находки чекера, покрытие, самопроверка |
| `evidence.jsonl`, `out/` | свидетельства, которые читал чекер |
| `test.log`, `prepare.log` | вывод `test.sh` и `prepare.sh` |
| `inputs/` | копия `spec.toml` и `checks.py`, снятая до `prepare.sh` |

## Автоматическая проверка учебника

`make e2e STACK=ts` собирает временный репозиторий из заготовки и `examples/e2e/ts`, прогоняет гейт на исправном коде (ожидает PASS), накладывает `examples/e2e/ts/defect/` и ожидает FAIL с `checker_failed` и без `protected_paths_changed`. Аналоги — `STACK=jvm` и `STACK=generic`. Нужна установленная команда `witnessbox`, `bun` (для `jvm` — `gradle` и JDK 17).

## Дальше

- Своё требование: [от требования до тестов свидетельств](authoring.ru.md).
- Другие стеки и договор `test.sh`: [заготовка](scaffold.ru.md).
- CI: [двухстадийный гейт](ci.ru.md).
- Что гейт не гарантирует: [модель угроз](security.ru.md).
