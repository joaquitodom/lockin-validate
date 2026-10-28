# Alert policy (0.2.0)

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
| P7 | coverage (session gaps) | 05, D03 | 2 | (b) |
| P7 | price_jumps | R10, D03 | 2 | (b) |
| P7 | dates ("calendar not declared") | R11 | 1 | (b) |
| | | | **40** | 16 (a), 23 (b), 1 (c) |

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

### P5. Autocorrelation: the single-lag band was a second 5% test (c)

The review fired when the Ljung-Box test was significant **or** |rho_1| > 1.96 / sqrt(T). Two tests at 5% joined by
OR have a size above 5%: on S06 (i.i.d. noise, 1,250 observations) rho_1 = 0.067 crossed the 1.96 band (0.055) while
Ljung-Box gave p = 0.17. The single-lag band now uses 2.576 / sqrt(T) (99%), so the combined test stays close to 5%.
The planted AR(1) case S03 (phi = 0.6) is still detected; S06 now passes.

### P6. Zero cost with turnover is a genuine review item (b)

Seven adversarial cases trade without declaring or charging any cost. No market trades for free; a reviewer must ask
whether the result is gross. The cases were written to test other problems, so they did not mention it; they now
expect it. R01, whose subject is exactly this, already did.

### P7. Footprints of the planted data problem (b)

- core 05 plants a price row dated 2027: the series of DDD then has 629 missing sessions to that row (coverage).
- D03 joins two companies under one ticker with a five-month gap and a level shift: coverage reports the gap and
  price_jumps the seam, besides the expected ticker_identity error.
- R10 plants an unadjusted 2:1 split: price_jumps reports the split-like move (the case already accepted any data
  check through `@data`).
- R11 is "BYMA data without a declared calendar"; its own description says the right answer is a review item for
  the undeclared calendar, which `dates` raises.

## Result

On the 36 cases of 0.1.0: **40 unexpected NEEDS_REVIEW before, 0 after**; every expected detection of 0.1.0 is still
met (36 of 36 cases with all expected outcomes, detection rate unchanged per check). Figures for the full 0.2.0
battery, including the lesson cases and the new checks, are in [VALIDATION_EVIDENCE.md](VALIDATION_EVIDENCE.md).

## Rules for future changes

- A new NEEDS_REVIEW that a case does not mention is reported by `lockin-validate cases` as "unexpected review". It
  is resolved by one of (a), (b) or (c) with an entry in this file; never by editing expected.json by hand.
- An expected detection is never removed to reduce noise.
- INFO never replaces CONFIRMED_ERROR, and never replaces NEEDS_REVIEW when the conclusion rule of
  docs/CONVENTIONS.md section 5 requires a review item.
