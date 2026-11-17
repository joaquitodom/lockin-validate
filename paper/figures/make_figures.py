"""Generate the figures of the working paper.

Every number below is transcribed from a LockIn repository document (path in the
comment next to it). No price data, vendor data or database access is used; the
script only draws already-published aggregates.

Usage (from the paper folder):
    python figures/make_figures.py
Outputs figures/fig_is_vs_oos.pdf and figures/fig_gap_cascade.pdf (+ .png).
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Figure 1: in-sample (2010-2021) vs single-use holdout (2022-2024), July runs.
# Sources: research/FROZEN_CONFIGS_2026-07-03.md (in-sample rows);
#          .planning/PROTOCOL-LOG.md entry 2026-10-08 (holdout, exact reproduction).
# SPY in-sample: 14.76% (monthly grid, m_D_nomom). SPY holdout: 10.08% (monthly grid).
# B-accel in-sample Sharpe 1.49 and return 13.4% from FROZEN_CONFIGS (maxDD not reported).
# ---------------------------------------------------------------------------
arms = ["D (primary)", "B-accel", "A (original)", "SPY"]
ret_is = [12.59, 13.4, 10.8, 14.76]
ret_oos = [-2.00, 0.30, -2.73, 10.08]
sh_is = [1.47, 1.49, 1.06]
sh_oos = [-0.527, -0.322, -0.471]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.0, 3.4))
x = range(len(arms))
w = 0.38
ax1.bar([i - w / 2 for i in x], ret_is, w, label="In-sample 2010-2021", color="#4a6fa5")
ax1.bar([i + w / 2 for i in x], ret_oos, w, label="Holdout 2022-2024", color="#c8553d")
ax1.axhline(0, color="black", lw=0.6)
ax1.set_xticks(list(x))
ax1.set_xticklabels(arms, fontsize=8)
ax1.set_ylabel("Annualized return (%)")
ax1.set_title("Return", fontsize=10)
ax1.legend(fontsize=7, frameon=False)

x2 = range(3)
ax2.bar([i - w / 2 for i in x2], sh_is, w, color="#4a6fa5")
ax2.bar([i + w / 2 for i in x2], sh_oos, w, color="#c8553d")
ax2.axhline(0, color="black", lw=0.6)
ax2.set_xticks(list(x2))
ax2.set_xticklabels(arms[:3], fontsize=8)
ax2.set_ylabel("Sharpe ratio")
ax2.set_title("Sharpe ratio", fontsize=10)
for ax in (ax1, ax2):
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(OUT / f"fig_is_vs_oos.{ext}", dpi=200)
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 2: sequential gap cascade, arm D on the certified database, 2022-2024.
# Source: research/diagnostico/DIAGNOSTICO_2026-10-24.md, section 2,
#         table "Cascada con los pesos reales de D" (t4_cascada_pesos_reales.csv).
# ---------------------------------------------------------------------------
steps = [
    ("SPY\n100%", 9.88, "level"),
    ("(a) Benchmark:\nSPY to RSP", -3.26, "delta"),
    ("(c1) Bands +\ntrend overlay", -0.15, "delta"),
    ("(c2) TLT\ninstead of cash", -4.85, "delta"),
    ("(d) Equity sleeve\nvs RSP", -3.52, "delta"),
    ("Arm D\n(realized)", -1.90, "level"),
]
fig, ax = plt.subplots(figsize=(8.6, 3.6))
running = 0.0
for i, (lab, val, kind) in enumerate(steps):
    if kind == "level":
        ax.bar(i, val, color="#4a6fa5" if i == 0 else "#2f2f2f", width=0.6)
        running = val
        ax.text(i, val + (0.3 if val >= 0 else -0.7), f"{val:+.2f}%", ha="center", fontsize=8)
    else:
        bottom = running + val
        ax.bar(i, -val, bottom=bottom, color="#c8553d", width=0.6)
        ax.text(i, running + 0.3, f"{val:+.2f} pp", ha="center", fontsize=8)
        running = bottom
ax.axhline(0, color="black", lw=0.6)
ax.set_xticks(range(len(steps)))
ax.set_xticklabels([s[0] for s in steps], fontsize=7.5)
ax.set_ylabel("Annualized return (%)")
ax.set_ylim(-3.5, 12)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(OUT / f"fig_gap_cascade.{ext}", dpi=200)
plt.close(fig)
print("figures written to", OUT)
