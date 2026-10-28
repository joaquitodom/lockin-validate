# Limitations

lockin-validate is an automated, offline review of the inputs a strategy owner delivers. Read these limits before
relying on any report. The same list (plus every NOT_EXECUTABLE reason of the run) is printed in each report.

## What it is not

- **Not a certification, an audit opinion or an independent professional approval.** A qualified person must review
  the findings, the NEEDS_REVIEW items and these limitations before any decision.
- **No claim about profitability**, past or future, and no investment advice. PASS means "this check found no
  problem within its scope", never "this strategy works".
- **No external data.** The tool judges internal coherence. A wrong price that is coherent with everything else is
  not detected unless an independent `reference_prices.csv` is provided, and even then the tool cannot say which
  source is right.
- **No execution evidence.** Reproducing the declared NAV from the delivered trades proves the trades are coherent
  with that NAV; it does not prove the trades happened. That needs third-party statements (broker, custodian).

## Scope limits of each block

- **Reconstruction**: values at the close; uses the executed price and commission delivered; does not model
  dividends, splits or other corporate actions unless they are already in adjusted prices; no intraday, no
  margin interest, no borrow fees, no FX. Large jumps and declared splits are checked, not repaired.
- **Calendars**: NYSE rules are hand-written from 2000 onwards (special closures listed in the code). The packaged
  BYMA holiday file covers 2015-2026 (206 closed days: 159 verified, 35 partially verified, 12 not verified; see
  docs/CALENDAR_BYMA.md). Open item: 2026-11-10 (papal visit, holiday only in CABA and Córdoba) is included as
  closed with `verified = partial` because BYMA has not said whether there is trading; check BYMA's notice before
  that date. Provide your own file with `conventions.holidays_file` for other years or markets.
- **Look-ahead**: proven only when availability timestamps (`available_from`, `filing_date`) and `data_date` are
  delivered, and only as declared: if `data_date` is wrong the check trusts it. The rank-correlation hint only
  catches gross cases (a signal almost perfectly correlated with the subsequent return); subtle leakage, leakage
  through hyper-parameters or through the universe definition is not detected.
- **Fundamentals point-in-time**: internal coherence of dates only; dates are not checked against a regulator's
  filing index.
- **Survivorship and identity**: relative to the universe and security master delivered. Without them only
  heuristics run (survivor-only panel, long gap plus level shift), which can raise review items but never PASS.
  The effect on returns is not quantified (that needs re-running the strategy on the corrected universe).
- **Rules vs implementation**: re-executes only ranking on one signal column, top N, periodic rebalance (monthly,
  weekly, daily; first or last day) and equal weights. Anything else is NOT_EXECUTABLE. It re-ranks the delivered
  signal column: it verifies selection, not how the signal was computed. Coincidence does not prove correctness
  (Knight and Leveson, 1986).
- **Costs**: when declared costs are below the total-return tolerance the test cannot discriminate and says so
  (NEEDS_REVIEW). Market impact is not modelled.
- **Metrics**: alternative conventions only explain a mismatch; the tool cannot say which convention is "right".
- **Statistics**: PSR, DSR, haircut and PBO are conditional on the declared number of trials being complete and on
  the data being correct; they say nothing about broken data or look-ahead. The haircut assumes independent tests;
  correlation between trials is only partially captured (cross-trial variance in the DSR). Reality Check / SPA,
  Romano-Wolf and combinatorial purged cross-validation are not implemented. The Lo (2002) adjustment truncates the
  autocorrelation sum at `autocorrelation_max_lag` lags.
- **LLM look-ahead**: a risk score from declarations; memorisation is never tested, so the check never returns PASS.
- **Thresholds and tolerances** are documented choices (docs/CONVENTIONS.md), not laws; they can be changed in
  rules.yaml and the report shows which values were used.

## Benchmark battery limits

The battery (cases/) shows that the tool detects the problems planted in synthetic cases and does not raise
confirmed errors on clean ones. It does not prove correctness outside those cases. All cases are synthetic; the
original case derived from vendor prices was replaced by a synthetic one (docs/CASE_CHANGES.md).

## Constants of the 0.2.x checks (documented choices, not laws)

- coverage_drift: at least 5 periods, baseline = median of at least 4 previous ones; fundamentals are expected up to
  120 days before the last date the strategy uses. Without universe.csv or a rules.yaml universe, the members are the
  tickers present anywhere in the table, so a genuinely shrinking universe reads as drift.
- input_sufficiency: default minimum share 0.5 when none is declared; as-of fundamentals expire 400 days after their
  period_end (conventions.max_input_age_days; about 230 suits quarterly reporters).
- dividend_corporate_actions: ratio tolerance 0.001; an event is not discriminable below 2 x tolerance (dividend
  yields under about 0.2% go unchecked); the ex-date drop test needs 3 dividends of at least 0.5%.
- liquidity_participation: ADV over 20 sessions with at least 5 that have volume; sigma from up to 60 returns (at
  least 20); `volume` must be consolidated volume in shares: with primary-venue or currency volume the "larger than
  the day's volume" error is not reliable.
- benchmark_fit: at least 20 common dates; R2 floor 25%; 1% tracking error (0.5 pp choice effect) to contrast a
  declared equal-weighted benchmark.
- stability_and_concentration: calendar years from 3 calendar years, halves otherwise (the subperiod rule needs at
  least 3 subperiods); day test from 250 periods; name test from 3 names; with a non-significant Sharpe the day test
  is an INFO note.
- conditional_rule_activation: 10% / 50% activation thresholds.
- sharpe_significance: `significance_review_ratio` = 2 was chosen with the battery in view; its sensitivity is in
  docs/ALERT_POLICY.md.
