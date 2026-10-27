"""Orchestrator: runs every block over an input folder and returns an AuditResult.

No network call and no remote AI: only local file reads, computation and templates.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .checks.data_integrity import run_data_checks
from .checks.llm_lookahead import check_llm_lookahead
from .checks.point_in_time import check_lookahead, check_pit_fundamentals
from .checks.statistics import run_statistics, strategy_returns
from .checks.strategy import check_metrics, check_omitted_costs, check_rules
from .checks.universe import check_survivorship, check_ticker_identity
from .findings import NEEDS_REVIEW, NOT_EXECUTABLE, AuditResult
from .inputs import REQUIREMENTS, read_package, validate_schema
from .reconciliation import check_positions, check_reconstruction, check_results
from .report import write_reports

log = logging.getLogger("lockin_validate")

DISCLAIMER = (
    "This is an automated, offline technical review of the inputs delivered. It makes no claim about future or past "
    "profitability, it is not a certification or an audit opinion, and it is not an independent professional "
    "approval: a qualified person must review the findings, the NEEDS_REVIEW items and the limitations before any "
    "decision. It is not investment advice."
)

FIXED_LIMITATIONS = [
    "The review judges the internal coherence of the inputs delivered. It does not query external sources: a wrong "
    "price that is coherent with everything else is not detected (unless reference_prices.csv is provided).",
    "The reconstruction starts from the initial cash, values at the close and uses the trades as delivered (executed "
    "price and commission of trades.csv). Declared costs are not imputed in the main reconstruction: they are "
    "contrasted in omitted_costs. Dividends, splits and other corporate actions are not modelled unless they are in "
    "adjusted prices; large jumps are flagged.",
    "A results curve alone does not validate the code, the execution or the absence of look-ahead: reproducing the "
    "declared NAV only proves the delivered trades are coherent with that NAV.",
    "rules_vs_implementation re-ranks the signal column delivered: it verifies the selection, not how the signal was "
    "computed. lookahead trusts the declared data_date; the hint test (correlation with the subsequent return) only "
    "detects gross cases.",
    "Rule re-execution supports only: ranking on one signal column, top N, periodic rebalance (monthly, weekly, daily) "
    "and equal weights. Any other rule is NOT_EXECUTABLE and needs a manual review.",
    "Statistical checks (PSR, deflated Sharpe, haircut, PBO) are conditional on the declared number of trials and on "
    "the data being correct; they say nothing about broken data or look-ahead.",
    "The LLM look-ahead score rests on declarations; memorisation is not tested.",
    "What is missing from the inputs (history, availability timestamps, universe, identity master) is a scope finding: "
    "it is never repaired or imputed.",
    "Thresholds and tolerances are documented choices, not laws; they are listed in docs/CONVENTIONS.md and can be "
    "changed in rules.yaml.",
]


def _diff_manifest(old: dict, new: dict) -> list[dict[str, Any]]:
    out = []
    of, nf = old.get("files", {}), new.get("files", {})
    for k in sorted(set(of) | set(nf)):
        a, b = of.get(k, {}), nf.get(k, {})
        if a.get("sha256") != b.get("sha256"):
            out.append({"input": k, "previous_sha256": (a.get("sha256") or "-")[:16],
                        "current_sha256": (b.get("sha256") or "-")[:16],
                        "previous_rows": a.get("rows"), "current_rows": b.get("rows")})
    return out


def audit(input_dir: str | Path, profile: str | None = None, today: date | None = None,
          previous_manifest: str | Path | dict | None = None) -> AuditResult:
    """Run the full review of one input folder and return the result (no files written)."""
    pkg = read_package(input_dir, profile)
    res = AuditResult()
    res.meta = {"tool": "lockin-validate", "tool_version": __version__,
                "run_at": datetime.now().isoformat(timespec="seconds"), "input_folder": Path(input_dir).name,
                "profile": pkg.profile["name"], "disclaimer": DISCLAIMER}
    res.manifest = pkg.manifest
    log.info("inputs read: %d tables", len(pkg.tables))

    validate_schema(pkg, res)
    run_data_checks(pkg, res, today)
    check_pit_fundamentals(pkg, res, today)
    check_survivorship(pkg, res)
    check_ticker_identity(pkg, res)
    rec = check_reconstruction(pkg, res)
    check_positions(pkg, res, rec)
    calc = check_results(pkg, res, rec)
    check_lookahead(pkg, res)
    check_omitted_costs(pkg, res, rec)
    check_metrics(pkg, res, rec, calc)
    check_rules(pkg, res, rec)
    run_statistics(pkg, res, rec)
    series = strategy_returns(pkg, rec)
    check_llm_lookahead(pkg, res, series.returns if series else None, series.dates if series else None)

    if previous_manifest is not None:
        old = previous_manifest if isinstance(previous_manifest, dict) else json.loads(
            Path(previous_manifest).read_text(encoding="utf-8"))
        old = old.get("manifest", old)
        changed = _diff_manifest(old, pkg.manifest)
        res.metrics["manifest_changes"] = changed
        if changed:
            res.add("schema_and_types", "input", NEEDS_REVIEW, "Inputs changed since the previous manifest",
                    f"{len(changed)} inputs have a different sha256 than in the previous run: results are not comparable "
                    "without knowing what changed.", changed, "sha256 of each input compared with the previous manifest.",
                    action="Document the change (new data vintage, correction) before comparing reports.",
                    priority="medium", inputs=[c["input"] for c in changed])

    res.transformations = pkg.log.to_list()
    present = [k for k, v in pkg.manifest["files"].items() if v.get("present")]
    absent = [k for k, v in pkg.manifest["files"].items() if not v.get("present")]
    cal = pkg.calendar()
    conv_sources = {}
    for k in ("calendar", "periods_per_year", "initial_cash", "stale_run", "jump_threshold", "review_date"):
        v, src = pkg.conv_with_source(k)
        conv_sources[k] = {"value": v, "source": src}
    res.scope = {
        "inputs_present": present,
        "inputs_absent": absent,
        "strategy_version": pkg.version,
        "profile": pkg.profile["name"],
        "calendar": {"name": cal.name, "declared": cal.declared, "declared_by": cal.declared_by,
                     "holidays_source": cal.source},
        "conventions_used": conv_sources,
        "requirements_per_check": REQUIREMENTS,
        "reconstruction_conventions": (res.metrics.get("reconstruction") or {}).get("conventions"),
        "review_date": str(pkg.conv("review_date") or (today or date.today())),
    }
    res.limitations = list(FIXED_LIMITATIONS)
    for f in res.by_status(NOT_EXECUTABLE):
        res.limitations.append(f"{f.check}: not executable ({f.reason}).")
    log.info("audit finished: %s", res.counts())
    return res


def run(input_dir: str | Path, out_dir: str | Path, profile: str | None = None, today: date | None = None,
        previous_manifest: str | Path | dict | None = None) -> tuple[AuditResult, dict[str, Path]]:
    """Audit and write the reports (REPORT.md, report.json, report.html) to ``out_dir``."""
    input_dir = Path(input_dir).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir == input_dir or input_dir in out_dir.parents:
        raise ValueError("the output folder cannot be inside the input folder (originals are opened read-only and are "
                         "never mixed with reports)")
    res = audit(input_dir, profile, today, previous_manifest)
    paths = write_reports(res, out_dir)
    return res, paths
