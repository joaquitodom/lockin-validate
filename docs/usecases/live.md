# Use case `live`: a live track record against the backtest that justified it

**Who it is for.** Portfolio managers who went live (or started paper trading), allocators doing due diligence on a
manager's track record, risk committees. The question is not whether the backtest was honest (that is the core of the
toolkit) but whether the strategy in production behaves like its simulation and whether the edge has decayed.

**Activation.** The module runs when `live_returns.csv` is present (`detect_files`), or when forced with
`lockin-validate run --use-case live` / `audit(folder, use_cases=["live"])`, in which case every check reports
NOT_EXECUTABLE with the missing input.

## Inputs

| File | Columns | Notes |
|---|---|---|
| `live_returns.csv` | `date`, `return` (or `nav`) [`account`, `aum`] | the live or paper record; several accounts are allowed (one row per date and account); they are averaged per date, AUM-weighted when `aum` exists |
| `returns.csv` | `date`, `return` (or `nav`) | the backtest series (core input). It should cover the live dates ("shadow backtest": the production code run over the live period). If it stops when live starts, the comparison is backtest-period vs live-period and the module says so. The core reconstruction already writes this series in `report.json` |
| `live_trades.csv` | `timestamp, ticker, side, quantity, price` [`commission`, `model_price`, `model_timestamp`, `trade_id`] | optional; `model_price` is the price the model assumed, `model_timestamp` when the model wanted to trade |
| `model_trades.csv` | same schema | optional: the trades the model requested, to measure fill ratio and overrides |
| `rules.yaml` | `live: {start, backtest_end, gap_reason, declared_sharpe, declared_annual_return, declared_max_drawdown}` | `declared_*` may also come from `declared_results.json` (`sharpe`, `annual_return`, `max_drawdown`) |

File aliases: `paper_returns.csv` / `track_record.csv` for `live_returns.csv`, `fills.csv` for `live_trades.csv`,
`target_trades.csv` for `model_trades.csv`. Column aliases follow the core (`ret`, `symbol`, `qty`, `fill_price`...),
plus `decision_price` / `arrival_price` for `model_price` and `decision_time` / `order_time` for `model_timestamp`.

The **backtest period** used by the decay, break and declared-vs-realised checks is `returns.csv` up to
`live.backtest_end` (if declared), else before `live.start` (if declared), else the first live date.

## Checks

### `live_period_integrity`

*What.* Live dates vs the declared live start and the review date (`conventions.review_date`, else today);
duplicated (date, account) rows; whether the live series is a copy of the backtest on the overlap (max |live -
backtest| < 1e-12 on 20 or more periods); the length of the overlap with the backtest; the gap between
`live.backtest_end` and `live.start`.

*Statuses.* CONFIRMED_ERROR: live dates before the declared start, dates after the review date, duplicates, or a
live series identical to the backtest (a pasted backtest). NEEDS_REVIEW: overlap shorter than `live_min_periods`
(it says how many), no backtest over the live period, gap after `backtest_end` longer than 1.5 x the median spacing of the series (at least 10 days; 46 days for monthly data) without
`live.gap_reason`, a live series that is an exact affine transform of the backtest (correlation > 0.99999). PASS:
none of the above with a proper shadow backtest. INFO: the overlap description when only review items exist.

*Why.* A record that starts before it was live, reaches into the future or equals the backtest is not a live record;
without a shadow backtest on the same dates every later comparison is period-vs-period.

*Fix.* Deliver the live returns from account statements and the backtest run over the live dates with the production
code; declare `live.start`, `live.backtest_end`, `live.gap_reason`.

*Allows.* Whether the live record can be compared with the backtest at all, and on how many periods. *Does not
allow.* Verifying that the live returns are the ones in the broker statements (GIPS-style third-party verification).

*Refs.* Bacon (2008); GIPS 2020; Dichev and Yu (2011) for the `aum` column (investor vs fund returns).

### `live_vs_shadow_backtest`

*What.* On the common dates: correlation, annualised tracking error `std(live - backtest, ddof 1) x sqrt(P)`, mean
difference with a Newey-West t-statistic (Bartlett kernel, lags `floor(4 (n/100)^(2/9))`), beta of live on backtest,
cumulative return gap (`prod(1 + live) - prod(1 + backtest)`), the date of the largest single-period widening and the
date since which the gap has been open, the share of periods whose sign differs.

*Small samples.* The Newey-West variance is multiplied by `n / (n - lags - 1)` and compared with a Student t(n - 1)
critical value; below 60 periods the plain iid t must reject as well. Monte Carlo of the one-sided 5% test at n = 30
under iid H0: asymptotic HAC 8.6%, this rule 5.0% (AR(1) rho 0.3: 10.2% and 7.8%; the residual excess is the
autocorrelation itself, not the correction). NAV columns with missing values give missing returns for the two
periods around each hole (they are never merged into a multi-period return); the number is disclosed. Returns that look
like percent (median |return| above 0.5, or beta of live on backtest near 100) are NEEDS_REVIEW "units look like percent".

*Statuses.* NEEDS_REVIEW when TE > `live_tracking_error_review`, or the mean difference is significantly negative
(one-sided at `live_alpha`), or correlation < 0.8. PASS for the specific property "no significant systematic
difference" when none of those holds and n >= `live_min_periods`. INFO ("tracks within the declared tolerance") on
a shorter overlap. NOT_EXECUTABLE without `returns.csv` or with fewer than 20 common dates.

*Why.* Live should differ from its simulation only by execution noise and costs. *Fix.* Attribute the gap to
execution (`live_execution_quality`), data feeds, risk limits or overrides. *Allows.* Whether live tracks the
simulation, the size and date of the gap. *Does not allow.* Judging whether the model has an edge.

*Refs.* Grinold and Kahn (2000); Perold (1988); Bacon (2008).

### `live_performance_decay`

*What.* Live annualised Sharpe vs the backtest Sharpe over the backtest period (or the declared one when no
backtest history precedes live): ratio, expected out-of-sample haircut (`live_haircut_expected`, default 0.5: live
Sharpe about half of backtest, Suhonen, Lennkh and Perez 2017; Harvey and Liu 2015), PSR of the live Sharpe against
the backtest Sharpe with the live skewness and kurtosis (Bailey and Lopez de Prado 2012: the probability that a true
Sharpe equal to the backtest one produces a live Sharpe this low is `1 - PSR`), the Minimum Track Record Length to
conclude the live Sharpe exceeds the haircut-adjusted expectation, the Sharpe-difference z-test for independent
samples with Lo's standard errors (Jobson and Korkie 1981; Memmel 2003), annual return and max drawdown side by side.

*Statuses.* NEEDS_REVIEW when the live Sharpe is below the haircut-adjusted expectation AND PSR(live vs backtest)
< `live_alpha`. PASS only when n >= `live_min_periods`, the live Sharpe is above the expectation and PSR(live vs
expectation) >= 1 - `live_alpha`. INFO otherwise, reporting the MinTRL (a short live record never passes).
NOT_EXECUTABLE below 20 live periods or without a backtest reference.

*Why.* Post-publication and post-launch decay are the norm (McLean and Pontiff 2016). *Fix.* Re-estimate expectations
and sizing from the live record. *Allows.* Whether the live record is statistically incompatible with the backtest
Sharpe and how long a record is needed. *Does not allow.* Concluding the edge is intact from a short record.

### `live_structural_break`

*What.* Live returns standardised with the backtest mean and sd, `z_t = (r_t - mean_bt) / sd_bt`; CUSUM
`C_k = sum z_t` with an alarm when `|C_k| / sqrt(k) > h` (`live_cusum_h`, in standard deviations; Page 1954; Brown,
Durbin and Evans 1975), the first crossing date; a Chow-style mean-shift test at the live start (two-sample t with
Newey-West variances); the live rolling `live_rolling_window`-period Sharpe against the backtest's own rolling
distribution (percentile of the live median and of the last value).

*Statuses.* NEEDS_REVIEW when the CUSUM crosses, the shift test rejects at `live_alpha`, or the live median rolling
Sharpe is below the backtest's 10th percentile. INFO otherwise. NOT_EXECUTABLE below 20 live periods or with fewer
than 40 backtest periods before the live start.

*Power note.* The CUSUM at h = 5 detects a shift of `delta` sd per period after about `(h / delta)^2` periods: losing
a backtest Sharpe of 2 a year (0.13 sd a day) takes about 1,500 days to cross; the mean-shift test and the rolling
Sharpe are the powered statistics. Absence of a crossing is not evidence that the edge is intact.

*Refs.* Page (1954); Brown, Durbin and Evans (1975); Chow (1960).

### `live_execution_quality`

*What.* With `live_trades.csv`: signed slippage vs `model_price` in bps (`side x (fill / model - 1) x 1e4`, buy +1,
sell -1; positive = worse) overall and per side with its t-statistic; delay `timestamp - model_timestamp` (median,
95th percentile, count of negative delays); with `model_trades.csv`: fill ratio (model trades with a live match,
matched by `trade_id` when both tables have it, else by ticker, side and date of the model timestamp) and overrides
(live trades the model never requested); commission per notional.

*Statuses.* NEEDS_REVIEW when mean slippage > `live_slippage_review_bps`, fill ratio < 0.9, overrides > 5% of live
trades, or fills dated before the model's request. INFO otherwise. NOT_EXECUTABLE without `live_trades.csv`; without
`model_price` only the delay, fills and commission are measured.

*Refs.* Perold (1988); Almgren and Chriss (2001).

### `live_declared_vs_realised`

*What.* Table declared / backtest series / live for Sharpe, annual return and max drawdown. The backtest-series
values are recomputed with the core metrics module (NAV = cumulative product of 1 + return over the backtest period)
under the declared convention (`declared_results.convention`, else `rules.yaml conventions`); the live values the
same way over the live period.

*Statuses.* CONFIRMED_ERROR when a declared backtest metric differs from the recomputed one beyond the core
tolerances (`sharpe` 0.05, `annual_return` 0.005, `max_drawdown` 0.005; `conventions.tolerances` overrides). NEEDS_REVIEW
when the live max drawdown is already deeper than the declared (else recomputed) backtest max drawdown. INFO
otherwise.

*Refs.* Bacon (2008); Magdon-Ismail and Atiya (2004); GIPS 2020.

## Conventions (rules.yaml `conventions:`) and profiles

| Key | Default | Meaning |
|---|---|---|
| `live_min_periods` | 60 | overlap / live length below which nothing is PASS |
| `live_tracking_error_review` | 0.03 | annualised TE between live and shadow backtest that triggers review |
| `live_alpha` | 0.05 | significance level of the mean-difference, decay and shift tests |
| `live_haircut_expected` | 0.5 | expected ratio live / backtest Sharpe |
| `live_cusum_h` | 5.0 | CUSUM threshold in standard deviations |
| `live_slippage_review_bps` | 10 | mean signed slippage that triggers review |
| `live_rolling_window` | 60 | rolling Sharpe window (periods) |

Profiles: `live_daily` (defaults above), `live_monthly` (`periods_per_year` 12, `live_min_periods` 24,
`live_tracking_error_review` 0.02, `live_rolling_window` 12).

## Cases (`cases/usecase_live/`, generator `cases/_generators/usecase_live_cases.py`)

01 clean tracking (no alert), 02 pasted backtest (integrity CONFIRMED_ERROR), 03 decayed edge (decay and break
NEEDS_REVIEW), 04 tracking gap (shadow NEEDS_REVIEW), 05 marketing number (declared-vs-realised CONFIRMED_ERROR),
06 bad execution (execution NEEDS_REVIEW), 07 short live (no PASS on the statistical checks), 08 no shadow
(integrity NEEDS_REVIEW, shadow NOT_EXECUTABLE), 09 drawdown exceeded (declared-vs-realised NEEDS_REVIEW), 10 two
accounts with AUM (adversarial-legitimate: two rows per date, no alert).

## Limitations

- The live returns are taken as delivered; nothing here verifies them against broker statements.
- Independence between the backtest period and the live period is assumed by the Sharpe-difference test; a shadow
  backtest over the live dates is correlated with live by construction, which is why the decay check compares live
  with the backtest *before* the live start.
- The haircut of 0.5 is a published average, not a property of this strategy.
- Fill matching without `trade_id` is by ticker, side and date; intraday multiple orders on the same name and side
  are matched by count, not by quantity.
- Newey-West lags follow the usual rule of thumb; no bandwidth selection.
