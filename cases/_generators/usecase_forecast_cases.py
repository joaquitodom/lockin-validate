"""Cases of the ``forecast`` use case (cases/usecase_forecast/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/usecase_forecast_cases.py

Each case plants a property with a known consequence and fixes expected.json from it BEFORE the tool runs. Where a
random draw could contradict the planted property, the generator asserts it with its OWN computation (numpy, coded
here independently of the tool) and fails loudly instead of writing a case whose expectation would be wrong.

  01_clean_skilful          AR(1) with the true conditional-mean forecast, 300 daily obs -> vs_naive INFO, bias INFO,
                            origin_integrity PASS; nothing in NEEDS_REVIEW / CONFIRMED_ERROR
  02_no_skill               i.i.d. returns, random forecasts, zero naive       -> vs_naive and directional NEEDS_REVIEW
  03_biased                 true forecast + 0.5 sigma                          -> bias NEEDS_REVIEW
  04_target_before_origin   five forecasts dated after their target            -> origin_integrity CONFIRMED_ERROR
  05_revised_data_cheat     monthly macro series with publication lags; the supplied naive uses the last actual by
                            target date although it was not yet published      -> origin_integrity CONFIRMED_ERROR
  06_many_models_one_lucky  12 noise models of i.i.d. returns, one marginally better -> multiple_models NEEDS_REVIEW
  07_insufficient           15 observations                                    -> NOT_EXECUTABLE, never PASS
  08_multi_horizon          h = 1, 3, 12 with a horizon column; errors MA(h-1) by construction -> error_dynamics must
                            NOT alert (adversarial: looks autocorrelated, is legitimate)
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "usecase_forecast"
EULER_GAMMA = 0.5772156649015329


# ---------------------------------------------------------------------------- independent statistics

def ncdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))


def ninv(p: float) -> float:
    """Inverse normal CDF by bisection (enough for the expected-maximum formula)."""
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def lrv(x: np.ndarray, lags: int) -> float:
    d = x - x.mean()
    T = d.size
    s = float((d * d).sum() / T)
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * float((d[k:] * d[:-k]).sum() / T)
    return s


def dm_t(em: np.ndarray, en: np.ndarray, h: int) -> float:
    """HLN-corrected DM statistic on squared losses (negative = model better)."""
    d = em ** 2 - en ** 2
    T = d.size
    dm = d.mean() / math.sqrt(lrv(d, h - 1) / T)
    return dm * math.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)


def lb_p(e: np.ndarray, lo: int, hi: int) -> float:
    """Portmanteau over lags lo..hi under an MA(lo - 1) null (Bartlett covariance of the autocorrelations); lo = 1 is
    the Ljung-Box test."""
    d = e - e.mean()
    T = d.size
    den = float((d * d).sum())
    rho = [1.0] + [float((d[k:] * d[:-k]).sum() / den) for k in range(1, hi + 1)]
    q = lo - 1
    ks = list(range(lo, hi + 1))
    K = len(ks)
    sig = np.zeros((K, K))
    for i, k in enumerate(ks):
        for j, m in enumerate(ks):
            sig[i, j] = sum(rho[abs(x)] * (rho[abs(x + m - k)] if abs(x + m - k) <= q else 0.0) for x in range(-q, q + 1))
    r = np.array([rho[k] * math.sqrt((T + 2) / (T - k)) for k in ks])
    Q = T * float(r @ np.linalg.solve(sig, r))
    z = ((Q / K) ** (1 / 3) - (1 - 2 / (9 * K))) / math.sqrt(2 / (9 * K))
    return 1 - ncdf(z)


def pt_p(a_up: np.ndarray, f_up: np.ndarray) -> float:
    n = a_up.size
    py, px, p = a_up.mean(), f_up.mean(), (a_up == f_up).mean()
    ps = py * px + (1 - py) * (1 - px)
    vp = ps * (1 - ps) / n
    vs = ((2 * py - 1) ** 2 * px * (1 - px) / n + (2 * px - 1) ** 2 * py * (1 - py) / n
          + 4 * py * px * (1 - py) * (1 - px) / n ** 2)
    return 1 - ncdf((p - ps) / math.sqrt(vp - vs))


def mz(y: np.ndarray, f: np.ndarray, h: int) -> tuple[float, float]:
    """(Wald p-value of (a, b) = (0, 1) with HAC h-1 lags, HAC t of the mean error)."""
    T = y.size
    X = np.column_stack([np.ones(T), f])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    u = y - X @ beta
    xu = X * u[:, None]
    S = xu.T @ xu
    L = h - 1
    for k in range(1, L + 1):
        G = xu[k:].T @ xu[:-k]
        S += (1 - k / (L + 1)) * (G + G.T)
    xi = np.linalg.inv(X.T @ X)
    V = xi @ S @ xi
    r = beta - np.array([0.0, 1.0])
    W = float(r @ np.linalg.solve(V, r))
    e = y - f
    t = e.mean() / math.sqrt(lrv(e, L) / T)
    return math.exp(-W / 2), t


def expected_max_t(n: int) -> float:
    return (1 - EULER_GAMMA) * ninv(1 - 1 / n) + EULER_GAMMA * ninv(1 - 1 / (n * math.e))


# ---------------------------------------------------------------------------- helpers

def ar1(rng: np.random.Generator, n: int, phi: float, sigma: float = 1.0, burn: int = 100) -> np.ndarray:
    y = np.zeros(n + burn)
    eps = rng.normal(0, sigma, n + burn)
    for t in range(1, n + burn):
        y[t] = phi * y[t - 1] + eps[t]
    return y[burn:]


def month_ends(start_year: int, start_month: int, n: int) -> list[date]:
    out, y, m = [], start_year, start_month
    for _ in range(n):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append(date(ny, nm, 1) - timedelta(days=1))
        y, m = ny, nm
    return out


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


def write(name: str, header: list[str], rows: list[list], expected: dict, description: str,
          rules: str | None = None):
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    with open(c / "forecasts.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    if rules:
        (c / "rules.yaml").write_text(rules, encoding="utf-8")
    exp = {"description": description, "origin": "usecase", "use_case": "forecast", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def fmt(x: float) -> str:
    return f"{x:.6f}"


def daily_rows(y: np.ndarray, f: np.ndarray, start: date) -> list[list]:
    """origin t, target t + 1 day; forecast f[t] for actual y[t + 1]."""
    rows = []
    for t in range(len(y) - 1):
        o = start + timedelta(days=t)
        rows.append([o.isoformat(), (o + timedelta(days=1)).isoformat(), fmt(f[t]), fmt(y[t + 1])])
    return rows


ALL = ["forecast_origin_integrity", "forecast_vs_naive", "forecast_bias", "forecast_directional",
       "forecast_error_dynamics", "forecast_multiple_models"]
CLEAN_NOT = [mustnot(c, s) for c in ALL for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")]


# ---------------------------------------------------------------------------- cases

def c01():
    rng = np.random.default_rng(101)
    phi = 0.5
    y = ar1(rng, 301, phi)
    f = phi * y  # true conditional mean of y[t + 1] given y[t]
    em = y[1:] - f[:-1]
    en = y[1:] - y[:-1]  # random walk
    assert dm_t(em, en, 1) < -3.0
    assert lb_p(em, 1, 11) > 0.10
    p_w, t_me = mz(y[1:], f[:-1], 1)
    assert p_w > 0.10 and abs(t_me) < 1.8, (p_w, t_me)
    assert pt_p(y[1:] - y[:-1] > 0, f[:-1] - y[:-1] > 0) < 0.01
    write("01_clean_skilful", ["origin_date", "target_date", "forecast", "actual"], daily_rows(y, f, date(2021, 1, 1)),
          expected={"must_include": [must("forecast_vs_naive", "INFO"), must("forecast_bias", "INFO"),
                                     must("forecast_origin_integrity", "PASS"), must("forecast_directional", "INFO"),
                                     must("forecast_error_dynamics", "INFO")],
                    "must_not_include": CLEAN_NOT + [mustnot("forecast_vs_naive", "PASS")], "errors_only_from": [],
                    "comment": "AR(1) phi = 0.5 forecast by its true conditional mean: beats the random walk, "
                               "unbiased, directional skill, white errors."},
          description="Clean: AR(1) series forecast one step ahead by the true model (300 daily observations).")


def c02():
    rng = np.random.default_rng(102)
    y = rng.normal(0, 1, 301)
    f = rng.normal(0, 0.5, 301)
    em = y[1:] - f[:-1]
    assert (em ** 2).mean() > (y[1:] ** 2).mean()  # U > 1 against the zero naive
    assert pt_p(y[1:] > 0, f[:-1] > 0) > 0.10
    write("02_no_skill", ["origin_date", "target_date", "forecast", "actual"], daily_rows(y, f, date(2021, 1, 1)),
          expected={"must_include": [must("forecast_vs_naive", "NEEDS_REVIEW"),
                                     must("forecast_directional", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("forecast_vs_naive", "PASS"), mustnot("forecast_vs_naive", "INFO"),
                                         mustnot("forecast_directional", "INFO")],
                    "errors_only_from": [],
                    "comment": "Random forecasts of i.i.d. returns: Theil's U > 1 against zero and a hit ratio "
                               "near 50%."},
          description="No skill: random forecasts of i.i.d. returns against the zero naive.",
          rules="conventions:\n  forecast_naive: zero\n")


def c03():
    rng = np.random.default_rng(103)
    phi = 0.5
    y = ar1(rng, 301, phi)
    f = phi * y + 0.5  # systematic over-forecast of half a residual standard deviation
    p_w, t_me = mz(y[1:], f[:-1], 1)
    assert p_w < 0.01 and t_me < -4
    write("03_biased", ["origin_date", "target_date", "forecast", "actual"], daily_rows(y, f, date(2021, 1, 1)),
          expected={"must_include": [must("forecast_bias", "NEEDS_REVIEW"), must("forecast_origin_integrity", "PASS")],
                    "must_not_include": [mustnot("forecast_bias", "INFO")], "errors_only_from": [],
                    "text_must_contain": [{"check": "forecast_bias", "text": "over-forecasts"}],
                    "comment": "Mean error -0.5 with t about -9; the Mincer-Zarnowitz intercept rejects a = 0."},
          description="Biased: the true forecast plus a constant 0.5 sigma (systematic over-forecasting).")


def c04():
    rng = np.random.default_rng(104)
    phi = 0.5
    y = ar1(rng, 301, phi)
    f = phi * y
    rows = daily_rows(y, f, date(2021, 1, 1))
    for i in (10, 50, 120, 200, 250):  # the forecast is dated after the period it predicts
        rows[i][0], rows[i][1] = rows[i][1], rows[i][0]
    write("04_target_before_origin", ["origin_date", "target_date", "forecast", "actual"], rows,
          expected={"must_include": [must("forecast_origin_integrity", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("forecast_origin_integrity", "PASS")],
                    "errors_only_from": ["forecast_origin_integrity"],
                    "comment": "Five rows with target_date < origin_date (forecasting the past)."},
          description="Target before origin: five forecasts are dated after the period they predict.")


def c05():
    rng = np.random.default_rng(105)
    n = 120
    y = 3.0 + ar1(rng, n + 1, 0.8, 0.4)  # monthly inflation-like level series
    ends = month_ends(2015, 1, n + 1)
    rows = []
    for t in range(n):
        origin, target = ends[t], ends[t + 1]
        published = target + timedelta(days=45)  # the value of month t + 1 is released 45 days after month end
        naive = y[t]  # last actual by target date: month t, released 45 days after origin -> not yet known
        forecast = 0.8 * y[t] + 0.6 + rng.normal(0, 0.2)
        rows.append([origin.isoformat(), target.isoformat(), fmt(forecast), fmt(y[t + 1]), "cpi",
                     published.isoformat(), fmt(naive)])
    write("05_revised_data_cheat", ["origin_date", "target_date", "forecast", "actual", "series",
                                    "actual_available_from", "naive"], rows,
          expected={"must_include": [must("forecast_origin_integrity", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("forecast_origin_integrity", "PASS")],
                    "errors_only_from": ["forecast_origin_integrity"],
                    "text_must_contain": [{"check": "forecast_origin_integrity", "text": "not yet published"}],
                    "comment": "Every supplied naive equals the previous month's value, published 45 days after the "
                               "origin; the publication-aware random walk is the value of two months earlier."},
          description="Revised-data cheat: the supplied naive uses the last actual by target date although it was "
                      "not yet published at the origin (actual_available_from).")


def c06():
    rng = np.random.default_rng(106)
    n = 201
    y = rng.normal(0, 1, n)
    header = ["origin_date", "target_date", "forecast", "actual", "model"]
    rows = []
    worst_t = -99.0
    for k in range(12):
        f = rng.normal(0, 0.3, n)
        if k == 6:
            f = 0.05 * y + rng.normal(0, 0.2, n)  # marginally informative, within the luck of the draw
        em = y[1:] - f[:-1]
        worst_t = max(worst_t, -dm_t(em, y[1:], 1))
        for r in daily_rows(y, f, date(2021, 1, 1)):
            rows.append(r + [f"m{k + 1:02d}"])
    assert worst_t < expected_max_t(12), worst_t
    write("06_many_models_one_lucky", header, rows,
          expected={"must_include": [must("forecast_multiple_models", "NEEDS_REVIEW"),
                                     must("forecast_vs_naive", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("forecast_multiple_models", "INFO"),
                                         mustnot("forecast_multiple_models", "NOT_EXECUTABLE")],
                    "errors_only_from": [],
                    "comment": "12 models of i.i.d. returns; the best t against the zero naive is below the expected "
                               "maximum of 12 skill-less t-statistics (about 1.63)."},
          description="Many models: 12 noise forecasts of i.i.d. returns, one marginally better by chance.",
          rules="conventions:\n  forecast_naive: zero\n")


def c07():
    rng = np.random.default_rng(107)
    phi = 0.5
    y = ar1(rng, 16, phi)
    f = phi * y
    write("07_insufficient", ["origin_date", "target_date", "forecast", "actual"], daily_rows(y, f, date(2021, 1, 1)),
          expected={"must_include": [must("forecast_vs_naive", "NOT_EXECUTABLE"), must("forecast_bias", "NOT_EXECUTABLE"),
                                     must("forecast_directional", "NOT_EXECUTABLE"),
                                     must("forecast_error_dynamics", "NOT_EXECUTABLE"),
                                     must("forecast_multiple_models", "NOT_EXECUTABLE")],
                    "must_not_include": [mustnot("forecast_vs_naive", "PASS"), mustnot("forecast_vs_naive", "INFO"),
                                         mustnot("forecast_bias", "PASS"), mustnot("forecast_directional", "PASS")],
                    "errors_only_from": [],
                    "comment": "15 forecasts, below forecast_min_observations = 30."},
          description="Insufficient data: 15 forecasts; the statistical checks must be NOT_EXECUTABLE, never PASS.")


def c08():
    rng = np.random.default_rng(110)
    phi, n = 0.7, 241
    y = ar1(rng, n, phi)
    ends = month_ends(2004, 1, n)
    header = ["origin_date", "target_date", "forecast", "actual", "horizon", "series"]
    rows = []
    for h in (1, 3, 12):
        f = phi ** h * y
        em = y[h:] - f[:-h]
        assert lb_p(em, h, h + 10) > 0.10, (h, lb_p(em, h, h + 10))
        p_w, t_me = mz(y[h:], f[:-h], h)
        assert p_w > 0.10 and abs(t_me) < 1.8, (h, p_w, t_me)
        for t in range(n - h):
            rows.append([ends[t].isoformat(), ends[t + h].isoformat(), fmt(f[t]), fmt(y[t + h]), h, "gdp_gap"])
    write("08_multi_horizon", header, rows,
          expected={"must_include": [must("forecast_error_dynamics", "INFO"), must("forecast_origin_integrity", "PASS"),
                                     must("forecast_vs_naive", "INFO")],
                    "must_not_include": [mustnot("forecast_error_dynamics", "NEEDS_REVIEW"),
                                         mustnot("forecast_origin_integrity", "NEEDS_REVIEW"),
                                         mustnot("forecast_bias", "NEEDS_REVIEW")],
                    "errors_only_from": [],
                    "comment": "True h-step forecasts of an AR(1): the errors are MA(h - 1) by construction; a test "
                               "that starts at lag 1 would reject for h = 3 and h = 12, the correct test starts at "
                               "lag h and does not."},
          description="Adversarial: horizons 1, 3 and 12 months with a horizon column; the h-step errors are MA(h - 1) "
                      "and must NOT be reported as residual autocorrelation.")


def main():
    OUT.mkdir(exist_ok=True)
    for fn in (c01, c02, c03, c04, c05, c06, c07, c08):
        fn()
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
