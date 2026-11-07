# Response to review v0.3.0 B (risk, portfolio, live)

Reviewer cases: `cases_review_v030b/` (expected.json and generator untouched).
Score on the 33 pre-registered cases: **29/33 before, 30/33 after** (live/01 and portfolio/10 now pass; risk/06,
risk/10 and risk/11 remain "failed" for the reasons under "Disputes"). The three original module batteries
(`cases/usecase_risk`, `usecase_portfolio`, `usecase_live`) stay at 8/8, 11/11 and 10/10 cases with 0 false
positives. `ruff check src tests` is clean; `tests/test_usecase_{risk,portfolio,live}.py` pass.

## Findings

| Finding | Status | Change | Test | New outcome |
|---|---|---|---|---|
| H1 portfolio_turnover false CONFIRMED_ERROR | fixed | `portfolio.py`, check_turnover rows loop: a row is a schedule change only if the raw delivered target differs (`raw > 0.001`) AND there is a trade net of drift; `off`, `off_big`, the schedule bookkeeping and the "changes per year vs declared frequency" test use this. `annual_turnover` stays drift-adjusted (cost measure). New metric `n_target_changes`. The INFO text says that the drift-adjusted turnover is the cost of restoring the target, not a change of the delivered weights | `test_h1_constant_target_quarterly_schedule_no_error`, updated `test_turnover_drift_not_trading_and_churn` | portfolio/10: INFO, no CONFIRMED_ERROR |
| H2 NaN NAV rows dropped before differencing | fixed | `live.py` `_series`: `pct_change(fill_method=None)` before dropping, so a missing NAV gives two NaN returns, never a two-period return; `n_nav_missing` is disclosed in the integrity description. Other places checked: the `return` source drops NaN per row (no differencing); the `dropna` calls on trades act on columns, not on a differenced series | `test_h2_nan_nav_is_not_merged_into_two_day_returns` | live/06: 245 periods, TE 0.654% (was 1.36%) |
| M1a fixed 30-day gap | fixed | `Ctx.gap_limit()`: limit = max(10 days, 1.5 x median spacing of the live series, else of the backtest); fallback 30 days only with fewer than 4 dates. The message states limit and spacing. Weekends and holidays in daily data sit inside the 10-day floor | `test_m1_monthly_consecutive_periods_are_not_a_gap` (also asserts a skipped quarter still flags) | live/01 integrity PASS |
| M1b HAC over-rejects at n=30 | fixed | `hac_mean_test` adds `t_adj` (variance x n/(n-lags-1)), `t_iid`, `p_adj` (t(n-1)); `significantly_below_zero()` uses the t(n-1) critical value and, below 60 periods, also requires the iid t to reject. Own t cdf/ppf (`t_cdf`, `t_ppf`), no scipy. Existing `t`, `se`, `p_value` keys unchanged | `test_t_cdf_matches_known_values`, `test_m1_hac_size_at_n30_is_not_inflated` | live/01 shadow: no alert (iid t -1.62) |
| M2 Kupiec message vs region | fixed | `risk.py` check_coverage: decision = x outside the exact equal-tail region [lo, hi]; exact two-sided p (`binom_two_sided_p`) in title and evidence; asymptotic LR_uc and p kept as "context only". Message and region now always agree. The Basel traffic light already used the exact cumulative binomial (unchanged) | `test_m2_kupiec_decision_agrees_with_exact_region` | risk/10: PASS (see Disputes) |
| M3 short/neutral vs long-only 1/N | fixed | `portfolio.py` check_vs_naive: mean net exposure (ex cash) <= `NAIVE_MIN_NET = 0.1` gives NOT_EXECUTABLE with the reason and a pointer to benchmark_returns.csv | `test_m3_short_only_and_market_neutral_have_no_naive_comparator` | portfolio/02, 03: NOT_EXECUTABLE |
| L1 risk/06 wording | fixed | `risk.py` check_independence: when only LR_cc rejects (LR_ind not rejected, no run of 3+), title "conditional coverage rejected (LR_cc = ...), independence alone not rejected" and no cluster sentence | `test_l1_only_conditional_coverage_rejected_is_not_called_clustering` | wording only; status stays NEEDS_REVIEW (see Disputes) |
| L2 z = nan vs 1/N | fixed | Model identical to 1/N: NEEDS_REVIEW kept (reviewer's expectation for portfolio/07), title "identical to 1/N of the same names: no difference to test", no "nan" | `test_l2_model_identical_to_one_over_n_says_so` | portfolio/07 passes |
| L3 identical slippages | fixed | zero dispersion: t not reported, "all slippages identical, no dispersion to test" | `test_l3_identical_slippages_report_mean_only` | live/09 |
| L4 percent units in live | fixed | integrity NEEDS_REVIEW "units look like percent" when median abs return > 0.5, or beta of live on backtest in (50, 200) with correlation > 0.5 | `test_l4_live_in_percent_units_is_flagged` | live/10 no longer PASS |
| L5 month-end lag | documented | `docs/usecases/portfolio.md` (`portfolio_vs_naive`) | - | - |
| L6 core checks in use-case-only folders | noted, not changed | "prices.csv: no adjustment flag" and "calendar not declared" come from core `schema_and_types` / `dates`; core is untouched as instructed | - | - |

Docs updated: `docs/usecases/{risk,live,portfolio}.md`. `docs/CHECKS.md` was not regenerated (catalog texts unchanged).

## Monte Carlo of the HAC rule

numpy, seed 1, 2000 reps per cell, one-sided 5% test of mean < 0, Bartlett lags floor(4 (n/100)^(2/9)).

| n | DGP | asymptotic HAC (old) | t(n-1) only | factor + t(n-1) | **factor + t(n-1) and iid t (adopted below 60)** | iid t |
|---|---|---|---|---|---|---|
| 24 | AR(0) | 8.1% | 7.3% | 5.9% | **4.8%** | 5.8% |
| 24 | AR(1) 0.3 | 10.8% | 10.0% | 9.0% | **8.7%** | 11.5% |
| 30 | AR(0) | 8.6% | 8.0% | 6.6% | **5.0%** | 5.7% |
| 30 | AR(1) 0.3 | 10.2% | 9.6% | 8.2% | **7.8%** | 11.5% |
| 60 | AR(0) | 6.2% | 5.6% | 4.8% | 4.2% | 5.1% |
| 60 | AR(1) 0.3 | 7.8% | 7.6% | 7.0% | 6.9% | 10.4% |

AR(0) size at n=30 is 5.0% (target met). With AR(1) rho 0.3 it is 7.8%: above 6%, but the best of the variants, and
the excess comes from the autocorrelation itself at n=30 (the iid t reaches 11.5%). Tightening further would cost
power on true alerts, so I stopped there. The regression test uses 1500 seeded AR(0) reps and requires size < 7%.

## Disputes (expected.json not edited)

- **risk/11**: the reviewer's own error (admitted). ES95 = 0.7 x the true value is below VaR95 on every day, so the
  CONFIRMED_ERROR in var_input_coherence is correct.
- **risk/10**: expected NEEDS_REVIEW "too few". That expectation encodes the asymptotic p = 0.022, which finding M2
  shows to contradict the printed region [0, 6] (exact P(X=0) = 0.073). Following M2, the exact region now decides, so
  0 exceptions in 260 days at 99% is PASS and the asymptotic LR stays in the text as context. The same data with 1000
  days (P = 4e-5) is still "too few" (tested). The case therefore fails by design.
- **risk/06**: expected independence not NEEDS_REVIEW. The documented rule is Christoffersen's LR_cc (coverage plus
  independence); with 10 exceptions in 250 days LR_cc = 13.79 rejects, which the reviewer classes as doc-consistent
  with a LOW wording problem. I fixed the wording (L1) and kept the status. Downgrading would be a policy change
  (one line) if the reviewer's reading is preferred.
- **Existing test `test_turnover_drift_not_trading_and_churn`** asserted CONFIRMED_ERROR for the same 60/40 target
  printed every 10 sessions under an annual schedule. That is exactly the reviewer's H1 scenario (identical target,
  only drift), so the test changed: a constant target gives INFO, and a target that really moves (60/40, 50/50,
  70/30, 40/60) still gives CONFIRMED_ERROR. Residual limit: a system that really trades back to target every month
  and exports the same target row is indistinguishable from a constant model table; the INFO text says so.
