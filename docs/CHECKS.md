# Check catalogue

Generated from `src/lockin_validate/catalog.py` by `docs/generate_checks_md.py`. The same text is available offline
with `lockin-validate explain <check_id>` and through the MCP tool `explain_check`.

Every check returns findings with one status: CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE (with the reason), INFO
(a note that is not an alert, see docs/ALERT_POLICY.md) or PASS (within its scope). Thresholds and formulas are in
docs/CONVENTIONS.md; the inputs of the 0.2.0 checks are in docs/INPUT_SPEC.md. Checks added in 0.2.0 carry a
"Motivation" line: the failure of the LockIn case study that each one would have caught.

Blocks run in this order: input, data, reconstruction, strategy, statistics. Statistics are conditional on the data
being correct ("data first, reconstruction second, statistics third").

| Check | Block | Title |
|---|---|---|
| [`schema_and_types`](#schema_and_types) | input | Input structure and types |
| [`duplicates`](#duplicates) | data | Duplicates |
| [`dates`](#dates) | data | Impossible or inconsistent dates and prices |
| [`essential_fields`](#essential_fields) | data | Missing essential fields |
| [`coverage`](#coverage) | data | Price coverage |
| [`trade_before_signal`](#trade_before_signal) | data | Trade before its signal |
| [`signal_data_after_decision`](#signal_data_after_decision) | data | Signal computed with data after its decision time |
| [`stale_prices`](#stale_prices) | data | Stale quotes (frozen price) |
| [`price_jumps`](#price_jumps) | data | Split-like jumps and bad ticks |
| [`corporate_actions`](#corporate_actions) | data | Declared corporate actions reflected in prices |
| [`reference_accuracy`](#reference_accuracy) | data | Accuracy against an independent reference |
| [`pit_fundamentals`](#pit_fundamentals) | data | Point-in-time fundamentals |
| [`survivorship`](#survivorship) | data | Survivorship (delisted members) |
| [`ticker_identity`](#ticker_identity) | data | Ticker identity (recycled tickers) |
| [`reconstruction`](#reconstruction) | reconstruction | Reconstruction of positions, cash and NAV |
| [`positions_reconciliation`](#positions_reconciliation) | reconstruction | Reconciliation of declared positions |
| [`results_reconciliation`](#results_reconciliation) | reconstruction | Reconciliation of declared results |
| [`lookahead`](#lookahead) | strategy | Future information in the signals |
| [`omitted_costs`](#omitted_costs) | strategy | Omitted costs |
| [`metrics`](#metrics) | strategy | Metric errors |
| [`rules_vs_implementation`](#rules_vs_implementation) | strategy | Declared rules vs implementation |
| [`sharpe_significance`](#sharpe_significance) | statistics | Statistical significance of the Sharpe ratio |
| [`sharpe_autocorrelation`](#sharpe_autocorrelation) | statistics | Sharpe annualisation under autocorrelation |
| [`trials_declared`](#trials_declared) | statistics | Declared number of trials |
| [`deflated_sharpe`](#deflated_sharpe) | statistics | Deflated Sharpe ratio |
| [`multiple_testing`](#multiple_testing) | statistics | Multiple-testing haircut |
| [`pbo`](#pbo) | statistics | Probability of backtest overfitting |
| [`llm_lookahead_risk`](#llm_lookahead_risk) | statistics | LLM look-ahead risk |
| [`coverage_drift`](#coverage_drift) | data | Coverage drift of inputs |
| [`input_sufficiency`](#input_sufficiency) | data | Names scored with too few inputs |
| [`dividend_corporate_actions`](#dividend_corporate_actions) | data | Dividends and corporate actions: adjusted vs as-traded prices |
| [`protocol_integrity`](#protocol_integrity) | statistics | Research protocol integrity |
| [`benchmark_fit`](#benchmark_fit) | strategy | Benchmark fit |
| [`liquidity_participation`](#liquidity_participation) | strategy | Participation in traded volume |
| [`cost_sensitivity`](#cost_sensitivity) | strategy | Sensitivity of the result to trading costs |
| [`stability_and_concentration`](#stability_and_concentration) | statistics | Stability across subperiods and concentration of the P&L |
| [`conditional_rule_activation`](#conditional_rule_activation) | statistics | Activation of conditional rules in and out of sample |

## schema_and_types

**Input structure and types** (block: input)

- What it checks: Required columns per table (with aliases), unparseable dates and numbers, unknown trade sides, missing price adjustment flag.
- Why it matters: A malformed input silently drops rows or misreads values; every later check depends on this one.
- How to fix: Follow docs/INPUT_SPEC.md: ISO 8601 dates, dot decimal, canonical column names.
- Allows concluding: Inputs are well formed.
- Does not allow: Anything about the values themselves.
- Required inputs: none
- Optional inputs: prices, signals, trades, positions, costs, fundamentals, universe, security_master, corporate_actions, reference_prices, returns, trials, benchmark_returns, universe_returns, unadjusted_prices, dividends, run_log, regimes

## duplicates

**Duplicates** (block: data)

- What it checks: Repeated (ticker, date) prices, repeated trades, signals and positions.
- Why it matters: Two prices for one day make the valuation depend on file order; a duplicated trade is counted twice.
- How to fix: Keep one row per natural key; resolve conflicting values with the original source.
- Allows concluding: Probable duplicates with their impact.
- Does not allow: Telling legitimate partial fills apart without trade ids.
- Required inputs: prices
- Optional inputs: trades, signals, positions

## dates

**Impossible or inconsistent dates and prices** (block: data)

- What it checks: Future dates, rows on non-session days of the declared calendar (NYSE / BYMA / none), non-positive closes, inconsistent OHLC, trades out of chronological order.
- Why it matters: Shifted dates (time zones, UTC stamps) misalign returns and signals; impossible prices corrupt valuation.
- How to fix: Normalise timestamps to the exchange session date; declare the calendar.
- Allows concluding: Rows that cannot be real under the declared calendar.
- Does not allow: Confirming a non-session day as an error when no calendar is declared.
- Required inputs: prices
- Optional inputs: trades, signals, positions, rules

## essential_fields

**Missing essential fields** (block: data)

- What it checks: Empty cells in key columns of the original CSV.
- Why it matters: Rows without a date, ticker, quantity or price cannot be used and bias the reconstruction.
- How to fix: Fill the fields or remove the rows with a written justification.
- Allows concluding: Unusable rows.
- Does not allow: -
- Required inputs: prices
- Optional inputs: trades, signals, positions

## coverage

**Price coverage** (block: data)

- What it checks: Traded tickers without prices, trades on dates without a price, session gaps inside each series (full calendar when declared), declared period not covered.
- Why it matters: A gap concentrates several days of return in one, or values positions with stale prices.
- How to fix: Complete the series; mark suspensions explicitly instead of deleting dates.
- Allows concluding: Scope limits of the reconstruction.
- Does not allow: Repairing missing data.
- Required inputs: prices
- Optional inputs: trades, rules

## trade_before_signal

**Trade before its signal** (block: data)

- What it checks: Buys timestamped before any signal of the ticker.
- Why it matters: A trade that precedes its signal cannot come from it: timestamps are wrong or the signal is not the one used.
- How to fix: Fix timestamps; deliver the signals actually used.
- Allows concluding: Trades the delivered signals cannot explain.
- Does not allow: -
- Required inputs: trades, signals
- Optional inputs: none

## signal_data_after_decision

**Signal computed with data after its decision time** (block: data)

- What it checks: data_date later than decision_time in signals.csv.
- Why it matters: Direct look-ahead declared in the signal file itself.
- How to fix: Recompute signals with data <= decision.
- Allows concluding: Signals that use future data according to their own declaration.
- Does not allow: Detecting look-ahead when data_date is wrong.
- Required inputs: signals, signals(data_date)
- Optional inputs: none

## stale_prices

**Stale quotes (frozen price)** (block: data)

- What it checks: Runs of identical consecutive closes (conventions.stale_run, default 10), crossed with trade dates.
- Why it matters: A stopped feed or a terminal price makes the asset look riskless and lets the strategy trade at prices nobody could get.
- How to fix: Replace with a live source or declare the asset halted.
- Allows concluding: Valuation or trading with an expired price.
- Does not allow: Telling illiquidity from a stopped feed without volume data.
- Required inputs: prices
- Optional inputs: trades

## price_jumps

**Split-like jumps and bad ticks** (block: data)

- What it checks: One-period moves above conventions.jump_threshold (default 40%), classified as split-like, one-day spikes that revert, or unexplained.
- Why it matters: An unadjusted split shows a loss or gain that never existed; a bad tick creates fake extremes.
- How to fix: Confirm corporate actions with the source and adjust the series.
- Allows concluding: Moves that must be explained.
- Does not allow: Proving an error: real events also jump.
- Required inputs: prices
- Optional inputs: corporate_actions

## corporate_actions

**Declared corporate actions reflected in prices** (block: data)

- What it checks: For each split in corporate_actions.csv, whether the price series still shows the 1/ratio move.
- Why it matters: An 'adjusted' series that keeps the split move is not adjusted.
- How to fix: Re-adjust the history for the declared actions.
- Allows concluding: Declared splits not applied.
- Does not allow: Detecting undeclared actions (see price_jumps).
- Required inputs: prices, corporate_actions
- Optional inputs: none

## reference_accuracy

**Accuracy against an independent reference** (block: data)

- What it checks: Daily returns (not levels) compared with reference_prices.csv per ticker; Wilson interval of the differing rate.
- Why it matters: Coherent but wrong prices are invisible to internal checks.
- How to fix: Check differing days against the primary source.
- Allows concluding: Days where two sources disagree.
- Does not allow: Deciding which source is right.
- Required inputs: prices, reference_prices
- Optional inputs: none

## pit_fundamentals

**Point-in-time fundamentals** (block: data)

- What it checks: Publication before period end (impossible), available_from earlier than filing_date (data exposed before publication), missing publication dates, implausibly short (<20 days) or long (>120 days) lags.
- Why it matters: Using a balance sheet before it was public is pure look-ahead; a period end copied as filing date hides it.
- How to fix: Store the original filing date and expose each value only from that date.
- Allows concluding: Rows that break point-in-time.
- Does not allow: Checking dates against the regulator's index.
- Required inputs: fundamentals
- Optional inputs: signals
- References: Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.

## survivorship

**Survivorship (delisted members)** (block: data)

- What it checks: Universe members that left inside the window without prices (or with prices ending early); buys outside membership. Without universe.csv only a heuristic for survivor-only panels runs.
- Why it matters: A universe built from today's survivors removes the losers and inflates returns.
- How to fix: Add delisted members with prices up to their exit.
- Allows concluding: Missing delisted members.
- Does not allow: Quantifying the effect without re-running the strategy.
- Required inputs: prices, universe
- Optional inputs: fundamentals, trades
- References: Brown, S., Goetzmann, W., Ibbotson, R. and Ross, S. (1992). Survivorship Bias in Performance Studies. Review of Financial Studies 5(4), 553-580.

## ticker_identity

**Ticker identity (recycled tickers)** (block: data)

- What it checks: Tickers mapped to two entities in security_master.csv whose prices or fundamentals span both; heuristic of long gap plus level shift.
- Why it matters: Two companies under one symbol create a fictitious return at the seam.
- How to fix: Join histories by entity_id, not ticker.
- Allows concluding: Mixed entities.
- Does not allow: Confirming identity without a master.
- Required inputs: prices, security_master
- Optional inputs: fundamentals

## reconstruction

**Reconstruction of positions, cash and NAV** (block: reconstruction)

- What it checks: Daily positions, cash and NAV rebuilt from trades with explicit conventions; negative cash without leverage, negative quantities without short selling, unvalued positions.
- Why it matters: Only a reconstructed ledger lets the reviewer reproduce the declared numbers.
- How to fix: Declare leverage/short selling or fix initial cash and trades.
- Allows concluding: A reproducible NAV or the list of breaks.
- Does not allow: Proving execution happened (needs third-party statements).
- Required inputs: trades, prices
- Optional inputs: rules
- References: Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley. CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.

## positions_reconciliation

**Reconciliation of declared positions** (block: reconstruction)

- What it checks: Declared positions vs reconstructed holdings per (date, ticker).
- Why it matters: A mismatch means missing or extra trades.
- How to fix: Find the missing trades around those dates.
- Allows concluding: Breaks between ledger and declared positions.
- Does not allow: -
- Required inputs: trades, prices, positions
- Optional inputs: none
- References: CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.

## results_reconciliation

**Reconciliation of declared results** (block: reconstruction)

- What it checks: Declared total return, final NAV, number of trades, Sharpe, annual return, max drawdown and curve vs the reconstruction, with explicit tolerances. Return base = initial cash.
- Why it matters: A declared result that the trades cannot reproduce is not supported by the trades.
- How to fix: Review costs, initial cash and missing trades.
- Allows concluding: Declared numbers reproduced or not.
- Does not allow: Validating code or the absence of look-ahead from a matching curve.
- Required inputs: trades, prices, declared_results
- Optional inputs: rules
- References: Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.

## lookahead

**Future information in the signals** (block: strategy)

- What it checks: Each signal's (ticker, data_date) is looked up in prices.csv (available_from) or fundamentals.csv (max of filing_date and available_from); error if available after decision_time. A rank-correlation hint (signal vs subsequent return) flags gross cases without timestamps.
- Why it matters: Look-ahead is the most common reason a backtest fails live.
- How to fix: Recompute signals with as-of data and rerun.
- Allows concluding: Concrete cases of early use.
- Does not allow: Claiming absence of look-ahead for data without timestamps; the hint only catches gross cases.
- Required inputs: signals, signals(data_date), prices(available_from) or fundamentals(available_from) or fundamentals(filing_date)
- Optional inputs: none
- References: Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74. Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.

## omitted_costs

**Omitted costs** (block: strategy)

- What it checks: Declared costs (commission and slippage separately) vs effective costs in trades vs the cost scenario that reproduces the declared return; zero cost with turnover is a review item.
- Why it matters: Many anomalies disappear after trading costs.
- How to fix: Report gross and net results with the actual cost schedule.
- Allows concluding: Costs omitted from the result.
- Does not allow: Concluding when costs are below the tolerance (the test does not discriminate).
- Required inputs: trades, prices
- Optional inputs: rules, costs, declared_results
- References: Novy-Marx, R. and Velikov, M. (2016). A Taxonomy of Anomalies and Their Trading Costs. Review of Financial Studies 29(1), 104-147. CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.

## metrics

**Metric errors** (block: strategy)

- What it checks: Sharpe, annual return and max drawdown recomputed with the declared convention and with common alternatives (252/260/365/360, arithmetic vs geometric, ddof, risk-free, log returns, drawdown variants).
- Why it matters: Most metric discrepancies are conventions; some are errors.
- How to fix: Publish the convention next to each number.
- Allows concluding: Convention vs error.
- Does not allow: Which convention is 'the right one'.
- Required inputs: trades, prices, declared_results
- Optional inputs: rules
- References: Sharpe, W. F. (1994). The Sharpe Ratio. Journal of Portfolio Management 21(1), 49-58. Lo, A. W. (2002). The Statistics of Sharpe Ratios. Financial Analysts Journal 58(4), 36-52. Magdon-Ismail, M. and Atiya, A. (2004). Maximum Drawdown. Risk 17(10), 99-102.

## rules_vs_implementation

**Declared rules vs implementation** (block: strategy)

- What it checks: Re-execution of simple rules (rank on one column, top N, monthly/weekly/daily rebalance, equal weight) and comparison with the reconstructed holdings; anything else is NOT_EXECUTABLE.
- Why it matters: Process verification: the trades must be explained by the written rule.
- How to fix: Align code and written rules.
- Allows concluding: Dates where trades differ from the rule.
- Does not allow: Verifying how the signal itself was computed; coincidence does not prove correctness.
- Required inputs: rules, signals, trades, prices
- Optional inputs: none
- References: Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## sharpe_significance

**Statistical significance of the Sharpe ratio** (block: statistics)

- What it checks: Sharpe standard error (i.i.d. and with skewness/kurtosis), t-statistic, PSR(0) and Minimum Track Record Length.
- Why it matters: A short track record cannot distinguish a good Sharpe from luck.
- How to fix: Extend the track record before claiming significance.
- Allows concluding: How much history is needed.
- Does not allow: Correcting for the number of trials (see deflated_sharpe).
- Required inputs: trades and prices, or returns
- Optional inputs: rules
- References: Lo, A. W. (2002). The Statistics of Sharpe Ratios. Financial Analysts Journal 58(4), 36-52. Bailey, D. H. and Lopez de Prado, M. (2012). The Sharpe Ratio Efficient Frontier. Journal of Risk 15(2), 3-44.

## sharpe_autocorrelation

**Sharpe annualisation under autocorrelation** (block: statistics)

- What it checks: Lo (2002) annualisation factor eta(q) with sample autocorrelations vs sqrt(q); Ljung-Box test.
- Why it matters: Positively autocorrelated (smoothed) returns overstate the annualised Sharpe, by up to 65% in Lo's examples.
- How to fix: Report the adjusted Sharpe; investigate return smoothing.
- Allows concluding: Inflation of the naive annualised Sharpe.
- Does not allow: -
- Required inputs: trades and prices, or returns
- Optional inputs: rules
- References: Lo, A. W. (2002). The Statistics of Sharpe Ratios. Financial Analysts Journal 58(4), 36-52. Ljung, G. M. and Box, G. E. P. (1978). On a Measure of Lack of Fit in Time Series Models. Biometrika 65(2), 297-303.

## trials_declared

**Declared number of trials** (block: statistics)

- What it checks: declared_results.n_trials vs the number of configurations in trials.csv; whether the reported strategy is in the log.
- Why it matters: The deflated Sharpe measures what the owner confesses to have tried.
- How to fix: Declare every configuration tried, including discarded ones.
- Allows concluding: Under-declared trials.
- Does not allow: Knowing about trials that were never logged.
- Required inputs: declared_results(n_trials) or trials
- Optional inputs: returns
- References: Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management 40(5), 94-107. Harvey, C. R. and Liu, Y. (2015). Backtesting. Journal of Portfolio Management 42(1), 13-28.

## deflated_sharpe

**Deflated Sharpe ratio** (block: statistics)

- What it checks: PSR against the expected maximum Sharpe of N trials under the null (N and the cross-trial variance from the declaration and trials.csv).
- Why it matters: The best of many noise strategies looks significant.
- How to fix: Out-of-sample test or pre-registration.
- Allows concluding: Probability of beating the selection threshold.
- Does not allow: Anything if N is not honest; anything about broken data.
- Required inputs: trades and prices, or returns, declared_results(n_trials) or trials
- Optional inputs: none
- References: Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management 40(5), 94-107. Bailey, D. H., Borwein, J., Lopez de Prado, M. and Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism. Notices of the AMS 61(5), 458-471.

## multiple_testing

**Multiple-testing haircut** (block: statistics)

- What it checks: Sharpe -> t -> p-value adjusted with Bonferroni, Holm and BHY -> haircut Sharpe.
- Why it matters: Marginal Sharpe ratios are heavily penalised once the number of tests is accounted for.
- How to fix: Treat as candidate, not discovery.
- Allows concluding: Sharpe after the haircut.
- Does not allow: Accounting for the real correlation between trials.
- Required inputs: trades and prices, or returns, declared_results(n_trials) or trials
- Optional inputs: none
- References: Harvey, C. R. and Liu, Y. (2015). Backtesting. Journal of Portfolio Management 42(1), 13-28. Harvey, C. R., Liu, Y. and Zhu, H. (2016). ... and the Cross-Section of Expected Returns. Review of Financial Studies 29(1), 5-68. Benjamini, Y. and Yekutieli, D. (2001). The control of the false discovery rate in multiple testing under dependency. Annals of Statistics 29(4), 1165-1188.

## pbo

**Probability of backtest overfitting** (block: statistics)

- What it checks: CSCV on the matrix of trial returns: how often the in-sample winner ends in the bottom half out-of-sample.
- Why it matters: Measures whether the selection process picks configurations that do not generalise.
- How to fix: Smaller search, untouched hold-out.
- Allows concluding: Tendency of the process to overfit.
- Does not allow: Anything with a single series.
- Required inputs: trials (at least 2 configurations)
- Optional inputs: none
- References: Bailey, D. H., Borwein, J., Lopez de Prado, M. and Zhu, Q. J. (2017). The Probability of Backtest Overfitting. Journal of Computational Finance 20(4), 39-69.

## llm_lookahead_risk

**LLM look-ahead risk** (block: statistics)

- What it checks: Weighted checklist of declared design choices (exposure to the training cutoff, identifying prompts, as-of retrieval, post-cutoff evaluation, memorisation probe) and Sharpe decay after the cutoff.
- Why it matters: A model may remember outcomes it is asked to predict.
- How to fix: Evaluate after the cutoff; anonymise; probe memorisation.
- Allows concluding: A risk score.
- Does not allow: Proving or ruling out memorisation (always NEEDS_REVIEW).
- Required inputs: llm_checklist
- Optional inputs: returns
- References: Glasserman, P. and Lin, C. (2023). Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis. arXiv:2309.17322.

## coverage_drift

**Coverage drift of inputs** (block: data)

- What it checks: Per input field (numeric columns of fundamentals.csv and signals.csv) and per period (quarter of period_end, month of decision_time), the share of universe members (universe.csv, the rules.yaml universe, or the tickers of the table) with a valid value; periods at least conventions.coverage_drop (10 pp) below the median of the previous periods (at least 4, of at least 5 periods) are flagged. Periods run to the last one the strategy uses (rules.yaml period, signals, trades; minus 120 days of publication lag for fundamentals) and a period with no rows counts as 0%. With required_inputs declared, drops of other fields are INFO.
- Why it matters: A database that silently loses part of the universe changes what the model ranks; row-level checks all pass.
- How to fix: Find why the inputs disappeared (vendor, mapping, membership) before using or spending those periods.
- Allows concluding: Periods whose input coverage is unlike the strategy's own history.
- Does not allow: Knowing which value is right; seeing members absent from every input when no universe is declared.
- Motivation (LockIn case study): LockIn spent its single-use holdout on a database where about 21% of the universe members had no fundamentals; every existing preflight check passed.
- Required inputs: fundamentals or signals
- Optional inputs: universe, rules(universe), rules(required_inputs)
- References: Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management. Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74.

## input_sufficiency

**Names scored with too few inputs** (block: data)

- What it checks: For every scored row of signals.csv, how many of rules.yaml required_inputs have a value (in signals.csv, or as of the decision in fundamentals.csv, at most conventions.max_input_age_days = 400 days after its period_end); names matched case-insensitively; rows below min_input_share. CONFIRMED_ERROR only with a declared minimum broken even if inputs missing from every table were present; otherwise a review item.
- Why it matters: A model that scores names with half of its inputs is a different model from the one validated.
- How to fix: Restore the inputs, or declare and evaluate the reduced model as a separate configuration.
- Allows concluding: Periods where the delivered scores break the declared input requirement.
- Does not allow: Judging inputs that are not declared in required_inputs.
- Motivation (LockIn case study): A LockIn reserved window ran with 13 of its 27 inputs and 91% of its evaluations were inconclusive; nothing flagged it before the window was spent.
- Required inputs: rules(required_inputs), signals
- Optional inputs: fundamentals, rules(min_input_share)
- References: Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## dividend_corporate_actions

**Dividends and corporate actions: adjusted vs as-traded prices** (block: data)

- What it checks: Step of the adjusted / as-traded ratio on each declared ex-date (1 / (1 - D / C) for a dividend, the ratio for a split); events not applied while others are, steps of the wrong size, ratio breaks without a declared event, adjusted prices frozen from an ex-date or the session after, declared total return that equals the price return. Without unadjusted_prices.csv application is NOT_EXECUTABLE, except an ex-date drop test on the adjusted series (>= 3 dividends of >= 0.5%) that can raise a review item.
- Why it matters: A dividend applied late or not at all shows a loss or a flat price that never existed and corrupts valuation and total returns.
- How to fix: Reload the affected rows after the vendor applies the event; re-adjust the history.
- Allows concluding: Events inconsistently reflected in the adjusted series; stale valuations after an event.
- Does not allow: Detecting dividends that are in no input; deciding which vendor is right.
- Motivation (LockIn case study): In LockIn paper trading, ex-dividend rows loaded before the vendor applied the dividend froze the prices of two holdings.
- Required inputs: prices, unadjusted_prices or dividends
- Optional inputs: corporate_actions, trades, declared_results(return_basis)
- References: Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley. CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.

## protocol_integrity

**Research protocol integrity** (block: statistics)

- What it checks: run_log.csv against protocol.yaml: train, validation, diagnostic or unknown-purpose runs touching a reserved (test or `reserved`) window; more than one configuration evaluated on it; 'reproductions' of configurations never tested on it; development after the first test look; validation looks vs declared trials (fed to the deflated Sharpe when n_trials is not declared). Purpose synonyms (holdout, oos, repro, ...) are mapped; an unrecognised purpose is a review item, never an error.
- Why it matters: A holdout reused to choose among configurations is in-sample; its result says nothing about new data.
- How to fix: Log every run with its purpose; declare a fresh untouched window for the final test.
- Allows concluding: Logged runs that break the single-use protocol.
- Does not allow: Seeing runs that were never logged.
- Motivation (LockIn case study): LockIn did not record whether a run over the test window was a reproduction or a new look, and diagnostic runs over a later window contaminated the window proposed as the next fresh holdout.
- Required inputs: run_log, protocol
- Optional inputs: declared_results(n_trials), rules(research.n_trials)
- References: Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74. Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. and Roth, A. (2015). The Reusable Holdout: Preserving Validity in Adaptive Data Analysis. Science 349(6248), 636-638. Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley. Bailey, D. H., Borwein, J., Lopez de Prado, M. and Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism. Notices of the AMS 61(5), 458-471.

## benchmark_fit

**Benchmark fit** (block: strategy)

- What it checks: Beta, correlation, tracking error and information ratio vs the declared benchmark and vs the equal-weight universe; gap split into benchmark-choice effect (equal-weight universe minus benchmark) and selection effect (strategy minus equal-weight universe); review when the benchmark construction differs from the strategy's weighting or is not declared, when a benchmark declared equal-weighted differs from the equal-weight universe computed from prices (tracking error > 1% or |choice effect| > 0.5 pp; conventions.benchmark_universe_tracking_error), or when R2 < 25% (at least 20 common dates).
- Why it matters: An equal-weight book against a cap-weighted index measures the size tilt as much as the selection.
- How to fix: Compare with a benchmark built like the strategy and report the benchmark-choice effect separately.
- Allows concluding: How much of the gap comes from the yardstick.
- Does not allow: Verifying the benchmark's own data.
- Motivation (LockIn case study): About 3 pp a year of LockIn's gap came from comparing an equal-weight book with a cap-weighted index.
- Required inputs: trades and prices, or returns, benchmark_returns
- Optional inputs: universe_returns, universe, prices, rules(benchmark), rules(sizing)
- References: Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill. Sensoy, B. (2009). Performance Evaluation and Self-Designated Benchmark Indexes in the Mutual Fund Industry. Journal of Financial Economics 92(1), 25-39. DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953. CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.

## liquidity_participation

**Participation in traded volume** (block: strategy)

- What it checks: Per ticker-day, the strategy's total |quantity| / ADV (previous 20 sessions, at least 5 with volume), so sliced orders are judged together; review above conventions.max_participation (10%); a ticker-day larger than the whole day's volume is a confirmed error (volume must be consolidated, in shares); trades without volume are disclosed, and below 90% of notional measured (conventions.min_volume_coverage) there is no PASS; square-root impact estimate reported as context.
- Why it matters: Orders that are a large part of the volume do not fill at the close the backtest assumes.
- How to fix: Cap orders at a fraction of ADV, spread them, or model impact explicitly.
- Allows concluding: Trades that are implausible or expensive at their size.
- Does not allow: Measuring actual impact (the square-root estimate is an order of magnitude).
- Motivation (LockIn case study): No single LockIn incident: LockIn backtests assumed every order fills at the close; this family (with cost_sensitivity) makes that assumption measurable.
- Required inputs: trades, prices(volume)
- Optional inputs: rules
- References: Almgren, R. and Chriss, N. (2001). Optimal Execution of Portfolio Transactions. Journal of Risk 3(2), 5-39. Almgren, R., Thum, C., Hauptmann, E. and Li, H. (2005). Direct Estimation of Equity Market Impact. Risk 18(7), 58-62. Toth, B., Lemperiere, Y., Deremble, C., de Lataillade, J., Kockelkoren, J. and Bouchaud, J.-P. (2011). Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets. Physical Review X 1, 021006. Bouchaud, J.-P., Bonart, J., Donier, J. and Gould, M. (2018). Trades, Quotes and Prices: Financial Markets Under the Microscope. Cambridge University Press.

## cost_sensitivity

**Sensitivity of the result to trading costs** (block: strategy)

- What it checks: Break-even cost per unit of turnover ((gross return - hurdle) / turnover; hurdle = benchmark when given, else zero) and full reconstructions at 1x, 2x and 3x the declared costs.
- Why it matters: Cost estimates are rarely better than a factor of two; a result that disappears at 2x is fragile.
- How to fix: Reduce turnover or report the result under realistic cost ranges.
- Allows concluding: How much cost the excess return can absorb.
- Does not allow: Knowing the true costs.
- Motivation (LockIn case study): No single LockIn incident: same family as liquidity_participation; it states how much cost margin a result has instead of a single cost assumption.
- Required inputs: trades, prices
- Optional inputs: rules, costs, benchmark_returns
- References: Novy-Marx, R. and Velikov, M. (2016). A Taxonomy of Anomalies and Their Trading Costs. Review of Financial Studies 29(1), 104-147. Almgren, R. and Chriss, N. (2001). Optimal Execution of Portfolio Transactions. Journal of Risk 3(2), 5-39.

## stability_and_concentration

**Stability across subperiods and concentration of the P&L** (block: statistics)

- What it checks: Subperiod metrics (years or halves) with dispersion; share of the P&L from the top names and days. Review when one subperiod (of >= 3) or one name (of >= 3) carries the whole result, or when the result disappears without its best 1% of periods (>= 250 periods). Years are used from 3 calendar years, halves otherwise. The PASS title names only the tests that ran; with none applicable the result is INFO.
- Why it matters: A result carried by one name, year or a few days is a bet on that exposure, not a repeatable rule.
- How to fix: Report the result without that name, subperiod or days.
- Allows concluding: Where the result comes from.
- Does not allow: Saying whether the concentration will persist.
- Motivation (LockIn case study): Same family as conditional_rule_activation: LockIn's test window was dominated by one rule (an inverted-curve bond rule); concentration by name, subperiod or day is the general form.
- Required inputs: trades and prices, or returns
- Optional inputs: rules
- References: Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley. Harvey, C. R. and Liu, Y. (2015). Backtesting. Journal of Portfolio Management 42(1), 13-28.

## conditional_rule_activation

**Activation of conditional rules in and out of sample** (block: statistics)

- What it checks: Share of periods in which each conditional rule (regimes.csv column, rules.yaml conditional_rules) is active before and after the out-of-sample start (protocol.yaml test, or conventions.oos_start); review when below 10% in sample and above 50% out of sample, or when a declared rule has no in-sample value; every declared rule is reported.
- Why it matters: A rule calibrated on a handful of in-sample periods and dominant in the test makes the test measure an almost untested rule.
- How to fix: Report results with and without the rule; do not count the window as a test of the in-sample model.
- Allows concluding: Rules whose exposure changed between the windows.
- Does not allow: Judging whether the rule is right.
- Motivation (LockIn case study): LockIn's inverted-curve bond rule was active in 5% of the in-sample months and 83% of the test months.
- Required inputs: regimes, protocol(test) or rules(conventions.oos_start)
- Optional inputs: rules(conditional_rules)
- References: Ang, A. and Timmermann, A. (2012). Regime Changes and Financial Markets. Annual Review of Financial Economics 4, 313-337. Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74.

## References

- Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.
- CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.
- Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.
- Sharpe, W. F. (1994). The Sharpe Ratio. Journal of Portfolio Management 21(1), 49-58.
- Lo, A. W. (2002). The Statistics of Sharpe Ratios. Financial Analysts Journal 58(4), 36-52.
- Bailey, D. H. and Lopez de Prado, M. (2012). The Sharpe Ratio Efficient Frontier. Journal of Risk 15(2), 3-44.
- Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management 40(5), 94-107.
- Bailey, D. H., Borwein, J., Lopez de Prado, M. and Zhu, Q. J. (2017). The Probability of Backtest Overfitting. Journal of Computational Finance 20(4), 39-69.
- Bailey, D. H., Borwein, J., Lopez de Prado, M. and Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism. Notices of the AMS 61(5), 458-471.
- Harvey, C. R. and Liu, Y. (2015). Backtesting. Journal of Portfolio Management 42(1), 13-28.
- Harvey, C. R., Liu, Y. and Zhu, H. (2016). ... and the Cross-Section of Expected Returns. Review of Financial Studies 29(1), 5-68.
- Benjamini, Y. and Yekutieli, D. (2001). The control of the false discovery rate in multiple testing under dependency. Annals of Statistics 29(4), 1165-1188.
- Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74.
- Magdon-Ismail, M. and Atiya, A. (2004). Maximum Drawdown. Risk 17(10), 99-102.
- Brown, S., Goetzmann, W., Ibbotson, R. and Ross, S. (1992). Survivorship Bias in Performance Studies. Review of Financial Studies 5(4), 553-580.
- Novy-Marx, R. and Velikov, M. (2016). A Taxonomy of Anomalies and Their Trading Costs. Review of Financial Studies 29(1), 104-147.
- Ljung, G. M. and Box, G. E. P. (1978). On a Measure of Lack of Fit in Time Series Models. Biometrika 65(2), 297-303.
- Glasserman, P. and Lin, C. (2023). Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis. arXiv:2309.17322.
- Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.
- Almgren, R. and Chriss, N. (2001). Optimal Execution of Portfolio Transactions. Journal of Risk 3(2), 5-39.
- Almgren, R., Thum, C., Hauptmann, E. and Li, H. (2005). Direct Estimation of Equity Market Impact. Risk 18(7), 58-62.
- Toth, B., Lemperiere, Y., Deremble, C., de Lataillade, J., Kockelkoren, J. and Bouchaud, J.-P. (2011). Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets. Physical Review X 1, 021006.
- Bouchaud, J.-P., Bonart, J., Donier, J. and Gould, M. (2018). Trades, Quotes and Prices: Financial Markets Under the Microscope. Cambridge University Press.
- Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.
- Sensoy, B. (2009). Performance Evaluation and Self-Designated Benchmark Indexes in the Mutual Fund Industry. Journal of Financial Economics 92(1), 25-39.
- DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953.
- Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. and Roth, A. (2015). The Reusable Holdout: Preserving Validity in Adaptive Data Analysis. Science 349(6248), 636-638.
- Ang, A. and Timmermann, A. (2012). Regime Changes and Financial Markets. Annual Review of Financial Economics 4, 313-337.

## Further literature on LLM look-ahead (not independently verified)

The original internal research behind the LLM checklist also cited the following works. Their bibliographic details
were collected from secondary sources and were NOT independently verified by the authors of this release; treat them
as pointers, not as authorities: Kong et al. (2026), position paper on bias in LLM finance evaluation (ICML 2026,
arXiv 2602.14233); Gao, Jiang and Yan (2025), a test of look-ahead bias in LLM forecasts (arXiv 2512.23847);
Benhenda (2026), Look-Ahead-Bench (arXiv 2601.13770); Jia (2026), HindsightBench (arXiv 2607.18867); Li et al. (2025),
FINSABER (arXiv 2505.07078); DatedGPT (arXiv 2603.11838). The checklist weights are a documented judgement, not a
calibrated model.
