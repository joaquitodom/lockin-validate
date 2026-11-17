# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses
semantic versioning.

## [0.3.1] - 2026-11-17

No change to the checks.

### Added
- The working paper (LaTeX sources and PDF) in `paper/`, linked from the README.
- Zenodo metadata (`.zenodo.json`) for DOI archiving of releases; `python -m lockin_validate` entry point.

## [0.3.0] - 2026-11-06

Use-case modules: validation of other kinds of financial models beyond the backtest of a trading strategy. The core
checks are unchanged. The modules are review aids, not a certification or a statement of regulatory compliance.

### Added
- Use-case registry (`lockin_validate.usecases`: `UseCase`, `register`, `run_usecases`, `describe`). A module declares
  its input tables, schema, aliases, requirements, catalogue entries, references, conventions and profiles in one file
  and `register` merges them into the package-wide tables. It runs automatically when one of its detect files is in
  the input folder; `--use-case NAME` (repeatable, or `all`) forces it and reports NOT_EXECUTABLE with the missing
  input when its tables are absent. Contract: docs/dev/USECASE_MODULE_GUIDE.md.
- `signals` (alpha signal research, 5 checks): per-date Spearman rank IC with Newey-West t-statistics under
  overlapping horizons and the Harvey-Liu-Zhu hurdle as context, quantile spread and monotonicity, rank
  autocorrelation, top-bucket turnover and half-life, forward-return alignment and a look-ahead hint from the IC with
  the contemporaneous return.
- `ml` (supervised model validation, 6 checks): temporal overlap, purging and embargo, train / validation / test
  metric gap, calibration (ECE, Brier with Murphy decomposition, Hosmer-Lemeshow), PSI and label-shift test, target
  leakage in features, and models scored on the test split against the declared trials.
- `risk` (VaR / ES backtesting, 6 checks): Kupiec proportion-of-failures, Christoffersen independence and
  conditional coverage, Basel traffic-light zones, Acerbi-Szekely ES tests, chi-square homogeneity of exception
  rates, input coherence (sign convention, monotone quantiles, ES >= VaR).
- `forecast` (point forecasts, 6 checks): forecast origin integrity (including revised data), Diebold-Mariano with
  the Harvey-Leybourne-Newbold correction against a naive benchmark, Mincer-Zarnowitz bias Wald test,
  Pesaran-Timmermann directional test, error dynamics (Ljung-Box and its multi-step variant), expected-maximum
  selection check across several models.
- `portfolio` (target weights, 6 checks): declared constraints on every date, HHI / effective N / top-5 and group
  concentration, turnover net of drift, weights against positions x prices, Sharpe difference against 1/N
  (Jobson-Korkie with the Memmel correction), active share against a benchmark (closet indexing).
- `live` (live track record, 6 checks): period integrity against the declared start, live against the shadow
  backtest (tracking error, Sharpe difference, PSR), performance decay with the expected out-of-sample haircut,
  structural break (CUSUM and a mean-shift test), execution quality (slippage, fill ratio, overrides), declared
  against realised metrics.
- 35 new catalogue entries (72 checks in total, regenerated docs/CHECKS.md), 11 new input tables
  (docs/INPUT_SPEC.md, "Use-case module tables") and 11 new review profiles.
- CLI: `lockin-validate usecases` lists the modules; `run --use-case NAME` (repeatable, or `all`). MCP: new tool
  `list_use_cases`. `lockin-validate init` scaffolds the module tables.
- Documentation: docs/usecases/ (one document per module), docs/dev/USECASE_MODULE_GUIDE.md, a "Use cases" section in
  README.md and README.es.md and section 7 of docs/CONVENTIONS.md (module conventions and the `rules.yaml` keys they
  read).
- Benchmark battery: 57 new cases in cases/usecase_*/ (signals 8, ml 12, risk 8, forecast 8, portfolio 11, live 10),
  generators in cases/_generators/. The battery now has 109 cases (52 before).

### Changed
- Version 0.3.0 (pyproject.toml, `__version__`, CITATION.cff).

### Fixed (two independent pre-registered reviews, docs/REVIEW_V030_A.md and docs/REVIEW_V030_B.md; responses in
docs/REVIEW_V030_A_RESPONSE.md and docs/REVIEW_V030_B_RESPONSE.md)
- signals: tied signal values share a quantile bucket (ties were broken by file order and produced fake spreads);
  constant signals make turnover and quantile spread NOT_EXECUTABLE.
- ml: rows with a blank probability are dropped before AUC, calibration and PSI (same n everywhere); an undefined
  AUC makes the overfit gap NOT_EXECUTABLE; calibration with a 0% or 100% base rate is no longer a silent PASS.
- forecast: horizons counted in observation steps, not calendar days (weekends created spurious horizons); exact
  duplicate forecasts dropped and disclosed; bias flagged on the joint Mincer-Zarnowitz Wald test only (the former
  "Wald or |t|>2" rule had a 12.5% false-alarm rate at n=30 in Monte Carlo).
- portfolio: off-schedule trading judged on changes of the delivered target weights, not on drift (false
  CONFIRMED_ERROR with constant targets); short-only and market-neutral books are not compared with long-only 1/N.
- live: a missing NAV no longer merges two returns into one; gap rule relative to the native frequency (monthly
  records were flagged); HAC test with a small-sample correction (size 8.6% -> 5.0% at n=30); returns in percent
  units flagged.
- risk: Kupiec decision on the exact binomial acceptance region, consistent with the printed region.
- `python -m lockin_validate` works; `usecases` lists the detect files of every module.

## [0.2.1] - 2026-10-28

Fixes from the independent review of 0.2.0 (docs/REVIEW_V020.md; response in docs/REVIEW_V020_RESPONSE.md). Score
on the reviewer's 28 pre-registered cases: 18 -> 27 (the remaining one is a defect of the reviewer's generator).

### Fixed
- coverage_drift: periods without any row count as 0% coverage up to the last period the strategy uses (it returned
  PASS when the vendor stopped delivering entirely).
- dividend_corporate_actions: no PASS when no adjusted / as-traded comparison was possible (NOT_EXECUTABLE); new
  ex-date drop test on the adjusted series; frozen prices are also searched from the session after the ex-date.
- input_sufficiency: required_inputs matched case-insensitively; CONFIRMED_ERROR only when the declared minimum is
  broken even counting inputs absent from every table as present; as-of fundamentals older than
  conventions.max_input_age_days (400) count as missing.
- protocol_integrity: purpose synonyms (holdout, oos, repro, ...) mapped and logged; an unrecognised purpose is a
  review item, never a confirmed error; corrected title.
- liquidity_participation: participation per ticker-day (sliced orders judged together); trades without volume are
  disclosed and below 90% of notional measured there is no PASS.
- benchmark_fit: a benchmark declared equal-weighted is contrasted with the equal-weight universe computed from
  prices.
- conditional_rule_activation: every declared rule is reported; a rule never computed in sample is a review item.
- stability_and_concentration: the PASS title names only the tests that ran; INFO when none applies.
- duplicates: repeated trades with distinct trade ids are INFO (partial fills), not a review item.

### Changed
- Battery reporting: pre-registered detections and post-hoc expectations (`"post_hoc": true`) are reported separately;
  three post-hoc P7 expectations withdrawn (docs/CASE_CHANGES.md).
- docs/ALERT_POLICY.md: sensitivity of the P1 threshold shown; P5 size measured by simulation
  (docs/simulations/alert_policy_checks.py) and re-graded from bug to refinement.
- BYMA: 2026-11-09 and 2026-07-10 relabelled `verified = partial`.
- New conventions: max_input_age_days, min_volume_coverage, benchmark_universe_tracking_error.

## [0.2.0] - 2026-10-28

### Added
- Six check families, each motivated by a failure of the LockIn case study and documented in docs/CHECKS.md with its
  motivation and references: `coverage_drift` and `input_sufficiency`; `protocol_integrity`; `benchmark_fit`;
  `dividend_corporate_actions`; `liquidity_participation` and `cost_sensitivity`; `stability_and_concentration` and
  `conditional_rule_activation`.
- Optional inputs: `benchmark_returns.csv`, `universe_returns.csv`, `unadjusted_prices.csv`, `dividends.csv`,
  `run_log.csv`, `regimes.csv`, `protocol.yaml`; rules.yaml keys `benchmark`, `required_inputs`, `min_input_share`,
  `conditional_rules` and new conventions (docs/INPUT_SPEC.md). Templates in `lockin-validate init`.
- `INFO` status: a note shown in the report that is not an alert (`AuditResult.n_alerts()` counts only
  CONFIRMED_ERROR and NEEDS_REVIEW). docs/ALERT_POLICY.md defines when a finding may be INFO.
- 16 lesson cases (`cases/lessons/`, generator `lessons_cases.py`) with expectations committed before the checks;
  22 unit tests for the new checks and the alert policy.
- BYMA holiday calendar 2015-2026 with sourced provenance (docs/CALENDAR_BYMA.md, data/calendars/).
- The battery runner prints the total of unexpected review items and false positives.

### Changed
- Alert noise: the 40 unexpected NEEDS_REVIEW of the 0.1.0 battery were classified (16 now INFO, 23 now expected by
  their cases via `cases/_generators/expectation_changes.py` and docs/CASE_CHANGES.md, 1 bug fixed): 0 left on those
  36 cases, no expected detection lost.
- `sharpe_significance` is a review item only when the Sharpe is positive and the MinTRL exceeds
  `significance_review_ratio` (2) times the history; otherwise INFO.
- `deflated_sharpe` and `multiple_testing` with a single trial are INFO (they repeat the single-test PSR).
- `omitted_costs` "costs consistent, no declared result to contrast" is INFO.
- The deflated Sharpe uses N = max(declared trials, trials.csv columns, validation configurations of run_log.csv).

### Fixed
- `sharpe_autocorrelation`: the single-lag band was an unadjusted second 5% test joined by OR with Ljung-Box; it is
  now 2.576 / sqrt(T) (99%), keeping the combined size near 5% (false review on i.i.d. case S06).

## [0.1.0] - 2026-10-27

First public version (not yet published).

### Added
- Input package reader with manifest (sha256 of every input), own schema and type validation, column aliases,
  required/optional inputs per check, transformation log (applied vs proposed, nothing fixed silently).
- Data checks: duplicates, dates (NYSE / BYMA / none calendars), essential fields, coverage against the calendar, stale
  prices, price jumps and bad ticks, declared corporate actions, accuracy against a reference, point-in-time
  fundamentals, survivorship, ticker identity, trade before signal, signal data after decision.
- Reconstruction of positions, cash and NAV from trades (return base = initial cash) and reconciliation against
  declared positions and results.
- Strategy checks: look-ahead with availability timestamps and a rank-correlation hint, omitted costs (commission and
  slippage separately, zero cost with turnover), metric errors under alternative conventions, rules vs implementation.
- Statistics: Sharpe standard error, Lo (2002) adjustment, PSR, MinTRL, deflated Sharpe, multiple-testing haircut, PBO
  via CSCV, declared number of trials, LLM look-ahead risk checklist.
- Reports in Markdown, JSON and static HTML with disclaimer, evidence, procedure, limitations and prioritised actions.
- CLI (`run`, `init`, `cases`, `explain`, `checks`), Python API (`audit`, `run`), optional MCP server.
- Benchmark battery of 36 synthetic cases (core, adversarial, statistical, data) with generators and expected outcomes.
- Independent oracle, hand-computed case, metamorphic tests and an offline test.

### Ported
- Core review blocks and synthetic cases from the internal review core; data and statistical checks from the earlier
  prototype. See docs/CASE_CHANGES.md.
