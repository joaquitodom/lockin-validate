"""Strategy checks (only those the inputs allow).

Check ids:
  omitted_costs            declared costs vs effective costs in trades vs costs implied by the result
  metrics                  Sharpe / annual return / max drawdown with the declared convention and alternatives
  rules_vs_implementation  re-execution of a simple rule from rules.yaml vs the trades
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd

from .. import metrics
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from ..reconciliation import tolerances
from ..reconstruction import Conventions, Reconstruction, reconstruct
from . import not_executable

BLOCK = "strategy"
COST_REL_DIFF = 0.20  # relative difference tolerated between declared and effective cost


# ---------------------------------------------------------------------------- omitted costs

def _costs_csv(pkg: Package) -> dict[str, float]:
    """{item: fraction of notional} from costs.csv (units pct, bps or fraction)."""
    out: dict[str, float] = {}
    c = pkg.df("costs")
    if c is None:
        return out
    for r in c.dropna(subset=["item", "value"]).itertuples():
        u = str(r.unit or "pct").strip().lower()
        v = float(r.value)
        key = str(r.item).strip().lower()
        if u in ("pct", "percent", "%"):
            out[key] = v / 100.0
        elif u in ("bps", "bp"):
            out[key] = v / 10_000.0
        elif u in ("fraction", "rate"):
            out[key] = v
    return out


def declared_costs(pkg: Package) -> tuple[float | None, float | None, str]:
    """(commission, slippage, source). None = not declared. rules.yaml wins over costs.csv."""
    costs = (pkg.rules or {}).get("costs") if pkg.rules else None
    if isinstance(costs, dict) and (costs.get("commission_rate") is not None or costs.get("slippage_rate") is not None):
        com, slip = costs.get("commission_rate"), costs.get("slippage_rate")
        return (None if com is None else float(com)), (None if slip is None else float(slip)), "rules.yaml"
    c = _costs_csv(pkg)
    if c:
        return (sum(v for k, v in c.items() if "slip" not in k), sum(v for k, v in c.items() if "slip" in k),
                "costs.csv")
    return None, None, "-"


def effective_slippage(pkg: Package) -> float | None:
    """Notional-weighted mean of |trade price / close of the day - 1|."""
    tr, px = pkg.df("trades"), pkg.df("prices")
    if tr is None or px is None:
        return None
    closes = {(t, f.date()): c for t, f, c in zip(px["ticker"], px["date"], px["close"]) if pd.notna(c) and pd.notna(f)}
    num = den = 0.0
    for r in tr.dropna(subset=["timestamp", "ticker", "quantity", "price"]).itertuples():
        c = closes.get((r.ticker, r.timestamp.date()))
        if not c:
            continue
        notional = abs(float(r.quantity) * float(r.price))
        num += notional * abs(float(r.price) / c - 1)
        den += notional
    return num / den if den > 0 else None


def _fmt(x: float | None, if_none: str) -> str:
    return if_none if x is None else f"{x:g}"


def check_omitted_costs(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Omitted costs"
    miss = pkg.missing("omitted_costs")
    if miss or rec is None:
        not_executable(res, "omitted_costs", BLOCK, title, "missing: " + ", ".join(miss or ["reconstruction"]))
        return
    decl_com, decl_slip, source = declared_costs(pkg)
    tr = pkg.df("trades")
    o = tr.dropna(subset=["quantity", "price"])
    notional = float((o["quantity"].abs() * o["price"]).sum())
    eff_com = None
    if "commission" in tr.columns and tr["commission"].notna().any():
        eff_com = float(o["commission"].fillna(0).sum()) / notional if notional > 0 else 0.0
    eff_slip = effective_slippage(pkg)
    capital = float(rec.conventions.initial_cash) or 1.0
    turnover = notional / capital
    decl_total = pkg.declared.get("total_return") if pkg.declared else None
    tol = tolerances(pkg)["total_return"]
    base = Conventions.from_package(pkg)
    scenarios: dict[str, dict[str, Any]] = {}
    candidates = {"no costs": dict(commission_rate=0.0, slippage_rate=0.0, impute_costs=True,
                                   use_trade_commissions=False)}
    if (decl_com or 0) > 0 or (decl_slip or 0) > 0:
        candidates["declared costs"] = dict(commission_rate=decl_com or 0.0, slippage_rate=decl_slip or 0.0,
                                            impute_costs=True, use_trade_commissions=False)
    if eff_com is not None:
        candidates["commissions in trades.csv"] = dict(commission_rate=0.0, slippage_rate=0.0, impute_costs=False,
                                                       use_trade_commissions=True)
    for name, kw in candidates.items():
        c = Conventions(**{**base.__dict__, **kw})
        try:
            r = reconstruct(pkg, c, log=False)
        except ValueError:
            continue
        scenarios[name] = {"total_return": metrics.total_return(r.nav), "dates_negative_cash": len(r.negative_cash),
                           "min_cash": min(r.cash) if r.cash else None}
    reproduce = None
    if decl_total is not None:
        reproduce = [n for n, v in scenarios.items() if abs(v["total_return"] - float(decl_total)) <= tol]
    res.metrics["costs"] = {"declared_source": source, "declared_commission": decl_com, "declared_slippage": decl_slip,
                            "effective_commission": eff_com, "effective_slippage": eff_slip,
                            "turnover_over_capital": turnover, "scenarios": scenarios, "reproduce_declared": reproduce}
    ev = [{"source": f"declared commission ({source})", "fraction": decl_com},
          {"source": f"declared slippage ({source})", "fraction": decl_slip},
          {"source": "effective commission (sum commission / notional)", "fraction": eff_com},
          {"source": "effective slippage (trade price vs close, weighted)", "fraction": eff_slip},
          {"source": "turnover (traded notional / initial cash)", "value": round(turnover, 4)},
          {"source": "declared total_return", "value": decl_total,
           "scenarios": {k: round(v["total_return"], 6) for k, v in scenarios.items()}, "reproduced_by": reproduce}]
    proc = ("Declared costs (rules.yaml or costs.csv; commission and slippage separately) are contrasted with the "
            "effective ones in trades.csv (commission column; execution price vs the close of the day) and with the "
            "cost scenario that reproduces the declared total_return. Each scenario is a full reconstruction from the "
            "initial cash: 'no costs' (zero commission and slippage), 'declared costs' (only the declared ones, not "
            "added to those in trades.csv) and 'commissions in trades.csv'. "
            f"Total return tolerance: {tol:g}.")
    ins = ["rules", "costs", "trades", "declared_results"]
    nothing_declared = decl_com is None and decl_slip is None
    if nothing_declared and eff_com is None and decl_total is None:
        not_executable(res, "omitted_costs", BLOCK, title,
                       "no declared costs (rules.yaml or costs.csv), no commission column in trades.csv and no "
                       "declared total_return")
        return
    eff_cost = (eff_com or 0.0) + (eff_slip or 0.0)
    decl_cost = (decl_com or 0.0) + (decl_slip or 0.0)
    if decl_cost == 0 and eff_cost < 1e-9 and turnover > 0:
        res.add("omitted_costs", BLOCK, NEEDS_REVIEW, "Zero cost with non-zero turnover",
                ("Declared costs are zero" if not nothing_declared else "No costs are declared")
                + f" and the trades show no costs, with a turnover of {turnover:.2f} times the capital. No market "
                  "trades for free: the result is gross or the costs are somewhere else.",
                ev, proc, action="Ask for the broker's commission, fee and spread schedule and recompute.",
                priority="high" if turnover > 2 else "medium", inputs=ins)
        return
    com_omitted = (decl_com or 0) > 0 and (eff_com is None or eff_com <= decl_com * (1 - COST_REL_DIFF))
    slip_omitted = (decl_slip or 0) > 0 and (eff_slip is None or eff_slip <= decl_slip * (1 - COST_REL_DIFF))
    sc_decl = scenarios.get("declared costs", {})
    consequence = ""
    if sc_decl.get("dates_negative_cash"):
        consequence = (" Consequence of the same problem (not a separate finding): with the declared costs applied, "
                       "the delivered trades leave cash negative on "
                       f"{sc_decl['dates_negative_cash']} dates (minimum {sc_decl['min_cash']:,.2f}), because they "
                       "were sized without costs.")
    if com_omitted or slip_omitted:
        what = " and ".join(x for x, f in (("commission", com_omitted), ("slippage", slip_omitted)) if f)
        detail = (f"Declared: commission {decl_com or 0:g}, slippage {decl_slip or 0:g} of notional. In the trades: "
                  f"commission {_fmt(eff_com, 'absent')}, slippage {_fmt(eff_slip, 'not measurable')}.")
        if reproduce is not None and "no costs" in reproduce and "declared costs" not in reproduce:
            res.add("omitted_costs", BLOCK, CONFIRMED_ERROR,
                    f"The declared result is reproduced only WITHOUT the declared costs ({what})",
                    detail + f" The declared total_return ({float(decl_total):+.4f}) matches the no-cost scenario "
                    f"({scenarios['no costs']['total_return']:+.4f}) and not the declared-cost one "
                    f"({sc_decl.get('total_return', float('nan')):+.4f})." + consequence,
                    ev, proc, action="Recompute the result with the declared costs and report both.", priority="high",
                    inputs=ins)
            return
        if reproduce and "no costs" in reproduce:
            res.add("omitted_costs", BLOCK, NEEDS_REVIEW,
                    f"Declared costs ({what}) absent from the trades; the test does not discriminate",
                    detail + " The declared result is reproduced both without costs and with the declared ones: the "
                    "costs are small relative to the tolerance and it cannot be told whether they were included."
                    + consequence, ev, proc, action="Ask for the per-trade cost detail.", priority="medium",
                    inputs=ins)
            return
        res.add("omitted_costs", BLOCK, NEEDS_REVIEW, f"Declared costs ({what}) larger than the effective ones in the trades",
                detail + consequence, ev, proc, action="Confirm whether the delivered trades include the costs.",
                priority="medium", inputs=ins)
        return
    if decl_com is not None and eff_com is not None and eff_com > max(decl_com, 1e-12) * (1 + COST_REL_DIFF):
        res.add("omitted_costs", BLOCK, NEEDS_REVIEW, "Effective costs larger than declared",
                f"Declared {decl_com:g}; effective {eff_com:g}.", ev, proc, action="Review the cost schedule.",
                priority="low", inputs=ins)
        return
    if reproduce is not None and not reproduce:
        res.add("omitted_costs", BLOCK, NEEDS_REVIEW, "No cost scenario reproduces the declared return",
                "Declared and effective costs are consistent, but the declared total_return matches no scenario (see "
                "results_reconciliation).", ev, proc, action="Review the results reconciliation.", priority="medium",
                inputs=ins)
        return
    if reproduce and "no costs" in reproduce and len(reproduce) > 1:
        res.add("omitted_costs", BLOCK, NEEDS_REVIEW, "Costs consistent, but the test does not discriminate",
                "Declared and effective costs match; the declared return is reproduced with costs and also without costs "
                "within tolerance: it cannot be confirmed that the result includes them.", ev, proc,
                action="If it matters, ask for net and gross results separately.", priority="low", inputs=ins)
        return
    if decl_total is None:
        res.add("omitted_costs", BLOCK, INFO, "Costs consistent, no declared result to contrast",
                "Declared and effective costs match, but there is no declared total_return to see whether the result "
                "includes them. Not an alert: the reconstruction already uses the costs present in the trades "
                "(docs/ALERT_POLICY.md, P2).", ev, proc, priority="low", inputs=ins)
        return
    res.add("omitted_costs", BLOCK, PASS, "Costs consistent",
            f"Declared commission {_fmt(decl_com, '-')}, slippage {_fmt(decl_slip, '-')}; effective commission "
            f"{_fmt(eff_com, '-')}; the declared return is reproduced with: {', '.join(reproduce or [])} and not without "
            "costs.", ev, proc, inputs=ins)


# ---------------------------------------------------------------------------- metrics

def check_metrics(pkg: Package, res: AuditResult, rec: Reconstruction | None, calc: dict | None) -> None:
    title = "Metric errors (Sharpe, annual return, max drawdown)"
    miss = pkg.missing("metrics")
    if miss or rec is None:
        not_executable(res, "metrics", BLOCK, title, "missing: " + ", ".join(miss or ["reconstruction"]))
        return
    if calc is None:
        not_executable(res, "metrics", BLOCK, title,
                       "declared_results.json has no recognised metrics to contrast (see results_reconciliation)")
        return
    decl = pkg.declared or {}
    tol = tolerances(pkg)
    rt_decl = decl.get("total_return")
    if rt_decl is not None and abs(float(rt_decl) - calc["total_return"]) > tol["total_return"]:
        res.add("metrics", BLOCK, NEEDS_REVIEW, "Metrics not assessable by convention: the total return does not reconcile",
                f"Declared total_return ({float(rt_decl):+.4f}) differs from the reconstructed one "
                f"({calc['total_return']:+.4f}). With different NAVs, comparing Sharpe, annual return or drawdown under "
                "alternative conventions can give chance matches. results_reconciliation must be closed first.",
                [{"metric": "total_return", "declared": float(rt_decl), "reconstructed": calc["total_return"],
                  "tolerance": tol["total_return"]}],
                "Declared vs reconstructed total_return compared before testing conventions.",
                action="Resolve the results reconciliation and run again.", priority="medium",
                inputs=["declared_results", "trades", "prices"])
        return
    explicit = isinstance(decl.get("convention"), dict) and bool(decl["convention"])
    used = calc["convention"]
    variants = {"sharpe": metrics.sharpe_variants(rec.nav, rec.dates),
                "annual_return": metrics.annual_return_variants(rec.nav, rec.dates),
                "max_drawdown": metrics.max_drawdown_variants(rec.nav)}
    res.metrics["metric_variants"] = variants
    ev, errors, reviews, ok = [], [], [], []
    for k in ("sharpe", "annual_return", "max_drawdown"):
        d = decl.get(k)
        if d is None:
            continue
        d = float(d)
        c = calc[k]
        note = ""
        if k == "max_drawdown" and d > 0 and c is not None and c <= 0:
            d, note = -d, "declared as positive; absolute values compared (sign convention, not an error)"
        matches = c is not None and not math.isnan(c) and abs(d - c) <= tol[k]
        repro = [n for n, v in variants[k].items() if v is not None and not math.isnan(v) and abs(d - v) <= tol[k]]
        row = {"metric": k, "declared": d, "with_declared_convention": c, "matches_declared_convention": matches,
               "conventions_that_reproduce_it": repro[:8], "tolerance": tol[k], "note": note}
        ev.append(row)
        if matches:
            ok.append(k)
        elif repro:
            (errors if explicit else reviews).append(row)
        else:
            errors.append(row)
    proc = ("Recomputed on the reconstructed NAV with the declared convention (" + metrics.describe_convention(used)
            + ") and with common alternatives: 252/260/365/360 periods, arithmetic vs geometric mean, std ddof 1 vs 0, "
              "with and without a risk-free rate (0/2/4/5%), simple vs log returns; max drawdown on the NAV, as a "
              "positive number, worst single period and sum of returns without compounding.")
    if not ev:
        not_executable(res, "metrics", BLOCK, title, "declared_results.json has no sharpe, annual_return or max_drawdown")
        return
    ins = ["declared_results", "trades", "prices"]
    if errors:
        wrong = [f for f in errors if not f["conventions_that_reproduce_it"]]
        other = [f for f in errors if f["conventions_that_reproduce_it"]]
        parts = []
        if other:
            parts.append("; ".join(f"{f['metric']} declared {f['declared']:.4f} is reproduced with "
                                   f"{f['conventions_that_reproduce_it'][0]} and not with the declared convention "
                                   f"({f['with_declared_convention']:.4f})" for f in other))
        if wrong:
            parts.append("; ".join(f"{f['metric']} declared {f['declared']:.4f} is not reproduced by any convention "
                                   f"tried (the declared one gives {f['with_declared_convention']:.4f})" for f in wrong))
        res.add("metrics", BLOCK, CONFIRMED_ERROR, "Declared metrics miscalculated or computed with another convention",
                ". ".join(parts) + ".", ev, proc,
                action="Recompute the metrics with the declared convention and publish it next to the number.",
                priority="high", inputs=ins)
    elif reviews:
        res.add("metrics", BLOCK, NEEDS_REVIEW, "Metrics reproduced only with an undeclared convention",
                "; ".join(f"{f['metric']} declared {f['declared']:.4f} matches {f['conventions_that_reproduce_it'][0]} "
                          f"(no convention declared; the default gives {f['with_declared_convention']:.4f})"
                          for f in reviews) + ".", ev, proc,
                action="Declare the convention in declared_results.convention.", priority="medium",
                inputs=["declared_results"])
    else:
        res.add("metrics", BLOCK, PASS, "Declared metrics reproduced",
                "They match the declared convention: " + ", ".join(ok) + ".", ev, proc, inputs=ins)


# ---------------------------------------------------------------------------- rules vs implementation

FREQ = {"monthly": "monthly", "weekly": "weekly", "daily": "daily"}
TIMING = {"first_day": "first_day", "last_day": "last_day", "first": "first_day", "last": "last_day"}


def rebalance_dates(dates: list[date], frequency: str, timing: str) -> list[date]:
    if frequency == "daily":
        return list(dates)
    groups: dict[Any, list[date]] = {}
    for f in dates:
        key = (f.year, f.month) if frequency == "monthly" else tuple(f.isocalendar()[:2])
        groups.setdefault(key, []).append(f)
    return [g[-1] if timing == "last_day" else g[0] for g in groups.values()]


def check_rules(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Declared rules vs implementation"
    miss = pkg.missing("rules_vs_implementation")
    if miss or rec is None:
        not_executable(res, "rules_vs_implementation", BLOCK, title, "missing: " + ", ".join(miss or ["reconstruction"]))
        return
    rules = pkg.rules or {}
    sig_cfg = rules.get("signal") if isinstance(rules.get("signal"), dict) else {}
    sel = rules.get("selection") if isinstance(rules.get("selection"), dict) else {}
    reb = rules.get("rebalance") if isinstance(rules.get("rebalance"), dict) else {}
    column = str(sig_cfg.get("column", "signal"))
    order = str(sig_cfg.get("order", "desc")).lower()
    top_n = sel.get("top_n")
    frequency = FREQ.get(str(reb.get("frequency", "")).lower(), "")
    timing = TIMING.get(str(reb.get("timing", "first_day")).lower(), "")
    sizing = str(rules.get("sizing", "equal_weight")).lower()
    universe = rules.get("universe", "all")
    tol_w = float(pkg.conv("rebalance_weight_tolerance"))
    unsupported = []
    if top_n is None:
        unsupported.append("selection.top_n missing")
    if not frequency:
        unsupported.append(f"rebalance.frequency={reb.get('frequency') or 'missing'} (supported: monthly, weekly, daily)")
    if not timing:
        unsupported.append(f"rebalance.timing={reb.get('timing')} (supported: first_day, last_day)")
    if sizing not in ("equal_weight", "equal"):
        unsupported.append(f"sizing={sizing} (supported: equal_weight)")
    if order not in ("desc", "asc"):
        unsupported.append(f"signal.order={order} (supported: desc, asc)")
    sig = pkg.df("signals")
    if column not in sig.columns:
        unsupported.append(f"signals.csv has no column {column}")
    if unsupported:
        not_executable(res, "rules_vs_implementation", BLOCK, title,
                       "rule not supported by the re-execution engine: " + "; ".join(unsupported),
                       "Express the rule as a ranking on one column, top N, periodic rebalance and equal weights, or "
                       "review it manually.")
        return
    top_n = int(top_n)
    s = sig.dropna(subset=["decision_time", "ticker", column]).copy()
    if isinstance(universe, list):
        u = {str(x).strip().upper() for x in universe}
        s = s[s["ticker"].isin(u)]
    s["day"] = s["decision_time"].dt.date
    sig_dates = sorted(set(s["day"]))
    reb_dates = rebalance_dates(sig_dates, frequency, timing)
    expected: dict[date, list[str]] = {}
    for f in reb_dates:
        g = s[s["day"] == f].sort_values([column, "ticker"], ascending=[order != "desc", True])
        expected[f] = list(g["ticker"].head(top_n))
    px = pkg.df("prices").dropna(subset=["date", "ticker", "close"])
    closes = {t: dict(zip(g["date"].dt.date, g["close"])) for t, g in px.groupby("ticker")}
    diffs, bad_weights, n_ok = [], [], 0
    for f, exp in expected.items():
        holding = rec.holdings_at(f)
        held = {t for t, q in holding.items() if q > 0}
        missing_t = sorted(set(exp) - held)
        extra_t = sorted(held - set(exp))
        if missing_t or extra_t:
            diffs.append({"date": f.isoformat(), "expected_top_n": exp, "reconstructed_holdings": sorted(held),
                          "missing": missing_t, "extra": extra_t, "n_expected": top_n, "n_held": len(held)})
        else:
            n_ok += 1
        if held and closes:
            vals = {t: holding[t] * closes.get(t, {}).get(f, float("nan")) for t in held}
            total = sum(v for v in vals.values() if not math.isnan(v))
            if total > 0:
                target = 1.0 / len(held)
                dev = {t: v / total / target - 1 for t, v in vals.items() if not math.isnan(v)}
                worst = max(dev.items(), key=lambda kv: abs(kv[1]))
                if abs(worst[1]) > tol_w:
                    bad_weights.append({"date": f.isoformat(), "ticker": worst[0],
                                        "relative_deviation_vs_1/N": round(worst[1], 4),
                                        "weights": {t: round(v / total, 4) for t, v in vals.items() if not math.isnan(v)}})
    trade_dates = sorted({date.fromisoformat(o["date"]) for o in rec.trades})
    off = [f.isoformat() for f in trade_dates if f not in set(reb_dates)]
    res.metrics["rules"] = {"column": column, "order": order, "top_n": top_n, "frequency": frequency, "timing": timing,
                            "sizing": sizing, "rebalance_dates": [f.isoformat() for f in reb_dates],
                            "trade_dates": [f.isoformat() for f in trade_dates], "dates_ok": n_ok,
                            "dates_with_differences": len(diffs), "trades_off_schedule": off}
    proc = (f"From rules.yaml: ranking on `{column}` ({order}), top {top_n}, {frequency} rebalance ({timing}), "
            f"{sizing}. On each rebalance date the top N of signals.csv is compared with the reconstructed holdings at "
            f"the close of that day, and the weights with 1/N (tolerance {tol_w:.0%}).")
    ev = diffs + [dict(p, kind="weights") for p in bad_weights[:5]] + (
        [{"kind": "trades_off_schedule", "dates": off[:20], "n": len(off)}] if off else [])
    ins = ["rules", "signals", "trades", "prices"]
    if diffs:
        res.add("rules_vs_implementation", BLOCK, CONFIRMED_ERROR, "The trades do not implement the declared rule",
                f"{len(diffs)} of {len(expected)} rebalance dates with holdings different from the declared top {top_n}"
                + (f"; {len(off)} dates with trades off the rebalance schedule" if off else "")
                + (f"; {len(bad_weights)} dates with weights far from 1/N" if bad_weights else "") + ".", ev, proc,
                action="Align the backtest code with rules.yaml or correct the declared rules.", priority="high",
                inputs=ins)
    elif off or bad_weights:
        res.add("rules_vs_implementation", BLOCK, NEEDS_REVIEW, "Holdings follow the declared top N but schedule or weights do not",
                (f"{len(off)} dates with trades off the rebalance schedule. " if off else "")
                + (f"{len(bad_weights)} dates with weights deviating more than {tol_w:.0%} from 1/N." if bad_weights
                   else ""), ev, proc,
                action="Confirm whether the extra trades are legitimate adjustments (dividends, rounding).",
                priority="medium", inputs=ins)
    else:
        res.add("rules_vs_implementation", BLOCK, PASS, "The trades implement the declared rule",
                f"{n_ok} rebalance dates with holdings equal to the top {top_n}; weights within {tol_w:.0%} of 1/N; no "
                "trades off schedule. Scope: the signal column delivered is re-ranked; the signal computation itself "
                "is not verified.", ev, proc, inputs=ins)
