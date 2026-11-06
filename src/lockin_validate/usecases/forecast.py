"""Use case ``forecast``: validation of point forecasts of a financial or economic series.

Input: ``forecasts.csv`` with one row per (model, series, origin_date, target_date): the forecast made at the origin
for the target period and the realised value. Several models and several series may share the file. The checks
answer the questions a reviewer asks of a forecasting track record:

  forecast_origin_integrity  are the forecasts really made before their target, is the naive benchmark built only
                             from values published at the origin, are there contradictory duplicates, are horizons
                             declared when they are mixed
  forecast_vs_naive          does the model beat a naive benchmark (random walk, historical mean or zero): RMSE, MAE,
                             Theil's U and the Diebold-Mariano test with the Harvey-Leybourne-Newbold correction
  forecast_bias              Mincer-Zarnowitz regression (a = 0, b = 1 jointly, HAC) and the mean error
  forecast_directional       Pesaran-Timmermann test of directional accuracy
  forecast_error_dynamics    autocorrelation of the h-step errors beyond lag h-1 and a rolling one-year RMSE
  forecast_multiple_models   reality-check caution when the best of several models is reported

Horizon convention: the ``horizon`` column is in periods of the series (1 = one step ahead). When it is absent the
horizon is computed as target_date - origin_date in days and converted to steps with the median spacing of the
series' target dates. The Newey-West bandwidth of the DM, Mincer-Zarnowitz and mean-error variances is h - 1 lags
(Bartlett weights), the autocorrelation test starts at lag h.

Naive benchmark (conventions.forecast_naive): ``random_walk`` = the last actual of the series whose target_date is
<= origin_date (and, when ``actual_available_from`` exists, published at the origin); ``mean`` = the expanding mean
of the actuals known at the origin (Goyal and Welch 2008); ``zero`` = 0 (the right benchmark for return forecasts).
A ``naive`` column, when supplied, is used as given and contrasted with the publication-aware random walk.

No scipy / statsmodels: the Student t and chi-square tails are computed here (regularised incomplete beta; the
chi-square with 2 degrees of freedom has the closed form exp(-W / 2)).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from ..stats import autocorrelations, expected_max_sharpe, ljung_box
from . import UseCase, register

NAME = "forecast"
TABLE = "forecasts"
_N = NormalDist()
NAIVE_KINDS = ("random_walk", "mean", "zero")
LB_EXTRA_LAGS = 10  # Ljung-Box window: lags h .. h + 10
REGIME_RATIO = 2.0  # worst rolling RMSE / best rolling RMSE that is reported as regime dependence
MIXED_HORIZON_RATIO = 1.5  # max / min of the computed horizons (days) that counts as mixed horizons


# ---------------------------------------------------------------------------- small distribution helpers

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the regularised incomplete beta (modified Lentz)."""
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
        c = 1.0 + aa / (c if abs(c) > tiny else tiny)
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / (c if abs(c) > tiny else tiny)
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(lbeta)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    """CDF of the Student t distribution with ``df`` degrees of freedom."""
    if not math.isfinite(t):
        return 1.0 if t > 0 else 0.0
    if df <= 0:
        return float("nan")
    if df > 1e6:
        return _N.cdf(t)
    x = df / (df + t * t)
    tail = 0.5 * betainc(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def student_t_pvalue(t: float, df: float) -> float:
    """Two-sided p-value."""
    return 2.0 * (1.0 - student_t_cdf(abs(t), df))


def chi2_2_pvalue(w: float) -> float:
    """Upper tail of a chi-square with 2 degrees of freedom: exp(-w / 2)."""
    return math.exp(-w / 2.0) if math.isfinite(w) and w >= 0 else float("nan")


def normal_sf(z: float) -> float:
    return 1.0 - _N.cdf(z)


# ---------------------------------------------------------------------------- statistics

def newey_west_lrv(x: np.ndarray, lags: int) -> float:
    """Long-run variance of a scalar series with Bartlett weights and ``lags`` lags (Newey and West 1987).

    gamma_k = (1 / T) sum (x_t - m)(x_{t-k} - m); LRV = gamma_0 + 2 sum_{k=1}^{L} (1 - k / (L + 1)) gamma_k.
    With lags = 0 it is the population variance (ddof = 0).
    """
    a = np.asarray(x, dtype=float)
    T = a.size
    if T < 2:
        return float("nan")
    d = a - a.mean()
    g0 = float((d * d).sum() / T)
    s = g0
    L = max(0, min(int(lags), T - 1))
    for k in range(1, L + 1):
        gk = float((d[k:] * d[:-k]).sum() / T)
        s += 2.0 * (1.0 - k / (L + 1.0)) * gk
    return max(s, 1e-18)


def diebold_mariano(e_model: np.ndarray, e_naive: np.ndarray, h: int, loss: str = "squared") -> dict[str, float]:
    """Diebold-Mariano (1995) test of equal predictive accuracy with the Harvey-Leybourne-Newbold (1997) correction.

    d_t = L(e_model) - L(e_naive) (negative = the model is better). DM = mean(d) / sqrt(LRV(d) / T), LRV with
    Bartlett weights and h - 1 lags. HLN: DM* = DM x sqrt((T + 1 - 2h + h(h - 1) / T) / T), compared with a
    Student t with T - 1 degrees of freedom. One-sided p-value for "the model is better" (d < 0) and two-sided.
    """
    em = np.asarray(e_model, dtype=float)
    en = np.asarray(e_naive, dtype=float)
    if loss == "absolute":
        d = np.abs(em) - np.abs(en)
    else:
        d = em ** 2 - en ** 2
    T = d.size
    h = max(1, int(h))
    dbar = float(d.mean())
    lrv = newey_west_lrv(d, h - 1)
    dm = dbar / math.sqrt(lrv / T)
    corr = (T + 1 - 2 * h + h * (h - 1) / T) / T
    dm_hln = dm * math.sqrt(corr) if corr > 0 else dm
    p_two = student_t_pvalue(dm_hln, T - 1)
    p_better = student_t_cdf(dm_hln, T - 1)  # P(t < DM*): small when the model is clearly better
    return {"mean_d": dbar, "dm": dm, "dm_hln": dm_hln, "p_two_sided": p_two, "p_model_better": p_better, "T": T}


def mincer_zarnowitz(actual: np.ndarray, forecast: np.ndarray, h: int) -> dict[str, float]:
    """OLS actual = a + b forecast + e; Wald test of (a, b) = (0, 1) with a Newey-West (h - 1 lags) covariance.

    V = (X'X)^-1 S (X'X)^-1, S = sum_k w_k sum_t x_t u_t u_{t-k} x_{t-k}' (+ transpose for k >= 1). The p-value
    uses the chi-square(2) closed form exp(-W / 2).
    """
    y = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    T = y.size
    X = np.column_stack([np.ones(T), f])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    u = y - X @ beta
    L = max(0, min(int(h) - 1, T - 1))
    xu = X * u[:, None]
    S = xu.T @ xu
    for k in range(1, L + 1):
        w = 1.0 - k / (L + 1.0)
        G = xu[k:].T @ xu[:-k]
        S += w * (G + G.T)
    xtx_inv = np.linalg.pinv(X.T @ X)
    V = xtx_inv @ S @ xtx_inv
    r = beta - np.array([0.0, 1.0])
    try:
        W = float(r @ np.linalg.solve(V, r))
    except np.linalg.LinAlgError:
        W = float(r @ np.linalg.pinv(V) @ r)
    se = np.sqrt(np.maximum(np.diag(V), 0))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((u * u).sum()) / ss_tot if ss_tot > 0 else float("nan")
    return {"a": float(beta[0]), "b": float(beta[1]), "se_a": float(se[0]), "se_b": float(se[1]), "wald": W,
            "p_value": chi2_2_pvalue(W), "r2": r2, "T": T}


def mean_error_test(e: np.ndarray, h: int) -> dict[str, float]:
    a = np.asarray(e, dtype=float)
    T = a.size
    me = float(a.mean())
    lrv = newey_west_lrv(a, max(0, int(h) - 1))
    t = me / math.sqrt(lrv / T)
    return {"mean_error": me, "t": t, "p_value": 2.0 * normal_sf(abs(t)), "T": T}


def pesaran_timmermann(actual_up: np.ndarray, forecast_up: np.ndarray) -> dict[str, float]:
    """Pesaran-Timmermann (1992) test of directional accuracy on two boolean arrays.

    P = hit ratio, Py = share of actual ups, Px = share of forecast ups, P* = Py Px + (1 - Py)(1 - Px).
    var(P) = P*(1 - P*) / n; var(P*) = (2Py - 1)^2 Px(1 - Px) / n + (2Px - 1)^2 Py(1 - Py) / n
    + 4 Py Px (1 - Py)(1 - Px) / n^2. PT = (P - P*) / sqrt(var(P) - var(P*)) ~ N(0, 1) under independence.
    """
    ay = np.asarray(actual_up, dtype=bool)
    fx = np.asarray(forecast_up, dtype=bool)
    n = ay.size
    py = float(ay.mean())
    px = float(fx.mean())
    hit = float((ay == fx).mean())
    p_star = py * px + (1 - py) * (1 - px)
    var_p = p_star * (1 - p_star) / n
    var_star = ((2 * py - 1) ** 2 * px * (1 - px) / n + (2 * px - 1) ** 2 * py * (1 - py) / n
                + 4 * py * px * (1 - py) * (1 - px) / n ** 2)
    den = var_p - var_star
    pt = (hit - p_star) / math.sqrt(den) if den > 1e-15 else float("nan")
    table = {"up_up": int((ay & fx).sum()), "up_down": int((ay & ~fx).sum()),
             "down_up": int((~ay & fx).sum()), "down_down": int((~ay & ~fx).sum())}
    return {"n": n, "hit_ratio": hit, "p_actual_up": py, "p_forecast_up": px, "p_independence": p_star,
            "pt": pt, "p_value": normal_sf(pt) if math.isfinite(pt) else float("nan"), **table}


def ljung_box_from(e: np.ndarray, lo: int, hi: int) -> dict[str, float]:
    """Portmanteau test of the autocorrelations over lags lo..hi under the null that the series is MA(lo - 1).

    lo = 1 is the Ljung-Box test (stats.ljung_box). For lo > 1 the plain Ljung-Box sum is badly oversized: under
    an MA(q) null (q = lo - 1) the sample autocorrelations r_k, k > q, have covariance (Bartlett 1946)
    cov(r_k, r_l) = (1 / T) sum_j rho_j rho_{j + l - k} over |j| <= q, not 1 / T and not independent. The statistic is
    Q = T r' Sigma^-1 r with r_k scaled by sqrt((T + 2) / (T - k)) as in Ljung-Box and Sigma built from the sample
    rho_1..rho_q; chi-square with K = hi - lo + 1 degrees of freedom (Wilson-Hilferty approximation). Monte Carlo
    size at 5% on true h-step AR(1) errors: 6% (h = 3), 2% (h = 12); the plain sum gives 41% and 55%.
    """
    a = np.asarray(e, dtype=float)
    a = a[np.isfinite(a)]
    T = a.size
    if lo <= 1:
        return ljung_box(a, hi)
    rho = autocorrelations(a, hi)
    ks = [k for k in range(lo, hi + 1) if k <= len(rho) and k < T]
    K = len(ks)
    if K == 0:
        return {"Q": float("nan"), "df": 0, "p_value": float("nan")}
    q = lo - 1
    full = {j: (1.0 if j == 0 else rho[abs(j) - 1]) for j in range(-q, q + 1)}
    sig = np.zeros((K, K))
    for i, k in enumerate(ks):
        for j, m in enumerate(ks):
            sig[i, j] = sum(full[x] * full.get(x + (m - k), 0.0) for x in range(-q, q + 1))
    r = np.array([rho[k - 1] * math.sqrt((T + 2) / (T - k)) for k in ks])
    try:
        Q = T * float(r @ np.linalg.solve(sig, r))
    except np.linalg.LinAlgError:
        Q = T * float(r @ np.linalg.pinv(sig) @ r)
    z = ((max(Q, 0.0) / K) ** (1 / 3) - (1 - 2 / (9 * K))) / math.sqrt(2 / (9 * K))
    return {"Q": float(Q), "df": K, "p_value": float(normal_sf(z))}


def expected_max_t(n: int) -> float:
    """E[max of n independent standard normal t-statistics] (Bailey and Lopez de Prado 2014 approximation)."""
    return expected_max_sharpe(1.0, int(n))


# ---------------------------------------------------------------------------- data preparation

def _conv_naive(pkg: Any) -> str:
    v = str(pkg.conv("forecast_naive", "random_walk") or "random_walk").strip().lower().replace("-", "_")
    return v if v in NAIVE_KINDS else "random_walk"


def _rules_forecast(pkg: Any) -> dict[str, Any]:
    r = (pkg.rules or {}).get("forecast")
    return r if isinstance(r, dict) else {}


class Prepared:
    """Work table of the module: one row per forecast with model, series, horizon in steps, naive and errors."""

    def __init__(self, pkg: Any):
        df = pkg.df(TABLE)
        if df is None:
            raise ValueError("no forecasts table")
        d = df.copy()
        for c in ("model", "series"):
            if c not in d.columns:
                d[c] = c
            d[c] = [str(x).strip() if x is not None and not (isinstance(x, float) and math.isnan(x)) else c
                    for x in d[c]]
        d = d.dropna(subset=["origin_date", "target_date", "forecast", "actual"]).copy()
        self.has_available = "actual_available_from" in d.columns and bool(d["actual_available_from"].notna().any())
        self.has_horizon = "horizon" in d.columns and bool(d["horizon"].notna().any())
        self.has_naive = "naive" in d.columns and bool(d["naive"].notna().any())
        d["days"] = (d["target_date"] - d["origin_date"]).dt.days.astype(float)
        # step of each series = median spacing of its distinct target dates (days)
        self.step_days: dict[str, float] = {}
        for s, g in d.groupby("series"):
            td = np.sort(g["target_date"].drop_duplicates().to_numpy())
            diffs = np.diff(td).astype("timedelta64[D]").astype(float) if td.size > 1 else np.array([])
            diffs = diffs[diffs > 0]
            self.step_days[s] = float(np.median(diffs)) if diffs.size else float("nan")
        if self.has_horizon:
            d["h"] = pd.to_numeric(d["horizon"], errors="coerce")
            d["h"] = [int(round(x)) if math.isfinite(x) and x > 0 else 1 for x in d["h"]]
        else:
            hs = []
            for s, days in zip(d["series"], d["days"]):
                st = self.step_days.get(s)
                hs.append(max(1, int(round(days / st))) if st and math.isfinite(st) and st > 0 and days > 0 else 1)
            d["h"] = hs
        d["naive_plain"], d["naive_aware"], d["naive_src_row"] = self._random_walk(d)
        d["naive_mean"] = self._expanding_mean(d)
        self.kind = _conv_naive(pkg)
        if self.has_naive:
            d["naive_used"] = pd.to_numeric(d["naive"], errors="coerce")
            self.naive_source = "the naive column of forecasts.csv"
        elif self.kind == "zero":
            d["naive_used"] = 0.0
            self.naive_source = "zero (conventions.forecast_naive = zero)"
        elif self.kind == "mean":
            d["naive_used"] = d["naive_mean"]
            self.naive_source = "expanding mean of the actuals known at the origin (conventions.forecast_naive = mean)"
        else:
            d["naive_used"] = d["naive_aware"]
            self.naive_source = ("last actual known at the origin" + (", publication-aware" if self.has_available else "")
                                 + " (conventions.forecast_naive = random_walk)")
        d["error"] = d["actual"] - d["forecast"]
        d["error_naive"] = d["actual"] - d["naive_used"]
        self.df = d.sort_values(["series", "model", "h", "target_date", "origin_date", "row"]).reset_index(drop=True)

    def _history(self, d: pd.DataFrame, s: str) -> pd.DataFrame:
        g = d[d["series"] == s][["target_date", "actual", "row"] + (["actual_available_from"] if self.has_available
                                                                     else [])]
        g = g.dropna(subset=["target_date", "actual"]).sort_values(["target_date", "row"]).drop_duplicates(
            "target_date", keep="first")
        return g

    def _random_walk(self, d: pd.DataFrame) -> tuple[list[float], list[float], list[Any]]:
        plain, aware, src = [], [], []
        hist = {s: self._history(d, s) for s in d["series"].unique()}
        for s, o in zip(d["series"], d["origin_date"]):
            g = hist[s]
            known = g[g["target_date"] <= o]
            if known.empty:
                plain.append(float("nan"))
                aware.append(float("nan"))
                src.append(None)
                continue
            last = known.iloc[-1]
            plain.append(float(last["actual"]))
            if self.has_available:
                pub = known[known["actual_available_from"].isna() | (known["actual_available_from"] <= o)]
                if pub.empty:
                    aware.append(float("nan"))
                    src.append(None)
                else:
                    aware.append(float(pub.iloc[-1]["actual"]))
                    src.append(int(pub.iloc[-1]["row"]))
            else:
                aware.append(float(last["actual"]))
                src.append(int(last["row"]))
        return plain, aware, src

    def _expanding_mean(self, d: pd.DataFrame) -> list[float]:
        out = []
        hist = {s: self._history(d, s) for s in d["series"].unique()}
        for s, o in zip(d["series"], d["origin_date"]):
            g = hist[s]
            known = g[g["target_date"] <= o]
            if self.has_available:
                known = known[known["actual_available_from"].isna() | (known["actual_available_from"] <= o)]
            out.append(float(known["actual"].mean()) if len(known) else float("nan"))
        return out

    def groups(self):
        """(model, series, h) -> frame with finite error and error_naive."""
        for key, g in self.df.groupby(["model", "series", "h"], sort=True):
            gg = g[np.isfinite(g["error"]) & np.isfinite(g["error_naive"])]
            yield key, gg

    def window_obs(self, series: str) -> int:
        st = self.step_days.get(series)
        if not st or not math.isfinite(st) or st <= 0:
            return 12
        return max(5, int(round(365.25 / st)))


def _prepare(pkg: Any, res: AuditResult, check: str, title: str) -> Prepared | None:
    miss = pkg.missing(check)
    if miss:
        missing_inputs(res, check, NAME, title, miss)
        return None
    try:
        p = Prepared(pkg)
    except Exception as e:  # odd data
        not_executable(res, check, NAME, title, f"forecasts.csv could not be prepared ({type(e).__name__}: {e})")
        return None
    if p.df.empty:
        not_executable(res, check, NAME, title, "forecasts.csv has no row with origin_date, target_date, forecast "
                                                 "and actual")
        return None
    return p


def _label(key: tuple) -> str:
    m, s, h = key
    return f"{m} / {s} / h={h}"


def _ev(r: pd.Series, **extra: Any) -> dict[str, Any]:
    d = {"row": int(r["row"]), "date": r["target_date"].date() if hasattr(r["target_date"], "date") else r["target_date"],
         "origin": r["origin_date"].date() if hasattr(r["origin_date"], "date") else r["origin_date"],
         "model": r["model"], "series": r["series"]}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------- checks

def check_origin_integrity(pkg: Any, res: AuditResult) -> None:
    cid, title = "forecast_origin_integrity", "Forecast origin integrity"
    p = _prepare(pkg, res, cid, title)
    if p is None:
        return
    d = p.df
    min_obs = int(pkg.conv("forecast_min_observations", 30))
    errors: list[tuple[str, list[dict]]] = []
    # 1. target before origin
    past = d[d["target_date"] < d["origin_date"]]
    if len(past):
        errors.append(("target_date before origin_date (the forecast is dated after the period it predicts)",
                       [_ev(r, target=r["target_date"].date()) for _, r in past.iterrows()]))
    # 2. publication dates
    if p.has_available:
        bad_pub = d[d["actual_available_from"].notna() & (d["actual_available_from"] < d["target_date"])]
        if len(bad_pub):
            errors.append(("actual_available_from before target_date (a value published before the period it "
                           "measures)", [_ev(r, available_from=r["actual_available_from"].date())
                                         for _, r in bad_pub.iterrows()]))
        if p.has_naive:
            cheat = d[np.isfinite(d["naive_used"]) & np.isfinite(d["naive_plain"])
                      & (np.abs(d["naive_used"] - d["naive_plain"]) <= 1e-12 * np.maximum(1, np.abs(d["naive_plain"])))
                      & ~(np.abs(d["naive_used"] - d["naive_aware"]) <= 1e-12 * np.maximum(1, np.abs(d["naive_aware"])))]
            if len(cheat):
                errors.append(("the supplied naive benchmark equals the last actual by target date although that "
                               "value was not yet published at the origin (actual_available_from > origin_date)",
                               [_ev(r, naive=float(r["naive_used"]), published_naive=float(r["naive_aware"]))
                                for _, r in cheat.iterrows()]))
    # 3. contradictory duplicates
    key = ["model", "series", "origin_date", "target_date"]
    dup = d[d.duplicated(key, keep=False)]
    if len(dup):
        contra = dup.groupby(key)["forecast"].nunique()
        contra = contra[contra > 1]
        if len(contra):
            rows = dup.set_index(key).loc[contra.index].reset_index()
            errors.append(("the same (model, series, origin, target) appears with different forecasts",
                           [_ev(r, forecast=float(r["forecast"])) for _, r in rows.iterrows()]))
    hist = d.groupby(["model", "h"]).size()
    horizon_ev = [{"model": m, "horizon_steps": int(h), "n": int(n)} for (m, h), n in hist.items()]
    proc = ("Rows with target_date < origin_date; actual_available_from < target_date; supplied naive equal to the "
            "last actual by target date but not to the last actual published at the origin; (model, series, origin, "
            "target) keys with more than one forecast. Horizon in steps = horizon column, else round((target - origin) "
            "/ median spacing of the series' target dates).")
    if errors:
        for msg, ev in errors:
            res.add(cid, NAME, CONFIRMED_ERROR, f"Forecast origin problem: {msg}",
                    f"{len(ev)} of {len(d)} rows. A forecast evaluated against information that was not available "
                    "at its origin overstates skill; contradictory duplicates make the score depend on file order.",
                    ev, proc, action="Fix the dates or rebuild the benchmark from values published at each origin; "
                                     "keep one forecast per key.", priority="high", inputs=[TABLE])
        return
    reviews: list[tuple[str, str, list[dict]]] = []
    revised = bool(_rules_forecast(pkg).get("revised_data")) or bool(pkg.conv("forecast_revised_data", False))
    if revised and not p.has_available:
        reviews.append(("the series is declared as revised data (rules.yaml forecast.revised_data) but "
                        "actual_available_from is absent",
                        "The actuals may be final vintages that were not known when the forecasts were made; the "
                        "naive benchmark and the directional reference use the last actual by target date (Croushore "
                        "and Stark 2001).", []))
    if not p.has_horizon:
        mixed = []
        for (m, s), g in d.groupby(["model", "series"]):
            days = g["days"][g["days"] > 0]
            if len(days) >= 2 and float(days.max()) / float(days.min()) > MIXED_HORIZON_RATIO:
                mixed.append({"model": m, "series": s, "min_days": float(days.min()), "max_days": float(days.max()),
                              "steps_used": sorted(int(x) for x in g["h"].unique())})
        if mixed:
            reviews.append(("horizons are mixed without a horizon column",
                            "target_date - origin_date varies by more than 1.5x within a model and series; the "
                            "horizon in steps was inferred from the spacing of the target dates and may be wrong.",
                            mixed))
    for msg, why, ev in reviews:
        res.add(cid, NAME, NEEDS_REVIEW, f"Forecast provenance to review: {msg}", why, ev, proc,
                action="Add actual_available_from (publication dates) and a horizon column in periods.",
                priority="medium", inputs=[TABLE, "rules"])
    short = [k for k, g in p.groups() if len(g) < min_obs]
    res.add(cid, NAME, INFO, "Horizon distribution per model",
            f"{len(d)} forecasts, {d['model'].nunique()} model(s), {d['series'].nunique()} series. Naive benchmark: "
            f"{p.naive_source}." + (f" {len(short)} (model, series, horizon) group(s) below "
                                    f"forecast_min_observations = {min_obs}." if short else ""),
            horizon_ev, proc, inputs=[TABLE])
    if not reviews:
        res.add(cid, NAME, PASS, "Forecast origins verified",
                f"All {len(d)} forecasts are dated before their target; "
                + ("publication dates are consistent and the naive benchmark uses only values published at the origin"
                   if p.has_available else "no publication dates were provided (not contrasted)")
                + "; no contradictory duplicates"
                + ("; horizon column present." if p.has_horizon else "; a single horizon per model and series."),
                horizon_ev[:5], proc, inputs=[TABLE])


def _vs_naive_groups(pkg: Any, p: Prepared, min_obs: int) -> tuple[list[dict], list[tuple]]:
    """One record per (model, series, h): scores and DM; also the short groups."""
    loss = str(pkg.conv("forecast_loss", "squared")).lower()
    out, short = [], []
    for key, g in p.groups():
        if len(g) < min_obs:
            short.append((key, len(g)))
            continue
        em = g["error"].to_numpy(dtype=float)
        en = g["error_naive"].to_numpy(dtype=float)
        rmse = float(np.sqrt((em ** 2).mean()))
        rmse_n = float(np.sqrt((en ** 2).mean()))
        dm = diebold_mariano(em, en, key[2], loss)
        out.append({"key": key, "model": key[0], "series": key[1], "horizon": int(key[2]), "n": len(g),
                    "rmse": rmse, "mae": float(np.abs(em).mean()), "rmse_naive": rmse_n,
                    "mae_naive": float(np.abs(en).mean()),
                    "theil_u": rmse / rmse_n if rmse_n > 0 else float("inf"), **dm, "rows": g})
    return out, short


def check_vs_naive(pkg: Any, res: AuditResult) -> None:
    cid, title = "forecast_vs_naive", "Forecast accuracy against the naive benchmark"
    p = _prepare(pkg, res, cid, title)
    if p is None:
        return
    min_obs = int(pkg.conv("forecast_min_observations", 30))
    alpha = float(pkg.conv("forecast_alpha", 0.05))
    loss = str(pkg.conv("forecast_loss", "squared")).lower()
    recs, short = _vs_naive_groups(pkg, p, min_obs)
    proc = (f"Per (model, series, horizon h): RMSE, MAE, Theil's U = RMSE / RMSE of the naive ({p.naive_source}); "
            f"Diebold-Mariano on d = {loss} loss(model) - {loss} loss(naive) with Newey-West (Bartlett, h - 1 lags) "
            "variance and the Harvey-Leybourne-Newbold small-sample correction, Student t(T - 1); one-sided p for "
            f"'model better'. Alpha = {alpha}.")
    if not recs:
        not_executable(res, cid, NAME, title, f"every (model, series, horizon) group has fewer than "
                                               f"forecast_min_observations = {min_obs} comparable forecasts "
                                               f"({', '.join(f'{_label(k)}: {n}' for k, n in short[:6])})")
        return
    res.metrics[cid] = [{k: v for k, v in r.items() if k not in ("rows", "key")} for r in recs]
    for r in recs:
        ev = [{"model": r["model"], "series": r["series"], "horizon": r["horizon"], "n": r["n"],
               "rmse": round(r["rmse"], 6), "mae": round(r["mae"], 6), "rmse_naive": round(r["rmse_naive"], 6),
               "theil_u": round(r["theil_u"], 4), "dm_hln": round(r["dm_hln"], 3),
               "p_model_better": round(r["p_model_better"], 4)}]
        g = r["rows"]
        worst = g.iloc[np.argsort(-np.abs(g["error"].to_numpy()))[:3]]
        ev += [_ev(x, error=round(float(x["error"]), 6), error_naive=round(float(x["error_naive"]), 6))
               for _, x in worst.iterrows()]
        beats_u = r["theil_u"] < 1
        beats_dm = r["p_model_better"] < alpha
        txt = (f"{_label(r['key'])}: RMSE {r['rmse']:.4g} vs naive {r['rmse_naive']:.4g} (Theil's U "
               f"{r['theil_u']:.3f}), MAE {r['mae']:.4g}, DM* {r['dm_hln']:.2f} (one-sided p {r['p_model_better']:.3f}), "
               f"n = {r['n']}.")
        if beats_u and beats_dm:
            res.add(cid, NAME, INFO, f"Beats the naive at the declared level: {_label(r['key'])}",
                    txt + f" The model beats the naive at alpha = {alpha}. Beating a naive is a judgement about the "
                          "benchmark chosen, not a verified property of the model.", ev, proc,
                    action="Confirm that the naive is the relevant benchmark for this series (random walk for levels, "
                           "zero or the historical mean for returns).", priority="low", inputs=[TABLE, "rules"])
        else:
            why = []
            if not beats_u:
                why.append(f"Theil's U {r['theil_u']:.3f} >= 1 (the naive is at least as accurate)")
            if not beats_dm:
                why.append(f"DM p {r['p_model_better']:.3f} >= alpha {alpha} (the difference is not significant)")
            res.add(cid, NAME, NEEDS_REVIEW, f"Does not beat the naive: {_label(r['key'])}",
                    txt + " " + "; ".join(why) + ".", ev, proc,
                    action="Report the naive alongside the model; a forecast that does not beat the random walk "
                           "or the historical mean adds no information for decisions.", priority="medium",
                    inputs=[TABLE, "rules"])
    if short:
        res.add(cid, NAME, INFO, f"{len(short)} group(s) below forecast_min_observations",
                ", ".join(f"{_label(k)}: {n}" for k, n in short[:10]), [], proc, inputs=[TABLE])


def check_bias(pkg: Any, res: AuditResult) -> None:
    cid, title = "forecast_bias", "Forecast bias (Mincer-Zarnowitz)"
    p = _prepare(pkg, res, cid, title)
    if p is None:
        return
    min_obs = int(pkg.conv("forecast_min_observations", 30))
    alpha = float(pkg.conv("forecast_bias_alpha", 0.05))
    proc = ("Per (model, series, h): OLS actual = a + b forecast + e; Wald test of (a, b) = (0, 1) with a Newey-West "
            "(Bartlett, h - 1 lags) covariance, p = exp(-W / 2) (chi-square with 2 df); mean error with its HAC "
            f"t-statistic. Review when the Wald p < {alpha} or |t(mean error)| > 2.")
    ran = 0
    for key, g in p.groups():
        g = g[np.isfinite(g["actual"]) & np.isfinite(g["forecast"])]
        if len(g) < min_obs:
            continue
        y = g["actual"].to_numpy(dtype=float)
        f = g["forecast"].to_numpy(dtype=float)
        if np.std(f) == 0:
            continue
        ran += 1
        mz = mincer_zarnowitz(y, f, key[2])
        me = mean_error_test(y - f, key[2])
        sign = "under-forecasts (actual above forecast on average)" if me["mean_error"] > 0 else \
            "over-forecasts (actual below forecast on average)"
        ev = [{"model": key[0], "series": key[1], "horizon": int(key[2]), "n": int(mz["T"]),
               "a": round(mz["a"], 6), "b": round(mz["b"], 4), "se_a": round(mz["se_a"], 6), "se_b": round(mz["se_b"], 4),
               "wald": round(mz["wald"], 3), "p_wald": round(mz["p_value"], 4), "r2": round(mz["r2"], 4),
               "mean_error": round(me["mean_error"], 6), "t_mean_error": round(me["t"], 3)}]
        res.metrics.setdefault(cid, []).append(dict(ev[0]))
        txt = (f"{_label(key)}: a = {mz['a']:.4g} (se {mz['se_a']:.3g}), b = {mz['b']:.3f} (se {mz['se_b']:.3f}), "
               f"Wald {mz['wald']:.2f} (p {mz['p_value']:.3f}), R2 {mz['r2']:.3f}; mean error {me['mean_error']:.4g} "
               f"(t {me['t']:.2f}); the model {sign}.")
        if mz["p_value"] < alpha or abs(me["t"]) > 2:
            res.add(cid, NAME, NEEDS_REVIEW, f"Systematic bias: {_label(key)}",
                    txt + " The forecasts are not unbiased and efficient in the Mincer-Zarnowitz sense; a linear "
                          "correction of the forecast would have improved it.", ev, proc,
                    action="Recalibrate the forecast (a + b forecast) on a separate sample and re-test; look for the "
                           "source of the systematic error.", priority="medium", inputs=[TABLE])
        else:
            res.add(cid, NAME, INFO, f"No systematic bias detected: {_label(key)}",
                    txt + f" The joint test does not reject (a, b) = (0, 1) at alpha = {alpha} and the mean error is "
                          "within 2 standard errors.", ev, proc, priority="low", inputs=[TABLE])
    if not ran:
        not_executable(res, cid, NAME, title, f"no (model, series, horizon) group with at least "
                                               f"forecast_min_observations = {min_obs} forecasts and a non-constant "
                                               "forecast")


def check_directional(pkg: Any, res: AuditResult) -> None:
    cid, title = "forecast_directional", "Directional accuracy (Pesaran-Timmermann)"
    p = _prepare(pkg, res, cid, title)
    if p is None:
        return
    min_obs = int(pkg.conv("forecast_min_observations", 30))
    alpha = float(pkg.conv("forecast_directional_alpha", 0.05))
    zero_ref = p.kind == "zero" and not p.has_naive
    ref_txt = "the sign of the value itself (return forecasts)" if zero_ref else \
        "the change relative to the last actual known at the origin"
    proc = (f"Per (model, series, h): direction = {ref_txt}; up = strictly positive. Hit ratio, Pesaran-Timmermann "
            "statistic PT = (P - P*) / sqrt(var(P) - var(P*)) with P* the hit ratio under independence, one-sided "
            f"normal p-value; alpha = {alpha}.")
    ran, degenerate = 0, []
    for key, g in p.groups():
        if zero_ref:
            ref = np.zeros(len(g))
            gg = g
        else:
            gg = g[np.isfinite(g["naive_aware"])]
            ref = gg["naive_aware"].to_numpy(dtype=float)
        if len(gg) < min_obs:
            continue
        a_up = gg["actual"].to_numpy(dtype=float) - ref > 0
        f_up = gg["forecast"].to_numpy(dtype=float) - ref > 0
        if a_up.all() or (~a_up).all():
            degenerate.append(f"{_label(key)}: every actual moves in the same direction")
            continue
        if f_up.all() or (~f_up).all():
            degenerate.append(f"{_label(key)}: every forecast points in the same direction")
            continue
        ran += 1
        pt = pesaran_timmermann(a_up, f_up)
        ev = [{"model": key[0], "series": key[1], "horizon": int(key[2]), **{k: (round(v, 4) if isinstance(v, float)
                                                                                 else v) for k, v in pt.items()}}]
        miss_rows = gg[a_up != f_up].head(3)
        ev += [_ev(x, forecast=float(x["forecast"]), actual=float(x["actual"])) for _, x in miss_rows.iterrows()]
        res.metrics.setdefault(cid, []).append(dict(ev[0]))
        txt = (f"{_label(key)}: hit ratio {pt['hit_ratio']:.1%} vs {pt['p_independence']:.1%} under independence, "
               f"PT {pt['pt']:.2f} (p {pt['p_value']:.3f}), n = {pt['n']}; confusion table up/up {pt['up_up']}, "
               f"up/down {pt['up_down']}, down/up {pt['down_up']}, down/down {pt['down_down']} (actual/forecast).")
        if not (pt["p_value"] < alpha):
            res.add(cid, NAME, NEEDS_REVIEW, f"Direction not better than chance: {_label(key)}",
                    txt + f" The hit ratio is not significantly above the independence benchmark at alpha = {alpha}.",
                    ev, proc, action="Do not use the forecast for directional decisions until the sign skill is "
                                     "established on more data.", priority="medium", inputs=[TABLE])
        else:
            res.add(cid, NAME, INFO, f"Directional skill at the declared level: {_label(key)}",
                    txt + f" Significant at alpha = {alpha}.", ev, proc, priority="low", inputs=[TABLE])
    if not ran:
        reason = ("; ".join(degenerate) + " (no variance to test)") if degenerate else \
            f"no (model, series, horizon) group with at least forecast_min_observations = {min_obs} forecasts"
        not_executable(res, cid, NAME, title, reason)
    elif degenerate:
        res.add(cid, NAME, INFO, f"{len(degenerate)} group(s) without directional variance", "; ".join(degenerate),
                [], proc, inputs=[TABLE])


def check_error_dynamics(pkg: Any, res: AuditResult) -> None:
    cid, title = "forecast_error_dynamics", "Forecast error dynamics"
    p = _prepare(pkg, res, cid, title)
    if p is None:
        return
    min_obs = int(pkg.conv("forecast_min_observations", 30))
    alpha = float(pkg.conv("forecast_alpha", 0.05))
    proc = (f"Per (model, series, h): portmanteau Q on the errors over lags h .. h + {LB_EXTRA_LAGS} (an optimal h-step "
            "forecast has errors that are at most MA(h - 1)): Ljung-Box for h = 1, for h > 1 Q = T r' Sigma^-1 r with "
            "the Bartlett covariance of the sample autocorrelations under the MA(h - 1) null; Wilson-Hilferty "
            "chi-square approximation; rolling RMSE "
            f"over one year of target dates (window = round(365 / median spacing)), worst / best ratio > {REGIME_RATIO:g} "
            "reported as regime dependence.")
    ran = 0
    for key, g in p.groups():
        g = g[np.isfinite(g["error"])]
        T = len(g)
        h = int(key[2])
        if T < min_obs or T <= h + 2:
            continue
        ran += 1
        e = g["error"].to_numpy(dtype=float)
        lb = ljung_box_from(e, h, min(h + LB_EXTRA_LAGS, T - 1))
        win = min(p.window_obs(key[1]), max(5, T // 2))
        roll = pd.Series(e ** 2).rolling(win).mean().to_numpy()
        roll = np.sqrt(roll)
        ok = np.isfinite(roll)
        reg_txt, reg_ev = "", []
        worst_ratio = float("nan")
        if ok.sum() >= 2:
            iw, ib = int(np.nanargmax(roll)), int(np.nanargmin(roll))
            dates = g["target_date"].to_numpy()
            worst_ratio = float(roll[iw] / roll[ib]) if roll[ib] > 0 else float("inf")
            reg_ev = [{"window": "worst", "end": pd.Timestamp(dates[iw]).date(), "rmse": round(float(roll[iw]), 6),
                       "row": int(g["row"].iloc[iw])},
                      {"window": "best", "end": pd.Timestamp(dates[ib]).date(), "rmse": round(float(roll[ib]), 6),
                       "row": int(g["row"].iloc[ib])}]
            reg_txt = (f" Rolling {win}-observation RMSE: worst {roll[iw]:.4g} (window ending "
                       f"{pd.Timestamp(dates[iw]).date()}), best {roll[ib]:.4g} (ending {pd.Timestamp(dates[ib]).date()}), "
                       f"ratio {worst_ratio:.2f}.")
        ev = [{"model": key[0], "series": key[1], "horizon": h, "n": T, "lags": f"{h}..{h + lb['df'] - 1}",
               "Q": round(lb["Q"], 3), "df": lb["df"], "p_value": round(lb["p_value"], 4),
               "rolling_window": win, "worst_best_rmse_ratio": round(worst_ratio, 3) if math.isfinite(worst_ratio) else None}]
        ev += reg_ev
        res.metrics.setdefault(cid, []).append(dict(ev[0]))
        txt = (f"{_label(key)}: {'Ljung-Box' if h == 1 else 'Bartlett-corrected portmanteau'} Q({lb['df']}) = "
               f"{lb['Q']:.2f} over lags {h}..{h + lb['df'] - 1}, "
               f"p {lb['p_value']:.3f}, n = {T}.")
        if lb["p_value"] < alpha:
            res.add(cid, NAME, NEEDS_REVIEW, f"Autocorrelated errors beyond lag h - 1: {_label(key)}",
                    txt + reg_txt + " The errors are predictable from their own past: information is left on the "
                                    "table (an optimal h-step forecast has errors that are at most MA(h - 1)).",
                    ev, proc, action="Model the error dynamics (add lagged errors or the omitted variable) and re-test "
                                     "out of sample.", priority="medium", inputs=[TABLE])
        elif math.isfinite(worst_ratio) and worst_ratio > REGIME_RATIO:
            res.add(cid, NAME, INFO, f"Regime-dependent accuracy: {_label(key)}",
                    txt + reg_txt + f" The worst one-year window has more than {REGIME_RATIO:g}x the RMSE of the best: "
                                    "the accuracy depends on the regime; the average score hides it.",
                    ev, proc, action="Report the accuracy per regime or per year, not only the full-sample average.",
                    priority="low", inputs=[TABLE])
        else:
            res.add(cid, NAME, INFO, f"No residual autocorrelation beyond lag h - 1: {_label(key)}",
                    txt + reg_txt, ev, proc, priority="low", inputs=[TABLE])
    if not ran:
        not_executable(res, cid, NAME, title, f"no (model, series, horizon) group with at least "
                                               f"forecast_min_observations = {min_obs} forecasts and more than h + 2 "
                                               "observations")


def check_multiple_models(pkg: Any, res: AuditResult) -> None:
    cid, title = "forecast_multiple_models", "Several models on the same series (reality check)"
    p = _prepare(pkg, res, cid, title)
    if p is None:
        return
    n_models_total = int(p.df["model"].nunique())
    if n_models_total < 2:
        not_executable(res, cid, NAME, title, "only one model in forecasts.csv (the reality check needs the set of "
                                               "models that were tried)")
        return
    min_obs = int(pkg.conv("forecast_min_observations", 30))
    recs, short = _vs_naive_groups(pkg, p, min_obs)
    proc = ("Per (series, h) with n >= 2 scored models: best model by RMSE; the best DM* statistic (sign flipped so "
            "that positive = better than the naive) compared with E[max of n standard normal t-statistics] = "
            "(1 - g) Z(1 - 1/n) + g Z(1 - 1/(n e)) (Bailey and Lopez de Prado 2014), the expected best t of n models "
            "with no skill; P(best of n noise t >= observed) = 1 - Phi(t)^n. Simplified White (2000) / Hansen (2005) "
            "argument: it ignores the correlation between the models' losses.")
    ran = 0
    by_sh: dict[tuple, list[dict]] = {}
    for r in recs:
        by_sh.setdefault((r["series"], r["horizon"]), []).append(r)
    for (s, h), rs in sorted(by_sh.items()):
        n = len(rs)
        if n < 2:
            continue
        ran += 1
        best_rmse = min(rs, key=lambda r: r["rmse"])
        best_dm = max(rs, key=lambda r: -r["dm_hln"])
        t_best = -best_dm["dm_hln"]
        e_max = expected_max_t(n)
        p_lucky = 1.0 - _N.cdf(t_best) ** n if math.isfinite(t_best) else float("nan")
        ev = [{"series": s, "horizon": int(h), "n_models": n, "best_by_rmse": best_rmse["model"],
               "best_rmse": round(best_rmse["rmse"], 6), "rmse_naive": round(best_rmse["rmse_naive"], 6),
               "best_dm_model": best_dm["model"], "best_t_vs_naive": round(t_best, 3),
               "expected_max_t_under_null": round(e_max, 3), "p_best_of_n_by_chance": round(p_lucky, 4)}]
        ev += [{"model": r["model"], "rmse": round(r["rmse"], 6), "theil_u": round(r["theil_u"], 4),
                "t_vs_naive": round(-r["dm_hln"], 3)} for r in sorted(rs, key=lambda r: r["rmse"])[:10]]
        res.metrics.setdefault(cid, []).append(dict(ev[0]))
        txt = (f"series {s}, h={h}: {n} models; best by RMSE {best_rmse['model']} (RMSE {best_rmse['rmse']:.4g} vs "
               f"naive {best_rmse['rmse_naive']:.4g}); best t against the naive {t_best:.2f} ({best_dm['model']}); "
               f"expected maximum of {n} skill-less t-statistics {e_max:.2f}; probability that the best of {n} noise "
               f"models reaches {t_best:.2f} by chance {p_lucky:.1%}.")
        if t_best < e_max:
            res.add(cid, NAME, NEEDS_REVIEW, f"Best of {n} models is within the luck of the draw: series {s}, h={h}",
                    txt + " The best model's advantage over the naive is below what the best of n skill-less models "
                          "would show on average: selecting the winner after the fact explains it.", ev, proc,
                    action="Pre-register one model, or evaluate the winner on a fresh sample; report the number of "
                           "models tried (White 2000, Hansen 2005).", priority="medium", inputs=[TABLE])
        else:
            res.add(cid, NAME, INFO, f"Best of {n} models exceeds the expected maximum under no skill: series {s}, h={h}",
                    txt + " The check ignores the correlation between models and is not a full bootstrap reality "
                          "check.", ev, proc, priority="low", inputs=[TABLE])
    if not ran:
        not_executable(res, cid, NAME, title, "no (series, horizon) with at least two models above "
                                               f"forecast_min_observations = {min_obs}"
                                               + (f" ({len(short)} short group(s))" if short else ""))


CHECK_FUNCS = ((check_origin_integrity, "forecast_origin_integrity"), (check_vs_naive, "forecast_vs_naive"),
               (check_bias, "forecast_bias"), (check_directional, "forecast_directional"),
               (check_error_dynamics, "forecast_error_dynamics"), (check_multiple_models, "forecast_multiple_models"))


def run(pkg: Any, res: AuditResult) -> None:
    for fn, cid in CHECK_FUNCS:
        try:
            fn(pkg, res)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------- spec

_REQ = {"required": [TABLE], "optional": ["rules(forecast)", "rules(conventions)"]}

SPEC = UseCase(
    name=NAME,
    title="Point forecasts of a financial or economic series",
    description="Validates a track record of point forecasts (returns, volatility, inflation, rates, FX, earnings, "
                "cash flows, demand): origin integrity and real-time information, accuracy against a naive benchmark "
                "(Diebold-Mariano), Mincer-Zarnowitz bias, Pesaran-Timmermann directional accuracy, error dynamics "
                "and a reality-check caution when several models are compared.",
    audience="economists, strategists, treasury and FP&A teams, time-series modellers",
    detect_files=[TABLE],
    files={TABLE: "forecasts.csv"},
    schema={TABLE: {"required": ["origin_date", "target_date", "forecast", "actual"],
                    "optional": ["model", "series", "horizon", "actual_available_from", "naive"]}},
    aliases={TABLE: {"origin_date": ["origin", "forecast_date", "issued", "as_of"],
                     "target_date": ["target", "date", "period"],
                     "forecast": ["prediction", "yhat", "fcst"],
                     "actual": ["realized", "realised", "y", "observed"],
                     "actual_available_from": ["available_from", "published", "release_date"]}},
    date_columns={TABLE: ["origin_date", "target_date", "actual_available_from"]},
    numeric_columns={TABLE: ["forecast", "actual", "horizon", "naive"]},
    requirements={cid: dict(_REQ) for _, cid in CHECK_FUNCS},
    catalog={
        "forecast_origin_integrity": {
            "title": "Forecast origin integrity",
            "what": "target_date before origin_date; publication dates before the period they measure; a supplied "
                    "naive benchmark built from values not yet published at the origin; contradictory duplicates; "
                    "mixed horizons without a horizon column; revised data without publication dates; horizon "
                    "distribution per model.",
            "why": "A forecast scored against information that did not exist at its origin, or against a final "
                   "vintage instead of the real-time value, overstates skill (Croushore and Stark 2001).",
            "fix": "Fix the dates; add actual_available_from and a horizon column; rebuild the naive from values "
                   "published at each origin; keep one forecast per key.",
            "allows": "That the forecasts and the benchmark respect the information available at each origin.",
            "does_not_allow": "Detecting revisions when no publication dates are provided.",
            "refs": ["croushore01", "diebold15"],
        },
        "forecast_vs_naive": {
            "title": "Forecast accuracy against the naive benchmark",
            "what": "RMSE, MAE, Theil's U and the Diebold-Mariano test (HLN correction, Newey-West h - 1 lags) of "
                    "each model against a random walk, the historical mean or zero, per model, series and horizon.",
            "why": "Many published forecasts do not beat the random walk or the historical mean (Meese and Rogoff, "
                   "Goyal and Welch); the naive is the minimum bar.",
            "fix": "Report the naive alongside the model and the DM p-value; choose the naive that fits the series.",
            "allows": "Whether the model beats the chosen naive at the declared level (a judgement, never PASS).",
            "does_not_allow": "That the model is useful for decisions, or the comparison with other naives.",
            "refs": ["dm95", "hln97", "theil66", "nw87", "gw08", "diebold15"],
        },
        "forecast_bias": {
            "title": "Forecast bias (Mincer-Zarnowitz)",
            "what": "Regression actual = a + b forecast; joint Wald test of (a, b) = (0, 1) with HAC covariance; mean "
                    "error with its HAC t-statistic and the sign of the bias.",
            "why": "A biased or inefficient forecast can be improved by a linear correction; systematic over- or "
                   "under-forecasting distorts the decisions that use it.",
            "fix": "Recalibrate on a separate sample and re-test; find the source of the systematic error.",
            "allows": "Systematic bias or inefficiency of the forecasts.",
            "does_not_allow": "Why the bias exists.",
            "refs": ["mz69", "nw87"],
        },
        "forecast_directional": {
            "title": "Directional accuracy (Pesaran-Timmermann)",
            "what": "Hit ratio of the sign of the forecast change against the sign of the actual change (relative to "
                    "the last known actual; the sign itself for return forecasts), the Pesaran-Timmermann statistic "
                    "and the confusion table.",
            "why": "A hit ratio above 50% means nothing when actuals mostly move one way; the PT test compares it "
                   "with the hit ratio expected under independence.",
            "fix": "Establish sign skill on more data before using the forecast for directional decisions.",
            "allows": "Whether the direction is predicted better than chance at the declared level.",
            "does_not_allow": "The size of the moves; a test when every actual moves the same way.",
            "refs": ["pt92"],
        },
        "forecast_error_dynamics": {
            "title": "Forecast error dynamics",
            "what": "Portmanteau test of the h-step errors over lags h .. h + 10 (an optimal h-step forecast has at most "
                    "MA(h - 1) errors): Ljung-Box at h = 1, with Bartlett's covariance of the autocorrelations under the "
                    "MA(h - 1) null for h > 1; and a rolling one-year RMSE with the worst and best windows.",
            "why": "Autocorrelated errors beyond lag h - 1 mean the forecast ignores information in its own past "
                    "errors; a worst window far above the best means the average accuracy hides regime dependence.",
            "fix": "Model the error dynamics; report the accuracy per regime or per year.",
            "allows": "Residual predictability of the errors and the time profile of the accuracy.",
            "does_not_allow": "Which variable is omitted.",
            "refs": ["lb", "bartlett46", "dm95", "diebold15"],
        },
        "forecast_multiple_models": {
            "title": "Several models on the same series (reality check)",
            "what": "Number of models per series and horizon, the best by RMSE, and the best DM statistic compared "
                    "with the expected maximum of n skill-less t-statistics (probability that the best of n noise "
                    "models reaches it by chance).",
            "why": "The best of many models beats the naive by chance with high probability; reporting only the "
                   "winner is data snooping (White 2000).",
            "fix": "Pre-register one model or evaluate the winner on a fresh sample; report the number tried.",
            "allows": "Whether the best model's advantage exceeds what selection alone would produce.",
            "does_not_allow": "A full bootstrap reality check (the correlation between models is ignored).",
            "refs": ["white00", "hansen05", "dsr"],
        },
    },
    references={
        "dm95": "Diebold, F. X. and Mariano, R. S. (1995). Comparing Predictive Accuracy. Journal of Business and "
                "Economic Statistics 13(3), 253-263.",
        "hln97": "Harvey, D., Leybourne, S. and Newbold, P. (1997). Testing the Equality of Prediction Mean Squared "
                 "Errors. International Journal of Forecasting 13(2), 281-291.",
        "mz69": "Mincer, J. and Zarnowitz, V. (1969). The Evaluation of Economic Forecasts. In Economic Forecasts and "
                "Expectations, NBER, 3-46.",
        "pt92": "Pesaran, M. H. and Timmermann, A. (1992). A Simple Nonparametric Test of Predictive Performance. "
                "Journal of Business and Economic Statistics 10(4), 461-465.",
        "theil66": "Theil, H. (1966). Applied Economic Forecasting. North-Holland.",
        "white00": "White, H. (2000). A Reality Check for Data Snooping. Econometrica 68(5), 1097-1126.",
        "hansen05": "Hansen, P. R. (2005). A Test for Superior Predictive Ability. Journal of Business and Economic "
                    "Statistics 23(4), 365-380.",
        "nw87": "Newey, W. K. and West, K. D. (1987). A Simple, Positive Semi-Definite, Heteroskedasticity and "
                "Autocorrelation Consistent Covariance Matrix. Econometrica 55(3), 703-708.",
        "diebold15": "Diebold, F. X. (2015). Comparing Predictive Accuracy, Twenty Years Later: A Personal Perspective "
                     "on the Use and Abuse of Diebold-Mariano Tests. Journal of Business and Economic Statistics "
                     "33(1), 1-9.",
        "croushore01": "Croushore, D. and Stark, T. (2001). A Real-Time Data Set for Macroeconomists. Journal of "
                       "Econometrics 105(1), 111-130.",
        "bartlett46": "Bartlett, M. S. (1946). On the Theoretical Specification and Sampling Properties of "
                      "Autocorrelated Time-Series. Supplement to the Journal of the Royal Statistical Society 8(1), "
                      "27-41.",
        "gw08": "Goyal, A. and Welch, I. (2008). A Comprehensive Look at the Empirical Performance of Equity Premium "
                "Prediction. Review of Financial Studies 21(4), 1455-1508.",
    },
    conventions={"forecast_alpha": 0.05, "forecast_min_observations": 30, "forecast_naive": "random_walk",
                 "forecast_loss": "squared", "forecast_bias_alpha": 0.05, "forecast_directional_alpha": 0.05,
                 "forecast_revised_data": False},
    profiles={
        "forecast_returns": {"description": "Return forecasts: the naive benchmark is zero and the direction is the "
                                            "sign of the forecast itself.",
                             "conventions": {"forecast_naive": "zero"}},
        "forecast_macro": {"description": "Macroeconomic forecasts (inflation, GDP, rates): random-walk naive and a "
                                          "caution that the actuals may be revised vintages (declare "
                                          "actual_available_from).",
                           "conventions": {"forecast_naive": "random_walk", "forecast_revised_data": True}},
    },
    run=run,
)
register(SPEC)
