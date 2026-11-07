"""Independent review generator (v0.3.0). Does NOT import lockin_validate. expected.json is written here, before any run."""
import csv, json, math, shutil, datetime as dt
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent


def out(mod, name, files, expected, rules=None):
    d = ROOT / mod / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for fn, (hdr, rows) in files.items():
        with open(d / fn, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(hdr)
            w.writerows(rows)
    if rules:
        (d / "rules.yaml").write_text(rules)
    expected = dict(expected)
    expected["origin"] = "review_v030"
    expected["use_case"] = mod
    (d / "expected.json").write_text(json.dumps(expected, indent=2))


def inc(check, st):
    return {"check": check, "status": st if isinstance(st, list) else [st]}


def exc(check, st):
    return {"check": check, "status": st}


def bdays(start, n):
    o, d = [], start
    while len(o) < n:
        if d.weekday() < 5:
            o.append(d)
        d += dt.timedelta(days=1)
    return o


# ---------------------------------------------------------------- SIGNALS
SIG_RULES = "strategy: alpha signal under research\nconventions:\n  periods_per_year: 252\n  review_date: '2026-10-20'\n  short_selling: false\n{extra}"


def sig_world(seed, nt=30, ns=300, mu=None):
    rng = np.random.default_rng(seed)
    dates = bdays(dt.date(2023, 1, 2), ns)
    ret = rng.normal(0, 0.015, (ns, nt))
    if mu is not None:
        ret = ret + mu[None, :]
    return rng, dates, ret


def px_rows(dates, ret, skip=None):
    px = 100 * np.cumprod(1 + ret, axis=0)
    rows = []
    for i, d in enumerate(dates):
        for j in range(ret.shape[1]):
            if skip and skip(i, j):
                continue
            rows.append([d.isoformat(), f"T{j:02d}", f"{px[i, j]:.4f}"])
    return rows


def sig_expected(desc, inc_l, exc_l):
    return {"description": desc, "profile": "signal_research", "must_include": inc_l, "must_not_include": exc_l,
            "errors_only_from": []}


# S01 clean predictive, tz-stamped decisions after the close
rng, dates, ret = sig_world(101)
dec = list(range(5, 281, 5))
Z = {d: rng.normal(size=30) for d in dec}
for d in dec:
    ret[d + 2] += 0.004 * Z[d]
srows = [[f"{dates[d].isoformat()} 17:30:00-05:00", f"T{j:02d}", f"{Z[d][j]:.6f}"] for d in dec for j in range(30)]
out("signals", "01_clean_tz_stamped", {"signals.csv": (["decision_time", "ticker", "signal"], srows),
    "prices.csv": (["date", "ticker", "close"], px_rows(dates, ret))},
    sig_expected("Genuine iid signal predicting the session t+2 return (IC ~0.25), decisions stamped with a -05:00 timezone after the close.",
                 [inc("signal_forward_alignment", "PASS"), inc("signal_predictive_power", "INFO"),
                  inc("signal_lookahead_hint", "INFO"), inc("signal_quantile_spread", "INFO")],
                 [exc("signal_predictive_power", "NEEDS_REVIEW"), exc("signal_forward_alignment", "NEEDS_REVIEW"),
                  exc("signal_lookahead_hint", "NEEDS_REVIEW")]), SIG_RULES.format(extra=""))

# S02 ticker with a price gap and a late-listed ticker, signals present throughout
rng, dates, ret = sig_world(102)
dec = list(range(5, 281, 5))
Z = {d: rng.normal(size=30) for d in dec}
for d in dec:
    ret[d + 2] += 0.004 * Z[d]
srows = [[dates[d].isoformat(), f"T{j:02d}", f"{Z[d][j]:.6f}"] for d in dec for j in range(30)]
skip = lambda i, j: (j == 7 and 100 <= i < 131) or (j == 12 and i < 150)
out("signals", "02_price_gaps_late_listing", {"signals.csv": (["decision_time", "ticker", "signal"], srows),
    "prices.csv": (["date", "ticker", "close"], px_rows(dates, ret, skip))},
    sig_expected("Same genuine signal; T07 has no prices for 31 sessions (halt) and T12 only lists after session 150, signals exist throughout (<3% of rows affected).",
                 [inc("signal_forward_alignment", ["PASS", "INFO"]), inc("signal_predictive_power", "INFO")],
                 [exc("signal_forward_alignment", "NEEDS_REVIEW")]), SIG_RULES.format(extra=""))

# S03 constant signal
rng, dates, ret = sig_world(103, ns=150)
dec = list(range(5, 141, 5))
srows = [[dates[d].isoformat(), f"T{j:02d}", "1.0"] for d in dec for j in range(30)]
out("signals", "03_constant_signal", {"signals.csv": (["decision_time", "ticker", "signal"], srows),
    "prices.csv": (["date", "ticker", "close"], px_rows(dates, ret))},
    sig_expected("Signal column is constant (1.0): no information, IC undefined. Must never be reported as a significant IC.",
                 [inc("signal_predictive_power", ["NOT_EXECUTABLE", "NEEDS_REVIEW"]),
                  inc("signal_quantile_spread", ["NOT_EXECUTABLE", "NEEDS_REVIEW"])],
                 [exc("signal_predictive_power", "INFO"), exc("signal_predictive_power", "PASS"),
                  exc("signal_quantile_spread", "INFO")]), SIG_RULES.format(extra=""))

# S04 heavy ties + NaN, returns with a ticker fixed effect aligned with file order, no skill
for seed in range(104, 140):
    rng, dates, ret = sig_world(seed, mu=(np.arange(30) - 14.5) * 0.0004)
    dec = list(range(5, 281, 5))
    S = {d: rng.integers(1, 4, size=30).astype(float) for d in dec}
    for d in dec:
        S[d][rng.random(30) < 0.05] = np.nan
    ics = []
    for d in dec:
        s, r = S[d], ret[d + 2]
        m = ~np.isnan(s)
        ics.append(np.corrcoef(s[m], r[m])[0, 1])
    t = np.mean(ics) / (np.std(ics, ddof=1) / math.sqrt(len(ics)))
    if abs(t) < 1.0:
        break
srows = [[dates[d].isoformat(), f"T{j:02d}", "" if np.isnan(S[d][j]) else f"{S[d][j]:.0f}"] for d in dec for j in range(30)]
out("signals", "04_ties_nan_ticker_effect", {"signals.csv": (["decision_time", "ticker", "signal"], srows),
    "prices.csv": (["date", "ticker", "close"], px_rows(dates, ret))},
    sig_expected("Signal is a random 3-level score (massive ties, 5% blank) with NO skill; returns carry a ticker fixed effect increasing with file order. Tie-breaking by file order must not manufacture a significant spread.",
                 [inc("signal_predictive_power", "NEEDS_REVIEW"), inc("signal_quantile_spread", "NEEDS_REVIEW")],
                 [exc("signal_predictive_power", "INFO"), exc("signal_quantile_spread", "INFO")]), SIG_RULES.format(extra=""))

# S05 lag 0 legit: decision after the close of a session day
rng, dates, ret = sig_world(105)
dec = list(range(5, 281, 5))
Z = {d: rng.normal(size=30) for d in dec}
for d in dec:
    ret[d + 1] += 0.004 * Z[d]
srows = [[f"{dates[d].isoformat()} 16:30:00", f"T{j:02d}", f"{Z[d][j]:.6f}"] for d in dec for j in range(30)]
out("signals", "05_lag0_after_close_legit", {"signals.csv": (["decision_time", "ticker", "signal"], srows),
    "prices.csv": (["date", "ticker", "close"], px_rows(dates, ret))},
    sig_expected("signal_lag_sessions: 0 declared, decisions on session days stamped 16:30 (after close): legitimate, signal predicts next session.",
                 [inc("signal_forward_alignment", ["INFO", "PASS"]), inc("signal_predictive_power", "INFO"),
                  inc("signal_lookahead_hint", "INFO")],
                 [exc("signal_lookahead_hint", "NEEDS_REVIEW")]), SIG_RULES.format(extra="  signal_lag_sessions: 0\n"))

# S06 Saturday decisions with lag 1 + 3 trailing decision dates beyond the price history
rng, dates, ret = sig_world(106)
fri = [i for i, d in enumerate(dates) if d.weekday() == 4 and 4 <= i < 281]
extra_dec = [300, 305, 310]  # virtual sessions beyond history
Z = {d: rng.normal(size=30) for d in fri + extra_dec}
for d in fri:
    if d + 3 < 300:
        ret[d + 3] += 0.004 * Z[d]


def sat(i):
    return dates[299] + dt.timedelta(days=1 + (i - 299) * 7 // 5) if i >= 300 else dates[i] + dt.timedelta(days=1)


srows = [[sat(d).isoformat(), f"T{j:02d}", f"{Z[d][j]:.6f}"] for d in fri + extra_dec for j in range(30)]
out("signals", "06_saturday_decisions_trailing", {"signals.csv": (["decision_time", "ticker", "signal"], srows),
    "prices.csv": (["date", "ticker", "close"], px_rows(dates, ret))},
    sig_expected("Decisions dated on Saturdays with default lag 1 (entry Tuesday close): legitimate. Plus 3 decision dates after the last price date (~5% of rows) that must be excluded, not crash or alert.",
                 [inc("signal_forward_alignment", "PASS"), inc("signal_predictive_power", "INFO")],
                 [exc("signal_forward_alignment", "NEEDS_REVIEW")]), SIG_RULES.format(extra=""))


# ---------------------------------------------------------------- ML
def sig(x):
    return 1 / (1 + np.exp(-x))


def ml_std(rng, n=(2000, 500, 1000), pf=None, names=("train", "validation", "test"),
           cols=("sample_id", "timestamp", "label_end", "split", "ticker"),
           pcols=("sample_id", "prediction", "actual", "probability"), nan_test=0, label_days=10):
    ranges = [(dt.date(2018, 1, 1), 364), (dt.date(2019, 1, 20), 130), (dt.date(2019, 8, 1), 152)]
    srows, prows, k = [], [], 0
    for si, (cnt, (st, span)) in enumerate(zip(n, ranges)):
        offs = np.sort(rng.integers(0, span + 1, cnt))
        p, y = pf(rng, cnt, si)
        for o, pi, yi in zip(offs, p, y):
            k += 1
            ts = st + dt.timedelta(days=int(o))
            sid = f"s{k:06d}"
            srows.append([sid, ts.isoformat(), (ts + dt.timedelta(days=label_days)).isoformat(), names[si], "ABCDEFGHIJ"[k % 10]])
            prows.append([sid, int(pi >= 0.5), int(yi), f"{pi:.6f}"])
    if nan_test:
        idx = [i for i, r in enumerate(srows) if r[3] == names[2]][:nan_test]
        for i in idx:
            prows[i][3] = ""
    return (list(cols), srows), (list(pcols), prows)


def pf_calibrated(rng, n, si):
    p = sig(rng.normal(0, 1.2, n))
    return p, (rng.random(n) < p).astype(int)


def ml_exp(desc, inc_l, exc_l=(), errs=()):
    return {"description": desc, "must_include": inc_l, "must_not_include": list(exc_l), "errors_only_from": list(errs)}


ML_RULES = "model: review\nconventions:\n  ml_embargo_days: 15\n"

# M01 clean with aliases, split synonyms, 3 blank probabilities
rng = np.random.default_rng(201)
(sh, sr), (ph, pr) = ml_std(rng, pf=pf_calibrated, names=("training", "dev", "oos"),
                            cols=("sample_id", "date", "label_end", "split", "ticker"),
                            pcols=("sample_id", "prediction", "y_true", "score"), nan_test=3)
out("ml", "01_clean_aliases_synonyms", {"ml_samples.csv": (sh, sr), "ml_predictions.csv": (ph, pr)},
    ml_exp("Clean temporal split with aliases (date, y_true, score), synonyms (training/dev/oos), calibrated probabilities, 3 blank scores in test.",
           [inc("ml_split_leakage", "PASS"), inc("ml_calibration", "PASS"), inc("ml_overfit_gap", "INFO"),
            inc("ml_population_stability", "INFO")]), ML_RULES)


# M02 probabilities exactly 0 and 1 (and correct)
def pf_extreme(rng, n, si):
    p = rng.uniform(0.1, 0.9, n)
    y = (rng.random(n) < p).astype(int)
    u = rng.random(n)
    p = np.where(u < 0.1, 1.0, np.where(u < 0.2, 0.0, p))
    y = np.where(u < 0.1, 1, np.where(u < 0.2, 0, y))
    return p, y


rng = np.random.default_rng(202)
(sh, sr), (ph, pr) = ml_std(rng, n=(1500, 400, 1000), pf=pf_extreme)
out("ml", "02_probabilities_exactly_0_and_1", {"ml_samples.csv": (sh, sr), "ml_predictions.csv": (ph, pr)},
    ml_exp("20% of the rows have probability exactly 1.0 or 0.0 and are always right; the rest is calibrated. No inf/NaN, no alert.",
           [inc("ml_split_leakage", "PASS"), inc("ml_calibration", "PASS"), inc("ml_overfit_gap", "INFO")]), ML_RULES)


# M03 single class in test
def pf_oneclass(rng, n, si):
    if si == 2:
        return rng.uniform(0.0, 0.1, n), np.zeros(n, int)
    p = sig(rng.normal(-2.4, 1.0, n))
    return p, (rng.random(n) < p).astype(int)


rng = np.random.default_rng(203)
(sh, sr), (ph, pr) = ml_std(rng, n=(1500, 400, 500), pf=pf_oneclass)
out("ml", "03_single_class_in_test", {"ml_samples.csv": (sh, sr), "ml_predictions.csv": (ph, pr)},
    ml_exp("Test split has no positives at all (calm year): AUC undefined. overfit_gap must not report a metric table as INFO/PASS; label shift is real.",
           [inc("ml_overfit_gap", ["NOT_EXECUTABLE", "NEEDS_REVIEW"]), inc("ml_population_stability", "NEEDS_REVIEW")],
           [exc("ml_overfit_gap", "INFO"), exc("ml_overfit_gap", "PASS")]), ML_RULES)


# M04 constant probability, exact base rates
def pf_const(rng, n, si):
    y = np.zeros(n, int)
    y[: n // 10] = 1
    rng.shuffle(y)
    return np.full(n, 0.1), y


rng = np.random.default_rng(204)
(sh, sr), (ph, pr) = ml_std(rng, n=(1000, 300, 1000), pf=pf_const)
out("ml", "04_constant_probability", {"ml_samples.csv": (sh, sr), "ml_predictions.csv": (ph, pr)},
    ml_exp("Model outputs the base rate 0.10 for every row (AUC exactly 0.5, train excess 0); base rate 10% in every split. Must flag no skill, not crash, calibration fine, PSI zero.",
           [inc("ml_overfit_gap", "NEEDS_REVIEW"), inc("ml_calibration", "PASS"), inc("ml_population_stability", "INFO")]), ML_RULES)

# M05 boundary: last train label_end == first test timestamp, tz-stamped
rng = np.random.default_rng(205)
base = dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc)
tr_off = np.sort(np.concatenate([rng.integers(0, 181, 999), [180]]))
te_off = np.sort(np.concatenate([rng.integers(190, 301, 599), [190]]))
srows, prows = [], []
for k, (o, sp) in enumerate([(o, "train") for o in tr_off] + [(o, "test") for o in te_off]):
    ts = base + dt.timedelta(days=int(o))
    p = float(sig(rng.normal(0, 1.2)))
    y = int(rng.random() < p)
    sid = f"b{k:05d}"
    srows.append([sid, ts.isoformat(), (ts + dt.timedelta(days=10)).isoformat(), sp, "ABCDE"[k % 5]])
    prows.append([sid, int(p >= .5), y, f"{p:.6f}"])
out("ml", "05_boundary_touching_tz", {"ml_samples.csv": (["sample_id", "timestamp", "label_end", "split", "ticker"], srows),
    "ml_predictions.csv": (["sample_id", "prediction", "actual", "probability"], prows)},
    ml_exp("Timestamps with +00:00; the last training label_end coincides exactly with the first test timestamp, embargo 0. No sample overlaps: legitimate.",
           [inc("ml_split_leakage", "PASS")]), "model: review\n")

# M06 unpurged K-fold
rng = np.random.default_rng(206)
n = 1000
z = rng.normal(0, 1.0, n)
p = sig(z)
y = (rng.random(n) < p).astype(int)
srows, prows = [], []
for k in range(1, 6):
    for i in range(n):
        ts = dt.date(2018, 1, 1) + dt.timedelta(days=i)
        role = "test" if i // 200 + 1 == k else "train"
        sid = f"k{i:06d}"
        srows.append([sid, ts.isoformat(), (ts + dt.timedelta(days=20)).isoformat(), role, "AB"[i % 2], k])
        prows.append([sid, int(p[i] >= .5), int(y[i]), f"{p[i]:.6f}", k])
out("ml", "06_unpurged_kfold", {"ml_samples.csv": (["sample_id", "timestamp", "label_end", "split", "ticker", "fold"], srows),
    "ml_predictions.csv": (["sample_id", "prediction", "actual", "probability", "fold"], prows)},
    ml_exp("5-fold CV with contiguous test blocks, 20-day labels and NO purging: training windows cross into the test blocks.",
           [inc("ml_split_leakage", "CONFIRMED_ERROR")], [exc("ml_split_leakage", "PASS")], errs=["ml_split_leakage"]), "model: review\n")


# ---------------------------------------------------------------- FORECAST
def ar1(rng, n, phi=0.5):
    x = np.zeros(n + 1)
    for t in range(1, n + 1):
        x[t] = phi * x[t - 1] + rng.normal()
    return x


def iso(d, tz=False):
    return d.isoformat() + ("T00:00:00+00:00" if tz else "")


def fc_exp(desc, inc_l, exc_l=(), errs=()):
    return {"description": desc, "must_include": inc_l, "must_not_include": list(exc_l), "errors_only_from": list(errs)}


def month_end(y, m):
    return dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)


# F01 clean AR(1), aliases, tz-stamped
rng = np.random.default_rng(301)
x = ar1(rng, 300)
d0 = dt.date(2021, 1, 1)
rows = [[iso(d0 + dt.timedelta(days=t - 1), True), iso(d0 + dt.timedelta(days=t), True), f"{0.5 * x[t - 1]:.6f}", f"{x[t]:.6f}"] for t in range(1, 301)]
out("forecast", "01_clean_aliases_tz", {"forecasts.csv": (["origin", "date", "yhat", "y"], rows)},
    fc_exp("True one-step AR(1) forecasts, aliases origin/date/yhat/y and +00:00 timestamps. Must behave like the clean base case.",
           [inc("forecast_origin_integrity", "PASS"), inc("forecast_vs_naive", "INFO"), inc("forecast_bias", "INFO")],
           [exc("forecast_error_dynamics", "NEEDS_REVIEW")]))

# F02 business-day series, origin = previous business day, no horizon column
rng = np.random.default_rng(302)
x = ar1(rng, 330)
bd = bdays(dt.date(2021, 1, 4), 331)
rows = [[iso(bd[t - 1]), iso(bd[t]), f"{0.5 * x[t - 1]:.6f}", f"{x[t]:.6f}"] for t in range(1, 331)]
out("forecast", "02_business_days_weekend_gaps", {"forecasts.csv": (["origin_date", "target_date", "forecast", "actual"], rows)},
    fc_exp("Daily business-day series, one-step forecasts (origin = previous business day), no horizon column. Weekend gaps (3 calendar days) are NOT a mixed horizon.",
           [inc("forecast_origin_integrity", "PASS"), inc("forecast_vs_naive", "INFO")],
           [exc("forecast_error_dynamics", "NEEDS_REVIEW")]))

# F03 flat series
me = [month_end(2016 + (i // 12), i % 12 + 1) for i in range(81)]
rows = [[iso(me[i - 1]), iso(me[i]), "5.25", "5.25"] for i in range(1, 81)]
out("forecast", "03_flat_series_zero_variance", {"forecasts.csv": (["origin_date", "target_date", "forecast", "actual"], rows)},
    fc_exp("Policy rate that never moves for 80 months, forecast equal to it: zero variance everywhere. Must not crash, must not claim the model beats the naive.",
           [inc("forecast_vs_naive", ["NEEDS_REVIEW", "NOT_EXECUTABLE"]), inc("forecast_directional", "NOT_EXECUTABLE")],
           [exc("forecast_vs_naive", "INFO"), exc("forecast_error_dynamics", "NEEDS_REVIEW")]))

# F04 publication date before the period it measures in 3 rows
rng = np.random.default_rng(304)
x = ar1(rng, 120)
me2 = [month_end(2012 + (i // 12), i % 12 + 1) for i in range(121)]
rows = []
for t in range(1, 121):
    tgt = me2[t]
    av = tgt + dt.timedelta(days=15)
    if t in (30, 60, 90):
        av = tgt - dt.timedelta(days=10)
    rows.append([iso(me2[t - 1]), iso(tgt), f"{0.5 * x[t - 1]:.6f}", f"{x[t]:.6f}", iso(av)])
out("forecast", "04_published_before_period", {"forecasts.csv": (["origin_date", "target_date", "forecast", "actual", "actual_available_from"], rows)},
    fc_exp("Monthly series published 15 days after month-end, except 3 rows whose publication date precedes the period they measure (entry error).",
           [inc("forecast_origin_integrity", "CONFIRMED_ERROR")], [exc("forecast_origin_integrity", "PASS")], errs=["forecast_origin_integrity"]))

# F05 legit publication-aware naive, revised data declared, first naive blank
rng = np.random.default_rng(305)
x = ar1(rng, 120)
rows = []
for t in range(1, 121):
    tgt = me2[t]
    nv = f"{x[t - 2]:.6f}" if t >= 2 else ""
    rows.append([iso(me2[t - 1]), iso(tgt), f"{0.5 * x[t - 1]:.6f}", f"{x[t]:.6f}", iso(tgt + dt.timedelta(days=20)), nv])
out("forecast", "05_naive_publication_aware_legit", {"forecasts.csv": (["origin_date", "target_date", "forecast", "actual", "actual_available_from", "naive"], rows)},
    fc_exp("Revised-data series with publication dates; the supplied naive is exactly the last value published at each origin (t-2). Legitimate: must PASS, no CONFIRMED_ERROR.",
           [inc("forecast_origin_integrity", "PASS")], [exc("forecast_origin_integrity", "NEEDS_REVIEW")]),
    "forecast:\n  revised_data: true\n")

# F06 20 unique forecasts duplicated + blanks
rng = np.random.default_rng(306)
x = ar1(rng, 20)
rows = []
for t in range(1, 21):
    r = [iso(d0 + dt.timedelta(days=t - 1)), iso(d0 + dt.timedelta(days=t)), f"{0.5 * x[t - 1]:.6f}", f"{x[t]:.6f}"]
    rows += [r, list(r)]
for k in range(4):
    rows.append([iso(d0 + dt.timedelta(days=30 + k)), iso(d0 + dt.timedelta(days=31 + k)), "", "1.0"])
out("forecast", "06_duplicated_rows_insufficient", {"forecasts.csv": (["origin_date", "target_date", "forecast", "actual"], rows)},
    fc_exp("Only 20 distinct forecasts, each exported twice (40 rows >= the 30 minimum) plus 4 blank rows. Duplicates are not observations: statistics must be NOT_EXECUTABLE.",
           [inc("forecast_vs_naive", "NOT_EXECUTABLE")], [exc("forecast_vs_naive", "INFO")]))
print("generated")
