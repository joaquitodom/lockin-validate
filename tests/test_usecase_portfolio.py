"""Use case ``portfolio``: statistics against hand-computed values, the check contract, and the case battery."""

from __future__ import annotations

import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from lockin_validate import audit
from lockin_validate.cases import available_cases, run_case
from lockin_validate.findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, NOT_EXECUTABLE, PASS, AuditResult
from lockin_validate.usecases import portfolio as pf

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases" / "usecase_portfolio"


# ------------------------------------------------------------------ statistics

def test_hhi_and_effective_n():
    assert pf.hhi([0.25, 0.25, 0.25, 0.25]) == pytest.approx(0.25)
    assert pf.effective_n([0.25, 0.25, 0.25, 0.25]) == pytest.approx(4.0)
    assert pf.hhi([1.0]) == pytest.approx(1.0)
    # absolute weights normalised by the gross: a 130/30 book with 4 longs of 0.325 and 3 shorts of -0.10
    w = [0.325] * 4 + [-0.10] * 3
    g = 1.6
    assert pf.hhi(w) == pytest.approx(sum((abs(x) / g) ** 2 for x in w))
    assert pf.top_share([0.5, 0.2, 0.1, 0.1, 0.05, 0.05], k=5) == pytest.approx(0.95)
    assert math.isnan(pf.hhi([0.0, 0.0]))


def test_turnover_with_drift_hand_example():
    # two names 60/40; prices +10% and -10%: drifted weights 0.66/0.36 over NAV 1.02 -> 0.6471 / 0.3529
    w_prev = np.array([0.6, 0.4])
    ratio = np.array([1.1, 0.9])
    drifted = pf.drifted_weights(w_prev, ratio)
    assert drifted == pytest.approx([0.66 / 1.02, 0.36 / 1.02])
    # reporting the drifted weights is NOT trading
    assert pf.one_way_turnover(drifted, w_prev, ratio) == pytest.approx(0.0, abs=1e-12)
    # without prices the same change looks like 0.5 * (|0.6471 - 0.6| + |0.3529 - 0.4|) = 0.0471 of turnover
    assert pf.one_way_turnover(drifted, w_prev) == pytest.approx(0.5 * (abs(0.66 / 1.02 - 0.6) + abs(0.36 / 1.02 - 0.4)))
    # rebalancing back to 60/40 after the drift is a trade of 0.0471
    assert pf.one_way_turnover(w_prev, w_prev, ratio) == pytest.approx(0.5 * (abs(0.6 - 0.66 / 1.02)
                                                                            + abs(0.4 - 0.36 / 1.02)))
    # market-neutral book: +0.5 / -0.5, NAV factor 1 + 0.5*0.1 - 0.5*(-0.1) = 1.1
    d = pf.drifted_weights(np.array([0.5, -0.5]), np.array([1.1, 0.9]))
    assert d == pytest.approx([0.55 / 1.1, -0.45 / 1.1])


def test_active_share():
    w = np.array([0.5, 0.3, 0.2, 0.0])
    wb = np.array([0.4, 0.3, 0.1, 0.2])
    assert pf.active_share(w, wb) == pytest.approx(0.5 * (0.1 + 0.0 + 0.1 + 0.2))
    assert pf.active_share(wb, wb) == 0.0


def test_jobson_korkie_memmel_against_direct_computation():
    rng = np.random.default_rng(0)
    r1 = rng.normal(0.001, 0.01, 400)
    r2 = 0.5 * r1 + rng.normal(0.0, 0.008, 400)
    out = pf.jobson_korkie_memmel(r1, r2)
    T = 400
    sr1 = r1.mean() / r1.std(ddof=1)
    sr2 = r2.mean() / r2.std(ddof=1)
    rho = np.corrcoef(r1, r2)[0, 1]
    theta = (2 * (1 - rho) + 0.5 * (sr1 ** 2 + sr2 ** 2) - sr1 * sr2 * rho ** 2) / T
    z = (sr1 - sr2) / math.sqrt(theta)
    assert out["z"] == pytest.approx(z)
    assert out["p_one_sided"] == pytest.approx(1 - NormalDist().cdf(z))
    assert out["p_two_sided"] == pytest.approx(2 * (1 - NormalDist().cdf(abs(z))))
    # identical series: rho = 1 and theta = 0, the statistic is undefined (reported as nan, never "beats")
    assert math.isnan(pf.jobson_korkie_memmel(r1, r1)["z"])
    assert pf.jobson_korkie_memmel(r2, r1)["z"] == pytest.approx(-z)
    assert math.isnan(pf.jobson_korkie_memmel([0.1, 0.2], [0.1, 0.3])["z"])


def test_ucits_5_10_40():
    s = pd.Series({"A": 0.12, "B": 0.06, "C": 0.04})
    u = pf.ucits_5_10_40(s)
    assert u["over_10"] == ["A"] and u["breach"]
    s2 = pd.Series([0.08] * 6 + [0.52 / 14] * 14)
    assert pf.ucits_5_10_40(s2)["breach"]  # six names above 5% add to 48% > 40%
    s3 = pd.Series([0.05] * 20)
    assert not pf.ucits_5_10_40(s3)["breach"]


def test_perf_and_ppy_inference():
    r = np.array([0.01, -0.01, 0.02])
    m = pf.perf(r, 252)
    nav = np.cumprod(1 + r)
    assert m["annual_return"] == pytest.approx(nav[-1] ** (252 / 3) - 1)
    assert m["max_drawdown"] == pytest.approx(-0.01)
    daily = pd.bdate_range("2024-01-01", periods=30)
    assert pf.infer_ppy(list(daily)) == 252
    assert pf.infer_ppy(list(pd.date_range("2024-01-31", periods=14, freq="ME"))) == 12
    assert pf.infer_ppy(list(pd.date_range("2024-01-01", periods=10, freq="7D"))) == 52


# ------------------------------------------------------------------ check contract on small packages

def _write(folder: Path, weights: list[tuple], rules: str | None = None, prices: list[tuple] | None = None,
           positions: list[tuple] | None = None, bench: list[tuple] | None = None, sector: dict | None = None):
    folder.mkdir(parents=True, exist_ok=True)
    hdr = "date,ticker,weight" + (",sector" if sector else "") + "\n"
    rows = [f"{d},{t},{w}" + (f",{sector[t]}" if sector else "") for d, t, w in weights]
    (folder / "weights.csv").write_text(hdr + "\n".join(rows) + "\n", encoding="utf-8")
    if rules is not None:
        (folder / "rules.yaml").write_text(rules, encoding="utf-8")
    if prices is not None:
        (folder / "prices.csv").write_text("date,ticker,close\n" + "\n".join(f"{d},{t},{c}" for d, t, c in prices)
                                           + "\n", encoding="utf-8")
    if positions is not None:
        (folder / "positions.csv").write_text("date,ticker,quantity\n"
                                              + "\n".join(f"{d},{t},{q}" for d, t, q in positions) + "\n",
                                              encoding="utf-8")
    if bench is not None:
        (folder / "benchmark_weights.csv").write_text("date,ticker,weight\n"
                                                      + "\n".join(f"{d},{t},{w}" for d, t, w in bench) + "\n",
                                                      encoding="utf-8")


def _status(res: AuditResult, check: str) -> str | None:
    return res.status_of(check)


def test_empty_folder_every_check_not_executable(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    res = audit(d, use_cases=["portfolio"])
    for c in pf.SPEC.checks:
        assert _status(res, c) == NOT_EXECUTABLE, c
        f = [x for x in res.findings if x.check == c][0]
        assert "weights" in f.reason


def test_constraints_detection_and_pass(tmp_path):
    dates = ["2024-01-31", "2024-02-29", "2024-03-29"]
    w = [(d, t, 0.25) for d in dates for t in ("A", "B", "C", "D")]
    rules = "constraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.30\n"
    _write(tmp_path / "ok", w, rules)
    res = audit(tmp_path / "ok", use_cases=["portfolio"])
    assert _status(res, "portfolio_constraints") == PASS
    # a short and a weight above the cap on one date
    w2 = list(w)
    w2[4] = ("2024-02-29", "A", 0.45)
    w2[5] = ("2024-02-29", "B", -0.20)
    w2[6] = ("2024-02-29", "C", 0.50)
    _write(tmp_path / "bad", w2, rules)
    res = audit(tmp_path / "bad", use_cases=["portfolio"])
    f = [x for x in res.findings if x.check == "portfolio_constraints"][0]
    assert f.status == CONFIRMED_ERROR
    kinds = {e["constraint"] for e in f.evidence}
    assert {"long_only", "max_weight"} <= kinds
    assert all(e["row"] is not None for e in f.evidence if e["ticker"])
    # nothing declared and weights that sum to 0.8: review (missing cash row?)
    w3 = [(d, t, 0.20) for d in dates for t in ("A", "B", "C", "D")]
    _write(tmp_path / "undeclared", w3)
    res = audit(tmp_path / "undeclared", use_cases=["portfolio"])
    assert _status(res, "portfolio_constraints") == NEEDS_REVIEW
    # with a cash ticker declared the remainder is cash: PASS under long_only
    w4 = w3 + [(d, "CASH", 0.20) for d in dates]
    _write(tmp_path / "cash", w4, "constraints:\n  portfolio:\n    long_only: true\n    cash_ticker: CASH\n")
    res = audit(tmp_path / "cash", use_cases=["portfolio"])
    assert _status(res, "portfolio_constraints") == PASS


def test_group_limit_and_unverifiable(tmp_path):
    dates = ["2024-01-31", "2024-02-29"]
    sector = {"A": "TECH", "B": "TECH", "C": "FIN", "D": "FIN"}
    w = [(d, t, x) for d in dates for t, x in zip("ABCD", (0.30, 0.30, 0.20, 0.20))]
    rules = "constraints:\n  portfolio:\n    long_only: true\n    group_limits:\n      sector: 0.50\n"
    _write(tmp_path / "g", w, rules, sector=sector)
    res = audit(tmp_path / "g", use_cases=["portfolio"])
    f = [x for x in res.findings if x.check == "portfolio_constraints"][0]
    assert f.status == CONFIRMED_ERROR and any(e["constraint"] == "sector=TECH" for e in f.evidence)
    _write(tmp_path / "nocol", w, rules)  # the column is missing: cannot verify, never PASS
    res = audit(tmp_path / "nocol", use_cases=["portfolio"])
    assert _status(res, "portfolio_constraints") == NEEDS_REVIEW


def test_concentration_review_and_info(tmp_path):
    dates = ["2024-01-31", "2024-02-29"]
    _write(tmp_path / "c", [(d, t, 0.5) for d in dates for t in "AB"])
    res = audit(tmp_path / "c", use_cases=["portfolio"])
    assert _status(res, "portfolio_concentration") == NEEDS_REVIEW
    f = [x for x in res.findings if x.check == "portfolio_concentration" and x.status == NEEDS_REVIEW][0]
    assert f.evidence[0]["hhi"] == pytest.approx(0.5) and f.evidence[0]["effective_n"] == pytest.approx(2.0)
    # a declared max_weight that allows 50% removes the single-name reason but the HHI reason stays
    _write(tmp_path / "c2", [(d, t, 0.1) for d in dates for t in "ABCDEFGHIJ"])
    res = audit(tmp_path / "c2", use_cases=["portfolio"])
    assert _status(res, "portfolio_concentration") == INFO


def test_turnover_drift_not_trading_and_churn(tmp_path):
    # daily prices for 40 sessions; weights reported at market value every 10 sessions (drift only)
    days = list(pd.bdate_range("2024-01-01", periods=40))
    pa = [100 * (1.01 ** i) for i in range(40)]
    pb = [100 * (0.99 ** i) for i in range(40)]
    prices = [(d.date(), "A", f"{pa[i]:.6f}") for i, d in enumerate(days)] + \
             [(d.date(), "B", f"{pb[i]:.6f}") for i, d in enumerate(days)]
    w0 = np.array([0.6, 0.4])
    weights = []
    for i in (0, 10, 20, 30):
        v = w0 * np.array([pa[i] / pa[0], pb[i] / pb[0]])
        v = v / v.sum()
        weights += [(days[i].date(), "A", f"{v[0]:.8f}"), (days[i].date(), "B", f"{v[1]:.8f}")]
    rules = "constraints:\n  portfolio:\n    rebalance_frequency: annual\n"
    _write(tmp_path / "drift", weights, rules, prices=prices)
    res = audit(tmp_path / "drift", use_cases=["portfolio"])
    assert _status(res, "portfolio_turnover") == INFO
    assert res.metrics["portfolio_turnover"]["default"]["annual_turnover"] < 0.01
    # same weights without prices: the drift cannot be separated -> review, never error
    _write(tmp_path / "drift_np", weights, rules)
    res = audit(tmp_path / "drift_np", use_cases=["portfolio"])
    assert _status(res, "portfolio_turnover") == NEEDS_REVIEW
    # real trades every 10 sessions (back to 60/40) under a declared annual rebalance, with prices -> error
    weights2 = [(days[i].date(), t, x) for i in (0, 10, 20, 30) for t, x in (("A", 0.6), ("B", 0.4))]
    _write(tmp_path / "churn", weights2, rules, prices=prices)
    res = audit(tmp_path / "churn", use_cases=["portfolio"])
    f = [x for x in res.findings if x.check == "portfolio_turnover"][0]
    assert f.status == CONFIRMED_ERROR and f.evidence[0]["rebalance_date"] is False


def test_weights_vs_positions(tmp_path):
    days = list(pd.bdate_range("2024-01-01", periods=5))
    prices = [(d.date(), t, c) for d in days for t, c in (("A", 10.0), ("B", 20.0))]
    weights = [(days[1].date(), "A", 0.5), (days[1].date(), "B", 0.5), (days[3].date(), "A", 0.5),
               (days[3].date(), "B", 0.5)]
    ok = [(days[1].date(), "A", 100), (days[1].date(), "B", 50), (days[3].date(), "A", 100), (days[3].date(), "B", 50)]
    _write(tmp_path / "ok", weights, prices=prices, positions=ok)
    res = audit(tmp_path / "ok", use_cases=["portfolio"])
    assert _status(res, "portfolio_weights_vs_positions") == PASS
    bad = [(days[1].date(), "A", 180), (days[1].date(), "B", 10), (days[3].date(), "A", 180), (days[3].date(), "B", 10)]
    _write(tmp_path / "bad", weights, prices=prices, positions=bad)
    res = audit(tmp_path / "bad", use_cases=["portfolio"])
    f = [x for x in res.findings if x.check == "portfolio_weights_vs_positions"][0]
    assert f.status == CONFIRMED_ERROR and f.evidence[0]["max_abs_diff"] == pytest.approx(0.4)
    # one session of execution lag is allowed: positions dated the day after the weights
    lag = [(days[2].date(), "A", 100), (days[2].date(), "B", 50), (days[4].date(), "A", 100), (days[4].date(), "B", 50)]
    _write(tmp_path / "lag", weights, prices=prices, positions=lag)
    res = audit(tmp_path / "lag", use_cases=["portfolio"])
    assert _status(res, "portfolio_weights_vs_positions") == PASS


def test_simulate_next_session_and_drift():
    days = list(pd.bdate_range("2024-01-01", periods=4))
    px = pd.DataFrame({"A": [100, 110, 121, 121], "B": [100, 100, 100, 50]}, index=days, dtype=float)
    long = pd.DataFrame({"date": [days[0], days[0]], "ticker": ["A", "B"], "weight": [0.5, 0.5], "row": [2, 3]})
    panel = pf.Panel(None, long)
    r, info = pf.simulate(panel, px)
    # weights of day 0 enter at the close of day 1; day 2: 0.5*10% = 5%; drifted to 0.5238/0.4762; day 3: -23.8%
    assert list(r.index) == [days[2], days[3]]
    assert r.iloc[0] == pytest.approx(0.05)
    assert r.iloc[1] == pytest.approx(0.55 / 1.05 * 0 + 0.5 / 1.05 * (-0.5))
    assert info["n_rebalances"] == 1


def test_vs_naive_and_active_share_contract(tmp_path):
    days = list(pd.bdate_range("2024-01-01", periods=300))
    rng = np.random.default_rng(3)
    pa = 100 * np.cumprod(1 + rng.normal(0.002, 0.01, 300))
    pb = 100 * np.cumprod(1 + rng.normal(-0.001, 0.01, 300))
    prices = [(d.date(), "A", f"{pa[i]:.4f}") for i, d in enumerate(days)] + \
             [(d.date(), "B", f"{pb[i]:.4f}") for i, d in enumerate(days)]
    wd = [days[i].date() for i in range(0, 300, 20)]  # 15 weights dates
    weights = [(d, t, x) for d in wd for t, x in (("A", 0.9), ("B", 0.1))]
    bench = [(d, t, x) for d in wd for t, x in (("A", 0.5), ("B", 0.5))]
    _write(tmp_path / "skill", weights, "strategy: active alpha stock picking\n", prices=prices, bench=bench)
    res = audit(tmp_path / "skill", use_cases=["portfolio"])
    assert _status(res, "portfolio_vs_naive") == INFO  # 90% in the name with +0.2% a day beats 1/N
    m = res.metrics["portfolio_vs_naive"]["default"]
    assert m["jk"]["p_one_sided"] < 0.05 and m["model"]["sharpe"] > m["naive"]["sharpe"]
    f = [x for x in res.findings if x.check == "portfolio_active_share"][0]
    assert f.status == INFO and f.evidence[0]["active_share"] == pytest.approx(0.4)
    assert res.metrics["portfolio_active_share"]["default"]["tracking_error"] is not None
    # closet index: the benchmark weights themselves under an "active" declaration
    weights2 = [(d, t, x) for d in wd for t, x in (("A", 0.50), ("B", 0.50))]
    _write(tmp_path / "closet", weights2, "strategy: active alpha stock picking\n", prices=prices, bench=bench)
    res = audit(tmp_path / "closet", use_cases=["portfolio"])
    assert _status(res, "portfolio_active_share") == NEEDS_REVIEW
    assert _status(res, "portfolio_vs_naive") == NEEDS_REVIEW  # identical to 1/N: no value added
    # too few weight dates: not executable, never PASS
    _write(tmp_path / "short", weights[:6], prices=prices)
    res = audit(tmp_path / "short", use_cases=["portfolio"])
    assert _status(res, "portfolio_vs_naive") == NOT_EXECUTABLE


def test_aliases_and_multiple_portfolios(tmp_path):
    d = tmp_path / "alias"
    d.mkdir()
    (d / "weights.csv").write_text("Date,Symbol,Target_Weight,portfolio\n2024-01-31,a,0.5,P1\n2024-01-31,b,0.5,P1\n"
                                   "2024-01-31,a,1.2,P2\n2024-02-29,a,0.5,P1\n2024-02-29,b,0.5,P1\n2024-02-29,a,1.2,P2\n",
                                   encoding="utf-8")
    (d / "rules.yaml").write_text("constraints:\n  portfolio:\n    long_only: true\n", encoding="utf-8")
    res = audit(d, use_cases=["portfolio"])
    fs = [x for x in res.findings if x.check == "portfolio_constraints"]
    assert {x.status for x in fs} == {PASS, CONFIRMED_ERROR}
    assert any("[portfolio P2]" in x.title for x in fs if x.status == CONFIRMED_ERROR)


def test_profile_constraints_apply(tmp_path):
    dates = ["2024-01-31", "2024-02-29"]
    _write(tmp_path / "p", [(d, t, x) for d in dates for t, x in (("A", 1.2), ("B", -0.2))])
    res = audit(tmp_path / "p", use_cases=["portfolio"], profile="portfolio_long_only_monthly")
    assert _status(res, "portfolio_constraints") == CONFIRMED_ERROR
    res = audit(tmp_path / "p", use_cases=["portfolio"])
    assert _status(res, "portfolio_constraints") == INFO  # nothing declared: sum is 1, no review


def test_odd_data_never_raises(tmp_path):
    d = tmp_path / "odd"
    d.mkdir()
    (d / "weights.csv").write_text("date,ticker,weight\n2024-01-31,A,\nnot a date,B,0.5\n", encoding="utf-8")
    (d / "prices.csv").write_text("date,ticker,close\n2024-01-31,A,0\n", encoding="utf-8")
    res = audit(d, use_cases=["portfolio"])
    for c in pf.SPEC.checks:
        assert _status(res, c) == NOT_EXECUTABLE, c
    (d / "weights.csv").write_text("date,ticker,weight\n2024-01-31,A,1.0\n", encoding="utf-8")
    res = audit(d, use_cases=["portfolio"])  # one row: nothing may raise
    assert _status(res, "portfolio_turnover") == NOT_EXECUTABLE
    assert _status(res, "portfolio_concentration") == NEEDS_REVIEW


# ------------------------------------------------------------------ battery

PORTFOLIO_CASES = [p for p in available_cases(ROOT / "cases") if p.parent.parent.name == "usecase_portfolio"]


def test_battery_composition():
    assert len(PORTFOLIO_CASES) == 11


@pytest.mark.parametrize("expected", PORTFOLIO_CASES, ids=[p.parent.name for p in PORTFOLIO_CASES])
def test_portfolio_case(expected):
    out = run_case(expected)
    assert out["ok"], "\n".join(out["problems"])
    assert out["false_positives"] == []
