// Tests of the canonical TypeScript SDK (make test-ts).
import { readFileSync } from 'node:fs';
import { beforeEach, expect, test } from 'bun:test';
import { Ebt, ev, traced } from '../../../src/witnessbox/resources/lib/ebt/ebt';

beforeEach(() => Ebt.reset());

test('ev writes a record with scope and seq, data is snapshotted at call time', () => {
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

test('traced writes the input fields and result, the call returns the function result', () => {
  const decide = traced('INV-S', 'REQ-S', (input: { seen: string[]; latest: string }) =>
    input.seen.includes(input.latest) ? null : input.latest,
  );
  expect(decide({ seen: [], latest: 'r2' })).toBe('r2');
  expect(Ebt.records()[0]).toEqual({
    seq: 1, req: 'REQ-S', inv: 'INV-S', ok: true, data: { seen: [], latest: 'r2', result: 'r2' },
  });
});

test('traced with its own witness and with a Promise; a rejected Promise is not recorded', async () => {
  const add = traced('INV-P', 'REQ-P', async (a: number, b: number) => a + b, ([a, b], sum) => ({ a, b, sum }));
  expect(await add(2, 3)).toBe(5);
  const fail = traced('INV-P', 'REQ-P', async (): Promise<number> => {
    throw new Error('x');
  });
  await expect(fail()).rejects.toThrow('x');
  await Promise.resolve();
  expect(Ebt.records().map((r) => r.data)).toEqual([{ a: 2, b: 3, sum: 5 }]);
});

test('traced with a Promise records the input and scope of the call time', async () => {
  const input = { n: 1 };
  Ebt.scope = 'first';
  const pending = traced('INV-P', 'REQ-P', async (x: { n: number }) => x.n)(input);
  input.n = 2;
  Ebt.scope = 'second';
  expect(await pending).toBe(1);
  expect(Ebt.records()).toEqual([{ seq: 1, scope: 'first', req: 'REQ-P', inv: 'INV-P', ok: true, data: { n: 1, result: 1 } }]);
});

test('toJsonl is one line per record, reset clears both seq and scope', () => {
  Ebt.scope = 's';
  ev('INV-A', 'REQ-A', true, {});
  ev('INV-A', 'REQ-A', true, {});
  expect(Ebt.toJsonl().split('\n')).toHaveLength(2);
  Ebt.reset();
  ev('INV-A', 'REQ-A', true, {});
  expect(Ebt.records()).toEqual([{ seq: 1, req: 'REQ-A', inv: 'INV-A', ok: true, data: {} }]);
});

test('golden: the scenario shared by Java, TypeScript and Dart is written byte for byte', () => {
  // Field order is set by literals only for byte comparison; the checker ignores order.
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

test('a value that cannot be recorded exactly is an error with the field path; the record does not reach the log', () => {
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

test('the test sees a traced recording error: a synchronous call throws, a Promise rejects', async () => {
  const half = traced('INV-T', 'REQ-T', (x: { n: number }) => x.n / 2);
  expect(() => half({ n: 3 })).toThrow('data.result');
  const halfLater = traced('INV-T', 'REQ-T', async (x: { n: number }) => x.n / 2);
  await expect(halfLater({ n: 3 })).rejects.toThrow('data.result');
  expect(await halfLater({ n: 4 })).toBe(2);
  expect(Ebt.records().map((r) => r.data)).toEqual([{ n: 4, result: 2 }]);
});
