"""Use case ``risk``: statistics against closed-form / hand-computed values, the check contract and the battery."""

import math
from pathlib import Path

import numpy as np
import pytest

from lockin_validate.auditor import audit
from lockin_validate.cases import available_cases, run_case
from lockin_validate.usecases import REGISTRY, load_all
from lockin_validate.usecases.risk import (
    SPEC,
    acerbi_szekely_z2,
    binom_acceptance_region,
    binom_cdf,
    chi2_sf,
    christoffersen_ind,
    exception_clusters,
    kupiec_lr,
    longest_run,
    parse_level,
    traffic_addon,
    traffic_zone,
)

ROOT = Path(__file__).resolve().parents[1] / "cases" / "usecase_risk"
CHECKS = ["var_input_coherence", "var_coverage", "var_independence", "basel_traffic_light", "es_backtest",
          "var_model_stability"]


def _kupiec_by_hand(x, n, p):
    pi = x / n
    ll0 = (n - x) * math.log(1 - p) + (x * math.log(p) if x else 0.0)
    ll1 = (n - x) * math.log(1 - pi) + (x * math.log(pi) if x else 0.0)
    return -2 * ll0 + 2 * ll1


# ----------------------------------------------------------------------------------------------- statistics

def test_chi2_tails_closed_form_and_gamma():
    assert chi2_sf(3.841459, 1) == pytest.approx(0.05, abs=1e-5)
    assert chi2_sf(5.991465, 2) == pytest.approx(0.05, abs=1e-5)
    assert chi2_sf(7.814728, 3) == pytest.approx(0.05, abs=1e-5)  # regularised gamma branch
    assert chi2_sf(9.487729, 4) == pytest.approx(0.05, abs=1e-5)
    assert chi2_sf(0.0, 1) == 1.0 and chi2_sf(float("nan"), 2) == 1.0


def test_kupiec_textbook_250_days():
    # N = 250, p = 1%: x = 5 gives LR about 1.96 (p about 0.16); x = 6 gives LR about 3.56 (p about 0.059);
    # the non-rejection region at 5% is therefore 1..6 exceptions (Kupiec 1995, Table; Jorion).
    r5 = kupiec_lr(5, 250, 0.01)
    assert r5["lr"] == pytest.approx(_kupiec_by_hand(5, 250, 0.01), abs=1e-9)
    assert r5["lr"] == pytest.approx(1.957, abs=0.01)
    assert r5["p_value"] == pytest.approx(0.162, abs=0.002)
    r6 = kupiec_lr(6, 250, 0.01)
    assert r6["lr"] == pytest.approx(3.555, abs=0.01)
    assert r6["p_value"] == pytest.approx(0.059, abs=0.002)
    assert kupiec_lr(7, 250, 0.01)["p_value"] < 0.05
    assert kupiec_lr(0, 250, 0.01)["lr"] == pytest.approx(-2 * 250 * math.log(0.99), abs=1e-9)  # x = 0 handled
    assert kupiec_lr(0, 250, 0.01)["p_value"] < 0.05  # too few exceptions is also a rejection
    assert kupiec_lr(1, 250, 0.01)["p_value"] > 0.05


def test_binomial_acceptance_region_and_cdf():
    assert binom_cdf(4, 250, 0.01) == pytest.approx(0.8922, abs=1e-3)  # Basel 1996 Table 1
    assert binom_cdf(9, 250, 0.01) == pytest.approx(0.99975, abs=1e-4)
    lo, hi = binom_acceptance_region(250, 0.01, 0.05)
    # equal-tail exact region: P(X = 0) = 8.1% > 2.5% keeps 0 inside; P(X > 6) = 1.4% <= 2.5% closes it at 6.
    # (Kupiec's LR rejects x = 0 with LR = 5.02: the two tests differ in the lower tail, as documented.)
    assert (lo, hi) == (0, 6)
    lo, hi = binom_acceptance_region(1000, 0.01, 0.05)
    assert lo >= 4 and 15 <= hi <= 17


def test_christoffersen_hand_made_sequence():
    # 20 observations: exceptions in two blocks of three -> strong clustering
    h = np.array([0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0])
    r = christoffersen_ind(h)
    assert (r["n00"], r["n01"], r["n10"], r["n11"]) == (11, 2, 2, 4)
    pi01, pi11, pi = 2 / 13, 4 / 6, 6 / 19
    ll0 = 13 * math.log(1 - pi) + 6 * math.log(pi)
    ll1 = 11 * math.log(1 - pi01) + 2 * math.log(pi01) + 2 * math.log(1 - pi11) + 4 * math.log(pi11)
    assert r["lr"] == pytest.approx(-2 * ll0 + 2 * ll1, abs=1e-9)
    assert r["p_value"] < 0.05
    # perfectly spread exceptions: no consecutive pair, LR_ind small
    spread = np.zeros(200, dtype=int)
    spread[::20] = 1
    assert christoffersen_ind(spread)["p_value"] > 0.05
    assert longest_run(h) == 3 and longest_run(spread) == 1
    assert exception_clusters(np.flatnonzero(h)) == (2, 6)
    assert exception_clusters(np.flatnonzero(spread)) == (0, 0)


def test_traffic_light_zones_and_addons():
    zones = [traffic_zone(k, 250) for k in range(13)]
    assert zones == ["green"] * 5 + ["yellow"] * 5 + ["red"] * 3
    assert [traffic_addon(k, 250) for k in range(11)] == [0, 0, 0, 0, 0, 0.40, 0.50, 0.65, 0.75, 0.85, 1.0]
    # another window: the probabilistic rule; it reproduces the 250-day table when applied to 250 (sanity)
    assert all(traffic_zone(k, 500) == "green" for k in range(0, 9))
    assert traffic_zone(9, 500) == "yellow" and traffic_zone(16, 500) == "red"
    assert 0.40 <= traffic_addon(10, 500) <= 0.85


def test_z2_tiny_example():
    # losses positive; ES = 2 every day; 10 days, p = 0.1 -> N p = 1 expected exception
    loss = np.array([0.1, 0.2, 2.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    es = np.full(10, 2.0)
    hits = (loss > 1.5).astype(int)
    assert acerbi_szekely_z2(loss, es, hits, 0.1) == pytest.approx(1 - 2.0 / (10 * 0.1 * 2.0))  # = 0: on target
    loss2 = loss.copy()
    loss2[2] = 4.0  # the realised loss is twice the ES
    assert acerbi_szekely_z2(loss2, es, hits, 0.1) == pytest.approx(-1.0)
    loss3 = loss.copy()
    loss3[5] = 3.0  # a second exception: too many AND too large
    hits3 = (loss3 > 1.5).astype(int)
    assert acerbi_szekely_z2(loss3, es, hits3, 0.1) == pytest.approx(1 - (2.0 + 3.0) / 2.0)


def test_parse_level():
    assert parse_level("var_99", "var") == pytest.approx(0.99)
    assert parse_level("var_975", "var") == pytest.approx(0.975)
    assert parse_level("var_95", "var") == pytest.approx(0.95)
    assert parse_level("es_0.99", "es") == pytest.approx(0.99)
    assert parse_level("var", "var") is None and parse_level("var_x", "var") is None
    assert parse_level("variance", "var") is None


# ----------------------------------------------------------------------------------------------- contract

def test_spec_registered():
    load_all()
    assert "risk" in REGISTRY and REGISTRY["risk"] is SPEC
    assert SPEC.checks == CHECKS
    assert set(SPEC.conventions) >= {"risk_kupiec_alpha", "risk_christoffersen_alpha", "risk_min_observations",
                                     "risk_traffic_light_window", "risk_es_alpha", "risk_var_sign"}


def test_empty_folder_all_not_executable(tmp_path):
    res = audit(tmp_path, use_cases=["risk"])
    for c in CHECKS:
        assert res.status_of(c) == "NOT_EXECUTABLE", c
        f = [x for x in res.findings if x.check == c][0]
        assert "var_forecasts" in f.reason


def test_odd_data_never_raises(tmp_path):
    (tmp_path / "var_forecasts.csv").write_text("date,pnl,var_99\n2024-01-02,abc,\n2024-01-02,,0\n", encoding="utf-8")
    res = audit(tmp_path, use_cases=["risk"])
    for c in CHECKS:
        assert res.status_of(c) in ("NOT_EXECUTABLE", "CONFIRMED_ERROR"), c
    (tmp_path / "var_forecasts.csv").write_text("date,return\n2024-01-02,0.01\n2024-01-03,-0.02\n", encoding="utf-8")
    res = audit(tmp_path, use_cases=["risk"])
    for c in CHECKS:
        st = res.status_of(c)
        assert st == "NOT_EXECUTABLE", (c, st)
        assert "var_<level>" in [x for x in res.findings if x.check == c][0].reason


def test_loss_alias_and_declared_negative_quantile(tmp_path):
    # a `loss` column (sign inverted) and VaR declared as negative quantiles: the clean 01 model must still pass
    import csv

    import pandas as pd

    src = pd.read_csv(ROOT / "01_clean_normal" / "var_forecasts.csv")
    with open(tmp_path / "var_forecasts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "loss", "var_99", "var_95"])
        for r in src.itertuples():
            w.writerow([r.date, f"{-r.pnl:.8f}", f"{-r.var_99:.8f}", f"{-r.var_95:.8f}"])
    (tmp_path / "rules.yaml").write_text("conventions:\n  risk_var_sign: negative_quantile\n", encoding="utf-8")
    res = audit(tmp_path, use_cases=["risk"])
    assert res.status_of("var_coverage") == "PASS"
    assert res.status_of("var_input_coherence") == "INFO"
    info = [f for f in res.findings if f.check == "var_input_coherence" and f.status == "INFO"][0]
    assert "loss" in info.detail and "negative_quantile" in info.detail
    assert res.metrics["risk"]["coverage"]["99%"]["exceptions"] >= 4


def test_traffic_light_window_from_rules(tmp_path):
    import shutil

    shutil.copy(ROOT / "02_too_many_exceptions" / "var_forecasts.csv", tmp_path / "var_forecasts.csv")
    (tmp_path / "rules.yaml").write_text("risk:\n  window: 500\n", encoding="utf-8")
    res = audit(tmp_path, use_cases=["risk"])
    assert res.metrics["risk"]["traffic_light"]["window"] == 500
    assert res.metrics["risk"]["traffic_light"]["zone"] == "red"


# ----------------------------------------------------------------------------------------------- battery

CASES = available_cases(ROOT)


def test_battery_has_eight_cases():
    assert len(CASES) == 8


@pytest.mark.parametrize("expected", CASES, ids=[p.parent.name for p in CASES])
def test_case(expected):
    out = run_case(expected)
    assert out["ok"], "\n".join(out["problems"])
    assert out["false_positives"] == []


def test_clean_and_adversarial_cases_raise_no_review():
    for name in ("01_clean_normal", "08_sign_inverted"):
        out = run_case(ROOT / name / "expected.json")
        risk_reviews = [c for c in out["unexpected_review"] if c in CHECKS]
        assert risk_reviews == [], (name, risk_reviews)
