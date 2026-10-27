"""CLI subcommands, scaffold template and MCP tool functions."""

import json

import pytest

from lockin_validate import audit
from lockin_validate.catalog import CHECKS
from lockin_validate.cli import main
from lockin_validate.inputs import REQUIREMENTS
from lockin_validate.tools import explain_tool, list_checks_tool, run_tool


def test_catalog_covers_every_check_run(core):
    res = audit(core / "01_clean")
    assert set(res.checks()) <= set(CHECKS)
    assert set(REQUIREMENTS) == set(CHECKS)
    for v in CHECKS.values():
        assert v["what"] and v["why"] and v["fix"]


def test_explain(capsys):
    assert main(["explain", "deflated_sharpe"]) == 0
    out = capsys.readouterr().out
    assert "Bailey" in out and "Required inputs" in out
    assert main(["explain", "nope"]) == 2


def test_checks_list(capsys):
    assert main(["checks"]) == 0
    assert "pbo" in capsys.readouterr().out


def test_init_scaffold_runs(tmp_path, capsys):
    d = tmp_path / "pkg"
    assert main(["init", str(d)]) == 0
    for f in ("prices.csv", "trades.csv", "rules.yaml", "declared_results.json", "README_INPUTS.md"):
        assert (d / f).exists()
    assert main(["init", str(d)]) == 2  # refuses a non-empty folder
    code = main(["run", str(d), "--out", str(tmp_path / "out")])
    assert code in (0, 1)
    assert (tmp_path / "out" / "REPORT.md").exists()


def test_run_exit_codes(core, tmp_path):
    assert main(["run", str(core / "01_clean"), "--out", str(tmp_path / "a")]) == 0
    assert main(["run", str(core / "02_duplicates"), "--out", str(tmp_path / "b")]) == 1
    assert main(["run", str(tmp_path / "missing"), "--out", str(tmp_path / "c")]) == 2


def test_cases_subcommand(cases, tmp_path, capsys):
    code = main(["cases", "--dir", str(cases / "data"), "--json", str(tmp_path / "b.json")])
    assert code == 0
    js = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert js["per_check"] and all(c["ok"] for c in js["cases"])


def test_mcp_tool_functions(core, tmp_path):
    out = run_tool(str(core / "02_duplicates"), str(tmp_path / "o"))
    assert out["counts"]["CONFIRMED_ERROR"] >= 1 and out["reports"]["markdown"].endswith("REPORT.md")
    assert any(f["check"] == "duplicates" for f in out["findings"])
    assert "error" in run_tool(str(tmp_path / "missing"))
    assert explain_tool("pbo")["block"] == "statistics"
    assert "lookahead" in list_checks_tool()


def test_mcp_server_builds():
    pytest.importorskip("mcp")
    from lockin_validate.mcp_server import build_server
    assert build_server() is not None
