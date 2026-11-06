# Conventions (source of truth)

This document is the specification of what lockin-validate computes. Three things are kept apart:

- **Specification**: this document.
- **Oracles**: `tests/oracle/oracle.py` (pure Python, implements this document without importing the package),
  empyrical-reloaded (external library, development dependency only) and the hand-computed case in
  `tests/oracle/hand_case/`, whose expected values come from the definitions below with exact arithmetic.
- **Code**: `src/lockin_validate/`. If the code and this document disagree, the code is wrong.

## 1. NAV series

1. **Initial point.** The series starts with NAV = declared initial cash (`conventions.initial_cash`, default
   100,000), before any trade. It is dated on the last date of `prices.csv` before the first trade; if there is
   none, the calendar day before the first trade. Rationale: the return of a period is measured against the value
   at the start of the period, and the transaction costs of the period are deducted from the return (Bacon,
   *Practical Portfolio Performance Measurement and Attribution*, 2nd ed., ch. 2; GIPS 2020 provisions on returns
   net of transaction costs). With this base, commissions and the difference between execution price and close on
   the first day are part of the return. **Return base = initial cash.**
2. **Following points.** One per date of `prices.csv` from the first trade to `conventions.end_date` (or the last
   price date). NAV = cash + sum of quantity x last available close at that date.
3. **Trades.** Applied in (timestamp, file line) order. `price` is the EXECUTED price: no slippage is added.
   Commission: the `commission` column if it exists; otherwise zero. The main reconstruction does NOT impute the
   declared costs: it reconstructs what was delivered. Declared costs are contrasted by the `omitted_costs` check, in
   separate scenarios (each a full reconstruction from the initial cash).
4. **Duplicated prices.** For valuation, the first row of the file (logged as an applied transformation).
5. **Missing close.** A position without a close on a date is valued at the last previous close (logged). A position
   with no close at all on or before the date is valued at zero and reported (scope finding).
6. **Leverage and short selling.** With `leverage: false` (default) negative cash is a confirmed error; with
   `short_selling: false` (default) a negative quantity is a confirmed error.

## 2. Metrics

With NAV_0 ... NAV_n (n + 1 points, n returns) and P periods per year (`periods_per_year`, default 252):

| Metric | Definition | Source |
|---|---|---|
| period return | r_t = NAV_t / NAV_{t-1} - 1 (simple) | Bacon, ch. 2 |
| total return | NAV_n / NAV_0 - 1 = NAV_n / initial cash - 1 | idem |
| annual return (geometric) | (1 + total return)^(P / n) - 1 | CFA Institute, annualising compound returns |
| Sharpe (arithmetic) | mean(r_t - rf / P) / sample std (n - 1) of r_t x sqrt(P) | Sharpe (1994); Lo (2002) for sqrt(P) |
| max drawdown | min_t (NAV_t / max_{s<=t} NAV_s - 1), a negative number; a positive declared value is compared in absolute value | Magdon-Ismail and Atiya (2004) |
| number of trades | valid rows of trades.csv | |

Alternatives (260/365/360 periods, population std, risk-free 2/4/5%, log returns, geometric Sharpe, calendar-day
annualisation, drawdown variants) are used only to explain a declared number that does not match the declared
convention. A declared metric reproduced only by an alternative is a CONFIRMED_ERROR when a convention was declared
explicitly (`declared_results.convention`) and NEEDS_REVIEW when none was declared.

Default tolerances (overridable in `conventions.tolerances`): quantity 1e-6 absolute; total and annual return 0.005
absolute; Sharpe 0.05; max drawdown 0.005; number of trades exact; final NAV and curve points 0.005 relative. A
mismatch in total return, final NAV or number of trades is a CONFIRMED_ERROR (something is missing in trades, costs
or initial cash); a mismatch only in Sharpe, annual return or drawdown is NEEDS_REVIEW in `results_reconciliation`
and is resolved by the `metrics` check.

## 3. Calendar and point-in-time

- `conventions.calendar`: `nyse` (hand-written rules, `src/lockin_validate/calendars/nyse.py`), `byma` (weekends
  plus a holiday file; the packaged `data/byma_holidays.csv` covers 2015-2026; sources and the verification status
  of each date are in docs/CALENDAR_BYMA.md) or `none`. A profile may set it; rules.yaml always wins. If nothing declares it, no market
  is presumed: a review item "calendar not declared" is raised, weekend rows are NEEDS_REVIEW and no day is ever a
  confirmed error for not being a session.
- With a full calendar (nyse, byma) coverage gaps are measured against the calendar's sessions; otherwise against
  the session dates present in the file.
- **Availability.** A price row is available from `prices.available_from`. A fundamentals row is available from
  `max(filing_date, available_from)` when both exist, otherwise whichever exists. A signal uses future information
  when the availability of the datum it used (`signals.data_date`, matched to the price date or the fundamentals
  `period_end`, optionally restricted by `data_source`) is later than its `decision_time`.
- `available_from < filing_date` in fundamentals means the data store exposed a value before it was published: a
  confirmed error. A publication lag below 20 days or above 120 days is a review item.

## 4. Statistics

Per-period Sharpe SR = mean / std (ddof 1) of the strategy returns (from the reconstructed NAV when trades and
prices exist; otherwise from `returns.csv`, declared and not verified). g3 = skewness, g4 = kurtosis (raw, normal 3).

| Quantity | Definition | Source |
|---|---|---|
| SE under i.i.d. | sqrt((1 + SR^2 / 2) / T) | Lo (2002) |
| SE with non-normality | sqrt((1 - g3 SR + (g4 - 1) / 4 SR^2) / (T - 1)) | Mertens (2002); Bailey and Lopez de Prado (2012) |
| PSR(SR*) | Phi((SR - SR*) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1) / 4 SR^2)) | Bailey and Lopez de Prado (2012) |
| MinTRL | 1 + (1 - g3 SR + (g4 - 1) / 4 SR^2) (Z_{1-a} / (SR - SR*))^2 | idem |
| E[max SR] of N trials | sqrt(V) ((1 - g) Z^-1(1 - 1/N) + g Z^-1(1 - 1/(N e))), g = 0.5772... | Bailey and Lopez de Prado (2014) |
| DSR | PSR(E[max SR]) | idem |
| Lo factor | eta(q) = q / sqrt(q + 2 sum_{k=1}^{q-1} (q - k) rho_k), q = P, rho_k = 0 beyond `autocorrelation_max_lag` (10) | Lo (2002), eq. 15 |
| Haircut | t = SR sqrt(T), two-sided p, Bonferroni / Holm / BHY over N, back to SR | Harvey and Liu (2015) |
| PBO | CSCV with S = 16 blocks (fewer if T is short), share of partitions where the in-sample best is below the out-of-sample median | Bailey, Borwein, Lopez de Prado and Zhu (2017) |

- N = max(declared `n_trials`, number of configurations in `trials.csv`). V = variance of the Sharpe across the
  trials in `trials.csv`; without a trials log, V = 1/T (sampling variance under a true Sharpe of zero).
- Thresholds (profile defaults, overridable in rules.yaml conventions): PSR >= 0.95, DSR >= 0.95, BHY p <= 0.05,
  PBO < 0.25. Autocorrelation is a review item when the naive annualised Sharpe exceeds the Lo-adjusted one by more
  than 10% and the autocorrelation is significant (Ljung-Box p < 0.05 or |rho_1| > 2.576 / sqrt(T); the
  single-lag band is at 99% so that the OR of the two tests keeps a size close to 5%, docs/ALERT_POLICY.md P5).
- A PSR below its threshold is a review item only when the Sharpe is positive and the MinTRL exceeds
  `significance_review_ratio` (default 2) times the history; otherwise it is an INFO note. With N = 1 trial the
  deflated Sharpe and the multiple-testing adjustment repeat the single-test evidence and are INFO notes
  (docs/ALERT_POLICY.md, P1 and P3).
- Statistics are conditional on the data being correct: when earlier blocks have confirmed errors every statistical
  finding says so.

## 5. Conclusion rule

A check only says PASS if it could verify what it claims. If it does not recognise the declared data, if the test does
not discriminate between hypotheses (for example, with and without costs give the same result within tolerance) or if
it depends only on what the strategy owner declares without being able to contrast it, it says NEEDS_REVIEW or
NOT_EXECUTABLE with the reason, and the title limits the conclusion. INFO (a note that is not an alert) is allowed
instead of NEEDS_REVIEW only under the three rules of docs/ALERT_POLICY.md (evidence judged by another check,
strength-of-evidence note below a documented threshold, nothing declared to contrast); INFO is never PASS. In particular: the LLM look-ahead checklist never
returns PASS; a declared number of trials without a trials log is NEEDS_REVIEW; an empty input folder has no PASS.

## 6. Statuses

| Status | Meaning |
|---|---|
| CONFIRMED_ERROR | the error is proven with the inputs (reproducible evidence) |
| NEEDS_REVIEW | something a person must look at; the inputs are not enough to confirm it |
| NOT_EXECUTABLE | the check could not run; the reason says what is missing |
| INFO | the check ran; a note worth reading that is not an alert (not counted as a review item) |
| PASS | the check ran and found no problem within its scope |

## 7. Use-case module conventions (0.3.0)

Each use-case module (docs/usecases/) declares its defaults in `UseCase.conventions` (module guide:
docs/dev/USECASE_MODULE_GUIDE.md). `register` merges them into the package defaults without overwriting a core key;
`rules.yaml` `conventions:` overrides them (and a review profile fills what rules.yaml does not declare). The report
says where each value came from. The thresholds are review aids chosen by the authors, not regulatory limits unless
a module document says that the number comes from a published rule. Defaults (the module document explains each use):

| Module | Convention (default) |
|---|---|
| signals | `signal_horizons` [1, 5, 21], `signal_quantiles` 5, `signal_min_cross_section` 10, `signal_min_periods` 24, `signal_ic_t_review` 2.0, `signal_turnover_review` 0.5, `signal_lag_sessions` 1 (reads also the core `short_selling` and `rebalance.frequency`) |
| ml | `ml_task` auto, `ml_embargo_days` 0, `ml_psi_review` 0.1, `ml_psi_error` 0.25, `ml_overfit_gap_review` 0.1, `ml_min_test_samples` 200, `ml_calibration_bins` 10, `ml_leak_correlation` 0.95, `ml_calibration_ece_review` 0.05, `ml_calibration_hl_p` 0.01, `ml_label_shift_p` 0.01 |
| risk | `risk_kupiec_alpha` 0.05, `risk_christoffersen_alpha` 0.05, `risk_min_observations` 250, `risk_traffic_light_window` 250, `risk_es_alpha` 0.05, `risk_var_sign` positive_loss (or negative_quantile) |
| forecast | `forecast_alpha` 0.05, `forecast_min_observations` 30, `forecast_naive` random_walk, `forecast_loss` squared, `forecast_bias_alpha` 0.05, `forecast_directional_alpha` 0.05, `forecast_revised_data` false |
| portfolio | `portfolio_weight_sum_tolerance` 0.01, `portfolio_hhi_review` 0.2, `portfolio_turnover_review_annual` 3.0, `portfolio_min_dates` 12, `portfolio_naive_alpha` 0.05, `portfolio_drift_tolerance` 0.02 |
| live | `live_min_periods` 60, `live_tracking_error_review` 0.03, `live_alpha` 0.05, `live_haircut_expected` 0.5, `live_cusum_h` 5.0, `live_slippage_review_bps` 10, `live_rolling_window` 60 |

`rules.yaml` keys read by the modules (all optional; only what is declared is verified):

- `constraints.portfolio` (portfolio): `long_only`, `max_weight`, `min_weight`, `gross_leverage_max`,
  `net_exposure` ([low, high]), `group_limits` ({column: limit} or {column: {GROUP: limit, default: limit}}),
  `cash_ticker`, `rebalance_frequency`, `turnover_max_annual`, `benchmark_weights_file`. A `constraints` block that
  holds these keys directly is also accepted; failing both, the profile's `portfolio_constraints` apply. The `strategy`
  text is read by `portfolio_active_share`.
- `live` (live): `start`, `backtest_end`, `gap_reason`, `declared_sharpe`, `declared_annual_return`,
  `declared_max_drawdown` (the `declared_*` values may also come from `declared_results.json`).
- `risk` (risk): `horizon_days`, `confidence` (context only) and `window` (traffic-light window when
  `risk_traffic_light_window` is not set).
- `forecast` (forecast): `revised_data` (actuals subject to revision).
- `research.n_trials` and `declared_results.json` `n_trials` (ml, `ml_evaluation_protocol`): trials declared for the
  models scored on the test split.

Conclusion rule (section 5) applies unchanged: a module check says PASS only for a property it verified, and a module
forced with `--use-case` on a folder without its tables reports NOT_EXECUTABLE with the missing input.
