# Contributing

Thanks for helping make backtest validation more honest. Before opening a change:

1. **Specification first.** If a computation changes, update [docs/CONVENTIONS.md](docs/CONVENTIONS.md) first, then the
   independent oracle in `tests/oracle/` (which must never import `lockin_validate`), then the code.
2. **Expected outcomes are fixed before running the tool.** A new benchmark case is a generator in
   `cases/_generators/` (seeded, no import of the package) plus an `expected.json` derived from the planted problem.
   Never edit an `expected.json` to match the tool's output; if an expectation turns out wrong, document why in
   [docs/CASE_CHANGES.md](docs/CASE_CHANGES.md).
3. **Never PASS what could not be verified.** A new check must return NOT_EXECUTABLE with a reason when its inputs are
   missing, NEEDS_REVIEW when the test cannot discriminate, and attach evidence (row ids, dates, values) and a
   reproducible procedure to every finding. Add it to `catalog.py`, `REQUIREMENTS` in `inputs.py`, docs/CHECKS.md
   (`uv run python docs/generate_checks_md.py`) and docs/INPUT_SPEC.md.
4. **No new runtime dependencies** beyond numpy, pandas and pyyaml, no network access, no telemetry, no remote AI.
5. **English only** in code, docs, CLI and reports.

Local checks:

```bash
uv sync
uv run ruff check src tests cases/_generators
uv run pytest
uv run lockin-validate cases
```

By contributing you agree that your contribution is licensed under the Apache License 2.0.
