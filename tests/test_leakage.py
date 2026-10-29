"""Leakage checks: a match's features must not change when its own result, or any later
result, changes. We build a synthetic three-season league in a temporary database."""
import itertools

import numpy as np
import pandas as pd
import pytest

from model import features as F
from pipeline import db

TEAMS = [f"t{i:02d}" for i in range(12)]


def synthetic_matches(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    strength = {t: rng.normal(0, 0.3) for t in TEAMS}
    rows = []
    for season in (2020, 2021, 2022):
        start = pd.Timestamp(f"{season}-08-15T14:00:00Z")
        pairs = list(itertools.permutations(TEAMS, 2))
        rng.shuffle(pairs)
        for i, (h, a) in enumerate(pairs):
            ko = start + pd.Timedelta(days=3 * (i // 6), hours=2 * (i % 6))
            lam = np.exp(0.3 + strength[h] - strength[a])
            mu = np.exp(0.1 + strength[a] - strength[h])
            gh, ga = rng.poisson(lam), rng.poisson(mu)
            rows.append({
                "match_id": f"E0-{season}-{h}-{a}", "div": "E0", "season": season,
                "kickoff_utc": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_id": h, "away_id": a,
                "status": "FINISHED", "gameweek": None, "fthg": gh, "ftag": ga,
                "hs": gh * 3 + rng.integers(5, 12), "as": ga * 3 + rng.integers(4, 10),
                "hst": gh + rng.integers(1, 5), "ast": ga + rng.integers(1, 4),
            })
    m = pd.DataFrame(rows)
    m["kickoff"] = pd.to_datetime(m["kickoff_utc"], utc=True)
    return m


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.sqlite")
    yield c
    c.close()


def build(conn, m):
    return F.build(conn, now=pd.Timestamp("2023-07-01T00:00:00Z"), first_season=2021, matches=m).frame.set_index("match_id")


def test_features_ignore_own_and_future_results(conn):
    m = synthetic_matches()
    base = build(conn, m)
    target = base[base["season"] == 2022].iloc[60]
    cutoff = target["kickoff"]

    # Scramble the target's result and every result after it.
    m2 = m.copy()
    later = m2["kickoff"] >= cutoff
    rng = np.random.default_rng(99)
    m2.loc[later, "fthg"] = rng.integers(0, 6, later.sum())
    m2.loc[later, "ftag"] = rng.integers(0, 6, later.sum())
    m2.loc[later, "hst"] = rng.integers(0, 12, later.sum())
    m2.loc[later, "ast"] = rng.integers(0, 12, later.sum())
    changed = build(conn, m2)

    before = base.loc[base["kickoff"] <= cutoff, F.FEATURES]
    after = changed.loc[before.index, F.FEATURES]
    pd.testing.assert_frame_equal(before, after, check_exact=False, rtol=1e-9, atol=1e-9)
    # Sanity: the scramble really did change later matches' features.
    later_ids = base.index[base["kickoff"] > cutoff + pd.Timedelta(days=7)]
    assert not np.allclose(base.loc[later_ids, "elo_diff"], changed.loc[later_ids, "elo_diff"])


def test_upcoming_match_features_use_only_finished_matches(conn):
    m = synthetic_matches()
    # Turn the last 30 matches into unplayed fixtures.
    m = m.sort_values("kickoff").reset_index(drop=True)
    tail = m.index[-30:]
    m.loc[tail, ["fthg", "ftag", "hs", "as", "hst", "ast"]] = np.nan
    m.loc[tail, "status"] = "SCHEDULED"
    m.loc[tail, "gameweek"] = 38
    now = m.loc[tail[0], "kickoff"] - pd.Timedelta(hours=1)
    fr = F.build(conn, now=now, first_season=2021, matches=m).frame
    up = fr[fr["status"] == "SCHEDULED"]
    assert len(up) == 30
    assert (up["y"] == -1).all()
    assert up["elo_home"].notna().all() and up["dc_ph"].notna().all()
    p = up[["dc_ph", "dc_pd", "dc_pa"]].sum(axis=1)
    assert np.allclose(p, 1.0, atol=1e-6)


def test_rest_days_are_positive_and_capped(conn):
    fr = build(conn, synthetic_matches())
    assert (fr["rest_h"] > 0).all() and (fr["rest_h"] <= F.REST_CAP_DAYS).all()
