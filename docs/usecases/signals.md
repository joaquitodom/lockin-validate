# Use case `signals`: alpha signal research

Validation of a predictive score (a factor, an alpha, a model output) BEFORE it becomes a strategy. The audience is
quant researchers and factor teams who have a cross-sectional (or single-asset) score and want to know whether it
predicts anything, how fast the prediction decays and how much turnover it implies.

Module: `src/lockin_validate/usecases/signals.py`. Activated when `signals.csv` is present (or with
`--use-case signals`). Profile: `signal_research` (no extra conventions; it only labels the review).

## Inputs

| File | Columns | Notes |
|---|---|---|
| `signals.csv` | `decision_time`, `ticker`, `signal` | one row per (decision date, ticker); duplicates keep the first row; `data_date` is used only by the core `signal_data_after_decision` check |
| `prices.csv` | `date`, `ticker`, `close` | the session calendar is the union of price dates; a missing close is carried forward |
| `rules.yaml` (optional) | `conventions.signal_*`, `conventions.short_selling`, `rebalance.frequency` | see the table at the end |

### Alignment convention

A decision dated t (calendar day of `decision_time`) enters at the close of the first price session at or after t,
plus `signal_lag_sessions` sessions (default 1), and exits h sessions later for every h in `signal_horizons`:

    forward return(h) = close(t + lag + h) / close(t + lag) - 1

With the default lag 1 the first forward session is skipped: a score computed at the close of t is traded at the
close of t + 1 and evaluated from there, so no same-close information can leak into the IC. Lag 0 (entry at the
decision session's own close) is only legitimate when the decision is taken at or after that close.

## Checks

### `signal_forward_alignment`

- **What.** Builds the forward returns above and reports the coverage per horizon.
- **Statuses.** CONFIRMED_ERROR when `signal_lag_sessions: 0` is declared and decisions fall on days that are not
  sessions (their entry would be the next session's close, a price not known at the decision). NEEDS_REVIEW when
  more than 20% of the rows have no forward price at the primary horizon (the first of `signal_horizons`). PASS when
  lag >= 1 and every row whose exit falls inside the price history aligns (rows decided too close to the end of the
  prices are counted and excluded from the statistics, not flagged). INFO otherwise (e.g. lag 0 on sessions).
- **Why.** An IC computed on a return that starts at or before the decision measures the timestamp, not the
  forecast; thin coverage biases every statistic below.
- **Fix.** Declare `signal_lag_sessions >= 1` or date the decisions after the close; provide prices for every
  signalled ticker up to the longest horizon.
- **Allows / does not allow.** Stating on which returns the IC and spreads are computed / detecting look-ahead
  inside the signal's own inputs (see `signal_lookahead_hint`).

### `signal_predictive_power`

- **What.** Per decision date, the Spearman rank correlation (information coefficient, IC) between the signal and
  the forward return at each horizon. Reported: mean IC, its standard deviation, hit rate (share of dates with
  IC > 0), the per-date IR (mean / sd) and a t-statistic whose variance uses Newey-West (1987) Bartlett weights with
  L = ceil(h / spacing) - 1 lags (spacing = median sessions between decision dates), so overlapping windows at
  h > 1 do not inflate the t-stat. The table across horizons is the decay profile.
- **Statuses.** NEEDS_REVIEW when |t| < `signal_ic_t_review` (2.0) at the primary horizon, or when the sign of the
  mean IC flips between the primary horizon and another horizon with |t| >= 1. INFO otherwise ("IC significant at
  the declared level"): a predictive signal is a judgement, never PASS. NOT_EXECUTABLE when fewer than
  `signal_min_periods` (24) dates have a cross-section of at least `signal_min_cross_section` (10) names and the
  time-series fallback is not possible either.
- **Time-series fallback.** When the cross-section is too thin on every date (a single asset, a handful of names)
  but there are at least `signal_min_periods` decision dates, the IC is computed through time within each
  ticker's own history: the per-date mean over tickers of the product of the standardised ranks of the signal and
  of the forward return (a rank correlation through time), with the same Newey-West t-stat. The procedure and the
  detail say so, and the finding carries the caution that a single-asset correlation is far noisier and exposed to
  one regime.
- **Thresholds quoted as information.** The 3.0 t-stat hurdle of Harvey, Liu and Zhu (2016) for a new factor is
  stated in the detail (cleared / not cleared); it is not a review threshold.
- **Why.** The IC is the unit of alpha (Grinold and Kahn; Qian, Hua and Sorensen): without a significant and stable
  IC there is nothing to build on; a sign that depends on the horizon is the signature of noise.
- **Fix.** Check alignment and universe; report the decay profile and the number of signals tried; test out of sample.
- **Allows / does not allow.** Whether the ranking predicts forward returns in this sample and at which horizon /
  skill: the IC is before costs, turnover and selection among the signals tried.

### `signal_quantile_spread`

- **What.** On each date with at least max(`signal_min_cross_section`, `signal_quantiles`) names, the signal is sorted
  into `signal_quantiles` (5) buckets by average rank (bucket q = highest signal). Tied values always share a bucket,
  so a graded score with fewer distinct values than `signal_quantiles` (for example ratings 1-5 or a 3-level score)
  fills only some buckets and the finding says how many dates collapsed; tie-breaking by file order is not used because
  it manufactures a spread from the order of the tickers. A signal that is constant on almost every date is
  NOT_EXECUTABLE (the same for `signal_turnover`, whose rank autocorrelation is undefined).
  Mean forward return per bucket at the primary horizon, averaged over dates; top-minus-bottom spread per date with
  its Newey-West t-stat; monotonicity = Spearman between bucket rank and mean return; long-leg share =
  (top - mean of the middle buckets) / spread.
- **Statuses.** NEEDS_REVIEW when the spread t-stat < 2.0, when monotonicity < 0.6, or when the long leg contributes
  less than 25% of a positive spread while `rules.yaml` declares `short_selling: false` (the spread lives in the
  short leg, which a long-only book cannot hold). INFO otherwise with the per-bucket table. NOT_EXECUTABLE without
  `signal_min_periods` dates of sufficient cross-section.
- **Why.** A long-only book captures the long leg only; a spread that is not monotonic or that lives in the bottom
  bucket is not the alpha the IC suggests.
- **Fix.** Report the per-bucket table; design the strategy on the leg it can hold.
- **Allows / does not allow.** Where in the ranking the return difference sits / capturability after costs.

### `signal_turnover`

- **What.** Spearman autocorrelation of the signal between decision dates k apart (k = 1..min(10, dates / 4)),
  averaged over dates (lag profile); one-way turnover of the top bucket = share of the names in the top bucket at
  one date that are not in it at the next; half-life fitted as log rho_k = b k through the origin on the positive
  part of the profile, in decision dates and in sessions (x spacing).
- **Statuses.** NEEDS_REVIEW when the lag-1 autocorrelation is below `signal_turnover_review` (0.5) and the primary
  horizon is longer than the spacing between decision dates (the signal is re-drawn faster than the horizon it is
  evaluated on), or when the half-life in sessions is shorter than the declared rebalance frequency
  (`rebalance.frequency`: daily 1, weekly 5, monthly 21, quarterly 63, annual 252 sessions). INFO otherwise.
  NOT_EXECUTABLE without a cross-section (single asset).
- **Why.** A signal that changes faster than it can be traded cannot deliver its IC after costs; breadth is paid
  in turnover (fundamental law of active management).
- **Fix.** Smooth the signal, shorten the horizon or the rebalance, and cost the implied turnover.
- **Allows / does not allow.** How much trading the signal implies per decision date / the actual cost, which
  depends on sizes and liquidity.

### `signal_lookahead_hint`

- **What.** The "too good to be true" test: the same per-date IC computed against the decision session's own return
  (h = 0, close(t) / close(t - 1) - 1), the previous session's return (h = -1) and the aligned forward return at
  h = 1.
- **Statuses.** NEEDS_REVIEW when |IC(h = 0)| is significant (|t| >= `signal_ic_t_review`) and more than 3 times
  |IC(h = 1)|: "the signal is more related to the contemporaneous return than to the future one: check timestamps".
  INFO otherwise. A significant IC with h = -1 is reported inside the finding as momentum / reversal content
  (legitimate when intended; say so in the signal's definition). NOT_EXECUTABLE without `signal_min_periods` dates.
- **Why.** A score that uses the close of its own decision session looks spectacular at h = 0 and vanishes at h = 1;
  that is the most common timestamp error in signal research.
- **Fix.** Trace how `decision_time` is set and which prices enter the signal; recompute with data strictly before
  the decision.
- **Allows / does not allow.** Flagging a suspicious contemporaneous relation / proving look-ahead: it is a hint,
  and a look-ahead through fundamentals or text does not show here.

## Conventions (rules.yaml `conventions`)

| Key | Default | Meaning |
|---|---|---|
| `signal_horizons` | `[1, 5, 21]` | forward horizons in sessions; the first is the primary horizon |
| `signal_quantiles` | 5 | buckets of the quantile sort |
| `signal_min_cross_section` | 10 | names per date below which the date is skipped (cross-sectional mode) |
| `signal_min_periods` | 24 | decision dates with a usable IC needed to conclude anything |
| `signal_ic_t_review` | 2.0 | review threshold on the primary-horizon IC t-stat (and on the h = 0 IC of the hint) |
| `signal_turnover_review` | 0.5 | lag-1 rank autocorrelation below which turnover is reviewed (with a long horizon) |
| `signal_lag_sessions` | 1 | sessions between the decision session and the entry close (0 = same close) |
| `short_selling` | false | read by `signal_quantile_spread` (core convention) |
| `rebalance.frequency` | - | top-level rules key read by `signal_turnover` |

Fixed thresholds (in the code, documented here): coverage review at 20% of rows without forward price; spread
t-stat 2.0; monotonicity 0.6; long-leg share 25%; look-ahead ratio 3; Harvey-Liu-Zhu hurdle 3.0 quoted as INFO.

## Cases (`cases/usecase_signals/`, generator `cases/_generators/usecase_signals_cases.py`)

| Case | Planted | Expected |
|---|---|---|
| 01_clean_predictive | AR(1) signal (rho 0.9) driving the return two sessions later, IC about 0.08 | alignment PASS; the other four INFO; nothing in NEEDS_REVIEW |
| 02_noise_signal | iid signal, iid returns | predictive_power and quantile_spread NEEDS_REVIEW |
| 03_lookahead_same_close | adversarial: lag 1 is formally right but the score is the decision session's own return | lookahead_hint NEEDS_REVIEW |
| 04_high_turnover | signal re-drawn every session, horizons [21, 42], monthly rebalance | turnover NEEDS_REVIEW |
| 05_short_leg_only | only the bottom quintile earns (negative) returns, `short_selling: false` | quantile_spread NEEDS_REVIEW mentioning the long leg |
| 06_insufficient | 3 decision dates | everything NOT_EXECUTABLE except alignment; predictive_power never PASS |
| 07_single_asset | one ticker, predictive through time | predictive_power INFO or NEEDS_REVIEW in time-series mode; quantile and turnover NOT_EXECUTABLE; nothing raises |
| 08_lag_zero_off_session | `signal_lag_sessions: 0` with Friday decisions dated Saturday | alignment CONFIRMED_ERROR |

The generator asserts each planted property with its own numpy computation before writing `expected.json`.

## Limitations

- Blank signal cells trigger the core `essential_fields` check (CONFIRMED_ERROR: "empty values in `signal`, those rows
  cannot be used"). This is the core data check, not this module: the rows are dropped and the module still runs. If
  a name legitimately has no score on a date, leave the row out of `signals.csv` instead of exporting an empty cell.
- Returns are close-to-close on the price file; no dividends, no costs, no borrow. The spread is before costs.
- The module has no notion of neutralisation: a signal correlated with the market or a sector will show an IC that
  is partly beta; neutralise before submitting if that is the claim.
- The look-ahead hint only sees price-based leakage at the decision session; leakage through fundamentals, news or
  model training is not visible here (see the core `pit_fundamentals` and `llm_lookahead_risk` checks).
- The half-life fit assumes a geometric decay of the rank autocorrelation; a signal with a seasonal profile will be
  summarised poorly (the lag profile is in the evidence).
- Time-series mode (thin cross-sections) is a fallback with much lower power and no cross-sectional diversification
  of the estimate; its result is a hint.

## References

- Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. (information coefficient, fundamental law).
- Qian, E., Hua, R. and Sorensen, E. (2007). Quantitative Equity Portfolio Management (IC, IR, quantile analysis).
- Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation
  Consistent Covariance Matrix. Econometrica 55(3).
- Harvey, C. R., Liu, Y. and Zhu, H. (2016). ... and the Cross-Section of Expected Returns. RFS 29(1) (t-stat
  hurdle 3.0).
- Lopez de Prado, M. (2018). Advances in Financial Machine Learning, ch. 11-12 (backtesting dangers).
- Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio. JPM 40(5) (selection among trials).
