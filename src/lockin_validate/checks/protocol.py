"""Research protocol integrity (0.2.0, family 2).

Check id: protocol_integrity. Inputs: run_log.csv (timestamp, run_id, window_start, window_end, config_hash, purpose)
and protocol.yaml (train / validation / test windows; ``reserved`` list of further single-use windows).

A reserved window (the test window, single-use by default, and every entry of ``reserved``) loses its value as an
out-of-sample test as soon as it informs a decision. From the run log this is unambiguous when (a) a run whose
purpose is train, validation or diagnostic touches it, or (b) more than one configuration was evaluated on it (a
"reproduction" counts as a reproduction only when it re-runs a configuration that was already tested on that window).
Development that continues after the first test look, and validation looks that exceed the declared number of trials,
are review items. When n_trials is not declared, the number of validation configurations is passed to the deflated
Sharpe as the number of trials.

Motivation (LockIn case study): the difference between a reproduction and a new look was not recorded, and diagnostic
runs over a later window contaminated the window proposed as the next fresh holdout.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..findings import CONFIRMED_ERROR, INFO, NEEDS_REVIEW, PASS, AuditResult
from ..inputs import Package
from . import missing_inputs, not_executable

BLOCK = "statistics"
PURPOSES = {"train", "validation", "test", "reproduction", "diagnostic"}
CONTAMINATING = {"train", "validation", "diagnostic", "other"}


def _d(x: Any) -> date | None:
    if x is None:
        return None
    try:
        return pd.Timestamp(str(x)).date()
    except (ValueError, TypeError):
        return None


def windows(pkg: Package) -> dict[str, dict[str, Any]]:
    """{name: {start, end, single_use}} from protocol.yaml (train, validation, test and every reserved entry)."""
    p = pkg.protocol or {}
    out: dict[str, dict[str, Any]] = {}
    for k in ("train", "validation", "test"):
        w = p.get(k)
        if isinstance(w, dict) and _d(w.get("start")) and _d(w.get("end")):
            out[k] = {"start": _d(w["start"]), "end": _d(w["end"]),
                      "single_use": bool(w.get("single_use", k == "test")), "reserved": k == "test"}
    for i, w in enumerate(p.get("reserved") or []):
        if isinstance(w, dict) and _d(w.get("start")) and _d(w.get("end")):
            out[str(w.get("name") or f"reserved_{i + 1}")] = {"start": _d(w["start"]), "end": _d(w["end"]),
                                                              "single_use": bool(w.get("single_use", True)),
                                                              "reserved": True}
    return out


def out_of_sample_start(pkg: Package) -> tuple[date | None, date | None, str]:
    """(start, end, source) of the out-of-sample window: protocol.yaml test, else conventions.oos_start."""
    w = windows(pkg).get("test")
    if w:
        return w["start"], w["end"], "protocol.yaml test window"
    v = _d(pkg.conv("oos_start"))
    return v, None, "rules.yaml conventions.oos_start" if v else "-"


def declared_trials(pkg: Package) -> int | None:
    v = (pkg.declared or {}).get("n_trials")
    if v is None and pkg.rules and isinstance(pkg.rules.get("research"), dict):
        v = pkg.rules["research"].get("n_trials")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def check_protocol(pkg: Package, res: AuditResult) -> None:
    title = "Research protocol integrity (single-use windows)"
    miss = pkg.missing("protocol_integrity")
    if miss:
        missing_inputs(res, "protocol_integrity", BLOCK, title, miss)
        return
    ws = windows(pkg)
    reserved = {k: v for k, v in ws.items() if v["reserved"]}
    if not reserved:
        not_executable(res, "protocol_integrity", BLOCK, title,
                       "protocol.yaml declares no test window and no reserved window (start and end)")
        return
    log = pkg.df("run_log").dropna(subset=["timestamp", "window_start", "window_end"]).sort_values(["timestamp", "row"])
    runs = []
    for r in log.itertuples():
        purpose = str(r.purpose or "").strip().lower()
        runs.append({"row": int(r.row), "timestamp": r.timestamp, "run_id": getattr(r, "run_id", None),
                     "start": r.window_start.date(), "end": r.window_end.date(),
                     "config": str(r.config_hash), "purpose": purpose if purpose in PURPOSES else "other"})
    violations: list[dict[str, Any]] = []
    first_test_look = None
    for name, w in reserved.items():
        touching = [x for x in runs if x["start"] <= w["end"] and x["end"] >= w["start"]]
        tested: set[str] = set()
        looks: list[str] = []
        for x in touching:
            ev = {"window": name, "row": x["row"], "run_id": x["run_id"], "timestamp": x["timestamp"],
                  "config_hash": x["config"], "purpose": x["purpose"],
                  "run_window": f"{x['start']} to {x['end']}", "reserved_window": f"{w['start']} to {w['end']}"}
            if x["purpose"] in CONTAMINATING:
                violations.append({**ev, "violation": f"{x['purpose']} run touches the reserved window {name}"})
                looks.append(x["config"])
            elif x["purpose"] == "reproduction" and x["config"] not in tested:
                violations.append({**ev, "violation": f"'reproduction' of config {x['config']} that was never tested on "
                                                      f"{name}: it is a new look"})
                looks.append(x["config"])
            elif x["purpose"] == "test":
                if name == "test" and first_test_look is None:
                    first_test_look = x["timestamp"]
                if tested and x["config"] not in tested:
                    violations.append({**ev, "violation": f"second configuration ({x['config']}) evaluated on {name} "
                                                          f"after {', '.join(sorted(tested))}: selection on the "
                                                          "reserved window"})
                tested.add(x["config"])
                looks.append(x["config"])
        w["distinct_configs_looked"] = sorted(set(looks))
    # development after the first test look
    changed = []
    if first_test_look is not None:
        before = {x["config"] for x in runs if x["timestamp"] < first_test_look}
        for x in runs:
            if x["timestamp"] > first_test_look and x["purpose"] in ("train", "validation") and x["config"] not in before:
                changed.append({"row": x["row"], "run_id": x["run_id"], "timestamp": x["timestamp"],
                                "config_hash": x["config"], "purpose": x["purpose"],
                                "first_test_look": first_test_look})
    n_val = len({x["config"] for x in runs if x["purpose"] == "validation"})
    n_decl = declared_trials(pkg)
    res.metrics["protocol"] = {"windows": {k: {kk: str(vv) if isinstance(vv, date) else vv for kk, vv in v.items()}
                                           for k, v in ws.items()},
                               "runs": len(runs), "validation_configs": n_val, "declared_n_trials": n_decl,
                               "first_test_look": first_test_look, "violations": len(violations)}
    proc = ("Each run of run_log.csv is matched to the windows of protocol.yaml by overlap of [window_start, "
            "window_end]. On a reserved window (test, single-use by default, and every `reserved` entry): a train, "
            "validation, diagnostic or unknown-purpose run is contamination; a test run of a second configuration is "
            "selection on the window; a 'reproduction' is accepted only if its config_hash was already tested on that "
            "window. Development after the first test look = train or validation runs of configurations not seen "
            "before it. Validation looks = distinct configurations with purpose validation.")
    single = all(reserved[v["window"]]["single_use"] for v in violations) if violations else True
    if violations:
        wins = sorted({v["window"] for v in violations})
        cfgs = sorted({v["config_hash"] for v in violations})
        status = CONFIRMED_ERROR if single else NEEDS_REVIEW
        res.add("protocol_integrity", BLOCK, status,
                f"Reserved window(s) {', '.join(wins)} used more than once ({len(violations)} runs)",
                f"Configurations involved: {', '.join(cfgs)}. "
                + ("The protocol declares these windows single-use: " if single else "")
                + "after these runs the window no longer measures out-of-sample performance; any result on it is "
                  "in-sample for the configurations that saw it.",
                violations, proc,
                action="Declare a new, untouched window for the final test and log every run with its purpose; "
                       "report the contaminated window as in-sample.", priority="high",
                inputs=["run_log", "protocol"])
    if changed:
        res.add("protocol_integrity", BLOCK, NEEDS_REVIEW,
                f"Development continued after the first look at the test window ({len(changed)} runs)",
                "New configurations (" + ", ".join(sorted({c['config_hash'] for c in changed})) + ") were trained or "
                "validated after the test window had been seen: their design may embed what the test showed.",
                changed, proc, action="Treat configurations created after the test look as untested.",
                priority="medium", inputs=["run_log", "protocol"])
    if n_decl is not None and n_val > n_decl:
        res.add("protocol_integrity", BLOCK, NEEDS_REVIEW,
                f"Validation looks ({n_val} configurations) exceed the declared number of trials ({n_decl})",
                "Every configuration evaluated on the validation window is a trial for the deflated Sharpe; the "
                "declared number is too small.", [{"validation_configs": n_val, "declared_n_trials": n_decl}], proc,
                action="Declare n_trials >= the number of validation configurations.", priority="medium",
                inputs=["run_log", "declared_results", "rules"])
    elif n_decl is None and n_val >= 2:
        res.add("protocol_integrity", BLOCK, INFO,
                f"n_trials not declared: the {n_val} validation configurations are used as the number of trials",
                "The deflated Sharpe and the multiple-testing haircut use N = max(declared, trials.csv columns, "
                "validation configurations of run_log.csv).", [{"validation_configs": n_val}], proc,
                inputs=["run_log"])
    if not violations and not changed and not (n_decl is not None and n_val > n_decl):
        res.add("protocol_integrity", BLOCK, PASS, "Reserved windows used once according to the run log",
                f"{len(runs)} runs; reserved windows: "
                + "; ".join(f"{k} ({v['start']} to {v['end']}): configs {', '.join(v['distinct_configs_looked']) or 'none'}"
                            for k, v in reserved.items())
                + ". Scope: runs that were logged; an unlogged run cannot be seen.",
                [{"window": k, "start": v["start"], "end": v["end"], "configs_looked": v["distinct_configs_looked"]}
                 for k, v in reserved.items()], proc, inputs=["run_log", "protocol"])
