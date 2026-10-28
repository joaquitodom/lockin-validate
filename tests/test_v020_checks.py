"""Unit tests of the 0.2.0 check families and of the INFO alert policy (docs/ALERT_POLICY.md).

Each test builds a small package in tmp_path, so the expected outcome follows from the construction.
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from lockin_validate import INFO, audit
from lockin_validate.checks.benchmark import fit, normalise_weighting
from lockin_validate.findings import ALERT_STATUSES, STATUSES, AuditResult
from lockin_validate.report import render_markdown

BASE = "conventions:\n  calendar: none\n  review_date: '2026-10-28'\n"


def bdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def write(folder, name, header, rows):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(header + "\n" + "\n".join(",".join(str(x) for x in r) for r in rows) + "\n",
                               encoding="utf-8")


def statuses(res, check):
    return [f.status for f in res.findings if f.check == check]


def findings(res, check):
    return [f for f in res.findings if f.check == check]


# ---------------------------------------------------------------------------- INFO status

def test_info_is_a_status_but_not_an_alert():
    assert STATUSES == ["CONFIRMED_ERROR", "NEEDS_REVIEW", "NOT_EXECUTABLE", "INFO", "PASS"]
    assert INFO not in ALERT_STATUSES
    res = AuditResult()
    res.add("x", "data", INFO, "a note")
    res.add("x", "data", "PASS", "ok")
    assert res.status_of("x") == INFO and res.n_alerts() == 0
    md = render_markdown(res)
    assert "Information notes (not alerts)" in md and "a note" in md


# ---------------------------------------------------------------------------- coverage_drift / input_sufficiency

def _fund_pkg(tmp_path, drop):
    tickers = [f"T{i:02d}" for i in range(20)]
    write(tmp_path, "universe.csv", "ticker,start_date,end_date", [(t, "2015-01-02", "") for t in tickers])
    rows = []
    for y in range(2016, 2022):
        for m in (3, 6, 9, 12):
            q = date(y, m, 30 if m in (6, 9) else 31)
            for i, t in enumerate(tickers):
                if drop and y == 2021 and i < 5:
                    continue
                f = q + timedelta(days=40)
                rows.append((t, q, f, f, 0.1))
    write(tmp_path, "fundamentals.csv", "ticker,period_end,filing_date,available_from,roe", rows)
    (tmp_path / "rules.yaml").write_text(BASE, encoding="utf-8")
    return audit(tmp_path)


def test_coverage_drift_flags_drop_against_own_history(tmp_path):
    res = _fund_pkg(tmp_path / "a", drop=True)
    f = findings(res, "coverage_drift")[0]
    assert f.status == "NEEDS_REVIEW" and "2021Q1" in f.title
    assert any(e.get("min_coverage") == 0.75 for e in f.evidence)


def test_coverage_drift_stable_passes_and_missing_inputs(tmp_path):
    assert statuses(_fund_pkg(tmp_path / "b", drop=False), "coverage_drift") == ["PASS"]
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "rules.yaml").write_text(BASE, encoding="utf-8")
    res = audit(tmp_path / "c")
    f = findings(res, "coverage_drift")[0]
    assert f.status == "NOT_EXECUTABLE" and "fundamentals or signals" in f.reason


def _signals_pkg(tmp_path, n_present, declare_min=True):
    inputs = ["a", "b", "c", "d"]
    rows = []
    for d in [date(2024, m, 1) for m in range(1, 7)]:
        for t in ("X1", "X2", "X3"):
            vals = [1.0 if k < n_present else "" for k in range(4)]
            rows.append((d, t, 0.5, *vals))
    write(tmp_path, "signals.csv", "decision_time,ticker,signal," + ",".join(inputs), rows)
    rules = "universe: [X1, X2, X3]\nrequired_inputs: [a, b, c, d]\n"
    if declare_min:
        rules += "min_input_share: 0.75\n"
    (tmp_path / "rules.yaml").write_text(rules + BASE, encoding="utf-8")
    return audit(tmp_path)


def test_input_sufficiency_statuses(tmp_path):
    assert statuses(_signals_pkg(tmp_path / "ok", 3), "input_sufficiency") == ["PASS"]
    assert statuses(_signals_pkg(tmp_path / "bad", 2), "input_sufficiency") == ["CONFIRMED_ERROR"]
    # without a declared minimum the default (0.5) gives a review item, never a confirmed error
    assert statuses(_signals_pkg(tmp_path / "undecl", 1, declare_min=False), "input_sufficiency") == ["NEEDS_REVIEW"]


def test_input_sufficiency_not_executable_without_required_inputs(tmp_path):
    write(tmp_path, "signals.csv", "decision_time,ticker,signal", [(date(2024, 1, 2), "X1", 1)])
    res = audit(tmp_path)
    f = findings(res, "input_sufficiency")[0]
    assert f.status == "NOT_EXECUTABLE" and "required_inputs" in f.reason


# ---------------------------------------------------------------------------- protocol_integrity

PROTOCOL = ("train: {start: '2010-01-01', end: '2017-12-31'}\nvalidation: {start: '2018-01-01', end: '2021-12-31'}\n"
            "test: {start: '2022-01-01', end: '2024-12-31', single_use: true}\n")
HDR = "timestamp,run_id,window_start,window_end,config_hash,purpose"


def _protocol_pkg(tmp_path, extra, protocol=PROTOCOL, rules=BASE):
    rows = [("2026-01-01T10:00:00", "r1", "2010-01-01", "2017-12-31", "c1", "train"),
            ("2026-01-02T10:00:00", "r2", "2018-01-01", "2021-12-31", "c1", "validation"),
            ("2026-01-03T10:00:00", "r3", "2018-01-01", "2021-12-31", "c2", "validation"),
            ("2026-02-01T10:00:00", "r4", "2022-01-01", "2024-12-31", "c1", "test")] + extra
    write(tmp_path, "run_log.csv", HDR, rows)
    (tmp_path / "protocol.yaml").write_text(protocol, encoding="utf-8")
    (tmp_path / "rules.yaml").write_text(rules, encoding="utf-8")
    return audit(tmp_path)


def test_protocol_reproduction_vs_new_look(tmp_path):
    ok = _protocol_pkg(tmp_path / "ok", [("2026-02-02T10:00:00", "r5", "2022-01-01", "2024-12-31", "c1",
                                          "reproduction")])
    assert "PASS" in statuses(ok, "protocol_integrity")
    assert not set(statuses(ok, "protocol_integrity")) & set(ALERT_STATUSES)
    bad = _protocol_pkg(tmp_path / "bad", [("2026-02-02T10:00:00", "r5", "2022-01-01", "2024-12-31", "c9",
                                            "reproduction")])
    f = [x for x in findings(bad, "protocol_integrity") if x.status == "CONFIRMED_ERROR"][0]
    assert "c9" in str(f.evidence) and "new look" in str(f.evidence)


def test_protocol_diagnostic_on_reserved_window_and_not_single_use(tmp_path):
    proto = PROTOCOL + "reserved:\n  - {name: fresh, start: '2025-01-01', end: '2025-06-30'}\n"
    res = _protocol_pkg(tmp_path / "a", [("2026-03-01T10:00:00", "r6", "2024-10-01", "2025-03-31", "c1",
                                          "diagnostic")], protocol=proto)
    assert "CONFIRMED_ERROR" in statuses(res, "protocol_integrity")
    loose = PROTOCOL.replace("single_use: true", "single_use: false")
    res = _protocol_pkg(tmp_path / "b", [("2026-02-03T10:00:00", "r7", "2022-01-01", "2024-12-31", "c2", "test")],
                        protocol=loose)
    assert "CONFIRMED_ERROR" not in statuses(res, "protocol_integrity")
    assert "NEEDS_REVIEW" in statuses(res, "protocol_integrity")


def test_protocol_development_after_look_and_trials(tmp_path):
    res = _protocol_pkg(tmp_path / "a", [("2026-02-05T10:00:00", "r8", "2010-01-01", "2017-12-31", "c3", "train")],
                        rules="research: {n_trials: 1}\n" + BASE)
    titles = " ".join(f.title for f in findings(res, "protocol_integrity"))
    assert "Development continued" in titles and "exceed the declared number of trials" in titles
    assert res.metrics["protocol"]["validation_configs"] == 2


def test_protocol_validation_configs_feed_deflated_sharpe(tmp_path):
    rng = np.random.default_rng(3)
    days = bdays(date(2020, 1, 1), 300)
    write(tmp_path, "returns.csv", "date,return", [(d, round(float(x), 6)) for d, x in
                                                    zip(days, rng.normal(0.001, 0.01, 300))])
    res = _protocol_pkg(tmp_path, [])
    assert res.metrics["statistics"]["protocol_validation_configs"] == 2
    ds = res.metrics["statistics"].get("deflated_sharpe")
    assert ds and ds["n_trials_used"] == 2


def test_protocol_not_executable_without_inputs(tmp_path):
    write(tmp_path, "run_log.csv", HDR, [("2026-01-01", "r1", "2010-01-01", "2011-01-01", "c1", "train")])
    f = findings(audit(tmp_path), "protocol_integrity")[0]
    assert f.status == "NOT_EXECUTABLE" and "protocol" in f.reason


# ---------------------------------------------------------------------------- benchmark_fit

def test_fit_and_weighting_helpers():
    rng = np.random.default_rng(1)
    b = rng.normal(0, 0.01, 500)
    s = 1.5 * b + rng.normal(0.0002, 0.002, 500)
    f = fit(s, b, 252)
    assert abs(f["beta"] - 1.5) < 0.05 and f["r2"] > 0.9
    assert math.isclose(f["information_ratio"], f["active_return_annual"] / f["tracking_error"])
    assert normalise_weighting("Equal-Weighted") == "equal" and normalise_weighting("market cap") == "cap"


def _bench_pkg(tmp_path, weighting, sizing="equal_weight"):
    rng = np.random.default_rng(7)
    days = bdays(date(2022, 1, 3), 260)
    tick = ["A", "B", "C", "D"]
    px = {t: 50 * np.cumprod(1 + rng.normal(0.0004 + 0.0004 * (t in "CD"), 0.01, len(days))) for t in tick}
    write(tmp_path, "prices.csv", "date,ticker,close,adjusted",
          [(d, t, round(float(px[t][k]), 4), "true") for t in tick for k, d in enumerate(days)])
    rets = {t: px[t][1:] / px[t][:-1] - 1 for t in tick}
    strat = (rets["A"] + rets["C"]) / 2
    capw = 0.45 * rets["A"] + 0.45 * rets["B"] + 0.05 * rets["C"] + 0.05 * rets["D"]
    write(tmp_path, "returns.csv", "date,return", [(days[k + 1], float(strat[k])) for k in range(len(strat))])
    write(tmp_path, "benchmark_returns.csv", "date,return", [(days[k + 1], float(capw[k])) for k in range(len(capw))])
    rules = f"universe: [A, B, C, D]\nsizing: {sizing}\n"
    if weighting:
        rules += f"benchmark: {{name: IDX, weighting: {weighting}}}\n"
    (tmp_path / "rules.yaml").write_text(rules + BASE, encoding="utf-8")
    return audit(tmp_path)


def test_benchmark_fit_statuses_and_decomposition(tmp_path):
    res = _bench_pkg(tmp_path / "a", "cap_weighted")
    f = findings(res, "benchmark_fit")[0]
    assert f.status == "NEEDS_REVIEW" and "benchmark-choice" in f.detail
    d = res.metrics["benchmark_fit"]["decomposition"]
    assert math.isclose(d["gap_vs_benchmark_annual"],
                        d["benchmark_choice_effect_annual"] + d["selection_effect_annual"], abs_tol=1e-12)
    assert statuses(_bench_pkg(tmp_path / "b", None), "benchmark_fit") == ["NEEDS_REVIEW"]  # undeclared
    # 0.2.1: declared equal but the file is cap-weighted -> the declaration is contrasted with the data
    f = findings(_bench_pkg(tmp_path / "c", "equal"), "benchmark_fit")[0]
    assert f.status == "NEEDS_REVIEW" and "declared equal-weighted but differs" in f.title


# ---------------------------------------------------------------------------- dividend_corporate_actions

def _div_pkg(tmp_path, skip=False, freeze=False, unadjusted=True):
    days = bdays(date(2023, 1, 2), 60)
    ex = days[30]
    raw, p = [], 100.0
    for d in days:
        p *= 1.001
        if d == ex:
            p -= 2.0
        raw.append(round(p, 4))
    f = 1 - 2.0 / raw[29]
    adj = [round(raw[k] * (f if (k < 30 and not skip) else 1.0), 4) for k in range(60)]
    if freeze:
        for k in range(30, 34):
            adj[k] = adj[29]
    write(tmp_path, "prices.csv", "date,ticker,close,adjusted", [(d, "DV", adj[k], "true") for k, d in enumerate(days)])
    if unadjusted:
        write(tmp_path, "unadjusted_prices.csv", "date,ticker,close", [(d, "DV", raw[k]) for k, d in enumerate(days)])
    write(tmp_path, "dividends.csv", "ticker,ex_date,amount", [("DV", ex, 2.0)])
    (tmp_path / "rules.yaml").write_text(BASE, encoding="utf-8")
    return audit(tmp_path)


def test_dividend_checks(tmp_path):
    assert statuses(_div_pkg(tmp_path / "ok"), "dividend_corporate_actions") == ["PASS"]
    # the only dividend not applied: a price series, not an inconsistent one -> review, not error
    assert statuses(_div_pkg(tmp_path / "skip", skip=True), "dividend_corporate_actions") == ["NEEDS_REVIEW"]
    fr = findings(_div_pkg(tmp_path / "frz", freeze=True), "dividend_corporate_actions")
    assert any(x.status == "CONFIRMED_ERROR" and "frozen" in x.title for x in fr)
    # breaks inside the frozen run are not reported a second time
    assert not any("without a declared event" in x.title for x in fr)
    # without the as-traded series only the frozen test runs, and it cannot confirm
    nu = findings(_div_pkg(tmp_path / "nu", freeze=True, unadjusted=False), "dividend_corporate_actions")
    assert [x.status for x in nu] == ["NEEDS_REVIEW"]


def test_dividend_not_executable(tmp_path):
    write(tmp_path, "prices.csv", "date,ticker,close,adjusted", [(date(2024, 1, 2), "A", 1, "true")])
    f = findings(audit(tmp_path), "dividend_corporate_actions")[0]
    assert f.status == "NOT_EXECUTABLE" and "unadjusted_prices or dividends" in f.reason


# ---------------------------------------------------------------------------- liquidity / costs

def _trade_pkg(tmp_path, qty, volume, rate, drift=0.002):
    days = bdays(date(2023, 1, 2), 60)
    px = [round(20 * (1 + drift) ** k, 4) for k in range(60)]
    vol = [volume] * 60
    write(tmp_path, "prices.csv", "date,ticker,close,volume,adjusted",
          [(d, "L", px[k], vol[k], "true") for k, d in enumerate(days)])
    trades = [(1, f"{days[30]}T16:00:00", "L", "buy", qty, px[30], round(qty * px[30] * rate, 4)),
              (2, f"{days[45]}T16:00:00", "L", "sell", qty, px[45], round(qty * px[45] * rate, 4))]
    write(tmp_path, "trades.csv", "trade_id,timestamp,ticker,side,quantity,price,commission", trades)
    (tmp_path / "rules.yaml").write_text(f"costs: {{commission_rate: {rate}, slippage_rate: 0.0}}\n" + BASE,
                                         encoding="utf-8")
    return audit(tmp_path)


def test_liquidity_participation(tmp_path):
    assert statuses(_trade_pkg(tmp_path / "ok", 1000, 1_000_000, 0.001), "liquidity_participation") == ["PASS"]
    hi = _trade_pkg(tmp_path / "hi", 3000, 10_000, 0.001)
    assert statuses(hi, "liquidity_participation") == ["NEEDS_REVIEW"]
    assert hi.metrics["liquidity_participation"]["impact_cost_estimate"] >= 0
    over = _trade_pkg(tmp_path / "over", 3000, 2_000, 0.001)
    assert "CONFIRMED_ERROR" in statuses(over, "liquidity_participation")


def test_cost_sensitivity_levels(tmp_path):
    # gross ~ +3.5% of a 100k capital invested 60k: about +2.1%; turnover 1.2
    robust = _trade_pkg(tmp_path / "r", 3000, 1_000_000, 0.0005)
    assert statuses(robust, "cost_sensitivity") == ["PASS"]
    ev = robust.metrics["cost_sensitivity"]
    assert math.isclose(ev["break_even_cost_per_unit_turnover"], ev["gross_total_return"] / ev["turnover"], rel_tol=1e-3)
    fragile = _trade_pkg(tmp_path / "f", 3000, 1_000_000, 0.012)
    assert statuses(fragile, "cost_sensitivity") == ["NEEDS_REVIEW"]
    flat = _trade_pkg(tmp_path / "z", 3000, 1_000_000, 0.001, drift=0.0)
    assert statuses(flat, "cost_sensitivity") == [INFO]


# ---------------------------------------------------------------------------- stability / regimes

def test_stability_one_name_and_subperiods(tmp_path):
    days = bdays(date(2023, 1, 2), 120)
    px = {"W": [round(10 * 1.01 ** k, 4) for k in range(120)],
          "L1": [round(10 * 0.999 ** k, 4) for k in range(120)],
          "L2": [round(10 * 0.999 ** k, 4) for k in range(120)]}
    write(tmp_path, "prices.csv", "date,ticker,close,adjusted",
          [(d, t, px[t][k], "true") for t in px for k, d in enumerate(days)])
    write(tmp_path, "trades.csv", "timestamp,ticker,side,quantity,price,commission",
          [(f"{days[0]}T16:00:00", t, "buy", 1000, px[t][0], 0) for t in px])
    (tmp_path / "rules.yaml").write_text(BASE, encoding="utf-8")
    res = audit(tmp_path)
    f = [x for x in findings(res, "stability_and_concentration") if x.status == "NEEDS_REVIEW"]
    assert f and "W" in f[0].title
    pnl = {x["ticker"]: x["pnl"] for x in res.metrics["stability_and_concentration"]["name_pnl"]}
    assert math.isclose(sum(pnl.values()), res.metrics["reconstruction"]["final_nav"] - 100000, abs_tol=0.05)


def test_stability_day_concentration_is_info_when_sharpe_not_significant(tmp_path):
    rng = np.random.default_rng(11)
    days = bdays(date(2019, 1, 1), 600)
    r = rng.normal(0.0001, 0.01, 600)
    write(tmp_path, "returns.csv", "date,return", [(d, round(float(x), 6) if i else 0.05)
                                                   for i, (d, x) in enumerate(zip(days, r))])
    (tmp_path / "rules.yaml").write_text(BASE, encoding="utf-8")
    res = audit(tmp_path)
    st = statuses(res, "stability_and_concentration")
    assert "NEEDS_REVIEW" not in st


def _regime_pkg(tmp_path, in_share, out_share):
    months = [date(2010 + m // 12, m % 12 + 1, 28) for m in range(120)]
    rows = []
    for k, m in enumerate(months):
        oos = m.year >= 2018
        share = out_share if oos else in_share
        rows.append((m, int((k % 20) < share * 20)))
    write(tmp_path, "regimes.csv", "date,flag", rows)
    (tmp_path / "rules.yaml").write_text("conditional_rules: [{name: curve_rule, column: flag}]\nconventions:\n"
                                         "  calendar: none\n  oos_start: '2018-01-01'\n", encoding="utf-8")
    return audit(tmp_path)


def test_conditional_rule_activation(tmp_path):
    bad = _regime_pkg(tmp_path / "bad", 0.05, 0.85)
    f = findings(bad, "conditional_rule_activation")[0]
    assert f.status == "NEEDS_REVIEW" and "curve_rule" in f.title
    assert statuses(_regime_pkg(tmp_path / "ok", 0.4, 0.4), "conditional_rule_activation") == ["PASS"]
    (tmp_path / "none").mkdir()
    write(tmp_path / "none", "regimes.csv", "date,flag", [(date(2020, 1, 31), 1)])
    f = findings(audit(tmp_path / "none"), "conditional_rule_activation")[0]
    assert f.status == "NOT_EXECUTABLE" and "oos_start" in f.reason


# ---------------------------------------------------------------------------- alert policy (Part B)

def _returns_pkg(tmp_path, n, mean, sd, seed, extra_conv=""):
    rng = np.random.default_rng(seed)
    days = bdays(date(2020, 1, 1), n)
    write(tmp_path, "returns.csv", "date,return", [(d, round(float(x), 8)) for d, x in
                                                    zip(days, rng.normal(mean, sd, n))])
    (tmp_path / "rules.yaml").write_text(BASE + extra_conv, encoding="utf-8")
    (tmp_path / "declared_results.json").write_text('{"n_trials": 1}', encoding="utf-8")
    return audit(tmp_path)


@pytest.mark.parametrize("ratio,expected", [(100.0, INFO), (0.5, "NEEDS_REVIEW")])
def test_significance_review_ratio(tmp_path, ratio, expected):
    res = _returns_pkg(tmp_path, 120, 0.0008, 0.01, 2, extra_conv=f"  significance_review_ratio: {ratio}\n")
    sig = res.metrics["statistics"]["significance"]
    assert sig["psr_vs_0"] < 0.95 and sig["sharpe_per_period"] > 0
    assert statuses(res, "sharpe_significance") == [expected]


def test_single_trial_deflation_is_info(tmp_path):
    res = _returns_pkg(tmp_path, 120, 0.0003, 0.01, 2)
    assert statuses(res, "deflated_sharpe") == [INFO]
    assert statuses(res, "multiple_testing") == [INFO]


# ---------------------------------------------------------------------------- 0.2.1: independent review fixes

def test_coverage_period_without_rows_counts_as_zero(tmp_path):
    tickers = [f"T{i:02d}" for i in range(10)]
    write(tmp_path, "universe.csv", "ticker,start_date,end_date", [(t, "2015-01-02", "") for t in tickers])
    rows = [(t, q, q + timedelta(days=40), 0.1) for q in [date(y, 12, 31) for y in range(2016, 2019)]
            + [date(y, 6, 30) for y in range(2016, 2019)] for t in tickers]
    write(tmp_path, "fundamentals.csv", "ticker,period_end,filing_date,roe", rows)
    (tmp_path / "rules.yaml").write_text("period: {start: '2016-01-04', end: '2021-12-31'}\n" + BASE, encoding="utf-8")
    res = audit(tmp_path)
    f = findings(res, "coverage_drift")[0]
    assert f.status == "NEEDS_REVIEW"
    assert res.metrics["coverage_drift"]["periods_without_rows"]


def test_coverage_undeclared_field_is_info(tmp_path):
    tickers = [f"T{i:02d}" for i in range(10)]
    write(tmp_path, "universe.csv", "ticker,start_date,end_date", [(t, "2015-01-02", "") for t in tickers])
    rows = []
    for y in range(2016, 2022):
        for m in (3, 6, 9, 12):
            q = date(y, m, 30 if m in (6, 9) else 31)
            for t in tickers:
                rows.append((t, q, q + timedelta(days=40), 0.1, "" if y >= 2021 else 5))
    write(tmp_path, "fundamentals.csv", "ticker,period_end,filing_date,roe,esg", rows)
    (tmp_path / "rules.yaml").write_text("required_inputs: [ROE]\n" + BASE, encoding="utf-8")
    st = statuses(audit(tmp_path), "coverage_drift")
    assert INFO in st and "NEEDS_REVIEW" not in st


def test_input_names_case_insensitive_and_absent_input_not_confirmed(tmp_path):
    rows = [(date(2024, m, 1), t, 0.5, 1.0, 1.0) for m in range(1, 7) for t in ("X1", "X2")]
    write(tmp_path / "a", "signals.csv", "decision_time,ticker,signal,ROE,Debt", rows)
    (tmp_path / "a" / "rules.yaml").write_text("required_inputs: [ROE, Debt]\nmin_input_share: 1.0\n" + BASE,
                                               encoding="utf-8")
    assert statuses(audit(tmp_path / "a"), "input_sufficiency") == ["PASS"]
    # one of three inputs exported in no table: the shortfall may be the package, not the model -> review
    write(tmp_path / "b", "signals.csv", "decision_time,ticker,signal,roe,debt", rows)
    (tmp_path / "b" / "rules.yaml").write_text("required_inputs: [roe, debt, fcf]\nmin_input_share: 1.0\n" + BASE,
                                               encoding="utf-8")
    assert statuses(audit(tmp_path / "b"), "input_sufficiency") == ["NEEDS_REVIEW"]


def test_stale_fundamentals_count_as_missing(tmp_path):
    write(tmp_path, "fundamentals.csv", "ticker,period_end,filing_date,roe", [("X1", date(2020, 12, 31),
                                                                             date(2021, 2, 10), 0.1)])
    write(tmp_path, "signals.csv", "decision_time,ticker,signal",
          [(date(2021, 3, 1), "X1", 1.0), (date(2023, 3, 1), "X1", 1.0)])
    (tmp_path / "rules.yaml").write_text("required_inputs: [roe]\nmin_input_share: 1.0\n" + BASE, encoding="utf-8")
    res = audit(tmp_path)
    f = findings(res, "input_sufficiency")[0]
    assert f.status == "CONFIRMED_ERROR" and "2023-03" in f.title and "2021-03" not in f.title
    assert res.metrics["input_sufficiency"]["rows_with_stale_fundamentals"] == 1


def test_protocol_purpose_synonyms_and_unknown(tmp_path):
    ok = _protocol_pkg(tmp_path / "a", [("2026-02-02T10:00:00", "r5", "2022-01-01", "2024-12-31", "c1", " Holdout ")])
    assert "CONFIRMED_ERROR" not in statuses(ok, "protocol_integrity")
    unk = _protocol_pkg(tmp_path / "b", [("2026-02-02T10:00:00", "r5", "2022-01-01", "2024-12-31", "c9", "sanity")])
    st = statuses(unk, "protocol_integrity")
    assert "NEEDS_REVIEW" in st and "CONFIRMED_ERROR" not in st


def test_dividends_without_as_traded_series_is_not_a_pass(tmp_path):
    res = _div_pkg(tmp_path, unadjusted=False)
    assert statuses(res, "dividend_corporate_actions") == ["NOT_EXECUTABLE"]


def test_liquidity_sliced_orders_and_unmeasured_trades(tmp_path):
    days = bdays(date(2023, 1, 2), 40)
    write(tmp_path / "s", "prices.csv", "date,ticker,close,volume,adjusted",
          [(d, "L", 10.0, 10_000, "true") for d in days])
    write(tmp_path / "s", "trades.csv", "trade_id,timestamp,ticker,side,quantity,price",
          [(k, f"{days[30]}T16:00:00", "L", "buy", 800, 10.0) for k in range(1, 6)])
    res = audit(tmp_path / "s")
    assert "NEEDS_REVIEW" in statuses(res, "liquidity_participation")  # 5 x 8% of ADV on one day = 40%
    assert "NEEDS_REVIEW" not in statuses(res, "duplicates")  # distinct trade ids: partial fills, INFO
    write(tmp_path / "u", "prices.csv", "date,ticker,close,volume,adjusted",
          [(d, t, 10.0, 1_000_000 if t == "A" else "", "true") for d in days for t in ("A", "B")])
    write(tmp_path / "u", "trades.csv", "timestamp,ticker,side,quantity,price",
          [(f"{days[30]}T16:00:00", "A", "buy", 100, 10.0), (f"{days[30]}T16:00:00", "B", "buy", 5000, 10.0)])
    st = statuses(audit(tmp_path / "u"), "liquidity_participation")
    assert "PASS" not in st and "NEEDS_REVIEW" in st


def test_rule_never_computed_in_sample_is_reported(tmp_path):
    months = [date(2010 + m // 12, m % 12 + 1, 28) for m in range(120)]
    write(tmp_path, "regimes.csv", "date,a,b", [(m, k % 2, "" if m.year < 2018 else 1) for k, m in enumerate(months)])
    (tmp_path / "rules.yaml").write_text("conditional_rules: [{name: rule_a, column: a}, {name: rule_b, column: b}]\n"
                                         "conventions:\n  calendar: none\n  oos_start: '2018-01-01'\n",
                                         encoding="utf-8")
    fs = findings(audit(tmp_path), "conditional_rule_activation")
    assert [f.status for f in fs] == ["NEEDS_REVIEW"] and "rule_b" in fs[0].title


def test_stability_pass_names_only_tests_that_ran(tmp_path):
    rng = np.random.default_rng(4)
    days = bdays(date(2023, 1, 2), 100)
    write(tmp_path, "returns.csv", "date,return", [(d, round(float(x), 6)) for d, x in
                                                    zip(days, rng.normal(0.002, 0.005, 100))])
    (tmp_path / "rules.yaml").write_text(BASE, encoding="utf-8")
    fs = findings(audit(tmp_path), "stability_and_concentration")
    assert [f.status for f in fs] == [INFO]  # halves, < 250 periods, no names: no test applicable
