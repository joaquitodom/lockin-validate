"""Live track record against the backtest that justified it (use case ``live``, 0.3.0).

Audience: portfolio managers who went live, allocators doing due diligence, risk committees. The question is not
"was the backtest honest" (the core answers that) but "is the strategy in production behaving like its simulation,
and has the edge decayed". Inputs (docs/usecases/live.md):

  live_returns.csv   date, return (or nav) [account, aum]      the live or paper-trading record
  returns.csv        date, return (or nav)                      the backtest series; it should cover the live
                                                                period ("shadow" backtest)
  live_trades.csv    timestamp, ticker, side, quantity, price [commission, model_price, model_timestamp, trade_id]
  model_trades.csv   the trades the model wanted (same schema)
  rules.yaml         live: {start, backtest_end, declared_sharpe, declared_annual_return, declared_max_drawdown}

Checks: live_period_integrity, live_vs_shadow_backtest, live_performance_decay, live_structural_break,
live_execution_quality, live_declared_vs_realised. All statistics are implemented here or in ``stats`` (numpy only).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from .. import metrics, stats
from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import review_date
from ..reconciliation import declared_convention, tolerances
from . import UseCase, register

NAME = "live"
_N = NormalDist()
MIN_LIVE = 20  # below this nothing statistical is attempted on the live series
IDENTICAL_TOL = 1e-12
AFFINE_CORR = 0.99999
GAP_DAYS = 30  # fallback only when the native spacing of the series cannot be inferred
GAP_FACTOR = 1.5  # a gap is a spacing above this multiple of the median spacing of the series
GAP_FLOOR_DAYS = 10  # ... and never below this many calendar days (weekends and holidays in daily data)
SMALL_SAMPLE_N = 60  # below this a HAC rejection also needs the iid t to reject, both against t(n-1)
PERCENT_MEDIAN = 0.5  # median |period return| above 50% (or beta ~100 against the shadow): the file is in percent
SIDES = {"buy": "buy", "sell": "sell", "b": "buy", "s": "sell", "long": "buy", "short": "sell"}


# --------------------------------------------------------------------------- statistics (numpy only)

def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def t_cdf(t: float, df: float) -> float:
    """Student t distribution function (regularised incomplete beta, numpy-free)."""
    if not math.isfinite(t):
        return float("nan")
    if df > 1e6:
        return _N.cdf(t)
    x = df / (df + t * t)
    lbeta = math.lgamma(df / 2) + math.lgamma(0.5) - math.lgamma((df + 1) / 2)
    front = math.exp(0.5 * df * math.log(x) + 0.5 * math.log(1 - x) - lbeta) if 0 < x < 1 else 0.0
    if x < (df / 2 + 1) / (df / 2 + 0.5 + 2):
        ib = front * _betacf(df / 2, 0.5, x) / (df / 2)
    else:
        ib = 1 - front * _betacf(0.5, df / 2, 1 - x) / 0.5
    tail = 0.5 * ib
    return tail if t < 0 else 1 - tail


def t_ppf(p: float, df: float) -> float:
    """Quantile of Student t by bisection on :func:`t_cdf`."""
    lo, hi = -50.0, 50.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def significantly_below_zero(h: dict[str, float], alpha: float) -> bool:
    """One-sided test that the mean is below zero, valid in small samples.

    Uses the finite-sample HAC t (variance x n / (n - lags - 1)) against t(n - 1); for n < SMALL_SAMPLE_N the plain iid t
    must reject as well, because the Newey-West variance is biased down at those sizes (see docs).
    """
    n = int(h.get("n", 0))
    ta, ti = h.get("t_adj", float("nan")), h.get("t_iid", float("nan"))
    if n < 3 or not math.isfinite(ta):
        return False
    crit = -t_ppf(1 - alpha, n - 1)
    if ta >= crit:
        return False
    return not (n < SMALL_SAMPLE_N and not (math.isfinite(ti) and ti < crit))


def hac_mean_test(x, lags: int | None = None) -> dict[str, float]:
    """Mean of ``x`` with a Newey-West (Bartlett) standard error. lags default: floor(4 (n/100)^(2/9))."""
    a = stats.clean(x)
    n = a.size
    if n < 3:
        return {"n": n, "mean": float("nan"), "se": float("nan"), "t": float("nan"), "p_value": float("nan"),
                "lags": 0, "t_adj": float("nan"), "t_iid": float("nan"), "p_adj": float("nan")}
    if lags is None:
        lags = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(lags, n - 2))
    e = a - a.mean()
    lrv = float(e @ e) / n
    for k in range(1, lags + 1):
        lrv += 2 * (1 - k / (lags + 1.0)) * float(e[k:] @ e[:-k]) / n
    lrv = max(lrv, 1e-30)
    se = math.sqrt(lrv / n)
    t = float(a.mean()) / se if se > 0 else float("nan")
    se_adj = se * math.sqrt(n / (n - lags - 1.0))
    sd = float(a.std(ddof=1))
    t_adj = float(a.mean()) / se_adj if se_adj > 0 else float("nan")
    t_iid = float(a.mean()) / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    return {"n": int(n), "mean": float(a.mean()), "se": se, "t": t,
            "p_value": 2 * (1 - _N.cdf(abs(t))) if math.isfinite(t) else float("nan"), "lags": lags,
            "t_adj": t_adj, "t_iid": t_iid,
            "p_adj": 2 * (1 - t_cdf(abs(t_adj), n - 1)) if math.isfinite(t_adj) else float("nan")}


def tracking_error(live, bt, ppy: int) -> float:
    """Annualised standard deviation of the return difference (sample ddof = 1)."""
    d = np.asarray(live, dtype=float) - np.asarray(bt, dtype=float)
    if d.size < 2:
        return float("nan")
    return float(np.std(d, ddof=1)) * math.sqrt(ppy)


def sharpe_difference_test(sr1: float, t1: int, sr2: float, t2: int) -> dict[str, float]:
    """z-test for two per-period Sharpe ratios from independent samples (Jobson-Korkie 1981, Memmel 2003 flavour:
    the asymptotic variance of each SR is Lo's (1 + SR^2 / 2) / T; independence makes the covariance zero)."""
    if t1 < 2 or t2 < 2:
        return {"z": float("nan"), "p_value": float("nan")}
    se = math.sqrt(stats.sharpe_se_iid(sr1, t1) ** 2 + stats.sharpe_se_iid(sr2, t2) ** 2)
    z = (sr1 - sr2) / se if se > 0 else float("nan")
    return {"z": z, "p_value": 2 * (1 - _N.cdf(abs(z))) if math.isfinite(z) else float("nan"), "se": se}


def cusum(z, h: float) -> dict[str, Any]:
    """CUSUM of standardised observations z (mean 0, sd 1 under the null), Page (1954) / Brown-Durbin-Evans (1975).

    C_k = sum_{t <= k} z_t. The statistic C_k / sqrt(k) is the z-score of the cumulative mean; an alarm is raised
    the first time |C_k| / sqrt(k) exceeds h (h in standard deviations). A shift of delta sd per period is detected
    after about (h / delta)^2 periods. Returns the index of the first crossing (or None), the direction, the largest
    |C_k| / sqrt(k) and the Brown-Durbin-Evans end statistic C_n / sqrt(n).
    """
    a = np.asarray(z, dtype=float)
    c = np.cumsum(a)
    k = np.arange(1, a.size + 1, dtype=float)
    stat = c / np.sqrt(k) if a.size else np.array([], dtype=float)
    over = np.where(np.abs(stat) > h)[0]
    first = int(over[0]) if over.size else None
    return {"first_crossing": first, "direction": (("down" if stat[first] < 0 else "up") if first is not None else None),
            "max_abs_statistic": float(np.max(np.abs(stat))) if a.size else float("nan"),
            "bde_end_statistic": float(stat[-1]) if a.size else float("nan"), "n": int(a.size), "h": h}


def rolling_sharpe(r, window: int, ppy: int) -> np.ndarray:
    a = np.asarray(r, dtype=float)
    if a.size < window or window < 3:
        return np.array([], dtype=float)
    s = pd.Series(a)
    m = s.rolling(window).mean()
    sd = s.rolling(window).std(ddof=1)
    out = (m / sd * math.sqrt(ppy)).to_numpy()
    return out[np.isfinite(out)]


def percentile_of(value: float, sample) -> float:
    a = np.asarray(sample, dtype=float)
    if a.size == 0 or not math.isfinite(value):
        return float("nan")
    return float((a < value).mean() + 0.5 * (a == value).mean())


# --------------------------------------------------------------------------- series preparation

def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(str(v)).date()
    except Exception:
        return None


def _series(df: pd.DataFrame | None) -> tuple[pd.Series | None, dict[str, Any]]:
    """date -> simple return from a returns table (``return`` column or ``nav`` level), one value per date.

    Several accounts (column ``account``) are averaged per date, AUM-weighted when ``aum`` exists. Duplicated
    (date, account) rows are reported in ``info['duplicates']`` and the first one is kept.
    """
    if df is None or "date" not in df.columns:
        return None, {"reason": "table absent"}
    d = df.dropna(subset=["date"]).copy()
    if d.empty:
        return None, {"reason": "no parseable dates"}
    d["_d"] = d["date"].dt.date
    has_acc = "account" in d.columns and d["account"].notna().any()
    d["_acc"] = d["account"].astype(object).where(d["account"].notna(), "default").astype(str) if has_acc else "default"
    n_nav_missing = 0
    if "return" in d.columns and d["return"].notna().any():
        d = d.dropna(subset=["return"])
        d["_r"] = d["return"].astype(float)
        source = "return"
    elif "nav" in d.columns and d["nav"].notna().sum() >= 3:
        # difference first, drop later: a missing NAV makes the two returns around it NaN instead of merging them
        # into one two-period return that would be compared with one-period shadow returns
        d = d.sort_values(["_acc", "date", "row"])
        n_nav_missing = int(d["nav"].isna().sum())
        d["_r"] = d.groupby("_acc")["nav"].pct_change(fill_method=None)
        d = d.dropna(subset=["_r"])
        source = "nav"
    else:
        return None, {"reason": "no return or nav column with values"}
    d = d.sort_values(["date", "row"])
    dup_mask = d.duplicated(subset=["_d", "_acc"], keep=False)
    dups = [{"row": int(r), "date": dd, "account": acc}
            for r, dd, acc in zip(d.loc[dup_mask, "row"], d.loc[dup_mask, "_d"], d.loc[dup_mask, "_acc"])]
    d = d[~d.duplicated(subset=["_d", "_acc"], keep="first")]
    n_acc = int(d["_acc"].nunique())
    agg = None
    if n_acc > 1:
        if "aum" in d.columns and d["aum"].notna().any():
            w = pd.to_numeric(d["aum"], errors="coerce").fillna(0.0).clip(lower=0.0)
            g = d.assign(_w=w, _wr=w * d["_r"]).groupby("_d")
            s = (g["_wr"].sum() / g["_w"].sum().replace(0.0, np.nan)).fillna(d.groupby("_d")["_r"].mean())
            agg = "AUM-weighted mean across accounts"
        else:
            s = d.groupby("_d")["_r"].mean()
            agg = "equal-weight mean across accounts"
    else:
        s = d.groupby("_d")["_r"].first()
    rows = {k: int(v) for k, v in d.groupby("_d")["row"].first().items()}
    s = s.sort_index()
    s = pd.Series(s.to_numpy(dtype=float), index=list(s.index))
    return s, {"rows": rows, "n_accounts": n_acc, "aggregation": agg, "duplicates": dups, "source": source,
               "n_nav_missing": n_nav_missing,
               "accounts": sorted(d["_acc"].unique().tolist())}


class Ctx:
    """Everything the checks share: the live and backtest series, the declared live start, the overlap."""

    def __init__(self, pkg: Any):
        self.pkg = pkg
        live_cfg = (pkg.rules or {}).get("live") if pkg.rules else None
        self.cfg: dict[str, Any] = live_cfg if isinstance(live_cfg, dict) else {}
        conv = declared_convention(pkg) or {}
        self.ppy = int(conv.get("periods_per_year") or pkg.conv("periods_per_year") or 252)
        self.conv = conv
        self.live_all, self.live_info = _series(pkg.df("live_returns"))
        self.bt, self.bt_info = _series(pkg.df("returns"))
        self.declared_start = _to_date(self.cfg.get("start"))
        self.bt_end = _to_date(self.cfg.get("backtest_end"))
        self.review = review_date(pkg)
        self.start = self.declared_start or (self.live_all.index[0] if self.live_all is not None and len(self.live_all)
                                             else None)
        self.live = None
        if self.live_all is not None and self.start is not None:
            self.live = self.live_all[[d >= self.start for d in self.live_all.index]]
        self.overlap: list[date] = []
        if self.live is not None and self.bt is not None:
            common = set(self.live.index) & set(self.bt.index)
            self.overlap = sorted(common)
        # backtest reference period (the backtest proper): up to backtest_end if declared, else before the live start
        self.bt_ref = None
        if self.bt is not None:
            if self.bt_end is not None:
                self.bt_ref = self.bt[[d <= self.bt_end for d in self.bt.index]]
            elif self.start is not None:
                self.bt_ref = self.bt[[d < self.start for d in self.bt.index]]
            else:
                self.bt_ref = self.bt
            if len(self.bt_ref) < 3:
                self.bt_ref = None
        self.min_periods = int(pkg.conv("live_min_periods"))
        self.alpha = float(pkg.conv("live_alpha"))

    def gap_limit(self) -> tuple[float, float]:
        """(days above which the interval between backtest end and live start is a gap, median spacing in days)."""
        for ser in (self.live_all, self.bt):
            if ser is not None and len(ser) >= 4:
                days = np.diff(np.array([pd.Timestamp(d).value // 86_400_000_000_000 for d in ser.index], dtype=float))
                days = days[days > 0]
                if days.size >= 3:
                    sp = float(np.median(days))
                    return max(GAP_FLOOR_DAYS, GAP_FACTOR * sp), sp
        return float(GAP_DAYS), float("nan")

    def row(self, d: date) -> int | None:
        return (self.live_info.get("rows") or {}).get(d)

    def bt_row(self, d: date) -> int | None:
        return (self.bt_info.get("rows") or {}).get(d)

    def declared(self, key: str) -> float | None:
        """live.declared_<key> from rules.yaml, else declared_results.json <key>."""
        v = self.cfg.get(f"declared_{key}")
        if v is None and self.pkg.declared:
            v = self.pkg.declared.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None


def _cap(t: str) -> str:
    return t[:1].upper() + t[1:]


def _nav(r) -> np.ndarray:
    a = np.asarray(r, dtype=float)
    return np.r_[1.0, np.cumprod(1.0 + a)]


def _no_backtest(res: AuditResult, check: str, title: str) -> None:
    not_executable(res, check, NAME, title,
                   "no returns.csv (the backtest series over the live period, a shadow backtest)",
                   "Deliver returns.csv with the backtest's periodic returns, ideally run over the live dates. The core "
                   "reconstruction already produces this series from trades and prices in report.json.")


def _live_too_short(res: AuditResult, check: str, title: str, n: int) -> None:
    not_executable(res, check, NAME, title, f"only {n} live periods (fewer than {MIN_LIVE})",
                   f"Deliver at least {MIN_LIVE} live periods; nothing statistical can be said before that.")


# --------------------------------------------------------------------------- 1. integrity

def check_period_integrity(pkg: Any, res: AuditResult, ctx: Ctx | None = None) -> None:
    check, title = "live_period_integrity", "Live period integrity"
    miss = pkg.missing(check)
    if miss:
        missing_inputs(res, check, NAME, title, miss)
        return
    ctx = ctx or Ctx(pkg)
    if ctx.live_all is None:
        not_executable(res, check, NAME, title, f"live_returns.csv: {ctx.live_info.get('reason')}",
                       "Deliver live_returns.csv with date and return (or nav).")
        return
    live = ctx.live_all
    errors: list[str] = []
    reviews: list[str] = []
    ev: list[dict[str, Any]] = []
    inputs = ["live_returns", "rules"]
    # duplicates
    dups = ctx.live_info.get("duplicates") or []
    if dups:
        errors.append(f"{len(dups)} live rows duplicate a (date, account) already present")
        ev += [{"problem": "duplicate", **d} for d in dups[:8]]
    # dates before the declared start
    if ctx.declared_start is not None:
        early = [d for d in live.index if d < ctx.declared_start]
        if early:
            errors.append(f"{len(early)} live periods precede the declared live start {ctx.declared_start}")
            ev += [{"problem": "before live start", "row": ctx.row(d), "date": d} for d in early[:8]]
    # dates after the review date
    late = [d for d in live.index if d > ctx.review]
    if late:
        errors.append(f"{len(late)} live periods are dated after the review date {ctx.review}")
        ev += [{"problem": "after review date", "row": ctx.row(d), "date": d} for d in late[:8]]
    # pasted backtest
    n_ov = len(ctx.overlap)
    corr = max_diff = float("nan")
    if n_ov >= MIN_LIVE and ctx.bt is not None and ctx.live is not None:
        a = ctx.live.loc[ctx.overlap].to_numpy(dtype=float)
        b = ctx.bt.loc[ctx.overlap].to_numpy(dtype=float)
        max_diff = float(np.max(np.abs(a - b)))
        corr = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else float("nan")
        if max_diff < IDENTICAL_TOL:
            errors.append(f"the live returns are IDENTICAL to the backtest on all {n_ov} overlapping periods "
                          f"(max |difference| {max_diff:.1e}, correlation {corr:.6f}): a backtest pasted as a track "
                          "record, not a live record")
            ev.append({"problem": "identical to backtest", "n_overlap": n_ov, "max_abs_diff": max_diff,
                       "correlation": corr, "first_date": ctx.overlap[0], "last_date": ctx.overlap[-1]})
        elif math.isfinite(corr) and corr > AFFINE_CORR:
            reviews.append(f"the live returns are an exact affine transform of the backtest (correlation {corr:.6f} "
                           f"on {n_ov} periods): a backtest with a constant haircut, not an independent record")
            ev.append({"problem": "affine copy of backtest", "n_overlap": n_ov, "max_abs_diff": max_diff,
                       "correlation": corr})
    # units: returns delivered in percent instead of fractions
    med_abs = float(np.median(np.abs(live.to_numpy(dtype=float)))) if len(live) else 0.0
    beta_u = float("nan")
    if n_ov >= MIN_LIVE and ctx.bt is not None and ctx.live is not None:
        a_u = ctx.live.loc[ctx.overlap].to_numpy(dtype=float)
        b_u = ctx.bt.loc[ctx.overlap].to_numpy(dtype=float)
        if np.var(b_u, ddof=1) > 0:
            beta_u = float(np.cov(a_u, b_u, ddof=1)[0, 1] / np.var(b_u, ddof=1))
    if med_abs > PERCENT_MEDIAN or (math.isfinite(beta_u) and 50 < abs(beta_u) < 200 and math.isfinite(corr)
                                    and abs(corr) > 0.5):
        reviews.append("the units look like percent, not fractions "
                       f"(median |period return| {med_abs:.3g}"
                       + (f", beta of live on backtest {beta_u:.0f}" if math.isfinite(beta_u) else "")
                       + "): 1.5 would be read as +150%; every live statistic is unreliable until the file is in "
                         "fractions (0.015 for 1.5%)")
        ev.append({"problem": "units look like percent", "median_abs_return": med_abs,
                   "beta_live_on_backtest": beta_u if math.isfinite(beta_u) else None})
    # shadow coverage
    bt_last = ctx.bt.index[-1] if ctx.bt is not None and len(ctx.bt) else None
    live_first = ctx.live.index[0] if ctx.live is not None and len(ctx.live) else live.index[0]
    live_last = live.index[-1]
    shadow = n_ov >= ctx.min_periods
    if ctx.bt is None:
        reviews.append("no returns.csv: the backtest cannot be compared with the live record (a shadow backtest over "
                       "the live dates is needed)")
        inputs.append("returns")
    elif n_ov == 0:
        reviews.append(f"the backtest series stops at {bt_last}, before the live period starts ({live_first}): the "
                       "comparison is backtest-period vs live-period, not a shadow backtest on the same dates")
        inputs.append("returns")
    elif n_ov < ctx.min_periods:
        reviews.append(f"the overlap between live and backtest is {n_ov} periods, fewer than live_min_periods = "
                       f"{ctx.min_periods}")
        inputs.append("returns")
    # gap after the backtest end
    if ctx.bt_end is not None and ctx.start is not None:
        gap = (ctx.start - ctx.bt_end).days
        gap_limit, spacing = ctx.gap_limit()
        if gap > gap_limit and not ctx.cfg.get("gap_reason"):
            reviews.append(f"the live start {ctx.start} is {gap} days after the declared backtest end {ctx.bt_end} "
                           + (f"(more than {gap_limit:.0f} days, {GAP_FACTOR:g} x the median spacing of "
                              f"{spacing:.0f} days of the series) " if math.isfinite(spacing) else "")
                           + "without a reason (rules.yaml live.gap_reason): what happened in between is not covered "
                           "by either record")
            ev.append({"problem": "gap", "backtest_end": ctx.bt_end, "live_start": ctx.start, "gap_days": gap})
        if gap < 0:
            reviews.append(f"the declared backtest end {ctx.bt_end} is after the live start {ctx.start}: the "
                           f"backtest window includes {-gap} days of the live period")
    desc = (f"live record: {len(live)} periods from {live.index[0]} to {live_last}"
            + (f" ({ctx.live_info['n_accounts']} accounts, {ctx.live_info['aggregation']})"
               if ctx.live_info.get("n_accounts", 1) > 1 else "")
            + f"; declared live start {ctx.declared_start or 'not declared (first live date used)'}; backtest "
            + (f"{len(ctx.bt)} periods to {bt_last}" if ctx.bt is not None else "absent")
            + (f"; {ctx.live_info['n_nav_missing']} missing NAV value(s) left as missing returns (not merged "
               "into multi-period returns)" if ctx.live_info.get("n_nav_missing") else "")
            + f"; overlap {n_ov} periods" + (f" (correlation {corr:.4f}, max |diff| {max_diff:.2e})"
                                             if math.isfinite(corr) else "") + ".")
    ev.insert(0, {"summary": "overlap", "live_periods": len(live), "live_first": live.index[0], "live_last": live_last,
                  "backtest_last": bt_last, "overlap_periods": n_ov, "review_date": ctx.review,
                  "correlation": corr if math.isfinite(corr) else None,
                  "max_abs_diff": max_diff if math.isfinite(max_diff) else None})
    res.metrics["live_period_integrity"] = {"live_periods": int(len(live)), "overlap": n_ov, "shadow": shadow,
                                            "correlation": corr, "max_abs_diff": max_diff,
                                            "n_accounts": ctx.live_info.get("n_accounts")}
    proc = ("Live dates compared with rules.yaml live.start and the review date; (date, account) duplicates counted; "
            f"on the dates common to live_returns.csv and returns.csv (n >= {MIN_LIVE}) the max |live - backtest| and "
            "the correlation are computed (identical series: max |diff| < 1e-12); the overlap is compared with "
            "live_min_periods and the live start with live.backtest_end.")
    if errors:
        res.add(check, NAME, CONFIRMED_ERROR, "Live record is not a valid live record: " + errors[0],
                _cap("; ".join(errors)) + ". " + desc, ev, proc,
                action="Deliver the actual live (or paper) returns from the production account statements, starting "
                       "at the declared live start, with one row per date and account.", priority="high",
                inputs=inputs)
    if reviews:
        res.add(check, NAME, NEEDS_REVIEW, "Live comparison scope is limited: " + reviews[0],
                _cap("; ".join(reviews)) + ". " + desc, ev, proc,
                action="Run the backtest over the live dates with the production code (shadow backtest) and declare "
                       "live.start, live.backtest_end and, if there was a gap, live.gap_reason in rules.yaml.",
                priority="medium", inputs=inputs)
    if not errors and not reviews:
        res.add(check, NAME, PASS, "Live period integrity verified with a shadow backtest",
                desc + " No dates before the live start or after the review date, no duplicates, the live series is "
                       "not a copy of the backtest and the overlap is long enough.", ev, proc, inputs=inputs)
    elif not errors:
        res.add(check, NAME, INFO, "Live period description", desc, ev[:1], proc, inputs=inputs)


# --------------------------------------------------------------------------- 2. live vs shadow backtest

def check_vs_shadow(pkg: Any, res: AuditResult, ctx: Ctx | None = None) -> None:
    check, title = "live_vs_shadow_backtest", "Live vs shadow backtest"
    miss = pkg.missing(check)
    if miss:
        if "returns" in miss and pkg.has("live_returns"):
            _no_backtest(res, check, title)
        else:
            missing_inputs(res, check, NAME, title, miss)
        return
    ctx = ctx or Ctx(pkg)
    if ctx.live is None or ctx.bt is None:
        not_executable(res, check, NAME, title, "no usable live or backtest return series",
                       "Check the return / nav columns of live_returns.csv and returns.csv.")
        return
    n = len(ctx.overlap)
    if n < MIN_LIVE:
        not_executable(res, check, NAME, title,
                       f"only {n} dates in common between the live record and the backtest (fewer than {MIN_LIVE})",
                       "Run the backtest over the live dates (shadow backtest) and deliver it as returns.csv.")
        return
    ppy = ctx.ppy
    a = ctx.live.loc[ctx.overlap].to_numpy(dtype=float)
    b = ctx.bt.loc[ctx.overlap].to_numpy(dtype=float)
    diff = a - b
    te = tracking_error(a, b, ppy)
    corr = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else float("nan")
    var_b = float(np.var(b, ddof=1))
    beta = float(np.cov(a, b, ddof=1)[0, 1]) / var_b if var_b > 0 else float("nan")
    hac = hac_mean_test(diff)
    sign_diff = float(np.mean(np.sign(a) != np.sign(b)))
    cum_gap = np.cumprod(1 + a) - np.cumprod(1 + b)
    widening = np.diff(np.r_[0.0, cum_gap])
    i_open = int(np.argmin(widening)) if len(widening) else 0  # largest single-period widening against live
    # the date from which the gap stays open: last date the cumulative gap was at or above zero
    nonneg = np.where(cum_gap >= 0)[0]
    i_from = int(nonneg[-1]) + 1 if len(nonneg) and nonneg[-1] + 1 < n else 0
    te_max = float(pkg.conv("live_tracking_error_review"))
    neg_sig = significantly_below_zero(hac, ctx.alpha)  # one-sided: live worse; small-sample safe
    problems = []
    if te > te_max:
        problems.append(f"tracking error {te:.2%} a year above live_tracking_error_review = {te_max:.0%}")
    if neg_sig:
        problems.append(f"the live return is systematically below the shadow backtest: mean difference "
                        f"{hac['mean'] * 1e4:+.2f} bps per period, HAC t = {hac['t_adj']:.2f} (one-sided p = "
                        f"{t_cdf(hac['t_adj'], n - 1):.4f} < {ctx.alpha}"
                        + (f"; iid t = {hac['t_iid']:.2f}, also required to reject below {SMALL_SAMPLE_N} periods"
                           if n < SMALL_SAMPLE_N else "") + ")")
    if math.isfinite(corr) and corr < 0.8:
        problems.append(f"correlation of live and backtest returns {corr:.3f} < 0.8")
    ev = [{"metric": "tracking_error_annual", "value": te, "threshold": te_max},
          {"metric": "correlation", "value": corr, "threshold": 0.8},
          {"metric": "beta_live_on_backtest", "value": beta},
          {"metric": "mean_difference_per_period", "value": hac["mean"], "hac_t": hac["t_adj"], "iid_t": hac["t_iid"],
              "p_two_sided": hac["p_adj"], "lags": hac["lags"]},
          {"metric": "share_of_periods_with_different_sign", "value": sign_diff},
          {"metric": "cumulative_gap_end", "value": float(cum_gap[-1]), "date": ctx.overlap[-1]},
          {"metric": "largest_widening", "value": float(widening[i_open]), "date": ctx.overlap[i_open],
           "row": ctx.row(ctx.overlap[i_open])},
          {"metric": "gap_open_since", "date": ctx.overlap[i_from], "row": ctx.row(ctx.overlap[i_from])},
          {"metric": "n_overlap", "value": n}]
    res.metrics["live_vs_shadow_backtest"] = {"n": n, "tracking_error": te, "correlation": corr, "beta": beta,
                                              "mean_difference": hac["mean"], "hac_t": hac["t_adj"],
                                              "iid_t": hac["t_iid"], "p_value": hac["p_adj"], "sign_disagreement": sign_diff,
                                              "cumulative_gap": float(cum_gap[-1])}
    detail = (f"On {n} common periods: tracking error {te:.2%} a year, correlation {corr:.3f}, beta of live on backtest "
              f"{beta:.2f}, mean difference {hac['mean'] * 1e4:+.2f} bps per period (HAC t = {hac['t_adj']:.2f}, iid t = {hac['t_iid']:.2f}), sign "
              f"differs on {sign_diff:.0%} of the periods. Cumulative return gap at {ctx.overlap[-1]}: "
              f"{cum_gap[-1]:+.2%}; largest single-period widening {widening[i_open]:+.2%} on {ctx.overlap[i_open]}; "
              + (f"the gap has been open since {ctx.overlap[i_from]}." if cum_gap[-1] < 0 else
                 "live is not behind the backtest cumulatively at the end of the overlap."))
    proc = (f"Common dates of live_returns.csv and returns.csv; TE = std(live - backtest, ddof 1) x sqrt({ppy}); "
            "mean difference tested with a Newey-West t (Bartlett kernel, lags = floor(4 (n/100)^(2/9)), variance x n/(n - lags - 1), t(n - 1) critical value; below 60 periods the iid t must reject too); beta = "
            "cov / var(backtest); cumulative gap = prod(1 + live) - prod(1 + backtest).")
    if problems:
        res.add(check, NAME, NEEDS_REVIEW, "Live does not track the shadow backtest: " + problems[0],
                _cap("; ".join(problems)) + ". " + detail, ev, proc,
                action="Attribute the gap: execution (live_execution_quality), data differences between the research "
                       "and production feeds, risk limits or discretionary overrides active in production.",
                priority="high", inputs=["live_returns", "returns", "rules"])
    elif n >= ctx.min_periods:
        res.add(check, NAME, PASS, "No significant systematic difference between live and the shadow backtest",
                detail + f" Scope: TE within {te_max:.0%}, correlation >= 0.8 and no significant negative mean "
                         f"difference at {ctx.alpha} on {n} periods; it does not say the edge is intact (see "
                         "live_performance_decay).", ev, proc, inputs=["live_returns", "returns", "rules"])
    else:
        res.add(check, NAME, INFO, "Live tracks the shadow backtest within the declared tolerance (short overlap)",
                detail + f" Only {n} periods (< live_min_periods = {ctx.min_periods}): consistent, not verified.",
                ev, proc, inputs=["live_returns", "returns", "rules"])


# --------------------------------------------------------------------------- 3. performance decay

def check_performance_decay(pkg: Any, res: AuditResult, ctx: Ctx | None = None) -> None:
    check, title = "live_performance_decay", "Live performance decay"
    miss = pkg.missing(check)
    if miss:
        missing_inputs(res, check, NAME, title, miss)
        return
    ctx = ctx or Ctx(pkg)
    if ctx.live is None:
        not_executable(res, check, NAME, title, f"live_returns.csv: {ctx.live_info.get('reason')}")
        return
    n = len(ctx.live)
    if n < MIN_LIVE:
        _live_too_short(res, check, title, n)
        return
    ppy = ctx.ppy
    lv = ctx.live.to_numpy(dtype=float)
    m_live = stats.moments(lv)
    sr_live = stats.sharpe(lv)
    live_m = metrics.compute(_nav(lv), [ctx.live.index[0] - timedelta(days=1)] + list(ctx.live.index), ctx.conv)
    # backtest reference: the backtest proper (series), else the declared Sharpe
    if ctx.bt_ref is not None and len(ctx.bt_ref) >= MIN_LIVE:
        bt = ctx.bt_ref.to_numpy(dtype=float)
        sr_bt = stats.sharpe(bt)
        t_bt = len(bt)
        bt_m = metrics.compute(_nav(bt), [ctx.bt_ref.index[0] - timedelta(days=1)] + list(ctx.bt_ref.index), ctx.conv)
        src = (f"returns.csv over the backtest period ({ctx.bt_ref.index[0]} to {ctx.bt_ref.index[-1]}, {t_bt} "
               "periods)")
    else:
        decl = ctx.declared("sharpe")
        if decl is None:
            not_executable(res, check, NAME, title,
                           "no backtest period in returns.csv before the live start and no declared Sharpe",
                           "Deliver the backtest series (returns.csv) or declare live.declared_sharpe in rules.yaml.")
            return
        sr_bt = decl / math.sqrt(ppy)
        t_bt = 0
        bt_m = {"sharpe": decl, "annual_return": ctx.declared("annual_return"),
                "max_drawdown": ctx.declared("max_drawdown")}
        src = "the declared backtest Sharpe (rules.yaml live.declared_sharpe or declared_results.json)"
    haircut = float(pkg.conv("live_haircut_expected"))
    expected_sr = haircut * sr_bt
    psr_vs_bt = stats.probabilistic_sharpe(sr_live, sr_bt, n, m_live["skew"], m_live["kurt"])
    psr_vs_exp = stats.probabilistic_sharpe(sr_live, expected_sr, n, m_live["skew"], m_live["kurt"])
    p_as_low = psr_vs_bt  # P[true SR > SR_bt | live] small <=> the observed live SR is unlikely under SR_bt
    mintrl = stats.min_track_record_length(sr_live, expected_sr, m_live["skew"], m_live["kurt"], ctx.alpha)
    mintrl0 = stats.min_track_record_length(sr_live, 0.0, m_live["skew"], m_live["kurt"], ctx.alpha)
    jk = sharpe_difference_test(sr_live, n, sr_bt, t_bt) if t_bt >= 2 else {"z": float("nan"), "p_value": float("nan")}
    ratio = sr_live / sr_bt if sr_bt not in (0.0,) and math.isfinite(sr_bt) else float("nan")
    ann = math.sqrt(ppy)
    ev = [{"metric": "sharpe_annual", "live": sr_live * ann, "backtest": sr_bt * ann, "ratio": ratio,
           "expected_after_haircut": expected_sr * ann, "haircut": haircut},
          {"metric": "annual_return", "live": live_m["annual_return"], "backtest": bt_m.get("annual_return")},
          {"metric": "max_drawdown", "live": live_m["max_drawdown"], "backtest": bt_m.get("max_drawdown")},
          {"metric": "psr_live_vs_backtest_sharpe", "value": psr_vs_bt,
           "meaning": "P[true live SR > backtest SR]; below alpha the live record rejects the backtest Sharpe"},
          {"metric": "psr_live_vs_haircut_expectation", "value": psr_vs_exp},
          {"metric": "min_track_record_length_vs_haircut_expectation", "periods": mintrl, "live_periods": n},
          {"metric": "min_track_record_length_vs_zero", "periods": mintrl0},
          {"metric": "sharpe_difference_z", "value": jk["z"], "p_two_sided": jk["p_value"], "backtest_periods": t_bt},
          {"metric": "live_moments", "T": n, "skew": m_live["skew"], "kurt": m_live["kurt"]}]
    res.metrics["live_performance_decay"] = {"live_sharpe": sr_live * ann, "backtest_sharpe": sr_bt * ann,
                                             "ratio": ratio, "haircut": haircut, "psr_vs_backtest": psr_vs_bt,
                                             "psr_vs_expectation": psr_vs_exp, "min_trl": mintrl,
                                             "sharpe_diff_z": jk["z"], "live_periods": n,
                                             "live_annual_return": live_m["annual_return"],
                                             "live_max_drawdown": live_m["max_drawdown"]}
    mintrl_txt = ("not reachable at the current live Sharpe (it is at or below the expectation)" if math.isinf(mintrl)
                  else f"{mintrl:.0f} periods")
    detail = (f"Live annualised Sharpe {sr_live * ann:.2f} on {n} periods vs backtest {sr_bt * ann:.2f} ({src}): "
              f"ratio {ratio:.2f}; expected out-of-sample haircut {haircut:.0%} gives an expectation of "
              f"{expected_sr * ann:.2f}. Probability that a true Sharpe equal to the backtest one produces a live "
              f"Sharpe this low or lower: {1 - psr_vs_bt:.3f} (PSR vs backtest {psr_vs_bt:.3f}). Sharpe-difference "
              f"z = {jk['z']:.2f} (p = {jk['p_value']:.3f}). Annual return live {live_m['annual_return']:+.1%} vs "
              f"backtest {_fmt(bt_m.get('annual_return'))}; max drawdown live {live_m['max_drawdown']:.1%} vs "
              f"backtest {_fmt(bt_m.get('max_drawdown'))}. Minimum track record to conclude the live Sharpe exceeds "
              f"the haircut expectation at {ctx.alpha}: {mintrl_txt}.")
    proc = (f"Per-period Sharpe = mean / std (ddof 1), annualised x sqrt({ppy}); PSR(SR*) of Bailey and Lopez de "
            "Prado (2012) with the live skewness and kurtosis; MinTRL for PSR >= 1 - alpha; Sharpe-difference z = "
            "(SR_live - SR_bt) / sqrt(SE_live^2 + SE_bt^2) with Lo's standard errors (independent samples); metrics "
            f"with the declared convention ({metrics.describe_convention(metrics.full_convention(ctx.conv))}).")
    below = math.isfinite(expected_sr) and sr_live < expected_sr
    significant = math.isfinite(p_as_low) and p_as_low < ctx.alpha
    if below and significant:
        res.add(check, NAME, NEEDS_REVIEW, f"Live Sharpe {sr_live * ann:.2f} is below the haircut-adjusted expectation "
                                           f"{expected_sr * ann:.2f} and the deficit is significant",
                detail + " The live record is statistically incompatible with the backtest Sharpe: the edge has decayed "
                         "or the backtest overstated it.", ev, proc,
                action="Stop treating the backtest Sharpe as the expectation; re-estimate capacity and sizing from the "
                       "live record and look for what changed (crowding, costs, regime, data vintage).",
                priority="high", inputs=["live_returns", "returns", "rules"])
    elif n >= ctx.min_periods and not below and psr_vs_exp >= 1 - ctx.alpha:
        res.add(check, NAME, PASS, f"Live Sharpe {sr_live * ann:.2f} is above the haircut-adjusted expectation with "
                                   f"PSR {psr_vs_exp:.3f}",
                detail + " Scope: the live record exceeds the expected out-of-sample Sharpe with confidence; it says "
                         "nothing about the future.", ev, proc, inputs=["live_returns", "returns", "rules"])
    else:
        res.add(check, NAME, INFO, f"Live history too short to conclude on decay: Sharpe {sr_live * ann:.2f} vs "
                                   f"backtest {sr_bt * ann:.2f} ({n} periods, MinTRL {mintrl_txt})",
                detail + (" The live Sharpe is below the expectation but the deficit is not significant at "
                          f"{ctx.alpha}." if below else " The live Sharpe is not below the expectation but the record "
                                                        "is not long enough to verify it."), ev, proc,
                action="Keep the shadow backtest running and re-run this check as the live record grows.",
                priority="low", inputs=["live_returns", "returns", "rules"])


def _fmt(v: Any) -> str:
    try:
        return f"{float(v):+.1%}" if v is not None and math.isfinite(float(v)) else "n/a"
    except (TypeError, ValueError):
        return "n/a"


# --------------------------------------------------------------------------- 4. structural break

def check_structural_break(pkg: Any, res: AuditResult, ctx: Ctx | None = None) -> None:
    check, title = "live_structural_break", "Structural break at the live start"
    miss = pkg.missing(check)
    if miss:
        if "returns" in miss and pkg.has("live_returns"):
            _no_backtest(res, check, title)
        else:
            missing_inputs(res, check, NAME, title, miss)
        return
    ctx = ctx or Ctx(pkg)
    if ctx.live is None or ctx.bt is None:
        not_executable(res, check, NAME, title, "no usable live or backtest return series")
        return
    n = len(ctx.live)
    if n < MIN_LIVE:
        _live_too_short(res, check, title, n)
        return
    if ctx.bt_ref is None or len(ctx.bt_ref) < 2 * MIN_LIVE:
        not_executable(res, check, NAME, title,
                       f"fewer than {2 * MIN_LIVE} backtest periods before the live start (live.backtest_end / "
                       "live.start)", "Deliver the backtest history before the live start in returns.csv.")
        return
    ppy = ctx.ppy
    bt = ctx.bt_ref.to_numpy(dtype=float)
    lv = ctx.live.to_numpy(dtype=float)
    mu, sd = float(bt.mean()), float(bt.std(ddof=1))
    if not sd > 0:
        not_executable(res, check, NAME, title, "the backtest returns have zero variance")
        return
    h = float(pkg.conv("live_cusum_h"))
    z = (lv - mu) / sd
    cs = cusum(z, h)
    cross_date = ctx.live.index[cs["first_crossing"]] if cs["first_crossing"] is not None else None
    # Chow-style mean shift: two-sample t with HAC variances
    h1, h2 = hac_mean_test(bt), hac_mean_test(lv)
    se = math.sqrt(h1["se"] ** 2 + h2["se"] ** 2)
    t_shift = (h2["mean"] - h1["mean"]) / se if se > 0 else float("nan")
    p_shift = 2 * (1 - _N.cdf(abs(t_shift))) if math.isfinite(t_shift) else float("nan")
    # rolling Sharpe: live vs the backtest's distribution
    window = int(pkg.conv("live_rolling_window"))
    rs_bt = rolling_sharpe(bt, window, ppy)
    rs_live = rolling_sharpe(lv, window, ppy)
    roll: dict[str, Any] = {"window": window}
    if rs_bt.size >= window and rs_live.size >= 1:
        med = float(np.median(rs_live))
        p10 = float(np.percentile(rs_bt, 10))
        roll.update({"live_median": med, "live_last": float(rs_live[-1]), "backtest_p10": p10,
                     "backtest_median": float(np.median(rs_bt)),
                     "percentile_of_live_median": percentile_of(med, rs_bt),
                     "percentile_of_live_last": percentile_of(float(rs_live[-1]), rs_bt)})
    problems = []
    if cross_date is not None:
        problems.append(f"the CUSUM of standardised live returns crossed h = {h:g} on {cross_date} "
                        f"(direction: {cs['direction']}, max |C_k| / sqrt(k) = {cs['max_abs_statistic']:.1f})")
    if math.isfinite(p_shift) and p_shift < ctx.alpha:
        problems.append(f"the mean return shifted at the live start: {h1['mean'] * 1e4:+.2f} bps per period in the "
                        f"backtest vs {h2['mean'] * 1e4:+.2f} bps live, HAC t = {t_shift:.2f} (p = {p_shift:.4f})")
    if "live_median" in roll and roll["live_median"] < roll["backtest_p10"]:
        problems.append(f"the live median rolling {window}-period Sharpe {roll['live_median']:.2f} is below the "
                        f"backtest 10th percentile {roll['backtest_p10']:.2f}")
    ev = [{"metric": "cusum", "first_crossing": cross_date, "direction": cs["direction"],
           "max_abs_statistic": cs["max_abs_statistic"], "h": h, "bde_end_statistic": cs["bde_end_statistic"],
           "row": ctx.row(cross_date) if cross_date else None},
          {"metric": "mean_shift", "backtest_mean": h1["mean"], "live_mean": h2["mean"], "hac_t": t_shift,
           "p_two_sided": p_shift, "backtest_periods": len(bt), "live_periods": n, "live_start": ctx.live.index[0]},
          {"metric": "rolling_sharpe", **roll}]
    res.metrics["live_structural_break"] = {"cusum_first_crossing": cross_date,
                                            "cusum_max_abs_statistic": cs["max_abs_statistic"], "shift_t": t_shift,
                                            "shift_p": p_shift, "rolling": roll}
    roll_txt = (f" Rolling {window}-period Sharpe: live median {roll['live_median']:.2f} (percentile "
                f"{roll['percentile_of_live_median']:.0%} of the backtest's rolling distribution, whose 10th "
                f"percentile is {roll['backtest_p10']:.2f} and median {roll['backtest_median']:.2f})."
                if "live_median" in roll else f" Rolling {window}-period Sharpe not computed (live or backtest shorter "
                                              "than the window).")
    detail = (f"Live returns standardised with the backtest mean ({mu * 1e4:+.2f} bps) and sd ({sd:.4%}); CUSUM "
              f"C_k / sqrt(k) with threshold h = {h:g}: largest |statistic| {cs['max_abs_statistic']:.2f}, "
              + (f"first crossing {cross_date}" if cross_date else "no crossing")
              + f"; Brown-Durbin-Evans end statistic sum(z)/sqrt(n) = {cs['bde_end_statistic']:.2f}. Mean shift at "
              f"the live start ({ctx.live.index[0]}): HAC t = {t_shift:.2f}, p = {p_shift:.3f}." + roll_txt)
    proc = ("z_t = (r_t - mean_bt) / sd_bt on the live periods; CUSUM C_k = sum z_t with alarm when |C_k| / sqrt(k) "
            "> h (Page 1954; Brown, Durbin and Evans 1975); two-sample mean test with Newey-West standard errors "
            f"(Chow 1960 flavour for a known break date); rolling {window}-period Sharpe annualised x sqrt({ppy}) "
            "compared by percentile with the backtest's own rolling distribution.")
    if problems:
        res.add(check, NAME, NEEDS_REVIEW, "Structural break at the live start: " + problems[0],
                _cap("; ".join(problems)) + ". " + detail, ev, proc,
                action="Date the break with the CUSUM crossing and the cumulative gap (live_vs_shadow_backtest) and "
                       "look for a cause at that date: code release, data vendor change, capacity, market regime.",
                priority="high", inputs=["live_returns", "returns", "rules"])
    else:
        res.add(check, NAME, INFO, "No structural break detected at the live start", detail
                + f" Note: the CUSUM at h = {h:g} detects a shift of delta sd per period after about (h / delta)^2 "
                  "periods (the loss of a backtest Sharpe of 2 a year, 0.13 sd a day, takes about 1,500 days); the "
                  "mean-shift test and the rolling Sharpe are the powered statistics. Absence of a crossing is not "
                  "evidence that the edge is intact.", ev, proc,
                inputs=["live_returns", "returns", "rules"])


# --------------------------------------------------------------------------- 5. execution quality

def _trades(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None:
        return None
    d = df.copy()
    if "side" in d.columns:
        d["side"] = [None if x is None else SIDES.get(str(x).strip().lower()) for x in d["side"]]
    for c in ("quantity", "price", "commission", "model_price"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def _match_keys(d: pd.DataFrame, ts_col: str) -> list[tuple]:
    ts = d[ts_col] if ts_col in d.columns else d["timestamp"]
    ts = ts.where(ts.notna(), d["timestamp"])
    return [(t, s, x.date() if pd.notna(x) else None) for t, s, x in zip(d["ticker"], d["side"], ts)]


def check_execution_quality(pkg: Any, res: AuditResult, ctx: Ctx | None = None) -> None:
    check, title = "live_execution_quality", "Live execution quality"
    miss = pkg.missing(check)
    if miss:
        missing_inputs(res, check, NAME, title, miss)
        return
    lt = _trades(pkg.df("live_trades"))
    if lt is None or lt.empty:
        not_executable(res, check, NAME, title, "live_trades.csv has no rows")
        return
    lt = lt.dropna(subset=["timestamp", "ticker", "quantity", "price"])
    n_live = len(lt)
    if n_live == 0:
        not_executable(res, check, NAME, title, "live_trades.csv has no complete rows")
        return
    bps_max = float(pkg.conv("live_slippage_review_bps"))
    problems: list[str] = []
    ev: list[dict[str, Any]] = []
    parts: list[str] = []
    m: dict[str, Any] = {"n_live_trades": n_live}
    # slippage vs model price
    if "model_price" in lt.columns and lt["model_price"].notna().any():
        s = lt.dropna(subset=["model_price", "side"])
        s = s[s["model_price"] > 0]
        sign = np.where(s["side"].to_numpy() == "buy", 1.0, -1.0)
        slip = sign * (s["price"].to_numpy(dtype=float) / s["model_price"].to_numpy(dtype=float) - 1.0) * 1e4
        hs = hac_mean_test(slip, lags=0)
        flat = slip.size < 2 or float(np.std(slip)) < 1e-9
        per_side = {}
        for side in ("buy", "sell"):
            sel = slip[s["side"].to_numpy() == side]
            if sel.size:
                per_side[side] = {"n": int(sel.size), "mean_bps": float(sel.mean())}
        worst = s.assign(slip_bps=slip).sort_values("slip_bps", ascending=False).head(5)
        ev.append({"metric": "slippage_bps", "n": int(slip.size), "mean": hs["mean"], "t": None if flat else hs["t"],
                   "median": float(np.median(slip)), "p95": float(np.percentile(slip, 95)), "per_side": per_side,
                   "threshold": bps_max})
        ev += [{"metric": "worst_slippage", "row": int(r.row), "date": r.timestamp, "ticker": r.ticker, "side": r.side,
                "slippage_bps": float(r.slip_bps)} for r in worst.itertuples()]
        m.update({"slippage_mean_bps": hs["mean"], "slippage_t": None if flat else hs["t"], "slippage_per_side": per_side})
        t_txt = ("all slippages identical, no dispersion to test" if flat else f"t = {hs['t']:.1f}")
        parts.append(f"slippage vs model price: mean {hs['mean']:+.1f} bps ({t_txt}, n = {slip.size}; "
                     + ", ".join(f"{k} {v['mean_bps']:+.1f} bps" for k, v in per_side.items()) + ")")
        if hs["mean"] > bps_max:
            problems.append(f"mean slippage {hs['mean']:+.1f} bps per trade above live_slippage_review_bps = "
                            f"{bps_max:g} (positive = worse than the model price)")
    else:
        parts.append("no model_price column: slippage not measured")
    # delay
    if "model_timestamp" in lt.columns and lt["model_timestamp"].notna().any():
        dl = lt.dropna(subset=["model_timestamp"])
        delay = (dl["timestamp"] - dl["model_timestamp"]).dt.total_seconds().to_numpy(dtype=float)
        neg = dl[delay < 0]
        ev.append({"metric": "delay_seconds", "n": int(delay.size), "median": float(np.median(delay)),
                   "p95": float(np.percentile(delay, 95)), "negative": int(len(neg))})
        m.update({"delay_median_s": float(np.median(delay)), "delay_p95_s": float(np.percentile(delay, 95))})
        parts.append(f"delay model -> fill: median {np.median(delay):.0f} s, 95th percentile "
                     f"{np.percentile(delay, 95):.0f} s")
        if len(neg):
            problems.append(f"{len(neg)} live trades were executed BEFORE the model asked for them (negative delay): "
                            "timestamps or the decision process need review")
            ev += [{"metric": "negative_delay", "row": int(r.row), "date": r.timestamp, "ticker": r.ticker,
                    "model_timestamp": r.model_timestamp} for r in neg.head(5).itertuples()]
    # fill ratio and overrides
    mt = _trades(pkg.df("model_trades"))
    if mt is not None and not mt.empty:
        mt = mt.dropna(subset=["timestamp", "ticker"])
        use_id = ("trade_id" in lt.columns and "trade_id" in mt.columns and lt["trade_id"].notna().mean() > 0.9
                  and mt["trade_id"].notna().mean() > 0.9)
        if use_id:
            live_ids = set(lt["trade_id"].dropna().astype(str))
            model_ids = set(mt["trade_id"].dropna().astype(str))
            filled = len(model_ids & live_ids)
            n_model = len(model_ids)
            overrides = lt[~lt["trade_id"].astype(str).isin(model_ids)]
            unfilled = mt[~mt["trade_id"].astype(str).isin(live_ids)]
            how = "matched by trade_id"
        else:
            lk = _match_keys(lt, "model_timestamp")
            mk = _match_keys(mt, "timestamp")
            from collections import Counter
            cl, cm = Counter(lk), Counter(mk)
            filled = sum(min(c, cl.get(k, 0)) for k, c in cm.items())
            n_model = len(mk)
            over_mask = []
            seen: Counter = Counter()
            for k in lk:
                seen[k] += 1
                over_mask.append(seen[k] > cm.get(k, 0))
            overrides = lt[np.array(over_mask, dtype=bool)]
            unf_mask = []
            seen = Counter()
            for k in mk:
                seen[k] += 1
                unf_mask.append(seen[k] > cl.get(k, 0))
            unfilled = mt[np.array(unf_mask, dtype=bool)]
            how = "matched by (ticker, side, date of the model timestamp)"
        fill_ratio = filled / n_model if n_model else float("nan")
        over_share = len(overrides) / n_live
        ev.append({"metric": "fill_ratio", "value": fill_ratio, "model_trades": n_model, "filled": filled,
                   "unfilled": len(unfilled), "overrides": len(overrides), "override_share": over_share, "how": how})
        ev += [{"metric": "unfilled_model_trade", "row": int(r.row), "date": r.timestamp, "ticker": r.ticker,
                "side": r.side} for r in unfilled.head(5).itertuples()]
        ev += [{"metric": "override", "row": int(r.row), "date": r.timestamp, "ticker": r.ticker, "side": r.side}
               for r in overrides.head(5).itertuples()]
        m.update({"fill_ratio": fill_ratio, "overrides": len(overrides), "override_share": over_share})
        parts.append(f"fill ratio {fill_ratio:.1%} of {n_model} model trades ({how}); {len(overrides)} live trades "
                     f"the model never requested ({over_share:.1%} of live trades)")
        if math.isfinite(fill_ratio) and fill_ratio < 0.9:
            problems.append(f"fill ratio {fill_ratio:.1%} < 90%: {len(unfilled)} model trades never executed")
        if over_share > 0.05:
            problems.append(f"{len(overrides)} live trades ({over_share:.1%}) were not requested by the model: "
                            "discretionary overrides above 5%")
    else:
        parts.append("no model_trades.csv: fill ratio and overrides not measured")
    # commission
    if "commission" in lt.columns and lt["commission"].notna().any():
        notional = float((lt["quantity"].abs() * lt["price"]).sum())
        comm = float(lt["commission"].fillna(0).sum())
        cpn = comm / notional * 1e4 if notional > 0 else float("nan")
        ev.append({"metric": "commission_per_notional_bps", "value": cpn, "commission": comm, "notional": notional})
        m["commission_bps"] = cpn
        parts.append(f"commission {cpn:.1f} bps of notional")
    res.metrics["live_execution_quality"] = m
    if len(ev) == 0:
        not_executable(res, check, NAME, title,
                       "live_trades.csv has none of model_price, model_timestamp, commission and there is no "
                       "model_trades.csv: nothing to measure",
                       "Add model_price and model_timestamp to live_trades.csv and deliver model_trades.csv.")
        return
    detail = f"{n_live} live trades; " + "; ".join(parts) + "."
    proc = ("Slippage = side x (fill price / model price - 1) x 1e4 (buy +1, sell -1; positive = worse), mean with a "
            "t-statistic; delay = timestamp - model_timestamp; fill ratio = model trades with a live match / model "
            "trades; overrides = live trades without a model match; commission / sum(|quantity| x price).")
    if problems:
        res.add(check, NAME, NEEDS_REVIEW, "Execution differs from the model: " + problems[0],
                _cap("; ".join(problems)) + ". " + detail, ev, proc,
                action="Measure the implementation shortfall (Perold 1988) per venue and order type, enforce the model "
                       "trade list or document every override, and feed the realised slippage back into the backtest "
                       "cost assumptions.", priority="high", inputs=["live_trades", "model_trades", "rules"])
    else:
        res.add(check, NAME, INFO, "Execution consistent with the model", detail, ev, proc,
                inputs=["live_trades", "model_trades", "rules"])


# --------------------------------------------------------------------------- 6. declared vs realised

def check_declared_vs_realised(pkg: Any, res: AuditResult, ctx: Ctx | None = None) -> None:
    check, title = "live_declared_vs_realised", "Declared backtest vs delivered series vs live"
    miss = pkg.missing(check)
    if miss:
        if "returns" in miss and pkg.has("live_returns"):
            _no_backtest(res, check, title)
        else:
            missing_inputs(res, check, NAME, title, miss)
        return
    ctx = ctx or Ctx(pkg)
    if ctx.live is None or ctx.bt is None:
        not_executable(res, check, NAME, title, "no usable live or backtest return series")
        return
    if ctx.bt_ref is None or len(ctx.bt_ref) < 3:
        not_executable(res, check, NAME, title, "no backtest period in returns.csv (before live.backtest_end / live.start)")
        return
    if len(ctx.live) < 3:
        not_executable(res, check, NAME, title, "fewer than 3 live periods")
        return
    bt = ctx.bt_ref.to_numpy(dtype=float)
    lv = ctx.live.to_numpy(dtype=float)
    bt_m = metrics.compute(_nav(bt), [ctx.bt_ref.index[0] - timedelta(days=1)] + list(ctx.bt_ref.index), ctx.conv)
    lv_m = metrics.compute(_nav(lv), [ctx.live.index[0] - timedelta(days=1)] + list(ctx.live.index), ctx.conv)
    tol = tolerances(pkg)
    rows = []
    errors = []
    declared_any = False
    for key in ("sharpe", "annual_return", "max_drawdown"):
        d = ctx.declared(key)
        r = bt_m.get(key)
        within = None
        if d is not None and r is not None and math.isfinite(r):
            declared_any = True
            within = abs(d - r) <= tol.get(key, 0.0)
            if not within:
                errors.append(f"declared {key} {d:.4g} vs {r:.4g} recomputed from returns.csv over the backtest period "
                              f"(tolerance {tol.get(key):g})")
        rows.append({"metric": key, "declared": d, "backtest_series": r, "live": lv_m.get(key),
                     "tolerance": tol.get(key), "within_tolerance": within})
    decl_dd = ctx.declared("max_drawdown")
    ref_dd = decl_dd if decl_dd is not None else bt_m["max_drawdown"]
    ref_src = "declared" if decl_dd is not None else "recomputed from the backtest series"
    live_dd = lv_m["max_drawdown"]
    reviews = []
    if math.isfinite(live_dd) and ref_dd is not None and live_dd < ref_dd:
        reviews.append(f"the live max drawdown {live_dd:.1%} already exceeds the backtest max drawdown {ref_dd:.1%} "
                       f"({ref_src}) after {len(lv)} live periods: the backtest worst case was not the worst case")
    ev = rows + [{"metric": "periods", "backtest_series": len(bt), "live": len(lv),
                  "backtest_period": f"{ctx.bt_ref.index[0]} to {ctx.bt_ref.index[-1]}",
                  "live_period": f"{ctx.live.index[0]} to {ctx.live.index[-1]}",
                  "live_drawdown_peak": lv_m.get("peak_date"), "live_drawdown_trough": lv_m.get("trough_date")}]
    res.metrics["live_declared_vs_realised"] = {"table": rows, "convention": bt_m["convention"]}
    table = " | ".join(f"{r['metric']}: declared {_g(r['declared'])} / backtest series {_g(r['backtest_series'])} / "
                       f"live {_g(r['live'])}" for r in rows)
    detail = (f"Table (declared / backtest series over {ctx.bt_ref.index[0]} to {ctx.bt_ref.index[-1]} / live over "
              f"{ctx.live.index[0]} to {ctx.live.index[-1]}): {table}. Convention: "
              f"{metrics.describe_convention(bt_m['convention'])}.")
    proc = ("Declared values from rules.yaml live.declared_* (else declared_results.json); Sharpe, annual return and "
            "max drawdown recomputed with the core metrics module on NAV = cumulative product of (1 + return) over the "
            "backtest period and over the live period; differences compared with the core tolerances "
            "(conventions.tolerances).")
    if errors:
        res.add(check, NAME, CONFIRMED_ERROR, "Declared backtest metric does not match the series delivered: "
                + errors[0], _cap("; ".join(errors)) + ". " + detail + " The marketing number is not the "
                "series delivered.", ev, proc,
                action="Deliver the series that produced the declared metrics, or correct the declared metrics and "
                       "state the convention used.", priority="high",
                inputs=["returns", "live_returns", "rules", "declared_results"])
    if reviews:
        res.add(check, NAME, NEEDS_REVIEW, "Live drawdown exceeds the backtest worst case",
                _cap("; ".join(reviews)) + ". " + detail, ev, proc,
                action="Re-estimate the risk budget from the live record; a backtest drawdown is a lower bound on the "
                       "worst case, not an estimate of it (Magdon-Ismail and Atiya 2004).", priority="medium",
                inputs=["returns", "live_returns", "rules", "declared_results"])
    if not errors and not reviews:
        res.add(check, NAME, INFO, "Declared, delivered and live metrics side by side",
                detail + (" Every declared metric is within tolerance of the series delivered."
                          if declared_any else " No declared backtest metric to contrast (rules.yaml live.declared_* "
                                               "or declared_results.json)."), ev, proc,
                inputs=["returns", "live_returns", "rules", "declared_results"])


def _g(v: Any) -> str:
    try:
        return f"{float(v):.4g}" if v is not None and math.isfinite(float(v)) else "n/a"
    except (TypeError, ValueError):
        return "n/a"


# --------------------------------------------------------------------------- run + spec

CHECK_FUNCTIONS = ((check_period_integrity, "live_period_integrity"),
                   (check_vs_shadow, "live_vs_shadow_backtest"),
                   (check_performance_decay, "live_performance_decay"),
                   (check_structural_break, "live_structural_break"),
                   (check_execution_quality, "live_execution_quality"),
                   (check_declared_vs_realised, "live_declared_vs_realised"))


def run(pkg: Any, res: AuditResult) -> None:
    try:
        ctx: Ctx | None = Ctx(pkg)
    except Exception:  # odd data: every check builds its own context and reports
        ctx = None
    for fn, cid in CHECK_FUNCTIONS:
        try:
            fn(pkg, res, ctx)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")


TRADE_SCHEMA = {"required": ["timestamp", "ticker", "side", "quantity", "price"],
                "optional": ["commission", "model_price", "model_timestamp", "trade_id"]}
TRADE_ALIASES = {"timestamp": ["date", "datetime", "time", "execution_time", "fill_time"], "ticker": ["symbol"],
                 "side": ["direction", "action"], "quantity": ["qty", "shares", "units"],
                 "price": ["fill_price", "execution_price"], "commission": ["fee", "fees", "commissions"],
                 "trade_id": ["id", "order_id"], "model_price": ["decision_price", "signal_price", "arrival_price"],
                 "model_timestamp": ["decision_time", "signal_time", "order_time"]}

SPEC = UseCase(
    name=NAME,
    title="Live track record vs backtest",
    description="Validates a live (or paper-trading) record against the backtest that justified it: is the strategy in "
                "production behaving like its simulation (tracking of a shadow backtest, execution quality) and has the "
                "edge decayed (Sharpe haircut, structural break, drawdown beyond the backtest worst case)? It also "
                "contrasts the declared backtest metrics with the series delivered.",
    audience="portfolio managers who went live, allocators doing due diligence, risk committees",
    detect_files=["live_returns"],
    files={"live_returns": "live_returns.csv", "live_trades": "live_trades.csv", "model_trades": "model_trades.csv"},
    file_aliases={"live_returns": ["paper_returns.csv", "track_record.csv"], "live_trades": ["fills.csv"],
                  "model_trades": ["target_trades.csv"]},
    schema={"live_returns": {"required": ["date"], "optional": ["return", "nav", "account", "aum"]},
            "live_trades": TRADE_SCHEMA, "model_trades": TRADE_SCHEMA},
    aliases={"live_returns": {"date": ["datetime", "timestamp"], "return": ["ret", "returns", "live_return", "r"],
                              "nav": ["equity", "value", "portfolio_value"], "account": ["account_id", "portfolio"],
                              "aum": ["assets", "capital", "notional"]},
             "live_trades": TRADE_ALIASES, "model_trades": TRADE_ALIASES},
    date_columns={"live_returns": ["date"], "live_trades": ["timestamp", "model_timestamp"],
                  "model_trades": ["timestamp", "model_timestamp"]},
    numeric_columns={"live_returns": ["return", "nav", "aum"],
                     "live_trades": ["quantity", "price", "commission", "model_price"],
                     "model_trades": ["quantity", "price", "commission", "model_price"]},
    requirements={
        "live_period_integrity": {"required": ["live_returns"], "optional": ["returns", "rules(live)"]},
        "live_vs_shadow_backtest": {"required": ["live_returns", "returns"], "optional": ["rules(live)"]},
        "live_performance_decay": {"required": ["live_returns",
                                                "returns or rules(live.declared_sharpe) or declared_results(sharpe)"],
                                   "optional": ["rules(live)"]},
        "live_structural_break": {"required": ["live_returns", "returns"], "optional": ["rules(live)"]},
        "live_execution_quality": {"required": ["live_trades"],
                                   "optional": ["model_trades", "live_trades(model_price)",
                                                "live_trades(model_timestamp)"]},
        "live_declared_vs_realised": {"required": ["live_returns", "returns"],
                                      "optional": ["rules(live)", "declared_results"]},
    },
    catalog={
        "live_period_integrity": {
            "title": "Live period integrity",
            "what": "Live dates vs the declared live start and the review date; duplicated (date, account) rows; whether "
                    "the live series is a copy of the backtest on the overlap; length of the overlap with the backtest "
                    "(shadow) and the gap after the declared backtest end.",
            "why": "A track record that starts before it was live, that reaches into the future, or that equals the "
                   "backtest is not a live record; without a shadow backtest on the same dates every later comparison "
                   "is period-vs-period, not model-vs-reality.",
            "fix": "Deliver the live returns from account statements and run the backtest over the live dates with the "
                   "production code; declare live.start, live.backtest_end and gap_reason in rules.yaml.",
            "allows": "Whether the live record can be compared with the backtest at all, and on how many periods.",
            "does_not_allow": "Verifying that the live returns are the ones in the broker statements (needs third-party "
                              "statements, GIPS-style).",
            "refs": ["bacon", "gips", "dy11"],
        },
        "live_vs_shadow_backtest": {
            "title": "Live vs shadow backtest",
            "what": "On the common dates: correlation, annualised tracking error, mean difference with a Newey-West "
                    "t-statistic, beta of live on backtest, cumulative gap and when it opened, share of periods with a "
                    "different sign.",
            "why": "Live should differ from its simulation only by execution noise and costs; a systematic negative "
                   "difference or a low correlation means production is not running the model that was validated.",
            "fix": "Attribute the gap to execution, data feeds, risk limits or overrides and fix the production pipeline.",
            "allows": "Whether live tracks the simulation and the size and date of any gap.",
            "does_not_allow": "Judging whether the model has an edge (see live_performance_decay).",
            "refs": ["gk00", "perold88", "bacon"],
        },
        "live_performance_decay": {
            "title": "Live performance decay",
            "what": "Live vs backtest Sharpe (ratio, expected out-of-sample haircut), PSR of the live Sharpe against the "
                    "backtest one, Minimum Track Record Length, Sharpe-difference z-test, annual return and max drawdown "
                    "side by side.",
            "why": "Live Sharpe ratios are typically about half the backtest ones (Suhonen et al. 2017; Harvey and Liu "
                   "2015); a deficit beyond the haircut that is also significant means the edge decayed or the backtest "
                   "overstated it (McLean and Pontiff 2016).",
            "fix": "Re-estimate expectations and sizing from the live record; look for what changed.",
            "allows": "Whether the live record is statistically incompatible with the backtest Sharpe, and how long a "
                      "record would be needed to conclude.",
            "does_not_allow": "Concluding the edge is intact from a short live record (it reports the MinTRL instead).",
            "refs": ["hl15", "slp17", "psr", "jk81", "memmel03", "mp16"],
        },
        "live_structural_break": {
            "title": "Structural break at the live start",
            "what": "Page CUSUM of live returns standardised with the backtest moments (threshold live_cusum_h), a "
                    "Chow-style mean-shift test at the live start with HAC variances, and the percentile of the live "
                    "rolling Sharpe within the backtest's rolling distribution.",
            "why": "A regime change at the moment of going live is the signature of overfitting or of a production "
                   "difference; the CUSUM dates it.",
            "fix": "Date the break and look for a cause: code release, data vendor, capacity, regime.",
            "allows": "Whether and when the live process left the backtest's distribution.",
            "does_not_allow": "Detecting small drifts quickly (the CUSUM needs about h / shift periods); absence of a "
                              "crossing is not evidence of an intact edge.",
            "refs": ["page54", "bde75", "chow60"],
        },
        "live_execution_quality": {
            "title": "Live execution quality",
            "what": "Signed slippage vs the model price in bps (overall and per side, with a t-statistic), delay between "
                    "the model timestamp and the fill, fill ratio and discretionary overrides against model_trades.csv, "
                    "commission per notional.",
            "why": "Implementation shortfall (Perold 1988) is the usual reason live underperforms a backtest that "
                   "assumed model prices; unfilled model trades and overrides mean the live record is not the model's.",
            "fix": "Measure shortfall per venue and order type, enforce the model trade list or document overrides, "
                   "feed realised costs back into the backtest.",
            "allows": "How much of the live gap is execution and how much the record departs from the model's orders.",
            "does_not_allow": "Judging market impact without quotes and volumes.",
            "refs": ["perold88", "ac01"],
        },
        "live_declared_vs_realised": {
            "title": "Declared backtest vs delivered series vs live",
            "what": "Table declared / backtest series (recomputed with the core metrics module and the declared "
                    "convention) / live realised for Sharpe, annual return and max drawdown.",
            "why": "The number in the pitch must be the series delivered; and a live drawdown beyond the backtest worst "
                   "case means the risk budget was set on a lower bound.",
            "fix": "Deliver the series behind the declared metrics or correct them; re-estimate the risk budget.",
            "allows": "Whether the declared metrics are the delivered series and whether live already broke the "
                      "backtest's worst case.",
            "does_not_allow": "Verifying the convention used by the strategy owner beyond the one declared.",
            "refs": ["bacon", "mia", "gips"],
        },
    },
    references={
        "slp17": "Suhonen, A., Lennkh, M. and Perez, F. (2017). Quantifying Backtest Overfitting in Alternative Beta "
                 "Strategies. Journal of Portfolio Management 43(2), 90-104.",
        "jk81": "Jobson, J. D. and Korkie, B. M. (1981). Performance Hypothesis Testing with the Sharpe and Treynor "
                "Measures. Journal of Finance 36(4), 889-908.",
        "memmel03": "Memmel, C. (2003). Performance Hypothesis Testing with the Sharpe Ratio. Finance Letters 1, 21-23.",
        "page54": "Page, E. S. (1954). Continuous Inspection Schemes. Biometrika 41(1/2), 100-115.",
        "bde75": "Brown, R. L., Durbin, J. and Evans, J. M. (1975). Techniques for Testing the Constancy of Regression "
                 "Relationships over Time. Journal of the Royal Statistical Society B 37(2), 149-192.",
        "chow60": "Chow, G. C. (1960). Tests of Equality Between Sets of Coefficients in Two Linear Regressions. "
                  "Econometrica 28(3), 591-605.",
        "perold88": "Perold, A. F. (1988). The Implementation Shortfall: Paper versus Reality. Journal of Portfolio "
                    "Management 14(3), 4-9.",
        "dy11": "Dichev, I. D. and Yu, G. (2011). Higher Risk, Lower Returns: What Hedge Fund Investors Really Earn. "
                "Journal of Financial Economics 100(2), 248-263.",
        "mp16": "McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? "
                "Journal of Finance 71(1), 5-32.",
    },
    conventions={"live_min_periods": 60, "live_tracking_error_review": 0.03, "live_alpha": 0.05,
                 "live_haircut_expected": 0.5, "live_cusum_h": 5.0, "live_slippage_review_bps": 10,
                 "live_rolling_window": 60},
    profiles={
        "live_daily": {"description": "Daily live record vs a daily backtest (default live conventions).",
                       "conventions": {}},
        "live_monthly": {"description": "Monthly live record: 12 periods a year, 24 months minimum overlap, 2% "
                                        "tracking-error review, 12-month rolling window.",
                         "conventions": {"periods_per_year": 12, "live_min_periods": 24,
                                         "live_tracking_error_review": 0.02, "live_rolling_window": 12,
                                         "stale_run": 3}},
    },
    run=run,
)
register(SPEC)
