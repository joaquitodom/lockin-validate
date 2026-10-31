"""Reports: Markdown, JSON and a simple static HTML page (no JavaScript), from templates only.

Sections: summary, scope, inputs and versions (manifest with sha256), checks run, confirmed errors, items that need
review, not-executable checks, passes within scope, evidence and procedure for each conclusion, reconstructed
metrics, statistics, transformation log, limitations and pending human review, prioritised suggested actions, and
the disclaimer at the top and at the bottom.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from .findings import (
    CONFIRMED_ERROR,
    INFO,
    NEEDS_REVIEW,
    NOT_EXECUTABLE,
    PASS,
    PRIORITIES,
    STATUS_TEXT,
    STATUSES,
    AuditResult,
    Finding,
)

EVIDENCE_ROWS_MD = 8


def fmt(x: Any) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        if math.isnan(x):
            return "-"
        if math.isinf(x):
            return "inf"
        if abs(x) >= 1000:
            return f"{x:,.2f}"
        return f"{x:.6g}"
    if isinstance(x, (list, tuple)):
        return ", ".join(fmt(v) for v in x[:6]) + (f" (+{len(x) - 6})" if len(x) > 6 else "")
    if isinstance(x, dict):
        return "; ".join(f"{k}={fmt(v)}" for k, v in list(x.items())[:6])
    return str(x)


def _cell(s: Any) -> str:
    return fmt(s).replace("|", "/").replace("\n", " ")


def _evidence_columns(ev: list[dict]) -> list[str]:
    cols: list[str] = []
    for e in ev[:EVIDENCE_ROWS_MD]:
        for k in e:
            if k not in cols:
                cols.append(k)
    return cols


def _evidence_md(ev: list[dict], n_total: int) -> list[str]:
    if not ev:
        return []
    cols = _evidence_columns(ev)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for e in ev[:EVIDENCE_ROWS_MD]:
        out.append("| " + " | ".join(_cell(e.get(c)) for c in cols) + " |")
    if n_total > EVIDENCE_ROWS_MD:
        out.append(f"\n({n_total - EVIDENCE_ROWS_MD} more evidence rows in report.json"
                   + (", which keeps up to 20" if n_total > 20 else "") + ".)")
    return out


def _actions(res: AuditResult) -> list[Finding]:
    acts = [f for f in res.findings if f.action and f.status not in (PASS, INFO)]
    acts.sort(key=lambda f: (PRIORITIES.index(f.priority) if f.priority in PRIORITIES else 9, STATUSES.index(f.status)))
    return acts


SECTIONS = [(CONFIRMED_ERROR, "Confirmed errors"), (NEEDS_REVIEW, "Items that need human review"),
            (NOT_EXECUTABLE, "Checks not executable (missing information)"),
            (INFO, "Information notes (not alerts)")]
KEY_METRICS = ("initial_nav", "final_nav", "total_return", "annual_return", "sharpe", "max_drawdown",
               "annual_volatility", "n_trades", "n_periods", "peak_date", "trough_date")


def render_markdown(res: AuditResult) -> str:
    m, c = res.meta, res.counts()
    L: list[str] = ["# Strategy validation report", "",
                    f"Tool: lockin-validate {m.get('tool_version', '-')}. Run: {m.get('run_at', '-')}. Input folder: "
                    f"`{m.get('input_folder', '-')}`. Profile: {m.get('profile', '-')}. Declared strategy version: "
                    f"{res.scope.get('strategy_version') or 'not provided'}.", "",
                    f"> **Disclaimer.** {m.get('disclaimer', '')}", "",
                    "Automated, local, offline review: no network and no remote AI were used. Every conclusion has its "
                    "procedure and its evidence (CSV line numbers, dates, values).", "",
                    "## Summary", "",
                    f"- Confirmed errors: **{c[CONFIRMED_ERROR]}**",
                    f"- Items that need human review: **{c[NEEDS_REVIEW]}**",
                    f"- Checks not executable (missing information): **{c[NOT_EXECUTABLE]}**",
                    f"- Information notes (not alerts, see docs/ALERT_POLICY.md): **{c[INFO]}**",
                    f"- Passed within scope: **{c[PASS]}**", ""]
    s = res.scope
    L += ["## Scope", "",
          f"Inputs present: {', '.join(s.get('inputs_present', [])) or 'none'}.", "",
          f"Inputs absent: {', '.join(s.get('inputs_absent', [])) or 'none'}.", "",
          f"Review date used for future dates: {s.get('review_date')}.", ""]
    cal = s.get("calendar") or {}
    if cal:
        L += [f"Calendar: {cal.get('name')} (declared: {fmt(cal.get('declared'))}, by {cal.get('declared_by')}"
              + (f", holidays from {cal.get('holidays_source')}" if cal.get("holidays_source") else "") + ").", ""]
    cu = s.get("conventions_used") or {}
    if cu:
        L += ["Conventions used: " + "; ".join(f"{k}={fmt(v['value'])} ({v['source']})" for k, v in cu.items()) + ".", ""]
    if s.get("reconstruction_conventions"):
        L += ["Reconstruction conventions: " + fmt(s["reconstruction_conventions"]) + ".", ""]
    uc = s.get("use_cases") or {}
    if uc:
        off = uc.get("not_run_activated_by") or {}
        L += ["Use-case modules run: " + (", ".join(uc.get("ran") or []) or "none (core only)")
              + (". Not run: " + "; ".join(f"{k} (add {' or '.join(v)})" for k, v in off.items()) + "." if off else "."),
              ""]
    L += ["## Inputs and versions (manifest)", "", "| Input | File | Present | Rows | sha256 |", "|---|---|---|---|---|"]
    for k, v in res.manifest.get("files", {}).items():
        L.append(f"| {k} | {v.get('file')} | {'yes' if v.get('present') else 'no'} | {v.get('rows', '-')} | "
                 f"{v.get('sha256') or '-'} |")
    if res.manifest.get("unrecognised"):
        L += ["", "Unrecognised files (not used): " + ", ".join(res.manifest["unrecognised"]) + "."]
    L.append("")
    L += ["## Checks run", "", "| Check | Block | Status |", "|---|---|---|"]
    seen = set()
    for f in res.findings:
        if f.check not in seen:
            seen.add(f.check)
            L.append(f"| {f.check} | {f.block} | {STATUS_TEXT[res.status_of(f.check)]} |")
    L.append("")
    for status, title in SECTIONS:
        fs = res.by_status(status)
        L += [f"## {title}", ""]
        if not fs:
            L += ["None.", ""]
            continue
        for i, f in enumerate(fs, 1):
            L += [f"### {i}. {f.title} (`{f.check}`)", ""]
            if f.detail:
                L += [f.detail, ""]
            if f.reason:
                L += [f"Reason: {f.reason.rstrip('.')}.", ""]
            if f.procedure:
                L += [f"Procedure: {f.procedure}", ""]
            if f.evidence:
                L += ["Evidence:", ""] + _evidence_md(f.evidence, f.n_evidence) + [""]
            if f.action:
                L += [f"Suggested action (priority {f.priority}): {f.action}", ""]
    L += ["## Passed within scope", ""]
    passes = res.by_status(PASS)
    for f in passes:
        L.append(f"- `{f.check}`: {f.title}. {f.detail} Procedure: {f.procedure}")
    if not passes:
        L.append("None.")
    L.append("")
    mr = res.metrics.get("reconstructed_metrics")
    if mr:
        L += ["## Reconstructed metrics", "", "| Metric | Value |", "|---|---|"]
        L += [f"| {k} | {fmt(mr[k])} |" for k in KEY_METRICS if k in mr]
        L.append("")
    st = res.metrics.get("statistics") or {}
    if st.get("source"):
        L += ["## Statistics", "", f"Return series: {st['source']}; periods per year: {st.get('periods_per_year')}; "
              f"declared trials: {fmt(st.get('declared_n_trials'))}; trials in trials.csv: {st.get('trials_in_matrix')}.", ""]
        sig = st.get("significance")
        if sig:
            L += [f"- Sharpe (annualised, sqrt rule): {fmt(sig['sharpe_annualised_sqrt_rule'])}; PSR(0): "
                  f"{fmt(sig['psr_vs_0'])}; minimum track record: {fmt(sig['min_track_record_years'])} years."]
        ac = st.get("autocorrelation")
        if ac:
            L += [f"- Lo (2002) adjusted annualised Sharpe: {fmt(ac['sharpe_annualised_lo'])} (naive "
                  f"{fmt(ac['sharpe_annualised_naive'])})."]
        ds = st.get("deflated_sharpe")
        if ds:
            L += [f"- Deflated Sharpe: {fmt(ds['dsr'])} with N = {ds['n_trials_used']}."]
        pb = st.get("pbo")
        if pb:
            L += [f"- PBO: {fmt(pb['pbo'])} over {pb['n_combinations']} CSCV partitions."]
        L.append("")
    L += ["## Transformation log", "",
          "Originals were not modified. These are the derivations made on working copies (applied = used by the "
          "review; proposed = suggested fix, NOT applied).", ""]
    if res.transformations:
        L += ["| Input | Operation | Kind | Reason | Before | After | Rows affected |", "|---|---|---|---|---|---|---|"]
        for t in res.transformations:
            L.append(f"| {t['input']} | {_cell(t['operation'])} | {t['kind']} | {_cell(t['reason'])} | "
                     f"{_cell(t['before'])} | {_cell(t['after'])} | {t['n_rows']} |")
    else:
        L.append("None.")
    L.append("")
    L += ["## Limitations and pending human review", ""] + [f"- {x}" for x in res.limitations]
    pend = sorted({f.check for f in res.findings if f.status == NEEDS_REVIEW})
    if pend:
        L += ["", "Review items a person must close: " + ", ".join(pend) + "."]
    L.append("")
    L += ["## Suggested actions (prioritised)", "", "| Priority | Check | Status | Action |", "|---|---|---|---|"]
    acts = _actions(res)
    L += [f"| {f.priority} | {f.check} | {STATUS_TEXT[f.status]} | {_cell(f.action)} |" for f in acts]
    if not acts:
        L.append("| - | - | - | No pending actions. |")
    L += ["", "---", "", f"*{m.get('disclaimer', '')}*", ""]
    return "\n".join(L)


CSS = """body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1100px;margin:2rem auto;
padding:0 1rem;color:#1d1d1f;background:#fff;line-height:1.45}h1,h2,h3{line-height:1.2}
table{border-collapse:collapse;margin:.5rem 0 1rem;font-size:.85rem;display:block;overflow-x:auto}
th,td{border:1px solid #ccc;padding:.25rem .5rem;text-align:left;vertical-align:top}th{background:#f2f2f2}
.CONFIRMED_ERROR{color:#a40000;font-weight:600}.NEEDS_REVIEW{color:#8a5a00;font-weight:600}
.NOT_EXECUTABLE{color:#555;font-weight:600}.PASS{color:#1b6e20;font-weight:600}.INFO{color:#1a4f8a;font-weight:600}
.disclaimer{border-left:4px solid #8a5a00;padding:.5rem 1rem;background:#fff8e6}.finding{border:1px solid #ddd;
border-radius:6px;padding:.25rem 1rem;margin:.75rem 0}code{background:#f4f4f4;padding:0 .2rem}
@media (prefers-color-scheme: dark){body{background:#161616;color:#e6e6e6}th{background:#262626}
th,td{border-color:#444}.disclaimer{background:#2b2410}.finding{border-color:#444}code{background:#262626}
.CONFIRMED_ERROR{color:#ff8a80}.NEEDS_REVIEW{color:#ffd180}.PASS{color:#9be7a0}.NOT_EXECUTABLE{color:#bbb}.INFO{color:#9ecbff}}"""


def _h(x: Any) -> str:
    return html.escape(fmt(x))


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    th = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{_h(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def render_html(res: AuditResult) -> str:
    m, c = res.meta, res.counts()
    P: list[str] = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
                    "<meta name='viewport' content='width=device-width, initial-scale=1'>",
                    f"<title>Validation report</title><style>{CSS}</style></head><body>",
                    "<h1>Strategy validation report</h1>",
                    f"<p>Tool: lockin-validate {_h(m.get('tool_version'))}. Run: {_h(m.get('run_at'))}. Input folder: "
                    f"<code>{_h(m.get('input_folder'))}</code>. Profile: {_h(m.get('profile'))}.</p>",
                    f"<p class='disclaimer'><strong>Disclaimer.</strong> {_h(m.get('disclaimer'))}</p>",
                    "<h2>Summary</h2><ul>"]
    for s in (CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE, INFO, PASS):
        P.append(f"<li><span class='{s}'>{html.escape(STATUS_TEXT[s])}</span>: {c[s]}</li>")
    P.append("</ul><h2>Inputs and versions (manifest)</h2>")
    P.append(_table(["Input", "File", "Present", "Rows", "sha256"],
                    [[k, v.get("file"), v.get("present"), v.get("rows", "-"), v.get("sha256") or "-"]
                     for k, v in res.manifest.get("files", {}).items()]))
    P.append("<h2>Checks run</h2>")
    rows, seen = [], set()
    for f in res.findings:
        if f.check not in seen:
            seen.add(f.check)
            rows.append([f.check, f.block, STATUS_TEXT[res.status_of(f.check)]])
    P.append(_table(["Check", "Block", "Status"], rows))
    for status, title in SECTIONS + [(PASS, "Passed within scope")]:
        fs = res.by_status(status)
        P.append(f"<h2>{html.escape(title)}</h2>")
        if not fs:
            P.append("<p>None.</p>")
        for f in fs:
            P.append(f"<div class='finding'><h3><span class='{status}'>{html.escape(STATUS_TEXT[status])}</span> "
                     f"{html.escape(f.title)} (<code>{html.escape(f.check)}</code>)</h3>")
            if f.detail:
                P.append(f"<p>{html.escape(f.detail)}</p>")
            if f.reason:
                P.append(f"<p><strong>Reason:</strong> {html.escape(f.reason)}</p>")
            if f.procedure:
                P.append(f"<p><strong>Procedure:</strong> {html.escape(f.procedure)}</p>")
            if f.evidence:
                cols = _evidence_columns(f.evidence)
                P.append(_table(cols, [[e.get(col) for col in cols] for e in f.evidence[:EVIDENCE_ROWS_MD]]))
                if f.n_evidence > EVIDENCE_ROWS_MD:
                    P.append(f"<p>({f.n_evidence - EVIDENCE_ROWS_MD} more evidence rows in report.json.)</p>")
            if f.action:
                P.append(f"<p><strong>Suggested action</strong> (priority {html.escape(f.priority)}): "
                         f"{html.escape(f.action)}</p>")
            P.append("</div>")
    mr = res.metrics.get("reconstructed_metrics")
    if mr:
        P.append("<h2>Reconstructed metrics</h2>")
        P.append(_table(["Metric", "Value"], [[k, mr[k]] for k in KEY_METRICS if k in mr]))
    P.append("<h2>Transformation log</h2>")
    P.append(_table(["Input", "Operation", "Kind", "Reason", "Before", "After", "Rows"],
                    [[t["input"], t["operation"], t["kind"], t["reason"], t["before"], t["after"], t["n_rows"]]
                     for t in res.transformations]) if res.transformations else "<p>None.</p>")
    P.append("<h2>Limitations and pending human review</h2><ul>")
    P += [f"<li>{html.escape(x)}</li>" for x in res.limitations]
    P.append("</ul><h2>Suggested actions (prioritised)</h2>")
    P.append(_table(["Priority", "Check", "Status", "Action"],
                    [[f.priority, f.check, STATUS_TEXT[f.status], f.action] for f in _actions(res)]))
    P.append(f"<p class='disclaimer'>{_h(m.get('disclaimer'))}</p></body></html>")
    return "\n".join(P)


def write_reports(res: AuditResult, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md, js, ht = out / "REPORT.md", out / "report.json", out / "report.html"
    md.write_text(render_markdown(res), encoding="utf-8")
    js.write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ht.write_text(render_html(res), encoding="utf-8")
    return {"markdown": md, "json": js, "html": ht}
