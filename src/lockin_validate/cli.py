"""Command line interface.

  lockin-validate run <input_dir> --out <dir> [--profile NAME] [--previous-manifest report.json]
  lockin-validate init <dir> [--force]
  lockin-validate cases [--dir cases] [--out DIR] [--json FILE]
  lockin-validate explain <check_id>
  lockin-validate checks

Exit codes of ``run``: 0 no confirmed errors, 1 confirmed errors, 2 usage error. ``cases``: 0 when every case has
its expected outcomes, 1 otherwise. The console prints only counts and check ids, never data rows.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__, usecases
from .auditor import DISCLAIMER, run
from .cases import default_cases_root, per_check_table, render_battery, run_battery
from .catalog import CHECKS, render_explain
from .findings import CONFIRMED_ERROR, PASS
from .inputs import InputError
from .profiles import PROFILES
from .scaffold import scaffold


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8()
    usecases.load_all()
    p = argparse.ArgumentParser(prog="lockin-validate",
                                description="Offline validation of quantitative strategies and their backtests.")
    p.add_argument("--version", action="version", version=f"lockin-validate {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="review an input package folder")
    r.add_argument("input_dir")
    r.add_argument("--out", required=True, help="output folder (must not be inside the input folder)")
    r.add_argument("--profile", default=None, choices=sorted(PROFILES))
    r.add_argument("--previous-manifest", default=None, help="report.json of a previous run, to detect silent changes")
    r.add_argument("--use-case", action="append", default=None, dest="use_cases",
                   help="force this use-case module (repeatable; 'all' forces every one; default: the modules whose input files are present; see `usecases`)")
    r.add_argument("-v", "--verbose", action="store_true")
    i = sub.add_parser("init", help="scaffold an input package template")
    i.add_argument("dir")
    i.add_argument("--force", action="store_true")
    c = sub.add_parser("cases", help="run the built-in benchmark battery")
    c.add_argument("--dir", default=None, help="cases folder (default: ./cases or the repository cases/)")
    c.add_argument("--out", default=None, help="write the report of every case here")
    c.add_argument("--json", default=None, help="write the battery results as JSON to this file")
    e = sub.add_parser("explain", help="explain a check")
    e.add_argument("check_id")
    sub.add_parser("checks", help="list the checks")
    sub.add_parser("usecases", help="list the use-case modules (what each validates, inputs, checks)")
    a = p.parse_args(argv)
    usecases.load_all()
    logging.basicConfig(level=logging.INFO if getattr(a, "verbose", False) else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if a.cmd == "run":
        try:
            res, paths = run(a.input_dir, a.out, profile=a.profile, previous_manifest=a.previous_manifest,
                             use_cases=a.use_cases)
        except (InputError, ValueError, FileNotFoundError) as ex:
            print(f"error: {ex}", file=sys.stderr)
            return 2
        cnt = res.counts()
        print("Review finished.")
        for k, v in cnt.items():
            print(f"  {k}: {v}")
        for f in res.findings:
            if f.status != PASS:
                print(f"  - [{f.status}] {f.check}: {f.title} (evidence rows: {f.n_evidence})")
        print(f"Report: {paths['markdown']}")
        print(f"JSON:   {paths['json']}")
        print(f"HTML:   {paths['html']}")
        print(f"Note: {DISCLAIMER}")
        return 1 if cnt[CONFIRMED_ERROR] else 0
    if a.cmd == "init":
        try:
            written = scaffold(a.dir, force=a.force)
        except FileExistsError as ex:
            print(f"error: {ex}", file=sys.stderr)
            return 2
        print(f"Template written to {Path(a.dir)} ({len(written)} files). Replace the example rows with your data.")
        return 0
    if a.cmd == "explain":
        print(render_explain(a.check_id))
        return 0 if a.check_id in CHECKS else 2
    if a.cmd == "checks":
        for k, v in CHECKS.items():
            print(f"{k:32} {v['block']:12} {v['title']}")
        return 0
    if a.cmd == "usecases":
        print("Core (always on): backtest of a systematic trading strategy; blocks input, data, reconstruction, "
              "strategy, statistics.")
        for u in usecases.describe():
            print(f"\n{u['name']}: {u['title']}  [{u['audience']}]")
            print(f"  {u['description']}")
            print(f"  inputs: {', '.join(u['inputs']) or '-'}")
            print(f"  checks: {', '.join(u['checks'])}")
        return 0
    root = Path(a.dir) if a.dir else default_cases_root()
    if not root.is_dir():
        print(f"error: cases folder not found: {root}", file=sys.stderr)
        return 2
    results = run_battery(root, Path(a.out) if a.out else None)
    print(render_battery(results))
    if a.json:
        Path(a.json).write_text(json.dumps({"cases": results, "per_check": per_check_table(results)}, indent=2,
                                           default=str), encoding="utf-8")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
