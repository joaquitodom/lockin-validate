"""lockin-validate: offline toolkit to validate quantitative investment strategies and their backtests.

Python API::

    from lockin_validate import audit, run
    res = audit("my_inputs/")                  # AuditResult, nothing written
    res, paths = run("my_inputs/", "review/")  # also writes REPORT.md, report.json, report.html

Statuses: CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE, INFO (a note, not an alert), PASS.
"""

from __future__ import annotations

__version__ = "0.2.0"

from .auditor import DISCLAIMER, audit, run  # noqa: E402
from .findings import (  # noqa: E402
    CONFIRMED_ERROR,
    INFO,
    NEEDS_REVIEW,
    NOT_EXECUTABLE,
    PASS,
    AuditResult,
    Finding,
)

__all__ = ["audit", "run", "AuditResult", "Finding", "CONFIRMED_ERROR", "NEEDS_REVIEW", "NOT_EXECUTABLE", "INFO",
           "PASS",            "DISCLAIMER", "__version__"]
