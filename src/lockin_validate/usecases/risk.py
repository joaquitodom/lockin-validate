"""Use case ``risk``: backtesting of market-risk models (Value at Risk and Expected Shortfall).

Input table ``var_forecasts.csv``: one row per day with the realised P&L (``pnl``) and the forecasts made for that
day: ``var_<level>`` columns (``var_99``, ``var_975``, ``var_95``...) and optionally ``es_<level>``, ``model`` and
``portfolio``. The forecasts are compared with what happened:

  var_input_coherence   sign convention, quantile monotonicity, ES >= VaR, duplicates, gaps, frozen P&L
  var_coverage          Kupiec (1995) unconditional coverage (proportion of failures) per level
  var_independence      Christoffersen (1998) independence and conditional coverage, runs and clusters
  basel_traffic_light   Basel (1996) zones on the last 250 one-day 99% observations, with the capital add-on
  es_backtest           Acerbi and Szekely (2014) Z2 and the exceedance-residual test for the ES forecasts
  var_model_stability   exception rates per year / block (chi-square homogeneity) and reaction to volatility

Sign conventions. Internally every loss is a POSITIVE number: L_t = -pnl_t, V_t = VaR as a positive loss quantile
and an exception is L_t > V_t. The convention ``risk_var_sign`` says how the file is written: ``positive_loss``
(default: VaR 0.025 means a 2.5% loss) or ``negative_quantile`` (VaR -0.025 is the 1% quantile of the P&L). When the
data contradict the declared convention (most VaR values of the other sign) the module switches and says so in an
INFO finding. A ``loss`` column (alias of ``pnl``) is a loss, so its sign is inverted on reading and logged.

All test statistics are implemented here from the published formulas: chi-square tails with 1 and 2 degrees of
freedom have closed forms (p = erfc(sqrt(x / 2)) and p = exp(-x / 2)); the chi-square with more degrees of freedom
(block homogeneity) uses the regularised incomplete gamma function. No scipy, no network.
"""

from __future__ import annotations

import math
import re
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from . import UseCase, register

NAME = "risk"
TABLE = "var_forecasts"
POSITIVE_LOSS = "positive_loss"
NEGATIVE_QUANTILE = "negative_quantile"
TRAFFIC_ADDON = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.40, 6: 0.50, 7: 0.65, 8: 0.75, 9: 0.85}  # red: 1.00
BASEL_250 = {"green": range(0, 5), "yellow": range(5, 10)}  # red: 10 or more (Basel 1996, Table 1)
Z2_BOUND = -0.70  # approximate 5% critical value cited by Acerbi and Szekely for typical P&L distributions
ES_RATIO_MAX = 1.25
CLUSTER_DAYS = 5
MAX_GAP_SESSIONS = 5
MAX_FLAT_RUN = 5


# ----------------------------------------------------------------------------------------------- statistics

def chi2_sf(x: float, df: int) -> float:
    """Upper tail of the chi-square distribution. Closed forms for df 1 and 2, regularised gamma otherwise."""
    if not math.isfinite(x) or x <= 0:
        return 1.0
    if df == 1:
        return math.erfc(math.sqrt(x / 2.0))
    if df == 2:
        return math.exp(-x / 2.0)
    return _gammaincc(df / 2.0, x / 2.0)


def _gammaincc(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (series for x < a + 1, continued fraction otherwise)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        term = total = 1.0 / a
        ap = a
        for _ in range(500):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        return max(0.0, 1.0 - total * math.exp(-x + a * math.log(x) - gln))
    b = x + 1.0 - a
    c = 1.0 / 1e-300
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - gln) * h)


def _sentence(s: str) -> str:
    return s[:1].upper() + s[1:]


def _xlogy(x: float, y: float) -> float:
    return 0.0 if x == 0 else x * math.log(y)


def kupiec_lr(x: int, n: int, p: float) -> dict[str, float]:
    """Kupiec (1995) proportion-of-failures test: LR_uc ~ chi-square(1) under H0 (exception rate = p)."""
    if n <= 0:
        return {"lr": float("nan"), "p_value": float("nan")}
    pi = x / n
    ll0 = _xlogy(n - x, 1 - p) + _xlogy(x, p)
    ll1 = _xlogy(n - x, 1 - pi) + _xlogy(x, pi)
    lr = max(0.0, -2.0 * ll0 + 2.0 * ll1)
    return {"lr": lr, "p_value": chi2_sf(lr, 1)}


def christoffersen_ind(hits: np.ndarray) -> dict[str, float]:
    """Christoffersen (1998) independence test on the exception indicator (first-order Markov chain)."""
    h = np.asarray(hits, dtype=int)
    if h.size < 2:
        return {"lr": float("nan"), "p_value": float("nan"), "n00": 0, "n01": 0, "n10": 0, "n11": 0,
                "pi01": float("nan"), "pi11": float("nan")}
    a, b = h[:-1], h[1:]
    n00 = int(((a == 0) & (b == 0)).sum())
    n01 = int(((a == 0) & (b == 1)).sum())
    n10 = int(((a == 1) & (b == 0)).sum())
    n11 = int(((a == 1) & (b == 1)).sum())
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll0 = _xlogy(n00 + n10, 1 - pi) + _xlogy(n01 + n11, pi)
    ll1 = _xlogy(n00, 1 - pi01) + _xlogy(n01, pi01) + _xlogy(n10, 1 - pi11) + _xlogy(n11, pi11)
    lr = max(0.0, -2.0 * ll0 + 2.0 * ll1)
    return {"lr": lr, "p_value": chi2_sf(lr, 1), "n00": n00, "n01": n01, "n10": n10, "n11": n11,
            "pi01": pi01, "pi11": pi11}


def binom_logpmf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log1p(-p))


def binom_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(math.exp(binom_logpmf(i, n, p)) for i in range(k + 1)))


def binom_acceptance_region(n: int, p: float, alpha: float) -> tuple[int, int]:
    """Two-sided exact (equal-tail) region of the exception count under H0: [lo, hi] with at most alpha/2 in each
    tail. lo = smallest k with P(X < k) <= alpha/2 ... the largest such k; hi = smallest k with P(X > k) <= alpha/2."""
    lo = 0
    while lo < n and binom_cdf(lo, n, p) <= alpha / 2:
        lo += 1
    hi = n
    while hi > 0 and 1.0 - binom_cdf(hi - 1, n, p) <= alpha / 2:
        hi -= 1
    return lo, hi


def traffic_zone(k: int, window: int, p: float = 0.01) -> str:
    """Basel (1996) zone: for 250 days the published table (green 0-4, yellow 5-9, red 10+); for another window the
    cumulative binomial probability P(X <= k): green below 95%, yellow from 95% to 99.99%, red above."""
    if window == 250:
        if k in BASEL_250["green"]:
            return "green"
        return "yellow" if k in BASEL_250["yellow"] else "red"
    c = binom_cdf(k, window, p)
    if c < 0.95:
        return "green"
    return "yellow" if c < 0.9999 else "red"


def traffic_addon(k: int, window: int, p: float = 0.01) -> float:
    zone = traffic_zone(k, window, p)
    if zone == "green":
        return 0.0
    if zone == "red":
        return 1.0
    if window == 250:
        return TRAFFIC_ADDON[k]
    # other windows: the yellow add-on grows linearly with the position inside the yellow band (an approximation)
    lo = k
    while lo > 0 and traffic_zone(lo - 1, window, p) == "yellow":
        lo -= 1
    hi = k
    while traffic_zone(hi + 1, window, p) == "yellow":
        hi += 1
    frac = (k - lo) / max(1, hi - lo)
    return round(0.40 + frac * 0.45, 2)


def acerbi_szekely_z2(loss: np.ndarray, es: np.ndarray, hits: np.ndarray, p: float) -> float:
    """Z2 = 1 - sum_t L_t 1[exception_t] / (N p ES_t), losses positive. 0 under H0, negative when ES is too small."""
    n = loss.size
    if n == 0:
        return float("nan")
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(hits == 1, loss / es, 0.0)
    return float(1.0 - np.nansum(terms) / (n * p))


def longest_run(hits: np.ndarray) -> int:
    best = cur = 0
    for v in hits:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def exception_clusters(idx: np.ndarray, within: int = CLUSTER_DAYS) -> tuple[int, int]:
    """(number of clusters of exceptions closer than ``within`` observations, exceptions inside a cluster)."""
    if idx.size == 0:
        return 0, 0
    clusters = 0
    inside = 0
    start = 0
    for i in range(1, idx.size + 1):
        if i == idx.size or idx[i] - idx[i - 1] > within:
            size = i - start
            if size >= 2:
                clusters += 1
                inside += size
            start = i
    return clusters, inside


# ----------------------------------------------------------------------------------------------- data access

def parse_level(col: str, prefix: str) -> float | None:
    m = re.fullmatch(prefix + r"_?(\d+(?:\.\d+)?)", col)
    if not m:
        return None
    s = m.group(1)
    if "." in s:
        v = float(s)
        return v / 100 if v > 1 else v
    v = int(s) / (10 ** len(s))
    return v if 0.5 < v < 1 else None


class RiskData:
    """Normalised view of var_forecasts.csv: losses positive, VaR / ES positive, one row per date."""

    def __init__(self, pkg: Any):
        t = pkg.tables.get(TABLE)
        df = pkg.df(TABLE)
        if df is None:
            raise ValueError("var_forecasts not available")
        self.notes: list[str] = []
        self.renames = dict(t.renames) if t is not None else {}
        d = df.copy()
        d["pnl"] = pd.to_numeric(d["pnl"], errors="coerce")
        self.loss_column = self.renames.get("loss") == "pnl"
        if self.loss_column:
            d["pnl"] = -d["pnl"]
            self.notes.append("the file has a `loss` column: its sign was inverted to obtain the P&L")
        self.var_cols = {c: lv for c in d.columns if (lv := parse_level(c, "var")) is not None}
        self.es_cols = {c: lv for c in d.columns if (lv := parse_level(c, "es")) is not None}
        for c in list(self.var_cols) + list(self.es_cols):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        self.declared_sign = str(pkg.conv("risk_var_sign", POSITIVE_LOSS) or POSITIVE_LOSS).strip().lower()
        if self.declared_sign not in (POSITIVE_LOSS, NEGATIVE_QUANTILE):
            self.notes.append(f"unknown risk_var_sign {self.declared_sign!r}: positive_loss assumed")
            self.declared_sign = POSITIVE_LOSS
        vals = np.concatenate([d[c].to_numpy(dtype=float) for c in self.var_cols]) if self.var_cols else np.array([])
        vals = vals[np.isfinite(vals) & (vals != 0)]
        self.share_negative = float((vals < 0).mean()) if vals.size else float("nan")
        self.sign = self.declared_sign
        self.sign_switched = False
        if vals.size:
            if self.declared_sign == POSITIVE_LOSS and self.share_negative > 0.5:
                self.sign, self.sign_switched = NEGATIVE_QUANTILE, True
            elif self.declared_sign == NEGATIVE_QUANTILE and self.share_negative < 0.5:
                self.sign, self.sign_switched = POSITIVE_LOSS, True
        self.raw = d.dropna(subset=["date"]).sort_values(["date", "row"]).reset_index(drop=True)
        dup = self.raw["date"].duplicated(keep=False)
        self.duplicate_rows = [int(r) for r in self.raw.loc[dup, "row"]]
        self.duplicate_dates = sorted({x.date() for x in self.raw.loc[dup, "date"]})
        w = self.raw.drop_duplicates("date", keep="first").dropna(subset=["pnl"]).reset_index(drop=True)
        self.n_dropped_pnl = int(len(self.raw.drop_duplicates("date")) - len(w))
        self.work = w
        self.dates = np.array([x.date() for x in w["date"]])
        self.rows = w["row"].to_numpy(dtype=int)
        self.loss = -w["pnl"].to_numpy(dtype=float)
        flip = -1.0 if self.sign == NEGATIVE_QUANTILE else 1.0
        self.var = {lv: flip * w[c].to_numpy(dtype=float) for c, lv in self.var_cols.items()}
        self.es = {lv: flip * w[c].to_numpy(dtype=float) for c, lv in self.es_cols.items()}
        self.var_name = {lv: c for c, lv in self.var_cols.items()}
        self.es_name = {lv: c for c, lv in self.es_cols.items()}
        rk = (pkg.rules or {}).get("risk") if isinstance((pkg.rules or {}).get("risk"), dict) else {}
        self.rules = rk or {}
        self.horizon = self.rules.get("horizon_days", 1)
        self.n = int(len(w))

    @property
    def levels(self) -> list[float]:
        return sorted(self.var)

    def hits(self, level: float) -> tuple[np.ndarray, np.ndarray]:
        """(mask of usable days, exception indicator 0/1 on those days) for one level."""
        v = self.var[level]
        ok = np.isfinite(v) & np.isfinite(self.loss)
        return ok, (self.loss[ok] > v[ok]).astype(int)

    def level_label(self, level: float) -> str:
        return f"{level * 100:g}%"

    def evidence_rows(self, mask: np.ndarray, level: float | None = None, limit: int = 20) -> list[dict[str, Any]]:
        idx = np.flatnonzero(mask)[:limit]
        out = []
        for i in idx:
            e: dict[str, Any] = {"row": int(self.rows[i]), "date": self.dates[i], "pnl": round(float(-self.loss[i]), 6)}
            if level is not None:
                e[self.var_name[level]] = round(float(self.var[level][i]), 6)
            out.append(e)
        return out


def _load(pkg: Any, res: AuditResult, check: str, title: str) -> RiskData | None:
    miss = pkg.missing(check)
    if miss:
        missing_inputs(res, check, NAME, title, miss)
        return None
    data = RiskData(pkg)
    if not data.var_cols:
        not_executable(res, check, NAME, title, "var_forecasts.csv has no `var_<level>` column (e.g. var_99)",
                       "Add one column per VaR level named var_99, var_975 or var_95.")
        return None
    if data.n == 0:
        not_executable(res, check, NAME, title, "var_forecasts.csv has no row with a date and a numeric pnl")
        return None
    return data


def _sign_text(d: RiskData) -> str:
    if d.sign == POSITIVE_LOSS:
        return "VaR written as a positive loss (exception when -pnl > VaR)"
    return "VaR written as a negative P&L quantile (exception when pnl < VaR)"


def _min_obs(pkg: Any) -> int:
    return int(pkg.conv("risk_min_observations", 250))


# ----------------------------------------------------------------------------------------------- checks

def check_input_coherence(pkg: Any, res: AuditResult) -> None:
    cid, title = "var_input_coherence", "VaR input coherence"
    d = _load(pkg, res, cid, title)
    if d is None:
        return
    inputs = [TABLE, "rules"]
    levels_txt = ", ".join(f"{d.var_name[lv]} ({d.level_label(lv)})" for lv in d.levels)
    es_txt = (", ".join(f"{d.es_name[lv]} ({d.level_label(lv)})" for lv in sorted(d.es)) or "none")
    sign_detail = (f"Declared convention risk_var_sign = {d.declared_sign}; used: {d.sign} ({_sign_text(d)}). "
                   f"{d.share_negative:.0%} of the non-zero VaR values are negative. Horizon: {d.horizon} day(s)"
                   f"{' (rules.yaml risk.horizon_days)' if 'horizon_days' in d.rules else ' (default)'}. "
                   f"VaR columns: {levels_txt}. ES columns: {es_txt}. {d.n} usable days from {d.dates[0]} to "
                   f"{d.dates[-1]}." + (" " + "; ".join(d.notes) + "." if d.notes else ""))
    if d.sign_switched:
        res.add(cid, NAME, INFO, f"Sign convention looks inverted: VaR treated as {d.sign}",
                "The declared convention was not applied because most VaR values have the opposite sign. " + sign_detail,
                [{"declared": d.declared_sign, "used": d.sign, "share_negative_var": round(d.share_negative, 4)}],
                "Share of negative values among the finite, non-zero VaR entries of every var_<level> column; "
                "above 50% means negative_quantile, below means positive_loss.",
                action="Declare conventions.risk_var_sign in rules.yaml so the sign is not inferred.", inputs=inputs)
    else:
        res.add(cid, NAME, INFO, f"Sign convention: {d.sign}; horizon {d.horizon} day(s)", sign_detail,
                [{"declared": d.declared_sign, "used": d.sign, "share_negative_var": round(d.share_negative, 4),
                  "horizon_days": d.horizon}],
                "Convention read from rules.yaml conventions.risk_var_sign (or the default) and contrasted with the "
                "sign of the VaR values.", inputs=inputs)
    errors: list[tuple[str, str, list[dict[str, Any]]]] = []
    # 1. non-finite or zero VaR
    for lv in d.levels:
        v = d.raw[d.var_name[lv]].to_numpy(dtype=float)
        bad = ~np.isfinite(v) | (v == 0)
        share = float(bad.mean()) if v.size else 0.0
        if share > 0.01:
            rows = d.raw.loc[bad, ["row", "date"]].head(20)
            errors.append((f"{d.var_name[lv]} is missing or zero on {share:.1%} of the days (> 1%)",
                           f"{int(bad.sum())} of {v.size} rows have a non-numeric, empty or zero {d.var_name[lv]}.",
                           [{"row": int(r.row), "date": r.date.date(), "column": d.var_name[lv]} for r in rows.itertuples()]))
    # 2. quantile monotonicity: a higher confidence level must have a VaR at least as large (positive losses)
    lv_sorted = d.levels
    for lo, hi in zip(lv_sorted[:-1], lv_sorted[1:]):
        a, b = d.var[lo], d.var[hi]
        bad = np.isfinite(a) & np.isfinite(b) & (a > b + 1e-12)
        if bad.any():
            ev = [{"row": int(d.rows[i]), "date": d.dates[i], d.var_name[lo]: round(float(a[i]), 6),
                   d.var_name[hi]: round(float(b[i]), 6)} for i in np.flatnonzero(bad)[:20]]
            errors.append((f"{d.var_name[lo]} > {d.var_name[hi]} on {int(bad.sum())} day(s): quantile monotonicity violated",
                           f"The {d.level_label(lo)} VaR exceeds the {d.level_label(hi)} VaR on {int(bad.sum())} of "
                           f"{int(np.isfinite(a).sum())} days; a loss quantile cannot decrease when the confidence level rises.",
                           ev))
    # 3. ES >= VaR for the same level
    for lv, e in d.es.items():
        if lv not in d.var:
            continue
        v = d.var[lv]
        bad = np.isfinite(e) & np.isfinite(v) & (e < v - 1e-12)
        if bad.any():
            ev = [{"row": int(d.rows[i]), "date": d.dates[i], d.var_name[lv]: round(float(v[i]), 6),
                   d.es_name[lv]: round(float(e[i]), 6)} for i in np.flatnonzero(bad)[:20]]
            errors.append((f"{d.es_name[lv]} < {d.var_name[lv]} on {int(bad.sum())} day(s)",
                           f"The expected shortfall is the mean loss beyond the VaR, so it is at least the VaR; "
                           f"{int(bad.sum())} days violate it.", ev))
    # 4. duplicated dates
    if d.duplicate_rows:
        errors.append((f"{len(d.duplicate_dates)} duplicated date(s) in var_forecasts.csv",
                       f"{len(d.duplicate_rows)} rows share a date with another row; which forecast counts depends on "
                       "file order. The first row of each date was used downstream.",
                       [{"row": r} for r in d.duplicate_rows[:20]]))
    proc = ("Per var_<level> column: share of non-finite or zero values; for consecutive levels, days where the lower "
            "level's VaR exceeds the higher level's (losses positive); es_<level> compared with var_<level> on each "
            "day; dates counted; gaps measured in sessions of the declared calendar (weekdays when undeclared); runs "
            "of identical consecutive pnl values.")
    for t, det, ev in errors:
        res.add(cid, NAME, CONFIRMED_ERROR, t, det, ev, proc, action="Fix the forecast file before backtesting: a "
                "VaR series that crosses its own quantiles or lacks values cannot be interpreted.", priority="high",
                inputs=inputs)
    # review items: gaps and frozen P&L
    reviews: list[tuple[str, str, list[dict[str, Any]]]] = []
    gaps = _gaps(pkg, d)
    if gaps:
        reviews.append((f"{len(gaps)} gap(s) longer than {MAX_GAP_SESSIONS} sessions in the realised P&L",
                        f"Largest gap: {gaps[0]['missing_sessions']} sessions before {gaps[0]['date']}. Days without a "
                        "P&L are days the model is not tested on; a backtest that skips the worst days is not a backtest.",
                        gaps[:20]))
    flat = _flat_runs(d)
    if flat:
        reviews.append((f"P&L identical on more than {MAX_FLAT_RUN} consecutive days ({len(flat)} run(s))",
                        f"Longest run: {flat[0]['length']} days ending {flat[0]['date']} with pnl {flat[0]['pnl']}. "
                        "A frozen P&L usually means a stale valuation or a filled-forward series.", flat[:20]))
    for t, det, ev in reviews:
        res.add(cid, NAME, NEEDS_REVIEW, t, det, ev, proc,
                action="Confirm the source of the realised P&L (holidays, suspensions, filled values).",
                inputs=inputs)
    if not errors and not reviews:
        res.add(cid, NAME, PASS, "VaR forecasts are coherent",
                f"{d.n} days, {len(d.levels)} VaR level(s), {len(d.es)} ES column(s): no missing or zero VaR beyond "
                "1%, quantiles ordered, ES >= VaR, no duplicated dates, no gap longer than "
                f"{MAX_GAP_SESSIONS} sessions, no frozen P&L.", [], proc, inputs=inputs)


def _gaps(pkg: Any, d: RiskData) -> list[dict[str, Any]]:
    try:
        cal = pkg.calendar()
    except Exception:
        cal = None
    out = []
    for i in range(1, d.n):
        a, b = d.dates[i - 1], d.dates[i]
        if (b - a).days <= MAX_GAP_SESSIONS:
            continue
        if cal is not None and cal.full_calendar:
            missing = len(cal.sessions(a + timedelta(days=1), b - timedelta(days=1)))
        elif cal is not None and cal.name == "none":
            missing = (b - a).days - 1
        else:
            missing = int(np.busday_count(a + timedelta(days=1), b))
        if missing > MAX_GAP_SESSIONS:
            out.append({"row": int(d.rows[i]), "date": b, "previous_date": a, "missing_sessions": int(missing)})
    return sorted(out, key=lambda e: -e["missing_sessions"])


def _flat_runs(d: RiskData) -> list[dict[str, Any]]:
    out = []
    run = 1
    for i in range(1, d.n):
        if d.loss[i] == d.loss[i - 1]:
            run += 1
        else:
            if run > MAX_FLAT_RUN:
                out.append({"row": int(d.rows[i - 1]), "date": d.dates[i - 1], "length": run,
                            "pnl": round(float(-d.loss[i - 1]), 6)})
            run = 1
    if run > MAX_FLAT_RUN:
        out.append({"row": int(d.rows[d.n - 1]), "date": d.dates[d.n - 1], "length": run,
                    "pnl": round(float(-d.loss[d.n - 1]), 6)})
    return sorted(out, key=lambda e: -e["length"])


def check_coverage(pkg: Any, res: AuditResult) -> None:
    cid, title = "var_coverage", "VaR unconditional coverage (Kupiec)"
    d = _load(pkg, res, cid, title)
    if d is None:
        return
    alpha = float(pkg.conv("risk_kupiec_alpha", 0.05))
    min_obs = _min_obs(pkg)
    inputs = [TABLE, "rules"]
    metrics: dict[str, Any] = {}
    for lv in d.levels:
        ok, h = d.hits(lv)
        n, x = int(h.size), int(h.sum())
        p = 1.0 - lv
        lab = d.level_label(lv)
        if n < min_obs:
            not_executable(res, cid, NAME, f"{title} at {lab}: {n} observations, fewer than {min_obs}",
                           f"only {n} usable observations at {lab}; at least {min_obs} (risk_min_observations) are "
                           "needed for the test to have power", "Extend the backtest window.", evidence=[
                               {"level": lab, "n": n, "exceptions": x, "required": min_obs}])
            continue
        k = kupiec_lr(x, n, p)
        lo, hi = binom_acceptance_region(n, p, alpha)
        rate = x / n
        ev = [{"level": lab, "n": n, "exceptions": x, "expected": round(n * p, 2), "observed_rate": round(rate, 5),
               "expected_rate": p, "lr_uc": round(k["lr"], 4), "p_value": round(k["p_value"], 5),
               "acceptance_region": f"[{lo}, {hi}]", "alpha": alpha}]
        idx = np.flatnonzero(ok)[h == 1]
        ev += [{"row": int(d.rows[i]), "date": d.dates[i], "pnl": round(float(-d.loss[i]), 6),
                d.var_name[lv]: round(float(d.var[lv][i]), 6)} for i in idx[:19]]
        proc = (f"Exceptions x = days with -pnl > {d.var_name[lv]} ({_sign_text(d)}); N = {n}; p = 1 - {lv:g}. "
                "LR_uc = -2 ln[(1-p)^(N-x) p^x] + 2 ln[(1-x/N)^(N-x) (x/N)^x] ~ chi-square(1); "
                "p-value = erfc(sqrt(LR/2)). Acceptance region: exact two-sided binomial region of x at alpha "
                f"= {alpha} (Kupiec 1995).")
        metrics[lab] = {"n": n, "exceptions": x, "rate": rate, "lr_uc": k["lr"], "p_value": k["p_value"],
                        "acceptance_region": [lo, hi]}
        if k["p_value"] < alpha:
            direction = "too many" if rate > p else "too few"
            if direction == "too many":
                why = (f"The model under-estimates risk: {x} exceptions against {n * p:.1f} expected "
                       f"({rate:.2%} vs {p:.2%}).")
                act = "Review the volatility and tail assumptions of the model; too many exceptions means losses beyond " \
                      "the VaR happen more often than the confidence level promises."
            else:
                why = (f"The model is too conservative: {x} exceptions against {n * p:.1f} expected "
                       f"({rate:.2%} vs {p:.2%}). A VaR that is never breached overstates risk and costs capital "
                       "(and hides whether the model would react to a real stress).")
                act = "Check whether the VaR is inflated (double-counted buffers, stale high volatility); a " \
                      "conservative VaR is not free: it ties up capital and limits."
            res.add(cid, NAME, NEEDS_REVIEW, f"{lab} VaR: {direction} exceptions (Kupiec p = {k['p_value']:.4f})",
                    why + f" LR_uc = {k['lr']:.2f}, p = {k['p_value']:.4f} < {alpha}; acceptance region [{lo}, {hi}].",
                    ev, proc, action=act, priority="high" if direction == "too many" else "medium", inputs=inputs)
        else:
            res.add(cid, NAME, PASS, f"{lab} VaR: exception rate consistent with {p:.2%} (Kupiec p = {k['p_value']:.3f})",
                    f"{x} exceptions in {n} days ({rate:.2%}); expected {n * p:.1f}; acceptance region [{lo}, {hi}]; "
                    f"LR_uc = {k['lr']:.2f}. Scope: unconditional coverage only; independence and the regulatory "
                    "zones are separate checks.", ev, proc, inputs=inputs)
    if metrics:
        res.metrics.setdefault("risk", {})["coverage"] = metrics


def check_independence(pkg: Any, res: AuditResult) -> None:
    cid, title = "var_independence", "VaR exception independence (Christoffersen)"
    d = _load(pkg, res, cid, title)
    if d is None:
        return
    alpha = float(pkg.conv("risk_christoffersen_alpha", 0.05))
    min_obs = _min_obs(pkg)
    inputs = [TABLE, "rules"]
    metrics: dict[str, Any] = {}
    for lv in d.levels:
        ok, h = d.hits(lv)
        n, x = int(h.size), int(h.sum())
        p = 1.0 - lv
        lab = d.level_label(lv)
        if n < min_obs:
            not_executable(res, cid, NAME, f"{title} at {lab}: {n} observations, fewer than {min_obs}",
                           f"only {n} usable observations at {lab}; at least {min_obs} are needed",
                           "Extend the backtest window.")
            continue
        idx = np.flatnonzero(h)
        run = longest_run(h)
        n_clusters, in_clusters = exception_clusters(idx)
        base = {"level": lab, "n": n, "exceptions": x, "longest_run": run, "clusters_within_5_days": n_clusters,
                "exceptions_in_clusters": in_clusters}
        proc = ("Exception indicator I_t; transitions n00, n01, n10, n11; pi01 = n01/(n00+n01), pi11 = n11/(n10+n11), "
                "pi = (n01+n11)/(N-1). LR_ind = -2 ln[(1-pi)^(n00+n10) pi^(n01+n11)] + 2 ln[(1-pi01)^n00 pi01^n01 "
                "(1-pi11)^n10 pi11^n11] ~ chi-square(1); LR_cc = LR_uc + LR_ind ~ chi-square(2), p = exp(-LR/2) "
                "(Christoffersen 1998). Clusters: groups of exceptions at most 5 observations apart. The Markov test "
                "has low power with few exceptions: with x < 5 it is not reported as a verdict.")
        ev_rows = [{"row": int(d.rows[i]), "date": d.dates[i], "pnl": round(float(-d.loss[i]), 6),
                    d.var_name[lv]: round(float(d.var[lv][i]), 6)} for i in np.flatnonzero(ok)[idx][:15]]
        if x < 5:
            res.add(cid, NAME, INFO, f"{lab} VaR: not enough exceptions for the independence test ({x})",
                    f"The Christoffersen Markov test needs transitions between exceptions; with {x} exception(s) in "
                    f"{n} days it has no power. Longest run {run}, clusters {n_clusters}.", [base] + ev_rows, proc,
                    action="None: re-run when more exceptions have been observed.", inputs=inputs)
            metrics[lab] = {**base, "lr_ind": None, "lr_cc": None}
            continue
        ind = christoffersen_ind(h)
        uc = kupiec_lr(x, n, p)
        lr_cc = uc["lr"] + ind["lr"]
        p_cc = chi2_sf(lr_cc, 2)
        base.update({"lr_ind": round(ind["lr"], 4), "p_ind": round(ind["p_value"], 5), "lr_cc": round(lr_cc, 4),
                     "p_cc": round(p_cc, 5), "pi01": round(ind["pi01"], 5), "pi11": round(ind["pi11"], 5),
                     "n11": ind["n11"], "alpha": alpha})
        metrics[lab] = dict(base)
        problems = []
        if ind["p_value"] < alpha:
            problems.append(f"LR_ind = {ind['lr']:.2f} (p = {ind['p_value']:.4f}) rejects independence: an exception "
                            f"is followed by another with probability {ind['pi11']:.1%} against {ind['pi01']:.1%} "
                            "after a normal day")
        if p_cc < alpha:
            problems.append(f"LR_cc = {lr_cc:.2f} (p = {p_cc:.4f}) rejects conditional coverage")
        if run >= 3 and abs(lv - 0.99) < 1e-9:
            problems.append(f"a run of {run} consecutive exceptions at 99%")
        if problems:
            res.add(cid, NAME, NEEDS_REVIEW, f"{lab} VaR: exceptions cluster ({problems[0].split(':')[0]})",
                    _sentence("; ".join(problems)) + f". {n_clusters} cluster(s) hold {in_clusters} of the {x} "
                    "exceptions. Clustered exceptions mean the model does not update fast enough when volatility "
                    "rises: the coverage may be right on average and wrong exactly when it matters.",
                    [base] + ev_rows, proc, action="Check the reaction speed of the volatility estimate (decay "
                    "factor, window) and whether the model is re-estimated daily.", priority="high", inputs=inputs)
        else:
            res.add(cid, NAME, PASS, f"{lab} VaR: exceptions independent (LR_ind p = {ind['p_value']:.3f}, "
                    f"LR_cc p = {p_cc:.3f})",
                    f"{x} exceptions in {n} days; longest run {run}; {n_clusters} cluster(s) within 5 days. Scope: "
                    "first-order Markov dependence only; longer-range dependence (Berkowitz, Christoffersen and "
                    "Pelletier 2011) is not tested.", [base] + ev_rows, proc, inputs=inputs)
    if metrics:
        res.metrics.setdefault("risk", {})["independence"] = metrics


def check_traffic_light(pkg: Any, res: AuditResult) -> None:
    cid, title = "basel_traffic_light", "Basel traffic light (99% one-day VaR)"
    d = _load(pkg, res, cid, title)
    if d is None:
        return
    inputs = [TABLE, "rules"]
    lv99 = next((lv for lv in d.levels if abs(lv - 0.99) < 1e-9), None)
    if lv99 is None:
        not_executable(res, cid, NAME, title, "traffic light is defined for 99% one-day VaR and there is no var_99 column",
                       "Add a var_99 column to var_forecasts.csv.")
        return
    window, src = pkg.conv_with_source("risk_traffic_light_window", None)
    if (window is None or src == "default") and d.rules.get("window") is not None:
        window = d.rules["window"]  # rules.yaml risk.window wins over the built-in default, not over a convention
    window = int(window or 250)
    ok, h = d.hits(lv99)
    n = int(h.size)
    if n < window:
        not_executable(res, cid, NAME, f"{title}: {n} observations, fewer than the {window}-day window",
                       f"only {n} usable 99% observations; the window is {window} days",
                       "Extend the backtest or lower conventions.risk_traffic_light_window (documenting why).",
                       evidence=[{"n": n, "window": window}])
        return
    p = 0.01
    last = h[-window:]
    k = int(last.sum())
    zone = traffic_zone(k, window, p)
    addon = traffic_addon(k, window, p)
    rolling = np.convolve(h, np.ones(window, dtype=int), mode="valid")  # count ending at each day >= window-1
    worst_i = int(np.argmax(rolling))
    worst_k = int(rolling[worst_i])
    worst_end = d.dates[np.flatnonzero(ok)[worst_i + window - 1]]
    worst_zone = traffic_zone(worst_k, window, p)
    zones_count = {z: int(sum(traffic_zone(int(c), window, p) == z for c in rolling)) for z in ("green", "yellow", "red")}
    rows = np.flatnonzero(ok)[-window:]
    ex_rows = rows[last == 1]
    ev = [{"window": window, "exceptions": k, "zone": zone, "scaling_addon": addon, "cumulative_probability":
           round(binom_cdf(k, window, p), 5), "period": f"{d.dates[rows[0]]} to {d.dates[rows[-1]]}",
           "worst_window_exceptions": worst_k, "worst_window_end": worst_end, "worst_window_zone": worst_zone,
           "rolling_windows_by_zone": zones_count}]
    ev += [{"row": int(d.rows[i]), "date": d.dates[i], "pnl": round(float(-d.loss[i]), 6),
            "var_99": round(float(d.var[lv99][i]), 6)} for i in ex_rows[:19]]
    proc = (f"Exceptions of the 99% VaR in the last {window} observations; zone by the Basel (1996) table for 250 days "
            "(green 0-4, yellow 5-9, red 10+) or, for another window, by the cumulative binomial probability "
            "P(X <= k) with p = 0.01 (green < 95%, yellow 95% to 99.99%, red above); add-on to the multiplier "
            "0 / 0.40 0.50 0.65 0.75 0.85 / 1.00. Rolling count over the full sample for the worst window.")
    res.metrics.setdefault("risk", {})["traffic_light"] = {"window": window, "exceptions": k, "zone": zone,
                                                           "addon": addon, "worst_window_exceptions": worst_k,
                                                           "worst_window_end": worst_end, "zones": zones_count}
    det = (f"{k} exception(s) in the last {window} days ({d.dates[rows[0]]} to {d.dates[rows[-1]]}); cumulative "
           f"probability under a correct model {binom_cdf(k, window, p):.2%}; scaling add-on {addon:.2f}. Worst "
           f"{window}-day window of the full sample: {worst_k} exceptions ending {worst_end} ({worst_zone}); "
           f"{zones_count['red']} of {len(rolling)} rolling windows were red and {zones_count['yellow']} yellow.")
    if zone == "green":
        res.add(cid, NAME, INFO, f"Traffic light: GREEN ({k} exceptions in {window} days)",
                det + " The green zone does not prove the model right (Basel 1996: about 11% of correct models "
                "fall outside it over time, and a flawed model can land in green); it means no supervisory add-on.",
                ev, proc, action="None from the traffic light; read the coverage and independence checks.",
                priority="low", inputs=inputs)
    elif zone == "yellow":
        res.add(cid, NAME, NEEDS_REVIEW, f"Traffic light: YELLOW ({k} exceptions in {window} days, add-on {addon:.2f})",
                det + " Yellow is ambiguous by construction: a correct model lands here with a few percent "
                "probability, but the supervisor asks for an explanation and may add to the multiplier.",
                ev, proc, action="Document the cause of each exception (market move, position change, model, data) "
                "as the Basel framework requires and decide whether the model must change.", priority="medium",
                inputs=inputs)
    else:
        res.add(cid, NAME, NEEDS_REVIEW, f"Traffic light: RED ({k} exceptions in {window} days, add-on 1.00)",
                det + " Red is a statistical signal that the model's coverage is very unlikely to be 99% (the "
                "probability of 10 or more exceptions under a correct 250-day model is about 0.01%); it is not a "
                "proven data error, which is why it is a high-priority review and not a confirmed error.",
                ev, proc, action="Escalate: the Basel framework presumes a model problem in the red zone; identify "
                "the cause and the remediation.", priority="high", inputs=inputs)


def check_es_backtest(pkg: Any, res: AuditResult) -> None:
    cid, title = "es_backtest", "Expected shortfall backtest (Acerbi-Szekely Z2)"
    d = _load(pkg, res, cid, title)
    if d is None:
        return
    inputs = [TABLE, "rules"]
    pairs = [lv for lv in sorted(d.es) if lv in d.var]
    if not pairs:
        not_executable(res, cid, NAME, title, "no es_<level> column with a matching var_<level> column",
                       "Add es_99 (or es_975) next to the VaR of the same level.")
        return
    metrics: dict[str, Any] = {}
    for lv in pairs:
        lab = d.level_label(lv)
        p = 1.0 - lv
        v, e = d.var[lv], d.es[lv]
        ok = np.isfinite(v) & np.isfinite(e) & np.isfinite(d.loss) & (e > 0)
        loss = d.loss[ok]
        es = e[ok]
        h = (loss > v[ok]).astype(int)
        n, x = int(h.size), int(h.sum())
        if x < 10:
            not_executable(res, cid, NAME, f"{title} at {lab}",
                           f"only {x} exception(s) at {lab} in {n} days; at least 10 are needed for the ES statistics",
                           "Extend the backtest window.", evidence=[{"level": lab, "n": n, "exceptions": x}])
            continue
        z2 = acerbi_szekely_z2(loss, es, h, p)
        exc = h == 1
        resid = loss[exc] - es[exc]
        mean_loss, mean_es = float(loss[exc].mean()), float(es[exc].mean())
        ratio = mean_loss / mean_es if mean_es > 0 else float("nan")
        sd = float(resid.std(ddof=1)) if x > 1 else float("nan")
        t_stat = float(resid.mean() / (sd / math.sqrt(x))) if sd and sd > 0 else float("nan")
        base = {"level": lab, "n": n, "exceptions": x, "z2": round(z2, 4), "mean_loss_on_exceptions": round(mean_loss, 6),
                "mean_es_on_exceptions": round(mean_es, 6), "ratio": round(ratio, 4),
                "exceedance_residual_mean": round(float(resid.mean()), 6), "exceedance_residual_t": round(t_stat, 3)}
        idx = np.flatnonzero(ok)[exc]
        ev = [base] + [{"row": int(d.rows[i]), "date": d.dates[i], "pnl": round(float(-d.loss[i]), 6),
                        d.var_name[lv]: round(float(d.var[lv][i]), 6), d.es_name[lv]: round(float(d.es[lv][i]), 6)}
                       for i in idx[:19]]
        proc = (f"Losses positive (L_t = -pnl_t; {_sign_text(d)}; ES as a positive loss). Exception: L_t > VaR_t. "
                f"Z2 = 1 - sum_t L_t 1[exception_t] / (N p ES_t), N = {n}, p = {p:g} (Acerbi and Szekely 2014, "
                "test 2): 0 under H0, negative when the ES is too small. The exact critical value depends on the "
                f"P&L distribution and needs simulation under the model; the bound {Z2_BOUND} is the approximate 5% "
                "value the authors report for typical distributions. Exceedance residual: mean of (L - ES) on "
                "exception days with its t-statistic. Ratio: mean realised loss / mean ES forecast on exception days.")
        metrics[lab] = dict(base)
        problems = []
        if z2 < Z2_BOUND:
            problems.append(f"Z2 = {z2:.2f} < {Z2_BOUND} (approximate 5% bound)")
        if math.isfinite(ratio) and ratio > ES_RATIO_MAX:
            problems.append(f"the mean loss on exception days ({mean_loss:.4f}) exceeds the mean ES forecast "
                            f"({mean_es:.4f}) by {ratio - 1:.0%} (> {ES_RATIO_MAX - 1:.0%})")
        if problems:
            res.add(cid, NAME, NEEDS_REVIEW, f"{lab} ES under-estimates the tail: " + problems[0],
                    _sentence("; ".join(problems)) + f". Exceedance residual mean {resid.mean():.5f} "
                    f"(t = {t_stat:.2f}) over {x} exceptions. The ES is what the FRTB capital charge rests on: "
                    "a VaR with the right coverage and an ES that is too small means the size of the losses beyond "
                    "the VaR is misjudged, which is exactly what the ES exists to measure.",
                    ev, proc, action="Re-estimate the tail (distribution beyond the VaR, scaling of the ES from the "
                    "VaR) and re-run; confirm the critical value of Z2 by simulation under the model.",
                    priority="high", inputs=inputs)
        else:
            res.add(cid, NAME, INFO, f"{lab} ES: Z2 = {z2:.2f}, mean loss / mean ES on exception days = {ratio:.2f}",
                    f"{x} exceptions in {n} days; exceedance residual mean {resid.mean():.5f} (t = {t_stat:.2f}). No "
                    f"alert under the approximate bound Z2 >= {Z2_BOUND} and ratio <= {ES_RATIO_MAX}; this is a "
                    "note and not a PASS because the exact critical value of Z2 is model-dependent and was not "
                    "simulated.", ev, proc, action="For a formal conclusion, simulate the Z2 distribution under "
                    "the model (Acerbi and Szekely 2014).", priority="low", inputs=inputs)
    if metrics:
        res.metrics.setdefault("risk", {})["es"] = metrics


def _blocks(d: RiskData, mask_idx: np.ndarray) -> tuple[list[tuple[str, np.ndarray]], str]:
    """Blocks of indices (positions inside mask_idx): calendar years when at least 2 years have 100+ days, else
    consecutive 250-day blocks."""
    years = np.array([d.dates[i].year for i in mask_idx])
    uniq = sorted(set(years))
    year_blocks = [(str(y), np.flatnonzero(years == y)) for y in uniq if (years == y).sum() >= 100]
    if len(year_blocks) >= 2:
        return year_blocks, "calendar years with at least 100 observations"
    n = mask_idx.size
    blocks = [(f"block {j + 1} ({d.dates[mask_idx[s]]} to {d.dates[mask_idx[min(s + 249, n - 1)]]})",
               np.arange(s, min(s + 250, n))) for j, s in enumerate(range(0, n, 250))]
    blocks = [b for b in blocks if b[1].size >= 100]
    return blocks, "consecutive 250-day blocks (the last one kept only if it has 100+ days)"


def check_model_stability(pkg: Any, res: AuditResult) -> None:
    cid, title = "var_model_stability", "VaR model stability over time"
    d = _load(pkg, res, cid, title)
    if d is None:
        return
    alpha = float(pkg.conv("risk_kupiec_alpha", 0.05))
    min_obs = _min_obs(pkg)
    inputs = [TABLE, "rules"]
    if d.n < min_obs:
        not_executable(res, cid, NAME, f"{title}: {d.n} observations, fewer than {min_obs}",
                       f"only {d.n} observations; at least {min_obs} are needed",
                       "Extend the backtest window.")
        return
    # realised volatility: rolling 20-day standard deviation of the pnl (past 20 days including the day)
    pnl = pd.Series(-d.loss)
    rvol = pnl.rolling(20, min_periods=20).std(ddof=1).to_numpy(dtype=float)
    problems: list[str] = []
    ev: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    for lv in d.levels:
        lab = d.level_label(lv)
        ok, h = d.hits(lv)
        idx = np.flatnonzero(ok)
        blocks, scheme = _blocks(d, idx)
        p = 1.0 - lv
        table = []
        chi2 = p_chi = float("nan")
        if len(blocks) >= 2:
            xs = np.array([h[b].sum() for _, b in blocks], dtype=float)
            ns = np.array([b.size for _, b in blocks], dtype=float)
            pooled = xs.sum() / ns.sum()
            testable = bool(0 < pooled < 1 and (ns * pooled).min() >= 5)
            if testable:
                exp1 = ns * pooled
                exp0 = ns * (1 - pooled)
                chi2 = float((((xs - exp1) ** 2) / exp1).sum() + (((ns - xs) - exp0) ** 2 / exp0).sum())
                p_chi = chi2_sf(chi2, len(blocks) - 1)
            for (name, b), xk, nk in zip(blocks, xs, ns):
                v = d.var[lv][idx[b]]
                rv = rvol[idx[b]]
                m = np.isfinite(v) & np.isfinite(rv) & (rv > 0)
                table.append({"level": lab, "block": name, "n": int(nk), "exceptions": int(xk),
                              "rate": round(xk / nk, 5), "expected_rate": p,
                              "mean_var": round(float(np.nanmean(v)), 6) if np.isfinite(v).any() else None,
                              "var_over_realised_vol": round(float(np.mean(v[m] / rv[m])), 3) if m.any() else None})
        v = d.var[lv][idx]
        rv = rvol[idx]
        m = np.isfinite(v) & np.isfinite(rv) & (rv > 0)
        if m.sum() >= 30:
            sv = float(np.std(v[m]))
            corr = float(np.corrcoef(v[m], rv[m])[0, 1]) if sv > 0 and np.std(rv[m]) > 0 else 0.0
        else:
            sv, corr = float("nan"), float("nan")
        summary = {"level": lab, "blocks": len(blocks), "block_scheme": scheme, "chi2_homogeneity": round(chi2, 4)
                   if math.isfinite(chi2) else None, "p_value": round(p_chi, 5) if math.isfinite(p_chi) else None,
                   "homogeneity_tested": math.isfinite(p_chi),
                   "corr_var_realised_vol_20d": round(corr, 4) if math.isfinite(corr) else None,
                   "var_constant": bool(math.isfinite(sv) and sv == 0)}
        ev.append(summary)
        ev.extend(table)
        metrics[lab] = {"summary": summary, "blocks": table}
        if math.isfinite(p_chi) and p_chi < alpha:
            worst = max(table, key=lambda r: r["rate"])
            problems.append(f"{lab}: the exception rate is not homogeneous across {len(blocks)} blocks (chi-square "
                            f"{chi2:.2f}, p = {p_chi:.4f}; worst {worst['block']} with {worst['rate']:.2%})")
        if math.isfinite(corr) and corr < 0.3:
            problems.append(f"{lab}: the model does not respond to volatility (correlation between the VaR and the "
                            f"20-day realised volatility {corr:.2f} < 0.30"
                            + ("; the VaR is constant" if sv == 0 else "") + ")")
    proc = ("Per level: exceptions and rate per calendar year (or 250-day block), chi-square test of homogeneity of the "
            "rate across blocks (2 x B table, B - 1 degrees of freedom, regularised gamma tail) at alpha = "
            f"{alpha}, run only when every block expects at least 5 exceptions (otherwise the chi-square "
            "approximation is unreliable and the table is reported without a test); Pearson correlation between the VaR forecast and the trailing 20-day standard deviation of "
            "the pnl, and the average ratio VaR / realised volatility per block.")
    res.metrics.setdefault("risk", {})["stability"] = metrics
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "VaR model stability: " + problems[0].split(" (")[0],
                _sentence("; ".join(problems)) + ". A VaR that does not move with volatility, or whose exception "
                "rate changes from one year to the next, passes the average coverage test while failing in the "
                "years that matter.", ev, proc, action="Check the volatility estimator and the re-estimation "
                "frequency; report the exception rate per year, not only the full-sample rate.", priority="medium",
                inputs=inputs)
    else:
        res.add(cid, NAME, INFO, "VaR model stability: exception rates homogeneous and VaR tracks volatility",
                "; ".join(f"{s['level']}: corr(VaR, 20d vol) = {s['corr_var_realised_vol_20d']}, homogeneity p = "
                          f"{s['p_value']}" for s in ev if "blocks" in s) + ". A note, not a PASS: stability over "
                "the sample does not say what the model does in a regime the sample does not contain.",
                ev, proc, action="None.", priority="low", inputs=inputs)


# ----------------------------------------------------------------------------------------------- spec

CHECK_FUNCTIONS = ((check_input_coherence, "var_input_coherence"), (check_coverage, "var_coverage"),
                   (check_independence, "var_independence"), (check_traffic_light, "basel_traffic_light"),
                   (check_es_backtest, "es_backtest"), (check_model_stability, "var_model_stability"))


def run(pkg: Any, res: AuditResult) -> None:
    for fn, cid in CHECK_FUNCTIONS:
        try:
            fn(pkg, res)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")


REFS = {
    "kupiec95": "Kupiec, P. (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. Journal of "
                "Derivatives 3(2), 73-84.",
    "christoffersen98": "Christoffersen, P. (1998). Evaluating Interval Forecasts. International Economic Review "
                        "39(4), 841-862.",
    "basel96": "Basel Committee on Banking Supervision (1996). Supervisory Framework for the Use of Backtesting in "
               "Conjunction with the Internal Models Approach to Market Risk Capital Requirements.",
    "basel19": "Basel Committee on Banking Supervision (2019). Minimum Capital Requirements for Market Risk (MAR, "
               "FRTB): backtesting and P&L attribution at desk level, 97.5% expected shortfall.",
    "as14": "Acerbi, C. and Szekely, B. (2014). Backtesting Expected Shortfall. Risk, December 2014, 76-81.",
    "campbell06": "Campbell, S. (2006). A Review of Backtesting and Backtesting Procedures. Journal of Risk 9(2), 1-17.",
    "bcp11": "Berkowitz, J., Christoffersen, P. and Pelletier, D. (2011). Evaluating Value-at-Risk Models with "
             "Desk-Level Data. Management Science 57(12), 2213-2227.",
    "eo10": "Escanciano, J. C. and Olmo, J. (2010). Backtesting Parametric Value-at-Risk with Estimation Risk. "
            "Journal of Business and Economic Statistics 28(1), 36-51.",
}

CATALOG = {
    "var_input_coherence": {
        "title": "VaR input coherence",
        "what": "Sign convention of the VaR (declared vs observed), horizon, missing or zero VaR, quantile monotonicity "
                "(var_95 <= var_99), ES >= VaR per level, duplicated dates, gaps longer than 5 sessions and frozen P&L.",
        "why": "An inverted sign turns every exception count into nonsense; crossed quantiles or an ES below its VaR "
               "cannot come from a coherent model; gaps and frozen P&L hide the days a backtest exists to test.",
        "fix": "Declare conventions.risk_var_sign, fix the forecast file (one row per date, ordered quantiles, ES >= VaR) "
               "and explain gaps.",
        "allows": "Whether the forecast file can be backtested at all.",
        "does_not_allow": "Anything about the quality of the forecasts.", "refs": ["basel96", "sr117"],
    },
    "var_coverage": {
        "title": "VaR unconditional coverage (Kupiec)",
        "what": "Per level: exceptions x in N days, observed vs expected rate, Kupiec LR_uc against chi-square(1), exact "
                "binomial acceptance region. Too many exceptions (risk under-estimated) or too few (model too "
                "conservative, capital wasted) are both review items.",
        "why": "Coverage is the first promise of a VaR: losses beyond it on 1% of days. A model breached 3% of the time "
               "under-states risk; one never breached ties up capital and tells nothing about its reaction to stress.",
        "fix": "Re-estimate volatility and tails; check the horizon and the P&L definition (hypothetical vs actual).",
        "allows": "Whether the long-run exception rate is consistent with the level.",
        "does_not_allow": "Whether the exceptions are independent (see var_independence); power is low below 250 days "
                          "(Kupiec 1995) and estimation risk inflates rejections (Escanciano and Olmo 2010).",
        "refs": ["kupiec95", "campbell06", "eo10", "basel96"],
    },
    "var_independence": {
        "title": "VaR exception independence (Christoffersen)",
        "what": "Christoffersen Markov independence test LR_ind, joint conditional coverage LR_cc = LR_uc + LR_ind, "
                "longest run of consecutive exceptions and clusters within 5 days.",
        "why": "A model with the right average coverage but clustered exceptions fails exactly in the stress episodes; "
               "clustering reveals a volatility estimate that reacts too slowly.",
        "fix": "Shorten the estimation window or decay factor; re-estimate daily; model volatility clustering.",
        "allows": "First-order dependence of the exceptions and the joint test.",
        "does_not_allow": "Higher-order or duration dependence (Berkowitz, Christoffersen and Pelletier 2011); with fewer "
                          "than 5 exceptions the test has no power and reports INFO.",
        "refs": ["christoffersen98", "bcp11", "campbell06"],
    },
    "basel_traffic_light": {
        "title": "Basel traffic light (99% one-day VaR)",
        "what": "Exceptions of the 99% VaR in the last 250 observations mapped to the Basel green / yellow / red zones "
                "with the multiplier add-on; rolling count over the full sample and the worst window.",
        "why": "It is the regulatory backtest: yellow asks for explanations and may raise capital, red presumes a "
               "model problem. It is also a statistical signal, not a proof: a correct model lands in yellow a few "
               "percent of the time.",
        "fix": "Explain every exception (market, position, model, data) and remediate the model when the cause is the "
               "model.",
        "allows": "The supervisory zone and the add-on; how often the model would have been yellow or red historically.",
        "does_not_allow": "Confirming an error: red is never a CONFIRMED_ERROR here. Defined for 99% one-day VaR only "
                          "(FRTB keeps it at 99% and 97.5% VaR for desks; the ES is backtested indirectly).",
        "refs": ["basel96", "basel19"],
    },
    "es_backtest": {
        "title": "Expected shortfall backtest (Acerbi-Szekely Z2)",
        "what": "Z2 = 1 - sum L_t 1[exception_t] / (N p ES_t) with losses positive (0 under H0, negative when the ES is "
                "too small), the mean realised loss on exception days against the mean ES forecast, and the exceedance "
                "residual (loss - ES) with its t-statistic.",
        "why": "FRTB capital rests on the 97.5% ES; a VaR with correct coverage says nothing about the size of the losses "
               "beyond it, which is what the ES forecasts.",
        "fix": "Re-estimate the tail beyond the VaR; do not scale the ES from the VaR with a fixed factor.",
        "allows": "Whether the realised tail losses are compatible with the ES forecasts, approximately.",
        "does_not_allow": "A formal verdict: the critical value of Z2 depends on the P&L distribution and must be "
                          "simulated under the model; the -0.70 bound is the authors' approximation. Fewer than 10 "
                          "exceptions: NOT_EXECUTABLE.",
        "refs": ["as14", "basel19"],
    },
    "var_model_stability": {
        "title": "VaR model stability over time",
        "what": "Exception rate per calendar year (or 250-day block) with a chi-square homogeneity test; correlation "
                "between the VaR and the 20-day realised volatility and the VaR / volatility ratio per block.",
        "why": "A full-sample coverage test averages good and bad years; a VaR that does not move with volatility "
               "is right on average and wrong in every regime.",
        "fix": "Report exceptions per year; use a volatility estimator that reacts (EWMA, GARCH, filtered historical).",
        "allows": "Whether the coverage is stable over time and the VaR tracks realised volatility.",
        "does_not_allow": "What the model does in a regime absent from the sample.",
        "refs": ["basel96", "campbell06", "sr117"],
    },
}

SPEC = UseCase(
    name=NAME,
    title="Market-risk model backtesting (VaR / ES)",
    description="Backtests Value-at-Risk and Expected Shortfall forecasts against the realised P&L: input coherence and "
                "sign convention, Kupiec coverage, Christoffersen independence, the Basel traffic light, the "
                "Acerbi-Szekely ES test and stability over time. For banks under Basel / FRTB, asset managers, prop "
                "desks and exchanges that publish a VaR.",
    audience="risk managers and model validation units",
    detect_files=[TABLE],
    files={TABLE: "var_forecasts.csv"},
    schema={TABLE: {"required": ["date", "pnl"], "optional": ["model", "portfolio"]}},
    aliases={TABLE: {"date": ["datetime", "timestamp", "day"], "pnl": ["return", "ret", "loss"]}},
    date_columns={TABLE: ["date"]},
    numeric_columns={TABLE: ["pnl"]},
    requirements={cid: {"required": [TABLE], "optional": ["rules"]} for _, cid in CHECK_FUNCTIONS},
    catalog=CATALOG,
    references=REFS,
    conventions={"risk_kupiec_alpha": 0.05, "risk_christoffersen_alpha": 0.05, "risk_min_observations": 250,
                 "risk_traffic_light_window": 250, "risk_es_alpha": 0.05, "risk_var_sign": POSITIVE_LOSS},
    profiles={
        "risk_var_daily": {"description": "Daily 99% one-day VaR backtest (Basel-style 250-day traffic light window).",
                           "conventions": {"risk_traffic_light_window": 250, "risk_min_observations": 250}},
        "risk_var_fund": {"description": "Asset-manager VaR at 95% / 99% with a UCITS-style 250-day window.",
                          "conventions": {"risk_traffic_light_window": 250, "risk_min_observations": 250,
                                          "periods_per_year": 252}},
    },
    run=run,
)
register(SPEC)
