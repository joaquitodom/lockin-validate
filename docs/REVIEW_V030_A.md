# Review v0.3.0 A: signals, ml, forecast

Independent adversarial review. Cases: `cases_review_v030/<module>/<NN_name>/` (18 cases; generator
`cases_review_v030/_gen_review.py`, which does not import lockin_validate). Every `expected.json` was written by the
generator before the first run and not changed afterwards. Module code, existing cases and tests are untouched.

## Score

- Cases fully as pre-registered: **13 of 18** (signals 5/6, ml 5/6, forecast 3/6).
- Pre-registered detections (runner count): **24 of 28**.
- Failed cases: signals/04, ml/03, forecast/01, forecast/02, forecast/06.
- Two of the five are partly my expectation, not a module defect: forecast/01 (L1) and the `essential_fields`
  CONFIRMED_ERROR in signals/04 (M2, core check).
- Defects found by reading the findings after the run, not covered by a pre-registered expectation ("post-hoc"):
  H3 (ml/03 calibration PASS), H4 (ml/01 AUC with blank probabilities), M1 (signals/03 turnover "nan").

## Failures

### HIGH

**H1. signals/04_ties_nan_ticker_effect: significant quantile spread manufactured by tie-breaking.**
Expected `signal_quantile_spread` NEEDS_REVIEW (random 3-level score, no skill). Got INFO "Quantile spread +54.6 bp
(t +4.09), monotonicity 0.60". The IC on the same data is t -0.11 (correctly NEEDS_REVIEW). The spread comes from a
ticker fixed effect in returns combined with file order: ties are broken "by position", so with a heavily tied signal the
top bucket is just the highest-index tickers. A user with a graded score (ratings 1-5, deciles) gets a spurious
significant spread and no alert. Code: `signals.py` `assign_quantiles` (~line 97, `s[ok].rank(method="first")`).
Fix idea: average ranks / split tied names across buckets, or review when many rows are tied.

**H2. ml/03_single_class_in_test: overfit_gap INFO "auc train 0.753, test nan ... gap is within the review threshold".**
Expected NOT_EXECUTABLE or NEEDS_REVIEW. The test AUC is undefined (no positives) and the text still says the gap is
within the threshold. Code: `ml.py` ~line 565 `if math.isfinite(te["auc"]) and ...` skips the baseline test when AUC is nan,
and ~line 556 `rel` is nan, so no problem is raised and the finding falls to INFO.

**H3 (post-hoc). ml/03: ml_calibration PASS when the test base rate is 0 (or 1).**
Mean predicted probability 0.049 against an observed rate of 0.000 on 500 rows (about 24 positives expected, 0 seen); the PASS
says "mean probability within 2 SE of the base rate". ECE 0.049 is just under the 0.05 gate. Code: `ml.py` line 653
`se = ... if 0 < base < 1 else float("nan")` and line 672 `if math.isfinite(se) and ...` skip the check exactly in the degenerate
case where it is most informative.

**H4 (post-hoc). ml/01_clean_aliases_synonyms: rows with a blank probability enter the AUC as the top score.**
3 of 1000 test rows have a blank `score`. Calibration uses n = 997, but `ml_overfit_gap` reports test AUC 0.751 on n = 1000. The AUC
on the 997 valid rows is 0.7538; ranking the blanks above every score reproduces the module's 0.7513 exactly. NaN sorts last in
`np.argsort`. Code: `ml.py` line 532 `j.dropna(subset=["prediction", "actual"])` does not include `probability`; `rankdata`
(line 49) has no NaN guard. Effect is small here, arbitrary with more blanks, and the n differs between checks.

**H5. forecast/02_business_days_weekend_gaps: weekend gaps become "mixed horizons" and a spurious h=3 group.**
Legitimate one-step business-day forecasts (origin = previous business day, no horizon column). Expected
`forecast_origin_integrity` PASS and one h=1 group of 330. Got NEEDS_REVIEW "horizons are mixed without a horizon column", and every
statistic split into h=1 (n=263) and h=3 (n=66; Monday targets with a Friday origin = 3 days / median spacing 1 day). The h=3 group
uses 2 Newey-West lags and the Bartlett portmanteau on a series that is one-step. Wrong horizon, lags and grouping, plus a false review item
on vs_naive. Code: `forecast.py` lines ~315-318 (`round(days / st)`, `st` = median calendar-day spacing) and `MIXED_HORIZON_RATIO` (line 51)
applied to calendar days. Fix idea: infer steps from the position of the target in the series' own sorted target dates.

**H6. forecast/06_duplicated_rows_insufficient: identical duplicate rows pass the minimum-sample gate.**
20 distinct forecasts, each exported twice, plus 4 blank rows. Expected `forecast_vs_naive` NOT_EXECUTABLE (20 < 30). Got a full DM/RMSE
result with n = 38 (NEEDS_REVIEW only because this sample is unlucky; with real skill the same file would be INFO "beats the naive" with the DM
variance understated by the duplicates). `forecast_origin_integrity` says PASS "no contradictory duplicates" and does not mention that rows are
repeated. Code: `forecast.py` ~line 461 (`d.duplicated(key, keep=False)` is only reported when forecasts differ) and no `drop_duplicates` on the
forecast table before the groups are built (line ~344 only dedups the actuals history).

### MEDIUM

**M1 (partly post-hoc). signals/03_constant_signal: quantile spread and turnover computed on a constant signal.**
Pre-registered quantile_spread NEEDS_REVIEW or NOT_EXECUTABLE: got NEEDS_REVIEW (met), but only because the file-order spread was negative
(t -0.82, monotonicity -0.40); same mechanism as H1, it would be INFO if ticker order correlated with returns. `signal_turnover` gives
INFO "Rank autocorrelation nan, ... half-life nan decision dates (~nan sessions)" instead of NOT_EXECUTABLE. Code: `signals.py` `assign_quantiles` (~97) and the
turnover summary (~509-513) with no nan guard. predictive_power and lookahead_hint correctly NOT_EXECUTABLE.

**M2. signals/04: 5% blank signals produce a CONFIRMED_ERROR (`essential_fields`).**
92 blank cells of 1680: "empty values in `signal` ... Those rows cannot be used". The rows are dropped and the module finishes. Treating names with
no score on a date as an error is arguable and it is the core check, not the module; docs/usecases/signals.md does not say it. My
errors_only_from = [] counted it as a false positive.

### LOW

**L1. forecast/01_clean_aliases_tz: forecast_bias NEEDS_REVIEW on the true model.**
Mean error -0.1323, HAC t -2.22 (Wald p 0.073, not rejecting). The rule "Wald p < 0.05 OR |t(mean error)| > 2" combines two tests on the same data, so the
false-alarm rate on a correct forecast is above the nominal 5% (I estimate 7-8%, not simulated). The arithmetic is right (t reproduced); my
INFO expectation did not account for the OR rule or check the seed. Code: `forecast.py` bias status (~lines 600-625). Documented behaviour.

**L2. forecast/03_flat_series_zero_variance: "Theil's U inf" and "ratio inf".** Statuses acceptable (NEEDS_REVIEW; bias and directional
NOT_EXECUTABLE; no crash), but `inf` appears in titles/text and error_dynamics reports Q = 0.00, p = 1.000 for zero-variance errors. NOT_EXECUTABLE would be cleaner.

**L3. forecast/04_published_before_period: finding text mentions "contradictory duplicates"** though the only cause is `actual_available_from < target_date`
(3 of 120 rows). Shared detail string in `forecast.py` (~lines 490-505).

**L4. Docs:** signals.md does not say that blank signals trigger the core `essential_fields` error, nor that tie-breaking by file order can create a spread (H1).

## Traps that held

signals/01 (-05:00 stamps; IC t +8.19), 02 (31-session price gap + late-listed ticker: INFO, 1.7% rows without forward price, no review), 03 (constant
signal: IC NOT_EXECUTABLE), 05 (lag 0 declared, after-close times: INFO, not CONFIRMED_ERROR), 06 (Saturday decisions with lag 1 and 3 decision dates after the end of prices:
PASS, 90 rows reported as excluded); ml/01 (aliases `date`/`y_true`/`score`, synonyms training/dev/oos, 3 blank scores), 02 (probabilities exactly 0 and 1: finite metrics, PASS),
04 (constant probability: AUC 0.500 NEEDS_REVIEW, PSI 0.000, no crash), 05 (last train label_end == first test timestamp, +00:00 stamps: PASS), 06 (unpurged 5-fold:
CONFIRMED_ERROR, 160 samples = 8 block sides x 20, matches my hand count); forecast/03 (flat series, no crash), 04 (3 publication dates before the target:
CONFIRMED_ERROR), 05 (publication-aware naive, blank naive in the first rows, revised_data: PASS).

## Cross-checked statistics (numpy, independent of the module)

| Module | Statistic | Case | Module | Mine |
|---|---|---|---|---|
| signals | Spearman IC mean, h=1 | 01 | +0.2223 | +0.2223 |
| signals | IC sd / t-stat (NW, L=0), h=1 | 01 | 0.205 / +8.19 | 0.2048 / +8.19 |
| signals | t-stat h=5 (L=0) / h=21 (L=4, Bartlett) | 01 | +4.46 / +2.66 | +4.46 / +2.66 |
| signals | IC mean / t, h=1, with ties and blanks | 04 | -0.0031 / -0.11 | -0.0031 / -0.11 |
| ml | AUC train | 01 | 0.776 | 0.7756 |
| ml | AUC test | 01 | 0.751 | **0.7538** on the 997 valid rows (module value = 0.7513 when the 3 blank scores rank as highest; H4) |
| ml | PSI of the model probability (10 train quantile bins, floor 1e-4) | 01 | 0.017 | 0.0173 |
| forecast | RMSE model / naive, Theil's U | 01 | 1.04 / 1.201, 0.866 | 1.0399 / 1.2011, 0.8658 |
| forecast | DM* (HLN, h=1), n | 01 | -4.43, n = 299 | -4.4270 (variance ddof 0) / -4.4196 (ddof 1); n = 299 |
| forecast | HAC t of the mean error | 01 | -2.22 | -2.219 |

All match except the ml AUC with blank probabilities (H4): 9 of 10 rows agree.
