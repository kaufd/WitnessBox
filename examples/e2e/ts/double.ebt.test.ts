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
