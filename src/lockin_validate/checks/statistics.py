"""Statistical significance and overfitting checks.

Check ids: sharpe_significance, sharpe_autocorrelation, trials_declared, deflated_sharpe,
multiple_testing, pbo.

Order of the review (Methods, section "what none of these allow"): data first, reconstruction
second, statistics third. A deflated Sharpe computed on data with look-ahead is a nice number about
a lie, so every statistical finding says when earlier blocks have confirmed errors.

Strategy returns come from the NAV reconstructed from trades when possible (verifiable), otherwise
from returns.csv (declared by the strategy owner, not verified).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .. import stats
from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from ..reconciliation import declared_convention
from ..reconstruction import Reconstruction
from . import missing_inputs, not_executable

BLOCK = "statistics"
MIN_OBS_SIGNIFICANCE = 20
MIN_OBS_AUTOCORR = 30
AUTOCORR_INFLATION = 1.10  # naive annualised Sharpe more than 10% above the Lo-adjusted one
RHO1_Z = 2.576  # single-lag band at 99% (docs/ALERT_POLICY.md, P5: the OR with Ljung-Box keeps the size near 5%)


class Series:
    def __init__(self, returns: np.ndarray, dates: list | None, source: str):
        self.returns = returns
        self.dates = dates
        self.source = source


def strategy_returns(pkg: Package, rec: Reconstruction | None) -> Series | None:
    if rec is not None and len(rec.nav) >= 3:
        nav = np.asarray(rec.nav, dtype=float)
        return Series(nav[1:] / nav[:-1] - 1, list(rec.dates[1:]), "NAV reconstructed from trades")
    r = pkg.df("returns")
    if r is not None:
        d = r.dropna(subset=["date"]).sort_values("date")
        if "return" in d.columns and d["return"].notna().any():
            d = d.dropna(subset=["return"])
            return Series(d["return"].to_numpy(dtype=float), list(d["date"].dt.date),
                          "returns.csv (declared, not reconstructed)")
        if "nav" in d.columns and d["nav"].notna().sum() >= 3:
            d = d.dropna(subset=["nav"])
            nav = d["nav"].to_numpy(dtype=float)
            pkg.log.applied("returns", "nav_to_returns", "returns.csv gives a NAV column; simple returns derived",
                            {"nav_points": int(len(nav))}, {"returns": int(len(nav) - 1)})
            return Series(nav[1:] / nav[:-1] - 1, list(d["date"].dt.date)[1:], "returns.csv NAV (declared)")
    return None


def periods_per_year(pkg: Package) -> int:
    conv = declared_convention(pkg) or {}
    return int(conv.get("periods_per_year") or pkg.conv("periods_per_year"))


def declared_n_trials(pkg: Package) -> int | None:
    v = (pkg.declared or {}).get("n_trials")
    if v is None and pkg.rules and isinstance(pkg.rules.get("research"), dict):
        v = pkg.rules["research"].get("n_trials")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def trials_matrix(pkg: Package) -> pd.DataFrame | None:
    t = pkg.df("trials")
    if t is None:
        return None
    cols = [c for c in t.columns if c not in ("row", "date")]
    if not cols:
        return None
    m = t.dropna(subset=["date"]).sort_values("date").set_index("date")[cols]
    return m.dropna(how="all")


def _caveat(res: AuditResult) -> str:
    bad = sorted({f.check for f in res.findings if f.status == CONFIRMED_ERROR and f.block != "statistics"})
    if not bad:
        return ""
    return (" Conditional result: earlier blocks have confirmed errors (" + ", ".join(bad) + "); these statistics "
            "describe the series as delivered, not a corrected one.")


def _strategy_in_log(series: Series, m: pd.DataFrame) -> str | None:
    """Column of the trials matrix that matches the reported strategy (correlation > 0.999)."""
    a = series.returns
    if series.dates is not None:
        idx = {d: i for i, d in enumerate(series.dates)}
        common = [d for d in m.index if hasattr(d, "date") and d.date() in idx]
        if len(common) > 10:
            av = np.array([a[idx[d.date()]] for d in common])
            B = m.loc[common]
        else:
            n = min(len(a), len(m))
            av, B = a[-n:], m.iloc[-n:]
    else:
        n = min(len(a), len(m))
        av, B = a[-n:], m.iloc[-n:]
    if len(av) <= 10 or np.std(av) == 0:
        return None
    for c in B.columns:
        b = B[c].to_numpy(dtype=float)
        ok = np.isfinite(b) & np.isfinite(av)
        if ok.sum() > 10 and np.std(b[ok]) > 0 and np.corrcoef(av[ok], b[ok])[0, 1] > 0.999:
            return str(c)
    return None


def run_statistics(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    series = strategy_returns(pkg, rec)
    ppy = periods_per_year(pkg)
    caveat = _caveat(res)
    m = trials_matrix(pkg)
    n_cols = 0 if m is None else m.shape[1]
    n_decl = declared_n_trials(pkg)
    info: dict[str, Any] = {"source": series.source if series else None, "periods_per_year": ppy,
                            "declared_n_trials": n_decl, "trials_in_matrix": n_cols}
    res.metrics["statistics"] = info
    ins_r = ["trades", "prices"] if series and series.source.startswith("NAV") else ["returns"]

    # ------------------------------------------------------------------ significance
    title = "Statistical significance of the Sharpe ratio"
    mom = None
    if series is None:
        missing_inputs(res, "sharpe_significance", BLOCK, title, pkg.missing("sharpe_significance") or
                       ["trades and prices, or returns"])
    elif len(stats.clean(series.returns)) < MIN_OBS_SIGNIFICANCE:
        not_executable(res, "sharpe_significance", BLOCK, title,
                       f"fewer than {MIN_OBS_SIGNIFICANCE} return observations")
    else:
        mom = stats.moments(series.returns)
        T = mom["T"]
        sr = mom["mean"] / mom["std"] if mom["std"] > 0 else 0.0
        se_iid = stats.sharpe_se_iid(sr, T)
        se_nn = stats.sharpe_se_nonnormal(sr, T, mom["skew"], mom["kurt"])
        psr0 = stats.probabilistic_sharpe(sr, 0.0, T, mom["skew"], mom["kurt"])
        mintrl = stats.min_track_record_length(sr, 0.0, mom["skew"], mom["kurt"])
        k = math.sqrt(ppy)
        ev = {"source": series.source, "T": T, "years": round(T / ppy, 3), "sharpe_per_period": sr,
              "sharpe_annualised_sqrt_rule": sr * k, "se_iid_per_period": se_iid, "se_nonnormal_per_period": se_nn,
              "ci95_annualised": [(sr - 1.96 * se_nn) * k, (sr + 1.96 * se_nn) * k], "t_stat": sr * math.sqrt(T),
              "skewness": mom["skew"], "kurtosis": mom["kurt"], "psr_vs_0": psr0, "min_track_record_periods": mintrl,
              "min_track_record_years": mintrl / ppy if math.isfinite(mintrl) else None}
        info["significance"] = ev
        thr = float(pkg.conv("psr_threshold"))
        proc = ("Per-period Sharpe = mean / std (ddof 1) of the returns; standard error under i.i.d. returns "
                "sqrt((1 + SR^2/2) / T) (Lo 2002) and with skewness and kurtosis sqrt((1 - g3 SR + (g4 - 1)/4 SR^2) / "
                "(T - 1)); PSR(0) = Phi(SR sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2)) and Minimum Track Record "
                f"Length at 95% (Bailey and Lopez de Prado 2012). Threshold PSR >= {thr:g}.")
        if psr0 >= thr:
            res.add("sharpe_significance", BLOCK, PASS, f"Sharpe ratio distinguishable from zero (PSR = {psr0:.3f})",
                    f"Annualised Sharpe {sr * k:.2f} over {T / ppy:.2f} years ({series.source}). Scope: a single test; "
                    "selection among several trials is handled by deflated_sharpe." + caveat, [ev], proc,
                    inputs=ins_r)
        else:
            ratio = float(pkg.conv("significance_review_ratio", 2.0))
            history_short = sr > 0 and (not math.isfinite(mintrl) or mintrl > ratio * T)
            # docs/ALERT_POLICY.md, P1: a review item only when a positive Sharpe would need more than `ratio`
            # times the available history; otherwise an INFO note (weak evidence, not a defect).
            status = NEEDS_REVIEW if history_short else INFO
            if sr <= 0:
                why = " Not an alert: the Sharpe is not positive, so there is no claim of skill to test."
            elif not history_short:
                why = (f" Not an alert: the history covers more than 1/{ratio:g} of the minimum track record "
                       "(docs/ALERT_POLICY.md, P1).")
            else:
                why = ""
            res.add("sharpe_significance", BLOCK, status,
                    f"Sharpe ratio not distinguishable from zero even as a single test (PSR = {psr0:.2f})",
                    f"Annualised Sharpe {sr * k:.2f} over {T / ppy:.2f} years ({series.source}); 95% interval "
                    f"{ev['ci95_annualised'][0]:.2f} to {ev['ci95_annualised'][1]:.2f}. With this Sharpe about "
                    + (f"{mintrl / ppy:.1f} years" if math.isfinite(mintrl) else "an infinite history")
                    + " of history would be needed for 95% confidence (Minimum Track Record Length)." + why + caveat,
                    [ev], proc + f" Review item only if the Sharpe is positive and MinTRL > {ratio:g} x T.",
                    action="Do not present the result as statistically significant; extend the track record.",
                    priority="medium", inputs=ins_r)

    # ------------------------------------------------------------------ autocorrelation (Lo 2002)
    title = "Sharpe annualisation under autocorrelation (Lo 2002)"
    if series is None:
        missing_inputs(res, "sharpe_autocorrelation", BLOCK, title, ["trades and prices, or returns"])
    elif len(stats.clean(series.returns)) < MIN_OBS_AUTOCORR:
        not_executable(res, "sharpe_autocorrelation", BLOCK, title, f"fewer than {MIN_OBS_AUTOCORR} return observations")
    else:
        r = stats.clean(series.returns)
        T = r.size
        max_lag = int(min(pkg.conv("autocorrelation_max_lag"), ppy - 1, T // 4)) if ppy > 1 else 0
        sr = stats.sharpe(r)
        if max_lag < 1 or sr == 0:
            not_executable(res, "sharpe_autocorrelation", BLOCK, title,
                           "not enough periods per year or observations to estimate autocorrelations")
        else:
            rho = stats.autocorrelations(r, max_lag)
            eta = stats.lo_annualisation_factor(rho, ppy)
            lb = stats.ljung_box(r, max_lag)
            naive = sr * math.sqrt(ppy)
            adjusted = sr * eta if math.isfinite(eta) else float("nan")
            inflation = naive / adjusted if adjusted and math.isfinite(adjusted) else float("inf")
            band = RHO1_Z / math.sqrt(T)
            significant = (lb["p_value"] < 0.05) or abs(rho[0]) > band
            ev = {"T": T, "periods_per_year": ppy, "max_lag": max_lag,
                  "autocorrelations": [round(x, 4) for x in rho], "rho1_band_99": band, "ljung_box_Q": lb["Q"],
                  "ljung_box_p": lb["p_value"], "eta_q": eta, "sqrt_q": math.sqrt(ppy),
                  "sharpe_annualised_naive": naive, "sharpe_annualised_lo": adjusted,
                  "naive_over_adjusted": inflation}
            info["autocorrelation"] = ev
            proc = (f"Sample autocorrelations rho_1..rho_{max_lag} of the period returns (rho_k = 0 beyond lag "
                    f"{max_lag}); Lo (2002) factor eta(q) = q / sqrt(q + 2 sum (q - k) rho_k) with q = {ppy}, compared "
                    "with the naive sqrt(q); Ljung-Box test on the same lags; single-lag band |rho_1| > 2.576 / sqrt(T). Review if the naive annualised Sharpe "
                    f"exceeds the adjusted one by more than {AUTOCORR_INFLATION - 1:.0%} and the autocorrelation is "
                    "statistically significant.")
            if significant and inflation > AUTOCORR_INFLATION:
                res.add("sharpe_autocorrelation", BLOCK, NEEDS_REVIEW,
                        f"Positive autocorrelation inflates the annualised Sharpe ({inflation:.2f}x)",
                        f"Naive annualised Sharpe {naive:.2f} vs {adjusted:.2f} after the Lo (2002) adjustment; rho_1 = "
                        f"{rho[0]:.2f}, Ljung-Box p = {lb['p_value']:.3g}. Smoothed returns (stale marks, illiquid assets, "
                        "overlapping positions) make the strategy look less risky than it is." + caveat,
                        [ev], proc, action="Report the Lo-adjusted Sharpe and investigate the source of the "
                                           "autocorrelation (valuation of illiquid assets, return smoothing).",
                        priority="high" if inflation > 1.5 else "medium", inputs=ins_r)
            else:
                res.add("sharpe_autocorrelation", BLOCK, PASS,
                        "No material Sharpe inflation from autocorrelation",
                        f"Naive annualised Sharpe {naive:.2f}, Lo-adjusted {adjusted:.2f} (ratio {inflation:.2f}); "
                        f"Ljung-Box p = {lb['p_value']:.3g}." + caveat, [ev], proc, inputs=ins_r)

    # ------------------------------------------------------------------ number of trials
    title = "Declared number of trials"
    strat_col = _strategy_in_log(series, m) if series is not None and m is not None and n_cols >= 2 else None
    info["strategy_column_in_trials"] = strat_col
    if n_decl is None and m is None:
        not_executable(res, "trials_declared", BLOCK, title,
                       "neither declared_results.n_trials nor trials.csv: the number of configurations tried is unknown, "
                       "so the Sharpe cannot be deflated for selection",
                       "Declare n_trials (every configuration tried, including discarded ones) and deliver trials.csv.")
    else:
        ev = [{"declared_n_trials": n_decl, "columns_in_trials_csv": n_cols, "strategy_column": strat_col}]
        if n_decl is not None and n_cols and n_decl < n_cols:
            res.add("trials_declared", BLOCK, CONFIRMED_ERROR, "Fewer trials declared than present in the trials log",
                    f"declared_results.n_trials = {n_decl} but trials.csv has {n_cols} configurations. Under-declaring "
                    "trials inflates the deflated Sharpe; the larger number is used.", ev,
                    "Declared n_trials compared with the number of return columns in trials.csv.",
                    action="Declare every configuration tried.", priority="high", inputs=["declared_results", "trials"])
        elif n_decl is None:
            res.add("trials_declared", BLOCK, NEEDS_REVIEW, "Number of trials not declared",
                    f"trials.csv has {n_cols} configurations; it is used as a LOWER bound of the number of trials.", ev,
                    "Count of return columns in trials.csv.", action="Declare n_trials in declared_results.json.",
                    priority="medium", inputs=["trials"])
        elif m is None:
            res.add("trials_declared", BLOCK, NEEDS_REVIEW, "Declared number of trials cannot be contrasted",
                    f"n_trials = {n_decl} is declared but no trials log was delivered; the deflation relies on the "
                    "declaration only.", ev, "Presence of trials.csv.",
                    action="Deliver trials.csv with the returns of every configuration tried.", priority="low",
                    inputs=["declared_results"])
        elif series is not None and n_cols >= 2 and strat_col is None:
            res.add("trials_declared", BLOCK, NEEDS_REVIEW, "The reported strategy does not appear in the trials log",
                    "No column of trials.csv matches the strategy returns (correlation > 0.999): it cannot be confirmed "
                    "that the log contains the search that produced the strategy.", ev,
                    "Correlation between the strategy returns and each column of trials.csv on common dates.",
                    action="Include the reported configuration in trials.csv.", priority="medium",
                    inputs=["trials"] + ins_r)
        else:
            res.add("trials_declared", BLOCK, PASS, "Declared number of trials consistent with the trials log",
                    f"n_trials = {n_decl} >= {n_cols} columns in trials.csv"
                    + (f"; the strategy matches column {strat_col}" if strat_col else "") + ".", ev,
                    "Declared n_trials compared with trials.csv.", inputs=["declared_results", "trials"])

    n_proto = int((res.metrics.get("protocol") or {}).get("validation_configs") or 0)
    info["protocol_validation_configs"] = n_proto
    n_eff = max(n_decl or 0, n_cols, n_proto) or None  # validation looks of run_log.csv count as trials
    # ------------------------------------------------------------------ deflated Sharpe
    title = "Deflated Sharpe ratio (selection among trials)"
    if series is None or mom is None:
        not_executable(res, "deflated_sharpe", BLOCK, title, "no strategy return series with enough observations")
        not_executable(res, "multiple_testing", BLOCK, "Multiple-testing haircut",
                       "no strategy return series with enough observations")
    elif n_eff is None:
        T = mom["T"]
        sr = mom["mean"] / mom["std"] if mom["std"] > 0 else 0.0
        bound = stats.probabilistic_sharpe(sr, 0.0, T, mom["skew"], mom["kurt"])
        not_executable(res, "deflated_sharpe", BLOCK, title,
                       "number of trials unknown (declared_results.n_trials or trials.csv); with N = 1 the DSR equals "
                       f"the PSR ({bound:.3f}), the most optimistic possible case",
                       "Declare n_trials and deliver trials.csv.", evidence=[{"dsr_with_n_1": bound}])
        not_executable(res, "multiple_testing", BLOCK, "Multiple-testing haircut",
                       "number of trials unknown (declared_results.n_trials or trials.csv)")
    else:
        T = mom["T"]
        sr = mom["mean"] / mom["std"] if mom["std"] > 0 else 0.0
        if n_cols >= 2:
            srs = [stats.sharpe(m[c].dropna().to_numpy()) for c in m.columns if m[c].notna().sum() >= 3]
            var_sr = float(np.var(srs, ddof=1)) if len(srs) >= 2 else 1.0 / T
            var_src = f"variance of the Sharpe ratio across the {len(srs)} trials in trials.csv"
        else:
            var_sr = 1.0 / T
            var_src = "approximation 1/T (sampling variance of the Sharpe under a true Sharpe of zero)"
        d = stats.deflated_sharpe(sr, T, mom["skew"], mom["kurt"], n_eff, var_sr)
        k = math.sqrt(ppy)
        ev = {"n_trials_used": n_eff, "var_sr": var_sr, "var_sr_source": var_src, "sr_per_period": sr,
              "sr_annualised": sr * k, "expected_max_sr_per_period": d["sr0"], "expected_max_sr_annualised": d["sr0"] * k,
              "dsr": d["dsr"], "T": T}
        info["deflated_sharpe"] = ev
        thr = float(pkg.conv("dsr_threshold"))
        proc = ("Expected maximum Sharpe under the null among N trials: sqrt(V) ((1 - g) Z^-1(1 - 1/N) + g Z^-1(1 - 1/(N e))), "
                "g = Euler-Mascheroni; DSR = PSR(SR0) with skewness and kurtosis (Bailey and Lopez de Prado 2014). "
                f"N = max(declared n_trials, columns of trials.csv); V = {var_src}. Threshold DSR >= {thr:g}.")
        ins = ["declared_results", "trials"] + ins_r
        if d["dsr"] >= thr:
            res.add("deflated_sharpe", BLOCK, PASS, f"Sharpe survives the deflation for {n_eff} trials (DSR = {d['dsr']:.3f})",
                    f"The expected maximum Sharpe by chance among {n_eff} trials is {d['sr0'] * k:.2f} annualised; the "
                    f"strategy has {sr * k:.2f}. Scope: conditional on the declared number of trials being complete."
                    + caveat, [ev], proc, inputs=ins)
        elif n_eff == 1:
            res.add("deflated_sharpe", BLOCK, INFO,
                    f"With one trial the deflated Sharpe equals the PSR ({d['dsr']:.2f}): see sharpe_significance",
                    "N = 1: there is no selection to deflate, so this number repeats the single-test PSR. Not an alert "
                    "here (docs/ALERT_POLICY.md, P3); the evidence strength is judged once, in sharpe_significance."
                    + caveat, [ev], proc, inputs=ins)
        else:
            res.add("deflated_sharpe", BLOCK, NEEDS_REVIEW,
                    f"Deflated Sharpe ratio below threshold: {d['dsr']:.2f} with {n_eff} trials",
                    f"With {n_eff} configurations tried, the maximum Sharpe expected BY CHANCE is {d['sr0'] * k:.2f} "
                    f"annualised; the strategy has {sr * k:.2f}. The probability that its true Sharpe exceeds that "
                    f"threshold is {d['dsr']:.0%} ({thr:.0%} required). The result is compatible with selection among "
                    "noise." + caveat, [ev], proc,
                    action="Do not present the best trial as evidence of skill; test it out of sample or pre-register.",
                    priority="high" if d["dsr"] < 0.5 else "medium", inputs=ins)
        # -------------------------------------------------------------- haircut
        others = None
        if m is not None and n_cols >= 2:
            sc = strat_col
            rest = m.drop(columns=[sc]) if sc is not None else m
            others = [stats.sharpe_pvalue(stats.sharpe(rest[c].dropna().to_numpy()), int(rest[c].notna().sum()))
                      for c in rest.columns if rest[c].notna().sum() >= 3]
            if n_decl and n_decl > len(others) + 1:
                others = None  # partial log: use the bound for the declared N
        h = stats.haircut_sharpe(sr, T, n_eff, others)
        h.update({"sr_annualised": sr * k, "sr_bhy_annualised": h["sr_bhy"] * k,
                  "sr_bonferroni_annualised": h["sr_bonferroni"] * k})
        info["multiple_testing"] = h
        evtxt = (f"Unadjusted p-value {h['p_value']:.4f}; with {h['n_trials']} trials: Bonferroni {h['p_bonferroni']:.3f}, "
                 f"Holm {h['p_holm']:.3f}, BHY {h['p_bhy']:.3f}. Annualised Sharpe {h['sr_annualised']:.2f} -> "
                 f"{h['sr_bhy_annualised']:.2f} after the BHY haircut ({h['haircut_bhy']:.0%} cut).")
        proc = ("t = SR sqrt(T); two-sided p-value; adjusted with Bonferroni, Holm and Benjamini-Hochberg-Yekutieli over "
                "the trials (with the other trials' p-values when trials.csv is complete, otherwise assuming the "
                "strategy is the most significant of N); adjusted p converted back to a Sharpe (Harvey and Liu 2015).")
        if h["p_bhy"] > 0.05 and h["n_trials"] <= 1:
            res.add("multiple_testing", BLOCK, INFO, "With one trial there is no multiple-testing adjustment",
                    evtxt + " N = 1: the adjusted p-values equal the unadjusted one; the single-test evidence is "
                    "judged in sharpe_significance (docs/ALERT_POLICY.md, P3)." + caveat, [h], proc, inputs=ins)
        elif h["p_bhy"] > 0.05:
            res.add("multiple_testing", BLOCK, NEEDS_REVIEW, "Does not survive the multiple-testing adjustment (BHY p > 5%)",
                    evtxt + caveat, [h], proc, action="Treat the result as a candidate, not a discovery.",
                    priority="high" if h["p_bhy"] >= 0.5 else "medium", inputs=ins)
        else:
            res.add("multiple_testing", BLOCK, PASS, "Survives the multiple-testing adjustment (BHY p <= 5%)",
                    evtxt + " Scope: conditional on the declared number of trials." + caveat, [h], proc, inputs=ins)

    # ------------------------------------------------------------------ PBO
    title = "Probability of backtest overfitting (CSCV)"
    if m is None or n_cols < 2:
        missing_inputs(res, "pbo", BLOCK, title, ["trials (at least 2 configurations)"])
    else:
        X = m.dropna(how="any")
        try:
            p = stats.cscv_pbo(X.to_numpy(dtype=float))
        except ValueError as exc:
            not_executable(res, "pbo", BLOCK, title, str(exc))
        else:
            info["pbo"] = p
            thr = float(pkg.conv("pbo_threshold"))
            txt = (f"In {p['n_combinations']} partitions (CSCV, {p['n_blocks']} blocks, {p['n_trials']} trials) the "
                   f"configuration chosen in-sample ends in the bottom half out-of-sample {p['pbo']:.0%} of the time; it "
                   f"loses money out-of-sample {p['prob_oos_loss']:.0%} of the time. Mean per-period Sharpe of the chosen "
                   f"one: IS {p['mean_is_sharpe_of_chosen']:.3f} vs OOS {p['mean_oos_sharpe_of_chosen']:.3f}.")
            proc = ("Combinatorially symmetric cross-validation on the T x N matrix of trials.csv (rows with any missing "
                    f"value dropped; Bailey, Borwein, Lopez de Prado and Zhu 2017). Review threshold PBO >= {thr:g}.")
            if p["pbo"] >= thr:
                res.add("pbo", BLOCK, NEEDS_REVIEW, f"Probability of backtest overfitting {p['pbo']:.0%}", txt + caveat,
                        [p], proc, action="Reduce the search, use a hold-out period never seen during selection.",
                        priority="high" if p["pbo"] >= 0.5 else "medium", inputs=["trials"])
            else:
                res.add("pbo", BLOCK, PASS, f"Low probability of backtest overfitting ({p['pbo']:.0%})", txt
                        + " Scope: only the configurations in trials.csv." + caveat, [p], proc, inputs=["trials"])
