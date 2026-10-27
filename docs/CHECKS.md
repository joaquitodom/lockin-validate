# Check catalogue

Generated from `src/lockin_validate/catalog.py` by `docs/generate_checks_md.py`. The same text is available offline
with `lockin-validate explain <check_id>` and through the MCP tool `explain_check`.

Every check returns findings with one status: CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE (with the reason) or
PASS (within its scope). Thresholds and formulas are in docs/CONVENTIONS.md.

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

## schema_and_types

**Input structure and types** (block: input)

- What it checks: Required columns per table (with aliases), unparseable dates and numbers, unknown trade sides, missing price adjustment flag.
- Why it matters: A malformed input silently drops rows or misreads values; every later check depends on this one.
- How to fix: Follow docs/INPUT_SPEC.md: ISO 8601 dates, dot decimal, canonical column names.
- Allows concluding: Inputs are well formed.
- Does not allow: Anything about the values themselves.
- Required inputs: none
- Optional inputs: prices, signals, trades, positions, costs, fundamentals, universe, security_master, corporate_actions, reference_prices, returns, trials

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

## Further literature on LLM look-ahead (not independently verified)

The original internal research behind the LLM checklist also cited the following works. Their bibliographic details
were collected from secondary sources and were NOT independently verified by the authors of this release; treat them
as pointers, not as authorities: Kong et al. (2026), position paper on bias in LLM finance evaluation (ICML 2026,
arXiv 2602.14233); Gao, Jiang and Yan (2025), a test of look-ahead bias in LLM forecasts (arXiv 2512.23847);
Benhenda (2026), Look-Ahead-Bench (arXiv 2601.13770); Jia (2026), HindsightBench (arXiv 2607.18867); Li et al. (2025),
FINSABER (arXiv 2505.07078); DatedGPT (arXiv 2603.11838). The checklist weights are a documented judgement, not a
calibrated model.
