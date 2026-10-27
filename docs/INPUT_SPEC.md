# Input package specification

The review takes ONE folder with fixed file names. **No file is mandatory**: the package runs what it can with what
arrived, and every check that cannot run is reported as NOT_EXECUTABLE with the missing input. The originals are
opened read-only; the report goes to another folder (if the output folder is inside the input folder, the run is
refused). `lockin-validate init <dir>` writes a template of every file below.

Format: CSV in UTF-8, comma separator, ISO 8601 dates (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`), dot decimal, no
thousands separator. Some common column aliases are accepted (`symbol`, `qty`, `adj_close`, `filed`, ...; full list
in `src/lockin_validate/inputs.py`, `ALIASES`); every rename is logged in the transformation log.

## Files

| File | Required columns | Optional columns | Used for |
|---|---|---|---|
| `prices.csv` | `date, ticker, close` | `open, high, low, volume`, `adjusted` (true/false), `available_from` (timestamp the datum became available), `source` | valuation, coverage, OHLC, frozen prices, jumps, look-ahead |
| `signals.csv` | `decision_time, ticker, signal` | `data_date` (date of the datum the signal used), `data_source` (`prices` or `fundamentals`) | rules vs implementation, trade before signal, look-ahead |
| `trades.csv` | `timestamp, ticker, side, quantity, price` | `commission`, `trade_id` | reconstruction, reconciliation, costs |
| `positions.csv` | `date, ticker, quantity` | | positions reconciliation |
| `costs.csv` | `item, value, unit` (`pct`, `bps` or `fraction`) | | declared costs (items containing "slip" are slippage) |
| `fundamentals.csv` | `ticker, period_end` | `filing_date`, `available_from`, any accounting field | point-in-time, look-ahead, identity |
| `universe.csv` | `ticker, start_date` | `end_date` (empty = still a member) | survivorship, membership of buys |
| `security_master.csv` | `ticker, entity_id` | `start_date, end_date` | recycled tickers |
| `corporate_actions.csv` | `ticker, date, ratio` (new shares / old shares) | `type` | declared splits reflected in prices |
| `reference_prices.csv` | `date, ticker, close` | | accuracy against an independent source |
| `returns.csv` | `date` and `return` (or `nav`) | | statistics when there are no trades |
| `trials.csv` | `date` + one column of returns per configuration tried | | deflated Sharpe, haircut, PBO, trials declared |
| `rules.yaml` | see below | | conventions, declared costs, rule to re-execute |
| `declared_results.json` | any of `total_return, annual_return, sharpe, max_drawdown, n_trades, final_nav` | `convention`, `curve` (list of `{date, nav}`), `n_trials` | results reconciliation, metrics, costs, statistics |
| `llm_checklist.json` | `uses_llm` | `model_name, model_training_cutoff, backtest_start, backtest_end, uses_company_names, uses_tickers, uses_explicit_dates, uses_news_or_filings_text, anonymized_entities, retrieval_pit_filtered, pit_model, post_cutoff_evaluation, memorization_probe_done` | LLM look-ahead risk |
| `version.txt` (alias `code_version.txt`) | | | strategy / code version, copied to the report |

`side` accepts buy / sell (and b / s, long / short). A table without its required columns is reported as a schema
error and counts as not delivered for the checks that need it.

## rules.yaml

```yaml
strategy: free text
universe: [AAA, BBB, CCC]          # or "all"
period: {start: 2024-01-02, end: 2024-06-28}
signal: {column: signal, order: desc}
selection: {top_n: 3}
rebalance: {frequency: monthly, timing: first_day}   # monthly | weekly | daily ; first_day | last_day
sizing: equal_weight
costs: {commission_rate: 0.001, slippage_rate: 0.0}  # FRACTIONS of notional, separately
research: {n_trials: 1}            # alternative to declared_results.n_trials
conventions:
  initial_cash: 100000
  valuation: close
  leverage: false
  short_selling: false
  calendar: nyse                   # nyse | byma | none
  holidays_file: holidays.csv      # optional with byma: own (date, reason, note) file in the input folder
  review_date: '2026-10-27'        # limit for "future dates" (default: today)
  start_date: '2024-01-02'         # optional start of the reconstructed NAV (default: first trade)
  end_date: '2024-06-28'           # end of the reconstructed NAV (default: last price)
  periods_per_year: 252
  sharpe: arithmetic               # arithmetic | geometric
  std_ddof: 1
  risk_free_annual: 0.0
  annual_return: geometric         # geometric | arithmetic | calendar
  returns: simple                  # simple | log
  stale_run: 10                    # identical consecutive closes that flag a frozen price
  jump_threshold: 0.40
  autocorrelation_max_lag: 10
  psr_threshold: 0.95
  dsr_threshold: 0.95
  pbo_threshold: 0.25
  rebalance_weight_tolerance: 0.10
  tolerances: {total_return: 0.005, sharpe: 0.05}   # optional, override the defaults
```

## Profiles

`lockin-validate run --profile NAME` fills conventions that rules.yaml does not declare (rules.yaml always wins; the
report says where each value came from): `equities_daily` (default; no calendar presumed), `nyse_equities_daily`,
`byma_equities_daily`, `equities_monthly` (12 periods, frozen run 3, jump 60%), `crypto_daily` (365 periods, calendar
none).

## Required and optional inputs per check

"table(column)" requires that column with at least one value; "a or b" accepts either.

| Check | Required | Optional |
|---|---|---|
| `schema_and_types` | nothing | every table |
| `duplicates` | prices | trades, signals, positions |
| `dates` | prices | trades, signals, positions, rules |
| `essential_fields` | prices | trades, signals, positions |
| `coverage` | prices | trades, rules |
| `trade_before_signal` | trades, signals | |
| `signal_data_after_decision` | signals with `data_date` | |
| `stale_prices` | prices | trades |
| `price_jumps` | prices | corporate_actions |
| `corporate_actions` | prices, corporate_actions | |
| `reference_accuracy` | prices, reference_prices | |
| `pit_fundamentals` | fundamentals | signals |
| `survivorship` | prices, universe (without universe a survivor-only heuristic may still raise a review item) | fundamentals, trades |
| `ticker_identity` | prices, security_master (without it a gap/level-shift heuristic may raise a review item) | fundamentals |
| `reconstruction` | trades, prices | rules |
| `positions_reconciliation` | trades, prices, positions | |
| `results_reconciliation` | trades, prices, declared_results | rules |
| `lookahead` | signals with `data_date` + prices(`available_from`) or fundamentals(`available_from` or `filing_date`) | (the rank-correlation hint runs with signals and prices alone) |
| `omitted_costs` | trades, prices | rules, costs, declared_results |
| `metrics` | trades, prices, declared_results | rules |
| `rules_vs_implementation` | rules (top_n, rebalance, sizing), signals, trades, prices | |
| `sharpe_significance` | trades and prices, or returns | rules |
| `sharpe_autocorrelation` | trades and prices, or returns | rules |
| `trials_declared` | declared_results(n_trials) or trials | returns |
| `deflated_sharpe` | a return series + declared_results(n_trials) or trials | |
| `multiple_testing` | a return series + declared_results(n_trials) or trials | |
| `pbo` | trials with at least 2 configurations | |
| `llm_lookahead_risk` | llm_checklist | returns |

The same table is in code (`src/lockin_validate/inputs.py`, `REQUIREMENTS`) and travels in the JSON report
(`scope.requirements_per_check`).

## Statuses

CONFIRMED_ERROR (proven with the inputs), NEEDS_REVIEW (a person must look at it), NOT_EXECUTABLE (with the reason),
PASS (within the scope of the check). See docs/CONVENTIONS.md, sections 5 and 6.
