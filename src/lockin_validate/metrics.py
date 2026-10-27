"""Metrics of a NAV series with explicit conventions (docs/CONVENTIONS.md, section 2).

Convention keys (accepted in declared_results.convention and in rules.conventions):

``periods_per_year``  252 (default), 260, 365, 360, 52, 12...
``sharpe``            ``arithmetic``: mean(r - rf/P) / std(r) * sqrt(P)  (default)
                      ``geometric``: (geometric annual return - rf) / (std(r) * sqrt(P))
``std_ddof``          1 (sample, default) or 0 (population)
``risk_free_annual``  0.0 (default); subtracted per period (rf / P) before averaging
``annual_return``     ``geometric``: (1 + R)^(P / n) - 1 (default); ``arithmetic``: mean(r) * P;
                      ``calendar``: (1 + R)^(365 / calendar days) - 1
``max_drawdown``      ``nav``: on the compounded NAV curve, reported as a negative number
``returns``           ``simple`` (default) or ``log``

Extension point: ``EXTERNAL_VARIANTS`` (callables (nav, dates) -> {name: sharpe}).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

import numpy as np

DEFAULT_CONVENTION: dict[str, Any] = {
    "periods_per_year": 252,
    "sharpe": "arithmetic",
    "std_ddof": 1,
    "risk_free_annual": 0.0,
    "annual_return": "geometric",
    "max_drawdown": "nav",
    "returns": "simple",
}

EXTERNAL_VARIANTS: list[Callable[[list[float], list[date]], dict[str, float]]] = []


def _clean(nav) -> np.ndarray:
    a = np.asarray(list(nav), dtype=float)
    return a[np.isfinite(a)]


def period_returns(nav, kind: str = "simple") -> np.ndarray:
    a = _clean(nav)
    if a.size < 2:
        return np.array([], dtype=float)
    if kind == "log":
        return np.diff(np.log(a))
    return a[1:] / a[:-1] - 1


def total_return(nav) -> float:
    a = _clean(nav)
    if a.size < 1 or a[0] == 0:
        return float("nan")
    return float(a[-1] / a[0] - 1)


def annual_return(nav, ppy: int = 252, method: str = "geometric", dates: list[date] | None = None,
                  kind: str = "simple") -> float:
    a = _clean(nav)
    n = a.size - 1
    if n < 1:
        return float("nan")
    rt = total_return(a)
    if method == "arithmetic":
        return float(period_returns(a, kind).mean() * ppy)
    if method == "calendar" and dates is not None and len(dates) >= 2:
        days = (dates[-1] - dates[0]).days
        if days <= 0:
            return float("nan")
        return float((1 + rt) ** (365.0 / days) - 1)
    if rt <= -1:
        return -1.0
    return float((1 + rt) ** (ppy / n) - 1)


def std(r, ddof: int = 1) -> float:
    r = np.asarray(r, dtype=float)
    if r.size <= ddof:
        return float("nan")
    return float(r.std(ddof=ddof))


def sharpe(nav, ppy: int = 252, method: str = "arithmetic", ddof: int = 1, rf_annual: float = 0.0,
           kind: str = "simple", dates: list[date] | None = None) -> float:
    r = period_returns(nav, kind)
    sd = std(r, ddof)
    if not (sd > 0):
        return float("nan")
    if method == "geometric":
        ra = annual_return(nav, ppy, "geometric", dates, kind)
        return float((ra - rf_annual) / (sd * math.sqrt(ppy)))
    excess = r.mean() - rf_annual / ppy
    return float(excess / sd * math.sqrt(ppy))


def max_drawdown(nav) -> float:
    """Largest peak-to-trough fall, as a negative number (0 if it never falls)."""
    a = _clean(nav)
    if a.size == 0:
        return float("nan")
    peak = np.maximum.accumulate(a)
    return float((a / peak - 1).min())


def max_drawdown_detail(nav, dates: list[date] | None = None) -> dict[str, Any]:
    a = _clean(nav)
    if a.size == 0:
        return {"max_drawdown": float("nan")}
    peak = np.maximum.accumulate(a)
    dd = a / peak - 1
    i_trough = int(dd.argmin())
    i_peak = int(np.argmax(a[: i_trough + 1]))
    out = {"max_drawdown": float(dd[i_trough]), "peak_index": i_peak, "trough_index": i_trough,
           "peak_nav": float(a[i_peak]), "trough_nav": float(a[i_trough])}
    if dates is not None and len(dates) == a.size:
        out["peak_date"] = dates[i_peak].isoformat()
        out["trough_date"] = dates[i_trough].isoformat()
    return out


ALIASES = {"arith": "arithmetic", "geo": "geometric", "simple_returns": "simple"}


def full_convention(declared: dict | None) -> dict[str, Any]:
    conv = dict(DEFAULT_CONVENTION)
    for k, v in (declared or {}).items():
        if k in conv and v is not None:
            conv[k] = ALIASES.get(v, v) if isinstance(v, str) else v
    conv["periods_per_year"] = int(conv["periods_per_year"])
    conv["std_ddof"] = int(conv["std_ddof"])
    conv["risk_free_annual"] = float(conv["risk_free_annual"])
    return conv


def compute(nav, dates: list[date] | None, conv: dict | None, n_trades: int | None = None) -> dict[str, Any]:
    c = full_convention(conv)
    a = _clean(nav)
    out = {
        "convention": c,
        "n_periods": int(max(a.size - 1, 0)),
        "initial_nav": float(a[0]) if a.size else float("nan"),
        "final_nav": float(a[-1]) if a.size else float("nan"),
        "total_return": total_return(a),
        "annual_return": annual_return(a, c["periods_per_year"], c["annual_return"], dates, c["returns"]),
        "sharpe": sharpe(a, c["periods_per_year"], c["sharpe"], c["std_ddof"], c["risk_free_annual"], c["returns"],
                         dates),
        "max_drawdown": max_drawdown(a),
        "annual_volatility": std(period_returns(a, c["returns"]), c["std_ddof"]) * math.sqrt(c["periods_per_year"])
        if a.size > 2 else float("nan"),
    }
    out.update(max_drawdown_detail(a, dates))
    if n_trades is not None:
        out["n_trades"] = int(n_trades)
    return out


def sharpe_variants(nav, dates: list[date] | None = None, rf_candidates=(0.0, 0.02, 0.04, 0.05)) -> dict[str, float]:
    """Sharpe under the most common alternative conventions (to see which reproduces a declared value)."""
    out: dict[str, float] = {}
    for ppy in (252, 260, 365, 360):
        for method in ("arithmetic", "geometric"):
            for ddof in (1, 0):
                for rf in rf_candidates:
                    for kind in ("simple", "log"):
                        if kind == "log" and (method == "geometric" or rf != 0.0):
                            continue
                        key = f"ppy={ppy}, {method}, ddof={ddof}, rf={rf:g}, {kind}"
                        out[key] = sharpe(nav, ppy, method, ddof, rf, kind, dates)
    for ext in EXTERNAL_VARIANTS:
        try:
            out.update(ext(list(nav), list(dates or [])))
        except Exception:  # pragma: no cover
            pass
    return out


def annual_return_variants(nav, dates: list[date] | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for ppy in (252, 260, 365, 360):
        out[f"geometric, ppy={ppy}"] = annual_return(nav, ppy, "geometric", dates)
        out[f"arithmetic, ppy={ppy}"] = annual_return(nav, ppy, "arithmetic", dates)
    if dates is not None and len(dates) >= 2:
        out["geometric, calendar days/365"] = annual_return(nav, 365, "calendar", dates)
    return out


def max_drawdown_variants(nav) -> dict[str, float]:
    a = _clean(nav)
    md = max_drawdown(a)
    out = {"nav (negative)": md, "nav (positive)": -md}
    if a.size > 1:
        r = period_returns(a)
        out["worst single period return"] = float(r.min())
        cum = np.r_[0.0, np.cumsum(r)]  # arithmetic cumulative returns (common error: not compounded)
        out["sum of returns, not compounded"] = float((cum - np.maximum.accumulate(cum)).min())
    return out


def describe_convention(c: dict) -> str:
    return (f"periods_per_year={c['periods_per_year']}, sharpe={c['sharpe']}, std_ddof={c['std_ddof']}, "
            f"risk_free_annual={c['risk_free_annual']:g}, annual_return={c['annual_return']}, returns={c['returns']}")
