"""Evidence for docs/ALERT_POLICY.md (0.2.1): threshold sensitivity of P1 and the size of the P5 test.

Usage (repository root):  uv run python docs/simulations/alert_policy_checks.py

1. sharpe_significance: for every battery case whose PSR is below 0.95, the status the policy gives at several values of
   significance_review_ratio (MinTRL / T above which a positive Sharpe is a review item). Shows where the chosen 2
   sits relative to the cases instead of citing the battery as support for it.
2. sharpe_autocorrelation: rejection rate (size) under i.i.d. normal returns, seeded Monte Carlo, of the 0.1.0 and
   0.2.x rules: "Ljung-Box p < 0.05 OR |rho_1| > z / sqrt(T)", alone and together with the inflation condition
   (naive / Lo-adjusted Sharpe > 1.10) that the review item also requires. The returns have a positive mean so that the
   Sharpe is not zero (as in the battery).
"""

from __future__ import annotations

import math

import numpy as np

from lockin_validate import stats
from lockin_validate.auditor import audit
from lockin_validate.cases import available_cases

RATIOS = [1.0, 1.5, 2.0, 3.0, 5.0]


def significance_table() -> None:
    rows = []
    for p in available_cases():
        res = audit(p.parent)
        sig = (res.metrics.get("statistics") or {}).get("significance")
        if not sig or sig["psr_vs_0"] >= 0.95:
            continue
        ratio = sig["min_track_record_periods"] / sig["T"]
        rows.append((p.parent.parent.name + "/" + p.parent.name, sig["sharpe_per_period"], ratio))
    print("1. sharpe_significance below PSR 0.95: status by significance_review_ratio (R = review, i = INFO)")
    print(f"{'case':48} {'MinTRL/T':>9} " + " ".join(f"{r:>5g}" for r in RATIOS))
    counts = dict.fromkeys(RATIOS, 0)
    for name, sr, ratio in sorted(rows, key=lambda x: x[2]):
        marks = []
        for r in RATIOS:
            review = sr > 0 and (not math.isfinite(ratio) or ratio > r)
            counts[r] += review
            marks.append("R" if review else "i")
        print(f"{name:48} {ratio:9.2f} " + " ".join(f"{m:>5}" for m in marks))
    print(f"{'review items':48} {'':9} " + " ".join(f"{counts[r]:>5}" for r in RATIOS))
    print(f"cases below PSR 0.95: {len(rows)}")


def size_simulation(n_draws: int = 2000, seed: int = 20261028) -> None:
    rng = np.random.default_rng(seed)
    print(f"\n2. sharpe_autocorrelation size under i.i.d. normal returns ({n_draws} draws per T, seed {seed}, q = 252, "
          "lags 10)")
    print(f"{'T':>6} {'LB only':>8} {'LB or z1.96':>12} {'LB or z2.576':>13} {'review 1.96':>12} {'review 2.576':>13}")
    for T in (250, 1250):
        hits = np.zeros(5)
        for _ in range(n_draws):
            r = rng.normal(0.0005, 0.01, T)
            rho = stats.autocorrelations(r, 10)
            lb = stats.ljung_box(r, 10)["p_value"] < 0.05
            a196 = abs(rho[0]) > 1.96 / math.sqrt(T)
            a258 = abs(rho[0]) > 2.576 / math.sqrt(T)
            sr = stats.sharpe(r)
            eta = stats.lo_annualisation_factor(rho, 252)
            infl = (sr * math.sqrt(252)) / (sr * eta) > 1.10 if math.isfinite(eta) and sr != 0 else False
            hits += [lb, lb or a196, lb or a258, (lb or a196) and infl, (lb or a258) and infl]
        f = hits / n_draws
        print(f"{T:>6} {f[0]:8.3f} {f[1]:12.3f} {f[2]:13.3f} {f[3]:12.3f} {f[4]:13.3f}")
    print("'review' = the full review condition (significance AND naive Sharpe more than 10% above the Lo-adjusted).")


if __name__ == "__main__":
    significance_table()
    size_simulation()
