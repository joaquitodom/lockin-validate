"""Frozen runtime dependencies, separation between code and oracles, and repository hygiene."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lockin_validate"


def _deps() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies = \[(.*?)\]", text, re.S | re.M).group(1)
    return sorted(re.split(r"[<>=!~ ]", d.strip().strip('",'))[0].lower() for d in block.split(",") if d.strip())


def test_runtime_dependencies():
    assert _deps() == ["numpy", "pandas", "pyyaml"]
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "empyrical-reloaded" in text and 'mcp = ["mcp' in text


def test_code_imports_no_oracle_network_or_remote_ai():
    for p in SRC.rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        for bad in ("import empyrical", "import requests", "import urllib", "import http", "import socket",
                    "anthropic", "openai", "httpx", "telemetry"):
            assert bad not in t, (p.name, bad)


def test_oracles_and_generators_do_not_import_the_package():
    files = list((ROOT / "tests" / "oracle").rglob("*.py")) + list((ROOT / "cases" / "_generators").glob("*.py"))
    assert files
    for p in files:
        t = p.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+lockin_validate", t, re.M), p.name
        assert "importlib" not in t, p.name


SPANISH = re.compile(r"\b(fecha|senal|señal|operaciones|precios|alerta|correcto|revision|informe|efectivo|"
                     r"conciliacion|costos|reglas|insumos|esperado|compra|venta|hallazgo)\b", re.I)


def test_no_spanish_leftovers_in_code_cases_and_docs():
    paths = list(SRC.rglob("*.py")) + list((ROOT / "cases").rglob("*.py")) + list((ROOT / "cases").rglob("*.json")) \
        + list((ROOT / "cases").rglob("*.yaml")) + list((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]
    for p in paths:
        if p.name in ("CASE_CHANGES.md",):  # documents the translation, quotes original names on purpose
            continue
        t = p.read_text(encoding="utf-8")
        m = SPANISH.search(t)
        assert m is None, (str(p.relative_to(ROOT)), m.group(0) if m else None)


def test_no_secrets_or_vendor_data():
    bad_names = [p for p in ROOT.rglob("*") if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts
                 and (p.name.startswith(".env") or p.suffix in (".pem", ".key", ".parquet", ".db", ".sqlite"))]
    assert bad_names == []
    pattern = re.compile(r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|tiingo|yfinance|api[_-]?key\s*=)", re.I)
    for p in list(SRC.rglob("*")) + list((ROOT / "cases").rglob("*")) + list((ROOT / "examples").rglob("*")):
        if p.is_file() and p.suffix in (".py", ".csv", ".json", ".yaml", ".md", ".txt"):
            assert not pattern.search(p.read_text(encoding="utf-8", errors="ignore")), p.name
