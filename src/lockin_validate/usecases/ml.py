"""Use case ``ml``: validation of a supervised machine-learning model used in finance.

Return prediction, default / credit scoring, classification of events. The audience is the data scientist who
built the model and the model-risk team that validates it (SR 11-7 style: conceptual soundness, outcomes
analysis, ongoing monitoring). The module never refits the model: it validates the sampling protocol and the
delivered predictions.

Inputs (all optional for the package; each check says what it needs):

  ml_samples.csv         sample_id, timestamp, split [label_end, ticker, fold]
  ml_predictions.csv     sample_id, prediction, actual [probability, model, fold]
  ml_features.csv        feature [available_from_lag_days, source, importance]
  ml_feature_values.csv  sample_id, feature, value   (long format; used for PSI and the target-leak test)

Checks: ml_split_leakage, ml_overfit_gap, ml_calibration, ml_population_stability, ml_target_leakage,
ml_evaluation_protocol. Statistics are implemented here from the published formulas (numpy + pandas only):
rank AUC (Mann-Whitney) with the Hanley-McNeil standard error, KS, Gini, log-loss, Brier and its Murphy
decomposition, ECE on quantile bins, PSI, Spearman, two-proportion z and Welch t tests.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from ..checks import missing_inputs, not_executable
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, NOT_EXECUTABLE, PASS, AuditResult
from . import UseCase, register

NAME = "ml"
_N = NormalDist()
EPS = 1e-15

SPLITS = {"train": "train", "training": "train", "fit": "train", "in_sample": "train", "is": "train",
          "learn": "train", "learning": "train",
          "validation": "validation", "val": "validation", "valid": "validation", "dev": "validation",
          "development": "validation", "tuning": "validation",
          "test": "test", "testing": "test", "oos": "test", "holdout": "test", "hold_out": "test",
          "out_of_sample": "test", "oot": "test"}
LEAK_NAME_PATTERNS = ("target", "label", "future", "fwd", "next")


# ---------------------------------------------------------------------------- statistics

def rankdata(a) -> np.ndarray:
    """Average ranks (1-based), ties share the mean rank."""
    a = np.asarray(a, dtype=float)
    fin = np.isfinite(a)
    if not fin.all():  # NaN would sort last and be ranked as the best score: rank the finite values, NaN stays NaN
        out = np.full(a.size, np.nan)
        out[fin] = rankdata(a[fin])
        return out
    n = a.size
    order = np.argsort(a, kind="mergesort")
    s = a[order]
    ranks = np.empty(n)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and s[j + 1] == s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auc(score, y) -> float:
    """Rank AUC = Mann-Whitney U / (n1 n0), ties counted one half."""
    score = np.asarray(score, dtype=float)
    y = np.asarray(y, dtype=int)
    keep = np.isfinite(score)  # a blank score is never ranked (NaN would sort above every real score)
    score, y = score[keep], y[keep]
    n1 = int((y == 1).sum())
    n0 = int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(score)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def auc_se(a: float, n1: int, n0: int) -> float:
    """Hanley and McNeil (1982) standard error of the AUC."""
    if not math.isfinite(a) or n1 == 0 or n0 == 0:
        return float("nan")
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    v = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)
    return math.sqrt(max(v, 0.0))


def ks_statistic(score, y) -> float:
    score = np.asarray(score, dtype=float)
    y = np.asarray(y, dtype=int)
    keep = np.isfinite(score)
    score, y = score[keep], y[keep]
    n1 = int((y == 1).sum())
    n0 = int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ys = y[order]
    c1 = np.cumsum(ys == 1) / n1
    c0 = np.cumsum(ys == 0) / n0
    # evaluate only at the last index of each tied block
    s = score[order]
    last = np.r_[s[1:] != s[:-1], True]
    return float(np.max(np.abs(c1[last] - c0[last])))


def spearman(x, y) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return float("nan")
    rx, ry = rankdata(x[ok]), rankdata(y[ok])
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y) -> float:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def regression_metrics(pred, actual) -> dict[str, float]:
    pred = np.asarray(pred, dtype=float)
    actual = np.asarray(actual, dtype=float)
    err = actual - pred
    sst = float(((actual - actual.mean()) ** 2).sum())
    r2 = 1 - float((err ** 2).sum()) / sst if sst > 0 else float("nan")
    return {"r2": r2, "rmse": float(math.sqrt(np.mean(err ** 2))), "mae": float(np.mean(np.abs(err))),
            "spearman_ic": spearman(pred, actual), "n": int(actual.size)}


def classification_metrics(score, y, prob=None, pred_class=None) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    a = auc(score, y)
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    out: dict[str, float] = {"auc": a, "auc_se": auc_se(a, n1, n0), "gini": 2 * a - 1 if math.isfinite(a) else float("nan"),
                             "ks": ks_statistic(score, y), "n": int(y.size), "n_positive": n1,
                             "base_rate": n1 / y.size if y.size else float("nan")}
    if pred_class is not None:
        out["accuracy"] = float(np.mean(np.asarray(pred_class, dtype=int) == y))
    if prob is not None:
        out["log_loss"] = log_loss(prob, y)
        out["brier"] = brier(prob, y)
    return out


def quantile_edges(ref, bins: int) -> np.ndarray:
    """Inner edges of ``bins`` quantile bins defined on ``ref`` (duplicates removed)."""
    ref = np.asarray(ref, dtype=float)
    qs = np.quantile(ref, np.linspace(0, 1, bins + 1)[1:-1])
    return np.unique(qs)


def bin_index(x, inner_edges) -> np.ndarray:
    return np.searchsorted(np.asarray(inner_edges, dtype=float), np.asarray(x, dtype=float), side="right")


def psi(ref, cur, bins: int = 10, floor: float = 1e-4) -> dict[str, Any]:
    """Population Stability Index: sum (a - e) ln(a / e) over quantile bins of ``ref`` (Siddiqi 2006)."""
    ref = np.asarray(ref, dtype=float)
    cur = np.asarray(cur, dtype=float)
    ref = ref[np.isfinite(ref)]
    cur = cur[np.isfinite(cur)]
    if ref.size < bins or cur.size < bins:
        return {"psi": float("nan"), "bins": 0, "table": []}
    edges = quantile_edges(ref, bins)
    k = edges.size + 1
    e = np.bincount(bin_index(ref, edges), minlength=k) / ref.size
    a = np.bincount(bin_index(cur, edges), minlength=k) / cur.size
    e2, a2 = np.maximum(e, floor), np.maximum(a, floor)
    contrib = (a2 - e2) * np.log(a2 / e2)
    table = [{"bin": i + 1, "expected_share": round(float(e[i]), 4), "actual_share": round(float(a[i]), 4),
              "contribution": round(float(contrib[i]), 4)} for i in range(k)]
    return {"psi": float(contrib.sum()), "bins": int(k), "table": table}


def reliability(p, y, bins: int) -> dict[str, Any]:
    """Reliability table on quantile bins of p; ECE (Guo et al. 2017) and the Murphy decomposition of the Brier score."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    edges = quantile_edges(p, bins)
    idx = bin_index(p, edges)
    k = edges.size + 1
    n = p.size
    obar = float(y.mean())
    rows, ece, rel, resol, hl = [], 0.0, 0.0, 0.0, 0.0
    for b in range(k):
        m = idx == b
        nb = int(m.sum())
        if nb == 0:
            continue
        mp, ob = float(p[m].mean()), float(y[m].mean())
        ece += nb / n * abs(mp - ob)
        rel += nb / n * (mp - ob) ** 2
        resol += nb / n * (ob - obar) ** 2
        exp_b = float(p[m].sum())
        if 0 < exp_b < nb:
            hl += (nb * ob - exp_b) ** 2 / (exp_b * (1 - exp_b / nb))
        rows.append({"bin": b + 1, "n": nb, "mean_probability": round(mp, 4), "observed_rate": round(ob, 4),
                     "gap": round(mp - ob, 4)})
    unc = obar * (1 - obar)
    df = max(len(rows) - 2, 1)
    return {"ece": float(ece), "table": rows, "reliability": float(rel), "resolution": float(resol),
            "uncertainty": float(unc), "brier": brier(p, y), "n_bins": len(rows),
            "hl_statistic": float(hl), "hl_df": df, "hl_p_value": chi2_sf(hl, df)}


def chi2_sf(x: float, df: int) -> float:
    """Upper tail of a chi-square with ``df`` degrees of freedom (Wilson-Hilferty normal approximation)."""
    if not math.isfinite(x) or x <= 0:
        return 1.0
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return float(1 - _N.cdf(z))


def two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    p1, p2 = k1 / n1, k2 / n2
    pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    return z, 2 * (1 - _N.cdf(abs(z)))


def welch_t(a, b) -> tuple[float, float]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 3 or b.size < 3:
        return float("nan"), float("nan")
    se = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    if se == 0:
        return 0.0, 1.0
    t = (a.mean() - b.mean()) / se
    return float(t), 2 * (1 - _N.cdf(abs(t)))  # normal approximation (large samples)


# ---------------------------------------------------------------------------- tables

def norm_split(x: Any) -> str | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip().lower().replace("-", "_").replace(" ", "_")
    return SPLITS.get(s)


def _ids(s: pd.Series) -> list[str | None]:
    return [None if x is None or (isinstance(x, float) and math.isnan(x)) else str(x).strip() for x in s]


def samples_table(pkg: Any) -> tuple[pd.DataFrame | None, list[str]]:
    """Normalised ml_samples: trimmed ids, canonical split (rows with an unknown split are dropped and listed)."""
    df = pkg.df("ml_samples")
    if df is None:
        return None, []
    d = df.copy()
    d["sample_id"] = _ids(d["sample_id"])
    raw = list(d["split"])
    d["split"] = [norm_split(x) for x in raw]
    unknown = sorted({str(r) for r, s in zip(raw, d["split"]) if s is None and r is not None})
    d = d.dropna(subset=["sample_id", "split"])
    if "fold" in d.columns:
        d["fold"] = _ids(d["fold"])
    return d, unknown


def predictions_table(pkg: Any) -> pd.DataFrame | None:
    df = pkg.df("ml_predictions")
    if df is None:
        return None
    d = df.copy()
    d["sample_id"] = _ids(d["sample_id"])
    d = d.dropna(subset=["sample_id"])
    d["model"] = [x if x is not None else "model" for x in (_ids(d["model"]) if "model" in d.columns
                                                           else [None] * len(d))]
    if "fold" in d.columns:
        d["fold"] = _ids(d["fold"])
    if "probability" not in d.columns:
        d["probability"] = np.nan
    return d


def joined(pkg: Any) -> pd.DataFrame | None:
    """Predictions joined to their sample (split, timestamp). Keys: sample_id, plus fold when both tables have it."""
    s, _ = samples_table(pkg)
    p = predictions_table(pkg)
    if s is None or p is None:
        return None
    keys = ["sample_id"]
    if "fold" in s.columns and "fold" in p.columns and s["fold"].notna().any() and p["fold"].notna().any():
        keys.append("fold")
    cols = [c for c in ("sample_id", "fold", "split", "timestamp", "row") if c in s.columns]
    s2 = s[cols].rename(columns={"row": "sample_row"}).drop_duplicates(keys)
    j = p.merge(s2, on=keys, how="inner")
    # rows with a blank probability are dropped where the model delivers probabilities, so that AUC, calibration and
    # PSI all use the same cleaned n; the count is kept in j.attrs and disclosed in the findings
    dropped = 0
    if "probability" in j.columns and len(j):
        prob = pd.to_numeric(j["probability"], errors="coerce")
        j["probability"] = prob
        has = prob.groupby(j["model"]).transform(lambda x: x.notna().any())
        bad = prob.isna() & has
        dropped = int(bad.sum())
        j = j[~bad].copy()
    j.attrs["dropped_blank_probability"] = dropped
    return j


def _dropped_note(j: pd.DataFrame) -> str:
    n = int(j.attrs.get("dropped_blank_probability", 0) or 0)
    return (f" {n} rows with a blank probability were excluded from every metric of this module." if n else "")


def task_of(pkg: Any, actual: pd.Series) -> str:
    t = str(pkg.conv("ml_task", "auto") or "auto").strip().lower()
    if t in ("classification", "regression"):
        return t
    vals = pd.Series(actual).dropna().unique()
    return "classification" if len(vals) == 2 else "regression"


def binarise(actual: pd.Series) -> np.ndarray:
    a = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    vals = np.unique(a[np.isfinite(a)])
    if vals.size == 2:
        return (a == vals.max()).astype(int)
    return (a > 0.5).astype(int)


def score_of(j: pd.DataFrame) -> tuple[np.ndarray, str]:
    """Ranking score for a classifier: the probability when delivered, else the prediction."""
    if "probability" in j.columns and j["probability"].notna().any():
        return j["probability"].to_numpy(dtype=float), "probability"
    return j["prediction"].to_numpy(dtype=float), "prediction"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _ne(res: AuditResult, cid: str, title: str, reason: str, action: str = "") -> None:
    """NOT_EXECUTABLE with the reason repeated in the detail so the report text carries it."""
    res.add(cid, NAME, NOT_EXECUTABLE, title, reason, [], reason=reason, action=action)


def _date(x: Any) -> Any:
    try:
        return pd.Timestamp(x).date().isoformat()
    except Exception:  # pragma: no cover
        return None


def _fmt(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (round(v, 4) if isinstance(v, float) and math.isfinite(v) else (None if isinstance(v, float) else v))
            for k, v in d.items()}


# ---------------------------------------------------------------------------- check 1: split leakage

def check_split_leakage(pkg: Any, res: AuditResult) -> None:
    cid, title = "ml_split_leakage", "Split leakage (temporal overlap, purging, embargo, feature availability)"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    s, unknown = samples_table(pkg)
    s = s.dropna(subset=["timestamp"])
    if s is None or s.empty or (s["split"] == "train").sum() == 0 or (s["split"] == "test").sum() == 0:
        _ne(res, cid, title, "ml_samples.csv needs at least one train and one test sample with a "
                       "parseable timestamp" + (f" (unknown split values: {unknown[:5]})" if unknown else ""),
                       "Use split values train / validation / test.")
        return
    embargo = float(pkg.conv("ml_embargo_days", 0) or 0)
    has_label_end = "label_end" in s.columns and bool(s["label_end"].notna().any())
    errors: list[tuple[str, list[dict[str, Any]]]] = []
    reviews: list[tuple[str, list[dict[str, Any]]]] = []
    inputs = ["ml_samples"]

    kfold = ("fold" in s.columns and s["fold"].notna().any() and s["fold"].nunique() >= 2
             and all(set(g["split"]) >= {"train", "test"} for _, g in s.groupby("fold")))
    groups = list(s.groupby("fold")) if kfold else [("single", s)]

    # a) the same sample id in two splits (per fold in a K-fold: a sample is legitimately test in one fold and
    #    train in the others)
    dup_rows: list[dict[str, Any]] = []
    for fold, g in groups:
        multi = g.groupby("sample_id")["split"].nunique()
        for sid in multi[multi > 1].index:
            rows = g[g["sample_id"] == sid]
            dup_rows.append({"row": int(rows["row"].iloc[0]), "sample_id": sid, "splits": sorted(set(rows["split"])),
                             "rows": [int(r) for r in rows["row"]][:6], **({"fold": fold} if kfold else {})})
    if dup_rows:
        errors.append((f"{len(dup_rows)} sample ids appear in more than one split", dup_rows))

    # b) temporal checks
    overlap_rows: list[dict[str, Any]] = []
    val_overlap_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    val_label_rows: list[dict[str, Any]] = []
    embargo_rows: list[dict[str, Any]] = []
    for fold, g in groups:
        tr = g[g["split"] == "train"]
        te = g[g["split"] == "test"]
        va = g[g["split"] == "validation"]
        if tr.empty or te.empty:
            continue
        t_min, t_max = te["timestamp"].min(), te["timestamp"].max()
        if kfold:
            # purged K-fold (Lopez de Prado 2018, ch. 7): no training label window may intersect the test block
            te_end = te["label_end"].max() if has_label_end and te["label_end"].notna().any() else t_max
            tr_end = tr["label_end"] if has_label_end else tr["timestamp"]
            bad = tr[(tr_end.fillna(tr["timestamp"]) >= t_min) & (tr["timestamp"] <= te_end)]
            for r in bad.itertuples():
                label_rows.append({"row": int(r.row), "sample_id": r.sample_id, "fold": fold, "timestamp": _date(r.timestamp),
                                   "label_end": _date(getattr(r, "label_end", None)) if has_label_end else None,
                                   "test_block": [_date(t_min), _date(te_end)]})
            if embargo > 0:
                after = tr[(tr["timestamp"] > te_end) & (tr["timestamp"] <= te_end + pd.Timedelta(days=embargo))]
                for r in after.itertuples():
                    embargo_rows.append({"row": int(r.row), "sample_id": r.sample_id, "fold": fold,
                                         "timestamp": _date(r.timestamp), "test_block_end": _date(te_end),
                                         "gap_days": int((r.timestamp - te_end).days), "embargo_days": embargo})
        else:
            lo, hi = tr["timestamp"].min(), tr["timestamp"].max()
            for r in te[(te["timestamp"] >= lo) & (te["timestamp"] <= hi)].itertuples():
                overlap_rows.append({"row": int(r.row), "sample_id": r.sample_id, "timestamp": _date(r.timestamp),
                                     "train_window": [_date(lo), _date(hi)]})
            if not va.empty:
                for r in va[(va["timestamp"] >= lo) & (va["timestamp"] <= hi)].itertuples():
                    val_overlap_rows.append({"row": int(r.row), "sample_id": r.sample_id, "timestamp": _date(r.timestamp),
                                             "train_window": [_date(lo), _date(hi)]})
            if has_label_end:
                for r in tr[tr["label_end"] > t_min].itertuples():
                    label_rows.append({"row": int(r.row), "sample_id": r.sample_id, "timestamp": _date(r.timestamp),
                                       "label_end": _date(r.label_end), "first_test_timestamp": _date(t_min)})
                if not va.empty:
                    v_min = va["timestamp"].min()
                    for r in tr[tr["label_end"] > v_min].itertuples():
                        val_label_rows.append({"row": int(r.row), "sample_id": r.sample_id, "timestamp": _date(r.timestamp),
                                               "label_end": _date(r.label_end), "first_validation_timestamp": _date(v_min)})
                last_end = tr["label_end"].max()
                if pd.notna(last_end) and embargo > 0:
                    gap = (t_min - last_end).days
                    if 0 <= gap < embargo:
                        embargo_rows.append({"row": int(tr.loc[tr["label_end"].idxmax(), "row"]),
                                             "last_train_label_end": _date(last_end), "first_test_timestamp": _date(t_min),
                                             "gap_days": int(gap), "embargo_days": embargo})
    if overlap_rows:
        errors.append((f"{len(overlap_rows)} test samples have a timestamp inside the training window", overlap_rows))
    if label_rows:
        errors.append((f"{len(label_rows)} training samples have a label window that reaches into the test period "
                       "(no purging)" if not kfold else
                       f"{len(label_rows)} training samples overlap the test block of their fold (no purging)", label_rows))
    if val_overlap_rows:
        reviews.append((f"{len(val_overlap_rows)} validation samples lie inside the training window (model selection "
                        "on in-sample dates)", val_overlap_rows))
    if val_label_rows:
        reviews.append((f"{len(val_label_rows)} training labels reach into the validation period", val_label_rows))
    if embargo_rows:
        reviews.append((f"the declared embargo of {embargo:g} days is not respected", embargo_rows))

    # c) features known only after the sample timestamp
    f = pkg.df("ml_features")
    if f is not None and "available_from_lag_days" in f.columns:
        inputs.append("ml_features")
        late = f[f["available_from_lag_days"] > 0]
        if len(late):
            errors.append((f"{len(late)} features become known after the sample timestamp (available_from_lag_days > 0)",
                           [{"row": int(r.row), "feature": r.feature, "available_from_lag_days": float(r.available_from_lag_days)}
                            for r in late.itertuples()]))
    if not has_label_end:
        reviews.append(("ml_samples.csv has no label_end: purging (training labels that use test-period information) "
                        "cannot be verified", [{"row": int(s["row"].iloc[0]), "missing_column": "label_end"}]))
    if unknown:
        reviews.append((f"{len(unknown)} split values were not recognised and their rows were ignored",
                        [{"split": u} for u in unknown[:10]]))

    mode = (f"purged K-fold with {len(groups)} folds (train and test compared inside each fold)" if kfold
            else "single temporal split (train / validation / test)")
    proc = (f"{mode}. Duplicate ids: nunique(split) per sample_id. Temporal overlap: test timestamp inside "
            "[min, max] of the training timestamps. Purging: training label_end later than the first test "
            "timestamp (K-fold: training window [timestamp, label_end] intersecting the test block). Embargo: gap "
            f"between the last training label_end and the first test timestamp against ml_embargo_days = {embargo:g}. "
            "Feature availability: ml_features.available_from_lag_days > 0.")
    if errors:
        for msg, ev in errors:
            res.add(cid, NAME, CONFIRMED_ERROR, "Split leakage: " + msg,
                    "The test set contains information that was available to the model at training time, so the "
                    "test metrics are not out-of-sample. " + _cap(msg) + ".", ev, proc,
                    action="Rebuild the split: test strictly after the last training label_end plus the embargo, "
                           "one split per sample, features lagged to their publication date.",
                    priority="high", inputs=inputs)
    if reviews:
        for msg, ev in reviews:
            res.add(cid, NAME, NEEDS_REVIEW, "Split protocol to review: " + msg, _cap(msg) + ".", ev, proc,
                    action="Deliver label_end for every sample and respect the declared embargo.", priority="medium",
                    inputs=inputs)
    if not errors and not reviews:
        n_tr, n_te = int((s["split"] == "train").sum()), int((s["split"] == "test").sum())
        res.add(cid, NAME, PASS, "No split leakage detected",
                f"{_cap(mode)}. {n_tr} training and {n_te} test samples: no shared ids, no temporal overlap, every training label "
                f"ends before the first test timestamp, embargo of {embargo:g} days respected"
                + (", no feature declared with a positive availability lag" if f is not None else
                   "; feature availability not checked (no ml_features.csv)") + ".",
                [{"row": int(s["row"].iloc[0]), "mode": mode, "train": n_tr, "test": n_te}], proc, inputs=inputs)


# ---------------------------------------------------------------------------- check 2: overfit gap

def _split_metrics(j: pd.DataFrame, task: str) -> tuple[dict[str, dict[str, float]], str]:
    out: dict[str, dict[str, float]] = {}
    src = "prediction"
    for sp in ("train", "validation", "test"):
        g = j[j["split"] == sp]
        if g.empty:
            continue
        if task == "classification":
            y = binarise(g["actual"])
            score, src = score_of(g)
            prob = g["probability"].to_numpy(dtype=float) if g["probability"].notna().all() else None
            pred = g["prediction"].to_numpy(dtype=float)
            pred_class = (pred >= 0.5).astype(int) if np.isfinite(pred).all() else None
            out[sp] = classification_metrics(score, y, prob, pred_class)
        else:
            out[sp] = regression_metrics(g["prediction"].to_numpy(dtype=float), g["actual"].to_numpy(dtype=float))
    return out, src


def check_overfit_gap(pkg: Any, res: AuditResult) -> None:
    cid, title = "ml_overfit_gap", "Train / validation / test metric gap"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    j = joined(pkg)
    if j is None or j.empty:
        _ne(res, cid, title, "no prediction could be joined to a sample (sample_id mismatch)")
        return
    attrs = dict(j.attrs)
    j = j.dropna(subset=["prediction", "actual"])
    j.attrs.update(attrs)
    min_test = int(pkg.conv("ml_min_test_samples", 200))
    gap_max = float(pkg.conv("ml_overfit_gap_review", 0.10))
    task = task_of(pkg, j["actual"])
    n_test_total = int((j["split"] == "test").sum())
    n_train_total = int((j["split"] == "train").sum())
    if n_test_total < min_test:
        _ne(res, cid, title, f"the test split has {n_test_total} scored samples, fewer than "
                       f"ml_min_test_samples = {min_test}: a metric on so few rows does not discriminate",
                       "Deliver a larger test set or lower ml_min_test_samples with a justification.")
        return
    if n_train_total == 0:
        _ne(res, cid, title, "no training predictions delivered: the gap to the test metric cannot "
                       "be measured (see ml_evaluation_protocol)")
        return
    ev: list[dict[str, Any]] = []
    problems: list[str] = []
    summary: dict[str, Any] = {}
    undefined: list[str] = []
    for model, jm in j.groupby("model"):
        m, src = _split_metrics(jm, task)
        if "test" not in m or "train" not in m or m["test"]["n"] < min_test:
            continue
        for sp, d in m.items():
            ev.append({"model": model, "split": sp, **_fmt(d)})
        tr, te = m["train"], m["test"]
        if task == "classification" and not (math.isfinite(tr["auc"]) and math.isfinite(te["auc"])):
            undefined.append(f"{model}: AUC is undefined on the "
                             f"{'test' if not math.isfinite(te['auc']) else 'train'} split (only one class present: "
                             f"{te['n_positive']} positives of {te['n']} in test, {tr['n_positive']} of {tr['n']} in train)")
            continue
        if task == "classification":
            ex_tr, ex_te = tr["auc"] - 0.5, te["auc"] - 0.5
            rel = (ex_tr - ex_te) / ex_tr if ex_tr > 0 else float("nan")
            se_gap = math.sqrt(tr["auc_se"] ** 2 + te["auc_se"] ** 2) if math.isfinite(tr["auc_se"]) else float("nan")
            if math.isfinite(rel) and rel > gap_max and (not math.isfinite(se_gap) or ex_tr - ex_te > 2 * se_gap):
                problems.append(f"{model}: AUC falls from {tr['auc']:.3f} (train) to {te['auc']:.3f} (test), a "
                                f"{rel:.0%} drop of the excess over 0.5 (> {gap_max:.0%}) and more than 2 combined "
                                f"standard errors ({se_gap:.3f})")
            if math.isfinite(te["auc"]) and te["auc"] <= 0.5 + 2 * te["auc_se"]:
                problems.append(f"{model}: test AUC {te['auc']:.3f} is within 2 standard errors "
                                f"({te['auc_se']:.3f}, Hanley-McNeil) of the naive 0.5")
            summary[model] = {"metric": "auc", "train": tr["auc"], "test": te["auc"], "relative_drop": rel,
                              "test_se": te["auc_se"]}
        else:
            r_tr, r_te = tr["r2"], te["r2"]
            rel = (r_tr - r_te) / r_tr if math.isfinite(r_tr) and r_tr > 0 else float("nan")
            if math.isfinite(rel) and rel > gap_max:
                problems.append(f"{model}: R2 falls from {r_tr:.3f} (train) to {r_te:.3f} (test), a {rel:.0%} relative "
                                f"drop (> {gap_max:.0%})")
            if math.isfinite(r_te) and r_te <= 0:
                problems.append(f"{model}: test R2 {r_te:.3f} is at or below the mean baseline (R2 <= 0)")
            summary[model] = {"metric": "r2", "train": r_tr, "test": r_te, "relative_drop": rel,
                              "test_spearman_ic": te["spearman_ic"]}
    res.metrics[cid] = {"task": task, "models": summary, "undefined": undefined,
                        "dropped_blank_probability": int(j.attrs.get("dropped_blank_probability", 0))}
    if not summary and undefined:
        _ne(res, cid, title, "the gap cannot be measured: " + "; ".join(undefined),
            "Deliver a test split that contains both classes (a metric on one class is undefined).")
        return
    problems.extend(u + ": the train/test gap cannot be measured" for u in undefined)
    if not summary:
        _ne(res, cid, title, "no model has both a training split and a test split with at least "
                       f"{min_test} scored samples")
        return
    proc = (f"Task {task} (ml_task = {pkg.conv('ml_task', 'auto')}). Predictions joined to ml_samples by sample_id; "
            "metrics per split and model. Classification: rank AUC (Mann-Whitney), Hanley-McNeil SE, Gini = 2 AUC - 1, "
            "KS, accuracy at 0.5, log-loss and Brier when a probability is delivered; the ranking score is the "
            f"{'probability' if task == 'classification' else 'prediction'}. Regression: R2, RMSE, MAE, Spearman IC. "
            f"Review when the test metric loses more than {gap_max:.0%} of the training excess (AUC - 0.5, or R2) or "
            "sits at the naive baseline (AUC <= 0.5 + 2 SE, R2 <= 0); an AUC drop smaller than 2 combined Hanley-McNeil "
            "SE is sampling noise and is reported as INFO.")
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "Test performance far below training: " + problems[0],
                _cap("; ".join(problems)) + ". A large in-sample / out-of-sample gap is the signature of "
                "overfitting or of a leak that only exists in training (Arnott, Harvey and Markowitz 2019); a test "
                "metric at the naive baseline means the model has no demonstrated skill." + _dropped_note(j), ev, proc,
                action="Regularise or simplify the model, repeat the evaluation with purged cross-validation, and "
                       "report the test metric with its standard error.", priority="high",
                inputs=["ml_samples", "ml_predictions"])
    else:
        res.add(cid, NAME, INFO, "Train / validation / test metrics",
                "; ".join(f"{m}: {d['metric']} train {d['train']:.3f}, test {d['test']:.3f}"
                          + (f" (relative drop {d['relative_drop']:.0%})" if math.isfinite(d["relative_drop"]) else "")
                          for m, d in summary.items())
                + ". The gap is within the review threshold; this is a description, not a proof of generalisation."
                + _dropped_note(j),
                ev, proc, inputs=["ml_samples", "ml_predictions"])


# ---------------------------------------------------------------------------- check 3: calibration

def check_calibration(pkg: Any, res: AuditResult) -> None:
    cid, title = "ml_calibration", "Probability calibration"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    j = joined(pkg)
    if j is None or j.empty:
        _ne(res, cid, title, "no prediction could be joined to a sample (sample_id mismatch)")
        return
    attrs = dict(j.attrs)
    j = j.dropna(subset=["actual"])
    j.attrs.update(attrs)
    task = task_of(pkg, j["actual"])
    if task == "regression":
        _ne(res, cid, title, "calibration applies to probabilistic classifiers; for a regression it "
                       "would need prediction intervals, which this version does not support")
        return
    if not j["probability"].notna().any():
        _ne(res, cid, title, "ml_predictions.csv has no probability column: calibration needs the "
                       "predicted probability of the positive class", "Add a `probability` column.")
        return
    min_test = int(pkg.conv("ml_min_test_samples", 200))
    bins = int(pkg.conv("ml_calibration_bins", 10))
    ece_max = float(pkg.conv("ml_calibration_ece_review", 0.05))
    hl_p = float(pkg.conv("ml_calibration_hl_p", 0.01))
    notes: list[str] = []
    te = j[(j["split"] == "test") & j["probability"].notna()]
    tr = j[(j["split"] == "train") & j["probability"].notna()]
    if len(te) < min_test:
        _ne(res, cid, title, f"the test split has {len(te)} samples with a probability, fewer than "
                       f"ml_min_test_samples = {min_test}")
        return
    ev: list[dict[str, Any]] = []
    problems: list[str] = []
    summary: dict[str, Any] = {}
    for model, g in te.groupby("model"):
        if len(g) < min_test:
            continue
        p = np.clip(g["probability"].to_numpy(dtype=float), 0, 1)
        y = binarise(g["actual"])
        r = reliability(p, y, bins)
        base = float(y.mean())
        mean_p = float(p.mean())
        if 0 < base < 1:
            se = math.sqrt(base * (1 - base) / len(y))
        else:
            # observed rate is exactly 0 or 1: the binomial SE of the observed rate is 0, so use the SE of the mean
            # under the model itself, sqrt(sum p (1 - p)) / n
            se = math.sqrt(float((p * (1 - p)).sum())) / len(y)
            notes.append(f"{model}: the test base rate is {base:.0f}, so the SE of the mean probability is taken from the "
                         "predicted probabilities")
        g_tr = tr[tr["model"] == model]
        base_tr = float(binarise(g_tr["actual"]).mean()) if len(g_tr) else float("nan")
        for row in r["table"]:
            ev.append({"model": model, **row})
        ev.append({"model": model, "summary": True, "ece": round(r["ece"], 4), "brier": round(r["brier"], 4),
                   "hosmer_lemeshow": round(r["hl_statistic"], 3), "hl_p_value": round(r["hl_p_value"], 5),
                   "reliability": round(r["reliability"], 5), "resolution": round(r["resolution"], 5),
                   "uncertainty": round(r["uncertainty"], 5), "base_rate_test": round(base, 4),
                   "base_rate_train": round(base_tr, 4) if math.isfinite(base_tr) else None,
                   "mean_probability_test": round(mean_p, 4), "n_test": int(len(y))})
        summary[model] = {"ece": r["ece"], "brier": r["brier"], "base_rate_test": base, "base_rate_train": base_tr,
                          "mean_probability": mean_p, "n": int(len(y))}
        if r["ece"] > ece_max and r["hl_p_value"] < hl_p:
            problems.append(f"{model}: ECE {r['ece']:.3f} > {ece_max:.2f} on {r['n_bins']} quantile bins "
                            f"(Hosmer-Lemeshow p = {r['hl_p_value']:.4f})")
        elif r["ece"] > ece_max:
            notes.append(f"{model}: ECE {r['ece']:.3f} is above {ece_max:.2f} but the Hosmer-Lemeshow test does not "
                         f"reject calibration (p = {r['hl_p_value']:.3f}): with {len(y)} rows the ECE is biased upward")
        if not (math.isfinite(se) and math.isfinite(r["ece"])):
            problems.append(f"{model}: calibration statistics are not finite (SE {se}, ECE {r['ece']}), so calibration "
                            "cannot be confirmed")
        elif abs(mean_p - base) > 2 * se + 1e-12:
            problems.append(f"{model}: mean predicted probability {mean_p:.3f} differs from the test base rate "
                            f"{base:.3f} by more than 2 SE ({se:.4f})")
    res.metrics[cid] = summary
    if not summary:
        _ne(res, cid, title, f"no model has {min_test} test samples with a probability")
        return
    proc = (f"Test split, {bins} quantile bins of the predicted probability; ECE = sum n_b / N |mean p_b - observed "
            "rate_b| (Guo et al. 2017); Brier score (Brier 1950) decomposed into reliability, resolution and "
            "uncertainty (Murphy 1973; exact only when p is constant inside each bin); base rate in train and test; mean "
            "probability against the base rate with the binomial SE sqrt(p (1 - p) / N) (sqrt(sum p (1 - p)) / N when the base rate is 0 or 1). The ECE alert requires the "
            f"Hosmer-Lemeshow chi-square ({bins} - 2 df) to reject calibration at p < {hl_p:g}, because the ECE of a "
            "perfectly calibrated model is biased upward on a few hundred rows.")
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "Probabilities are not calibrated: " + problems[0],
                _cap("; ".join(problems)) + ". A miscalibrated score ranks but does not mean what it says: "
                "expected losses, thresholds and position sizes built on it are wrong even if the AUC is fine.", ev,
                proc, action="Recalibrate on the validation split (Platt scaling or isotonic regression) and report "
                             "the reliability table with the AUC.", priority="medium",
                inputs=["ml_samples", "ml_predictions"])
    else:
        res.add(cid, NAME, PASS, "Probabilities calibrated within the threshold",
                "; ".join(f"{m}: ECE {d['ece']:.3f}, Brier {d['brier']:.3f}, mean probability {d['mean_probability']:.3f} "
                          f"vs base rate {d['base_rate_test']:.3f} (n = {d['n']})" for m, d in summary.items())
                + f". ECE below {ece_max:.2f} (or not rejected by Hosmer-Lemeshow) and mean probability within 2 SE of "
                "the base rate on the test split." + (" " + "; ".join(notes) + "." if notes else "") + _dropped_note(j),
                ev, proc, inputs=["ml_samples", "ml_predictions"])


# ---------------------------------------------------------------------------- check 4: population stability

def check_population_stability(pkg: Any, res: AuditResult) -> None:
    cid, title = "ml_population_stability", "Population stability (PSI) and label shift"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    j = joined(pkg)
    if j is None or j.empty:
        _ne(res, cid, title, "no prediction could be joined to a sample (sample_id mismatch)")
        return
    min_test = int(pkg.conv("ml_min_test_samples", 200))
    p_rev = float(pkg.conv("ml_psi_review", 0.10))
    p_err = float(pkg.conv("ml_psi_error", 0.25))
    p_shift = float(pkg.conv("ml_label_shift_p", 0.01))
    tr = j[j["split"] == "train"]
    te = j[j["split"] == "test"]
    if len(te) < min_test or len(tr) < min_test:
        _ne(res, cid, title, f"train ({len(tr)}) or test ({len(te)}) has fewer than "
                       f"ml_min_test_samples = {min_test} scored samples; PSI on 10 bins needs more")
        return
    task = task_of(pkg, j["actual"])
    ev: list[dict[str, Any]] = []
    psis: dict[str, float] = {}
    inputs = ["ml_samples", "ml_predictions"]
    # prediction distribution
    if task == "classification":
        s_tr, src = score_of(tr)
        s_te, _ = score_of(te)
    else:
        s_tr, s_te, src = tr["prediction"].to_numpy(dtype=float), te["prediction"].to_numpy(dtype=float), "prediction"
    r = psi(s_tr, s_te, 10)
    psis[f"model {src}"] = r["psi"]
    ev.append({"variable": f"model {src}", "psi": round(r["psi"], 4), "bins": r["bins"], "n_train": int(len(tr)),
               "n_test": int(len(te))})
    # per-feature PSI
    fv = pkg.df("ml_feature_values")
    n_features = 0
    if fv is not None:
        inputs.append("ml_feature_values")
        f = fv.copy()
        f["sample_id"] = _ids(f["sample_id"])
        f = f.dropna(subset=["sample_id", "feature", "value"])
        s_all, _ = samples_table(pkg)
        split_of = s_all.drop_duplicates("sample_id").set_index("sample_id")["split"]
        f["split"] = f["sample_id"].map(split_of)
        for feat, g in f.groupby("feature"):
            a = g.loc[g["split"] == "train", "value"].to_numpy(dtype=float)
            b = g.loc[g["split"] == "test", "value"].to_numpy(dtype=float)
            if a.size < 10 or b.size < 10:
                continue
            rf = psi(a, b, 10)
            n_features += 1
            psis[f"feature {feat}"] = rf["psi"]
            ev.append({"row": int(g["row"].iloc[0]), "variable": f"feature {feat}", "psi": round(rf["psi"], 4),
                       "bins": rf["bins"], "n_train": int(a.size), "n_test": int(b.size)})
    # label shift
    a_tr = pd.to_numeric(tr["actual"], errors="coerce").dropna()
    a_te = pd.to_numeric(te["actual"], errors="coerce").dropna()
    shift_msg = None
    if task == "classification":
        y_tr, y_te = binarise(a_tr), binarise(a_te)
        z, pval = two_proportion_z(int(y_tr.sum()), int(y_tr.size), int(y_te.sum()), int(y_te.size))
        lab = {"variable": "label base rate", "train": round(float(y_tr.mean()), 4), "test": round(float(y_te.mean()), 4),
               "z": round(z, 3) if math.isfinite(z) else None, "p_value": round(pval, 5) if math.isfinite(pval) else None}
        if math.isfinite(pval) and pval < p_shift and abs(float(y_tr.mean()) - float(y_te.mean())) > 0.05:
            shift_msg = (f"the base rate moves from {y_tr.mean():.3f} (train) to {y_te.mean():.3f} (test), "
                         f"two-proportion z = {z:.2f}, p = {pval:.4f}")
    else:
        t, pval = welch_t(a_tr.to_numpy(dtype=float), a_te.to_numpy(dtype=float))
        sd = float(np.std(a_tr, ddof=1)) if len(a_tr) > 1 else float("nan")
        d = abs(float(a_tr.mean()) - float(a_te.mean())) / sd if sd and sd > 0 else float("nan")
        lab = {"variable": "label mean", "train": round(float(a_tr.mean()), 5), "test": round(float(a_te.mean()), 5),
               "welch_t": round(t, 3) if math.isfinite(t) else None, "p_value": round(pval, 5) if math.isfinite(pval) else None,
               "effect_size_d": round(d, 3) if math.isfinite(d) else None}
        if math.isfinite(pval) and pval < p_shift and math.isfinite(d) and d > 0.2:
            shift_msg = (f"the mean of actual moves from {a_tr.mean():.4f} (train) to {a_te.mean():.4f} (test), Welch "
                         f"t = {t:.2f}, p = {pval:.4f}, d = {d:.2f}")
    ev.append(lab)
    res.metrics[cid] = {"psi": psis, "label_shift": lab, "n_features": n_features}
    proc = ("PSI = sum (actual share - expected share) x ln(actual / expected) over 10 quantile bins defined on the "
            "training split (empty bins floored at 1e-4); computed for the model score"
            + (f" and {n_features} features" if n_features else " (no ml_feature_values.csv: features not checked)")
            + ". Label shift: two-proportion z test of the base rate (classification) or Welch t test of the mean "
            f"(regression), review when p < {p_shift:g} and the shift is material (> 5 pp or d > 0.2). Thresholds "
            f"{p_rev:g} / {p_err:g} are the credit-scoring convention (Siddiqi 2006), not a statistical test.")
    worst = max(psis.items(), key=lambda kv: kv[1] if math.isfinite(kv[1]) else -1)
    above = {k: v for k, v in psis.items() if math.isfinite(v) and v > p_rev}
    if above or shift_msg:
        high = any(v > p_err for v in above.values())
        msgs = [f"{k} PSI {v:.3f}" for k, v in sorted(above.items(), key=lambda kv: -kv[1])]
        if shift_msg:
            msgs.append(shift_msg)
        res.add(cid, NAME, NEEDS_REVIEW, "Population shift between train and test: " + msgs[0],
                _cap("; ".join(msgs)) + f". PSI above {p_err:g} is a major shift by the scorecard convention, "
                f"above {p_rev:g} a moderate one; drift is not an error of the model but the test metrics describe a "
                "population the model was not fitted on, and a scorecard is normally recalibrated or rebuilt.", ev,
                proc, action="Confirm the shift is genuine (regime, segment mix) and not a processing difference; "
                             "monitor PSI in production and recalibrate.", priority="high" if high else "medium",
                inputs=inputs)
    else:
        res.add(cid, NAME, INFO, "Population stable between train and test",
                f"Largest PSI {worst[1]:.3f} ({worst[0]}), below {p_rev:g}; label shift test p = "
                f"{lab.get('p_value')}. PSI is a convention, not a hypothesis test.", ev, proc, inputs=inputs)


# ---------------------------------------------------------------------------- check 5: target leakage

def check_target_leakage(pkg: Any, res: AuditResult) -> None:
    cid, title = "ml_target_leakage", "Target leakage in features"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    rho_max = float(pkg.conv("ml_leak_correlation", 0.95))
    inputs = ["ml_samples", "ml_predictions"]
    names: list[str] = []
    feats = pkg.df("ml_features")
    if feats is not None:
        inputs.append("ml_features")
        names = [str(x) for x in feats["feature"].dropna()]
    fv = pkg.df("ml_feature_values")
    if fv is not None:
        inputs.append("ml_feature_values")
        names = sorted(set(names) | {str(x) for x in fv["feature"].dropna()})
    name_rows = [{"feature": n, "pattern": next(p for p in LEAK_NAME_PATTERNS if p in n.lower())}
                 for n in names if any(p in n.lower() for p in LEAK_NAME_PATTERNS)]
    if name_rows:
        res.add(cid, NAME, INFO, f"{len(name_rows)} feature names suggest forward-looking information",
                "Names containing target / label / future / fwd / next are often, not always, built from the "
                "outcome; a name proves nothing, so this is a note for the reviewer.", name_rows,
                "Feature names matched case-insensitively against " + ", ".join(LEAK_NAME_PATTERNS) + ".",
                action="Confirm how each such feature is computed and when it is known.", priority="low", inputs=inputs)
    if fv is None:
        _ne(res, cid, title, "ml_feature_values.csv absent: the correlation of each feature with "
                       "the target on the training split cannot be computed", "Deliver ml_feature_values.csv (long "
                       "format sample_id, feature, value) for at least the training split.")
        return
    j = joined(pkg)
    if j is None or j.empty:
        _ne(res, cid, title, "no prediction could be joined to a sample (sample_id mismatch)")
        return
    tr = j[j["split"] == "train"].drop_duplicates("sample_id").set_index("sample_id")["actual"]
    tr = pd.to_numeric(tr, errors="coerce").dropna()
    if len(tr) < 30:
        _ne(res, cid, title, f"only {len(tr)} training samples with an actual value (30 needed)")
        return
    task = task_of(pkg, tr)
    f = fv.copy()
    f["sample_id"] = _ids(f["sample_id"])
    f = f.dropna(subset=["sample_id", "feature", "value"])
    f = f[f["sample_id"].isin(tr.index)]
    ev: list[dict[str, Any]] = []
    suspicious: list[str] = []
    n_tested = 0
    y_bin = binarise(tr) if task == "classification" else None
    for feat, g in f.groupby("feature"):
        g = g.drop_duplicates("sample_id")
        x = g["value"].to_numpy(dtype=float)
        y = tr.loc[g["sample_id"]].to_numpy(dtype=float)
        if x.size < 30:
            continue
        n_tested += 1
        rho = spearman(x, y)
        row: dict[str, Any] = {"row": int(g["row"].iloc[0]), "feature": feat, "n_train": int(x.size),
                               "spearman_with_actual": round(rho, 4) if math.isfinite(rho) else None}
        flag = math.isfinite(rho) and abs(rho) > rho_max
        if y_bin is not None:
            yb = pd.Series(y_bin, index=tr.index).loc[g["sample_id"]].to_numpy()
            x1, x0 = x[yb == 1], x[yb == 0]
            if x1.size and x0.size and np.isfinite(x).all():
                sep = bool(x1.min() > x0.max() or x1.max() < x0.min())
                row["perfectly_separates_classes"] = sep
                flag = flag or sep
        if flag:
            suspicious.append(f"{feat} (|rho| = {abs(rho):.3f}" + (", perfect separation" if row.get("perfectly_separates_classes")
                                                                  else "") + ")")
            ev.insert(0, row)
        else:
            ev.append(row)
    proc = (f"Training split, {n_tested} features with at least 30 values: Spearman rank correlation between the "
            f"feature and `actual` (threshold ml_leak_correlation = {rho_max:g})"
            + ("; perfect separation = the feature ranges of the two classes do not overlap" if y_bin is not None else "")
            + ".")
    if suspicious:
        res.add(cid, NAME, NEEDS_REVIEW, f"{len(suspicious)} features are almost a copy of the target: "
                + suspicious[0], _cap("; ".join(suspicious)) + ". A feature this close to the label on the "
                "training data is the signature of target leakage (Kaufman, Rosset and Perlich 2012): the feature was "
                "computed with the outcome or with information known only after it. It is NOT a CONFIRMED_ERROR "
                "because a legitimate feature can, rarely, be this predictive (e.g. a near-deterministic rule); the "
                "reviewer must trace how the feature is built and when it is known.", ev, proc,
                action="Trace the construction of each flagged feature; remove it or lag it to its availability "
                       "date and re-evaluate.", priority="high", inputs=inputs)
    elif n_tested:
        res.add(cid, NAME, PASS, "No feature mirrors the target",
                f"{n_tested} features tested on {len(tr)} training samples; the largest |Spearman| with the target is "
                f"{max((abs(r['spearman_with_actual'] or 0) for r in ev), default=0):.3f}, below {rho_max:g}"
                + (" and no feature separates the classes perfectly" if y_bin is not None else "") + ".",
                ev, proc, inputs=inputs)
    else:
        _ne(res, cid, title, "no feature has 30 values on training samples with an actual")


# ---------------------------------------------------------------------------- check 6: evaluation protocol

def check_evaluation_protocol(pkg: Any, res: AuditResult) -> None:
    cid, title = "ml_evaluation_protocol", "Evaluation protocol (models scored on the test split)"
    miss = pkg.missing(cid)
    if miss:
        missing_inputs(res, cid, NAME, title, miss)
        return
    j = joined(pkg)
    if j is None or j.empty:
        _ne(res, cid, title, "no prediction could be joined to a sample (sample_id mismatch)")
        return
    n_trials = None
    src = None
    if pkg.has_column("declared_results", "n_trials"):
        n_trials, src = pkg.declared.get("n_trials"), "declared_results.json n_trials"
    elif pkg.has_column("rules", "research.n_trials"):
        n_trials, src = pkg.rules["research"]["n_trials"], "rules.yaml research.n_trials"
    te = j[j["split"] == "test"]
    models_test = sorted(te["model"].dropna().unique())
    splits = {sp: int((j["split"] == sp).sum()) for sp in ("train", "validation", "test")}
    ev = [{"split": sp, "scored_samples": n, "models": sorted(j.loc[j["split"] == sp, "model"].unique())}
          for sp, n in splits.items()]
    ev.append({"n_models_on_test": len(models_test), "n_trials_declared": n_trials, "n_trials_source": src})
    res.metrics[cid] = {"n_models_on_test": len(models_test), "n_trials_declared": n_trials, "splits": splits}
    proc = ("Distinct values of ml_predictions.model among test-split rows; scored samples per split; number of "
            f"trials from {src or 'declared_results.json / rules.yaml (not declared)'}.")
    problems = []
    if len(models_test) > 1:
        problems.append(f"{len(models_test)} models were scored on the single test split")
    if splits["test"] and not splits["train"] and not splits["validation"]:
        problems.append("only test predictions were delivered (no train or validation): overfitting cannot be judged")
    if problems:
        res.add(cid, NAME, NEEDS_REVIEW, "Evaluation protocol: " + problems[0],
                _cap("; ".join(problems)) + ". A holdout that scores several candidates stops being a holdout: "
                "choosing the best of k on the test set is selection on the test set and the reported metric is "
                "biased upward (Dwork et al. 2015; Arnott, Harvey and Markowitz 2019)."
                + (f" {n_trials} trials declared ({src})." if n_trials is not None else
                   " The number of trials is not declared."), ev, proc,
                action="Select on the validation split and score the chosen model once on the test split; declare the "
                       "number of configurations tried.", priority="medium", inputs=["ml_samples", "ml_predictions"])
    else:
        res.add(cid, NAME, INFO, f"{len(models_test)} model evaluated on the test split",
                f"Scored samples: train {splits['train']}, validation {splits['validation']}, test {splits['test']}."
                + (f" {n_trials} trials declared ({src}); the test split should have been touched once." if n_trials
                   is not None else " Number of trials not declared (declared_results.json n_trials or rules.yaml "
                                     "research.n_trials)."), ev, proc, inputs=["ml_samples", "ml_predictions"])


# ---------------------------------------------------------------------------- run and spec

CHECKS = ((check_split_leakage, "ml_split_leakage"), (check_overfit_gap, "ml_overfit_gap"),
          (check_calibration, "ml_calibration"), (check_population_stability, "ml_population_stability"),
          (check_target_leakage, "ml_target_leakage"), (check_evaluation_protocol, "ml_evaluation_protocol"))


def run(pkg: Any, res: AuditResult) -> None:
    for fn, cid in CHECKS:
        try:
            fn(pkg, res)
        except Exception as e:  # never break the review
            not_executable(res, cid, NAME, cid, f"internal error {type(e).__name__}: {e}")


SPEC = UseCase(
    name=NAME,
    title="Machine-learning model validation",
    description="Validates a supervised model used in finance (return prediction, default or credit scoring, event "
                "classification) from its sampling protocol and delivered predictions: split leakage (temporal "
                "overlap, purging, embargo, feature availability), train / test metric gap, probability calibration, "
                "population stability, target leakage in features and the evaluation protocol. The model is never "
                "refitted.",
    audience="data scientists and model-risk teams (SR 11-7 validation)",
    detect_files=["ml_samples", "ml_predictions"],
    files={"ml_samples": "ml_samples.csv", "ml_predictions": "ml_predictions.csv", "ml_features": "ml_features.csv",
           "ml_feature_values": "ml_feature_values.csv"},
    schema={"ml_samples": {"required": ["sample_id", "timestamp", "split"], "optional": ["label_end", "ticker", "fold"]},
            "ml_predictions": {"required": ["sample_id", "prediction", "actual"], "optional": ["probability", "model", "fold"]},
            "ml_features": {"required": ["feature"], "optional": ["available_from_lag_days", "source", "importance"]},
            "ml_feature_values": {"required": ["sample_id", "feature", "value"], "optional": []}},
    aliases={"ml_samples": {"sample_id": ["id", "obs_id", "observation_id", "row_id", "sample"],
                            "timestamp": ["date", "datetime", "time", "as_of", "decision_time"],
                            "split": ["set", "partition", "subset", "dataset", "role"],
                            "label_end": ["label_time", "label_date", "label_available", "target_end", "horizon_end",
                                          "t1", "end_time"],
                            "ticker": ["entity", "symbol", "asset", "instrument"], "fold": ["cv_fold", "k", "fold_id"]},
             "ml_predictions": {"sample_id": ["id", "obs_id", "observation_id", "row_id", "sample"],
                                "prediction": ["pred", "y_pred", "predicted", "y_hat", "yhat", "forecast"],
                                "actual": ["y", "y_true", "target", "label", "truth", "outcome", "realized", "realised"],
                                "probability": ["prob", "proba", "p", "score", "p1", "probability_1", "prob_1"],
                                "model": ["model_name", "model_id", "model_version", "version"], "fold": ["cv_fold", "k", "fold_id"]},
             "ml_features": {"feature": ["name", "feature_name", "column", "variable"],
                             "available_from_lag_days": ["lag_days", "availability_lag_days", "publication_lag_days",
                                                         "lag", "available_lag_days"],
                             "importance": ["gain", "weight", "shap"]},
             "ml_feature_values": {"sample_id": ["id", "obs_id", "observation_id", "row_id", "sample"],
                                   "feature": ["name", "feature_name", "variable"], "value": ["x", "val"]}},
    date_columns={"ml_samples": ["timestamp", "label_end"]},
    numeric_columns={"ml_predictions": ["prediction", "actual", "probability"],
                     "ml_features": ["available_from_lag_days", "importance"], "ml_feature_values": ["value"]},
    requirements={
        "ml_split_leakage": {"required": ["ml_samples"], "optional": ["ml_samples(label_end)", "ml_samples(fold)",
                                                                       "ml_features(available_from_lag_days)",
                                                                       "rules(conventions.ml_embargo_days)"]},
        "ml_overfit_gap": {"required": ["ml_samples", "ml_predictions"], "optional": ["ml_predictions(probability)"]},
        "ml_calibration": {"required": ["ml_samples", "ml_predictions"], "optional": ["ml_predictions(probability)"]},
        "ml_population_stability": {"required": ["ml_samples", "ml_predictions"], "optional": ["ml_feature_values"]},
        "ml_target_leakage": {"required": ["ml_samples", "ml_predictions", "ml_feature_values or ml_features"],
                              "optional": []},
        "ml_evaluation_protocol": {"required": ["ml_samples", "ml_predictions"],
                                   "optional": ["declared_results(n_trials)", "rules(research.n_trials)",
                                                "ml_predictions(model)"]},
    },
    catalog={
        "ml_split_leakage": {
            "title": "Split leakage",
            "what": "Same sample_id in two splits; test timestamps inside the training window; training label_end "
                    "later than the first test timestamp (no purging; per fold when `fold` declares a purged K-fold); "
                    "gap to the first test timestamp shorter than ml_embargo_days; features with "
                    "available_from_lag_days > 0.",
            "why": "A test sample that shares dates, ids or label windows with the training set is not out of sample: "
                   "every test metric is then optimistic by an unknown amount.",
            "fix": "Test strictly after the last training label_end plus the embargo; one split per sample; lag each "
                   "feature to its publication date.",
            "allows": "Proving a leak from the sampling table alone (rows listed).",
            "does_not_allow": "Detecting leaks that live inside feature construction (see ml_target_leakage) or "
                              "verifying purging without label_end.",
            "refs": ["lopez18", "bergmeir12", "kaufman12", "sr117"],
        },
        "ml_overfit_gap": {
            "title": "Train / test metric gap",
            "what": "AUC (rank-based) with the Hanley-McNeil SE, accuracy, log-loss, Brier, KS and Gini per split for "
                    "classifiers; R2, RMSE, MAE and Spearman IC for regressions. Review when the test metric loses "
                    "more than ml_overfit_gap_review of the training excess or sits at the naive baseline.",
            "why": "A model that is excellent in sample and ordinary out of sample has memorised its training data; "
                   "the in-sample figure is what gets reported.",
            "fix": "Regularise, simplify, use purged cross-validation, report the test metric with its SE.",
            "allows": "Measuring the gap from delivered predictions.",
            "does_not_allow": "Separating overfitting from a regime change (see ml_population_stability).",
            "refs": ["hanley82", "ahm", "lopez18"],
        },
        "ml_calibration": {
            "title": "Probability calibration",
            "what": "Reliability table on ml_calibration_bins quantile bins, ECE, Brier decomposition, base rate in "
                    "train and test, mean probability against the base rate (2 binomial SE).",
            "why": "A score that ranks but is not calibrated gives wrong expected losses, thresholds and sizes.",
            "fix": "Platt scaling or isotonic regression fitted on the validation split.",
            "allows": "Judging calibration of a delivered probability on the test split.",
            "does_not_allow": "Regression models (prediction intervals are not supported).",
            "refs": ["guo17", "brier50", "sr117"],
        },
        "ml_population_stability": {
            "title": "Population stability (PSI)",
            "what": "PSI of the model score train vs test on 10 quantile bins of train, per-feature PSI when "
                    "ml_feature_values.csv exists, and a label-shift test (two-proportion z or Welch t).",
            "why": "If the test population differs from the training one, the test metric describes a model applied "
                   "where it was not fitted; scorecards are recalibrated when PSI crosses the convention.",
            "fix": "Confirm the shift, monitor PSI in production, recalibrate or rebuild.",
            "allows": "Quantifying drift between the delivered splits.",
            "does_not_allow": "Calling drift an error: the thresholds 0.10 / 0.25 are an industry convention.",
            "refs": ["siddiqi06", "sr117"],
        },
        "ml_target_leakage": {
            "title": "Target leakage in features",
            "what": "On the training split, features whose |Spearman| with `actual` exceeds ml_leak_correlation or "
                    "that separate the classes perfectly (NEEDS_REVIEW, high); feature names containing target / "
                    "label / future / fwd / next (INFO).",
            "why": "A feature computed with the outcome makes any backtest perfect and any deployment useless.",
            "fix": "Trace the construction of the feature, remove it or lag it to its availability date.",
            "allows": "Flagging features statistically indistinguishable from the label.",
            "does_not_allow": "Proving the leak: a legitimate near-deterministic feature exists, rarely.",
            "refs": ["kaufman12", "lopez18"],
        },
        "ml_evaluation_protocol": {
            "title": "Evaluation protocol",
            "what": "Number of distinct models scored on the test split and the number of trials declared "
                    "(declared_results.json n_trials or rules.yaml research.n_trials); which splits were delivered.",
            "why": "Scoring several candidates on the holdout and reporting the best is selection on the test set.",
            "fix": "Select on validation, score once on test, declare the number of configurations tried.",
            "allows": "Counting what was scored where.",
            "does_not_allow": "Knowing about models that were scored and not delivered.",
            "refs": ["dwork15", "ahm", "sr117"],
        },
    },
    references={
        "hanley82": "Hanley, J. A. and McNeil, B. J. (1982). The Meaning and Use of the Area under a Receiver Operating "
                    "Characteristic (ROC) Curve. Radiology 143(1), 29-36.",
        "siddiqi06": "Siddiqi, N. (2006). Credit Risk Scorecards: Developing and Implementing Intelligent Credit Scoring. "
                     "Wiley. (population stability index conventions 0.10 / 0.25)",
        "guo17": "Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. "
                 "ICML. (expected calibration error)",
        "brier50": "Brier, G. W. (1950). Verification of Forecasts Expressed in Terms of Probability. Monthly Weather "
                   "Review 78(1), 1-3.",
        "kaufman12": "Kaufman, S., Rosset, S., Perlich, C. and Stitelman, O. (2012). Leakage in Data Mining: Formulation, "
                     "Detection, and Avoidance. ACM TKDD 6(4).",
        "bergmeir12": "Bergmeir, C. and Benitez, J. M. (2012). On the Use of Cross-validation for Time Series Predictor "
                      "Evaluation. Information Sciences 191, 192-213.",
    },
    conventions={"ml_task": "auto", "ml_embargo_days": 0, "ml_psi_review": 0.10, "ml_psi_error": 0.25,
                 "ml_overfit_gap_review": 0.10, "ml_min_test_samples": 200, "ml_calibration_bins": 10,
                 "ml_leak_correlation": 0.95, "ml_calibration_ece_review": 0.05, "ml_calibration_hl_p": 0.01,
                 "ml_label_shift_p": 0.01},
    profiles={"ml_classification": {"description": "Supervised classifier / scoring model (ml_task = classification).",
                                    "conventions": {"ml_task": "classification"}},
              "ml_regression": {"description": "Supervised regression model (ml_task = regression).",
                                "conventions": {"ml_task": "regression"}}},
    run=run,
)
register(SPEC)
