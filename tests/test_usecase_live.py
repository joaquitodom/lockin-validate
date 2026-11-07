"""Use case ``live``: statistics against hand-computed values and the check contract."""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from lockin_validate.auditor import audit
from lockin_validate.cases import available_cases, run_case
from lockin_validate.catalog import CHECKS
from lockin_validate.findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, NOT_EXECUTABLE, PASS, AuditResult
from lockin_validate.inputs import REQUIREMENTS, read_package
from lockin_validate.usecases import live

ROOT = Path(__file__).resolve().parents[1]
LIVE_CASES = [p for p in available_cases(ROOT / "cases") if p.parent.parent.name == "usecase_live"]
CHECK_IDS = ["live_period_integrity", "live_vs_shadow_backtest", "live_performance_decay", "live_structural_break",
             "live_execution_quality", "live_declared_vs_realised"]


# ------------------------------------------------------------------ statistics on hand examples

def test_tracking_error_hand_example():
    lv = np.array([0.010, -0.005, 0.002, 0.007, -0.001])
    bt = np.array([0.008, -0.004, 0.003, 0.009, -0.002])
    d = lv - bt  # 0.002, -0.001, -0.001, -0.002, 0.001 -> mean -0.0002
    sd = math.sqrt(sum((x + 0.0002) ** 2 for x in d) / 4)
    assert live.tracking_error(lv, bt, 252) == pytest.approx(sd * math.sqrt(252))


def test_hac_mean_test_matches_plain_t_with_zero_lags():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    h = live.hac_mean_test(x, lags=0)
    # mean 3.5; population variance 35/12; se = sqrt((35/12) / 6)
    assert h["mean"] == pytest.approx(3.5)
    assert h["se"] == pytest.approx(math.sqrt((35 / 12) / 6))
    assert h["t"] == pytest.approx(3.5 / math.sqrt((35 / 12) / 6))


def test_hac_mean_test_one_lag_by_hand():
    x = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])  # alternating: strong negative autocorrelation
    h = live.hac_mean_test(x, lags=1)
    e = x - x.mean()
    g0 = float(e @ e) / 6
    g1 = float(e[1:] @ e[:-1]) / 6
    lrv = g0 + 2 * 0.5 * g1  # Bartlett weight 1 - 1/2
    assert h["se"] == pytest.approx(math.sqrt(lrv / 6))
    assert h["lags"] == 1
    assert h["se"] < math.sqrt(g0 / 6)  # negative autocorrelation shrinks the HAC standard error


def test_sharpe_difference_z_hand_example():
    out = live.sharpe_difference_test(0.10, 101, 0.05, 401)
    se1 = math.sqrt((1 + 0.5 * 0.01) / 101)
    se2 = math.sqrt((1 + 0.5 * 0.0025) / 401)
    assert out["z"] == pytest.approx(0.05 / math.sqrt(se1 ** 2 + se2 ** 2))
    assert 0 < out["p_value"] < 1
    assert math.isnan(live.sharpe_difference_test(0.1, 1, 0.0, 10)["z"])


def test_cusum_crossing_on_constructed_series():
    z = np.zeros(100)
    z[40:] = -1.5  # a shift of 1.5 sd per period from index 40: -1.5 (k - 40) / sqrt(k) < -5 from k = 68 on
    out = live.cusum(z, 5.0)
    assert out["first_crossing"] == 67  # 0-based index of k = 68
    assert out["direction"] == "down"
    assert out["bde_end_statistic"] == pytest.approx(-1.5 * 60 / 10)
    # the statistic at the crossing index is exactly C_k / sqrt(k)
    k = out["first_crossing"] + 1
    assert abs(np.cumsum(z)[k - 1] / math.sqrt(k)) > 5.0
    assert abs(np.cumsum(z)[k - 2] / math.sqrt(k - 1)) <= 5.0


def test_cusum_no_crossing_under_null():
    rng = np.random.default_rng(0)
    out = live.cusum(rng.normal(0, 1, 2000), 5.0)
    assert out["first_crossing"] is None and out["max_abs_statistic"] < 5


def test_rolling_sharpe_and_percentile():
    r = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    rs = live.rolling_sharpe(r, 3, 252)
    assert rs.size == 4
    assert rs[0] == pytest.approx(0.02 / 0.01 * math.sqrt(252))
    assert live.percentile_of(2.5, np.array([1, 2, 3, 4])) == 0.5
    assert live.percentile_of(2.0, np.array([1, 2, 3, 4])) == pytest.approx(0.375)


# ------------------------------------------------------------------ helpers to build packages

def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _write(folder: Path, name: str, header: list[str], rows: list[list]) -> None:
    with open(folder / name, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _package(tmp_path: Path, bt: np.ndarray, lv: np.ndarray, n_bt: int, rules_extra: str = "") -> Path:
    dates = _weekdays(date(2021, 1, 4), n_bt + lv.size)
    _write(tmp_path, "returns.csv", ["date", "return"], [[d.isoformat(), f"{r:.10f}"] for d, r in zip(dates, bt)])
    _write(tmp_path, "live_returns.csv", ["date", "return"],
           [[d.isoformat(), f"{r:.10f}"] for d, r in zip(dates[n_bt:], lv)])
    (tmp_path / "rules.yaml").write_text(
        f"conventions:\n  periods_per_year: 252\n  review_date: '2030-01-01'\nlive:\n  start: {dates[n_bt]}\n"
        f"  backtest_end: {dates[n_bt - 1]}\n{rules_extra}", encoding="utf-8")
    return tmp_path


def _run(folder: Path) -> AuditResult:
    pkg = read_package(folder)
    res = AuditResult()
    live.run(pkg, res)
    return res


# ------------------------------------------------------------------ contract

def test_identical_series_is_confirmed_error(tmp_path):
    rng = np.random.default_rng(1)
    bt = rng.normal(0.0005, 0.01, 300)
    folder = _package(tmp_path, bt, bt[200:].copy(), 200)
    res = _run(folder)
    f = [x for x in res.findings if x.check == "live_period_integrity" and x.status == CONFIRMED_ERROR]
    assert f and "IDENTICAL" in f[0].detail
    assert f[0].evidence and f[0].procedure


def test_affine_copy_is_review_not_error(tmp_path):
    rng = np.random.default_rng(2)
    bt = rng.normal(0.0005, 0.01, 300)
    folder = _package(tmp_path, bt, bt[200:] - 0.0001, 200)
    res = _run(folder)
    assert res.status_of("live_period_integrity") == NEEDS_REVIEW
    assert "affine" in " ".join(x.detail for x in res.findings if x.check == "live_period_integrity")


def test_dates_before_start_and_after_review_are_errors(tmp_path):
    rng = np.random.default_rng(3)
    bt = rng.normal(0.0005, 0.01, 300)
    folder = _package(tmp_path, bt, bt[200:] + rng.normal(0, 0.001, 100), 200)
    (folder / "rules.yaml").write_text(
        "conventions:\n  periods_per_year: 252\n  review_date: '2021-12-01'\nlive:\n  start: 2021-12-01\n",
        encoding="utf-8")
    res = _run(folder)
    f = [x for x in res.findings if x.check == "live_period_integrity" and x.status == CONFIRMED_ERROR]
    assert f and "precede" in f[0].detail and "after the review date" in f[0].detail


def test_duplicate_date_account_is_error(tmp_path):
    rng = np.random.default_rng(4)
    bt = rng.normal(0.0005, 0.01, 300)
    folder = _package(tmp_path, bt, bt[200:] + rng.normal(0, 0.001, 100), 200)
    rows = list(csv.reader(open(folder / "live_returns.csv", encoding="utf-8")))
    rows.append(rows[5])
    _write(folder, "live_returns.csv", rows[0], rows[1:])
    res = _run(folder)
    f = [x for x in res.findings if x.check == "live_period_integrity" and x.status == CONFIRMED_ERROR]
    assert f and "duplicate" in f[0].detail
    assert any(e.get("problem") == "duplicate" and e.get("row") for e in f[0].evidence)


def test_no_returns_csv_is_not_executable_with_hint(tmp_path):
    rng = np.random.default_rng(5)
    dates = _weekdays(date(2024, 1, 2), 100)
    _write(tmp_path, "live_returns.csv", ["date", "return"],
           [[d.isoformat(), f"{r:.8f}"] for d, r in zip(dates, rng.normal(0, 0.01, 100))])
    res = _run(tmp_path)
    assert res.status_of("live_vs_shadow_backtest") == NOT_EXECUTABLE
    f = [x for x in res.findings if x.check == "live_vs_shadow_backtest"][0]
    assert "returns.csv" in f.reason and "report.json" in f.action
    assert res.status_of("live_performance_decay") == NOT_EXECUTABLE
    assert res.status_of("live_period_integrity") == NEEDS_REVIEW  # no backtest to compare with


def test_decay_uses_declared_sharpe_without_backtest(tmp_path):
    rng = np.random.default_rng(6)
    dates = _weekdays(date(2024, 1, 2), 300)
    r = rng.normal(0, 0.01, 300)
    r = (r - r.mean()) / r.std(ddof=1) * 0.01  # exact Sharpe 0
    _write(tmp_path, "live_returns.csv", ["date", "return"], [[d.isoformat(), f"{x:.8f}"] for d, x in zip(dates, r)])
    (tmp_path / "rules.yaml").write_text("conventions:\n  review_date: '2030-01-01'\nlive:\n  declared_sharpe: 2.5\n",
                                         encoding="utf-8")
    res = _run(tmp_path)
    assert res.status_of("live_performance_decay") == NEEDS_REVIEW
    m = res.metrics["live_performance_decay"]
    assert m["backtest_sharpe"] == pytest.approx(2.5)
    assert m["psr_vs_backtest"] < 0.05


def test_empty_folder_all_not_executable(tmp_path):
    res = _run(tmp_path)
    assert {f.check for f in res.findings} == set(CHECK_IDS)
    assert all(f.status == NOT_EXECUTABLE and f.reason for f in res.findings)
    full = audit(tmp_path, use_cases=["live"])
    for c in CHECK_IDS:
        assert full.status_of(c) == NOT_EXECUTABLE


def test_run_never_raises_on_odd_data(tmp_path):
    _write(tmp_path, "live_returns.csv", ["date", "return"], [["2024-01-02", "0.01"]])
    _write(tmp_path, "returns.csv", ["date", "return"], [["2024-01-02", "nan"], ["bad", ""]])
    _write(tmp_path, "live_trades.csv", ["timestamp", "ticker", "side", "quantity", "price"],
           [["2024-01-02", "AAA", "buy", "x", ""]])
    res = _run(tmp_path)
    assert {f.check for f in res.findings} == set(CHECK_IDS)
    assert PASS not in {f.status for f in res.findings}


def test_execution_quality_statistics(tmp_path):
    hdr = ["trade_id", "timestamp", "model_timestamp", "ticker", "side", "quantity", "price", "model_price",
           "commission"]
    rows = [["1", "2024-01-02T10:05:00", "2024-01-02T10:00:00", "AAA", "buy", 100, 100.10, 100.0, 1.0],
            ["2", "2024-01-03T10:01:00", "2024-01-03T10:00:00", "BBB", "sell", 100, 99.90, 100.0, 1.0],
            ["3", "2024-01-04T10:02:00", "2024-01-04T10:00:00", "CCC", "buy", 100, 100.00, 100.0, 1.0],
            ["9", "2024-01-05T14:00:00", "", "DDD", "buy", 100, 50.00, "", 0.5]]
    _write(tmp_path, "live_trades.csv", hdr, rows)
    _write(tmp_path, "model_trades.csv", hdr[:7], [["1", "2024-01-02T10:00:00", "", "AAA", "buy", 100, 100],
                                                   ["2", "2024-01-03T10:00:00", "", "BBB", "sell", 100, 100],
                                                   ["3", "2024-01-04T10:00:00", "", "CCC", "buy", 100, 100],
                                                   ["4", "2024-01-05T10:00:00", "", "EEE", "buy", 100, 100]])
    res = _run(tmp_path)
    m = res.metrics["live_execution_quality"]
    assert m["slippage_mean_bps"] == pytest.approx((10 + 10 + 0) / 3, abs=1e-6)  # buy +10, sell +10, 0
    assert m["fill_ratio"] == pytest.approx(0.75)
    assert m["overrides"] == 1 and m["override_share"] == pytest.approx(0.25)
    assert m["delay_median_s"] == pytest.approx(120.0)
    assert res.status_of("live_execution_quality") == NEEDS_REVIEW  # fill ratio < 0.9 and overrides > 5%


def test_execution_without_model_price_only_delay(tmp_path):
    _write(tmp_path, "live_trades.csv", ["timestamp", "model_timestamp", "ticker", "side", "quantity", "price"],
           [["2024-01-02T10:05:00", "2024-01-02T10:00:00", "AAA", "buy", 100, 100.10]])
    res = _run(tmp_path)
    f = [x for x in res.findings if x.check == "live_execution_quality"][0]
    assert f.status == INFO and "slippage not measured" in f.detail


def test_declared_mismatch_is_error_and_live_drawdown_is_review(tmp_path):
    rng = np.random.default_rng(7)
    bt = rng.normal(0.0005, 0.01, 400)
    lv = bt[300:] + rng.normal(0, 0.001, 100)
    folder = _package(tmp_path, bt, lv, 300, rules_extra="  declared_sharpe: 9.0\n  declared_max_drawdown: -0.001\n")
    res = _run(folder)
    st = {f.status for f in res.findings if f.check == "live_declared_vs_realised"}
    assert CONFIRMED_ERROR in st and NEEDS_REVIEW in st
    tab = res.metrics["live_declared_vs_realised"]["table"]
    assert tab[0]["metric"] == "sharpe" and tab[0]["within_tolerance"] is False


def test_multi_account_aggregation_and_nav():
    import pandas as pd
    df = pd.DataFrame({"row": [2, 3, 4, 5], "date": pd.to_datetime(["2024-01-02"] * 2 + ["2024-01-03"] * 2),
                       "return": [0.01, 0.03, 0.0, 0.02], "account": ["A", "B", "A", "B"], "aum": [3.0, 1.0, 3.0, 1.0]})
    s, info = live._series(df)
    assert info["n_accounts"] == 2 and info["duplicates"] == []
    assert s.iloc[0] == pytest.approx(0.015) and s.iloc[1] == pytest.approx(0.005)
    nav = pd.DataFrame({"row": [2, 3, 4], "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
                        "nav": [100.0, 101.0, 99.99]})
    s2, info2 = live._series(nav)
    assert info2["source"] == "nav" and s2.iloc[0] == pytest.approx(0.01) and s2.iloc[1] == pytest.approx(-0.01)


# ------------------------------------------------------------------ registration and battery

def test_registration_and_catalog():
    for c in CHECK_IDS:
        assert c in CHECKS and c in REQUIREMENTS
        assert CHECKS[c]["use_case"] == "live" and CHECKS[c]["block"] == "live"
    assert live.SPEC.detect_files == ["live_returns"]
    from lockin_validate.profiles import PROFILES
    assert "live_daily" in PROFILES and PROFILES["live_monthly"]["conventions"]["live_min_periods"] == 24


def test_battery_composition():
    names = sorted(p.parent.name for p in LIVE_CASES)
    assert len(names) == 10 and names[0] == "01_clean_tracking"


@pytest.mark.parametrize("expected", LIVE_CASES, ids=[p.parent.name for p in LIVE_CASES])
def test_live_case(expected):
    out = run_case(expected)
    assert out["ok"], "\n".join(out["problems"])
    assert out["false_positives"] == []


# ------------------------------------------------------------------ review v0.3.0 B (H2, M1, L3, L4)

def test_t_cdf_matches_known_values():
    assert live.t_cdf(0.0, 10) == pytest.approx(0.5)
    assert live.t_cdf(2.228138852, 10) == pytest.approx(0.975, abs=1e-6)
    assert live.t_cdf(-1.699127027, 29) == pytest.approx(0.05, abs=1e-6)
    assert live.t_ppf(0.95, 29) == pytest.approx(1.699127027, abs=1e-6)


def test_m1_hac_size_at_n30_is_not_inflated():
    # Monte Carlo (seeded): one-sided 5% test under iid H0 at n = 30; the plain asymptotic HAC test is at 8-9%
    rng = np.random.default_rng(11)
    reps, n = 1500, 30
    rej = sum(live.significantly_below_zero(live.hac_mean_test(rng.standard_normal(n)), 0.05) for _ in range(reps))
    assert rej / reps < 0.07
    # at large n a clearly negative mean is still detected
    assert live.significantly_below_zero(live.hac_mean_test(rng.standard_normal(400) - 0.4), 0.05)


def test_h2_nan_nav_is_not_merged_into_two_day_returns(tmp_path):
    dates = _weekdays(date(2021, 1, 4), 120)
    rng = np.random.default_rng(4)
    r = rng.normal(0.0005, 0.01, 120)
    nav = 100 * np.cumprod(1 + r)
    live_nav = nav.copy()
    live_nav[[40, 80]] = np.nan
    _write(tmp_path, "returns.csv", ["date", "return"], [[d.isoformat(), f"{x:.10f}"] for d, x in zip(dates, r)])
    _write(tmp_path, "live_returns.csv", ["date", "nav"],
           [[d.isoformat(), "" if np.isnan(v) else f"{v:.8f}"] for d, v in zip(dates, live_nav)])
    (tmp_path / "rules.yaml").write_text("conventions:\n  periods_per_year: 252\n  review_date: '2030-01-01'\n"
                                         "live:\n  start: " + dates[0].isoformat() + "\n", encoding="utf-8")
    res = _run(tmp_path)
    m = res.metrics["live_vs_shadow_backtest"]
    assert m["n"] == 115  # 120 dates - first date - 2 returns around each of the 2 missing NAVs
    assert m["tracking_error"] < 1e-6  # live is exactly the shadow wherever both exist
    pkg = read_package(tmp_path)
    ctx = live.Ctx(pkg)
    assert ctx.live_info["n_nav_missing"] == 2


def test_m1_monthly_consecutive_periods_are_not_a_gap(tmp_path):
    from pandas import date_range

    me = [d.date() for d in date_range("2018-01-31", periods=66, freq="ME")]
    rng = np.random.default_rng(8)
    r = rng.normal(0.008, 0.03, 66)
    _write(tmp_path, "returns.csv", ["date", "return"], [[d.isoformat(), f"{x:.8f}"] for d, x in zip(me, r)])
    lv = r[36:] + rng.normal(0, 0.002, 30)
    _write(tmp_path, "live_returns.csv", ["date", "return"], [[d.isoformat(), f"{x:.8f}"] for d, x in zip(me[36:], lv)])
    (tmp_path / "rules.yaml").write_text(
        f"conventions:\n  periods_per_year: 12\n  review_date: '2030-01-01'\nlive:\n  start: {me[36]}\n"
        f"  backtest_end: {me[35]}\n", encoding="utf-8")
    res = _run(tmp_path)
    f = [x for x in res.findings if x.check == "live_period_integrity"]
    assert all("without a reason" not in (x.detail + x.title) for x in f)
    # a skipped quarter in monthly data is still a gap
    (tmp_path / "rules.yaml").write_text(
        f"conventions:\n  periods_per_year: 12\n  review_date: '2030-01-01'\nlive:\n  start: {me[36]}\n"
        f"  backtest_end: {me[32]}\n", encoding="utf-8")
    f = [x for x in _run(tmp_path).findings if x.check == "live_period_integrity"]
    assert any("without a reason" in (x.detail + x.title) for x in f)


def test_l3_identical_slippages_report_mean_only(tmp_path):
    rows = [[f"2024-01-{2 + i:02d}T10:00:00", "AAA", "buy" if i % 2 == 0 else "sell", 100,
             f"{100.15 if i % 2 == 0 else 99.85:.4f}", "100.0000" if i % 2 == 0 else "100.0000"] for i in range(20)]
    _write(tmp_path, "live_trades.csv", ["timestamp", "ticker", "side", "quantity", "price", "model_price"], rows)
    res = _run(tmp_path)
    f = [x for x in res.findings if x.check == "live_execution_quality"][0]
    assert "no dispersion" in f.detail and "e+" not in f.detail


def test_l4_live_in_percent_units_is_flagged(tmp_path):
    folder = _package(tmp_path, np.random.default_rng(6).normal(0.001, 0.01, 300),
                      np.random.default_rng(6).normal(0.001, 0.01, 300) * 100, 100)
    # live = 100 x the same series on its own dates: beta of live on backtest ~ 100
    res = _run(folder)
    f = [x for x in res.findings if x.check == "live_period_integrity"]
    assert any("look like percent" in (x.detail + x.title) for x in f)
