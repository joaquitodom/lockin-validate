"""Data cases for the extended data checks (cases/data/), seeded. Does NOT import lockin_validate.

Usage (from the repository root):  uv run python cases/_generators/data_cases.py

  D01  fundamentals exposed before their filing date                  -> pit_fundamentals CONFIRMED_ERROR
  D02  universe members that left without any price                   -> survivorship CONFIRMED_ERROR
  D03  one ticker recycled by two entities, prices spanning both      -> ticker_identity CONFIRMED_ERROR
  D04  declared 2:1 split not applied in an 'adjusted' series         -> corporate_actions CONFIRMED_ERROR,
                                                                         price_jumps NEEDS_REVIEW
  D05  one bad tick that an independent reference does not have       -> reference_accuracy NEEDS_REVIEW
  D06  every extended input present and clean (false-positive control) -> the five extended checks PASS
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import expectation_changes  # noqa: E402  (sibling module: docs/CASE_CHANGES.md, 0.2.0)
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data"
# NYSE full-day holidays 2022-2024 as published by the exchange (own list, not the package's calendar).
NYSE_HOLIDAYS = {
    date(2022, 1, 17), date(2022, 2, 21), date(2022, 4, 15), date(2022, 5, 30), date(2022, 6, 20), date(2022, 7, 4),
    date(2022, 9, 5), date(2022, 11, 24), date(2022, 12, 26),
    date(2023, 1, 2), date(2023, 1, 16), date(2023, 2, 20), date(2023, 4, 7), date(2023, 5, 29), date(2023, 6, 19),
    date(2023, 7, 4), date(2023, 9, 4), date(2023, 11, 23), date(2023, 12, 25),
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19),
    date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28), date(2024, 12, 25),
}
START, END = date(2022, 1, 3), date(2024, 12, 31)


def sessions(start=START, end=END) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in NYSE_HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


def walk(rng, n, p0, vol=0.012, drift=0.0003) -> list[float]:
    out, p = [], p0
    for _ in range(n):
        p *= 1 + drift + vol * rng.standard_normal()
        out.append(round(p, 4))
    return out


def write_csv(p: Path, rows, cols):
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


RULES = ("strategy: data-quality case (no trades)\nconventions:\n  calendar: nyse\n  review_date: '2026-10-20'\n")


def folder(name: str) -> Path:
    c = OUT / name
    if c.exists():
        shutil.rmtree(c)
    c.mkdir(parents=True)
    (c / "rules.yaml").write_text(RULES, encoding="utf-8")
    return c


def write_expected(c: Path, description: str, must, must_not, errors_only_from, comment=None):
    exp = {"description": description, "origin": "data", "must_include": must, "must_not_include": must_not,
           "errors_only_from": errors_only_from}
    if comment:
        exp["comment"] = comment
    (c / "expected.json").write_text(json.dumps(exp, indent=2), encoding="utf-8")


def price_rows(series: dict[str, dict[date, float]]):
    return [{"date": d.isoformat(), "ticker": t, "close": v, "adjusted": "true"}
            for t, s in series.items() for d, v in sorted(s.items())]


def quarter_ends():
    out = []
    for y in (2021, 2022, 2023, 2024):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = date(y, m, d)
            if date(2021, 9, 30) <= q <= date(2024, 9, 30):
                out.append(q)
    return out


def fundamentals_rows(tickers, rng, bad: set[tuple[str, date]] = frozenset()):
    rows = []
    for t in tickers:
        for q in quarter_ends():
            filing = q + timedelta(days=40)
            avail = filing + timedelta(days=1)
            if (t, q) in bad:
                avail = q + timedelta(days=5)  # exposed 5 days after the period end, weeks before publication
            rows.append({"ticker": t, "period_end": q.isoformat(), "filing_date": filing.isoformat(),
                         "available_from": f"{avail.isoformat()}T09:30:00", "roe": round(float(rng.normal(0.12, 0.05)), 4)})
    return rows


def d01():
    rng = np.random.default_rng(1)
    ds = sessions()
    tickers = ["FA", "FB", "FC", "FD"]
    series = {t: dict(zip(ds, walk(rng, len(ds), 40 + 10 * i))) for i, t in enumerate(tickers)}
    c = folder("D01_fundamentals_before_filing")
    write_csv(c / "prices.csv", price_rows(series), ["date", "ticker", "close", "adjusted"])
    bad = {("FB", date(2023, 3, 31)), ("FD", date(2023, 12, 31))}
    write_csv(c / "fundamentals.csv", fundamentals_rows(tickers, rng, bad),
              ["ticker", "period_end", "filing_date", "available_from", "roe"])
    write_expected(c, "Two fundamentals rows are available to the strategy 5 days after the period end, about 35 days "
                      "before their filing date.",
                   [{"check": "pit_fundamentals", "status": ["CONFIRMED_ERROR"]}],
                   [{"check": "pit_fundamentals", "status": "PASS"}], ["pit_fundamentals"])


def d02():
    rng = np.random.default_rng(2)
    ds = sessions()
    survivors = ["SA", "SB", "SC", "SD", "SE", "SF"]
    series = {t: dict(zip(ds, walk(rng, len(ds), 30 + 5 * i))) for i, t in enumerate(survivors)}
    late = [d for d in ds if d <= date(2023, 5, 31)]
    series["XT"] = dict(zip(late, walk(rng, len(late), 25, drift=-0.002)))  # truncated: exit is 2023-11-01
    c = folder("D02_survivorship")
    write_csv(c / "prices.csv", price_rows(series), ["date", "ticker", "close", "adjusted"])
    uni = [{"ticker": t, "start_date": "2021-01-04", "end_date": ""} for t in survivors]
    uni += [{"ticker": "XA", "start_date": "2021-01-04", "end_date": "2022-09-01"},
            {"ticker": "XB", "start_date": "2021-01-04", "end_date": "2023-03-01"},
            {"ticker": "XC", "start_date": "2021-01-04", "end_date": "2024-02-01"},
            {"ticker": "XT", "start_date": "2021-01-04", "end_date": "2023-11-01"}]
    write_csv(c / "universe.csv", uni, ["ticker", "start_date", "end_date"])
    write_expected(c, "Three members left the universe inside the window (XA, XB, XC) and have no price at all; XT's "
                      "series stops five months before its exit.",
                   [{"check": "survivorship", "status": ["CONFIRMED_ERROR"]}],
                   [{"check": "survivorship", "status": "PASS"}], ["survivorship"])


def d03():
    rng = np.random.default_rng(3)
    ds = sessions()
    series = {t: dict(zip(ds, walk(rng, len(ds), 50 + 5 * i))) for i, t in enumerate(["IA", "IB", "IC"])}
    first = [d for d in ds if d <= date(2022, 12, 30)]
    second = [d for d in ds if d >= date(2023, 6, 1)]
    zzz = dict(zip(first, walk(rng, len(first), 80, drift=-0.003)))
    zzz.update(dict(zip(second, walk(rng, len(second), 9))))
    series["ZZZ"] = zzz
    c = folder("D03_recycled_ticker")
    write_csv(c / "prices.csv", price_rows(series), ["date", "ticker", "close", "adjusted"])
    master = [{"ticker": t, "entity_id": f"ENT-{t}", "start_date": "2010-01-04", "end_date": ""} for t in ["IA", "IB", "IC"]]
    master += [{"ticker": "ZZZ", "entity_id": "ENT-OLDCO", "start_date": "2010-01-04", "end_date": "2022-12-30"},
               {"ticker": "ZZZ", "entity_id": "ENT-NEWCO", "start_date": "2023-06-01", "end_date": ""}]
    write_csv(c / "security_master.csv", master, ["ticker", "entity_id", "start_date", "end_date"])
    write_expected(c, "Ticker ZZZ belonged to one company until 2022-12-30 and to a different one from 2023-06-01; the "
                      "price series joins both under one symbol.",
                   [{"check": "ticker_identity", "status": ["CONFIRMED_ERROR"]}],
                   [{"check": "ticker_identity", "status": "PASS"}], ["ticker_identity"],
                   comment="coverage is expected to raise a review item for the 5-month gap in ZZZ (same problem).")


def d04():
    rng = np.random.default_rng(4)
    ds = sessions()
    series = {t: dict(zip(ds, walk(rng, len(ds), 60 + 10 * i))) for i, t in enumerate(["CA", "CB", "CC"])}
    for d in ds:
        if d >= date(2023, 5, 15):
            series["CB"][d] = round(series["CB"][d] / 2, 4)
    c = folder("D04_split_not_applied")
    write_csv(c / "prices.csv", price_rows(series), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "corporate_actions.csv", [{"ticker": "CB", "date": "2023-05-15", "ratio": 2, "type": "split"}],
              ["ticker", "date", "ratio", "type"])
    write_expected(c, "CB had a declared 2:1 split on 2023-05-15; the series flagged as adjusted still halves that day.",
                   [{"check": "corporate_actions", "status": ["CONFIRMED_ERROR"]},
                    {"check": "price_jumps", "status": ["NEEDS_REVIEW"]}],
                   [{"check": "corporate_actions", "status": "PASS"}], ["corporate_actions"])


def d05():
    rng = np.random.default_rng(5)
    ds = sessions()
    series = {t: dict(zip(ds, walk(rng, len(ds), 20 + 10 * i))) for i, t in enumerate(["RA", "RB", "RC"])}
    ref = {t: dict(s) for t, s in series.items()}
    bad_day = date(2023, 8, 15)
    series["RB"][bad_day] = round(series["RB"][bad_day] * 1.30, 4)  # bad tick in the main source only
    c = folder("D05_reference_mismatch")
    write_csv(c / "prices.csv", price_rows(series), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "reference_prices.csv", [{"date": r["date"], "ticker": r["ticker"], "close": r["close"]}
                                           for r in price_rows(ref)], ["date", "ticker", "close"])
    write_expected(c, "RB has a +30% one-day bad tick on 2023-08-15 that the independent reference does not show.",
                   [{"check": "reference_accuracy", "status": ["NEEDS_REVIEW"]}],
                   [{"check": "reference_accuracy", "status": "PASS"}], [])


def d06():
    rng = np.random.default_rng(6)
    ds = sessions()
    tickers = ["KA", "KB", "KC", "KD"]
    series = {t: dict(zip(ds, walk(rng, len(ds), 30 + 10 * i))) for i, t in enumerate(tickers)}
    c = folder("D06_clean_extended_inputs")
    write_csv(c / "prices.csv", price_rows(series), ["date", "ticker", "close", "adjusted"])
    write_csv(c / "reference_prices.csv", [{"date": r["date"], "ticker": r["ticker"], "close": r["close"]}
                                           for r in price_rows(series)], ["date", "ticker", "close"])
    write_csv(c / "fundamentals.csv", fundamentals_rows(tickers, rng), ["ticker", "period_end", "filing_date",
                                                                        "available_from", "roe"])
    write_csv(c / "universe.csv", [{"ticker": t, "start_date": "2021-01-04", "end_date": ""} for t in tickers],
              ["ticker", "start_date", "end_date"])
    write_csv(c / "security_master.csv", [{"ticker": t, "entity_id": f"ENT-{t}", "start_date": "2010-01-04",
                                           "end_date": ""} for t in tickers], ["ticker", "entity_id", "start_date",
                                                                               "end_date"])
    # a split that IS reflected (the adjusted series is smooth across the date)
    write_csv(c / "corporate_actions.csv", [{"ticker": "KC", "date": "2023-09-12", "ratio": 3, "type": "split"}],
              ["ticker", "date", "ratio", "type"])
    checks = ["pit_fundamentals", "survivorship", "ticker_identity", "corporate_actions", "reference_accuracy",
              "price_jumps", "coverage", "dates", "duplicates", "stale_prices"]
    write_expected(c, "Every extended data input present and clean: measures false positives of the extended checks.",
                   [{"check": k, "status": ["PASS"]} for k in checks],
                   [{"check": k, "status": s} for k in checks for s in ("CONFIRMED_ERROR", "NEEDS_REVIEW")], [])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (d01, d02, d03, d04, d05, d06):
        f()
        print("generated", f.__name__)
    print("0.2.0 expectation changes applied to", expectation_changes.apply(OUT))


if __name__ == "__main__":
    main()
