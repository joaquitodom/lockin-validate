"""Content of the packaged BYMA holiday file (src/lockin_validate/data/byma_holidays.csv).

The packaged file is the subset ``market_closed == yes`` of the research table
data/calendars/byma_holidays_sourced.csv; provenance in docs/CALENDAR_BYMA.md.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from importlib import resources
from pathlib import Path

import pytest

from lockin_validate.calendars import calendar_from, packaged_byma_holidays

YEARS = range(2015, 2027)
TYPES = {"national_fixed", "national_movable", "bridge_non_working_day", "market_specific"}
SOURCED = Path(__file__).resolve().parents[1] / "data" / "calendars" / "byma_holidays_sourced.csv"


def _read(source) -> list[dict[str, str]]:
    with open(source, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _packaged_rows() -> list[dict[str, str]]:
    ref = resources.files("lockin_validate").joinpath("data/byma_holidays.csv")
    with resources.as_file(ref) as p:
        return _read(p)


def _easter(y: int) -> date:
    """Gregorian Easter (anonymous algorithm), independent of the data file."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(y, month, day)


ROWS = _packaged_rows()
HOL, _ = packaged_byma_holidays()


def test_easter_helper():
    assert _easter(2024) == date(2024, 3, 31) and _easter(2026) == date(2026, 4, 5)


def test_years_covered():
    assert {d.year for d in HOL} == set(YEARS)
    cal = calendar_from("byma")
    assert cal.years_covered == set(YEARS)
    assert all(cal.covers(date(y, 6, 1)) for y in YEARS)


def test_no_duplicates_and_sorted():
    dates = [r["date"] for r in ROWS]
    assert len(dates) == len(set(dates))
    assert dates == sorted(dates)
    assert len(HOL) == len(ROWS)


def test_no_weekends():
    assert [d for d in HOL if d.weekday() >= 5] == []


@pytest.mark.parametrize("year", YEARS)
def test_fixed_holidays_present(year):
    for m, d in ((1, 1), (5, 25), (7, 9), (12, 25), (4, 2)):
        x = date(year, m, d)
        if x.weekday() >= 5 or x == date(2020, 4, 2):  # 2020: 2 April moved to 31 March (DNU 297/2020)
            continue
        assert x in HOL, x


@pytest.mark.parametrize("year", YEARS)
def test_easter_based_holidays_present(year):
    e = _easter(year)
    for off in (-48, -47, -3, -2):  # Carnival Monday and Tuesday, Holy Thursday, Good Friday
        assert e + timedelta(off) in HOL, (year, off)


def test_known_one_off_closures_present():
    for d in (date(2018, 11, 30), date(2020, 3, 31), date(2022, 5, 18), date(2022, 9, 2), date(2024, 12, 31),
              date(2025, 12, 31), date(2026, 11, 9), date(2026, 12, 31)):
        assert d in HOL, d


def test_known_sessions_absent():
    """Days that look like holidays but on which BYMA traded."""
    for d in (date(2020, 4, 2), date(2022, 12, 20), date(2024, 8, 19), date(2024, 12, 24), date(2025, 11, 21),
              date(2026, 3, 23), date(2026, 7, 10), date(2026, 11, 6), date(2026, 12, 24)):
        assert d not in HOL, d
        assert calendar_from("byma").is_session(d)


def test_movable_holidays_on_the_moved_date():
    for moved, original in ((date(2020, 6, 15), date(2020, 6, 17)), (date(2025, 6, 16), date(2025, 6, 17)),
                            (date(2025, 10, 10), date(2025, 10, 13)), (date(2025, 11, 24), date(2025, 11, 17)),
                            (date(2026, 6, 15), date(2026, 6, 17))):
        assert moved in HOL and original not in HOL


def test_columns_types_and_sources():
    assert list(ROWS[0]) == ["date", "name", "type", "market_closed", "source_url", "verified", "notes"]
    for r in ROWS:
        assert r["type"] in TYPES, r
        assert r["verified"] in {"yes", "partial", "no"}, r
        assert r["market_closed"] == "yes", r
        assert r["name"].strip(), r
        if r["verified"] == "yes":
            assert r["source_url"].startswith("https://"), r


@pytest.mark.skipif(not SOURCED.exists(), reason="research table not shipped with the installed package")
def test_packaged_is_the_closed_subset_of_the_sourced_table():
    src = _read(SOURCED)
    assert [r for r in src if r["market_closed"] == "yes"] == ROWS
    assert {r["market_closed"] for r in src} <= {"yes", "no", "unknown"}
    for r in src:
        assert r["type"] in TYPES and r["verified"] in {"yes", "partial", "no"}, r
        if r["verified"] == "yes":
            assert r["source_url"].startswith("https://"), r
    dates = [r["date"] for r in src]
    assert len(dates) == len(set(dates))
