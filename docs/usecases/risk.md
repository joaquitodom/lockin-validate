# Use case `risk`: backtesting market-risk models (VaR / ES)

**Who it is for.** Risk managers, model validation units and anyone who publishes a Value at Risk: banks under
Basel / FRTB, asset managers (UCITS VaR limits), prop desks, crypto exchanges. The module compares the VaR and
Expected Shortfall forecasts a model produced with the P&L that actually happened on the day each forecast was for.

**What it does not do.** It does not estimate a VaR, does not judge the methodology from its description and does
not replace the supervisory process: it says whether the realised exceptions are consistent with the promised
coverage, whether they cluster, which Basel zone the model would be in, whether the ES is the right size and whether
the model reacts to volatility. The checks are the published ones (Kupiec 1995, Christoffersen 1998, Basel 1996,
Acerbi and Szekely 2014); their power limits are stated in each finding.

## Inputs

One table, `var_forecasts.csv`, one row per day:

| column | required | meaning |
|---|---|---|
| `date` (aliases `datetime`, `timestamp`, `day`) | yes | the day the forecast was for |
| `pnl` (aliases `return`, `ret`, `loss`) | yes | realised P&L or return of that day. `loss` is read as a loss and its sign is inverted (logged) |
| `var_<level>` | at least one | VaR forecast made before the day: `var_99`, `var_975`, `var_95` (the suffix is the confidence level) |
| `es_<level>` | optional | expected shortfall forecast at the same level |
| `model`, `portfolio` | optional | names, carried as context |

Sign convention (`conventions.risk_var_sign` in rules.yaml): `positive_loss` (default; `var_99 = 0.025` means a
2.5% loss) or `negative_quantile` (`var_99 = -0.025` is the 1% quantile of the P&L). When most VaR values have the
opposite sign of the declared convention the module switches and says so (INFO). Internally every loss is a positive
number: L = -pnl, exception when L > VaR.

Optional rules.yaml block:

```yaml
risk:
  horizon_days: 1      # reported as context
  confidence: 0.99     # reported as context
  window: 250          # traffic-light window when conventions.risk_traffic_light_window is not set
conventions:
  risk_var_sign: positive_loss
```

Profiles: `risk_var_daily` (daily 99% one-day VaR, 250-day window) and `risk_var_fund` (asset-manager VaR at
95% / 99%, UCITS-style 250-day window). Use `--profile risk_var_fund`.

## Checks

### `var_input_coherence`

- **What:** sign convention (declared vs observed) and horizon (INFO); CONFIRMED_ERROR when a `var_<level>` column
  is missing or zero on more than 1% of days, when a lower level's VaR exceeds a higher level's on any day
  (`var_95 > var_99`), when `es_<l> < var_<l>` on any day, or when dates are duplicated; NEEDS_REVIEW when the P&L has
  a gap longer than 5 sessions (sessions of the declared calendar; weekdays when undeclared) or is identical on more
  than 5 consecutive days.
- **Why:** an inverted sign makes every exception count meaningless; crossed quantiles or an ES below its VaR cannot
  come from a coherent model; gaps and frozen P&L remove the days a backtest exists to test.
- **Fix:** declare the convention, one row per date, ordered quantiles, ES at least the VaR; explain gaps.
- **Allows / does not allow:** whether the file can be backtested / anything about forecast quality.
- **Refs:** Basel 1996; SR 11-7.

### `var_coverage`

- **What:** Kupiec (1995) proportion-of-failures test per level: exceptions x in N days, expected rate p = 1 - level,
  `LR_uc = -2 ln[(1-p)^(N-x) p^x] + 2 ln[(1-x/N)^(N-x) (x/N)^x]` against chi-square(1) (p-value `erfc(sqrt(LR/2))`),
  as context, and the exact two-sided binomial acceptance region of x, which **decides** (x outside the region rejects;
  the asymptotic LR over-rejects with about 3 expected exceptions, e.g. 0 in 260 days at 99%: asymptotic p = 0.022 but
  exact P(X = 0) = 0.073). NEEDS_REVIEW when x is outside the region at `risk_kupiec_alpha`, saying whether
  there are **too many** exceptions (risk under-estimated, high priority) or **too few** (model too conservative: it
  costs capital and hides whether the model reacts to stress). PASS when x is inside the region and N >= `risk_min_observations`.
  NOT_EXECUTABLE below that, saying how many observations there are.
- **Why:** coverage is the first promise of a VaR.
- **Fix:** re-estimate volatility and tails; check the horizon and the P&L definition (hypothetical vs actual).
- **Does not allow:** independence (next check); the test has low power below 250 days (Kupiec 1995) and estimation
  risk inflates rejections (Escanciano and Olmo 2010).
- **Refs:** Kupiec 1995; Campbell 2006; Escanciano and Olmo 2010.

### `var_independence`

- **What:** Christoffersen (1998) Markov independence test `LR_ind` (transitions n00, n01, n10, n11) against
  chi-square(1) and the joint conditional coverage `LR_cc = LR_uc + LR_ind` against chi-square(2) (p = exp(-LR/2));
  the longest run of consecutive exceptions and the number of clusters (exceptions within 5 days of another).
  NEEDS_REVIEW when either test rejects at `risk_christoffersen_alpha` or when a run of 3+ consecutive exceptions
  exists at 99%. PASS when neither rejects. With fewer than 5 exceptions the Markov test has no power: INFO.
- **Why:** a model right on average and wrong in the stress weeks shows up as clustered exceptions.
- **Fix:** faster volatility estimate (decay, window), daily re-estimation.
- **Does not allow:** higher-order or duration dependence (Berkowitz, Christoffersen and Pelletier 2011).
- **Refs:** Christoffersen 1998; Berkowitz, Christoffersen and Pelletier 2011; Campbell 2006.

### `basel_traffic_light`

- **What:** exceptions of the 99% VaR in the last `risk_traffic_light_window` observations (default 250; else
  rules.yaml `risk.window`), mapped to the Basel zones: for 250 days the published table (green 0-4, yellow 5-9,
  red 10+); for another window the cumulative binomial probability P(X <= k) with p = 0.01 (green below 95%, yellow
  95% to 99.99%, red above, the definition of the 1996 document). Multiplier add-on 0 / 0.40, 0.50, 0.65, 0.75, 0.85
  / 1.00. Rolling count over the full sample with the worst window and the number of windows in each zone.
  INFO for green, NEEDS_REVIEW for yellow, NEEDS_REVIEW with high priority for red. Never CONFIRMED_ERROR: red is a
  statistical signal, not a proven error. NOT_EXECUTABLE without a `var_99` column or with fewer observations than
  the window.
- **Why:** it is the regulatory backtest; yellow asks for explanations, red presumes a model problem.
- **Refs:** Basel 1996; Basel 2019 (MAR / FRTB: desk-level backtesting at 99% and 97.5%).

### `es_backtest`

- **What:** when `es_<level>` exists, the Acerbi and Szekely (2014) second test with losses positive:
  `Z2 = 1 - sum_t L_t 1[exception_t] / (N p ES_t)`, 0 under H0, negative when the ES is too small; the mean realised
  loss on exception days against the mean ES forecast on those days; the exceedance residual mean(L - ES) on exception
  days with its t-statistic. NEEDS_REVIEW when Z2 < -0.70 (the approximate 5% critical value the authors cite for
  typical distributions; the exact value is model-dependent and needs simulation under the model) or when the mean
  realised loss exceeds the mean ES by more than 25%. INFO otherwise (not PASS: the critical value was not simulated).
  NOT_EXECUTABLE with fewer than 10 exceptions.
- **Why:** FRTB capital rests on the 97.5% ES; the VaR coverage says nothing about the size of the losses beyond it.
- **Refs:** Acerbi and Szekely 2014; Basel 2019.

### `var_model_stability`

- **What:** exception rate per calendar year (years with 100+ observations; otherwise 250-day blocks) per level, with
  a chi-square homogeneity test across blocks (2 x B table, B - 1 degrees of freedom) run only when every block
  expects at least 5 exceptions; the correlation between the VaR and the trailing 20-day realised volatility of the
  P&L and the VaR / volatility ratio per block. NEEDS_REVIEW when the homogeneity test rejects at `risk_kupiec_alpha`
  or when the correlation is below 0.30 ("the model does not respond to volatility"; a constant VaR counts as 0).
  INFO otherwise.
- **Why:** a full-sample coverage test averages good and bad years.
- **Refs:** Basel 1996; Campbell 2006; SR 11-7.

## Conventions and defaults

| key | default | used by |
|---|---|---|
| `risk_kupiec_alpha` | 0.05 | var_coverage, var_model_stability (homogeneity) |
| `risk_christoffersen_alpha` | 0.05 | var_independence |
| `risk_min_observations` | 250 | var_coverage, var_independence, var_model_stability |
| `risk_traffic_light_window` | 250 (else rules.yaml `risk.window`) | basel_traffic_light |
| `risk_es_alpha` | 0.05 | es_backtest (documented level of the approximate Z2 bound -0.70) |
| `risk_var_sign` | `positive_loss` | all (sign of the VaR / ES columns) |

Fixed thresholds stated in the findings: 1% missing / zero VaR, 5-session gaps, 5-day flat P&L, 5 exceptions for the
Markov test, 10 exceptions for the ES statistics, Z2 < -0.70, ES ratio 1.25, correlation 0.30, 20-day realised
volatility.

## Limitations

- Power: with 250 days and p = 1%, Kupiec cannot tell a 1% model from a 1.5% one; a one-year backtest that "passes"
  is weak evidence (Kupiec 1995, Campbell 2006). The findings say N and the acceptance region.
- The Christoffersen test sees first-order dependence only; a model whose exceptions cluster over weeks with gaps
  between them can pass it.
- The Z2 bound is an approximation; a formal ES verdict requires simulating Z2 under the model.
- Estimation risk in the VaR itself (Escanciano and Olmo 2010) is not corrected for.
- The module does not check that the forecast was made before the day (that is the backtest owner's declaration); a
  VaR estimated with the day's own return would look perfect here.

## Cases (`cases/usecase_risk/`)

01 clean normal model (no alert) - 02 VaR x 0.7 (coverage, traffic light) - 03 volatility regimes with a constant VaR
(independence, stability) - 04 VaR x 2 (too few exceptions) - 05 Student-t P&L with ES = 1.05 x VaR (ES) - 06 var_95 >
var_99 (coherence error) - 07 120 days (not executable) - 08 negative quantiles declared as positive losses
(adversarial: INFO, coverage still PASS). Expectations were written from the planted properties before running the
tool; the generator asserts each planted property with its own arithmetic.
