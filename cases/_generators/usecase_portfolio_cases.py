"""Cases of the ``portfolio`` use case (cases/usecase_portfolio/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/usecase_portfolio_cases.py

Every case is a table of target weights (weights.csv) for 20 synthetic names over monthly dates, with daily prices
(prices.csv) and a rules.yaml. expected.json is fixed from the planted problem BEFORE the tool runs. Where a random
draw could contradict the planted property (01 beats 1/N, 08 does not), the generator asserts it with its OWN
computation (numpy only) and fails loudly instead of writing a wrong expectation.

  01_clean_long_only    declared long_only / max_weight 0.10 / sector 0.30 / monthly all satisfied; a planted tilt
                        towards the names with higher drift so the path beats 1/N  -> constraints PASS, the rest INFO
  02_weights_dont_sum   on 3 dates the weights sum to 0.92 with no cash row under long_only -> constraints CONFIRMED_ERROR
  03_max_weight_breach  one name at 14% with max_weight 0.10                       -> constraints CONFIRMED_ERROR
  04_group_limit        one sector at 38% with group_limits sector 0.30             -> constraints CONFIRMED_ERROR
  05_concentrated       3 names hold 90%                                            -> concentration NEEDS_REVIEW
  06_churn              weights re-randomised weekly under a declared monthly rebalance, prices present
                                                                                    -> turnover CONFIRMED_ERROR
  07_positions_mismatch positions imply the weights of other names                  -> weights_vs_positions CONFIRMED_ERROR
  08_optimizer_vs_1n    mean-variance weights from 60-day noisy estimates, no true difference between names
                                                                                    -> vs_naive NEEDS_REVIEW
  09_closet_index       strategy text "active alpha", active share 0.08 vs benchmark_weights -> active_share NEEDS_REVIEW
  10_insufficient       4 weight dates                                              -> vs_naive NOT_EXECUTABLE (not PASS)
  11_drift_not_trading  buy-and-hold weights reported as drifted every month (adversarial: looks like monthly trading,
                        is none)                                                    -> turnover INFO, never an alert
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path
from statistics import NormalDist

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "usecase_portfolio"
N = 20
TICKERS = [f"T{i:02d}" for i in range(1, N + 1)]
SECTORS = ["TECH", "FIN", "HEALTH", "ENERGY"]
SECTOR_OF = {t: SECTORS[i % 4] for i, t in enumerate(TICKERS)}  # interleaved: 5 names per sector
PPY = 252


def weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def month_ends(dates: list[date]) -> list[date]:
    out = []
    for i, d in enumerate(dates):
        if i + 1 == len(dates) or dates[i + 1].month != d.month:
            out.append(d)
    return out


def gbm(rng: np.random.Generator, dates: list[date], drift: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """Close prices (T x N) from daily log-normal returns with annual drift and vol per name."""
    T = len(dates)
    z = rng.standard_normal((T, len(drift)))
    r = drift / PPY - 0.5 * vol ** 2 / PPY + vol / math.sqrt(PPY) * z
    return 100.0 * np.exp(np.cumsum(r, axis=0))


# ------------------------------------------------------------------ independent computation (asserts only)

def simulate(dates: list[date], px: np.ndarray, wdates: list[date], W: np.ndarray) -> np.ndarray:
    """Periodic returns of the weight path: weights dated d enter at the close of the first session after d and
    drift until the next rebalance (same convention as the tool, written independently)."""
    first_after = {}
    for k, d in enumerate(wdates):
        pos = next((i for i, pd_ in enumerate(dates) if pd_ > d), None)
        if pos is not None:
            first_after[pos] = W[k]
    start = min(first_after)
    w = first_after[start].copy()
    out = []
    for i in range(start + 1, len(dates)):
        ratio = px[i] / px[i - 1]
        out.append(float(np.sum(w * (ratio - 1))))
        nav = 1 + float(np.sum(w * (ratio - 1)))
        w = w * ratio / nav
        if i in first_after:
            w = first_after[i].copy()
    return np.array(out)


def jk_memmel_p(r1: np.ndarray, r2: np.ndarray) -> tuple[float, float]:
    T = len(r1)
    s1, s2 = r1.std(ddof=1), r2.std(ddof=1)
    sr1, sr2 = r1.mean() / s1, r2.mean() / s2
    rho = float(np.corrcoef(r1, r2)[0, 1])
    theta = (2 * (1 - rho) + 0.5 * (sr1 ** 2 + sr2 ** 2) - sr1 * sr2 * rho ** 2) / T
    z = (sr1 - sr2) / math.sqrt(theta)
    return z, 1 - NormalDist().cdf(z)


def naive_of(W: np.ndarray) -> np.ndarray:
    held = np.abs(W) > 0
    return held / held.sum(axis=1, keepdims=True)


# ------------------------------------------------------------------ writing

def write(name: str, *, dates, px, wdates, W, rules: str, expected: dict, description: str, sector=True,
          positions=None, benchmark=None, prices=True):
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    with open(c / "weights.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "weight"] + (["sector"] if sector else []))
        for d, row in zip(wdates, W):
            for t, v in zip(TICKERS, row):
                if abs(v) > 0:
                    w.writerow([d.isoformat(), t, f"{v:.8f}"] + ([SECTOR_OF[t]] if sector else []))
    if prices:
        with open(c / "prices.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "close", "adjusted"])
            for i, d in enumerate(dates):
                for j, t in enumerate(TICKERS):
                    w.writerow([d.isoformat(), t, f"{px[i, j]:.4f}", "true"])
    if positions is not None:
        with open(c / "positions.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "quantity"])
            for d, row in positions:
                for t, q in zip(TICKERS, row):
                    if q:
                        w.writerow([d.isoformat(), t, int(q)])
    if benchmark is not None:
        with open(c / "benchmark_weights.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "weight"])
            for d, row in benchmark:
                for t, v in zip(TICKERS, row):
                    w.writerow([d.isoformat(), t, f"{v:.8f}"])
    (c / "rules.yaml").write_text(rules, encoding="utf-8")
    exp = {"description": description, "origin": "usecase", "use_case": "portfolio", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


ALL = ["portfolio_constraints", "portfolio_concentration", "portfolio_turnover", "portfolio_weights_vs_positions",
       "portfolio_vs_naive", "portfolio_active_share"]
NO_ALERTS = [mustnot(c, s) for c in ALL for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")]
RULES_BASE = "conventions:\n  periods_per_year: 252\n  review_date: '2026-10-20'\n"


def rules_with(strategy: str, constraints: dict | None) -> str:
    out = f"strategy: {strategy}\n"
    if constraints:
        out += "constraints:\n  portfolio:\n"
        for k, v in constraints.items():
            if isinstance(v, dict):
                out += f"    {k}:\n" + "".join(f"      {a}: {b}\n" for a, b in v.items())
            elif isinstance(v, list):
                out += f"    {k}: [{', '.join(str(x) for x in v)}]\n"
            else:
                out += f"    {k}: {str(v).lower() if isinstance(v, bool) else v}\n"
    return out + RULES_BASE


DATES = weekdays(date(2023, 1, 2), date(2024, 12, 31))
MONTHLY = month_ends(DATES)  # 24 dates


def tilt_weights(rng: np.random.Generator, n_dates: int, good=0.08, bad=0.02, noise=0.003) -> np.ndarray:
    """10 'good' names at ~8%, 10 at ~2%, small zero-sum monthly noise; sums to 1, max < 0.10, sector < 0.30."""
    base = np.array([good] * 10 + [bad] * 10)
    W = []
    for _ in range(n_dates):
        e = rng.uniform(-noise, noise, N)
        e -= e.mean()
        W.append(base + e)
    W = np.array(W)
    assert np.allclose(W.sum(axis=1), 1.0) and W.max() < 0.10 and W.min() > 0
    for s in SECTORS:
        assert W[:, [SECTOR_OF[t] == s for t in TICKERS]].sum(axis=1).max() < 0.30
    return W


def skill_prices(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    drift = np.array([0.25] * 10 + [-0.05] * 10)
    vol = np.full(N, 0.15)
    return gbm(rng, DATES, drift, vol)


def flat_prices(seed: int, drift=0.05, vol=0.20) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return gbm(rng, DATES, np.full(N, drift), np.full(N, vol))


def c01():
    rng = np.random.default_rng(1)
    px = skill_prices(11)
    W = tilt_weights(rng, len(MONTHLY))
    rp = simulate(DATES, px, MONTHLY, W)
    rn = simulate(DATES, px, MONTHLY, naive_of(W))
    z, p = jk_memmel_p(rp, rn)
    assert p < 0.01, (z, p)  # the planted tilt beats 1/N in this draw
    write("01_clean_long_only", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Long-only quality-tilt model portfolio of 20 names, rebalanced monthly",
                           {"long_only": True, "max_weight": 0.10, "group_limits": {"sector": 0.30},
                            "rebalance_frequency": "monthly"}),
          expected={"must_include": [must("portfolio_constraints", "PASS"), must("portfolio_concentration", "INFO"),
                                     must("portfolio_turnover", "INFO"), must("portfolio_vs_naive", "INFO"),
                                     must("portfolio_weights_vs_positions", "NOT_EXECUTABLE"),
                                     must("portfolio_active_share", "NOT_EXECUTABLE")],
                    "must_not_include": NO_ALERTS, "errors_only_from": [],
                    "comment": f"Jobson-Korkie-Memmel z = {z:.2f}, one-sided p = {p:.4f} computed by the generator."},
          description="24 monthly dates, 20 names, declared long_only / max_weight 0.10 / sector 0.30 / monthly all "
                      "satisfied; weights tilted to the names with higher drift, so the path beats 1/N.")


def c02():
    rng = np.random.default_rng(2)
    px = flat_prices(12)
    W = tilt_weights(rng, len(MONTHLY))
    for k in (5, 11, 17):
        W[k] = W[k] * 0.92
    write("02_weights_dont_sum", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Long-only model portfolio, fully invested", {"long_only": True, "max_weight": 0.10,
                                                                        "rebalance_frequency": "monthly"}),
          expected={"must_include": [must("portfolio_constraints", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("portfolio_constraints", "PASS")],
                    "errors_only_from": ["portfolio_constraints"],
                    "text_must_contain": [{"check": "portfolio_constraints", "text": "sum of weights"}]},
          description="On 3 of 24 dates the weights sum to 0.92 with no cash row under a declared long_only mandate.")


def c03():
    rng = np.random.default_rng(3)
    px = flat_prices(13)
    W = tilt_weights(rng, len(MONTHLY))
    extra = 0.14 - W[:, 0]
    W[:, 0] = 0.14
    W[:, 10:] -= (extra / 10)[:, None]
    assert np.allclose(W.sum(axis=1), 1.0) and W.min() > 0
    write("03_max_weight_breach", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Long-only model portfolio with a 10% single-name cap", {"long_only": True,
                                                                                   "max_weight": 0.10}),
          expected={"must_include": [must("portfolio_constraints", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("portfolio_constraints", "PASS")],
                    "errors_only_from": ["portfolio_constraints"],
                    "text_must_contain": [{"check": "portfolio_constraints", "text": "max_weight"}]},
          description="T01 holds 14% on every date while rules.yaml declares max_weight 0.10.")


def c04():
    px = flat_prices(14)
    tech = np.array([SECTOR_OF[t] == "TECH" for t in TICKERS])
    row = np.where(tech, 0.38 / 5, 0.62 / 15)
    W = np.tile(row, (len(MONTHLY), 1))
    write("04_group_limit", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Long-only sector-constrained model portfolio", {"long_only": True,
                                                                           "group_limits": {"sector": 0.30}}),
          expected={"must_include": [must("portfolio_constraints", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("portfolio_constraints", "PASS")],
                    "errors_only_from": ["portfolio_constraints"],
                    "text_must_contain": [{"check": "portfolio_constraints", "text": "sector"}]},
          description="The TECH sector holds 38% on every date while rules.yaml declares a 30% sector limit.")


def c05():
    px = flat_prices(15)
    row = np.array([0.30, 0.30, 0.30] + [0.10 / 17] * 17)
    W = np.tile(row, (len(MONTHLY), 1))
    h = float((row ** 2).sum())
    assert h > 0.20
    write("05_concentrated", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Concentrated conviction portfolio", None),
          expected={"must_include": [must("portfolio_concentration", "NEEDS_REVIEW"),
                                     must("portfolio_constraints", "INFO")],
                    "must_not_include": [mustnot("portfolio_constraints", "CONFIRMED_ERROR"),
                                         mustnot("portfolio_concentration", "PASS")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "portfolio_concentration", "text": "UCITS"}],
                    "comment": f"HHI {h:.3f} (effective N {1 / h:.1f}); three names above 25% with no declared "
                               "max_weight; also breaches UCITS 5/10/40 (INFO)."},
          description="Three names hold 90% (30% each); nothing declared.")


def c06():
    rng = np.random.default_rng(6)
    px = flat_prices(16)
    weekly = DATES[4::5]  # every 5th session
    W = rng.uniform(0.5, 1.5, (len(weekly), N))
    W = W / W.sum(axis=1, keepdims=True)
    write("06_churn", dates=DATES, px=px, wdates=weekly, W=W,
          rules=rules_with("Long-only model portfolio rebalanced monthly", {"long_only": True,
                                                                           "rebalance_frequency": "monthly"}),
          expected={"must_include": [must("portfolio_turnover", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("portfolio_turnover", "INFO"), mustnot("portfolio_turnover", "PASS")],
                    "errors_only_from": ["portfolio_turnover"],
                    "comment": "Prices are present, so drift is removed and the weekly changes that remain on "
                               "non-rebalance dates are trades outside the declared monthly schedule: CONFIRMED_ERROR "
                               "(without prices the same case would be NEEDS_REVIEW)."},
          description="Weights re-randomised every week (104 dates) under a declared monthly rebalance; prices present.")


def c07():
    rng = np.random.default_rng(7)
    px = flat_prices(17)
    W = tilt_weights(rng, len(MONTHLY))
    pos = []
    for k, d in enumerate(MONTHLY):
        i = DATES.index(d)
        w_other = np.roll(W[k], 10)  # each name gets the weight of another name
        pos.append((d, np.floor(1_000_000 * w_other / px[i])))
    write("07_positions_mismatch", dates=DATES, px=px, wdates=MONTHLY, W=W, positions=pos,
          rules=rules_with("Long-only model portfolio", {"long_only": True}),
          expected={"must_include": [must("portfolio_weights_vs_positions", "CONFIRMED_ERROR"),
                                     must("portfolio_constraints", "PASS")],
                    "must_not_include": [mustnot("portfolio_weights_vs_positions", "PASS")],
                    "errors_only_from": ["portfolio_weights_vs_positions"]},
          description="positions.csv holds, for every name, the weight declared for another name (8% vs 2%): the "
                      "implied weights differ from the declared ones by 6 points on every ticker-date.")


def c08():
    px = flat_prices(18, drift=0.05, vol=0.20)
    rets = px[1:] / px[:-1] - 1
    W = []
    for d in MONTHLY:
        i = DATES.index(d)
        if i < 61:
            W.append(np.full(N, 1.0 / N))
            continue
        R = rets[i - 60:i]
        mu = R.mean(axis=0)
        S = np.cov(R.T) + 1e-6 * np.eye(N)
        w = np.linalg.solve(S, mu)
        w = np.clip(w, 0, None)
        W.append(w / w.sum() if w.sum() > 0 else np.full(N, 1.0 / N))
    W = np.array(W)
    rp = simulate(DATES, px, MONTHLY, W)
    rn = simulate(DATES, px, MONTHLY, naive_of(W))
    z, p = jk_memmel_p(rp, rn)
    assert p >= 0.05, (z, p)  # the optimiser does not beat 1/N in this draw
    write("08_optimizer_vs_1n", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Mean-variance optimised portfolio re-estimated monthly on a 60-day window", None),
          expected={"must_include": [must("portfolio_vs_naive", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("portfolio_vs_naive", "INFO"), mustnot("portfolio_vs_naive", "PASS")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "portfolio_vs_naive", "text": "1/N"}],
                    "comment": f"Jobson-Korkie-Memmel z = {z:.2f}, one-sided p = {p:.3f} by the generator. The names "
                               "share the same true drift and vol, so the optimiser only fits noise; concentration and "
                               "turnover may also be review items (not planted, not forbidden)."},
          description="Long-only mean-variance weights from 60-day sample means and covariances, 20 names with "
                      "identical true drift: out of sample the optimiser does not beat 1/N.")


def c09():
    px = flat_prices(19)
    bw = np.arange(N, 0, -1) / (N * (N + 1) / 2)  # cap-like benchmark weights
    tilt = np.array([-0.008] * 10 + [0.008] * 10)  # underweight the large names, overweight the small
    W = np.tile(bw + tilt, (len(MONTHLY), 1))
    assert abs(0.5 * np.abs(W[0] - bw).sum() - 0.08) < 1e-9 and W.min() > 0
    write("09_closet_index", dates=DATES, px=px, wdates=MONTHLY, W=W, benchmark=[(d, bw) for d in MONTHLY],
          rules=rules_with("Active alpha-seeking equity portfolio with conviction stock picking", None),
          expected={"must_include": [must("portfolio_active_share", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("portfolio_active_share", "INFO"),
                                         mustnot("portfolio_active_share", "PASS")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "portfolio_active_share", "text": "Closet"}]},
          description="Strategy text says active alpha; the weights are the benchmark weights plus a 0.8-point tilt: "
                      "active share 0.08 on every date.")


def c10():
    rng = np.random.default_rng(10)
    sub_dates = [d for d in DATES if d >= date(2024, 9, 1)]
    px_full = flat_prices(20)
    px = px_full[[DATES.index(d) for d in sub_dates]]
    wd = month_ends(sub_dates)
    assert len(wd) == 4
    W = tilt_weights(rng, 4)
    write("10_insufficient", dates=sub_dates, px=px, wdates=wd, W=W,
          rules=rules_with("Model portfolio, short history", None),
          expected={"must_include": [must("portfolio_vs_naive", "NOT_EXECUTABLE"), must("portfolio_turnover", "INFO"),
                                     must("portfolio_weights_vs_positions", "NOT_EXECUTABLE"),
                                     must("portfolio_active_share", "NOT_EXECUTABLE")],
                    "must_not_include": [mustnot("portfolio_vs_naive", "PASS"), mustnot("portfolio_vs_naive", "INFO"),
                                         mustnot("portfolio_vs_naive", "NEEDS_REVIEW")],
                    "errors_only_from": []},
          description="Only 4 weight dates (below portfolio_min_dates 12): the comparison with 1/N must not run.")


def c11():
    px = flat_prices(21)
    w0 = np.array([0.08] * 5 + [0.06] * 5 + [0.04] * 5 + [0.02] * 5)
    i0 = DATES.index(MONTHLY[0])
    W = []
    for d in MONTHLY:
        i = DATES.index(d)
        w = w0 * px[i] / px[i0]
        W.append(np.round(w / w.sum(), 8))
    W = np.array(W)
    raw_turnover = 0.5 * np.abs(np.diff(W, axis=0)).sum(axis=1)
    assert raw_turnover.max() > 0.01  # looks like trading every month without the drift correction
    write("11_drift_not_trading", dates=DATES, px=px, wdates=MONTHLY, W=W,
          rules=rules_with("Buy-and-hold model portfolio; weights reported monthly at market value",
                           {"long_only": True, "rebalance_frequency": "annual"}),
          expected={"must_include": [must("portfolio_turnover", "INFO"), must("portfolio_constraints", "PASS")],
                    "must_not_include": [mustnot("portfolio_turnover", "NEEDS_REVIEW"),
                                         mustnot("portfolio_turnover", "CONFIRMED_ERROR")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "portfolio_turnover", "text": "net of drift"}],
                    "comment": f"Raw monthly turnover up to {raw_turnover.max():.3f} without the drift correction; "
                               "with prices it is ~0 on every date."},
          description="Buy-and-hold book whose weights are reported every month at market value (they drift with "
                      "prices); declared annual rebalance. Adversarial: looks like monthly trading, is none.")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for fn in (c01, c02, c03, c04, c05, c06, c07, c08, c09, c10, c11):
        fn()
    print(f"written {len(list(OUT.iterdir()))} cases in {OUT}")
