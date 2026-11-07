"""Generator of the v0.3.0 (B) adversarial review cases. Does NOT import lockin_validate.
expected.json files are written together with the inputs, before the tool is ever run on them."""
from __future__ import annotations
import json, math, shutil
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
Z99, Z975 = 2.3263478740, 1.9599639845


def chi1_sf(x): return math.erfc(math.sqrt(max(x, 0) / 2))

def kupiec(x, n, p):
    ph = x / n
    ll0 = (n - x) * math.log(1 - p) + (x * math.log(p) if x else 0)
    ll1 = (n - x) * math.log(1 - ph) + (x * math.log(ph) if x else 0)
    return -2 * (ll0 - ll1)

def lr_ind(ex):
    ex = np.asarray(ex, int)
    a, b = ex[:-1], ex[1:]
    n00 = int(((a == 0) & (b == 0)).sum()); n01 = int(((a == 0) & (b == 1)).sum())
    n10 = int(((a == 1) & (b == 0)).sum()); n11 = int(((a == 1) & (b == 1)).sum())
    def ll(k, n, p): return (k * math.log(p) if k else 0) + ((n - k) * math.log(1 - p) if n - k else 0)
    p01 = n01 / (n00 + n01); p11 = n11 / (n10 + n11) if n10 + n11 else 0
    p = (n01 + n11) / (n00 + n01 + n10 + n11)
    l1 = ll(n01, n00 + n01, p01) + ll(n11, n10 + n11, p11)
    l0 = ll(n01 + n11, n00 + n01 + n10 + n11, p)
    return -2 * (l0 - l1), (n00, n01, n10, n11)

def put(mod, name, files, exp, rules=None):
    d = ROOT / mod / name
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True)
    for fn, df in files.items():
        df.to_csv(d / fn, index=False)
    if rules is not None:
        (d / "rules.yaml").write_text(rules, encoding="utf-8")
    exp = dict(exp); exp["use_case"] = mod; exp["origin"] = "review_v030"
    if exp.get("errors_only_from") is None: exp.pop("errors_only_from", None)
    (d / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")

def E(desc, inc=(), notinc=(), only=None, text=(), profile=None):
    e = {"description": desc,
         "must_include": [{"check": c, "status": s} for c, s in inc],
         "must_not_include": [{"check": c, "status": s} for c, s in notinc],
         "errors_only_from": only}
    if text: e["text_must_contain"] = [{"check": c, "text": t} for c, t in text]
    if profile: e["profile"] = profile
    return e

NOALERT = lambda checks: [(c, s) for c in checks for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")]
NOCE = lambda checks: [(c, "CONFIRMED_ERROR") for c in checks]

# ============================================================== RISK
def risk_base(n, seed, sig0=0.01, clip=None, dates=None):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    sig = sig0 * (1 + 0.3 * np.sin(2 * np.pi * t / 250))
    z = rng.standard_normal(n)
    if clip: z = np.clip(z, -clip, clip)
    if dates is None: dates = pd.bdate_range("2019-01-01", periods=n)
    return dates, sig, z

def ex_flags(pnl, var): return (-pnl > var).astype(int)

def calibrated(n, seed0, sig0=0.01, dates=None, lo=6, hi=14, both=False):
    for s in range(seed0, seed0 + 2000):
        dts, sig, z = risk_base(n, s, sig0, dates=dates)
        pnl = sig * z
        ex = ex_flags(pnl, Z99 * sig)
        x = ex.sum()
        if not (lo <= x <= hi): continue
        if chi1_sf(kupiec(x, n, 0.01)) < 0.3: continue
        lr, _ = lr_ind(ex)
        if chi1_sf(lr) < 0.3: continue
        if any(ex[i] and ex[i + 1] for i in range(n - 1)): continue
        if both:
            e2 = ex_flags(pnl, Z975 * sig)
            if chi1_sf(kupiec(e2.sum(), n, 0.025)) < 0.3: continue
        return dts, sig, pnl
    raise RuntimeError("no seed")

def gen_risk():
    m = "risk"
    dates, sig, pnl = calibrated(1000, 11, both=True)
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_0.99": Z99 * sig, "var_97.5": Z975 * sig})
    put(m, "01_dotted_level_names", {"var_forecasts.csv": df},
        E("Calibrated normal model, columns named var_0.99 and var_97.5 (both are common spellings). 1000 days.",
          inc=[("var_coverage", ["PASS"]), ("basel_traffic_light", ["INFO"]), ("var_independence", ["PASS", "INFO"])],
          notinc=NOALERT(["var_input_coherence", "var_coverage", "var_independence", "basel_traffic_light"]), only=[]))
    wk = pd.date_range("2018-01-05", periods=400, freq="W-FRI")
    dates, sig, pnl = calibrated(400, 21, sig0=0.02, dates=wk, lo=2, hi=6)
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": Z99 * sig})
    put(m, "02_weekly_frequency", {"var_forecasts.csv": df},
        E("Weekly P&L and weekly 99% VaR, 400 consecutive Fridays, calibrated. Consecutive Fridays are not a gap.",
          inc=[("var_coverage", ["PASS"]), ("var_input_coherence", ["PASS", "INFO"])],
          notinc=NOALERT(["var_input_coherence", "var_coverage", "var_independence"]), only=[]))
    dates, sig, pnl = calibrated(1000, 31)
    es = 2.665 * sig
    es[500] = 0.9 * Z99 * sig[500]
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": Z99 * sig, "es_99": es})
    put(m, "03_es_below_var_one_day", {"var_forecasts.csv": df},
        E("Correct VaR/ES except one day (row 500) where es_99 < var_99. Doc: CONFIRMED_ERROR on any day.",
          inc=[("var_input_coherence", ["CONFIRMED_ERROR"])], only=["var_input_coherence"]))
    dates, sig, pnl = calibrated(1000, 41)
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": Z99 * sig})
    df = pd.concat([df.iloc[:400], df.iloc[[399]], df.iloc[400:]], ignore_index=True)
    put(m, "04_duplicated_date", {"var_forecasts.csv": df},
        E("Row 399 repeated (date duplicated, 1001 rows). Doc: CONFIRMED_ERROR.",
          inc=[("var_input_coherence", ["CONFIRMED_ERROR"])], only=["var_input_coherence"]))
    dates, sig, z = risk_base(1000, 51, clip=2.2)
    pnl = sig * z; var = Z99 * sig
    for a in (300, 700):
        for k in range(5): pnl[a + k] = -1.3 * var[a + k]
    ex = ex_flags(pnl, var); assert ex.sum() == 10
    lr, c = lr_ind(ex); assert chi1_sf(lr) < 1e-4
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": var})
    put(m, "05_two_runs_of_five", {"var_forecasts.csv": df},
        E("Exactly 10 exceptions in 1000 days (Kupiec LR=0) in two runs of 5 consecutive days. "
          "Coverage passes, independence must flag clusters. Last 250 days have 0 exceptions (green).",
          inc=[("var_coverage", ["PASS"]), ("var_independence", ["NEEDS_REVIEW"]), ("basel_traffic_light", ["INFO"])],
          notinc=NOALERT(["var_coverage"]) + NOCE(["var_independence", "basel_traffic_light"]), only=[]))
    dates, sig, z = risk_base(250, 61, clip=2.2)
    pnl = sig * z; var = Z99 * sig
    for k in range(10): pnl[10 + 24 * k] = -1.4 * var[10 + 24 * k]
    ex = ex_flags(pnl, var); assert ex.sum() == 10
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": var})
    put(m, "06_red_zone_250_scattered", {"var_forecasts.csv": df},
        E("Exactly 250 days, 10 well-spread exceptions at 99%: Basel red, Kupiec rejects (too many), no clustering. "
          "Red is NEEDS_REVIEW, never CONFIRMED_ERROR.",
          inc=[("basel_traffic_light", ["NEEDS_REVIEW"]), ("var_coverage", ["NEEDS_REVIEW"])],
          notinc=NOALERT(["var_independence"]) + NOCE(["basel_traffic_light", "var_coverage"]), only=[]))
    dates, sig, pnl = calibrated(1000, 71)
    var = Z99 * sig
    df = pd.DataFrame({"day": dates, "loss": -pnl, "var_99": var})
    df.loc[[100, 400, 700], "var_99"] = np.nan
    put(m, "07_loss_column_nan_var", {"var_forecasts.csv": df},
        E("Columns day, loss (positive = loss), var_99; var_99 NaN on 3 of 1000 days (0.3%, below the 1% threshold). Calibrated.",
          inc=[("var_coverage", ["PASS"])],
          notinc=NOALERT(["var_coverage", "var_independence"]) + NOCE(["var_input_coherence", "basel_traffic_light"]), only=[]))

# ============================================================== PORTFOLIO
def gbm_prices(tickers, mus, vols, seed, start="2021-01-01", end="2023-12-31"):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    rows = []
    for t, mu, vol in zip(tickers, mus, vols):
        r = mu / 252 + vol / math.sqrt(252) * rng.standard_normal(len(days))
        px = 100 * np.cumprod(1 + r)
        rows.append(pd.DataFrame({"date": days, "ticker": t, "close": px}))
    return pd.concat(rows, ignore_index=True), days

def month_ends(days):
    s = pd.Series(days, index=days)
    return list(s.groupby([days.year, days.month]).max())

def wrows(dates, wmap, port=None):
    rows = []
    for d in dates:
        for t, w in wmap.items():
            r = {"date": d, "ticker": t, "weight": w}
            if port: r["portfolio"] = port
            rows.append(r)
    return pd.DataFrame(rows)

def own_sim(prices, weights, dates):
    px = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    ret = px.pct_change().fillna(0.0)
    days = list(px.index); out = []
    reb = {}
    for d in dates:
        i = px.index.searchsorted(d, side="right")
        if i < len(days): reb[days[i]] = weights[d]
    hold = None
    for d in days:
        if hold is not None:
            r = ret.loc[d]
            pr = sum(hold[t] * r[t] for t in hold)
            out.append((d, pr))
            hold = {t: hold[t] * (1 + r[t]) / (1 + pr) for t in hold}
        if d in reb:
            hold = dict(reb[d])
    return pd.Series(dict(out))

def jkm_z(a, b):
    a = np.asarray(a); b = np.asarray(b)
    T = len(a); s1 = a.mean() / a.std(ddof=1); s2 = b.mean() / b.std(ddof=1)
    rho = np.corrcoef(a, b)[0, 1]
    v = (2 * (1 - rho) + 0.5 * (s1 ** 2 + s2 ** 2) - s1 * s2 * rho ** 2) / T
    return (s1 - s2) / math.sqrt(v), s1, s2, rho, T

def gen_portfolio():
    m = "portfolio"
    tk = [f"T{i:02d}" for i in range(1, 11)]
    px, days = gbm_prices(tk, [0.08] * 10, [0.2] * 10, 5)
    me = month_ends(days)
    w = {t: 0.09 for t in tk}; w["CASH"] = 0.10
    put(m, "01_cash_row", {"weights.csv": wrows(me, w), "prices.csv": px},
        E("Long-only fund holding 10 names at 9% plus an explicit CASH row at 10% (sum 1.00), cash_ticker declared, max_weight 0.12. No price for CASH. Constant target rebalanced monthly.",
          inc=[("portfolio_constraints", ["PASS"])],
          notinc=NOALERT(["portfolio_constraints", "portfolio_concentration", "portfolio_turnover"]), only=[]),
        "strategy: Long-only fund with a 10% cash sleeve\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.12\n    gross_leverage_max: 1.0\n    cash_ticker: CASH\n    rebalance_frequency: monthly\n")
    w = {t: 0.10 for t in tk[:5]}; w.update({t: -0.10 for t in tk[5:]})
    put(m, "02_market_neutral_nothing_declared", {"weights.csv": wrows(me, w), "prices.csv": px},
        E("Dollar-neutral book: 5 longs +10%, 5 shorts -10%, net 0, gross 1.0. rules.yaml declares nothing. Doc: sum 0 is market neutral and is not a missing cash row.",
          inc=[("portfolio_constraints", ["INFO"])],
          notinc=NOALERT(["portfolio_constraints", "portfolio_concentration"]), only=[]),
        "strategy: Dollar-neutral long/short equity\n")
    w = {t: -0.10 for t in tk}
    put(m, "03_short_only_declared", {"weights.csv": wrows(me, w), "prices.csv": px},
        E("Short-only book, ten shorts at -10% (net -1.0, gross 1.0), declared net_exposure [-1.05,-0.95], gross_leverage_max 1.0, max_weight 0.12.",
          inc=[("portfolio_constraints", ["PASS"])],
          notinc=NOALERT(["portfolio_constraints", "portfolio_concentration"]), only=[]),
        "strategy: Short-only overlay\nconstraints:\n  portfolio:\n    net_exposure: [-1.05, -0.95]\n    gross_leverage_max: 1.0\n    max_weight: 0.12\n")
    for seed in range(100, 400):
        px4, days4 = gbm_prices(tk, [0.35] * 5 + [-0.05] * 5, [0.15] * 10, seed)
        me4 = month_ends(days4)
        wm = {t: 0.15 for t in tk[:5]}; wm.update({t: 0.05 for t in tk[5:]})
        ws = {d: wm for d in me4}
        sa = own_sim(px4, ws, me4)
        sb = own_sim(px4, {d: {t: 0.1 for t in tk} for d in me4}, me4)
        idx = sa.index.intersection(sb.index)
        z = jkm_z(sa[idx], sb[idx])
        if z[0] > 3.0: break
    print("P04 seed", seed, "own JKM (z, sr1, sr2, rho, T):", z)
    put(m, "04_tilt_beats_naive", {"weights.csv": wrows(me4, wm), "prices.csv": px4},
        E("Constant 15%/5% tilt towards the five high-drift names, rebalanced monthly to the same target; own JKM z > 3 (asserted in the generator). Drift-adjusted turnover is small, not an alert.",
          inc=[("portfolio_constraints", ["PASS"]), ("portfolio_turnover", ["INFO"]), ("portfolio_vs_naive", ["INFO"])],
          notinc=NOALERT(["portfolio_constraints", "portfolio_turnover", "portfolio_vs_naive"]), only=[]),
        "strategy: Quality tilt model portfolio\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.20\n    rebalance_frequency: monthly\n")
    wp = {t: 10.0 for t in tk}
    put(m, "05_weights_in_percent", {"weights.csv": wrows(me, wp), "prices.csv": px},
        E("Weights delivered in percent (ten names at 10.0, sum 100) with long_only and max_weight 0.10 declared as fractions.",
          inc=[("portfolio_constraints", ["CONFIRMED_ERROR"])]),
        "strategy: Long-only\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.10\n")
    t8 = tk[:8]
    a = wrows(me[:24], {t: 0.125 for t in t8}, "PA")
    b = wrows(me[:24], {t: 0.125 for t in t8}, "PB")
    sel = (b["date"] == me[10]) & (b["ticker"] == "T01"); b.loc[sel, "weight"] = 0.20
    sel = (b["date"] == me[10]) & (b["ticker"] == "T02"); b.loc[sel, "weight"] = 0.05
    put(m, "06_two_portfolios_one_breach", {"weights.csv": pd.concat([a, b], ignore_index=True), "prices.csv": px},
        E("Two portfolios in one file; PB holds T01 at 20% on one date with max_weight 0.15 declared (sum still 1). PA is clean.",
          inc=[("portfolio_constraints", ["CONFIRMED_ERROR"])], text=[("portfolio_constraints", "PB")]),
        "strategy: Two model portfolios\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.15\n")
    w = {t: 0.1 for t in tk}
    put(m, "07_model_is_one_over_n", {"weights.csv": wrows(me, w), "prices.csv": px},
        E("The model is exactly 1/N rebalanced monthly; model minus 1/N is identically zero (zero variance of the difference). Must not crash and must say it does not beat 1/N.",
          inc=[("portfolio_vs_naive", ["NEEDS_REVIEW"]), ("portfolio_constraints", ["PASS"])],
          notinc=NOCE(["portfolio_vs_naive", "portfolio_turnover"]), only=[]),
        "strategy: Equal-weight\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.12\n    rebalance_frequency: monthly\n")

# ============================================================== LIVE
def bt_series(n, seed, mu=0.0006, sd=0.008, start="2019-01-01"):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n)
    return days, mu + sd * rng.standard_normal(n), rng

def sharpe(r, ppy): r = np.asarray(r); return r.mean() / r.std(ddof=1) * math.sqrt(ppy)

def rules(days, n0, extra=""):
    return (f"strategy: daily\nconventions:\n  periods_per_year: 252\n  review_date: '{days[-1].date()}'\n"
            f"live:\n  start: {days[n0].date()}\n  backtest_end: {days[n0-1].date()}\n{extra}")

def gen_live():
    m = "live"
    for seed in range(1, 300):
        days = pd.date_range("2018-01-31", periods=72, freq="ME")
        rng = np.random.default_rng(seed)
        bt = 0.008 + 0.035 * rng.standard_normal(72)
        live = bt - 0.0002 + 0.002 * rng.standard_normal(72)
        s_bt, s_live = sharpe(bt[:42], 12), sharpe(live[42:], 12)
        if s_live > 0.8 * s_bt and abs(live[42:].mean() - bt[:42].mean()) < 0.003 and bt[:42].mean() > 0.005: break
    put(m, "01_monthly_clean", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                                "live_returns.csv": pd.DataFrame({"date": days[42:], "return": live[42:]})},
        E("Monthly record, 42 months backtest + 30 live months with shadow backtest over the live months; live = shadow + 20 bps noise; same drift. live_monthly profile (min 24 periods).",
          inc=[("live_period_integrity", ["PASS"]), ("live_vs_shadow_backtest", ["PASS", "INFO"])],
          notinc=NOALERT(["live_period_integrity", "live_vs_shadow_backtest", "live_performance_decay", "live_structural_break", "live_declared_vs_realised"]),
          only=[], profile="live_monthly"),
        f"strategy: monthly strategy\nconventions:\n  periods_per_year: 12\n  review_date: '2023-12-31'\nlive:\n  start: {days[42].date()}\n  backtest_end: {days[41].date()}\n")
    days, bt, rng = bt_series(1100, 7)
    live = bt + 0.0005 * rng.standard_normal(1100) - 0.00002
    n0 = 700
    put(m, "02_boundary_dates", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                                 "live_returns.csv": pd.DataFrame({"date": days[n0:], "return": live[n0:]})},
        E("First live date equals live.start and last live date equals review_date exactly (neither is before start nor after review); shadow backtest present; no gap.",
          inc=[("live_period_integrity", ["PASS"])],
          notinc=NOCE(["live_period_integrity", "live_vs_shadow_backtest"]) + [("live_period_integrity", "NEEDS_REVIEW")], only=[]),
        rules(days, n0))
    days, bt, rng = bt_series(1000, 8)
    live = 0.9 * bt + 0.00001
    n0 = 700
    put(m, "03_scaled_copy", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                              "live_returns.csv": pd.DataFrame({"date": days[n0:], "return": live[n0:]})},
        E("Live = 0.9 x backtest + 1e-5, an exact affine transform of the shadow backtest on 300 days: a doctored paste. Doc: NEEDS_REVIEW (affine, corr > 0.99999).",
          inc=[("live_period_integrity", ["NEEDS_REVIEW", "CONFIRMED_ERROR"])], notinc=[("live_period_integrity", "PASS")]),
        rules(days, n0))
    days, bt, rng = bt_series(1100, 9)
    n0 = 600
    live = bt + 0.003 * rng.standard_normal(1100)
    te = np.std((live - bt)[n0:], ddof=1) * math.sqrt(252)
    print("L04 own TE", te)
    put(m, "04_high_tracking_error", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                                      "live_returns.csv": pd.DataFrame({"date": days[n0:], "return": live[n0:]})},
        E("Live = shadow + N(0, 30 bps) per day over 500 days: tracking error about 4.8% a year > 3% default threshold; correlation still high; mean diff zero.",
          inc=[("live_vs_shadow_backtest", ["NEEDS_REVIEW"])], notinc=NOCE(["live_vs_shadow_backtest", "live_period_integrity"]), only=[]),
        rules(days, n0))
    days, bt, rng = bt_series(1000, 10)
    n0 = 700
    live = bt + 0.0005 * rng.standard_normal(1000)
    ldf = pd.DataFrame({"date": days[n0:], "return": live[n0:]})
    ldf = pd.concat([ldf.iloc[:120], ldf.iloc[[119]], ldf.iloc[120:]], ignore_index=True)
    put(m, "05_duplicate_live_row", {"returns.csv": pd.DataFrame({"date": days, "return": bt}), "live_returns.csv": ldf},
        E("One live date appears twice (single account, no account column). Doc: duplicates are CONFIRMED_ERROR.",
          inc=[("live_period_integrity", ["CONFIRMED_ERROR"])], only=["live_period_integrity"]),
        rules(days, n0))
    days, bt, rng = bt_series(1000, 11)
    n0 = 750
    live = bt + 0.0004 * rng.standard_normal(1000)
    nav = 100 * np.cumprod(1 + live[n0:])
    nav[[60, 140]] = np.nan
    put(m, "06_nav_with_nan", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                               "live_returns.csv": pd.DataFrame({"date": days[n0:], "nav": nav})},
        E("Live record delivered as NAV (starting ~100), two NaN NAV days. 250 days, shadow backtest. Must not crash; no CONFIRMED_ERROR; shadow comparison runs (PASS/INFO).",
          inc=[("live_vs_shadow_backtest", ["PASS", "INFO"])],
          notinc=NOCE(["live_period_integrity", "live_vs_shadow_backtest", "live_performance_decay", "live_structural_break", "live_declared_vs_realised"]), only=[]),
        rules(days, n0))
    for seed in range(12, 200):
        days, bt, rng = bt_series(1000, seed)
        n0 = 700
        live = bt + 0.0005 * rng.standard_normal(1000)
        b = bt[:n0]
        nav = np.cumprod(1 + b); dd_bt = (nav / np.maximum.accumulate(nav) - 1).min()
        nl = np.cumprod(1 + live[n0:]); dd_l = (nl / np.maximum.accumulate(nl) - 1).min()
        if abs(dd_l) < 0.8 * abs(dd_bt) and sharpe(live[n0:], 252) > 0.7 * sharpe(b, 252): break
    sh = round(sharpe(b, 252), 4); ar = round(nav[-1] ** (252 / n0) - 1, 5); md = round(float(dd_bt), 5)
    print("L07 declared", sh, ar, md)
    put(m, "07_correct_declarations", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                                       "live_returns.csv": pd.DataFrame({"date": days[n0:], "return": live[n0:]})},
        E("Declared sharpe / annual_return (geometric CAGR, 252/n) / max_drawdown exactly equal what the backtest period gives; live drawdown shallower than the backtest's.",
          inc=[("live_declared_vs_realised", ["INFO"])], notinc=NOALERT(["live_declared_vs_realised"]) + NOCE(["live_period_integrity"]), only=[]),
        rules(days, n0, f"  declared_sharpe: {sh}\n  declared_annual_return: {ar}\n  declared_max_drawdown: {md}\n"))
    for seed in range(13, 300):
        rng = np.random.default_rng(seed)
        days = pd.bdate_range("2017-01-02", periods=1400)
        bt = 0.0008 + 0.008 * rng.standard_normal(1000)
        lv = -0.0004 + 0.008 * rng.standard_normal(400)
        se = math.sqrt(bt.var(ddof=1) / 1000 + lv.var(ddof=1) / 400)
        if (bt.mean() - lv.mean()) / se > 2.6 and sharpe(lv, 252) < 0.3 * sharpe(bt, 252): break
    print("L08 own sharpes", sharpe(bt, 252), sharpe(lv, 252), "seed", seed)
    put(m, "08_decay_no_shadow", {"returns.csv": pd.DataFrame({"date": days[:1000], "return": bt}),
                                  "live_returns.csv": pd.DataFrame({"date": days[1000:], "return": lv})},
        E("Backtest 1000 days SR~1.6 (ends the day before live); live 400 days with negative mean (edge gone), no shadow over the live period.",
          inc=[("live_performance_decay", ["NEEDS_REVIEW"]), ("live_structural_break", ["NEEDS_REVIEW"]),
               ("live_period_integrity", ["NEEDS_REVIEW"]), ("live_vs_shadow_backtest", ["NOT_EXECUTABLE"])],
          notinc=NOCE(["live_performance_decay", "live_structural_break", "live_period_integrity"]), only=[]),
        rules(days, 1000))


# ============================================================== EXTRA CASES (pre-registered in this same file, before the first tool run on them)
def gen_extra():
    # ---- risk
    m = "risk"
    dates, sig, pnl = calibrated(1000, 81)
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": -Z99 * sig})
    put(m, "08_negative_quantile_declared", {"var_forecasts.csv": df},
        E("VaR delivered as negative quantiles (var_99 = -2.33 sigma), declared conventions.risk_var_sign negative_quantile; calibrated, 1000 days.",
          inc=[("var_coverage", ["PASS"])],
          notinc=NOALERT(["var_input_coherence", "var_coverage", "var_independence"]) + NOCE(["basel_traffic_light"]), only=[]),
        "conventions:\n  risk_var_sign: negative_quantile\n")
    for s0 in range(91, 3000):
        dates, sig, z = risk_base(300, s0)
        pnl = sig * z; ex = ex_flags(pnl, Z975 * sig); x = ex.sum()
        if 5 <= x <= 10 and chi1_sf(kupiec(x, 300, 0.025)) > 0.3 and not any(ex[i] and ex[i + 1] for i in range(299)):
            break
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_975": Z975 * sig})
    put(m, "09_only_975_level", {"var_forecasts.csv": df},
        E("Only a 97.5% VaR column (var_975), 300 days, calibrated. Coverage passes; the Basel traffic light needs var_99 and must be NOT_EXECUTABLE (not PASS, not an alert).",
          inc=[("var_coverage", ["PASS"]), ("basel_traffic_light", ["NOT_EXECUTABLE"])],
          notinc=NOALERT(["var_input_coherence", "var_coverage"]) + NOCE(["basel_traffic_light", "var_independence"]), only=[]))
    dates, sig, z = risk_base(260, 101, clip=2.2)
    pnl = sig * z; var = 1.6 * Z99 * sig
    assert ex_flags(pnl, var).sum() == 0
    df = pd.DataFrame({"date": dates, "pnl": pnl, "var_99": var})
    put(m, "10_zero_exceptions_260_days", {"var_forecasts.csv": df},
        E("260 days, VaR 60% too large, 0 exceptions (2.6 expected). Doc rule: Kupiec p<alpha -> NEEDS_REVIEW 'too few' (LR=5.22, p=0.022). Exact binomial P(X=0)=0.073 though.",
          inc=[("var_coverage", ["NEEDS_REVIEW"])], notinc=NOCE(["var_coverage", "basel_traffic_light"]) + [("var_coverage", "PASS")],
          text=[("var_coverage", "too few")], only=[]))
    # ---- portfolio
    m = "portfolio"
    tk = [f"T{i:02d}" for i in range(1, 11)]
    px, days = gbm_prices(tk, [0.08] * 10, [0.2] * 10, 5)
    me = month_ends(days)
    w = wrows(me, {t: 0.10 for t in tk[1:]})
    w1 = wrows(me, {"T01": 0.06}); w2 = wrows(me, {"T01": 0.04})
    put(m, "08_duplicate_rows_summed", {"weights.csv": pd.concat([w, w1, w2], ignore_index=True), "prices.csv": px},
        E("T01 delivered as two rows per date (0.06 + 0.04, two lots/sleeves); doc: duplicates are summed -> 0.10 = max_weight 0.10, sum 1.00. Must not alert.",
          inc=[("portfolio_constraints", ["PASS"])], notinc=NOALERT(["portfolio_constraints"]), only=[]),
        "strategy: Long-only\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.10\n")
    wm = {t: 0.08 for t in tk[:5]}; wm.update({t: -0.08 for t in tk[5:]})
    pxp = px.pivot(index="date", columns="ticker", values="close")
    prow = []
    for d in me:
        for t, wt in wm.items():
            prow.append({"date": d, "ticker": t, "quantity": round(wt * 1e6 / pxp.loc[d, t], 6)})
    put(m, "09_positions_market_neutral_gross_08", {"weights.csv": wrows(me, wm), "prices.csv": px, "positions.csv": pd.DataFrame(prow)},
        E("Market-neutral book (+-8%, net 0, gross 0.8) with positions that implement it exactly (quantity = w x 1e6 / close). Implied weights are normalised by gross, so they equal the declared ones normalised by gross. Net is zero: a normalisation by net or sum would blow up.",
          inc=[("portfolio_weights_vs_positions", ["PASS"])], notinc=NOALERT(["portfolio_weights_vs_positions"]), only=[]),
        "strategy: Dollar-neutral long/short equity\nconstraints:\n  portfolio:\n    gross_leverage_max: 1.0\n")
    # ---- live
    m = "live"
    days, bt, rng = bt_series(1000, 21)
    n0 = 700
    live = bt + 0.0003 * rng.standard_normal(1000)
    ts = []
    idx = rng.choice(np.arange(n0, 1000), 150, replace=False); idx.sort()
    rows = []
    for k, i in enumerate(idx):
        side = "buy" if k % 2 == 0 else "sell"
        mp = 100 * (1 + 0.01 * rng.standard_normal())
        fp = mp * (1 - 0.0015) if side == "buy" else mp * (1 + 0.0015)
        mt = pd.Timestamp(days[i]) + pd.Timedelta(hours=10)
        rows.append({"timestamp": mt + pd.Timedelta(minutes=5), "ticker": "AAA" if k % 3 else "BBB", "side": side,
                     "quantity": 100, "price": fp, "model_price": mp, "model_timestamp": mt})
    put(m, "09_favourable_fills_both_sides", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                                              "live_returns.csv": pd.DataFrame({"date": days[n0:], "return": live[n0:]}),
                                              "live_trades.csv": pd.DataFrame(rows)},
        E("All 150 fills are 15 bps BETTER than the model price (buys 15 bps below, sells 15 bps above): signed slippage is -15 bps on both sides. Execution quality must not flag (a side-blind computation would show +15 bps on sells... and a sign error +15 overall).",
          inc=[("live_execution_quality", ["INFO"])], notinc=NOALERT(["live_execution_quality"]), only=[]),
        rules(days, n0))
    days, bt, rng = bt_series(1000, 22)
    n0 = 700
    live = bt + 0.0005 * rng.standard_normal(1000)
    put(m, "10_live_in_percent_units", {"returns.csv": pd.DataFrame({"date": days, "return": bt}),
                                        "live_returns.csv": pd.DataFrame({"date": days[n0:], "return": 100 * live[n0:]})},
        E("Live returns delivered in percent (x100) while the backtest is in fractions; same underlying record. Shadow comparison must not PASS.",
          inc=[("live_vs_shadow_backtest", ["NEEDS_REVIEW", "CONFIRMED_ERROR"])], notinc=[("live_vs_shadow_backtest", "PASS")]),
        rules(days, n0))


def gen_extra2():
    m = "risk"
    Z95, ES95 = 1.6448536270, 2.0627128075
    for tag, mult, name in (("es_too_small", 0.7, "11_es_95_too_small_30pct"), ("es_right", 1.0, "12_es_95_correct")):
        dates, sig, z = risk_base(2000, 111 if mult < 1 else 112)
        pnl = sig * z; var = Z95 * sig; es = mult * ES95 * sig
        ex = ex_flags(pnl, var); x = ex.sum()
        print(name, "exceptions", x, "kupiec p", chi1_sf(kupiec(x, 2000, .05)))
        df = pd.DataFrame({"date": dates, "pnl": pnl, "var_95": var, "es_95": es})
        if mult < 1:
            e = E("2000 days, correct 95% VaR, ES forecast 30% too small (0.7 x true): mean realised loss on exception days about 1.43 x mean ES (> 1.25 rule), Z2 about -0.43 (not below -0.70).",
                  inc=[("es_backtest", ["NEEDS_REVIEW"])], notinc=NOCE(["es_backtest", "var_input_coherence"]), only=[])
        else:
            e = E("2000 days, correct 95% VaR and correct ES (sigma x 2.0627). ES backtest must not alert (INFO).",
                  inc=[("es_backtest", ["INFO"])], notinc=NOALERT(["es_backtest", "var_input_coherence"]), only=[])
        put(m, name, {"var_forecasts.csv": df}, e)
    m = "portfolio"
    tk = [f"T{i:02d}" for i in range(1, 11)]
    px, days = gbm_prices(tk, [0.35] * 5 + [-0.05] * 5, [0.15] * 10, 100)
    me = month_ends(days)
    wm = {t: 0.15 for t in tk[:5]}; wm.update({t: 0.05 for t in tk[5:]})
    put(m, "10_quarterly_declared_monthly_constant_rows", {"weights.csv": wrows(me, wm), "prices.csv": px},
        E("Target never changes (raw weights identical on all 36 month-ends) but rules.yaml declares quarterly rebalancing. No weight changed, so no change can be outside the schedule: no CONFIRMED_ERROR. (Drift between rows exists but the delivered weights did not change.)",
          notinc=NOCE(["portfolio_turnover", "portfolio_constraints"]), only=[]),
        "strategy: Quality tilt\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.20\n    rebalance_frequency: quarterly\n")
    pxm = px[px["date"].isin(me)]
    put(m, "11_monthly_price_frequency", {"weights.csv": wrows(me, wm), "prices.csv": pxm},
        E("Same tilt as 04 but prices.csv has month-end rows only (36 per name): periods per year must be inferred as 12; the path beats nothing in particular (statuses INFO or NEEDS_REVIEW), no crash, no CONFIRMED_ERROR; Sharpe annualised with 12.",
          inc=[("portfolio_vs_naive", ["INFO", "NEEDS_REVIEW"])], notinc=NOCE(["portfolio_vs_naive", "portfolio_turnover", "portfolio_constraints"]), only=[]),
        "strategy: Quality tilt\nconstraints:\n  portfolio:\n    long_only: true\n    max_weight: 0.20\n    rebalance_frequency: monthly\n")

if __name__ == "__main__":
    gen_risk(); gen_portfolio(); gen_live(); gen_extra(); gen_extra2()
    print("done")
