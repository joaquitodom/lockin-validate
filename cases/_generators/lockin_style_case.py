"""Synthetic "lockin-style" case (cases/core/09_lockin_style), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/lockin_style_case.py

Replaces the original case 09, which was derived from real vendor prices that cannot be redistributed. Same
shape and the same intent: a monthly top-N ranking on a quality score with equal weights, delivered as a PARTIAL
package (no available_from in prices, no positions.csv, no costs.csv), like a real strategy owner would. What can
be reviewed must PASS; lookahead and positions_reconciliation must be NOT_EXECUTABLE.

Prices follow a one-factor model (market + idiosyncratic noise); the quality score of each ticker is a persistent
latent value plus monthly noise, observed with the data of the previous session.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from core_cases import DECL_CONV, REVIEW_DATE, case_metrics, firsts_of_period, simulate, trading_days  # noqa: E402

OUT = HERE.parent / "core" / "09_lockin_style"
TICKERS = ["QA01", "QA02", "QA03", "QA04", "QA05", "QA06", "QA07", "QA08", "QA09", "QA10"]
TOP_N = 3
COMMISSION = 0.001
CASH0 = 100_000.0
TOL_TOTAL_RETURN = 0.005  # documented default tolerance of the reviewer (docs/CONVENTIONS.md)


def write_csv(p: Path, rows: list[dict], cols: list[str]) -> None:
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rng = np.random.default_rng(2026)
    dates = trading_days(date(2023, 12, 1), date(2025, 6, 30))
    start, end = date(2024, 1, 2), date(2025, 6, 30)
    market = rng.normal(0.0004, 0.009, len(dates))
    prices: dict[str, dict[date, float]] = {}
    for i, t in enumerate(TICKERS):
        beta = 0.8 + 0.04 * i
        p = 30.0 + 7 * i
        series = {}
        for k, f in enumerate(dates):
            p *= 1 + beta * market[k] + rng.normal(0.0001, 0.011)
            series[f] = round(p, 4)
        prices[t] = series
    period = [f for f in dates if start <= f <= end]
    rebal = firsts_of_period(period, "monthly")
    latent = {t: float(rng.normal(0, 1)) for t in TICKERS}
    scores = {f: {t: round(0.6 * latent[t] + float(rng.normal(0, 1)), 6) for t in TICKERS} for f in rebal}
    sel = {f: [t for t, _ in sorted(scores[f].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]] for f in rebal}
    date_zero = dates[dates.index(rebal[0]) - 1]
    trades, navs, _ = simulate(prices, period, rebal, sel, CASH0, COMMISSION, date_zero=date_zero)
    # construction check (generator side, independent of the tool): the commissions must exceed twice the total
    # return tolerance, otherwise the cost test could not discriminate and PASS would not be the right expectation.
    costs = sum(o["commission"] for o in trades)
    assert costs / CASH0 > 2 * TOL_TOTAL_RETURN, costs / CASH0
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    write_csv(OUT / "prices.csv", [{"date": f.isoformat(), "ticker": t, "close": prices[t][f], "adjusted": "true"}
                                   for f in dates for t in TICKERS], ["date", "ticker", "close", "adjusted"])
    write_csv(OUT / "signals.csv",
              [{"decision_time": f"{f.isoformat()}T09:30:00", "ticker": t, "signal": scores[f][t],
                "data_date": dates[dates.index(f) - 1].isoformat()} for f in rebal for t in TICKERS],
              ["decision_time", "ticker", "signal", "data_date"])
    write_csv(OUT / "trades.csv", [dict(o, trade_id=i + 1) for i, o in enumerate(trades)],
              ["trade_id", "timestamp", "ticker", "side", "quantity", "price", "commission"])
    rules = {
        "strategy": "quality ranking, top 3 of 10, monthly, equal weights (synthetic, lockin-style)",
        "universe": TICKERS,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "signal": {"column": "signal", "order": "desc", "description": "quality score with data of the previous close"},
        "selection": {"top_n": TOP_N},
        "rebalance": {"frequency": "monthly", "timing": "first_day"},
        "sizing": "equal_weight",
        "costs": {"commission_rate": COMMISSION, "slippage_rate": 0.0},
        "conventions": {"initial_cash": CASH0, "valuation": "close", "leverage": False, "short_selling": False,
                        "calendar": "nyse", "review_date": REVIEW_DATE, "end_date": end.isoformat(),
                        "periods_per_year": 252, "sharpe": "arithmetic", "std_ddof": 1, "risk_free_annual": 0.0,
                        "annual_return": "geometric"},
    }
    (OUT / "rules.yaml").write_text(yaml.safe_dump(rules, sort_keys=False), encoding="utf-8")
    m = case_metrics(navs, n_trades=len(trades))
    decl = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in m.items()}
    decl["convention"] = DECL_CONV
    decl["curve"] = [{"date": f.isoformat(), "nav": round(v, 4)} for f, v in navs[::10]]
    (OUT / "declared_results.json").write_text(json.dumps(decl, indent=2), encoding="utf-8")
    (OUT / "version.txt").write_text("lockin-style-quality-0.1 (synthetic)\n", encoding="utf-8")
    passes = ["duplicates", "dates", "stale_prices", "reconstruction", "omitted_costs"]
    must_not = [{"check": c, "status": s} for c in passes for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW", "NOT_EXECUTABLE")]
    exp = {
        "description": "Synthetic lockin-style case (replaces the original case 09, which used vendor prices). Partial "
                       "package: no available_from in prices, no positions.csv, no costs.csv. What can be reviewed "
                       "passes; lookahead and positions_reconciliation are NOT_EXECUTABLE.",
        "origin": "lockin-style",
        "must_include": [{"check": "lookahead", "status": ["NOT_EXECUTABLE"]},
                         {"check": "positions_reconciliation", "status": ["NOT_EXECUTABLE"]},
                         {"check": "results_reconciliation", "status": ["PASS"]}, {"check": "metrics", "status": ["PASS"]},
                         {"check": "rules_vs_implementation", "status": ["PASS"]}],
        "must_not_include": must_not,
        "errors_only_from": [],
        "comment": f"Commissions total {costs / CASH0:.2%} of the initial cash (> 2 x tolerance), so omitted_costs can "
                   "discriminate with and without costs.",
    }
    (OUT / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")
    print("generated 09_lockin_style;", len(trades), "trades; costs", round(costs, 2), "; total return",
          round(m["total_return"], 4), "; sharpe", round(m["sharpe"], 3), "; ok" if math.isfinite(m["sharpe"]) else "")


if __name__ == "__main__":
    main()
