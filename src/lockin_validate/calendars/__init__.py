"""Configurable trading calendars: ``nyse``, ``byma`` or ``none``.

``conventions.calendar`` in rules.yaml (or the selected profile):

``nyse``  hand-written NYSE rules (calendars/nyse.py).
``byma``  weekends plus the holidays of a CSV (columns ``date, reason, note``). Default:
          the packaged ``data/byma_holidays.csv`` (2015-2026; provenance and the
          verification status of every date in docs/CALENDAR_BYMA.md); override with ``conventions.holidays_file`` (path relative to the
          input folder). Years not covered by the file are only checked for weekends (and the
          report says so).
``none``  no trading-day requirement (e.g. crypto 24x7).

If nothing is declared no market is presumed: weekend rows are NEEDS_REVIEW, never CONFIRMED_ERROR.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from importlib import resources
from pathlib import Path
from typing import Any

from .nyse import is_trading_day as nyse_is_trading_day

ALIASES = {"nyse": "nyse", "xnys": "nyse", "byma": "byma", "xbue": "byma", "none": "none", "ninguno": "none",
           "24x7": "none"}


@dataclass
class Calendar:
    name: str  # nyse, byma, none, undeclared
    declared: bool
    holidays: set[date] = field(default_factory=set)
    years_covered: set[int] = field(default_factory=set)
    source: str | None = None  # file name of the holiday list, or "profile"
    declared_by: str = "rules.yaml"

    def is_session(self, d: date) -> bool:
        if self.name == "nyse":
            return nyse_is_trading_day(d)
        if self.name == "byma":
            return d.weekday() < 5 and d not in self.holidays
        if self.name == "undeclared":
            return d.weekday() < 5
        return True

    def covers(self, d: date) -> bool:
        if self.name == "byma":
            return d.year in self.years_covered
        return True

    def sessions(self, start: date, end: date) -> list[date]:
        out, d = [], start
        while d <= end:
            if self.is_session(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    @property
    def full_calendar(self) -> bool:
        """True when the calendar defines the expected sessions on its own (nyse, byma)."""
        return self.name in ("nyse", "byma")


def read_holidays(source: Any) -> set[date]:
    with open(source, encoding="utf-8", newline="") as f:
        return {date.fromisoformat(r["date"].strip()) for r in csv.DictReader(f) if r.get("date")}


def packaged_byma_holidays() -> tuple[set[date], str]:
    ref = resources.files("lockin_validate").joinpath("data/byma_holidays.csv")
    with resources.as_file(ref) as p:
        return read_holidays(p), "byma_holidays.csv (packaged)"


def calendar_from(value: Any, folder: Path | None = None, holidays_file: str | None = None,
                  declared_by: str = "rules.yaml") -> Calendar:
    if value is None:
        return Calendar("undeclared", False, declared_by="-")
    name = ALIASES.get(str(value).strip().lower())
    if name is None:
        raise ValueError(f"unknown calendar {value!r} (use nyse, byma or none)")
    if name == "nyse":
        return Calendar("nyse", True, declared_by=declared_by)
    if name == "byma":
        if holidays_file:
            p = (folder / holidays_file) if folder is not None else Path(holidays_file)
            hol, src = read_holidays(p), p.name
        else:
            hol, src = packaged_byma_holidays()
        return Calendar("byma", True, hol, {d.year for d in hol}, src, declared_by=declared_by)
    return Calendar("none", True, declared_by=declared_by)
