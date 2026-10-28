# Validation evidence

Three records: release 0.2.1 (after the independent review), release 0.2.0 and release 0.1.0 (the "before" of the
alert-noise comparison), newest first; older records are kept unchanged. Every command was run from the repository root on Windows 11, Python
3.12.13. Nothing was edited by hand except headings and short notes.

## 0.2.1 (2026-10-28, after the independent review)

### Tests and lint

```
$ uv run pytest
187 passed, 1 skipped
$ uv run ruff check src tests cases/_generators docs
All checks passed!
```

Nine tests were added to tests/test_v020_checks.py for the review fixes (31 in that file).

### Our battery (52 cases)

```
$ uv run lockin-validate cases
...                                   (every case OK)
52 of 52 cases with all expected outcomes
Unexpected NEEDS_REVIEW (case x check): 6; false positives: 0
Pre-registered detections met: 52 of 52; expectations added after seeing the output (post_hoc, not counted as detections): 20 of 20

Per check (detections = pre-registered non-PASS outcomes found; post-hoc expectations are excluded; false positives = unexpected CONFIRMED_ERROR or forbidden review items; unexpected review = NEEDS_REVIEW on checks the case does not mention):

check                          detected   rate   passes  false+  unexp.review
@data                               1/1   100%        -       0             0
benchmark_fit                       1/1   100%      1/1       0             0
conditional_rule_activation         1/1   100%      1/1       0             0
corporate_actions                   1/1   100%      1/1       0             0
cost_sensitivity                    1/1   100%      1/1       0             0
coverage                              -      -      2/2       0             2
coverage_drift                      2/2   100%      2/2       0             0
dates                               1/1   100%      2/2       0             0
deflated_sharpe                     3/3   100%      1/1       0             0
dividend_corporate_actions          1/1   100%      1/1       0             0
duplicates                          1/1   100%      2/2       0             0
essential_fields                      -      -      1/1       0             0
input_sufficiency                   1/1   100%      1/1       0             0
liquidity_participation             1/1   100%      1/1       0             0
llm_lookahead_risk                  1/1   100%        -       0             0
lookahead                           5/5   100%      1/1       0             0
metrics                             1/1   100%      3/3       0             0
multiple_testing                    1/1   100%      1/1       0             0
omitted_costs                       5/5   100%      2/2       0             0
pbo                                 2/2   100%      1/1       0             0
pit_fundamentals                    1/1   100%      1/1       0             0
positions_reconciliation            2/2   100%      1/1       0             0
price_jumps                         1/1   100%      1/1       0             1
protocol_integrity                  2/2   100%      1/1       0             0
reconstruction                      2/2   100%      2/2       0             0
reference_accuracy                  1/1   100%      1/1       0             0
results_reconciliation              2/2   100%      4/4       0             0
rules_vs_implementation             1/1   100%      2/2       0             0
schema_and_types                      -      -      1/1       0             0
sharpe_autocorrelation              1/1   100%        -       0             0
sharpe_significance                 1/1   100%      1/1       0             3
signal_data_after_decision            -      -      1/1       0             0
stability_and_concentration         1/1   100%      1/1       0             0
stale_prices                        1/1   100%      2/2       0             0
survivorship                        1/1   100%      1/1       0             0
ticker_identity                     1/1   100%      1/1       0             0
trade_before_signal                   -      -      1/1       0             0
trials_declared                     4/4   100%      2/2       0             0
```

Pre-registered detections and post-hoc expectations are separate lines and are never summed. On the 36 cases of
0.1.0: pre-registered detections 40 / 40; post-hoc expectations 20 / 20; 3 unexpected review items (the withdrawn P7
footprints of core 05 and D03).

| Battery | Version | NEEDS_REVIEW | Unexpected NEEDS_REVIEW | INFO | Pre-registered detections | Post-hoc expectations |
|---|---|---|---|---|---|---|
| 36 cases of 0.1.0 | 0.1.0 | 57 | 40 | - | 40 / 40 | - |
| same 36 cases | 0.2.1 | 40 | 3 | 26 | 40 / 40 | 20 / 20 |
| all 52 cases | 0.2.1 | 53 | 6 | 36 | 52 / 52 | 20 / 20 |

### The reviewer's battery (28 cases, their expectations, unedited)

```
$ uv run lockin-validate cases --dir cases_review_v020
OK   cases_review_v020/V01_cov_single_field_late_drop: errors 0, review 1, not executable 34, info 0, pass 2
OK   cases_review_v020/V02_cov_vendor_stops_entirely: errors 0, review 1, not executable 34, info 0, pass 2
OK   cases_review_v020/V03_cov_universe_genuinely_shrinks: errors 0, review 0, not executable 34, info 0, pass 3
OK   cases_review_v020/V04_cov_unused_optional_field_dropped: errors 0, review 0, not executable 34, info 1, pass 3
OK   cases_review_v020/V05_suff_one_month_just_below: errors 1, review 1, not executable 34, info 0, pass 1
OK   cases_review_v020/V06_suff_inputs_declared_in_mixed_case: errors 0, review 0, not executable 34, info 0, pass 3
OK   cases_review_v020/V07_suff_insufficient_names_left_unscored: errors 0, review 0, not executable 34, info 0, pass 3
OK   cases_review_v020/V08_proto_validation_run_spills_into_test: errors 1, review 1, not executable 34, info 0, pass 1
OK   cases_review_v020/V09_proto_adjacent_windows_and_sloppy_labels: errors 0, review 1, not executable 34, info 0, pass 2
OK   cases_review_v020/V10_proto_single_look_labelled_holdout: errors 0, review 1, not executable 34, info 0, pass 2
OK   cases_review_v020/V11_bench_declared_equal_but_data_cap_weighted: errors 0, review 1, not executable 25, info 1, pass 10
OK   cases_review_v020/V12_bench_equal_vs_equal_misaligned_dates: errors 0, review 0, not executable 25, info 1, pass 11
OK   cases_review_v020/V13_div_frozen_from_session_after_ex_date: errors 1, review 0, not executable 29, info 0, pass 7
OK   cases_review_v020/V14_div_raw_prices_labelled_adjusted: errors 0, review 1, not executable 29, info 0, pass 7
OK   cases_review_v020/V15_div_clean_dividend_on_non_holding: errors 0, review 1, not executable 23, info 1, pass 12
OK   cases_review_v020/V16_liq_parent_order_sliced_into_child_fills: errors 0, review 1, not executable 23, info 5, pass 8
OK   cases_review_v020/V17_liq_half_the_trades_have_no_volume: errors 0, review 1, not executable 23, info 4, pass 9
FAIL cases_review_v020/V18_liq_illiquid_name_tiny_trades: errors 1, review 0, not executable 23, info 4, pass 9
       unexpected CONFIRMED_ERROR (false positive) reconstruction: Sells that leave a negative quantity without declared short selling
OK   cases_review_v020/V19_cost_fragile_only_against_benchmark: errors 0, review 2, not executable 23, info 1, pass 11
OK   cases_review_v020/V20_cost_clean_costs_in_bps_file: errors 0, review 1, not executable 24, info 1, pass 11
OK   cases_review_v020/V21_stab_one_year_carries_by_a_hair: errors 0, review 2, not executable 33, info 1, pass 1
OK   cases_review_v020/V22_stab_clean_one_big_winner_others_positive: errors 0, review 0, not executable 24, info 1, pass 12
OK   cases_review_v020/V23_rule_never_computed_in_sample: errors 0, review 1, not executable 32, info 0, pass 4
OK   cases_review_v020/V24_rule_just_inside_both_thresholds: errors 0, review 1, not executable 32, info 1, pass 3
OK   cases_review_v020/V25_rule_clean_rare_in_both_and_common_in_both: errors 0, review 0, not executable 32, info 0, pass 5
OK   cases_review_v020/V26_e2e_research_package_four_problems: errors 1, review 6, not executable 25, info 0, pass 5
OK   cases_review_v020/V27_e2e_trading_package_three_errors: errors 3, review 3, not executable 19, info 1, pass 12
OK   cases_review_v020/V28_lockin_like_holdout_coverage_drop: errors 1, review 2, not executable 31, info 0, pass 3

27 of 28 cases with all expected outcomes
Unexpected NEEDS_REVIEW (case x check): 14; false positives: 1
Pre-registered detections met: 22 of 22; expectations added after seeing the output (post_hoc, not counted as detections): 0 of 0

Per check (detections = pre-registered non-PASS outcomes found; post-hoc expectations are excluded; false positives = unexpected CONFIRMED_ERROR or forbidden review items; unexpected review = NEEDS_REVIEW on checks the case does not mention):

check                          detected   rate   passes  false+  unexp.review
benchmark_fit                       2/2   100%      1/1       0             1
conditional_rule_activation         3/3   100%      1/1       0             0
cost_sensitivity                    1/1   100%      1/1       0             0
coverage_drift                      4/4   100%      1/1       0             2
deflated_sharpe                       -      -        -       0             1
dividend_corporate_actions          3/3   100%      1/1       0             0
input_sufficiency                   3/3   100%      2/2       0             0
liquidity_participation             3/3   100%      1/1       0             0
multiple_testing                      -      -        -       0             1
pit_fundamentals                      -      -      1/1       0             0
protocol_integrity                  2/2   100%      2/2       0             0
reconstruction                        -      -        -       1             0
sharpe_autocorrelation                -      -        -       0             2
sharpe_significance                   -      -        -       0             2
stability_and_concentration         1/1   100%      1/1       0             0
trials_declared                       -      -        -       0             5
```

Score: 18 / 28 on 0.2.0 -> 27 / 28. The failing case, V18, is the defect of the reviewer's generator described in
REVIEW_V020.md section 2 (a sell before any buy); the tool's `reconstruction` CONFIRMED_ERROR is correct for the
delivered trades and its target check passes as expected. The 14 unexpected review items are those the reviewer
classified as mostly legitimate (trials_declared by policy, autocorrelation genuinely in V20/V21, short-record
significance, second views of planted gaps, an undeclared benchmark in V19); the duplicates item of V16 is gone (now
INFO).

### Threshold sensitivity and simulated size (docs/simulations/alert_policy_checks.py)

```
$ uv run python docs/simulations/alert_policy_checks.py
1. sharpe_significance below PSR 0.95: status by significance_review_ratio (R = review, i = INFO)
case                                              MinTRL/T     1   1.5     2     3     5
adversarial/R11_byma_calendar_undeclared              1.14     R     i     i     i     i
core/06_lookahead                                     1.19     R     i     i     i     i
core/06b_lookahead_without_availability               1.19     R     i     i     i     i
core/05_impossible_dates                              1.41     R     i     i     i     i
statistical/S06_llm_before_cutoff                     1.54     R     R     i     i     i
adversarial/R07_undeclared_leverage                   1.55     R     R     i     i     i
statistical/S03_autocorrelated_returns                1.58     R     R     i     i     i
adversarial/R01_zero_costs_declared                   1.59     R     R     i     i     i
adversarial/R02_small_costs_omitted                   1.59     R     R     i     i     i
adversarial/R04_lookahead_fundamentals                1.59     R     R     i     i     i
adversarial/R08_declared_slippage_omitted             1.59     R     R     i     i     i
adversarial/R13_unrecognised_results                  1.59     R     R     i     i     i
adversarial/R00_clean                                 1.70     R     R     i     i     i
lessons/L14_one_name_carries                          1.87     R     R     i     i     i
core/08_rules_vs_implementation                       2.24     R     R     R     i     i
lessons/L12_illiquid_and_cost_fragile                 2.31     R     R     R     i     i
adversarial/R06_undeclared_short                      2.45     R     R     R     i     i
adversarial/R03_first_day_commission                  3.22     R     R     R     R     i
core/10_independent                                   4.19     R     R     R     R     i
core/04_omitted_costs                                 6.74     R     R     R     R     R
statistical/S07_short_track_record                    8.98     R     R     R     R     R
lessons/L08_equal_weight_vs_cap_weighted             15.60     R     R     R     R     R
lessons/L09_equal_weight_vs_equal_weight             15.60     R     R     R     R     R
adversarial/R10_unadjusted_split                       inf     i     i     i     i     i
review items                                                  23    19     9     6     4
cases below PSR 0.95: 24

2. sharpe_autocorrelation size under i.i.d. normal returns (2000 draws per T, seed 20261028, q = 252, lags 10)
     T  LB only  LB or z1.96  LB or z2.576  review 1.96  review 2.576
   250    0.054        0.103         0.064        0.024         0.015
  1250    0.050        0.087         0.056        0.017         0.010
'review' = the full review condition (significance AND naive Sharpe more than 10% above the Lo-adjusted).
```

## 0.2.0 (2026-10-28)

### Tests and lint

```
$ uv run pytest
178 passed, 1 skipped in 27.27s
$ uv run ruff check src tests cases/_generators
All checks passed!
```

The 71 tests added since 0.1.0 are the 22 of `tests/test_v020_checks.py` (positive, negative and NOT_EXECUTABLE
paths of every new check, the INFO status and the alert policy), the BYMA calendar data tests
(`tests/test_calendar_byma_data.py`) and the 16 new battery cases run by `tests/test_battery.py`. The skipped test
builds the MCP server and needs the optional `mcp` extra. Python 3.10 was not re-run for 0.2.0.

### Benchmark battery: 52 cases

```
$ uv run lockin-validate cases
...                                   (the 36 cases of 0.1.0: all OK, see the per-check table)
OK   lessons/L01_fundamentals_coverage_drop: errors 0, review 1, not executable 34, info 0, pass 2
OK   lessons/L02_fundamentals_coverage_stable: errors 0, review 0, not executable 34, info 0, pass 3
OK   lessons/L03_reserved_window_half_inputs: errors 1, review 1, not executable 34, info 0, pass 1
OK   lessons/L04_inputs_sufficient: errors 0, review 0, not executable 34, info 0, pass 3
OK   lessons/L05_test_window_reused: errors 1, review 3, not executable 34, info 0, pass 1
OK   lessons/L06_reproductions_only: errors 0, review 0, not executable 35, info 1, pass 2
OK   lessons/L07_fresh_window_contaminated: errors 1, review 0, not executable 35, info 1, pass 1
OK   lessons/L08_equal_weight_vs_cap_weighted: errors 0, review 2, not executable 25, info 1, pass 9
OK   lessons/L09_equal_weight_vs_equal_weight: errors 0, review 1, not executable 25, info 1, pass 10
OK   lessons/L10_dividend_not_applied_and_frozen: errors 2, review 0, not executable 29, info 0, pass 7
OK   lessons/L11_dividends_consistent: errors 0, review 0, not executable 29, info 0, pass 8
OK   lessons/L12_illiquid_and_cost_fragile: errors 1, review 3, not executable 23, info 1, pass 10
OK   lessons/L13_liquid_and_cost_robust: errors 0, review 0, not executable 23, info 1, pass 13
OK   lessons/L14_one_name_carries: errors 0, review 1, not executable 24, info 2, pass 10
OK   lessons/L15_conditional_rule_dominant_oos: errors 0, review 1, not executable 32, info 0, pass 4
OK   lessons/L16_stable_and_regime_balanced: errors 0, review 0, not executable 32, info 0, pass 5

52 of 52 cases with all expected outcomes
Unexpected NEEDS_REVIEW (case x check): 3; false positives: 0

check                          detected   rate   passes  false+  unexp.review
@data                               1/1   100%        -       0             0
benchmark_fit                       1/1   100%      1/1       0             0
conditional_rule_activation         1/1   100%      1/1       0             0
corporate_actions                   1/1   100%      1/1       0             0
cost_sensitivity                    1/1   100%      1/1       0             0
coverage                            2/2   100%      2/2       0             0
coverage_drift                      2/2   100%      2/2       0             0
dates                               2/2   100%      2/2       0             0
deflated_sharpe                     4/4   100%      1/1       0             0
dividend_corporate_actions          1/1   100%      1/1       0             0
duplicates                          1/1   100%      2/2       0             0
essential_fields                      -      -      1/1       0             0
input_sufficiency                   1/1   100%      1/1       0             0
liquidity_participation             1/1   100%      1/1       0             0
llm_lookahead_risk                  1/1   100%        -       0             0
lookahead                           5/5   100%      1/1       0             0
metrics                             1/1   100%      3/3       0             0
multiple_testing                    3/3   100%      1/1       0             0
omitted_costs                     13/13   100%      2/2       0             0
pbo                                 3/3   100%      1/1       0             0
pit_fundamentals                    1/1   100%      1/1       0             0
positions_reconciliation            2/2   100%      1/1       0             0
price_jumps                         3/3   100%      1/1       0             0
protocol_integrity                  2/2   100%      1/1       0             0
reconstruction                      2/2   100%      2/2       0             0
reference_accuracy                  1/1   100%      1/1       0             0
results_reconciliation              2/2   100%      4/4       0             0
rules_vs_implementation             1/1   100%      2/2       0             0
schema_and_types                      -      -      1/1       0             0
sharpe_autocorrelation              1/1   100%        -       0             0
sharpe_significance                 6/6   100%      1/1       0             3
signal_data_after_decision            -      -      1/1       0             0
stability_and_concentration         1/1   100%      1/1       0             0
stale_prices                        1/1   100%      2/2       0             0
survivorship                        1/1   100%      1/1       0             0
ticker_identity                     1/1   100%      1/1       0             0
trade_before_signal                   -      -      1/1       0             0
trials_declared                     5/5   100%      2/2       0             0
```

Exit code: 0. The 16 lesson cases were generated and their expected.json committed (commit "Pre-register lesson
benchmark cases for six new check families") before any of the new checks existed; all 16 met their expectations
on the first run of the checks, without changing any expectation. Regenerating every case with
`cases/_generators/*.py` reproduces the committed files after line-ending normalisation (CI step "Cases are
reproducible", now including `lessons_cases.py`).

### Detection and false positives of the new checks

| Check | Positive case (planted) | Detected as | Clean negative | Result | False positives |
|---|---|---|---|---|---|
| coverage_drift | L01 (coverage 97% -> 80%), L03 (5 of 10 inputs empty) | NEEDS_REVIEW, NEEDS_REVIEW | L02, L04 | PASS, PASS | 0 |
| input_sufficiency | L03 (scored with 50% < declared 80%) | CONFIRMED_ERROR | L04 | PASS | 0 |
| protocol_integrity | L05 (test reused, c21, false reproduction), L07 (fresh_2025 touched) | CONFIRMED_ERROR, CONFIRMED_ERROR | L06 | PASS (+ INFO: N = 12 fed to the DSR) | 0 |
| benchmark_fit | L08 (equal weight vs cap weight) | NEEDS_REVIEW | L09 | PASS | 0 |
| dividend_corporate_actions | L10 (DV2 dividend missing, DV3 frozen) | CONFIRMED_ERROR (2 findings) | L11 | PASS | 0 |
| liquidity_participation | L12 (40% of ADV; order > day volume) | CONFIRMED_ERROR + NEEDS_REVIEW | L13 | PASS | 0 |
| cost_sensitivity | L12 (gone at 2x costs) | NEEDS_REVIEW | L13 | PASS | 0 |
| stability_and_concentration | L14 (CN1 carries the P&L) | NEEDS_REVIEW | L16 | PASS | 0 |
| conditional_rule_activation | L15 (5% in sample, 83% out of sample) | NEEDS_REVIEW | L16 | PASS | 0 |

On the 36 cases of 0.1.0 the new checks are NOT_EXECUTABLE (inputs absent) except cost_sensitivity and
stability_and_concentration, which run on every reconstructed NAV; they raised no NEEDS_REVIEW and no
CONFIRMED_ERROR there.

### Alert noise before and after (docs/ALERT_POLICY.md)

| Battery | Version | NEEDS_REVIEW findings | Unexpected NEEDS_REVIEW (case x check) | INFO notes | Expected detections met |
|---|---|---|---|---|---|
| 36 cases of 0.1.0 | 0.1.0 | 57 | **40** | - | 40 / 40 |
| same 36 cases | 0.2.0 | 40 | **0** | 25 | 63 / 63 (40 original + 23 added) |
| all 52 cases | 0.2.0 | 53 | **3** | 33 | 75 / 75 |

(0.2.1 note: the 0.2.0 figures above merge 40 pre-registered and 23 post-hoc expectations; see the 0.2.1 section for
the separated figures, as the independent review asked.)

The 40 were classified as 16 informative (INFO), 23 genuine (now expected, docs/CASE_CHANGES.md) and 1 bug
(autocorrelation band). The 3 left are `sharpe_significance` on L08, L09 (annualised Sharpe 0.18 over 5 years,
MinTRL about 80 years) and L12 (MinTRL 2.4 x the history): genuine under policy P1, but the lesson cases were
pre-registered for other checks and their expected.json files are not edited after the run, so they are reported
here as unexpected rather than absorbed. No expected detection was removed or relaxed.

## 0.1.0 (2026-10-27)

### 1. Test suite

```
$ uv run pytest
107 passed, 1 skipped in 23.03s          (Python 3.12.13, pandas 3.1.0, numpy 2.5.4)
```

The skipped test builds the MCP server and needs the optional extra:

```
$ uv run --with "mcp>=1.2" pytest tests/test_cli_and_mcp.py
8 passed in 6.30s
```

Python 3.10 (pandas 2.3.3), separate environment:

```
$ uv sync --python <cpython-3.10.20>  &&  uv run --python <cpython-3.10.20> pytest
107 passed, 1 skipped
```

Lint:

```
$ uv run ruff check src tests cases/_generators
All checks passed!
```

### 2. Benchmark battery

```
$ uv run lockin-validate cases
OK   adversarial/R00_clean: errors 0, review 2, not executable 12, pass 14
OK   adversarial/R01_zero_costs_declared: errors 0, review 2, not executable 12, pass 14
OK   adversarial/R02_small_costs_omitted: errors 0, review 2, not executable 12, pass 14
OK   adversarial/R03_first_day_commission: errors 0, review 1, not executable 12, pass 15
OK   adversarial/R04_lookahead_fundamentals: errors 1, review 2, not executable 11, pass 14
OK   adversarial/R05_undeclared_lookahead: errors 0, review 2, not executable 12, pass 14
OK   adversarial/R06_undeclared_short: errors 1, review 2, not executable 12, pass 13
OK   adversarial/R07_undeclared_leverage: errors 1, review 2, not executable 12, pass 13
OK   adversarial/R08_declared_slippage_omitted: errors 1, review 1, not executable 12, pass 14
OK   adversarial/R10_unadjusted_split: errors 0, review 3, not executable 12, pass 13
OK   adversarial/R11_byma_calendar_undeclared: errors 0, review 3, not executable 12, pass 13
OK   adversarial/R13_unrecognised_results: errors 0, review 2, not executable 13, pass 13
OK   core/01_clean: errors 0, review 0, not executable 10, pass 18
OK   core/02_duplicates: errors 1, review 0, not executable 10, pass 17
OK   core/03_stale_prices: errors 1, review 0, not executable 10, pass 17
OK   core/04_omitted_costs: errors 1, review 1, not executable 10, pass 16
OK   core/05_impossible_dates: errors 2, review 2, not executable 10, pass 15
OK   core/06_lookahead: errors 1, review 1, not executable 10, pass 16
OK   core/06b_lookahead_without_availability: errors 0, review 1, not executable 11, pass 16
OK   core/07_metric_error: errors 1, review 1, not executable 10, pass 16
OK   core/08_rules_vs_implementation: errors 1, review 1, not executable 10, pass 16
OK   core/09_lockin_style: errors 0, review 0, not executable 12, pass 16
OK   core/10_independent: errors 1, review 2, not executable 10, pass 15
OK   data/D01_fundamentals_before_filing: errors 1, review 0, not executable 20, pass 7
OK   data/D02_survivorship: errors 1, review 1, not executable 20, pass 7
OK   data/D03_recycled_ticker: errors 1, review 2, not executable 20, pass 5
OK   data/D04_split_not_applied: errors 1, review 1, not executable 20, pass 6
OK   data/D05_reference_mismatch: errors 0, review 1, not executable 20, pass 7
OK   data/D06_clean_extended_inputs: errors 0, review 0, not executable 16, pass 12
OK   statistical/S01_noise_best_of_200: errors 0, review 3, not executable 21, pass 4
OK   statistical/S02_genuine_signal: errors 0, review 0, not executable 21, pass 7
OK   statistical/S03_autocorrelated_returns: errors 0, review 2, not executable 25, pass 1
OK   statistical/S04_undeclared_trials: errors 1, review 3, not executable 21, pass 3
OK   statistical/S05_overfit_search_undeclared: errors 0, review 4, not executable 21, pass 3
OK   statistical/S06_llm_before_cutoff: errors 0, review 3, not executable 24, pass 1
OK   statistical/S07_short_track_record: errors 0, review 4, not executable 22, pass 2

36 of 36 cases with all expected outcomes

Per check (detections = expected non-PASS outcomes found; false positives = unexpected CONFIRMED_ERROR or forbidden review items; unexpected review = NEEDS_REVIEW on checks the case does not mention):

check                          detected   rate   passes  false+  unexp.review
@data                               1/1   100%        -       0             0
corporate_actions                   1/1   100%      1/1       0             0
coverage                              -      -      2/2       0             2
dates                               1/1   100%      2/2       0             1
deflated_sharpe                     3/3   100%      1/1       0             2
duplicates                          1/1   100%      2/2       0             0
essential_fields                      -      -      1/1       0             0
llm_lookahead_risk                  1/1   100%        -       0             0
lookahead                           5/5   100%      1/1       0             0
metrics                             1/1   100%      3/3       0             0
multiple_testing                    1/1   100%      1/1       0             3
omitted_costs                       5/5   100%      2/2       0             8
pbo                                 2/2   100%      1/1       0             1
pit_fundamentals                    1/1   100%      1/1       0             0
positions_reconciliation            2/2   100%      1/1       0             0
price_jumps                         1/1   100%      1/1       0             2
reconstruction                      2/2   100%      2/2       0             0
reference_accuracy                  1/1   100%      1/1       0             0
results_reconciliation              2/2   100%      4/4       0             0
rules_vs_implementation             1/1   100%      2/2       0             0
schema_and_types                      -      -      1/1       0             0
sharpe_autocorrelation              1/1   100%        -       0             1
sharpe_significance                 1/1   100%      1/1       0            19
signal_data_after_decision            -      -      1/1       0             0
stale_prices                        1/1   100%      2/2       0             0
survivorship                        1/1   100%      1/1       0             0
ticker_identity                     1/1   100%      1/1       0             0
trade_before_signal                   -      -      1/1       0             0
trials_declared                     3/3   100%      2/2       0             1
```

Exit code: 0 (all 36 cases with all expected outcomes).

### Detection and false positives per check

- **detected**: expected non-PASS outcomes (CONFIRMED_ERROR, NEEDS_REVIEW or NOT_EXECUTABLE written in a case's
  `must_include`) that the tool produced; **rate** = detected / expected.
- **passes**: expected PASS outcomes met.
- **false+**: CONFIRMED_ERROR on a check the case does not allow (`errors_only_from`) or a forbidden review item
  (`must_not_include`). **Zero in every check.**
- **unexp.review**: NEEDS_REVIEW on checks the case does not mention (informational). They are explained below.

Notes on the informational review items (0.1.0 wording; superseded by docs/ALERT_POLICY.md):

- `sharpe_significance` (19): most synthetic cases cover 3 to 18 months; a Sharpe ratio over such a short record is
  honestly not distinguishable from zero (PSR < 0.95). This is the intended conservative behaviour.
- `omitted_costs` (8): adversarial cases R04 to R13 trade with zero commission and declare no costs; the rule "zero
  cost with non-zero turnover is never PASS" raises a review item. The original review already recorded this as
  expected and harmless for those cases.
- `multiple_testing` / `deflated_sharpe` (3 / 2): statistical cases whose expectation focuses on another check
  (e.g. S04 under-declared trials, S07 short record) also fail the deflation, as they should.
- `coverage`, `dates`, `price_jumps`, `pbo`, `trials_declared`, `sharpe_autocorrelation`: consequences of the planted
  problem of the same case (e.g. a future-dated price row creates a long session gap; a split is also a jump).

### 3. Faithfulness of the ported cases

The translated generators were run and every ported case compared value by value with the original (Spanish) case
files (prices, trades, signals, positions, declared results; ticker renames applied). Output of the comparison:

```
01_clean                                 prices=True trades=True signals=True declared=True positions=True
02_duplicates                            prices=True trades=True signals=True declared=True positions=True
03_stale_prices                          prices=True trades=True signals=True declared=True positions=True
04_omitted_costs                         prices=True trades=True signals=True declared=True positions=True
05_impossible_dates                      prices=True trades=True signals=True declared=True positions=True
06_lookahead                             prices=True trades=True signals=True declared=True positions=True
06b_lookahead_without_availability       prices=True trades=True signals=True declared=True positions=True
07_metric_error                          prices=True trades=True signals=True declared=True positions=True
08_rules_vs_implementation               prices=True trades=True signals=True declared=True positions=True
10_independent                           prices=True trades=True signals=True declared=True positions=True
MISMATCHES: 0

R00_limpio_rol4                     -> R00_clean                        prices=True trades=True signals=True declared=True
R01_costos_cero_declarados          -> R01_zero_costs_declared          prices=True trades=True signals=True declared=True
R02_costos_chicos_omitidos          -> R02_small_costs_omitted          prices=True trades=True signals=True declared=True
R03_comision_primer_dia             -> R03_first_day_commission         prices=True trades=True signals=True declared=True
R04_info_futura_balances            -> R04_lookahead_fundamentals       prices=True trades=True signals=True declared=True
R05_info_futura_no_declarada        -> R05_undeclared_lookahead         prices=True trades=True signals=True declared=True
R06_cortos_no_declarados            -> R06_undeclared_short             prices=True trades=True signals=True declared=True
R07_apalancamiento_no_declarado     -> R07_undeclared_leverage          prices=True trades=True signals=True declared=True
R08_slippage_declarado_omitido      -> R08_declared_slippage_omitted    prices=True trades=True signals=True declared=True
R10_split_no_ajustado               -> R10_unadjusted_split             prices=True trades=True signals=True declared=True
R11_calendario_byma_sin_declarar    -> R11_byma_calendar_undeclared     prices=True trades=True signals=True declared=True
R13_resultados_no_reconocidos       -> R13_unrecognised_results         prices=True trades=True signals=True declared=True
MISMATCHES: 0
```

(The comparison script reads the original private files and is therefore not part of this repository.) Regenerating
every case with `cases/_generators/*.py` reproduces the committed files byte for byte after line-ending normalisation
(also checked in CI).

### 4. Independent verification

- Hand-computed case (`tests/oracle/hand_case/`): ledger and metrics reproduced exactly by the package, by the
  independent oracle and (metrics) by empyrical-reloaded.
- Package vs oracle vs empyrical on six core cases: NAV, cash and metrics agree to 1e-9 relative.
- Statistics vs oracle: PSR, MinTRL, expected maximum Sharpe and the Lo factor agree; the DSR reproduces the numerical
  example of Bailey and Lopez de Prado (2014) (E[max SR] = 0.1132, DSR = 0.90).
- Metamorphic tests: row order, capital scale, price-unit change, untraded asset, extra commission, doubled costs.
- Offline test: sockets blocked, four complete cases (core, lockin-style, statistical, data) produce full reports.
