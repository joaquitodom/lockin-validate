"""Adversarial cases (cases/adversarial/), written by an independent reviewer role. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/adversarial_cases.py

Own simulator, written without looking at the core-case simulator. Convention of the declared results (the
"honest" strategy owner of these cases): total_return = final NAV / initial cash - 1, i.e. costs and the
difference between execution price and first-day close DO count in the return.

Each case carries expected.json with what a correct reviewer should produce, fixed BEFORE running the tool.
Ported from the original Spanish generator with the same seeds, the same random-number call order and the same
expected outcomes; only names were translated (see docs/CASE_CHANGES.md).
"""

from __future__ import annotations

import csv
import json
import math
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "adversarial"
TICKERS = ["ALPHA", "BETA", "GAMMA", "DELTA"]
NYSE_HOLIDAYS_2024 = {date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4)}
# BYMA 2024 holidays / non-working days in June-July (2024 decrees): 17, 20 and 21 June, 9 July (and 1 May).
BYMA_NO_SESSION_2024 = {date(2024, 5, 1), date(2024, 6, 17), date(2024, 6, 20), date(2024, 6, 21), date(2024, 7, 9)}


def sessions(start: date, end: date, holidays: set[date]) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def synthetic_prices(dates: list[date], seed: int) -> dict[str, dict[date, float]]:
    rnd = random.Random(seed)
    out = {}
    for k, t in enumerate(TICKERS):
        p = 50.0 + 20 * k
        series = {}
        for f in dates:
            p *= math.exp(rnd.gauss(0.0004 * (k - 1.5), 0.018))
            series[f] = round(p, 2)
        out[t] = series
    return out


def month_firsts(dates: list[date], start: date) -> list[date]:
    seen, out = set(), []
    for f in dates:
        if f < start:
            continue
        if (f.year, f.month) not in seen:
            seen.add((f.year, f.month))
            out.append(f)
    return out


def momentum_signal(prices, dates, f, window=20):
    """Return of the `window` sessions ending on the session BEFORE f (no future information)."""
    i = dates.index(f)
    a, b = dates[i - 1 - window], dates[i - 1]
    return {t: prices[t][b] / prices[t][a] - 1 for t in TICKERS}, b


def future_signal(prices, dates, f, window=20):
    """Return of the next `window` sessions from f: gross future information."""
    i = dates.index(f)
    b = dates[min(i + window, len(dates) - 1)]
    return {t: prices[t][b] / prices[t][f] - 1 for t in TICKERS}, dates[i - 1]


def simulate(prices, dates, rebal, selection, cash0, commission=0.0, slip=0.0, buffer=0.01, extra_trades=None):
    """Own loop. Execution at the close of the rebalance day with slippage (buys pay more, sells receive less)."""
    cash, q = cash0, {}
    trades, navs = [], []
    extra_trades = extra_trades or {}
    for f in dates:
        if f < rebal[0]:
            continue
        if f in rebal:
            sel = selection[f]
            value = cash + sum(n * prices[t][f] for t, n in q.items())
            target = {t: math.floor(value * (1 - buffer) / len(sel) / prices[t][f]) for t in sel}
            moves = []
            for t in sorted(set(q) | set(target)):
                d = target.get(t, 0) - q.get(t, 0)
                if d:
                    moves.append(("sell" if d < 0 else "buy", t, abs(d)))
            moves.sort(key=lambda m: 0 if m[0] == "sell" else 1)
            moves += extra_trades.get(f, [])
            for side, t, n in moves:
                s = 1 if side == "buy" else -1
                px = round(prices[t][f] * (1 + s * slip), 4)
                com = round(n * px * commission, 4)
                cash -= s * n * px + com
                q[t] = q.get(t, 0) + s * n
                trades.append({"timestamp": f"{f.isoformat()}T16:00:00", "ticker": t, "side": side, "quantity": n,
                               "price": px, "commission": com})
            q = {t: n for t, n in q.items() if n != 0}
        navs.append((f, cash + sum(n * prices[t][f] for t, n in q.items())))
    return trades, navs


def write_csv(p: Path, rows, cols):
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build(name, *, seed=1, holidays=NYSE_HOLIDAYS_2024, start=date(2024, 3, 1), end=date(2024, 6, 28),
          first_rebal=date(2024, 4, 1), real_commission=0.0, real_slip=0.0, buffer=0.01, top_n=2,
          rules_costs=None, costs_csv=None, with_commission=True, declared_from_sim=None, declare=None,
          signal="momentum", calendar="nyse", extra_trades=None, fundamentals=None, data_source=None,
          prices_mod=None, availability=True, expected=None, description=""):
    dates = sessions(start, end, holidays)
    prices = synthetic_prices(dates, seed)
    if prices_mod:
        prices_mod(prices, dates)
    rebal = month_firsts(dates, first_rebal)
    sel, sig_rows = {}, []
    for f in rebal:
        sc, fdata = (momentum_signal if signal == "momentum" else future_signal)(prices, dates, f)
        sel[f] = sorted(TICKERS, key=lambda t: (-sc[t], t))[:top_n]
        for t in TICKERS:
            sig_rows.append({"decision_time": f"{f.isoformat()}T09:30:00", "ticker": t, "signal": round(sc[t], 8),
                             "data_date": fdata.isoformat()})
    if fundamentals:
        sig_rows = fundamentals["signals"](rebal)
    trades, navs = simulate(prices, dates, rebal, sel, 100000.0, real_commission, real_slip, buffer, extra_trades)
    # declared results: by default the real simulation; a case can declare another (e.g. gross)
    navs_decl = navs
    if declared_from_sim:
        _, navs_decl = simulate(prices, dates, rebal, sel, 100000.0, buffer=buffer, extra_trades=extra_trades,
                                **declared_from_sim)
    final_nav = navs_decl[-1][1]
    decl = {"total_return": round(final_nav / 100000.0 - 1, 8), "final_nav": round(final_nav, 4),
            "n_trades": len(trades)}
    if declare is not None:
        decl = declare(decl, navs_decl)
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    px_rows = []
    for t in TICKERS:
        for f in dates:
            r = {"date": f.isoformat(), "ticker": t, "close": prices[t][f], "adjusted": "true"}
            if availability:
                r["available_from"] = f"{f.isoformat()}T17:00:00"
            px_rows.append(r)
    write_csv(c / "prices.csv", px_rows, ["date", "ticker", "close", "adjusted"] + (["available_from"] if availability else []))
    cols_tr = ["trade_id", "timestamp", "ticker", "side", "quantity", "price"] + (["commission"] if with_commission else [])
    write_csv(c / "trades.csv", [dict(o, trade_id=i + 1) for i, o in enumerate(trades)], cols_tr)
    cols_sig = ["decision_time", "ticker", "signal", "data_date"] + (["data_source"] if data_source else [])
    write_csv(c / "signals.csv", sig_rows, cols_sig)
    if fundamentals:
        write_csv(c / "fundamentals.csv", fundamentals["rows"], ["ticker", "period_end", "available_from", "score"])
    if costs_csv is not None:
        write_csv(c / "costs.csv", costs_csv, ["item", "value", "unit"])
    conv = {"initial_cash": 100000.0, "valuation": "close", "leverage": False, "short_selling": False,
            "review_date": "2026-10-20", "end_date": end.isoformat(), "periods_per_year": 252,
            "sharpe": "arithmetic", "std_ddof": 1, "risk_free_annual": 0.0, "annual_return": "geometric"}
    if calendar is not None:
        conv["calendar"] = calendar
    rules = {"strategy": "20-session momentum, top 2 of 4, monthly, equal weights", "universe": TICKERS,
             "period": {"start": first_rebal.isoformat(), "end": end.isoformat()},
             "signal": {"column": "signal", "order": "desc"}, "selection": {"top_n": top_n},
             "rebalance": {"frequency": "monthly", "timing": "first_day"}, "sizing": "equal_weight",
             "conventions": conv}
    if rules_costs is not None:
        rules["costs"] = rules_costs
    (c / "rules.yaml").write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (c / "declared_results.json").write_text(json.dumps(decl, indent=2, ensure_ascii=False), encoding="utf-8")
    (c / "version.txt").write_text(f"{name} (adversarial review)\n", encoding="utf-8")
    exp = {"description": description, "origin": "adversarial", **(expected or {})}
    (c / "expected.json").write_text(json.dumps(exp, indent=2, ensure_ascii=False), encoding="utf-8")


def must(check, statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # R00: clean, 10 bps commission included in trades, execution at the close. Measures false positives.
    build("R00_clean", real_commission=0.001, rules_costs={"commission_rate": 0.001, "slippage_rate": 0.0},
          expected={"must_include": [], "must_not_include": [], "errors_only_from": []},
          description="Clean, data from another generator: momentum top 2 of 4, 10 bps commission in trades.")
    # R01: costs declared as zero and absent from every input.
    build("R01_zero_costs_declared", rules_costs={"commission_rate": 0.0, "slippage_rate": 0.0},
          costs_csv=[{"item": "commission", "value": 0, "unit": "bps"}], with_commission=False,
          expected={"must_include": [must("omitted_costs", ["NEEDS_REVIEW", "CONFIRMED_ERROR"])],
                    "must_not_include": [mustnot("omitted_costs", "PASS")], "errors_only_from": ["omitted_costs"]},
          description="100% monthly turnover with zero cost declared in rules and costs.csv: implausible. A reviewer "
                      "cannot conclude 'costs consistent'.")
    # R02: small declared costs (5 bps) omitted from the result.
    build("R02_small_costs_omitted", rules_costs={"commission_rate": 0.0005, "slippage_rate": 0.0},
          costs_csv=[{"item": "commission", "value": 5, "unit": "bps"}], with_commission=False,
          expected={"must_include": [must("omitted_costs", ["NEEDS_REVIEW", "CONFIRMED_ERROR", "NOT_EXECUTABLE"])],
                    "must_not_include": [mustnot("omitted_costs", "PASS")],
                    "errors_only_from": ["omitted_costs", "reconstruction", "results_reconciliation"]},
          description="5 bps declared, trades without commission, gross declared result. The test does not "
                      "discriminate: the honest answer is NEEDS_REVIEW or not conclusive, never PASS.")
    # R03: high commission (0.7% + VAT ~ 0.85%, typical of Argentine retail accounts) correctly declared.
    build("R03_first_day_commission", real_commission=0.0085, buffer=0.03,
          rules_costs={"commission_rate": 0.0085, "slippage_rate": 0.0},
          expected={"must_include": [must("results_reconciliation", ["PASS"]), must("omitted_costs", ["PASS"])],
                    "must_not_include": [mustnot("results_reconciliation", "CONFIRMED_ERROR")], "errors_only_from": []},
          description="Everything correct and declared; total_return = final NAV / initial cash - 1. Tests whether "
                      "the core excludes first-day costs from the return (NAV base after trading).")

    # R04: future information through fundamentals.csv
    def fund_signals(rebal):
        rows = []
        for f in rebal:
            for t in TICKERS:
                rows.append({"decision_time": f"{f.isoformat()}T09:30:00", "ticker": t, "signal": SCORE[(t, f)],
                             "data_date": PERIOD[f].isoformat(), "data_source": "fundamentals"})
        return rows

    global SCORE, PERIOD
    tmp_dates = sessions(date(2024, 3, 1), date(2024, 6, 28), NYSE_HOLIDAYS_2024)
    tmp_px = synthetic_prices(tmp_dates, 1)
    tmp_rebal = month_firsts(tmp_dates, date(2024, 4, 1))
    SCORE, PERIOD = {}, {}
    for f in tmp_rebal:
        sc, _ = momentum_signal(tmp_px, tmp_dates, f)
        for t in TICKERS:
            SCORE[(t, f)] = round(sc[t], 8)
    PERIOD = {tmp_rebal[0]: date(2023, 12, 31), tmp_rebal[1]: date(2024, 3, 31), tmp_rebal[2]: date(2024, 3, 31)}
    fund_rows = []
    for t in TICKERS:
        fund_rows.append({"ticker": t, "period_end": "2023-12-31", "available_from": "2024-03-10T18:00:00", "score": 1})
        # Q1-2024 report published on 10 May, but used in the 1 May decision
        fund_rows.append({"ticker": t, "period_end": "2024-03-31", "available_from": "2024-05-10T18:00:00", "score": 1})
    build("R04_lookahead_fundamentals", fundamentals={"signals": fund_signals, "rows": fund_rows}, data_source=True,
          availability=False,
          expected={"must_include": [must("lookahead", ["CONFIRMED_ERROR"])],
                    "must_not_include": [mustnot("lookahead", "PASS")], "errors_only_from": ["lookahead"]},
          description="The 2024-05-01 decision uses the Q1-2024 report, available only on 2024-05-10. Exercises the "
                      "fundamentals.csv branch that no core case tests.")
    # R05: undeclared future information (signal = return of the next 20 sessions; data_date declared t-1)
    build("R05_undeclared_lookahead", signal="future",
          expected={"must_include": [must("lookahead", ["NEEDS_REVIEW", "CONFIRMED_ERROR", "NOT_EXECUTABLE"])],
                    "must_not_include": [mustnot("lookahead", "PASS")], "errors_only_from": ["lookahead"]},
          description="The signal is the FUTURE 20-session return, but data_date declares the previous session. With "
                      "the declarations alone it cannot be confirmed; a correct reviewer cannot say 'no future "
                      "information': it must raise a hint or limit the conclusion.")
    # R06: undeclared short sale
    build("R06_undeclared_short", extra_trades={date(2024, 4, 1): [("sell", "DELTA", 100)]},
          expected={"must_include": [must("reconstruction", ["CONFIRMED_ERROR"])], "must_not_include": [],
                    "errors_only_from": ["reconstruction", "rules_vs_implementation"]},
          description="Sale of 100 DELTA without holdings on 2024-04-01, with short selling not declared.")
    # R07: undeclared leverage (invests 150%)
    build("R07_undeclared_leverage", buffer=-0.5,
          expected={"must_include": [must("reconstruction", ["CONFIRMED_ERROR"])], "must_not_include": [],
                    "errors_only_from": ["reconstruction", "rules_vs_implementation"]},
          description="Buys for 150% of the capital with leverage=false.")
    # R08: slippage declared and omitted from trades and result
    build("R08_declared_slippage_omitted", rules_costs={"commission_rate": 0.0, "slippage_rate": 0.005},
          with_commission=False,
          expected={"must_include": [must("omitted_costs", ["CONFIRMED_ERROR"])],
                    "must_not_include": [mustnot("omitted_costs", "PASS")],
                    "errors_only_from": ["omitted_costs", "results_reconciliation", "reconstruction"]},
          description="Rules declare 50 bps of slippage; trades at the exact close and a gross result. The result is "
                      "reproduced only without costs: it should be the same finding as core case 04.")

    # R10: 2:1 split not adjusted in prices (adjusted=true declared) with the position open
    def split(prices, dates):
        for f in dates:
            if f >= date(2024, 5, 15):
                for t in TICKERS:
                    prices[t][f] = round(prices[t][f] / 2, 2)
    build("R10_unadjusted_split", prices_mod=split,
          expected={"must_include": [must("@data", ["NEEDS_REVIEW", "CONFIRMED_ERROR"])], "must_not_include": [],
                    "errors_only_from": ["@data"]},
          description="Every ticker falls 50% on 2024-05-15 (2:1 split not adjusted, adjusted=true). Some data check "
                      "should flag the jump.")
    # R11: BYMA data (no session on Argentine holidays, session on 4 July) without a declared calendar
    build("R11_byma_calendar_undeclared", start=date(2024, 5, 1), end=date(2024, 7, 31), first_rebal=date(2024, 6, 3),
          holidays=BYMA_NO_SESSION_2024, calendar=None,
          expected={"must_include": [], "must_not_include": [], "errors_only_from": []},
          description="Clean data from a market with another calendar (BYMA 2024) and no declared calendar, as an "
                      "Argentine client would send it. A confirmed error here is a false positive; the right answer "
                      "is a review item for the undeclared calendar.")
    # R13: declared results with unrecognised names
    build("R13_unrecognised_results",
          declare=lambda d, navs: {"profitability": d["total_return"] + 0.30, "sharpe_ratio": 3.5},
          expected={"must_include": [must("results_reconciliation", ["NOT_EXECUTABLE", "NEEDS_REVIEW"])],
                    "must_not_include": [mustnot("results_reconciliation", "PASS")], "errors_only_from": []},
          description="declared_results.json with keys the tool does not recognise (profitability, sharpe_ratio), "
                      "one of them false. Concluding 'reconciled' would be a false negative.")
    print("generated 12 adversarial cases")


if __name__ == "__main__":
    main()
