"""Transformation log: nothing is ever fixed silently.

The original input files are opened read-only and never written. Whenever the toolkit derives
a working table (parse dates, normalise tickers, drop rows without a valid date so other checks
can run, pick the first of two duplicated prices for valuation) it records it here with a
before/after summary (counts, never whole rows).

Three things are kept apart:

``diagnosis``  what was found (it is a finding, see findings.py).
``proposed``   the fix the toolkit suggests; it is NOT applied (``applied = False``).
``applied``    a transformation the toolkit DID apply on its working copy to be able to continue;
               always explicit and logged with its before and after.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Transformation:
    input: str
    operation: str
    reason: str
    before: dict[str, Any]
    after: dict[str, Any]
    applied: bool = True  # False = proposal only
    rows: list[int] = field(default_factory=list)  # CSV line numbers affected

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rows"] = self.rows[:50]
        d["n_rows"] = len(self.rows)
        d["kind"] = "applied" if self.applied else "proposed"
        return d


class TransformationLog:
    def __init__(self) -> None:
        self.items: list[Transformation] = []

    def applied(self, input: str, operation: str, reason: str, before: dict, after: dict,
                rows: list[int] | None = None) -> Transformation:
        t = Transformation(input, operation, reason, dict(before), dict(after), True, list(rows or []))
        self.items.append(t)
        return t

    def propose(self, input: str, operation: str, reason: str, before: dict, after: dict,
                rows: list[int] | None = None) -> Transformation:
        t = Transformation(input, operation, reason, dict(before), dict(after), False, list(rows or []))
        self.items.append(t)
        return t

    def to_list(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.items]
