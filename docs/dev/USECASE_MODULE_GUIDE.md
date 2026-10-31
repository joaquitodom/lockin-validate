# Writing a use-case module (0.3.0)

A use-case module adds a family of checks for a kind of financial model other than the backtest of a trading
strategy. It is ONE file in `src/lockin_validate/usecases/<name>.py`, plus its own cases, tests and doc page.
Nothing in the core files is edited: the module declares its inputs and checks in a `UseCase` spec and calls
`register(...)` at import time (see `src/lockin_validate/usecases/__init__.py`).

## Files a module owns (and nothing else)

| Path | Content |
|---|---|
| `src/lockin_validate/usecases/<name>.py` | spec, check functions, `register(SPEC)` at the bottom |
| `cases/_generators/usecase_<name>_cases.py` | deterministic generator (stdlib + pandas allowed; it must NOT import `lockin_validate`); writes `cases/usecase_<name>/<NN_case>/` with the inputs and `expected.json` |
| `cases/usecase_<name>/` | generated cases (committed) |
| `tests/test_usecase_<name>.py` | unit tests of the statistics (against hand-computed or closed-form values) and of the check contract |
| `docs/usecases/<name>.md` | the user-facing page: who it is for, inputs, every check (what / why / fix / allows / does not allow / refs), conventions and thresholds with defaults, limitations |

## Contract (identical to the core; do not relax it)

- Statuses: `CONFIRMED_ERROR` only when the input itself proves the error (a target date before its origin, a
  test sample inside the training window, weights summing to 1.3 under a declared no-leverage rule).
  `NEEDS_REVIEW` when a statistic crosses a documented threshold (a person must look). `NOT_EXECUTABLE` with the
  reason when an input is missing or too short (use `missing_inputs` / `not_executable` from `lockin_validate.checks`).
  `PASS` only when the property was actually verified on enough data; never PASS on an empty or trivial input.
  `INFO` for context that is not an alert.
- Every finding carries evidence rows (`[{"row": ..., "date": ..., ...}]` with the CSV line numbers from the
  `row` column of the work table when they exist), a `procedure` sentence saying how it was computed, and an
  `action`.
- Thresholds are conventions read with `pkg.conv("<key>")` and declared in the spec `conventions` with their
  defaults, so rules.yaml can override them and docs/CONVENTIONS.md can list them. Name them with the module prefix
  (`var_kupiec_alpha`, `ml_psi_review`, ...).
- The module never reads the network, never imports scipy / sklearn / statsmodels (numpy + pandas only; implement
  the test statistics yourself: normal and chi-square tails are in `lockin_validate.stats` or write small helpers;
  a chi-square with 1 or 2 degrees of freedom has a closed form).
- Package access: `pkg.df("<table>")` (normalised work DataFrame or None), `pkg.has_column(table, col)`,
  `pkg.missing("<check>")` (from the spec requirements), `pkg.rules`, `pkg.conv(key)`. Core tables (`prices`,
  `signals`, `returns`, `trades`, `positions`, `benchmark_returns`...) are available the same way.
- Findings: `res.add(check, SPEC.name, status, title, detail, evidence, procedure, reason, action, priority, inputs)`.
- `run(pkg, res)` must run every check of the module, each reporting NOT_EXECUTABLE when it cannot run; it must
  never raise on odd data (empty tables, NaN, one row): catch and report NOT_EXECUTABLE with the exception name.

## Cases (pre-registration)

- Write `expected.json` from the planted problem BEFORE running the tool; never edit it after seeing the output.
  If an expectation turns out to be wrong, change the CODE or add a `post_hoc: true` entry (counted separately).
- At least: one clean case (`must_not_include` every check of the module in CONFIRMED_ERROR and NEEDS_REVIEW,
  `errors_only_from: []`), one case per check with the planted error, one adversarial case (an input that looks
  fine but hides the problem, or one that looks wrong but is legitimate and must NOT alert), one
  insufficient-data case (checks must be NOT_EXECUTABLE, not PASS).
- The format of `expected.json` is documented at the top of `src/lockin_validate/cases.py`. Add
  `"use_case": "<name>"` and `"origin": "usecase"`.
- The generator must be re-runnable with identical output (fixed seeds, `random.Random(seed)`).

## Verification before you finish

```
uv run ruff check src tests cases
uv run pytest -q tests/test_usecase_<name>.py
uv run lockin-validate cases --dir cases/usecase_<name>
uv run pytest -q           # the whole suite still passes (the core battery must not change)
uv run lockin-validate explain <one of your checks>
```
Also run `lockin-validate init` scratch + `run` on an EMPTY folder: every check of your module must be
NOT_EXECUTABLE and nothing may raise.

## Spec skeleton

```python
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from . import UseCase, register

NAME = "<name>"

def check_x(pkg: Any, res: AuditResult) -> None:
    title = "..."
    miss = pkg.missing("x")
    if miss:
        missing_inputs(res, "x", NAME, title, miss); return
    ...

def run(pkg: Any, res: AuditResult) -> None:
    for fn, cid in ((check_x, "x"), ...):
        try:
            fn(pkg, res)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")

SPEC = UseCase(name=NAME, title=..., description=..., audience=..., detect_files=[...], files={...},
               schema={...}, aliases={...}, date_columns={...}, numeric_columns={...}, requirements={...},
               catalog={...}, references={...}, conventions={...}, profiles={...}, run=run)
register(SPEC)
```
