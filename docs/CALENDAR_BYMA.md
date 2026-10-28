# BYMA trading calendar: provenance

`conventions.calendar: byma` treats a day as a session when it is a weekday and is not listed in
`src/lockin_validate/data/byma_holidays.csv`. This document says where every row comes from.

## Files

| File | Role |
|---|---|
| `data/calendars/byma_holidays_sourced.csv` | Research table: every candidate day examined, including days that look like holidays but on which BYMA traded (`market_closed = no`). Not shipped in the wheel. |
| `src/lockin_validate/data/byma_holidays.csv` | Packaged calendar: exactly the rows of the research table with `market_closed = yes`, same columns. The loader reads only the `date` column; the other columns are ignored. |
| `tests/test_calendar_byma_data.py` | Checks content (known holidays per year, no weekends, no duplicates, years covered, sources) and that the packaged file is the closed subset of the research table. |

Columns: `date, name, type, market_closed, source_url, verified, notes`.

- `type`: `national_fixed` (fixed national holidays, Carnival, Good Friday, one-off national holidays set by decree),
  `national_movable` (17 June, 17 August, 12 October, 20 November after moving), `bridge_non_working_day`
  (tourism bridge days, whether set as a full holiday or as a "día no laborable"), `market_specific` (days BYMA
  closes without a national holiday: Holy Thursday, 24/31 December in some years, Bank Employees' Day in some
  years, the 2018 G20 and 2026 papal-visit holidays that applied only in the City of Buenos Aires).
- `market_closed`: `yes` = no trading at BYMA (goes to the packaged file); `no` = BYMA traded (a session, even if
  settlement was suspended).
- `verified`: `yes` = an official or primary source (law or decree text, argentina.gob.ar official list, a BYMA
  notice or the BYMA trading calendar) establishes both the date and that the market was closed (for national
  holidays, closure follows from the holiday). `partial` = the date has an official basis but BYMA's behaviour
  comes only from price evidence, or the official text was read through a third-party reproduction. `no` = no
  official or primary source found; the row rests on price evidence only.

## Coverage and counts (built 2026-10-28)

Years 2015 to 2026. Packaged file: 206 closed days (159 `yes`, 35 `partial`, 12 `no`; 2026-11-09 relabelled `partial` in 0.2.1 after the independent review, as was the 2026-07-10 session row of the research table, because the BYMA calendar they rest on could not be retrieved to confirm). Research table: 222 rows
(16 rows are days on which BYMA traded and are therefore not in the calendar).

## Sources (accessed 2026-10-28)

Official and primary:

- Ley 27.399 (holiday regime since October 2017; art. 6 moving rule; art. 7 tourism days):
  https://www.argentina.gob.ar/normativa/nacional/ley-27399-281835
- Decreto 1584/2010 (regime for 2015 to 2017), AFIP library: https://biblioteca.afip.gob.ar/dcp/DEC_C_001584_2010_11_02
- DNU 52/2017 and 80/2017 (2017 moves): https://www.argentina.gob.ar/normativa/nacional/norma-271094/texto,
  https://www.argentina.gob.ar/normativa/nacional/norma-271382/texto
- Tourism days by year: Decreto 923/2017 for 2018 and 2019 (norma-287145), 717/2019 for 2020 (norma-330204),
  947/2020 for 2021 (norma-344620), 789/2021 for 2022 (norma-356678), 764/2022 for 2023 (norma-375264),
  106/2023 for 2024 (norma-395689), all under https://www.argentina.gob.ar/normativa/nacional/; 1027/2024 for 2025
  and Resolución 164/2025 for 2026 as cited by the official lists below.
- Official national holiday lists (JSON behind argentina.gob.ar/jefatura/feriados-nacionales-YYYY), 2025 and 2026:
  https://www.argentina.gob.ar/sites/default/files/holidays-2025-es.json,
  https://www.argentina.gob.ar/sites/default/files/holidays-2026-es.json (includes Decreto 614/2025 and the
  papal-visit Decreto 1103/2026). The pages for 2015 to 2024 returned HTTP 403/404 to automated requests.
- One-off holidays: DNU 967/2018 (G20, CABA only):
  https://www.boletinoficial.gob.ar/detalleAviso/primera/194810/20181030; DNU 573/2022:
  https://www.argentina.gob.ar/normativa/nacional/decreto-573-2022-370795/texto; Decreto 42/2022 (census) as
  cited by BCRA: https://www.bcra.gob.ar/archivos/Pdfs/comytexord/C92108.pdf
- BYMA trading calendar 2026 (version published 5 October 2026): https://byma.com.ar/mercado/calendario-bursatil
- BYMA notices: 31 March 2020 "feriado bursátil" https://www.byma.com.ar/newsroom/byma-lunes30-martes31;
  2 September 2022 https://www.byma.com.ar/newsroom/actividad-byma-negociacin-y-liquidacin-2-de-septiembre-2022;
  24/31 December 2024 https://www.byma.com.ar/newsroom/actividad-de-byma-durante-el-24-y-31-de-diciembre;
  24/31 December 2025 (Comunicado 18897) https://www.byma.com.ar/newsroom/24-y-31-de-diciembre-en-byma

Secondary (evidence of whether trading happened, never the only basis for `verified = yes`):

- Rava monthly price history (GGAL, BYMA), e.g. https://www.rava.com/cotizaciones/historico/ggal/2018/11
- Yahoo Finance daily history of GGAL.BA, YPFD.BA, PAMP.BA (a weekday counts as traded when any of the three has
  volume > 0). Yahoo has gaps (for example 5 to 11 September 2017, 9 October 2017); every Yahoo gap that is not in
  the calendar was checked against Rava and BYMA traded.
- Decreto 1768/2013 (2015 and 2016 bridge days), third-party reproduction at aldiaargentina.microjuris.com.

## Method

1. Fixed holidays and Carnival / Good Friday (from Easter) from the law in force each year (Decreto 1584/2010 until
   2017, Ley 27.399 after). Movable holidays by the moving rule of the year, checked against the decree when one
   moved them differently (2015 Sovereignty Day, 2022 Güemes, 2025 Cultural Diversity Day).
2. Bridge days and one-off holidays from the yearly decrees.
3. Days that are not national holidays (Holy Thursday, "días no laborables", 24/31 December, Bank Employees' Day,
   local holidays in Buenos Aires) are included only when BYMA did not trade: a BYMA notice or calendar, or else
   price evidence (Rava and Yahoo).
4. Cross-check: every date in the packaged file through 2026-10-27 is a no-trade day in Yahoo, and every Yahoo
   no-trade day not in the file was confirmed as a session in Rava.

What BYMA actually did on "días no laborables" changes over time: it closed on the 2018/2019 tourism non-working
days, on 2 May and 15 August 2025, and on Holy Thursday every year; it traded on 21 November 2025 and its 2026
calendar marks the tourism days (23 March, 10 July, 7 December), Bank Employees' Day and 24 December as
"jornada con negociación, sin liquidación". Those are sessions here. 24 December was closed through 2021 and has
been a shortened session since 2024; 31 December has been closed in 2015, 2018 to 2021 and 2024 to 2026 (on a
weekend in the other years). Bank Employees' Day (6 November) closed the market in 2015, 2017 and 2023 and not in
2018, 2019, 2020, 2024, 2025 or 2026. 20 December 2022 was a national holiday but BYMA traded (banks opened until
12:00), so it is a session.

## Disagreements with exchange_calendars XBUE (version 4.13.2)

XBUE lists as closed but BYMA traded: 2020-04-02 (holiday moved to 31 March), 2020-06-17, 2021-06-17, 2025-06-17,
2026-06-17 (Güemes moved to Monday), 2024-08-19 and 2024-10-14 (17 August and 12 October 2024 fell on Saturday and
were not moved), 2025-08-18, 2025-10-13, 2025-11-17 (2025 moves differ).

XBUE misses closures: 2015-12-24, 2015-12-31, 2016-12-30, 2019-12-24, 2019-12-31, 2020-12-24, 2020-12-31,
2021-12-24, 2021-12-31, 2023-11-06, 2024-12-31, 2025-12-31, 2026-12-31 (market-specific days); the tourism
bridge days from 2020 on except 2021-11-22 and 2022-11-21 (2020-03-23, 2020-07-10, 2020-12-07, 2021-05-24, 2021-10-08, 2022-10-07, 2022-12-09,
2023-05-26, 2023-06-19, 2023-10-13, 2024-04-01, 2024-06-21, 2024-10-11, 2025-05-02, 2025-08-15); the one-off
holidays 2020-03-31, 2022-05-18, 2022-09-02, 2026-11-09 and 2026-11-10; and the moved dates 2020-06-15,
2021-06-21, 2025-06-16, 2025-10-10, 2025-11-24, 2026-06-15. XBUE agrees with this file on 2015 to 2019 except
for the year-end days.

## Open items

- 2026-11-10 (papal visit, holiday only in CABA and Córdoba): BYMA lists it under the decree criterion without
  saying whether there is trading; included as closed with `verified = partial`. Check BYMA's notice before the date.
- 2016-12-30 and the 24/31 December closures of 2015 and 2019 to 2021, and Bank Employees' Day 2015, 2017 and
  2023: price evidence only (`verified = no`). The BYMA notices were not located.
- 2015 to 2017 rows are `partial` where the decree text was not read from an official site (Decreto 1768/2013, the
  decree that moved 20 November 2015 to 27 November, DNU 80/2017).
- 2015-12-04: GGAL has no quote in Rava but Yahoo shows volume; left as a session (not in the calendar).
- 2026 dates after 2026-10-28 come from the BYMA calendar of 5 October 2026 and can change by decree.
- Years after 2026 are not covered: the audit reports a review item for uncovered years and checks only weekends.

## Using your own calendar

Put a CSV with at least a `date` column (ISO dates, one per closed weekday) in the input folder and declare it in
rules.yaml; other columns are ignored, so you can copy the packaged file and edit it:

```yaml
conventions:
  calendar: byma
  holidays_file: holidays.csv   # relative to the input folder; replaces the packaged list entirely
```

The years present in your file define the years the calendar covers. To update the packaged file, edit
`data/calendars/byma_holidays_sourced.csv` and copy its `market_closed = yes` rows (same header) to
`src/lockin_validate/data/byma_holidays.csv`; the test checks that both stay in sync.
