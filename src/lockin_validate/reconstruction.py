"""Reconstruction of positions, cash and daily NAV from trades (docs/CONVENTIONS.md, section 1).

Explicit, configurable conventions (rules.yaml ``conventions`` or :class:`Conventions`):

``initial_cash``      cash at the start (default 100000). It is the FIRST NAV point: returns are measured
                      from here (return base = initial cash).
``valuation``         ``close``: each day is valued at that day's close. If a ticker has no close that day the
                      last available close is used and logged (count per ticker) as an applied transformation.
``commission_rate``,  declared costs (rules.yaml ``costs``, fractions of notional). The MAIN reconstruction
``slippage_rate``     does not apply them: it uses the executed price of trades.csv and its ``commission``
                      column (zero if absent). They are only applied with ``impute_costs=True``, which the
                      omitted_costs check uses to build scenarios.
``leverage``          false: negative cash is a finding (default).
``short_selling``     false: a negative quantity is a finding (default).
``start_date``, ``end_date``  NAV window (default: from the first trade to the last price).

Everything is computed with an explicit loop per date (no pandas inside the core computation) so the
independent oracle in tests/oracle/ is a genuinely different implementation.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from .inputs import Package


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


@dataclass
class Conventions:
    initial_cash: float = 100_000.0
    valuation: str = "close"
    commission_rate: float = 0.0
    slippage_rate: float = 0.0
    leverage: bool = False
    short_selling: bool = False
    start_date: date | None = None
    end_date: date | None = None
    use_trade_commissions: bool = True
    impute_costs: bool = False

    @classmethod
    def from_package(cls, pkg: Package) -> Conventions:
        c = cls()
        c.initial_cash = float(pkg.conv("initial_cash", c.initial_cash))
        c.valuation = str(pkg.conv("valuation", c.valuation))
        c.leverage = _bool(pkg.conv("leverage", c.leverage))
        c.short_selling = _bool(pkg.conv("short_selling", c.short_selling))
        costs = (pkg.rules or {}).get("costs") if pkg.rules else None
        if isinstance(costs, dict):
            c.commission_rate = float(costs.get("commission_rate", c.commission_rate) or 0.0)
            c.slippage_rate = float(costs.get("slippage_rate", c.slippage_rate) or 0.0)
        for k in ("start_date", "end_date"):
            v = pkg.conv(k)
            if v is not None:
                setattr(c, k, pd.Timestamp(str(v)).date())
        return c

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        for k in ("start_date", "end_date"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d


@dataclass
class Reconstruction:
    dates: list[date]
    nav: list[float]
    cash: list[float]
    positions_value: list[float]
    holdings: list[dict[str, float]]  # per date, {ticker: quantity} at the close
    trades: list[dict[str, Any]]  # applied, in order, with source row
    total_costs: float
    total_notional: float
    conventions: Conventions
    stale_valued: dict[str, int] = field(default_factory=dict)  # ticker -> days valued with an older close
    unvalued: dict[str, int] = field(default_factory=dict)  # ticker -> days without any close
    negative_cash: list[dict[str, Any]] = field(default_factory=list)
    negative_quantity: list[dict[str, Any]] = field(default_factory=list)
    trades_without_price: list[dict[str, Any]] = field(default_factory=list)
    window: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def holdings_at(self, d: date) -> dict[str, float]:
        """Holdings at the close of the last date <= d (empty before the first date)."""
        i = bisect_right(self.dates, d) - 1
        return {} if i < 0 else self.holdings[i]

    def nav_at(self, d: date) -> float | None:
        i = bisect_right(self.dates, d) - 1
        return None if i < 0 else self.nav[i]

    def summary(self) -> dict[str, Any]:
        return {"conventions": self.conventions.to_dict(), "window": self.window, "n_dates": len(self.dates),
                "initial_nav": self.nav[0] if self.nav else None, "final_nav": self.nav[-1] if self.nav else None,
                "n_trades_applied": len(self.trades), "total_costs": self.total_costs,
                "total_notional": self.total_notional, "days_valued_with_older_close": self.stale_valued,
                "days_unvalued": self.unvalued, "n_negative_cash": len(self.negative_cash),
                "n_negative_quantity": len(self.negative_quantity), "notes": self.notes}


def price_table(px: pd.DataFrame) -> dict[str, tuple[list[date], list[float]]]:
    """{ticker: (sorted dates, closes)}; with duplicates the first row of the file is used."""
    out: dict[str, tuple[list[date], list[float]]] = {}
    d = px.dropna(subset=["date", "ticker", "close"]).sort_values(["ticker", "date", "row"])
    d = d.drop_duplicates(["ticker", "date"], keep="first")
    for t, g in d.groupby("ticker"):
        out[t] = (list(g["date"].dt.date), [float(x) for x in g["close"]])
    return out


def reconstruct(pkg: Package, conv: Conventions | None = None, log: bool = True) -> Reconstruction:
    conv = conv or Conventions.from_package(pkg)
    px = pkg.df("prices")
    tr = pkg.df("trades")
    if px is None or tr is None:
        raise ValueError("the reconstruction needs prices.csv and trades.csv")
    prices = price_table(px)
    n_dup = int(px.dropna(subset=["date", "ticker"]).duplicated(["ticker", "date"]).sum())
    if n_dup and log:
        pkg.log.applied("prices", "first_occurrence_per_(ticker, date)",
                        "duplicates present; valuation uses the first row of the file",
                        {"duplicated_rows": n_dup}, {"duplicated_rows_used": 0})
    o = tr.dropna(subset=["timestamp", "ticker", "side", "quantity", "price"]).copy()
    dropped = int(len(tr) - len(o))
    if dropped and log:
        pkg.log.applied("trades", "exclude_incomplete_trades", "without a valid timestamp, ticker, side, quantity or price",
                        {"rows": int(len(tr))}, {"rows_used": int(len(o))},
                        rows=[int(x) for x in tr[~tr.index.isin(o.index)]["row"]])
    if not o["timestamp"].is_monotonic_increasing and log:
        pkg.log.applied("trades", "sort_by_timestamp", "the reconstruction applies trades in chronological order",
                        {"order": "file"}, {"order": "timestamp, row"})
    o = o.sort_values(["timestamp", "row"])
    has_commission = "commission" in o.columns and o["commission"].notna().any() and conv.use_trade_commissions
    com_rate = conv.commission_rate if conv.impute_costs else 0.0
    slip_rate = conv.slippage_rate if conv.impute_costs else 0.0

    all_dates = sorted({d for fs, _ in prices.values() for d in fs})
    if not all_dates:
        raise ValueError("prices.csv has no valid dates")
    first_trade = o["timestamp"].min().date() if len(o) else all_dates[0]
    start = conv.start_date or first_trade
    end = conv.end_date or all_dates[-1]
    dates = [d for d in all_dates if start <= d <= end]
    if len(o) and first_trade < (dates[0] if dates else start):
        dates = [first_trade] + dates
    # initial point: NAV = initial cash, dated on the last price date before the first trade
    earlier = [d for d in all_dates if d < dates[0]] if dates else []
    date_zero = earlier[-1] if earlier else (dates[0] if dates else start) - timedelta(days=1)
    rec = Reconstruction(dates=[], nav=[], cash=[], positions_value=[], holdings=[], trades=[], total_costs=0.0,
                         total_notional=0.0, conventions=conv, window={"start": start.isoformat(), "end": end.isoformat()})
    if not has_commission and com_rate > 0:
        rec.notes.append(f"scenario with imputed costs: commission_rate={com_rate:g}, slippage_rate={slip_rate:g}")
    elif not has_commission:
        rec.notes.append("trades.csv has no commission: the reconstruction uses zero commission (declared costs are "
                         "contrasted in omitted_costs)")
    rec.dates.append(date_zero)
    rec.cash.append(conv.initial_cash)
    rec.positions_value.append(0.0)
    rec.nav.append(conv.initial_cash)
    rec.holdings.append({})

    trades_by_date: dict[date, list] = {}
    for r in o.itertuples():
        trades_by_date.setdefault(r.timestamp.date(), []).append(r)
    cash = conv.initial_cash
    qty: dict[str, float] = {}
    price_dates = {t: set(fs) for t, (fs, _) in prices.items()}
    for f in dates:
        for r in trades_by_date.get(f, []):
            sign = 1 if r.side == "buy" else -1
            price = float(r.price) * (1 + sign * slip_rate)
            notional = float(r.quantity) * price
            if has_commission:
                com = float(r.commission) if pd.notna(r.commission) else 0.0
            else:
                com = notional * com_rate
            cash -= sign * notional + com
            qty[r.ticker] = qty.get(r.ticker, 0.0) + sign * float(r.quantity)
            if abs(qty[r.ticker]) < 1e-9:
                qty[r.ticker] = 0.0
            rec.total_costs += com
            rec.total_notional += abs(notional)
            rec.trades.append({"row": int(r.row), "date": f.isoformat(), "ticker": r.ticker, "side": r.side,
                               "quantity": float(r.quantity), "price": price, "commission": com,
                               "cash_after": cash, "quantity_after": qty[r.ticker]})
            if r.ticker in prices and f not in price_dates[r.ticker]:
                rec.trades_without_price.append({"row": int(r.row), "ticker": r.ticker, "date": f.isoformat()})
            if qty[r.ticker] < 0 and not conv.short_selling:
                rec.negative_quantity.append({"row": int(r.row), "ticker": r.ticker, "date": f.isoformat(),
                                              "quantity_after": qty[r.ticker]})
        value = 0.0
        for t, q in qty.items():
            if q == 0:
                continue
            if t not in prices:
                rec.unvalued[t] = rec.unvalued.get(t, 0) + 1
                continue
            fs, cs = prices[t]
            i = bisect_right(fs, f) - 1
            if i < 0:
                rec.unvalued[t] = rec.unvalued.get(t, 0) + 1
                continue
            if fs[i] != f:
                rec.stale_valued[t] = rec.stale_valued.get(t, 0) + 1
            value += q * cs[i]
        if cash < -1e-6 and not conv.leverage:
            rec.negative_cash.append({"date": f.isoformat(), "cash": cash})
        rec.dates.append(f)
        rec.cash.append(cash)
        rec.positions_value.append(value)
        rec.nav.append(cash + value)
        rec.holdings.append({t: q for t, q in qty.items() if q != 0})
    if rec.stale_valued and log:
        pkg.log.applied("prices", "last_available_close_for_valuation",
                        "days without a close of the ticker: valued with the previous close",
                        {"days_without_close": dict(rec.stale_valued)}, {"valued_with_previous_close": True})
    return rec
