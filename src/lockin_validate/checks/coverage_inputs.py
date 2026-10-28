"""Coverage drift and input sufficiency (0.2.0, family 1).

Check ids:
  coverage_drift     per input field and per period, the share of universe members with a valid current value,
                     compared with the strategy's OWN history (median of the previous periods)
  input_sufficiency  periods where the model scored names with fewer than the declared minimum share of its
                     declared inputs (rules.yaml: required_inputs, min_input_share)

Motivation (LockIn case study): a single-use holdout was spent on a database where ~21% of the universe members had
no fundamentals, and a reserved window was run with 13 of its 27 inputs (91% of the evaluations inconclusive) while
every existing preflight check passed. Neither problem is visible row by row: both are only visible as a drop
against the strategy's own history or against its own declared input list.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from . import missing_inputs, not_executable

BLOCK = "data"
MIN_PERIODS = 5  # periods needed to have an own history to compare with
MIN_HISTORY = 4  # previous periods in the baseline
FUND_META = {"row", "ticker", "period_end", "filing_date", "available_from"}
SIGNAL_META = {"row", "decision_time", "ticker", "data_date", "data_source"}


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _universe_members(pkg: Package, table_tickers: set[str]):
    """Return (members_at(date) -> set, source description)."""
    u = pkg.df("universe")
    if u is not None:
        u = u.dropna(subset=["ticker", "start_date"])
        rows = [(r.ticker, r.start_date, getattr(r, "end_date", None)) for r in u.itertuples()]

        def at(d: pd.Timestamp) -> set[str]:
            return {t for t, s, e in rows if s <= d and (e is None or pd.isna(e) or e >= d)}
        return at, "universe.csv (point-in-time membership)"
    lst = (pkg.rules or {}).get("universe")
    if isinstance(lst, list) and lst:
        members = {str(x).strip().upper() for x in lst}
        return (lambda d: members), "rules.yaml universe list"
    return (lambda d: set(table_tickers)), ("tickers present anywhere in the table (no universe declared: members "
                                            "missing from the table altogether cannot be seen)")


def _fields(df: pd.DataFrame, meta: set[str]) -> list[str]:
    out = []
    for c in df.columns:
        if c in meta:
            continue
        if _numeric(df[c]).notna().any():
            out.append(c)
    return out


def _coverage_table(df: pd.DataFrame, date_col: str, freq: str, fields: list[str], members_at) -> pd.DataFrame:
    """Rows: (field, period, period_end, members, covered, coverage)."""
    d = df.dropna(subset=[date_col, "ticker"]).copy()
    d["_period"] = d[date_col].dt.to_period(freq)
    out = []
    for per, g in sorted(d.groupby("_period"), key=lambda x: x[0]):
        end = per.end_time.normalize()
        members = members_at(end)
        if not members:
            continue
        for f in fields:
            v = _numeric(g[f])
            ok = set(g.loc[v.notna() & np.isfinite(v.fillna(np.nan)), "ticker"])
            cov = len(ok & members) / len(members)
            out.append({"field": f, "period": str(per), "members": len(members), "covered": len(ok & members),
                        "coverage": cov})
    return pd.DataFrame(out)


def _drops(tab: pd.DataFrame, threshold: float) -> list[dict[str, Any]]:
    flagged = []
    for f, g in tab.groupby("field", sort=False):
        covs = list(g["coverage"])
        pers = list(g["period"])
        bad = []
        for i in range(MIN_HISTORY, len(covs)):
            base = float(np.median(covs[:i]))
            if base - covs[i] >= threshold:
                bad.append((pers[i], covs[i], base))
        if bad:
            flagged.append({"field": f, "first_period": bad[0][0], "last_period": bad[-1][0],
                            "periods_flagged": len(bad), "baseline_coverage": round(bad[0][2], 4),
                            "min_coverage": round(min(b[1] for b in bad), 4),
                            "examples": [f"{p}: {c:.0%}" for p, c, _ in bad[:4]]})
    return flagged


def check_coverage_drift(pkg: Package, res: AuditResult) -> None:
    title = "Coverage drift of inputs against the strategy's own history"
    miss = pkg.missing("coverage_drift")
    if miss:
        missing_inputs(res, "coverage_drift", BLOCK, title, miss)
        return
    threshold = float(pkg.conv("coverage_drop", 0.10))
    sources = []
    if pkg.df("fundamentals") is not None:
        sources.append(("fundamentals", "period_end", "Q", FUND_META))
    if pkg.df("signals") is not None:
        sources.append(("signals", "decision_time", "M", SIGNAL_META))
    flagged: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    universe_src = "-"
    reasons = []
    for name, col, freq, meta in sources:
        df = pkg.df(name)
        fields = _fields(df, meta)
        if not fields:
            reasons.append(f"{name}: no numeric input field")
            continue
        members_at, universe_src = _universe_members(pkg, set(df["ticker"].dropna()))
        tab = _coverage_table(df, col, freq, fields, members_at)
        n_per = tab["period"].nunique() if len(tab) else 0
        if n_per < MIN_PERIODS:
            reasons.append(f"{name}: {n_per} periods (fewer than {MIN_PERIODS}: no own history to compare)")
            continue
        for f, g in tab.groupby("field", sort=False):
            summary.append({"source": name, "field": f, "periods": int(len(g)),
                            "median_coverage": round(float(g["coverage"].median()), 4),
                            "min_coverage": round(float(g["coverage"].min()), 4),
                            "min_period": str(g.loc[g["coverage"].idxmin(), "period"])})
        for x in _drops(tab, threshold):
            flagged.append({"source": name, **x})
    res.metrics["coverage_drift"] = {"summary": summary, "flagged": flagged, "universe": universe_src}
    if not summary:
        not_executable(res, "coverage_drift", BLOCK, title, "; ".join(reasons) or "no input field to measure")
        return
    proc = ("Per input field and per period (calendar quarter of period_end for fundamentals, calendar month of "
            "decision_time for signals): coverage = members with a finite value in the period / members of the "
            f"universe at the period end (universe: {universe_src}). A period is flagged when its coverage is at least "
            f"{threshold:.0%} (conventions.coverage_drop) below the median coverage of all previous periods (at least "
            f"{MIN_HISTORY}).")
    if flagged:
        names = ", ".join(f"{x['source']}.{x['field']}" for x in flagged[:6]) + (" ..." if len(flagged) > 6 else "")
        first = min(x["first_period"] for x in flagged)
        worst = min(flagged, key=lambda x: x["min_coverage"])
        res.add("coverage_drift", BLOCK, NEEDS_REVIEW,
                f"Coverage of {len(flagged)} inputs falls below the strategy's own history (from {first})",
                f"{names}: coverage drops from a baseline of {worst['baseline_coverage']:.0%} to "
                f"{worst['min_coverage']:.0%} ({worst['source']}.{worst['field']}, periods {worst['first_period']} to "
                f"{worst['last_period']}). Results computed in those periods rest on a smaller or different part of "
                "the universe than the history they are compared with; checks that look at single rows pass.",
                flagged + summary, proc,
                action="Find why the inputs disappeared (vendor, mapping, membership) before using those periods; "
                       "never spend a holdout on them.", priority="high",
                inputs=[s[0] for s in sources] + ["universe"])
    else:
        res.add("coverage_drift", BLOCK, PASS, "No coverage drift against the strategy's own history",
                f"{len(summary)} input fields measured; lowest coverage {min(s['min_coverage'] for s in summary):.0%}. "
                "Scope: members the universe source can see.", summary, proc,
                inputs=[s[0] for s in sources])


# ---------------------------------------------------------------------------- input sufficiency

def _asof_fundamentals(pkg: Package, fields: list[str]):
    """{ticker: (availability timestamps sorted, rows)} for the as-of lookup of fields not in signals.csv."""
    f = pkg.df("fundamentals")
    if f is None or not fields:
        return {}
    d = f.copy()
    avail = None
    for c in ("filing_date", "available_from"):
        if c in d.columns:
            avail = d[c] if avail is None else pd.concat([avail, d[c]], axis=1).max(axis=1)
    d["_avail"] = avail if avail is not None else d["period_end"]
    d = d.dropna(subset=["ticker", "_avail"]).sort_values(["ticker", "_avail"])
    out = {}
    for t, g in d.groupby("ticker"):
        out[t] = (list(g["_avail"]), [{k: _num1(r.get(k)) for k in fields} for r in g.to_dict("records")])
    return out


def _num1(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def check_input_sufficiency(pkg: Package, res: AuditResult) -> None:
    title = "Names scored with too few of the declared inputs"
    miss = pkg.missing("input_sufficiency")
    if miss:
        missing_inputs(res, "input_sufficiency", BLOCK, title, miss)
        return
    req = (pkg.rules or {}).get("required_inputs")
    if not isinstance(req, list) or not req:
        not_executable(res, "input_sufficiency", BLOCK, title, "rules.yaml required_inputs is not a list of names")
        return
    req = [str(x).strip() for x in req]
    declared_min = (pkg.rules or {}).get("min_input_share")
    min_share = float(declared_min) if declared_min is not None else 0.5
    s = pkg.df("signals").dropna(subset=["decision_time", "ticker"]).copy()
    s["_sig"] = _numeric(s["signal"])
    in_signals = [c for c in req if c in s.columns]
    lookup_fields = [c for c in req if c not in s.columns]
    fund = _asof_fundamentals(pkg, lookup_fields)
    in_fund = [c for c in lookup_fields if pkg.df("fundamentals") is not None and c in pkg.df("fundamentals").columns]
    absent = [c for c in lookup_fields if c not in in_fund]
    for c in in_signals:
        s[c] = _numeric(s[c])
    rows = []
    fund_arr = {t: (np.array(ts, dtype="datetime64[ns]"), recs) for t, (ts, recs) in fund.items()}
    for rd in s.to_dict("records"):
        n_ok = sum(1 for c in in_signals if _num1(rd.get(c)) is not None)
        if in_fund and rd["ticker"] in fund_arr:
            ts, recs = fund_arr[rd["ticker"]]
            i = int(np.searchsorted(ts, np.datetime64(rd["decision_time"]), "right")) - 1
            if i >= 0:
                n_ok += sum(1 for c in in_fund if recs[i].get(c) is not None)
        rows.append({"period": str(pd.Timestamp(rd["decision_time"]).to_period("M")), "ticker": rd["ticker"],
                     "row": int(rd["row"]), "scored": _num1(rd["_sig"]) is not None, "share": n_ok / len(req),
                     "n_inputs": n_ok})
    t = pd.DataFrame(rows)
    per = []
    for p, g in t.groupby("period"):
        sc = g[g["scored"]]
        low = sc[sc["share"] < min_share - 1e-12]
        per.append({"period": p, "names": int(len(g)), "scored": int(len(sc)),
                    "unscored_share": round(1 - len(sc) / len(g), 4) if len(g) else None,
                    "scored_below_minimum": int(len(low)),
                    "mean_inputs_of_scored": round(float(sc["n_inputs"].mean()), 2) if len(sc) else None})
    bad = [p for p in per if p["scored_below_minimum"]]
    res.metrics["input_sufficiency"] = {"required_inputs": req, "min_input_share": min_share,
                                        "declared_min": declared_min is not None, "periods": per,
                                        "inputs_not_delivered": absent}
    src = ("signals.csv columns " + ", ".join(in_signals) if in_signals else "") + \
        ("; fundamentals.csv as of the decision for " + ", ".join(in_fund) if in_fund else "")
    proc = (f"For every scored row of signals.csv (finite signal) the number of the {len(req)} required inputs with a "
            f"finite value is counted ({src or 'no input column found'}; inputs in no table count as missing). A row "
            f"is insufficient below min_input_share = {min_share:g} ("
            + ("declared in rules.yaml" if declared_min is not None else "not declared: default 0.5") + ").")
    if absent:
        proc += " Inputs delivered in no table: " + ", ".join(absent) + "."
    if bad:
        n_bad = sum(p["scored_below_minimum"] for p in bad)
        n_sc = sum(p["scored"] for p in bad)
        status = CONFIRMED_ERROR if declared_min is not None else NEEDS_REVIEW
        examples = [{"row": int(x.row), "period": x.period, "ticker": x.ticker, "inputs_present": int(x.n_inputs),
                     "inputs_required": len(req)} for x in t[t["scored"] & (t["share"] < min_share - 1e-12)]
                    .head(10).itertuples()]
        res.add("input_sufficiency", BLOCK, status,
                f"Names scored with fewer than {min_share:.0%} of the declared inputs in {len(bad)} periods "
                f"({bad[0]['period']} to {bad[-1]['period']})",
                f"{n_bad} of {n_sc} scored names in those periods had fewer than {math.ceil(min_share * len(req))} of "
                f"the {len(req)} required inputs (mean inputs of scored names as low as "
                f"{min(p['mean_inputs_of_scored'] or 0 for p in bad):g}). "
                + ("The declared minimum is broken: those scores are not the declared model."
                   if declared_min is not None else
                   "No minimum is declared; the default of 0.5 is used, so this is a review item.")
                + (" Inputs delivered in no table: " + ", ".join(absent) + "." if absent else ""),
                bad + examples, proc,
                action="Do not evaluate (and never spend a reserved window on) periods scored with missing inputs; "
                       "either restore the inputs or declare the reduced model as a different configuration.",
                priority="high", inputs=["rules", "signals"] + (["fundamentals"] if in_fund else []))
    else:
        res.add("input_sufficiency", BLOCK, PASS, "Every scored name had the declared minimum of inputs",
                f"{int(t['scored'].sum())} scored rows in {len(per)} periods; minimum share {min_share:g} of "
                f"{len(req)} inputs respected.", per[:20], proc,
                inputs=["rules", "signals"] + (["fundamentals"] if in_fund else []))
