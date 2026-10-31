"""Tool functions behind the MCP server (no dependency on ``mcp``, so they can be tested)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .auditor import audit, run
from .catalog import CHECKS, explain
from .findings import PASS
from .inputs import InputError


def run_tool(input_dir: str, out_dir: str | None = None, profile: str | None = None,
             include_report: bool = False, max_findings: int = 40) -> dict[str, Any]:
    """Review a local input folder; optionally write the reports to out_dir. Returns a compact summary."""
    try:
        if out_dir:
            res, paths = run(input_dir, out_dir, profile=profile)
        else:
            res, paths = audit(input_dir, profile=profile), {}
    except (InputError, ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}
    findings = [{"check": f.check, "status": f.status, "title": f.title, "priority": f.priority,
                 "reason": f.reason or None, "n_evidence": f.n_evidence}
                for f in res.findings if f.status != PASS][:max_findings]
    out: dict[str, Any] = {"counts": res.counts(),
                           "checks": [{"check": c, "status": res.status_of(c)} for c in res.checks()],
                           "findings": findings, "disclaimer": res.meta.get("disclaimer"),
                           "reports": {k: str(v) for k, v in paths.items()}}
    if include_report:
        from .report import render_markdown
        out["report_markdown"] = render_markdown(res)
    return out


def explain_tool(check_id: str) -> dict[str, Any]:
    return explain(check_id)


def list_checks_tool() -> dict[str, Any]:
    return {k: {"block": v["block"], "title": v["title"]} for k, v in CHECKS.items()}


def list_use_cases_tool() -> list[dict[str, Any]]:
    """The use-case modules (what each validates, who it is for, inputs and checks)."""
    from . import usecases

    usecases.load_all()
    return usecases.describe()


def _exists(p: str) -> bool:
    return Path(p).exists()
