# Adversarial review v0.3.0 (B): risk, portfolio, live

Scope: `usecases/risk.py`, `portfolio.py`, `live.py`. Method: cases designed from the docs pages only, `expected.json`
written by `cases_review_v030b/_gen_review.py` (no `lockin_validate` import) together with the inputs and before the
tool ever ran on them; never edited afterwards. 33 cases (12 risk, 11 portfolio, 10 live), origin `review_v030`.
Run: `uv run lockin-validate cases --dir cases_review_v030b`. No module code, existing case or existing test was touched.

## Score of pre-registered expectations

- Cases with every expectation met: **29 of 33**.
- Individual expectation items (must_include + must_not_include + text + errors_only_from): **179 of 188 met**
  (risk 79/82, portfolio 52/54, live 48/52). The 9 misses come from 4 cases.
- Of the 4 failed cases, 1 is a reviewer error (risk/11), 1 is a documented-rule wording problem (risk/06), 2 are
  genuine tool problems (live/01, portfolio/10). Genuine problems found by cases that "passed" are listed below too.

## Failures of the pre-registered expectations

| Case | Expected | Got | Verdict |
|---|---|---|---|
| portfolio/10_quarterly_declared_monthly_constant_rows | no CONFIRMED_ERROR in turnover (target identical on all 36 rows) | CONFIRMED_ERROR "Weights change on 23 date(s) outside the declared quarterly rebalance schedule" | tool bug, HIGH |
| live/01_monthly_clean (live_monthly profile) | integrity PASS; shadow PASS/INFO | integrity NEEDS_REVIEW (31-day "gap"); shadow NEEDS_REVIEW (HAC t = -2.88) | tool bug, MEDIUM |
| risk/06_red_zone_250_scattered | independence not NEEDS_REVIEW (10 well-spread exceptions) | NEEDS_REVIEW "exceptions cluster (LR_cc = 13.79)" | consistent with doc (LR_cc rejects); misleading wording, LOW |
| risk/11_es_95_too_small_30pct | es_backtest NEEDS_REVIEW | CONFIRMED_ERROR in var_input_coherence | **reviewer error**: 0.7 x ES95 = 1.44 sigma < VaR95 = 1.645 sigma, the file really has ES < VaR on every day; tool is right |

## Findings (tool problems)

### HIGH

**H1. False CONFIRMED_ERROR: constant target printed every month under a declared quarterly schedule.**
Case `portfolio/10_quarterly_declared_monthly_constant_rows`. Raw weights are identical on all 36 dates (the finding
itself says "without the drift correction 0.00x"), rules.yaml declares `rebalance_frequency: quarterly`, prices present.
Expected: no CONFIRMED_ERROR (no weight changed, so nothing changed outside the schedule). Got: CONFIRMED_ERROR
"Weights change on 23 date(s) outside the declared quarterly rebalance schedule, not explained by drift". The title is
false: the delivered weights did not change; the "change" is the difference between the target and the market-drifted
previous weights. A model-portfolio table that lists the same target every month is a common export.
Cause: `portfolio.py` L665 `traded = to > ZERO_TURNOVER` uses the drift-adjusted turnover `to`, and L684-L685
(`off = df[df["traded"] & ~df["rebalance_date"]]`, `off_big`) and the emission at L713-L714 never check that the raw
delivered weights differ (`raw`, computed at L664, is available). Fix idea: require `turnover_without_drift > tol` for
an off-schedule "change" (or downgrade to INFO/NEEDS_REVIEW saying the rows imply monthly restoring trades).

**H2. Wrong tracking error when the NAV column has missing values (NaN rows are dropped before differencing).**
Case `live/06_nav_with_nan` (expectations met, but the number is wrong). `live_returns.csv` delivered as `nav`, two NaN
NAV days of 250. Tool reports 247 periods and tracking error **1.36%**; the live series is shadow + 4 bps noise per day
(true TE 0.0004 x sqrt(252) = 0.64%; recomputed with NaN returns left as NaN: **0.654%**, 245 periods). The dropped NaN
rows turn two one-day returns into two-day returns that are then compared with one-day shadow returns (max |diff|
1.12e-02 in the integrity text). TE, correlation, HAC t, cumulative gap and the largest-widening date are all
contaminated. With a larger share of missing NAVs this would produce a false "does not track" NEEDS_REVIEW.
Cause: `live.py` L156-L157: `d.dropna(subset=["nav"])` before `groupby(...)["nav"].pct_change()`; should difference
first and drop the NaN returns (or mark the multi-day return NaN).

### MEDIUM

**M1. Monthly record: consecutive periods flagged as a "gap" (false NEEDS_REVIEW), plus HAC test over-rejects at n = 30.**
Case `live/01_monthly_clean`. live.start 2021-07-31 right after backtest_end 2021-06-30 (consecutive month-ends): integrity
says "31 days after the declared backtest end without a reason", because the gap threshold is a fixed 30 calendar
days. Cause: `live.py` L40 `GAP_DAYS = 30`, L335-L336; should scale with the data periodicity (median spacing of the
series x ~1.5), or compare in periods. Same case: shadow check reports "systematically below the shadow backtest, mean
difference -5.98 bps, HAC t = -2.88, p = 0.002" on 30 monthly periods where live = shadow + iid noise (sd 20 bps) - 2 bps.
The plain iid t is -1.62 (not significant). The module's Newey-West value is arithmetically correct (my NW with
3 Bartlett lags: -2.884), but the HAC standard error (2.07 bps) is far below the iid one (3.69 bps) because the
estimator has no small-sample correction. Simulated size of the one-sided 5% test under iid H0: **7.5%** at n = 30
(24: 7.4%, 60: 6.2%, 250: 5.6%, 1000: 4.9%). So at the `live_min_periods` of the monthly profile the "PASS/NEEDS_REVIEW"
cut is about 50% too trigger-happy. Cause: `live.py` `hac_mean_test` L44-L64 (no n/(n-lags) or t(n-1) correction).

**M2. Kupiec "too few exceptions" printed together with an acceptance region that contains the observed count.**
Case `risk/10_zero_exceptions_260_days` (expectation met as documented). 0 exceptions in 260 days at 99%:
finding "99% VaR: too few exceptions (Kupiec p = 0.0222)" while its own text says "acceptance region [0, 6]". The
asymptotic chi-square(1) p-value is used with 2.6 expected exceptions; the exact binomial P(X=0) = 0.073, so the
exact test (which the module computes for the region) does not reject. The module contradicts itself and rejects at
a size above the nominal one. Cause: `risk.py` L528-L542 decide on `k['p_value']` (asymptotic) and ignore the
exact region [lo, hi]. Suggest: decide with the exact region when expected count < ~5, or say "asymptotic".

**M3. Short-only and market-neutral books are judged against long-only 1/N (NEEDS_REVIEW "adds no measurable value").**
Cases `portfolio/02_market_neutral_nothing_declared` and `03_short_only_declared` (not covered by my expectations; the
tool raised NEEDS_REVIEW in vs_naive). For the short-only book: Sharpe -2.34 vs 1/N +2.35, "z = -4.05"; the text then
tells the user to weigh "extra complexity, turnover and concentration" of an "optimiser". The comparator (long 1/N of
the same names) is meaningless for a book with negative net exposure; the status should be INFO or NOT_EXECUTABLE
("comparator not applicable: net exposure <= 0"). `portfolio.py` vs_naive block (around L880-L900).

### LOW

- L1. `risk/06`: independence title "exceptions cluster" and detail "0 cluster(s) hold 0 of the 10 exceptions" when
  only `LR_cc` rejects (LR_uc = 12.96 from the coverage failure; LR_ind = 0.84, p = 0.36). Double-counts the coverage
  failure and states clustering that does not exist (`risk.py` var_independence emission). Doc-consistent, wording wrong.
- L2. `portfolio/07_model_is_one_over_n`: model identical to 1/N prints "z = nan, one-sided p = nan" (`portfolio.py`
  L243-L245, theta = 0). Status NEEDS_REVIEW is reasonable; the text should say "model and 1/N are identical".
- L3. `live/09_favourable_fills_both_sides`: all slippages identical (-15 bps), t = -258775645108291.5 printed
  (`live.py` L62, variance floored at 1e-30 at L60). Cosmetic; should print "no dispersion". Sign handling of the
  slippage is correct (buys below and sells above the model price gave -15.0 bps on both sides, no alert).
- L4. `live/10_live_in_percent_units`: live in percent (x100), shadow check correctly NEEDS_REVIEW, but
  `live_period_integrity` is PASS "verified with a shadow backtest" with beta of live on backtest = 99.6, and
  `live_declared_vs_realised` prints a live max drawdown of -100.5% and annual return -100% (a drawdown below -100% is
  impossible: product of 1+r crossed zero). A units hint ("beta about 100, looks like percent") would be the
  right diagnosis.
- L5. `portfolio/11_monthly_price_frequency`: with month-end prices "enters at the close of the first session after d"
  means a full month of delay (first model return is earned one period later). Numbers match my replication (z = 3.693
  vs 3.69), so it is a documented-semantics note, not a bug.
- L6. Core checks leak into use-case-only folders: every portfolio case shows NEEDS_REVIEW "prices.csv: no adjustment
  flag" and "Market calendar not declared" (core `schema_and_types` / `dates`), which inflates the NEEDS_REVIEW count of
  folders whose rules.yaml is about weights.

## What held (no finding)

- risk: `var_0.99` / `var_97.5` / `var_975` spellings parsed to 99 / 97.5 / 97.5 percent; weekly Fridays are not a gap;
  `day` + `loss` aliases invert the sign correctly; 3 NaN VaR (0.3%) do not alert; `negative_quantile` declared works;
  only-97.5% file gives traffic light NOT_EXECUTABLE; ES < VaR on one day and one duplicated date are CONFIRMED_ERROR;
  two runs of 5 exceptions: Kupiec PASS and LR_ind NEEDS_REVIEW; red zone is NEEDS_REVIEW, never CONFIRMED_ERROR;
  correct ES (Z2 = 0.02) is INFO.
- portfolio: cash row (CASH declared, no price), dollar-neutral book with nothing declared (INFO, not the "missing cash"
  alert), short-only with declared net range, duplicate (date,ticker) rows summed to exactly max_weight, positions of a
  net-zero book with gross 0.8 (normalised by gross, PASS), percent units and a breach in the second portfolio of a
  two-portfolio file are CONFIRMED_ERROR (with `[portfolio PB]` in the text).
- live: boundary dates (first live date = live.start, last = review_date) PASS; exact affine copy (0.9 x bt + 1e-5)
  NEEDS_REVIEW; duplicate row CONFIRMED_ERROR; correct declared Sharpe / CAGR / drawdown give INFO, no
  CONFIRMED_ERROR; decayed edge without shadow gives decay and break NEEDS_REVIEW and shadow NOT_EXECUTABLE.

## Cross-checked statistics (own numpy / math, independent of the module)

| Module | Statistic | Case | Mine | Module |
|---|---|---|---|---|
| risk | Kupiec LR_uc, p | 06 (10 of 250, p=1%) | 12.955, p = 0.0003 | 12.96, p = 0.0003 |
| risk | Kupiec LR_uc | 01 (22/1000 at 2.5%; 9/1000 at 1%) | 0.385; 0.105 | 0.38; 0.10 |
| risk | Christoffersen LR_ind (n00,n01,n10,n11) | 05 (987,2,2,8) | 73.165, p ~ 0 | 73.16, p = 0.0000 |
| risk | LR_ind, LR_cc | 06 (229,10,10,0) | 0.837 (p 0.360); LR_cc 13.793 (p 0.0010) | LR_cc = 13.79 (p = 0.0010) |
| risk | LR_ind, LR_cc | 01 at 97.5% (957,20,20,2) | 2.861 (p 0.0907); LR_cc 3.246 (p 0.1973) | p = 0.091; p = 0.197 |
| risk | LR_ind | 01 at 99% (981,9,9,0) | 0.164 (p 0.686) | p = 0.686, LR_cc p = 0.875 (mine 0.8745) |
| portfolio | drift-adjusted annual turnover | 04 (35 intervals) | 0.6268 total, 0.2152 / yr | 0.63 total, 0.22x |
| portfolio | Jobson-Korkie-Memmel z (daily, T = 759) | 04 | 6.372 (SR 5.61 vs 3.84 annualised) | 6.37, Sharpe 5.61 vs 3.84 |
| portfolio | JKM z, monthly prices (T = 34) | 11 | 3.693 (SR 6.164, 12 periods/yr) | 3.69, Sharpe 6.16 |
| live | tracking error | 04 | 4.874% | 4.87% |
| live | Newey-West t of mean difference (3 lags) | 01 | -2.884 (iid t -1.624) | -2.88 |
| live | Sharpe-difference z, Lo standard errors (iid) | 08 | -2.746 (p 0.0060); with skew/kurtosis -2.734 | -2.75 (p = 0.006) |
| live | PSR of the live Sharpe vs backtest | 08 | 0.00062 | 0.001 (PSR vs backtest, rounded) |
| live | tracking error with NaN NAV rows | 06 | 0.654% (NaN returns kept as NaN) | **1.36%** (see H2) |

Every standard formula the module implements matches; the problems are in inputs handling (H1, H2, M1 gap), in
small-sample behaviour (M1 HAC, M2 Kupiec) and in comparator choice (M3).

## Files

- Generator: `cases_review_v030b/_gen_review.py` (deterministic seeds; rerun reproduces inputs and expectations).
- Cases: `cases_review_v030b/{risk,portfolio,live}/NN_name/` with `expected.json` (`use_case`, `origin: review_v030`).
