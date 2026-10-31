"""Findings, statuses and the audit result.

Every check produces one or more findings. A finding has exactly one status:

``CONFIRMED_ERROR``  the error is proven with the inputs (reproducible evidence).
``NEEDS_REVIEW``     something a person must look at; the inputs are not enough to confirm it.
``NOT_EXECUTABLE``   the check could not run; ``reason`` says what is missing.
``INFO``             the check ran; a note worth reading that is NOT an alert (not counted as a review item;
                     see docs/ALERT_POLICY.md for why each INFO is not a NEEDS_REVIEW).
``PASS``             the check ran and found no problem *within its scope*.

Conclusion rule (docs/CONVENTIONS.md, section 5): a check only says PASS if it could verify
what it claims. A check that depends only on a declaration it cannot contrast, or whose test
does not discriminate between hypotheses, says NEEDS_REVIEW, NOT_EXECUTABLE or (when the policy in
docs/ALERT_POLICY.md classifies it as informative) INFO; never PASS.

Privacy: evidence stores row ids, dates, tickers and point values, never whole rows. Log and
console messages use only counts and check ids.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

CONFIRMED_ERROR = "CONFIRMED_ERROR"
NEEDS_REVIEW = "NEEDS_REVIEW"
NOT_EXECUTABLE = "NOT_EXECUTABLE"
INFO = "INFO"
PASS = "PASS"
STATUSES = [CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE, INFO, PASS]  # most severe first
ALERT_STATUSES = (CONFIRMED_ERROR, NEEDS_REVIEW)  # what counts as an alert
STATUS_TEXT = {
    CONFIRMED_ERROR: "Confirmed error",
    NEEDS_REVIEW: "Needs human review",
    NOT_EXECUTABLE: "Not executable",
    INFO: "Information (not an alert)",
    PASS: "Pass (within scope)",
}
PRIORITIES = ["high", "medium", "low"]
MAX_EVIDENCE = 20  # evidence rows kept per finding in the JSON report

BLOCKS = ["input", "data", "reconstruction", "strategy", "statistics",
          # use-case modules (src/lockin_validate/usecases/)
          "signals", "ml", "risk", "forecast", "portfolio", "live"]


@dataclass
class Finding:
    check: str  # check id, e.g. "duplicates"
    block: str  # one of BLOCKS
    status: str  # one of STATUSES
    title: str
    detail: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    n_evidence: int = 0  # total evidence rows (the list may be truncated)
    procedure: str = ""  # how the conclusion was reached (reproducible)
    reason: str = ""  # NOT_EXECUTABLE only: what is missing
    action: str = ""  # suggested action
    priority: str = "medium"
    inputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [jsonable(e) for e in self.evidence]
        return d


def jsonable(x: Any) -> Any:
    """Convert numpy / pandas / date objects to plain JSON values (NaN -> None)."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v) for v in x]
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except Exception:  # pragma: no cover
            return str(x)
    if hasattr(x, "isoformat"):
        return x.isoformat()
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None if math.isnan(x) else ("inf" if x > 0 else "-inf")
    return x


@dataclass
class AuditResult:
    """Full result of an audit (consumed by the report, the CLI, the MCP server and the tests)."""

    findings: list[Finding] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    transformations: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(
        self,
        check: str,
        block: str,
        status: str,
        title: str,
        detail: str = "",
        evidence: list[dict] | None = None,
        procedure: str = "",
        reason: str = "",
        action: str = "",
        priority: str = "medium",
        inputs: list[str] | None = None,
    ) -> Finding:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        ev = list(evidence or [])
        f = Finding(check, block, status, title, detail, ev[:MAX_EVIDENCE], len(ev), procedure, reason, action,
                    priority, list(inputs or []))
        self.findings.append(f)
        return f

    def by_status(self, status: str) -> list[Finding]:
        return [f for f in self.findings if f.status == status]

    def checks(self) -> list[str]:
        seen: list[str] = []
        for f in self.findings:
            if f.check not in seen:
                seen.append(f.check)
        return seen

    def status_of(self, check: str) -> str | None:
        """Most severe status recorded for a check (CONFIRMED_ERROR > NEEDS_REVIEW > NOT_EXECUTABLE > INFO > PASS)."""
        st = {f.status for f in self.findings if f.check == check}
        for s in STATUSES:
            if s in st:
                return s
        return None

    def counts(self) -> dict[str, int]:
        return {s: len(self.by_status(s)) for s in STATUSES}

    def n_alerts(self) -> int:
        """CONFIRMED_ERROR + NEEDS_REVIEW findings (INFO notes are not alerts)."""
        return sum(len(self.by_status(s)) for s in ALERT_STATUSES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": jsonable(self.meta),
            "scope": jsonable(self.scope),
            "manifest": jsonable(self.manifest),
            "counts": self.counts(),
            "checks_run": [{"check": c, "status": self.status_of(c)} for c in self.checks()],
            "findings": [f.to_dict() for f in self.findings],
            "metrics": jsonable(self.metrics),
            "transformations": jsonable(self.transformations),
            "limitations": list(self.limitations),
        }
