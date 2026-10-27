"""Configurable calendar: nyse, byma (holiday file), none, undeclared; and profiles."""

import shutil
from datetime import date
from pathlib import Path

import yaml

from lockin_validate import audit
from lockin_validate.calendars.nyse import is_trading_day, nyse_holidays, trading_days

R11 = Path(__file__).resolve().parents[1] / "cases" / "adversarial" / "R11_byma_calendar_undeclared"


def _with_calendar(src, dst, value, extra_rows=()):
    shutil.copytree(src, dst)
    r = yaml.safe_load((dst / "rules.yaml").read_text(encoding="utf-8"))
    if value is None:
        r["conventions"].pop("calendar", None)
    else:
        r["conventions"]["calendar"] = value
    (dst / "rules.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    if extra_rows:
        with open(dst / "prices.csv", "a", encoding="utf-8") as f:
            for line in extra_rows:
                f.write(line + "\n")
    return dst


def _dates(res):
    return {(f.status, f.title) for f in res.findings if f.check == "dates"}


def test_nyse_known_holidays():
    h = nyse_holidays(2024)
    for d in [date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29), date(2024, 5, 27),
              date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28), date(2024, 12, 25)]:
        assert d in h
    assert len(h) == 10
    assert not is_trading_day(date(2025, 1, 9))  # Carter national day of mourning
    assert is_trading_day(date(2021, 12, 31))  # New Year 2022 on Saturday is not observed on Friday
    assert date(2022, 6, 20) in nyse_holidays(2022) and date(2021, 6, 18) not in nyse_holidays(2021)
    assert len(trading_days(date(2023, 1, 1), date(2023, 12, 31))) == 250


def test_byma_declared_flags_argentine_holiday(tmp_path):
    d = _with_calendar(R11, tmp_path / "byma", "byma", ["2024-07-09,ALPHA,50,true,2024-07-09T17:00:00"])
    res = audit(d)
    assert any(s == "CONFIRMED_ERROR" and "byma calendar" in t for s, t in _dates(res))


def test_byma_declared_clean_data_passes(tmp_path):
    res = audit(_with_calendar(R11, tmp_path / "byma", "byma"))
    assert res.status_of("dates") == "PASS"
    assert res.status_of("coverage") == "PASS"


def test_nyse_declared_on_byma_data_is_an_error(tmp_path):
    res = audit(_with_calendar(R11, tmp_path / "nyse", "nyse"))
    assert res.status_of("dates") == "CONFIRMED_ERROR"  # 4 July: BYMA session, NYSE holiday


def test_no_calendar_review_never_error(core, tmp_path):
    res = audit(_with_calendar(core / "05_impossible_dates", tmp_path / "x", None))
    t = _dates(res)
    assert ("NEEDS_REVIEW", "Market calendar not declared") in t
    assert any(s == "NEEDS_REVIEW" and "weekend" in x for s, x in t)
    assert not any(s == "CONFIRMED_ERROR" and "session" in x for s, x in t)


def test_none_does_not_check_sessions(core, tmp_path):
    res = audit(_with_calendar(core / "05_impossible_dates", tmp_path / "x", "none"))
    assert not any("session" in x or "weekend" in x for _, x in _dates(res))


def test_profile_sets_calendar_but_rules_win(tmp_path):
    d = _with_calendar(R11, tmp_path / "p", None)
    res = audit(d, profile="byma_equities_daily")
    assert res.status_of("dates") == "PASS"
    assert res.scope["calendar"]["declared_by"].startswith("profile")
    res2 = audit(d, profile="nyse_equities_daily")
    assert res2.status_of("dates") == "CONFIRMED_ERROR"
