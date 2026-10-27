"""Independent oracle for the essential computations.

Implements docs/CONVENTIONS.md (sections 1, 2 and 4) WITHOUT reading or importing lockin_validate, and without
pandas or numpy: csv module, row-by-row loops and math only.

What the specification fixes and this file implements on its own:
- NAV series: first point = initial cash, dated on the last price date before the first trade (or the previous
  calendar day); then one point per price date from the first trade until conventions.end_date.
- price = executed price; commission = ``commission`` column if present, otherwise zero (costs are not imputed).
- With a repeated (ticker, date) price, the first row; with no close that day, the last previous close.
- Metrics: simple returns; total return against the initial cash; geometric annual return with 252; Sharpe =
  mean / sample std * sqrt(252); max drawdown negative.
- Statistics: PSR, MinTRL, expected maximum Sharpe, DSR and the Lo (2002) annualisation factor, from the formulas.
"""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist

import yaml

_N = NormalDist()


def _date(s: str) -> date:
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def read_rules(folder: Path) -> dict:
    p = folder / "rules.yaml"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def nav_oracle(folder: str | Path) -> dict:
    folder = Path(folder)
    conv = read_rules(folder).get("conventions") or {}
    cash = float(conv.get("initial_cash", 100000))
    end = _date(str(conv["end_date"])) if conv.get("end_date") else None

    closes: dict[str, dict[date, float]] = {}
    with open(folder / "prices.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("close"):
                continue
            t = row["ticker"].strip().upper()
            d = _date(row["date"])
            closes.setdefault(t, {})
            if d not in closes[t]:
                closes[t][d] = float(row["close"])
    price_dates = sorted({d for series in closes.values() for d in series})

    trades = []
    with open(folder / "trades.csv", encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f)):
            trades.append((row["timestamp"], n, row))
    trades.sort(key=lambda x: (x[0], x[1]))
    first = _date(trades[0][0])

    dates = [d for d in price_dates if d >= first and (end is None or d <= end)]
    if not dates or dates[0] > first:
        dates.insert(0, first)
    earlier = [d for d in price_dates if d < dates[0]]
    date_zero = earlier[-1] if earlier else dates[0] - timedelta(days=1)

    out = [{"date": date_zero, "cash": cash, "positions_value": 0.0, "nav": cash}]
    qty: dict[str, float] = {}
    costs = 0.0
    i = 0
    for d in dates:
        while i < len(trades) and _date(trades[i][0]) == d:
            row = trades[i][2]
            t = row["ticker"].strip().upper()
            q = float(row["quantity"])
            p = float(row["price"])
            com = float(row["commission"]) if row.get("commission") not in (None, "") else 0.0
            if row["side"].strip().lower() in ("buy", "b", "long"):
                cash = cash - q * p - com
                qty[t] = qty.get(t, 0.0) + q
            else:
                cash = cash + q * p - com
                qty[t] = qty.get(t, 0.0) - q
            costs += com
            i += 1
        value = 0.0
        for t, q in qty.items():
            if q == 0 or t not in closes:
                continue
            last = None
            for dd in sorted(closes[t]):
                if dd <= d:
                    last = closes[t][dd]
                else:
                    break
            if last is not None:
                value += q * last
        out.append({"date": d, "cash": cash, "positions_value": value, "nav": cash + value})
    return {"rows": out, "n_trades": len(trades), "total_costs": costs}


def metrics_oracle(navs: list[float], ppy: int = 252) -> dict:
    r = [navs[k] / navs[k - 1] - 1 for k in range(1, len(navs))]
    n = len(r)
    mean = 0.0
    for x in r:
        mean += x
    mean /= n
    acc = 0.0
    for x in r:
        acc += (x - mean) * (x - mean)
    sd = math.sqrt(acc / (n - 1))
    total = navs[-1] / navs[0] - 1
    peak, worst = navs[0], 0.0
    for v in navs:
        if v > peak:
            peak = v
        fall = v / peak - 1
        if fall < worst:
            worst = fall
    return {"total_return": total, "annual_return": (1 + total) ** (ppy / n) - 1,
            "sharpe": mean / sd * math.sqrt(ppy), "max_drawdown": worst, "final_nav": navs[-1]}


# ---------------------------------------------------------------------------- statistics, from the formulas

def moments_oracle(r: list[float]) -> tuple[int, float, float, float, float]:
    T = len(r)
    mu = sum(r) / T
    sd1 = math.sqrt(sum((x - mu) ** 2 for x in r) / (T - 1))
    sd0 = math.sqrt(sum((x - mu) ** 2 for x in r) / T)
    skew = sum(((x - mu) / sd0) ** 3 for x in r) / T
    kurt = sum(((x - mu) / sd0) ** 4 for x in r) / T
    return T, mu, sd1, skew, kurt


def psr_oracle(sr: float, sr_star: float, T: int, skew: float, kurt: float) -> float:
    return _N.cdf((sr - sr_star) * math.sqrt(T - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr * sr))


def expected_max_oracle(var_sr: float, n: int) -> float:
    g = 0.5772156649015329
    return math.sqrt(var_sr) * ((1 - g) * _N.inv_cdf(1 - 1 / n) + g * _N.inv_cdf(1 - 1 / (n * math.e)))


def min_trl_oracle(sr: float, sr_star: float, skew: float, kurt: float, alpha: float = 0.05) -> float:
    z = _N.inv_cdf(1 - alpha)
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr * sr) * (z / (sr - sr_star)) ** 2


def lo_eta_oracle(rho: list[float], q: int) -> float:
    s = 0.0
    for k in range(1, q):
        rk = rho[k - 1] if k - 1 < len(rho) else 0.0
        s += (q - k) * rk
    return q / math.sqrt(q + 2 * s)
