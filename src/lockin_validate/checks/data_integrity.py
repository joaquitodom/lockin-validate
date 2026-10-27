"""Data integrity checks.

Check ids: duplicates, dates, essential_fields, coverage, trade_before_signal,
signal_data_after_decision, stale_prices, price_jumps, corporate_actions, reference_accuracy.

Nothing is fixed. Each check diagnoses, proposes a fix (logged as a NOT applied transformation)
and, when another block needs a usable table, the derivation is logged as an applied
transformation.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package, review_date
from . import missing_inputs, not_executable

BLOCK = "data"
SPLIT_LIKE = [2, 3, 4, 5, 10, 20, 1.5, 0.5, 1 / 3, 0.25, 0.2, 0.1, 0.05, 2 / 3]
SPIKE_REVERT = 0.25
REF_TOL_DAILY = 0.005  # absolute difference of daily returns vs the reference
REF_MISMATCH_RATE = 0.01  # a ticker "matches" if fewer than 1% of its days differ...
REF_GROSS_ERROR = 0.10  # ...and no single day differs by more than 10 points


def _iso(x) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return None
    return x.isoformat()


# ---------------------------------------------------------------------------- duplicates

def check_duplicates(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("duplicates")
    if miss:
        missing_inputs(res, "duplicates", BLOCK, "Duplicates", miss)
        return
    found = False
    px = pkg.df("prices")
    d = px.dropna(subset=["ticker", "date"])
    mask = d.duplicated(["ticker", "date"], keep=False)
    if mask.any():
        dup = d[mask].sort_values(["ticker", "date", "row"])
        ev, conflicting = [], 0
        for (t, f), g in dup.groupby(["ticker", "date"]):
            closes = sorted({round(float(x), 8) for x in g["close"].dropna()})
            conflict = len(closes) > 1
            conflicting += int(conflict)
            ev.append({"ticker": t, "date": f.date().isoformat(), "rows": [int(x) for x in g["row"]],
                       "closes": closes, "conflict": conflict})
        n_extra = int(d.duplicated(["ticker", "date"]).sum())
        res.add("duplicates", BLOCK, CONFIRMED_ERROR, "prices.csv: duplicated (ticker, date) rows",
                f"{len(ev)} repeated (ticker, date) pairs, {n_extra} extra rows; {conflicting} with different "
                "closes. With two prices for the same day the valuation depends on file order.",
                ev, "df.duplicated([ticker, date], keep=False) on prices.csv; CSV lines and closes of each group "
                    "are listed.",
                action="Keep one row per (ticker, date). If closes differ, decide which is right with the original "
                       "source.", priority="high", inputs=["prices"])
        pkg.log.propose("prices", "drop_duplicates(ticker, date)", "duplicates found by the check",
                        {"rows": int(len(d))}, {"rows": int(len(d) - n_extra)},
                        rows=[int(x) for x in d[d.duplicated(["ticker", "date"])]["row"]])
        found = True
    tr = pkg.df("trades")
    if tr is not None:
        keys = ["timestamp", "ticker", "side", "quantity", "price"]
        d = tr.dropna(subset=keys)
        mask = d.duplicated(keys, keep=False)
        if mask.any():
            dup = d[mask]
            ev = [{"ticker": g["ticker"].iloc[0], "timestamp": k[0].isoformat(), "side": g["side"].iloc[0],
                   "quantity": float(g["quantity"].iloc[0]), "price": float(g["price"].iloc[0]),
                   "rows": [int(x) for x in g["row"]]}
                  for k, g in dup.groupby(keys)]
            same_id = "trade_id" in d.columns and bool(d[mask].duplicated(keys + ["trade_id"], keep=False).any())
            status = CONFIRMED_ERROR if same_id or "trade_id" not in d.columns else NEEDS_REVIEW
            res.add("duplicates", BLOCK, status, "trades.csv: repeated trades",
                    f"{len(ev)} trades appear more than once with the same timestamp, ticker, side, quantity and "
                    "price. Two legitimate partial fills should have different trade ids; otherwise the "
                    "reconstruction counts the trade twice.",
                    ev, "df.duplicated([timestamp, ticker, side, quantity, price], keep=False).",
                    action="Confirm with the broker record; if duplicated, remove them and recompute the result.",
                    priority="high", inputs=["trades"])
            found = True
    sig = pkg.df("signals")
    if sig is not None:
        d = sig.dropna(subset=["decision_time", "ticker"])
        mask = d.duplicated(["decision_time", "ticker"], keep=False)
        if mask.any():
            dup = d[mask]
            ev = [{"ticker": t, "decision_time": ts.isoformat(), "rows": [int(x) for x in g["row"]],
                   "signals": sorted({round(float(x), 8) for x in g["signal"].dropna()})}
                  for (ts, t), g in dup.groupby(["decision_time", "ticker"])]
            conflict = any(len(e["signals"]) > 1 for e in ev)
            res.add("duplicates", BLOCK, CONFIRMED_ERROR if conflict else NEEDS_REVIEW,
                    "signals.csv: repeated signal for the same (decision_time, ticker)",
                    f"{len(ev)} repeated pairs" + (" with different values." if conflict else " with the same value."),
                    ev, "df.duplicated([decision_time, ticker], keep=False).",
                    action="Keep one signal per ticker and decision time.", priority="medium", inputs=["signals"])
            found = True
    pos = pkg.df("positions")
    if pos is not None:
        d = pos.dropna(subset=["date", "ticker"])
        mask = d.duplicated(["date", "ticker"], keep=False)
        if mask.any():
            dup = d[mask]
            ev = [{"ticker": t, "date": f.date().isoformat(), "rows": [int(x) for x in g["row"]],
                   "quantities": sorted({float(x) for x in g["quantity"].dropna()})}
                  for (f, t), g in dup.groupby(["date", "ticker"])]
            res.add("duplicates", BLOCK, CONFIRMED_ERROR, "positions.csv: repeated (date, ticker) position",
                    f"{len(ev)} repeated pairs.", ev, "df.duplicated([date, ticker], keep=False).",
                    action="Keep one row per date and ticker.", priority="medium", inputs=["positions"])
            found = True
    if not found:
        res.add("duplicates", BLOCK, PASS, "No duplicates",
                "No repeated (ticker, date) in prices and no repeated trades, signals or positions.", [],
                "df.duplicated on the natural keys of each table.", inputs=list(pkg.tables))


# ---------------------------------------------------------------------------- dates

def check_dates(pkg: Package, res: AuditResult, today: date | None = None) -> None:
    miss = pkg.missing("dates")
    if miss:
        missing_inputs(res, "dates", BLOCK, "Inconsistent or impossible dates", miss)
        return
    limit = review_date(pkg, today)
    cal = pkg.calendar()
    found = False
    if not cal.declared:
        res.add("dates", BLOCK, NEEDS_REVIEW, "Market calendar not declared",
                "rules.yaml does not declare conventions.calendar (and the profile does not set one). No market is "
                "presumed: only weekends are checked (as review items) and non-trading days cannot be confirmed "
                "as errors.",
                [{"conventions.calendar": None, "options": ["nyse", "byma", "none"]}],
                "Read conventions.calendar from rules.yaml and the selected profile.",
                action="Declare the market calendar (nyse, byma or none).", priority="medium", inputs=["rules"])
        found = True
    date_tables = [("prices", "date"), ("trades", "timestamp"), ("signals", "decision_time"), ("positions", "date")]
    for name, col in date_tables:
        df = pkg.df(name)
        if df is None or col not in df.columns:
            continue
        d = df.dropna(subset=[col])
        fut = d[d[col].dt.date > limit]
        if len(fut):
            ev = [{"row": int(r.row), "ticker": getattr(r, "ticker", None), col: getattr(r, col).isoformat()}
                  for r in fut.itertuples()]
            res.add("dates", BLOCK, CONFIRMED_ERROR, f"{name}.csv: future dates (after the review date {limit})",
                    f"{len(fut)} rows dated after {limit}.", ev,
                    f"`{col}` compared with the review date ({limit}; conventions.review_date or today).",
                    action="Fix the dates or explain why there is data after the review date.", priority="high",
                    inputs=[name])
            found = True
        if cal.name != "none" and name in ("prices", "trades"):
            off = d[[not cal.is_session(x.date()) for x in d[col]]]
            if len(off):
                ev = [{"row": int(r.row), "ticker": getattr(r, "ticker", None), col: getattr(r, col).isoformat(),
                       "weekday": getattr(r, col).strftime("%A")} for r in off.itertuples()]
                if cal.declared:
                    res.add("dates", BLOCK, CONFIRMED_ERROR, f"{name}.csv: dates that are not sessions ({cal.name} calendar)",
                            f"{len(off)} rows on days without a session according to the declared calendar "
                            f"(conventions.calendar = {cal.name}, declared in {cal.declared_by}"
                            + (f", holidays from {cal.source}" if cal.source else "") + ").", ev,
                            f"is_session(date) of the {cal.name} calendar on every row.",
                            action="Check the time zone or the source; if the market is another one, declare the "
                                   "right calendar.", priority="high", inputs=[name, "rules"])
                else:
                    res.add("dates", BLOCK, NEEDS_REVIEW, f"{name}.csv: weekend dates",
                            f"{len(off)} rows on a Saturday or Sunday. Without a declared calendar this cannot be "
                            "confirmed as an error (some markets trade on weekends).", ev, "weekday(date) >= 5.",
                            action="Declare the calendar and review those rows.", priority="medium", inputs=[name])
                found = True
            if cal.name == "byma" and name == "prices":
                uncovered = sorted({x.year for x in d[col] if not cal.covers(x.date())})
                if uncovered:
                    res.add("dates", BLOCK, NEEDS_REVIEW, "BYMA calendar without holidays for some years",
                            f"{cal.source} does not cover the years {uncovered}: there only weekends are checked.",
                            [{"years_without_holidays": uncovered, "file": cal.source}],
                            "Years present in the holiday file.",
                            action="Complete the BYMA holiday file (conventions.holidays_file).", priority="medium",
                            inputs=["prices", "rules"])
                    found = True
    px = pkg.df("prices")
    d = px.dropna(subset=["date", "ticker"])
    ordered = d.sort_values(["ticker", "date", "row"])
    if not (ordered["row"].to_numpy() == np.sort(ordered["row"].to_numpy())).all():
        pkg.log.applied("prices", "sort(ticker, date)", "working table sorted for the checks",
                        {"order": "file"}, {"order": "ticker, date"})
    bad = d[d["close"].notna() & (d["close"] <= 0)]
    if len(bad):
        ev = [{"row": int(r.row), "ticker": r.ticker, "date": r.date.date().isoformat(), "close": float(r.close)}
              for r in bad.itertuples()]
        res.add("dates", BLOCK, CONFIRMED_ERROR, "prices.csv: non-positive closes", f"{len(bad)} rows with close <= 0.",
                ev, "close <= 0.", action="Fix or remove those rows using the original source.", priority="high",
                inputs=["prices"])
        found = True
    if {"open", "high", "low", "close"} <= set(d.columns):
        o = d.dropna(subset=["open", "high", "low", "close"])
        inc = o[(o["low"] > o[["open", "close"]].min(axis=1) * 1.0001) |
                (o["high"] < o[["open", "close"]].max(axis=1) * 0.9999) | (o["low"] > o["high"])]
        if len(inc):
            ev = [{"row": int(r.row), "ticker": r.ticker, "date": r.date.date().isoformat(), "open": float(r.open),
                   "high": float(r.high), "low": float(r.low), "close": float(r.close)} for r in inc.itertuples()]
            res.add("dates", BLOCK, CONFIRMED_ERROR, "prices.csv: inconsistent OHLC",
                    f"{len(inc)} rows with low > min(open, close), high < max(open, close) or low > high.", ev,
                    "Vectorised comparison of open/high/low/close per row (0.01% tolerance).",
                    action="Review the price source.", priority="medium", inputs=["prices"])
            found = True
    tr = pkg.df("trades")
    if tr is not None:
        ts = tr["timestamp"].dropna()
        if len(ts) > 1 and not ts.is_monotonic_increasing:
            t2 = tr.dropna(subset=["timestamp"])
            out_of_order = t2[t2["timestamp"] < t2["timestamp"].cummax()]
            res.add("dates", BLOCK, NEEDS_REVIEW, "trades.csv: trades out of chronological order",
                    f"{len(out_of_order)} rows with a timestamp earlier than a previous row. The reconstruction "
                    "sorts them by timestamp (logged transformation).",
                    [{"row": int(r.row), "timestamp": r.timestamp.isoformat()} for r in out_of_order.itertuples()],
                    "timestamp < running maximum of timestamp in file order.",
                    action="Deliver trades in chronological order.", priority="low", inputs=["trades"])
            found = True
    if not found:
        res.add("dates", BLOCK, PASS, "Dates consistent",
                f"No future dates (limit {limit}), no non-session days"
                + (f" ({cal.name} calendar)" if cal.name != "none" else " (calendar: none, not required)")
                + ", no non-positive closes and no inconsistent OHLC.", [],
                "Row-wise comparison against review date, calendar and OHLC range.",
                inputs=[n for n, _ in date_tables if pkg.has(n)])


# ---------------------------------------------------------------------------- essential fields

ESSENTIAL = {"prices": ["date", "ticker", "close"], "trades": ["timestamp", "ticker", "side", "quantity", "price"],
             "signals": ["decision_time", "ticker", "signal"], "positions": ["date", "ticker", "quantity"]}


def check_essential_fields(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("essential_fields")
    if miss:
        missing_inputs(res, "essential_fields", BLOCK, "Missing essential fields", miss)
        return
    found = False
    for name, cols in ESSENTIAL.items():
        t = pkg.tables.get(name)
        if t is None:
            continue
        for c in cols:
            if c not in t.work.columns:
                continue
            orig = next((k for k, v in t.renames.items() if v == c), c)
            lower = {str(x).strip().lower(): x for x in t.original.columns}
            if orig not in lower:
                continue
            empty = t.original[lower[orig]].astype(str).to_numpy() == ""
            rows = t.work[empty]
            if len(rows):
                found = True
                res.add("essential_fields", BLOCK, CONFIRMED_ERROR, f"{name}.csv: empty values in `{c}`",
                        f"{len(rows)} rows without `{c}`. Those rows cannot be used.",
                        [{"row": int(x), "column": c} for x in rows["row"]],
                        "Empty cells in the original CSV (before any coercion).",
                        action="Fill the field or remove the row with a justification.", priority="high",
                        inputs=[name])
    if not found:
        res.add("essential_fields", BLOCK, PASS, "Essential fields complete",
                "No empty cell in the essential fields of the tables present.", [],
                "Search for empty cells in the original CSV.", inputs=list(pkg.tables))


# ---------------------------------------------------------------------------- coverage

def check_coverage(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("coverage")
    if miss:
        missing_inputs(res, "coverage", BLOCK, "Price coverage", miss)
        return
    px = pkg.df("prices").dropna(subset=["date", "ticker"])
    found = False
    dates_by_ticker = {t: set(g["date"].dt.date) for t, g in px.groupby("ticker")}
    all_dates = sorted(set(px["date"].dt.date))
    tr = pkg.df("trades")
    if tr is not None:
        o = tr.dropna(subset=["timestamp", "ticker"])
        no_series = sorted(set(o["ticker"]) - set(dates_by_ticker))
        if no_series:
            ev = [{"ticker": t, "trades": int((o["ticker"] == t).sum()),
                   "rows": [int(x) for x in o[o["ticker"] == t]["row"]][:10]} for t in no_series]
            res.add("coverage", BLOCK, NEEDS_REVIEW, "Missing history: traded tickers without any row in prices.csv",
                    f"{len(no_series)} traded tickers have no prices. This is a SCOPE finding: it is not repaired; the "
                    "reconstruction cannot value those positions and says so.",
                    ev, "set(tickers in trades) - set(tickers in prices).",
                    action="Provide the price series of those tickers.", priority="high", inputs=["prices", "trades"])
            found = True
        no_date = [{"row": int(r.row), "ticker": r.ticker, "date": r.timestamp.date().isoformat()}
                   for r in o.itertuples()
                   if r.ticker in dates_by_ticker and r.timestamp.date() not in dates_by_ticker[r.ticker]]
        if no_date:
            res.add("coverage", BLOCK, CONFIRMED_ERROR, "Trades on dates without a price for that ticker",
                    f"{len(no_date)} trades on a date for which prices.csv has no close of the ticker. Valuation "
                    "that day uses the last available close (logged).", no_date,
                    "For each trade: date(timestamp) in the price dates of the ticker.",
                    action="Complete prices.csv on those dates or explain the gap.", priority="high",
                    inputs=["prices", "trades"])
            found = True
    cal = pkg.calendar()
    if all_dates:
        gaps = []
        for t, ds in dates_by_ticker.items():
            lo, hi = min(ds), max(ds)
            if cal.full_calendar:
                expected = [d for d in cal.sessions(lo, hi) if cal.covers(d)]
                basis = f"{cal.name} sessions"
            else:
                expected = [d for d in all_dates if lo <= d <= hi and cal.is_session(d)]
                basis = "session dates present in the file for other tickers"
            gap = [d for d in expected if d not in ds]
            if gap:
                gaps.append({"ticker": t, "missing_sessions": len(gap), "from": lo.isoformat(), "to": hi.isoformat(),
                             "examples": [d.isoformat() for d in gap[:5]]})
        if gaps:
            res.add("coverage", BLOCK, NEEDS_REVIEW, "Session gaps inside price series",
                    f"{len(gaps)} tickers with missing sessions between their first and last date (expected "
                    f"sessions: {basis}).", gaps,
                    f"Expected sessions ({basis}) absent for the ticker.",
                    action="Fill the missing sessions or justify them (suspension, later listing).",
                    priority="medium", inputs=["prices"])
            found = True
    period = (pkg.rules or {}).get("period") if pkg.rules else None
    if isinstance(period, dict) and all_dates:
        try:
            start = pd.Timestamp(str(period.get("start"))).date()
            end = pd.Timestamp(str(period.get("end"))).date()
        except Exception:
            start = end = None
        if start and end and (all_dates[0] > start or all_dates[-1] < end):
            res.add("coverage", BLOCK, NEEDS_REVIEW, "Prices do not cover the whole declared period",
                    f"rules.yaml declares {start} to {end}; prices.csv goes from {all_dates[0]} to {all_dates[-1]}. "
                    "Scope finding: what falls outside cannot be reconstructed.",
                    [{"declared_start": start.isoformat(), "declared_end": end.isoformat(),
                      "prices_start": all_dates[0].isoformat(), "prices_end": all_dates[-1].isoformat()}],
                    "Price date range compared with rules.period.",
                    action="Provide prices for the whole declared period.", priority="high", inputs=["prices", "rules"])
            found = True
    if not found:
        res.add("coverage", BLOCK, PASS, "Price coverage sufficient",
                "Every traded ticker has a price on its trade dates; no session gaps; the declared period is "
                "covered.", [], "Tickers/dates of trades crossed with prices and the calendar.",
                inputs=["prices"] + (["trades"] if tr is not None else []))


# ---------------------------------------------------------------------------- temporal consistency

def check_temporal(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("trade_before_signal")
    if miss:
        missing_inputs(res, "trade_before_signal", BLOCK, "Trade before its signal", miss)
    else:
        tr = pkg.df("trades").dropna(subset=["timestamp", "ticker"])
        sig = pkg.df("signals").dropna(subset=["decision_time", "ticker"])
        by_ticker = {t: sorted(g["decision_time"]) for t, g in sig.groupby("ticker")}
        before, no_signal = [], []
        for r in tr[tr["side"] == "buy"].itertuples():
            ts = by_ticker.get(r.ticker)
            if not ts:
                no_signal.append({"row": int(r.row), "ticker": r.ticker, "timestamp": r.timestamp.isoformat()})
                continue
            if not [x for x in ts if x <= r.timestamp]:
                before.append({"row": int(r.row), "ticker": r.ticker, "trade_time": r.timestamp.isoformat(),
                               "first_signal": min(ts).isoformat()})
        if before:
            res.add("trade_before_signal", BLOCK, CONFIRMED_ERROR, "Buys executed before the first signal of the ticker",
                    f"{len(before)} buys timestamped before any signal of that ticker. The trade cannot come from the "
                    "delivered signals.", before,
                    "For each buy, search a signal of the same ticker with decision_time <= trade timestamp.",
                    action="Review the order of signal and execution; fix the timestamps.", priority="high",
                    inputs=["trades", "signals"])
        elif no_signal:
            res.add("trade_before_signal", BLOCK, NEEDS_REVIEW, "Buys of tickers without any signal",
                    f"{len(no_signal)} buys of tickers absent from signals.csv.", no_signal,
                    "Tickers of buys not present in signals.", action="Provide the missing signals.",
                    priority="medium", inputs=["trades", "signals"])
        else:
            res.add("trade_before_signal", BLOCK, PASS, "Every buy has an earlier signal",
                    "Each buy has at least one signal of its ticker with decision_time earlier or equal.", [],
                    "Search of a previous signal per ticker.", inputs=["trades", "signals"])
    miss = pkg.missing("signal_data_after_decision")
    if miss:
        not_executable(res, "signal_data_after_decision", BLOCK, "Signal computed with data after its decision time",
                       "missing required inputs: " + ", ".join(miss)
                       + " (data_date = date of the data used by each signal)",
                       "Add a data_date column to signals.csv.")
        return
    sig = pkg.df("signals").dropna(subset=["decision_time", "ticker", "data_date"])
    post = sig[sig["data_date"] > sig["decision_time"]]
    if len(post):
        ev = [{"row": int(r.row), "ticker": r.ticker, "decision_time": r.decision_time.isoformat(),
               "data_date": r.data_date.isoformat()} for r in post.itertuples()]
        res.add("signal_data_after_decision", BLOCK, CONFIRMED_ERROR,
                "Signals computed with data dated after the decision",
                f"{len(post)} signals whose data_date is later than decision_time.", ev,
                "data_date > decision_time per row.",
                action="Recompute the signals with data dated <= decision only.", priority="high", inputs=["signals"])
    else:
        res.add("signal_data_after_decision", BLOCK, PASS, "Signals use data not later than the decision",
                "data_date <= decision_time for every signal.", [], "data_date > decision_time per row.",
                inputs=["signals"])


# ---------------------------------------------------------------------------- stale prices

def stale_runs(px: pd.DataFrame, minimum: int) -> list[dict]:
    """All runs of >= ``minimum`` identical consecutive closes per ticker."""
    out = []
    for t, g in px.sort_values(["ticker", "date"]).groupby("ticker"):
        c = g["close"].to_numpy(dtype=float)
        f = list(g["date"].dt.date)
        rows = list(g["row"])
        if len(c) < minimum:
            continue
        i = 0
        while i < len(c):
            j = i
            while j + 1 < len(c) and c[j + 1] == c[i]:
                j += 1
            n = j - i + 1
            if n >= minimum:
                out.append({"ticker": t, "sessions": int(n), "from": f[i].isoformat(), "to": f[j].isoformat(),
                            "close": float(c[i]), "rows": [int(rows[i]), int(rows[j])]})
            i = j + 1
    return out


def check_stale_prices(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("stale_prices")
    if miss:
        missing_inputs(res, "stale_prices", BLOCK, "Stale quotes (frozen price)", miss)
        return
    px = pkg.df("prices").dropna(subset=["date", "ticker", "close"]).drop_duplicates(["ticker", "date"])
    minimum = int(pkg.conv("stale_run"))
    runs = stale_runs(px, minimum)
    if not runs:
        res.add("stale_prices", BLOCK, PASS, "No frozen prices",
                f"No run of {minimum} or more identical consecutive closes.", [],
                "Scan of consecutive closes per ticker.", inputs=["prices"])
        return
    tr = pkg.df("trades")
    affected = []
    if tr is not None:
        o = tr.dropna(subset=["timestamp", "ticker"])
        for r in runs:
            d0, d1 = date.fromisoformat(r["from"]), date.fromisoformat(r["to"])
            g = o[o["ticker"] == r["ticker"]]
            hit = g[(g["timestamp"].dt.date >= d0) & (g["timestamp"].dt.date <= d1)]
            if len(hit):
                r = dict(r, trades_in_run=[int(x) for x in hit["row"]][:10])
                affected.append(r)
    if affected:
        res.add("stale_prices", BLOCK, CONFIRMED_ERROR, "Frozen price on dates when the strategy traded the ticker",
                f"{len(affected)} runs of {minimum}+ identical closes with trades inside: the quote used to value and "
                "trade was stale (stopped feed or terminal price).", affected,
                "Runs of identical consecutive closes per ticker crossed with trade dates.",
                action="Replace the series with a live source and recompute; if the asset stopped trading, declare it.",
                priority="high", inputs=["prices", "trades"])
    else:
        res.add("stale_prices", BLOCK, NEEDS_REVIEW, "Frozen price runs",
                f"{len(runs)} runs of {minimum}+ identical closes, without trades inside. It can be an illiquid "
                "asset or a stopped feed: it needs review.", runs, "Runs of identical consecutive closes per ticker.",
                action="Confirm with another source whether the price really did not change.", priority="medium",
                inputs=["prices"])


# ---------------------------------------------------------------------------- price jumps

def detect_jumps(px: pd.DataFrame, threshold: float) -> list[dict]:
    out = []
    d = px.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    for t, g in d.groupby("ticker"):
        c = [float(x) for x in g["close"]]
        f = list(g["date"].dt.date)
        rows = list(g["row"])
        for i in range(1, len(c)):
            if c[i - 1] <= 0:
                continue
            x = c[i] / c[i - 1]
            if abs(x - 1) > threshold:
                nxt = c[i + 1] / c[i] - 1 if i + 1 < len(c) and c[i] > 0 else None
                reverts = nxt is not None and abs(nxt) > SPIKE_REVERT and np.sign(nxt) != np.sign(x - 1)
                out.append({"row": int(rows[i]), "ticker": t, "date": f[i].isoformat(), "previous_close": c[i - 1],
                            "close": c[i], "return": round(x - 1, 4),
                            "split_like": bool(any(abs(x / k - 1) < 0.03 for k in SPLIT_LIKE)),
                            "reverts_next_day": bool(reverts)})
    return out


def check_price_jumps(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("price_jumps")
    if miss:
        missing_inputs(res, "price_jumps", BLOCK, "Split-like jumps and bad ticks", miss)
        return
    thr = float(pkg.conv("jump_threshold"))
    px = pkg.df("prices").dropna(subset=["date", "ticker", "close"])
    jumps = detect_jumps(px, thr)
    proc = (f"close_t / close_(t-1) - 1 per ticker on consecutive dates of the series; split-like if the ratio is "
            f"within 3% of 1/2, 1/3, 1/4, 1/5, 1/10, 2, 3, 4, 5, 10...; spike if the next day reverts by more than "
            f"{SPIKE_REVERT:.0%}. Threshold {thr:.0%} (conventions.jump_threshold).")
    if not jumps:
        res.add("price_jumps", BLOCK, PASS, f"No one-period price move larger than {thr:.0%}", "", [], proc,
                inputs=["prices"])
        return
    adjusted = "adjusted" in px.columns and bool(px["adjusted"].any())
    split_like = [j for j in jumps if j["split_like"] and not j["reverts_next_day"]]
    spikes = [j for j in jumps if j["reverts_next_day"]]
    res.add("price_jumps", BLOCK, NEEDS_REVIEW,
            f"Price moves larger than {thr:.0%} in one period" + (" with split-like ratios" if split_like else ""),
            f"{len(jumps)} jumps; {len(split_like)} with a split-like ratio"
            + (" in a series flagged as adjusted" if adjusted else "") + f"; {len(spikes)} one-day spikes that revert "
            "(probable bad tick). An unadjusted split makes the strategy see a gain or loss that never existed; real "
            "events (bankruptcy, acquisition) also cause jumps: they must be looked at.", jumps, proc,
            action="Confirm with the source whether there was a split or corporate action and adjust the series.",
            priority="high" if split_like or spikes else "medium", inputs=["prices"])


def check_corporate_actions(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("corporate_actions")
    if miss:
        missing_inputs(res, "corporate_actions", BLOCK, "Declared corporate actions reflected in prices", miss)
        return
    px = pkg.df("prices").dropna(subset=["date", "ticker", "close"]).drop_duplicates(["ticker", "date"])
    ca = pkg.df("corporate_actions").dropna(subset=["ticker", "date", "ratio"])
    adjusted_flag = None
    if "adjusted" in px.columns:
        adjusted_flag = bool(px["adjusted"].all())
    not_reflected, raw_split, unverifiable, ok = [], [], [], []
    for r in ca.itertuples():
        g = px[px["ticker"] == r.ticker].sort_values("date")
        dates = list(g["date"].dt.date)
        closes = [float(x) for x in g["close"]]
        d = r.date.date()
        after = [i for i, x in enumerate(dates) if x >= d]
        if not after or after[0] == 0 or float(r.ratio) <= 0:
            unverifiable.append({"row": int(r.row), "ticker": r.ticker, "date": d.isoformat(),
                                 "reason": "no prices on both sides of the action date"})
            continue
        i = after[0]
        x = closes[i] / closes[i - 1]
        ev = {"row": int(r.row), "ticker": r.ticker, "action_date": d.isoformat(), "ratio": float(r.ratio),
              "close_before": closes[i - 1], "close_after": closes[i], "price_ratio": round(x, 6)}
        if abs(x * float(r.ratio) - 1) < 0.03:
            (not_reflected if adjusted_flag else raw_split).append(ev)
        else:
            ok.append(ev)
    proc = ("For each declared action (ratio = new shares / old shares): first close on or after the action date "
            "divided by the previous close; the split is NOT reflected if that ratio is within 3% of 1/ratio.")
    if not_reflected:
        res.add("corporate_actions", BLOCK, CONFIRMED_ERROR, "Declared split not reflected in the adjusted price series",
                f"{len(not_reflected)} declared splits show the full 1/ratio price move in a series flagged as "
                "adjusted: the backtest sees a loss (or gain) that did not exist.", not_reflected, proc,
                action="Re-adjust the price history for those splits and rerun the backtest.", priority="high",
                inputs=["prices", "corporate_actions"])
    if raw_split:
        res.add("corporate_actions", BLOCK, NEEDS_REVIEW,
                "Split visible in a price series that is not flagged as adjusted",
                f"{len(raw_split)} declared splits appear as a 1/ratio move. With raw prices, positions must change "
                "by the ratio on that date; this toolkit does not apply corporate actions to the reconstruction.",
                raw_split, proc, action="Confirm how the backtest handles the split (adjusted prices or share "
                                        "adjustment).", priority="high", inputs=["prices", "corporate_actions"])
    if unverifiable:
        res.add("corporate_actions", BLOCK, NEEDS_REVIEW, "Declared corporate actions that cannot be verified",
                f"{len(unverifiable)} actions without prices on both sides of their date.", unverifiable, proc,
                action="Provide prices around those dates.", priority="low", inputs=["prices", "corporate_actions"])
    if not (not_reflected or raw_split or unverifiable):
        res.add("corporate_actions", BLOCK, PASS, "Declared corporate actions reflected in the price series",
                f"{len(ok)} declared actions; none shows an unadjusted 1/ratio move.", ok, proc,
                inputs=["prices", "corporate_actions"])


# ---------------------------------------------------------------------------- reference accuracy

def compare_returns(a: dict, b: dict, tol: float = REF_TOL_DAILY) -> dict:
    common = sorted(set(a) & set(b))
    diffs = []
    for d0, d1 in zip(common, common[1:]):
        if a[d0] > 0 and b[d0] > 0:
            ra, rb = a[d1] / a[d0] - 1, b[d1] / b[d0] - 1
            diffs.append((abs(ra - rb), d1, ra, rb))
    bad = sorted([x for x in diffs if x[0] > tol], key=lambda x: -x[0])
    return {"days": len(diffs), "days_differing": len(bad), "max_abs_diff": max((x[0] for x in diffs), default=0.0),
            "worst": [{"date": x[1].isoformat(), "return": round(x[2], 6), "reference_return": round(x[3], 6)}
                      for x in bad[:5]]}


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, float(centre - half)), min(1.0, float(centre + half)))


def check_reference_accuracy(pkg: Package, res: AuditResult) -> None:
    miss = pkg.missing("reference_accuracy")
    if miss:
        missing_inputs(res, "reference_accuracy", BLOCK, "Accuracy against an independent reference", miss)
        return
    px = pkg.df("prices").dropna(subset=["date", "ticker", "close"]).drop_duplicates(["ticker", "date"])
    ref = pkg.df("reference_prices").dropna(subset=["date", "ticker", "close"]).drop_duplicates(["ticker", "date"])
    rows, differ, no_overlap = [], [], []
    for t, g in ref.groupby("ticker"):
        mine = px[px["ticker"] == t]
        cmp = compare_returns(dict(zip(mine["date"].dt.date, mine["close"].astype(float))),
                              dict(zip(g["date"].dt.date, g["close"].astype(float))))
        if cmp["days"] == 0:
            no_overlap.append(t)
            continue
        gross = cmp["max_abs_diff"] > REF_GROSS_ERROR
        matches = cmp["days_differing"] / cmp["days"] <= REF_MISMATCH_RATE and not gross
        row = {"ticker": t, "matches": matches, **cmp}
        rows.append(row)
        if not matches:
            differ.append(row)
    proc = (f"Daily returns (not levels) on consecutive common dates compared per ticker; a day differs if the "
            f"absolute difference exceeds {REF_TOL_DAILY:g}; a ticker matches if under {REF_MISMATCH_RATE:.0%} of days "
            f"differ and no day differs by more than {REF_GROSS_ERROR:g}.")
    if not rows:
        not_executable(res, "reference_accuracy", BLOCK, "Accuracy against an independent reference",
                       "no common dates between prices.csv and reference_prices.csv",
                       "Provide a reference covering the same tickers and dates.")
        return
    lo, hi = wilson_interval(len(differ), len(rows))
    res.metrics["reference_accuracy"] = {"tickers_compared": len(rows), "tickers_differing": len(differ),
                                         "wilson_95": [lo, hi], "no_overlap": no_overlap}
    if differ:
        res.add("reference_accuracy", BLOCK, NEEDS_REVIEW, "Daily returns differ from the independent reference",
                f"{len(differ)} of {len(rows)} tickers differ (95% Wilson interval of the rate: {lo:.0%} to {hi:.0%})."
                + (f" {len(no_overlap)} reference tickers have no common dates and are NOT verified." if no_overlap
                   else "") + " Which source is right cannot be decided from the inputs.", differ, proc,
                action="Check the differing days against the primary source (exchange or vendor of record).",
                priority="high" if any(r["max_abs_diff"] > REF_GROSS_ERROR for r in differ) else "medium",
                inputs=["prices", "reference_prices"])
    else:
        res.add("reference_accuracy", BLOCK, PASS, "Daily returns match the independent reference",
                f"{len(rows)} tickers compared, all match"
                + (f"; {len(no_overlap)} without common dates are not verified" if no_overlap else "") + ".",
                rows, proc, inputs=["prices", "reference_prices"])


def run_data_checks(pkg: Package, res: AuditResult, today: date | None = None) -> None:
    check_duplicates(pkg, res)
    check_dates(pkg, res, today)
    check_essential_fields(pkg, res)
    check_coverage(pkg, res)
    check_temporal(pkg, res)
    check_stale_prices(pkg, res)
    check_price_jumps(pkg, res)
    check_corporate_actions(pkg, res)
    check_reference_accuracy(pkg, res)
