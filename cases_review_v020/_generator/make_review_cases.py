"""Independent adversarial review cases for lockin-validate 0.2.0 (cases_review_v020/).

Written by an external reviewer. Does NOT import lockin_validate. Seeded and deterministic.
Usage (repository root):  uv run python cases_review_v020/_generator/make_review_cases.py

Every expected.json is written here, from the problem planted, BEFORE the tool is run on these cases (git history:
the generator and the expected files are committed before docs/REVIEW_V020.md, which records the run).

Each case targets one of the nine 0.2.0 checks with either a SUBTLE planted problem (near a threshold, in a field or
period other than the obvious one, or hidden behind a verification gap) or a CLEAN package designed to tempt a false
positive. V26-V27 combine several problems; V28 reproduces the LockIn holdout failure (fundamentals coverage of the
universe falls from ~97% to ~79% in the test years while preflight-style checks pass).

Expectation vocabulary is the battery's (src/lockin_validate/cases.py): must_include, must_not_include,
errors_only_from, text_must_contain. Extra key "reviewer_note" explains what a correct tool should say and whether
the expectation is a firm requirement or a reviewer judgement ("stretch").
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
ALERTS = ["CONFIRMED_ERROR", "NEEDS_REVIEW"]
NOT_PASS = ["CONFIRMED_ERROR", "NEEDS_REVIEW", "NOT_EXECUTABLE"]
BASE_CONV = "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n"


# ---------------------------------------------------------------------------- helpers

def bdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def month_ends(start: date, end: date) -> list[date]:
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        out.append(nxt - timedelta(days=1))
        y, m = nxt.year, nxt.month
    return out


def quarter_ends(start: date, end: date) -> list[date]:
    return [d for d in month_ends(start, end) if d.month in (3, 6, 9, 12)]


def first_bdays(days: list[date]) -> list[date]:
    seen, out = set(), []
    for d in days:
        if (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            out.append(d)
    return out


def write_csv(p: Path, rows, cols):
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def folder(name: str, rules: str) -> Path:
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    (c / "rules.yaml").write_text(rules, encoding="utf-8")
    return c


def must(check, statuses):
    return {"check": check, "status": statuses if isinstance(statuses, list) else [statuses]}


def forbid(check, statuses):
    return [{"check": check, "status": s} for s in statuses]


def expected(c: Path, kind: str, target: list[str], description: str, must_include, must_not, errors_only_from=None,
             text=None, note: str = ""):
    exp = {"description": description, "origin": "review_v020", "kind": kind, "target_checks": target,
           "must_include": must_include, "must_not_include": must_not}
    if errors_only_from is not None:
        exp["errors_only_from"] = errors_only_from
    if text:
        exp["text_must_contain"] = text
    if note:
        exp["reviewer_note"] = note
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def gbm(rng, n, p0, mu, sigma, nd=4):
    p, out = p0, []
    for _ in range(n):
        p *= math.exp(rng.normal(mu, sigma))
        out.append(round(p, nd))
    return out


def price_rows(days, prices, volume=None, adjusted="true"):
    rows = []
    for t, s in prices.items():
        for k, d in enumerate(days):
            r = {"date": d.isoformat(), "ticker": t, "close": s[k], "adjusted": adjusted}
            if volume is not None:
                v = volume[t][k]
                r["volume"] = "" if v is None else v
            rows.append(r)
    return rows


def universe_rows(tickers, start="2010-01-04", ends=None):
    ends = ends or {}
    return [{"ticker": t, "start_date": start, "end_date": ends.get(t, "")} for t in tickers]


def fundamentals_rows(rng, tickers, quarters, keep, fields=("roe", "debt_to_equity", "gross_margin"), lag=40):
    """keep(ticker_index, quarter_index, quarter, field) -> bool; a row is written when any field is kept."""
    rows = []
    for qi, q in enumerate(quarters):
        for ti, t in enumerate(tickers):
            vals = {}
            for f in fields:
                v = round(float(rng.normal(0.12 if f == "roe" else 0.8 if f == "debt_to_equity" else 0.35, 0.05)), 4)
                vals[f] = v if keep(ti, qi, q, f) else ""
            if all(v == "" for v in vals.values()):
                continue
            filed = (q + timedelta(days=lag)).isoformat()
            rows.append({"ticker": t, "period_end": q.isoformat(), "filing_date": filed, "available_from": filed,
                         **vals})
    return rows


FUND_COLS = ["ticker", "period_end", "filing_date", "available_from", "roe", "debt_to_equity", "gross_margin"]


# ---------------------------------------------------------------------------- coverage_drift

def v01_cov_single_field_late_drop():
    tickers = [f"C{i:02d}" for i in range(1, 41)]
    quarters = quarter_ends(date(2016, 1, 1), date(2023, 12, 31))
    rng = np.random.default_rng(1001)
    late = date(2023, 6, 30)

    def keep(ti, qi, q, f):
        if ti == (qi * 7 + len(f)) % 40:  # one member missing per field per quarter: 97.5%
            return False
        if f == "gross_margin" and q >= late and ti >= 35:  # five more members lose ONLY gross_margin
            return False
        return True
    c = folder("V01_cov_single_field_late_drop", "strategy: quality screen (no trades)\n" + BASE_CONV)
    write_csv(c / "universe.csv", universe_rows(tickers, "2015-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "fundamentals.csv", fundamentals_rows(rng, tickers, quarters, keep), FUND_COLS)
    expected(c, "planted_subtle", ["coverage_drift"],
             "Only ONE of three fields drifts, and only in the last three quarters (2023-Q2..Q4): gross_margin coverage "
             "falls from 97.5% to 85% (-12.5 pp, just above the 10 pp threshold). roe and debt_to_equity are stable, "
             "so the rows still exist for every member.",
             [must("coverage_drift", "NEEDS_REVIEW")], forbid("coverage_drift", ["PASS"]), ["coverage_drift"],
             [{"check": "coverage_drift", "text": "gross_margin"}])


def v02_cov_vendor_stops():
    tickers = [f"K{i:02d}" for i in range(1, 31)]
    quarters = quarter_ends(date(2016, 1, 1), date(2021, 12, 31))  # vendor delivery stops after 2021-Q4
    rng = np.random.default_rng(1002)
    rules = ("strategy: quarterly quality screen, monthly scores 2016-2024\n"
             "period: {start: '2016-01-04', end: '2024-12-31'}\n" + BASE_CONV)
    c = folder("V02_cov_vendor_stops_entirely", rules)
    write_csv(c / "universe.csv", universe_rows(tickers, "2015-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "fundamentals.csv",
              fundamentals_rows(rng, tickers, quarters, lambda ti, qi, q, f: ti != qi % 30), FUND_COLS)
    sig = []
    for d in first_bdays(bdays(date(2016, 1, 1), date(2024, 12, 31))):
        for t in tickers:
            sig.append({"decision_time": d.isoformat(), "ticker": t, "signal": round(float(rng.normal()), 4)})
    write_csv(c / "signals.csv", sig, ["decision_time", "ticker", "signal"])
    expected(c, "planted_gap", ["coverage_drift"],
             "Fundamentals for EVERY member stop after 2021-Q4 while the universe is active and the model keeps "
             "scoring every month until 2024-12 (declared period 2016-2024). Coverage of 2022-2024 is 0%: the "
             "extreme case of drift. A period with no rows at all must not be invisible.",
             [must("coverage_drift", NOT_PASS)], forbid("coverage_drift", ["PASS"]), ["coverage_drift"],
             note="Firm: PASS here would be the LockIn failure in its purest form (the holdout years have no inputs).")


def v03_cov_universe_shrinks():
    tickers = [f"U{i:02d}" for i in range(1, 31)]
    leavers = {t: "2021-12-31" for t in tickers[22:]}  # 8 members leave the index at the end of 2021
    quarters = quarter_ends(date(2016, 1, 1), date(2024, 12, 31))
    rng = np.random.default_rng(1003)

    def keep(ti, qi, q, f):
        if ti >= 22 and q > date(2021, 12, 31):
            return False  # left the universe: no more filings delivered (legitimately)
        return ti != qi % 30
    c = folder("V03_cov_universe_genuinely_shrinks", "strategy: quality screen (no trades)\n" + BASE_CONV)
    write_csv(c / "universe.csv", universe_rows(tickers, "2015-01-02", leavers), ["ticker", "start_date", "end_date"])
    write_csv(c / "fundamentals.csv", fundamentals_rows(rng, tickers, quarters, keep), FUND_COLS)
    expected(c, "clean_tempting", ["coverage_drift"],
             "The number of rows falls by 27% from 2022 because 8 of 30 members LEFT the universe (end_date "
             "2021-12-31 in universe.csv). Coverage of the members that remain is unchanged (~97%).",
             [must("coverage_drift", "PASS")], forbid("coverage_drift", ALERTS), [])


def v04_cov_optional_field():
    tickers = [f"O{i:02d}" for i in range(1, 31)]
    quarters = quarter_ends(date(2016, 1, 1), date(2024, 12, 31))
    rng = np.random.default_rng(1004)
    rows = []
    for qi, q in enumerate(quarters):
        for ti, t in enumerate(tickers):
            if ti == qi % 30:
                continue
            filed = (q + timedelta(days=40)).isoformat()
            rows.append({"ticker": t, "period_end": q.isoformat(), "filing_date": filed, "available_from": filed,
                         "roe": round(float(rng.normal(0.12, 0.05)), 4),
                         "debt_to_equity": round(float(abs(rng.normal(0.8, 0.3))), 4),
                         # vendor discontinued the optional ESG field in 2022; the model never used it
                         "esg_score": round(float(rng.uniform(10, 90)), 1) if q < date(2022, 1, 1) else ""})
    rules = ("strategy: two-input quality screen (no trades)\nrequired_inputs: [roe, debt_to_equity]\n" + BASE_CONV)
    c = folder("V04_cov_unused_optional_field_dropped", rules)
    write_csv(c / "universe.csv", universe_rows(tickers, "2015-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "fundamentals.csv", rows, ["ticker", "period_end", "filing_date", "available_from", "roe",
                                             "debt_to_equity", "esg_score"])
    expected(c, "clean_tempting", ["coverage_drift"],
             "The vendor stopped an OPTIONAL field (esg_score) in 2022. rules.yaml declares required_inputs "
             "[roe, debt_to_equity], both ~97% throughout. docs/INPUT_SPEC.md lists rules(required_inputs) as an input "
             "of coverage_drift, so a drop in an undeclared field should at most be a note.",
             [], forbid("coverage_drift", ALERTS), [],
             note="Reviewer judgement (disputable): an INFO about esg_score is fine; a NEEDS_REVIEW is noise when the "
                  "owner declared the inputs the model uses.")


# ---------------------------------------------------------------------------- input_sufficiency

def _signals(rng, tickers, inputs, months, missing, unscored=lambda d, ti: False, header=None):
    rows = []
    for mi, d in enumerate(months):
        for ti, t in enumerate(tickers):
            r = {"decision_time": d.isoformat(), "ticker": t}
            for k, f in enumerate(inputs):
                r[f] = "" if missing(mi, d, ti, k) else round(float(rng.normal()), 4)
            r["signal"] = "" if unscored(d, ti) else round(float(rng.normal()), 4)
            rows.append(r)
    cols = ["decision_time", "ticker", "signal"] + inputs
    if header:
        rows = [{(header.get(k, k)): v for k, v in r.items()} for r in rows]
        cols = [header.get(k, k) for k in cols]
    return rows, cols


def v05_suff_one_month_below():
    tickers = [f"S{i:02d}" for i in range(1, 21)]
    inputs = [f"x{i:02d}" for i in range(1, 11)]
    months = first_bdays(bdays(date(2021, 1, 1), date(2024, 6, 30)))
    rng = np.random.default_rng(1005)

    def missing(mi, d, ti, k):
        if d.year == 2023 and d.month == 7 and ti in (3, 8, 13, 18) and k >= 6:
            return True  # four names scored with 6 of 10 inputs in ONE month
        return ti == mi % 20 and k == mi % 10  # otherwise at most one input missing (9/10)
    rows, cols = _signals(rng, tickers, inputs, months, missing)
    rules = ("strategy: ten-input score\n" f"universe: [{', '.join(tickers)}]\n"
             f"required_inputs: [{', '.join(inputs)}]\nmin_input_share: 0.7\n" + BASE_CONV)
    c = folder("V05_suff_one_month_just_below", rules)
    write_csv(c / "signals.csv", rows, cols)
    expected(c, "planted_subtle", ["input_sufficiency"],
             "Declared minimum 0.7 of 10 inputs. In ONE month (2023-07) four of twenty names are scored with 6 of 10 "
             "(0.6, one input below the minimum); every other row has 9 or 10.",
             [must("input_sufficiency", "CONFIRMED_ERROR")], forbid("input_sufficiency", ["PASS"]),
             ["input_sufficiency"], [{"check": "input_sufficiency", "text": "2023-07"}])


def v06_suff_case_mismatch():
    tickers = [f"M{i:02d}" for i in range(1, 21)]
    inputs = ["roe", "debt_to_equity", "gross_margin", "fcf_yield"]
    shown = {"roe": "ROE", "debt_to_equity": "Debt_To_Equity", "gross_margin": "Gross_Margin", "fcf_yield": "FCF_Yield"}
    months = first_bdays(bdays(date(2021, 1, 1), date(2024, 6, 30)))
    rng = np.random.default_rng(1006)
    rows, cols = _signals(rng, tickers, inputs, months, lambda mi, d, ti, k: False, header=shown)
    rules = ("strategy: four-input score\n" f"universe: [{', '.join(tickers)}]\n"
             "required_inputs: [ROE, Debt_To_Equity, Gross_Margin, FCF_Yield]\nmin_input_share: 0.75\n" + BASE_CONV)
    c = folder("V06_suff_inputs_declared_in_mixed_case", rules)
    write_csv(c / "signals.csv", rows, cols)
    expected(c, "clean_tempting", ["input_sufficiency"],
             "Every row has all four inputs. rules.yaml names them exactly as the CSV header does, in mixed case "
             "(ROE, Debt_To_Equity, ...). The loader lowercases headers; a correct tool must still match them.",
             [must("input_sufficiency", "PASS")], forbid("input_sufficiency", ALERTS), [])


def v07_suff_unscored_when_missing():
    tickers = [f"N{i:02d}" for i in range(1, 21)]
    inputs = [f"y{i:02d}" for i in range(1, 9)]
    months = first_bdays(bdays(date(2021, 1, 1), date(2024, 6, 30)))
    rng = np.random.default_rng(1007)
    gap = lambda mi, d, ti, k: (ti in (2, 11) and k >= 2) or (ti == mi % 20 and k == 0)  # noqa: E731
    rows, cols = _signals(rng, tickers, inputs, months, gap, unscored=lambda d, ti: ti in (2, 11))
    rules = ("strategy: eight-input score; names with missing inputs are not scored\n"
             f"universe: [{', '.join(tickers)}]\n" f"required_inputs: [{', '.join(inputs)}]\nmin_input_share: 0.75\n"
             + BASE_CONV)
    c = folder("V07_suff_insufficient_names_left_unscored", rules)
    write_csv(c / "signals.csv", rows, cols)
    expected(c, "clean_tempting", ["input_sufficiency"],
             "Two names have only 2 of 8 inputs every month, but the model correctly leaves them UNSCORED (empty "
             "signal). Every scored row has at least 7 of 8.",
             [must("input_sufficiency", "PASS")], forbid("input_sufficiency", ALERTS), [])


# ---------------------------------------------------------------------------- protocol_integrity

PROTOCOL = ("train: {start: '2010-01-01', end: '2017-12-31'}\n"
            "validation: {start: '2018-01-01', end: '2021-12-31'}\n"
            "test: {start: '2022-01-01', end: '2024-12-31', single_use: true}\n")
WIN = {"train": ("2010-01-01", "2017-12-31"), "validation": ("2018-01-01", "2021-12-31"),
       "test": ("2022-01-01", "2024-12-31")}
RUN_COLS = ["timestamp", "run_id", "window_start", "window_end", "config_hash", "purpose"]


def _runs(extra, n_val=12):
    runs, i = [], 0
    for k in range(1, 21):
        i += 1
        runs.append({"timestamp": f"2026-01-{(k % 28) + 1:02d}T10:00:00", "run_id": f"r{i:03d}",
                     "window_start": WIN["train"][0], "window_end": WIN["train"][1], "config_hash": f"c{k:02d}",
                     "purpose": "train"})
    for k in range(1, n_val + 1):
        i += 1
        runs.append({"timestamp": f"2026-02-{k + 1:02d}T10:00:00", "run_id": f"r{i:03d}",
                     "window_start": WIN["validation"][0], "window_end": WIN["validation"][1],
                     "config_hash": f"c{k:02d}", "purpose": "validation"})
    for ts, w, cfg, p in extra:
        i += 1
        w = WIN[w] if isinstance(w, str) else w
        runs.append({"timestamp": ts, "run_id": f"r{i:03d}", "window_start": w[0], "window_end": w[1],
                     "config_hash": cfg, "purpose": p})
    return runs


def v08_proto_validation_window_overlaps_test():
    c = folder("V08_proto_validation_run_spills_into_test",
               "strategy: research log\nresearch: {n_trials: 13}\n" + BASE_CONV)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    runs = _runs([("2026-03-01T10:00:00", "test", "c07", "test"),
                  ("2026-03-05T10:00:00", ("2018-01-01", "2022-06-30"), "c13", "validation")])
    write_csv(c / "run_log.csv", runs, RUN_COLS)
    expected(c, "planted_subtle", ["protocol_integrity"],
             "One clean test look (c07). Four days later a run LABELLED 'validation' of a new config c13 uses "
             "2018-01 to 2022-06: it spills six months into the single-use test window, after the test was seen. "
             "n_trials (13) covers the validation configs, so the trial-count rule does not fire.",
             [must("protocol_integrity", "CONFIRMED_ERROR")], forbid("protocol_integrity", ["PASS"]),
             ["protocol_integrity"], [{"check": "protocol_integrity", "text": "c13"}])


def v09_proto_adjacent_clean():
    c = folder("V09_proto_adjacent_windows_and_sloppy_labels",
               "strategy: research log\nresearch: {n_trials: 12}\n" + BASE_CONV)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    runs = _runs([("2026-02-20T10:00:00", ("2015-01-01", "2021-12-31"), "c07", "diagnostic"),
                  ("2026-03-01T10:00:00", "test", "c07", "Test"),
                  ("2026-03-02T10:00:00", "test", "c07", " Reproduction "),
                  ("2026-03-03T10:00:00", ("2023-01-01", "2023-12-31"), "c07", "reproduction"),
                  ("2026-03-04T10:00:00", ("2012-01-01", "2014-12-31"), "c07", "diagnostic")])
    write_csv(c / "run_log.csv", runs, RUN_COLS)
    expected(c, "clean_tempting", ["protocol_integrity"],
             "A diagnostic run ends on 2021-12-31, the day BEFORE the test window starts (adjacent, not overlapping). "
             "One test look by c07 (purpose written 'Test'); then reproductions of the same c07 (one written "
             "' Reproduction ' with spaces, one on a sub-window). 12 validation configs, 12 trials declared.",
             [must("protocol_integrity", "PASS")], forbid("protocol_integrity", ALERTS), [])


def v10_proto_holdout_label():
    c = folder("V10_proto_single_look_labelled_holdout",
               "strategy: research log\nresearch: {n_trials: 12}\n" + BASE_CONV)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    runs = _runs([("2026-03-01T10:00:00", "test", "c07", "holdout")])
    write_csv(c / "run_log.csv", runs, RUN_COLS)
    expected(c, "clean_tempting", ["protocol_integrity"],
             "The ONLY run on the test window is c07 with purpose 'holdout' (a common synonym of test, not in the "
             "documented vocabulary). Nothing proves a second look. Unknown purpose may be a review item; it is not "
             "unambiguous evidence of contamination.",
             [], forbid("protocol_integrity", ["CONFIRMED_ERROR"]), [],
             note="Firm on CONFIRMED_ERROR (the conclusion rule requires unambiguous evidence); NEEDS_REVIEW "
                  "('unknown purpose') would be the right answer.")


# ---------------------------------------------------------------------------- benchmark_fit

def _bench_world(seed, n_t=20):
    tickers = [f"B{i:02d}" for i in range(1, n_t + 1)]
    days = bdays(date(2019, 1, 1), date(2023, 12, 29))
    rng = np.random.default_rng(seed)
    n = len(days)
    market = rng.normal(0.0003, 0.010, n)
    prices = {}
    for i, t in enumerate(tickers):
        alpha = 0.00025 if i >= n_t // 2 else 0.0
        r = (0.9 + 0.2 * rng.random()) * market + rng.normal(alpha, 0.012, n)
        p, s = 20.0 + i, [round(20.0 + i, 4)]
        for x in r[1:]:
            p *= 1 + x
            s.append(round(p, 4))
        prices[t] = s
    rets = {t: [prices[t][k] / prices[t][k - 1] - 1 for k in range(1, n)] for t in tickers}
    return tickers, days, prices, rets


def v11_bench_declared_equal_actually_cap():
    tickers, days, prices, rets = _bench_world(1011)
    n = len(days)
    caps = {t: (10.0 - i) if i < 10 else 0.5 for i, t in enumerate(tickers)}
    capsum = sum(caps.values())
    held = tickers[:5] + tickers[10:15]
    strat = [sum(rets[t][k] for t in held) / len(held) for k in range(n - 1)]
    cw = [sum(caps[t] * rets[t][k] for t in tickers) / capsum for k in range(n - 1)]
    rules = ("strategy: equal-weight book of ten of twenty names\n" f"universe: [{', '.join(tickers)}]\n"
             "sizing: equal_weight\nbenchmark: {name: UNIV20, weighting: equal_weighted}\n" + BASE_CONV)
    c = folder("V11_bench_declared_equal_but_data_cap_weighted", rules)
    write_csv(c / "prices.csv", price_rows(days, prices), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "universe.csv", universe_rows(tickers, "2018-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "returns.csv", [{"date": days[k + 1].isoformat(), "return": round(strat[k], 8)}
                                  for k in range(n - 1)], ["date", "return"])
    write_csv(c / "benchmark_returns.csv", [{"date": days[k + 1].isoformat(), "return": round(cw[k], 8)}
                                            for k in range(n - 1)], ["date", "return"])
    expected(c, "planted_subtle", ["benchmark_fit"],
             "rules.yaml DECLARES the benchmark equal-weighted, but benchmark_returns.csv is in fact the cap-weighted "
             "index of the universe (the prices and the universe are delivered, so the equal-weight universe can be "
             "computed and differs from the benchmark by several pp a year). The declaration is contradicted by data.",
             [must("benchmark_fit", "NEEDS_REVIEW")], forbid("benchmark_fit", ["PASS"]), [],
             note="Firm: the check can contrast the declaration (it computes the equal-weight universe itself); "
                  "docs/CONVENTIONS.md s.5 forbids a PASS that rests only on the owner's declaration when it can.")


def v12_bench_clean_misaligned_dates():
    tickers, days, prices, rets = _bench_world(1012)
    n = len(days)
    held = tickers[:5] + tickers[10:15]
    strat = [sum(rets[t][k] for t in held) / len(held) for k in range(n - 1)]
    ew = [sum(rets[t][k] for t in tickers) / len(tickers) for k in range(n - 1)]
    skip = set(range(50, n - 1, 120))  # benchmark vendor misses ~10 dates
    brows = [{"date": days[k + 1].isoformat(), "return": round(ew[k], 8)} for k in range(n - 1) if k not in skip]
    brows += [{"date": "2019-12-25", "return": 0.0}, {"date": "2020-12-25", "return": 0.0}]  # holiday rows
    rules = ("strategy: equal-weight book of ten of twenty names\n" f"universe: [{', '.join(tickers)}]\n"
             "sizing: equal_weight\nbenchmark: {name: UNIV20-EW, weighting: 1/N}\n" + BASE_CONV)
    c = folder("V12_bench_equal_vs_equal_misaligned_dates", rules)
    write_csv(c / "prices.csv", price_rows(days, prices), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "universe.csv", universe_rows(tickers, "2018-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "returns.csv", [{"date": days[k + 1].isoformat(), "return": round(strat[k], 8)}
                                  for k in range(n - 1)], ["date", "return"])
    write_csv(c / "benchmark_returns.csv", sorted(brows, key=lambda r: r["date"]), ["date", "return"])
    expected(c, "clean_tempting", ["benchmark_fit"],
             "Equal-weight book vs the equal-weight index of its own universe, declared with the alias '1/N'. The "
             "benchmark file misses ~10 dates and has two holiday rows the strategy does not have.",
             [must("benchmark_fit", "PASS")], forbid("benchmark_fit", ALERTS), [])


# ---------------------------------------------------------------------------- dividend_corporate_actions

def _div_world(seed, tickers, days, ex_dates, yield_q=0.012, skip=()):
    rng = np.random.default_rng(seed)
    raw, divs = {}, []
    for i, t in enumerate(tickers):
        p, s = 40.0 + 10 * i, []
        for d in days:
            p *= 1 + rng.normal(0.0003, 0.012)
            if d in ex_dates.get(t, ()):
                amt = round(p * yield_q, 2)
                divs.append({"ticker": t, "ex_date": d.isoformat(), "amount": amt})
                p -= amt
            s.append(round(p, 4))
        raw[t] = s
    idx = {d: k for k, d in enumerate(days)}
    adj = {}
    for t in tickers:
        f = [1.0] * len(days)
        for dv in divs:
            if dv["ticker"] != t or (t, dv["ex_date"]) in skip:
                continue
            k = idx[date.fromisoformat(dv["ex_date"])]
            g = 1 - dv["amount"] / raw[t][k - 1]
            for j in range(k):
                f[j] *= g
        adj[t] = [round(raw[t][k] * f[k], 4) for k in range(len(days))]
    return raw, adj, divs


QEX = [date(2023, 3, 15), date(2023, 6, 15), date(2023, 9, 15), date(2023, 12, 14)]


def v13_div_freeze_from_day_after():
    tickers = ["DA1", "DA2", "DA3"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    raw, adj, divs = _div_world(1013, tickers, days, {t: QEX for t in tickers})
    k = days.index(date(2023, 9, 15))
    for j in range(k + 1, k + 5):  # frozen from the session AFTER the ex-date, 4 sessions
        adj["DA2"][j] = adj["DA2"][k]
    c = folder("V13_div_frozen_from_session_after_ex_date", "strategy: dividend payers (no trades)\n" + BASE_CONV)
    write_csv(c / "prices.csv", price_rows(days, adj), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "unadjusted_prices.csv", [{"date": d.isoformat(), "ticker": t, "close": raw[t][i]}
                                            for t in tickers for i, d in enumerate(days)], ["date", "ticker", "close"])
    write_csv(c / "dividends.csv", divs, ["ticker", "ex_date", "amount"])
    expected(c, "planted_subtle", ["dividend_corporate_actions"],
             "All dividends are applied correctly, but DA2's adjusted close is frozen for 4 sessions starting the "
             "session AFTER its 2023-09-15 ex-date (the vendor applied the dividend, then stopped updating) while the "
             "as-traded price moves.",
             [must("dividend_corporate_actions", ALERTS)], forbid("dividend_corporate_actions", ["PASS"]),
             ["dividend_corporate_actions"], [{"check": "dividend_corporate_actions", "text": "DA2"}])


def v14_div_raw_labelled_adjusted_no_unadjusted():
    tickers = ["DR1", "DR2", "DR3"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    raw, adj, divs = _div_world(1014, tickers, days, {t: QEX for t in tickers}, yield_q=0.03)
    c = folder("V14_div_raw_prices_labelled_adjusted", "strategy: high-dividend payers (no trades)\n" + BASE_CONV)
    write_csv(c / "prices.csv", price_rows(days, raw, adjusted="true"), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "dividends.csv", divs, ["ticker", "ex_date", "amount"])
    expected(c, "planted_gap", ["dividend_corporate_actions"],
             "prices.csv is flagged adjusted=true but is the AS-TRADED series: each 3% quarterly dividend shows as a "
             "3% drop on the ex-date. unadjusted_prices.csv is not delivered, so the ratio test cannot run. The check "
             "cannot verify that dividends are applied and must not report the series as consistent.",
             [must("dividend_corporate_actions", NOT_PASS)], forbid("dividend_corporate_actions", ["PASS"]), [],
             note="Firm on 'not PASS'. A strong tool could even detect the ex-date drops (price falls by ~the "
                  "dividend on every ex-date) and raise NEEDS_REVIEW.")


def v15_div_clean_non_holding():
    tickers = ["DH1", "DH2"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    ex = {"DH1": QEX, "DH2": QEX}
    raw, adj, divs = _div_world(1015, tickers, days, ex)
    divs.append({"ticker": "ZZZ", "ex_date": "2023-06-15", "amount": 0.50})  # dividend of a name never held/priced
    # a tiny dividend (0.04%) on DH2 that is applied but too small to discriminate
    k = days.index(date(2023, 10, 16))
    amt = round(raw["DH2"][k - 1] * 0.0004, 4)
    divs.append({"ticker": "DH2", "ex_date": "2023-10-16", "amount": amt})
    g = 1 - amt / raw["DH2"][k - 1]
    adj["DH2"] = [round(v * (g if j < k else 1.0), 4) for j, v in enumerate(adj["DH2"])]
    q = int(40_000 // raw["DH1"][0])
    trades = [{"trade_id": 1, "timestamp": f"{days[0].isoformat()}T16:00:00", "ticker": "DH1", "side": "buy",
               "quantity": q, "price": adj["DH1"][0], "commission": round(q * adj["DH1"][0] * 0.001, 2)}]
    rules = ("strategy: buy and hold DH1\ncosts: {commission_rate: 0.001, slippage_rate: 0.0}\n" + BASE_CONV)
    c = folder("V15_div_clean_dividend_on_non_holding", rules)
    write_csv(c / "prices.csv", price_rows(days, adj), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "unadjusted_prices.csv", [{"date": d.isoformat(), "ticker": t, "close": raw[t][i]}
                                            for t in tickers for i, d in enumerate(days)], ["date", "ticker", "close"])
    write_csv(c / "dividends.csv", sorted(divs, key=lambda r: (r["ticker"], r["ex_date"])),
              ["ticker", "ex_date", "amount"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    expected(c, "clean_tempting", ["dividend_corporate_actions"],
             "Adjusted series consistent with every dividend. dividends.csv also lists a dividend of ZZZ (never priced "
             "nor held) and a tiny 0.04% dividend of DH2 (DH2 is priced but not held).",
             [must("dividend_corporate_actions", "PASS")], forbid("dividend_corporate_actions", ALERTS), [])


# ---------------------------------------------------------------------------- liquidity_participation

def _trade(i, d, t, side, q, px, rate):
    return {"trade_id": i, "timestamp": f"{d.isoformat()}T16:00:00", "ticker": t, "side": side, "quantity": q,
            "price": px, "commission": round(q * px * rate, 2)}


def v16_liq_sliced_orders():
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    rng = np.random.default_rng(1016)
    prices = {"SL1": gbm(rng, len(days), 10.0, 0.0003, 0.01, 2), "SL2": gbm(rng, len(days), 30.0, 0.0003, 0.01, 2)}
    volume = {"SL1": [int(100_000 * (0.9 + 0.2 * rng.random())) for _ in days],
              "SL2": [int(2_000_000 * (0.9 + 0.2 * rng.random())) for _ in days]}
    trades, i = [], 0
    for m, d in enumerate(first_bdays(days)[1:7]):
        k = days.index(d)
        side = "buy" if m % 2 == 0 else "sell"
        for _ in range(5):  # one parent order of ~40% of ADV sliced into five child fills of 8,000 shares
            i += 1
            trades.append(_trade(i, d, "SL1", side, 8_000, prices["SL1"][k], 0.0005))
        i += 1
        trades.append(_trade(i, d, "SL2", side, 1_000, prices["SL2"][k], 0.0005))
    rules = ("strategy: periodic trades\ncosts: {commission_rate: 0.0005, slippage_rate: 0.0}\n"
             "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n  initial_cash: 1000000\n")
    c = folder("V16_liq_parent_order_sliced_into_child_fills", rules)
    write_csv(c / "prices.csv", price_rows(days, prices, volume), ["date", "ticker", "close", "volume", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    expected(c, "planted_subtle", ["liquidity_participation"],
             "Each SL1 child fill is 8,000 shares (~8% of an ADV of ~100,000: below the 10% threshold), but five "
             "fills on the same day add up to 40,000 shares, ~40% of ADV (below the day's volume, so the "
             "'larger than the day' rule does not fire). Participation must be judged per ticker-day.",
             [must("liquidity_participation", "NEEDS_REVIEW")], forbid("liquidity_participation", ["PASS"]),
             ["liquidity_participation"], [{"check": "liquidity_participation", "text": "SL1"}])


def v17_liq_unmeasured_large_trades():
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    rng = np.random.default_rng(1017)
    prices = {"UM1": gbm(rng, len(days), 20.0, 0.0003, 0.01, 2), "UM2": gbm(rng, len(days), 5.0, 0.0003, 0.02, 2)}
    volume = {"UM1": [int(3_000_000 * (0.9 + 0.2 * rng.random())) for _ in days],
              "UM2": [None for _ in days]}  # volume not delivered for the small-cap UM2
    trades, i = [], 0
    for m, d in enumerate(first_bdays(days)[1:9]):
        k = days.index(d)
        side = "buy" if m % 2 == 0 else "sell"
        i += 1
        trades.append(_trade(i, d, "UM1", side, 2_000, prices["UM1"][k], 0.0005))
        i += 1
        trades.append(_trade(i, d, "UM2", side, 120_000, prices["UM2"][k], 0.0005))
    rules = ("strategy: periodic trades\ncosts: {commission_rate: 0.0005, slippage_rate: 0.0}\n"
             "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n  initial_cash: 1000000\n")
    c = folder("V17_liq_half_the_trades_have_no_volume", rules)
    write_csv(c / "prices.csv", price_rows(days, prices, volume), ["date", "ticker", "close", "volume", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    expected(c, "planted_gap", ["liquidity_participation"],
             "Half of the trades (all UM2, ~60% of the traded notional, 120,000 shares of a small cap) have no "
             "volume at all, so their participation is unmeasurable; the measured half (UM1) is tiny. A PASS "
             "'every trade below 10% of ADV' would claim what was not verified.",
             [must("liquidity_participation", NOT_PASS)], forbid("liquidity_participation", ["PASS"]), [],
             note="Firm on 'not PASS' for the claim 'every trade'; a PASS scoped explicitly to the measured trades "
                  "with an alert for the rest would also be acceptable but is not what the vocabulary allows.")


def v18_liq_illiquid_tiny_trades():
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    rng = np.random.default_rng(1018)
    prices = {"IL1": gbm(rng, len(days), 8.0, 0.0002, 0.015, 2), "IL2": gbm(rng, len(days), 50.0, 0.0003, 0.01, 2)}
    volume = {"IL1": [1_000 if k % 5 == 4 else 0 for k in range(len(days))],  # trades one day in five
              "IL2": [int(1_500_000 * (0.9 + 0.2 * rng.random())) for _ in days]}
    trades, i = [], 0
    for k in range(30, len(days) - 5, 25):
        while volume["IL1"][k] == 0:
            k += 1
        i += 1
        trades.append(_trade(i, days[k], "IL1", "buy" if i % 2 else "sell", 10, prices["IL1"][k], 0.001))
        i += 1
        trades.append(_trade(i, days[k], "IL2", "buy" if i % 2 else "sell", 100, prices["IL2"][k], 0.001))
    rules = ("strategy: tiny satellite positions in an illiquid name\n"
             "costs: {commission_rate: 0.001, slippage_rate: 0.0}\n" + BASE_CONV)
    c = folder("V18_liq_illiquid_name_tiny_trades", rules)
    write_csv(c / "prices.csv", price_rows(days, prices, volume), ["date", "ticker", "close", "volume", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    expected(c, "clean_tempting", ["liquidity_participation"],
             "IL1 is illiquid (zero volume four days in five, ADV ~200 shares) but every IL1 trade is 10 shares (~5% "
             "of ADV, 1% of its day's volume) and happens on a day with volume.",
             [must("liquidity_participation", "PASS")], forbid("liquidity_participation", ALERTS), [])


# ---------------------------------------------------------------------------- cost_sensitivity

def _round_trip_book(days, px, cash0, invest, rate, every=10):
    """Hold one name; every `every` sessions sell all and buy back. Returns trades, final NAV, notional."""
    trades, cash, q, notional, i = [], cash0, 0, 0.0, 0
    for k in range(0, len(days) - 1, every):
        d, p = days[k], px[k]
        if q:
            n = q * p
            cash += n - round(n * rate, 2)
            notional += n
            i += 1
            trades.append(_trade(i, d, "CS1", "sell", q, p, rate))
        q = int(cash * invest // p)
        n = q * p
        cash -= n + round(n * rate, 2)
        notional += n
        i += 1
        trades.append(_trade(i, d, "CS1", "buy", q, p, rate))
    return trades, cash + q * px[-1], notional


def v19_cost_fragile_only_vs_benchmark():
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    n = len(days)
    rng = np.random.default_rng(1019)
    noise = rng.normal(0, 0.004, n)
    px = [round(100 * math.exp(math.log(1.21) * k / (n - 1) + noise[k] - noise[0]), 2) for k in range(n)]
    cash0 = 100_000.0
    _, nav0, notional = _round_trip_book(days, px, cash0, 0.9, 0.0)
    gross = nav0 / cash0 - 1
    turnover = notional / cash0
    bench_total = gross - 0.045  # benchmark 4.5 pp below the gross result
    rate = round(0.03 / turnover, 6)  # 1x costs take ~3 pp: 1x survives the benchmark, 2x (6 pp) does not
    trades, nav1, _ = _round_trip_book(days, px, cash0, 0.9, rate)
    _, nav2, _ = _round_trip_book(days, px, cash0, 0.9, 2 * rate)
    assert nav1 / cash0 - 1 > bench_total > nav2 / cash0 - 1, (gross, nav1, nav2, bench_total)
    assert nav2 / cash0 - 1 > 0 and _round_trip_book(days, px, cash0, 0.9, 3 * rate)[1] > cash0
    b_daily = (1 + bench_total) ** (1 / (n - 1)) - 1
    brng = np.random.default_rng(2019)
    bret = [b_daily + float(x) for x in brng.normal(0, 0.006, n - 1)]
    adj = (1 + bench_total) / float(np.prod([1 + x for x in bret]))
    bret[-1] = (1 + bret[-1]) * adj - 1  # exact benchmark total
    rules = ("strategy: one-name book rebalanced every two weeks\n"
             f"costs: {{commission_rate: {rate}, slippage_rate: 0.0}}\n" + BASE_CONV)
    c = folder("V19_cost_fragile_only_against_benchmark", rules)
    write_csv(c / "prices.csv", price_rows(days, {"CS1": px}), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    write_csv(c / "benchmark_returns.csv", [{"date": days[k + 1].isoformat(), "return": round(bret[k], 10)}
                                            for k in range(n - 1)], ["date", "return"])
    expected(c, "planted_subtle", ["cost_sensitivity"],
             f"Gross {gross:+.2%}, turnover {turnover:.1f}x, benchmark {bench_total:+.2%}. Net of 1x declared costs the "
             f"book beats the benchmark ({nav1 / cash0 - 1:+.2%}); at 2x ({nav2 / cash0 - 1:+.2%}) it does not. Against a "
             "zero hurdle the result survives even 3x, so the fragility is visible only against the benchmark.",
             [must("cost_sensitivity", "NEEDS_REVIEW")], forbid("cost_sensitivity", ["PASS"]), [],
             [{"check": "cost_sensitivity", "text": "2x"}])


def v20_cost_clean_bps_costs_csv():
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    n = len(days)
    rng = np.random.default_rng(1020)
    noise = rng.normal(0, 0.004, n)
    px = [round(100 * math.exp(math.log(1.25) * k / (n - 1) + noise[k] - noise[0]), 2) for k in range(n)]
    trades, _, _ = _round_trip_book(days, px, 100_000.0, 0.9, 0.0010, every=21)
    c = folder("V20_cost_clean_costs_in_bps_file", "strategy: one-name book, monthly round trip\n" + BASE_CONV)
    write_csv(c / "prices.csv", price_rows(days, {"CS1": px}), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    write_csv(c / "costs.csv", [{"item": "commission", "value": 10, "unit": "bps"},
                                {"item": "slippage", "value": 0, "unit": "bps"}], ["item", "value", "unit"])
    expected(c, "clean_tempting", ["cost_sensitivity"],
             "Gross ~+22%, turnover ~11x, costs declared in costs.csv as 10 bps (unit bps, not a fraction), charged "
             "in trades.csv: 3x costs take ~3 pp. Must PASS (and must read 10 bps as 0.001, not 10).",
             [must("cost_sensitivity", "PASS")], forbid("cost_sensitivity", ALERTS), [])


# ---------------------------------------------------------------------------- stability_and_concentration

def v21_stab_one_year_barely_carries():
    days = bdays(date(2020, 1, 1), date(2023, 12, 29))
    rng = np.random.default_rng(1021)
    target = {2020: 0.05, 2021: 0.30, 2022: -0.04, 2023: -0.02}  # others net -0.01: 2021 = 103% of total
    rows = []
    for y, tot in target.items():
        dd = [d for d in days if d.year == y]
        x = rng.normal(0, 0.006, len(dd))
        x = x - x.mean() + tot / len(dd)
        rows += [{"date": d.isoformat(), "return": round(float(v), 10)} for d, v in zip(dd, x)]
    c = folder("V21_stab_one_year_carries_by_a_hair", "strategy: declared daily returns\n" + BASE_CONV)
    write_csv(c / "returns.csv", rows, ["date", "return"])
    expected(c, "planted_subtle", ["stability_and_concentration"],
             "Four calendar years with summed returns +5%, +30%, -4%, -2%: 2021 alone is 103% of the total; the other "
             "three years together are net -1% (barely negative, near the rule's edge).",
             [must("stability_and_concentration", "NEEDS_REVIEW")], forbid("stability_and_concentration", ["PASS"]),
             [], [{"check": "stability_and_concentration", "text": "2021"}])


def v22_stab_clean_big_but_not_whole():
    days = bdays(date(2021, 1, 4), date(2023, 12, 29))
    rng = np.random.default_rng(1022)
    drifts = {"BG1": 0.0012, "BG2": 0.0003, "BG3": 0.0003, "BG4": 0.0002, "BG5": 0.0002}
    prices = {t: gbm(rng, len(days), 50.0, mu, 0.004, 2) for t, mu in drifts.items()}
    trades, qty = [], {}
    for i, t in enumerate(drifts, 1):
        q = int(19_000 // prices[t][0])
        qty[t] = q
        trades.append(_trade(i, days[0], t, "buy", q, prices[t][0], 0.001))
    # the generator verifies its own description: every name ends up, every calendar year is positive
    assert all(prices[t][-1] > prices[t][0] for t in drifts)
    nav = [sum(qty[t] * prices[t][k] for t in drifts) for k in range(len(days))]
    for y in (2021, 2022, 2023):
        ks = [k for k, d in enumerate(days) if d.year == y]
        assert nav[ks[-1]] > nav[max(ks[0] - 1, 0)], y
    rules = "strategy: buy and hold five names\ncosts: {commission_rate: 0.001, slippage_rate: 0.0}\n" + BASE_CONV
    c = folder("V22_stab_clean_one_big_winner_others_positive", rules)
    write_csv(c / "prices.csv", price_rows(days, prices), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    expected(c, "clean_tempting", ["stability_and_concentration"],
             "Three years, five names all with positive drift; BG1 contributes well over half of the P&L but the "
             "other four are positive too, every year is positive and no handful of days carries the result.",
             [must("stability_and_concentration", "PASS")], forbid("stability_and_concentration", ALERTS), [])


# ---------------------------------------------------------------------------- conditional_rule_activation

def _monthly(seed, start=date(2010, 1, 1), end=date(2024, 12, 31)):
    rng = np.random.default_rng(seed)
    months = month_ends(start, end)
    rets = [{"date": m.isoformat(), "return": round(float(rng.normal(0.006, 0.03)), 6)} for m in months]
    return months, rets


MONTHLY_CONV = ("conventions:\n  calendar: none\n  review_date: '2026-10-28'\n  periods_per_year: 12\n"
                "  oos_start: '2022-01-01'\n")


def v23_rule_never_computed_in_sample():
    months, rets = _monthly(1023)
    ins = [m for m in months if m < date(2022, 1, 1)]
    oos = [m for m in months if m >= date(2022, 1, 1)]
    reg = []
    for k, m in enumerate(months):
        a = int(k % 5 in (0, 2))  # balanced rule, ~40% everywhere
        b = "" if m < date(2022, 1, 1) else int(oos.index(m) < 29)  # not computed in sample; 29/36 out of sample
        reg.append({"date": m.isoformat(), "high_vol": a, "credit_stress": b})
    rules = ("strategy: monthly allocation with two conditional rules\nconditional_rules:\n"
             "  - {name: high_vol_rule, column: high_vol}\n  - {name: credit_stress_rule, column: credit_stress}\n"
             + MONTHLY_CONV)
    c = folder("V23_rule_never_computed_in_sample", rules)
    write_csv(c / "regimes.csv", reg, ["date", "high_vol", "credit_stress"])
    write_csv(c / "returns.csv", rets, ["date", "return"])
    expected(c, "planted_gap", ["conditional_rule_activation"],
             f"Two declared rules. high_vol is balanced (~40% in and out). credit_stress was never computed in sample "
             f"(empty in all {len(ins)} in-sample months) and is active in 29 of 36 out-of-sample months (81%): the "
             "test window measures a rule the training period never exercised.",
             [must("conditional_rule_activation", NOT_PASS)], forbid("conditional_rule_activation", ["PASS"]), [],
             [{"check": "conditional_rule_activation", "text": "credit_stress"}],
             note="Firm on 'not PASS': a declared rule with no in-sample value cannot be reported as 'active "
                  "comparably in and out of sample'. NEEDS_REVIEW is the right answer.")


def v24_rule_near_threshold():
    months, rets = _monthly(1024)
    ins = [m for m in months if m < date(2022, 1, 1)]
    oos = [m for m in months if m >= date(2022, 1, 1)]
    act_in = set(ins[3::11][:13])  # 13 of 144 = 9.0%
    act_out = set(oos[::2][:18]) | {oos[1]}  # 19 of 36 = 52.8%
    reg = [{"date": m.isoformat(), "inverted_curve": int(m in act_in or m in act_out)} for m in months]
    assert sum(r["inverted_curve"] for r in reg if r["date"] < "2022") == 13
    assert sum(r["inverted_curve"] for r in reg if r["date"] >= "2022") == 19
    rules = ("strategy: bond allocation with an inverted-curve rule\nconditional_rules:\n"
             "  - {name: inverted_curve_rule, column: inverted_curve}\n" + MONTHLY_CONV)
    c = folder("V24_rule_just_inside_both_thresholds", rules)
    write_csv(c / "regimes.csv", reg, ["date", "inverted_curve"])
    write_csv(c / "returns.csv", rets, ["date", "return"])
    expected(c, "planted_subtle", ["conditional_rule_activation"],
             "Active in 13 of 144 in-sample months (9.0%, just below 10%) and 19 of 36 out-of-sample months (52.8%, "
             "just above 50%).",
             [must("conditional_rule_activation", "NEEDS_REVIEW")], forbid("conditional_rule_activation", ["PASS"]),
             [], [{"check": "conditional_rule_activation", "text": "inverted_curve_rule"}])


def v25_rule_clean_rare_both_and_common_both():
    months, rets = _monthly(1025)
    ins = [m for m in months if m < date(2022, 1, 1)]
    oos = [m for m in months if m >= date(2022, 1, 1)]
    rare = set(ins[::20]) | {oos[10], oos[25]} | {ins[7]}  # ~5% in, ~6% out
    common = {m for k, m in enumerate(months) if k % 10 < 6} | set(oos[:26])  # ~60% in, ~72% out
    reg = [{"date": m.isoformat(), "crisis": int(m in rare), "uptrend": int(m in common)} for m in months]
    rules = ("strategy: allocation with two conditional rules\nconditional_rules:\n"
             "  - {name: crisis_rule, column: crisis}\n  - {name: trend_rule, column: uptrend}\n" + MONTHLY_CONV)
    c = folder("V25_rule_clean_rare_in_both_and_common_in_both", rules)
    write_csv(c / "regimes.csv", reg, ["date", "crisis", "uptrend"])
    write_csv(c / "returns.csv", rets, ["date", "return"])
    expected(c, "clean_tempting", ["conditional_rule_activation"],
             "crisis_rule is rare in sample (~5%) AND rare out of sample (~6%); trend_rule is common in both (~60% "
             "and ~72%). Neither is 'rare in sample but dominant out of sample'.",
             [must("conditional_rule_activation", "PASS")], forbid("conditional_rule_activation", ALERTS), [])


# ---------------------------------------------------------------------------- end to end

def v26_e2e_research_package():
    tickers = [f"E{i:02d}" for i in range(1, 21)]
    quarters = quarter_ends(date(2016, 1, 1), date(2024, 12, 31))
    rng = np.random.default_rng(1026)

    def keep(ti, qi, q, f):
        if q >= date(2022, 3, 31) and ti >= 15:
            return False  # 5 of 20 members without fundamentals in the test years (75%)
        return ti != qi % 20
    months, rets = _monthly(2026, date(2016, 1, 1), date(2024, 12, 31))
    oos = [m for m in months if m >= date(2022, 1, 1)]
    ins = [m for m in months if m < date(2022, 1, 1)]
    act = set(ins[4::18]) | set(oos[:28])
    reg = [{"date": m.isoformat(), "defensive": int(m in act)} for m in months]
    bench = [{"date": r["date"], "return": round(float(r["return"]) * 0.8 + float(rng.normal(0, 0.01)), 6)}
             for r in rets]
    rules = ("strategy: equal-weight quality book, monthly\n" f"universe: [{', '.join(tickers)}]\n"
             "sizing: equal_weight\nbenchmark: {name: CAPIDX, weighting: cap_weighted}\n"
             "research: {n_trials: 12}\nconditional_rules:\n  - {name: defensive_rule, column: defensive}\n"
             "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n  periods_per_year: 12\n")
    c = folder("V26_e2e_research_package_four_problems", rules)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    write_csv(c / "universe.csv", universe_rows(tickers, "2015-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "fundamentals.csv", fundamentals_rows(rng, tickers, quarters, keep), FUND_COLS)
    write_csv(c / "returns.csv", rets, ["date", "return"])
    write_csv(c / "benchmark_returns.csv", bench, ["date", "return"])
    write_csv(c / "regimes.csv", reg, ["date", "defensive"])
    write_csv(c / "run_log.csv", _runs([("2026-03-01T10:00:00", "test", "c07", "test"),
                                        ("2026-03-08T10:00:00", "test", "c09", "test")]), RUN_COLS)
    expected(c, "end_to_end", ["coverage_drift", "protocol_integrity", "benchmark_fit", "conditional_rule_activation"],
             "Four problems at once: fundamentals coverage 95% -> 75% from 2022; a second config (c09) evaluated on "
             "the single-use test window; equal-weight book vs a cap-weighted benchmark; defensive rule active in 5% "
             "of in-sample months and 78% of test months.",
             [must("coverage_drift", "NEEDS_REVIEW"), must("protocol_integrity", "CONFIRMED_ERROR"),
              must("benchmark_fit", "NEEDS_REVIEW"), must("conditional_rule_activation", "NEEDS_REVIEW")],
             forbid("coverage_drift", ["PASS"]) + forbid("protocol_integrity", ["PASS"])
             + forbid("benchmark_fit", ["PASS"]) + forbid("conditional_rule_activation", ["PASS"]),
             ["protocol_integrity", "coverage_drift"], [{"check": "protocol_integrity", "text": "c09"}])


def v27_e2e_trading_package():
    tickers = ["EX1", "EX2"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    raw, adj, divs = _div_world(1027, tickers, days, {t: QEX for t in tickers}, yield_q=0.015,
                                skip={("EX1", "2023-06-15")})
    rng = np.random.default_rng(1127)
    volume = {"EX1": [int(2_000_000 * (0.9 + 0.2 * rng.random())) for _ in days],
              "EX2": [int(300_000 * (0.9 + 0.2 * rng.random())) for _ in days]}
    k5 = days.index(date(2023, 5, 2))
    volume["EX2"][k5] = 4_000  # the day of the second EX2 buy trades less than the order
    trades = [_trade(1, days[0], "EX1", "buy", 1_000, adj["EX1"][0], 0.001),
              _trade(2, days[0], "EX2", "buy", 500, adj["EX2"][0], 0.001),
              _trade(3, days[k5], "EX2", "buy", 5_000, adj["EX2"][k5], 0.001)]
    inputs = ["roe", "margin", "growth", "leverage"]
    months = first_bdays(days)
    sig = []
    for d in months:
        for t in tickers:
            r = {"decision_time": d.isoformat(), "ticker": t, "signal": round(float(rng.normal()), 4)}
            for kk, f in enumerate(inputs):
                r[f] = "" if (d.month >= 11 and kk >= 2) else round(float(rng.normal()), 4)
            sig.append(r)
    rules = ("strategy: two-name dividend book\ncosts: {commission_rate: 0.001, slippage_rate: 0.0}\n"
             f"required_inputs: [{', '.join(inputs)}]\nmin_input_share: 0.75\n"
             "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n  initial_cash: 1000000\n")
    c = folder("V27_e2e_trading_package_three_errors", rules)
    write_csv(c / "prices.csv", price_rows(days, adj, volume), ["date", "ticker", "close", "volume", "adjusted"])
    write_csv(c / "unadjusted_prices.csv", [{"date": d.isoformat(), "ticker": t, "close": raw[t][i]}
                                            for t in tickers for i, d in enumerate(days)], ["date", "ticker", "close"])
    write_csv(c / "dividends.csv", divs, ["ticker", "ex_date", "amount"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    write_csv(c / "signals.csv", sig, ["decision_time", "ticker", "signal"] + inputs)
    expected(c, "end_to_end", ["dividend_corporate_actions", "liquidity_participation", "input_sufficiency"],
             "Three confirmed errors at once: EX1's 2023-06-15 dividend is not applied while its other three are; the "
             "2023-05-02 EX2 buy (5,000 shares) exceeds that day's whole volume (4,000); in Nov-Dec 2023 names are "
             "scored with 2 of 4 inputs against a declared minimum of 0.75.",
             [must("dividend_corporate_actions", "CONFIRMED_ERROR"), must("liquidity_participation", "CONFIRMED_ERROR"),
              must("input_sufficiency", "CONFIRMED_ERROR")],
             forbid("dividend_corporate_actions", ["PASS"]) + forbid("liquidity_participation", ["PASS"])
             + forbid("input_sufficiency", ["PASS"]), None,
             [{"check": "dividend_corporate_actions", "text": "EX1"}, {"check": "liquidity_participation",
                                                                         "text": "EX2"}])


def v28_lockin_like_holdout():
    rng = np.random.default_rng(1028)
    tickers = [f"Q{i:03d}" for i in range(1, 101)]
    quarters = quarter_ends(date(2010, 1, 1), date(2024, 12, 31))
    lost = set(rng.choice(100, size=18, replace=False).tolist())  # 18 more members lose fundamentals in 2022+

    def keep(ti, qi, q, f):
        if q >= date(2022, 3, 31) and ti in lost:
            return False
        return (ti * 13 + qi * 7) % 100 >= 3  # ~97% coverage
    fund = fundamentals_rows(rng, tickers, quarters, keep)
    months = first_bdays(bdays(date(2010, 4, 1), date(2024, 12, 31)))
    sig = [{"decision_time": d.isoformat(), "ticker": t, "signal": round(float(rng.normal()), 4)}
           for d in months for t in tickers]  # every member scored every month (stale values carried forward)
    rules = ("strategy: LockIn-style quality ranking (top 10 of 100, monthly)\n"
             f"universe: [{', '.join(tickers)}]\n"
             "required_inputs: [roe, debt_to_equity, gross_margin]\nmin_input_share: 0.67\n"
             "research: {n_trials: 12}\n" + BASE_CONV)
    c = folder("V28_lockin_like_holdout_coverage_drop", rules)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    write_csv(c / "universe.csv", universe_rows(tickers, "2009-01-02"), ["ticker", "start_date", "end_date"])
    write_csv(c / "fundamentals.csv", fund, FUND_COLS)
    write_csv(c / "signals.csv", sig, ["decision_time", "ticker", "signal"])
    write_csv(c / "run_log.csv", _runs([("2026-03-01T10:00:00", "test", "c07", "test")]), RUN_COLS)
    expected(c, "lockin_holdout", ["coverage_drift", "input_sufficiency", "pit_fundamentals", "protocol_integrity"],
             "LockIn's central failure: fundamentals cover ~97% of the 100 members through 2021 and ~79% in the "
             "single-use test years 2022-2024, while every member is still scored every month. Row-level preflight "
             "checks (point-in-time lag 40 days, schema, protocol: one clean test look) pass.",
             [must("coverage_drift", "NEEDS_REVIEW"), must("pit_fundamentals", "PASS"),
              must("protocol_integrity", "PASS"), must("input_sufficiency", ALERTS)],
             forbid("coverage_drift", ["PASS"]), ["coverage_drift", "input_sufficiency"],
             [{"check": "coverage_drift", "text": "2022"}],
             note="coverage_drift NEEDS_REVIEW is the firm expectation. input_sufficiency is a STRETCH expectation: "
                  "the 18 members are scored in 2024 from fundamentals filed in early 2022 (as-of lookup without a "
                  "staleness limit); a reviewer would call those inputs missing.")


def main():
    for f in [v01_cov_single_field_late_drop, v02_cov_vendor_stops, v03_cov_universe_shrinks, v04_cov_optional_field,
              v05_suff_one_month_below, v06_suff_case_mismatch, v07_suff_unscored_when_missing,
              v08_proto_validation_window_overlaps_test, v09_proto_adjacent_clean, v10_proto_holdout_label,
              v11_bench_declared_equal_actually_cap, v12_bench_clean_misaligned_dates,
              v13_div_freeze_from_day_after, v14_div_raw_labelled_adjusted_no_unadjusted, v15_div_clean_non_holding,
              v16_liq_sliced_orders, v17_liq_unmeasured_large_trades, v18_liq_illiquid_tiny_trades,
              v19_cost_fragile_only_vs_benchmark, v20_cost_clean_bps_costs_csv,
              v21_stab_one_year_barely_carries, v22_stab_clean_big_but_not_whole,
              v23_rule_never_computed_in_sample, v24_rule_near_threshold, v25_rule_clean_rare_both_and_common_both,
              v26_e2e_research_package, v27_e2e_trading_package, v28_lockin_like_holdout]:
        f()
    print("review cases written to", OUT)


if __name__ == "__main__":
    main()
