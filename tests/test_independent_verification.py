"""Independent verification: specification, oracles and code kept apart.

- Specification: docs/CONVENTIONS.md.
- Oracle 1: hand-computed case (tests/oracle/hand_case), values from the definitions with exact arithmetic.
- Oracle 2: tests/oracle/oracle.py (pure Python, does not import lockin_validate).
- Oracle 3: empyrical-reloaded (external library, development dependency only) for Sharpe, annual return, max DD.
- Metamorphic tests: input transformations that must NOT change the result (or change it in a known way).
"""

from __future__ import annotations

import csv
import json
import math
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "oracle"))
from lockin_validate import audit, stats  # noqa: E402
from lockin_validate import metrics as M  # noqa: E402
from lockin_validate.inputs import read_package  # noqa: E402
from lockin_validate.reconstruction import reconstruct  # noqa: E402
from oracle import (  # noqa: E402
    expected_max_oracle,
    lo_eta_oracle,
    metrics_oracle,
    min_trl_oracle,
    moments_oracle,
    nav_oracle,
    psr_oracle,
)

empyrical = pytest.importorskip("empyrical")

HAND = HERE / "oracle" / "hand_case"
CORE = HERE.parent / "cases" / "core"
KEYS = ("total_return", "annual_return", "sharpe", "max_drawdown", "final_nav")


def _ledger():
    with open(HAND / "expected_ledger.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _expected_metrics():
    with open(HAND / "expected_metrics.csv", encoding="utf-8") as f:
        return {r["metric"]: float(r["value"]) for r in csv.DictReader(f)}


def _empyrical(navs):
    r = np.diff(np.asarray(navs, dtype=float)) / np.asarray(navs[:-1], dtype=float)
    return {"total_return": float(empyrical.cum_returns_final(r)), "annual_return": float(empyrical.annual_return(r)),
            "sharpe": float(empyrical.sharpe_ratio(r)), "max_drawdown": float(empyrical.max_drawdown(r))}


def test_hand_case_oracle():
    out = nav_oracle(HAND)
    led = _ledger()
    assert len(out["rows"]) == len(led)
    for row, exp in zip(out["rows"], led):
        assert row["date"].isoformat() == exp["date"]
        for k in ("cash", "positions_value", "nav"):
            assert row[k] == pytest.approx(float(exp[k]), abs=1e-9)
    m = metrics_oracle([r["nav"] for r in out["rows"]])
    e = _expected_metrics()
    for k in KEYS:
        assert m[k] == pytest.approx(e[k], abs=1e-12), k
    assert out["n_trades"] == e["n_trades"] and out["total_costs"] == pytest.approx(e["total_costs"])


def test_hand_case_empyrical():
    e = _expected_metrics()
    emp = _empyrical([float(p["nav"]) for p in _ledger()])
    for k in ("total_return", "annual_return", "sharpe", "max_drawdown"):
        assert emp[k] == pytest.approx(e[k], abs=1e-10), k


def test_hand_case_package():
    rec = reconstruct(read_package(HAND))
    led = _ledger()
    assert [d.isoformat() for d in rec.dates] == [p["date"] for p in led]
    for nav, cash, val, exp in zip(rec.nav, rec.cash, rec.positions_value, led):
        assert cash == pytest.approx(float(exp["cash"]), abs=1e-9)
        assert val == pytest.approx(float(exp["positions_value"]), abs=1e-9)
        assert nav == pytest.approx(float(exp["nav"]), abs=1e-9)
    calc = M.compute(rec.nav, rec.dates, None, n_trades=len(rec.trades))
    e = _expected_metrics()
    for k in KEYS:
        assert calc[k] == pytest.approx(e[k], abs=1e-12), k
    assert calc["n_trades"] == e["n_trades"] and rec.total_costs == pytest.approx(e["total_costs"])


def test_return_base_is_initial_cash():
    """Analytic case where the two bases differ by more than the tolerance."""
    rt = M.total_return(reconstruct(read_package(HAND)).nav)
    assert rt == pytest.approx(997.5 / 1000 - 1)
    assert abs(rt - (997.5 / 998.5 - 1)) > 0.0014


@pytest.mark.parametrize("case", ["01_clean", "02_duplicates", "04_omitted_costs", "07_metric_error",
                                  "09_lockin_style", "10_independent"])
def test_package_vs_oracle_vs_empyrical(case):
    folder = CORE / case
    ind = nav_oracle(folder)
    res = audit(folder)
    rows = res.metrics["reconstructed_nav"]
    assert len(rows) == len(ind["rows"])
    for a, b in zip(rows, ind["rows"]):
        assert a["date"] == b["date"].isoformat()
        assert a["nav"] == pytest.approx(b["nav"], rel=1e-10)
        assert a["cash"] == pytest.approx(b["cash"], rel=1e-10, abs=1e-6)
    navs = [r["nav"] for r in ind["rows"]]
    mi, me = metrics_oracle(navs), _empyrical(navs)
    mp = res.metrics["reconstructed_metrics"]
    for k in KEYS:
        assert mp[k] == pytest.approx(mi[k], rel=1e-9, abs=1e-12), k
    for k in ("total_return", "annual_return", "sharpe", "max_drawdown"):
        assert mp[k] == pytest.approx(me[k], rel=1e-8, abs=1e-10), k
    assert mp["n_trades"] == ind["n_trades"]


def test_declared_results_of_clean_case_match_oracle():
    folder = CORE / "01_clean"
    decl = json.loads((folder / "declared_results.json").read_text(encoding="utf-8"))
    ind = nav_oracle(folder)
    mi = metrics_oracle([r["nav"] for r in ind["rows"]])
    for k in ("total_return", "sharpe", "max_drawdown"):
        assert decl[k] == pytest.approx(mi[k], abs=1e-5), k
    assert decl["n_trades"] == ind["n_trades"]


def test_statistics_vs_oracle():
    rng = np.random.default_rng(9)
    r = list(rng.standard_t(5, 800) * 0.01 + 0.0005)
    T, mu, sd, skew, kurt = moments_oracle(r)
    m = stats.moments(r)
    assert m["skew"] == pytest.approx(skew, rel=1e-9) and m["kurt"] == pytest.approx(kurt, rel=1e-9)
    sr = mu / sd
    assert stats.probabilistic_sharpe(sr, 0.01, T, skew, kurt) == pytest.approx(psr_oracle(sr, 0.01, T, skew, kurt))
    assert stats.min_track_record_length(sr, 0.0, skew, kurt) == pytest.approx(min_trl_oracle(sr, 0.0, skew, kurt))
    assert stats.expected_max_sharpe(0.002, 37) == pytest.approx(expected_max_oracle(0.002, 37))
    rho = stats.autocorrelations(r, 10)
    assert stats.lo_annualisation_factor(rho, 252) == pytest.approx(lo_eta_oracle(rho, 252))


# ---------------------------------------------------------------------------- metamorphic tests

def _read(p: Path):
    with open(p, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def _write(p: Path, cols, rows):
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _copy(tmp_path: Path, case: str = "01_clean") -> Path:
    d = tmp_path / case
    shutil.copytree(CORE / case, d)
    return d


def _nav(folder: Path) -> list[float]:
    return reconstruct(read_package(folder)).nav


def test_metamorphic_price_row_order(tmp_path):
    d = _copy(tmp_path)
    base = _nav(d)
    cols, rows = _read(d / "prices.csv")
    random.Random(7).shuffle(rows)
    _write(d / "prices.csv", cols, rows)
    assert _nav(d) == pytest.approx(base, rel=1e-12)


def test_metamorphic_capital_scale(tmp_path):
    """Doubling initial cash, quantities and commissions doubles the NAV and leaves returns unchanged."""
    d = _copy(tmp_path)
    base = _nav(d)
    rules = yaml.safe_load((d / "rules.yaml").read_text(encoding="utf-8"))
    rules["conventions"]["initial_cash"] *= 2
    (d / "rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")
    cols, rows = _read(d / "trades.csv")
    for f in rows:
        f["quantity"] = str(float(f["quantity"]) * 2)
        f["commission"] = str(float(f["commission"]) * 2)
    _write(d / "trades.csv", cols, rows)
    new = _nav(d)
    assert new == pytest.approx([2 * x for x in base], rel=1e-10)
    assert M.sharpe(new) == pytest.approx(M.sharpe(base), rel=1e-9)


def test_metamorphic_untraded_asset(tmp_path):
    d = _copy(tmp_path)
    base = _nav(d)
    cols, rows = _read(d / "prices.csv")
    extra = [dict(f, ticker="ZZZ", close=str(float(f["close"]) * 3)) for f in rows if f["ticker"] == "AAA"]
    _write(d / "prices.csv", cols, rows + extra)
    assert _nav(d) == pytest.approx(base, rel=1e-12)


def test_metamorphic_price_unit_change(tmp_path):
    """Prices x 4 and quantities / 4: same NAV (unit change, e.g. an adjusted split)."""
    d = _copy(tmp_path)
    base = _nav(d)
    cols, rows = _read(d / "prices.csv")
    for f in rows:
        for c in ("open", "high", "low", "close"):
            f[c] = str(float(f[c]) * 4)
    _write(d / "prices.csv", cols, rows)
    cols, tr = _read(d / "trades.csv")
    for f in tr:
        f["price"] = str(float(f["price"]) * 4)
        f["quantity"] = str(float(f["quantity"]) / 4)
    _write(d / "trades.csv", cols, tr)
    assert _nav(d) == pytest.approx(base, rel=1e-10)


def test_metamorphic_extra_commission_lowers_final_nav_exactly(tmp_path):
    d = _copy(tmp_path)
    base = _nav(d)
    cols, tr = _read(d / "trades.csv")
    tr[0]["commission"] = str(float(tr[0]["commission"]) + 100)
    _write(d / "trades.csv", cols, tr)
    new = _nav(d)
    assert new[0] == pytest.approx(base[0])
    assert new[-1] == pytest.approx(base[-1] - 100, abs=1e-6)


def test_metamorphic_doubling_costs_never_raises_net_result(tmp_path):
    d = _copy(tmp_path)
    base = _nav(d)[-1]
    cols, tr = _read(d / "trades.csv")
    for f in tr:
        f["commission"] = str(float(f["commission"]) * 2)
    _write(d / "trades.csv", cols, tr)
    assert _nav(d)[-1] <= base


def test_metamorphic_returns_shuffle_keeps_sharpe_and_psr(tmp_path):
    rng = np.random.default_rng(3)
    r = rng.normal(0.0005, 0.01, 500)
    s = rng.permutation(r)
    assert stats.sharpe(r) == pytest.approx(stats.sharpe(s))
    m1, m2 = stats.moments(r), stats.moments(s)
    a = stats.probabilistic_sharpe(stats.sharpe(r), 0, 500, m1["skew"], m1["kurt"])
    b = stats.probabilistic_sharpe(stats.sharpe(s), 0, 500, m2["skew"], m2["kurt"])
    assert a == pytest.approx(b) and not math.isnan(a)
