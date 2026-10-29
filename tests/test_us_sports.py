from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from model import ledger
from model import us_features as U
from model.us_models import USEnsemble, binary_metrics, fit_margin, make_elo_lr, make_gbm, make_ridge, GBMParams, market_home_prob
from model.us_predict import confidence
from pipeline import us_ingest
from pipeline.http import SourceError
from pipeline.teams import TeamMapper, UnknownTeamError
from pipeline.us_export import LEDGER_COLUMNS

HEADER = ("game_id,season,game_type,week,gameday,weekday,gametime,away_team,away_score,home_team,home_score,location,"
          "result,total,overtime,espn,away_rest,home_rest,away_moneyline,home_moneyline,spread_line,total_line,"
          "away_qb_name,home_qb_name,stadium\n")


@pytest.fixture(scope="module")
def mapper():
    return TeamMapper.from_csv()


def test_nflverse_parsing_handles_relocations_spreads_and_times(mapper):
    csv = HEADER + (
        "2019_01_KC_OAK,2019,REG,1,2019-09-09,Monday,22:20,KC,28,OAK,10,Home,-18,38,0,401,7,7,-300,250,-7,52,P Mahomes,D Carr,Oakland Coliseum\n"
        "2026_09_NE_LA,2026,REG,9,2026-11-08,Sunday,16:25,NE,NA,LA,NA,Neutral,NA,NA,NA,402,7,7,NA,NA,NA,NA,D Maye,M Stafford,Somewhere\n"
    )
    games, odds = us_ingest.parse_nflverse(csv, mapper)
    g1, g2 = games
    assert g1["home_id"] == "nfl-lv" and g1["away_id"] == "nfl-kc"       # Oakland Raiders -> Las Vegas franchise
    assert g1["kickoff_utc"] == "2019-09-10T02:20:00Z"                    # 10:20 pm ET (EDT) -> UTC
    assert g1["status"] == "FINISHED" and g1["home_score"] == 10
    assert g2["home_id"] == "nfl-lar" and g2["neutral"] == 1 and g2["status"] == "SCHEDULED"
    assert g2["kickoff_utc"] == "2026-11-08T21:25:00Z"                    # after DST ends: EST (UTC-5)
    assert len(odds) == 1
    assert odds[0]["home_spread"] == 7.0  # nflverse spread_line -7 = home underdog by 7 -> home line +7


def test_nflverse_format_change_is_a_source_error(mapper):
    with pytest.raises(SourceError):
        us_ingest.parse_nflverse("<html>rate limited</html>", mapper)
    with pytest.raises(SourceError, match="missing columns"):
        us_ingest.parse_nflverse("game_id,season\nx,2020\n", mapper)


def test_us_team_names_are_exact_match_only(mapper):
    assert mapper.resolve("espn-nba", "2") == "nba-bos"
    with pytest.raises(UnknownTeamError):
        mapper.resolve("nflverse", "XYZ")
    # NBA/NFL names never leak into the loose Premier League matching.
    with pytest.raises(UnknownTeamError):
        mapper.resolve("fpl", "Boston Celtics")


def test_espn_event_parsing(mapper):
    e = {"id": "123", "date": "2026-10-30T23:00Z", "seasonType": {"type": 2},
         "competitions": [{"neutralSite": False, "venue": {"fullName": "TD Garden"},
                           "status": {"type": {"name": "STATUS_FINAL", "completed": True, "state": "post"}},
                           "competitors": [{"homeAway": "home", "team": {"id": "2"}, "score": {"value": 110.0}},
                                           {"homeAway": "away", "team": {"id": "1"}, "score": "101"}]}]}
    g = us_ingest._espn_event(e, "nba", mapper)
    assert (g["home_id"], g["away_id"], g["home_score"], g["away_score"]) == ("nba-bos", "nba-atl", 110, 101)
    assert g["status"] == "FINISHED" and g["season"] == 2026 and g["venue"] == "TD Garden"


def test_moneyline_probabilities():
    p = market_home_prob(np.array([-200.0, 150.0]), np.array([170.0, -180.0]))
    assert 0.5 < p[0] < 0.7 and 0.3 < p[1] < 0.5
    # Margin removed: home + away = 1
    pa = market_home_prob(np.array([170.0]), np.array([-200.0]))
    assert p[0] + pa[0] == pytest.approx(1.0)


def test_binary_metrics_and_confidence():
    m = binary_metrics([0.8, 0.3], [1, 0])
    assert m["accuracy"] == 1.0
    assert m["brier"] == pytest.approx((0.04 + 0.09) / 2)
    assert confidence(0.8) == "high" and confidence(0.3) == "medium" and confidence(0.55) == "low"


# ------------------------------------------------------------------ leakage on synthetic league
TEAMS = [f"nba-t{i}" for i in range(10)]


def synthetic(seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    strength = {t: rng.normal(0, 4) for t in TEAMS}
    rows = []
    for season in (2016, 2017, 2018):
        ko = pd.Timestamp(f"{season}-10-20T23:00Z")
        for rnd in range(30):
            perm = rng.permutation(TEAMS)
            for i in range(0, 10, 2):
                h, a = perm[i], perm[i + 1]
                m = strength[h] - strength[a] + 3 + rng.normal(0, 12)
                hs = int(105 + m / 2); as_ = int(105 - m / 2)
                if hs == as_:
                    hs += 1
                rows.append({"game_id": f"g{season}{rnd}{i}", "sport": "nba", "season": season, "season_type": "REG",
                             "week": None, "kickoff": ko + pd.Timedelta(days=2 * rnd, minutes=i), "home_id": h, "away_id": a,
                             "neutral": 0, "status": "FINISHED", "home_score": hs, "away_score": as_, "home_qb": None, "away_qb": None})
    g = pd.DataFrame(rows)
    g["kickoff_utc"] = g["kickoff"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return g


CFG = U.SportConfig("nba", 2016, 2017, (2017,), (2018,), (5, 15), 5.0, 200, 7, {})


def test_us_features_ignore_own_and_future_results():
    g = synthetic()
    base = U.build(None, CFG, U.EloParams(), now=pd.Timestamp("2019-07-01", tz="UTC"), games=g).frame.set_index("game_id")
    target = base[base["season"] == 2018].iloc[40]
    later = g["kickoff"] >= target["kickoff"]
    g2 = g.copy()
    rng = np.random.default_rng(5)
    g2.loc[later, "home_score"] = rng.integers(80, 140, later.sum())
    g2.loc[later, "away_score"] = rng.integers(80, 140, later.sum())
    changed = U.build(None, CFG, U.EloParams(), now=pd.Timestamp("2019-07-01", tz="UTC"), games=g2).frame.set_index("game_id")
    feats = U.feature_list("nba")
    before = base.loc[base["kickoff"] <= target["kickoff"], feats]
    pd.testing.assert_frame_equal(before, changed.loc[before.index, feats], check_exact=False, atol=1e-9)
    after_ids = base.index[base["kickoff"] > target["kickoff"] + pd.Timedelta(days=4)]
    assert not np.allclose(base.loc[after_ids, "elo_diff"], changed.loc[after_ids, "elo_diff"])


def test_us_ensemble_probabilities_and_scores():
    fr = U.build(None, CFG, U.EloParams(), now=pd.Timestamp("2019-07-01", tz="UTC"), games=synthetic()).frame
    feats = U.feature_list("nba")
    ens = USEnsemble("nba", feats, {"elo": 0.3, "margin": 0.5, "gbm": 0.2},
                     make_elo_lr().fit(fr[["elo_diff", "neutral"]], fr["y"]), fit_margin(fr[feats], fr["margin"], 10.0),
                     make_ridge(10.0).fit(fr[feats], fr["total"]), make_gbm(GBMParams(max_iter=20)).fit(fr[feats], fr["y"]))
    p = ens.predict(fr)
    assert np.all((p > 0) & (p < 1))
    margin = ens.predict_margin(fr)
    assert np.all(np.sign(margin) == np.sign(p - 0.5))  # projected winner matches the probability
    assert 150 < ens.predict_total(fr).mean() < 270


def test_ledger_keyed_by_game_id():
    rows = {}
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    ko = (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = {"game_id": "nba-1", "kickoff_utc": ko, "p_home": 0.6, "p_away": 0.4, "pred_margin": 3.1}
    ledger.update(rows, [p], {}, now, columns=LEDGER_COLUMNS)
    assert rows["nba-1"]["pred_margin"] == "3.1"
    ledger.update(rows, [{**p, "p_home": 0.9}], {"nba-1": {"kickoff_utc": ko, "status": "IN_PLAY"}}, now + timedelta(hours=4),
                  columns=LEDGER_COLUMNS)
    assert rows["nba-1"]["locked"] == "1" and rows["nba-1"]["p_home"] == "0.6"
