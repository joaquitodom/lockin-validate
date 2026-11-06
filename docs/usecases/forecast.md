# Use case `forecast`: point forecasts of a financial or economic series

Module `src/lockin_validate/usecases/forecast.py`. Activated by `forecasts.csv` (or with `--use-case forecast`).

**Who it is for.** Economists, strategists, treasury and FP&A teams and time-series modellers who publish or consume
point forecasts of returns, volatility, inflation, rates, FX, earnings, cash flows or demand, and the people who
review their track record. The questions it answers are the ones a reviewer asks before trusting a forecast: were
the forecasts really made before the fact, do they beat a naive benchmark, are they biased, do they get the
direction right, is there information left in their own errors, and how much of the best model's edge is selection.

## Input: `forecasts.csv`

One row per (model, series, origin, target).

| Column | Required | Meaning | Aliases |
|---|---|---|---|
| `origin_date` | yes | when the forecast was made | origin, forecast_date, issued, as_of |
| `target_date` | yes | the period the forecast is for | target, date, period |
| `forecast` | yes | the point forecast | prediction, yhat, fcst |
| `actual` | yes | the realised value | realized, realised, y, observed |
| `model` | no | model name (several models allowed) | |
| `series` | no | series name (several series allowed) | |
| `horizon` | no | horizon **in periods of the series** (1 = one step ahead); if absent it is computed as target - origin in days and converted to steps with the median spacing of the series' target dates | |
| `actual_available_from` | no | when the realised value was published (real-time / revised macro data) | available_from, published, release_date |
| `naive` | no | the benchmark forecast; if absent it is built from the conventions below | |

Rows without origin, target, forecast or actual are dropped. Dates are ISO 8601, decimals use a dot.

`rules.yaml` (optional): `forecast: {revised_data: true}` declares that the actuals are subject to revisions;
`conventions:` overrides the thresholds below.

## Naive benchmark

`conventions.forecast_naive`:

- `random_walk` (default): the last actual of the series whose `target_date <= origin_date` **and**, when
  `actual_available_from` exists, whose publication date is `<= origin_date`. The history is taken from the `actual`
  column of the same series (all models pooled).
- `mean`: the expanding mean of the actuals known at the origin (the historical-mean benchmark of Goyal and Welch
  2008).
- `zero`: 0. The right benchmark for return forecasts (profile `forecast_returns`).

A supplied `naive` column is used as given and contrasted with the publication-aware random walk (see
`forecast_origin_integrity`). Rows whose naive cannot be built (no earlier actual) are excluded from the comparisons.

## Checks

### `forecast_origin_integrity`

**What.** CONFIRMED_ERROR when (a) `target_date < origin_date` (forecasting the past), (b) `actual_available_from <
target_date` (a value published before the period it measures), (c) a supplied `naive` equals the last actual by
target date although that value was not yet published at the origin (the benchmark used unpublished information),
(d) the same (model, series, origin, target) carries different forecasts. NEEDS_REVIEW when the data are declared
as revised (`rules.yaml forecast.revised_data` or profile `forecast_macro`) without `actual_available_from`, and when
horizons are mixed (max / min of target - origin > 1.5 within a model and series) without a `horizon` column. INFO
with the horizon distribution per model. PASS when all of the above were verified.
**Why.** A forecast scored against information that did not exist at its origin, or against a final vintage instead
of the real-time value, overstates skill (Croushore and Stark 2001).
**Fix.** Fix the dates; add `actual_available_from` and a `horizon` column; rebuild the naive from values published at
each origin; keep one forecast per key.
**Allows.** That the forecasts and the benchmark respect the information available at each origin.
**Does not allow.** Detecting revisions when no publication dates are provided (the PASS says "not contrasted").

### `forecast_vs_naive`

**What.** Per (model, series, horizon h): RMSE, MAE, Theil's U = RMSE / RMSE of the naive, and the Diebold-Mariano
(1995) test of equal predictive accuracy on the loss differential d = L(model) - L(naive) (`forecast_loss`: squared
or absolute), with a Newey-West long-run variance (Bartlett weights, h - 1 lags) and the Harvey-Leybourne-Newbold
(1997) small-sample correction DM* = DM x sqrt((T + 1 - 2h + h(h - 1) / T) / T), compared with a Student t with
T - 1 degrees of freedom. The one-sided p-value is for "the model is better".
**Status.** NEEDS_REVIEW when the model does not beat the naive at `forecast_alpha` (U >= 1 or DM p >= alpha; the
finding says which). INFO when it does ("beats the naive at the declared level"): beating a naive is a judgement
about the benchmark chosen, never PASS. NOT_EXECUTABLE below `forecast_min_observations`.
**Why.** Many published forecasts do not beat the random walk or the historical mean; the naive is the minimum bar.
**Fix.** Report the naive and the DM p-value next to the model; choose the naive that fits the series.
**Allows.** Whether the model beats the chosen naive at the declared level.
**Does not allow.** That the model is useful for decisions, or the comparison with other naives.

### `forecast_bias`

**What.** Mincer-Zarnowitz (1969) regression actual = a + b forecast + e per (model, series, h); joint Wald test of
(a, b) = (0, 1) with a Newey-West covariance (Bartlett, h - 1 lags) and p = exp(-W / 2) (chi-square with 2 df); the
mean error with its HAC t-statistic and the sign of the bias (over- or under-forecasting).
**Status.** NEEDS_REVIEW when the Wald p < `forecast_bias_alpha` or |t(mean error)| > 2; INFO otherwise.
**Why.** A biased or inefficient forecast can be improved by a linear correction; a systematic sign distorts the
decisions that use it.
**Fix.** Recalibrate (a + b forecast) on a separate sample and re-test; find the source of the systematic error.
**Allows.** Systematic bias or inefficiency. **Does not allow.** Why the bias exists.

### `forecast_directional`

**What.** Pesaran-Timmermann (1992) test. Direction = sign of the change relative to the last actual known at the
origin (publication-aware); for return forecasts (`forecast_naive: zero` without a `naive` column) the sign of the
value itself. "Up" is strictly positive. Reports the hit ratio, the hit ratio under independence P* = Py Px +
(1 - Py)(1 - Px), PT = (P - P*) / sqrt(var(P) - var(P*)) ~ N(0, 1), its one-sided p-value and the confusion table.
**Status.** NEEDS_REVIEW when the hit ratio is not significantly above P* at `forecast_directional_alpha`; INFO
otherwise; NOT_EXECUTABLE when every actual (or every forecast) moves in the same direction (no variance to test).
**Why.** A hit ratio above 50% means nothing when the actuals mostly move one way.
**Fix.** Establish sign skill on more data before using the forecast for directional decisions.
**Allows.** Direction predicted better than chance. **Does not allow.** The size of the moves.

### `forecast_error_dynamics`

**What.** An optimal h-step forecast has errors that are at most MA(h - 1), so autocorrelation beyond lag h - 1
means information was left on the table. Portmanteau test over lags h .. h + 10: the Ljung-Box test at h = 1; for
h > 1, Q = T r' Sigma^-1 r with Bartlett's (1946) covariance of the sample autocorrelations under the MA(h - 1) null.
The plain Ljung-Box sum from lag h is **not** used for h > 1: in a Monte Carlo on true h-step AR(1) errors it rejected
41% (h = 3) and 55% (h = 12) of the time at the 5% level, against 6% and 2% for the Bartlett-corrected statistic.
Also a rolling RMSE over one year of target dates (window = round(365 / median spacing), at most half the sample)
with the worst and best windows.
**Status.** NEEDS_REVIEW when the portmanteau rejects at `forecast_alpha`. INFO "regime-dependent accuracy" when
the worst window RMSE is more than 2x the best. INFO summary otherwise.
**Why.** Predictable errors mean an omitted variable or dynamic; an average score hides regime dependence.
**Fix.** Model the error dynamics; report the accuracy per regime or per year.
**Allows.** Residual predictability of the errors and the time profile of the accuracy.
**Does not allow.** Which variable is omitted.

### `forecast_multiple_models`

**What.** When several models are scored on the same (series, horizon): their number, the best by RMSE, and the
best DM* statistic against the naive (sign flipped: positive = better) compared with the expected maximum of n
independent standard normal t-statistics E[max] = (1 - g) Z(1 - 1/n) + g Z(1 - 1/(n e)) (g = Euler-Mascheroni;
the formula of the deflated Sharpe ratio, applied to t-statistics), and the probability that the best of n
skill-less models reaches the observed t by chance, 1 - Phi(t)^n.
**Status.** NEEDS_REVIEW when the best t is below E[max] (the winner's edge is what selection alone produces: White
2000 / Hansen 2005, simplified); INFO otherwise; NOT_EXECUTABLE with one model.
**Why.** The best of many models beats the naive by chance with high probability; reporting only the winner is
data snooping.
**Fix.** Pre-register one model or evaluate the winner on a fresh sample; report the number of models tried.
**Allows.** Whether the best model's advantage exceeds what selection alone would produce.
**Does not allow.** A full bootstrap reality check: the correlation between the models' losses is ignored (with
highly correlated models E[max] is lower, so the check is conservative towards NEEDS_REVIEW).

## Conventions and thresholds

| Key | Default | Meaning |
|---|---|---|
| `forecast_alpha` | 0.05 | level of the DM and portmanteau tests |
| `forecast_min_observations` | 30 | minimum comparable forecasts per (model, series, horizon) |
| `forecast_naive` | random_walk | random_walk, mean or zero |
| `forecast_loss` | squared | squared or absolute loss in the DM test |
| `forecast_bias_alpha` | 0.05 | level of the Mincer-Zarnowitz Wald test |
| `forecast_directional_alpha` | 0.05 | level of the Pesaran-Timmermann test |
| `forecast_revised_data` | false | caution when the actuals may be revised vintages (set by `forecast_macro`) |

Profiles: `forecast_returns` (naive zero, direction = sign of the forecast), `forecast_macro` (random-walk naive,
revised-data caution).

## Cases (`cases/usecase_forecast/`, generator `cases/_generators/usecase_forecast_cases.py`)

| Case | Planted | Expected |
|---|---|---|
| 01_clean_skilful | AR(1) phi = 0.5, true one-step forecast, 300 daily obs | vs_naive INFO, bias INFO, origin_integrity PASS, nothing in review |
| 02_no_skill | random forecasts of i.i.d. returns, zero naive | vs_naive and directional NEEDS_REVIEW |
| 03_biased | true forecast + 0.5 sigma | bias NEEDS_REVIEW ("over-forecasts") |
| 04_target_before_origin | five rows with target < origin | origin_integrity CONFIRMED_ERROR |
| 05_revised_data_cheat | monthly series published 45 days after month end; supplied naive = last actual by target date (unpublished at the origin) | origin_integrity CONFIRMED_ERROR |
| 06_many_models_one_lucky | 12 noise models of i.i.d. returns | multiple_models NEEDS_REVIEW |
| 07_insufficient | 15 forecasts | statistical checks NOT_EXECUTABLE, never PASS |
| 08_multi_horizon (adversarial) | h = 1, 3, 12 with a horizon column; errors MA(h - 1) by construction | error_dynamics must NOT alert; origin_integrity PASS |

Expected outcomes are fixed by the generator from the planted property, with its own independent computation of
the statistics, before the tool runs.

## Limitations

- The horizon must be in periods of the series; when inferred from the dates it can be wrong for irregular spacing
  (reported as NEEDS_REVIEW when horizons are mixed).
- Without `actual_available_from` the naive and the directional reference use the last actual by target date, which
  for revised macro data may be a later vintage (Croushore and Stark 2001).
- The DM test assumes a covariance-stationary loss differential; with very persistent losses or very long horizons
  relative to the sample (h close to T / 3) it is unreliable (Diebold 2015).
- The reality check ignores the correlation between models (no bootstrap); it is a caution, not the SPA test.
- Several series or several horizons in one file produce one finding per group; the module does not adjust for
  the number of groups tested.
- Tail probabilities use the Student t (regularised incomplete beta), the normal distribution, the closed form of
  the chi-square with 2 df and the Wilson-Hilferty approximation for other degrees of freedom; no scipy.
