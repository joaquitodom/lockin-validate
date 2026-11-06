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
| `benchmark_returns.csv` (0.2.0) | `date` and `return` (or `nav` / `close`) | | benchmark_fit (declared benchmark), cost_sensitivity (hurdle) |
| `universe_returns.csv` (0.2.0) | `date` and `return` (or `nav` / `close`) | | benchmark_fit (equal-weight universe; otherwise computed from prices + membership) |
| `unadjusted_prices.csv` (0.2.0) | `date, ticker, close` (as traded) | `volume` | dividend_corporate_actions |
| `dividends.csv` (0.2.0) | `ticker, ex_date, amount` (cash per share) | `pay_date` | dividend_corporate_actions |
| `run_log.csv` (0.2.0) | `timestamp, window_start, window_end, config_hash, purpose` (`train`, `validation`, `test`, `reproduction`, `diagnostic`) | `run_id` | protocol_integrity; validation looks feed the number of trials |
| `regimes.csv` (0.2.0) | `date` + one column per conditional rule (1 / true = active) | | conditional_rule_activation |
| `protocol.yaml` (0.2.0) | `train`, `validation`, `test` windows (`start`, `end`; `test.single_use` default true) | `reserved`: list of `{name, start, end, single_use}` | protocol_integrity; the test start is the out-of-sample start of conditional_rule_activation |

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
# 0.2.0 (all optional)
benchmark: {name: IDX, weighting: cap_weighted, strategy_weighting: equal_weighted}  # strategy_weighting defaults to sizing
required_inputs: [roe, debt_to_equity]  # inputs each scored name needs (signals.csv columns or fundamentals.csv as of)
min_input_share: 0.8               # declared minimum: below it is a CONFIRMED_ERROR (default 0.5 -> NEEDS_REVIEW)
conditional_rules:                 # regimes.csv columns (default: every column of regimes.csv)
  - {name: inverted_curve_bond_rule, column: inverted_curve}
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
  # 0.2.0 thresholds (defaults shown)
  significance_review_ratio: 2.0   # PSR review only when MinTRL > ratio x history (else INFO)
  coverage_drop: 0.10              # coverage drop vs the median of previous periods
  adjustment_tolerance: 0.001      # adjusted / as-traded ratio step tolerance
  stale_after_event: 3             # identical adjusted closes from an ex-date that flag a frozen price
  adv_window: 20                   # sessions in the average daily volume
  max_participation: 0.10          # participation (quantity / ADV) above which a trade is reviewed
  impact_coefficient: 1.0          # Y of the square-root impact estimate (context only)
  oos_start: '2022-01-01'          # out-of-sample start when protocol.yaml has no test window
  regime_rare_in_sample: 0.10
  regime_dominant_out_of_sample: 0.50
  # 0.2.1
  max_input_age_days: 400          # as-of fundamentals older than this (from period_end) count as missing
  min_volume_coverage: 0.90        # share of traded notional with volume needed for a liquidity PASS
  benchmark_universe_tracking_error: 0.01  # declared equal-weighted benchmark vs computed equal-weight universe
```

`volume` (prices.csv) must be the consolidated daily volume in shares. `required_inputs` are matched
case-insensitively (headers are lower-cased on reading). `run_log.csv` purposes accept synonyms (holdout, oos,
out_of_sample, final_test -> test; repro, rerun -> reproduction; val, cv -> validation; training, fit -> train; diag,
analysis -> diagnostic); any other purpose is reported as unrecognised.

`declared_results.json` may also carry `return_basis: total | price` (0.2.0), contrasted with the dividends held
over ex-dates by dividend_corporate_actions.

## Profiles

`lockin-validate run --profile NAME` fills conventions that rules.yaml does not declare (rules.yaml always wins; the
report says where each value came from): `equities_daily` (default; no calendar presumed), `nyse_equities_daily`,
`byma_equities_daily`, `equities_monthly` (12 periods, frozen run 3, jump 60%), `crypto_daily` (365 periods, calendar
none). The use-case modules add their own profiles (0.3.0): `signal_research`, `ml_classification`, `ml_regression`,
`risk_var_daily`, `risk_var_fund`, `forecast_returns`, `forecast_macro`, `portfolio_long_only_monthly`,
`portfolio_risk_parity`, `live_daily`, `live_monthly`.

## Use-case module tables

Version 0.3.0 adds six optional use-case modules (docs/usecases/). Each module is activated when one of its detect
tables is present in the folder (or forced with `--use-case NAME`); a core-only folder is not affected. The tables
below are declared by the modules themselves (`lockin_validate.usecases`), so `lockin-validate init` scaffolds them
and `lockin-validate usecases` lists them. Column aliases, date formats and extra columns are described in each
module document.

| Module | Table | File | Required columns | Optional columns |
|---|---|---|---|---|
| [signals](usecases/signals.md) | signals (detect) | `signals.csv` | decision_time, ticker, signal | data_date, data_source |
| | prices (shared with the core) | `prices.csv` | date, ticker, close | |
| [ml](usecases/ml.md) | ml_samples (detect) | `ml_samples.csv` | sample_id, timestamp, split | label_end, ticker, fold |
| | ml_predictions (detect) | `ml_predictions.csv` | sample_id, prediction, actual | probability, model, fold |
| | ml_features | `ml_features.csv` | feature | available_from_lag_days, source, importance |
| | ml_feature_values | `ml_feature_values.csv` | sample_id, feature, value | |
| [risk](usecases/risk.md) | var_forecasts (detect) | `var_forecasts.csv` | date, pnl | model, portfolio (plus at least one `var_<level>` column such as `var_99`, and optionally `es_<level>`) |
| [forecast](usecases/forecast.md) | forecasts (detect) | `forecasts.csv` | origin_date, target_date, forecast, actual | model, series, horizon, actual_available_from, naive |
| [portfolio](usecases/portfolio.md) | weights (detect) | `weights.csv` | date, ticker, weight | portfolio, asset_class, sector, group, industry, country |
| | benchmark_weights | `benchmark_weights.csv` | date, ticker, weight | portfolio |
| | positions, prices (shared with the core) | `positions.csv`, `prices.csv` | date, ticker, quantity; date, ticker, close | |
| [live](usecases/live.md) | live_returns (detect) | `live_returns.csv` | date | return, nav, account, aum (one of return or nav is needed) |
| | live_trades | `live_trades.csv` | timestamp, ticker, side, quantity, price | commission, model_price, model_timestamp, trade_id |
| | model_trades | `model_trades.csv` | timestamp, ticker, side, quantity, price | commission, model_price, model_timestamp, trade_id |
| | returns (shared with the core; the shadow backtest) | `returns.csv` | date, return (or nav) | |

The `rules.yaml` blocks the modules read (`constraints.portfolio`, `live`, `risk`, `forecast`) are listed in
docs/CONVENTIONS.md, section 7. The required and optional inputs of each new check are in docs/CHECKS.md.

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
| `coverage_drift` | fundamentals or signals | universe, rules(universe), rules(required_inputs) |
| `input_sufficiency` | rules(required_inputs), signals | fundamentals, rules(min_input_share) |
| `dividend_corporate_actions` | prices, unadjusted_prices or dividends | corporate_actions, trades, declared_results(return_basis) |
| `protocol_integrity` | run_log, protocol | declared_results(n_trials), rules(research.n_trials) |
| `benchmark_fit` | trades and prices, or returns, benchmark_returns | universe_returns, universe, prices, rules(benchmark), rules(sizing) |
| `liquidity_participation` | trades, prices(volume) | rules |
| `cost_sensitivity` | trades, prices | rules, costs, benchmark_returns |
| `stability_and_concentration` | trades and prices, or returns | rules |
| `conditional_rule_activation` | regimes, protocol(test) or rules(conventions.oos_start) | rules(conditional_rules) |

The same table is in code (`src/lockin_validate/inputs.py`, `REQUIREMENTS`) and travels in the JSON report
(`scope.requirements_per_check`).

Every input of the 0.2.0 checks is optional: without it the check is NOT_EXECUTABLE and the reason names the missing
input; the rest of the review runs as before.

## Statuses

CONFIRMED_ERROR (proven with the inputs), NEEDS_REVIEW (a person must look at it), NOT_EXECUTABLE (with the reason),
INFO (a note that is not an alert, docs/ALERT_POLICY.md), PASS (within the scope of the check). See docs/CONVENTIONS.md, sections 5 and 6.
