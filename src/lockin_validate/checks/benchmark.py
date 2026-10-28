"""Benchmark fit (0.2.0, family 3).

Check id: benchmark_fit. Beta, correlation, tracking error and information ratio of the strategy against the declared
benchmark (benchmark_returns.csv) and against the equal-weight universe (universe_returns.csv, or computed from
prices.csv and the universe membership). The gap to the benchmark is split exactly, on common dates and with
arithmetic annualised means, into

  benchmark-choice effect = equal-weight universe - benchmark
  selection effect        = strategy - equal-weight universe

A benchmark whose construction (rules.yaml benchmark.weighting) differs from the strategy's weighting (rules.yaml
sizing or benchmark.strategy_weighting), or whose construction is not declared, is a review item: part of the gap is
the choice of yardstick, not skill.

Motivation (LockIn case study): about 3 pp a year of LockIn's gap to its index came from comparing an equal-weight
book with a cap-weighted index.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..findings import NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from ..reconstruction import Reconstruction
from . import missing_inputs, not_executable
from .statistics import periods_per_year, strategy_returns

BLOCK = "strategy"
MIN_OBS = 20
R2_MIN = 0.25

EQUAL = {"equal", "equal_weight", "equal_weighted", "equally_weighted", "ew", "1/n"}
CAP = {"cap", "cap_weight", "cap_weighted", "market_cap", "market_cap_weighted", "value", "value_weighted", "vw",
       "float_adjusted"}


def normalise_weighting(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower().replace("-", "_").replace(" ", "_")
    if s in EQUAL:
        return "equal"
    if s in CAP:
        return "cap"
    return s


def return_series(df: pd.DataFrame | None) -> pd.Series | None:
    """date -> simple return from a returns-like table (return column, or nav/close level)."""
    if df is None:
        return None
    d = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="first")
    if "return" in d.columns and d["return"].notna().any():
        d = d.dropna(subset=["return"])
        return pd.Series(d["return"].to_numpy(dtype=float), index=d["date"].dt.date)
    if "nav" in d.columns and d["nav"].notna().sum() >= 3:
        d = d.dropna(subset=["nav"])
        nav = d["nav"].to_numpy(dtype=float)
        return pd.Series(nav[1:] / nav[:-1] - 1, index=list(d["date"].dt.date)[1:])
    return None


def equal_weight_universe(pkg: Package) -> tuple[pd.Series | None, str]:
    s = return_series(pkg.df("universe_returns"))
    if s is not None:
        return s, "universe_returns.csv"
    px = pkg.df("prices")
    if px is None:
        return None, "no universe_returns.csv and no prices.csv"
    u = pkg.df("universe")
    lst = (pkg.rules or {}).get("universe")
    if u is None and not (isinstance(lst, list) and lst):
        return None, "no universe membership (universe.csv or a rules.yaml universe list)"
    d = px.dropna(subset=["date", "ticker", "close"]).sort_values(["date", "row"]).drop_duplicates(["ticker", "date"])
    wide = d.pivot(index="date", columns="ticker", values="close").sort_index()
    rets = wide / wide.shift(1) - 1
    if u is not None:
        uu = u.dropna(subset=["ticker", "start_date"])
        mask = pd.DataFrame(False, index=rets.index, columns=rets.columns)
        for r in uu.itertuples():
            if r.ticker in mask.columns:
                end = getattr(r, "end_date", None)
                sel = (mask.index >= r.start_date) & ((mask.index <= end) if end is not None and pd.notna(end) else True)
                mask.loc[sel, r.ticker] = True
        src = "computed from prices.csv: equal weight of universe.csv members with a return that day"
    else:
        members = [str(x).strip().upper() for x in lst]
        mask = pd.DataFrame({c: c in members for c in rets.columns}, index=rets.index)
        src = "computed from prices.csv: equal weight of the rules.yaml universe with a return that day"
    ew = rets.where(mask).mean(axis=1, skipna=True).dropna()
    ew = ew.iloc[1:] if len(ew) else ew
    return pd.Series(ew.to_numpy(dtype=float), index=[x.date() for x in ew.index]), src


def fit(s: np.ndarray, b: np.ndarray, ppy: int) -> dict[str, float]:
    var_b = float(np.var(b, ddof=1))
    cov = float(np.cov(s, b, ddof=1)[0, 1])
    beta = cov / var_b if var_b > 0 else float("nan")
    corr = float(np.corrcoef(s, b)[0, 1]) if np.std(s) > 0 and np.std(b) > 0 else float("nan")
    active = s - b
    te = float(np.std(active, ddof=1)) * math.sqrt(ppy)
    ar = float(np.mean(active)) * ppy
    return {"beta": beta, "correlation": corr, "r2": corr * corr if math.isfinite(corr) else float("nan"),
            "tracking_error": te, "active_return_annual": ar, "information_ratio": ar / te if te > 0 else float("nan")}


def check_benchmark_fit(pkg: Package, res: AuditResult, rec: Reconstruction | None) -> None:
    title = "Benchmark fit"
    miss = pkg.missing("benchmark_fit")
    if miss:
        missing_inputs(res, "benchmark_fit", BLOCK, title, miss)
        return
    series = strategy_returns(pkg, rec)
    bench = return_series(pkg.df("benchmark_returns"))
    if series is None or series.dates is None or bench is None:
        not_executable(res, "benchmark_fit", BLOCK, title, "no dated strategy series or no usable benchmark returns")
        return
    ppy = periods_per_year(pkg)
    strat = pd.Series(series.returns, index=series.dates)
    strat = strat[~strat.index.duplicated()]
    ew, ew_src = equal_weight_universe(pkg)
    common = strat.index.intersection(bench.index)
    if ew is not None:
        common3 = common.intersection(ew.index)
        if len(common3) >= MIN_OBS:
            common = common3
        else:
            ew, ew_src = None, ew_src + " (fewer than 20 dates in common with the strategy and the benchmark)"
    common = sorted(common)
    if len(common) < MIN_OBS:
        not_executable(res, "benchmark_fit", BLOCK, title,
                       f"fewer than {MIN_OBS} dates in common between the strategy and the benchmark")
        return
    s = strat.loc[common].to_numpy(dtype=float)
    b = bench.loc[common].to_numpy(dtype=float)
    vs_b = fit(s, b, ppy)
    bcfg = (pkg.rules or {}).get("benchmark") if isinstance((pkg.rules or {}).get("benchmark"), dict) else {}
    b_name = bcfg.get("name") or "declared benchmark"
    b_w = normalise_weighting(bcfg.get("weighting"))
    s_w = normalise_weighting(bcfg.get("strategy_weighting") or (pkg.rules or {}).get("sizing"))
    ev: list[dict[str, Any]] = [{"comparator": f"{b_name} (benchmark_returns.csv)", "weighting": b_w or "not declared",
                                 **{k: round(v, 4) for k, v in vs_b.items()}}]
    decomposition = None
    te_bu = None
    if ew is not None:
        u = ew.loc[common].to_numpy(dtype=float)
        vs_u = fit(s, u, ppy)
        ev.append({"comparator": f"equal-weight universe ({ew_src})", "weighting": "equal",
                   **{k: round(v, 4) for k, v in vs_u.items()}})
        te_bu = float(np.std(b - u, ddof=1)) * math.sqrt(ppy)
        gap = float(np.mean(s - b)) * ppy
        choice = float(np.mean(u - b)) * ppy
        selection = float(np.mean(s - u)) * ppy
        decomposition = {"gap_vs_benchmark_annual": gap, "benchmark_choice_effect_annual": choice,
                         "selection_effect_annual": selection}
        ev.append({"comparator": "decomposition (arithmetic, annualised)", **{k: round(v, 4)
                                                                               for k, v in decomposition.items()}})
    res.metrics["benchmark_fit"] = {"benchmark_vs_universe_tracking_error": te_bu, "vs_benchmark": vs_b, "decomposition": decomposition, "n": len(common),
                                    "benchmark_weighting": b_w, "strategy_weighting": s_w, "universe_source": ew_src}
    proc = (f"{len(common)} common dates; beta = cov(s, b) / var(b); tracking error = std(s - b) x sqrt({ppy}); active "
            f"return = mean(s - b) x {ppy}; information ratio = active return / tracking error (Grinold and Kahn). "
            "Decomposition on the same dates: gap = (u - b) + (s - u), u = equal-weight universe. Strategy series: "
            f"{series.source}.")
    dec_txt = ""
    if decomposition:
        dec_txt = (f" Of the annual gap of {decomposition['gap_vs_benchmark_annual'] * 100:+.2f} pp to the benchmark, "
                   f"{decomposition['benchmark_choice_effect_annual'] * 100:+.2f} pp is the benchmark-choice effect "
                   "(equal-weight universe minus benchmark) and "
                   f"{decomposition['selection_effect_annual'] * 100:+.2f} pp the selection effect (strategy minus "
                   "equal-weight universe).")
    else:
        dec_txt = f" The benchmark-choice effect cannot be separated: {ew_src}."
    problems = []
    if b_w is None:
        problems.append("the benchmark construction (rules.yaml benchmark.weighting) is not declared")
    elif s_w is None:
        problems.append("the strategy weighting (rules.yaml sizing or benchmark.strategy_weighting) is not declared")
    elif b_w != s_w:
        problems.append(f"the benchmark is {b_w}-weighted while the strategy is {s_w}-weighted")
    te_max = float(pkg.conv("benchmark_universe_tracking_error", 0.01))
    contrasted = False
    if b_w == "equal" and te_bu is not None and decomposition is not None:
        contrasted = True
        if te_bu > te_max or abs(decomposition["benchmark_choice_effect_annual"]) > te_max / 2:
            problems.append(f"the benchmark is declared equal-weighted but differs from the equal-weight universe "
                            f"computed from the prices (tracking error {te_bu:.1%} > {te_max:.0%} or |benchmark-choice "
                            f"effect| {abs(decomposition['benchmark_choice_effect_annual']):.2%} > {te_max / 2:.1%})")
    if math.isfinite(vs_b["r2"]) and vs_b["r2"] < R2_MIN:
        problems.append(f"the benchmark explains only {vs_b['r2']:.0%} of the strategy's variance (R2 < {R2_MIN:.0%})")
    if problems:
        res.add("benchmark_fit", BLOCK, NEEDS_REVIEW,
                "Benchmark does not match the strategy's construction: " + problems[0],
                "; ".join(problems).capitalize() + f". Against {b_name}: beta {vs_b['beta']:.2f}, tracking error "
                f"{vs_b['tracking_error']:.1%}, information ratio {vs_b['information_ratio']:.2f}." + dec_txt
                + " A gap measured against a yardstick built differently mixes skill with the choice of yardstick.",
                ev, proc, action="Compare with a benchmark built like the strategy (same universe and weighting) and "
                                 "report the benchmark-choice effect separately.",
                priority="medium", inputs=["benchmark_returns", "rules", "universe", "prices"])
    else:
        res.add("benchmark_fit", BLOCK, PASS, "Benchmark built like the strategy",
                f"Both {s_w}-weighted. Against {b_name}: beta {vs_b['beta']:.2f}, R2 {vs_b['r2']:.2f}, tracking error "
                f"{vs_b['tracking_error']:.1%}, information ratio {vs_b['information_ratio']:.2f}." + dec_txt
                + (f" The declared equal weighting was contrasted with the equal-weight universe (tracking error "
                   f"{te_bu:.2%})." if contrasted else
                   " Scope: construction as declared (it could not be contrasted with the data)."),
                ev, proc, inputs=["benchmark_returns", "rules"])
