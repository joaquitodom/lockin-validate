"""Deterministic generator of the core synthetic battery (cases/core/).

Usage (from the repository root):  uv run python cases/_generators/core_cases.py

Each case is a folder of inputs plus expected.json. Expected outcomes are fixed BY CONSTRUCTION (we know which
problem we planted), never by running the tool under test. Declared results are computed with a simulator of this
file (loop per session), different from the package. This script does NOT import lockin_validate.

Ported from the original Spanish generator of the review core (same seeds, same random-number call order, same
planted problems and expected outcomes; only names were translated). Case 09 of the original battery used real
vendor prices and is replaced by cases/_generators/lockin_style_case.py (fully synthetic).
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "core"

# Generator's own calendar (does NOT import the package): NYSE holidays and closures published by the exchange
# for the years used by the synthetic cases.
NYSE_NO_SESSION = {
    date(2023, 12, 25),
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29), date(2024, 5, 27),
    date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28), date(2024, 12, 25),
    date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18),
    date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
}
REVIEW_DATE = "2026-10-20"


def trading_days(start: date, end: date) -> list[date]:
    if not (date(2023, 12, 1) <= start and end <= date(2025, 7, 31)):
        raise ValueError("the generator calendar only covers 2023-12 to 2025-07")
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in NYSE_NO_SESSION:
            out.append(d)
        d += timedelta(days=1)
    return out


def write_csv(p: Path, rows: list[dict], cols: list[str]) -> None:
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_yaml(p: Path, d: dict) -> None:
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


def firsts_of_period(dates: list[date], frequency: str) -> list[date]:
    seen, out = set(), []
    for f in dates:
        k = (f.year, f.month) if frequency == "monthly" else tuple(f.isocalendar()[:2])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def month_ends(dates: list[date]) -> list[date]:
    out = {}
    for f in dates:
        out[(f.year, f.month)] = f
    return list(out.values())


# ---------------------------------------------------------------------------- case simulator

def simulate(prices: dict[str, dict[date, float]], dates: list[date], rebal: list[date],
             selection: dict[date, list[str]], cash0: float, commission: float, buffer: float = 0.01,
             date_zero: date | None = None):
    """Return trades, NAV per date and holdings per date.

    NAV series as in docs/CONVENTIONS.md: the first point is the initial cash, dated on the session before the first
    rebalance (date_zero); then one point per session from the first rebalance.

    At the close of each rebalance date: value = cash + holdings at close; target per asset = value * (1 - buffer) / N;
    integer quantities (floor); sells first, then buys, all at the close, commission = rate * notional.
    """
    cash = cash0
    q: dict[str, int] = {}
    trades, navs, holdings = [], [], []
    rset = set(rebal)
    active = False
    if date_zero is not None:
        navs.append((date_zero, cash0))
        holdings.append((date_zero, {}))
    for f in dates:
        if f in rset:
            active = True
            sel = selection[f]
            value = cash + sum(n * prices[t][f] for t, n in q.items())
            target = {t: math.floor(value * (1 - buffer) / len(sel) / prices[t][f]) for t in sel}
            sells, buys = [], []
            for t in sorted(set(q) | set(target)):
                d = target.get(t, 0) - q.get(t, 0)
                if d < 0:
                    sells.append((t, -d))
                elif d > 0:
                    buys.append((t, d))
            for side, lst in (("sell", sells), ("buy", buys)):
                for t, n in lst:
                    p = prices[t][f]
                    com = round(n * p * commission, 6)
                    if side == "buy":
                        cash -= n * p + com
                        q[t] = q.get(t, 0) + n
                    else:
                        cash += n * p - com
                        q[t] = q.get(t, 0) - n
                    trades.append({"timestamp": f"{f.isoformat()}T16:00:00", "ticker": t, "side": side, "quantity": n,
                                   "price": p, "commission": com})
            q = {t: n for t, n in q.items() if n != 0}
        if active:
            navs.append((f, cash + sum(n * prices[t][f] for t, n in q.items())))
            holdings.append((f, dict(q)))
    return trades, navs, holdings


def case_metrics(navs: list[tuple[date, float]], ppy: int = 252, n_trades: int = 0) -> dict:
    v = [x for _, x in navs]
    r = [v[i] / v[i - 1] - 1 for i in range(1, len(v))]
    n = len(r)
    mean = sum(r) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1))
    rt = v[-1] / v[0] - 1
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    return {"total_return": rt, "annual_return": (1 + rt) ** (252 / n) - 1, "sharpe": mean / sd * math.sqrt(ppy),
            "max_drawdown": mdd, "n_trades": n_trades, "final_nav": v[-1]}


def base_rules(tickers, top_n, frequency, start, end, commission, cash0, extra_conv=None) -> dict:
    conv = {"initial_cash": cash0, "valuation": "close", "leverage": False, "short_selling": False,
            "calendar": "nyse", "review_date": REVIEW_DATE, "end_date": end.isoformat(),
            "periods_per_year": 252, "sharpe": "arithmetic", "std_ddof": 1, "risk_free_annual": 0.0,
            "annual_return": "geometric"}
    conv.update(extra_conv or {})
    return {
        "strategy": "ranking on signal, top N, equal weights",
        "universe": list(tickers),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "signal": {"column": "signal", "order": "desc", "description": "score computed with data of the previous close"},
        "selection": {"top_n": top_n},
        "rebalance": {"frequency": frequency, "timing": "first_day"},
        "sizing": "equal_weight",
        "costs": {"commission_rate": commission, "slippage_rate": 0.0},
        "conventions": conv,
    }


DECL_CONV = {"periods_per_year": 252, "sharpe": "arithmetic", "std_ddof": 1, "risk_free_annual": 0.0,
             "annual_return": "geometric", "max_drawdown": "nav", "returns": "simple"}


# ---------------------------------------------------------------------------- base synthetic case

class Base:
    """Universe of 8 fictitious assets, 2023-12-01 to 2024-06-28, monthly rebalance, top 3."""

    def __init__(self, seed=11, tickers=("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"), top_n=3,
                 frequency="monthly", start=date(2024, 1, 2), end=date(2024, 6, 28), prices_from=date(2023, 12, 1),
                 commission=0.001, cash0=100_000.0, drift=0.0012, vol=0.012):
        self.rng = np.random.default_rng(seed)
        self.tickers = list(tickers)
        self.top_n, self.frequency, self.start, self.end = top_n, frequency, start, end
        self.commission, self.cash0 = commission, cash0
        self.dates = trading_days(prices_from, end)
        self.prices: dict[str, dict[date, float]] = {}
        self.ohlc: dict[str, dict[date, tuple]] = {}
        for i, t in enumerate(self.tickers):
            p = 40 + 15 * i
            series, ohlc = {}, {}
            for f in self.dates:
                p = p * (1 + drift + vol * self.rng.standard_normal())
                c = round(p, 2)
                o = round(c * (1 + 0.003 * self.rng.standard_normal()), 2)
                h = round(max(o, c) * (1 + abs(0.004 * self.rng.standard_normal())), 2)
                lo = round(min(o, c) * (1 - abs(0.004 * self.rng.standard_normal())), 2)
                series[f] = c
                ohlc[f] = (o, h, lo, c)
            self.prices[t], self.ohlc[t] = series, ohlc
        self.period_dates = [f for f in self.dates if start <= f <= end]
        self.rebal = firsts_of_period(self.period_dates, frequency)
        self.scores = {f: {t: round(float(self.rng.uniform(0, 100)), 3) for t in self.tickers} for f in self.rebal}

    def freeze(self, t: str, from_idx: int, n: int) -> None:
        fs = self.dates[from_idx:from_idx + n]
        c = self.prices[t][fs[0]]
        for f in fs:
            self.prices[t][f] = c
            self.ohlc[t][f] = (c, c, c, c)

    def selection(self, top_n: int | None = None) -> dict[date, list[str]]:
        n = top_n or self.top_n
        return {f: [t for t, _ in sorted(self.scores[f].items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
                for f in self.rebal}

    def previous(self, f: date) -> date:
        return self.dates[self.dates.index(f) - 1]

    def price_rows(self, availability=True):
        rows = []
        for f in self.dates:
            for t in self.tickers:
                o, h, lo, c = self.ohlc[t][f]
                c = self.prices[t][f]
                row = {"date": f.isoformat(), "ticker": t, "open": o, "high": max(h, c, o), "low": min(lo, c, o),
                       "close": c, "volume": 100000 + self.dates.index(f), "adjusted": "true"}
                if availability:
                    row["available_from"] = f"{f.isoformat()}T17:00:00"
                rows.append(row)
        return rows

    def signal_rows(self, data_date_func=None):
        rows = []
        for f in self.rebal:
            for t in self.tickers:
                fd = data_date_func(f, t) if data_date_func else self.previous(f)
                rows.append({"decision_time": f"{f.isoformat()}T09:30:00", "ticker": t, "signal": self.scores[f][t],
                             "data_date": fd.isoformat()})
        return rows

    def write(self, folder: Path, *, trades, navs, holdings, declared, rules, expected, price_rows=None,
              signal_rows=None, with_commission=True, costs_csv=True, positions=True, version="1.0") -> None:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        cols_px = ["date", "ticker", "open", "high", "low", "close", "volume", "adjusted", "available_from"]
        pr = price_rows if price_rows is not None else self.price_rows()
        if pr and "available_from" not in pr[0]:
            cols_px.remove("available_from")
        write_csv(folder / "prices.csv", pr, cols_px)
        write_csv(folder / "signals.csv", signal_rows if signal_rows is not None else self.signal_rows(),
                  ["decision_time", "ticker", "signal", "data_date"])
        cols_tr = ["trade_id", "timestamp", "ticker", "side", "quantity", "price"] + (
            ["commission"] if with_commission else [])
        write_csv(folder / "trades.csv", [dict(o, trade_id=i + 1) for i, o in enumerate(trades)], cols_tr)
        if positions:
            rows = []
            hold = dict(holdings)
            for f in month_ends([f for f, _ in navs]):
                for t, n in sorted(hold[f].items()):
                    rows.append({"date": f.isoformat(), "ticker": t, "quantity": n})
            write_csv(folder / "positions.csv", rows, ["date", "ticker", "quantity"])
        if costs_csv:
            write_csv(folder / "costs.csv",
                      [{"item": "commission", "value": round(rules["costs"]["commission_rate"] * 10000, 6), "unit": "bps"},
                       {"item": "slippage", "value": 0, "unit": "bps"}], ["item", "value", "unit"])
        write_yaml(folder / "rules.yaml", rules)
        (folder / "declared_results.json").write_text(json.dumps(declared, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")
        (folder / "version.txt").write_text(version + "\n", encoding="utf-8")
        (folder / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")


def declared_results(navs, trades, conv=DECL_CONV, curve=True, **override) -> dict:
    m = case_metrics(navs, n_trades=len(trades))
    m.update(override)
    d = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in m.items()}
    d["convention"] = conv
    if curve:
        d["curve"] = [{"date": f.isoformat(), "nav": round(v, 4)} for f, v in navs[::10]]
    return d


ALL = ["schema_and_types", "duplicates", "dates", "essential_fields", "coverage", "trade_before_signal",
       "signal_data_after_decision", "stale_prices", "reconstruction", "positions_reconciliation",
       "results_reconciliation", "lookahead", "omitted_costs", "metrics", "rules_vs_implementation"]


def E(check, status="CONFIRMED_ERROR"):
    return {"check": check, "status": [status]}


def expected(description, must, must_not=None, allowed_errors=None, only=True, passes=None, comment=None,
             prediction_note=None, text_must=None) -> dict:
    must_not = list(must_not or [])
    for c in passes or []:
        must_not += [{"check": c, "status": s} for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW", "NOT_EXECUTABLE")]
    out = {"description": description, "origin": "core", "must_include": must, "must_not_include": must_not}
    if only:
        out["errors_only_from"] = sorted({d["check"] for d in must if "CONFIRMED_ERROR" in d["status"]}
                                         | set(allowed_errors or []))
    if comment:
        out["comment"] = comment
    if prediction_note:
        out["prediction_note"] = prediction_note
    if text_must:
        out["text_must_contain"] = text_must
    return out


def nm(d: dict) -> dict:
    """must_not entry helper: {check, status} with a single status string."""
    return {"check": d["check"], "status": d["status"][0]}


# ---------------------------------------------------------------------------- cases

def base_case(b: Base, top_n=None):
    sel = b.selection(top_n)
    return simulate(b.prices, b.period_dates, b.rebal, sel, b.cash0, b.commission, date_zero=b.previous(b.rebal[0]))


def c01(root: Path):
    b = Base()
    trades, navs, hold = base_case(b)
    b.write(root / "01_clean", trades=trades, navs=navs, holdings=hold, declared=declared_results(navs, trades),
            rules=base_rules(b.tickers, 3, "monthly", b.start, b.end, b.commission, b.cash0),
            expected=expected("Everything correct: measures false positives. Every original check must PASS.",
                              [E(c, "PASS") for c in ALL], passes=ALL))


def c02(root: Path):
    b = Base(seed=12)
    trades, navs, hold = base_case(b)
    pr = b.price_rows()
    dup_exact = dict(pr[40])
    dup_conflict = dict(pr[85])
    dup_conflict["close"] = round(float(dup_conflict["close"]) * 1.05, 2)
    dup_conflict["high"] = max(dup_conflict["high"], dup_conflict["close"])
    pr = pr[:41] + [dup_exact] + pr[41:86] + [dup_conflict] + pr[86:]
    b.write(root / "02_duplicates", trades=trades, navs=navs, holdings=hold, declared=declared_results(navs, trades),
            price_rows=pr, rules=base_rules(b.tickers, 3, "monthly", b.start, b.end, b.commission, b.cash0),
            expected=expected("Two duplicated rows in prices.csv (one identical, one with a different close, both AFTER "
                              "the original and before the traded period).",
                              [E("duplicates")], passes=["reconstruction", "results_reconciliation", "metrics",
                                                         "rules_vs_implementation", "stale_prices"]))


def c03(root: Path):
    b = Base(seed=13)
    sel = b.selection()
    # ticker that ENTERS at the third rebalance: its price is frozen for 12 sessions around that date
    f3 = b.rebal[2]
    enters = sorted(set(sel[f3]) - set(sel[b.rebal[1]]))[0]
    i = b.dates.index(f3)
    b.freeze(enters, i - 5, 12)
    trades, navs, hold = base_case(b)
    b.write(root / "03_stale_prices", trades=trades, navs=navs, holdings=hold, declared=declared_results(navs, trades),
            rules=base_rules(b.tickers, 3, "monthly", b.start, b.end, b.commission, b.cash0),
            expected=expected(f"Price of {enters} frozen for 12 sessions from {b.dates[i - 5]}; the strategy buys it on "
                              f"{f3} at that stale price.", [E("stale_prices")],
                              passes=["duplicates", "results_reconciliation", "rules_vs_implementation"]))


def c04(root: Path):
    b = Base(seed=14, commission=0.0025)
    sel = b.selection()
    trades, navs, hold = simulate(b.prices, b.period_dates, b.rebal, sel, b.cash0, 0.0,
                                  date_zero=b.previous(b.rebal[0]))
    b.write(root / "04_omitted_costs", trades=trades, navs=navs, holdings=hold, declared=declared_results(navs, trades),
            with_commission=False, rules=base_rules(b.tickers, 3, "monthly", b.start, b.end, 0.0025, b.cash0),
            expected=expected(
                "The rules declare 25 bps of commission, the trades carry no commission and the declared result was "
                "computed without costs.",
                [E("omitted_costs"), E("reconstruction", "PASS"), E("results_reconciliation", "PASS"),
                 E("metrics", "PASS")],
                only=True, allowed_errors=[],
                passes=["duplicates", "dates", "stale_prices", "lookahead", "reconstruction", "results_reconciliation",
                        "metrics", "rules_vs_implementation", "positions_reconciliation"],
                comment=(
                    "Derived from the planted problem (one problem -> one error). By docs/CONVENTIONS.md 1.3 the main "
                    "reconstruction uses the trades as delivered (no commission), so: reconstruction PASS (no negative "
                    "cash with those trades), results_reconciliation PASS (the declared result is the one of those "
                    "trades), metrics PASS (same series). The problem is that the declared costs are neither in the "
                    "trades nor in the result: omitted_costs CONFIRMED_ERROR, because the declared return is reproduced "
                    "only in the no-cost scenario. Derived effect expected INSIDE that finding, not as a separate "
                    "error: with 25 bps imputed on trades sized without costs and a 1% buffer, cash turns negative in "
                    "the declared-cost scenario."),
                prediction_note=("2026-10-21: written when the case was redesigned (review cycle 2), before running "
                                 "the tool on the regenerated case."),
                text_must=[{"check": "omitted_costs", "text": "Consequence of the same problem"}]))


def c05(root: Path):
    b = Base(seed=15)
    trades, navs, hold = base_case(b)
    pr = b.price_rows()
    # Saturday 2024-03-16 for CCC with Friday's close; and a row in 2027 for DDD
    fri = date(2024, 3, 15)
    c = b.prices["CCC"][fri]
    pr.append({"date": "2024-03-16", "ticker": "CCC", "open": c, "high": c, "low": c, "close": c, "volume": 1,
               "adjusted": "true", "available_from": "2024-03-16T17:00:00"})
    c2 = b.prices["DDD"][b.end]
    pr.append({"date": "2027-01-04", "ticker": "DDD", "open": c2, "high": c2, "low": c2, "close": c2, "volume": 1,
               "adjusted": "true", "available_from": "2027-01-04T17:00:00"})
    b.write(root / "05_impossible_dates", trades=trades, navs=navs, holdings=hold,
            declared=declared_results(navs, trades, curve=False), price_rows=pr,
            rules=base_rules(b.tickers, 3, "monthly", b.start, b.end, b.commission, b.cash0),
            expected=expected("One price row on a Saturday (2024-03-16) and one in the future (2027-01-04).",
                              [E("dates")], passes=["duplicates", "stale_prices", "rules_vs_implementation",
                                                    "positions_reconciliation"]))


def c06(root: Path):
    b = Base(seed=16)
    trades, navs, hold = base_case(b)
    f_bad = b.rebal[3]
    sig = b.signal_rows(lambda f, t: f if f == f_bad else b.previous(f))
    rules = base_rules(b.tickers, 3, "monthly", b.start, b.end, b.commission, b.cash0)
    b.write(root / "06_lookahead", trades=trades, navs=navs, holdings=hold, declared=declared_results(navs, trades),
            signal_rows=sig, rules=rules,
            expected=expected(f"At the {f_bad} rebalance the signals (decision 09:30) use the close of that same day, "
                              "available only at 17:00.", [E("lookahead")],
                              passes=["signal_data_after_decision", "rules_vs_implementation", "results_reconciliation",
                                      "duplicates"]))
    # variant without availability timestamps: the check must be NOT_EXECUTABLE
    b.write(root / "06b_lookahead_without_availability", trades=trades, navs=navs, holdings=hold,
            declared=declared_results(navs, trades), signal_rows=sig, price_rows=b.price_rows(availability=False),
            rules=rules,
            expected=expected("Same case as 06 but prices.csv has no available_from and there are no fundamentals: "
                              "future information cannot be proven.", [E("lookahead", "NOT_EXECUTABLE")],
                              must_not=[nm(E("lookahead")), nm(E("lookahead", "PASS"))],
                              passes=["rules_vs_implementation", "results_reconciliation"]))


def c07(root: Path):
    b = Base(seed=17, drift=0.0018)
    trades, navs, hold = base_case(b)
    m = case_metrics(navs, ppy=365, n_trades=len(trades))
    b.write(root / "07_metric_error", trades=trades, navs=navs, holdings=hold,
            declared=declared_results(navs, trades, sharpe=round(m["sharpe"], 6)),
            rules=base_rules(b.tickers, 3, "monthly", b.start, b.end, b.commission, b.cash0),
            expected=expected("Declared convention 252 periods per year, but the declared Sharpe was annualised with "
                              "sqrt(365).", [E("metrics"), E("results_reconciliation", "NEEDS_REVIEW")],
                              must_not=[nm(E("results_reconciliation"))],
                              passes=["reconstruction", "omitted_costs", "rules_vs_implementation",
                                      "positions_reconciliation"]))


def c08(root: Path):
    b = Base(seed=18)
    trades, navs, hold = base_case(b, top_n=3)
    b.write(root / "08_rules_vs_implementation", trades=trades, navs=navs, holdings=hold,
            declared=declared_results(navs, trades),
            rules=base_rules(b.tickers, 5, "monthly", b.start, b.end, b.commission, b.cash0),
            expected=expected("rules.yaml says monthly top 5 with equal weights; the trades buy the top 3.",
                              [E("rules_vs_implementation")],
                              passes=["results_reconciliation", "metrics", "omitted_costs", "duplicates"]))


def c10(root: Path):
    """Unrelated to LockIn: 3 invented assets, weekly rebalance top 2, cash 50,000."""
    b = Base(seed=101, tickers=("WHEAT", "COPPER", "BOND"), top_n=2, frequency="weekly", start=date(2025, 2, 3),
             end=date(2025, 4, 30), prices_from=date(2025, 1, 15), commission=0.0005, cash0=50_000.0,
             drift=0.0008, vol=0.009)
    trades, navs, hold = base_case(b)
    folder = root / "10_independent"
    decl = declared_results(navs, trades)
    decl["max_drawdown"] = abs(decl["max_drawdown"])  # declared as positive: convention, not an error
    b.write(folder, trades=trades, navs=navs, holdings=hold, declared=decl,
            rules=base_rules(b.tickers, 2, "weekly", b.start, b.end, b.commission, b.cash0),
            expected={}, version="independent-1")
    # planted error: one declared position at the end of March differs by 7 units
    p = folder / "positions.csv"
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    target = next(r for r in rows if r["date"].startswith("2025-03"))
    target["quantity"] = str(int(target["quantity"]) + 7)
    write_csv(p, rows, ["date", "ticker", "quantity"])
    (folder / "expected.json").write_text(json.dumps(expected(
        f"Unrelated to LockIn. Planted error: declared position of {target['ticker']} on {target['date']} with 7 extra "
        "units. Max drawdown declared as a positive number (convention, not an error).",
        [E("positions_reconciliation"), E("omitted_costs", "NEEDS_REVIEW")],
        must_not=[nm(E("omitted_costs", "PASS")), nm(E("omitted_costs"))],
        comment=("omitted_costs: 5 bps over a turnover of ~9 times the capital add up to ~0.47% of capital, less than "
                 "the total return tolerance (0.5 pp): the test cannot tell with and without costs apart, and by the "
                 "conclusion rule (docs/CONVENTIONS.md section 5) it must be NEEDS_REVIEW, not PASS."),
        prediction_note="2026-10-21, review cycle 2, before running the tool on the regenerated case.",
        passes=["duplicates", "dates", "stale_prices", "reconstruction", "results_reconciliation", "metrics",
                "rules_vs_implementation", "lookahead"]), indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (c01, c02, c03, c04, c05, c06, c07, c08, c10):
        f(OUT)
        print("generated", f.__name__)


if __name__ == "__main__":
    main()
