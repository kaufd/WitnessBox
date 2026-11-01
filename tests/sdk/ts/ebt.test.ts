// Тесты канонического TypeScript SDK (make test-ts).
import { readFileSync } from 'node:fs';
import { beforeEach, expect, test } from 'bun:test';
import { Ebt, ev, traced } from '../../../src/ebt_verification/resources/lib/ebt/ebt';

beforeEach(() => Ebt.reset());

test('ev пишет запись со scope и seq, data снимается в момент вызова', () => {
  Ebt.scope = 'cart';
  const data = { result: 1 };
  ev('INV-A', 'REQ-A', true, data);
  data.result = 2;
  ev('INV-A', 'REQ-A', false, () => ({ result: 3 }));
  expect(Ebt.records()).toEqual([
    { seq: 1, scope: 'cart', req: 'REQ-A', inv: 'INV-A', ok: true, data: { result: 1 } },
    { seq: 2, scope: 'cart', req: 'REQ-A', inv: 'INV-A', ok: false, data: { result: 3 } },
  ]);
});

test('traced пишет поля входа и result, вызов возвращает результат функции', () => {
  const decide = traced('INV-S', 'REQ-S', (input: { seen: string[]; latest: string }) =>
    input.seen.includes(input.latest) ? null : input.latest,
  );
  expect(decide({ seen: [], latest: 'r2' })).toBe('r2');
  expect(Ebt.records()[0]).toEqual({
    seq: 1, req: 'REQ-S', inv: 'INV-S', ok: true, data: { seen: [], latest: 'r2', result: 'r2' },
  });
});

test('traced со своим witness и с Promise; отклонённый Promise не пишется', async () => {
  const add = traced('INV-P', 'REQ-P', async (a: number, b: number) => a + b, ([a, b], sum) => ({ a, b, sum }));
  expect(await add(2, 3)).toBe(5);
  const fail = traced('INV-P', 'REQ-P', async (): Promise<number> => {
    throw new Error('x');
  });
  await expect(fail()).rejects.toThrow('x');
  await Promise.resolve();
  expect(Ebt.records().map((r) => r.data)).toEqual([{ a: 2, b: 3, sum: 5 }]);
});

test('traced с Promise пишет вход и scope момента вызова', async () => {
  const input = { n: 1 };
  Ebt.scope = 'first';
  const pending = traced('INV-P', 'REQ-P', async (x: { n: number }) => x.n)(input);
  input.n = 2;
  Ebt.scope = 'second';
  expect(await pending).toBe(1);
  expect(Ebt.records()).toEqual([{ seq: 1, scope: 'first', req: 'REQ-P', inv: 'INV-P', ok: true, data: { n: 1, result: 1 } }]);
});

test('toJsonl — строка на запись, reset очищает и seq, и scope', () => {
  Ebt.scope = 's';
  ev('INV-A', 'REQ-A', true, {});
  ev('INV-A', 'REQ-A', true, {});
  expect(Ebt.toJsonl().split('\n')).toHaveLength(2);
  Ebt.reset();
  ev('INV-A', 'REQ-A', true, {});
  expect(Ebt.records()).toEqual([{ seq: 1, req: 'REQ-A', inv: 'INV-A', ok: true, data: {} }]);
});

test('golden: общий для Java, TypeScript и Dart сценарий записывается байт в байт', () => {
  // Порядок полей задан литералами только для сравнения байтов; чекер порядок не учитывает.
  Ebt.scope = 'golden';
  ev('INV-G', 'REQ-G', true, {
    int: -42,
    max: Number.MAX_SAFE_INTEGER,
    text: 'q"b\\s\nt\tr\rc\u0001 ё 😀',
    flag: false,
    none: null,
    list: [1, null, [2, 'x'], {}],
    map: { b: 1, a: 2 },
  });
  ev('INV-G', 'REQ-G', false, {});
  Ebt.scope = undefined;
  ev('INV-G', 'REQ-G', true, { n: 1 });
  expect(Ebt.toJsonl() + '\n').toBe(readFileSync(new URL('../golden.jsonl', import.meta.url), 'utf8'));
});

test('значение, которое нельзя записать точно, — ошибка с путём поля; запись не попадает в лог', () => {
  const holes: unknown[] = [1];
  holes[2] = 2;
  const bad: [unknown, string][] = [
    [1.5, 'data.v[0].x'], [NaN, 'data.v[0].x'], [Infinity, 'data.v[0].x'], [-Infinity, 'data.v[0].x'],
    [2 ** 53, 'data.v[0].x'], [undefined, 'data.v[0].x'], [new Date(0), 'data.v[0].x'],
    [new Map(), 'data.v[0].x'], [() => 1, 'data.v[0].x'], [BigInt(1), 'data.v[0].x'], [holes, 'data.v[0].x[1]'],
  ];
  for (const [value, path] of bad) {
    expect(() => ev('INV-N', 'REQ-N', true, { v: [{ x: value }] })).toThrow(path);
  }
  expect(Ebt.toJsonl()).toBe('');
  ev('INV-N', 'REQ-N', true, { v: null, min: Number.MIN_SAFE_INTEGER });
  expect(Ebt.records()).toEqual([
    { seq: 1, req: 'REQ-N', inv: 'INV-N', ok: true, data: { v: null, min: Number.MIN_SAFE_INTEGER } },
  ]);
});

test('ошибку записи traced видит тест: синхронный вызов бросает, Promise отклоняется', async () => {
  const half = traced('INV-T', 'REQ-T', (x: { n: number }) => x.n / 2);
  expect(() => half({ n: 3 })).toThrow('data.result');
  const halfLater = traced('INV-T', 'REQ-T', async (x: { n: number }) => x.n / 2);
  await expect(halfLater({ n: 3 })).rejects.toThrow('data.result');
  expect(await halfLater({ n: 4 })).toBe(2);
  expect(Ebt.records().map((r) => r.data)).toEqual([{ n: 4, result: 2 }]);
});
