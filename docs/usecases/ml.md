# Use case `ml`: validation of a supervised machine-learning model

**Who it is for.** The data scientist who built a model used in finance (return prediction, default or credit
scoring, classification of events) and the model-risk team that validates it in the SR 11-7 sense: conceptual
soundness of the evaluation protocol, outcomes analysis on the delivered predictions, and the stability of the
population the model is applied to. The module never refits the model and never reads the network: it validates
the sampling protocol and the predictions as delivered, from the tables below.

Activate it by placing `ml_samples.csv` and `ml_predictions.csv` in the input folder (`lockin-validate run
<folder>`), or run it alone with `--use-case ml`. Profiles `ml_classification` and `ml_regression` fix the task
(`ml_task`); without them the task is inferred (classification when `actual` has exactly two distinct values).

## Inputs

| File | Columns (required in bold) | Notes |
|---|---|---|
| `ml_samples.csv` | **sample_id, timestamp, split**, label_end, ticker, fold | `split` in train / validation / test (synonyms: training, fit, in_sample -> train; val, dev, valid -> validation; oos, holdout, out_of_sample, oot -> test). `label_end` is the time at which the label is known (end of the forward-return window). `fold` declares a purged K-fold: a sample is then listed once per fold with its role in that fold. |
| `ml_predictions.csv` | **sample_id, prediction, actual**, probability, model, fold | `probability` is the predicted probability of the positive class (classifiers). `model` names the model or version; several values mean several models were scored. `fold` joins K-fold predictions to the right role. |
| `ml_features.csv` | **feature**, available_from_lag_days, source, importance | `available_from_lag_days` > 0 means the feature value is known only that many days after the sample timestamp. |
| `ml_feature_values.csv` | **sample_id, feature, value** | Long format, can be large. Used for per-feature PSI and for the target-correlation leak test. |

Shared with the core: `rules.yaml` (`conventions:` overrides below; `research.n_trials`) and
`declared_results.json` (`n_trials`). Column aliases are listed in `src/lockin_validate/usecases/ml.py`
(for example `date` -> `timestamp`, `y_true` / `label` -> `actual`, `prob` / `score` -> `probability`).

## Checks

### `ml_split_leakage`: split leakage

- **What.** (a) The same `sample_id` in two splits. (b) A test timestamp inside `[min, max]` of the training
  timestamps. (c) A training `label_end` later than the first test timestamp: the training label was computed
  with information from the test period (no purging). (d) Gap between the last training `label_end` and the first
  test timestamp shorter than `ml_embargo_days`. (e) Features with `available_from_lag_days > 0`. When `fold`
  declares a purged K-fold (every fold has train and test rows), (a)-(d) are evaluated inside each fold: a
  training sample whose window `[timestamp, label_end]` intersects the fold's test block, or a training sample
  inside the embargo after the block, is listed. Validation samples inside the training window are a review item,
  not an error.
- **Why.** A test sample that shares dates, ids or label windows with the training set is not out of sample, and
  every test metric is then optimistic by an unknown amount. In finance, labels are forward-looking (a 20-day
  return), so the last training labels overlap the first test observations unless the training set is purged.
- **Status.** CONFIRMED_ERROR for (a), (b), (c), (e) with the offending rows. NEEDS_REVIEW when `label_end` is
  absent (purging cannot be verified), when the embargo is not respected, when validation overlaps training, or
  when split values were not recognised. PASS only with `label_end` present and every condition verified.
- **Fix.** Test strictly after the last training `label_end` plus the embargo; one split per sample; features
  lagged to their publication date; in cross-validation, purge and embargo (Lopez de Prado 2018, ch. 7).
- **Allows.** Proving a leak from the sampling table alone. **Does not allow.** Detecting leaks hidden inside
  feature construction (see `ml_target_leakage`) or verifying purging without `label_end`.
- **References.** Lopez de Prado (2018) ch. 7; Bergmeir and Benitez (2012); Kaufman et al. (2012); SR 11-7.

### `ml_overfit_gap`: train / validation / test metric gap

- **What.** Per split and per model, from the delivered predictions. Classification: rank AUC (Mann-Whitney U,
  ties one half) with the Hanley and McNeil (1982) standard error, Gini = 2 AUC - 1, KS, accuracy at 0.5,
  log-loss and Brier when a probability is delivered. Regression: R2, RMSE, MAE, Spearman IC.
- **Status.** NEEDS_REVIEW when the test metric loses more than `ml_overfit_gap_review` of the training excess
  (AUC - 0.5 for classifiers, R2 for regressions) and, for AUC, the drop also exceeds 2 combined standard errors
  (a smaller drop is sampling noise and is reported as INFO); or when the test metric sits at the naive baseline
  (AUC <= 0.5 + 2 SE, R2 <= 0). INFO with the metric table otherwise. NOT_EXECUTABLE when the test split has
  fewer than `ml_min_test_samples` scored rows (the count is stated) or no training predictions were delivered.
- **Why.** A model that is excellent in sample and ordinary out of sample has memorised its training data; the
  in-sample figure is the one that gets reported (Arnott, Harvey and Markowitz 2019).
- **Fix.** Regularise or simplify, repeat the evaluation with purged cross-validation, report the test metric with
  its standard error.
- **Allows.** Measuring the gap. **Does not allow.** Separating overfitting from a regime change (see
  `ml_population_stability`); judging a model with only test predictions.
- **References.** Hanley and McNeil (1982); Arnott, Harvey and Markowitz (2019); Lopez de Prado (2018).

### `ml_calibration`: probability calibration

- **What.** On the test split, `ml_calibration_bins` quantile bins of the predicted probability: reliability
  table (mean probability vs observed rate per bin), expected calibration error ECE = sum n_b / N |p_b - o_b|
  (Guo et al. 2017), Brier score (Brier 1950) with its Murphy decomposition (reliability, resolution,
  uncertainty), Hosmer-Lemeshow chi-square, base rate in train and test, mean predicted probability against the
  test base rate.
- **Status.** NEEDS_REVIEW when ECE > `ml_calibration_ece_review` (0.05) and the Hosmer-Lemeshow test rejects
  calibration at `ml_calibration_hl_p` (0.01), or when the mean probability differs from the base rate by more
  than 2 binomial standard errors. The Hosmer-Lemeshow gate exists because the ECE of a perfectly calibrated
  model is biased upward on a few hundred rows. PASS otherwise (on at least `ml_min_test_samples` rows).
  NOT_EXECUTABLE for regressions ("calibration applies to probabilistic classifiers"; prediction intervals are
  not supported), without a `probability` column, or with too few test rows.
- **Why.** A score that ranks but is not calibrated gives wrong expected losses, thresholds and position sizes
  even when the AUC is fine.
- **Fix.** Platt scaling or isotonic regression fitted on the validation split; report the reliability table.
- **References.** Guo et al. (2017); Brier (1950); SR 11-7.

### `ml_population_stability`: PSI and label shift

- **What.** PSI = sum (actual share - expected share) ln(actual / expected) of the model score (probability, else
  prediction) between train and test on 10 quantile bins defined on train (empty bins floored at 1e-4); the same
  per feature when `ml_feature_values.csv` is delivered; a label-shift test (two-proportion z test of the base
  rate for classifiers, Welch t test of the mean for regressions).
- **Status.** NEEDS_REVIEW when any PSI exceeds `ml_psi_review` (0.10), high priority above `ml_psi_error`
  (0.25), or when the label shifts materially (p < `ml_label_shift_p` and more than 5 pp of base rate or
  Cohen's d > 0.2). INFO otherwise. Never CONFIRMED_ERROR: drift is not an error of the model.
- **Why.** The test metric then describes a population the model was not fitted on; in credit scoring a
  scorecard is recalibrated or rebuilt when PSI crosses the convention (Siddiqi 2006). The thresholds 0.10 / 0.25
  are an industry convention, not a hypothesis test.
- **Fix.** Confirm the shift is genuine (regime, segment mix) rather than a processing difference; monitor PSI in
  production; recalibrate.
- **References.** Siddiqi (2006); SR 11-7.

### `ml_target_leakage`: target leakage in features

- **What.** On the training split, for every feature in `ml_feature_values.csv` with at least 30 values: the
  Spearman rank correlation with `actual`, and (classifiers) whether the feature separates the two classes
  perfectly (non-overlapping ranges). Feature names containing target / label / future / fwd / next are listed as
  INFO.
- **Status.** NEEDS_REVIEW with high priority when |Spearman| > `ml_leak_correlation` (0.95) or the classes are
  perfectly separated. It is not CONFIRMED_ERROR because a legitimate near-deterministic feature can, rarely,
  behave like this; the reviewer must trace how the feature is built and when it is known. PASS when every
  feature was tested and none crosses the threshold. NOT_EXECUTABLE without `ml_feature_values.csv`.
- **Why.** A feature computed with the outcome makes any backtest perfect and any deployment useless (Kaufman,
  Rosset and Perlich 2012).
- **Fix.** Trace the construction of each flagged feature; remove it or lag it to its availability date.
- **References.** Kaufman et al. (2012); Lopez de Prado (2018).

### `ml_evaluation_protocol`: models scored on the test split

- **What.** The number of distinct `model` values among test-split predictions, the scored rows per split, and
  the number of trials declared (`declared_results.json` `n_trials` or `rules.yaml` `research.n_trials`).
- **Status.** NEEDS_REVIEW when more than one model was scored on the single test split (the holdout was reused
  for selection) or when only test predictions were delivered (overfitting cannot be judged). INFO otherwise.
- **Why.** Choosing the best of k on the test set is selection on the test set; the reported metric is biased
  upward (Dwork et al. 2015; Arnott, Harvey and Markowitz 2019).
- **Fix.** Select on the validation split, score the chosen model once on the test split, declare the number of
  configurations tried.
- **Does not allow.** Knowing about models that were scored and not delivered.
- **References.** Dwork et al. (2015); Arnott, Harvey and Markowitz (2019); SR 11-7.

## Conventions (rules.yaml `conventions:`)

| Key | Default | Meaning |
|---|---|---|
| `ml_task` | `auto` | `classification`, `regression`, or `auto` (classification when `actual` has two distinct values) |
| `ml_embargo_days` | 0 | Declared embargo between the last training `label_end` and the first test timestamp (and after each K-fold test block) |
| `ml_psi_review` | 0.10 | PSI above this is NEEDS_REVIEW |
| `ml_psi_error` | 0.25 | PSI above this is NEEDS_REVIEW with high priority (never CONFIRMED_ERROR) |
| `ml_overfit_gap_review` | 0.10 | Relative drop of the training excess (AUC - 0.5, or R2) tolerated on the test split |
| `ml_min_test_samples` | 200 | Fewer scored test rows -> the metric checks are NOT_EXECUTABLE |
| `ml_calibration_bins` | 10 | Quantile bins of the reliability table |
| `ml_calibration_ece_review` | 0.05 | ECE above this (with Hosmer-Lemeshow rejection) is NEEDS_REVIEW |
| `ml_calibration_hl_p` | 0.01 | Hosmer-Lemeshow p-value below which the ECE alert fires |
| `ml_leak_correlation` | 0.95 | |Spearman| with the target above this flags a feature |
| `ml_label_shift_p` | 0.01 | p-value of the label-shift test below which (with a material shift) a review is raised |

## Cases (`cases/usecase_ml/`, generator `cases/_generators/usecase_ml_cases.py`)

01 clean purged split (nothing alerts) | 02 temporal overlap | 03 label leak without purging (clean by timestamp,
leaks by label) | 04 duplicate ids | 05 overfit (train AUC 1.0, test 0.55) | 06 covariate drift (PSI > 0.25) |
07 feature equal to the label plus noise | 08 squeezed probabilities | 09 six models on one test split |
10 fifty test rows (NOT_EXECUTABLE, never PASS) | 11 honest regression | 12 purged 5-fold whose test blocks sit
inside the overall range (adversarial: must PASS). `expected.json` was written before running the tool.

## Limitations

- The module validates the protocol and the delivered predictions; it cannot refit the model, so it cannot
  detect leaks that only exist in the training pipeline (scaling fitted on the full data, target encoding).
- Purging is verified only when `label_end` is delivered; without it the check is NEEDS_REVIEW, never PASS.
- The target-leak test flags; it does not prove. A near-deterministic legitimate feature is possible.
- PSI thresholds, the ECE threshold and the overfit gap are conventions; the Welch and chi-square p-values use
  normal approximations (Wilson-Hilferty) and are indicative with small samples.
- Calibration of regressions (prediction intervals) and multi-class classifiers are not supported: `actual` with
  more than two values is treated as a regression unless `ml_task: classification` is declared, in which case
  values above 0.5 are the positive class.
- With a purged K-fold, train predictions should be the in-fold fit and test predictions the out-of-fold score;
  join them by `fold` in both tables. Without `fold` in `ml_predictions.csv` the same prediction serves every
  role and the overfit gap is only descriptive.
