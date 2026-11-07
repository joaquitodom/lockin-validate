"""Use case ``forecast``: statistics against direct computations and the check contract."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lockin_validate.auditor import audit
from lockin_validate.cases import available_cases, run_case
from lockin_validate.findings import NOT_EXECUTABLE, PASS, AuditResult
from lockin_validate.inputs import read_package
from lockin_validate.usecases import REGISTRY, load_all
from lockin_validate.usecases import forecast as fc

ROOT = Path(__file__).resolve().parents[1]
CASES = available_cases(ROOT / "cases" / "usecase_forecast")
load_all()


# ---------------------------------------------------------------------------- statistics

def test_diebold_mariano_tiny_example():
    em = np.array([0.5, -1.0, 0.2, 0.8, -0.3, 1.1])
    en = np.array([1.0, -1.5, 0.7, 1.2, -0.9, 1.4])
    d = em ** 2 - en ** 2
    T = d.size
    dm_direct = d.mean() / math.sqrt(((d - d.mean()) ** 2).mean() / T)  # h = 1: LRV = population variance
    out = fc.diebold_mariano(em, en, 1)
    assert out["dm"] == pytest.approx(dm_direct, rel=1e-12)
    assert out["dm_hln"] == pytest.approx(dm_direct * math.sqrt((T + 1 - 2) / T), rel=1e-12)
    assert out["dm"] < 0 and out["p_model_better"] < 0.5
    # h = 2 Newey-West with one Bartlett lag, weight 1/2
    out2 = fc.diebold_mariano(em, en, 2)
    dd = d - d.mean()
    lrv = (dd * dd).sum() / T + 2 * 0.5 * (dd[1:] * dd[:-1]).sum() / T
    assert out2["dm"] == pytest.approx(d.mean() / math.sqrt(lrv / T), rel=1e-12)


def test_student_t_tail_and_chi2():
    assert fc.student_t_cdf(0.0, 5) == pytest.approx(0.5)
    assert fc.student_t_cdf(2.015, 5) == pytest.approx(0.95, abs=2e-3)  # table value t_{0.95, 5}
    assert fc.student_t_cdf(1.96, 1e7) == pytest.approx(0.975, abs=1e-3)
    assert fc.chi2_2_pvalue(5.991) == pytest.approx(0.05, abs=1e-3)


def test_mincer_zarnowitz_matches_lstsq():
    rng = np.random.default_rng(0)
    f = rng.normal(0, 1, 80)
    y = 0.3 + 1.2 * f + rng.normal(0, 0.5, 80)
    X = np.column_stack([np.ones(80), f])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    out = fc.mincer_zarnowitz(y, f, 1)
    assert out["a"] == pytest.approx(beta[0], rel=1e-10)
    assert out["b"] == pytest.approx(beta[1], rel=1e-10)
    # White (lags = 0) covariance by hand
    u = y - X @ beta
    xtx_inv = np.linalg.inv(X.T @ X)
    V = xtx_inv @ ((X * u[:, None]).T @ (X * u[:, None])) @ xtx_inv
    r = beta - np.array([0, 1])
    W = r @ np.linalg.solve(V, r)
    assert out["wald"] == pytest.approx(W, rel=1e-8)
    assert out["p_value"] == pytest.approx(math.exp(-W / 2))
    perfect = fc.mincer_zarnowitz(f, f, 1)
    assert perfect["a"] == pytest.approx(0, abs=1e-10) and perfect["b"] == pytest.approx(1, abs=1e-10)


def test_pesaran_timmermann_textbook_table():
    # 2x2 table (actual up / forecast up): 30 up-up, 10 up-down, 15 down-up, 45 down-down, n = 100
    a_up = np.array([True] * 40 + [False] * 60)
    f_up = np.array([True] * 30 + [False] * 10 + [True] * 15 + [False] * 45)
    out = fc.pesaran_timmermann(a_up, f_up)
    n, py, px, p = 100, 0.40, 0.45, 0.75
    ps = py * px + (1 - py) * (1 - px)  # 0.51
    vp = ps * (1 - ps) / n
    vs = ((2 * py - 1) ** 2 * px * (1 - px) / n + (2 * px - 1) ** 2 * py * (1 - py) / n
          + 4 * py * px * (1 - py) * (1 - px) / n ** 2)
    pt = (p - ps) / math.sqrt(vp - vs)
    assert out["hit_ratio"] == pytest.approx(0.75)
    assert out["p_independence"] == pytest.approx(0.51)
    assert out["pt"] == pytest.approx(pt, rel=1e-12)
    assert out["p_value"] < 0.001
    assert (out["up_up"], out["up_down"], out["down_up"], out["down_down"]) == (30, 10, 15, 45)
    degenerate = fc.pesaran_timmermann(np.ones(20, bool), np.array([True, False] * 10))
    assert math.isnan(degenerate["pt"])


def test_ljung_box_from_lag_h():
    rng = np.random.default_rng(1)
    e = rng.normal(0, 1, 200)
    assert fc.ljung_box_from(e, 1, 11)["Q"] == pytest.approx(fc.ljung_box(e, 11)["Q"])
    # h = 3: Q = T r' Sigma^-1 r with Bartlett's covariance under the MA(2) null, built by hand
    rho = [1.0] + fc.autocorrelations(e, 13)
    ks = list(range(3, 14))
    sig = np.zeros((11, 11))
    for i, k in enumerate(ks):
        for j, m in enumerate(ks):
            sig[i, j] = sum(rho[abs(x)] * (rho[abs(x + m - k)] if abs(x + m - k) <= 2 else 0.0) for x in (-2, -1, 0, 1, 2))
    r = np.array([rho[k] * math.sqrt(202 / (200 - k)) for k in ks])
    Q = 200 * r @ np.linalg.solve(sig, r)
    out = fc.ljung_box_from(e, 3, 13)
    assert out["Q"] == pytest.approx(Q) and out["df"] == 11
    # true 3-step AR(1) errors are MA(2): the test must not reject them (size, not power)
    rng = np.random.default_rng(3)
    rejections = 0
    for _ in range(60):
        eps = rng.normal(0, 1, 400)
        y = np.zeros(400)
        for t in range(1, 400):
            y[t] = 0.7 * y[t - 1] + eps[t]
        err = y[3:] - 0.7 ** 3 * y[:-3]
        rejections += fc.ljung_box_from(err, 3, 13)["p_value"] < 0.05
    assert rejections <= 10


def test_expected_max_t():
    assert fc.expected_max_t(1) == 0.0
    assert 1.5 < fc.expected_max_t(12) < 1.8
    assert fc.expected_max_t(100) > fc.expected_max_t(12)


# ---------------------------------------------------------------------------- naive construction

def _write(tmp_path: Path, text: str, rules: str | None = None) -> Path:
    (tmp_path / "forecasts.csv").write_text(text, encoding="utf-8")
    if rules:
        (tmp_path / "rules.yaml").write_text(rules, encoding="utf-8")
    return tmp_path


def test_naive_respects_actual_available_from(tmp_path):
    csv = ("origin_date,target_date,forecast,actual,actual_available_from\n"
           "2020-01-31,2020-02-29,1.0,10,2020-04-15\n"
           "2020-02-29,2020-03-31,1.0,20,2020-05-15\n"
           "2020-03-31,2020-04-30,1.0,30,2020-06-15\n"
           "2020-04-30,2020-05-31,1.0,40,2020-07-15\n"
           "2020-05-31,2020-06-30,1.0,50,2020-08-15\n")
    pkg = read_package(_write(tmp_path, csv))
    p = fc.Prepared(pkg)
    d = p.df.sort_values("row")
    # plain random walk: last actual by target date; publication-aware: the one released by the origin
    assert list(d["naive_plain"].round(6).fillna(-1)) == [-1, 10, 20, 30, 40]
    assert list(d["naive_aware"].fillna(-1)) == [-1, -1, -1, 10, 20]  # 10 (Feb) is published 15 Apr <= 30 Apr
    assert p.naive_source.startswith("last actual known at the origin, publication-aware")
    # without publication dates both coincide
    pkg2 = read_package(_write(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path / "b",
                               csv.replace(",actual_available_from", "").replace(",2020-0", ",").split("\n")[0]
                               + "\n" + "\n".join(line.rsplit(",", 1)[0] for line in csv.split("\n")[1:])))
    p2 = fc.Prepared(pkg2)
    assert list(p2.df.sort_values("row")["naive_aware"].fillna(-1)) == [-1, 10, 20, 30, 40]


def test_mean_and_zero_naive_and_profiles(tmp_path):
    csv = "origin_date,target_date,forecast,actual\n" + "\n".join(
        f"2020-01-{i:02d},2020-01-{i + 1:02d},0.1,{i / 10:.1f}" for i in range(1, 10))
    folder = _write(tmp_path, csv, "conventions:\n  forecast_naive: mean\n")
    p = fc.Prepared(read_package(folder))
    d = p.df.sort_values("row")
    assert p.kind == "mean"
    assert d["naive_used"].iloc[2] == pytest.approx((0.1 + 0.2) / 2)  # mean of the actuals known at the origin
    pz = fc.Prepared(read_package(folder, profile="forecast_returns"))
    assert pz.kind == "mean"  # rules.yaml wins over the profile
    (folder / "rules.yaml").unlink()
    pz = fc.Prepared(read_package(folder, profile="forecast_returns"))
    assert pz.kind == "zero" and (pz.df["naive_used"] == 0).all()
    pm = read_package(folder, profile="forecast_macro")
    assert pm.conv("forecast_naive") == "random_walk" and pm.conv("forecast_revised_data") is True


def test_horizon_inferred_from_spacing(tmp_path):
    rows = ["origin_date,target_date,forecast,actual"]
    ends = pd.date_range("2019-01-31", periods=14, freq="ME")
    for i in range(11):
        rows.append(f"{ends[i].date()},{ends[i + 3].date()},0,{i}")
    p = fc.Prepared(read_package(_write(tmp_path, "\n".join(rows))))
    assert set(p.df["h"]) == {3}


# ---------------------------------------------------------------------------- contract

def test_registered_spec():
    uc = REGISTRY["forecast"]
    assert uc.detect_files == ["forecasts"]
    assert set(uc.checks) == {"forecast_origin_integrity", "forecast_vs_naive", "forecast_bias",
                              "forecast_directional", "forecast_error_dynamics", "forecast_multiple_models"}
    for entry in uc.catalog.values():
        assert all(k in entry for k in ("what", "why", "fix", "allows", "does_not_allow", "refs"))


def test_empty_folder_all_not_executable(tmp_path):
    res = audit(tmp_path, use_cases=["forecast"])
    st = {f.check: f.status for f in res.findings if f.block == "forecast"}
    assert set(st) == set(REGISTRY["forecast"].checks)
    assert set(st.values()) == {NOT_EXECUTABLE}
    assert all(f.reason for f in res.findings if f.block == "forecast")


def test_odd_data_never_raises(tmp_path):
    _write(tmp_path, "origin_date,target_date,forecast,actual\n2020-01-01,2020-01-02,nan,\n")
    res = AuditResult()
    fc.run(read_package(tmp_path), res)
    assert {f.status for f in res.findings} == {NOT_EXECUTABLE}
    _write(tmp_path, "origin_date,target_date,forecast,actual\n2020-01-01,2020-01-02,1,1\n")
    res = AuditResult()
    fc.run(read_package(tmp_path), res)
    assert PASS not in {f.status for f in res.findings if f.check != "forecast_origin_integrity"}


def test_aliases_and_schema(tmp_path):
    csv = "forecast_date,date,yhat,realized,model\n" + "\n".join(
        f"2020-01-{i:02d},2020-01-{i + 1:02d},0.1,{i / 10:.1f},m" for i in range(1, 10))
    pkg = read_package(_write(tmp_path, csv))
    assert pkg.has("forecasts")
    assert {"origin_date", "target_date", "forecast", "actual"} <= set(pkg.df("forecasts").columns)


def test_duplicate_contradictory_forecast_is_confirmed_error(tmp_path):
    csv = "origin_date,target_date,forecast,actual\n" + "\n".join(
        f"2020-01-{i:02d},2020-01-{i + 1:02d},0.1,{i / 10:.1f}" for i in range(1, 10)) + "\n2020-01-01,2020-01-02,0.9,0.1\n"
    res = AuditResult()
    fc.check_origin_integrity(read_package(_write(tmp_path, csv)), res)
    f = res.findings[0]
    assert f.status == "CONFIRMED_ERROR" and "different forecasts" in f.title and f.evidence[0]["row"] >= 2


def test_every_finding_has_procedure_and_evidence_rows():
    for exp in CASES:
        res = audit(exp.parent, use_cases=["forecast"])
        for f in res.findings:
            if f.block != "forecast":
                continue
            if f.status == NOT_EXECUTABLE:
                assert f.reason
            else:
                assert f.procedure
            if f.status in ("CONFIRMED_ERROR",):
                assert f.evidence and all("row" in e for e in f.evidence)


# ---------------------------------------------------------------------------- battery

def test_battery_composition():
    names = sorted(p.parent.name for p in CASES)
    assert len(names) == 8 and names[0].startswith("01_clean") and names[-1].startswith("08_")


@pytest.mark.parametrize("expected", CASES, ids=[p.parent.name for p in CASES])
def test_case(expected, tmp_path):
    out = run_case(expected, tmp_path)
    assert out["ok"], "\n".join(out["problems"])


def test_clean_case_no_alerts_from_module():
    out = run_case(CASES[0])
    assert out["false_positives"] == []
    assert not [c for c in out["unexpected_review"] if c.startswith("forecast_")]


# ---------------------------------------------------------------------------- review v0.3.0 A regressions

def _review_audit(prefix: str):
    folder = next((ROOT / "cases_review_v030" / "forecast").glob(prefix + "*"))
    return audit(folder)


def test_h5_business_day_weekend_gaps_are_one_step():
    res = _review_audit("02_")
    assert any(x.check == "forecast_origin_integrity" and x.status == PASS for x in res.findings)
    vs = [x for x in res.findings if x.check == "forecast_vs_naive"]
    assert vs and all(x.evidence[0]["horizon"] == 1 for x in vs)
    assert len(vs) == 1  # a single h = 1 group, no spurious h = 3 group


def test_h6_exact_duplicates_dropped_and_counted():
    res = _review_audit("06_")
    assert res.status_of("forecast_vs_naive") == NOT_EXECUTABLE
    f = next(x for x in res.findings if x.check == "forecast_origin_integrity" and x.status == "NEEDS_REVIEW")
    assert "20 exact duplicate row" in f.title


def test_l2_zero_naive_error_has_no_inf_in_text():
    res = _review_audit("03_")
    for x in res.findings:
        if x.check == "forecast_vs_naive":
            assert "inf" not in (x.title + " " + x.detail).lower().replace("information", "")
