"""Use case ``ml``: statistics against hand-computed values, the check contract, and the case battery."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from lockin_validate.auditor import audit
from lockin_validate.cases import available_cases, run_case
from lockin_validate.findings import CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE, PASS, AuditResult
from lockin_validate.inputs import read_package
from lockin_validate.usecases import ml

ROOT = Path(__file__).resolve().parents[1]
ML_CASES = [p for p in available_cases(ROOT / "cases") if p.parent.parent.name == "usecase_ml"]


# ---------------------------------------------------------------------------- statistics

def test_auc_hand_computed():
    # positives score 0.9, 0.8, 0.4; negatives 0.7, 0.3, 0.2, 0.1 -> pairs with pos > neg:
    # 0.9: 4, 0.8: 4, 0.4: 3 -> 11 of 12
    score = [0.9, 0.8, 0.4, 0.7, 0.3, 0.2, 0.1]
    y = [1, 1, 1, 0, 0, 0, 0]
    assert ml.auc(score, y) == pytest.approx(11 / 12)
    assert ml.auc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == pytest.approx(0.5)  # all tied -> one half
    assert ml.auc([0.2, 0.9], [0, 1]) == 1.0
    assert math.isnan(ml.auc([0.2, 0.9], [1, 1]))


def test_auc_se_hanley_mcneil():
    # A = 0.8, n1 = 10, n0 = 20: Q1 = 0.8/1.2, Q2 = 1.28/1.8
    a, n1, n0 = 0.8, 10, 20
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    v = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)
    assert ml.auc_se(a, n1, n0) == pytest.approx(math.sqrt(v))
    assert ml.auc_se(0.8, 10, 20) == pytest.approx(0.0936, abs=5e-4)


def test_psi_hand_computed():
    # reference: 100 values uniform over 10 bins (10 each); current: all mass in the top bin -> every other bin has
    # a = 1e-4 floor
    ref = np.repeat(np.arange(10), 10) + 0.5
    cur = np.full(50, 9.5)
    r = ml.psi(ref, cur, 10)
    e = 0.1
    expected = 9 * (1e-4 - e) * math.log(1e-4 / e) + (1.0 - e) * math.log(1.0 / e)
    assert r["bins"] == 10
    assert r["psi"] == pytest.approx(expected, rel=1e-6)
    # identical distributions -> PSI 0
    assert ml.psi(ref, ref, 10)["psi"] == pytest.approx(0.0)
    # two-bin hand example: expected 50/50, actual 30/70 -> (0.3-0.5)ln(0.6) + (0.7-0.5)ln(1.4)
    ref2 = np.r_[np.zeros(50), np.ones(50)]
    cur2 = np.r_[np.zeros(30), np.ones(70)]
    assert ml.psi(ref2, cur2, 2)["psi"] == pytest.approx(-0.2 * math.log(0.6) + 0.2 * math.log(1.4))


def test_ece_tiny_table():
    # two bins of 2: bin 1 p = (0.1, 0.2) mean 0.15, observed 0.5 -> |0.35|; bin 2 p = (0.8, 0.9) mean 0.85,
    # observed 1.0 -> |0.15|; ECE = 0.5 * 0.35 + 0.5 * 0.15 = 0.25
    r = ml.reliability([0.1, 0.2, 0.8, 0.9], [1, 0, 1, 1], 2)
    assert r["ece"] == pytest.approx(0.25)
    assert r["n_bins"] == 2
    assert r["brier"] == pytest.approx(np.mean([(0.1 - 1) ** 2, 0.2 ** 2, 0.2 ** 2, 0.1 ** 2]))
    assert r["reliability"] == pytest.approx(0.5 * 0.35 ** 2 + 0.5 * 0.15 ** 2)
    assert r["uncertainty"] == pytest.approx(0.75 * 0.25)
    assert r["resolution"] == pytest.approx(0.5 * 0.25 ** 2 + 0.5 * 0.25 ** 2)
    # Murphy decomposition is exact when p is constant inside each bin
    r2 = ml.reliability([0.1, 0.1, 0.9, 0.9], [1, 0, 1, 1], 2)
    assert r2["brier"] == pytest.approx(r2["reliability"] - r2["resolution"] + r2["uncertainty"])


def test_chi2_tail_closed_form():
    # 2 degrees of freedom: P(X > x) = exp(-x / 2) exactly
    for x in (1.0, 3.0, 9.21):
        assert ml.chi2_sf(x, 2) == pytest.approx(math.exp(-x / 2), abs=0.01)
    assert ml.chi2_sf(15.5, 8) == pytest.approx(0.05, abs=0.01)


def test_spearman_and_ks():
    assert ml.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert ml.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert ml.ks_statistic([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == pytest.approx(1.0)


def test_regression_metrics():
    m = ml.regression_metrics([1, 2, 3], [1, 2, 3])
    assert m["r2"] == 1.0 and m["rmse"] == 0.0 and m["mae"] == 0.0
    m = ml.regression_metrics([2, 2, 2], [1, 2, 3])
    assert m["r2"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------- check contract

def _write(folder: Path, name: str, header: str, rows: list[str]) -> None:
    (folder / name).write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_split_leakage_on_six_rows(tmp_path):
    # s3 is a test sample inside the training window; s2 has a label_end after the first test timestamp; s5 is
    # both train and test; s6 is a clean test sample
    _write(tmp_path, "ml_samples.csv", "sample_id,timestamp,split,label_end", [
        "s1,2020-01-02,train,2020-01-22",
        "s2,2020-06-30,train,2020-07-20",
        "s3,2020-03-15,test,2020-04-04",
        "s5,2020-02-01,train,2020-02-21",
        "s5,2020-08-01,test,2020-08-21",
        "s6,2020-07-10,test,2020-07-30",
    ])
    res = AuditResult()
    ml.check_split_leakage(read_package(tmp_path), res)
    errs = [f for f in res.findings if f.check == "ml_split_leakage" and f.status == CONFIRMED_ERROR]
    titles = " | ".join(f.title for f in errs)
    assert "more than one split" in titles
    assert "inside the training window" in titles
    assert "purging" in titles
    ids = {e.get("sample_id") for f in errs for e in f.evidence}
    assert {"s3", "s5", "s2"} <= ids
    assert all("row" in e for f in errs for e in f.evidence)
    assert res.status_of("ml_split_leakage") == CONFIRMED_ERROR


def test_split_leakage_pass_and_review_without_label_end(tmp_path):
    _write(tmp_path, "ml_samples.csv", "sample_id,timestamp,split,label_end", [
        "a,2020-01-02,train,2020-01-22", "b,2020-02-03,train,2020-02-23", "c,2020-04-01,test,2020-04-21"])
    res = AuditResult()
    ml.check_split_leakage(read_package(tmp_path), res)
    assert res.status_of("ml_split_leakage") == PASS
    _write(tmp_path, "ml_samples.csv", "sample_id,timestamp,split", ["a,2020-01-02,train", "c,2020-04-01,test"])
    res = AuditResult()
    ml.check_split_leakage(read_package(tmp_path), res)
    assert res.status_of("ml_split_leakage") == NEEDS_REVIEW  # cannot verify purging, never PASS


def test_feature_lag_is_confirmed_error(tmp_path):
    _write(tmp_path, "ml_samples.csv", "sample_id,timestamp,split,label_end", [
        "a,2020-01-02,train,2020-01-22", "c,2020-04-01,test,2020-04-21"])
    _write(tmp_path, "ml_features.csv", "feature,available_from_lag_days", ["x1,0", "x2,3"])
    res = AuditResult()
    ml.check_split_leakage(read_package(tmp_path), res)
    f = next(f for f in res.findings if f.status == CONFIRMED_ERROR)
    assert f.evidence[0]["feature"] == "x2"


def test_empty_folder_all_not_executable(tmp_path):
    res = audit(tmp_path, use_cases=["ml"])
    for cid in ml.SPEC.checks:
        assert res.status_of(cid) == NOT_EXECUTABLE, cid
    # running the module directly on an empty package never raises either
    res2 = AuditResult()
    ml.run(read_package(tmp_path), res2)
    assert {f.status for f in res2.findings} == {NOT_EXECUTABLE}
    assert len(res2.findings) == len(ml.SPEC.checks)


def test_odd_data_never_raises(tmp_path):
    _write(tmp_path, "ml_samples.csv", "sample_id,timestamp,split", ["a,not-a-date,train"])
    _write(tmp_path, "ml_predictions.csv", "sample_id,prediction,actual", ["a,,"])
    _write(tmp_path, "ml_feature_values.csv", "sample_id,feature,value", ["a,x,nan"])
    res = AuditResult()
    ml.run(read_package(tmp_path), res)
    assert {f.check for f in res.findings} >= set(ml.SPEC.checks)
    assert not any(f.status == PASS for f in res.findings)


def test_spec_registered_and_conventions():
    from lockin_validate import catalog, inputs
    from lockin_validate.profiles import PROFILES

    for cid in ml.SPEC.checks:
        assert cid in catalog.CHECKS and cid in inputs.REQUIREMENTS
    assert inputs.FILES["ml_samples"] == "ml_samples.csv"
    assert inputs.DEFAULTS["ml_psi_error"] == 0.25
    assert PROFILES["ml_classification"]["conventions"]["ml_task"] == "classification"
    for k in ("hanley82", "siddiqi06", "guo17", "brier50", "kaufman12", "bergmeir12"):
        assert k in catalog.REF


def test_evaluation_protocol_reads_n_trials(tmp_path):
    _write(tmp_path, "ml_samples.csv", "sample_id,timestamp,split,label_end", [
        "a,2020-01-02,train,2020-01-22", "c,2020-04-01,test,2020-04-21"])
    _write(tmp_path, "ml_predictions.csv", "sample_id,prediction,actual,model", [
        "a,1,1,m1", "c,0,1,m1", "c,1,1,m2", "c,1,0,m3"])
    (tmp_path / "declared_results.json").write_text('{"n_trials": 3}', encoding="utf-8")
    res = AuditResult()
    ml.check_evaluation_protocol(read_package(tmp_path), res)
    f = res.findings[-1]
    assert f.status == NEEDS_REVIEW and "3 models" in f.title and "3 trials declared" in f.detail


# ---------------------------------------------------------------------------- case battery

def test_ml_battery_composition():
    names = {p.parent.name for p in ML_CASES}
    assert len(names) >= 11
    assert {"01_clean_purged", "10_insufficient", "11_regression_clean", "12_purged_kfold_legit"} <= names


@pytest.mark.parametrize("expected", ML_CASES, ids=[p.parent.name for p in ML_CASES])
def test_ml_case(expected):
    out = run_case(expected)
    assert out["ok"], "\n".join(out["problems"])
    assert out["false_positives"] == []


# ---------------------------------------------------------------------------- review v0.3.0 A regressions

def _review_audit(prefix: str):
    import json

    folder = next((ROOT / "cases_review_v030" / "ml").glob(prefix + "*"))
    exp = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    return audit(folder, profile=exp.get("profile"))


def test_h2_single_class_in_test_overfit_gap_not_executable():
    res = _review_audit("03_")
    f = [x for x in res.findings if x.check == "ml_overfit_gap"]
    assert f and all(x.status == NOT_EXECUTABLE for x in f)
    assert "undefined" in (f[0].reason or f[0].detail)


def test_h3_base_rate_zero_calibration_never_passes():
    res = _review_audit("03_")
    f = [x for x in res.findings if x.check == "ml_calibration"]
    assert f and all(x.status == NEEDS_REVIEW for x in f)
    assert "2 SE" in f[0].detail


def test_h4_rankdata_and_auc_ignore_nan():
    r = ml.rankdata([3.0, float("nan"), 1.0, 2.0])
    assert r[0] == 3 and r[2] == 1 and r[3] == 2 and math.isnan(r[1])
    clean = ml.auc([0.9, 0.8, 0.4, 0.7, 0.3], [1, 1, 1, 0, 0])
    assert ml.auc([0.9, 0.8, float("nan"), 0.4, 0.7, 0.3], [1, 1, 1, 1, 0, 0]) == pytest.approx(clean)


def test_h4_blank_probability_rows_dropped_and_disclosed():
    res = _review_audit("01_")
    f = next(x for x in res.findings if x.check == "ml_overfit_gap")
    assert "3 rows with a blank probability" in f.detail
    n_cal = next(x for x in res.findings if x.check == "ml_calibration")
    assert "n = 997" in n_cal.detail
    assert any(e.get("split") == "test" and e.get("n") == 997 for e in f.evidence)
