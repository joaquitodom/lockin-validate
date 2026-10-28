"""Lesson cases (cases/lessons/): one positive and one clean negative per new check family, seeded.

Does NOT import lockin_validate. Usage (from the repository root):  uv run python cases/_generators/lessons_cases.py

Every case reproduces, in synthetic form, a failure observed in the LockIn case study (see docs/CHECKS.md,
"Motivation"). expected.json is written by this generator from the problem planted, BEFORE the checks that read
these inputs were implemented (see the git history: this file was committed first).

  L01  fundamentals coverage falls from ~97% to ~80% of the universe        -> coverage_drift NEEDS_REVIEW
  L02  fundamentals coverage stable (97-100%)                               -> coverage_drift PASS
  L03  reserved window scored with 5 of 10 required inputs (min share 0.8)  -> input_sufficiency CONFIRMED_ERROR,
                                                                               coverage_drift NEEDS_REVIEW
  L04  every scored name has at least 9 of 10 required inputs               -> input_sufficiency PASS, coverage_drift PASS
  L05  single-use test window looked at by several configs + a diagnostic   -> protocol_integrity CONFIRMED_ERROR
  L06  one test look, then only same-config reproductions                   -> protocol_integrity PASS
  L07  diagnostic runs over a proposed fresh (reserved) window              -> protocol_integrity CONFIRMED_ERROR
  L08  equal-weight book against a cap-weighted benchmark                   -> benchmark_fit NEEDS_REVIEW
  L09  equal-weight book against an equal-weight benchmark of its universe  -> benchmark_fit PASS
  L10  dividend not applied in the adjusted series; adjusted price frozen
       from an ex-date while the as-traded price moves                      -> dividend_corporate_actions CONFIRMED_ERROR
  L11  adjusted series consistent with dividends and as-traded prices       -> dividend_corporate_actions PASS
  L12  orders of about 40% of ADV, one larger than the day's volume; excess
       return gone at 2x declared costs                                     -> liquidity_participation CONFIRMED_ERROR,
                                                                               cost_sensitivity NEEDS_REVIEW
  L13  participation below 1% of ADV; result robust to 3x declared costs    -> liquidity_participation PASS,
                                                                               cost_sensitivity PASS
  L14  one name of five carries the whole P&L                               -> stability_and_concentration NEEDS_REVIEW
  L15  conditional rule active in 5% of in-sample months, 83% out of sample -> conditional_rule_activation NEEDS_REVIEW
  L16  steady five-year series; regime active ~40% in and out of sample     -> stability_and_concentration PASS,
                                                                               conditional_rule_activation PASS
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
OUT = HERE.parent / "lessons"
ALERTS = ["CONFIRMED_ERROR", "NEEDS_REVIEW"]


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


def write_expected(c: Path, description: str, must_include, must_not, errors_only_from, text=None):
    exp = {"description": description, "origin": "lessons", "must_include": must_include,
           "must_not_include": must_not, "errors_only_from": errors_only_from}
    if text:
        exp["text_must_contain"] = text
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


BASE_CONV = "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n"


# ---------------------------------------------------------------------------- family 1: coverage and inputs

def fundamentals_case(name: str, drop: bool):
    tickers = [f"T{i:02d}" for i in range(1, 31)]
    c = folder(name, "strategy: quality screen on quarterly fundamentals (no trades)\n" + BASE_CONV)
    write_csv(c / "universe.csv", [{"ticker": t, "start_date": "2015-01-02", "end_date": ""} for t in tickers],
              ["ticker", "start_date", "end_date"])
    rng = np.random.default_rng(101)
    rows = []
    quarters = [d for d in month_ends(date(2016, 3, 1), date(2023, 12, 31)) if d.month in (3, 6, 9, 12)]
    for qi, q in enumerate(quarters):
        for ti, t in enumerate(tickers):
            if qi % 3 == 0 and ti == qi % 30:  # one member without a filing every third quarter (~97-100%)
                continue
            if drop and q >= date(2022, 3, 31) and ti >= 24:  # six of thirty members lose fundamentals
                continue
            filed = q + timedelta(days=40)
            rows.append({"ticker": t, "period_end": q.isoformat(), "filing_date": filed.isoformat(),
                         "available_from": filed.isoformat(), "roe": round(float(rng.normal(0.12, 0.05)), 4),
                         "debt_to_equity": round(float(abs(rng.normal(0.8, 0.3))), 4),
                         "gross_margin": round(float(rng.normal(0.35, 0.08)), 4)})
    write_csv(c / "fundamentals.csv", rows,
              ["ticker", "period_end", "filing_date", "available_from", "roe", "debt_to_equity", "gross_margin"])
    if drop:
        write_expected(c, "From 2022-Q1 six of thirty universe members have no fundamentals: coverage falls from "
                          "about 97% to 80% (the LockIn holdout database had ~21% of members without fundamentals).",
                       [must("coverage_drift", "NEEDS_REVIEW")], forbid("coverage_drift", ["PASS"]),
                       ["coverage_drift"], [{"check": "coverage_drift", "text": "2022"}])
    else:
        write_expected(c, "Fundamentals coverage stable between 97% and 100% of the universe in every quarter.",
                       [must("coverage_drift", "PASS")], forbid("coverage_drift", ALERTS), [])


def signals_inputs_case(name: str, insufficient: bool):
    tickers = [f"S{i:02d}" for i in range(1, 21)]
    inputs = [f"f{i:02d}" for i in range(1, 11)]
    rules = ("strategy: multi-input score (10 declared inputs) ranked monthly\n"
             f"universe: [{', '.join(tickers)}]\n"
             f"required_inputs: [{', '.join(inputs)}]\n"
             "min_input_share: 0.8\n" + BASE_CONV)
    c = folder(name, rules)
    rng = np.random.default_rng(202)
    rows = []
    for mi, d in enumerate(first_bdays(bdays(date(2021, 1, 1), date(2024, 12, 31)))):
        for ti, t in enumerate(tickers):
            row = {"decision_time": d.isoformat(), "ticker": t}
            for k, f in enumerate(inputs):
                v = round(float(rng.normal()), 4)
                if insufficient and d >= date(2024, 1, 1) and k >= 5:
                    v = ""  # the reserved window ran with only half of the inputs
                if not insufficient and ti == mi % 20 and k == mi % 10:
                    v = ""  # one input missing for one name per month: 9 of 10 present
                row[f] = v
            row["signal"] = round(float(rng.normal()), 4)
            rows.append(row)
    write_csv(c / "signals.csv", rows, ["decision_time", "ticker", "signal"] + inputs)
    if insufficient:
        write_expected(c, "rules.yaml requires 10 inputs with a minimum share of 0.8; during 2024 (the reserved "
                          "window) inputs f06-f10 are empty but every name is still scored (5 of 10 inputs). LockIn "
                          "ran a reserved window with 13 of 27 inputs while existing preflight checks passed.",
                       [must("input_sufficiency", "CONFIRMED_ERROR"), must("coverage_drift", "NEEDS_REVIEW")],
                       forbid("input_sufficiency", ["PASS"]) + forbid("coverage_drift", ["PASS"]),
                       ["input_sufficiency"], [{"check": "input_sufficiency", "text": "2024"}])
    else:
        write_expected(c, "Every scored name has at least 9 of its 10 required inputs (minimum share 0.8); "
                          "per-input coverage never falls below 95%.",
                       [must("input_sufficiency", "PASS"), must("coverage_drift", "PASS")],
                       forbid("input_sufficiency", ALERTS) + forbid("coverage_drift", ALERTS), [])


# ---------------------------------------------------------------------------- family 2: protocol

PROTOCOL = """\
train: {start: '2010-01-01', end: '2017-12-31'}
validation: {start: '2018-01-01', end: '2021-12-31'}
test: {start: '2022-01-01', end: '2024-12-31', single_use: true}
"""
WINDOWS = {"train": ("2010-01-01", "2017-12-31"), "validation": ("2018-01-01", "2021-12-31"),
           "test": ("2022-01-01", "2024-12-31")}
RUN_COLS = ["timestamp", "run_id", "window_start", "window_end", "config_hash", "purpose"]


def _run(ts: str, i: int, window, cfg: str, purpose: str) -> dict:
    w = WINDOWS[window] if isinstance(window, str) else window
    return {"timestamp": ts, "run_id": f"run-{i:03d}", "window_start": w[0], "window_end": w[1],
            "config_hash": cfg, "purpose": purpose}


def _research_runs() -> list[dict]:
    runs, i = [], 0
    for k in range(1, 21):
        i += 1
        runs.append(_run(f"2026-01-{(k % 28) + 1:02d}T10:00:00", i, "train", f"c{k:02d}", "train"))
    for k in range(1, 13):
        i += 1
        runs.append(_run(f"2026-02-{k + 1:02d}T10:00:00", i, "validation", f"c{k:02d}", "validation"))
    return runs


def protocol_case_reused():
    c = folder("L05_test_window_reused", "strategy: research log of a ranking model\nresearch: {n_trials: 3}\n"
               + BASE_CONV)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    runs = _research_runs()
    i = len(runs)
    extra = [("2026-03-01T10:00:00", "test", "c07", "test"),
             ("2026-03-02T10:00:00", ("2023-01-01", "2024-12-31"), "c07", "diagnostic"),
             ("2026-03-10T10:00:00", "train", "c21", "train"),
             ("2026-03-12T10:00:00", "validation", "c21", "validation"),
             ("2026-03-15T10:00:00", "test", "c21", "test"),
             ("2026-03-16T10:00:00", "test", "c99", "reproduction")]
    for ts, w, cfg, p in extra:
        i += 1
        runs.append(_run(ts, i, w, cfg, p))
    write_csv(c / "run_log.csv", runs, RUN_COLS)
    write_expected(c, "Single-use test window (2022-2024) looked at by c07, then a diagnostic run over 2023-2024, a "
                      "new config c21 developed after the look and tested on the same window, and a 'reproduction' "
                      "with a config that never ran on it (c99). 13 validation configs vs 3 declared trials.",
                   [must("protocol_integrity", "CONFIRMED_ERROR"), must("trials_declared", "NEEDS_REVIEW")],
                   forbid("protocol_integrity", ["PASS"]), ["protocol_integrity"],
                   [{"check": "protocol_integrity", "text": "c21"}])


def protocol_case_clean():
    c = folder("L06_reproductions_only", "strategy: research log of a ranking model\n" + BASE_CONV)
    (c / "protocol.yaml").write_text(PROTOCOL, encoding="utf-8")
    runs = _research_runs()
    i = len(runs)
    extra = [("2026-03-01T10:00:00", "test", "c07", "test"),
             ("2026-03-05T10:00:00", "test", "c07", "reproduction"),
             ("2026-03-06T10:00:00", "test", "c07", "reproduction"),
             ("2026-03-07T10:00:00", ("2012-01-01", "2014-12-31"), "c07", "diagnostic")]
    for ts, w, cfg, p in extra:
        i += 1
        runs.append(_run(ts, i, w, cfg, p))
    write_csv(c / "run_log.csv", runs, RUN_COLS)
    write_expected(c, "One look at the test window by c07; afterwards only reproductions of the same config over it "
                      "and a diagnostic over the training window.",
                   [must("protocol_integrity", "PASS")], forbid("protocol_integrity", ALERTS), [])


def protocol_case_fresh_window():
    c = folder("L07_fresh_window_contaminated", "strategy: research log of a ranking model\n" + BASE_CONV)
    (c / "protocol.yaml").write_text(
        PROTOCOL + "reserved:\n  - {name: fresh_2025, start: '2025-01-01', end: '2025-09-30', single_use: true}\n",
        encoding="utf-8")
    runs = _research_runs()
    i = len(runs)
    extra = [("2026-03-01T10:00:00", "test", "c07", "test"),
             ("2026-04-01T10:00:00", ("2024-07-01", "2025-06-30"), "c07", "diagnostic"),
             ("2026-04-02T10:00:00", ("2024-07-01", "2025-06-30"), "c08", "diagnostic")]
    for ts, w, cfg, p in extra:
        i += 1
        runs.append(_run(ts, i, w, cfg, p))
    write_csv(c / "run_log.csv", runs, RUN_COLS)
    write_expected(c, "The test window was used once, but diagnostic runs over 2024-07 to 2025-06 touched the window "
                      "reserved as the next fresh holdout (fresh_2025) before it was opened (LockIn: diagnostics over "
                      "a later window contaminated the proposed fresh window).",
                   [must("protocol_integrity", "CONFIRMED_ERROR")], forbid("protocol_integrity", ["PASS"]),
                   ["protocol_integrity"], [{"check": "protocol_integrity", "text": "fresh_2025"}])


# ---------------------------------------------------------------------------- family 3: benchmark fit

def benchmark_case(name: str, weighting: str):
    tickers = [f"B{i:02d}" for i in range(1, 21)]
    days = bdays(date(2019, 1, 1), date(2023, 12, 29))
    rng = np.random.default_rng(303)
    n = len(days)
    market = rng.normal(0.0003, 0.010, n)
    prices = {}
    for i, t in enumerate(tickers):
        small = i >= 10
        beta = 0.9 + 0.2 * rng.random()
        alpha = 0.00025 if small else 0.0
        r = beta * market + rng.normal(alpha, 0.012, n)
        p = 20.0 + i
        series = [p]
        for x in r[1:]:
            p *= 1 + x
            series.append(round(p, 4))
        series[0] = round(series[0], 4)
        prices[t] = series
    caps = {t: (10.0 - i) if i < 10 else 0.5 for i, t in enumerate(tickers)}
    rets = {t: [prices[t][k] / prices[t][k - 1] - 1 for k in range(1, n)] for t in tickers}
    held = tickers[:5] + tickers[10:15]
    strat = [sum(rets[t][k] for t in held) / len(held) for k in range(n - 1)]
    ew = [sum(rets[t][k] for t in tickers) / len(tickers) for k in range(n - 1)]
    capsum = sum(caps.values())
    cw = [sum(caps[t] * rets[t][k] for t in tickers) / capsum for k in range(n - 1)]
    bench = cw if weighting == "cap_weighted" else ew
    rules = ("strategy: equal-weight book of ten names out of a twenty-name universe\n"
             f"universe: [{', '.join(tickers)}]\n"
             "sizing: equal_weight\n"
             f"benchmark: {{name: UNIV20, weighting: {weighting}}}\n" + BASE_CONV)
    c = folder(name, rules)
    write_csv(c / "prices.csv", [{"date": d.isoformat(), "ticker": t, "close": prices[t][k], "adjusted": "true"}
                                 for t in tickers for k, d in enumerate(days)], ["date", "ticker", "close", "adjusted"])
    write_csv(c / "universe.csv", [{"ticker": t, "start_date": "2018-01-02", "end_date": ""} for t in tickers],
              ["ticker", "start_date", "end_date"])
    write_csv(c / "returns.csv", [{"date": days[k + 1].isoformat(), "return": round(strat[k], 8)} for k in range(n - 1)],
              ["date", "return"])
    write_csv(c / "benchmark_returns.csv",
              [{"date": days[k + 1].isoformat(), "return": round(bench[k], 8)} for k in range(n - 1)], ["date", "return"])
    if weighting == "cap_weighted":
        write_expected(c, "Equal-weight book compared with a cap-weighted benchmark of the same universe; the smaller "
                          "half of the universe earns ~6%/yr more, so part of the gap is the benchmark choice (LockIn: "
                          "~3 pp/yr of the gap came from comparing an equal-weight book with a cap-weighted index).",
                       [must("benchmark_fit", "NEEDS_REVIEW")], forbid("benchmark_fit", ["PASS"]), [],
                       [{"check": "benchmark_fit", "text": "benchmark-choice"}])
    else:
        write_expected(c, "Equal-weight book compared with the equal-weight benchmark of its own universe.",
                       [must("benchmark_fit", "PASS")], forbid("benchmark_fit", ALERTS), [])


# ---------------------------------------------------------------------------- family 4: dividends

def dividend_case(name: str, planted: bool):
    tickers = ["DV1", "DV2", "DV3", "DV4"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    rng = np.random.default_rng(404)
    ex_dates = [date(2023, 3, 15), date(2023, 6, 15), date(2023, 9, 15), date(2023, 12, 14)]
    raw, divs = {}, []
    for i, t in enumerate(tickers):
        p = 40.0 + 10 * i
        series = []
        for d in days:
            p *= 1 + rng.normal(0.0003, 0.012)
            if t != "DV4" and d in ex_dates:
                amount = round(p * 0.012, 2)
                divs.append({"ticker": t, "ex_date": d.isoformat(), "amount": amount})
                p -= amount
            series.append(round(p, 4))
        raw[t] = series
    adj = {}
    for t in tickers:
        idx = {d: k for k, d in enumerate(days)}
        factor = [1.0] * len(days)
        for dv in divs:
            if dv["ticker"] != t:
                continue
            e = date.fromisoformat(dv["ex_date"])
            if planted and t == "DV2" and e == date(2023, 6, 15):
                continue  # dividend never applied by the vendor
            k = idx[e]
            f = 1 - dv["amount"] / raw[t][k - 1]
            for j in range(k):
                factor[j] *= f
        adj[t] = [round(raw[t][k] * factor[k], 4) for k in range(len(days))]
    if planted:  # DV3: rows loaded before the dividend was applied; the adjusted close stays frozen 4 sessions
        k = days.index(date(2023, 9, 15))
        for j in range(k, k + 4):
            adj["DV3"][j] = adj["DV3"][k - 1]
    c = folder(name, "strategy: dividend-paying equities (no trades)\n" + BASE_CONV)
    write_csv(c / "prices.csv", [{"date": d.isoformat(), "ticker": t, "close": adj[t][k], "adjusted": "true"}
                                 for t in tickers for k, d in enumerate(days)], ["date", "ticker", "close", "adjusted"])
    write_csv(c / "unadjusted_prices.csv", [{"date": d.isoformat(), "ticker": t, "close": raw[t][k]}
                                            for t in tickers for k, d in enumerate(days)], ["date", "ticker", "close"])
    write_csv(c / "dividends.csv", divs, ["ticker", "ex_date", "amount"])
    if planted:
        write_expected(c, "DV2's 2023-06-15 dividend is missing from the adjusted series; DV3's adjusted close stays "
                          "frozen for four sessions from its 2023-09-15 ex-date while the as-traded price moves (LockIn "
                          "paper trading: ex-dividend rows loaded before the vendor applied the dividend froze two "
                          "holdings' prices).",
                       [must("dividend_corporate_actions", "CONFIRMED_ERROR")],
                       forbid("dividend_corporate_actions", ["PASS"]), ["dividend_corporate_actions"],
                       [{"check": "dividend_corporate_actions", "text": "DV2"}])
    else:
        write_expected(c, "Adjusted series consistent with the declared dividends and the as-traded prices.",
                       [must("dividend_corporate_actions", "PASS")], forbid("dividend_corporate_actions", ALERTS), [])


# ---------------------------------------------------------------------------- family 5: liquidity and costs

def _liquidity_sim(prices, days, tickers, cash0, rate, invest=0.95):
    """Monthly full rotation into 3 of 5 names (equal weight); returns trades and final NAV."""
    rebal = first_bdays(days)
    trades, cash, qty = [], cash0, {t: 0 for t in tickers}
    notional_total = 0.0
    for m, d in enumerate(rebal):
        k = days.index(d)
        for t in tickers:
            if qty[t]:
                px = prices[t][k]
                n = qty[t] * px
                com = round(n * rate, 2)
                cash += n - com
                notional_total += n
                trades.append({"timestamp": f"{d.isoformat()}T16:00:00", "ticker": t, "side": "sell",
                               "quantity": qty[t], "price": px, "commission": com})
                qty[t] = 0
        chosen = [tickers[(m + j) % 5] for j in range(3)]
        budget = cash * invest / 3
        for t in chosen:
            px = prices[t][k]
            q = int(budget // px)
            n = q * px
            com = round(n * rate, 2)
            cash -= n + com
            notional_total += n
            qty[t] = q
            trades.append({"timestamp": f"{d.isoformat()}T16:00:00", "ticker": t, "side": "buy",
                           "quantity": q, "price": px, "commission": com})
    nav = cash + sum(qty[t] * prices[t][-1] for t in tickers)
    return trades, nav, notional_total


def liquidity_case(name: str, illiquid: bool):
    tickers = ["LQ1", "LQ2", "LQ3", "LQ4", "LQ5"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    rng = np.random.default_rng(505)
    prices, volume = {}, {}
    for i, t in enumerate(tickers):
        p = 20.0 + 5 * i
        s = []
        for _ in days:
            p *= 1 + rng.normal(0.0008, 0.010)
            s.append(round(p, 2))
        prices[t] = s
        base = 20_000 if (illiquid and t == "LQ5") else 3_000_000
        volume[t] = [int(base * (0.75 + 0.5 * rng.random())) for _ in days]
    cash0 = 1_000_000.0 if illiquid else 100_000.0
    _, nav_gross, notional = _liquidity_sim(prices, days, tickers, cash0, 0.0)
    gross = nav_gross / cash0 - 1
    turnover = notional / cash0
    rate = round((0.6 if illiquid else 0.1) * gross / turnover, 6)
    trades, _, _ = _liquidity_sim(prices, days, tickers, cash0, rate)
    if illiquid:  # the day of one LQ5 buy trades less than the order itself
        lq5_buys = [tr for tr in trades if tr["ticker"] == "LQ5" and tr["side"] == "buy"]
        d0 = date.fromisoformat(lq5_buys[1]["timestamp"][:10])
        volume["LQ5"][days.index(d0)] = 5_000
    for k, tr in enumerate(trades, 1):
        tr["trade_id"] = k
    rules = ("strategy: monthly rotation into three of five names, equal weight\n"
             f"costs: {{commission_rate: {rate}, slippage_rate: 0.0}}\n"
             "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n"
             f"  initial_cash: {int(cash0)}\n")
    c = folder(name, rules)
    write_csv(c / "prices.csv", [{"date": d.isoformat(), "ticker": t, "close": prices[t][k], "volume": volume[t][k],
                                  "adjusted": "true"} for t in tickers for k, d in enumerate(days)],
              ["date", "ticker", "close", "volume", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    if illiquid:
        write_expected(c, f"LQ5 trades about 20,000 shares a day while the book buys about 40% of that per order; on {d0} the order "
                          "is larger than the whole day's volume. Gross return is positive but the declared commission "
                          "consumes 60% of it, so the excess return is gone at 2x declared costs.",
                       [must("liquidity_participation", "CONFIRMED_ERROR"), must("cost_sensitivity", "NEEDS_REVIEW")],
                       forbid("liquidity_participation", ["PASS"]) + forbid("cost_sensitivity", ["PASS"]),
                       ["liquidity_participation"], [{"check": "liquidity_participation", "text": "LQ5"}])
    else:
        write_expected(c, "Every order is below 1% of ADV; declared costs consume about 10% of the gross return, "
                          "so the result survives 3x declared costs.",
                       [must("liquidity_participation", "PASS"), must("cost_sensitivity", "PASS")],
                       forbid("liquidity_participation", ALERTS) + forbid("cost_sensitivity", ALERTS), [])


# ---------------------------------------------------------------------------- family 6: stability, concentration, regimes

def concentration_case():
    tickers = ["CN1", "CN2", "CN3", "CN4", "CN5"]
    days = bdays(date(2023, 1, 2), date(2023, 12, 29))
    rng = np.random.default_rng(606)
    prices = {}
    for t in tickers:
        drift = 0.0036 if t == "CN1" else -0.0006
        p, s = 50.0, []
        for _ in days:
            p *= math.exp(rng.normal(drift, 0.012))
            s.append(round(p, 2))
        prices[t] = s
    rate, cash = 0.001, 100_000.0
    trades = []
    for k, t in enumerate(tickers, 1):
        px = prices[t][0]
        q = int(19_000 // px)
        trades.append({"trade_id": k, "timestamp": f"{days[0].isoformat()}T16:00:00", "ticker": t, "side": "buy",
                       "quantity": q, "price": px, "commission": round(q * px * rate, 2)})
    rules = ("strategy: buy and hold five names\ncosts: {commission_rate: 0.001, slippage_rate: 0.0}\n" + BASE_CONV)
    c = folder("L14_one_name_carries", rules)
    write_csv(c / "prices.csv", [{"date": d.isoformat(), "ticker": t, "close": prices[t][k], "adjusted": "true"}
                                 for t in tickers for k, d in enumerate(days)], ["date", "ticker", "close", "adjusted"])
    write_csv(c / "trades.csv", trades, ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    write_expected(c, "Five names held all year; CN1 more than doubles while the other four drift down: without CN1 "
                      "the book loses money.",
                   [must("stability_and_concentration", "NEEDS_REVIEW")], forbid("stability_and_concentration", ["PASS"]),
                   [], [{"check": "stability_and_concentration", "text": "CN1"}])


def regime_case(name: str, dominant: bool):
    rng = np.random.default_rng(707)
    if dominant:
        months = month_ends(date(2010, 1, 1), date(2024, 12, 31))
        rules = ("strategy: monthly bond allocation with a conditional inverted-curve rule\n"
                 "conditional_rules:\n  - {name: inverted_curve_bond_rule, column: inverted_curve}\n"
                 "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n  periods_per_year: 12\n"
                 "  oos_start: '2022-01-01'\n")
        c = folder(name, rules)
        ins = [m for m in months if m < date(2022, 1, 1)]
        oos = [m for m in months if m >= date(2022, 1, 1)]
        active_in = {ins[k] for k in (5, 26, 47, 68, 89, 110, 131)}  # 7 of 144 in-sample months (~5%)
        active_out = set(oos[:30])  # 30 of 36 out-of-sample months (~83%)
        reg = [{"date": m.isoformat(), "inverted_curve": int(m in active_in or m in active_out)} for m in months]
        rets = [{"date": m.isoformat(), "return": round(float(rng.normal(0.006, 0.03)), 6)} for m in months]
        write_csv(c / "regimes.csv", reg, ["date", "inverted_curve"])
        write_csv(c / "returns.csv", rets, ["date", "return"])
        write_expected(c, "The inverted-curve rule is active in 7 of 144 in-sample months (5%) and 30 of 36 "
                          "out-of-sample months (83%): the out-of-sample result is driven by a rule the in-sample "
                          "period barely tested (LockIn: 5% of in-sample months vs 83% in the test).",
                       [must("conditional_rule_activation", "NEEDS_REVIEW")],
                       forbid("conditional_rule_activation", ["PASS"]), [],
                       [{"check": "conditional_rule_activation", "text": "inverted_curve_bond_rule"}])
    else:
        days = bdays(date(2019, 1, 1), date(2023, 12, 29))
        rules = ("strategy: steady daily strategy with a conditional volatility rule\n"
                 "conditional_rules:\n  - {name: high_vol_rule, column: high_vol}\n" + BASE_CONV)
        c = folder(name, rules)
        (c / "protocol.yaml").write_text("train: {start: '2019-01-01', end: '2022-12-31'}\n"
                                         "test: {start: '2023-01-01', end: '2023-12-31', single_use: true}\n",
                                         encoding="utf-8")
        months = month_ends(date(2019, 1, 1), date(2023, 12, 31))
        reg = [{"date": m.isoformat(), "high_vol": int(k % 5 in (0, 2))} for k, m in enumerate(months)]  # 40%
        rets = [{"date": d.isoformat(), "return": round(float(rng.normal(0.0008, 0.008)), 6)} for d in days]
        write_csv(c / "regimes.csv", reg, ["date", "high_vol"])
        write_csv(c / "returns.csv", rets, ["date", "return"])
        write_expected(c, "Five years of a steady daily series (annual Sharpe about 1.6), no year or day carrying the "
                          "result; the conditional rule is active in 40% of months both in and out of sample.",
                       [must("stability_and_concentration", "PASS"), must("conditional_rule_activation", "PASS")],
                       forbid("stability_and_concentration", ALERTS) + forbid("conditional_rule_activation", ALERTS),
                       [])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fundamentals_case("L01_fundamentals_coverage_drop", drop=True)
    fundamentals_case("L02_fundamentals_coverage_stable", drop=False)
    signals_inputs_case("L03_reserved_window_half_inputs", insufficient=True)
    signals_inputs_case("L04_inputs_sufficient", insufficient=False)
    protocol_case_reused()
    protocol_case_clean()
    protocol_case_fresh_window()
    benchmark_case("L08_equal_weight_vs_cap_weighted", "cap_weighted")
    benchmark_case("L09_equal_weight_vs_equal_weight", "equal_weighted")
    dividend_case("L10_dividend_not_applied_and_frozen", planted=True)
    dividend_case("L11_dividends_consistent", planted=False)
    liquidity_case("L12_illiquid_and_cost_fragile", illiquid=True)
    liquidity_case("L13_liquid_and_cost_robust", illiquid=False)
    concentration_case()
    regime_case("L15_conditional_rule_dominant_oos", dominant=True)
    regime_case("L16_stable_and_regime_balanced", dominant=False)
    print("lesson cases written to", OUT)


if __name__ == "__main__":
    main()
