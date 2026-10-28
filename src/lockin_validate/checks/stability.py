"""Stability, concentration and conditional-rule activation (0.2.0, family 6).

Check ids:
  stability_and_concentration  subperiod metrics (calendar years when the series spans at least 3 years, halves
                               otherwise) with their dispersion; share of the total P&L from the top names (with trades)
                               and the top days. Review items: one subperiod carries the whole result (>= 3
                               subperiods, the others net <= 0); one name carries it (>= 3 names, the rest of the book
                               net <= 0); the result disappears without its best 1% of days (series of >= 250 periods).
  conditional_rule_activation  activation frequency of each conditional rule (regimes.csv column, declared in
                               rules.yaml conditional_rules) in sample vs out of sample; review when a rule is active in
                               fewer than conventions.regime_rare_in_sample (10%) of in-sample periods and more than
                               conventions.regime_dominant_out_of_sample (50%) of out-of-sample periods.

Motivation (LockIn case study): the inverted-curve bond rule was active in 5% of the in-sample months and in 83% of
the test months, so the test measured a rule the training period had barely exercised.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .. import stats
from ..findings import INFO, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from ..reconstruction import Reconstruction, price_table
from . import missing_inputs, not_executable
from .protocol import out_of_sample_start
from .statistics import periods_per_year, strategy_returns

BLOCK = "statistics"
MIN_DAYS_FOR_DAY_TEST = 250


def name_pnl(rec: Reconstruction, pkg: Package) -> dict[str, float]:
    """P&L per ticker: cash flows of its trades (commissions included) plus the final holding at the last close."""
    pnl: dict[str, float] = {}
    for t in rec.trades:
        sign = 1 if t["side"] == "buy" else -1
        pnl[t["ticker"]] = pnl.get(t["ticker"], 0.0) - sign * t["quantity"] * t["price"] - t["commission"]
    prices = price_table(pkg.df("prices"))
    last = rec.dates[-1]
    for tk, q in (rec.holdings[-1] if rec.holdings else {}).items():
        if tk in prices:
            fs, cs = prices[tk]
            i = int(np.searchsorted(np.array(fs, dtype="datetime64[D]"), np.datetime64(last), "right")) - 1
            if i >= 0:
                pnl[tk] = pnl.get(tk, 0.0) + q * cs[i]
    return pnl


def check_stability(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Stability across subperiods and concentration of the P&L"
    series = strategy_returns(pkg, rec)
    if series is None:
        missing_inputs(res, "stability_and_concentration", BLOCK, title, ["trades and prices, or returns"])
        return
    r = np.asarray(series.returns, dtype=float)
    ok = np.isfinite(r)
    if ok.sum() < 20 or series.dates is None:
        not_executable(res, "stability_and_concentration", BLOCK, title, "fewer than 20 dated return observations")
        return
    dates = [d for d, k in zip(series.dates, ok) if k]
    r = r[ok]
    ppy = periods_per_year(pkg)
    if rec is not None and series.source.startswith("NAV"):
        nav = np.asarray(rec.nav, dtype=float)
        pnl = np.diff(nav)[ok]
        unit = "currency (NAV change)"
    else:
        pnl = r.copy()
        unit = "return points (returns.csv, constant capital)"
    total = float(pnl.sum())
    years = sorted({d.year for d in dates})
    if len(years) >= 3:
        keys = [str(d.year) for d in dates]
        how = "calendar years"
    else:
        half = len(dates) // 2
        keys = ["first half" if i < half else "second half" for i in range(len(dates))]
        how = "halves"
    subs: list[dict[str, Any]] = []
    for k in dict.fromkeys(keys):
        m = np.array([x == k for x in keys])
        rr = r[m]
        sd = float(np.std(rr, ddof=1)) if len(rr) > 1 else float("nan")
        subs.append({"subperiod": k, "n": int(m.sum()), "pnl": round(float(pnl[m].sum()), 6),
                     "compounded_return": round(float(np.prod(1 + rr) - 1), 6),
                     "sharpe_annualised": round(float(np.mean(rr)) / sd * math.sqrt(ppy), 3) if sd and sd > 0 else None})
    srs = [s["sharpe_annualised"] for s in subs if s["sharpe_annualised"] is not None]
    dispersion = float(np.std(srs, ddof=1)) if len(srs) >= 2 else None
    k_days = max(1, math.ceil(0.01 * len(pnl)))
    top_days = np.sort(pnl)[::-1][:k_days]
    top5 = np.sort(pnl)[::-1][:5]
    info: dict[str, Any] = {"subperiods": subs, "subperiod_sharpe_dispersion": dispersion, "total_pnl": total,
                            "pnl_unit": unit, "top_1pct_days": k_days, "pnl_without_top_1pct_days":
                            total - float(top_days.sum()),
                            "share_top5_days": float(top5.sum()) / total if total else None}
    problems: list[tuple[str, str, list]] = []
    if total > 0 and len(subs) >= 3:
        best = max(subs, key=lambda s: s["pnl"])
        if best["pnl"] >= total:
            problems.append((f"One subperiod ({best['subperiod']}) carries the whole result",
                             f"P&L of {best['subperiod']}: {best['pnl']:,.4g} of a total {total:,.4g} {unit}; the other "
                             f"{len(subs) - 1} {how} together are net <= 0.", subs))
    notes: list[tuple[str, str, list]] = []
    if total > 0 and len(pnl) >= MIN_DAYS_FOR_DAY_TEST and info["pnl_without_top_1pct_days"] <= 0:
        mom = stats.moments(r)
        sr = mom["mean"] / mom["std"] if mom["std"] > 0 else 0.0
        psr0 = stats.probabilistic_sharpe(sr, 0.0, mom["T"], mom["skew"], mom["kurt"])
        target = problems
        if psr0 < float(pkg.conv("psr_threshold")):
            # docs/ALERT_POLICY.md rule 1: with a Sharpe that is not significant, losing the result without the best
            # 1% of periods is the same evidence that sharpe_significance judges; reported as a note.
            target = notes
        target.append((f"The result disappears without its best {k_days} periods (1%)",
                         f"Total P&L {total:,.4g}; the best {k_days} periods add {float(top_days.sum()):,.4g}.",
                         [{"top_periods": k_days, "pnl_top": float(top_days.sum()), "total": total,
                           "psr_vs_0": round(psr0, 4)}]))
    names = None
    if rec is not None and rec.trades:
        names = name_pnl(rec, pkg)
        tot_n = sum(names.values())
        order = sorted(names.items(), key=lambda x: -x[1])
        info["name_pnl"] = [{"ticker": t, "pnl": round(v, 2), "share_of_total": round(v / tot_n, 4) if tot_n else None}
                            for t, v in order]
        if tot_n > 0 and len(names) >= 3 and tot_n - order[0][1] <= 0:
            problems.append((f"One name ({order[0][0]}) carries the whole result",
                             f"{order[0][0]} contributes {order[0][1]:,.2f} of a total P&L of {tot_n:,.2f}; the other "
                             f"{len(names) - 1} names together lose {tot_n - order[0][1]:,.2f}.", info["name_pnl"][:10]))
    res.metrics["stability_and_concentration"] = info
    proc = (f"Subperiods: {how} of the return series ({series.source}); per subperiod P&L in {unit}, compounded return "
            "and annualised Sharpe; dispersion = std of the subperiod Sharpe ratios. Days: P&L without the best 1% of "
            f"periods (tested from {MIN_DAYS_FOR_DAY_TEST} periods). Names (with trades): cash flows of each ticker's "
            "trades including commissions plus its final holding at the last close.")
    ins = ["trades", "prices"] if series.source.startswith("NAV") else ["returns"]
    for ttl, det, ev in notes:
        res.add("stability_and_concentration", BLOCK, INFO, ttl,
                det + " Not an alert: the Sharpe ratio is not significant (PSR below its threshold), so this is the "
                "evidence already judged by sharpe_significance (docs/ALERT_POLICY.md, rule 1).", ev, proc, inputs=ins)
    if problems:
        for ttl, det, ev in problems:
            res.add("stability_and_concentration", BLOCK, NEEDS_REVIEW, ttl,
                    det + " A result that rests on one name, one subperiod or a handful of days is a bet on that "
                    "exposure, not evidence of a repeatable rule.", ev, proc,
                    action="Report the result without that name, subperiod or days, and explain the exposure.",
                    priority="medium", inputs=ins)
    else:
        ran, skipped = [], []
        (ran if len(subs) >= 3 else skipped).append(
            f"subperiods ({len(subs)} {how}" + ("" if len(subs) >= 3 else "; the rule needs >= 3") + ")")
        (ran if len(pnl) >= MIN_DAYS_FOR_DAY_TEST else skipped).append(
            f"best 1% of periods ({len(pnl)} periods" + ("" if len(pnl) >= MIN_DAYS_FOR_DAY_TEST else
                                                         f"; the test needs >= {MIN_DAYS_FOR_DAY_TEST}") + ")")
        n_names = len(names) if names else 0
        if names is None:
            skipped.append("names (no trades: return series only)")
        else:
            (ran if n_names >= 3 else skipped).append(
                f"names ({n_names}" + ("" if n_names >= 3 else "; the test needs >= 3") + ")")
        if notes:
            ran = [x for x in ran if not x.startswith("best 1%")]  # judged as an INFO note above
        top_name = ""
        if names:
            tot_n = sum(names.values())
            if tot_n:
                b = max(names.items(), key=lambda x: x[1])
                top_name = f" Largest name contribution: {b[0]} {b[1] / tot_n:.0%} of the P&L."
        desc = (f"{len(subs)} {how}; Sharpe by subperiod: " + ", ".join(f"{s['subperiod']} {s['sharpe_annualised']}"
                                                                      for s in subs[:8])
                + (f" (dispersion {dispersion:.2f})" if dispersion is not None else "") + "." + top_name
                + (" Not run: " + "; ".join(skipped) + "." if skipped else ""))
        evd = subs + ([{"name_pnl_top": info["name_pnl"][:5]}] if names else [])
        if ran:
            # the title names only the tests that ran (reviewer finding M6)
            res.add("stability_and_concentration", BLOCK, PASS,
                    "No concentration found by the tests that ran: " + "; ".join(ran), desc, evd, proc, inputs=ins)
        elif not notes:
            res.add("stability_and_concentration", BLOCK, INFO,
                    "Subperiods and contributions described; no concentration test applicable",
                    desc + " Not an alert and not a PASS: the series is too short or too narrow for the tests.",
                    evd, proc, inputs=ins)


def _active(v: Any) -> bool | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "active", "on"):
        return True
    if s in ("0", "false", "no", "n", "inactive", "off", ""):
        return False
    try:
        return float(s) != 0
    except ValueError:
        return None


def check_conditional_rules(pkg: Package, res: AuditResult) -> None:
    title = "Activation of conditional rules in and out of sample"
    miss = pkg.missing("conditional_rule_activation")
    if miss:
        missing_inputs(res, "conditional_rule_activation", BLOCK, title, miss)
        return
    start, end, src = out_of_sample_start(pkg)
    reg = pkg.df("regimes").dropna(subset=["date"]).sort_values("date")
    decl = (pkg.rules or {}).get("conditional_rules")
    rules: list[tuple[str, str]] = []
    if isinstance(decl, list):
        for x in decl:
            if isinstance(x, dict) and x.get("column"):
                rules.append((str(x.get("name") or x["column"]), str(x["column"]).strip().lower()))
            elif isinstance(x, str):
                rules.append((x, x.strip().lower()))
    if not rules:
        rules = [(c, c) for c in reg.columns if c not in ("row", "date")]
    rules = [(n, c) for n, c in rules if c in reg.columns]
    if not rules:
        not_executable(res, "conditional_rule_activation", BLOCK, title,
                       "no regimes.csv column matches the declared conditional_rules")
        return
    ins_mask = reg["date"].dt.date < start
    oos_mask = (reg["date"].dt.date >= start) & ((reg["date"].dt.date <= end) if end else True)
    if not ins_mask.any() or not oos_mask.any():
        not_executable(res, "conditional_rule_activation", BLOCK, title,
                       f"regimes.csv has no rows on one side of the out-of-sample start {start} ({src})")
        return
    rare = float(pkg.conv("regime_rare_in_sample", 0.10))
    dom = float(pkg.conv("regime_dominant_out_of_sample", 0.50))
    ev, flagged = [], []
    declared_missing = []
    if isinstance(decl, list):
        cols = {c for _, c in rules}
        for x in decl:
            c = str(x.get("column") if isinstance(x, dict) else x).strip().lower()
            if c not in cols:
                declared_missing.append({"rule": str(x.get("name") if isinstance(x, dict) else x), "column": c,
                                         "problem": "column not in regimes.csv"})
    never_in, no_oos = [], []
    for name, col in rules:
        a = reg[col].map(_active)
        ai, ao = a[ins_mask].dropna(), a[oos_mask].dropna()
        if not len(ai) or not len(ao):
            row = {"rule": name, "column": col, "in_sample_periods": int(len(ai)),
                   "out_of_sample_active": int(ao.sum()) if len(ao) else 0, "out_of_sample_periods": int(len(ao)),
                   "out_of_sample_share": round(float(ao.mean()), 4) if len(ao) else None}
            (never_in if not len(ai) else no_oos).append(row)
            continue
        row = {"rule": name, "column": col, "in_sample_active": int(ai.sum()), "in_sample_periods": int(len(ai)),
               "in_sample_share": round(float(ai.mean()), 4), "out_of_sample_active": int(ao.sum()),
               "out_of_sample_periods": int(len(ao)), "out_of_sample_share": round(float(ao.mean()), 4)}
        ev.append(row)
        if row["in_sample_share"] < rare and row["out_of_sample_share"] > dom:
            flagged.append(row)
    res.metrics["conditional_rule_activation"] = {"oos_start": str(start), "source": src, "rules": ev,
                                                  "never_computed_in_sample": never_in,
                                                  "not_computed_out_of_sample": no_oos,
                                                  "declared_not_found": declared_missing}
    proc = (f"Out-of-sample start {start} ({src}). Per rule: share of regimes.csv rows where the rule is active "
            f"(1/true) before and from that date. Review when the in-sample share is below {rare:.0%} "
            f"(conventions.regime_rare_in_sample) and the out-of-sample share above {dom:.0%} "
            "(conventions.regime_dominant_out_of_sample).")
    if never_in:
        # a declared rule with no in-sample values was never exercised where the model was fitted: every rule is
        # reported, none is dropped (reviewer finding M5)
        res.add("conditional_rule_activation", BLOCK, NEEDS_REVIEW,
                "Conditional rule never computed in sample: " + ", ".join(x["rule"] for x in never_in),
                "; ".join(f"{x['rule']} has no in-sample value and is active in {x['out_of_sample_active']} of "
                          f"{x['out_of_sample_periods']} out-of-sample periods" for x in never_in)
                + ". The out-of-sample window tests a rule the in-sample period never exercised.",
                never_in + ev, proc, action="Compute the rule over the in-sample period or report results without it.",
                priority="high", inputs=["regimes", "rules"])
    if no_oos or declared_missing:
        not_executable(res, "conditional_rule_activation", BLOCK, title + " (some declared rules)",
                       "declared rules that cannot be compared: "
                       + ", ".join(f"{x['rule']} ({x.get('problem', 'no out-of-sample value')})"
                                   for x in no_oos + declared_missing),
                       evidence=no_oos + declared_missing)
    if not ev:
        if not never_in and not no_oos and not declared_missing:
            not_executable(res, "conditional_rule_activation", BLOCK, title, "no parseable activation values")
        return
    if flagged:
        res.add("conditional_rule_activation", BLOCK, NEEDS_REVIEW,
                "Conditional rule rarely active in sample but dominant out of sample: "
                + ", ".join(x["rule"] for x in flagged),
                "; ".join(f"{x['rule']} active in {x['in_sample_active']} of {x['in_sample_periods']} in-sample periods "
                          f"({x['in_sample_share']:.0%}) and {x['out_of_sample_active']} of {x['out_of_sample_periods']} "
                          f"out-of-sample periods ({x['out_of_sample_share']:.0%})" for x in flagged)
                + ". The out-of-sample result mostly measures a rule calibrated on a handful of in-sample periods.",
                ev, proc, action="Report out-of-sample results with and without the rule; do not count the window as a "
                                 "test of the in-sample model.", priority="high", inputs=["regimes", "rules", "protocol"])
    elif not never_in and not no_oos and not declared_missing:
        res.add("conditional_rule_activation", BLOCK, PASS, "Conditional rules active comparably in and out of sample",
                "; ".join(f"{x['rule']}: {x['in_sample_share']:.0%} in sample, {x['out_of_sample_share']:.0%} out of "
                          "sample" for x in ev) + ".", ev, proc, inputs=["regimes", "rules"])

