# Быстрый старт: от нуля до первого PASS

Учебник проходит весь путь на крошечном TypeScript-проекте: установка, заготовка `ebt/`, тест свидетельств, зелёный гейт, затем внесённый дефект и красный гейт с причиной `checker_failed`. Это тот же сценарий, что в [examples/e2e/ts](../examples/e2e/ts) (D48); его же прогоняет `make e2e STACK=ts`. Для готового примера на скидке в магазине см. [как это работает](example.md), для написания собственной спецификации — [руководство](authoring.md).

Чему учебник не учит: он берёт шаблонное требование «`result = value × 2`» как есть. В реальном проекте спецификацию утверждает человек (D4), а не тот, кто пишет код; пример нужен, чтобы увидеть работающий цикл.

## Что понадобится

- Python 3.11+ и [uv](https://docs.astral.sh/uv/) (или `pipx`);
- [Bun](https://bun.sh/) — запускает тесты Vitest в стеке `ts`;
- `git`: гейт проверяет закоммиченный чистый клон.

Команды `--check-only` и `--test-checks` появились в 0.7.0; на более ранних выпусках шаги 5 и 6 пропустите или обновите установку. Вывод ниже снят с wheel 0.7.0, собранного из этого дерева (`uv build`); пути в нём сокращены.

## 1. Установка

```bash
uv tool install witnessbox
```

Появятся две команды: `ebt-gate` и `ebt-check`. Отдельной команды `witnessbox` нет. Версию и отпечатки поставки показывает `ebt-gate --installation`.

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
ebt-gate --scaffold ts ebt
```

`bun install` создаст `bun.lock`: его нужно закоммитить, потому что гейт ставит зависимости в чистом клоне командой `bun install --frozen-lockfile`. Заготовка печатает список созданного:

```
Создана заготовка ebt/ (ts) в …/double-demo/ebt:
  spec.toml
  checks.py
  test_checks.py
  README.md
  test.sh
  pinned.txt
```

Что в ней важно сейчас:

- `ebt/spec.toml` — пример требования `REQ-EXAMPLE-1` и инварианта `INV-EXAMPLE-1`: `result == value × 2`, `witness = ["value", "result"]`, классы входов `zero`, `positive`, `negative`;
- `ebt/checks.py` — независимый чекер `example_rule`: он пересчитывает `value × 2` сам и не импортирует приложение;
- `ebt/test.sh` — запуск `bunx vitest run .ebt.test` и копирование `build/ebt/*.jsonl` в `OUT_DIR`; его трогать не нужно.

Здесь шаблонную спецификацию мы оставляем как есть. Для своего требования её заменяют по [руководству](authoring.md).

## 3. Копия SDK

```bash
ebt-gate --sync-pinned ebt
```

```
обновлён src/lib/ebt/ebt.ts
```

Команда прочитала `ebt/pinned.txt` (строка `kit:lib/ebt/ebt.ts  src/lib/ebt/ebt.ts`) и положила SDK из установленной поставки в проект. Гейт сверяет копию с оригиналом байт в байт; правка копии вручную даст `pinned_drift`.

## 4. Тест свидетельств

`double.ebt.test.ts` в корне проекта: тест водит код по классам входов и записывает по одному свидетельству на класс.

```ts
import { afterAll, describe, expect, it } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";

import { Ebt, ev } from "./src/lib/ebt/ebt";
import { double } from "./src/double";

// Свидетельства пишутся после всех случаев: классы покрытия — zero/positive/negative.
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

Формат записи и допустимые значения `data` — в [SDK](sdk.md).

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
ebt-gate --test-checks ebt
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
BASE=$(git rev-parse HEAD) ebt-gate --check-only ebt .
```

```
ок spec
ок checks
ок known: нет known.toml
ок baseline: нет baseline.jsonl
ок runner
ок pinned
ок clone
ок base
```

До коммита та же команда нашла бы проблему: `проблема clone: дерево клона не чистое`, код `1`. Без `BASE` строка `base` будет `пропущено`: защищённые пути не проверялись. `--check-only` — подсказка, а не вердикт.

## 7. Гейт: PASS

```bash
BASE=$(git rev-parse HEAD) ebt-gate ebt . ../results
echo $?
```

Три аргумента — каталог `ebt/`, клон проекта и каталог результатов (его гейт создаёт и очищает сам; держите его вне клона). `BASE` — коммит, относительно которого гейт ищет изменения защищённых путей; здесь он совпадает с проверяемым коммитом.

Код возврата `0`. В `../results/gate.md` первая строка — `# EBT-гейт: зелёный`, а в `gate.json`:

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

В `report.md` — «Итог: ✅ доказано на этом прогоне», все категории находок равны нулю, а в самопроверке чекера: «порча любого поля ловится».

Что гейт сделал: поставил зависимости (`prepare.sh`), запустил `test.sh`, собрал свидетельства, пересчитал каждую запись чекером `example_rule`, проверил, что встретились все классы входов, и записал итог. PASS означает: на записанных сценариях правило выполнено. Он не означает, что код верен вне этих сценариев; границы гарантий — в [модели угроз](security.md).

Если свидетельств нет вовсе (например, нет файла теста), гейт даёт не PASS, а ERROR: код `2`, причина `gate_error`, в `gate.json` — `"message": "нет свидетельств …"`. Отсутствие проверки не считается успехом.

## 8. Внесите дефект

Замените `src/double.ts`:

```ts
export function double(value: number): number {
  return value * 3;
}
```

```bash
git commit -am "double: умножение на 3"
BASE=$(git rev-parse HEAD~1) ebt-gate ebt . ../results-defect
echo $?
```

Код возврата `1`. Заготовка и тест не менялись, `BASE` — коммит до дефекта; защищённые пути не тронуты.

## 9. Как читать результат

`gate.md` начинается строкой `# EBT-гейт: красный`, затем идут версии, хеши и коды стадий: `Тесты test.sh: код 1 · ebt_check: код 1`. Причины — в `gate.json`:

```json
{ "result": "FAIL", "exit_code": 1, "reasons": ["checker_failed", "tests_failed"] }
```

- `checker_failed` — чекер нашёл нарушение или дыру в покрытии: смотрите `report.md`;
- `tests_failed` — упали сами тесты (`expect(result).toBe(value * 2)`); подробности — в `test.log`. Здесь причин две, потому что дефект виден и тесту, и чекеру. Полный список причин — в [usage](usage.md#запуск-гейта-и-чекера).

Главное — `report.md`:

```
**Итог: ❌ не доказано**

| Подтверждённое нарушение | 2 |
| Инварианты с непройденными классами входов | 1 |

### Подтверждённое нарушение — `INV-EXAMPLE-1`
- Где: строка 2, scope `positive`, seq 2
- Инвариант: result == value × 2
- Код заявил ok=False; чекер: нарушение
- Причина: result=63, по правилу value × 2 ожидалось 42
- Свидетельство: `{"value":21,"result":63}`
…
## Покрытие

- **INV-EXAMPLE-1**: не встретились классы входов: `positive`, `negative`
```

Читать его надо так: «Где» указывает строку и `scope` свидетельства, «Причина» — что пересчитал чекер, «Свидетельство» — записанные данные. Строка «код заявил ok=…» показывает, что решило приложение; чекер её не использует. Если приложение запишет `ok=true` на неверных данных, это отдельная категория — «Ложное доказательство (код: ok, чекер: нарушение)»: чекер нарушение всё равно найдёт. Нарушенное свидетельство не засчитывает класс входов: поэтому классы `positive` и `negative` числятся непройденными.

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

`make e2e STACK=ts` собирает временный репозиторий из заготовки и `examples/e2e/ts`, прогоняет гейт на исправном коде (ожидает PASS), накладывает `examples/e2e/ts/defect/` и ожидает FAIL с `checker_failed` и без `protected_paths_changed`. Аналоги — `STACK=jvm` и `STACK=generic`. Нужны установленный `ebt-gate`, `bun` (для `jvm` — `gradle` и JDK 17).

## Дальше

- Своё требование: [от требования до тестов свидетельств](authoring.md).
- Другие стеки и договор `test.sh`: [заготовка](scaffold.md).
- CI: [двухстадийный гейт](ci.md).
- Что гейт не гарантирует: [модель угроз](security.md).
