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
| [`signal_forward_alignment`](#signal_forward_alignment) | signals | Forward-return alignment of the signal |
| [`signal_predictive_power`](#signal_predictive_power) | signals | Predictive power of the signal (rank IC) |
| [`signal_quantile_spread`](#signal_quantile_spread) | signals | Quantile portfolios and top-minus-bottom spread |
| [`signal_turnover`](#signal_turnover) | signals | Signal persistence and implied turnover |
| [`signal_lookahead_hint`](#signal_lookahead_hint) | signals | Look-ahead hint: IC with the contemporaneous return |
| [`ml_split_leakage`](#ml_split_leakage) | ml | Split leakage |
| [`ml_overfit_gap`](#ml_overfit_gap) | ml | Train / test metric gap |
| [`ml_calibration`](#ml_calibration) | ml | Probability calibration |
| [`ml_population_stability`](#ml_population_stability) | ml | Population stability (PSI) |
| [`ml_target_leakage`](#ml_target_leakage) | ml | Target leakage in features |
| [`ml_evaluation_protocol`](#ml_evaluation_protocol) | ml | Evaluation protocol |
| [`var_input_coherence`](#var_input_coherence) | risk | VaR input coherence |
| [`var_coverage`](#var_coverage) | risk | VaR unconditional coverage (Kupiec) |
| [`var_independence`](#var_independence) | risk | VaR exception independence (Christoffersen) |
| [`basel_traffic_light`](#basel_traffic_light) | risk | Basel traffic light (99% one-day VaR) |
| [`es_backtest`](#es_backtest) | risk | Expected shortfall backtest (Acerbi-Szekely Z2) |
| [`var_model_stability`](#var_model_stability) | risk | VaR model stability over time |
| [`forecast_origin_integrity`](#forecast_origin_integrity) | forecast | Forecast origin integrity |
| [`forecast_vs_naive`](#forecast_vs_naive) | forecast | Forecast accuracy against the naive benchmark |
| [`forecast_bias`](#forecast_bias) | forecast | Forecast bias (Mincer-Zarnowitz) |
| [`forecast_directional`](#forecast_directional) | forecast | Directional accuracy (Pesaran-Timmermann) |
| [`forecast_error_dynamics`](#forecast_error_dynamics) | forecast | Forecast error dynamics |
| [`forecast_multiple_models`](#forecast_multiple_models) | forecast | Several models on the same series (reality check) |
| [`portfolio_constraints`](#portfolio_constraints) | portfolio | Declared portfolio constraints |
| [`portfolio_concentration`](#portfolio_concentration) | portfolio | Concentration of the weights |
| [`portfolio_turnover`](#portfolio_turnover) | portfolio | Turnover of the weight path |
| [`portfolio_weights_vs_positions`](#portfolio_weights_vs_positions) | portfolio | Declared weights vs the weights implied by the positions |
| [`portfolio_vs_naive`](#portfolio_vs_naive) | portfolio | Realised weight path vs the 1/N portfolio |
| [`portfolio_active_share`](#portfolio_active_share) | portfolio | Active share vs the benchmark weights |
| [`live_period_integrity`](#live_period_integrity) | live | Live period integrity |
| [`live_vs_shadow_backtest`](#live_vs_shadow_backtest) | live | Live vs shadow backtest |
| [`live_performance_decay`](#live_performance_decay) | live | Live performance decay |
| [`live_structural_break`](#live_structural_break) | live | Structural break at the live start |
| [`live_execution_quality`](#live_execution_quality) | live | Live execution quality |
| [`live_declared_vs_realised`](#live_declared_vs_realised) | live | Declared backtest vs delivered series vs live |

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

## signal_forward_alignment

**Forward-return alignment of the signal** (block: signals)

- What it checks: Builds the forward returns of every (decision date, ticker): entry = close of the first session at or after the decision plus signal_lag_sessions (default 1), exit = entry + h sessions for each horizon in signal_horizons. CONFIRMED_ERROR when lag 0 is declared and decisions fall on days that are not sessions (the entry close was not yet known); NEEDS_REVIEW when more than 20% of the rows have no forward price at the primary horizon; PASS when every row aligns with lag >= 1; INFO otherwise.
- Why it matters: An IC computed on a return that starts at or before the decision measures the timestamp, not the forecast; a thin coverage biases every statistic below.
- How to fix: Declare signal_lag_sessions >= 1 (or date decisions after the close) and provide prices for every signalled ticker up to the longest horizon.
- Allows concluding: Stating on which returns the IC and spreads were computed.
- Does not allow: Detecting look-ahead inside the signal's own inputs (see signal_lookahead_hint).
- Required inputs: signals, prices
- Optional inputs: rules
- References: Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley. Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.

## signal_predictive_power

**Predictive power of the signal (rank IC)** (block: signals)

- What it checks: Per-date Spearman IC between the signal and the forward return at each horizon; mean, sd, hit rate and Newey-West t-stat (Bartlett, ceil(h / spacing) - 1 lags). NEEDS_REVIEW when |t| < signal_ic_t_review (2.0) at the primary horizon or the sign of the mean IC flips across horizons; INFO otherwise (never PASS); NOT_EXECUTABLE with fewer than signal_min_periods (24) dates of cross-section >= signal_min_cross_section (10). Thin cross-sections fall back to a time-series rank correlation per ticker, flagged as such. The 3.0 hurdle of Harvey, Liu and Zhu is quoted as INFO.
- Why it matters: The IC is the unit of alpha: without a significant and stable IC there is nothing to build a strategy on, and a sign that depends on the horizon is the signature of noise.
- How to fix: Check alignment and universe, report the decay profile and the number of signals tried, test out of sample.
- Allows concluding: Whether the ranking predicts forward returns in this sample, and at which horizon.
- Does not allow: Skill: an IC is before costs, turnover and selection among the signals tried.
- Required inputs: signals, prices
- Optional inputs: rules
- References: Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill. Qian, E., Hua, R. and Sorensen, E. (2007). Quantitative Equity Portfolio Management: Modern Techniques and Applications. Chapman and Hall/CRC. Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. Econometrica 55(3), 703-708. Harvey, C. R., Liu, Y. and Zhu, H. (2016). ... and the Cross-Section of Expected Returns. Review of Financial Studies 29(1), 5-68. Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management 40(5), 94-107.

## signal_quantile_spread

**Quantile portfolios and top-minus-bottom spread** (block: signals)

- What it checks: Each date the signal is sorted into signal_quantiles (5) buckets by average rank (tied values share a bucket); mean forward return per bucket at the primary horizon, top-minus-bottom spread with Newey-West t-stat, monotonicity (Spearman between bucket rank and mean return) and the share of the spread from the long leg. NEEDS_REVIEW when the spread t-stat < 2, monotonicity < 0.6, or the long leg contributes less than 25% of the spread while rules.yaml declares short_selling: false; INFO otherwise.
- Why it matters: A long-only book captures the long leg only; a spread that lives in the bottom bucket, or that is not monotonic, is not the alpha the IC suggests.
- How to fix: Report the per-bucket table; design the strategy on the leg it can actually hold.
- Allows concluding: Where in the ranking the return difference sits.
- Does not allow: Capturability after costs and constraints.
- Required inputs: signals, prices
- Optional inputs: rules
- References: Qian, E., Hua, R. and Sorensen, E. (2007). Quantitative Equity Portfolio Management: Modern Techniques and Applications. Chapman and Hall/CRC. Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.

## signal_turnover

**Signal persistence and implied turnover** (block: signals)

- What it checks: Spearman autocorrelation of the signal between decision dates (lag profile), one-way turnover of the top bucket and the half-life fitted on the profile. NEEDS_REVIEW when the lag-1 autocorrelation is below signal_turnover_review (0.5) and the primary horizon is longer than the spacing between decision dates, or when the half-life in sessions is shorter than the declared rebalance frequency (rules.yaml rebalance.frequency); INFO otherwise.
- Why it matters: A signal that is re-drawn faster than the horizon it is evaluated on, or than the book can be rebalanced, cannot deliver its IC after costs (fundamental law: breadth is paid in turnover).
- How to fix: Smooth the signal, shorten the horizon or the rebalance, and cost the implied turnover.
- Allows concluding: How much trading the signal implies per decision date.
- Does not allow: The actual cost, which depends on sizes and liquidity.
- Required inputs: signals, prices
- Optional inputs: rules
- References: Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill. Qian, E., Hua, R. and Sorensen, E. (2007). Quantitative Equity Portfolio Management: Modern Techniques and Applications. Chapman and Hall/CRC.

## signal_lookahead_hint

**Look-ahead hint: IC with the contemporaneous return** (block: signals)

- What it checks: Per-date IC of the signal with the decision session's own return (h = 0), with the previous session's return (h = -1) and with the aligned forward return (h = 1). NEEDS_REVIEW when |IC(h=0)| is significant (|t| >= signal_ic_t_review) and more than 3 times |IC(h=1)|: the signal is more related to the contemporaneous return than to the future one. A significant IC with h = -1 is reported as momentum / reversal content (legitimate when intended).
- Why it matters: A score that uses the close of its own decision session looks spectacular at h = 0 and vanishes at h = 1; that is the most common timestamp error in signal research.
- How to fix: Trace how decision_time is set and which prices enter the signal; recompute with data strictly before the decision.
- Allows concluding: Flagging a 'too good to be true' contemporaneous relation.
- Does not allow: Proving look-ahead: a hint, not evidence; look-ahead through fundamentals or text does not show here.
- Required inputs: signals, prices
- Optional inputs: rules
- References: Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley. Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management 40(5), 94-107.

## ml_split_leakage

**Split leakage** (block: ml)

- What it checks: Same sample_id in two splits; test timestamps inside the training window; training label_end later than the first test timestamp (no purging; per fold when `fold` declares a purged K-fold); gap to the first test timestamp shorter than ml_embargo_days; features with available_from_lag_days > 0.
- Why it matters: A test sample that shares dates, ids or label windows with the training set is not out of sample: every test metric is then optimistic by an unknown amount.
- How to fix: Test strictly after the last training label_end plus the embargo; one split per sample; lag each feature to its publication date.
- Allows concluding: Proving a leak from the sampling table alone (rows listed).
- Does not allow: Detecting leaks that live inside feature construction (see ml_target_leakage) or verifying purging without label_end.
- Required inputs: ml_samples
- Optional inputs: ml_samples(label_end), ml_samples(fold), ml_features(available_from_lag_days), rules(conventions.ml_embargo_days)
- References: Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley. Bergmeir, C. and Benitez, J. M. (2012). On the Use of Cross-validation for Time Series Predictor Evaluation. Information Sciences 191, 192-213. Kaufman, S., Rosset, S., Perlich, C. and Stitelman, O. (2012). Leakage in Data Mining: Formulation, Detection, and Avoidance. ACM TKDD 6(4). Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## ml_overfit_gap

**Train / test metric gap** (block: ml)

- What it checks: AUC (rank-based) with the Hanley-McNeil SE, accuracy, log-loss, Brier, KS and Gini per split for classifiers; R2, RMSE, MAE and Spearman IC for regressions. Review when the test metric loses more than ml_overfit_gap_review of the training excess or sits at the naive baseline.
- Why it matters: A model that is excellent in sample and ordinary out of sample has memorised its training data; the in-sample figure is what gets reported.
- How to fix: Regularise, simplify, use purged cross-validation, report the test metric with its SE.
- Allows concluding: Measuring the gap from delivered predictions.
- Does not allow: Separating overfitting from a regime change (see ml_population_stability).
- Required inputs: ml_samples, ml_predictions
- Optional inputs: ml_predictions(probability)
- References: Hanley, J. A. and McNeil, B. J. (1982). The Meaning and Use of the Area under a Receiver Operating Characteristic (ROC) Curve. Radiology 143(1), 29-36. Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74. Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.

## ml_calibration

**Probability calibration** (block: ml)

- What it checks: Reliability table on ml_calibration_bins quantile bins, ECE, Brier decomposition, base rate in train and test, mean probability against the base rate (2 binomial SE).
- Why it matters: A score that ranks but is not calibrated gives wrong expected losses, thresholds and sizes.
- How to fix: Platt scaling or isotonic regression fitted on the validation split.
- Allows concluding: Judging calibration of a delivered probability on the test split.
- Does not allow: Regression models (prediction intervals are not supported).
- Required inputs: ml_samples, ml_predictions
- Optional inputs: ml_predictions(probability)
- References: Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. ICML. (expected calibration error) Brier, G. W. (1950). Verification of Forecasts Expressed in Terms of Probability. Monthly Weather Review 78(1), 1-3. Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## ml_population_stability

**Population stability (PSI)** (block: ml)

- What it checks: PSI of the model score train vs test on 10 quantile bins of train, per-feature PSI when ml_feature_values.csv exists, and a label-shift test (two-proportion z or Welch t).
- Why it matters: If the test population differs from the training one, the test metric describes a model applied where it was not fitted; scorecards are recalibrated when PSI crosses the convention.
- How to fix: Confirm the shift, monitor PSI in production, recalibrate or rebuild.
- Allows concluding: Quantifying drift between the delivered splits.
- Does not allow: Calling drift an error: the thresholds 0.10 / 0.25 are an industry convention.
- Required inputs: ml_samples, ml_predictions
- Optional inputs: ml_feature_values
- References: Siddiqi, N. (2006). Credit Risk Scorecards: Developing and Implementing Intelligent Credit Scoring. Wiley. (population stability index conventions 0.10 / 0.25) Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## ml_target_leakage

**Target leakage in features** (block: ml)

- What it checks: On the training split, features whose |Spearman| with `actual` exceeds ml_leak_correlation or that separate the classes perfectly (NEEDS_REVIEW, high); feature names containing target / label / future / fwd / next (INFO).
- Why it matters: A feature computed with the outcome makes any backtest perfect and any deployment useless.
- How to fix: Trace the construction of the feature, remove it or lag it to its availability date.
- Allows concluding: Flagging features statistically indistinguishable from the label.
- Does not allow: Proving the leak: a legitimate near-deterministic feature exists, rarely.
- Required inputs: ml_samples, ml_predictions, ml_feature_values or ml_features
- Optional inputs: none
- References: Kaufman, S., Rosset, S., Perlich, C. and Stitelman, O. (2012). Leakage in Data Mining: Formulation, Detection, and Avoidance. ACM TKDD 6(4). Lopez de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.

## ml_evaluation_protocol

**Evaluation protocol** (block: ml)

- What it checks: Number of distinct models scored on the test split and the number of trials declared (declared_results.json n_trials or rules.yaml research.n_trials); which splits were delivered.
- Why it matters: Scoring several candidates on the holdout and reporting the best is selection on the test set.
- How to fix: Select on validation, score once on test, declare the number of configurations tried.
- Allows concluding: Counting what was scored where.
- Does not allow: Knowing about models that were scored and not delivered.
- Required inputs: ml_samples, ml_predictions
- Optional inputs: declared_results(n_trials), rules(research.n_trials), ml_predictions(model)
- References: Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. and Roth, A. (2015). The Reusable Holdout: Preserving Validity in Adaptive Data Analysis. Science 349(6248), 636-638. Arnott, R., Harvey, C. R. and Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Financial Data Science 1(1), 64-74. Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## var_input_coherence

**VaR input coherence** (block: risk)

- What it checks: Sign convention of the VaR (declared vs observed), horizon, missing or zero VaR, quantile monotonicity (var_95 <= var_99), ES >= VaR per level, duplicated dates, gaps longer than 5 sessions and frozen P&L.
- Why it matters: An inverted sign turns every exception count into nonsense; crossed quantiles or an ES below its VaR cannot come from a coherent model; gaps and frozen P&L hide the days a backtest exists to test.
- How to fix: Declare conventions.risk_var_sign, fix the forecast file (one row per date, ordered quantiles, ES >= VaR) and explain gaps.
- Allows concluding: Whether the forecast file can be backtested at all.
- Does not allow: Anything about the quality of the forecasts.
- Required inputs: var_forecasts
- Optional inputs: rules
- References: Basel Committee on Banking Supervision (1996). Supervisory Framework for the Use of Backtesting in Conjunction with the Internal Models Approach to Market Risk Capital Requirements. Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## var_coverage

**VaR unconditional coverage (Kupiec)** (block: risk)

- What it checks: Per level: exceptions x in N days, observed vs expected rate, Kupiec LR_uc against chi-square(1), exact binomial acceptance region. Too many exceptions (risk under-estimated) or too few (model too conservative, capital wasted) are both review items.
- Why it matters: Coverage is the first promise of a VaR: losses beyond it on 1% of days. A model breached 3% of the time under-states risk; one never breached ties up capital and tells nothing about its reaction to stress.
- How to fix: Re-estimate volatility and tails; check the horizon and the P&L definition (hypothetical vs actual).
- Allows concluding: Whether the long-run exception rate is consistent with the level.
- Does not allow: Whether the exceptions are independent (see var_independence); power is low below 250 days (Kupiec 1995) and estimation risk inflates rejections (Escanciano and Olmo 2010).
- Required inputs: var_forecasts
- Optional inputs: rules
- References: Kupiec, P. (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. Journal of Derivatives 3(2), 73-84. Campbell, S. (2006). A Review of Backtesting and Backtesting Procedures. Journal of Risk 9(2), 1-17. Escanciano, J. C. and Olmo, J. (2010). Backtesting Parametric Value-at-Risk with Estimation Risk. Journal of Business and Economic Statistics 28(1), 36-51. Basel Committee on Banking Supervision (1996). Supervisory Framework for the Use of Backtesting in Conjunction with the Internal Models Approach to Market Risk Capital Requirements.

## var_independence

**VaR exception independence (Christoffersen)** (block: risk)

- What it checks: Christoffersen Markov independence test LR_ind, joint conditional coverage LR_cc = LR_uc + LR_ind, longest run of consecutive exceptions and clusters within 5 days.
- Why it matters: A model with the right average coverage but clustered exceptions fails exactly in the stress episodes; clustering reveals a volatility estimate that reacts too slowly.
- How to fix: Shorten the estimation window or decay factor; re-estimate daily; model volatility clustering.
- Allows concluding: First-order dependence of the exceptions and the joint test.
- Does not allow: Higher-order or duration dependence (Berkowitz, Christoffersen and Pelletier 2011); with fewer than 5 exceptions the test has no power and reports INFO.
- Required inputs: var_forecasts
- Optional inputs: rules
- References: Christoffersen, P. (1998). Evaluating Interval Forecasts. International Economic Review 39(4), 841-862. Berkowitz, J., Christoffersen, P. and Pelletier, D. (2011). Evaluating Value-at-Risk Models with Desk-Level Data. Management Science 57(12), 2213-2227. Campbell, S. (2006). A Review of Backtesting and Backtesting Procedures. Journal of Risk 9(2), 1-17.

## basel_traffic_light

**Basel traffic light (99% one-day VaR)** (block: risk)

- What it checks: Exceptions of the 99% VaR in the last 250 observations mapped to the Basel green / yellow / red zones with the multiplier add-on; rolling count over the full sample and the worst window.
- Why it matters: It is the regulatory backtest: yellow asks for explanations and may raise capital, red presumes a model problem. It is also a statistical signal, not a proof: a correct model lands in yellow a few percent of the time.
- How to fix: Explain every exception (market, position, model, data) and remediate the model when the cause is the model.
- Allows concluding: The supervisory zone and the add-on; how often the model would have been yellow or red historically.
- Does not allow: Confirming an error: red is never a CONFIRMED_ERROR here. Defined for 99% one-day VaR only (FRTB keeps it at 99% and 97.5% VaR for desks; the ES is backtested indirectly).
- Required inputs: var_forecasts
- Optional inputs: rules
- References: Basel Committee on Banking Supervision (1996). Supervisory Framework for the Use of Backtesting in Conjunction with the Internal Models Approach to Market Risk Capital Requirements. Basel Committee on Banking Supervision (2019). Minimum Capital Requirements for Market Risk (MAR, FRTB): backtesting and P&L attribution at desk level, 97.5% expected shortfall.

## es_backtest

**Expected shortfall backtest (Acerbi-Szekely Z2)** (block: risk)

- What it checks: Z2 = 1 - sum L_t 1[exception_t] / (N p ES_t) with losses positive (0 under H0, negative when the ES is too small), the mean realised loss on exception days against the mean ES forecast, and the exceedance residual (loss - ES) with its t-statistic.
- Why it matters: FRTB capital rests on the 97.5% ES; a VaR with correct coverage says nothing about the size of the losses beyond it, which is what the ES forecasts.
- How to fix: Re-estimate the tail beyond the VaR; do not scale the ES from the VaR with a fixed factor.
- Allows concluding: Whether the realised tail losses are compatible with the ES forecasts, approximately.
- Does not allow: A formal verdict: the critical value of Z2 depends on the P&L distribution and must be simulated under the model; the -0.70 bound is the authors' approximation. Fewer than 10 exceptions: NOT_EXECUTABLE.
- Required inputs: var_forecasts
- Optional inputs: rules
- References: Acerbi, C. and Szekely, B. (2014). Backtesting Expected Shortfall. Risk, December 2014, 76-81. Basel Committee on Banking Supervision (2019). Minimum Capital Requirements for Market Risk (MAR, FRTB): backtesting and P&L attribution at desk level, 97.5% expected shortfall.

## var_model_stability

**VaR model stability over time** (block: risk)

- What it checks: Exception rate per calendar year (or 250-day block) with a chi-square homogeneity test; correlation between the VaR and the 20-day realised volatility and the VaR / volatility ratio per block.
- Why it matters: A full-sample coverage test averages good and bad years; a VaR that does not move with volatility is right on average and wrong in every regime.
- How to fix: Report exceptions per year; use a volatility estimator that reacts (EWMA, GARCH, filtered historical).
- Allows concluding: Whether the coverage is stable over time and the VaR tracks realised volatility.
- Does not allow: What the model does in a regime absent from the sample.
- Required inputs: var_forecasts
- Optional inputs: rules
- References: Basel Committee on Banking Supervision (1996). Supervisory Framework for the Use of Backtesting in Conjunction with the Internal Models Approach to Market Risk Capital Requirements. Campbell, S. (2006). A Review of Backtesting and Backtesting Procedures. Journal of Risk 9(2), 1-17. Board of Governors of the Federal Reserve System (2011). SR 11-7: Guidance on Model Risk Management.

## forecast_origin_integrity

**Forecast origin integrity** (block: forecast)

- What it checks: target_date before origin_date; publication dates before the period they measure; a supplied naive benchmark built from values not yet published at the origin; contradictory duplicates; mixed horizons without a horizon column; revised data without publication dates; horizon distribution per model.
- Why it matters: A forecast scored against information that did not exist at its origin, or against a final vintage instead of the real-time value, overstates skill (Croushore and Stark 2001).
- How to fix: Fix the dates; add actual_available_from and a horizon column; rebuild the naive from values published at each origin; keep one forecast per key.
- Allows concluding: That the forecasts and the benchmark respect the information available at each origin.
- Does not allow: Detecting revisions when no publication dates are provided.
- Required inputs: forecasts
- Optional inputs: rules(forecast), rules(conventions)
- References: Croushore, D. and Stark, T. (2001). A Real-Time Data Set for Macroeconomists. Journal of Econometrics 105(1), 111-130. Diebold, F. X. (2015). Comparing Predictive Accuracy, Twenty Years Later: A Personal Perspective on the Use and Abuse of Diebold-Mariano Tests. Journal of Business and Economic Statistics 33(1), 1-9.

## forecast_vs_naive

**Forecast accuracy against the naive benchmark** (block: forecast)

- What it checks: RMSE, MAE, Theil's U and the Diebold-Mariano test (HLN correction, Newey-West h - 1 lags) of each model against a random walk, the historical mean or zero, per model, series and horizon.
- Why it matters: Many published forecasts do not beat the random walk or the historical mean (Meese and Rogoff, Goyal and Welch); the naive is the minimum bar.
- How to fix: Report the naive alongside the model and the DM p-value; choose the naive that fits the series.
- Allows concluding: Whether the model beats the chosen naive at the declared level (a judgement, never PASS).
- Does not allow: That the model is useful for decisions, or the comparison with other naives.
- Required inputs: forecasts
- Optional inputs: rules(forecast), rules(conventions)
- References: Diebold, F. X. and Mariano, R. S. (1995). Comparing Predictive Accuracy. Journal of Business and Economic Statistics 13(3), 253-263. Harvey, D., Leybourne, S. and Newbold, P. (1997). Testing the Equality of Prediction Mean Squared Errors. International Journal of Forecasting 13(2), 281-291. Theil, H. (1966). Applied Economic Forecasting. North-Holland. Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. Econometrica 55(3), 703-708. Goyal, A. and Welch, I. (2008). A Comprehensive Look at the Empirical Performance of Equity Premium Prediction. Review of Financial Studies 21(4), 1455-1508. Diebold, F. X. (2015). Comparing Predictive Accuracy, Twenty Years Later: A Personal Perspective on the Use and Abuse of Diebold-Mariano Tests. Journal of Business and Economic Statistics 33(1), 1-9.

## forecast_bias

**Forecast bias (Mincer-Zarnowitz)** (block: forecast)

- What it checks: Regression actual = a + b forecast; joint Wald test of (a, b) = (0, 1) with HAC covariance; mean error with its HAC t-statistic and the sign of the bias.
- Why it matters: A biased or inefficient forecast can be improved by a linear correction; systematic over- or under-forecasting distorts the decisions that use it.
- How to fix: Recalibrate on a separate sample and re-test; find the source of the systematic error.
- Allows concluding: Systematic bias or inefficiency of the forecasts.
- Does not allow: Why the bias exists.
- Required inputs: forecasts
- Optional inputs: rules(forecast), rules(conventions)
- References: Mincer, J. and Zarnowitz, V. (1969). The Evaluation of Economic Forecasts. In Economic Forecasts and Expectations, NBER, 3-46. Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. Econometrica 55(3), 703-708.

## forecast_directional

**Directional accuracy (Pesaran-Timmermann)** (block: forecast)

- What it checks: Hit ratio of the sign of the forecast change against the sign of the actual change (relative to the last known actual; the sign itself for return forecasts), the Pesaran-Timmermann statistic and the confusion table.
- Why it matters: A hit ratio above 50% means nothing when actuals mostly move one way; the PT test compares it with the hit ratio expected under independence.
- How to fix: Establish sign skill on more data before using the forecast for directional decisions.
- Allows concluding: Whether the direction is predicted better than chance at the declared level.
- Does not allow: The size of the moves; a test when every actual moves the same way.
- Required inputs: forecasts
- Optional inputs: rules(forecast), rules(conventions)
- References: Pesaran, M. H. and Timmermann, A. (1992). A Simple Nonparametric Test of Predictive Performance. Journal of Business and Economic Statistics 10(4), 461-465.

## forecast_error_dynamics

**Forecast error dynamics** (block: forecast)

- What it checks: Portmanteau test of the h-step errors over lags h .. h + 10 (an optimal h-step forecast has at most MA(h - 1) errors): Ljung-Box at h = 1, with Bartlett's covariance of the autocorrelations under the MA(h - 1) null for h > 1; and a rolling one-year RMSE with the worst and best windows.
- Why it matters: Autocorrelated errors beyond lag h - 1 mean the forecast ignores information in its own past errors; a worst window far above the best means the average accuracy hides regime dependence.
- How to fix: Model the error dynamics; report the accuracy per regime or per year.
- Allows concluding: Residual predictability of the errors and the time profile of the accuracy.
- Does not allow: Which variable is omitted.
- Required inputs: forecasts
- Optional inputs: rules(forecast), rules(conventions)
- References: Ljung, G. M. and Box, G. E. P. (1978). On a Measure of Lack of Fit in Time Series Models. Biometrika 65(2), 297-303. Bartlett, M. S. (1946). On the Theoretical Specification and Sampling Properties of Autocorrelated Time-Series. Supplement to the Journal of the Royal Statistical Society 8(1), 27-41. Diebold, F. X. and Mariano, R. S. (1995). Comparing Predictive Accuracy. Journal of Business and Economic Statistics 13(3), 253-263. Diebold, F. X. (2015). Comparing Predictive Accuracy, Twenty Years Later: A Personal Perspective on the Use and Abuse of Diebold-Mariano Tests. Journal of Business and Economic Statistics 33(1), 1-9.

## forecast_multiple_models

**Several models on the same series (reality check)** (block: forecast)

- What it checks: Number of models per series and horizon, the best by RMSE, and the best DM statistic compared with the expected maximum of n skill-less t-statistics (probability that the best of n noise models reaches it by chance).
- Why it matters: The best of many models beats the naive by chance with high probability; reporting only the winner is data snooping (White 2000).
- How to fix: Pre-register one model or evaluate the winner on a fresh sample; report the number tried.
- Allows concluding: Whether the best model's advantage exceeds what selection alone would produce.
- Does not allow: A full bootstrap reality check (the correlation between models is ignored).
- Required inputs: forecasts
- Optional inputs: rules(forecast), rules(conventions)
- References: White, H. (2000). A Reality Check for Data Snooping. Econometrica 68(5), 1097-1126. Hansen, P. R. (2005). A Test for Superior Predictive Ability. Journal of Business and Economic Statistics 23(4), 365-380. Bailey, D. H. and Lopez de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management 40(5), 94-107.

## portfolio_constraints

**Declared portfolio constraints** (block: portfolio)

- What it checks: On every weights date: sum of weights within 1 +/- conventions.portfolio_weight_sum_tolerance (0.01) under long_only with no cash ticker (<= 1 when a cash ticker is declared), net exposure within the declared net_exposure range, no negative weight under long_only, no weight above max_weight, held weights above min_weight, gross leverage sum|w| within gross_leverage_max, and group exposures within group_limits (needs the sector / asset_class column). Confirmed error on any breach; INFO with the observed ranges when nothing is declared (review when the sum is neither 1 nor 0 on some dates, a likely missing cash row); PASS when every declared constraint holds on every date.
- Why it matters: A weight table that contradicts its own mandate is either a bug in the optimiser or export, or a false declaration; both invalidate the backtest of the allocation.
- How to fix: Fix the constraint handling or the export (cash row, rounding, group mapping) or correct rules.yaml.
- Allows concluding: Whether the delivered weights respect what was declared, date by date, with the breaching rows.
- Does not allow: Judging whether the constraints are sensible, or constraints that were not declared.
- Required inputs: weights
- Optional inputs: rules
- References: European Parliament and Council (2009). Directive 2009/65/EC (UCITS IV), art. 52: the 5/10/40 concentration rule. Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.

## portfolio_concentration

**Concentration of the weights** (block: portfolio)

- What it checks: Per date: Herfindahl index of the absolute weights (normalised by the gross), effective number of positions 1/HHI, top-5 share, largest name and group exposures; summary over time (median, worst date). Review when the worst-date HHI exceeds conventions.portfolio_hhi_review (0.20, effective N 5) or a single name exceeds 25% without a declared max_weight that allows it; INFO otherwise. A separate INFO when the portfolio would breach the UCITS 5/10/40 rule (it applies only to UCITS funds).
- Why it matters: Estimation error in optimisers concentrates weights in the assets whose inputs were most over-estimated; the out-of-sample cost is documented and often exceeds the gain over 1/N.
- How to fix: Declare and enforce position and group caps; use shrinkage or resampling in the optimiser.
- Allows concluding: How concentrated the delivered weights are and when.
- Does not allow: Whether the concentration was rewarded; that is portfolio_vs_naive.
- Required inputs: weights
- Optional inputs: rules
- References: Chopra, V. K. and Ziemba, W. T. (1993). The Effect of Errors in Means, Variances, and Covariances on Optimal Portfolio Choice. Journal of Portfolio Management 19(2), 6-11. Michaud, R. O. (1989). The Markowitz Optimization Enigma: Is 'Optimized' Optimal? Financial Analysts Journal 45(1), 31-42. DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953. European Parliament and Council (2009). Directive 2009/65/EC (UCITS IV), art. 52: the 5/10/40 concentration rule.

## portfolio_turnover

**Turnover of the weight path** (block: portfolio)

- What it checks: One-way turnover between consecutive weight dates, 0.5 x sum |w_t - drifted w_(t-1)|, with the previous weights drifted by the price returns when prices.csv exists (buy-and-hold drift is not trading); annualised turnover, trade dates per year vs the declared rebalance_frequency, share of dates with no trade. Review when the annual turnover exceeds the declared turnover_max_annual or conventions.portfolio_turnover_review_annual (3.0), or when the trade count is incompatible with the declared frequency; confirmed error when, with prices, weights change by more than 1% on dates outside the declared schedule.
- Why it matters: The paper result of a weight path carries no costs; turnover is what the costs will be charged on, and a path that trades more often than declared is not the declared model.
- How to fix: Align the declared frequency with the model or export only rebalance dates; provide prices so drift can be separated from trading.
- Allows concluding: How much the path trades, net of drift, and whether it matches the declared schedule.
- Does not allow: The cost of that turnover (costs are not an input of this use case).
- Required inputs: weights
- Optional inputs: prices, rules
- References: DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953. Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.

## portfolio_weights_vs_positions

**Declared weights vs the weights implied by the positions** (block: portfolio)

- What it checks: When positions.csv and prices.csv exist: implied weights quantity x close / gross, compared with the declared weights (normalised, cash excluded) on the same date or the next positions date (one session of execution lag); max and mean absolute difference per date. Confirmed error when more than 10% of the ticker-dates differ by more than conventions.portfolio_drift_tolerance (0.02); PASS when they agree.
- Why it matters: A track record belongs to the book that was held, not to the weights a model printed.
- How to fix: Reconcile target weights with executed positions (cash, lot rounding, unexecuted orders).
- Allows concluding: Whether the positions implement the declared weights.
- Does not allow: Why they differ (costs, liquidity, discretion).
- Required inputs: weights, positions, prices
- Optional inputs: rules
- References: Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.

## portfolio_vs_naive

**Realised weight path vs the 1/N portfolio** (block: portfolio)

- What it checks: Realised return of the weight path with prices.csv (weights applied at the next session, drift between rebalances, no costs) against the equal-weight portfolio of the same names on the same dates and, if benchmark_returns.csv exists, the benchmark: annualised return, volatility, Sharpe, max drawdown, tracking error, and the Jobson-Korkie test of the Sharpe difference with the Memmel correction. Review when the model does not beat 1/N at conventions.portfolio_naive_alpha (0.05); INFO otherwise; not executable without prices or below conventions.portfolio_min_dates (12) weight dates.
- Why it matters: 1/N is the mandatory comparator of any allocation model: with estimation error it is hard to beat out of sample, so a model that does not beat it adds complexity without measurable value.
- How to fix: Report 1/N alongside the model; consider shrinkage, constraints or a longer sample.
- Allows concluding: Whether the construction added value over the naive rule on this sample, with a test.
- Does not allow: That failing to beat 1/N is an error (it is common); robustness to heavy tails (Ledoit and Wolf 2008 bootstrap not implemented).
- Required inputs: weights, prices
- Optional inputs: benchmark_returns, rules
- References: DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953. Jobson, J. D. and Korkie, B. M. (1981). Performance Hypothesis Testing with the Sharpe and Treynor Measures. Journal of Finance 36(4), 889-908. Memmel, C. (2003). Performance Hypothesis Testing with the Sharpe Ratio. Finance Letters 1, 21-23. Ledoit, O. and Wolf, M. (2008). Robust Performance Hypothesis Testing with the Sharpe Ratio. Journal of Empirical Finance 15(5), 850-859. Michaud, R. O. (1989). The Markowitz Optimization Enigma: Is 'Optimized' Optimal? Financial Analysts Journal 45(1), 31-42.

## portfolio_active_share

**Active share vs the benchmark weights** (block: portfolio)

- What it checks: When benchmark_weights.csv exists: active share 0.5 x sum |w - w_b| per date, share of held names outside the benchmark, tracking error of the two simulated paths when prices exist. INFO with the numbers; review when the rules.yaml strategy text says active / alpha and the median active share is below 0.20 (closet indexing), or says index / tracker and it is above 0.20.
- Why it matters: Fees and narrative follow the declared style; the weights show the real one.
- How to fix: Confirm the mandate and the benchmark composition file; document the sources of active risk.
- Allows concluding: How far the weights depart from the benchmark composition.
- Does not allow: Whether the active positions were skilful.
- Required inputs: weights, benchmark_weights
- Optional inputs: prices, rules
- References: Cremers, K. J. M. and Petajisto, A. (2009). How Active Is Your Fund Manager? A New Measure That Predicts Performance. Review of Financial Studies 22(9), 3329-3365. Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.

## live_period_integrity

**Live period integrity** (block: live)

- What it checks: Live dates vs the declared live start and the review date; duplicated (date, account) rows; whether the live series is a copy of the backtest on the overlap; length of the overlap with the backtest (shadow) and the gap after the declared backtest end.
- Why it matters: A track record that starts before it was live, that reaches into the future, or that equals the backtest is not a live record; without a shadow backtest on the same dates every later comparison is period-vs-period, not model-vs-reality.
- How to fix: Deliver the live returns from account statements and run the backtest over the live dates with the production code; declare live.start, live.backtest_end and gap_reason in rules.yaml.
- Allows concluding: Whether the live record can be compared with the backtest at all, and on how many periods.
- Does not allow: Verifying that the live returns are the ones in the broker statements (needs third-party statements, GIPS-style).
- Required inputs: live_returns
- Optional inputs: returns, rules(live)
- References: Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley. CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020. Dichev, I. D. and Yu, G. (2011). Higher Risk, Lower Returns: What Hedge Fund Investors Really Earn. Journal of Financial Economics 100(2), 248-263.

## live_vs_shadow_backtest

**Live vs shadow backtest** (block: live)

- What it checks: On the common dates: correlation, annualised tracking error, mean difference with a Newey-West t-statistic, beta of live on backtest, cumulative gap and when it opened, share of periods with a different sign.
- Why it matters: Live should differ from its simulation only by execution noise and costs; a systematic negative difference or a low correlation means production is not running the model that was validated.
- How to fix: Attribute the gap to execution, data feeds, risk limits or overrides and fix the production pipeline.
- Allows concluding: Whether live tracks the simulation and the size and date of any gap.
- Does not allow: Judging whether the model has an edge (see live_performance_decay).
- Required inputs: live_returns, returns
- Optional inputs: rules(live)
- References: Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill. Perold, A. F. (1988). The Implementation Shortfall: Paper versus Reality. Journal of Portfolio Management 14(3), 4-9. Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.

## live_performance_decay

**Live performance decay** (block: live)

- What it checks: Live vs backtest Sharpe (ratio, expected out-of-sample haircut), PSR of the live Sharpe against the backtest one, Minimum Track Record Length, Sharpe-difference z-test, annual return and max drawdown side by side.
- Why it matters: Live Sharpe ratios are typically about half the backtest ones (Suhonen et al. 2017; Harvey and Liu 2015); a deficit beyond the haircut that is also significant means the edge decayed or the backtest overstated it (McLean and Pontiff 2016).
- How to fix: Re-estimate expectations and sizing from the live record; look for what changed.
- Allows concluding: Whether the live record is statistically incompatible with the backtest Sharpe, and how long a record would be needed to conclude.
- Does not allow: Concluding the edge is intact from a short live record (it reports the MinTRL instead).
- Required inputs: live_returns, returns or rules(live.declared_sharpe) or declared_results(sharpe)
- Optional inputs: rules(live)
- References: Harvey, C. R. and Liu, Y. (2015). Backtesting. Journal of Portfolio Management 42(1), 13-28. Suhonen, A., Lennkh, M. and Perez, F. (2017). Quantifying Backtest Overfitting in Alternative Beta Strategies. Journal of Portfolio Management 43(2), 90-104. Bailey, D. H. and Lopez de Prado, M. (2012). The Sharpe Ratio Efficient Frontier. Journal of Risk 15(2), 3-44. Jobson, J. D. and Korkie, B. M. (1981). Performance Hypothesis Testing with the Sharpe and Treynor Measures. Journal of Finance 36(4), 889-908. Memmel, C. (2003). Performance Hypothesis Testing with the Sharpe Ratio. Finance Letters 1, 21-23. McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? Journal of Finance 71(1), 5-32.

## live_structural_break

**Structural break at the live start** (block: live)

- What it checks: Page CUSUM of live returns standardised with the backtest moments (threshold live_cusum_h), a Chow-style mean-shift test at the live start with HAC variances, and the percentile of the live rolling Sharpe within the backtest's rolling distribution.
- Why it matters: A regime change at the moment of going live is the signature of overfitting or of a production difference; the CUSUM dates it.
- How to fix: Date the break and look for a cause: code release, data vendor, capacity, regime.
- Allows concluding: Whether and when the live process left the backtest's distribution.
- Does not allow: Detecting small drifts quickly (the CUSUM needs about h / shift periods); absence of a crossing is not evidence of an intact edge.
- Required inputs: live_returns, returns
- Optional inputs: rules(live)
- References: Page, E. S. (1954). Continuous Inspection Schemes. Biometrika 41(1/2), 100-115. Brown, R. L., Durbin, J. and Evans, J. M. (1975). Techniques for Testing the Constancy of Regression Relationships over Time. Journal of the Royal Statistical Society B 37(2), 149-192. Chow, G. C. (1960). Tests of Equality Between Sets of Coefficients in Two Linear Regressions. Econometrica 28(3), 591-605.

## live_execution_quality

**Live execution quality** (block: live)

- What it checks: Signed slippage vs the model price in bps (overall and per side, with a t-statistic), delay between the model timestamp and the fill, fill ratio and discretionary overrides against model_trades.csv, commission per notional.
- Why it matters: Implementation shortfall (Perold 1988) is the usual reason live underperforms a backtest that assumed model prices; unfilled model trades and overrides mean the live record is not the model's.
- How to fix: Measure shortfall per venue and order type, enforce the model trade list or document overrides, feed realised costs back into the backtest.
- Allows concluding: How much of the live gap is execution and how much the record departs from the model's orders.
- Does not allow: Judging market impact without quotes and volumes.
- Required inputs: live_trades
- Optional inputs: model_trades, live_trades(model_price), live_trades(model_timestamp)
- References: Perold, A. F. (1988). The Implementation Shortfall: Paper versus Reality. Journal of Portfolio Management 14(3), 4-9. Almgren, R. and Chriss, N. (2001). Optimal Execution of Portfolio Transactions. Journal of Risk 3(2), 5-39.

## live_declared_vs_realised

**Declared backtest vs delivered series vs live** (block: live)

- What it checks: Table declared / backtest series (recomputed with the core metrics module and the declared convention) / live realised for Sharpe, annual return and max drawdown.
- Why it matters: The number in the pitch must be the series delivered; and a live drawdown beyond the backtest worst case means the risk budget was set on a lower bound.
- How to fix: Deliver the series behind the declared metrics or correct them; re-estimate the risk budget.
- Allows concluding: Whether the declared metrics are the delivered series and whether live already broke the backtest's worst case.
- Does not allow: Verifying the convention used by the strategy owner beyond the one declared.
- Required inputs: live_returns, returns
- Optional inputs: rules(live), declared_results
- References: Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley. Magdon-Ismail, M. and Atiya, A. (2004). Maximum Drawdown. Risk 17(10), 99-102. CFA Institute (2019). Global Investment Performance Standards (GIPS) 2020.

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
- Qian, E., Hua, R. and Sorensen, E. (2007). Quantitative Equity Portfolio Management: Modern Techniques and Applications. Chapman and Hall/CRC.
- Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. Econometrica 55(3), 703-708.
- Hanley, J. A. and McNeil, B. J. (1982). The Meaning and Use of the Area under a Receiver Operating Characteristic (ROC) Curve. Radiology 143(1), 29-36.
- Siddiqi, N. (2006). Credit Risk Scorecards: Developing and Implementing Intelligent Credit Scoring. Wiley. (population stability index conventions 0.10 / 0.25)
- Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. ICML. (expected calibration error)
- Brier, G. W. (1950). Verification of Forecasts Expressed in Terms of Probability. Monthly Weather Review 78(1), 1-3.
- Kaufman, S., Rosset, S., Perlich, C. and Stitelman, O. (2012). Leakage in Data Mining: Formulation, Detection, and Avoidance. ACM TKDD 6(4).
- Bergmeir, C. and Benitez, J. M. (2012). On the Use of Cross-validation for Time Series Predictor Evaluation. Information Sciences 191, 192-213.
- Kupiec, P. (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. Journal of Derivatives 3(2), 73-84.
- Christoffersen, P. (1998). Evaluating Interval Forecasts. International Economic Review 39(4), 841-862.
- Basel Committee on Banking Supervision (1996). Supervisory Framework for the Use of Backtesting in Conjunction with the Internal Models Approach to Market Risk Capital Requirements.
- Basel Committee on Banking Supervision (2019). Minimum Capital Requirements for Market Risk (MAR, FRTB): backtesting and P&L attribution at desk level, 97.5% expected shortfall.
- Acerbi, C. and Szekely, B. (2014). Backtesting Expected Shortfall. Risk, December 2014, 76-81.
- Campbell, S. (2006). A Review of Backtesting and Backtesting Procedures. Journal of Risk 9(2), 1-17.
- Berkowitz, J., Christoffersen, P. and Pelletier, D. (2011). Evaluating Value-at-Risk Models with Desk-Level Data. Management Science 57(12), 2213-2227.
- Escanciano, J. C. and Olmo, J. (2010). Backtesting Parametric Value-at-Risk with Estimation Risk. Journal of Business and Economic Statistics 28(1), 36-51.
- Diebold, F. X. and Mariano, R. S. (1995). Comparing Predictive Accuracy. Journal of Business and Economic Statistics 13(3), 253-263.
- Harvey, D., Leybourne, S. and Newbold, P. (1997). Testing the Equality of Prediction Mean Squared Errors. International Journal of Forecasting 13(2), 281-291.
- Mincer, J. and Zarnowitz, V. (1969). The Evaluation of Economic Forecasts. In Economic Forecasts and Expectations, NBER, 3-46.
- Pesaran, M. H. and Timmermann, A. (1992). A Simple Nonparametric Test of Predictive Performance. Journal of Business and Economic Statistics 10(4), 461-465.
- Theil, H. (1966). Applied Economic Forecasting. North-Holland.
- White, H. (2000). A Reality Check for Data Snooping. Econometrica 68(5), 1097-1126.
- Hansen, P. R. (2005). A Test for Superior Predictive Ability. Journal of Business and Economic Statistics 23(4), 365-380.
- Diebold, F. X. (2015). Comparing Predictive Accuracy, Twenty Years Later: A Personal Perspective on the Use and Abuse of Diebold-Mariano Tests. Journal of Business and Economic Statistics 33(1), 1-9.
- Croushore, D. and Stark, T. (2001). A Real-Time Data Set for Macroeconomists. Journal of Econometrics 105(1), 111-130.
- Bartlett, M. S. (1946). On the Theoretical Specification and Sampling Properties of Autocorrelated Time-Series. Supplement to the Journal of the Royal Statistical Society 8(1), 27-41.
- Goyal, A. and Welch, I. (2008). A Comprehensive Look at the Empirical Performance of Equity Premium Prediction. Review of Financial Studies 21(4), 1455-1508.
- Chopra, V. K. and Ziemba, W. T. (1993). The Effect of Errors in Means, Variances, and Covariances on Optimal Portfolio Choice. Journal of Portfolio Management 19(2), 6-11.
- Michaud, R. O. (1989). The Markowitz Optimization Enigma: Is 'Optimized' Optimal? Financial Analysts Journal 45(1), 31-42.
- Jobson, J. D. and Korkie, B. M. (1981). Performance Hypothesis Testing with the Sharpe and Treynor Measures. Journal of Finance 36(4), 889-908.
- Memmel, C. (2003). Performance Hypothesis Testing with the Sharpe Ratio. Finance Letters 1, 21-23.
- Cremers, K. J. M. and Petajisto, A. (2009). How Active Is Your Fund Manager? A New Measure That Predicts Performance. Review of Financial Studies 22(9), 3329-3365.
- Ledoit, O. and Wolf, M. (2008). Robust Performance Hypothesis Testing with the Sharpe Ratio. Journal of Empirical Finance 15(5), 850-859.
- European Parliament and Council (2009). Directive 2009/65/EC (UCITS IV), art. 52: the 5/10/40 concentration rule.
- Suhonen, A., Lennkh, M. and Perez, F. (2017). Quantifying Backtest Overfitting in Alternative Beta Strategies. Journal of Portfolio Management 43(2), 90-104.
- Page, E. S. (1954). Continuous Inspection Schemes. Biometrika 41(1/2), 100-115.
- Brown, R. L., Durbin, J. and Evans, J. M. (1975). Techniques for Testing the Constancy of Regression Relationships over Time. Journal of the Royal Statistical Society B 37(2), 149-192.
- Chow, G. C. (1960). Tests of Equality Between Sets of Coefficients in Two Linear Regressions. Econometrica 28(3), 591-605.
- Perold, A. F. (1988). The Implementation Shortfall: Paper versus Reality. Journal of Portfolio Management 14(3), 4-9.
- Dichev, I. D. and Yu, G. (2011). Higher Risk, Lower Returns: What Hedge Fund Investors Really Earn. Journal of Financial Economics 100(2), 248-263.
- McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? Journal of Finance 71(1), 5-32.

## Further literature on LLM look-ahead (not independently verified)

The original internal research behind the LLM checklist also cited the following works. Their bibliographic details
were collected from secondary sources and were NOT independently verified by the authors of this release; treat them
as pointers, not as authorities: Kong et al. (2026), position paper on bias in LLM finance evaluation (ICML 2026,
arXiv 2602.14233); Gao, Jiang and Yan (2025), a test of look-ahead bias in LLM forecasts (arXiv 2512.23847);
Benhenda (2026), Look-Ahead-Bench (arXiv 2601.13770); Jia (2026), HindsightBench (arXiv 2607.18867); Li et al. (2025),
FINSABER (arXiv 2505.07078); DatedGPT (arXiv 2603.11838). The checklist weights are a documented judgement, not a
calibrated model.
