"""Cases of the ``signals`` use case (cases/usecase_signals/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/usecase_signals_cases.py

Each case plants a property of an alpha signal and fixes expected.json from that property BEFORE the tool runs.
Where a random draw could contradict the planted property, the generator asserts it with its OWN computation
(numpy only) and fails loudly instead of writing a case whose expectation would be wrong.

Universe: 40 tickers x 300 weekday sessions (prices.csv), one signal per (session, ticker) from the third session.
Alignment convention of the module (default lag 1): a decision dated t enters at close(t + 1) and the h = 1
forward return is close(t + 2) / close(t + 1) - 1, i.e. the return of session t + 2.

  01_clean_predictive     AR(1) signal (rho 0.9) that drives the return two sessions later (IC about 0.08)
                          -> signal_predictive_power INFO, nothing in NEEDS_REVIEW
  02_noise_signal         iid signal, iid returns                   -> predictive_power and quantile_spread NEEDS_REVIEW
  03_lookahead_same_close signal = the decision session's own return -> signal_lookahead_hint NEEDS_REVIEW
  04_high_turnover        signal re-drawn every session, horizons [21, 42] declared -> signal_turnover NEEDS_REVIEW
  05_short_leg_only       only the bottom quintile earns (negative) returns, short_selling false
                          -> signal_quantile_spread NEEDS_REVIEW (long-leg share)
  06_insufficient         3 decision dates                           -> everything NOT_EXECUTABLE except alignment
  07_single_asset         one ticker, predictive through time        -> predictive_power INFO or NEEDS_REVIEW (never
                                                                        NOT_EXECUTABLE, never raises)
  08_lag_zero_off_session lag 0 declared and decisions dated on Saturdays -> signal_forward_alignment CONFIRMED_ERROR
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
OUT = HERE.parent / "usecase_signals"
N_TICKERS = 40
N_SESSIONS = 300
EPS = 0.02  # daily idiosyncratic volatility
CHECKS = ["signal_forward_alignment", "signal_predictive_power", "signal_quantile_spread", "signal_turnover",
          "signal_lookahead_hint"]


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def tickers(n: int) -> list[str]:
    return [f"T{i:02d}" for i in range(n)]


# ------------------------------------------------------------------ own statistics (independent of the tool)

def ranks(x: np.ndarray) -> np.ndarray:
    r = np.empty(len(x))
    r[np.argsort(x)] = np.arange(1, len(x) + 1)
    return r


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(ranks(x), ranks(y))[0, 1])


def tstat(v: np.ndarray) -> float:
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def ic_series(S: np.ndarray, R: np.ndarray, offset: int) -> np.ndarray:
    """Per-date Spearman between S[t] and R[t + offset] (cross-section over the second axis)."""
    T = S.shape[0]
    return np.array([spearman(S[t], R[t + offset]) for t in range(T) if 0 <= t + offset < T])


def bucket_means(S: np.ndarray, R: np.ndarray, offset: int, q: int = 5) -> np.ndarray:
    T, N = S.shape
    per = []
    for t in range(T):
        if not 0 <= t + offset < T:
            continue
        b = np.ceil(ranks(S[t]) * q / N).astype(int)
        per.append([R[t + offset][b == k].mean() for k in range(1, q + 1)])
    return np.array(per)


# ------------------------------------------------------------------ writing

def write_case(name: str, *, dates, tick, closes, signals, conventions: dict, rules_extra: str = "",
               expected: dict, description: str, decision_dates=None, signal_from: int = 2):
    """closes: (T, N) array; signals: (T, N) array (NaN = no signal); decision_dates: per-session label override."""
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    with open(c / "prices.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "close"])
        for t, d in enumerate(dates):
            for i, tk in enumerate(tick):
                w.writerow([d.isoformat(), tk, f"{closes[t, i]:.4f}"])
    with open(c / "signals.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["decision_time", "ticker", "signal"])
        for t in range(signal_from, len(dates)):
            lab = (decision_dates[t] if decision_dates is not None else dates[t]).isoformat()
            for i, tk in enumerate(tick):
                if np.isfinite(signals[t, i]):
                    w.writerow([lab, tk, f"{signals[t, i]:.6f}"])
    conv_lines = "".join(f"  {k}: {json.dumps(v)}\n" for k, v in conventions.items())
    rules = ("strategy: alpha signal under research (no trades yet)\n"
             "signal:\n  column: signal\n  order: desc\n  description: score known at the decision date\n"
             + rules_extra +
             "conventions:\n  periods_per_year: 252\n  review_date: '2026-10-20'\n  short_selling: false\n" + conv_lines)
    (c / "rules.yaml").write_text(rules, encoding="utf-8")
    exp = {"description": description, "origin": "usecase", "use_case": "signals", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


def to_closes(R: np.ndarray) -> np.ndarray:
    return 100.0 * np.cumprod(1.0 + R, axis=0)


def ar1(rng, T: int, N: int, rho: float) -> np.ndarray:
    S = np.empty((T, N))
    S[0] = rng.normal(0, 1, N)
    sd = math.sqrt(1 - rho * rho)
    for t in range(1, T):
        S[t] = rho * S[t - 1] + rng.normal(0, sd, N)
    return S


def lagged(S: np.ndarray, k: int) -> np.ndarray:
    """L[u] = S[u - k] (zeros before)."""
    L = np.zeros_like(S)
    L[k:] = S[:-k]
    return L


# ------------------------------------------------------------------ cases

def c01():
    rng = np.random.default_rng(3101)
    T, N = N_SESSIONS, N_TICKERS
    S = ar1(rng, T, N, 0.9)
    c = 0.0016
    R = c * lagged(S, 2) + rng.normal(0, EPS, (T, N))
    ic1 = ic_series(S, R, 2)  # h = 1 under lag 1: return of session t + 2
    assert ic1.mean() > 0.03 and tstat(ic1) > 3.0, (ic1.mean(), tstat(ic1))
    ic0 = ic_series(S, R, 0)
    assert abs(ic0.mean()) < 3 * abs(ic1.mean()), (ic0.mean(), ic1.mean())
    bm = bucket_means(S, R, 2)
    spread = bm[:, -1] - bm[:, 0]
    assert tstat(spread) > 2.5 and spearman(np.arange(5.0), bm.mean(axis=0)) >= 0.8, (tstat(spread), bm.mean(axis=0))
    write_case("01_clean_predictive", dates=weekdays(date(2023, 1, 2), T), tick=tickers(N), closes=to_closes(R),
               signals=S, conventions={},
               expected={"profile": "signal_research",
                         "must_include": [must("signal_forward_alignment", "PASS"),
                                          must("signal_predictive_power", "INFO"),
                                          must("signal_quantile_spread", "INFO"),
                                          must("signal_turnover", "INFO"),
                                          must("signal_lookahead_hint", "INFO")],
                         "must_not_include": [mustnot(ch, s) for ch in CHECKS for s in ("NEEDS_REVIEW", "CONFIRMED_ERROR")],
                         "errors_only_from": [],
                         "comment": f"Planted IC at h=1 about {ic1.mean():.3f} (t {tstat(ic1):.1f}); persistent signal "
                                    "(rank autocorrelation about 0.9), so turnover is low and no horizon flips sign."},
               description="Persistent AR(1) signal that drives the return two sessions after the decision: a genuine, "
                           "modest, decaying alpha. Nothing should be flagged.")


def c02():
    rng = np.random.default_rng(3102)
    T, N = N_SESSIONS, N_TICKERS
    S = rng.normal(0, 1, (T, N))
    R = rng.normal(0, EPS, (T, N))
    ic1 = ic_series(S, R, 2)
    assert abs(tstat(ic1)) < 2.0, tstat(ic1)
    bm = bucket_means(S, R, 2)
    spread = bm[:, -1] - bm[:, 0]
    assert tstat(spread) < 2.0 or spearman(np.arange(5.0), bm.mean(axis=0)) < 0.6, tstat(spread)
    write_case("02_noise_signal", dates=weekdays(date(2023, 1, 2), T), tick=tickers(N), closes=to_closes(R),
               signals=S, conventions={},
               expected={"must_include": [must("signal_predictive_power", "NEEDS_REVIEW"),
                                          must("signal_quantile_spread", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("signal_predictive_power", "INFO"),
                                              mustnot("signal_predictive_power", "PASS")],
                         "errors_only_from": [],
                         "comment": f"Noise: IC t-stat at h=1 is {tstat(ic1):.2f}, spread t-stat {tstat(spread):.2f}."},
               description="Pure-noise signal on pure-noise returns: no predictive power and no quantile spread.")


def c03():
    rng = np.random.default_rng(3103)
    T, N = N_SESSIONS, N_TICKERS
    R = rng.normal(0, EPS, (T, N))
    S = 100.0 * R + rng.normal(0, 0.05, (T, N))  # the score IS the decision session's return
    ic0 = ic_series(S, R, 0)
    ic1 = ic_series(S, R, 2)
    assert ic0.mean() > 0.9 and abs(ic1.mean()) < 0.1, (ic0.mean(), ic1.mean())
    write_case("03_lookahead_same_close", dates=weekdays(date(2023, 1, 2), T), tick=tickers(N), closes=to_closes(R),
               signals=S, conventions={},
               expected={"must_include": [must("signal_lookahead_hint", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("signal_lookahead_hint", "INFO"),
                                              mustnot("signal_predictive_power", "INFO")],
                         "errors_only_from": [],
                         "comment": f"IC with the same-session return {ic0.mean():.2f} vs {ic1.mean():+.3f} at h=1."},
               description="Adversarial: the alignment is formally correct (lag 1), but the score is the return of the "
                           "decision session itself, i.e. it was computed with that session's close. The IC at h=0 "
                           "dwarfs the IC at h=1.")


def c04():
    rng = np.random.default_rng(3104)
    T, N = N_SESSIONS, N_TICKERS
    S = rng.normal(0, 1, (T, N))
    R = rng.normal(0, EPS, (T, N))
    ac = np.array([spearman(S[t], S[t + 1]) for t in range(T - 1)])
    assert abs(ac.mean()) < 0.2, ac.mean()
    write_case("04_high_turnover", dates=weekdays(date(2023, 1, 2), T), tick=tickers(N), closes=to_closes(R),
               signals=S, conventions={"signal_horizons": [21, 42]},
               rules_extra="rebalance:\n  frequency: monthly\n  timing: first_day\n",
               expected={"must_include": [must("signal_turnover", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("signal_turnover", "INFO")],
                         "errors_only_from": [],
                         "comment": f"Lag-1 rank autocorrelation {ac.mean():+.2f} with a 21-session primary horizon and a "
                                    "monthly rebalance declared."},
               description="Signal re-drawn independently every session while the declared horizons are 21 and 42 "
                           "sessions and the rebalance is monthly: the signal cannot be held for its horizon.")


def c05():
    rng = np.random.default_rng(3105)
    T, N = N_SESSIONS, N_TICKERS
    S = rng.normal(0, 1, (T, N))
    bottom = np.zeros((T, N))
    for t in range(T):
        bottom[t] = ranks(S[t]) <= N / 5
    c = 0.004
    R = -c * lagged(bottom, 2) + rng.normal(0, EPS, (T, N))
    bm = bucket_means(S, R, 2)
    m = bm.mean(axis=0)
    spread = bm[:, -1] - bm[:, 0]
    long_share = (m[-1] - m[1:-1].mean()) / (m[-1] - m[0])
    assert tstat(spread) > 3.0 and long_share < 0.15, (tstat(spread), long_share)
    write_case("05_short_leg_only", dates=weekdays(date(2023, 1, 2), T), tick=tickers(N), closes=to_closes(R),
               signals=S, conventions={},
               expected={"must_include": [must("signal_quantile_spread", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("signal_quantile_spread", "INFO")],
                         "text_must_contain": [{"check": "signal_quantile_spread", "text": "long leg"}],
                         "errors_only_from": [],
                         "comment": f"Spread t-stat {tstat(spread):.1f} but the long leg contributes {long_share:.0%} of it; "
                                    "rules.yaml declares short_selling: false."},
               description="Only the bottom quintile earns a (negative) return: the top-minus-bottom spread is large and "
                           "significant but comes entirely from the short leg, which a long-only book cannot hold.")


def c06():
    rng = np.random.default_rng(3106)
    T, N = 60, N_TICKERS
    S = rng.normal(0, 1, (T, N))
    S[:20] = np.nan
    S[23:] = np.nan  # decision dates: sessions 20, 21, 22 only
    R = rng.normal(0, EPS, (T, N))
    write_case("06_insufficient", dates=weekdays(date(2023, 1, 2), T), tick=tickers(N), closes=to_closes(R),
               signals=S, conventions={},
               expected={"must_include": [must("signal_forward_alignment", "PASS", "INFO"),
                                          must("signal_predictive_power", "NOT_EXECUTABLE"),
                                          must("signal_quantile_spread", "NOT_EXECUTABLE"),
                                          must("signal_turnover", "NOT_EXECUTABLE"),
                                          must("signal_lookahead_hint", "NOT_EXECUTABLE")],
                         "must_not_include": [mustnot("signal_predictive_power", "PASS"),
                                              mustnot("signal_predictive_power", "INFO"),
                                              mustnot("signal_predictive_power", "NEEDS_REVIEW"),
                                              mustnot("signal_quantile_spread", "INFO"),
                                              mustnot("signal_turnover", "INFO")],
                         "errors_only_from": []},
               description="Three decision dates with a full cross-section: the rows align, but no statistic can be "
                           "concluded (signal_min_periods = 24).")


def c07():
    rng = np.random.default_rng(3107)
    T, N = N_SESSIONS, 1
    S = ar1(rng, T, N, 0.8)
    c = 0.004
    R = c * lagged(S, 2) + rng.normal(0, EPS, (T, N))
    rho = float(np.corrcoef(ranks(S[:-2, 0]), ranks(R[2:, 0]))[0, 1])
    assert rho > 0.1, rho
    write_case("07_single_asset", dates=weekdays(date(2023, 1, 2), T), tick=["ONLY"], closes=to_closes(R),
               signals=S, conventions={},
               expected={"must_include": [must("signal_predictive_power", "NEEDS_REVIEW", "INFO"),
                                          must("signal_quantile_spread", "NOT_EXECUTABLE"),
                                          must("signal_turnover", "NOT_EXECUTABLE"),
                                          must("signal_lookahead_hint", "NEEDS_REVIEW", "INFO")],
                         "must_not_include": [mustnot("signal_predictive_power", "NOT_EXECUTABLE"),
                                              mustnot("signal_predictive_power", "PASS")],
                         "errors_only_from": [],
                         "comment": f"Time-series Spearman between the signal and the return two sessions later: {rho:.2f}."},
               description="A single asset: there is no cross-section, so the predictive power must be computed as a "
                           "time-series correlation (and said so), the quantile and turnover checks cannot run, and "
                           "nothing may raise.")


def c08():
    rng = np.random.default_rng(3108)
    T, N = N_SESSIONS, N_TICKERS
    S = ar1(rng, T, N, 0.9)
    R = 0.0012 * lagged(S, 2) + rng.normal(0, EPS, (T, N))
    dates = weekdays(date(2023, 1, 2), T)
    labels = [d + timedelta(days=1) if d.weekday() == 4 else d for d in dates]  # Friday decisions dated Saturday
    write_case("08_lag_zero_off_session", dates=dates, tick=tickers(N), closes=to_closes(R), signals=S,
               conventions={"signal_lag_sessions": 0}, decision_dates=labels,
               expected={"must_include": [must("signal_forward_alignment", "CONFIRMED_ERROR")],
                         "errors_only_from": ["signal_forward_alignment"]},
               description="rules.yaml declares signal_lag_sessions: 0 (entry at the decision session's close) but one "
                           "decision in five is dated on a Saturday: its entry would be Monday's close, a price that was "
                           "not known at the decision.")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (c01, c02, c03, c04, c05, c06, c07, c08):
        fn()
    print(f"written: {OUT}")
