"""Liquidity and cost sensitivity (0.2.0, family 5).

Check ids:
  liquidity_participation  participation rate per trade = |quantity| / ADV (mean volume of the previous
                           conventions.adv_window sessions, default 20); above conventions.max_participation (default
                           10%) is a review item; an order larger than the whole volume of its day is a CONFIRMED_ERROR
                           (it cannot have been filled that day at that size). A square-root impact estimate
                           Y x sigma_daily x sqrt(Q / ADV) (Y = conventions.impact_coefficient, default 1) is reported as
                           context, never as a finding on its own.
  cost_sensitivity         break-even cost per unit of turnover (the cost per traded unit of notional that sets the
                           excess return to zero) and full reconstructions at 1x, 2x and 3x the declared costs.

Literature, honestly: Almgren and Chriss (2001) is the optimal-execution framework (with linear temporary impact);
the square-root law of impact is an empirical regularity (Almgren, Thum, Hauptmann and Li 2005 estimate an exponent
of about 0.6; Toth et al. 2011 and Bouchaud et al. 2018 document about 0.5). The coefficient Y is of order one and
varies by market and period: the estimate is an order of magnitude, not a measurement of the strategy's costs.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .. import metrics
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from ..reconstruction import Conventions, Reconstruction, reconstruct
from . import missing_inputs, not_executable
from .benchmark import return_series
from .strategy import declared_costs

BLOCK = "strategy"


def check_liquidity(pkg: Package, res: AuditResult) -> None:
    title = "Participation in traded volume"
    miss = pkg.missing("liquidity_participation")
    if miss:
        missing_inputs(res, "liquidity_participation", BLOCK, title, miss)
        return
    win = int(pkg.conv("adv_window", 20))
    max_p = float(pkg.conv("max_participation", 0.10))
    y = float(pkg.conv("impact_coefficient", 1.0))
    px = pkg.df("prices").dropna(subset=["date", "ticker"]).sort_values(["ticker", "date", "row"])
    px = px.drop_duplicates(["ticker", "date"], keep="first")
    by_t = {}
    for t, g in px.groupby("ticker"):
        dates = list(g["date"].dt.date)
        close = g["close"].to_numpy(dtype=float)
        rets = np.concatenate([[np.nan], close[1:] / close[:-1] - 1])
        by_t[t] = (dates, g["volume"].to_numpy(dtype=float), rets, {d: i for i, d in enumerate(dates)})
    tr = pkg.df("trades").dropna(subset=["timestamp", "ticker", "quantity", "price"])
    day_qty: dict[tuple[str, Any], float] = {}
    for r in tr.itertuples():
        k = (r.ticker, r.timestamp.date())
        day_qty[k] = day_qty.get(k, 0.0) + abs(float(r.quantity))
    rows, over_day, unmeasured = [], [], 0
    impact_cost = 0.0
    notional = 0.0
    unmeasured_notional = 0.0
    unmeasured_rows: list[dict[str, Any]] = []
    for r in tr.itertuples():
        d = r.timestamp.date()
        q = abs(float(r.quantity))
        n = q * float(r.price)
        notional += n
        if r.ticker not in by_t or d not in by_t[r.ticker][3]:
            unmeasured += 1
            unmeasured_notional += n
            unmeasured_rows.append({"row": int(r.row), "date": d, "ticker": r.ticker, "quantity": q,
                                    "why": "no price row that day"})
            continue
        dates, vol, rets, idx = by_t[r.ticker]
        i = idx[d]
        prev = vol[max(0, i - win):i]
        prev = prev[np.isfinite(prev)]
        if len(prev) < 5 or prev.mean() <= 0:
            unmeasured += 1
            unmeasured_notional += n
            unmeasured_rows.append({"row": int(r.row), "date": d, "ticker": r.ticker, "quantity": q,
                                    "why": f"{len(prev)} previous sessions with volume (5 needed)"})
            continue
        adv = float(prev.mean())
        # participation of the ticker-day total: child fills of one parent order are judged together
        part = day_qty[(r.ticker, d)] / adv
        rr = rets[max(1, i - 60):i]
        rr = rr[np.isfinite(rr)]
        sigma = float(np.std(rr, ddof=1)) if len(rr) >= 20 else float("nan")
        imp = y * sigma * math.sqrt(part) if math.isfinite(sigma) else float("nan")
        if math.isfinite(imp):
            impact_cost += imp * n
        row = {"row": int(r.row), "date": d, "ticker": r.ticker, "quantity": q,
               "day_quantity": day_qty[(r.ticker, d)], "adv": round(adv, 1), "participation": round(part, 4), "day_volume": vol[i] if np.isfinite(vol[i]) else None,
               "impact_estimate": round(imp, 5) if math.isfinite(imp) else None}
        rows.append(row)
        dv = vol[i]
        if np.isfinite(dv) and day_qty[(r.ticker, d)] > dv:
            over_day.append({**row, "day_traded_by_strategy": day_qty[(r.ticker, d)]})
    if not rows:
        not_executable(res, "liquidity_participation", BLOCK, title,
                       f"no trade has a volume history of at least 5 sessions ({unmeasured} trades unmeasured)")
        return
    seen_days: set[tuple[str, Any]] = set()
    high = []
    for x in sorted(rows, key=lambda x: -x["participation"]):
        if x["participation"] > max_p and (x["ticker"], x["date"]) not in seen_days:
            seen_days.add((x["ticker"], x["date"]))
            high.append(x)
    seen_days = set()
    over_day = [x for x in over_day if (x["ticker"], x["date"]) not in seen_days
                and not seen_days.add((x["ticker"], x["date"]))]
    min_cov = float(pkg.conv("min_volume_coverage", 0.90))
    coverage = 1 - unmeasured_notional / notional if notional else 0.0
    cap = float(pkg.conv("initial_cash", 100000.0)) or 1.0
    ctx = {"trades_measured": len(rows), "trades_unmeasured": unmeasured,
           "measured_notional_share": round(coverage, 4),
           "max_participation": max(x["participation"] for x in rows),
           "median_participation": float(np.median([x["participation"] for x in rows])),
           "impact_cost_estimate": round(impact_cost, 2), "impact_over_capital": round(impact_cost / cap, 6),
           "impact_per_unit_notional": round(impact_cost / notional, 6) if notional else None,
           "impact_coefficient": y}
    res.metrics["liquidity_participation"] = ctx
    proc = (f"ADV = mean volume of the {win} previous sessions of the ticker (at least 5; conventions.adv_window); "
            "participation = |quantity traded by the strategy in the ticker that day| / ADV (fills of the same day "
            f"are added, so a sliced order is judged as a whole), review above {max_p:.0%} "
            "(conventions.max_participation); trades without a volume history are unmeasured and below "
            f"{min_cov:.0%} of notional measured (conventions.min_volume_coverage) there is no PASS. An order "
            "is impossible as filled when the strategy's quantity of the day exceeds the day's volume. Context: "
            f"square-root impact Y sigma sqrt(Q / ADV), Y = {y:g}, sigma = std of the previous 60 daily returns "
            "(Almgren et al. 2005; Toth et al. 2011): an order of magnitude only.")
    ctx_txt = (f" Square-root impact estimate (context, not a measurement): {impact_cost:,.0f} in total, "
               f"{impact_cost / cap:.2%} of the initial capital.")
    ins = ["trades", "prices"]
    if over_day:
        res.add("liquidity_participation", BLOCK, CONFIRMED_ERROR,
                f"Orders larger than the whole day's volume ({len(over_day)}: "
                + ", ".join(sorted({f"{x['ticker']} {x['date']}" for x in over_day})[:4]) + ")",
                "The strategy traded more shares of these tickers on these days than the market traded in total: "
                "those fills cannot have happened at that size and price." + ctx_txt, over_day, proc,
                action="Cap orders at a fraction of volume and spread large orders over several days; rerun.",
                priority="high", inputs=ins)
    if unmeasured:
        st = NEEDS_REVIEW if coverage < min_cov else INFO
        res.add("liquidity_participation", BLOCK, st,
                f"Volume missing for {unmeasured} of {unmeasured + len(rows)} trades ({1 - coverage:.0%} of notional)",
                "These trades cannot be compared with traded volume: "
                + ("too much of the notional is unmeasured to conclude on liquidity." if st == NEEDS_REVIEW else
                   f"not an alert, more than {min_cov:.0%} of the notional is measured.")
                + " Volume must be consolidated volume in shares (docs/INPUT_SPEC.md).",
                unmeasured_rows, proc, action="Deliver volume for every traded ticker and date.",
                priority="medium", inputs=ins)
    if high:
        res.add("liquidity_participation", BLOCK, NEEDS_REVIEW,
                f"{len(high)} ticker-days above {max_p:.0%} of ADV (max {ctx['max_participation']:.0%}; "
                + ", ".join(sorted({x['ticker'] for x in high})) + ")",
                "Orders of this size move the price against the strategy; the backtest assumes they fill at the "
                "close." + ctx_txt, sorted(high, key=lambda x: -x["participation"]), proc,
                action="Model market impact or reduce the size; check capacity at the intended capital.",
                priority="high" if ctx["max_participation"] > 0.25 else "medium", inputs=ins)
    if not over_day and not high and coverage >= min_cov:
        scope = (f"Every trade-day below {max_p:.0%} of ADV" if not unmeasured else
                 f"All {len(rows)} measured trades (of {len(rows) + unmeasured}; {coverage:.0%} of notional) below "
                 f"{max_p:.0%} of ADV")
        res.add("liquidity_participation", BLOCK, PASS, scope,
                f"{len(rows)} trades measured, maximum participation of a ticker-day "
                f"{ctx['max_participation']:.2%}." + ctx_txt,
                [ctx] + sorted(rows, key=lambda x: -x["participation"])[:5], proc, inputs=ins)


def _scenario(pkg: Package, base: Conventions, com: float, slip: float) -> float | None:
    c = Conventions(**{**base.__dict__, "commission_rate": com, "slippage_rate": slip, "impute_costs": True,
                       "use_trade_commissions": False})
    try:
        return metrics.total_return(reconstruct(pkg, c, log=False).nav)
    except ValueError:
        return None


def check_cost_sensitivity(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Sensitivity of the result to trading costs"
    miss = pkg.missing("cost_sensitivity")
    if miss or rec is None:
        missing_inputs(res, "cost_sensitivity", BLOCK, title, miss or ["reconstruction"])
        return
    base = Conventions.from_package(pkg)
    cap = float(base.initial_cash) or 1.0
    gross = _scenario(pkg, base, 0.0, 0.0)
    if gross is None:
        not_executable(res, "cost_sensitivity", BLOCK, title, "the no-cost scenario could not be reconstructed")
        return
    turnover = rec.total_notional / cap
    hurdle, hurdle_src = 0.0, "zero"
    b = return_series(pkg.df("benchmark_returns"))
    if b is not None and len(rec.dates) > 1:
        sel = b[(b.index > rec.dates[0]) & (b.index <= rec.dates[-1])]
        if len(sel):
            hurdle, hurdle_src = float(np.prod(1 + sel.to_numpy()) - 1), "benchmark_returns.csv over the same dates"
    com, slip, src = declared_costs(pkg)
    tr = pkg.df("trades")
    if (com is None and slip is None) and "commission" in tr.columns and tr["commission"].notna().any():
        o = tr.dropna(subset=["quantity", "price"])
        n = float((o["quantity"].abs() * o["price"]).sum())
        com, slip, src = (float(o["commission"].fillna(0).sum()) / n if n else 0.0), 0.0, "commissions in trades.csv"
    unit = (com or 0.0) + (slip or 0.0)
    be = (gross - hurdle) / turnover if turnover > 0 else float("inf")
    ev: dict[str, Any] = {"gross_total_return": round(gross, 6), "hurdle": round(hurdle, 6), "hurdle_source": hurdle_src,
                          "turnover": round(turnover, 4), "break_even_cost_per_unit_turnover": round(be, 6)
                          if math.isfinite(be) else None, "break_even_bps": round(be * 1e4, 1) if math.isfinite(be)
                          else None, "declared_cost_per_unit": unit, "declared_source": src}
    proc = ("Break-even cost = (gross total return - hurdle) / turnover, turnover = traded notional / initial cash "
            f"(linear approximation; hurdle = {hurdle_src}). Scenarios: full reconstructions from the initial cash with "
            "k x the declared commission and slippage imputed on every trade (k = 1, 2, 3; commissions of trades.csv "
            "replaced). Novy-Marx and Velikov (2016) for why anomalies are judged net of costs.")
    ins = ["trades", "prices", "rules", "costs"]
    res.metrics["cost_sensitivity"] = ev
    if turnover <= 0:
        not_executable(res, "cost_sensitivity", BLOCK, title, "no traded notional")
        return
    if gross <= hurdle:
        res.add("cost_sensitivity", BLOCK, INFO, "No gross excess return to protect from costs",
                f"Gross total return {gross:+.2%} vs hurdle {hurdle:+.2%} ({hurdle_src}) before any cost.", [ev], proc,
                inputs=ins)
        return
    if unit <= 0:
        res.add("cost_sensitivity", BLOCK, INFO,
                f"Break-even cost {be * 1e4:.0f} bps per unit of turnover; no declared costs to scale",
                f"Gross total return {gross:+.2%}, turnover {turnover:.1f}x the capital: any cost above {be * 1e4:.0f} bps "
                "of traded notional removes the excess return. Zero costs are reviewed by omitted_costs.", [ev], proc,
                inputs=ins)
        return
    sc = {k: _scenario(pkg, base, k * (com or 0.0), k * (slip or 0.0)) for k in (1, 2, 3)}
    ev.update({f"total_return_{k}x_costs": (round(v, 6) if v is not None else None) for k, v in sc.items()})
    txt = (f"Gross {gross:+.2%}; with 1x / 2x / 3x the declared costs ({unit * 1e4:g} bps per unit of notional, {src}): "
           + " / ".join(f"{v:+.2%}" if v is not None else "n/a" for v in sc.values())
           + f"; hurdle {hurdle:+.2%}. Break-even cost {be * 1e4:.0f} bps per unit of turnover ({turnover:.1f}x).")
    if sc[1] is not None and sc[1] <= hurdle:
        res.add("cost_sensitivity", BLOCK, NEEDS_REVIEW, "The declared costs already consume the whole excess return",
                txt, [ev], proc, action="Reduce turnover or report the result as not viable net of costs.",
                priority="high", inputs=ins)
    elif sc[2] is not None and sc[2] <= hurdle:
        res.add("cost_sensitivity", BLOCK, NEEDS_REVIEW, "The excess return disappears at 2x the declared costs",
                txt + " Cost estimates are rarely better than a factor of two: the result is fragile.", [ev], proc,
                action="Document how the declared costs were estimated; show results under higher costs.",
                priority="medium", inputs=ins)
    elif sc[3] is not None and sc[3] <= hurdle:
        res.add("cost_sensitivity", BLOCK, INFO, "The excess return survives 2x but not 3x the declared costs",
                txt + " Not an alert: the margin covers a doubling of costs (docs/ALERT_POLICY.md).", [ev], proc,
                inputs=ins)
    else:
        res.add("cost_sensitivity", BLOCK, PASS, "The excess return survives 3x the declared costs", txt, [ev], proc,
                inputs=ins)

