# Alert policy (0.2.0, revised in 0.2.1)

0.2.1 revisions after the independent review (docs/REVIEW_V020.md, docs/REVIEW_V020_RESPONSE.md): post-hoc
expectations are reported apart from pre-registered detections (D1); the P7 footprints of core 05 and D03 are
withdrawn (D2); the P1 threshold is shown with its sensitivity (D3); the P5 size is measured (D4).

A review report is only useful if every `NEEDS_REVIEW` is something a person must actually look at. Release 0.1.0
raised 40 `NEEDS_REVIEW` items in the benchmark battery on checks that the cases did not mention ("unexpected
review"; 36 cases). This document classifies every one of them, with the rule that now governs it.

## The INFO status

`INFO` is a fifth status: the check ran and produced a note worth reading, but **not an alert**. It is shown in its
own report section ("Information notes (not alerts)"), it is listed in `report.json` with its evidence and procedure,
it is never counted as a review item (`AuditResult.n_alerts()`, the battery's "unexpected review") and it is never
a PASS: an INFO says what the check could or could not establish. Severity order: CONFIRMED_ERROR > NEEDS_REVIEW >
NOT_EXECUTABLE > INFO > PASS. The exit code of `run` is unchanged (1 only with confirmed errors).

A finding may be downgraded to INFO only when one of these holds, and the finding text says which:

1. the same evidence is already judged, once, by another check (no double counting);
2. the observation describes the strength of the evidence, not a defect, and is below a documented materiality
   threshold;
3. there is no claim to contrast (nothing declared that the note could contradict).

## Classification of the 40 unexpected review items of 0.1.0

Decisions: **(a)** informative, downgraded to INFO; **(b)** genuine signal, the case now expects it (entry in
[CASE_CHANGES.md](CASE_CHANGES.md), applied by `cases/_generators/expectation_changes.py`); **(c)** bug, fixed.

| Policy | Check | Cases | n | Decision |
|---|---|---|---|---|
| P1 | sharpe_significance | R00, R01, R02, R04, R07, R08, R10, R11, R13, 05, 06, 06b, S03, S06 | 14 | (a) |
| P1 | sharpe_significance | R03, R06, 04, 08, 10 | 5 | (b) |
| P2 | omitted_costs ("test does not discriminate") | R00 | 1 | (b) |
| P3 | deflated_sharpe, multiple_testing with N = 1 | S07 | 2 | (a) |
| P4 | deflated_sharpe, multiple_testing, pbo | S04 | 3 | (b) |
| P4 | multiple_testing | S05 | 1 | (b) |
| P4 | trials_declared ("cannot be contrasted") | S07 | 1 | (b) |
| P5 | sharpe_autocorrelation | S06 | 1 | (c) |
| P6 | omitted_costs ("zero cost with non-zero turnover") | R04, R05, R06, R07, R10, R11, R13 | 7 | (b) |
| P7 | coverage (session gaps) | 05, D03 | 2 | (b) in 0.2.0; **withdrawn in 0.2.1** (rule 1), unexpected again |
| P7 | price_jumps | R10 | 1 | (b) |
| P7 | price_jumps | D03 | 1 | (b) in 0.2.0; **withdrawn in 0.2.1** (rule 1), unexpected again |
| P7 | dates ("calendar not declared") | R11 | 1 | (b) |
| | | | **40** | 0.2.1: 16 (a), 20 (b), 1 (c), 3 withdrawn |

### P1. sharpe_significance: review only when the history is clearly too short

A PSR below 0.95 says that the Sharpe ratio is not distinguishable from zero as a single test. That is a statement
about the strength of the evidence, not a defect of the backtest, and on the 3 to 6 month synthetic cases it fired
almost always. The new rule (convention `significance_review_ratio`, default 2):

- `NEEDS_REVIEW` when the Sharpe is positive and the Minimum Track Record Length (Bailey and Lopez de Prado 2012)
  exceeds **twice** the available history: the owner shows a positive result that would need more than double the
  data to be told apart from luck. This keeps the planted case S07 (MinTRL = 9.0 x T) and five other cases (MinTRL
  between 2.2 and 6.7 x T), which now expect it (b): a 3-month record that needs 7 more months is something a
  reviewer must be told.
- `INFO` when the history covers more than half of the MinTRL (14 cases with MinTRL between 1.1 and 1.7 x T: close to
  significance, nothing misleading), or when the Sharpe is not positive (R10: there is no claim of skill to test).

The threshold 2 is a documented judgement, not a statistical constant; rules.yaml can change it. The PSR, the MinTRL
and the interval are in the evidence of the INFO note exactly as before.

**Sensitivity (0.2.1).** The value 2 was chosen with the battery in view and falls in the gap between the cases it
separates (reviewer finding D3), so the battery is not evidence for it. Every battery case below PSR 0.95 and its
status at other ratios (R = review, i = INFO; `uv run python docs/simulations/alert_policy_checks.py`):

```
case                                              MinTRL/T     1   1.5     2     3     5
adversarial/R11_byma_calendar_undeclared              1.14     R     i     i     i     i
core/06_lookahead                                     1.19     R     i     i     i     i
core/06b_lookahead_without_availability               1.19     R     i     i     i     i
core/05_impossible_dates                              1.41     R     i     i     i     i
statistical/S06_llm_before_cutoff                     1.54     R     R     i     i     i
adversarial/R07_undeclared_leverage                   1.55     R     R     i     i     i
statistical/S03_autocorrelated_returns                1.58     R     R     i     i     i
adversarial/R01_zero_costs_declared                   1.59     R     R     i     i     i
adversarial/R02_small_costs_omitted                   1.59     R     R     i     i     i
adversarial/R04_lookahead_fundamentals                1.59     R     R     i     i     i
adversarial/R08_declared_slippage_omitted             1.59     R     R     i     i     i
adversarial/R13_unrecognised_results                  1.59     R     R     i     i     i
adversarial/R00_clean                                 1.70     R     R     i     i     i
lessons/L14_one_name_carries                          1.87     R     R     i     i     i
core/08_rules_vs_implementation                       2.24     R     R     R     i     i
lessons/L12_illiquid_and_cost_fragile                 2.31     R     R     R     i     i
adversarial/R06_undeclared_short                      2.45     R     R     R     i     i
adversarial/R03_first_day_commission                  3.22     R     R     R     R     i
core/10_independent                                   4.19     R     R     R     R     i
core/04_omitted_costs                                 6.74     R     R     R     R     R
statistical/S07_short_track_record                    8.98     R     R     R     R     R
lessons/L08_equal_weight_vs_cap_weighted             15.60     R     R     R     R     R
lessons/L09_equal_weight_vs_equal_weight             15.60     R     R     R     R     R
adversarial/R10_unadjusted_split                       inf     i     i     i     i     i
review items                                                  23    19     9     6     4
```

At ratio 1 every positive Sharpe below PSR 0.95 is a review item (the 0.1.0 behaviour less the negative-Sharpe
case); at 5 only the four longest shortfalls remain. Users who want the stricter reading set
`significance_review_ratio: 1`.

### P2. omitted_costs that cannot discriminate stays a review item

When declared and effective costs agree but the declared return is reproduced both with and without costs, the
test cannot say whether the result is net. docs/CONVENTIONS.md section 5 requires NEEDS_REVIEW here, and core case 10
already expected it. R00 (clean, 10 bps over a turnover of 4) is the same situation, so it now expects the review
item (b). The related finding "costs consistent, no declared result to contrast" is downgraded to INFO (rule 3:
there is no declared result to contradict; the reconstruction already uses the costs in the trades). No battery case
had that finding.

### P3. Deflation with a single trial repeats the PSR

With N = 1 the deflated Sharpe is, by definition, the PSR of P1, and the multiple-testing adjustment leaves the
p-value unchanged. Raising them as two more review items counted the same evidence three times. With N = 1 both are
INFO (rule 1) and point to sharpe_significance, which keeps the alert (S07 still has its expected NEEDS_REVIEW).

### P4. Statistical review items that follow from the planted search (b)

S04 logs 50 configurations (5 declared): a deflated Sharpe of 0.77 with 50 trials, a BHY p-value above 5% and a PBO
of exactly the 0.25 threshold are genuine consequences of that search. S05 (best of 100 noise strategies) failing the
multiple-testing adjustment is the textbook outcome. S07 declares one trial without a trials log; by
docs/CONVENTIONS.md section 5 an uncontrastable declaration is NEEDS_REVIEW. All five are now expected.

### P5. Autocorrelation: the single-lag band was a second 5% test (c, re-graded in 0.2.1)

The review fires when the autocorrelation is significant (Ljung-Box p < 0.05 **or** |rho_1| above a band) **and** the
naive annualised Sharpe exceeds the Lo-adjusted one by more than 10%. 0.2.0 moved the band from 1.96 / sqrt(T) to
2.576 / sqrt(T) on the argument that two 5% tests joined by OR are oversized. The 0.2.1 measurement (seeded Monte
Carlo, i.i.d. normal returns with a positive mean, 2,000 draws per T):

```
     T  LB only  LB or z1.96  LB or z2.576  review 1.96  review 2.576
   250    0.054        0.103         0.064        0.024         0.015
  1250    0.050        0.087         0.056        0.017         0.010
'review' = the full review condition (significance AND naive Sharpe more than 10% above the Lo-adjusted).
```

The significance component was indeed oversized with 1.96 (8.7-10.3%) and is close to 5% with 2.576 (5.6-6.4%). But
the full review condition, which also requires the inflation, had a size of only 1.7-2.4% even with 1.96, now
1.0-1.5%. So 0.1.0's rule was not producing false reviews at an excess rate: S06 (rho_1 = 0.067 against a band of
0.055) was an event of about 2%. The change is kept as a refinement of the significance component and re-graded from
"bug" to "refinement"; the planted AR(1) case S03 (phi = 0.6) is still detected.

### P6. Zero cost with turnover is a genuine review item (b)

Seven adversarial cases trade without declaring or charging any cost. No market trades for free; a reviewer must ask
whether the result is gross. The cases were written to test other problems, so they did not mention it; they now
expect it. R01, whose subject is exactly this, already did.

### P7. Footprints of the planted data problem (b; partly withdrawn in 0.2.1)

0.2.1: the core 05 `coverage` and D03 `coverage` / `price_jumps` expectations were withdrawn. They are consequences
already judged by `dates` and `ticker_identity`; counting them as detections contradicted rule 1, which this policy
uses to downgrade other items (reviewer finding D2). The tool still raises them, so they reappear as unexpected
review. The 0.2.0 text follows.

- core 05 plants a price row dated 2027: the series of DDD then has 629 missing sessions to that row (coverage).
- D03 joins two companies under one ticker with a five-month gap and a level shift: coverage reports the gap and
  price_jumps the seam, besides the expected ticker_identity error.
- R10 plants an unadjusted 2:1 split: price_jumps reports the split-like move (the case already accepted any data
  check through `@data`).
- R11 is "BYMA data without a declared calendar"; its own description says the right answer is a review item for
  the undeclared calendar, which `dates` raises.

## INFO in the 0.2.0 and 0.2.1 checks

0.2.1 additions: coverage_drift drops of fields outside a declared required_inputs (rule 3); duplicates of trades
with distinct trade ids (likely partial fills); liquidity_participation trades without volume when at least 90% of
the notional is measured; stability_and_concentration when no concentration test is applicable (descriptive only,
neither alert nor PASS).

The new checks use INFO under the same three rules:

- cost_sensitivity: excess return that survives 2x but not 3x the declared costs (below the materiality threshold of
  rule 2); no declared costs to scale (rule 3; zero cost is judged by omitted_costs); no gross excess return to
  protect (rule 3).
- stability_and_concentration: the result disappears without its best 1% of periods while the Sharpe ratio is not
  significant (rule 1: for a weak Sharpe this is the same evidence sharpe_significance judges).
- protocol_integrity: n_trials not declared, so the validation configurations are used as the number of trials
  (rule 3: a note on how the deflated Sharpe was computed).
- dividend_corporate_actions does not use INFO; ratio breaks inside a frozen run are folded into the frozen-price
  finding instead of being reported twice (rule 1).

## Result

Pre-registered detections (expected outcomes written before the tool ran on the case) and post-hoc expectations
(written after seeing the output, flagged `"post_hoc": true`) are reported separately and never added together.

| Battery | Version | NEEDS_REVIEW findings | Unexpected NEEDS_REVIEW | INFO notes | Pre-registered detections met | Post-hoc expectations met |
|---|---|---|---|---|---|---|
| 36 cases of 0.1.0 | 0.1.0 | 57 | **40** | - | 40 / 40 | - |
| same 36 cases | 0.2.1 | 40 | **3** | 26 | 40 / 40 | 20 / 20 |
| all 52 cases | 0.2.1 | 53 | **6** | 36 | 52 / 52 | 20 / 20 |

The reduction from 40 to 3 unexpected items is mostly relabelling, not a change of the tool: 20 items are now
expected (post hoc) and 16 are INFO. The 3 left on the old cases are the withdrawn P7 footprints; the other 3 on the
full battery are `sharpe_significance` on lesson cases L08, L09 and L12 (genuine under P1; the lesson cases were
pre-registered for other checks and are not edited after the run). Commands and full output:
[VALIDATION_EVIDENCE.md](VALIDATION_EVIDENCE.md).

## Rules for future changes

- A new NEEDS_REVIEW that a case does not mention is reported by `lockin-validate cases` as "unexpected review". It
  is resolved by one of (a), (b) or (c) with an entry in this file; never by editing expected.json by hand.
- An expected detection is never removed to reduce noise.
- INFO never replaces CONFIRMED_ERROR, and never replaces NEEDS_REVIEW when the conclusion rule of
  docs/CONVENTIONS.md section 5 requires a review item.
