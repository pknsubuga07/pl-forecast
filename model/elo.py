"""Goal-difference Elo over the Premier League and Championship together.

Running both divisions in one rating pool is how promoted clubs are handled: a promoted team
arrives with the rating it earned in the Championship, and rating points flow between the
divisions through the clubs that move up and down. Each summer every rating is pulled part of
the way back towards the mean of the division the club played in that season.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EloParams:
    k: float = 20.0
    home_adv: float = 60.0
    season_regression: float = 0.2
    init_e0: float = 1550.0
    init_e1: float = 1400.0


def expected_home(r_home: float, r_away: float, home_adv: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(r_home + home_adv - r_away) / 400.0))


def goal_multiplier(goal_diff: int, rating_gap: float) -> float:
    """Bigger wins move ratings more, damped when the favourite wins (FiveThirtyEight style)."""
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    return math.log(gd + 1) * (2.2 / (0.001 * rating_gap + 2.2))


def run_elo(matches: pd.DataFrame, params: EloParams = EloParams()) -> tuple[pd.DataFrame, dict[str, float]]:
    """matches: finished E0+E1 matches with columns match_id, div, season, kickoff_utc,
    home_id, away_id, fthg, ftag. Returns per-match pre/post ratings and the final ratings."""
    m = matches.sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)
    ratings: dict[str, float] = {}
    last_div: dict[str, str] = {}
    current_season = None
    out = np.empty((len(m), 4))
    for i, row in enumerate(m.itertuples(index=False)):
        if row.season != current_season:
            if current_season is not None:
                # Off-season regression towards the mean of the division each club just played in.
                for div in ("E0", "E1"):
                    members = [t for t, d in last_div.items() if d == div and t in ratings]
                    if members:
                        mean = float(np.mean([ratings[t] for t in members]))
                        for t in members:
                            ratings[t] = mean + (1 - params.season_regression) * (ratings[t] - mean)
            current_season = row.season
        for t in (row.home_id, row.away_id):
            if t not in ratings:
                ratings[t] = params.init_e0 if row.div == "E0" else params.init_e1
            last_div[t] = row.div
        rh, ra = ratings[row.home_id], ratings[row.away_id]
        exp_h = expected_home(rh, ra, params.home_adv)
        score = 1.0 if row.fthg > row.ftag else 0.5 if row.fthg == row.ftag else 0.0
        gap = (rh + params.home_adv - ra) if score == 1.0 else (ra - rh - params.home_adv) if score == 0.0 else 0.0
        delta = params.k * goal_multiplier(int(row.fthg - row.ftag), gap) * (score - exp_h)
        ratings[row.home_id] = rh + delta
        ratings[row.away_id] = ra - delta
        out[i] = (rh, ra, rh + delta, ra - delta)
    hist = pd.DataFrame(out, columns=["elo_home_pre", "elo_away_pre", "elo_home_post", "elo_away_post"])
    hist.insert(0, "match_id", m["match_id"].values)
    return hist, ratings


def season_start_ratings(ratings: dict[str, float], last_div: dict[str, str], params: EloParams) -> dict[str, float]:
    """Apply the off-season regression (used when predicting the first round of a new season)."""
    out = dict(ratings)
    for div in ("E0", "E1"):
        members = [t for t, d in last_div.items() if d == div and t in out]
        if members:
            mean = float(np.mean([out[t] for t in members]))
            for t in members:
                out[t] = mean + (1 - params.season_regression) * (out[t] - mean)
    return out
