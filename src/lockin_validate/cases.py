"""Benchmark battery runner: runs every case in cases/ and compares it with its expected.json.

expected.json is written BEFORE running the tool, by the case generator, from the problem planted in the case;
the tool never writes it. Format:

  description         what was planted
  origin              core | adversarial | statistical | data | lockin-style
  must_include        [{check, status: [allowed statuses]}]  at least one finding of the check in one of the statuses
                      (check "@data" matches any check of the data block)
  must_not_include    [{check, status}]                      must not appear
  errors_only_from    [checks]  if present, any CONFIRMED_ERROR of another check is a false positive
  text_must_contain   [{check, text}]                        title + detail of some finding of the check contains text
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .auditor import audit, run
from .findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult, Finding


def default_cases_root() -> Path:
    here = Path.cwd() / "cases"
    if here.is_dir():
        return here
    return Path(__file__).resolve().parents[2] / "cases"


def _match(f: Finding, pattern: str) -> bool:
    """``@data`` matches any data-quality check (blocks ``data`` and ``input``); ``@<block>`` matches a block."""
    if pattern == "@data":
        return f.block in ("data", "input")
    if pattern.startswith("@"):
        return f.block == pattern[1:]
    return f.check == pattern


def compare(res: AuditResult, exp: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    detections: list[dict[str, Any]] = []
    false_pos: list[dict[str, Any]] = []
    for d in exp.get("must_include", []):
        allowed = d["status"] if isinstance(d["status"], list) else [d["status"]]
        ok = any(_match(f, d["check"]) and f.status in allowed for f in res.findings)
        kind = "pass" if allowed == [PASS] else ("post_hoc" if d.get("post_hoc") else "detection")
        detections.append({"check": d["check"], "kind": kind, "ok": ok, "allowed": allowed})
        if not ok:
            got = sorted({f.status for f in res.findings if _match(f, d["check"])}) or ["(no finding)"]
            problems.append(f"missing {d['check']} in {allowed} (got: {', '.join(got)})")
    for d in exp.get("must_not_include", []):
        for f in res.findings:
            if _match(f, d["check"]) and f.status == d["status"]:
                problems.append(f"{f.check}={f.status} must not appear ({f.title})")
                if f.status in (CONFIRMED_ERROR, NEEDS_REVIEW):
                    false_pos.append({"check": f.check, "status": f.status, "title": f.title})
    if "errors_only_from" in exp:
        allowed = exp["errors_only_from"]
        for f in res.by_status(CONFIRMED_ERROR):
            if not any(_match(f, p) for p in allowed):
                problems.append(f"unexpected CONFIRMED_ERROR (false positive) {f.check}: {f.title}")
                if not any(x["check"] == f.check and x["title"] == f.title for x in false_pos):
                    false_pos.append({"check": f.check, "status": f.status, "title": f.title})
    for d in exp.get("text_must_contain", []):
        texts = [f.title + " " + f.detail for f in res.findings if f.check == d["check"]]
        if not any(d["text"] in t for t in texts):
            problems.append(f"the {d['check']} finding does not say: {d['text']!r}")
    mentioned = {d["check"] for d in exp.get("must_include", []) + exp.get("must_not_include", [])}
    unexpected_review = sorted({f.check for f in res.by_status(NEEDS_REVIEW) if f.check not in mentioned})
    c = res.counts()
    return {"ok": not problems, "problems": problems, "detections": detections, "false_positives": false_pos,
            "unexpected_review": unexpected_review, "counts": c,
            "summary": f"errors {c['CONFIRMED_ERROR']}, review {c['NEEDS_REVIEW']}, not executable "
                       f"{c['NOT_EXECUTABLE']}, info {c['INFO']}, pass {c['PASS']}"}


def available_cases(root: Path | None = None) -> list[Path]:
    root = root or default_cases_root()
    return sorted(p for p in root.rglob("expected.json") if p.parent != root and not p.parent.name.startswith("_"))


def run_case(expected_path: Path, out: Path | None = None) -> dict[str, Any]:
    folder = expected_path.parent
    exp = json.loads(expected_path.read_text(encoding="utf-8"))
    if out is not None:
        res, _ = run(folder, out / folder.name, profile=exp.get("profile"))
    else:
        res = audit(folder, profile=exp.get("profile"))
    r = compare(res, exp)
    r.update({"case": folder.name, "group": folder.parent.name, "origin": exp.get("origin", ""),
              "description": exp.get("description", "")})
    return r


def run_battery(root: Path | None = None, out: Path | None = None) -> list[dict[str, Any]]:
    return [run_case(p, out) for p in available_cases(root)]


def per_check_table(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"expected_detections": 0, "detected": 0,
                                                          "expected_passes": 0, "passes_met": 0,
                                                          "false_positives": 0, "unexpected_review": 0,
                                                          "post_hoc_expected": 0, "post_hoc_met": 0})
    for r in results:
        for d in r["detections"]:
            a = agg[d["check"]]
            if d["kind"] == "detection":
                a["expected_detections"] += 1
                a["detected"] += int(d["ok"])
            elif d["kind"] == "post_hoc":
                a["post_hoc_expected"] += 1
                a["post_hoc_met"] += int(d["ok"])
            else:
                a["expected_passes"] += 1
                a["passes_met"] += int(d["ok"])
        for fp in r["false_positives"]:
            agg[fp["check"]]["false_positives"] += 1
        for ch in r["unexpected_review"]:
            agg[ch]["unexpected_review"] += 1
    rows = []
    for ch in sorted(agg):
        a = agg[ch]
        rate = (a["detected"] / a["expected_detections"]) if a["expected_detections"] else None
        rows.append({"check": ch, **a, "detection_rate": rate})
    return rows


def render_battery(results: list[dict[str, Any]]) -> str:
    lines = []
    for r in results:
        lines.append(f"{'OK' if r['ok'] else 'FAIL':4} {r['group']}/{r['case']}: {r['summary']}")
        lines += [f"       {p}" for p in r["problems"]]
    ok = sum(r["ok"] for r in results)
    n_unexp = sum(len(r["unexpected_review"]) for r in results)
    n_fp = sum(len(r["false_positives"]) for r in results)
    det = [d for r in results for d in r["detections"]]
    pre = [d for d in det if d["kind"] == "detection"]
    post = [d for d in det if d["kind"] == "post_hoc"]
    lines += ["", f"{ok} of {len(results)} cases with all expected outcomes",
              f"Unexpected NEEDS_REVIEW (case x check): {n_unexp}; false positives: {n_fp}",
              f"Pre-registered detections met: {sum(d['ok'] for d in pre)} of {len(pre)}; expectations added after "
              f"seeing the output (post_hoc, not counted as detections): {sum(d['ok'] for d in post)} of {len(post)}",
              "",
              "Per check (detections = pre-registered non-PASS outcomes found; post-hoc expectations are excluded; false positives = unexpected CONFIRMED_ERROR or "
              "forbidden review items; unexpected review = NEEDS_REVIEW on checks the case does not mention):", "",
              f"{'check':28} {'detected':>10} {'rate':>6} {'passes':>8} {'false+':>7} {'unexp.review':>13}"]
    for row in per_check_table(results):
        det = f"{row['detected']}/{row['expected_detections']}" if row["expected_detections"] else "-"
        rate = f"{row['detection_rate']:.0%}" if row["detection_rate"] is not None else "-"
        pas = f"{row['passes_met']}/{row['expected_passes']}" if row["expected_passes"] else "-"
        lines.append(f"{row['check']:28} {det:>10} {rate:>6} {pas:>8} {row['false_positives']:>7} "
                     f"{row['unexpected_review']:>13}")
    return "\n".join(lines)
