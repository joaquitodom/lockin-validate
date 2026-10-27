"""Checks, grouped by block. Each check function takes (Package, AuditResult, ...) and adds findings."""

from __future__ import annotations

from ..findings import NOT_EXECUTABLE, AuditResult


def not_executable(res: AuditResult, check: str, block: str, title: str, reason: str, action: str = "",
                   priority: str = "medium", evidence: list[dict] | None = None) -> None:
    res.add(check, block, NOT_EXECUTABLE, title, "", evidence or [], reason=reason, action=action,
            priority=priority)


def missing_inputs(res: AuditResult, check: str, block: str, title: str, missing: list[str]) -> None:
    not_executable(res, check, block, title, "missing required inputs: " + ", ".join(missing),
                   "Provide " + ", ".join(missing) + " to enable this check.")
