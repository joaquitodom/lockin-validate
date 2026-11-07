# Use case `portfolio`: portfolio construction and asset allocation from target weights

## Who it is for

Portfolio managers, allocators, investment committees and compliance teams that receive a table of target
weights over time and must decide whether to trust it: the output of a mean-variance or risk-parity optimiser,
a Black-Litterman allocation, the model portfolios of an advisor or a robo-advisor, an index tracker, the model
portfolio of a fund (FCI). The core of `lockin-validate` validates a trading strategy from its trades; this module
validates an allocation from its weights, which is the object those models actually deliver.

It is activated when `weights.csv` is in the package (or with `--use-case portfolio`).

## Inputs

| File | Columns | Notes |
|---|---|---|
| `weights.csv` (required) | `date, ticker, weight` | weight = fraction of NAV, negative = short. Optional `portfolio` (several portfolios in one file: each is validated separately), `asset_class`, `sector` (or `group`, `industry`, `country`). Aliases: ticker -> symbol / asset / instrument; weight -> w / target_weight / allocation; date -> datetime / timestamp / as_of / rebalance_date. |
| `prices.csv` (optional) | `date, ticker, close` | enables the drift correction of the turnover, the comparison with 1/N, the reconciliation with positions and the tracking error. |
| `positions.csv` (optional) | `date, ticker, quantity` | what was actually held; with prices gives the implied weights. |
| `benchmark_weights.csv` (optional) | `date, ticker, weight` | composition of the benchmark (as-of: the latest benchmark date on or before each weights date is used). |
| `benchmark_returns.csv` (optional) | `date, return` or `nav` | benchmark series for the return comparison. |
| `rules.yaml` (optional) | `strategy` text and a `constraints.portfolio` block | see below. |

Declared constraints (all optional; only what is declared is verified):

```yaml
strategy: Long-only quality-tilt model portfolio rebalanced monthly
constraints:
  portfolio:
    long_only: true
    max_weight: 0.10
    min_weight: 0.0
    gross_leverage_max: 1.0
    net_exposure: [0.95, 1.05]
    group_limits: {sector: 0.30}      # or {sector: {TECH: 0.25, default: 0.30}}
    cash_ticker: CASH
    rebalance_frequency: monthly      # daily, weekly, monthly, quarterly, semiannual, annual
    turnover_max_annual: 2.0
    benchmark_weights_file: null      # informative; the file is benchmark_weights.csv
```

The profile `portfolio_long_only_monthly` presumes `long_only: true` and `rebalance_frequency: monthly` when
rules.yaml declares nothing; `portfolio_risk_parity` presumes nothing (declare `gross_leverage_max`).

## Checks

### `portfolio_constraints`: declared constraints hold on every date

- **What.** On each weights date: sum of weights within `1 +/- portfolio_weight_sum_tolerance` under `long_only`
  with no cash ticker (at most 1 when a cash ticker is declared: the remainder is cash); net exposure within the
  declared `net_exposure` range; no negative weight under `long_only`; no weight above `max_weight` (cash excluded);
  held weights not below `min_weight`; gross leverage `sum |w|` within `gross_leverage_max`; exposure per group within
  `group_limits` (needs the classification column in weights.csv).
- **Statuses.** CONFIRMED_ERROR on any breach, with the date, ticker, value and limit of every breaching row. INFO
  with the observed ranges (sum, gross, min, max, dates with a short) when nothing is declared; NEEDS_REVIEW when,
  with nothing declared, the sum of weights is neither 1 (fully invested) nor 0 (market neutral) on some dates, the
  usual symptom of a missing cash row. NEEDS_REVIEW when a declared group limit cannot be verified (column missing):
  never PASS on a declaration that could not be contrasted. PASS when every declared constraint holds on every date.
- **Why.** A weight table that contradicts its own mandate is a bug in the optimiser or the export, or a false
  declaration; both invalidate the backtest of the allocation.
- **Fix.** Fix the constraint handling or the export (cash row, rounding, group mapping) or correct rules.yaml.
- **Allows.** Whether the delivered weights respect what was declared, date by date. **Does not allow.** Judging
  whether the constraints are sensible, or constraints that were not declared.
- **Refs.** UCITS Directive 2009/65/EC art. 52; Grinold and Kahn (2000).

### `portfolio_concentration`: HHI, effective N, top-5, largest name, groups

- **What.** Per date: Herfindahl index of the absolute weights normalised by the gross (`sum (|w| / sum|w|)^2`),
  effective number of positions `1 / HHI`, top-5 share, largest single weight, largest exposure per classification
  column; summary over time (median and worst date). Cash is excluded when a cash ticker is declared or a ticker
  named CASH exists.
- **Statuses.** NEEDS_REVIEW when the worst-date HHI exceeds `portfolio_hhi_review` (0.20 = effective 5 names) or a
  single name exceeds 25% without a declared `max_weight` that allows it; INFO otherwise. A separate INFO when the
  portfolio would breach the UCITS 5/10/40 rule (no issuer above 10%, positions above 5% adding to at most 40%):
  the rule applies only to UCITS funds and is shown because it is the most common declared concentration limit.
- **Why.** Estimation error in optimisers concentrates weights in the assets whose inputs were most over-estimated
  (Chopra and Ziemba 1993; Michaud 1989); the out-of-sample cost often exceeds the gain over 1/N (DeMiguel, Garlappi
  and Uppal 2009).
- **Fix.** Declare and enforce position and group caps; use shrinkage or resampling in the optimiser.
- **Allows.** How concentrated the weights are and when. **Does not allow.** Whether the concentration was rewarded
  (that is `portfolio_vs_naive`).

### `portfolio_turnover`: trading net of drift, rebalance schedule

- **What.** One-way turnover between consecutive weight dates `0.5 x sum |w_t - drift(w_{t-1})|`. With prices.csv
  the previous weights are drifted by the price ratios (`w r / (1 + sum w (r - 1))`, cash at zero return), so a
  buy-and-hold book reported at market value shows zero turnover; without prices the raw difference is used and the
  finding says that drift could not be removed. Annualised turnover = total / years of span; trade dates per year;
  share of intervals with no trade (turnover below 0.001). Under a declared `rebalance_frequency`, a change is a
  rebalance when it is the first in its period (calendar month, ISO week, quarter...). A "change outside the
  schedule" needs the **delivered target weights** to differ from the previous row (raw difference above 0.001) and a
  trade net of drift above 1%; the same target printed every month under a quarterly schedule is not a change (its
  drift-adjusted turnover stays the cost measure and the finding says so).
- **Statuses.** NEEDS_REVIEW when the annual turnover exceeds the declared `turnover_max_annual` or
  `portfolio_turnover_review_annual` (3.0), when the number of dates with a changed target and a trade per year exceeds 1.5 x the declared frequency, or
  when (without prices) weights change on non-rebalance dates. CONFIRMED_ERROR only when prices are present, drift
  has been removed and weights still change by more than 1% on dates outside the declared schedule. INFO otherwise.
  NOT_EXECUTABLE with fewer than 2 weight dates.
- **Why.** The paper result of a weight path carries no costs; turnover is what the costs will be charged on, and a
  path that trades more often than declared is not the declared model.
- **Fix.** Align the declared frequency with the model, or export only rebalance dates; provide prices so drift can
  be separated from trading.
- **Allows.** How much the path trades, net of drift, and whether it matches the declared schedule. **Does not
  allow.** The cost of that turnover (costs are not an input of this use case).

### `portfolio_weights_vs_positions`: were the declared weights what was held?

- **What.** With positions.csv and prices.csv: implied weight = `quantity x close / sum |quantity x close|` on each
  positions date (last close on or before the date); declared weights normalised by their gross, cash excluded;
  compared on the same date or the next positions date within 7 days (one session of execution lag), keeping the
  closer of the two; max and mean absolute difference per date; share of ticker-dates differing by more than
  `portfolio_drift_tolerance` (0.02).
- **Statuses.** CONFIRMED_ERROR when more than 10% of the ticker-dates differ; PASS when they agree;
  NOT_EXECUTABLE without positions or prices, or without a positions date within 7 days of a weights date.
- **Why.** A track record belongs to the book that was held, not to the weights a model printed.
- **Fix.** Reconcile target weights with executed positions (cash, lot rounding, unexecuted orders); confirm both
  files describe the same portfolio.
- **Allows.** Whether the positions implement the declared weights. **Does not allow.** Why they differ.

### `portfolio_vs_naive`: did the construction add value over 1/N?

- **What.** Realised return of the weight path with prices.csv: weights dated d enter at the close of the first
  session after d (no look-ahead), drift until the next rebalance, no costs, uninvested remainder in cash at zero.
  Compared with the equal-weight portfolio of the same names on the same dates (1/N, long) and, if
  benchmark_returns.csv exists, with the benchmark: annualised return, volatility, Sharpe, max drawdown, tracking
  error. The Sharpe difference is tested with the Jobson-Korkie (1981) statistic with the Memmel (2003) correction,
  `z = (SR1 - SR2) / sqrt((2 (1 - rho) + 0.5 (SR1^2 + SR2^2) - SR1 SR2 rho^2) / T)`, one-sided H1: model > 1/N.
  Periods per year inferred from the spacing of the price dates. With prices at a coarser frequency than the model
  (e.g. month-end prices) "the first session after d" is the next price date, i.e. a full period of delay: the first
  model return is earned one period later. Books whose mean net exposure is at most 0.1 (short-only, market-neutral)
  are not compared with the long-only 1/N (NOT_EXECUTABLE with the reason): use `benchmark_returns.csv`.
- **Statuses.** NEEDS_REVIEW when the model does not beat 1/N at `portfolio_naive_alpha` (0.05): the finding says
  explicitly that this is common and not an error (DeMiguel, Garlappi and Uppal 2009), but that the construction
  added no measurable value on this sample. INFO when it does. NOT_EXECUTABLE without prices, with fewer than
  `portfolio_min_dates` (12) weight dates, or with no priced name.
- **Why.** 1/N is the mandatory comparator of any allocation model: with estimation error it is hard to beat out of
  sample, so a model that does not beat it adds complexity, turnover and concentration without measurable value.
- **Fix.** Report 1/N alongside the model; consider shrinkage, constraints or a longer sample before claiming value.
- **Allows.** Whether the construction added value over the naive rule on this sample, with a test. **Does not
  allow.** That failing to beat 1/N is an error; robustness under heavy tails and autocorrelation. Ledoit and Wolf
  (2008) is the preferred robust test (studentised circular block bootstrap); it needs a bootstrap and is not
  implemented here, so the p-value is the asymptotic normal one.

### `portfolio_active_share`: closet indexing

- **What.** With benchmark_weights.csv: active share `0.5 x sum |w - w_b|` per weights date over the union of names
  (cash excluded from w; benchmark weights as of the latest benchmark date on or before the weights date); share of
  held names with zero benchmark weight; tracking error of the simulated model path minus the simulated
  benchmark-weights path when prices exist.
- **Statuses.** INFO with the numbers. NEEDS_REVIEW when the rules.yaml `strategy` text (or `description`,
  `mandate`, `objective`) says active / alpha / stock picking / conviction and the median active share is below
  0.20 (closet indexing, Cremers and Petajisto 2009), or says index / tracker / passive / replication and it is above
  0.20. When the text has both kinds of words no contrast is made. NOT_EXECUTABLE without benchmark weights.
- **Why.** Fees and narrative follow the declared style; the weights show the real one.
- **Fix.** Confirm the mandate and the benchmark composition file; document the sources of active risk.
- **Allows.** How far the weights depart from the benchmark composition. **Does not allow.** Whether the active
  positions were skilful.

## Conventions and thresholds (rules.yaml `conventions`)

| Key | Default | Used by |
|---|---|---|
| `portfolio_weight_sum_tolerance` | 0.01 | sum / gross / net checks in `portfolio_constraints` |
| `portfolio_hhi_review` | 0.20 | `portfolio_concentration` (effective N 5) |
| `portfolio_turnover_review_annual` | 3.0 | `portfolio_turnover` when no `turnover_max_annual` is declared |
| `portfolio_min_dates` | 12 | minimum weight dates for `portfolio_vs_naive` |
| `portfolio_naive_alpha` | 0.05 | one-sided significance level of the Sharpe difference |
| `portfolio_drift_tolerance` | 0.02 | `portfolio_weights_vs_positions` |

Fixed constants (documented in the procedure of each finding): per-name limits are compared with a tolerance of
1e-6; a date "trades" when the one-way turnover exceeds 0.001; a change outside the declared schedule is a confirmed
error above 0.01.

## Cases (`cases/usecase_portfolio/`, generator `cases/_generators/usecase_portfolio_cases.py`)

| Case | Planted | Expected |
|---|---|---|
| 01_clean_long_only | all declared constraints satisfied; tilt towards the higher-drift names | constraints PASS, concentration / turnover / vs_naive INFO, no alert |
| 02_weights_dont_sum | sum 0.92 on 3 dates, no cash, long_only | constraints CONFIRMED_ERROR |
| 03_max_weight_breach | one name at 14% with max_weight 0.10 | constraints CONFIRMED_ERROR |
| 04_group_limit | TECH 38% with sector limit 0.30 | constraints CONFIRMED_ERROR |
| 05_concentrated | 3 names hold 90% | concentration NEEDS_REVIEW (+ UCITS INFO) |
| 06_churn | weekly re-randomised weights under declared monthly, prices present | turnover CONFIRMED_ERROR (NEEDS_REVIEW without prices) |
| 07_positions_mismatch | positions carry other names' weights | weights_vs_positions CONFIRMED_ERROR |
| 08_optimizer_vs_1n | mean-variance from 60-day noisy estimates, no true difference between names | vs_naive NEEDS_REVIEW |
| 09_closet_index | "active alpha" text, active share 0.08 | active_share NEEDS_REVIEW |
| 10_insufficient | 4 weight dates | vs_naive NOT_EXECUTABLE, never PASS |
| 11_drift_not_trading | buy-and-hold weights reported at market value monthly (adversarial) | turnover INFO, never an alert |

The generator asserts, with its own numpy computation, that the draw of case 01 beats 1/N (p < 0.01) and that the
draw of case 08 does not (p >= 0.05) before writing the expectation.

## Limitations

- Weights are taken as fractions of NAV; a file in notional or in percent (sum 100) is reported as a sum far from 1
  (review when nothing is declared, error under long_only), not silently rescaled.
- The simulation of the weight path has no costs, no borrow cost for shorts and cash at zero; a name without a price
  on a date keeps its last price, a name never priced is dropped (listed in the finding).
- The Sharpe-difference test assumes i.i.d. returns (asymptotic normal); heavy tails and autocorrelation widen the
  true confidence band (Ledoit and Wolf 2008 not implemented).
- Group limits are checked on the net exposure per group with the classification given in weights.csv; a group
  mapping that changes over time is honoured row by row (forward-filled per ticker).
- The rebalance schedule uses calendar periods (month, ISO week, quarter): a monthly model that rebalances twice in
  one calendar month because of a holiday shift is counted as a change outside the schedule.
- Duplicate (date, ticker) rows are summed.

## References

- DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is the 1/N
  Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953.
- Chopra, V. K. and Ziemba, W. T. (1993). The Effect of Errors in Means, Variances, and Covariances on Optimal
  Portfolio Choice. Journal of Portfolio Management 19(2), 6-11.
- Michaud, R. O. (1989). The Markowitz Optimization Enigma: Is 'Optimized' Optimal? Financial Analysts Journal 45(1).
- Jobson, J. D. and Korkie, B. M. (1981). Performance Hypothesis Testing with the Sharpe and Treynor Measures.
  Journal of Finance 36(4), 889-908.
- Memmel, C. (2003). Performance Hypothesis Testing with the Sharpe Ratio. Finance Letters 1, 21-23.
- Ledoit, O. and Wolf, M. (2008). Robust Performance Hypothesis Testing with the Sharpe Ratio. Journal of Empirical
  Finance 15(5), 850-859.
- Cremers, K. J. M. and Petajisto, A. (2009). How Active Is Your Fund Manager? Review of Financial Studies 22(9).
- Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.
- European Parliament and Council (2009). Directive 2009/65/EC (UCITS), art. 52.
- Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.
