# EBT: independent verification report

**Result: ❌ not proven**

Spec `2026-10-28` (sha 357df9c6b7aa) · records: 13 · scopes: 2

| Category | Count |
|---|---|
| False proof (code: ok, checker: violation) | 2 |
| Confirmed violation | 0 |
| Code reported a violation, checker disagrees | 0 |
| Incomplete evidence | 1 |
| Malformed evidence | 0 |
| Invariant not registered | 1 |
| Wrong requirement | 0 |
| No checker | 0 |
| Checker error | 0 |
| Lost records | 0 |
| Broken log line | 0 |
| Requirements without invariants | 1 |
| Invariants without records | 0 |
| Invariants with uncovered partitions | 3 |

## Critical findings

### False proof (code: ok, checker: violation) — `INV-CART-3`
- Where: line 3, scope `checkout_discount`, seq 3
- Requirement REQ-CART-1: Cart total = sum of (price × quantity) over the lines minus the discount. Money is whole minor units. A percent discount is rounded down to the minor unit. A fixed discount is not greater than the sum of the lines. The total is never negative.
- Invariant: result == subtotal − off, where subtotal = Σ price·qty, off is computed by the discount rule from REQ-CART-1
- Code claimed ok=True; checker: violation
- Reason: off=150, by the discount rule percent:15 it must be 149
- Evidence: `{"lines":[[333,3]],"discount":{"type":"percent","value":15},"subtotal":999,"off":150,"result":849}`

### False proof (code: ok, checker: violation) — `INV-SYNC-1`
- Where: line 13, scope `sync_offline`, seq 3
- Requirement REQ-SYNC-1: When merging local and server records by id, the greater version wins, on equal versions the server one. Deleted records (tombstones) do not get into the result. There are no duplicate ids in the result.
- Invariant: out matches the result of merging local and remote by the rule REQ-SYNC-1
- Code claimed ok=True; checker: violation
- Reason: extra/deleted ['e']
- Evidence: `{"local":[["e",5,false]],"remote":[["e",5,true]],"out":[["e",5]]}`

### Incomplete evidence — `INV-CART-3`
- Where: line 9, scope `checkout_discount`, seq 9
- Requirement REQ-CART-1: Cart total = sum of (price × quantity) over the lines minus the discount. Money is whole minor units. A percent discount is rounded down to the minor unit. A fixed discount is not greater than the sum of the lines. The total is never negative.
- Invariant: result == subtotal − off, where subtotal = Σ price·qty, off is computed by the discount rule from REQ-CART-1
- Code claimed ok=True; checker: could not verify
- Reason: missing fields: lines, discount, subtotal, off
- Evidence: `{"result":8490}`

### Invariant not registered — `INV-CART-9`
- Where: line 10, scope `checkout_discount`, seq 10
- Code claimed ok=True; checker: could not verify
- Reason: not in ebt/spec.toml: a new invariant must be approved
- Evidence: `{"items":2}`


## Coverage

- **REQ-PROFILE-1** is not formalized by any invariant
- **INV-CART-3**: partitions not encountered: `empty_cart`, `percent`, `percent_rounding`, `fixed_exceeds_subtotal`
- **INV-SYNC-1**: partitions not encountered: `conflict_remote_wins`
- **SM-CHECKOUT**: partitions not encountered: `confirmed --edit--> cart`

## Changes since the previous run

- `checkout_discount / INV-CART-9` appeared
- `checkout_discount / INV-CART-3`: records were 3, now 4
- `checkout_discount / INV-CART-3`, record #2: off: 149 → 150; result: 850 → 849
- `sync_offline / INV-SYNC-1`, record #3: out: [] → [["e", 5]]

## Checker self-test

Each evidence field and the first elements of its lists are corrupted, and the checker is verified to notice it.

- ℹ️ **INV-CART-3**: corruption of path `discount.type` is caught only by the shape check: substitute another valid value in the test or check that the checker compares it with the rule
- **INV-SYNC-1**: corruption of any field is caught (samples: 2)
- **SM-CHECKOUT**: corruption of any field is caught (samples: 5)
