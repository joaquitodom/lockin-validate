"""Expectation changes of release 0.2.0, applied by every generator after it writes its cases.

Does NOT import lockin_validate. Each entry adds a must_include item to an existing case; the justification of every
entry is in docs/CASE_CHANGES.md ("0.2.0: review items that cases now expect") and the policy that classified the
review item as a genuine signal is in docs/ALERT_POLICY.md. Nothing is removed and no status is relaxed: every
detection expected before 0.2.0 is still expected. Every added entry carries ``"post_hoc": true``: it was written after
the tool's output was seen, so the battery reports it apart from the pre-registered detections (0.2.1).
"""

from __future__ import annotations

import json
from pathlib import Path

REVIEW = ["NEEDS_REVIEW"]

ADDED: dict[str, list[dict]] = {
    # P6: zero cost with turnover is a genuine review item in every case that trades without any cost.
    "R04_lookahead_fundamentals": [{"check": "omitted_costs", "status": REVIEW}],
    "R05_undeclared_lookahead": [{"check": "omitted_costs", "status": REVIEW}],
    "R06_undeclared_short": [{"check": "omitted_costs", "status": REVIEW},
                             {"check": "sharpe_significance", "status": REVIEW}],
    "R07_undeclared_leverage": [{"check": "omitted_costs", "status": REVIEW}],
    "R10_unadjusted_split": [{"check": "omitted_costs", "status": REVIEW},
                             {"check": "price_jumps", "status": REVIEW}],
    "R11_byma_calendar_undeclared": [{"check": "omitted_costs", "status": REVIEW},
                                     {"check": "dates", "status": REVIEW}],
    "R13_unrecognised_results": [{"check": "omitted_costs", "status": REVIEW}],
    # P2: a cost test that does not discriminate stays a review item (as core case 10 already expected).
    "R00_clean": [{"check": "omitted_costs", "status": REVIEW}],
    # P1: positive Sharpe whose minimum track record is more than twice the history.
    "R03_first_day_commission": [{"check": "sharpe_significance", "status": REVIEW}],
    "04_omitted_costs": [{"check": "sharpe_significance", "status": REVIEW}],
    "08_rules_vs_implementation": [{"check": "sharpe_significance", "status": REVIEW}],
    "10_independent": [{"check": "sharpe_significance", "status": REVIEW}],
    # P7 footprints of core 05 (coverage) and D03 (coverage, price_jumps) were withdrawn in 0.2.1: they are the same
    # evidence another check already judges (rule 1 of docs/ALERT_POLICY.md), so they are not counted as detections.
    # P4: statistical review items that follow from the planted search.
    "S04_undeclared_trials": [{"check": "deflated_sharpe", "status": REVIEW},
                              {"check": "multiple_testing", "status": REVIEW},
                              {"check": "pbo", "status": REVIEW}],
    "S05_overfit_search_undeclared": [{"check": "multiple_testing", "status": REVIEW}],
    "S07_short_track_record": [{"check": "trials_declared", "status": REVIEW}],
}


def apply(root: Path) -> int:
    """Append the 0.2.0 expectations to the cases under ``root``; returns the number of cases changed."""
    n = 0
    for name, entries in ADDED.items():
        p = root / name / "expected.json"
        if not p.exists():
            continue
        exp = json.loads(p.read_text(encoding="utf-8"))
        have = {(d["check"], tuple(d["status"])) for d in exp.get("must_include", [])}
        add = [{**e, "post_hoc": True} for e in entries if (e["check"], tuple(e["status"])) not in have]
        if not add:
            continue
        exp.setdefault("must_include", []).extend(add)
        exp["expectation_changes"] = "0.2.0: " + ", ".join(e["check"] for e in entries) + \
            " added (docs/CASE_CHANGES.md, docs/ALERT_POLICY.md)"
        p.write_text(json.dumps(exp, indent=2, ensure_ascii=False), encoding="utf-8")
        n += 1
    return n
