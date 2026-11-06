"""Use case ``portfolio``: validation of a portfolio-construction / asset-allocation model from its target WEIGHTS.

Mean-variance and risk-parity optimisers, Black-Litterman, the model portfolios of an advisor or a robo-advisor,
index trackers and the model portfolios of a fund (FCI) all deliver the same object: a table of target weights per
date and instrument (``weights.csv``). This module validates that table against what was DECLARED (constraints in
rules.yaml), against what was HELD (positions.csv x prices.csv), against what the weights would have earned
(prices.csv) compared with the naive 1/N portfolio of the same names, and against a benchmark composition
(benchmark_weights.csv).

Checks (ids):
  portfolio_constraints          declared constraints hold on every date (sum, long-only, max weight, gross, net, groups)
  portfolio_concentration        HHI / effective N / top-5 / largest name per date; UCITS 5/10/40 as context
  portfolio_turnover             one-way turnover net of buy-and-hold drift; rebalance count vs the declared frequency
  portfolio_weights_vs_positions declared weights vs the weights implied by positions x prices
  portfolio_vs_naive             realised path vs 1/N (and the benchmark); Jobson-Korkie-Memmel test of the Sharpe gap
  portfolio_active_share         active share vs benchmark_weights; closet indexing vs the declared strategy text

Statistics implemented here (numpy + pandas only): Herfindahl index, one-way turnover with drift correction,
Jobson and Korkie (1981) z-test of the difference of two Sharpe ratios with the Memmel (2003) correction as written
in DeMiguel, Garlappi and Uppal (2009), active share (Cremers and Petajisto 2009).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from . import UseCase, register

NAME = "portfolio"
_N = NormalDist()
EPS_WEIGHT = 1e-6  # tolerance for per-name limits (rounding of the delivered weights)
ZERO_TURNOVER = 1e-3  # one-way turnover below 0.1% counts as "no trade" (rounding and price-source noise)
NON_REBALANCE_TRADE = 0.01  # one-way turnover above 1% on a non-rebalance date, net of drift, is a trade
FREQ_PER_YEAR = {"daily": 252, "weekly": 52, "biweekly": 26, "fortnightly": 26, "monthly": 12, "bimonthly": 6,
                 "quarterly": 4, "semiannual": 2, "semi-annual": 2, "semi_annual": 2, "annual": 1, "yearly": 1}
CONSTRAINT_KEYS = ("long_only", "max_weight", "min_weight", "gross_leverage_max", "net_exposure", "group_limits",
                   "cash_ticker", "rebalance_frequency", "turnover_max_annual", "benchmark_weights_file")


# ---------------------------------------------------------------------------- helpers

def constraints(pkg: Any) -> tuple[dict[str, Any], str]:
    """Declared portfolio constraints: rules.yaml ``constraints.portfolio`` (or ``constraints`` with known keys),
    else the review profile's ``portfolio_constraints``. Returns (dict, source)."""
    rules = pkg.rules if isinstance(pkg.rules, dict) else {}
    c = rules.get("constraints")
    if isinstance(c, dict):
        if isinstance(c.get("portfolio"), dict):
            return dict(c["portfolio"]), "rules.yaml constraints.portfolio"
        if any(k in c for k in CONSTRAINT_KEYS):
            return dict(c), "rules.yaml constraints"
    prof = getattr(pkg, "profile", None) or {}
    pc = prof.get("portfolio_constraints") if isinstance(prof, dict) else None
    if isinstance(pc, dict) and pc:
        return dict(pc), f"profile {prof.get('name')}"
    return {}, "none declared"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _is_true(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "yes", "1", "y")


def cash_ticker(decl: dict[str, Any], tickers: list[str]) -> str | None:
    """Declared cash ticker (upper-cased), else a ticker literally named CASH when present."""
    v = decl.get("cash_ticker")
    if v:
        return str(v).strip().upper()
    return "CASH" if "CASH" in tickers else None


class Panel:
    """Weights of ONE portfolio: long table, wide date x ticker (missing = 0) and the group columns."""

    def __init__(self, name: str | None, long: pd.DataFrame):
        self.name = name
        self.long = long
        self.wide = (long.pivot_table(index="date", columns="ticker", values="weight", aggfunc="sum")
                     .sort_index().fillna(0.0))
        self.dates = list(self.wide.index)
        self.tickers = list(self.wide.columns)
        self.rows = long.groupby(["date", "ticker"])["row"].min()

    def all_zero(self) -> bool:
        return bool(float(self.wide.abs().to_numpy().sum()) == 0.0)

    def label(self) -> str:
        return f" [portfolio {self.name}]" if self.name is not None else ""

    def row(self, d, t) -> int | None:
        try:
            return int(self.rows.loc[(d, t)])
        except KeyError:
            return None

    def group_cols(self) -> list[str]:
        return [c for c in ("sector", "asset_class", "group", "industry", "country") if c in self.long.columns
                and self.long[c].notna().any()]

    def group_of(self, col: str) -> pd.DataFrame:
        """date x ticker -> group label (forward-filled per ticker), for date-varying classifications."""
        g = self.long.dropna(subset=[col]).pivot_table(index="date", columns="ticker", values=col, aggfunc="last")
        g = g.reindex(index=self.wide.index, columns=self.wide.columns).ffill().bfill()
        return g


def panels(pkg: Any) -> list[Panel]:
    w = pkg.df("weights")
    if w is None:
        return []
    d = w.dropna(subset=["date", "ticker", "weight"]).copy()
    d["date"] = d["date"].dt.normalize()
    if d.empty:
        return []
    if "portfolio" in d.columns and d["portfolio"].notna().any():
        d["portfolio"] = d["portfolio"].fillna("default").astype(str)
        names = sorted(d["portfolio"].unique())
        if len(names) > 1:
            return [Panel(n, d[d["portfolio"] == n]) for n in names]
    return [Panel(None, d)]


def price_matrix(pkg: Any) -> pd.DataFrame | None:
    px = pkg.df("prices")
    if px is None:
        return None
    d = px.dropna(subset=["date", "ticker", "close"]).copy()
    d = d[d["close"] > 0]
    if d.empty:
        return None
    d["date"] = d["date"].dt.normalize()
    d = d.sort_values(["date", "row"]).drop_duplicates(["ticker", "date"], keep="last")
    return d.pivot(index="date", columns="ticker", values="close").sort_index()


def infer_ppy(dates: list) -> int:
    if len(dates) < 3:
        return 252
    gaps = np.diff(np.array([pd.Timestamp(x).value for x in dates])) / 86_400e9
    med = float(np.median(gaps))
    if med <= 1.6:
        return 252
    if med <= 8:
        return 52
    if med <= 35:
        return 12
    if med <= 100:
        return 4
    return 1


def return_series(df: pd.DataFrame | None) -> pd.Series | None:
    """date -> simple return from benchmark_returns (return column, or nav level)."""
    if df is None:
        return None
    d = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="first")
    if "return" in d.columns and d["return"].notna().any():
        d = d.dropna(subset=["return"])
        return pd.Series(d["return"].to_numpy(dtype=float), index=d["date"].dt.normalize())
    if "nav" in d.columns and d["nav"].notna().sum() >= 3:
        d = d.dropna(subset=["nav"])
        nav = d["nav"].to_numpy(dtype=float)
        return pd.Series(nav[1:] / nav[:-1] - 1, index=d["date"].dt.normalize()[1:])
    return None


# ---------------------------------------------------------------------------- statistics

def hhi(weights) -> float:
    """Herfindahl index of the absolute weights normalised by the gross exposure (1/N -> 1/N; one name -> 1)."""
    a = np.abs(np.asarray(weights, dtype=float))
    g = a.sum()
    if g <= 0:
        return float("nan")
    s = a / g
    return float((s * s).sum())


def effective_n(weights) -> float:
    h = hhi(weights)
    return 1.0 / h if h and math.isfinite(h) and h > 0 else float("nan")


def top_share(weights, k: int = 5) -> float:
    a = np.sort(np.abs(np.asarray(weights, dtype=float)))[::-1]
    g = a.sum()
    return float(a[:k].sum() / g) if g > 0 else float("nan")


def drifted_weights(w_prev: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """Buy-and-hold drift of ``w_prev`` over one period: w * ratio / NAV factor, with NAV factor
    1 + sum(w * (ratio - 1)); the uninvested remainder (cash) earns nothing and names without a price ratio keep it
    at 1. Works for long-only, long-short and market-neutral books alike."""
    r = np.where(np.isfinite(ratio), ratio, 1.0)
    nav = 1.0 + float(np.sum(w_prev * (r - 1.0)))
    if nav <= 0:
        return w_prev.copy()
    return w_prev * r / nav


def one_way_turnover(w_new: np.ndarray, w_prev: np.ndarray, ratio: np.ndarray | None = None) -> float:
    """0.5 * sum |w_new - drift(w_prev)| (drift only when price ratios are given)."""
    base = drifted_weights(w_prev, ratio) if ratio is not None else w_prev
    return 0.5 * float(np.abs(w_new - base).sum())


def jobson_korkie_memmel(r1, r2) -> dict[str, float]:
    """Test of SR1 - SR2 (per-period Sharpe ratios of two series on the same dates).

    z = (SR1 - SR2) / sqrt(theta), theta = (1/T) [2 (1 - rho) + 0.5 (SR1^2 + SR2^2) - SR1 SR2 rho^2]
    (Jobson and Korkie 1981 with the correction of Memmel 2003, as written in DeMiguel, Garlappi and Uppal 2009,
    section 2.3). ``p_one_sided`` is P[Z > z] (H1: SR1 > SR2); ``p_two_sided`` = 2 P[Z > |z|].
    """
    a = np.asarray(r1, dtype=float)
    b = np.asarray(r2, dtype=float)
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    T = a.size
    if T < 3:
        return {"T": T, "sr1": float("nan"), "sr2": float("nan"), "rho": float("nan"), "z": float("nan"),
                "p_one_sided": float("nan"), "p_two_sided": float("nan")}
    s1, s2 = a.std(ddof=1), b.std(ddof=1)
    if s1 <= 0 or s2 <= 0:
        return {"T": T, "sr1": float("nan"), "sr2": float("nan"), "rho": float("nan"), "z": float("nan"),
                "p_one_sided": float("nan"), "p_two_sided": float("nan")}
    sr1, sr2 = a.mean() / s1, b.mean() / s2
    rho = float(np.corrcoef(a, b)[0, 1])
    theta = (2.0 * (1.0 - rho) + 0.5 * (sr1 ** 2 + sr2 ** 2) - sr1 * sr2 * rho ** 2) / T
    z = (sr1 - sr2) / math.sqrt(theta) if theta > 0 else float("nan")
    p1 = 1.0 - _N.cdf(z) if math.isfinite(z) else float("nan")
    p2 = 2.0 * (1.0 - _N.cdf(abs(z))) if math.isfinite(z) else float("nan")
    return {"T": T, "sr1": float(sr1), "sr2": float(sr2), "rho": rho, "z": float(z), "p_one_sided": float(p1),
            "p_two_sided": float(p2)}


def active_share(w: np.ndarray, wb: np.ndarray) -> float:
    return 0.5 * float(np.abs(w - wb).sum())


def perf(r: np.ndarray, ppy: int) -> dict[str, float]:
    r = np.asarray(r, dtype=float)
    T = r.size
    nav = np.cumprod(1.0 + r)
    total = float(nav[-1]) if T else float("nan")
    ann = total ** (ppy / T) - 1.0 if T and total > 0 else float("nan")
    vol = float(r.std(ddof=1)) * math.sqrt(ppy) if T > 1 else float("nan")
    sr = float(r.mean() / r.std(ddof=1)) * math.sqrt(ppy) if T > 1 and r.std(ddof=1) > 0 else float("nan")
    peak = np.maximum.accumulate(nav)
    mdd = float((nav / peak - 1.0).min()) if T else float("nan")
    return {"annual_return": ann, "volatility": vol, "sharpe": sr, "max_drawdown": mdd, "n": int(T)}


# ---------------------------------------------------------------------------- simulation of a weight path

def simulate(panel: Panel, px: pd.DataFrame, naive: bool = False, cash: str | None = None
             ) -> tuple[pd.Series, dict[str, Any]]:
    """Periodic returns of the weight path over the price dates, no costs.

    Weights dated d are applied at the close of the first price date AFTER d (next session) and drift (buy and hold)
    until the next rebalance; the uninvested remainder is cash at zero return. With ``naive`` the same names (those
    with a non-zero weight on that date, cash excluded) get 1/N. Names without a price on a date keep their previous
    price (ratio 1); names never priced are dropped and reported in ``info``.
    """
    pdates = list(px.index)
    pvals = np.array([pd.Timestamp(x).to_datetime64() for x in pdates], dtype="datetime64[ns]")
    wide = panel.wide
    if cash is not None and cash in wide.columns:
        wide = wide.drop(columns=[cash])
    held = [t for t in wide.columns if t in px.columns]
    dropped = [t for t in wide.columns if t not in px.columns]
    if not held:
        raise ValueError("no priced ticker in the weights")
    P = px[held].ffill()
    ratios = (P / P.shift(1)).to_numpy(dtype=float)
    rows: dict[int, np.ndarray] = {}
    for d in panel.dates:
        tw = wide.loc[d, held].to_numpy(dtype=float)
        if naive:
            n = int((np.abs(tw) > 0).sum())
            tw = np.where(np.abs(tw) > 0, 1.0 / n, 0.0) if n else tw
        pos = int(np.searchsorted(pvals, pd.Timestamp(d).to_datetime64(), side="right"))  # first price date after d
        if pos < len(pdates):
            rows[pos] = tw  # a later weights date mapping to the same session wins (latest target)
    if not rows:
        raise ValueError("no price date after any weights date")
    start = min(rows)
    w = rows[start].copy()  # entered at the close of the first session after the first weights date
    out = []
    idx = []
    for i in range(start + 1, len(pdates)):
        r = ratios[i]
        r = np.where(np.isfinite(r), r, 1.0)
        out.append(float(np.sum(w * (r - 1.0))))
        idx.append(pdates[i])
        w = drifted_weights(w, r)
        if i in rows:
            w = rows[i].copy()  # rebalance at this close: earns from the next session
    info = {"dropped_unpriced": dropped, "n_rebalances": len(rows), "first_date": pdates[start]}
    return pd.Series(out, index=idx), info


# ---------------------------------------------------------------------------- checks

def check_constraints(pkg: Any, res: AuditResult) -> None:
    cid, title = "portfolio_constraints", "Declared portfolio constraints"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    pans = panels(pkg)
    if not pans:
        not_executable(res, cid, NAME, title, "weights.csv has no row with date, ticker and weight")
        return
    decl, src = constraints(pkg)
    tol = float(pkg.conv("portfolio_weight_sum_tolerance", 0.01))
    for p in pans:
        if p.all_zero():
            not_executable(res, cid, NAME, title + p.label(), "every weight is zero (example or empty table)")
            continue
        _constraints_one(pkg, res, p, decl, src, tol)


def _constraints_one(pkg: Any, res: AuditResult, p: Panel, decl: dict[str, Any], src: str, tol: float) -> None:
    cid, plab = "portfolio_constraints", p.label()
    cash = cash_ticker(decl, p.tickers)
    W = p.wide
    non_cash = [t for t in p.tickers if t != cash]
    sums = W.sum(axis=1)
    gross = W.abs().sum(axis=1)
    mins = W[non_cash].min(axis=1) if non_cash else sums * 0
    maxs = W[non_cash].max(axis=1) if non_cash else sums * 0
    observed = {"n_dates": len(p.dates), "n_tickers": len(p.tickers), "cash_ticker": cash,
                "sum_min": float(sums.min()), "sum_max": float(sums.max()), "gross_min": float(gross.min()),
                "gross_max": float(gross.max()), "weight_min": float(mins.min()), "weight_max": float(maxs.max()),
                "n_negative_dates": int((W[non_cash] < -EPS_WEIGHT).any(axis=1).sum()) if non_cash else 0}
    res.metrics.setdefault(cid, {})[p.name or "default"] = {"observed": observed, "declared": decl, "source": src}
    ev: list[dict[str, Any]] = []
    violated: list[str] = []
    unverifiable: list[str] = []
    checked: list[str] = []
    declared_any = any(k in decl for k in ("long_only", "max_weight", "min_weight", "gross_leverage_max",
                                              "net_exposure", "group_limits"))

    def add(kind, d, t, value, limit):
        ev.append({"row": p.row(d, t) if t else None, "date": d.date(), "ticker": t, "constraint": kind,
                   "value": round(float(value), 6), "limit": limit})

    long_only = _is_true(decl.get("long_only"))
    net = decl.get("net_exposure")
    if isinstance(net, (list, tuple)) and len(net) == 2 and _num(net[0]) is not None and _num(net[1]) is not None:
        lo, hi = float(net[0]), float(net[1])
        checked.append(f"net exposure in [{lo}, {hi}]")
        bad = sums[(sums < lo - tol) | (sums > hi + tol)]
        for d, v in bad.items():
            add("net_exposure", d, None, v, [lo, hi])
        if len(bad):
            violated.append(f"net exposure outside [{lo}, {hi}] on {len(bad)} date(s)")
    elif long_only:
        if cash is None:
            checked.append(f"sum of weights = 1 +/- {tol} (no cash ticker: fully invested)")
            bad = sums[(sums - 1.0).abs() > tol]
            for d, v in bad.items():
                add("sum_of_weights", d, None, v, 1.0)
            if len(bad):
                violated.append(f"sum of weights outside 1 +/- {tol} on {len(bad)} date(s) (min {sums.min():.4f}, "
                                f"max {sums.max():.4f}) with no cash ticker")
        else:
            checked.append(f"sum of weights <= 1 + {tol} (cash ticker {cash}: the remainder is cash)")
            bad = sums[sums > 1.0 + tol]
            for d, v in bad.items():
                add("sum_of_weights", d, None, v, 1.0)
            if len(bad):
                violated.append(f"sum of weights above 1 + {tol} on {len(bad)} date(s)")
    if long_only and non_cash:
        checked.append("long only (no negative weight)")
        neg = W[non_cash].stack()
        neg = neg[neg < -EPS_WEIGHT]
        for (d, t), v in neg.items():
            add("long_only", d, t, v, 0.0)
        if len(neg):
            violated.append(f"{len(neg)} negative weight(s) under long_only")
    mw = _num(decl.get("max_weight"))
    if mw is not None and non_cash:
        checked.append(f"max weight {mw} (cash excluded)")
        over = W[non_cash].stack()
        over = over[over > mw + EPS_WEIGHT]
        for (d, t), v in over.items():
            add("max_weight", d, t, v, mw)
        if len(over):
            violated.append(f"{len(over)} weight(s) above max_weight {mw} (largest {over.max():.4f})")
    mnw = _num(decl.get("min_weight"))
    if mnw is not None and mnw > 0 and non_cash:
        checked.append(f"min weight {mnw} for held names")
        s = W[non_cash].stack()
        under = s[(s.abs() > EPS_WEIGHT) & (s < mnw - EPS_WEIGHT)]
        for (d, t), v in under.items():
            add("min_weight", d, t, v, mnw)
        if len(under):
            violated.append(f"{len(under)} held weight(s) below min_weight {mnw}")
    gl = _num(decl.get("gross_leverage_max"))
    if gl is not None:
        checked.append(f"gross leverage sum|w| <= {gl}")
        bad = gross[gross > gl + tol]
        for d, v in bad.items():
            add("gross_leverage", d, None, v, gl)
        if len(bad):
            violated.append(f"gross leverage above {gl} on {len(bad)} date(s) (max {gross.max():.4f})")
    gls = decl.get("group_limits")
    if isinstance(gls, dict):
        for col, lim in gls.items():
            col = str(col).strip().lower()
            if col not in p.group_cols():
                unverifiable.append(f"group limit on '{col}' (column missing in weights.csv)")
                continue
            g = p.group_of(col)
            default_lim = _num(lim) if not isinstance(lim, dict) else _num(lim.get("default"))
            per = {str(k).strip().upper(): _num(v) for k, v in lim.items()} if isinstance(lim, dict) else {}
            checked.append(f"{col} limit {lim}")
            n_bad = 0
            for d in p.dates:
                lab = g.loc[d]
                ws = W.loc[d]
                for grp in lab.dropna().unique():
                    lim_g = per.get(str(grp).strip().upper(), default_lim)
                    if lim_g is None:
                        continue
                    expo = float(ws[lab == grp].sum())
                    if expo > lim_g + tol:
                        n_bad += 1
                        ev.append({"row": None, "date": d.date(), "ticker": None, "constraint": f"{col}={grp}",
                                   "value": round(expo, 6), "limit": lim_g})
            if n_bad:
                violated.append(f"{col} limit breached on {n_bad} group-date(s)")
    proc = (f"{len(p.dates)} dates x {len(p.tickers)} tickers from weights.csv (missing ticker-date = 0). Declared "
            f"constraints from {src}: {', '.join(checked) or 'none'}. Sum / gross / net tolerance "
            f"{tol} (conventions.portfolio_weight_sum_tolerance); per-name limits tolerance {EPS_WEIGHT}.")
    ins = ["weights", "rules"]
    if violated:
        res.add(cid, NAME, CONFIRMED_ERROR, "Delivered weights violate a declared constraint: " + violated[0] + plab,
                "; ".join(violated).capitalize() + ". The weights table itself contradicts the rules declared for the "
                "portfolio, so the model, its export or the declaration is wrong. "
                f"Observed: sum {observed['sum_min']:.4f}..{observed['sum_max']:.4f}, gross "
                f"{observed['gross_min']:.4f}..{observed['gross_max']:.4f}, weights {observed['weight_min']:.4f}.."
                f"{observed['weight_max']:.4f}." + (" Not verifiable: " + "; ".join(unverifiable) + "." if unverifiable
                                                   else ""),
                ev, proc, action="Fix the optimiser constraints or the export (cash row, rounding, group mapping), or "
                                 "correct the declaration in rules.yaml; re-run.", priority="high", inputs=ins)
        return
    if not declared_any:
        off = sums[((sums - 1.0).abs() > tol) & (sums.abs() > tol)]
        for d, v in off.items():
            add("sum_of_weights", d, None, v, "1 or 0")
        desc = (f"No constraint declared (rules.yaml constraints.portfolio). Observed over {len(p.dates)} dates: sum "
                f"of weights {observed['sum_min']:.4f}..{observed['sum_max']:.4f}, gross "
                f"{observed['gross_min']:.4f}..{observed['gross_max']:.4f}, min weight {observed['weight_min']:.4f}, "
                f"max weight {observed['weight_max']:.4f}, dates with a short {observed['n_negative_dates']}"
                + (f", cash ticker {cash}" if cash else "") + ".")
        if len(off):
            res.add(cid, NAME, NEEDS_REVIEW, f"Weights do not sum to 1 or 0 on {len(off)} date(s) and nothing is "
                    "declared" + plab, desc + f" On {len(off)} date(s) the sum is neither 1 (fully invested) nor 0 (market "
                    "neutral) within the tolerance: a cash row is probably missing, or the weights are not fractions "
                    "of NAV.", ev, proc, action="Declare the constraints (long_only, max_weight, gross_leverage_max, "
                    "net_exposure, cash_ticker) in rules.yaml and add the cash row if the portfolio holds cash.",
                    inputs=ins)
        else:
            res.add(cid, NAME, INFO, "No portfolio constraint declared: observed ranges only" + plab, desc
                    + " Declare the constraints so they can be verified date by date.", ev, proc,
                    action="Declare constraints.portfolio in rules.yaml.", priority="low", inputs=ins)
        return
    if unverifiable:
        res.add(cid, NAME, NEEDS_REVIEW, "Declared constraints hold where verifiable; some could not be checked: "
                + unverifiable[0] + plab, "Verified on every date: " + "; ".join(checked) + ". Not verifiable: "
                + "; ".join(unverifiable) + ".", ev, proc,
                action="Add the missing classification column to weights.csv.", inputs=ins)
        return
    res.add(cid, NAME, PASS, "Declared constraints hold on every date" + plab,
            f"Verified on {len(p.dates)} dates: " + "; ".join(checked) + f". Observed sum "
            f"{observed['sum_min']:.4f}..{observed['sum_max']:.4f}, gross {observed['gross_min']:.4f}.."
            f"{observed['gross_max']:.4f}, max weight {observed['weight_max']:.4f}.", ev, proc, inputs=ins)


def ucits_5_10_40(w: pd.Series) -> dict[str, Any]:
    """UCITS 2009/65/EC art. 52: no single issuer above 10% and the sum of positions above 5% at most 40% (long
    weights, cash excluded). Returns the breaches on one date."""
    a = w[w > 0]
    over10 = a[a > 0.10 + EPS_WEIGHT]
    big = a[a > 0.05 + EPS_WEIGHT]
    return {"over_10": list(over10.index), "sum_over_5": float(big.sum()), "breach": bool(len(over10))
            or float(big.sum()) > 0.40 + EPS_WEIGHT}


def check_concentration(pkg: Any, res: AuditResult) -> None:
    cid, title = "portfolio_concentration", "Concentration of the weights"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    pans = panels(pkg)
    if not pans:
        not_executable(res, cid, NAME, title, "weights.csv has no row with date, ticker and weight")
        return
    decl, src = constraints(pkg)
    review_hhi = float(pkg.conv("portfolio_hhi_review", 0.20))
    mw = _num(decl.get("max_weight"))
    for p in pans:
        cash = cash_ticker(decl, p.tickers)
        cols = [t for t in p.tickers if t != cash]
        if not cols or p.all_zero():
            not_executable(res, cid, NAME, title + p.label(), "only the cash ticker in the weights, or every weight "
                           "is zero")
            continue
        W = p.wide[cols]
        rows = []
        gcols = p.group_cols()
        groups = {c: p.group_of(c) for c in gcols}
        for d in p.dates:
            w = W.loc[d].to_numpy(dtype=float)
            largest_t = W.loc[d].abs().idxmax()
            r = {"date": d.date(), "hhi": hhi(w), "effective_n": effective_n(w), "top5_share": top_share(w),
                 "largest_weight": float(np.abs(w).max()), "largest_ticker": largest_t,
                 "n_held": int((np.abs(w) > 0).sum())}
            for c in gcols:
                lab = groups[c].loc[d]
                expo = W.loc[d].groupby(lab).sum()
                if len(expo):
                    r[f"max_{c}"] = str(expo.abs().idxmax())
                    r[f"max_{c}_share"] = float(expo.abs().max())
            u = ucits_5_10_40(W.loc[d])
            r["ucits_breach"] = u["breach"]
            rows.append(r)
        df = pd.DataFrame(rows)
        worst = df.loc[df["hhi"].idxmax()]
        big = df.loc[df["largest_weight"].idxmax()]
        summary = {"median_hhi": float(df["hhi"].median()), "worst_hhi": float(worst["hhi"]),
                   "worst_hhi_date": worst["date"], "median_effective_n": float(df["effective_n"].median()),
                   "min_effective_n": float(df["effective_n"].min()), "max_top5_share": float(df["top5_share"].max()),
                   "max_single_weight": float(big["largest_weight"]), "max_single_ticker": big["largest_ticker"],
                   "max_single_date": big["date"], "n_dates_ucits_breach": int(df["ucits_breach"].sum())}
        for c in gcols:
            if f"max_{c}_share" in df.columns:
                summary[f"max_{c}_share"] = float(df[f"max_{c}_share"].max())
        res.metrics.setdefault(cid, {})[p.name or "default"] = summary
        ev = [{"row": p.row(pd.Timestamp(r["date"]), r["largest_ticker"]), **{k: (round(v, 4) if isinstance(v, float)
              else v) for k, v in r.items() if k != "ucits_breach"}} for r in
              sorted(rows, key=lambda x: -x["hhi"])]
        proc = (f"Per date: HHI = sum (|w| / sum|w|)^2 over {len(cols)} tickers" + (f" (cash ticker {cash} excluded)"
                if cash else "") + ", effective N = 1 / HHI, top-5 share and largest |w| as fractions of the gross; "
                "group exposure per classification column; UCITS 5/10/40 on long weights. Review when the worst-date "
                f"HHI > {review_hhi} (conventions.portfolio_hhi_review) or a single name > 25% without a declared "
                "max_weight that allows it.")
        reasons = []
        if summary["worst_hhi"] > review_hhi:
            reasons.append(f"worst-date HHI {summary['worst_hhi']:.3f} (effective N {1 / summary['worst_hhi']:.1f}) on "
                           f"{summary['worst_hhi_date']} is above {review_hhi} (effective N {1 / review_hhi:.0f})")
        if summary["max_single_weight"] > 0.25 and not (mw is not None and mw >= summary["max_single_weight"]):
            reasons.append(f"{summary['max_single_ticker']} reaches {summary['max_single_weight']:.1%} on "
                           f"{summary['max_single_date']} with no declared max_weight that allows it")
        desc = (f"Median HHI {summary['median_hhi']:.3f} (effective N {summary['median_effective_n']:.1f}); worst date "
                f"{summary['worst_hhi_date']}: HHI {summary['worst_hhi']:.3f}, effective N {summary['min_effective_n']:.1f}; "
                f"max top-5 share {summary['max_top5_share']:.1%}; largest single weight {summary['max_single_weight']:.1%} "
                f"({summary['max_single_ticker']}, {summary['max_single_date']})."
                + "".join(f" Max {c} exposure {summary[f'max_{c}_share']:.1%}." for c in gcols if f"max_{c}_share" in summary))
        ins = ["weights", "rules"]
        if reasons:
            res.add(cid, NAME, NEEDS_REVIEW, "Concentrated weights: " + reasons[0], desc + " " + "; ".join(reasons)
                    + ". Concentration is where estimation error in an optimiser shows first: mean-variance weights "
                    "amplify small errors in the expected returns (Chopra and Ziemba 1993; Michaud 1989) and the "
                    "out-of-sample gain over 1/N is rarely enough to pay for it (DeMiguel, Garlappi and Uppal 2009). A "
                    "person must confirm the concentration is intended and within the mandate.",
                    ev, proc, action="Declare the concentration limits (max_weight, group_limits) in rules.yaml, or add "
                                     "shrinkage / position caps to the optimiser.", inputs=ins)
        else:
            res.add(cid, NAME, INFO, "Concentration of the weights (context)", desc + " Within the review thresholds; "
                    "shown for context (estimation error in optimisers concentrates weights: Chopra and Ziemba 1993, "
                    "DeMiguel, Garlappi and Uppal 2009).", ev, proc, priority="low", inputs=ins)
        if summary["n_dates_ucits_breach"]:
            uev = []
            for d in p.dates:
                u = ucits_5_10_40(W.loc[d])
                if u["breach"]:
                    uev.append({"row": None, "date": d.date(), "names_over_10pct": u["over_10"],
                                "sum_of_positions_over_5pct": round(u["sum_over_5"], 4)})
            res.add(cid, NAME, INFO, f"The portfolio would breach the UCITS 5/10/40 rule on "
                    f"{summary['n_dates_ucits_breach']} date(s)",
                    "A single issuer above 10% of NAV, or positions above 5% adding to more than 40%, is not allowed "
                    "for a UCITS fund (Directive 2009/65/EC, art. 52). The rule applies only to UCITS funds and was not "
                    "declared here; shown because it is the most common declared concentration constraint.",
                    uev, "Per date on long weights: any name > 10%; sum of names > 5% compared with 40%.",
                    action="If the vehicle is a UCITS fund declare the rule (max_weight 0.10 and the 40% bucket) so it "
                           "is enforced; otherwise ignore.", priority="low", inputs=ins)


def rebalance_period_key(d: pd.Timestamp, freq: str):
    if freq == "daily":
        return d.date()
    if freq == "weekly":
        iso = d.isocalendar()
        return (iso[0], iso[1])
    if freq in ("biweekly", "fortnightly"):
        iso = d.isocalendar()
        return (iso[0], iso[1] // 2)
    if freq == "monthly":
        return (d.year, d.month)
    if freq == "bimonthly":
        return (d.year, (d.month - 1) // 2)
    if freq == "quarterly":
        return (d.year, (d.month - 1) // 3)
    if freq in ("semiannual", "semi-annual", "semi_annual"):
        return (d.year, (d.month - 1) // 6)
    return d.year


def check_turnover(pkg: Any, res: AuditResult) -> None:
    cid, title = "portfolio_turnover", "Turnover of the weight path"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    pans = panels(pkg)
    if not pans:
        not_executable(res, cid, NAME, title, "weights.csv has no row with date, ticker and weight")
        return
    decl, src = constraints(pkg)
    px = price_matrix(pkg)
    review_annual = float(pkg.conv("portfolio_turnover_review_annual", 3.0))
    declared_max = _num(decl.get("turnover_max_annual"))
    freq = str(decl.get("rebalance_frequency") or "").strip().lower() or None
    if freq is not None and freq not in FREQ_PER_YEAR:
        freq = None
    for p in pans:
        if len(p.dates) < 2 or p.all_zero():
            not_executable(res, cid, NAME, title + p.label(), "fewer than 2 weight dates, or every weight is zero: "
                           "no turnover to measure")
            continue
        W = p.wide
        drift_applied = px is not None and any(t in px.columns for t in p.tickers)
        P = px.reindex(columns=p.tickers).ffill() if drift_applied else None
        rows = []
        seen_periods: set = set()
        for i in range(1, len(p.dates)):
            d0, d1 = p.dates[i - 1], p.dates[i]
            w0 = W.loc[d0].to_numpy(dtype=float)
            w1 = W.loc[d1].to_numpy(dtype=float)
            ratio = None
            if drift_applied:
                p0 = P.reindex([d0], method="ffill").iloc[0].to_numpy(dtype=float)
                p1 = P.reindex([d1], method="ffill").iloc[0].to_numpy(dtype=float)
                ratio = np.where(np.isfinite(p0) & np.isfinite(p1) & (p0 > 0), p1 / p0, 1.0)
            raw = one_way_turnover(w1, w0)
            to = one_way_turnover(w1, w0, ratio)
            traded = to > ZERO_TURNOVER
            is_reb = True
            if freq is not None:
                key = rebalance_period_key(d1, freq)
                if i == 1:
                    seen_periods.add(rebalance_period_key(d0, freq))
                is_reb = key not in seen_periods
                if traded:
                    seen_periods.add(key)
            rows.append({"date": d1.date(), "turnover": to, "turnover_without_drift": raw, "traded": traded,
                         "rebalance_date": bool(is_reb), "days": (d1 - d0).days})
        df = pd.DataFrame(rows)
        span_days = max(1, (p.dates[-1] - p.dates[0]).days)
        years = span_days / 365.25
        total = float(df["turnover"].sum())
        annual = total / years
        n_trade = int(df["traded"].sum())
        trades_per_year = n_trade / years
        zero_share = 1.0 - n_trade / len(df)
        off = df[df["traded"] & ~df["rebalance_date"]] if freq else df.iloc[0:0]
        off_big = off[off["turnover"] > NON_REBALANCE_TRADE]
        summary = {"n_intervals": len(df), "annual_turnover": annual, "mean_turnover": float(df["turnover"].mean()),
                   "max_turnover": float(df["turnover"].max()), "max_turnover_date": df.loc[df["turnover"].idxmax(), "date"],
                   "n_trade_dates": n_trade, "trades_per_year": trades_per_year, "zero_turnover_share": zero_share,
                   "drift_applied": drift_applied, "declared_frequency": freq,
                   "expected_rebalances_per_year": FREQ_PER_YEAR.get(freq) if freq else None,
                   "n_changes_on_non_rebalance_dates": int(len(off)), "span_years": years,
                   "annual_turnover_without_drift": float(df["turnover_without_drift"].sum()) / years}
        res.metrics.setdefault(cid, {})[p.name or "default"] = summary
        ev = [{"row": None, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}}
              for r in sorted(rows, key=lambda x: -x["turnover"])]
        proc = ("One-way turnover between consecutive weight dates = 0.5 x sum |w_t - w_(t-1)"
                + (" drifted|, the previous weights drifted by the price ratios of prices.csv (NAV factor "
                   "1 + sum w (r - 1)) so buy-and-hold drift is not counted as trading" if drift_applied else
                   "| (no prices: drift cannot be removed, so part of the turnover may be drift)")
                + f"; annualised = total / {years:.2f} years of span; a date trades when turnover > {ZERO_TURNOVER}."
                + (f" Declared rebalance frequency {freq} ({FREQ_PER_YEAR[freq]}/year): a change is a rebalance when it is "
                   f"the first in its {freq} period; a change above {NON_REBALANCE_TRADE} on another date is a trade "
                   "outside the schedule." if freq else ""))
        limit_txt = (f"declared turnover_max_annual {declared_max}" if declared_max is not None else
                     f"conventions.portfolio_turnover_review_annual {review_annual}")
        limit = declared_max if declared_max is not None else review_annual
        desc = (f"Annual one-way turnover {annual:.2f}x" + (" net of drift" if drift_applied else "")
                + f" ({total:.2f} over {years:.2f} years; without the drift correction "
                  f"{summary['annual_turnover_without_drift']:.2f}x); {n_trade} of {len(df)} intervals with a trade "
                f"({trades_per_year:.1f} per year), {zero_share:.0%} with none; largest {summary['max_turnover']:.2f} on "
                f"{summary['max_turnover_date']}.")
        ins = ["weights", "prices", "rules"]
        if freq and len(off_big) and drift_applied:
            res.add(cid, NAME, CONFIRMED_ERROR, f"Weights change on {len(off_big)} date(s) outside the declared {freq} "
                    "rebalance schedule, not explained by drift", desc + f" With prices the drift of the previous "
                    f"weights is removed, and {len(off_big)} change(s) above {NON_REBALANCE_TRADE} remain on dates that are "
                    f"not the first rebalance of their {freq} period (declared in {src}): the delivered path trades more "
                    "often than declared.", [e for e in ev if e["traded"] and not e["rebalance_date"]]
                    + [e for e in ev if not (e["traded"] and not e["rebalance_date"])],
                    proc, action="Align the declaration (rebalance_frequency) with the model, or fix the export so that "
                                 "only rebalance dates carry new target weights.", priority="high", inputs=ins)
            continue
        reasons = []
        if annual > limit:
            reasons.append(f"annual turnover {annual:.2f}x is above the {limit_txt}")
        if freq:
            exp_py = FREQ_PER_YEAR[freq]
            if trades_per_year > 1.5 * exp_py and years >= 0.1:
                reasons.append(f"{trades_per_year:.1f} trade dates per year is incompatible with the declared {freq} "
                               f"rebalance ({exp_py}/year)")
            if len(off_big) and not drift_applied:
                reasons.append(f"{len(off_big)} change(s) on non-rebalance dates that cannot be separated from drift "
                               "without prices.csv")
        if reasons:
            res.add(cid, NAME, NEEDS_REVIEW, "Turnover to review: " + reasons[0], desc + " " + "; ".join(reasons)
                    + ". High turnover makes the paper result sensitive to costs that the weight path does not carry.",
                    ev, proc, action="Compare with the declared frequency and cost budget; provide prices.csv so drift "
                                     "can be separated from trading.", inputs=ins)
        else:
            res.add(cid, NAME, INFO, "Turnover of the weight path (context)", desc
                    + (f" Compatible with the declared {freq} rebalance." if freq else " No rebalance frequency declared.")
                    + (" Drift removed with prices." if drift_applied else " No prices: drift not removed."),
                    ev, proc, priority="low", inputs=ins)


def check_weights_vs_positions(pkg: Any, res: AuditResult) -> None:
    cid, title = "portfolio_weights_vs_positions", "Declared weights vs the weights implied by the positions"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    pans = panels(pkg)
    px = price_matrix(pkg)
    pos = pkg.df("positions")
    if not pans or px is None or pos is None:
        not_executable(res, cid, NAME, title, "weights, positions or prices without usable rows")
        return
    decl, _ = constraints(pkg)
    tol = float(pkg.conv("portfolio_drift_tolerance", 0.02))
    q = pos.dropna(subset=["date", "ticker", "quantity"]).copy()
    q["date"] = q["date"].dt.normalize()
    if "portfolio" in q.columns and q["portfolio"].notna().any() and len(pans) > 1:
        q["portfolio"] = q["portfolio"].astype(str)
    Q = q.pivot_table(index="date", columns="ticker", values="quantity", aggfunc="sum").sort_index().fillna(0.0)
    P = px.reindex(columns=Q.columns).ffill()
    pdates = list(Q.index)
    for p in pans:
        cash = cash_ticker(decl, p.tickers)
        rows = []
        n_pairs = 0
        n_bad = 0
        for d in p.dates:
            cands = [x for x in pdates if x >= d]
            if not cands:
                continue
            cands = [c for c in cands[:2] if (c - d).days <= 7]  # same date or one session of lag for execution
            if not cands:
                continue
            best = None
            for c in cands:
                pr = P.reindex([c], method="ffill").iloc[0]
                val = (Q.loc[c] * pr).dropna()
                g = float(val.abs().sum())
                if g <= 0:
                    continue
                implied = val / g
                decl_w = p.wide.loc[d].drop(labels=[cash], errors="ignore")
                gd = float(decl_w.abs().sum())
                if gd <= 0:
                    continue
                decl_w = decl_w / gd
                names = sorted(set(implied.index) | set(decl_w[decl_w.abs() > 0].index))
                diff = pd.Series({t: float(decl_w.get(t, 0.0) - implied.get(t, 0.0)) for t in names})
                cand = (float(diff.abs().max()), c, diff, implied, decl_w)
                if best is None or cand[0] < best[0]:
                    best = cand
            if best is None:
                continue
            mx, c, diff, implied, decl_w = best
            bad = diff[diff.abs() > tol]
            n_pairs += len(diff)
            n_bad += len(bad)
            rows.append({"date": d.date(), "positions_date": c.date(), "max_abs_diff": mx,
                         "mean_abs_diff": float(diff.abs().mean()), "n_names": len(diff), "n_over_tolerance": len(bad),
                         "worst_ticker": diff.abs().idxmax(), "declared": float(decl_w.get(diff.abs().idxmax(), 0.0)),
                         "implied": float(implied.get(diff.abs().idxmax(), 0.0))})
        if not rows:
            not_executable(res, cid, NAME, title + p.label(), "no weights date with positions on the same date or the next "
                           "session (within 7 days) and prices")
            continue
        df = pd.DataFrame(rows)
        share = n_bad / n_pairs if n_pairs else float("nan")
        summary = {"n_dates": len(df), "share_over_tolerance": share, "max_abs_diff": float(df["max_abs_diff"].max()),
                   "mean_abs_diff": float(df["mean_abs_diff"].mean()), "tolerance": tol}
        res.metrics.setdefault(cid, {})[p.name or "default"] = summary
        ev = [{"row": p.row(pd.Timestamp(r["date"]), r["worst_ticker"]), **{k: (round(v, 4) if isinstance(v, float)
              else v) for k, v in r.items()}} for r in sorted(rows, key=lambda x: -x["max_abs_diff"])]
        proc = ("Implied weight = quantity x close / sum |quantity x close| over the positions of the date (prices.csv, "
                "last close on or before the date); declared weights normalised by their gross (cash excluded); "
                "compared on the same date or the next positions date within 7 days (one session of lag for "
                f"execution), keeping the closer of the two. A ticker-date differs when |declared - implied| > {tol} "
                "(conventions.portfolio_drift_tolerance); confirmed error when more than 10% of the ticker-dates differ.")
        desc = (f"{len(df)} weights dates compared; {n_bad} of {n_pairs} ticker-dates differ by more than {tol:.0%} "
                f"({share:.1%}); max |difference| {summary['max_abs_diff']:.3f}, mean {summary['mean_abs_diff']:.4f}.")
        ins = ["weights", "positions", "prices"]
        if share > 0.10:
            res.add(cid, NAME, CONFIRMED_ERROR, f"The positions held are not the declared weights ({share:.0%} of the "
                    "ticker-dates differ)", desc + " The book that was actually held differs from the weights the model "
                    "reports, beyond execution lag and the tolerance: the weights are not what was implemented, or "
                    "the positions file is another portfolio.", ev, proc,
                    action="Reconcile the export of the target weights with the executed positions (cash, lot "
                           "rounding, unexecuted orders); confirm both files describe the same portfolio.",
                    priority="high", inputs=ins)
        else:
            res.add(cid, NAME, PASS, "Positions agree with the declared weights", desc + " Within tolerance after "
                    "allowing one session of lag.", ev, proc, inputs=ins)


def check_vs_naive(pkg: Any, res: AuditResult) -> None:
    cid, title = "portfolio_vs_naive", "Realised weight path vs the 1/N portfolio"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    pans = panels(pkg)
    px = price_matrix(pkg)
    if not pans or px is None:
        not_executable(res, cid, NAME, title, "weights or prices without usable rows")
        return
    decl, _ = constraints(pkg)
    min_dates = int(pkg.conv("portfolio_min_dates", 12))
    alpha = float(pkg.conv("portfolio_naive_alpha", 0.05))
    bench = return_series(pkg.df("benchmark_returns"))
    for p in pans:
        if len(p.dates) < min_dates:
            not_executable(res, cid, NAME, title + p.label(), f"{len(p.dates)} weight dates, fewer than "
                           f"{min_dates} (conventions.portfolio_min_dates)")
            continue
        cash = cash_ticker(decl, p.tickers)
        try:
            rp, info = simulate(p, px, cash=cash)
            rn, _ = simulate(p, px, naive=True, cash=cash)
        except ValueError as e:
            not_executable(res, cid, NAME, title + p.label(), str(e))
            continue
        common = rp.index.intersection(rn.index)
        if len(common) < min_dates:
            not_executable(res, cid, NAME, title + p.label(), f"only {len(common)} return periods after the first "
                           "applied weights")
            continue
        rp, rn = rp.loc[common], rn.loc[common]
        ppy = infer_ppy(list(px.index))
        m_p, m_n = perf(rp.to_numpy(), ppy), perf(rn.to_numpy(), ppy)
        jk = jobson_korkie_memmel(rp.to_numpy(), rn.to_numpy())
        te_n = float((rp - rn).std(ddof=1)) * math.sqrt(ppy)
        ev = [{"series": "model weights", **{k: round(v, 4) for k, v in m_p.items()}},
              {"series": "1/N of the same names", **{k: round(v, 4) for k, v in m_n.items()},
               "tracking_error_vs_model": round(te_n, 4)}]
        m_b = None
        if bench is not None:
            cb = common.intersection(bench.index)
            if len(cb) >= min_dates:
                m_b = perf(bench.loc[cb].to_numpy(), ppy)
                te_b = float((rp.loc[cb] - bench.loc[cb]).std(ddof=1)) * math.sqrt(ppy)
                jk_b = jobson_korkie_memmel(rp.loc[cb].to_numpy(), bench.loc[cb].to_numpy())
                ev.append({"series": "benchmark_returns.csv", **{k: round(v, 4) for k, v in m_b.items()},
                           "tracking_error_vs_model": round(te_b, 4), "jk_z_model_minus_benchmark": round(jk_b["z"], 3),
                           "p_one_sided": round(jk_b["p_one_sided"], 4)})
        ev.append({"series": "Sharpe difference model - 1/N", "z": round(jk["z"], 3),
                   "p_one_sided": round(jk["p_one_sided"], 4), "p_two_sided": round(jk["p_two_sided"], 4),
                   "rho": round(jk["rho"], 3), "T": jk["T"]})
        summary = {"model": m_p, "naive": m_n, "benchmark": m_b, "tracking_error_vs_naive": te_n, "jk": jk,
                   "ppy": ppy, "n_rebalances": info["n_rebalances"], "dropped_unpriced": info["dropped_unpriced"]}
        res.metrics.setdefault(cid, {})[p.name or "default"] = summary
        proc = (f"Weights dated d applied at the close of the first price date after d and drifted until the next; no "
                f"costs; cash at zero. 1/N = equal weight of the names held on each weights date. {ppy} periods per year "
                f"inferred from the price dates; {len(common)} periods from {common[0].date()}. Sharpe difference tested "
                "with z = (SR1 - SR2) / sqrt((2(1 - rho) + 0.5(SR1^2 + SR2^2) - SR1 SR2 rho^2) / T) (Jobson and Korkie "
                f"1981, Memmel 2003 correction), one-sided H1: model > 1/N at alpha {alpha} "
                "(conventions.portfolio_naive_alpha). Ledoit and Wolf (2008) is the robust alternative under "
                "heavy tails and autocorrelation; it needs a bootstrap and is not implemented here.")
        desc = (f"Model: annual return {m_p['annual_return']:.1%}, volatility {m_p['volatility']:.1%}, Sharpe "
                f"{m_p['sharpe']:.2f}, max drawdown {m_p['max_drawdown']:.1%}. 1/N of the same names: return "
                f"{m_n['annual_return']:.1%}, volatility {m_n['volatility']:.1%}, Sharpe {m_n['sharpe']:.2f}, max drawdown "
                f"{m_n['max_drawdown']:.1%}; tracking error {te_n:.1%}. Sharpe difference z = {jk['z']:.2f}, one-sided "
                f"p = {jk['p_one_sided']:.3f}."
                + (f" Benchmark: return {m_b['annual_return']:.1%}, Sharpe {m_b['sharpe']:.2f}." if m_b else "")
                + (f" Unpriced names dropped: {', '.join(info['dropped_unpriced'][:5])}." if info["dropped_unpriced"]
                   else ""))
        ins = ["weights", "prices", "benchmark_returns"]
        beats = math.isfinite(jk["p_one_sided"]) and jk["p_one_sided"] < alpha and jk["sr1"] > jk["sr2"]
        if not beats:
            res.add(cid, NAME, NEEDS_REVIEW, "The weight path does not beat 1/N of the same names in Sharpe at "
                    f"alpha {alpha}", desc + " An optimiser that does not beat the equal-weight portfolio out of sample "
                    "is common and is NOT an error (DeMiguel, Garlappi and Uppal 2009: with estimation error, 1/N is hard "
                    "to beat for realistic sample sizes). It does mean the construction adds no measurable value over "
                    "the naive rule on this sample; a person should decide whether the extra complexity, turnover and "
                    "concentration are justified.", ev, proc,
                    action="Report 1/N as the mandatory comparator; consider shrinkage, constraints or a longer sample "
                           "before claiming value added by the optimiser.", inputs=ins)
        else:
            res.add(cid, NAME, INFO, f"The weight path beats 1/N in Sharpe (one-sided p {jk['p_one_sided']:.3f})",
                    desc + " The difference is significant on this sample under the Jobson-Korkie-Memmel test (normal "
                    "i.i.d. assumption; see the procedure for the robust alternative).", ev, proc, priority="low",
                    inputs=ins)


def strategy_text(pkg: Any) -> str:
    rules = pkg.rules if isinstance(pkg.rules, dict) else {}
    s = rules.get("strategy")
    parts = []
    if isinstance(s, dict):
        parts += [str(v) for v in s.values() if isinstance(v, str)]
    elif s is not None:
        parts.append(str(s))
    for k in ("description", "name", "objective", "mandate"):
        if isinstance(rules.get(k), str):
            parts.append(rules[k])
    return " ".join(parts).lower()


def check_active_share(pkg: Any, res: AuditResult) -> None:
    cid, title = "portfolio_active_share", "Active share vs the benchmark weights"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    pans = panels(pkg)
    bw = pkg.df("benchmark_weights")
    if not pans or bw is None:
        not_executable(res, cid, NAME, title, "weights or benchmark_weights without usable rows")
        return
    b = bw.dropna(subset=["date", "ticker", "weight"]).copy()
    b["date"] = b["date"].dt.normalize()
    if b.empty:
        not_executable(res, cid, NAME, title, "benchmark_weights.csv has no usable row")
        return
    B = b.pivot_table(index="date", columns="ticker", values="weight", aggfunc="sum").sort_index().fillna(0.0)
    decl, _ = constraints(pkg)
    px = price_matrix(pkg)
    text = strategy_text(pkg)
    says_active = any(k in text for k in ("active", "alpha", "stock picking", "stock-picking", "conviction"))
    says_index = any(k in text for k in ("index", "tracker", "tracking", "passive", "replicat"))
    for p in pans:
        if p.all_zero():
            not_executable(res, cid, NAME, title + p.label(), "every weight is zero (example or empty table)")
            continue
        cash = cash_ticker(decl, p.tickers)
        rows = []
        for d in p.dates:
            bd = B.index[B.index <= d]
            if not len(bd):
                continue
            wb = B.loc[bd[-1]]
            w = p.wide.loc[d].drop(labels=[cash], errors="ignore")
            names = sorted(set(w.index) | set(wb.index))
            wv = np.array([float(w.get(t, 0.0)) for t in names])
            bv = np.array([float(wb.get(t, 0.0)) for t in names])
            held = np.abs(wv) > 0
            outside = int((held & (bv == 0)).sum())
            rows.append({"date": d.date(), "benchmark_date": bd[-1].date(), "active_share": active_share(wv, bv),
                         "n_held": int(held.sum()), "n_outside_benchmark": outside,
                         "share_outside_benchmark": outside / held.sum() if held.sum() else float("nan"),
                         "benchmark_sum": float(bv.sum())})
        if not rows:
            not_executable(res, cid, NAME, title + p.label(), "no benchmark weights dated on or before a weights date")
            continue
        df = pd.DataFrame(rows)
        med = float(df["active_share"].median())
        te = None
        if px is not None:
            try:
                rp, _ = simulate(p, px, cash=cash)
                bpanel = Panel(None, b.assign(row=0) if "row" not in b.columns else b)
                rb, _ = simulate(bpanel, px)
                cm = rp.index.intersection(rb.index)
                if len(cm) >= 12:
                    te = float((rp.loc[cm] - rb.loc[cm]).std(ddof=1)) * math.sqrt(infer_ppy(list(px.index)))
            except ValueError:
                te = None
        summary = {"median_active_share": med, "min_active_share": float(df["active_share"].min()),
                   "max_active_share": float(df["active_share"].max()),
                   "median_share_outside_benchmark": float(df["share_outside_benchmark"].median()),
                   "tracking_error": te, "strategy_says_active": says_active, "strategy_says_index": says_index}
        res.metrics.setdefault(cid, {})[p.name or "default"] = summary
        ev = [{"row": None, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}} for r in rows]
        proc = ("Per weights date, with the benchmark weights of the latest benchmark date on or before it: active share "
                "= 0.5 x sum |w - w_b| over the union of names (cash excluded from w); names held with zero benchmark "
                "weight counted as outside the benchmark" + ("; tracking error = std of the simulated model path minus "
                "the simulated benchmark-weights path, annualised (prices.csv, no costs)" if te is not None else "")
                + ". Review when rules.yaml strategy text says active / alpha and the median active share is below 0.20, "
                "or says index / tracker and it is above 0.20 (Cremers and Petajisto 2009).")
        desc = (f"Median active share {med:.1%} (min {summary['min_active_share']:.1%}, max "
                f"{summary['max_active_share']:.1%}) over {len(df)} dates; median share of held names outside the "
                f"benchmark {summary['median_share_outside_benchmark']:.0%}"
                + (f"; tracking error {te:.1%}" if te is not None else "") + ".")
        ins = ["weights", "benchmark_weights", "prices", "rules"]
        if says_active and not says_index and med < 0.20:
            res.add(cid, NAME, NEEDS_REVIEW, f"Closet indexing: declared active but median active share {med:.0%}",
                    desc + " The declared strategy text speaks of active management / alpha, but the weights barely "
                    "depart from the benchmark: Cremers and Petajisto (2009) call funds below 20% active share closet "
                    "indexers (and need about 60% for a fund to be 'truly active'). The fee and the narrative may not "
                    "match what the portfolio does.", ev, proc,
                    action="Confirm the mandate; if active, document the sources of active risk; if not, declare it as "
                           "an index-tracking portfolio.", inputs=ins)
        elif says_index and not says_active and med > 0.20:
            res.add(cid, NAME, NEEDS_REVIEW, f"Declared index tracking but median active share {med:.0%}",
                    desc + " The declared strategy text speaks of index tracking, yet the weights depart from the "
                    "benchmark composition by more than 20% on a typical date: either the benchmark weights file is "
                    "not the index tracked or the portfolio takes active positions.", ev, proc,
                    action="Confirm the benchmark composition file and the tracking tolerance of the mandate.",
                    inputs=ins)
        else:
            res.add(cid, NAME, INFO, f"Active share vs the benchmark: median {med:.0%}", desc
                    + (" The strategy text mentions both active and index terms; no contrast made." if says_active
                       and says_index else " No conflicting declaration found in the rules.yaml strategy text."),
                    ev, proc, priority="low", inputs=ins)


def run(pkg: Any, res: AuditResult) -> None:
    for fn, cid in ((check_constraints, "portfolio_constraints"), (check_concentration, "portfolio_concentration"),
                    (check_turnover, "portfolio_turnover"),
                    (check_weights_vs_positions, "portfolio_weights_vs_positions"),
                    (check_vs_naive, "portfolio_vs_naive"), (check_active_share, "portfolio_active_share")):
        try:
            fn(pkg, res)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------- spec

_REFS = {
    "cz93": "Chopra, V. K. and Ziemba, W. T. (1993). The Effect of Errors in Means, Variances, and Covariances on "
            "Optimal Portfolio Choice. Journal of Portfolio Management 19(2), 6-11.",
    "michaud89": "Michaud, R. O. (1989). The Markowitz Optimization Enigma: Is 'Optimized' Optimal? Financial Analysts "
                 "Journal 45(1), 31-42.",
    "jk81": "Jobson, J. D. and Korkie, B. M. (1981). Performance Hypothesis Testing with the Sharpe and Treynor "
            "Measures. Journal of Finance 36(4), 889-908.",
    "memmel03": "Memmel, C. (2003). Performance Hypothesis Testing with the Sharpe Ratio. Finance Letters 1, 21-23.",
    "cp09": "Cremers, K. J. M. and Petajisto, A. (2009). How Active Is Your Fund Manager? A New Measure That Predicts "
            "Performance. Review of Financial Studies 22(9), 3329-3365.",
    "lw08": "Ledoit, O. and Wolf, M. (2008). Robust Performance Hypothesis Testing with the Sharpe Ratio. Journal of "
            "Empirical Finance 15(5), 850-859.",
    "ucits": "European Parliament and Council (2009). Directive 2009/65/EC (UCITS IV), art. 52: the 5/10/40 "
             "concentration rule.",
    "gk00": "Grinold, R. and Kahn, R. (2000). Active Portfolio Management, 2nd ed. McGraw-Hill.",
    "dgu09": "DeMiguel, V., Garlappi, L. and Uppal, R. (2009). Optimal Versus Naive Diversification: How Inefficient Is "
             "the 1/N Portfolio Strategy? Review of Financial Studies 22(5), 1915-1953.",
    "bacon": "Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution, 2nd ed. Wiley.",
}

SPEC = UseCase(
    name=NAME,
    title="Portfolio construction / asset allocation (target weights)",
    description="Validates a portfolio-construction or asset-allocation model from its target weights over time "
                "(mean-variance, risk parity, Black-Litterman, model portfolios of an advisor or robo-advisor, "
                "index trackers, FCI model portfolios): declared constraints hold on every date, concentration, "
                "turnover net of drift, agreement with the positions actually held, value added over the naive 1/N "
                "portfolio of the same names, and active share against a benchmark composition.",
    audience="portfolio managers, allocators, investment committees, compliance",
    detect_files=["weights"],
    files={"weights": "weights.csv", "benchmark_weights": "benchmark_weights.csv"},
    schema={"weights": {"required": ["date", "ticker", "weight"],
                        "optional": ["portfolio", "asset_class", "sector", "group", "industry", "country"]},
            "benchmark_weights": {"required": ["date", "ticker", "weight"], "optional": ["portfolio"]}},
    aliases={"weights": {"date": ["datetime", "timestamp", "as_of", "rebalance_date"],
                         "ticker": ["symbol", "asset", "instrument"],
                         "weight": ["w", "target_weight", "allocation", "target"],
                         "sector": ["gics_sector", "industry_group"], "asset_class": ["class", "assetclass"],
                         "portfolio": ["portfolio_id", "model", "account"]},
             "benchmark_weights": {"date": ["datetime", "timestamp", "as_of"], "ticker": ["symbol", "asset", "instrument"],
                                   "weight": ["w", "benchmark_weight", "index_weight", "allocation"]}},
    date_columns={"weights": ["date"], "benchmark_weights": ["date"]},
    numeric_columns={"weights": ["weight"], "benchmark_weights": ["weight"]},
    requirements={
        "portfolio_constraints": {"required": ["weights"], "optional": ["rules"]},
        "portfolio_concentration": {"required": ["weights"], "optional": ["rules"]},
        "portfolio_turnover": {"required": ["weights"], "optional": ["prices", "rules"]},
        "portfolio_weights_vs_positions": {"required": ["weights", "positions", "prices"], "optional": ["rules"]},
        "portfolio_vs_naive": {"required": ["weights", "prices"], "optional": ["benchmark_returns", "rules"]},
        "portfolio_active_share": {"required": ["weights", "benchmark_weights"], "optional": ["prices", "rules"]},
    },
    catalog={
        "portfolio_constraints": {
            "title": "Declared portfolio constraints",
            "what": "On every weights date: sum of weights within 1 +/- conventions.portfolio_weight_sum_tolerance "
                    "(0.01) under long_only with no cash ticker (<= 1 when a cash ticker is declared), net exposure "
                    "within the declared net_exposure range, no negative weight under long_only, no weight above "
                    "max_weight, held weights above min_weight, gross leverage sum|w| within gross_leverage_max, and "
                    "group exposures within group_limits (needs the sector / asset_class column). Confirmed error on "
                    "any breach; INFO with the observed ranges when nothing is declared (review when the sum is "
                    "neither 1 nor 0 on some dates, a likely missing cash row); PASS when every declared constraint "
                    "holds on every date.",
            "why": "A weight table that contradicts its own mandate is either a bug in the optimiser or export, or a "
                   "false declaration; both invalidate the backtest of the allocation.",
            "fix": "Fix the constraint handling or the export (cash row, rounding, group mapping) or correct rules.yaml.",
            "allows": "Whether the delivered weights respect what was declared, date by date, with the breaching rows.",
            "does_not_allow": "Judging whether the constraints are sensible, or constraints that were not declared.",
            "refs": ["ucits", "gk00"],
        },
        "portfolio_concentration": {
            "title": "Concentration of the weights",
            "what": "Per date: Herfindahl index of the absolute weights (normalised by the gross), effective number of "
                    "positions 1/HHI, top-5 share, largest name and group exposures; summary over time (median, worst "
                    "date). Review when the worst-date HHI exceeds conventions.portfolio_hhi_review (0.20, effective N "
                    "5) or a single name exceeds 25% without a declared max_weight that allows it; INFO otherwise. A "
                    "separate INFO when the portfolio would breach the UCITS 5/10/40 rule (it applies only to UCITS "
                    "funds).",
            "why": "Estimation error in optimisers concentrates weights in the assets whose inputs were most "
                   "over-estimated; the out-of-sample cost is documented and often exceeds the gain over 1/N.",
            "fix": "Declare and enforce position and group caps; use shrinkage or resampling in the optimiser.",
            "allows": "How concentrated the delivered weights are and when.",
            "does_not_allow": "Whether the concentration was rewarded; that is portfolio_vs_naive.",
            "refs": ["cz93", "michaud89", "dgu09", "ucits"],
        },
        "portfolio_turnover": {
            "title": "Turnover of the weight path",
            "what": "One-way turnover between consecutive weight dates, 0.5 x sum |w_t - drifted w_(t-1)|, with the "
                    "previous weights drifted by the price returns when prices.csv exists (buy-and-hold drift is not "
                    "trading); annualised turnover, trade dates per year vs the declared rebalance_frequency, share of "
                    "dates with no trade. Review when the annual turnover exceeds the declared turnover_max_annual or "
                    "conventions.portfolio_turnover_review_annual (3.0), or when the trade count is incompatible with the "
                    "declared frequency; confirmed error when, with prices, weights change by more than 1% on dates "
                    "outside the declared schedule.",
            "why": "The paper result of a weight path carries no costs; turnover is what the costs will be charged on, "
                   "and a path that trades more often than declared is not the declared model.",
            "fix": "Align the declared frequency with the model or export only rebalance dates; provide prices so drift "
                   "can be separated from trading.",
            "allows": "How much the path trades, net of drift, and whether it matches the declared schedule.",
            "does_not_allow": "The cost of that turnover (costs are not an input of this use case).",
            "refs": ["dgu09", "bacon"],
        },
        "portfolio_weights_vs_positions": {
            "title": "Declared weights vs the weights implied by the positions",
            "what": "When positions.csv and prices.csv exist: implied weights quantity x close / gross, compared with "
                    "the declared weights (normalised, cash excluded) on the same date or the next positions date "
                    "(one session of execution lag); max and mean absolute difference per date. Confirmed error when "
                    "more than 10% of the ticker-dates differ by more than conventions.portfolio_drift_tolerance "
                    "(0.02); PASS when they agree.",
            "why": "A track record belongs to the book that was held, not to the weights a model printed.",
            "fix": "Reconcile target weights with executed positions (cash, lot rounding, unexecuted orders).",
            "allows": "Whether the positions implement the declared weights.",
            "does_not_allow": "Why they differ (costs, liquidity, discretion).",
            "refs": ["bacon"],
        },
        "portfolio_vs_naive": {
            "title": "Realised weight path vs the 1/N portfolio",
            "what": "Realised return of the weight path with prices.csv (weights applied at the next session, drift "
                    "between rebalances, no costs) against the equal-weight portfolio of the same names on the same "
                    "dates and, if benchmark_returns.csv exists, the benchmark: annualised return, volatility, Sharpe, "
                    "max drawdown, tracking error, and the Jobson-Korkie test of the Sharpe difference with the Memmel "
                    "correction. Review when the model does not beat 1/N at conventions.portfolio_naive_alpha (0.05); "
                    "INFO otherwise; not executable without prices or below conventions.portfolio_min_dates (12) weight "
                    "dates.",
            "why": "1/N is the mandatory comparator of any allocation model: with estimation error it is hard to beat "
                   "out of sample, so a model that does not beat it adds complexity without measurable value.",
            "fix": "Report 1/N alongside the model; consider shrinkage, constraints or a longer sample.",
            "allows": "Whether the construction added value over the naive rule on this sample, with a test.",
            "does_not_allow": "That failing to beat 1/N is an error (it is common); robustness to heavy tails (Ledoit "
                              "and Wolf 2008 bootstrap not implemented).",
            "refs": ["dgu09", "jk81", "memmel03", "lw08", "michaud89"],
        },
        "portfolio_active_share": {
            "title": "Active share vs the benchmark weights",
            "what": "When benchmark_weights.csv exists: active share 0.5 x sum |w - w_b| per date, share of held names "
                    "outside the benchmark, tracking error of the two simulated paths when prices exist. INFO with the "
                    "numbers; review when the rules.yaml strategy text says active / alpha and the median active share "
                    "is below 0.20 (closet indexing), or says index / tracker and it is above 0.20.",
            "why": "Fees and narrative follow the declared style; the weights show the real one.",
            "fix": "Confirm the mandate and the benchmark composition file; document the sources of active risk.",
            "allows": "How far the weights depart from the benchmark composition.",
            "does_not_allow": "Whether the active positions were skilful.",
            "refs": ["cp09", "gk00"],
        },
    },
    references=_REFS,
    conventions={"portfolio_weight_sum_tolerance": 0.01, "portfolio_hhi_review": 0.20,
                 "portfolio_turnover_review_annual": 3.0, "portfolio_min_dates": 12, "portfolio_naive_alpha": 0.05,
                 "portfolio_drift_tolerance": 0.02},
    profiles={
        "portfolio_long_only_monthly": {
            "description": "Long-only model portfolio rebalanced monthly (weights are fractions of NAV; constraints "
                           "long_only and rebalance_frequency monthly unless rules.yaml declares otherwise).",
            "conventions": {},
            "portfolio_constraints": {"long_only": True, "rebalance_frequency": "monthly"},
        },
        "portfolio_risk_parity": {
            "description": "Risk-parity allocation: weights inversely related to risk, usually long-only with leverage "
                           "declared through gross_leverage_max; nothing is presumed, declare the constraints.",
            "conventions": {},
        },
    },
    run=run,
)
register(SPEC)
