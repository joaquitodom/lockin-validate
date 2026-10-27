"""Survivorship and identity checks.

Check ids:
  survivorship     with universe.csv (point-in-time membership: ticker, start_date, end_date): members that left
                   the universe inside the price window must have prices up to their exit; trades outside
                   membership are listed.
  ticker_identity  with security_master.csv (ticker, entity_id, start_date, end_date): one ticker used by two
                   entities whose price series spans both (recycled ticker). Without a master only a heuristic runs
                   (long gap plus level shift), which can raise a review item but never a PASS.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from . import missing_inputs, not_executable

BLOCK = "data"
DELIST_TOL_DAYS = 10  # last price within 10 calendar days of the exit
GAP_RECYCLE_DAYS = 90  # internal gap of >= 90 calendar days...
LEVEL_SHIFT = 2.5  # ...with a level change x2.5 (or /2.5)
HEURISTIC_MIN_TICKERS = 20
HEURISTIC_MIN_YEARS = 3.0


def _intervals(u: pd.DataFrame) -> dict[str, list[tuple[date, date | None]]]:
    out: dict[str, list[tuple[date, date | None]]] = {}
    for r in u.dropna(subset=["ticker", "start_date"]).itertuples():
        end = getattr(r, "end_date", None)
        end = None if end is None or pd.isna(end) else end.date()
        out.setdefault(r.ticker, []).append((r.start_date.date(), end))
    return out


def check_survivorship(pkg: Package, res: AuditResult) -> None:
    title = "Survivorship (delisted members)"
    px = pkg.df("prices")
    if pkg.missing("survivorship"):
        if px is not None:
            d = px.dropna(subset=["date", "ticker"])
            last = d.groupby("ticker")["date"].max().dt.date
            years = (d["date"].max() - d["date"].min()).days / 365.25 if len(d) else 0
            if len(last) >= HEURISTIC_MIN_TICKERS and years >= HEURISTIC_MIN_YEARS and \
                    (last.max() - last.min()).days <= DELIST_TOL_DAYS:
                res.add("survivorship", BLOCK, NEEDS_REVIEW, "No price series ends early: probable survivor-only universe",
                        f"{len(last)} tickers over {years:.1f} years and not a single series ends before the last date. In "
                        "a real equity universe several companies leave every year.",
                        [{"tickers": int(len(last)), "years": round(years, 2)}],
                        "Last price date per ticker compared with the last date of the file.",
                        action="Provide universe.csv (point-in-time membership with exits) to verify it.",
                        priority="high", inputs=["prices"])
                return
        missing_inputs(res, "survivorship", BLOCK, title, pkg.missing("survivorship"))
        return
    d = px.dropna(subset=["date", "ticker"])
    dates_by = {t: sorted(g["date"].dt.date) for t, g in d.groupby("ticker")}
    start, end = d["date"].min().date(), d["date"].max().date()
    iv = _intervals(pkg.df("universe"))
    none_, short, ok = [], [], 0
    for t, ivs in iv.items():
        if any(b is None for _, b in ivs):
            continue
        last_exit = max(b for _, b in ivs)
        if not (start < last_exit <= end + timedelta(days=1)):
            continue
        ds = dates_by.get(t)
        if not ds:
            none_.append({"ticker": t, "exit": last_exit.isoformat()})
            continue
        before = [x for x in ds if x < last_exit]
        last = max(before) if before else None
        if last and (last_exit - last).days <= DELIST_TOL_DAYS:
            ok += 1
        else:
            short.append({"ticker": t, "exit": last_exit.isoformat(), "last_price": last.isoformat() if last else None,
                          "days_missing": (last_exit - last).days if last else None})
    found = False
    proc = (f"universe.csv exits inside the price window [{start}, {end}] crossed with the last price date of each "
            f"ticker (tolerance {DELIST_TOL_DAYS} calendar days).")
    ins = ["prices", "universe"]
    if none_:
        res.add("survivorship", BLOCK, CONFIRMED_ERROR, "Members that left the universe have NO price at all",
                f"{len(none_)} of {len(none_) + len(short) + ok} exits inside the window have no price series: the "
                "backtest can never buy them nor suffer their fall (survivorship bias).", none_, proc,
                action="Add prices of delisted members up to their exit date, including the last price.",
                priority="high", inputs=ins)
        found = True
    if short:
        res.add("survivorship", BLOCK, NEEDS_REVIEW, "Delisted members whose prices end before their exit",
                f"{len(short)} series stop before the member left the universe: the final loss (bankruptcy, takeover at "
                "a discount) may be outside the backtest.", short, proc,
                action="Complete the series up to the exit or document a trading halt.", priority="high", inputs=ins)
        found = True
    tr = pkg.df("trades")
    if tr is not None:
        outside = []
        for r in tr.dropna(subset=["timestamp", "ticker"]).itertuples():
            if r.side != "buy":
                continue
            ivs = iv.get(r.ticker)
            day = r.timestamp.date()
            if not ivs or not any(a <= day and (b is None or day < b) for a, b in ivs):
                outside.append({"row": int(r.row), "ticker": r.ticker, "date": day.isoformat()})
        if outside:
            res.add("survivorship", BLOCK, NEEDS_REVIEW, "Buys of tickers outside the point-in-time universe",
                    f"{len(outside)} buys on dates when the ticker was not a member according to universe.csv.", outside,
                    "Each buy date checked against the membership intervals of its ticker.",
                    action="Confirm the universe rule (membership at decision date) used by the backtest.",
                    priority="medium", inputs=ins + ["trades"])
            found = True
    if not found:
        res.add("survivorship", BLOCK, PASS, "Delisted members have prices up to their exit",
                f"{ok} exits inside the window, all with prices up to the exit. Scope: relative to the universe file "
                "delivered.", [], proc, inputs=ins)


def _windows(g: pd.DataFrame) -> list[tuple[str, date | None, date | None]]:
    out = []
    for r in g.itertuples():
        a = getattr(r, "start_date", None)
        b = getattr(r, "end_date", None)
        out.append((str(r.entity_id), None if a is None or pd.isna(a) else a.date(),
                    None if b is None or pd.isna(b) else b.date()))
    return out


def gap_shifts(dates: list[date], closes: list[float]) -> list[dict]:
    out = []
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap >= GAP_RECYCLE_DAYS:
            pre = float(np.median(closes[max(0, i - 5):i]))
            post = float(np.median(closes[i:i + 5]))
            ratio = post / pre if pre > 0 else float("inf")
            out.append({"before": dates[i - 1].isoformat(), "after": dates[i].isoformat(), "gap_days": gap,
                        "level_ratio": round(ratio, 4),
                        "level_shift": bool(ratio >= LEVEL_SHIFT or ratio <= 1 / LEVEL_SHIFT)})
    return out


def check_ticker_identity(pkg: Package, res: AuditResult) -> None:
    title = "Ticker identity (recycled tickers)"
    px = pkg.df("prices")
    heur = []
    if px is not None:
        d = px.dropna(subset=["date", "ticker", "close"]).drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
        for t, g in d.groupby("ticker"):
            for x in gap_shifts(list(g["date"].dt.date), [float(c) for c in g["close"]]):
                if x["level_shift"]:
                    heur.append(dict(x, ticker=t))
    heur_proc = (f"Heuristic: internal gap of >= {GAP_RECYCLE_DAYS} calendar days followed by a level change of "
                 f"x{LEVEL_SHIFT} or more (median of 5 closes on each side).")
    if pkg.missing("ticker_identity"):
        if heur:
            res.add("ticker_identity", BLOCK, NEEDS_REVIEW, "Long gap and level shift in a series: possible recycled ticker",
                    f"{len(heur)} gaps after which the series reappears at another level. Without a security master "
                    "this cannot be confirmed.", heur, heur_proc,
                    action="Provide security_master.csv (ticker -> entity_id with dates) and join histories by entity.",
                    priority="high", inputs=["prices"])
        else:
            not_executable(res, "ticker_identity", BLOCK, title,
                           "missing security_master.csv (ticker -> entity_id); the price heuristic found no gap with a "
                           "level shift, which does not prove identity",
                           "Provide security_master.csv.")
        return
    sm = pkg.df("security_master").dropna(subset=["ticker", "entity_id"])
    dates_by = {t: sorted(g["date"].dt.date) for t, g in px.dropna(subset=["date", "ticker"]).groupby("ticker")}
    fu = pkg.df("fundamentals")
    multi = sm.groupby("ticker")["entity_id"].nunique()
    recycled = sorted(multi[multi > 1].index)
    mixed, clean = [], []
    for t in recycled:
        wins = _windows(sm[sm["ticker"] == t])
        ds = dates_by.get(t, [])
        hit = sorted({e for e, a, b in wins for x in ds if (a is None or x >= a) and (b is None or x <= b)})
        fd_hit: list[str] = []
        if fu is not None:
            pe = fu.loc[fu["ticker"] == t, "period_end"].dropna().dt.date.unique()
            fd_hit = sorted({e for e, a, b in wins for x in pe if (a is None or x >= a) and (b is None or x <= b)})
        if len(hit) > 1 or len(fd_hit) > 1:
            mixed.append({"ticker": t, "entities_in_prices": hit, "entities_in_fundamentals": fd_hit,
                          "windows": [{"entity_id": e, "start": a.isoformat() if a else None,
                                       "end": b.isoformat() if b else None} for e, a, b in wins]})
        else:
            clean.append(t)
    ins = ["prices", "security_master"]
    proc = ("security_master.csv: tickers mapped to more than one entity_id; the price dates (and fundamentals period "
            "ends) of the ticker are assigned to each entity window.")
    found = False
    if mixed:
        res.add("ticker_identity", BLOCK, CONFIRMED_ERROR, "One ticker's series mixes two different entities (recycled ticker)",
                f"{len(mixed)} tickers: the backtest treats two companies as one and the return across the seam is "
                "fictitious.", mixed, proc, action="Join histories by entity_id, not by ticker.", priority="high",
                inputs=ins + (["fundamentals"] if fu is not None else []))
        found = True
    flagged = {m["ticker"] for m in mixed}
    unexplained = [h for h in heur if h["ticker"] not in flagged and h["ticker"] not in recycled]
    if unexplained:
        res.add("ticker_identity", BLOCK, NEEDS_REVIEW, "Long gap and level shift not explained by the security master",
                f"{len(unexplained)} gaps with a level shift in tickers with a single entity.", unexplained, heur_proc,
                action="Check whether the master is complete for those tickers.", priority="medium", inputs=ins)
        found = True
    if not found:
        res.add("ticker_identity", BLOCK, PASS, "No recycled ticker mixes entities in the price series",
                f"{len(recycled)} recycled tickers in the master, all correctly separated; {sm['ticker'].nunique()} "
                "tickers mapped. Scope: relative to the master delivered.", [{"recycled_clean": clean}], proc,
                inputs=ins)
