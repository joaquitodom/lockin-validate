"""Reconstruction check and reconciliation against declared positions and declared results.

Check ids: reconstruction, positions_reconciliation, results_reconciliation.

Explicit tolerances (override in rules.yaml: conventions.tolerances):
  quantity       1e-6   absolute quantity difference per (date, ticker)
  total_return   0.005  absolute difference (0.5 percentage points)
  annual_return  0.005
  sharpe         0.05
  max_drawdown   0.005
  n_trades       0      exact
  final_nav      0.005  relative difference
  curve          0.005  relative difference per date
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from . import metrics
from .checks import missing_inputs
from .findings import CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE, PASS, AuditResult
from .inputs import Package
from .reconstruction import Conventions, Reconstruction, reconstruct

BLOCK = "reconstruction"
TOLERANCES: dict[str, float] = {
    "quantity": 1e-6, "total_return": 0.005, "annual_return": 0.005, "sharpe": 0.05, "max_drawdown": 0.005,
    "n_trades": 0, "final_nav": 0.005, "curve": 0.005,
}
RELATIVE = {"final_nav", "curve"}
RESULT_KEYS = ["total_return", "annual_return", "sharpe", "max_drawdown", "n_trades", "final_nav"]
AUXILIARY_KEYS = ["convention", "curve", "comment", "currency", "n_trials", "notes"]


def tolerances(pkg: Package) -> dict[str, float]:
    t = dict(TOLERANCES)
    extra = pkg.conv("tolerances")
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k in t and v is not None:
                t[k] = float(v)
    return t


def check_reconstruction(pkg: Package, res: AuditResult, conv: Conventions | None = None) -> Reconstruction | None:
    title = "Reconstruction of positions, cash and NAV"
    miss = pkg.missing("reconstruction")
    if miss:
        missing_inputs(res, "reconstruction", BLOCK, title, miss)
        return None
    try:
        rec = reconstruct(pkg, conv)
    except ValueError as e:
        res.add("reconstruction", BLOCK, NOT_EXECUTABLE, title, "", [], reason=str(e), priority="high")
        return None
    res.metrics["reconstruction"] = rec.summary()
    res.metrics["reconstructed_nav"] = [{"date": f.isoformat(), "cash": c, "positions_value": v, "nav": n}
                                        for f, c, v, n in zip(rec.dates, rec.cash, rec.positions_value, rec.nav)]
    problems = False
    if rec.unvalued:
        problems = True
        res.add("reconstruction", BLOCK, NEEDS_REVIEW, "Missing history: positions that could not be valued",
                "Tickers with a non-zero quantity and no close on or before the date. Scope finding: the "
                "reconstructed NAV counts them at zero and the reconciliation is partial.",
                [{"ticker": t, "days_unvalued": n} for t, n in rec.unvalued.items()],
                "Loop per date: bisect of the last close <= date in the ticker series.",
                action="Provide prices for those tickers.", priority="high", inputs=["prices", "trades"])
    if rec.negative_cash:
        problems = True
        res.add("reconstruction", BLOCK, CONFIRMED_ERROR, "Negative cash without declared leverage",
                f"{len(rec.negative_cash)} dates with negative cash. With conventions.leverage=false the strategy cannot "
                "buy more than it has: initial cash is missing, sales are missing, or there is undeclared leverage.",
                rec.negative_cash,
                f"Cash = {rec.conventions.initial_cash:g} initial - buys - commissions + sells, in chronological order.",
                action="Declare leverage or fix initial_cash / trades.", priority="high", inputs=["trades", "rules"])
    if rec.negative_quantity:
        problems = True
        res.add("reconstruction", BLOCK, CONFIRMED_ERROR, "Sells that leave a negative quantity without declared short selling",
                f"{len(rec.negative_quantity)} trades sell more than is held.", rec.negative_quantity,
                "Cumulative quantity per ticker after each trade.",
                action="Declare short selling or fix the trades.", priority="high", inputs=["trades", "rules"])
    if rec.trades_without_price:
        problems = True
        res.add("reconstruction", BLOCK, NEEDS_REVIEW, "Trades on dates without a close of the ticker",
                f"{len(rec.trades_without_price)} trades; that day the ticker is valued with the previous close "
                "(logged transformation).", rec.trades_without_price,
                "date(timestamp) not in the price dates of the ticker.", action="Complete prices.csv.",
                priority="medium", inputs=["trades", "prices"])
    if not problems:
        res.add("reconstruction", BLOCK, PASS, "Reconstruction complete with the available inputs",
                f"{len(rec.trades)} trades applied over {len(rec.dates)} dates; initial NAV {rec.nav[0]:,.2f} and final "
                f"{rec.nav[-1]:,.2f}; costs {rec.total_costs:,.2f}.", [],
                "Loop per date with the declared conventions (see metrics.reconstruction).",
                inputs=["trades", "prices", "rules"])
    return rec


def check_positions(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Reconciliation of declared positions"
    miss = pkg.missing("positions_reconciliation")
    if miss or rec is None:
        missing_inputs(res, "positions_reconciliation", BLOCK, title, miss or ["reconstruction"])
        return
    tol = tolerances(pkg)["quantity"]
    pos = pkg.df("positions").dropna(subset=["date", "ticker"])
    diffs, n = [], 0
    for f, g in pos.groupby(pos["date"].dt.date):
        recon = rec.holdings_at(f)
        declared = {}
        for r in g.itertuples():
            n += 1
            q = float(r.quantity) if pd.notna(r.quantity) else float("nan")
            declared[r.ticker] = q
            qr = recon.get(r.ticker, 0.0)
            if not (abs(q - qr) <= tol):
                diffs.append({"row": int(r.row), "date": f.isoformat(), "ticker": r.ticker, "declared": q,
                              "reconstructed": qr, "difference": q - qr})
        for t, qr in recon.items():
            if t not in declared and abs(qr) > tol:
                diffs.append({"row": None, "date": f.isoformat(), "ticker": t, "declared": 0.0, "reconstructed": qr,
                              "difference": -qr})
    if diffs:
        res.add("positions_reconciliation", BLOCK, CONFIRMED_ERROR, "Declared positions differ from reconstructed ones",
                f"{len(diffs)} differences in {n} declared positions (tolerance {tol:g}). Each row gives date, ticker, "
                "declared and reconstructed quantity.", diffs,
                "Reconstructed holdings at the close of the date (cumulative trades up to that date) versus "
                "positions.csv.", action="Look for missing or extra trades around those dates.", priority="high",
                inputs=["positions", "trades"])
    else:
        res.add("positions_reconciliation", BLOCK, PASS, "Declared positions reconciled",
                f"{n} declared positions match the reconstruction (tolerance {tol:g}).", [],
                "Comparison per (date, ticker).", inputs=["positions", "trades"])


def _diff(decl, calc, tol, relative: bool) -> tuple[float | None, bool]:
    if decl is None or calc is None or (isinstance(calc, float) and math.isnan(calc)):
        return None, False
    d = float(decl) - float(calc)
    if relative:
        base = abs(float(calc)) if calc else 1.0
        return d, abs(d) / base <= tol
    return d, abs(d) <= tol


def declared_convention(pkg: Package) -> dict | None:
    decl = pkg.declared or {}
    conv = decl.get("convention") if isinstance(decl.get("convention"), dict) else None
    if conv is None and pkg.rules and isinstance(pkg.rules.get("conventions"), dict):
        conv = {k: v for k, v in pkg.rules["conventions"].items() if k in metrics.DEFAULT_CONVENTION}
    if conv is None:
        p = (pkg.profile.get("conventions") or {})
        conv = {k: v for k, v in p.items() if k in metrics.DEFAULT_CONVENTION} or None
    return conv


def check_results(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> dict[str, Any] | None:
    title = "Reconciliation of declared results"
    miss = pkg.missing("results_reconciliation")
    if miss or rec is None:
        missing_inputs(res, "results_reconciliation", BLOCK, title, miss or ["reconstruction"])
        return None
    decl = pkg.declared or {}
    known = [k for k in RESULT_KEYS if decl.get(k) is not None]
    unknown = sorted(k for k in decl if k not in RESULT_KEYS and k not in AUXILIARY_KEYS)
    if not known and not (isinstance(decl.get("curve"), list) and decl.get("curve")):
        res.add("results_reconciliation", BLOCK, NOT_EXECUTABLE, title, "", [{"unrecognised_keys": unknown}],
                reason="declared_results.json has no recognised key (" + ", ".join(RESULT_KEYS)
                       + "); keys received: " + (", ".join(unknown) or "none"),
                action="Rename the metrics to the keys documented in docs/INPUT_SPEC.md and declare their convention.",
                priority="high", inputs=["declared_results"])
        return None
    if unknown:
        res.add("results_reconciliation", BLOCK, NEEDS_REVIEW, "Declared metrics with unrecognised keys were not verified",
                f"{len(unknown)} keys of declared_results.json are not recognised and were not contrasted: "
                + ", ".join(unknown) + ". Whatever they say is not reviewed.",
                [{"key": k} for k in unknown], "Keys compared with the documented list.",
                action="Rename them to the documented keys or remove them from the client report.",
                priority="medium", inputs=["declared_results"])
    conv = declared_convention(pkg)
    calc = metrics.compute(rec.nav, rec.dates, conv, n_trades=len(rec.trades))
    res.metrics["reconstructed_metrics"] = calc
    res.metrics["declared_convention"] = conv or {}
    tol = tolerances(pkg)
    rows, hard, soft = [], [], []
    for k in RESULT_KEYS:
        d = decl.get(k)
        c = calc.get(k)
        if k == "max_drawdown" and d is not None and float(d) > 0 and c is not None and c <= 0:
            d_cmp, note = -float(d), "declared as positive"
        else:
            d_cmp, note = d, ""
        difference, ok = _diff(d_cmp, c, tol[k], k in RELATIVE)
        row = {"metric": k, "declared": d, "reconstructed": c, "difference": difference, "tolerance": tol[k],
               "within_tolerance": ok if d is not None else None, "note": note}
        rows.append(row)
        if d is None or ok:
            continue
        (hard if k in ("total_return", "final_nav", "n_trades") else soft).append(row)
    curve_diffs: list[dict] = []
    curve = decl.get("curve")
    if isinstance(curve, list) and curve:
        nav_by_date = dict(zip(rec.dates, rec.nav))
        for p in curve:
            try:
                f = pd.Timestamp(str(p.get("date"))).date()
                v = float(p.get("nav"))
            except Exception:
                continue
            r = nav_by_date.get(f)
            if r is None:
                continue
            if abs(v - r) / (abs(r) or 1.0) > tol["curve"]:
                curve_diffs.append({"date": f.isoformat(), "declared": v, "reconstructed": r, "difference": v - r})
        res.metrics["declared_curve_points"] = len(curve)
        res.metrics["curve_differences"] = len(curve_diffs)
    absent = [k for k in RESULT_KEYS if decl.get(k) is None]
    proc = ("Daily NAV reconstructed from trades -> metrics with the declared convention ("
            + metrics.describe_convention(calc["convention"]) + ") -> comparison with declared_results.json using "
            "explicit tolerances.")
    ev = rows + [dict(e, metric="curve") for e in curve_diffs[:10]]
    ins = ["declared_results", "trades", "prices"]
    if hard or curve_diffs:
        res.add("results_reconciliation", BLOCK, CONFIRMED_ERROR, "Declared results are not reproduced from the trades",
                f"{len(hard)} metrics out of tolerance among total return, final NAV and number of trades"
                + (f"; {len(curve_diffs)} points of the declared curve differ" if curve_diffs else "")
                + ". A difference in these is not a convention issue: something is missing or extra in the trades, "
                  "the costs or the initial cash.", ev, proc,
                action="Review costs, initial cash and missing trades (see the omitted_costs check).", priority="high",
                inputs=ins)
    elif soft:
        res.add("results_reconciliation", BLOCK, NEEDS_REVIEW, "Declared metrics out of tolerance with the declared convention",
                f"{len(soft)} metrics (" + ", ".join(f["metric"] for f in soft) + ") do not match; total return, "
                "final NAV and number of trades do. It may be a different convention: see the metrics check.",
                ev, proc, action="Confirm the calculation convention with the strategy owner.", priority="medium",
                inputs=ins)
    else:
        res.add("results_reconciliation", BLOCK, PASS, "Declared results reconciled",
                "Every declared metric present is within tolerance" + (f" (not declared: {', '.join(absent)})" if absent
                                                                        else "") + ".", ev, proc, inputs=ins)
    return calc
