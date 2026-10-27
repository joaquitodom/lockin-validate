"""Benchmark battery: every case in cases/ against its expected.json (fixed before running the tool)."""

import json
from pathlib import Path

import pytest

from lockin_validate.cases import available_cases, per_check_table, run_case

ROOT = Path(__file__).resolve().parents[1] / "cases"
CASES = available_cases(ROOT)
CORE_CHECKS = ["schema_and_types", "duplicates", "dates", "essential_fields", "coverage", "trade_before_signal",
               "signal_data_after_decision", "stale_prices", "reconstruction", "positions_reconciliation",
               "results_reconciliation", "lookahead", "omitted_costs", "metrics", "rules_vs_implementation"]


def test_battery_composition():
    groups = {}
    for p in CASES:
        groups.setdefault(p.parent.parent.name, []).append(p.parent.name)
    assert len(groups["core"]) == 11  # 10 ported + the synthetic lockin-style replacement of case 09
    assert len(groups["adversarial"]) == 12
    assert len(groups["statistical"]) >= 5
    assert len(groups["data"]) >= 5
    assert "09_lockin_style" in groups["core"]


@pytest.mark.parametrize("expected", CASES, ids=[f"{p.parent.parent.name}/{p.parent.name}" for p in CASES])
def test_case(expected, tmp_path):
    out = run_case(expected, tmp_path)
    assert out["ok"], "\n".join(out["problems"])
    name = expected.parent.name
    for f in ("REPORT.md", "report.json", "report.html"):
        assert (tmp_path / name / f).exists()


def test_clean_case_has_no_false_positive(core):
    out = run_case(core / "01_clean" / "expected.json")
    assert out["false_positives"] == []
    assert out["counts"]["CONFIRMED_ERROR"] == 0
    js = json.loads((core / "01_clean" / "expected.json").read_text(encoding="utf-8"))
    assert {d["check"] for d in js["must_include"]} == set(CORE_CHECKS)


def test_per_check_table_counts():
    results = [run_case(p) for p in CASES if p.parent.name in ("01_clean", "02_duplicates", "S04_undeclared_trials")]
    rows = {r["check"]: r for r in per_check_table(results)}
    assert rows["duplicates"]["expected_detections"] == 1 and rows["duplicates"]["detected"] == 1
    assert rows["trials_declared"]["detection_rate"] == 1.0
    assert all(r["false_positives"] == 0 for r in rows.values())
