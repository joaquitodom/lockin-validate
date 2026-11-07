# Response to review v0.3.0 A (signals, ml, forecast)

Reviewer files (`docs/REVIEW_V030_A.md`, `cases_review_v030/`) are untouched. Score on the reviewer's battery:
**13/18 before, 17/18 after** (pre-registered detections 24/28 before, 28/28 after). The module batteries
`cases/usecase_signals` (8/8), `cases/usecase_ml` (12/12) and `cases/usecase_forecast` (8/8) stay at 100% with 0 false
positives. The one remaining failure is signals/04, solely because of the core `essential_fields` check (M2, disputed below).

| Finding | Status | Change (file) | Test | Reviewer case now |
|---|---|---|---|---|
| H1 | fixed | `signals.py` `assign_quantiles` (~96-110): average rank, tied values share a bucket; `check_quantile_spread` (~425-470): dates with fewer than 2 distinct values dropped, empty buckets handled, collapsed dates disclosed | `test_h1_tied_values_share_a_bucket`, `test_h1_skill_less_three_level_signal_has_no_significant_spread`, updated `test_quantile_assignment` | signals/04 spread NEEDS_REVIEW (was INFO +54.6 bp) |
| H2 | fixed | `ml.py` `check_overfit_gap` (~565 and ~610): undefined train or test AUC collects a reason; NOT_EXECUTABLE when no model is measurable, else NEEDS_REVIEW | `test_h2_single_class_in_test_overfit_gap_not_executable` | ml/03 OK |
| H3 | fixed | `ml.py` `check_calibration` (~690-725): base rate 0 or 1 uses SE = sqrt(sum p(1-p))/n; a non-finite SE or ECE is NEEDS_REVIEW, never PASS | `test_h3_base_rate_zero_calibration_never_passes` | ml/03 calibration NEEDS_REVIEW (was PASS) |
| H4 | fixed | `ml.py` `joined()` (~295-320) drops blank-probability rows (per model that delivers probabilities) so AUC, calibration, PSI and protocol share one n; `_dropped_note` discloses the count; `rankdata`, `auc`, `ks_statistic` ignore non-finite values (`rankdata` returns NaN for them) | `test_h4_rankdata_and_auc_ignore_nan`, `test_h4_blank_probability_rows_dropped_and_disclosed` | ml/01 test AUC on n = 997 |
| H5 | fixed | `forecast.py` `Prepared.__init__` (~315-330): horizon = number of distinct target dates of the series in (origin, target]; the mixed-horizon review now compares steps, not calendar days (~520). An explicit `horizon` column is still used as is | `test_h5_business_day_weekend_gaps_are_one_step` | forecast/02 OK (PASS, one h = 1 group) |
| H6 | fixed | `forecast.py` `Prepared.__init__` (~300-306): exact duplicates (model, series, origin, target, forecast) dropped before everything; `check_origin_integrity` (~507) reports them as NEEDS_REVIEW with the count; the 30-observation gate counts distinct rows | `test_h6_exact_duplicates_dropped_and_counted` | forecast/06 OK (vs_naive NOT_EXECUTABLE) |
| M1 | fixed | `signals.py` `check_turnover` (~525): undefined lag-1 autocorrelation is NOT_EXECUTABLE; `check_quantile_spread`: constant signal NOT_EXECUTABLE | `test_m1_constant_signal_turnover_and_spread_not_executable` | signals/03 OK |
| M2 | documented | `docs/usecases/signals.md`: blank cells trigger core `essential_fields`; tie handling | none (docs) | disputed, see below |
| L1 | tightened | `forecast.py` `check_bias` (~659): NEEDS_REVIEW only on the joint Wald p < alpha; the mean-error HAC t is shown as context | existing battery | forecast/01 OK |
| L2 | fixed | `forecast.py` `_fmt_u`, ratio text, error-dynamics group with all-zero errors is NOT_EXECUTABLE | `test_l2_zero_naive_error_has_no_inf_in_text` | forecast/03 no inf |
| L3 | fixed | `forecast.py` `check_origin_integrity` (~490): the "different forecasts" sentence only appears for that cause | none | forecast/04 |
| L4 | documented | `docs/usecases/signals.md` | none | |

## L1 Monte Carlo (true model: y = f + N(0,1), f ~ N(0,1), h = 1, 2000 replications, module functions)

| n | Wald p < 0.05 | abs(t) > 2 | union (old rule) |
|---|---|---|---|
| 30 | 10.6% | 5.8% | 12.5% |
| 60 | 7.9% | 5.4% | 10.0% |
| 300 | 5.9% | 4.7% | 7.8% |

The old OR rule exceeded the 10% threshold at the minimum sample (n = 30), so the rule was tightened to the Wald test alone.
The Wald test is itself above 5% at small n (HAC covariance, 2 df), which is a property of the existing test, not changed here.

## Disputed expectation

**signals/04 `errors_only_from = []`.** The only failing item is `essential_fields` CONFIRMED_ERROR for 92 blank `signal` cells.
That is the core data check working as designed (blank cells in a required column are an input defect and the rows
are unusable), it is not part of the signals module, and 5% blank signals is the reviewer's own planted noise. I do
not think a blank signal should be silent, so I left the rule and documented it (M2). All module findings of
signals/04 now match the reviewer's expectations (predictive power and quantile spread NEEDS_REVIEW, no INFO).

## Notes on behaviour changes

- Tie-aware buckets are not equal-sized; with q = 5 a 3-level signal populates buckets 1, 3, 5, monotonicity is computed on
  the populated buckets (and skipped, not flagged, with fewer than 3).
- The old `test_quantile_assignment` assertion for four tied values (split by position) was updated to the new defined behaviour.
