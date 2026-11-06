"""Alpha signal research (0.3.0, use case ``signals``).

Validation of a predictive score (a factor, an alpha signal, a model output) BEFORE it becomes a strategy: does
it predict forward returns, how fast does the prediction decay, how much turnover does it imply, and is it
suspiciously related to the contemporaneous return (a timestamp problem)?

Inputs: ``signals.csv`` (decision_time, ticker, signal) and ``prices.csv`` (date, ticker, close). Nothing else is
required; ``rules.yaml`` may declare the conventions below and ``short_selling`` / ``rebalance.frequency``.

Alignment convention (``signal_lag_sessions``, default 1): a decision dated t enters at the close of session
t + lag and exits h sessions later, so the forward return at horizon h is close(t + lag + h) / close(t + lag) - 1.
With lag 0 the entry is the close of the decision session itself, which is only legitimate if the decision was
taken at or after that close.

Statistics (numpy + pandas only):
- per-date Spearman rank information coefficient (IC) between the signal and the forward return;
- mean IC, its standard deviation, hit rate and a t-statistic whose variance uses Newey-West (Bartlett) weights
  with L = ceil(h / spacing) - 1 lags when forward windows overlap (spacing = median sessions between decision
  dates);
- quantile portfolios (equal-sized buckets by rank; bucket q = highest signal), top-minus-bottom spread, its
  Newey-West t-stat and the monotonicity (Spearman between bucket rank and mean return);
- rank autocorrelation of the signal between decision dates, one-way turnover of the top bucket and the signal
  half-life fitted on the lag profile;
- IC with the contemporaneous return (h = 0) and the previous one (h = -1) as a look-ahead hint.

Single-asset or thin cross-sections: when fewer than ``signal_min_periods`` dates have a cross-section of at least
``signal_min_cross_section`` names, the predictive-power and look-ahead checks fall back to a time-series rank
correlation per ticker (per-date mean of the products of standardised ranks, same Newey-West t-stat) and say so;
the quantile and turnover checks need a cross-section and report NOT_EXECUTABLE.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from . import UseCase, register

NAME = "signals"
DEFAULT_HORIZONS = [1, 5, 21]
HLZ_HURDLE = 3.0  # Harvey, Liu and Zhu (2016) t-stat hurdle for a new factor
LOOKAHEAD_RATIO = 3.0  # |IC(h=0)| / |IC(h=1)| above which the hint is raised
SPREAD_T_REVIEW = 2.0
MONOTONICITY_REVIEW = 0.6
LONG_LEG_MIN_SHARE = 0.25  # share of the spread that must come from the long leg when short selling is off
COVERAGE_REVIEW = 0.20  # share of signal rows without a forward price that triggers a review
REBALANCE_SESSIONS = {"daily": 1, "weekly": 5, "monthly": 21, "quarterly": 63, "annual": 252, "yearly": 252}
ALL = ["signal_forward_alignment", "signal_predictive_power", "signal_quantile_spread", "signal_turnover",
       "signal_lookahead_hint"]


# ---------------------------------------------------------------------------- statistics (pure numpy / pandas)

def spearman(x, y) -> float:
    """Spearman rank correlation (average ranks for ties); nan with fewer than 3 pairs or a constant side."""
    a = pd.Series(np.asarray(x, dtype=float))
    b = pd.Series(np.asarray(y, dtype=float))
    ok = a.notna() & b.notna()
    if ok.sum() < 3:
        return float("nan")
    ra = a[ok].rank(method="average").to_numpy()
    rb = b[ok].rank(method="average").to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def nw_tstat(x, lags: int) -> dict[str, float]:
    """Mean, sd, Newey-West (1987) t-stat of the mean with Bartlett weights 1 - k / (L + 1), k = 1..L.

    var(mean) = (gamma_0 + 2 sum_k w_k gamma_k) / n with gamma_k = sum_t (x_t - m)(x_{t-k} - m) / n.
    L = 0 gives the usual t = m / (sd / sqrt(n)) (up to the 1/n vs 1/(n-1) variance convention).
    """
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    n = int(a.size)
    if n < 3:
        return {"mean": float("nan"), "sd": float("nan"), "t": float("nan"), "n": n, "lags": int(lags)}
    m = float(a.mean())
    d = a - m
    L = int(max(0, min(lags, n - 1)))
    var = float((d * d).sum() / n)
    for k in range(1, L + 1):
        gk = float((d[k:] * d[:-k]).sum() / n)
        var += 2.0 * (1.0 - k / (L + 1.0)) * gk
    se = math.sqrt(max(var, 0.0) / n)
    t = m / se if se > 0 else float("nan")
    return {"mean": m, "sd": float(a.std(ddof=1)), "t": float(t), "n": n, "lags": L}


def assign_quantiles(values, q: int) -> np.ndarray:
    """Bucket 1..q by ascending rank (ties broken by position, equal-sized buckets); q = highest signal.
    NaN values get 0."""
    s = pd.Series(np.asarray(values, dtype=float))
    out = np.zeros(len(s), dtype=int)
    ok = s.notna()
    n = int(ok.sum())
    if n == 0:
        return out
    r = s[ok].rank(method="first").to_numpy()
    out[ok.to_numpy()] = np.minimum(q, np.ceil(r * q / n)).astype(int)
    return out


def half_life_from_profile(rho: list[float]) -> float:
    """Half-life (in decision dates) from the lag profile rho_1..rho_K: least-squares fit of log rho_k = b k
    through the origin on the positive values; inf when the signal does not decay; < 1 when rho_1 <= 0."""
    pts = [(k, math.log(r)) for k, r in enumerate(rho, start=1) if math.isfinite(r) and 0 < r < 1]
    if not rho or not math.isfinite(rho[0]):
        return float("nan")
    if rho[0] <= 0:
        return 0.5
    if not pts:
        return float("inf")
    b = sum(k * lr for k, lr in pts) / sum(k * k for k, _ in pts)
    return math.log(0.5) / b if b < 0 else float("inf")


# ---------------------------------------------------------------------------- conventions and panel

def horizons_of(pkg: Any) -> list[int]:
    v = pkg.conv("signal_horizons", DEFAULT_HORIZONS)
    if isinstance(v, str):
        v = [p for p in v.replace(";", ",").split(",") if p.strip()]
    if not isinstance(v, (list, tuple)):
        v = [v]
    out: list[int] = []
    for x in v:
        try:
            h = int(x)
        except (TypeError, ValueError):
            continue
        if h >= 1 and h not in out:
            out.append(h)
    return out or list(DEFAULT_HORIZONS)


def conventions(pkg: Any) -> dict[str, Any]:
    return {
        "horizons": horizons_of(pkg),
        "quantiles": max(2, int(pkg.conv("signal_quantiles", 5))),
        "min_cs": max(2, int(pkg.conv("signal_min_cross_section", 10))),
        "min_periods": max(3, int(pkg.conv("signal_min_periods", 24))),
        "ic_t": float(pkg.conv("signal_ic_t_review", 2.0)),
        "turnover_rho": float(pkg.conv("signal_turnover_review", 0.5)),
        "lag": max(0, int(pkg.conv("signal_lag_sessions", 1))),
    }


def _bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "y")


class Panel:
    """Signals joined with forward returns on the session calendar of prices.csv."""

    def __init__(self, pkg: Any, cv: dict[str, Any]):
        self.cv = cv
        px = pkg.df("prices").dropna(subset=["date", "ticker", "close"])
        px = px.sort_values(["date", "row"]).drop_duplicates(["ticker", "date"], keep="first")
        wide = px.pivot(index="date", columns="ticker", values="close").sort_index()
        wide = wide.ffill()  # a missing close is valued at the last available one (as the core reconstruction)
        self.sessions = pd.DatetimeIndex(wide.index)
        self.tickers = list(wide.columns)
        self.W = wide.to_numpy(dtype=float)
        sig = pkg.df("signals").dropna(subset=["decision_time", "ticker", "signal"]).copy()
        sig["decision_date"] = sig["decision_time"].dt.normalize()
        sig = sig.sort_values(["decision_date", "row"]).drop_duplicates(["decision_date", "ticker"], keep="first")
        self.n_rows_signals = int(len(pkg.df("signals")))
        col_idx = {t: i for i, t in enumerate(self.tickers)}
        sig["col"] = [col_idx.get(t, -1) for t in sig["ticker"]]
        sig["i0"] = self.sessions.searchsorted(sig["decision_date"].to_numpy(), side="left")
        n_s = len(self.sessions)
        sig["has_session"] = sig["i0"] < n_s
        sig["off_session"] = sig["has_session"] & (
            self.sessions[np.minimum(sig["i0"].to_numpy(), max(n_s - 1, 0))].to_numpy()
            != sig["decision_date"].to_numpy())
        lag = cv["lag"]
        for h in cv["horizons"]:
            sig[f"fwd_{h}"] = self._ret(sig, lag, lag + h)
        sig["ret_0"] = self._ret(sig, -1, 0)
        sig["ret_m1"] = self._ret(sig, -2, -1)
        sig["entry_known"] = (sig["col"] >= 0) & sig["has_session"] & np.isfinite(self._close(sig, lag))
        self.df = sig.reset_index(drop=True)
        self.spacing = self._spacing()

    def _close(self, sig: pd.DataFrame, offset: int) -> np.ndarray:
        idx = sig["i0"].to_numpy() + offset
        col = sig["col"].to_numpy()
        ok = (col >= 0) & (idx >= 0) & (idx < len(self.sessions))
        out = np.full(len(sig), np.nan)
        if ok.any():
            out[ok] = self.W[idx[ok], col[ok]]
        return out

    def _ret(self, sig: pd.DataFrame, entry_off: int, exit_off: int) -> np.ndarray:
        a = self._close(sig, entry_off)
        b = self._close(sig, exit_off)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = b / a - 1.0
        r[~np.isfinite(r) | (a <= 0)] = np.nan
        return r

    def _spacing(self) -> int:
        d = np.sort(self.df["i0"].unique())
        if len(d) < 2:
            return 1
        return int(max(1, np.median(np.diff(d))))

    def nw_lags(self, h: int) -> int:
        return int(max(0, math.ceil(h / self.spacing) - 1))

    # per-date statistics -----------------------------------------------------------------------------------
    def dates_with_cross_section(self, ycol: str) -> pd.Series:
        """decision_date -> number of names with a signal and a value of ``ycol``."""
        d = self.df.dropna(subset=["signal", ycol])
        return d.groupby("decision_date").size()

    def ic_series(self, ycol: str) -> tuple[pd.Series, str, int]:
        """Per-date IC series. Cross-sectional Spearman on dates with >= min_cs names when at least min_periods such
        dates exist; otherwise the time-series fallback (per-date mean of products of standardised ranks within each
        ticker's history). Returns (series, mode, n_dates_with_cross_section)."""
        cv = self.cv
        d = self.df.dropna(subset=["signal", ycol])
        counts = d.groupby("decision_date").size()
        good = counts[counts >= cv["min_cs"]].index
        if len(good) >= cv["min_periods"]:
            sub = d[d["decision_date"].isin(good)]
            ic = sub.groupby("decision_date")[["signal", ycol]].apply(lambda g: spearman(g["signal"], g[ycol]))
            return ic.dropna().sort_index(), "cross-sectional", int(len(good))
        if d["decision_date"].nunique() < cv["min_periods"]:
            return pd.Series(dtype=float), "insufficient", int(len(good))
        parts = []
        for _, g in d.groupby("ticker"):
            if len(g) < cv["min_periods"]:
                continue
            rs = g["signal"].rank(method="average")
            ry = g[ycol].rank(method="average")
            if rs.std() == 0 or ry.std() == 0:
                continue
            zs = (rs - rs.mean()) / rs.std(ddof=0)
            zy = (ry - ry.mean()) / ry.std(ddof=0)
            parts.append(pd.Series((zs * zy).to_numpy(), index=g["decision_date"].to_numpy()))
        if not parts:
            return pd.Series(dtype=float), "insufficient", int(len(good))
        allp = pd.concat(parts)
        return allp.groupby(level=0).mean().sort_index(), "time-series", int(len(good))


def _panel(pkg: Any) -> Panel:
    return Panel(pkg, conventions(pkg))


def _ev_rows(d: pd.DataFrame, n: int = 20) -> list[dict[str, Any]]:
    return [{"row": int(r.row), "date": r.decision_date.date() if pd.notna(r.decision_date) else None,
             "ticker": r.ticker} for r in d.head(n).itertuples()]


# ---------------------------------------------------------------------------- checks

def check_alignment(pkg: Any, res: AuditResult) -> None:
    cid, title = "signal_forward_alignment", "Forward-return alignment of the signal"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    P = _panel(pkg)
    cv = P.cv
    d = P.df
    if d.empty:
        not_executable(res, cid, NAME, title, "signals.csv has no row with decision_time, ticker and a numeric signal")
        return
    h1 = cv["horizons"][0]
    proc = (f"decision date = calendar day of decision_time; entry = close of the first price session at or after it "
            f"plus {cv['lag']} session(s) (conventions.signal_lag_sessions); exit = entry + h sessions, h in "
            f"{cv['horizons']}; forward return = close(exit) / close(entry) - 1 on prices.csv (missing closes carried "
            f"forward). {len(d)} distinct (decision date, ticker) rows of {P.n_rows_signals}; median spacing between "
            f"decision dates {P.spacing} session(s).")
    unknown = d[(cv["lag"] == 0) & d["off_session"] & (d["col"] >= 0)]
    if cv["lag"] == 0 and len(unknown):
        res.add(cid, NAME, CONFIRMED_ERROR, "Entry at a close that was not yet known (lag 0 on a non-session date)",
                f"signal_lag_sessions is 0, so the entry is the close of the decision session, but {len(unknown)} "
                "signal rows are dated on days that are not price sessions: their entry would be the NEXT session's "
                "close, a price not known when the decision was taken.",
                _ev_rows(unknown), proc, action="Declare signal_lag_sessions >= 1 or date the decisions on sessions.",
                priority="high", inputs=["signals", "prices", "rules"])
        return
    no_fwd = d[d[f"fwd_{h1}"].isna()]
    tail = no_fwd["i0"] + cv["lag"] + h1 >= len(P.sessions)  # exit after the last price session: not yet observable
    missing = no_fwd[~tail]
    unknown_ticker = int((d["col"] < 0).sum())
    share = len(no_fwd) / len(d)
    cover = [{"horizon": h, "rows_with_forward_return": int(d[f"fwd_{h}"].notna().sum()), "rows": int(len(d))}
             for h in cv["horizons"]]
    res.metrics[cid] = {"rows": int(len(d)), "no_forward_share_primary": share, "lag": cv["lag"],
                        "spacing_sessions": P.spacing, "tickers_not_in_prices": unknown_ticker, "coverage": cover}
    if share > COVERAGE_REVIEW:
        res.add(cid, NAME, NEEDS_REVIEW, f"{share:.0%} of the signal rows have no forward price at h = {h1}",
                f"{len(no_fwd)} of {len(d)} rows cannot be matched to an entry and exit close ({unknown_ticker} rows "
                f"with a ticker absent from prices.csv). The IC and spreads below are computed on the rest; a biased "
                "subset (e.g. only survivors with prices) would bias them.",
                _ev_rows(no_fwd), proc, action="Provide prices for every signalled ticker up to the longest horizon "
                "after the last decision, or explain the gap.", priority="medium", inputs=["signals", "prices"])
        return
    if cv["lag"] >= 1 and len(missing) == 0:
        res.add(cid, NAME, PASS, f"Every signal row aligns with a forward close (lag {cv['lag']} session)",
                f"{len(d)} rows, horizons {cv['horizons']}: entry strictly after the decision session, exit h "
                "sessions later. " + "; ".join(f"h={c['horizon']}: {c['rows_with_forward_return']} rows" for c in cover)
                + (f". {len(no_fwd)} rows decided too close to the end of prices.csv to have a forward return at "
                   f"h = {h1} yet (excluded from the statistics, not a misalignment)." if len(no_fwd) else "."),
                cover, proc, inputs=["signals", "prices"])
        return
    note = ("lag 0: the entry is the decision session's own close, legitimate only if the decision is taken at or "
            "after that close. " if cv["lag"] == 0 else "")
    res.add(cid, NAME, INFO, f"Alignment convention: lag {cv['lag']} session(s), {share:.1%} rows without forward price",
            note + f"{len(missing)} rows lack a price inside the history, {len(no_fwd) - len(missing)} are too recent. "
            + "; ".join(f"h={c['horizon']}: {c['rows_with_forward_return']} of {c['rows']} rows" for c in cover) + ".",
            cover + _ev_rows(missing, 10), proc, action="Declare signal_lag_sessions >= 1 unless decisions are taken "
            "after the close." if cv["lag"] == 0 else "", inputs=["signals", "prices"])


def _ic_table(P: Panel) -> tuple[list[dict[str, Any]], str, int]:
    rows = []
    mode_primary = "insufficient"
    n_good_primary = 0
    for i, h in enumerate(P.cv["horizons"]):
        ic, mode, n_good = P.ic_series(f"fwd_{h}")
        if i == 0:
            mode_primary, n_good_primary = mode, n_good
        st = nw_tstat(ic.to_numpy(), P.nw_lags(h)) if len(ic) else nw_tstat([], 0)
        hit = float((ic > 0).mean()) if len(ic) else float("nan")
        rows.append({"horizon": h, "mode": mode, "n_dates": st["n"], "mean_ic": st["mean"], "ic_sd": st["sd"],
                     "t_stat": st["t"], "nw_lags": st["lags"], "hit_rate": hit,
                     "ir_per_date": (st["mean"] / st["sd"]) if st["sd"] and st["sd"] > 0 else float("nan")})
    return rows, mode_primary, n_good_primary


def check_predictive_power(pkg: Any, res: AuditResult) -> None:
    cid, title = "signal_predictive_power", "Predictive power of the signal (rank IC)"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    P = _panel(pkg)
    cv = P.cv
    rows, mode, n_good = _ic_table(P)
    res.metrics[cid] = {"table": rows, "mode": mode, "conventions": cv}
    if mode == "insufficient" or not rows or rows[0]["n_dates"] < cv["min_periods"]:
        not_executable(res, cid, NAME, title,
                       f"only {n_good} decision dates have a cross-section of at least {cv['min_cs']} names with a "
                       f"forward return at h = {cv['horizons'][0]} (signal_min_periods = {cv['min_periods']}), and "
                       f"fewer than {cv['min_periods']} dates for the time-series fallback",
                       action="Provide at least signal_min_periods decision dates (with prices after them).")
        return
    primary = rows[0]
    proc = (f"Per decision date, Spearman rank correlation between the signal and the forward return (alignment as in "
            f"signal_forward_alignment); t-stat = mean IC / Newey-West standard error with Bartlett weights and "
            f"L = ceil(h / {P.spacing}) - 1 lags for overlapping windows; hit rate = share of dates with IC > 0. "
            + ("Cross-sectional mode: dates with fewer than "
               f"{cv['min_cs']} names are skipped." if mode == "cross-sectional" else
               "TIME-SERIES FALLBACK: the cross-section is too thin, so the IC is the per-date mean over tickers of "
               "the product of standardised ranks of the signal and of the forward return within each ticker's own "
               "history (a rank correlation through time, not across names)."))
    ev = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    txt = "; ".join(f"h={r['horizon']}: IC {r['mean_ic']:+.4f} (sd {r['ic_sd']:.3f}, t {r['t_stat']:+.2f}, "
                    f"hit {r['hit_rate']:.0%}, n {r['n_dates']})" for r in rows if r["n_dates"] >= 3)
    problems = []
    if not math.isfinite(primary["t_stat"]) or abs(primary["t_stat"]) < cv["ic_t"]:
        problems.append(f"|t| = {abs(primary['t_stat']):.2f} < {cv['ic_t']} at the primary horizon h = "
                        f"{primary['horizon']} (signal_ic_t_review)")
    flips = [r for r in rows[1:] if r["n_dates"] >= cv["min_periods"] and math.isfinite(r["t_stat"])
             and abs(r["t_stat"]) >= 1.0 and math.isfinite(primary["mean_ic"])
             and np.sign(r["mean_ic"]) != np.sign(primary["mean_ic"]) and primary["mean_ic"] != 0]
    if flips:
        problems.append("the sign of the mean IC flips across horizons (h = "
                        + ", ".join(str(r["horizon"]) for r in flips) + f" vs h = {primary['horizon']})")
    hlz = (f" The primary t-stat {'clears' if abs(primary['t_stat']) >= HLZ_HURDLE else 'does not clear'} the 3.0 "
           "hurdle that Harvey, Liu and Zhu (2016) propose for a new factor after multiple testing.")
    caution = (" Time-series fallback: a single-asset correlation is far noisier than a cross-sectional IC and is "
               "exposed to one regime; treat as a hint, not a result." if mode == "time-series" else "")
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "The signal does not show significant predictive power: " + problems[0],
                "; ".join(problems).capitalize() + ". " + txt + "." + hlz + caution
                + " A mean IC indistinguishable from zero, or one whose sign depends on the horizon, is what a noise "
                  "signal looks like (Grinold and Kahn; Qian, Hua and Sorensen).",
                ev, proc, action="Do not build a strategy on this signal as it stands; check the alignment and the "
                "universe, and remember the number of signals tried.", priority="medium",
                inputs=["signals", "prices", "rules"])
        return
    res.add(cid, NAME, INFO, f"IC significant at the declared level: t = {primary['t_stat']:+.2f} at h = {primary['horizon']}",
            txt + "." + hlz + caution + " Significance is not skill: an IC of this size must survive costs, "
            "turnover (signal_turnover) and the number of signals tried (Bailey and Lopez de Prado 2014).",
            ev, proc, action="Report the IC decay profile with the number of signals tried; test out of sample.",
            priority="low", inputs=["signals", "prices", "rules"])


def check_quantile_spread(pkg: Any, res: AuditResult) -> None:
    cid, title = "signal_quantile_spread", "Quantile portfolios and top-minus-bottom spread"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    P = _panel(pkg)
    cv = P.cv
    q = cv["quantiles"]
    h = cv["horizons"][0]
    ycol = f"fwd_{h}"
    d = P.df.dropna(subset=["signal", ycol])
    counts = d.groupby("decision_date").size()
    need = max(cv["min_cs"], q)
    good = counts[counts >= need].index
    if len(good) < cv["min_periods"]:
        not_executable(res, cid, NAME, title,
                       f"only {len(good)} decision dates have at least {need} names with a forward return at h = {h} "
                       f"(need signal_min_periods = {cv['min_periods']}); quantile portfolios need a cross-section")
        return
    d = d[d["decision_date"].isin(good)].copy()
    d["bucket"] = 0
    for _, g in d.groupby("decision_date"):
        d.loc[g.index, "bucket"] = assign_quantiles(g["signal"].to_numpy(), q)
    per_date = d.groupby(["decision_date", "bucket"])[ycol].mean().unstack("bucket").sort_index()
    means = per_date.mean()
    spread = (per_date[q] - per_date[1]).dropna()
    st = nw_tstat(spread.to_numpy(), P.nw_lags(h))
    mono = spearman(list(range(1, q + 1)), [means.get(b, np.nan) for b in range(1, q + 1)])
    middle = float(means.drop([1, q]).mean()) if q > 2 else float(means.mean())
    long_leg = float(means[q] - middle)
    short_leg = float(middle - means[1])
    long_share = long_leg / st["mean"] if st["mean"] and st["mean"] > 0 else float("nan")
    short_selling = _bool(pkg.conv("short_selling"), False)
    ev = [{"bucket": int(b), "mean_forward_return": round(float(means[b]), 6), "n_dates": int(per_date[b].notna().sum()),
           "label": "top (highest signal)" if b == q else ("bottom" if b == 1 else "")} for b in range(1, q + 1)]
    ev.append({"bucket": "top - bottom", "mean_forward_return": round(st["mean"], 6), "t_stat": round(st["t"], 2),
               "nw_lags": st["lags"], "n_dates": st["n"], "monotonicity": round(mono, 3) if math.isfinite(mono) else None,
               "long_leg_share": round(long_share, 3) if math.isfinite(long_share) else None})
    res.metrics[cid] = {"means": {int(b): float(means[b]) for b in means.index}, "spread": st, "monotonicity": mono,
                        "long_leg": long_leg, "short_leg": short_leg, "long_leg_share": long_share, "horizon": h}
    proc = (f"On each of {len(good)} decision dates with at least {need} names, the signal is sorted into {q} equal-sized "
            f"buckets (bucket {q} = highest); the mean forward return at h = {h} per bucket is averaged over dates; "
            f"spread = bucket {q} - bucket 1 per date, t-stat with Newey-West L = {st['lags']}; monotonicity = Spearman "
            "between bucket rank and mean return; long-leg share = (top - mean of middle buckets) / spread.")
    txt = (f"Spread {st['mean'] * 1e4:+.1f} bp per {h}-session horizon (t {st['t']:+.2f}, n {st['n']}), monotonicity "
           f"{mono:.2f}, long leg {long_leg * 1e4:+.1f} bp, short leg {short_leg * 1e4:+.1f} bp.")
    problems = []
    if not math.isfinite(st["t"]) or st["t"] < SPREAD_T_REVIEW:
        problems.append(f"spread t-stat {st['t']:.2f} < {SPREAD_T_REVIEW}")
    if not math.isfinite(mono) or mono < MONOTONICITY_REVIEW:
        problems.append(f"monotonicity {mono:.2f} < {MONOTONICITY_REVIEW}")
    if not short_selling and st["mean"] > 0 and math.isfinite(long_share) and long_share < LONG_LEG_MIN_SHARE:
        problems.append(f"only {max(long_share, 0):.0%} of the spread comes from the long leg (< {LONG_LEG_MIN_SHARE:.0%}) "
                        "while rules.yaml declares short_selling: false, so the spread is not capturable")
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "Quantile spread does not support the signal: " + problems[0],
                "; ".join(problems).capitalize() + ". " + txt, ev, proc,
                action="Look at the per-bucket table: a spread that is not monotonic or that lives in the short leg is "
                "not a long-only alpha.", priority="medium", inputs=["signals", "prices", "rules"])
        return
    res.add(cid, NAME, INFO, f"Quantile spread {st['mean'] * 1e4:+.1f} bp (t {st['t']:+.2f}), monotonicity {mono:.2f}",
            txt + " Before costs and before the number of signals tried.", ev, proc,
            action="Net the spread of the turnover-implied costs (signal_turnover).", priority="low",
            inputs=["signals", "prices", "rules"])


def check_turnover(pkg: Any, res: AuditResult) -> None:
    cid, title = "signal_turnover", "Signal persistence and implied turnover"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    P = _panel(pkg)
    cv = P.cv
    q = cv["quantiles"]
    d = P.df.dropna(subset=["signal"])
    counts = d.groupby("decision_date").size()
    good = sorted(counts[counts >= max(cv["min_cs"], q)].index)
    if len(good) < cv["min_periods"]:
        not_executable(res, cid, NAME, title,
                       f"only {len(good)} decision dates have at least {max(cv['min_cs'], q)} names (need "
                       f"signal_min_periods = {cv['min_periods']}); turnover of a ranked portfolio needs a cross-section")
        return
    by_date = {dt: g.set_index("ticker")["signal"] for dt, g in d[d["decision_date"].isin(good)].groupby("decision_date")}
    K = int(max(1, min(10, len(good) // 4)))
    profile: list[float] = []
    turn: list[float] = []
    for k in range(1, K + 1):
        acs = []
        for a, b in zip(good[:-k], good[k:]):
            sa, sb = by_date[a], by_date[b]
            common = sa.index.intersection(sb.index)
            if len(common) >= 3:
                acs.append(spearman(sa.loc[common], sb.loc[common]))
                if k == 1:
                    qa = assign_quantiles(sa.loc[common].to_numpy(), q)
                    qb = assign_quantiles(sb.loc[common].to_numpy(), q)
                    top_a = set(np.asarray(common)[qa == q])
                    top_b = set(np.asarray(common)[qb == q])
                    if top_a:
                        turn.append(len(top_a - top_b) / len(top_a))
        acs = [x for x in acs if math.isfinite(x)]
        profile.append(float(np.mean(acs)) if acs else float("nan"))
    rho1 = profile[0]
    hl_dates = half_life_from_profile(profile)
    hl_sessions = hl_dates * P.spacing if math.isfinite(hl_dates) else hl_dates
    turnover = float(np.mean(turn)) if turn else float("nan")
    h1 = cv["horizons"][0]
    reb = (pkg.rules or {}).get("rebalance") if isinstance((pkg.rules or {}).get("rebalance"), dict) else {}
    freq = str(reb.get("frequency") or "").strip().lower()
    reb_sessions = REBALANCE_SESSIONS.get(freq)
    ev = [{"lag_dates": k, "rank_autocorrelation": round(r, 4) if math.isfinite(r) else None} for k, r in enumerate(profile, 1)]
    ev.append({"one_way_turnover_top_bucket": round(turnover, 4) if math.isfinite(turnover) else None,
               "half_life_dates": None if not math.isfinite(hl_dates) else round(hl_dates, 2),
               "half_life_sessions": None if not math.isfinite(hl_sessions) else round(hl_sessions, 2),
               "spacing_sessions": P.spacing, "primary_horizon": h1, "rebalance_frequency": freq or "not declared"})
    res.metrics[cid] = {"profile": profile, "rho1": rho1, "turnover": turnover, "half_life_dates": hl_dates,
                        "half_life_sessions": hl_sessions, "spacing": P.spacing, "rebalance_sessions": reb_sessions}
    proc = (f"On {len(good)} decision dates with at least {max(cv['min_cs'], q)} names: Spearman correlation of the "
            f"signal between dates k apart (k = 1..{K}), averaged over dates; one-way turnover = share of the top "
            f"bucket (of {q}) at one date that is not in the top bucket at the next; half-life fitted as log rho_k = b k "
            f"on the positive part of the profile, in decision dates (x {P.spacing} = sessions).")
    txt = (f"Rank autocorrelation at lag 1: {rho1:.2f}; one-way turnover of the top bucket per decision date: "
           f"{turnover:.0%}; half-life {hl_dates:.1f} decision dates (~{hl_sessions:.0f} sessions).")
    problems = []
    if math.isfinite(rho1) and rho1 < cv["turnover_rho"] and h1 > P.spacing:
        problems.append(f"rank autocorrelation {rho1:.2f} < {cv['turnover_rho']} (signal_turnover_review) while the "
                        f"primary horizon is {h1} sessions: the signal is re-drawn faster than the horizon it is "
                        "evaluated on")
    if reb_sessions is not None and math.isfinite(hl_sessions) and hl_sessions < reb_sessions:
        problems.append(f"half-life ~{hl_sessions:.0f} sessions is shorter than the declared {freq} rebalance "
                        f"({reb_sessions} sessions): the signal implies more turnover than the rebalance schedule allows")
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "Turnover incompatible with the horizon or the rebalance: " + problems[0],
                "; ".join(problems).capitalize() + ". " + txt, ev, proc,
                action="Smooth the signal or shorten the horizon / rebalance; cost the implied turnover before "
                "reading the IC as capturable.", priority="medium", inputs=["signals", "prices", "rules"])
        return
    res.add(cid, NAME, INFO, f"Rank autocorrelation {rho1:.2f}, top-bucket turnover {turnover:.0%} per decision date",
            txt + " Compare the implied turnover with the cost assumptions of the strategy that will use the signal.",
            ev, proc, priority="low", inputs=["signals", "prices", "rules"])


def check_lookahead_hint(pkg: Any, res: AuditResult) -> None:
    cid, title = "signal_lookahead_hint", "Look-ahead hint: IC with the contemporaneous return"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    P = _panel(pkg)
    cv = P.cv
    rows = []
    for label, ycol, h in (("h=0 (decision session's own return)", "ret_0", 0),
                           ("h=-1 (previous session's return)", "ret_m1", 0),
                           ("h=1 (forward, aligned)", "fwd_1" if 1 in cv["horizons"] else f"fwd_{cv['horizons'][0]}",
                            1 if 1 in cv["horizons"] else cv["horizons"][0])):
        ic, mode, _ = P.ic_series(ycol)
        st = nw_tstat(ic.to_numpy(), P.nw_lags(h) if h else 0) if len(ic) else nw_tstat([], 0)
        rows.append({"return": label, "mode": mode, "n_dates": st["n"], "mean_ic": st["mean"], "t_stat": st["t"]})
    ic0, icm1, ic1 = rows
    if ic0["mode"] == "insufficient" or ic1["mode"] == "insufficient" or ic0["n_dates"] < cv["min_periods"]:
        not_executable(res, cid, NAME, title, f"fewer than signal_min_periods = {cv['min_periods']} decision dates with a "
                       f"cross-section of {cv['min_cs']} names (or enough history for the time-series fallback)")
        return
    ev = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    res.metrics[cid] = {"table": rows}
    proc = (f"Same per-date rank IC as signal_predictive_power ({ic0['mode']} mode), computed against the return of the "
            "decision session itself (close(t) / close(t-1) - 1), the previous session's return and the aligned forward "
            f"return at h = 1 (entry at lag {cv['lag']}); the ratio |IC(h=0)| / |IC(h=1)| is compared with {LOOKAHEAD_RATIO:.0f}.")
    ratio = abs(ic0["mean_ic"]) / abs(ic1["mean_ic"]) if math.isfinite(ic1["mean_ic"]) and ic1["mean_ic"] != 0 else float("inf")
    mom = ""
    if math.isfinite(icm1["t_stat"]) and abs(icm1["t_stat"]) >= cv["ic_t"]:
        mom = (f" The IC with the PREVIOUS session's return is {icm1['mean_ic']:+.3f} (t {icm1['t_stat']:+.2f}): the "
               "signal embeds recent returns (momentum- or reversal-like). That is legitimate when intended; say so in "
               "the signal's definition.")
    txt = (f"IC h=0: {ic0['mean_ic']:+.4f} (t {ic0['t_stat']:+.2f}); h=-1: {icm1['mean_ic']:+.4f} (t {icm1['t_stat']:+.2f}); "
           f"h=1: {ic1['mean_ic']:+.4f} (t {ic1['t_stat']:+.2f}); ratio |IC0| / |IC1| = "
           + (f"{ratio:.1f}" if math.isfinite(ratio) else "inf") + ".")
    if math.isfinite(ic0["t_stat"]) and abs(ic0["t_stat"]) >= cv["ic_t"] and ratio > LOOKAHEAD_RATIO:
        res.add(cid, NAME, NEEDS_REVIEW, "The signal is more related to the contemporaneous return than to the future one: "
                "check timestamps", txt + " A score computed with the close of the decision session (or later) is "
                "correlated with that session's return and not with the next; that pattern is what a timestamp error "
                "looks like, not what a forecast looks like." + mom, ev, proc,
                action="Trace how decision_time is set and which prices enter the signal; recompute with data strictly "
                "before the decision.", priority="high", inputs=["signals", "prices"])
        return
    res.add(cid, NAME, INFO, "No look-ahead pattern: |IC(h=0)| / |IC(h=1)| = " + (f"{ratio:.1f}" if math.isfinite(ratio) else "inf"),
            txt + mom + " This is a hint, not a proof: a look-ahead through fundamentals or news would not show here.",
            ev, proc, priority="low", inputs=["signals", "prices"])


def run(pkg: Any, res: AuditResult) -> None:
    for fn, cid in ((check_alignment, "signal_forward_alignment"), (check_predictive_power, "signal_predictive_power"),
                    (check_quantile_spread, "signal_quantile_spread"), (check_turnover, "signal_turnover"),
                    (check_lookahead_hint, "signal_lookahead_hint")):
        try:
            fn(pkg, res)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------- spec

_REQ = {"required": ["signals", "prices"], "optional": ["rules"]}

SPEC = UseCase(
    name=NAME,
    title="Alpha signal research",
    description="Validation of a predictive score before it becomes a strategy: forward-return alignment strictly "
                "after the decision, per-date rank IC with Newey-West t-stats and the decay across horizons, quantile "
                "spreads and their monotonicity, signal persistence and implied turnover, and a look-ahead hint from "
                "the IC with the contemporaneous return.",
    audience="quant researchers and factor teams",
    detect_files=["signals"],
    requirements={c: dict(_REQ) for c in ALL},
    references={
        "qhs07": "Qian, E., Hua, R. and Sorensen, E. (2007). Quantitative Equity Portfolio Management: Modern "
                 "Techniques and Applications. Chapman and Hall/CRC.",
        "nw87": "Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and "
                "Autocorrelation Consistent Covariance Matrix. Econometrica 55(3), 703-708.",
    },
    catalog={
        "signal_forward_alignment": {
            "title": "Forward-return alignment of the signal",
            "what": "Builds the forward returns of every (decision date, ticker): entry = close of the first session at "
                    "or after the decision plus signal_lag_sessions (default 1), exit = entry + h sessions for each "
                    "horizon in signal_horizons. CONFIRMED_ERROR when lag 0 is declared and decisions fall on days that "
                    "are not sessions (the entry close was not yet known); NEEDS_REVIEW when more than 20% of the rows "
                    "have no forward price at the primary horizon; PASS when every row aligns with lag >= 1; INFO otherwise.",
            "why": "An IC computed on a return that starts at or before the decision measures the timestamp, not the "
                   "forecast; a thin coverage biases every statistic below.",
            "fix": "Declare signal_lag_sessions >= 1 (or date decisions after the close) and provide prices for every "
                   "signalled ticker up to the longest horizon.",
            "allows": "Stating on which returns the IC and spreads were computed.",
            "does_not_allow": "Detecting look-ahead inside the signal's own inputs (see signal_lookahead_hint).",
            "refs": ["lopez18", "gk00"],
        },
        "signal_predictive_power": {
            "title": "Predictive power of the signal (rank IC)",
            "what": "Per-date Spearman IC between the signal and the forward return at each horizon; mean, sd, hit rate "
                    "and Newey-West t-stat (Bartlett, ceil(h / spacing) - 1 lags). NEEDS_REVIEW when |t| < "
                    "signal_ic_t_review (2.0) at the primary horizon or the sign of the mean IC flips across horizons; "
                    "INFO otherwise (never PASS); NOT_EXECUTABLE with fewer than signal_min_periods (24) dates of "
                    "cross-section >= signal_min_cross_section (10). Thin cross-sections fall back to a time-series rank "
                    "correlation per ticker, flagged as such. The 3.0 hurdle of Harvey, Liu and Zhu is quoted as INFO.",
            "why": "The IC is the unit of alpha: without a significant and stable IC there is nothing to build a "
                   "strategy on, and a sign that depends on the horizon is the signature of noise.",
            "fix": "Check alignment and universe, report the decay profile and the number of signals tried, test out of "
                   "sample.",
            "allows": "Whether the ranking predicts forward returns in this sample, and at which horizon.",
            "does_not_allow": "Skill: an IC is before costs, turnover and selection among the signals tried.",
            "refs": ["gk00", "qhs07", "nw87", "hlz16", "dsr"],
        },
        "signal_quantile_spread": {
            "title": "Quantile portfolios and top-minus-bottom spread",
            "what": "Each date the signal is sorted into signal_quantiles (5) equal-sized buckets; mean forward return per "
                    "bucket at the primary horizon, top-minus-bottom spread with Newey-West t-stat, monotonicity "
                    "(Spearman between bucket rank and mean return) and the share of the spread from the long leg. "
                    "NEEDS_REVIEW when the spread t-stat < 2, monotonicity < 0.6, or the long leg contributes less than "
                    "25% of the spread while rules.yaml declares short_selling: false; INFO otherwise.",
            "why": "A long-only book captures the long leg only; a spread that lives in the bottom bucket, or that is not "
                   "monotonic, is not the alpha the IC suggests.",
            "fix": "Report the per-bucket table; design the strategy on the leg it can actually hold.",
            "allows": "Where in the ranking the return difference sits.",
            "does_not_allow": "Capturability after costs and constraints.",
            "refs": ["qhs07", "gk00"],
        },
        "signal_turnover": {
            "title": "Signal persistence and implied turnover",
            "what": "Spearman autocorrelation of the signal between decision dates (lag profile), one-way turnover of the "
                    "top bucket and the half-life fitted on the profile. NEEDS_REVIEW when the lag-1 autocorrelation is "
                    "below signal_turnover_review (0.5) and the primary horizon is longer than the spacing between "
                    "decision dates, or when the half-life in sessions is shorter than the declared rebalance frequency "
                    "(rules.yaml rebalance.frequency); INFO otherwise.",
            "why": "A signal that is re-drawn faster than the horizon it is evaluated on, or than the book can be "
                   "rebalanced, cannot deliver its IC after costs (fundamental law: breadth is paid in turnover).",
            "fix": "Smooth the signal, shorten the horizon or the rebalance, and cost the implied turnover.",
            "allows": "How much trading the signal implies per decision date.",
            "does_not_allow": "The actual cost, which depends on sizes and liquidity.",
            "refs": ["gk00", "qhs07"],
        },
        "signal_lookahead_hint": {
            "title": "Look-ahead hint: IC with the contemporaneous return",
            "what": "Per-date IC of the signal with the decision session's own return (h = 0), with the previous session's "
                    "return (h = -1) and with the aligned forward return (h = 1). NEEDS_REVIEW when |IC(h=0)| is "
                    "significant (|t| >= signal_ic_t_review) and more than 3 times |IC(h=1)|: the signal is more related "
                    "to the contemporaneous return than to the future one. A significant IC with h = -1 is reported as "
                    "momentum / reversal content (legitimate when intended).",
            "why": "A score that uses the close of its own decision session looks spectacular at h = 0 and vanishes at "
                   "h = 1; that is the most common timestamp error in signal research.",
            "fix": "Trace how decision_time is set and which prices enter the signal; recompute with data strictly "
                   "before the decision.",
            "allows": "Flagging a 'too good to be true' contemporaneous relation.",
            "does_not_allow": "Proving look-ahead: a hint, not evidence; look-ahead through fundamentals or text does not "
                              "show here.",
            "refs": ["lopez18", "dsr"],
        },
    },
    conventions={
        "signal_horizons": list(DEFAULT_HORIZONS),
        "signal_quantiles": 5,
        "signal_min_cross_section": 10,
        "signal_min_periods": 24,
        "signal_ic_t_review": 2.0,
        "signal_turnover_review": 0.5,
        "signal_lag_sessions": 1,
    },
    profiles={
        "signal_research": {
            "description": "Alpha signal research: cross-sectional IC, quantile spreads, turnover",
            "conventions": {},
        },
    },
    run=run,
)
register(SPEC)
