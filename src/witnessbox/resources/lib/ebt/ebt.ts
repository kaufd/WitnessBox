// SPDX-License-Identifier: MIT
// lib/ebt/ebt.ts
//
// EBT: recording proofs along the chain "requirement ⇒ invariant ⇒ proof".
// Copied into the application unchanged (the gate compares the copy with the original, pinned.txt).
//
// Records are made only in tests (Vite/Vitest: import.meta.env.MODE === 'test'). With any other MODE
// ev() returns immediately and traced() returns the original function; what the bundler removes from the bundle
// the SDK does not guarantee. Without import.meta.env (not Vite) the module fails on import.
//
// Valid data values (docs/sdk.md): null, boolean, string, safe integer, array
// and a plain object of those. Anything else is a TypeError with the field path; the record is not logged.
//
// Logic in a pure function: wrap at the declaration, a record on every call:
//
//   export const cartTotal = traced('INV-CART-3', 'REQ-CART-1', (input: CartInput) => …);
//
// Evidence fields by default are the fields of the first argument plus `result`; another shape
// goes through witness. Otherwise, a record at the point where the invariant must hold:
//
//   ev('INV-CART-3', 'REQ-CART-1', result >= 0, () => ({ subtotal, off, result }));
//
// In a test: Ebt.scope = '<scope>'; in afterAll, write Ebt.toJsonl() to build/ebt/<feature>.jsonl.

const ON = import.meta.env.MODE === 'test';

type Data = Record<string, unknown>;

// A record is stored as a JSON string taken at call time: a later edit of data does not change the proof.
const records: string[] = [];
let seq = 0;

// JSON.stringify would silently distort such values: NaN → null, an undefined field disappears,
// Date → string, Map → {}, a fraction and an unsafe integer lose precision on reading.
function checkValue(v: unknown, path: string): void {
  if (v === null || typeof v === 'string' || typeof v === 'boolean') return;
  if (typeof v === 'number') {
    if (Number.isSafeInteger(v)) return;
    throw new TypeError(`${path}: cannot record number ${v} exactly; pass a safe integer`);
  }
  if (Array.isArray(v)) {
    // By index, not forEach: a hole in an array is undefined, not a skip.
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
  throw new TypeError(`${path}: cannot record value ${Object.prototype.toString.call(v)} exactly`
    + ' — pass an integer, string, boolean, null, array or plain object');
}

function record(inv: string, req: string, ok: boolean, data: Data, scope = Ebt.scope): void {
  checkValue(data, 'data');
  // No time or random values: the log must be comparable between runs.
  records.push(JSON.stringify({ seq: ++seq, ...(scope ? { scope } : {}), req, inv, ok, data }));
}

// The input is snapshotted at call time: the arguments may change by the time a Promise settles.
// An argument that cannot be cloned (a function) is kept as is.
function snapshot<A extends unknown[]>(args: A): A {
  try {
    return structuredClone(args);
  } catch {
    return args;
  }
}

/** Record a proof. `ok` is a claim by the code; the checker ignores it. */
export function ev(inv: string, req: string, ok: boolean, data: Data | (() => Data)): void {
  if (!ON) return;
  record(inv, req, ok, typeof data === 'function' ? data() : data);
}

/**
 * Wrap a pure function: every call in tests records the input and the result.
 * The record is made after the result; for a Promise after it settles, a rejected one is not recorded,
 * and the input and scope are those taken at call time. A recording error is visible to the caller: a synchronous call
 * throws it, and for a Promise a derived Promise is returned that rejects with it.
 * The wrapper makes no claim of its own, so ok is always true: the checker decides.
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
  /** Current scope: a name of a test or a group of cases. */
  scope: undefined as string | undefined,

  /** Log in JSON Lines format, for the checker and diffs between runs. */
  toJsonl(): string {
    return records.join('\n');
  },

  /** Copies of the records: changing them does not touch the log. */
  records(): Data[] {
    return records.map((line) => JSON.parse(line) as Data);
  },

  reset(): void {
    records.length = 0;
    seq = 0;
    Ebt.scope = undefined;
  },
};
