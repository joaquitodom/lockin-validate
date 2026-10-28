# lockin-validate

**Offline toolkit to validate quantitative investment strategies and their backtests.** Give it a folder with what a
strategy owner delivers (prices, signals, trades, positions, costs, rules, declared results, optionally fundamentals,
universe membership, a trials log...) and it produces a reproducible report in which **every finding links to its
evidence**: CSV line numbers, dates, values and the procedure that produced the conclusion.

[Leer en castellano](README.es.md)

## Why

Most backtests that "work" and then fail live have one of a handful of causes: data the model could not know at that
date, costs left out, a metric computed with a different convention, trades that do not follow the written rule,
delisted companies missing, or a Sharpe ratio that is simply the best of many tries. lockin-validate looks for each of
them explicitly, runs locally without network or remote AI, never fixes data silently, and never says PASS about
something it could not verify.

Every result has exactly one status (alerts are the first two):

| Status | Meaning |
|---|---|
| `CONFIRMED_ERROR` | proven with the inputs (reproducible evidence) |
| `NEEDS_REVIEW` | a person must look at it; the inputs are not enough to confirm |
| `NOT_EXECUTABLE` | the check could not run; the reason says which input is missing |
| `INFO` | a note worth reading that is not an alert ([docs/ALERT_POLICY.md](docs/ALERT_POLICY.md) says when) |
| `PASS` | the check ran and found no problem *within its scope* |

## What it checks

| Block | Checks |
|---|---|
| Input | schema and types, manifest with sha256 of every input, silent changes vs a previous run |
| Data | duplicates, impossible dates and prices (NYSE / BYMA / no calendar), OHLC, essential fields, coverage vs calendar, stale quotes, split-like jumps and bad ticks, declared corporate actions, accuracy vs an independent reference, point-in-time fundamentals (`period_end` / `filing_date` / `available_from`), survivorship (with universe membership), ticker recycling (with a security master), trade before signal, signal data after decision |
| Reconstruction | positions, cash and NAV rebuilt from trades with explicit conventions (return base = initial cash); reconciliation against declared positions and declared results with explicit tolerances |
| Strategy | look-ahead (availability timestamps, plus a statistical hint for gross cases), omitted costs (commission and slippage separately; zero cost with turnover is flagged), metric errors (declared convention vs 252/365, arithmetic/geometric, risk-free, log, drawdown variants), rules vs implementation (re-executes rank / top-N / periodic rebalance / equal weight; anything else is NOT_EXECUTABLE) |
| Statistics | Sharpe standard error, Lo (2002) autocorrelation adjustment, PSR, MinTRL, deflated Sharpe with the declared number of trials, multiple-testing haircut (Bonferroni / Holm / BHY), PBO via CSCV, consistency of the declared number of trials, LLM look-ahead risk checklist |
| New in 0.2.0 (each motivated by a failure of the LockIn case study) | **coverage drift** of inputs against the strategy's own history and **input sufficiency** (names scored with fewer than the declared minimum of inputs); **protocol integrity** from a run log (single-use test and reserved windows, reproduction vs new look, development after the test look, validation looks as trials); **benchmark fit** (beta, tracking error, information ratio; gap split into benchmark-choice and selection effects); **dividend and corporate-action consistency** between adjusted and as-traded prices (dividends not applied, frozen prices after an ex-date, total vs price return); **liquidity participation** (orders vs ADV and day volume, square-root impact as context) and **cost sensitivity** (break-even cost, 1x/2x/3x costs); **stability and concentration** (subperiods, top names and days) and **conditional-rule activation** in vs out of sample |

Full catalogue with references: [docs/CHECKS.md](docs/CHECKS.md) or `lockin-validate explain <check_id>`.

## Two-minute quickstart

```bash
git clone <this repository> && cd lockin-validate
uv sync                                    # Python >= 3.10; runtime deps: numpy, pandas, pyyaml
uv run lockin-validate run examples/quickstart_inputs --out review/
# open review/REPORT.md (also report.json and a static report.html)

uv run lockin-validate init my_strategy/   # template of every input file, with documented headers
uv run lockin-validate explain deflated_sharpe
uv run lockin-validate cases               # benchmark battery: detection rate and false positives per check
```

With pip: `pip install .` (add `.[mcp]` for the MCP server, `.[dev]` for tests). Exit code of `run`: 0 without
confirmed errors, 1 with confirmed errors, 2 usage error.

Python API:

```python
from lockin_validate import audit, run

res = audit("my_strategy/")                 # AuditResult, nothing written
print(res.counts())
res, paths = run("my_strategy/", "review/")  # also writes REPORT.md, report.json, report.html
```

## Example report excerpt

From `examples/quickstart_report/REPORT.md` (the rules declare 25 bps of commission; the trades and the declared
result have none):

> ### 1. The declared result is reproduced only WITHOUT the declared costs (commission) (`omitted_costs`)
>
> Declared: commission 0.0025, slippage 0 of notional. In the trades: commission absent, slippage 0. The declared
> total_return (+0.0461) matches the no-cost scenario (+0.0461) and not the declared-cost one (+0.0265). Consequence
> of the same problem (not a separate finding): with the declared costs applied, the delivered trades leave cash
> negative on 63 dates (minimum -914.14), because they were sized without costs.
>
> | source | fraction | value | scenarios | reproduced_by |
> |---|---|---|---|---|
> | declared commission (rules.yaml) | 0.0025 | - | - | - |
> | turnover (traded notional / initial cash) | - | 7.8484 | - | - |
> | declared total_return | - | 0.046093 | no costs=0.046093; declared costs=0.026472 | no costs |
>
> Suggested action (priority high): Recompute the result with the declared costs and report both.

## Benchmark battery

`cases/` holds 52 synthetic cases, each with an `expected.json` fixed by construction before the tool runs: 11 core
cases (one problem each, plus a clean case and a synthetic "lockin-style" quality-ranking case), 12 adversarial cases
written by an independent reviewer role, 7 statistical cases (best-of-200 noise must fail the deflated Sharpe, a
genuine signal must pass it, autocorrelated returns inflate the naive Sharpe, under-declared trials, short track record,
LLM before its cutoff...), 6 data cases (fundamentals before filing, survivorship, recycled ticker, split not
applied, reference mismatch, clean extended inputs) and 16 lesson cases for the 0.2.0 checks (a planted positive and
a clean negative per family, expectations committed before the checks existed). Current result: 52 of 52 cases with
all expected outcomes, no false positive, and 3 unexpected review items (40 in 0.1.0; see
[docs/ALERT_POLICY.md](docs/ALERT_POLICY.md) and [docs/VALIDATION_EVIDENCE.md](docs/VALIDATION_EVIDENCE.md)). The cases are regenerated deterministically by
`cases/_generators/*.py`, which never import the package.

## Independence of the verification

- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) is the written source of truth for NAV, metrics and statistics.
- `tests/oracle/` is an independent pure-Python implementation of that document (it does not import the package),
  plus a case computed by hand; empyrical-reloaded is used as a third oracle in development only.
- Metamorphic tests (row order, capital scale, price-unit change, untraded asset, extra commission) and an offline
  test that blocks sockets and runs complete cases.

## MCP server (optional)

`pip install ".[mcp]"`, then `lockin-validate-mcp` (stdio). Tools: `run_validation`, `explain_check`, `list_checks`.
For Claude Code: `claude mcp add lockin-validate -- lockin-validate-mcp`. The tools read local files only.

## What it does NOT do

- It does not say whether a strategy is good, will make money or did make money. It is **not investment advice, not
  a certification and not an independent professional approval**; a qualified person must review every report.
- It does not download data, call any API or remote AI, or send telemetry.
- It does not prove that trades happened (that needs broker statements) and it does not detect a wrong price that is
  coherent with everything else unless you provide an independent reference.
- It does not repair data: originals are opened read-only; every derivation is logged as applied or proposed.
- It re-executes only simple rules; it does not run your code. Statistical checks depend on an honest number of
  trials. The LLM checklist is a risk score from declarations, not a memorisation test.

More in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Key references

- Bailey, D. and Lopez de Prado, M. (2012). The Sharpe Ratio Efficient Frontier. *Journal of Risk* 15(2).
- Bailey, D. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio. *Journal of Portfolio Management* 40(5).
- Bailey, D., Borwein, J., Lopez de Prado, M. and Zhu, Q. (2017). The Probability of Backtest Overfitting. *Journal
  of Computational Finance* 20(4).
- Harvey, C. and Liu, Y. (2015). Backtesting. *Journal of Portfolio Management* 42(1).
- Lo, A. (2002). The Statistics of Sharpe Ratios. *Financial Analysts Journal* 58(4).
- Arnott, R., Harvey, C. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. *Journal
  of Financial Data Science* 1(1).
- Board of Governors of the Federal Reserve System (2011). SR 11-7, Guidance on Model Risk Management.
- CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.
- Almgren, R. and Chriss, N. (2001). Optimal Execution of Portfolio Transactions. *Journal of Risk* 3(2).
- Dwork, C. et al. (2015). The Reusable Holdout: Preserving Validity in Adaptive Data Analysis. *Science* 349(6248).
- Sensoy, B. (2009). Performance Evaluation and Self-Designated Benchmark Indexes in the Mutual Fund Industry.
  *Journal of Financial Economics* 92(1).
- Glasserman, P. and Lin, C. (2023). Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment
  Analysis. arXiv:2309.17322.

## License

Apache-2.0 for the whole package (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). Copyright 2026 Joaquín Domínguez and
Mateo Domínguez. A future hosted / web service will be released under AGPL-3.0 in a **separate repository**; this
toolkit stays Apache-2.0.

How to cite: [CITATION.cff](CITATION.cff). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Security and privacy of
inputs: [SECURITY.md](SECURITY.md).
