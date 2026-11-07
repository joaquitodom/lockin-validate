"""Use case ``signals``: statistics against hand-computed values, the check contract and the case battery."""

import math
from pathlib import Path

import numpy as np
import pytest

from lockin_validate.auditor import audit
from lockin_validate.cases import available_cases, run_case
from lockin_validate.catalog import CHECKS, REF
from lockin_validate.findings import NEEDS_REVIEW, NOT_EXECUTABLE, PASS
from lockin_validate.inputs import DEFAULTS
from lockin_validate.profiles import PROFILES
from lockin_validate.usecases import REGISTRY, load_all
from lockin_validate.usecases.signals import (
    ALL,
    SPEC,
    assign_quantiles,
    half_life_from_profile,
    nw_tstat,
    spearman,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = available_cases(ROOT / "cases" / "usecase_signals")


# ---------------------------------------------------------------- statistics

def test_spearman_hand_example():
    # ranks of y with an average tie: [1, 2, 3, 4.5, 4.5]; cov 9.5, var x 10, var y 9.5 -> sqrt(9.5 / 10)
    assert spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 8]) == pytest.approx(math.sqrt(9.5 / 10))
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2, 3, 4], [10, 30, 20, 40]) == pytest.approx(0.8)
    assert math.isnan(spearman([1, 2], [1, 2]))
    assert math.isnan(spearman([1, 1, 1], [1, 2, 3]))
    assert spearman([1, 2, np.nan, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_newey_west_tstat_against_direct_computation():
    x = np.array([0.3, -0.1, 0.4, 0.2, -0.2, 0.5, 0.1, 0.0])
    n = len(x)
    m = x.mean()
    d = x - m
    g = [float((d[k:] * d[: n - k]).sum() / n) if k else float((d * d).sum() / n) for k in range(3)]
    L = 2
    var = g[0] + 2 * ((1 - 1 / (L + 1)) * g[1] + (1 - 2 / (L + 1)) * g[2])
    expected_t = m / math.sqrt(var / n)
    out = nw_tstat(x, L)
    assert out["t"] == pytest.approx(expected_t)
    assert out["lags"] == 2 and out["n"] == n and out["mean"] == pytest.approx(m)
    # L = 0: the plain t-stat with the 1/n variance
    plain = nw_tstat(x, 0)
    assert plain["t"] == pytest.approx(m / math.sqrt(g[0] / n))
    assert math.isnan(nw_tstat([1.0, 2.0], 0)["t"])


def test_quantile_assignment():
    v = np.array([5, 1, 9, 3, 7, 2, 8, 4, 6, 10], dtype=float)
    b = assign_quantiles(v, 5)
    assert list(b) == [3, 1, 5, 2, 4, 1, 4, 2, 3, 5]
    assert sorted(np.bincount(b)[1:]) == [2, 2, 2, 2, 2]
    # tied values share one bucket (average rank); NaN gets bucket 0
    b2 = assign_quantiles([1, 1, 1, 1, np.nan], 2)
    assert list(b2) == [2, 2, 2, 2, 0]


def test_half_life_from_profile():
    rho = [0.5 ** k for k in range(1, 6)]
    assert half_life_from_profile(rho) == pytest.approx(1.0)
    assert half_life_from_profile([0.9 ** k for k in range(1, 4)]) == pytest.approx(math.log(0.5) / math.log(0.9))
    assert half_life_from_profile([-0.1, 0.0]) == 0.5
    assert math.isinf(half_life_from_profile([1.0, 1.0]))


# ---------------------------------------------------------------- registration and contract

def test_registered_with_catalog_conventions_and_profile():
    load_all()
    assert REGISTRY["signals"] is SPEC
    assert set(ALL) <= set(CHECKS)
    for c in ALL:
        assert CHECKS[c]["use_case"] == "signals" and CHECKS[c]["block"] == "signals"
        for r in CHECKS[c]["refs"]:
            assert r in REF
    assert DEFAULTS["signal_horizons"] == [1, 5, 21] and DEFAULTS["signal_lag_sessions"] == 1
    assert "signal_research" in PROFILES
    assert "nw87" in REF and "qhs07" in REF


def test_empty_folder_everything_not_executable(tmp_path):
    (tmp_path / "rules.yaml").write_text("conventions:\n  review_date: '2026-10-20'\n", encoding="utf-8")
    res = audit(tmp_path, use_cases=["signals"])
    for c in ALL:
        st = {f.status for f in res.findings if f.check == c}
        assert st == {NOT_EXECUTABLE}, (c, st)
    assert not any("internal error" in f.reason for f in res.findings if f.check in ALL)


def test_odd_data_never_raises(tmp_path):
    (tmp_path / "prices.csv").write_text("date,ticker,close\n2024-01-02,AAA,10\n", encoding="utf-8")
    (tmp_path / "signals.csv").write_text("decision_time,ticker,signal\n2024-01-02,AAA,nan\n2024-01-03,BBB,1\n",
                                          encoding="utf-8")
    res = audit(tmp_path, use_cases=["signals"])
    for c in ALL[1:]:
        assert {f.status for f in res.findings if f.check == c} <= {NOT_EXECUTABLE}, c
    # alignment: the only row with a ticker in prices.csv has no numeric signal; the other has no prices (coverage)
    assert {f.status for f in res.findings if f.check == ALL[0]} <= {NOT_EXECUTABLE, NEEDS_REVIEW}
    assert not any("internal error" in f.reason for f in res.findings if f.check in ALL)


# ---------------------------------------------------------------- battery

def test_cases_exist():
    names = {p.parent.name for p in CASES}
    assert {"01_clean_predictive", "02_noise_signal", "03_lookahead_same_close", "04_high_turnover",
            "05_short_leg_only", "06_insufficient", "07_single_asset", "08_lag_zero_off_session"} <= names


@pytest.mark.parametrize("expected", CASES, ids=[p.parent.name for p in CASES])
def test_case(expected):
    out = run_case(expected)
    assert out["ok"], "\n".join(out["problems"])


def test_clean_case_values_and_no_pass_on_judgement():
    res = audit(ROOT / "cases" / "usecase_signals" / "01_clean_predictive", profile="signal_research")
    assert not any(f.status == PASS for f in res.findings if f.check == "signal_predictive_power")
    m = res.metrics["signal_predictive_power"]["table"]
    assert m[0]["horizon"] == 1 and m[0]["mean_ic"] > 0.03 and m[0]["t_stat"] > 3
    assert m[1]["nw_lags"] == 4 and m[2]["nw_lags"] == 20  # daily decisions, overlapping windows of 5 and 21
    assert res.metrics["signal_turnover"]["rho1"] > 0.8
    assert res.metrics["signal_quantile_spread"]["monotonicity"] == pytest.approx(1.0)


def test_single_asset_uses_time_series_mode():
    res = audit(ROOT / "cases" / "usecase_signals" / "07_single_asset", use_cases=["signals"])
    f = [x for x in res.findings if x.check == "signal_predictive_power"][0]
    assert f.status != NOT_EXECUTABLE and "TIME-SERIES" in f.procedure


# ---------------------------------------------------------------------------- review v0.3.0 A regressions

REVIEW = ROOT / "cases_review_v030"


def _review_audit(group: str, prefix: str):
    import json

    folder = next((REVIEW / group).glob(prefix + "*"))
    exp = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    return audit(folder, profile=exp.get("profile"))


def test_h1_tied_values_share_a_bucket():
    from lockin_validate.usecases.signals import assign_quantiles

    vals = np.array([1, 2, 3] * 20, dtype=float)
    b = assign_quantiles(vals, 5)
    for v in (1.0, 2.0, 3.0):
        assert len(set(b[vals == v])) == 1  # one bucket per value, whatever the file order
    assert (assign_quantiles(vals[::-1], 5)[::-1] == b).all()
    assert b[vals == 1].max() < b[vals == 2].max() < b[vals == 3].max()
    assert (assign_quantiles(np.arange(10.0), 5) == np.repeat([1, 2, 3, 4, 5], 2)).all()  # no ties: unchanged


def test_h1_skill_less_three_level_signal_has_no_significant_spread():
    res = _review_audit("signals", "04_")
    f = [x for x in res.findings if x.check == "signal_quantile_spread"]
    assert f and all(x.status != "INFO" for x in f)


def test_m1_constant_signal_turnover_and_spread_not_executable():
    res = _review_audit("signals", "03_")
    assert res.status_of("signal_turnover") == NOT_EXECUTABLE
    assert res.status_of("signal_quantile_spread") == NOT_EXECUTABLE
