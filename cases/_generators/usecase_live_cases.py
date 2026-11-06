"""Cases of the ``live`` use case (cases/usecase_live/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/usecase_live_cases.py

Every case plants a property and writes expected.json from it BEFORE the tool runs. Where a random draw could
contradict the planted property, the generator checks it with its OWN pure-Python computation and fails loudly.

  01_clean_tracking     shadow backtest + live that differs by noise and 0.5 bps/day of costs -> no alert
  02_pasted_backtest    live identical to the backtest on the overlap            -> live_period_integrity CONFIRMED_ERROR
  03_decayed_edge       backtest Sharpe 2.0 (5 y), live Sharpe 0.0 (1.5 y)       -> decay + structural break NEEDS_REVIEW
  04_tracking_gap       live diverges from the shadow from a date on (TE 6%)     -> live_vs_shadow_backtest NEEDS_REVIEW
  05_marketing_number   declared Sharpe 1.8, the series gives 1.1                -> live_declared_vs_realised CONFIRMED_ERROR
  06_bad_execution      25 bps slippage and 15% overrides                        -> live_execution_quality NEEDS_REVIEW
  07_short_live         30 live days                                             -> nothing concluded (no PASS on decay)
  08_no_shadow          backtest ends when live starts                           -> integrity NEEDS_REVIEW, shadow N/E
  09_drawdown_exceeded  live max drawdown about -18% vs backtest about -10%      -> live_declared_vs_realised NEEDS_REVIEW
  10_multi_account      two accounts with AUM, aggregated per date (adversarial: looks odd, is legitimate) -> no alert
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "usecase_live"
PPY = 252
REVIEW = "2026-10-20"
MODULE_CHECKS = ["live_period_integrity", "live_vs_shadow_backtest", "live_performance_decay", "live_structural_break",
                 "live_execution_quality", "live_declared_vs_realised"]


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def sharpe(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(x.mean() / x.std(ddof=1))


def scale_to(x, sr_annual: float, sd: float = 0.01) -> np.ndarray:
    """Rescale a draw so its sample Sharpe (annualised) and sample sd are exactly the targets."""
    x = np.asarray(x, dtype=float)
    z = (x - x.mean()) / x.std(ddof=1)
    return z * sd + sr_annual / math.sqrt(PPY) * sd


def nav(r) -> np.ndarray:
    return np.r_[1.0, np.cumprod(1.0 + np.asarray(r, dtype=float))]


def max_dd(r) -> float:
    a = nav(r)
    return float((a / np.maximum.accumulate(a) - 1).min())


def ann_return(r) -> float:
    a = nav(r)
    return float((a[-1] / a[0]) ** (PPY / (a.size - 1)) - 1)


def psr(sr, sr_star, T) -> float:
    """PSR under normality (skew 0, kurt 3): Phi((sr - sr*) sqrt(T - 1) / sqrt(1 + sr^2 / 2))."""
    from statistics import NormalDist
    return NormalDist().cdf((sr - sr_star) * math.sqrt(T - 1) / math.sqrt(1 + 0.5 * sr * sr))


def two_sample_t(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float((b.mean() - a.mean()) / math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size))


def write_returns(path: Path, dates, returns, extra: dict | None = None):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "return"] + list((extra or {}).keys()))
        for i, (d, r) in enumerate(zip(dates, returns)):
            w.writerow([d.isoformat(), f"{r:.10f}"] + [v[i] for v in (extra or {}).values()])


def write_case(name: str, *, bt_dates, bt, live_dates, live, live_cfg: dict, expected: dict, description: str,
               declared: dict | None = None, live_rows: list[list] | None = None, live_header: list[str] | None = None,
               trades: tuple | None = None, conventions: dict | None = None):
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    write_returns(c / "returns.csv", bt_dates, bt)
    if live_rows is not None:
        with open(c / "live_returns.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(live_header)
            w.writerows(live_rows)
    else:
        write_returns(c / "live_returns.csv", live_dates, live)
    conv = {"periods_per_year": PPY, "review_date": REVIEW, **(conventions or {})}
    lines = ["strategy: synthetic live record against its backtest", "conventions:"]
    lines += [f"  {k}: {v!r}" if isinstance(v, str) else f"  {k}: {v}" for k, v in conv.items()]
    lines.append("live:")
    lines += [f"  {k}: {v}" for k, v in live_cfg.items()]
    (c / "rules.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if declared is not None:
        (c / "declared_results.json").write_text(json.dumps(declared, indent=2), encoding="utf-8")
    if trades is not None:
        live_trades, model_trades = trades
        for fname, rows in (("live_trades.csv", live_trades), ("model_trades.csv", model_trades)):
            if rows is None:
                continue
            with open(c / fname, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(rows[0])
                w.writerows(rows[1:])
    exp = {"description": description, "origin": "usecase", "use_case": "live", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


def quiet_all():
    return [mustnot(ch, s) for ch in MODULE_CHECKS for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")]


BT_START = date(2020, 1, 2)
N_BT = 5 * PPY  # five years of backtest proper
N_LIVE = 378  # 1.5 years live


def cfg_for(bt_dates, live_dates) -> dict:
    """live.start = first live date; live.backtest_end = last date of the backtest proper."""
    return {"start": live_dates[0].isoformat(), "backtest_end": bt_dates[-1].isoformat()}


def page_cusum_crosses(z, h=5.0) -> bool:
    c = np.cumsum(np.asarray(z, dtype=float))
    return bool(np.any(np.abs(c) / np.sqrt(np.arange(1, c.size + 1)) > h))


def base_series(seed: int, sr_bt: float = 1.2, sr_live_shadow: float | None = None):
    """Backtest proper (N_BT periods, exact Sharpe sr_bt) followed by the shadow part (N_LIVE periods)."""
    rng = np.random.default_rng(seed)
    dates = weekdays(BT_START, N_BT + N_LIVE)
    pre = scale_to(rng.normal(0, 1, N_BT), sr_bt)
    shadow = scale_to(rng.normal(0, 1, N_LIVE), sr_bt if sr_live_shadow is None else sr_live_shadow)
    return dates[:N_BT], pre, dates[N_BT:], shadow, rng


def assert_quiet(pre, shadow, live, te_max=0.03):
    """The generator's own version of every module alert, so the clean cases are clean by construction."""
    d = live - shadow
    te = float(d.std(ddof=1)) * math.sqrt(PPY)
    assert te < te_max * 0.8, te
    assert np.corrcoef(live, shadow)[0, 1] > 0.9
    t_diff = float(d.mean() / (d.std(ddof=1) / math.sqrt(d.size)))
    assert t_diff > -1.3, t_diff  # not significantly negative at 5% one-sided (1.645) with margin
    sr_l, sr_b = sharpe(live), sharpe(pre)
    assert psr(sr_l, sr_b, live.size) > 0.10, (sr_l, sr_b)  # decay not significant with margin
    assert abs(two_sample_t(pre, live)) < 1.5, two_sample_t(pre, live)  # no mean shift
    assert not page_cusum_crosses((live - pre.mean()) / pre.std(ddof=1))
    assert max_dd(live) > max_dd(pre) + 0.005, (max_dd(live), max_dd(pre))  # live drawdown within the backtest's
    # rolling 60-day Sharpe: live median above the backtest 10th percentile
    def roll(x):
        x = np.asarray(x)
        return np.array([sharpe(x[i:i + 60]) for i in range(x.size - 59)]) * math.sqrt(PPY)
    assert np.median(roll(live)) > np.percentile(roll(pre), 10) + 0.3


def c01():
    bt_d, pre, lv_d, shadow, rng = base_series(11)
    live = shadow + rng.normal(0, 0.001, N_LIVE) - 0.5e-4
    assert_quiet(pre, shadow, live)
    assert np.max(np.abs(live - shadow)) > 1e-6
    write_case("01_clean_tracking", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg_for(bt_d, lv_d),
               expected={"must_include": [must("live_period_integrity", "PASS"),
                                          must("live_vs_shadow_backtest", "PASS", "INFO"),
                                          must("live_performance_decay", "INFO", "PASS"),
                                          must("live_structural_break", "INFO"),
                                          must("live_declared_vs_realised", "INFO")],
                         "must_not_include": quiet_all(), "errors_only_from": [],
                         "comment": "Live = shadow backtest + N(0, 10 bps) noise - 0.5 bps/day; tracking error about "
                                    "1.6% a year, mean difference not significant, same drift before and after going "
                                    "live, live drawdown inside the backtest's worst case."},
               description="Clean live record: a shadow backtest covers the 1.5 live years and live differs only by "
                           "execution noise and 0.5 bps a day of costs.")


def c02():
    bt_d, pre, lv_d, shadow, rng = base_series(22)
    live = shadow.copy()
    write_case("02_pasted_backtest", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg_for(bt_d, lv_d),
               expected={"must_include": [must("live_period_integrity", "CONFIRMED_ERROR")],
                         "must_not_include": [mustnot("live_period_integrity", "PASS")],
                         "errors_only_from": ["live_period_integrity"],
                         "text_must_contain": [{"check": "live_period_integrity", "text": "IDENTICAL"}],
                         "comment": "live_returns.csv is returns.csv over the live dates, to the last digit."},
               description="The 'live' track record is the backtest pasted over the live dates (correlation 1, max "
                           "difference 0 on 378 periods).")


def c03():
    bt_d, pre, lv_d, shadow, rng = base_series(33, sr_bt=2.0, sr_live_shadow=0.0)
    # the shadow backtest itself decays to Sharpe 0 (the model stopped working, not the execution)
    live = shadow + rng.normal(0, 0.0005, N_LIVE)
    live = scale_to(live, 0.0, float(live.std(ddof=1)))  # exact live Sharpe 0.0
    t = two_sample_t(pre, live)
    assert t < -1.96, t  # mean shift significant at 5% (about -2.15 with these sizes)
    assert psr(sharpe(live), sharpe(pre), N_LIVE) < 0.05
    write_case("03_decayed_edge", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg_for(bt_d, lv_d),
               expected={"must_include": [must("live_performance_decay", "NEEDS_REVIEW"),
                                          must("live_structural_break", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("live_performance_decay", "PASS"),
                                              mustnot("live_structural_break", "INFO")],
                         "errors_only_from": [],
                         "comment": "Backtest Sharpe exactly 2.0 on 1260 days, live exactly 0.0 on 378 days: PSR of "
                                    "the live Sharpe against 2.0 is about 0.007; two-sample t of the mean shift about "
                                    "-2.15. The CUSUM at h = 5 does not cross for a shift of 0.126 sd per day; the "
                                    "mean-shift test carries the structural-break alert."},
               description="The edge decayed: five years of backtest at Sharpe 2.0 and 1.5 years live at Sharpe 0.0 "
                           "(the shadow backtest tracks live, so the model itself stopped working).")


def c04():
    bt_d, pre, lv_d, shadow, rng = base_series(44)
    live = shadow.copy()
    k = N_LIVE // 2
    live[k:] = shadow[k:] + rng.normal(0, 0.06 / math.sqrt(PPY) * math.sqrt(2), N_LIVE - k)
    te = float((live - shadow).std(ddof=1)) * math.sqrt(PPY)
    assert te > 0.045, te
    assert np.corrcoef(live, shadow)[0, 1] > 0.8  # the alert comes from the tracking error, not the correlation
    write_case("04_tracking_gap", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg_for(bt_d, lv_d),
               expected={"must_include": [must("live_vs_shadow_backtest", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("live_vs_shadow_backtest", "PASS")], "errors_only_from": [],
                         "comment": f"Live equals the shadow for the first half, then diverges with noise; overall "
                                    f"tracking error {te:.1%} a year, above the 3% review threshold. The divergence "
                                    f"date is {lv_d[k]}."},
               description="Live tracks the shadow backtest perfectly for nine months, then diverges from "
                           f"{lv_d[k]} on with an annualised tracking error of about 6%.")


def c05():
    bt_d, pre, lv_d, shadow, rng = base_series(55, sr_bt=1.1)
    live = shadow + rng.normal(0, 0.001, N_LIVE) - 0.5e-4
    assert abs(sharpe(pre) * math.sqrt(PPY) - 1.1) < 1e-9
    cfg = {**cfg_for(bt_d, lv_d), "declared_sharpe": 1.8, "declared_annual_return": round(ann_return(pre), 6),
           "declared_max_drawdown": round(max_dd(pre), 6)}
    write_case("05_marketing_number", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg,
               expected={"must_include": [must("live_declared_vs_realised", "CONFIRMED_ERROR")],
                         "errors_only_from": ["live_declared_vs_realised"],
                         "text_must_contain": [{"check": "live_declared_vs_realised", "text": "1.8"}],
                         "comment": "rules.yaml live.declared_sharpe = 1.8 while returns.csv over the backtest period "
                                    "gives exactly 1.1 (arithmetic, 252, ddof 1); annual return and max drawdown are "
                                    "declared correctly."},
               description="The marketing Sharpe (1.8) is not the one of the series delivered (1.1); the live record "
                           "itself tracks the shadow backtest.")


def c06():
    bt_d, pre, lv_d, shadow, rng = base_series(66)
    live = shadow + rng.normal(0, 0.001, N_LIVE) - 0.5e-4
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    header = ["trade_id", "timestamp", "model_timestamp", "ticker", "side", "quantity", "price", "model_price",
              "commission"]
    model_rows, live_rows = [header[:1] + header[1:2] + header[3:7]], [header]
    n_model = 100
    rs = np.random.default_rng(666)
    for i in range(n_model):
        d = lv_d[int(rs.integers(0, N_LIVE))]
        t_model = datetime(d.year, d.month, d.day, 10, 0, 0)
        tk = tickers[i % 5]
        side = "buy" if i % 3 else "sell"
        qty = int(rs.integers(100, 1000))
        px = round(float(50 + rs.uniform(0, 50)), 2)
        model_rows.append([f"M{i:04d}", t_model.isoformat(), tk, side, qty, f"{px:.2f}"])
        if i % 100 < 85:  # 85 of 100 model trades executed (fill ratio 0.85)
            fill = px * (1 + 0.0025) if side == "buy" else px * (1 - 0.0025)  # 25 bps worse
            t_fill = t_model + timedelta(seconds=int(rs.integers(30, 600)))
            live_rows.append([f"M{i:04d}", t_fill.isoformat(), t_model.isoformat(), tk, side, qty, f"{fill:.4f}",
                              f"{px:.2f}", f"{qty * fill * 0.0005:.2f}"])
    for j in range(15):  # 15 overrides the model never requested: 15 / 100 live trades = 15%
        d = lv_d[int(rs.integers(0, N_LIVE))]
        t_fill = datetime(d.year, d.month, d.day, 14, 30, 0)
        px = round(float(50 + rs.uniform(0, 50)), 2)
        live_rows.append([f"X{j:04d}", t_fill.isoformat(), "", tickers[j % 5], "buy" if j % 2 else "sell", 200,
                          f"{px:.4f}", "", f"{200 * px * 0.0005:.2f}"])
    assert len(live_rows) - 1 == 100
    write_case("06_bad_execution", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg_for(bt_d, lv_d), trades=(live_rows, model_rows),
               expected={"must_include": [must("live_execution_quality", "NEEDS_REVIEW")],
                         "must_not_include": [mustnot("live_execution_quality", "INFO"),
                                              mustnot("live_execution_quality", "PASS")], "errors_only_from": [],
                         "text_must_contain": [{"check": "live_execution_quality", "text": "slippage"}],
                         "comment": "Every fill is 25 bps worse than the model price (threshold 10), 15 of 100 model "
                                    "trades never executed (fill ratio 0.85 < 0.9) and 15 live trades have no model "
                                    "order (15% overrides > 5%)."},
               description="Execution problems: 25 bps of signed slippage, fill ratio 85% and 15% discretionary "
                           "overrides; the return series themselves are clean.")


def c07():
    bt_d, pre, lv_d, shadow, rng = base_series(77)
    n = 30
    live = shadow[:n] + rng.normal(0, 0.001, n) - 0.5e-4
    write_case("07_short_live", bt_dates=bt_d + lv_d[:n], bt=np.r_[pre, shadow[:n]], live_dates=lv_d[:n], live=live,
               live_cfg=cfg_for(bt_d, lv_d),
               expected={"must_include": [must("live_period_integrity", "NEEDS_REVIEW"),
                                          must("live_performance_decay", "INFO", "NOT_EXECUTABLE"),
                                          must("live_structural_break", "INFO", "NOT_EXECUTABLE"),
                                          must("live_vs_shadow_backtest", "INFO", "NOT_EXECUTABLE")],
                         "must_not_include": [mustnot("live_performance_decay", "PASS"),
                                              mustnot("live_vs_shadow_backtest", "PASS"),
                                              mustnot("live_period_integrity", "PASS"),
                                              mustnot("live_period_integrity", "CONFIRMED_ERROR")],
                         "errors_only_from": [],
                         "comment": "30 live days: overlap below live_min_periods = 60 (integrity NEEDS_REVIEW); the "
                                    "decay and tracking checks may describe but must not PASS."},
               description="Insufficient data: only 30 live days; nothing can be concluded (no PASS anywhere on the "
                           "statistical checks).")


def c08():
    bt_d, pre, lv_d, shadow, rng = base_series(88)
    live = shadow + rng.normal(0, 0.001, N_LIVE) - 0.5e-4
    write_case("08_no_shadow", bt_dates=bt_d, bt=pre, live_dates=lv_d, live=live, live_cfg=cfg_for(bt_d, lv_d),
               expected={"must_include": [must("live_period_integrity", "NEEDS_REVIEW"),
                                          must("live_vs_shadow_backtest", "NOT_EXECUTABLE"),
                                          must("live_performance_decay", "INFO", "NEEDS_REVIEW", "PASS")],
                         "must_not_include": [mustnot("live_period_integrity", "PASS"),
                                              mustnot("live_period_integrity", "CONFIRMED_ERROR")],
                         "errors_only_from": [],
                         "comment": "returns.csv ends the period before the first live date: no common dates, so "
                                    "the comparison is period vs period and the shadow checks cannot run."},
               description="No shadow backtest: the backtest series stops the day live starts.")


def c09():
    dates = weekdays(BT_START, N_BT + N_LIVE)
    bt_d, lv_d = dates[:N_BT], dates[N_BT:]
    # deterministic search: the first seed from 99 that gives a backtest max drawdown near -10% AND a live record
    # whose only anomaly is a drawdown about 8 pp deeper (tracking, decay and break quiet by own computation)
    for seed in range(99, 399):
        rng = np.random.default_rng(seed)
        pre = scale_to(rng.normal(0, 1, N_BT), 1.2, sd=0.006)  # 9.5% annual volatility
        # live period: a planted drawdown (negative drift for 110 days) followed by a recovery
        drift = np.r_[np.full(110, -0.0016), np.full(N_LIVE - 110, 0.0007)]
        shadow = rng.normal(0, 1, N_LIVE) * 0.006 + drift
        live = shadow + rng.normal(0, 0.001, N_LIVE) - 0.5e-4
        dd_bt, dd_live = max_dd(pre), max_dd(live)
        ok = (-0.12 < dd_bt < -0.08 and dd_live < dd_bt - 0.05 and dd_live < -0.15
              and float((live - shadow).std(ddof=1)) * math.sqrt(PPY) < 0.024
              and psr(sharpe(live), sharpe(pre), N_LIVE) > 0.10
              and abs(two_sample_t(pre, live)) < 1.5
              and not page_cusum_crosses((live - pre.mean()) / pre.std(ddof=1)))
        if ok:
            break
    else:  # pragma: no cover
        raise AssertionError("no seed satisfies the planted properties of case 09")
    cfg = {**cfg_for(bt_d, lv_d), "declared_sharpe": round(sharpe(pre) * math.sqrt(PPY), 6),
           "declared_annual_return": round(ann_return(pre), 6), "declared_max_drawdown": round(dd_bt, 6)}
    write_case("09_drawdown_exceeded", bt_dates=dates, bt=np.r_[pre, shadow], live_dates=lv_d, live=live,
               live_cfg=cfg,
               expected={"must_include": [must("live_declared_vs_realised", "NEEDS_REVIEW"),
                                          must("live_period_integrity", "PASS")],
                         "must_not_include": [mustnot("live_declared_vs_realised", "CONFIRMED_ERROR"),
                                              mustnot("live_vs_shadow_backtest", "NEEDS_REVIEW"),
                                              mustnot("live_performance_decay", "NEEDS_REVIEW"),
                                              mustnot("live_structural_break", "NEEDS_REVIEW")],
                         "errors_only_from": [],
                         "text_must_contain": [{"check": "live_declared_vs_realised", "text": "drawdown"}],
                         "comment": f"Declared metrics equal the backtest series (max drawdown {dd_bt:.1%}); the live "
                                    f"record already fell {dd_live:.1%} while tracking the shadow backtest."},
               description="The backtest worst case was not the worst case: live max drawdown about -18% against a "
                           "declared (and correct) backtest max drawdown of about -10%, everything else consistent.")


def c10():
    bt_d, pre, lv_d, shadow, rng = base_series(1010)
    live_a = shadow + rng.normal(0, 0.0008, N_LIVE) - 0.4e-4
    live_b = shadow + rng.normal(0, 0.0012, N_LIVE) - 0.6e-4
    aum_a, aum_b = 3_000_000.0, 1_000_000.0
    agg = (live_a * aum_a + live_b * aum_b) / (aum_a + aum_b)
    assert_quiet(pre, shadow, agg)
    rows = []
    for d, ra, rb in zip(lv_d, live_a, live_b):
        rows.append([d.isoformat(), "ACC-A", f"{ra:.10f}", f"{aum_a:.0f}"])
        rows.append([d.isoformat(), "ACC-B", f"{rb:.10f}", f"{aum_b:.0f}"])
    write_case("10_multi_account", bt_dates=bt_d + lv_d, bt=np.r_[pre, shadow], live_dates=lv_d, live=agg,
               live_cfg=cfg_for(bt_d, lv_d), live_rows=rows, live_header=["date", "account", "return", "aum"],
               expected={"must_include": [must("live_period_integrity", "PASS"),
                                          must("live_vs_shadow_backtest", "PASS", "INFO")],
                         "must_not_include": quiet_all(), "errors_only_from": [],
                         "comment": "Two rows per date (one per account) look like duplicates but are not: the "
                                    "(date, account) key is unique and the module aggregates by AUM."},
               description="Adversarial-legitimate: two live accounts with AUM, two rows per date; must aggregate, not "
                           "alert on duplicates.")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (c01, c02, c03, c04, c05, c06, c07, c08, c09, c10):
        f()
        print("generated", f.__name__)


if __name__ == "__main__":
    main()
