"""Regenerate docs/CHECKS.md from the check catalogue (uv run python docs/generate_checks_md.py)."""

from pathlib import Path

from lockin_validate.catalog import CHECKS, REF
from lockin_validate.inputs import REQUIREMENTS

HEADER = """# Check catalogue

Generated from `src/lockin_validate/catalog.py` by `docs/generate_checks_md.py`. The same text is available offline
with `lockin-validate explain <check_id>` and through the MCP tool `explain_check`.

Every check returns findings with one status: CONFIRMED_ERROR, NEEDS_REVIEW, NOT_EXECUTABLE (with the reason), INFO
(a note that is not an alert, see docs/ALERT_POLICY.md) or PASS (within its scope). Thresholds and formulas are in
docs/CONVENTIONS.md; the inputs of the 0.2.0 checks are in docs/INPUT_SPEC.md. Checks added in 0.2.0 carry a
"Motivation" line: the failure of the LockIn case study that each one would have caught.

Blocks run in this order: input, data, reconstruction, strategy, statistics. Statistics are conditional on the data
being correct ("data first, reconstruction second, statistics third").

| Check | Block | Title |
|---|---|---|
"""

LLM_NOTE = """
## Further literature on LLM look-ahead (not independently verified)

The original internal research behind the LLM checklist also cited the following works. Their bibliographic details
were collected from secondary sources and were NOT independently verified by the authors of this release; treat them
as pointers, not as authorities: Kong et al. (2026), position paper on bias in LLM finance evaluation (ICML 2026,
arXiv 2602.14233); Gao, Jiang and Yan (2025), a test of look-ahead bias in LLM forecasts (arXiv 2512.23847);
Benhenda (2026), Look-Ahead-Bench (arXiv 2601.13770); Jia (2026), HindsightBench (arXiv 2607.18867); Li et al. (2025),
FINSABER (arXiv 2505.07078); DatedGPT (arXiv 2603.11838). The checklist weights are a documented judgement, not a
calibrated model.
"""


def main() -> None:
    lines = [HEADER.rstrip("\n")]
    for k, v in CHECKS.items():
        lines.append(f"| [`{k}`](#{k}) | {v['block']} | {v['title']} |")
    for k, v in CHECKS.items():
        req = REQUIREMENTS.get(k, {})
        lines += ["", f"## {k}", "", f"**{v['title']}** (block: {v['block']})", "",
                  f"- What it checks: {v['what']}", f"- Why it matters: {v['why']}", f"- How to fix: {v['fix']}",
                  f"- Allows concluding: {v['allows']}", f"- Does not allow: {v['does_not_allow']}"]
        if v.get("motivation"):
            lines.append(f"- Motivation (LockIn case study): {v['motivation']}")
        lines += [
                  "- Required inputs: " + (", ".join(req.get("required", [])) or "none"),
                  "- Optional inputs: " + (", ".join(req.get("optional", [])) or "none")]
        if v["refs"]:
            lines.append("- References: " + " ".join(f"{REF[r]}" for r in v["refs"]))
    lines += ["", "## References", ""] + [f"- {r}" for r in REF.values()]
    lines.append(LLM_NOTE)
    out = Path(__file__).resolve().parent / "CHECKS.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
