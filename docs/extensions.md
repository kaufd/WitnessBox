# Checker extensions

**English** · [Русский](extensions.ru.md)

Extensions live in the trusted project `checks.py`. They receive the specification data and the evidence; an independent implementation of a rule must not import the application, its SDK or its runtime logic. This keeps the result re-checkable separately from the code that produced it.

Import the public types like this:

```python
from witnessbox.api import Verdict, WitnessError
```

Existing projects may keep the old import `from ebt_verification.api import Verdict, WitnessError`: it returns the same objects, and there is no second implementation.

Custom rules are registered through `CHECKERS`; derived partitions are declared through `DERIVED_PARTITIONS`. The names must not conflict with base rules or other custom rules. Keep the type contract described in `api.py` and raise `WitnessError` for malformed evidence. The compatible re-exports of the old types preserve object identity, but new extensions must use the public API module.

The checker verifies the content of the evidence itself: the application's `ok` flag does not determine the verdict. Scope, baseline and known findings have a separate meaning and must not turn into a way around the check. For every extension, write tests for correct evidence and for boundary/error cases; `--self-test` must verify the sensitivity of the rule.

`--self-test` corrupts every evidence field and the first 8 elements of lists: an element is removed, and its content is corrupted along the paths (`lines[1]`, `lines[1].qty`). The report lists weak spots as paths, not only as a field name. If a field or a path legitimately does not affect the verdict, the owner lists it in `not_in_verdict`: a field name covers all of its subpaths, and a path is written with `[*]` instead of an index (`lines[*].note`); concrete indexes in `not_in_verdict` are not supported, because paths are normalized. The decision to exclude is made by a human (D4), not by the checker author.

## Limits of applicability

The project `checks.py` is trusted Python code and runs inside the checker process. It is not an isolated environment. An extension checks only the data it receives under the contract; it does not prove that the application performed behaviour outside the collected evidence. Parallel scenarios require proper isolation and ordering on the project side. Changing the API format, a new Runner API, a UI or new runtime dependencies require a separate decision. The decisions and their status are collected in [decisions](decisions.md).
