"""Dividend and corporate-action consistency between adjusted and as-traded prices (0.2.0, family 4).

Check id: dividend_corporate_actions. prices.csv is taken as the adjusted series; unadjusted_prices.csv is the
as-traded series; dividends.csv lists cash dividends (ticker, ex_date, amount); corporate_actions.csv lists splits.

With both series the ratio R_t = adjusted / as-traded must step, on each ex-date, by exactly
1 / (1 - D / C_{t-1}) for a cash dividend D (C = as-traded close of the previous session) and by the split ratio for a
split (back-adjustment as in the CRSP cumulative factor). Findings:

  - declared event not applied (no step) while other dividends of the same series are applied: CONFIRMED_ERROR
    (the series is internally inconsistent); no dividend applied at all: NEEDS_REVIEW (a price-return series);
  - step of a different size, or a ratio break on a day without a declared event: NEEDS_REVIEW;
  - adjusted close frozen for >= conventions.stale_after_event (3) sessions from an ex-date: CONFIRMED_ERROR when the
    as-traded price moves on those days, NEEDS_REVIEW otherwise;
  - declared_results.return_basis 'total' reproduced by a reconstruction on unadjusted prices that ignores dividends
    held over ex-dates: CONFIRMED_ERROR; 'price' with dividend-adjusted prices: NEEDS_REVIEW.

Motivation (LockIn paper trading): ex-dividend rows loaded before the vendor applied the dividend froze the prices of
two holdings.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .. import metrics
from ..findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from ..reconciliation import tolerances
from ..reconstruction import Reconstruction, price_table
from . import missing_inputs

BLOCK = "data"


def _events(pkg: Package) -> tuple[dict[tuple[str, date], float], dict[tuple[str, date], float]]:
    divs: dict[tuple[str, date], float] = defaultdict(float)
    d = pkg.df("dividends")
    if d is not None:
        for r in d.dropna(subset=["ticker", "ex_date", "amount"]).itertuples():
            divs[(r.ticker, r.ex_date.date())] += float(r.amount)
    splits: dict[tuple[str, date], float] = {}
    c = pkg.df("corporate_actions")
    if c is not None:
        for r in c.dropna(subset=["ticker", "date", "ratio"]).itertuples():
            if float(r.ratio) > 0:
                splits[(r.ticker, r.date.date())] = float(r.ratio)
    return dict(divs), splits


def check_dividends(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Dividends and corporate actions: adjusted vs as-traded prices"
    miss = pkg.missing("dividend_corporate_actions")
    if miss:
        missing_inputs(res, "dividend_corporate_actions", BLOCK, title, miss)
        return
    tol = float(pkg.conv("adjustment_tolerance", 0.001))
    stale_n = int(pkg.conv("stale_after_event", 3))
    adj = price_table(pkg.df("prices"))
    raw = price_table(pkg.df("unadjusted_prices")) if pkg.df("unadjusted_prices") is not None else {}
    divs, splits = _events(pkg)
    events_by_ticker: dict[str, set[date]] = defaultdict(set)
    for t, d in list(divs) + list(splits):
        events_by_ticker[t].add(d)
    applied, not_applied, mismatch, undiscriminable, breaks, frozen = [], [], [], [], [], []
    for t, (fs, cs) in adj.items():
        a = dict(zip(fs, cs))
        u = dict(zip(*raw[t])) if t in raw else {}
        common = [d for d in fs if d in u] if u else []
        if len(common) >= 2:
            for k in range(1, len(common)):
                d0, d1 = common[k - 1], common[k]
                if u[d0] <= 0 or u[d1] <= 0 or a[d0] <= 0:
                    continue
                step = (a[d1] / u[d1]) / (a[d0] / u[d0])
                exp = 1.0
                kinds = []
                if (t, d1) in divs:
                    exp *= 1.0 / (1.0 - divs[(t, d1)] / u[d0])
                    kinds.append(f"dividend {divs[(t, d1)]:g}")
                if (t, d1) in splits:
                    exp *= splits[(t, d1)]
                    kinds.append(f"split {splits[(t, d1)]:g}")
                ev = {"ticker": t, "date": d1, "event": ", ".join(kinds) or "-", "expected_step": round(exp, 6),
                      "observed_step": round(step, 6), "adjusted_close": a[d1], "as_traded_close": u[d1]}
                if kinds:
                    if abs(exp - 1) <= 2 * tol:
                        undiscriminable.append(ev)
                    elif abs(step - exp) <= tol * max(1.0, exp):
                        applied.append(ev)
                    elif abs(step - 1) <= tol:
                        not_applied.append(ev)
                    else:
                        mismatch.append(ev)
                elif abs(step - 1) > tol:
                    breaks.append(ev)
        # frozen adjusted close from an event date
        idx = {d: i for i, d in enumerate(fs)}
        for e in sorted(events_by_ticker.get(t, ())):
            i = idx.get(e)
            if i is None or i == 0:
                continue
            n, j = 0, i
            while j < len(fs) and cs[j] == cs[j - 1]:
                n += 1
                j += 1
            if n >= stale_n:
                days = fs[i:i + n]
                moved = bool(u) and any(u.get(days[q]) is not None and u.get(fs[i + q - 1]) is not None
                                        and u[days[q]] != u[fs[i + q - 1]] for q in range(n))
                frozen.append({"ticker": t, "event_date": e, "frozen_sessions": n, "frozen_close": cs[i],
                               "until": days[-1], "as_traded_moves": moved if u else None})
    # ratio breaks inside a frozen run are the same problem, reported once (docs/ALERT_POLICY.md, rule 1)
    frozen_days = set()
    for x in frozen:
        fs = adj[x["ticker"]][0]
        i = fs.index(x["event_date"])
        frozen_days |= {(x["ticker"], d) for d in fs[i:i + x["frozen_sessions"] + 1]}
    breaks = [x for x in breaks if (x["ticker"], x["date"]) not in frozen_days]
    div_events = [x for x in applied + not_applied + mismatch if "dividend" in x["event"]]
    applied_div = {x["ticker"] for x in applied if "dividend" in x["event"]}
    findings: list[tuple[str, str, str, list]] = []
    inconsistent = [x for x in not_applied if x["ticker"] in applied_div or "split" in x["event"]]
    if inconsistent:
        findings.append((CONFIRMED_ERROR, f"Declared events not applied in the adjusted series ({len(inconsistent)}: "
                         + ", ".join(sorted({x['ticker'] for x in inconsistent})) + ")",
                         "On these ex-dates the adjusted / as-traded ratio does not move although the declared event "
                         "requires it, while other dividends of the same series ARE applied: the adjusted series is "
                         "internally inconsistent (" + ", ".join(f"{x['ticker']} {x['date']}" for x in inconsistent[:6])
                         + ").", inconsistent))
    rest = [x for x in not_applied if x not in inconsistent]
    if rest:
        findings.append((NEEDS_REVIEW, f"Adjusted series not adjusted for dividends ({len(rest)} ex-dates)",
                         "No declared dividend of these tickers is reflected in the adjusted series: it is a price "
                         "series, not a total-return one. Confirm returns are not presented as total returns.", rest))
    if frozen:
        hard = [x for x in frozen if x["as_traded_moves"]]
        st = CONFIRMED_ERROR if hard else NEEDS_REVIEW
        findings.append((st, f"Adjusted price frozen from an ex-date ({len(frozen)}: "
                         + ", ".join(f"{x['ticker']} {x['event_date']}" for x in frozen[:4]) + ")",
                         "The adjusted close repeats for at least " + str(stale_n) + " sessions starting on a declared "
                         "event date" + (" while the as-traded price moves: rows were loaded before the event was "
                                         "applied and positions are valued at a stale price." if hard else
                                         " (the as-traded series is not available or also flat)."), frozen))
    if mismatch:
        findings.append((NEEDS_REVIEW, f"Adjustment step of a different size than the declared event ({len(mismatch)})",
                         "The ratio moves on the ex-date but not by the amount the declared dividend or split implies.",
                         mismatch))
    if breaks:
        findings.append((NEEDS_REVIEW, f"Adjusted / as-traded ratio breaks without a declared event ({len(breaks)})",
                         "The adjustment factor changes on days with no dividend or split in the inputs: an "
                         "undeclared event or a data error (" + ", ".join(f"{x['ticker']} {x['date']}"
                                                                         for x in breaks[:6]) + ").", breaks))
    # declared return basis vs dividends held
    basis = str((pkg.declared or {}).get("return_basis") or "").strip().lower()
    if basis in ("total", "price") and rec is not None and divs and pkg.declared.get("total_return") is not None:
        px = pkg.df("prices")
        adj_flags = set(px["adjusted"]) if "adjusted" in px.columns else set()
        income = 0.0
        for (t, e), amt in divs.items():
            prev = [d for d in rec.dates if d < e]
            if prev:
                income += rec.holdings_at(prev[-1]).get(t, 0.0) * amt
        cap = float(rec.conventions.initial_cash) or 1.0
        tr_tol = tolerances(pkg)["total_return"]
        rec_tr = metrics.total_return(rec.nav)
        decl = float(pkg.declared["total_return"])
        ev = [{"return_basis": basis, "declared_total_return": decl, "reconstructed_price_return": round(rec_tr, 6),
               "dividend_income_over_capital": round(income / cap, 6), "prices_adjusted_flags": sorted(adj_flags)}]
        if basis == "total" and adj_flags == {False} and income / cap > tr_tol and abs(decl - rec_tr) <= tr_tol:
            findings.append((CONFIRMED_ERROR, "Declared total return equals the price return",
                             f"declared_results says return_basis = total, prices are unadjusted and the declared "
                             f"total_return ({decl:+.4f}) is reproduced without the dividends held over ex-dates "
                             f"({income / cap:.2%} of capital).", ev))
        elif basis == "price" and adj_flags == {True} and income / cap > tr_tol:
            findings.append((NEEDS_REVIEW, "Declared price return valued with adjusted prices",
                             "declared_results says return_basis = price but prices.csv is flagged adjusted: if the "
                             "adjustment includes dividends the result is a total return.", ev))
    res.metrics["dividend_corporate_actions"] = {"applied": len(applied), "not_applied": len(not_applied),
                                                 "mismatch": len(mismatch), "breaks": len(breaks),
                                                 "frozen": len(frozen), "undiscriminable": len(undiscriminable)}
    proc = ("Ratio R_t = adjusted close (prices.csv) / as-traded close (unadjusted_prices.csv) per ticker on common "
            "dates; step R_t / R_{t-1} compared with 1 / (1 - D / C_{t-1}) for a cash dividend and with the ratio for "
            f"a split, tolerance {tol:g} (conventions.adjustment_tolerance); events whose expected step is within "
            f"2 x tolerance are not discriminable. Frozen: identical adjusted closes for >= {stale_n} sessions from an "
            "event date (conventions.stale_after_event).")
    if not raw:
        proc += " Without unadjusted_prices.csv only the frozen-after-event test runs."
    ins = ["prices", "unadjusted_prices", "dividends", "corporate_actions"]
    for st, ttl, det, ev in findings:
        res.add("dividend_corporate_actions", BLOCK, st, ttl, det, ev, proc,
                action="Reload the affected rows after the vendor applies the event and re-adjust the history; "
                       "value positions with the corrected series.",
                priority="high" if st == CONFIRMED_ERROR else "medium", inputs=ins)
    if not findings:
        res.add("dividend_corporate_actions", BLOCK, PASS, "Adjusted series consistent with the declared events",
                f"{len(applied)} declared events applied with the expected step, no unexplained ratio break and no "
                f"price frozen after an event ({len(div_events)} dividend events checked"
                + (f", {len(undiscriminable)} too small to discriminate" if undiscriminable else "") + ")."
                + ("" if raw else " Ex-day application not verifiable without unadjusted_prices.csv."),
                [{"applied": len(applied), "undiscriminable": len(undiscriminable)}] + applied[:10], proc, inputs=ins)

