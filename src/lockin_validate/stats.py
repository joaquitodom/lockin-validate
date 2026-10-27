"""Statistics of backtest honesty, implemented from the published formulas (docs/CONVENTIONS.md, section 4).

References:
- Lo, A. (2002). "The Statistics of Sharpe Ratios". Financial Analysts Journal 58(4), 36-52.
  (standard error under i.i.d. returns and annualisation under autocorrelation)
- Bailey, D. and Lopez de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier". Journal of Risk 15(2).
  (Probabilistic Sharpe Ratio and Minimum Track Record Length)
- Bailey, D. and Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias,
  Backtest Overfitting and Non-Normality". Journal of Portfolio Management 40(5), 94-107.
- Bailey, D., Borwein, J., Lopez de Prado, M. and Zhu, Q. (2017). "The Probability of Backtest
  Overfitting". Journal of Computational Finance 20(4). (PBO via CSCV)
- Harvey, C. and Liu, Y. (2015). "Backtesting". Journal of Portfolio Management 42(1), 13-28.
  (multiple-testing haircut: Bonferroni, Holm, BHY)
- Benjamini, Y. and Yekutieli, D. (2001). Annals of Statistics 29(4), 1165-1188. (BHY)
- Ljung, G. and Box, G. (1978). Biometrika 65(2), 297-303. (portmanteau test)

Convention: a "per-period" Sharpe is NOT annualised (mean / std of the period returns). Annualised
values are reported separately. Kurtosis is the raw fourth standardised moment (normal = 3).
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def clean(r) -> np.ndarray:
    a = np.asarray(r, dtype=float)
    return a[np.isfinite(a)]


def moments(r) -> dict[str, float]:
    """T, mean, std (ddof=1), skewness and kurtosis (NOT excess; normal = 3)."""
    a = clean(r)
    T = a.size
    if T < 3:
        raise ValueError("at least 3 returns are needed")
    mu = float(a.mean())
    sd = float(a.std(ddof=1))
    sd0 = float(a.std(ddof=0))
    if sd0 == 0:
        return {"T": T, "mean": mu, "std": sd, "skew": 0.0, "kurt": 3.0}
    z = (a - mu) / sd0
    return {"T": T, "mean": mu, "std": sd, "skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean())}


def sharpe(r) -> float:
    """Per-period Sharpe ratio (not annualised, zero risk-free rate)."""
    m = moments(r)
    return m["mean"] / m["std"] if m["std"] > 0 else 0.0


def _sr_variance_term(sr: float, skew: float, kurt: float) -> float:
    return max(1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2, 1e-12)


def sharpe_se_iid(sr: float, T: int) -> float:
    """Lo (2002): standard error of the per-period Sharpe under i.i.d. normal returns."""
    return math.sqrt((1 + 0.5 * sr ** 2) / T)


def sharpe_se_nonnormal(sr: float, T: int, skew: float, kurt: float) -> float:
    """Standard error with skewness and kurtosis (Mertens 2002; as used in the PSR of Bailey and Lopez de Prado)."""
    return math.sqrt(_sr_variance_term(sr, skew, kurt) / (T - 1))


def probabilistic_sharpe(sr: float, sr_star: float, T: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """PSR(SR*) = P[true SR > SR*] (Bailey and Lopez de Prado 2012), per-period SR."""
    if T < 2:
        return float("nan")
    z = (sr - sr_star) * math.sqrt(T - 1) / math.sqrt(_sr_variance_term(sr, skew, kurt))
    return _N.cdf(z)


def min_track_record_length(sr: float, sr_star: float, skew: float = 0.0, kurt: float = 3.0,
                            alpha: float = 0.05) -> float:
    """Minimum number of periods for PSR(SR*) >= 1 - alpha. inf if SR <= SR*."""
    if sr <= sr_star:
        return float("inf")
    z = _N.inv_cdf(1 - alpha)
    return 1 + _sr_variance_term(sr, skew, kurt) * (z / (sr - sr_star)) ** 2


def expected_max_sharpe(var_sr: float, n_trials: int) -> float:
    """E[max SR] of n trials with true SR 0 and cross-trial variance var_sr (Bailey and Lopez de Prado 2014):
    sqrt(V) * ((1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N e))), g = Euler-Mascheroni constant."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    n = float(n_trials)
    return math.sqrt(var_sr) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n)
                                + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * math.e)))


def deflated_sharpe(sr: float, T: int, skew: float, kurt: float, n_trials: int, var_sr: float) -> dict[str, float]:
    """DSR = PSR(SR0) with SR0 = E[max SR] under the null."""
    sr0 = expected_max_sharpe(var_sr, n_trials)
    return {"sr0": sr0, "dsr": probabilistic_sharpe(sr, sr0, T, skew, kurt)}


def sharpe_pvalue(sr: float, T: int) -> float:
    """Two-sided p-value of the t-ratio SR * sqrt(T) (Harvey and Liu 2015, i.i.d. returns)."""
    return 2 * (1 - _N.cdf(abs(sr) * math.sqrt(T)))


def adjust_pvalues(pvals, method: str) -> np.ndarray:
    """Multiple-testing adjustment: 'bonferroni', 'holm' or 'bhy'."""
    p = np.asarray(pvals, dtype=float)
    m = p.size
    if m == 0:
        return p
    if method == "bonferroni":
        return np.minimum(1.0, p * m)
    order = np.argsort(p)
    ps = p[order]
    if method == "holm":
        adj = np.maximum.accumulate(np.minimum(1.0, (m - np.arange(m)) * ps))
    elif method == "bhy":
        c = np.sum(1.0 / np.arange(1, m + 1))
        raw = ps * m * c / np.arange(1, m + 1)
        adj = np.minimum(1.0, np.minimum.accumulate(raw[::-1])[::-1])
    else:
        raise ValueError(f"unknown method: {method}")
    out = np.empty(m)
    out[order] = adj
    return out


def haircut_sharpe(sr: float, T: int, n_trials: int, other_pvalues=None) -> dict[str, float]:
    """Multiple-testing haircut of the Sharpe ratio (Harvey and Liu 2015).

    If the p-values of the other trials are known they are used; otherwise the strategy is assumed to be the
    most significant of n_trials (rank 1), which is the usual situation when "the best" is reported.
    """
    p = sharpe_pvalue(sr, T)
    n = max(1, int(n_trials))
    if other_pvalues is not None and len(other_pvalues) >= 1:
        allp = np.r_[p, np.asarray(other_pvalues, dtype=float)]
        n = int(allp.size)
        adj = {m: float(adjust_pvalues(allp, m)[0]) for m in ("bonferroni", "holm", "bhy")}
    else:
        c = float(np.sum(1.0 / np.arange(1, n + 1)))
        adj = {"bonferroni": min(1.0, p * n), "holm": min(1.0, p * n), "bhy": min(1.0, p * n * c)}
    out: dict[str, float] = {"p_value": p, "n_trials": n}
    for m, pa in adj.items():
        if pa >= 1:
            sr_adj = 0.0
        elif pa <= 1e-15:
            sr_adj = abs(sr)
        else:
            sr_adj = _N.inv_cdf(1 - pa / 2) / math.sqrt(T)
        sr_adj = max(0.0, min(abs(sr), sr_adj)) * (1 if sr >= 0 else -1)
        out[f"p_{m}"] = pa
        out[f"sr_{m}"] = sr_adj
        out[f"haircut_{m}"] = 1 - (sr_adj / sr) if sr != 0 else 1.0
    return out


def autocorrelations(r, max_lag: int) -> list[float]:
    a = clean(r)
    T = a.size
    d = a - a.mean()
    den = float((d * d).sum())
    if den == 0:
        return [0.0] * max_lag
    return [float((d[k:] * d[:-k]).sum() / den) for k in range(1, max_lag + 1) if k < T]


def lo_annualisation_factor(rho: list[float], q: int) -> float:
    """eta(q) = q / sqrt(q + 2 * sum_{k=1}^{q-1} (q - k) rho_k) (Lo 2002, eq. 15); rho_k = 0 beyond len(rho)."""
    s = sum((q - k) * rho[k - 1] for k in range(1, min(q - 1, len(rho)) + 1))
    inner = q + 2 * s
    if inner <= 0:
        return float("nan")
    return q / math.sqrt(inner)


def ljung_box(r, max_lag: int) -> dict[str, float]:
    """Ljung-Box Q statistic with a Wilson-Hilferty chi-square approximation for the p-value."""
    a = clean(r)
    T = a.size
    rho = autocorrelations(a, max_lag)
    K = len(rho)
    if K == 0:
        return {"Q": float("nan"), "df": 0, "p_value": float("nan")}
    Q = T * (T + 2) * sum(rk ** 2 / (T - k) for k, rk in enumerate(rho, start=1))
    z = ((Q / K) ** (1 / 3) - (1 - 2 / (9 * K))) / math.sqrt(2 / (9 * K))
    return {"Q": float(Q), "df": K, "p_value": float(1 - _N.cdf(z))}


def subperiod_sharpes(r, index, cutoff) -> tuple[float | None, float | None, int, int]:
    """Per-period Sharpe before and after a cutoff date."""
    a = np.asarray(r, dtype=float)
    idx = list(index)
    pre = a[[i for i, d in enumerate(idx) if d is not None and d < cutoff]]
    post = a[[i for i, d in enumerate(idx) if d is not None and d >= cutoff]]
    s_pre = sharpe(pre) if pre.size >= 3 else None
    s_post = sharpe(post) if post.size >= 3 else None
    return s_pre, s_post, int(pre.size), int(post.size)


def cscv_pbo(M, n_splits: int = 16, max_combinations: int = 20000, seed: int = 0) -> dict[str, float]:
    """Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation.

    1. Matrix M of T x N (returns of N tried configurations).
    2. Split in S contiguous blocks (S even). For every combination of S/2 blocks as in-sample (IS) and the
       rest as out-of-sample (OOS): pick the configuration with the best IS Sharpe, measure its relative rank w
       OOS and the logit l = log(w / (1 - w)).
    3. PBO = share of combinations with l <= 0 (the chosen configuration ends in the bottom half OOS).
    """
    X = np.asarray(M, dtype=float)
    if X.ndim != 2 or X.shape[1] < 2:
        raise ValueError("a T x N matrix with N >= 2 trials is needed")
    if n_splits % 2:
        raise ValueError("n_splits must be even")
    T, N = X.shape
    S = min(n_splits, (T // 4) // 2 * 2)
    if S < 2:
        raise ValueError("too few observations for CSCV")
    L = T // S
    X = X[: L * S]
    blocks = X.reshape(S, L, N)
    bsum = blocks.sum(axis=1)
    bsq = (blocks ** 2).sum(axis=1)
    combos = list(combinations(range(S), S // 2))
    if len(combos) > max_combinations:
        rng = np.random.default_rng(seed)
        combos = [combos[i] for i in rng.choice(len(combos), max_combinations, replace=False)]
    mask = np.zeros((len(combos), S))
    for k, c in enumerate(combos):
        mask[k, list(c)] = 1.0
    n_is = L * (S // 2)

    def sr(sums, sqs, n):
        mean = sums / n
        var = np.maximum(sqs / n - mean ** 2, 1e-18) * n / (n - 1)
        return mean / np.sqrt(var)

    sr_is = sr(mask @ bsum, mask @ bsq, n_is)
    sr_oos = sr((1 - mask) @ bsum, (1 - mask) @ bsq, n_is)
    best = sr_is.argmax(axis=1)
    rows = np.arange(len(combos))
    chosen_oos = sr_oos[rows, best]
    below = (sr_oos < chosen_oos[:, None]).sum(axis=1)
    ties = (sr_oos == chosen_oos[:, None]).sum(axis=1) - 1
    rank = below + 0.5 * ties + 1
    w = rank / (N + 1)
    logits = np.log(w / (1 - w))
    chosen_is = sr_is[rows, best]
    slope = float(np.polyfit(chosen_is, chosen_oos, 1)[0]) if len(combos) > 2 and np.std(chosen_is) > 0 else float("nan")
    return {
        "pbo": float((logits <= 0).mean()),
        "n_combinations": len(combos),
        "n_blocks": S,
        "n_trials": N,
        "median_logit": float(np.median(logits)),
        "prob_oos_loss": float((chosen_oos < 0).mean()),
        "degradation_slope": slope,
        "mean_is_sharpe_of_chosen": float(chosen_is.mean()),
        "mean_oos_sharpe_of_chosen": float(chosen_oos.mean()),
    }
