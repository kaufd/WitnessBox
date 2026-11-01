// SPDX-License-Identifier: MIT
// lib/ebt/ebt.ts
//
// EBT: запись доказательств по цепочке «требование ⇒ инвариант ⇒ доказательство».
// Копируется в приложение без изменений (гейт сверяет копию с оригиналом, pinned.txt).
//
// Записи идут только в тестах (Vite/Vitest: import.meta.env.MODE === 'test'). При другом MODE
// ev() сразу возвращается, а traced() отдаёт исходную функцию; что сборщик удалит из бандла,
// SDK не гарантирует. Без import.meta.env (не Vite) модуль падает при импорте.
//
// Допустимые значения data — docs/sdk.md: null, boolean, строка, безопасное целое, массив
// и простой объект из них. Остальное — TypeError с путём поля; запись в лог не попадает.
//
// Логика в чистой функции — обёртка при объявлении, запись на каждый вызов:
//
//   export const cartTotal = traced('INV-CART-3', 'REQ-CART-1', (input: CartInput) => …);
//
// Поля свидетельства по умолчанию — поля первого аргумента плюс `result`; другой вид —
// через witness. Иначе — запись в точке, где инвариант должен выполняться:
//
//   ev('INV-CART-3', 'REQ-CART-1', result >= 0, () => ({ subtotal, off, result }));
//
// В тесте: Ebt.scope = '<сценарий>'; в afterAll — запись Ebt.toJsonl() в build/ebt/<feature>.jsonl.

const ON = import.meta.env.MODE === 'test';

type Data = Record<string, unknown>;

// Запись хранится строкой JSON, снятой в момент вызова: поздняя правка data не меняет доказательство.
const records: string[] = [];
let seq = 0;

// JSON.stringify молча исказил бы такие значения: NaN → null, поле undefined пропадает,
// Date → строка, Map → {}, дробь и небезопасное целое теряют точность при чтении.
function checkValue(v: unknown, path: string): void {
  if (v === null || typeof v === 'string' || typeof v === 'boolean') return;
  if (typeof v === 'number') {
    if (Number.isSafeInteger(v)) return;
    throw new TypeError(`${path}: нельзя записать точно число ${v} — передайте безопасное целое`);
  }
  if (Array.isArray(v)) {
    // По индексу, а не forEach: дыра в массиве — undefined, а не пропуск.
    for (let i = 0; i < v.length; i++) checkValue(v[i], `${path}[${i}]`);
    return;
  }
  if (typeof v === 'object') {
    const proto = Object.getPrototypeOf(v);
    if (proto === Object.prototype || proto === null) {
      for (const [key, item] of Object.entries(v)) checkValue(item, `${path}.${key}`);
      return;
    }
  }
  throw new TypeError(`${path}: нельзя записать точно значение ${Object.prototype.toString.call(v)}`
    + ' — передайте целое, строку, boolean, null, массив или простой объект');
}

function record(inv: string, req: string, ok: boolean, data: Data, scope = Ebt.scope): void {
  checkValue(data, 'data');
  // Без времени и случайных значений: лог должен сравниваться между прогонами.
  records.push(JSON.stringify({ seq: ++seq, ...(scope ? { scope } : {}), req, inv, ok, data }));
}

// Вход снимается при вызове: к исполнению Promise аргументы могли измениться.
// Аргумент, который не клонируется (функция), — как есть.
function snapshot<A extends unknown[]>(args: A): A {
  try {
    return structuredClone(args);
  } catch {
    return args;
  }
}

/** Записать доказательство. `ok` — заявление кода; чекер его не учитывает. */
export function ev(inv: string, req: string, ok: boolean, data: Data | (() => Data)): void {
  if (!ON) return;
  record(inv, req, ok, typeof data === 'function' ? data() : data);
}

/**
 * Обернуть чистую функцию: каждый вызов в тестах записывает вход и результат.
 * Запись — после результата; у Promise — после его исполнения, отклонённый не записывается,
 * а вход и scope — снятые в момент вызова. Ошибка записи видна вызывающему: синхронный вызов
 * бросает её, а у Promise возвращается производный Promise, который ею отклоняется.
 * Своего заявления у обёртки нет, поэтому ok всегда true: решает чекер.
 */
export function traced<A extends unknown[], R>(
  inv: string,
  req: string,
  fn: (...args: A) => R,
  witness: (args: A, result: Awaited<R>) => Data = (args, result) => ({ ...(args[0] as Data), result }),
): (...args: A) => R {
  if (!ON) return fn;
  return (...args: A): R => {
    const out = fn(...args);
    if (out instanceof Promise) {
      const input = snapshot(args);
      const scope = Ebt.scope;
      return out.then((r: Awaited<R>) => {
        record(inv, req, true, witness(input, r), scope);
        return r;
      }) as R;
    }
    record(inv, req, true, witness(args, out as Awaited<R>));
    return out;
  };
}

export const Ebt = {
  /** Текущий сценарий: имя теста или группы случаев. */
  scope: undefined as string | undefined,

  /** Лог в формате JSON Lines — для чекера и диффа между прогонами. */
  toJsonl(): string {
    return records.join('\n');
  },

  /** Копии записей: их изменение не трогает лог. */
  records(): Data[] {
    return records.map((line) => JSON.parse(line) as Data);
  },

  reset(): void {
    records.length = 0;
    seq = 0;
    Ebt.scope = undefined;
  },
};
