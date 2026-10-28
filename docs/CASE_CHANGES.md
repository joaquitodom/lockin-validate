# Changes made to the benchmark cases while porting them

The benchmark battery was ported from the internal review core (written in Spanish). The rule was: translate names,
keep the data and keep every expected outcome. This file documents everything that had to change and why. It quotes
original (Spanish) names on purpose.

## How faithfulness was verified

The case generators were translated line by line keeping the seeds and the order of random-number calls. After
regenerating, every ported case was compared value by value with the original files (prices: date, ticker, open,
close, availability; trades: timestamp, ticker, side, quantity, price, commission; signals; positions; declared
results). Result: **0 mismatches in the 10 core cases and 0 in the 12 adversarial cases** (comparison script run on
2026-10-27, output recorded in docs/VALIDATION_EVIDENCE.md).

## Renames (no change in meaning)

- File names: `precios.csv` -> `prices.csv`, `senales.csv` -> `signals.csv`, `operaciones.csv` -> `trades.csv`,
  `posiciones.csv` -> `positions.csv`, `costos.csv` -> `costs.csv`, `balances.csv` -> `fundamentals.csv`,
  `reglas.yaml` -> `rules.yaml`, `resultados_declarados.json` -> `declared_results.json`, `esperado.json` and
  `esperado_rol4.json` -> `expected.json`.
- Columns and keys translated (`fecha` -> `date`, `timestamp_decision` -> `decision_time`, `fecha_dato` ->
  `data_date`, `disponible_desde` -> `available_from`, `lado` compra/venta -> `side` buy/sell, `cantidad` ->
  `quantity`, `precio` -> `price`, `comision` -> `commission`, `retorno_total` -> `total_return`, `n_operaciones` ->
  `n_trades`, `nav_final` -> `final_nav`, `efectivo_inicial` -> `initial_cash`, `comision_pct` -> `commission_rate`
  (it always was a fraction of notional), etc.).
- Check ids: `estructura_y_tipos` -> `schema_and_types`, `duplicados` -> `duplicates`, `fechas` -> `dates`,
  `campos_esenciales` -> `essential_fields`, `cobertura` -> `coverage`, `temporal_operacion_vs_senal` ->
  `trade_before_signal`, `temporal_senal_vs_dato` -> `signal_data_after_decision`, `precios_antiguos` ->
  `stale_prices`, `reconstruccion` -> `reconstruction`, `conciliacion_posiciones` -> `positions_reconciliation`,
  `conciliacion_resultados` -> `results_reconciliation`, `informacion_futura` -> `lookahead`, `costos_omitidos` ->
  `omitted_costs`, `metricas` -> `metrics`, `reglas_vs_implementacion` -> `rules_vs_implementation`.
- Statuses: `ERROR_CONFIRMADO` -> `CONFIRMED_ERROR`, `ALERTA` -> `NEEDS_REVIEW`, `NO_EJECUTABLE` -> `NOT_EXECUTABLE`,
  `CORRECTO` -> `PASS`.
- Tickers that were Spanish words: case 10 `TRIGO, COBRE, BONO` -> `WHEAT, COPPER, BOND`; adversarial cases
  `ALFA, GAMA` -> `ALPHA, GAMMA`. The alphabetical order of the tickers (which decides tie-breaks and file order) is
  the same before and after.
- Case folders: `01_correcto` -> `core/01_clean`, `02_duplicados` -> `core/02_duplicates`, `03_precios_antiguos` ->
  `core/03_stale_prices`, `04_costos_omitidos` -> `core/04_omitted_costs`, `05_fechas_imposibles` ->
  `core/05_impossible_dates`, `06_informacion_futura` -> `core/06_lookahead`,
  `06b_informacion_futura_sin_disponibilidad` -> `core/06b_lookahead_without_availability`, `07_error_de_metricas` ->
  `core/07_metric_error`, `08_reglas_vs_implementacion` -> `core/08_rules_vs_implementation`, `10_independiente` ->
  `core/10_independent`; `R00_limpio_rol4` ... `R13_resultados_no_reconocidos` -> `adversarial/R00_clean` ...
  `adversarial/R13_unrecognised_results`.

## Changes forced by the translation or by the new tool

1. **Expected-text of core case 04.** The original expected file required the finding text to contain "Consecuencia
   del mismo problema". The English expectation requires "Consequence of the same problem": same assertion, translated.
2. **Unrecognised key of adversarial case R13.** The false declared key `rentabilidad` became `profitability` (still a
   key the tool does not recognise, still with the same false value). `sharpe_ratio` is unchanged.
3. **Unified expected format.** The core battery used `debe_aparecer / no_debe_aparecer / solo_estos_errores /
   errores_permitidos` and the adversarial battery used `debe / no_debe / sin_errores_salvo` with its own evaluator.
   Both are now `must_include / must_not_include / errors_only_from / text_must_contain`, with the same semantics:
   `debe_aparecer {control, estado}` -> `must_include {check, status: [estado]}`; `debe [control, [estados]]` ->
   `must_include {check, status: [estados]}`; `solo_estos_errores: true` with `errores_permitidos` ->
   `errors_only_from` = expected error checks plus the allowed ones; `sin_errores_salvo` -> `errors_only_from`.
4. **The `*datos*` pattern (adversarial R10).** The original evaluator matched a fixed list of data-check ids. It is now
   `@data`, which matches every check of the data and input blocks. This is the change the original review
   recommended ("accept any finding of the data block instead of a list of ids"): it lets the split jump live in its
   own check (`price_jumps`, previously folded into `dates`) without rewriting the case. The set of allowed checks only
   grew (new data checks); no previously allowed check was removed.
5. **Price jumps moved out of `dates`.** In the original core the "jump > 40% / split-like" finding was raised by the
   `fechas` check. It is now the separate `price_jumps` check. No core case expected a jump, and R10 is covered by
   point 4.
6. **New checks in old cases.** The ported cases now also receive results from the new checks (statistics,
   point-in-time fundamentals, survivorship, identity, corporate actions, reference accuracy, LLM). They are
   NOT_EXECUTABLE when the inputs are missing, and the statistical checks run on the reconstructed NAV. None of the
   original expectations mention those checks, so no expectation changed; the battery runner reports their review
   items as "unexpected review" (informational, not a failure).
7. **Case 09 replaced.** The original `09_lockin` was generated from vendor prices (not redistributable). It is
   replaced by `core/09_lockin_style`, generated by `cases/_generators/lockin_style_case.py` (seed 2026): a monthly
   top-3 of 10 quality ranking with equal weights, delivered as a partial package. Its expected outcomes mirror the
   original 09: lookahead and positions_reconciliation NOT_EXECUTABLE; results_reconciliation, metrics and
   rules_vs_implementation PASS; duplicates, dates, stale_prices, reconstruction and omitted_costs PASS. The generator
   asserts that commissions exceed twice the total-return tolerance so that the omitted_costs PASS expectation is
   discriminating.

No expected outcome (status of a check in a case) was changed.

## 0.2.0: review items that cases now expect

Release 0.2.0 classified the 40 "unexpected review" items of the 0.1.0 battery (docs/ALERT_POLICY.md). The 23 that
are genuine signals are now expected by their cases. They are added by `cases/_generators/expectation_changes.py`,
which every generator calls after writing its cases (so regenerating reproduces them) and which also writes an
`expectation_changes` note into each touched expected.json. Only `must_include` entries were added; nothing was
removed, no allowed status was widened and no data file changed (regeneration verified: only expected.json files
differ).

| Case | Added expectation | Policy | Justification |
|---|---|---|---|
| adversarial/R00_clean | omitted_costs NEEDS_REVIEW | P2 | 10 bps over a turnover of ~4: with and without costs are within the 0.5 pp tolerance; the conclusion rule requires a review item (same as core 10). |
| adversarial/R03_first_day_commission | sharpe_significance NEEDS_REVIEW | P1 | Positive Sharpe over 63 sessions, MinTRL 3.2 x the history. |
| adversarial/R04_lookahead_fundamentals | omitted_costs NEEDS_REVIEW | P6 | No cost declared or charged, turnover > 0. |
| adversarial/R05_undeclared_lookahead | omitted_costs NEEDS_REVIEW | P6 | Idem. |
| adversarial/R06_undeclared_short | omitted_costs NEEDS_REVIEW; sharpe_significance NEEDS_REVIEW | P6, P1 | No costs; MinTRL 2.4 x the history. |
| adversarial/R07_undeclared_leverage | omitted_costs NEEDS_REVIEW | P6 | No costs. |
| adversarial/R10_unadjusted_split | omitted_costs NEEDS_REVIEW; price_jumps NEEDS_REVIEW | P6, P7 | No costs; the planted split is the jump (the case already accepted it through `@data`). |
| adversarial/R11_byma_calendar_undeclared | omitted_costs NEEDS_REVIEW; dates NEEDS_REVIEW | P6, P7 | No costs; the case description itself names "a review item for the undeclared calendar" as the right answer. |
| adversarial/R13_unrecognised_results | omitted_costs NEEDS_REVIEW | P6 | No costs. |
| core/04_omitted_costs | sharpe_significance NEEDS_REVIEW | P1 | MinTRL 6.7 x the history. |
| core/05_impossible_dates | coverage NEEDS_REVIEW | P7 | The planted 2027 row leaves 629 missing sessions in DDD's series. |
| core/08_rules_vs_implementation | sharpe_significance NEEDS_REVIEW | P1 | MinTRL 2.2 x the history. |
| core/10_independent | sharpe_significance NEEDS_REVIEW | P1 | MinTRL 4.2 x the history. |
| data/D03_recycled_ticker | coverage NEEDS_REVIEW; price_jumps NEEDS_REVIEW | P7 | The five-month gap and the level shift at the seam of the two companies. |
| statistical/S04_undeclared_trials | deflated_sharpe, multiple_testing, pbo NEEDS_REVIEW | P4 | Consequences of the 50 logged configurations. |
| statistical/S05_overfit_search_undeclared | multiple_testing NEEDS_REVIEW | P4 | Best of 100 noise series. |
| statistical/S07_short_track_record | trials_declared NEEDS_REVIEW | P4 | One trial declared, no trials log: uncontrastable declaration. |

Items reclassified as INFO (16) or fixed as a bug (1) needed no expectation change; the policy behind each is in
docs/ALERT_POLICY.md.

## 0.2.0: lesson cases

`cases/lessons/` (16 cases, `cases/_generators/lessons_cases.py`) was added for the six new check families. Their
expected.json files were committed before the checks were implemented (commit "Pre-register lesson benchmark cases
for six new check families"); any later change to them is listed here.

## 0.2.1: after the independent review

- Every expectation added in 0.2.0 now carries `"post_hoc": true` (written by `expectation_changes.apply`), so the
  battery reports it apart from the pre-registered detections and excludes it from detection rates (review D1).
- Withdrawn (review D2, rule 1 of docs/ALERT_POLICY.md): core/05_impossible_dates `coverage NEEDS_REVIEW`;
  data/D03_recycled_ticker `coverage NEEDS_REVIEW` and `price_jumps NEEDS_REVIEW`. The tool still raises them; they are
  reported as unexpected review. 20 post-hoc expectations remain.
- No pre-registered expectation and no lesson case changed. The reviewer's cases (`cases_review_v020/`) were not
  edited.
