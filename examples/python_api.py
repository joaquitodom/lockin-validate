"""Minimal use of the Python API (run from the repository root: uv run python examples/python_api.py)."""

from pathlib import Path

from lockin_validate import CONFIRMED_ERROR, NEEDS_REVIEW, audit, run

HERE = Path(__file__).resolve().parent

# 1. In memory: nothing is written.
res = audit(HERE / "quickstart_inputs")
print("counts:", res.counts())
for f in res.findings:
    if f.status in (CONFIRMED_ERROR, NEEDS_REVIEW):
        print(f"[{f.status}] {f.check}: {f.title}")

# 2. With reports (Markdown, JSON and static HTML) in a separate folder.
res, paths = run(HERE / "quickstart_inputs", HERE / "quickstart_report")
print("report:", paths["markdown"])
