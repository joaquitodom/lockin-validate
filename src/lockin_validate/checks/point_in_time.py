"""Point-in-time and look-ahead checks.

Check ids:
  pit_fundamentals  coherence of fundamentals dates: period_end, filing_date (publication) and
                    available_from (moment from which the strategy's data store exposes the value).
  lookahead         signals that use a datum available only after the decision time, plus a
                    statistical hint (signal vs subsequent return) for gross cases without timestamps.

Semantics (docs/CONVENTIONS.md, section 3): the availability of a fundamentals row is
``max(filing_date, available_from)`` when both exist, otherwise whichever exists. A signal uses
future information when that availability is later than its ``decision_time``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package, review_date
from . import missing_inputs, not_executable

LAG_MIN_DAYS, LAG_MAX_DAYS = 20, 120
HINT_IC = 0.80  # mean rank correlation signal vs subsequent return considered implausible
HINT_MIN_DATES = 3


# ---------------------------------------------------------------------------- fundamentals PIT

def _availability(row: Any) -> pd.Timestamp | None:
    vals = [v for v in (getattr(row, "filing_date", None), getattr(row, "available_from", None))
            if v is not None and not pd.isna(v)]
    return max(vals) if vals else None


def check_pit_fundamentals(pkg: Package, res: AuditResult, today: date | None = None) -> None:
    title = "Point-in-time fundamentals"
    miss = pkg.missing("pit_fundamentals")
    if miss:
        missing_inputs(res, "pit_fundamentals", "data", title, miss)
        return
    f = pkg.df("fundamentals").dropna(subset=["ticker", "period_end"])
    has_filing = "filing_date" in f.columns and f["filing_date"].notna().any()
    has_avail = "available_from" in f.columns and f["available_from"].notna().any()
    ins = ["fundamentals"]
    found = False
    limit = review_date(pkg, today)
    fut = f[f["period_end"].dt.date > limit]
    if len(fut):
        res.add("pit_fundamentals", "data", CONFIRMED_ERROR, "Fundamentals with a period end after the review date",
                f"{len(fut)} rows with period_end after {limit}.",
                [{"row": int(r.row), "ticker": r.ticker, "period_end": r.period_end.date().isoformat()}
                 for r in fut.itertuples()], "period_end > review date.",
                action="Remove or quarantine rows with future dates.", priority="high", inputs=ins)
        found = True
    if not has_filing and not has_avail:
        res.add("pit_fundamentals", "data", NEEDS_REVIEW, "Fundamentals without publication or availability dates",
                "fundamentals.csv has neither filing_date nor available_from: there is no point-in-time information, "
                "so the backtest may have seen each value at its period end, weeks before it was published.",
                [{"rows": int(len(f))}], "Search for non-empty filing_date / available_from columns.",
                action="Add the filing date of the original report (and the date the backtest could see it).",
                priority="high", inputs=ins)
        return
    rows_missing = []
    impossible, early_use, fast, slow = [], [], [], []
    for r in f.itertuples():
        fd = getattr(r, "filing_date", None) if has_filing else None
        av = getattr(r, "available_from", None) if has_avail else None
        fd = None if fd is None or pd.isna(fd) else fd
        av = None if av is None or pd.isna(av) else av
        if fd is None and av is None:
            rows_missing.append({"row": int(r.row), "ticker": r.ticker, "period_end": r.period_end.date().isoformat()})
            continue
        pub = fd if fd is not None else av
        lag = (pub.normalize() - r.period_end.normalize()).days
        base = {"row": int(r.row), "ticker": r.ticker, "period_end": r.period_end.date().isoformat()}
        if fd is not None:
            base["filing_date"] = fd.isoformat()
        if av is not None:
            base["available_from"] = av.isoformat()
        if lag < 0:
            impossible.append(dict(base, lag_days=lag))
        elif lag < LAG_MIN_DAYS:
            fast.append(dict(base, lag_days=lag))
        elif lag > LAG_MAX_DAYS:
            slow.append(dict(base, lag_days=lag))
        if fd is not None and av is not None and av < fd:
            early_use.append(dict(base, days_before_publication=round((fd - av).total_seconds() / 86400, 2)))
    if impossible:
        res.add("pit_fundamentals", "data", CONFIRMED_ERROR, "Publication date earlier than the period end (impossible)",
                f"{len(impossible)} rows published before the period they report on closed: crossed columns or a load "
                "error, and an open door to look-ahead.", impossible,
                "filing_date (or available_from) - period_end < 0 per row.",
                action="Review the column mapping and reload those rows from the source.", priority="high", inputs=ins)
        found = True
    if early_use:
        res.add("pit_fundamentals", "data", CONFIRMED_ERROR, "Fundamentals available to the strategy BEFORE publication",
                f"{len(early_use)} rows with available_from earlier than filing_date: the strategy could use a value "
                "the market did not know yet (look-ahead).", early_use, "available_from < filing_date per row.",
                action="Make the data store expose each row only from filing_date (ideally the next session).",
                priority="high", inputs=ins)
        found = True
    if rows_missing:
        res.add("pit_fundamentals", "data", NEEDS_REVIEW, "Fundamentals rows without publication date",
                f"{len(rows_missing)} rows have neither filing_date nor available_from.", rows_missing,
                "Empty filing_date and available_from per row.",
                action="Fill the publication date from the original filing.", priority="medium", inputs=ins)
        found = True
    if fast:
        res.add("pit_fundamentals", "data", NEEDS_REVIEW,
                f"Publication lag shorter than {LAG_MIN_DAYS} days (date probably mis-assigned)",
                f"{len(fast)} rows. A real annual or quarterly report is almost never public that fast; lag 0 usually "
                "means the period end was copied as the publication date.", fast,
                "publication date - period_end in days.", action="Check against the original filing date.",
                priority="high", inputs=ins)
        found = True
    if slow:
        res.add("pit_fundamentals", "data", NEEDS_REVIEW, f"Publication lag longer than {LAG_MAX_DAYS} days",
                f"{len(slow)} rows. Safe direction (it delays visibility) but it can be the date of an amendment with "
                "restated values the market did not know at the time.", slow,
                "publication date - period_end in days.",
                action="Keep the original value with its date and the amendment as a separate vintage.",
                priority="low", inputs=ins)
        found = True
    if not found:
        res.add("pit_fundamentals", "data", PASS, "Fundamentals dates coherent",
                f"{len(f)} rows: publication after period end with a plausible lag"
                + ("; available_from never earlier than filing_date" if has_filing and has_avail else "")
                + ". Scope: internal coherence only; dates are not checked against the regulator's filing index.",
                [], "Per-row comparison of period_end, filing_date and available_from.", inputs=ins)


# ---------------------------------------------------------------------------- look-ahead

def anticipation_hint(pkg: Package) -> dict[str, Any] | None:
    """Spearman correlation between the signal of each decision date and the SUBSEQUENT return.

    Subsequent return: from the close of the decision day to the close of the next decision date (or 20 sessions
    later for the last one). A legitimate signal has small correlations (around 0.05); a mean close to 1 hints that
    the signal was computed with the future, whatever data_date says.
    """
    sig, px = pkg.df("signals"), pkg.df("prices")
    if sig is None or px is None:
        return None
    s = sig.dropna(subset=["decision_time", "ticker", "signal"]).copy()
    s["day"] = s["decision_time"].dt.date
    p = px.dropna(subset=["date", "ticker", "close"]).drop_duplicates(["ticker", "date"])
    closes = {t: dict(zip(g["date"].dt.date, g["close"])) for t, g in p.groupby("ticker")}
    price_dates = sorted(set(p["date"].dt.date))
    decisions = sorted(set(s["day"]))
    order = str(((pkg.rules or {}).get("signal") or {}).get("order", "desc")).lower() if pkg.rules else "desc"
    ics = []
    for k, d in enumerate(decisions):
        start = next((f for f in price_dates if f >= d), None)
        if start is None:
            continue
        if k + 1 < len(decisions):
            end = next((f for f in price_dates if f >= decisions[k + 1]), None)
        else:
            i = price_dates.index(start)
            end = price_dates[min(i + 20, len(price_dates) - 1)]
        if end is None or end == start:
            continue
        g = s[s["day"] == d]
        pairs = [(float(r.signal), closes[r.ticker][end] / closes[r.ticker][start] - 1) for r in g.itertuples()
                 if r.ticker in closes and start in closes[r.ticker] and end in closes[r.ticker]]
        if len(pairs) < 3:
            continue
        df = pd.DataFrame(pairs, columns=["signal", "future"])
        ic = df["signal"].rank().corr(df["future"].rank())
        if pd.notna(ic):
            ics.append({"decision_date": d.isoformat(), "ic": round(float(ic) * (1 if order == "desc" else -1), 4),
                        "n": len(pairs)})
    if len(ics) < HINT_MIN_DATES:
        return {"evaluable": False, "ics": ics}
    mean = sum(x["ic"] for x in ics) / len(ics)
    return {"evaluable": True, "mean_ic": mean, "ics": ics, "hint": mean >= HINT_IC}


def check_lookahead(pkg: Package, res: AuditResult) -> None:
    title = "Future information in the signals"
    miss = pkg.missing("lookahead")
    hint = anticipation_hint(pkg)
    if hint is not None:
        res.metrics["anticipation_hint"] = hint
    if hint and hint.get("hint"):
        res.add("lookahead", "strategy", NEEDS_REVIEW,
                "Hint of future information: the signal anticipates the subsequent return almost perfectly",
                f"Mean rank correlation between the signal and the return after the decision: {hint['mean_ic']:.2f} over "
                f"{len(hint['ics'])} dates (a legitimate signal is usually around 0.05). The declared dates are not "
                "enough to rule out that the signal uses data after the decision.", hint["ics"],
                "Spearman per decision date between signal and the return from the decision close to the next decision "
                f"close; hint threshold {HINT_IC:g}.",
                action="Ask for the signal code or formula and recompute it with data up to t-1.", priority="high",
                inputs=["signals", "prices"])
    if miss:
        not_executable(res, "lookahead", "strategy", title,
                       "missing: " + ", ".join(miss) + ". Without the availability timestamp of each datum "
                       "(available_from / filing_date) and the date of the datum each signal used (data_date) it "
                       "cannot be proven whether a decision used information that did not exist yet.",
                       "Add available_from to prices.csv or filing_date/available_from to fundamentals.csv, and "
                       "data_date to signals.csv.")
        return
    sig = pkg.df("signals").dropna(subset=["decision_time", "ticker", "data_date"])
    sources: dict[str, dict[tuple[str, date], pd.Timestamp]] = {}
    px = pkg.df("prices")
    if px is not None and "available_from" in px.columns and px["available_from"].notna().any():
        d = px.dropna(subset=["date", "ticker", "available_from"])
        sources["prices"] = {(t, f.date()): a for t, f, a in zip(d["ticker"], d["date"], d["available_from"])}
    fu = pkg.df("fundamentals")
    if fu is not None:
        m: dict[tuple[str, date], pd.Timestamp] = {}
        for r in fu.dropna(subset=["ticker", "period_end"]).itertuples():
            a = _availability(r)
            if a is not None:
                m[(r.ticker, r.period_end.date())] = a
        if m:
            sources["fundamentals"] = m
    future, no_datum = [], 0
    for r in sig.itertuples():
        key = (r.ticker, r.data_date.date())
        src = str(getattr(r, "data_source", "") or "").lower() if "data_source" in sig.columns else ""
        order = [src] if src in sources else list(sources)
        avail = None
        for s in order:
            if key in sources[s]:
                avail = (s, sources[s][key])
                break
        if avail is None:
            no_datum += 1
            continue
        if avail[1] > r.decision_time:
            future.append({"row": int(r.row), "ticker": r.ticker, "decision_time": r.decision_time.isoformat(),
                           "data_date": r.data_date.date().isoformat(), "source": avail[0],
                           "available_from": avail[1].isoformat(),
                           "hours_early": round((avail[1] - r.decision_time).total_seconds() / 3600, 2)})
    proc = ("For each signal: (ticker, data_date) -> availability in prices.csv (available_from) or fundamentals.csv "
            "(max of filing_date and available_from); error if availability > decision_time.")
    ins = ["signals", "prices", "fundamentals"]
    if future:
        res.add("lookahead", "strategy", CONFIRMED_ERROR, "Signals that use data available after the decision",
                f"{len(future)} of {len(sig)} signals use a datum that became available after the decision time"
                + (f" ({no_datum} signals without availability data, not evaluated)." if no_datum else "."), future,
                proc, action="Recompute the signals using only data available at or before the decision and rerun "
                             "the backtest.", priority="high", inputs=ins)
    elif no_datum == len(sig):
        not_executable(res, "lookahead", "strategy", title,
                       "no signal has its (ticker, data_date) in the tables with availability timestamps",
                       "Align data_date with the dates of prices / the period_end of fundamentals.")
    else:
        if hint and hint.get("hint"):
            return
        res.add("lookahead", "strategy", PASS,
                "No early use of data according to the declared dates (data_date and availability)",
                f"{len(sig) - no_datum} signals evaluated: according to data_date and the availability timestamps, all "
                "use data available before the decision. Scope: the data_date declared by the strategy owner is "
                "trusted; the hint test (correlation with the subsequent return) "
                + (f"gives {hint['mean_ic']:.2f}, no hint" if hint and hint.get("evaluable") else "was not evaluable")
                + (f" ({no_datum} without availability data, not evaluated)." if no_datum else "."), [], proc,
                inputs=ins)
