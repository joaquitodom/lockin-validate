# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses
semantic versioning.

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
