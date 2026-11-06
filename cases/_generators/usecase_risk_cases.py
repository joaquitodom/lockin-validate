"""Cases of the ``risk`` use case (cases/usecase_risk/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/usecase_risk_cases.py

Each case plants a property of the VaR / ES forecasts with a known consequence and writes expected.json from that
property BEFORE the tool runs. Where a random draw could contradict the planted property, the generator asserts it
with its OWN computation (pure Python) and fails loudly instead of writing a wrong expectation.

  01_clean_normal          correct 95/99% VaR and ES for a normal P&L with slowly varying volatility, 1000 days
  02_too_many_exceptions   the same, VaR and ES scaled by 0.7
  03_clustered_exceptions  volatility regimes (two high-vol episodes) with a constant VaR
  04_too_conservative      VaR scaled by 2: no exception in 1000 days
  05_es_underestimated     Student-t(3) P&L with the right VaR but ES = 1.05 x VaR
  06_quantile_crossing     clean case with var_95 > var_99 on 12 days
  07_insufficient          120 days only
  08_sign_inverted         clean model delivered as negative P&L quantiles (looks wrong, is legitimate: adversarial)
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
OUT = HERE.parent / "usecase_risk"
Z99, Z95 = 2.3263478740, 1.6448536270  # standard normal quantiles
ES99, ES95 = 2.6652142, 2.0627128  # phi(z) / p: normal ES multipliers
RULES = ("strategy: synthetic VaR backtest for the risk use case\nrisk:\n  horizon_days: 1\n  confidence: 0.99\n"
         "  window: 250\nconventions:\n  review_date: '2026-10-30'\n  risk_var_sign: positive_loss\n")


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------------- independent statistics (pure Python)

def xlogy(x, y):
    return 0.0 if x == 0 else x * math.log(y)


def kupiec(x, n, p):
    pi = x / n
    return -2 * (xlogy(n - x, 1 - p) + xlogy(x, p)) + 2 * (xlogy(n - x, 1 - pi) + xlogy(x, pi))


def christoffersen(h):
    n00 = n01 = n10 = n11 = 0
    for a, b in zip(h[:-1], h[1:]):
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    pi01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll0 = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    ll1 = xlogy(n00, 1 - pi01) + xlogy(n01, pi01) + xlogy(n10, 1 - pi11) + xlogy(n11, pi11)
    return -2 * ll0 + 2 * ll1


CHI2_1_95 = 3.841459  # chi-square(1) 95% quantile


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1])


def rolling_vol(pnl, w=20):
    out = np.full(len(pnl), np.nan)
    for i in range(w - 1, len(pnl)):
        out[i] = np.std(pnl[i - w + 1:i + 1], ddof=1)
    return out


# --------------------------------------------------------------------------- writing

def write(name, *, dates, pnl, cols: dict, expected: dict, description: str, rules: str = RULES, pnl_name="pnl"):
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    with open(c / "var_forecasts.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", pnl_name] + list(cols) + ["model"])
        for i, d in enumerate(dates):
            w.writerow([d.isoformat(), f"{pnl[i]:.8f}"] + [f"{cols[k][i]:.8f}" for k in cols] + ["synthetic"])
    (c / "rules.yaml").write_text(rules, encoding="utf-8")
    exp = {"description": description, "origin": "usecase", "use_case": "risk", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


ALL = ["var_input_coherence", "var_coverage", "var_independence", "basel_traffic_light", "es_backtest",
       "var_model_stability"]


def clean_model(seed=11, T=1000):
    """Normal P&L with a slowly varying volatility and the exact VaR / ES of that volatility."""
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    sigma = 0.01 * (1 + 0.35 * np.sin(2 * math.pi * t / 250))
    pnl = rng.normal(0.0, 1.0, T) * sigma
    return pnl, sigma


def c01():
    pnl, sigma = clean_model()
    T = len(pnl)
    h99 = (-pnl > Z99 * sigma).astype(int)
    h95 = (-pnl > Z95 * sigma).astype(int)
    x99, x95 = int(h99.sum()), int(h95.sum())
    assert kupiec(x99, T, 0.01) < CHI2_1_95 and kupiec(x95, T, 0.05) < CHI2_1_95, (x99, x95)
    assert christoffersen(h99) < CHI2_1_95 and christoffersen(h95) < CHI2_1_95
    assert kupiec(x99, T, 0.01) + christoffersen(h99) < 5.991 and kupiec(x95, T, 0.05) + christoffersen(h95) < 5.991
    assert max(len(s) for s in "".join(map(str, h99)).split("0")) < 3
    assert int(h99[-250:].sum()) <= 4, int(h99[-250:].sum())
    assert corr(Z99 * sigma, rolling_vol(pnl)) > 0.3
    assert x99 >= 5 and x95 >= 5
    write("01_clean_normal", dates=weekdays(date(2021, 1, 4), T), pnl=pnl,
          cols={"var_99": Z99 * sigma, "var_95": Z95 * sigma, "es_99": ES99 * sigma, "es_95": ES95 * sigma},
          expected={"must_include": [must("var_input_coherence", "PASS"), must("var_coverage", "PASS"),
                                     must("var_independence", "PASS"), must("basel_traffic_light", "INFO"),
                                     must("es_backtest", "INFO", "NOT_EXECUTABLE"),
                                     must("var_model_stability", "INFO")],
                    "must_not_include": [mustnot(c, s) for c in ALL for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")],
                    "errors_only_from": [],
                    "comment": f"{x99} exceptions at 99% and {x95} at 95% in {T} days; {int(h99[-250:].sum())} in "
                               "the last 250 (green)."},
          description="Correct 95% and 99% VaR and ES for a normal P&L with slowly varying volatility, 1000 days.")


def c02():
    pnl, sigma = clean_model(seed=22)
    T = len(pnl)
    v99 = 0.7 * Z99 * sigma
    h99 = (-pnl > v99).astype(int)
    x99 = int(h99.sum())
    assert kupiec(x99, T, 0.01) > CHI2_1_95 and x99 / T > 0.01, x99
    assert int(h99[-250:].sum()) >= 5, int(h99[-250:].sum())
    write("02_too_many_exceptions", dates=weekdays(date(2021, 1, 4), T), pnl=pnl,
          cols={"var_99": v99, "var_95": 0.7 * Z95 * sigma, "es_99": 0.7 * ES99 * sigma},
          expected={"must_include": [must("var_coverage", "NEEDS_REVIEW"), must("basel_traffic_light", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("var_coverage", "PASS"), mustnot("basel_traffic_light", "INFO"),
                                         mustnot("var_input_coherence", "CONFIRMED_ERROR")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "var_coverage", "text": "too many"}],
                    "comment": f"{x99} exceptions at 99% in {T} days; {int(h99[-250:].sum())} in the last 250."},
          description="VaR and ES scaled by 0.7: about 5% of days breach the 99% VaR; the traffic light is yellow or red.")


def c03():
    rng = np.random.default_rng(33)
    T = 1000
    sigma = np.full(T, 0.005)
    sigma[300:400] = 0.035
    sigma[700:800] = 0.035
    pnl = rng.normal(0.0, 1.0, T) * sigma
    v99 = np.full(T, Z99 * 0.009)  # one unconditional number for the whole sample
    h99 = (-pnl > v99).astype(int)
    x99 = int(h99.sum())
    assert x99 >= 5 and christoffersen(h99) > CHI2_1_95, (x99, christoffersen(h99))
    write("03_clustered_exceptions", dates=weekdays(date(2021, 1, 4), T), pnl=pnl, cols={"var_99": v99},
          expected={"must_include": [must("var_independence", "NEEDS_REVIEW"), must("var_model_stability", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("var_independence", "PASS"), mustnot("var_model_stability", "INFO"),
                                         mustnot("var_input_coherence", "CONFIRMED_ERROR")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "var_model_stability", "text": "does not respond to volatility"}],
                    "comment": f"{x99} exceptions, all inside the two high-volatility episodes; LR_ind = "
                               f"{christoffersen(h99):.1f}."},
          description="Two high-volatility episodes with a constant VaR: exceptions cluster and the VaR ignores volatility.")


def c04():
    pnl, sigma = clean_model(seed=44)
    T = len(pnl)
    v99 = 2.0 * Z99 * sigma
    x99 = int((-pnl > v99).sum())
    assert kupiec(x99, T, 0.01) > CHI2_1_95 and x99 / T < 0.01, x99
    write("04_too_conservative", dates=weekdays(date(2021, 1, 4), T), pnl=pnl,
          cols={"var_99": v99, "var_95": 2.0 * Z95 * sigma},
          expected={"must_include": [must("var_coverage", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("var_coverage", "PASS"), mustnot("var_input_coherence", "CONFIRMED_ERROR")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "var_coverage", "text": "too few"}],
                    "comment": f"{x99} exceptions at 99% in {T} days (expected 10)."},
          description="VaR scaled by 2: the model is never breached; Kupiec rejects on the conservative side.")


def c05():
    rng = np.random.default_rng(55)
    T = 2000
    scale = 0.006
    pnl = rng.standard_t(3, T) * scale
    q99 = 4.5407  # Student-t(3) 99% quantile
    v99 = np.full(T, q99 * scale)
    es99 = 1.05 * v99
    exc = -pnl > v99
    x = int(exc.sum())
    mean_loss = float((-pnl[exc]).mean())
    assert x >= 10, x
    assert mean_loss / (1.05 * q99 * scale) > 1.25, mean_loss / (1.05 * q99 * scale)
    assert kupiec(x, T, 0.01) < CHI2_1_95, x  # the VaR itself is right: only the ES is wrong
    write("05_es_underestimated", dates=weekdays(date(2017, 1, 2), T), pnl=pnl,
          cols={"var_99": v99, "es_99": es99},
          expected={"must_include": [must("es_backtest", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("es_backtest", "INFO"), mustnot("es_backtest", "NOT_EXECUTABLE"),
                                         mustnot("var_input_coherence", "CONFIRMED_ERROR")],
                    "errors_only_from": [],
                    "comment": f"{x} exceptions; mean loss on exception days / ES = "
                               f"{mean_loss / (1.05 * q99 * scale):.2f} (the true t(3) ES / VaR ratio is about 1.54)."},
          description="Student-t(3) P&L with the correct 99% VaR but an ES fixed at 1.05 x VaR: the tail beyond the VaR is "
                      "under-estimated.")


def c06():
    pnl, sigma = clean_model(seed=66)
    T = len(pnl)
    v99 = Z99 * sigma
    v95 = Z95 * sigma.copy()
    bad = list(range(100, 1000, 75))[:12]
    v95[bad] = v99[bad] * 1.2  # the 95% VaR above the 99% VaR on 12 days
    write("06_quantile_crossing", dates=weekdays(date(2021, 1, 4), T), pnl=pnl, cols={"var_99": v99, "var_95": v95},
          expected={"must_include": [must("var_input_coherence", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("var_input_coherence", "PASS")],
                    "errors_only_from": ["var_input_coherence"],
                    "text_must_contain": [{"check": "var_input_coherence", "text": "monotonicity"}],
                    "comment": f"var_95 > var_99 on {len(bad)} days."},
          description="Clean model with var_95 > var_99 on 12 days: quantile monotonicity violated.")


def c07():
    pnl, sigma = clean_model(seed=77, T=120)
    T = len(pnl)
    write("07_insufficient", dates=weekdays(date(2026, 1, 5), T), pnl=pnl,
          cols={"var_99": Z99 * sigma, "es_99": ES99 * sigma},
          expected={"must_include": [must("var_coverage", "NOT_EXECUTABLE"), must("var_independence", "NOT_EXECUTABLE"),
                                     must("basel_traffic_light", "NOT_EXECUTABLE"),
                                     must("es_backtest", "NOT_EXECUTABLE"),
                                     must("var_model_stability", "NOT_EXECUTABLE")],
                    "must_not_include": [mustnot(c, "PASS") for c in ALL if c != "var_input_coherence"]
                    + [mustnot(c, "NEEDS_REVIEW") for c in ALL],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "var_coverage", "text": "120"}]},
          description="120 days only: below the minimum of 250 observations, the tests are not executable.")


def c08():
    pnl, sigma = clean_model(seed=88)
    T = len(pnl)
    h99 = (-pnl > Z99 * sigma).astype(int)
    h95 = (-pnl > Z95 * sigma).astype(int)
    x99, x95 = int(h99.sum()), int(h95.sum())
    assert kupiec(x99, T, 0.01) < CHI2_1_95 and kupiec(x95, T, 0.05) < CHI2_1_95, (x99, x95)
    assert christoffersen(h99) < CHI2_1_95 and christoffersen(h95) < CHI2_1_95
    assert kupiec(x99, T, 0.01) + christoffersen(h99) < 5.991 and kupiec(x95, T, 0.05) + christoffersen(h95) < 5.991
    assert max(len(s) for s in "".join(map(str, h99)).split("0")) < 3
    assert x99 >= 5 and x95 >= 5
    write("08_sign_inverted", dates=weekdays(date(2021, 1, 4), T), pnl=pnl,
          cols={"var_99": -Z99 * sigma, "var_95": -Z95 * sigma, "es_99": -ES99 * sigma},
          expected={"must_include": [must("var_input_coherence", "INFO"), must("var_coverage", "PASS"),
                                     must("var_independence", "PASS")],
                    "must_not_include": [mustnot("var_input_coherence", "CONFIRMED_ERROR"),
                                         mustnot("var_coverage", "NEEDS_REVIEW"), mustnot("var_coverage", "NOT_EXECUTABLE")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "var_input_coherence", "text": "negative_quantile"}],
                    "comment": f"{x99} exceptions at 99% and {x95} at 95% once the sign is read correctly."},
          description="A correct model delivered as negative P&L quantiles while rules.yaml declares positive_loss: the sign "
                      "must be auto-detected (INFO) and the coverage test must still pass.")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (c01, c02, c03, c04, c05, c06, c07, c08):
        f()
        print("generated", f.__name__)


if __name__ == "__main__":
    main()
