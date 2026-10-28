"""Statistical cases (cases/statistical/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/statistical_cases.py

Each case plants a property with a known theoretical consequence and fixes expected.json from that theory before
the tool runs. Where a random draw could, with small probability, contradict the planted property, the generator
asserts the property with its OWN computation (pure Python, independent of the tool) and fails loudly instead of
silently writing a case whose expectation would be wrong.

  S01  best of 200 pure-noise strategies, 200 trials declared and logged      -> deflated_sharpe / multiple_testing /
                                                                                 pbo NEEDS_REVIEW
  S02  genuine signal: best of 20 configurations with real, dispersed Sharpe  -> deflated_sharpe / multiple_testing /
                                                                                 pbo / sharpe_significance PASS
  S03  AR(1) returns (phi = 0.6), as from smoothed marks                      -> sharpe_autocorrelation NEEDS_REVIEW
  S04  5 trials declared, 50 in the log                                       -> trials_declared CONFIRMED_ERROR
  S05  best of 100 noise strategies, number of trials NOT declared            -> trials_declared NEEDS_REVIEW,
                                                                                 deflated_sharpe and pbo NEEDS_REVIEW
  S06  LLM-driven strategy evaluated before the model's training cutoff       -> llm_lookahead_risk NEEDS_REVIEW
  S07  short track record (6 months) of a modest true Sharpe                  -> sharpe_significance NEEDS_REVIEW
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np

import expectation_changes  # noqa: E402  (sibling module: docs/CASE_CHANGES.md, 0.2.0)

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "statistical"
PPY = 252


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def sharpe(x) -> float:
    x = list(x)
    m = sum(x) / len(x)
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))
    return m / sd


def write(name: str, *, dates, returns, trials=None, n_trials=None, llm=None, expected: dict, description: str):
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    with open(c / "returns.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "return"])
        for d, r in zip(dates, returns):
            w.writerow([d.isoformat(), f"{r:.10f}"])
    if trials is not None:
        with open(c / "trials.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date"] + [f"config_{j + 1:03d}" for j in range(trials.shape[1])])
            for i, d in enumerate(dates):
                w.writerow([d.isoformat()] + [f"{v:.10f}" for v in trials[i]])
    decl = {"comment": "declared by the strategy owner"}
    if n_trials is not None:
        decl["n_trials"] = n_trials
    (c / "declared_results.json").write_text(json.dumps(decl, indent=2), encoding="utf-8")
    rules = ("strategy: synthetic return series for statistical checks\nconventions:\n  periods_per_year: 252\n"
             "  review_date: '2026-10-20'\n")
    (c / "rules.yaml").write_text(rules, encoding="utf-8")
    if llm is not None:
        (c / "llm_checklist.json").write_text(json.dumps(llm, indent=2), encoding="utf-8")
    exp = {"description": description, "origin": "statistical", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


def s01():
    rng = np.random.default_rng(101)
    T, N = 1000, 200
    M = rng.normal(0.0, 0.01, (T, N))
    srs = [sharpe(M[:, j]) for j in range(N)]
    best = int(np.argmax(srs))
    write("S01_noise_best_of_200", dates=weekdays(date(2019, 1, 1), T), returns=M[:, best], trials=M, n_trials=N,
          expected={"must_include": [must("deflated_sharpe", "NEEDS_REVIEW"), must("multiple_testing", "NEEDS_REVIEW"),
                                     must("pbo", "NEEDS_REVIEW"), must("trials_declared", "PASS")],
                    "must_not_include": [mustnot("deflated_sharpe", "PASS"), mustnot("multiple_testing", "PASS")],
                    "errors_only_from": [],
                    "comment": f"The best of 200 noise series has an annualised Sharpe of {srs[best] * math.sqrt(PPY):.2f} "
                               "and looks significant as a single test; the expected maximum of 200 noise Sharpe ratios "
                               "is about 2.75 / sqrt(T) per period, so the deflated Sharpe is near 0.5."},
          description="The reported strategy is the best of 200 pure-noise series; all 200 are declared and logged.")


def s02():
    rng = np.random.default_rng(202)
    T, N = 1260, 20
    true_sr = np.linspace(0.5, 3.0, N) / math.sqrt(PPY)
    sigma = 0.01
    M = rng.normal(0.0, sigma, (T, N)) + true_sr * sigma
    best_true = N - 1
    obs = sharpe(M[:, best_true])
    assert obs * math.sqrt(PPY) > 2.0, obs  # the planted genuine signal is visible in this draw
    write("S02_genuine_signal", dates=weekdays(date(2019, 1, 1), T), returns=M[:, best_true], trials=M, n_trials=N,
          expected={"must_include": [must("deflated_sharpe", "PASS"), must("multiple_testing", "PASS"),
                                     must("sharpe_significance", "PASS"), must("pbo", "PASS"),
                                     must("trials_declared", "PASS")],
                    "must_not_include": [mustnot("deflated_sharpe", "NEEDS_REVIEW"), mustnot("pbo", "NEEDS_REVIEW")],
                    "errors_only_from": [],
                    "comment": "20 configurations with true annual Sharpe from 0.5 to 3.0; the reported one has a true "
                               "Sharpe of 3.0 over 5 years. Expected maximum Sharpe by chance with N = 20 and the "
                               "cross-trial variance is far below it; the in-sample winner stays near the top out of "
                               "sample, so PBO is low."},
          description="Genuine signal: the reported configuration is the truly best of 20 with real, dispersed Sharpe.")


def s03():
    rng = np.random.default_rng(303)
    T, phi = 1000, 0.6
    e = rng.normal(0.0, 0.008, T)
    r = np.empty(T)
    prev = 0.0
    for i in range(T):
        prev = phi * prev + e[i]
        r[i] = 0.0004 + prev
    write("S03_autocorrelated_returns", dates=weekdays(date(2019, 1, 1), T), returns=r,
          expected={"must_include": [must("sharpe_autocorrelation", "NEEDS_REVIEW"),
                                     must("deflated_sharpe", "NOT_EXECUTABLE"), must("trials_declared", "NOT_EXECUTABLE")],
                    "must_not_include": [mustnot("sharpe_autocorrelation", "PASS")], "errors_only_from": [],
                    "comment": "For AR(1) with phi = 0.6 the naive sqrt(q) annualisation overstates the Sharpe by about "
                               "sqrt((1 + phi) / (1 - phi)) = 2 (Lo 2002)."},
          description="Returns follow an AR(1) process with phi = 0.6 (smoothed marks of an illiquid book).")


def s04():
    rng = np.random.default_rng(404)
    T, N = 750, 50
    M = rng.normal(0.0002, 0.01, (T, N))
    best = int(np.argmax([sharpe(M[:, j]) for j in range(N)]))
    write("S04_undeclared_trials", dates=weekdays(date(2020, 1, 1), T), returns=M[:, best], trials=M, n_trials=5,
          expected={"must_include": [must("trials_declared", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("trials_declared", "PASS")], "errors_only_from": ["trials_declared"]},
          description="declared_results.json declares 5 trials but trials.csv logs 50 configurations.")


def s05():
    rng = np.random.default_rng(505)
    T, N = 1000, 100
    M = rng.normal(0.0, 0.01, (T, N))
    best = int(np.argmax([sharpe(M[:, j]) for j in range(N)]))
    write("S05_overfit_search_undeclared", dates=weekdays(date(2019, 1, 1), T), returns=M[:, best], trials=M,
          expected={"must_include": [must("trials_declared", "NEEDS_REVIEW"), must("deflated_sharpe", "NEEDS_REVIEW"),
                                     must("pbo", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("deflated_sharpe", "PASS")], "errors_only_from": []},
          description="Best of 100 noise strategies; the number of trials is not declared, only the log is delivered.")


def s06():
    rng = np.random.default_rng(606)
    T = 1250
    r = rng.normal(0.0006, 0.01, T)
    llm = {"uses_llm": True, "model_name": "generic-llm", "model_training_cutoff": "2024-10",
           "backtest_start": "2019-01-01", "backtest_end": "2023-12-31", "uses_company_names": True,
           "uses_tickers": True, "uses_explicit_dates": True, "uses_news_or_filings_text": True,
           "anonymized_entities": False, "retrieval_pit_filtered": False, "pit_model": False,
           "post_cutoff_evaluation": False, "memorization_probe_done": False}
    write("S06_llm_before_cutoff", dates=weekdays(date(2019, 1, 1), T), returns=r, llm=llm,
          expected={"must_include": [must("llm_lookahead_risk", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("llm_lookahead_risk", "PASS"),
                                         mustnot("llm_lookahead_risk", "NOT_EXECUTABLE")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "llm_lookahead_risk", "text": "uses_company_names"}]},
          description="An LLM with a 2024-10 training cutoff is asked about 2019-2023 with company names, tickers and "
                      "dates, no as-of retrieval and no post-cutoff evaluation.")


def s07():
    rng = np.random.default_rng(707)
    T = 126
    true_sr = 0.5 / math.sqrt(PPY)
    r = rng.normal(true_sr * 0.01, 0.01, T)
    obs = sharpe(r)
    # PSR(0) >= 0.95 would need an observed per-period Sharpe above about 1.645 / sqrt(T - 1)
    assert obs < 1.645 / math.sqrt(T - 1), obs
    write("S07_short_track_record", dates=weekdays(date(2024, 1, 1), T), returns=r, n_trials=1,
          expected={"must_include": [must("sharpe_significance", "NEEDS_REVIEW")],
                    "must_not_include": [mustnot("sharpe_significance", "PASS")], "errors_only_from": []},
          description="Six months of a strategy with a true annual Sharpe of 0.5: too short to tell from luck.")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (s01, s02, s03, s04, s05, s06, s07):
        f()
        print("generated", f.__name__)
    print("0.2.0 expectation changes applied to", expectation_changes.apply(OUT))


if __name__ == "__main__":
    main()
