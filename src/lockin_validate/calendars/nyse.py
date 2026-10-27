"""NYSE full-day trading calendar (rules valid from 2000 onwards), written by hand.

Rules: fixed holidays shifted for weekends (Saturday -> previous Friday, Sunday -> next
Monday; exception: New Year's Day on a Saturday is NOT observed on Friday 31 December),
moving holidays (Martin Luther King Jr. Day since 1998, Presidents' Day, Good Friday,
Memorial Day, Labor Day, Thanksgiving), Juneteenth since 2022 and the known unscheduled
full-day closures listed below. Early closes (half days) are trading days.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

# Unscheduled full-day NYSE closures since 2000.
SPECIAL_CLOSURES = {
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),  # September 11
    date(2004, 6, 11),  # national day of mourning, President Reagan
    date(2007, 1, 2),  # national day of mourning, President Ford
    date(2012, 10, 29), date(2012, 10, 30),  # Hurricane Sandy
    date(2018, 12, 5),  # national day of mourning, President G. H. W. Bush
    date(2025, 1, 9),  # national day of mourning, President Carter
}


def easter(year: int) -> date:
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date, allow_friday: bool = True) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1) if allow_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@cache
def nyse_holidays(year: int) -> frozenset[date]:
    hs: set[date | None] = set()
    hs.add(_observed(date(year, 1, 1), allow_friday=False))
    if year >= 1998:
        hs.add(_nth_weekday(year, 1, 0, 3))  # Martin Luther King Jr. Day
    hs.add(_nth_weekday(year, 2, 0, 3))  # Presidents' Day
    hs.add(easter(year) - timedelta(days=2))  # Good Friday
    hs.add(_last_weekday(year, 5, 0))  # Memorial Day
    if year >= 2022:
        hs.add(_observed(date(year, 6, 19)))  # Juneteenth
    hs.add(_observed(date(year, 7, 4)))  # Independence Day
    hs.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    hs.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    hs.add(_observed(date(year, 12, 25)))  # Christmas
    hs.discard(None)
    hs |= {d for d in SPECIAL_CLOSURES if d.year == year}
    return frozenset(h for h in hs if h is not None and h.year == year)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def trading_days(start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out
