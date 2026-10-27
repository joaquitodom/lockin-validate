import math
from datetime import date

import numpy as np
import pytest

from lockin_validate import metrics as M
from lockin_validate import stats
from lockin_validate.checks.llm_lookahead import exposure, score_checklist


def test_drawdown_and_return():
    nav = [100, 110, 99, 120, 90, 95]
    assert M.max_drawdown(nav) == pytest.approx(90 / 120 - 1)
    assert M.total_return(nav) == pytest.approx(-0.05)


def test_sharpe_conventions():
    nav = [100, 101, 100.5, 102, 103, 102.5, 104]
    s252, s365 = M.sharpe(nav, 252), M.sharpe(nav, 365)
    assert s365 / s252 == pytest.approx(math.sqrt(365 / 252))
    assert M.sharpe(nav, 252, rf_annual=0.04) < s252
    assert any(abs(x - s365) < 1e-12 for x in M.sharpe_variants(nav).values())


def test_flat_nav_has_no_sharpe():
    assert math.isnan(M.sharpe([100, 100, 100]))


def test_dsr_matches_bailey_lopez_de_prado_2014_example():
    # Numerical example of the paper: annual SR 2.5, T = 1250 daily, skew -3, kurtosis 10, N = 100 trials, annual
    # cross-trial variance of the Sharpe 0.5. E[max SR] = 0.1132 per period, DSR ~ 0.90.
    sr = 2.5 / math.sqrt(250)
    var = 0.5 / 250
    assert stats.expected_max_sharpe(var, 100) == pytest.approx(0.1132, abs=5e-4)
    assert stats.deflated_sharpe(sr, 1250, -3, 10, 100, var)["dsr"] == pytest.approx(0.9004, abs=2e-3)


def test_psr_properties():
    assert stats.probabilistic_sharpe(0.0, 0.0, 100) == pytest.approx(0.5)
    assert stats.probabilistic_sharpe(0.1, 0.0, 1000) > stats.probabilistic_sharpe(0.1, 0.0, 100)
    assert stats.probabilistic_sharpe(0.1, 0, 500, -2, 10) < stats.probabilistic_sharpe(0.1, 0, 500)


def test_min_trl_is_where_psr_reaches_95():
    sr, sk, ku = 0.08, -0.5, 5.0
    n = stats.min_track_record_length(sr, 0.0, sk, ku)
    assert stats.probabilistic_sharpe(sr, 0.0, math.ceil(n), sk, ku) >= 0.95
    assert stats.probabilistic_sharpe(sr, 0.0, math.floor(n) - 5, sk, ku) < 0.95
    assert stats.min_track_record_length(0.0, 0.0) == math.inf


def test_expected_max_grows_with_trials():
    a = [stats.expected_max_sharpe(1e-3, n) for n in (1, 2, 10, 100, 1000)]
    assert a[0] == 0.0 and all(x < y for x, y in zip(a, a[1:]))


def test_se_iid_lo():
    assert stats.sharpe_se_iid(0.0, 100) == pytest.approx(0.1)
    assert stats.sharpe_se_iid(1.0, 100) == pytest.approx(math.sqrt(1.5 / 100))


def test_adjust_pvalues_known_values():
    p = [0.01, 0.04, 0.03, 0.005]
    assert list(stats.adjust_pvalues(p, "bonferroni")) == pytest.approx([0.04, 0.16, 0.12, 0.02])
    assert list(stats.adjust_pvalues(p, "holm")) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    bhy = stats.adjust_pvalues(p, "bhy")
    assert bhy[3] == pytest.approx(min(1, 0.02 * (1 + 1 / 2 + 1 / 3 + 1 / 4)))
    assert np.all(bhy >= np.asarray(p))


def test_haircut_grows_with_trials():
    sr, T = 2.0 / math.sqrt(252), 252 * 5
    one = stats.haircut_sharpe(sr, T, 1)
    many = stats.haircut_sharpe(sr, T, 100)
    assert one["haircut_bonferroni"] == pytest.approx(0, abs=1e-9)
    assert many["haircut_bhy"] > many["haircut_bonferroni"] > 0.2


def test_lo_factor_iid_and_ar1():
    assert stats.lo_annualisation_factor([0.0] * 10, 12) == pytest.approx(math.sqrt(12))
    phi = 0.5
    rho = [phi ** k for k in range(1, 12)]
    eta = stats.lo_annualisation_factor(rho, 12)
    assert eta < math.sqrt(12)  # positive autocorrelation: naive sqrt(q) overstates
    assert stats.lo_annualisation_factor([-0.3] + [0.0] * 10, 12) > math.sqrt(12)


def test_ljung_box_detects_ar1():
    rng = np.random.default_rng(0)
    e = rng.normal(0, 1, 2000)
    x = np.empty_like(e)
    prev = 0.0
    for i, v in enumerate(e):
        prev = 0.5 * prev + v
        x[i] = prev
    assert stats.ljung_box(x, 10)["p_value"] < 1e-6
    assert stats.ljung_box(e, 10)["p_value"] > 0.01


def test_pbo_noise_near_half_and_edge_low():
    rng = np.random.default_rng(1)
    p = stats.cscv_pbo(rng.normal(0, 0.01, (1000, 50)), n_splits=10)
    assert 0.2 < p["pbo"] < 0.8 and p["n_combinations"] == 252
    M2 = np.random.default_rng(2).normal(0, 0.01, (1000, 30))
    M2[:, 7] += 0.004
    q = stats.cscv_pbo(M2, n_splits=10)
    assert q["pbo"] < 0.05 and q["prob_oos_loss"] < 0.05
    with pytest.raises(ValueError):
        stats.cscv_pbo(np.zeros((100, 1)))
    with pytest.raises(ValueError):
        stats.cscv_pbo(np.zeros((100, 3)), n_splits=5)


def test_llm_exposure_and_scores():
    before, _ = exposure(date(2015, 1, 1), date(2021, 1, 1), date(2023, 1, 1))
    assert before == 1.0
    before, _ = exposure(date(2020, 1, 1), date(2022, 1, 1), date(2021, 1, 1))
    assert before == pytest.approx(0.5, abs=0.01)
    assert score_checklist({"uses_llm": False})["applies"] is False
    worst = score_checklist({"uses_llm": True, "model_training_cutoff": "2023-10", "backtest_start": "2015-01-01",
                             "backtest_end": "2020-12-31", "uses_company_names": True, "uses_tickers": True,
                             "uses_explicit_dates": True, "uses_news_or_filings_text": True,
                             "anonymized_entities": False, "retrieval_pit_filtered": False,
                             "post_cutoff_evaluation": False, "memorization_probe_done": False})
    safe = score_checklist({"uses_llm": True, "pit_model": True, "uses_company_names": False, "uses_tickers": False,
                            "uses_explicit_dates": False, "uses_news_or_filings_text": False,
                            "anonymized_entities": True, "retrieval_pit_filtered": True,
                            "post_cutoff_evaluation": True, "memorization_probe_done": True})
    unknown = score_checklist({"uses_llm": True})
    assert worst["score"] > 90 and safe["score"] == 0
    assert safe["score"] < unknown["score"] < worst["score"]
