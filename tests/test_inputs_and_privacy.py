"""Partial input, read-only originals, separate output, transformation log and console privacy."""

import hashlib
import json
import shutil

import pytest

from lockin_validate import audit, run
from lockin_validate.cli import main
from lockin_validate.inputs import read_package


def _hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def test_manifest_sha256_and_rows(core):
    pkg = read_package(core / "01_clean")
    f = pkg.manifest["files"]
    assert f["prices"]["present"] and len(f["prices"]["sha256"]) == 64
    with open(core / "01_clean" / "prices.csv", encoding="utf-8") as fh:
        assert f["prices"]["rows"] == sum(1 for _ in fh) - 1
    assert f["fundamentals"]["present"] is False
    assert "expected.json" in pkg.manifest["unrecognised"]


def test_originals_untouched_and_output_separate(core, tmp_path):
    src = tmp_path / "inputs"
    shutil.copytree(core / "02_duplicates", src)
    before = _hashes(src)
    run(src, tmp_path / "out")
    assert _hashes(src) == before
    with pytest.raises(ValueError):
        run(src, src / "report")


def test_partial_package_runs_what_it_can(core, tmp_path):
    src = tmp_path / "partial"
    src.mkdir()
    shutil.copy(core / "01_clean" / "prices.csv", src / "prices.csv")
    res = audit(src)
    st = {c: res.status_of(c) for c in res.checks()}
    assert st["duplicates"] == "PASS"
    assert st["stale_prices"] == "PASS"
    for c in ["reconstruction", "results_reconciliation", "lookahead", "metrics", "rules_vs_implementation",
              "omitted_costs", "deflated_sharpe", "pbo", "survivorship", "pit_fundamentals", "llm_lookahead_risk"]:
        assert st[c] == "NOT_EXECUTABLE", c
    assert all(f.reason for f in res.by_status("NOT_EXECUTABLE"))


def test_never_pass_without_inputs(tmp_path):
    (tmp_path / "empty").mkdir()
    res = audit(tmp_path / "empty")
    assert res.by_status("PASS") == []
    assert res.by_status("CONFIRMED_ERROR") == []


def test_transformations_proposed_and_applied(core):
    res = audit(core / "02_duplicates")
    ops = [(t["operation"], t["applied"]) for t in res.transformations]
    assert ("drop_duplicates(ticker, date)", False) in ops  # proposed, NOT applied
    assert any(a for o, a in ops if o.startswith("first_occurrence"))  # applied and logged


def test_console_does_not_print_rows(core, tmp_path, capsys):
    code = main(["run", str(core / "02_duplicates"), "--out", str(tmp_path / "s")])
    assert code == 1
    out = capsys.readouterr()
    text = out.out + out.err
    lines = (core / "02_duplicates" / "prices.csv").read_text(encoding="utf-8").splitlines()[1:]
    for line in lines[:200]:
        assert line not in text
    assert "AAA" not in text  # not even tickers: only check ids and counts


def test_schema_errors(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    (d / "prices.csv").write_text("date,ticker,close\n2024-01-02,AAA,10\nnot-a-date,AAA,abc\n", encoding="utf-8")
    (d / "trades.csv").write_text("timestamp,ticker,quantity\n2024-01-02,AAA,1\n", encoding="utf-8")
    res = audit(d)
    titles = [f.title for f in res.findings if f.check == "schema_and_types"]
    assert any("required columns missing" in t for t in titles)
    assert any("unparseable dates" in t for t in titles)
    assert any("non-numeric" in t for t in titles)
    assert res.status_of("reconstruction") == "NOT_EXECUTABLE"


def test_aliases_are_logged(tmp_path, core):
    d = tmp_path / "alias"
    d.mkdir()
    text = (core / "01_clean" / "prices.csv").read_text(encoding="utf-8").replace("date,ticker", "Date,Symbol", 1)
    (d / "prices.csv").write_text(text, encoding="utf-8")
    res = audit(d)
    assert any(t["operation"] == "rename_columns" for t in res.transformations)
    assert res.status_of("duplicates") == "PASS"


def test_report_json_has_evidence_and_procedure(core, tmp_path):
    _, paths = run(core / "10_independent", tmp_path / "s")
    js = json.loads(paths["json"].read_text(encoding="utf-8"))
    errors = [f for f in js["findings"] if f["status"] == "CONFIRMED_ERROR"]
    assert errors
    for f in errors:
        assert f["evidence"] and f["procedure"] and f["action"]
    ev = errors[0]["evidence"][0]
    assert {"date", "ticker", "declared", "reconstructed"} <= set(ev)
    assert "disclaimer" in js["meta"] and "not an independent professional approval" in js["meta"]["disclaimer"]


def test_report_sections_and_static_html(core, tmp_path):
    _, paths = run(core / "04_omitted_costs", tmp_path / "s")
    md = paths["markdown"].read_text(encoding="utf-8")
    for s in ["## Scope", "## Inputs and versions (manifest)", "## Checks run", "## Confirmed errors",
              "## Items that need human review", "## Checks not executable (missing information)",
              "## Passed within scope", "## Transformation log", "## Limitations and pending human review",
              "## Suggested actions (prioritised)", "Disclaimer"]:
        assert s in md, s
    html = paths["html"].read_text(encoding="utf-8")
    assert "<script" not in html.lower() and "omitted_costs" in html


def test_previous_manifest_detects_silent_change(core, tmp_path):
    src = tmp_path / "in"
    shutil.copytree(core / "01_clean", src)
    _, paths = run(src, tmp_path / "r1")
    p = src / "prices.csv"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    res = audit(src, previous_manifest=paths["json"])
    assert any(f.title.startswith("Inputs changed") for f in res.findings)
