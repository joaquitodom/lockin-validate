# Response to the independent review of 0.2.0 (release 0.2.1)

Review: [REVIEW_V020.md](REVIEW_V020.md), cases in `cases_review_v020/` (commits 56c12c5, 6e6337c). None of the
reviewer's files (cases, expected.json, generator, review text) were edited. Date: 2026-10-28.

## Score on the reviewer's cases

| | 0.2.0 | 0.2.1 |
|---|---|---|
| Whole-case battery verdict (their runner, their expectations) | 18 / 28 | **27 / 28** |
| Firm detections (13 single-check planted cases + end-to-end + LockIn-like) | 15 / 21 | **21 / 21** |
| Clean cases correct on their target check | 9 / 12 | **12 / 12** |
| False positives (battery count) | 4 | 1 |
| Unexpected NEEDS_REVIEW (case x check) | 15 | 14 |

The remaining failure is V18 (see "Disagreements"). Command and output are in VALIDATION_EVIDENCE.md.

## Findings and what was done

| Finding | Action in 0.2.1 |
|---|---|
| H1 coverage_drift PASS when the inputs disappear (V02) | Periods now run to the last period the strategy uses (max of rules.yaml period.end, signal decisions and trades; minus 120 days of publication lag for fundamentals); a period without rows counts as 0%. V02 -> NEEDS_REVIEW from 2022Q1. |
| H2 dividend PASS with 0 events checked (V14) | No PASS without a compared adjusted / as-traded series: NOT_EXECUTABLE with the reason. Added the suggested ex-date drop test on the adjusted series (>= 3 dividends of >= 0.5%, mean ex-date return below -half the yield and t < -2): V14 -> NEEDS_REVIEW "adjusted prices drop by about the dividend". PASS titles now state the compared sessions and how many declared events were verifiable. |
| H3 input_sufficiency CONFIRMED_ERROR from letter case (V06) | Declared names are lower-cased like the headers. A CONFIRMED_ERROR now also requires the rows to be below the declared minimum even if every input missing from all tables were present; otherwise NEEDS_REVIEW. |
| H4 protocol CONFIRMED_ERROR on one 'holdout' look (V10) | Explicit synonyms (holdout, oos, out_of_sample, final_test -> test; repro, rerun -> reproduction; val, cv -> validation; training, fit -> train; diag, analysis -> diagnostic), logged as a transformation. An unrecognised purpose on a reserved window is NEEDS_REVIEW, never contamination. Title now says "not used once: N runs break the protocol". |
| M1 benchmark_fit declaration-only PASS (V11) | A benchmark declared equal-weighted is contrasted with the equal-weight universe computed from prices: NEEDS_REVIEW above 1% tracking error or 0.5 pp of choice effect (conventions.benchmark_universe_tracking_error). The PASS text says whether the contrast was possible. |
| M2 order slicing (V16) | Participation is computed on the strategy's ticker-day total; findings are per ticker-day. |
| M3 stale fundamentals (V28) | conventions.max_input_age_days (default 400 days from period_end: an annual reporter plus a filing lag). Older as-of values count as missing; V28's test years are now flagged. 400 is deliberately loose (annual reporters must not be flagged); quarterly packages should set about 230. |
| M4 PASS covering only measured trades (V17) | Unmeasured trades are disclosed with their notional share; below 90% of notional measured (conventions.min_volume_coverage) the check is NEEDS_REVIEW and never PASS; above it, an INFO note and a PASS title that states the coverage. |
| M5 declared rule silently dropped (V23) | Every declared rule is reported. No in-sample value -> NEEDS_REVIEW "never computed in sample"; no out-of-sample value or column missing -> NOT_EXECUTABLE for that rule. No PASS while a declared rule is unevaluated. |
| M6 stability PASS naming tests that did not run | The PASS title lists only the tests that ran; skipped ones are listed with their minimum; with no applicable test the result is INFO. |
| M7 required_inputs ignored by coverage_drift (V04) | With required_inputs declared, drops of other fields are INFO notes (rule 3). |
| L1 hidden constants | Documented in CHECKS.md (catalogue text), INPUT_SPEC.md and LIMITATIONS.md. |
| L2 volume unit | INPUT_SPEC.md: `volume` must be consolidated volume in shares; the confirmed error depends on it. |
| L3 universe from the table | Stated in CHECKS.md (catalogue) and LIMITATIONS.md. |
| L4 duplicates on child fills with distinct ids (V16) | INFO "repeated trades with distinct trade ids (partial fills?)". |
| L5 freeze starting the session after the ex-date (V13) | The frozen search starts at the ex-date or the next session; V13 is now CONFIRMED_ERROR "frozen" (the as-traded price moves). |
| D1 post-hoc expectations counted as detections | Every expectation added after seeing output carries `"post_hoc": true`; the battery reports pre-registered detections and post-hoc expectations on separate lines and excludes the latter from detection rates. README and VALIDATION_EVIDENCE give them separately. |
| D2 P7 footprints vs rule 1 | Withdrawn: core 05 `coverage` and D03 `coverage` / `price_jumps` are no longer expected (they are the same evidence `dates` and `ticker_identity` judge). They are again reported as unexpected review, which is honest: the tool still raises them. R10 and R11 stay (the reviewer accepted them). |
| D3 P1 threshold placed in the gap | ALERT_POLICY.md now shows, for every case below PSR 0.95, the status at ratios 1, 1.5, 2, 3 and 5 (23, 19, 9, 6, 4 review items) and says that 2 was chosen with the battery in view; the battery is not cited as support. |
| D4 P5 size not measured | Measured by a seeded Monte Carlo (2,000 draws, T = 250 and 1,250; docs/simulations/alert_policy_checks.py). The significance part had a size of 0.087-0.103 with the 1.96 band and 0.056-0.064 with 2.576; the full review condition (also requiring > 10% inflation) had 0.017-0.024 with 1.96 and 0.010-0.015 with 2.576. P5 is therefore reclassified: the full rule was not oversized; the change is a refinement of the significance component, and S06 was a ~2% event. |
| BYMA labels | 2026-11-09 (packaged file) and 2026-07-10 (research table) relabelled `verified = partial`. |
| Item 11 (add the reviewer's gap cases to our battery) | Not done: the reviewer's cases stay in `cases_review_v020/` as an independent battery run with its own expectations; copying them into `cases/` would make them our expectations. |

## Disagreements

**V18 (reviewer's own generator defect).** The case raises `reconstruction` CONFIRMED_ERROR "sells that leave a
negative quantity without declared short selling". The reviewer states in REVIEW_V020.md section 2 that this comes
from the generator (a buy/sell counter shared by two tickers, so IL2 starts with a sell). The confirmed error is
correct for the delivered trades, and suppressing it to pass the case would be a false negative. We leave the case
failing and its expected.json unchanged; the target check of V18 (liquidity_participation) returns PASS as
expected.

**stability INFO rule (reservation in section 4).** Kept: with a non-significant Sharpe, losing the result without
the best 1% of days carries the same information as the low PSR (the day test flags Sharpe below about 0.4 by
construction). It is an INFO note with its evidence, never hidden. We accept that this is a judgement and list it in
ALERT_POLICY.md.

No reviewer expected.json is believed wrong.
