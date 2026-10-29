import numpy as np
import pandas as pd
import pytest

from model import dixon_coles as dc
from model.elo import EloParams, run_elo
from model.features import FEATURES
from model.learners import Ensemble, GBMParams, make_gbm, make_logreg
from model.metrics import all_metrics, brier, calibration, implied_probs, log_loss, rps
from model.predict import adjust_matrix, confidence


def test_score_matrix_is_a_distribution():
    m = dc.score_matrix(1.6, 1.1, -0.08)
    assert m.shape == (11, 11)
    assert np.all(m >= 0)
    assert m.sum() == pytest.approx(1.0)
    p = dc.outcome_probs(m)
    assert p["p_home"] + p["p_draw"] + p["p_away"] == pytest.approx(1.0)
    assert p["p_home"] > p["p_away"]


def test_adjusted_matrix_matches_target_outcomes():
    m = dc.score_matrix(1.4, 1.2, -0.05)
    target = np.array([0.5, 0.2, 0.3])
    adj = adjust_matrix(m, target)
    got = dc.outcome_probs(adj)
    assert [got["p_home"], got["p_draw"], got["p_away"]] == pytest.approx(target.tolist())


def test_implied_probs_remove_margin():
    p = implied_probs([1.9], [3.5], [4.2])
    assert p.sum() == pytest.approx(1.0)
    assert p[0, 0] > p[0, 2]


def test_metrics_known_values():
    p = np.array([[1.0, 0.0, 0.0], [0.5, 0.3, 0.2]])
    y = np.array([0, 2])
    assert brier(p[:1], y[:1]) == pytest.approx(0.0)
    assert rps(p[:1], y[:1]) == pytest.approx(0.0)
    assert log_loss(p[1:], y[1:]) == pytest.approx(-np.log(0.2))
    # RPS for [0.5, 0.3, 0.2] when away wins: ((0.5-0)^2 + (0.8-0)^2) / 2
    assert rps(p[1:], y[1:]) == pytest.approx((0.25 + 0.64) / 2)
    m = all_metrics(p, y)
    assert m["accuracy"] == 0.5 and m["n"] == 2


def test_metrics_reject_probabilities_that_do_not_sum_to_one():
    with pytest.raises(ValueError):
        log_loss(np.array([[0.5, 0.3, 0.3]]), np.array([0]))


def test_calibration_bins_cover_all_forecasts():
    rng = np.random.default_rng(0)
    p = rng.dirichlet([3, 2, 2], size=500)
    y = np.array([rng.choice(3, p=row) for row in p])
    bins = calibration(p, y)
    assert sum(b["n"] for b in bins) == 1500
    assert all(0 <= b["observed"] <= 1 for b in bins)


@pytest.mark.parametrize("p,level", [([0.65, 0.2, 0.15], "high"), ([0.5, 0.3, 0.2], "medium"), ([0.38, 0.32, 0.30], "low")])
def test_confidence_levels(p, level):
    assert confidence(np.array(p)) == level


def test_ensemble_probabilities_sum_to_one():
    rng = np.random.default_rng(1)
    n = 400
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURES))), columns=FEATURES)
    p_dc = rng.dirichlet([4, 2.5, 3], size=n)
    X["dc_ph"], X["dc_pd"], X["dc_pa"] = p_dc[:, 0], p_dc[:, 1], p_dc[:, 2]
    X.loc[::7, "form5_ppg_h"] = np.nan  # missing data must not break anything
    y = rng.integers(0, 3, size=n)
    gbm = make_gbm(GBMParams(max_iter=20)).fit(X[FEATURES], y)
    lr = make_logreg(0.1).fit(X[FEATURES], y)
    ens = Ensemble(weights={"dc": 0.5, "gbm": 0.3, "logreg": 0.2}, gbm=gbm, logreg=lr)
    p = ens.predict(X)
    assert p.shape == (n, 3)
    assert np.allclose(p.sum(axis=1), 1.0)
    assert np.all((p > 0) & (p < 1))


def test_elo_is_zero_sum_and_rewards_winners():
    m = pd.DataFrame({
        "match_id": ["a", "b"], "div": ["E0", "E0"], "season": [2020, 2020],
        "kickoff_utc": ["2020-09-01T14:00:00Z", "2020-09-08T14:00:00Z"],
        "home_id": ["x", "y"], "away_id": ["y", "x"], "fthg": [3, 1], "ftag": [0, 1],
    })
    hist, ratings = run_elo(m, EloParams())
    first = hist.iloc[0]
    assert first["elo_home_post"] > first["elo_home_pre"]
    assert (first["elo_home_post"] - first["elo_home_pre"]) == pytest.approx(first["elo_away_pre"] - first["elo_away_post"])
    assert sum(ratings.values()) == pytest.approx(2 * EloParams().init_e0)
