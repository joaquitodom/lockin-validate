# Strategy validation report

Tool: lockin-validate 0.1.0. Run: 2026-10-27T11:34:48. Input folder: `quickstart_inputs`. Profile: equities_daily. Declared strategy version: 1.0.

> **Disclaimer.** This is an automated, offline technical review of the inputs delivered. It makes no claim about future or past profitability, it is not a certification or an audit opinion, and it is not an independent professional approval: a qualified person must review the findings, the NEEDS_REVIEW items and the limitations before any decision. It is not investment advice.

Automated, local, offline review: no network and no remote AI were used. Every conclusion has its procedure and its evidence (CSV line numbers, dates, values).

## Summary

- Confirmed errors: **1**
- Items that need human review: **1**
- Checks not executable (missing information): **10**
- Passed within scope: **16**

## Scope

Inputs present: prices, signals, trades, positions, costs, rules, declared_results, version.

Inputs absent: fundamentals, universe, security_master, corporate_actions, reference_prices, returns, trials, llm_checklist.

Review date used for future dates: 2026-10-20.

Calendar: nyse (declared: yes, by rules.yaml).

Conventions used: calendar=nyse (rules.yaml); periods_per_year=252 (rules.yaml); initial_cash=100,000.00 (rules.yaml); stale_run=10 (default); jump_threshold=0.4 (default); review_date=2026-10-20 (rules.yaml).

Reconstruction conventions: initial_cash=100,000.00; valuation=close; commission_rate=0.0025; slippage_rate=0; leverage=no; short_selling=no.

## Inputs and versions (manifest)

| Input | File | Present | Rows | sha256 |
|---|---|---|---|---|
| prices | prices.csv | yes | 1152 | c5af45afe939645ec9cda55f2be505ea45c50faae40367408ef323447ac8d7ba |
| signals | signals.csv | yes | 48 | 0282d6252e472127911fbdc3f6d59ab9c82bc58527e612df1a9dcbfd1388cc48 |
| trades | trades.csv | yes | 28 | ac4239b6ab225be85c03ff310135976eb39b9498f3cd21e58f2a452e9eff1712 |
| positions | positions.csv | yes | 18 | f101c64e1de72a7cb401197d198bf06d977e0c2e8defbfe46e924f2affd3f5f6 |
| costs | costs.csv | yes | 2 | c5424573b1f273a562eec463e6f50f0e3bdb51f0a041340f2a42d44a60515182 |
| fundamentals | fundamentals.csv | no | - | - |
| universe | universe.csv | no | - | - |
| security_master | security_master.csv | no | - | - |
| corporate_actions | corporate_actions.csv | no | - | - |
| reference_prices | reference_prices.csv | no | - | - |
| returns | returns.csv | no | - | - |
| trials | trials.csv | no | - | - |
| rules | rules.yaml | yes | - | 33b8e3417af285e6867b7c6586f2fba27f2483ac6869a98b8eb0335087b54f3f |
| declared_results | declared_results.json | yes | - | 8054c85448230bdaccac3e5944c8452c827b3600b2d8cfbfd2a3b77235b2a331 |
| llm_checklist | llm_checklist.json | no | - | - |
| version | version.txt | yes | - | 8a4434489576de41f28a2d1d6e9d15e53deac6b48c2a4f416a52b7584a92964f |

## Checks run

| Check | Block | Status |
|---|---|---|
| schema_and_types | input | Pass (within scope) |
| duplicates | data | Pass (within scope) |
| dates | data | Pass (within scope) |
| essential_fields | data | Pass (within scope) |
| coverage | data | Pass (within scope) |
| trade_before_signal | data | Pass (within scope) |
| signal_data_after_decision | data | Pass (within scope) |
| stale_prices | data | Pass (within scope) |
| price_jumps | data | Pass (within scope) |
| corporate_actions | data | Not executable |
| reference_accuracy | data | Not executable |
| pit_fundamentals | data | Not executable |
| survivorship | data | Not executable |
| ticker_identity | data | Not executable |
| reconstruction | reconstruction | Pass (within scope) |
| positions_reconciliation | reconstruction | Pass (within scope) |
| results_reconciliation | reconstruction | Pass (within scope) |
| lookahead | strategy | Pass (within scope) |
| omitted_costs | strategy | Confirmed error |
| metrics | strategy | Pass (within scope) |
| rules_vs_implementation | strategy | Pass (within scope) |
| sharpe_significance | statistics | Needs human review |
| sharpe_autocorrelation | statistics | Pass (within scope) |
| trials_declared | statistics | Not executable |
| deflated_sharpe | statistics | Not executable |
| multiple_testing | statistics | Not executable |
| pbo | statistics | Not executable |
| llm_lookahead_risk | statistics | Not executable |

## Confirmed errors

### 1. The declared result is reproduced only WITHOUT the declared costs (commission) (`omitted_costs`)

Declared: commission 0.0025, slippage 0 of notional. In the trades: commission absent, slippage 0. The declared total_return (+0.0461) matches the no-cost scenario (+0.0461) and not the declared-cost one (+0.0265). Consequence of the same problem (not a separate finding): with the declared costs applied, the delivered trades leave cash negative on 63 dates (minimum -914.14), because they were sized without costs.

Procedure: Declared costs (rules.yaml or costs.csv; commission and slippage separately) are contrasted with the effective ones in trades.csv (commission column; execution price vs the close of the day) and with the cost scenario that reproduces the declared total_return. Each scenario is a full reconstruction from the initial cash: 'no costs' (zero commission and slippage), 'declared costs' (only the declared ones, not added to those in trades.csv) and 'commissions in trades.csv'. Total return tolerance: 0.005.

Evidence:

| source | fraction | value | scenarios | reproduced_by |
|---|---|---|---|---|
| declared commission (rules.yaml) | 0.0025 | - | - | - |
| declared slippage (rules.yaml) | 0 | - | - | - |
| effective commission (sum commission / notional) | - | - | - | - |
| effective slippage (trade price vs close, weighted) | 0 | - | - | - |
| turnover (traded notional / initial cash) | - | 7.8484 | - | - |
| declared total_return | - | 0.046093 | no costs=0.046093; declared costs=0.026472 | no costs |

Suggested action (priority high): Recompute the result with the declared costs and report both.

## Items that need human review

### 1. Sharpe ratio not distinguishable from zero even as a single test (PSR = 0.74) (`sharpe_significance`)

Annualised Sharpe 0.90 over 0.49 years (NAV reconstructed from trades); 95% interval -1.90 to 3.71. With this Sharpe about 3.3 years of history would be needed for 95% confidence (Minimum Track Record Length). Conditional result: earlier blocks have confirmed errors (omitted_costs); these statistics describe the series as delivered, not a corrected one.

Procedure: Per-period Sharpe = mean / std (ddof 1) of the returns; standard error under i.i.d. returns sqrt((1 + SR^2/2) / T) (Lo 2002) and with skewness and kurtosis sqrt((1 - g3 SR + (g4 - 1)/4 SR^2) / (T - 1)); PSR(0) = Phi(SR sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2)) and Minimum Track Record Length at 95% (Bailey and Lopez de Prado 2012). Threshold PSR >= 0.95.

Evidence:

| source | T | years | sharpe_per_period | sharpe_annualised_sqrt_rule | se_iid_per_period | se_nonnormal_per_period | ci95_annualised | t_stat | skewness | kurtosis | psr_vs_0 | min_track_record_periods | min_track_record_years |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NAV reconstructed from trades | 124 | 0.492 | 0.0568969 | 0.90321 | 0.0898753 | 0.0900939 | -1.89998, 3.7064 | 0.633577 | 0.0522767 | 2.67479 | 0.736152 | 835.4 | 3.31508 |

Suggested action (priority medium): Do not present the result as statistically significant; extend the track record.

## Checks not executable (missing information)

### 1. Declared corporate actions reflected in prices (`corporate_actions`)

Reason: missing required inputs: corporate_actions.

Suggested action (priority medium): Provide corporate_actions to enable this check.

### 2. Accuracy against an independent reference (`reference_accuracy`)

Reason: missing required inputs: reference_prices.

Suggested action (priority medium): Provide reference_prices to enable this check.

### 3. Point-in-time fundamentals (`pit_fundamentals`)

Reason: missing required inputs: fundamentals.

Suggested action (priority medium): Provide fundamentals to enable this check.

### 4. Survivorship (delisted members) (`survivorship`)

Reason: missing required inputs: universe.

Suggested action (priority medium): Provide universe to enable this check.

### 5. Ticker identity (recycled tickers) (`ticker_identity`)

Reason: missing security_master.csv (ticker -> entity_id); the price heuristic found no gap with a level shift, which does not prove identity.

Suggested action (priority medium): Provide security_master.csv.

### 6. Declared number of trials (`trials_declared`)

Reason: neither declared_results.n_trials nor trials.csv: the number of configurations tried is unknown, so the Sharpe cannot be deflated for selection.

Suggested action (priority medium): Declare n_trials (every configuration tried, including discarded ones) and deliver trials.csv.

### 7. Deflated Sharpe ratio (selection among trials) (`deflated_sharpe`)

Reason: number of trials unknown (declared_results.n_trials or trials.csv); with N = 1 the DSR equals the PSR (0.736), the most optimistic possible case.

Evidence:

| dsr_with_n_1 |
|---|
| 0.736152 |

Suggested action (priority medium): Declare n_trials and deliver trials.csv.

### 8. Multiple-testing haircut (`multiple_testing`)

Reason: number of trials unknown (declared_results.n_trials or trials.csv).

### 9. Probability of backtest overfitting (CSCV) (`pbo`)

Reason: missing required inputs: trials (at least 2 configurations).

Suggested action (priority medium): Provide trials (at least 2 configurations) to enable this check.

### 10. LLM look-ahead risk (`llm_lookahead_risk`)

Reason: missing required inputs: llm_checklist.

Suggested action (priority medium): Provide llm_checklist to enable this check.

## Passed within scope

- `schema_and_types`: Input structure and types. Every table present has its required columns and its dates and numbers parse. Procedure: Header compared with the input schema; dates and numbers coerced.
- `duplicates`: No duplicates. No repeated (ticker, date) in prices and no repeated trades, signals or positions. Procedure: df.duplicated on the natural keys of each table.
- `dates`: Dates consistent. No future dates (limit 2026-10-20), no non-session days (nyse calendar), no non-positive closes and no inconsistent OHLC. Procedure: Row-wise comparison against review date, calendar and OHLC range.
- `essential_fields`: Essential fields complete. No empty cell in the essential fields of the tables present. Procedure: Search for empty cells in the original CSV.
- `coverage`: Price coverage sufficient. Every traded ticker has a price on its trade dates; no session gaps; the declared period is covered. Procedure: Tickers/dates of trades crossed with prices and the calendar.
- `trade_before_signal`: Every buy has an earlier signal. Each buy has at least one signal of its ticker with decision_time earlier or equal. Procedure: Search of a previous signal per ticker.
- `signal_data_after_decision`: Signals use data not later than the decision. data_date <= decision_time for every signal. Procedure: data_date > decision_time per row.
- `stale_prices`: No frozen prices. No run of 10 or more identical consecutive closes. Procedure: Scan of consecutive closes per ticker.
- `price_jumps`: No one-period price move larger than 40%.  Procedure: close_t / close_(t-1) - 1 per ticker on consecutive dates of the series; split-like if the ratio is within 3% of 1/2, 1/3, 1/4, 1/5, 1/10, 2, 3, 4, 5, 10...; spike if the next day reverts by more than 25%. Threshold 40% (conventions.jump_threshold).
- `reconstruction`: Reconstruction complete with the available inputs. 28 trades applied over 125 dates; initial NAV 100,000.00 and final 104,609.34; costs 0.00. Procedure: Loop per date with the declared conventions (see metrics.reconstruction).
- `positions_reconciliation`: Declared positions reconciled. 18 declared positions match the reconstruction (tolerance 1e-06). Procedure: Comparison per (date, ticker).
- `results_reconciliation`: Declared results reconciled. Every declared metric present is within tolerance. Procedure: Daily NAV reconstructed from trades -> metrics with the declared convention (periods_per_year=252, sharpe=arithmetic, std_ddof=1, risk_free_annual=0, annual_return=geometric, returns=simple) -> comparison with declared_results.json using explicit tolerances.
- `lookahead`: No early use of data according to the declared dates (data_date and availability). 48 signals evaluated: according to data_date and the availability timestamps, all use data available before the decision. Scope: the data_date declared by the strategy owner is trusted; the hint test (correlation with the subsequent return) gives -0.37, no hint. Procedure: For each signal: (ticker, data_date) -> availability in prices.csv (available_from) or fundamentals.csv (max of filing_date and available_from); error if availability > decision_time.
- `metrics`: Declared metrics reproduced. They match the declared convention: sharpe, annual_return, max_drawdown. Procedure: Recomputed on the reconstructed NAV with the declared convention (periods_per_year=252, sharpe=arithmetic, std_ddof=1, risk_free_annual=0, annual_return=geometric, returns=simple) and with common alternatives: 252/260/365/360 periods, arithmetic vs geometric mean, std ddof 1 vs 0, with and without a risk-free rate (0/2/4/5%), simple vs log returns; max drawdown on the NAV, as a positive number, worst single period and sum of returns without compounding.
- `rules_vs_implementation`: The trades implement the declared rule. 6 rebalance dates with holdings equal to the top 3; weights within 10% of 1/N; no trades off schedule. Scope: the signal column delivered is re-ranked; the signal computation itself is not verified. Procedure: From rules.yaml: ranking on `signal` (desc), top 3, monthly rebalance (first_day), equal_weight. On each rebalance date the top N of signals.csv is compared with the reconstructed holdings at the close of that day, and the weights with 1/N (tolerance 10%).
- `sharpe_autocorrelation`: No material Sharpe inflation from autocorrelation. Naive annualised Sharpe 0.90, Lo-adjusted 1.48 (ratio 0.61); Ljung-Box p = 0.767. Conditional result: earlier blocks have confirmed errors (omitted_costs); these statistics describe the series as delivered, not a corrected one. Procedure: Sample autocorrelations rho_1..rho_10 of the period returns (rho_k = 0 beyond lag 10); Lo (2002) factor eta(q) = q / sqrt(q + 2 sum (q - k) rho_k) with q = 252, compared with the naive sqrt(q); Ljung-Box test on the same lags. Review if the naive annualised Sharpe exceeds the adjusted one by more than 10% and the autocorrelation is statistically significant.

## Reconstructed metrics

| Metric | Value |
|---|---|
| initial_nav | 100,000.00 |
| final_nav | 104,609.34 |
| total_return | 0.0460934 |
| annual_return | 0.0959033 |
| sharpe | 0.90321 |
| max_drawdown | -0.0665513 |
| annual_volatility | 0.107787 |
| n_trades | 28 |
| n_periods | 124 |
| peak_date | 2024-04-29 |
| trough_date | 2024-06-03 |

## Statistics

Return series: NAV reconstructed from trades; periods per year: 252; declared trials: -; trials in trials.csv: 0.

- Sharpe (annualised, sqrt rule): 0.90321; PSR(0): 0.736152; minimum track record: 3.31508 years.
- Lo (2002) adjusted annualised Sharpe: 1.48443 (naive 0.90321).

## Transformation log

Originals were not modified. These are the derivations made on working copies (applied = used by the review; proposed = suggested fix, NOT applied).

| Input | Operation | Kind | Reason | Before | After | Rows affected |
|---|---|---|---|---|---|---|
| prices | sort(ticker, date) | applied | working table sorted for the checks | order=file | order=ticker, date | 0 |

## Limitations and pending human review

- The review judges the internal coherence of the inputs delivered. It does not query external sources: a wrong price that is coherent with everything else is not detected (unless reference_prices.csv is provided).
- The reconstruction starts from the initial cash, values at the close and uses the trades as delivered (executed price and commission of trades.csv). Declared costs are not imputed in the main reconstruction: they are contrasted in omitted_costs. Dividends, splits and other corporate actions are not modelled unless they are in adjusted prices; large jumps are flagged.
- A results curve alone does not validate the code, the execution or the absence of look-ahead: reproducing the declared NAV only proves the delivered trades are coherent with that NAV.
- rules_vs_implementation re-ranks the signal column delivered: it verifies the selection, not how the signal was computed. lookahead trusts the declared data_date; the hint test (correlation with the subsequent return) only detects gross cases.
- Rule re-execution supports only: ranking on one signal column, top N, periodic rebalance (monthly, weekly, daily) and equal weights. Any other rule is NOT_EXECUTABLE and needs a manual review.
- Statistical checks (PSR, deflated Sharpe, haircut, PBO) are conditional on the declared number of trials and on the data being correct; they say nothing about broken data or look-ahead.
- The LLM look-ahead score rests on declarations; memorisation is not tested.
- What is missing from the inputs (history, availability timestamps, universe, identity master) is a scope finding: it is never repaired or imputed.
- Thresholds and tolerances are documented choices, not laws; they are listed in docs/CONVENTIONS.md and can be changed in rules.yaml.
- corporate_actions: not executable (missing required inputs: corporate_actions).
- reference_accuracy: not executable (missing required inputs: reference_prices).
- pit_fundamentals: not executable (missing required inputs: fundamentals).
- survivorship: not executable (missing required inputs: universe).
- ticker_identity: not executable (missing security_master.csv (ticker -> entity_id); the price heuristic found no gap with a level shift, which does not prove identity).
- trials_declared: not executable (neither declared_results.n_trials nor trials.csv: the number of configurations tried is unknown, so the Sharpe cannot be deflated for selection).
- deflated_sharpe: not executable (number of trials unknown (declared_results.n_trials or trials.csv); with N = 1 the DSR equals the PSR (0.736), the most optimistic possible case).
- multiple_testing: not executable (number of trials unknown (declared_results.n_trials or trials.csv)).
- pbo: not executable (missing required inputs: trials (at least 2 configurations)).
- llm_lookahead_risk: not executable (missing required inputs: llm_checklist).

Review items a person must close: sharpe_significance.

## Suggested actions (prioritised)

| Priority | Check | Status | Action |
|---|---|---|---|
| high | omitted_costs | Confirmed error | Recompute the result with the declared costs and report both. |
| medium | sharpe_significance | Needs human review | Do not present the result as statistically significant; extend the track record. |
| medium | corporate_actions | Not executable | Provide corporate_actions to enable this check. |
| medium | reference_accuracy | Not executable | Provide reference_prices to enable this check. |
| medium | pit_fundamentals | Not executable | Provide fundamentals to enable this check. |
| medium | survivorship | Not executable | Provide universe to enable this check. |
| medium | ticker_identity | Not executable | Provide security_master.csv. |
| medium | trials_declared | Not executable | Declare n_trials (every configuration tried, including discarded ones) and deliver trials.csv. |
| medium | deflated_sharpe | Not executable | Declare n_trials and deliver trials.csv. |
| medium | pbo | Not executable | Provide trials (at least 2 configurations) to enable this check. |
| medium | llm_lookahead_risk | Not executable | Provide llm_checklist to enable this check. |

---

*This is an automated, offline technical review of the inputs delivered. It makes no claim about future or past profitability, it is not a certification or an audit opinion, and it is not an independent professional approval: a qualified person must review the findings, the NEEDS_REVIEW items and the limitations before any decision. It is not investment advice.*
