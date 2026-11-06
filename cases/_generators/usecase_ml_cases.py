"""Cases of the ``ml`` use case (cases/usecase_ml/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/usecase_ml_cases.py

Every case plants one problem in the sampling protocol or the predictions of a synthetic classifier (or
regression) and fixes expected.json from that problem BEFORE the tool runs. Where a random draw could contradict
the planted property, the generator asserts it with its OWN computation (pure numpy) and fails loudly.

  01_clean_purged          temporal split, label_end, 10-day embargo, calibrated honest model  -> nothing alerts
  02_temporal_overlap      test timestamps drawn inside the training window                   -> ml_split_leakage CONFIRMED_ERROR
  03_label_leak_no_purge   training label windows reach past the first test timestamp         -> ml_split_leakage CONFIRMED_ERROR
  04_duplicate_ids         30 sample ids both in train and test                               -> ml_split_leakage CONFIRMED_ERROR
  05_overfit               train AUC ~0.95, test AUC ~0.52                                    -> ml_overfit_gap NEEDS_REVIEW
  06_drift                 covariate shift in test (score distribution moves)                 -> ml_population_stability NEEDS_REVIEW
  07_target_leak_feature   a feature equal to the label plus small noise                      -> ml_target_leakage NEEDS_REVIEW
  08_miscalibrated         probabilities squeezed to 0.45-0.55                                -> ml_calibration NEEDS_REVIEW
  09_many_models_one_test  6 models scored on the same test split                             -> ml_evaluation_protocol NEEDS_REVIEW
  10_insufficient          50 test rows                                                       -> ml_overfit_gap NOT_EXECUTABLE
  11_regression_clean      honest regression                                                  -> ml_overfit_gap INFO, no alert
  12_purged_kfold_legit    5 purged folds whose test blocks sit inside the overall range       -> ml_split_leakage PASS (adversarial)
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "usecase_ml"
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]
HORIZON = 20  # calendar days from the sample timestamp to label_end
EMBARGO = 10
ALL_CHECKS = ["ml_split_leakage", "ml_overfit_gap", "ml_calibration", "ml_population_stability", "ml_target_leakage",
              "ml_evaluation_protocol"]


# ---------------------------------------------------------------------------- independent statistics

def auc(score, y) -> float:
    score, y = np.asarray(score, float), np.asarray(y, int)
    pos, neg = score[y == 1], score[y == 0]
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (pos.size * neg.size))


def ece(p, y, bins=10) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)[1:-1]))
    idx = np.searchsorted(edges, p, side="right")
    return float(sum((idx == b).sum() / p.size * abs(p[idx == b].mean() - y[idx == b].mean())
                     for b in range(edges.size + 1) if (idx == b).any()))


def psi(ref, cur, bins=10) -> float:
    ref, cur = np.asarray(ref, float), np.asarray(cur, float)
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)[1:-1]))
    e = np.maximum(np.bincount(np.searchsorted(edges, ref, side="right"), minlength=edges.size + 1) / ref.size, 1e-4)
    a = np.maximum(np.bincount(np.searchsorted(edges, cur, side="right"), minlength=edges.size + 1) / cur.size, 1e-4)
    return float(((a - e) * np.log(a / e)).sum())


def r2(pred, actual) -> float:
    pred, actual = np.asarray(pred, float), np.asarray(actual, float)
    return 1 - ((actual - pred) ** 2).sum() / ((actual - actual.mean()) ** 2).sum()


# ---------------------------------------------------------------------------- building blocks

def weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def dgp(rng, n: int, beta: float = 1.5, x_mean: float = 0.0):
    """Two features, a logistic outcome and the TRUE probability (a calibrated honest model)."""
    x1 = rng.normal(x_mean, 1.0, n)
    x2 = rng.normal(0.0, 1.0, n)
    p = sigmoid(beta * x1 + 0.3 * x2 - 0.2)
    y = (rng.random(n) < p).astype(int)
    return x1, x2, p, y


def block(rng, n: int, start: date, end: date, split: str, prefix: str, offset: int = 0, horizon: int = HORIZON):
    days = weekdays(start, end)
    ts = sorted(rng.choice(len(days), n, replace=True))
    rows = []
    for i, k in enumerate(ts):
        d = days[k]
        rows.append({"sample_id": f"{prefix}{offset + i + 1:06d}", "timestamp": d.isoformat(),
                     "label_end": (d + timedelta(days=horizon)).isoformat(), "split": split,
                     "ticker": TICKERS[int(rng.integers(len(TICKERS)))]})
    return rows


def write(name: str, samples, preds, features=None, fvals=None, rules: str = "", declared=None, *, expected: dict,
          description: str):
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)

    def table(fname, rows, cols):
        with open(c / fname, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    scols = ["sample_id", "timestamp", "label_end", "split", "ticker"] + (["fold"] if samples and "fold" in samples[0] else [])
    table("ml_samples.csv", samples, scols)
    pcols = ["sample_id", "prediction", "actual"] + [k for k in ("probability", "model", "fold") if preds and k in preds[0]]
    table("ml_predictions.csv", preds, pcols)
    if features is not None:
        table("ml_features.csv", features, ["feature", "available_from_lag_days", "source"])
    if fvals is not None:
        table("ml_feature_values.csv", fvals, ["sample_id", "feature", "value"])
    (c / "rules.yaml").write_text("model: synthetic model for the ml use-case battery\nconventions:\n"
                                  f"  ml_embargo_days: {EMBARGO}\n" + rules, encoding="utf-8")
    if declared is not None:
        (c / "declared_results.json").write_text(json.dumps(declared, indent=2), encoding="utf-8")
    exp = {"description": description, "origin": "usecase", "use_case": "ml", **expected}
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def must(check, *statuses):
    return {"check": check, "status": list(statuses)}


def mustnot(check, status):
    return {"check": check, "status": status}


def no_alerts(exclude=()):
    return [mustnot(c, s) for c in ALL_CHECKS if c not in exclude for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")]


def fmt(x, nd=6):
    return f"{x:.{nd}f}"


def classifier_case(seed: int, n_train: int, n_val: int, n_test: int, *, train_range, val_range, test_range,
                    beta=1.5, test_x_mean=0.0, model_prob=None, id_prefix="s"):
    """Samples + predictions of a calibrated classifier on a temporal split. Returns dict of arrays per split."""
    rng = np.random.default_rng(seed)
    out = {}
    offset = 0
    for split, n, rg in (("train", n_train, train_range), ("validation", n_val, val_range), ("test", n_test, test_range)):
        if n == 0:
            continue
        rows = block(rng, n, rg[0], rg[1], split, id_prefix, offset)
        offset += n
        x1, x2, p, y = dgp(rng, n, beta, test_x_mean if split == "test" else 0.0)
        prob = p if model_prob is None else model_prob(split, x1, x2, p, y, rng)
        out[split] = {"rows": rows, "x1": x1, "x2": x2, "p": p, "y": y, "prob": prob}
    return out


def assert_no_gap(parts, tol=0.10):
    a_tr, a_te = auc(parts["train"]["prob"], parts["train"]["y"]), auc(parts["test"]["prob"], parts["test"]["y"])
    assert (a_tr - a_te) / (a_tr - 0.5) < tol, (a_tr, a_te)


def to_tables(parts, model_name=None, feature_names=("x1", "x2")):
    samples, preds, fvals = [], [], []
    for d in parts.values():
        samples += d["rows"]
        for i, r in enumerate(d["rows"]):
            pr = {"sample_id": r["sample_id"], "prediction": int(d["prob"][i] >= 0.5), "actual": int(d["y"][i]),
                  "probability": fmt(d["prob"][i])}
            if model_name:
                pr["model"] = model_name
            preds.append(pr)
            for fn, arr in zip(feature_names, (d["x1"], d["x2"])):
                fvals.append({"sample_id": r["sample_id"], "feature": fn, "value": fmt(arr[i])})
    return samples, preds, fvals


TRAIN = (date(2018, 1, 2), date(2020, 12, 31))
VAL = (date(2021, 2, 1), date(2021, 6, 30))
TEST = (date(2021, 8, 2), date(2022, 6, 30))
FEATURES = [{"feature": "x1", "available_from_lag_days": 0, "source": "prices"},
            {"feature": "x2", "available_from_lag_days": 0, "source": "fundamentals"}]


def c01():
    parts = classifier_case(11, 1500, 400, 1000, train_range=TRAIN, val_range=VAL, test_range=TEST)
    tr, te = parts["train"], parts["test"]
    a_tr, a_te = auc(tr["prob"], tr["y"]), auc(te["prob"], te["y"])
    assert (a_tr - 0.5 - (a_te - 0.5)) / (a_tr - 0.5) < 0.08, (a_tr, a_te)
    assert ece(te["prob"], te["y"]) < 0.04
    assert psi(tr["prob"], te["prob"]) < 0.05
    assert abs(te["prob"].mean() - te["y"].mean()) < 1.5 * math.sqrt(te["y"].mean() * (1 - te["y"].mean()) / te["y"].size)
    assert abs(tr["y"].mean() - te["y"].mean()) < 0.04
    samples, preds, fvals = to_tables(parts)
    val_ids = {r["sample_id"] for r in parts["validation"]["rows"]}
    fvals = [v for v in fvals if v["sample_id"] not in val_ids]  # keep the file small: train + test only
    write("01_clean_purged", samples, preds, FEATURES, fvals,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_split_leakage", "PASS"), must("ml_overfit_gap", "INFO"),
                                     must("ml_calibration", "PASS"), must("ml_population_stability", "INFO"),
                                     must("ml_target_leakage", "PASS"), must("ml_evaluation_protocol", "INFO")],
                    "must_not_include": no_alerts(), "errors_only_from": [],
                    "comment": f"honest calibrated model, train AUC {a_tr:.3f}, test AUC {a_te:.3f}"},
          description="Temporal split with label_end and a 10-day embargo respected; calibrated honest classifier; "
                      "features with zero availability lag. Nothing may alert.")


def c02():
    # test timestamps drawn inside the training window (a random split of a time series)
    parts = classifier_case(22, 1200, 0, 500, train_range=TRAIN, val_range=VAL, test_range=(date(2019, 1, 2), date(2019, 12, 31)))
    samples, preds, _ = to_tables(parts)
    write("02_temporal_overlap", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_split_leakage", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("ml_split_leakage", "PASS")], "errors_only_from": ["ml_split_leakage"],
                    "text_must_contain": [{"check": "ml_split_leakage", "text": "inside the training window"}]},
          description="500 test samples dated inside the 2018-2020 training window (random split of a time series).")


def c03():
    # training timestamps do not overlap the test, but the label windows (20 days) run past the first test date
    parts = classifier_case(33, 1200, 0, 500, train_range=(date(2018, 1, 2), date(2021, 1, 29)), val_range=VAL,
                            test_range=(date(2021, 2, 1), date(2021, 12, 31)))
    samples, preds, _ = to_tables(parts)
    late = [r for r in parts["train"]["rows"] if r["label_end"] > "2021-02-01"]
    assert len(late) >= 5, len(late)
    write("03_label_leak_no_purge", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_split_leakage", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("ml_split_leakage", "PASS")], "errors_only_from": ["ml_split_leakage"],
                    "text_must_contain": [{"check": "ml_split_leakage", "text": "purging"}]},
          description="Training samples end on 2021-01-29 and the test starts on 2021-02-01, but the 20-day label window of "
                      f"the last {len(late)} training samples reaches into the test period (no purging): looks clean by "
                      "timestamp, leaks by label.")


def c04():
    parts = classifier_case(44, 1200, 0, 500, train_range=TRAIN, val_range=VAL, test_range=TEST)
    samples, preds, _ = to_tables(parts)
    train_ids = [r["sample_id"] for r in parts["train"]["rows"]][:30]
    for r, sid in zip(parts["test"]["rows"][:30], train_ids):
        r["sample_id"] = sid  # the same id in both splits (the test rows keep their test dates)
    for p, sid in zip(preds[len(parts["train"]["rows"]):][:30], train_ids):
        p["sample_id"] = sid
    write("04_duplicate_ids", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_split_leakage", "CONFIRMED_ERROR")],
                    "must_not_include": [mustnot("ml_split_leakage", "PASS")], "errors_only_from": ["ml_split_leakage"],
                    "text_must_contain": [{"check": "ml_split_leakage", "text": "more than one split"}]},
          description="30 sample ids appear both in the training and in the test split.")


def c05():
    def overfit(split, x1, x2, p, y, rng):
        if split == "train":  # memorised labels: probability tracks y with little noise
            return np.clip(0.15 + 0.7 * y + rng.normal(0, 0.12, y.size), 0.01, 0.99)
        return np.clip(rng.normal(0.5, 0.15, y.size) + 0.01 * (2 * y - 1), 0.01, 0.99)  # near random out of sample
    parts = classifier_case(55, 1200, 300, 600, train_range=TRAIN, val_range=VAL, test_range=TEST, model_prob=overfit)
    a_tr, a_te = auc(parts["train"]["prob"], parts["train"]["y"]), auc(parts["test"]["prob"], parts["test"]["y"])
    assert a_tr > 0.92 and a_te < 0.58, (a_tr, a_te)
    samples, preds, _ = to_tables(parts)
    write("05_overfit", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_overfit_gap", "NEEDS_REVIEW"), must("ml_split_leakage", "PASS")],
                    "must_not_include": [mustnot("ml_overfit_gap", "INFO"), mustnot("ml_overfit_gap", "PASS")],
                    "errors_only_from": [],
                    "comment": f"train AUC {a_tr:.3f}, test AUC {a_te:.3f}"},
          description="Clean temporal split; the model memorised the training labels (AUC ~0.95) and is random on the "
                      "test split (AUC ~0.52).")


def c06():
    # covariate shift: x1 ~ N(1, 1) in test; the model stays calibrated (it reports the true probability)
    parts = classifier_case(66, 1200, 300, 600, train_range=TRAIN, val_range=VAL, test_range=TEST, test_x_mean=1.2)
    v = psi(parts["train"]["prob"], parts["test"]["prob"])
    assert v > 0.25, v
    assert_no_gap(parts)
    samples, preds, fvals = to_tables(parts)
    write("06_drift", samples, preds, FEATURES, fvals,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_population_stability", "NEEDS_REVIEW"), must("ml_split_leakage", "PASS")],
                    "must_not_include": [mustnot("ml_population_stability", "INFO")], "errors_only_from": [],
                    "comment": f"PSI of the score computed by the generator: {v:.3f} (> 0.25, high priority)"},
          description="Covariate shift: the main feature moves by 1.2 standard deviations in the test split, so the score "
                      "distribution and the base rate shift (PSI > 0.25). Not an error of the model, but a review item.")


def c07():
    parts = classifier_case(77, 1000, 0, 300, train_range=TRAIN, val_range=VAL, test_range=TEST)
    assert_no_gap(parts)
    samples, preds, fvals = to_tables(parts)
    rng = np.random.default_rng(777)
    for sp, d in parts.items():
        noise = rng.normal(0, 0.05, d["y"].size)
        leak = d["y"] + noise
        if sp == "train":
            assert leak[d["y"] == 1].min() > leak[d["y"] == 0].max()  # perfect separation on train
        fvals += [{"sample_id": r["sample_id"], "feature": "x3", "value": fmt(leak[i])} for i, r in enumerate(d["rows"])]
    feats = FEATURES + [{"feature": "x3", "available_from_lag_days": 0, "source": "vendor"}]
    write("07_target_leak_feature", samples, preds, feats, fvals,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_target_leakage", "NEEDS_REVIEW"), must("ml_split_leakage", "PASS")],
                    "must_not_include": [mustnot("ml_target_leakage", "PASS"), mustnot("ml_target_leakage", "CONFIRMED_ERROR")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "ml_target_leakage", "text": "x3"}]},
          description="Feature x3 equals the label plus N(0, 0.05) noise: it separates the classes perfectly on the training "
                      "split. The name gives nothing away. Must be NEEDS_REVIEW (high), not CONFIRMED_ERROR.")


def c08():
    def squeeze(split, x1, x2, p, y, rng):
        return 0.5 + 0.1 * (p - 0.5)
    parts = classifier_case(89, 1200, 300, 600, train_range=TRAIN, val_range=VAL, test_range=TEST, model_prob=squeeze)
    e = ece(parts["test"]["prob"], parts["test"]["y"])
    assert e > 0.10, e
    assert_no_gap(parts)
    samples, preds, _ = to_tables(parts)
    write("08_miscalibrated", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_calibration", "NEEDS_REVIEW"), must("ml_split_leakage", "PASS")],
                    "must_not_include": [mustnot("ml_calibration", "PASS")], "errors_only_from": [],
                    "comment": f"ECE computed by the generator: {e:.3f}"},
          description="Probabilities squeezed to 0.45-0.55 (ranking intact, AUC unchanged) so the reliability curve is flat: "
                      "ECE far above 0.05.")


def c09():
    parts = classifier_case(99, 500, 0, 300, train_range=TRAIN, val_range=VAL, test_range=TEST)
    assert_no_gap(parts)
    samples, preds = [], []
    rng = np.random.default_rng(999)
    for d in parts.values():
        samples += d["rows"]
    for m in range(1, 7):
        for d in parts.values():
            prob = np.clip(d["prob"] + rng.normal(0, 0.02, d["prob"].size), 0.01, 0.99)
            for i, r in enumerate(d["rows"]):
                preds.append({"sample_id": r["sample_id"], "prediction": int(prob[i] >= 0.5), "actual": int(d["y"][i]),
                              "probability": fmt(prob[i]), "model": f"gbm_v{m}"})
    write("09_many_models_one_test", samples, preds, rules="research:\n  n_trials: 6\n",
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_evaluation_protocol", "NEEDS_REVIEW"), must("ml_split_leakage", "PASS")],
                    "must_not_include": [mustnot("ml_evaluation_protocol", "INFO")], "errors_only_from": [],
                    "text_must_contain": [{"check": "ml_evaluation_protocol", "text": "6 models"}]},
          description="Six model versions scored on the same single test split (the holdout was reused for selection).")


def c10():
    parts = classifier_case(1010, 600, 0, 50, train_range=TRAIN, val_range=VAL, test_range=TEST)
    samples, preds, _ = to_tables(parts)
    write("10_insufficient", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_overfit_gap", "NOT_EXECUTABLE"), must("ml_calibration", "NOT_EXECUTABLE"),
                                     must("ml_population_stability", "NOT_EXECUTABLE")],
                    "must_not_include": [mustnot("ml_overfit_gap", "PASS"), mustnot("ml_overfit_gap", "INFO"),
                                         mustnot("ml_calibration", "PASS"), mustnot("ml_population_stability", "INFO")],
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "ml_overfit_gap", "text": "50"}]},
          description="Only 50 test samples: the metric checks must say NOT_EXECUTABLE (and how many rows there are), never "
                      "PASS or INFO.")


def c11():
    rng = np.random.default_rng(1111)
    samples, preds, fvals = [], [], []
    offset = 0
    parts = {}
    for split, n, rg in (("train", 1200, TRAIN), ("validation", 300, VAL), ("test", 600, TEST)):
        rows = block(rng, n, rg[0], rg[1], split, "r", offset)
        offset += n
        x1 = rng.normal(0, 1, n)
        x2 = rng.normal(0, 1, n)
        actual = 0.02 * x1 + 0.005 * x2 + rng.normal(0, 0.02, n)
        pred = 0.02 * x1 + 0.005 * x2  # the true conditional mean: honest
        parts[split] = (pred, actual)
        samples += rows
        for i, r in enumerate(rows):
            preds.append({"sample_id": r["sample_id"], "prediction": fmt(pred[i]), "actual": fmt(actual[i])})
            fvals += [{"sample_id": r["sample_id"], "feature": "x1", "value": fmt(x1[i])}]
    r_tr, r_te = r2(*parts["train"]), r2(*parts["test"])
    assert r_tr > 0 and r_te > 0 and (r_tr - r_te) / r_tr < 0.08, (r_tr, r_te)
    write("11_regression_clean", samples, preds, [FEATURES[0]], fvals,
          expected={"profile": "ml_regression",
                    "must_include": [must("ml_overfit_gap", "INFO"), must("ml_calibration", "NOT_EXECUTABLE"),
                                     must("ml_split_leakage", "PASS"), must("ml_target_leakage", "PASS")],
                    "must_not_include": no_alerts(), "errors_only_from": [],
                    "text_must_contain": [{"check": "ml_calibration", "text": "calibration applies to probabilistic classifiers"}],
                    "comment": f"R2 train {r_tr:.3f}, test {r_te:.3f}"},
          description="Honest return-forecast regression (prediction = true conditional mean) on a clean temporal split; "
                      "the overfit gap is an INFO table and calibration is not applicable.")


def c12():
    """Purged 5-fold: each test block lies inside the overall sample range (looks like temporal overlap to a naive
    check) but the training rows of each fold exclude every sample whose label window touches the block, plus the
    embargo after it."""
    rng = np.random.default_rng(1212)
    n = 800
    days = weekdays(date(2018, 1, 2), date(2022, 12, 30))
    ts = sorted(rng.choice(len(days), n, replace=True))
    base = []
    for i, k in enumerate(ts):
        d = days[k]
        base.append({"sample_id": f"k{i + 1:06d}", "timestamp": d, "label_end": d + timedelta(days=HORIZON),
                     "ticker": TICKERS[int(rng.integers(len(TICKERS)))]})
    x1, x2, p, y = dgp(rng, n)
    edges = [date(2018, 1, 1), date(2019, 1, 1), date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1), date(2023, 1, 1)]
    samples, preds = [], []
    for k in range(5):
        t0, t1 = edges[k], edges[k + 1] - timedelta(days=1)
        test = [b for b in base if t0 <= b["timestamp"] <= t1]
        te_end = max(b["label_end"] for b in test)
        te_start = min(b["timestamp"] for b in test)
        for b in base:
            if b in test:
                split = "test"
            elif b["label_end"] < te_start or b["timestamp"] > te_end + timedelta(days=EMBARGO):
                split = "train"
            else:
                continue  # purged or embargoed
            samples.append({"sample_id": b["sample_id"], "timestamp": b["timestamp"].isoformat(),
                            "label_end": b["label_end"].isoformat(), "split": split, "ticker": b["ticker"], "fold": k + 1})
            i = int(b["sample_id"][1:]) - 1
            preds.append({"sample_id": b["sample_id"], "prediction": int(p[i] >= 0.5), "actual": int(y[i]),
                          "probability": fmt(p[i]), "fold": k + 1})
    assert len(samples) < 5000, len(samples)
    write("12_purged_kfold_legit", samples, preds,
          expected={"profile": "ml_classification",
                    "must_include": [must("ml_split_leakage", "PASS")],
                    "must_not_include": no_alerts(exclude=("ml_overfit_gap", "ml_calibration", "ml_population_stability")),
                    "errors_only_from": [],
                    "text_must_contain": [{"check": "ml_split_leakage", "text": "K-fold"}]},
          description="Adversarial: purged 5-fold cross-validation with a 10-day embargo. Every test block sits inside the "
                      "overall training range, so a naive window check would scream; compared per fold it is legitimate "
                      "and must PASS.")


def main():
    OUT.mkdir(exist_ok=True)
    for fn in (c01, c02, c03, c04, c05, c06, c07, c08, c09, c10, c11, c12):
        fn()
        print("wrote", fn.__name__)


if __name__ == "__main__":
    main()
