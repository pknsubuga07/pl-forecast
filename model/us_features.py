"""Pre-game features for NBA and NFL games.

Same leakage rule as the Premier League model: "state after game" rows from finished games are
attached to each target game with a strict before-kickoff as-of join, so nothing from the game
itself or later can leak in. Elo is computed sequentially and each game gets its pre-game rating.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features import _asof


@dataclass(frozen=True)
class SportConfig:
    sport: str
    first_season: int          # first season loaded (Elo / form warm-up)
    first_train_season: int    # first season used as training targets
    validation: tuple[int, ...]
    test: tuple[int, ...]
    windows: tuple[int, int]   # short / long rolling windows (games)
    rest_cap: float
    stale_days: int            # rolling form older than this is dropped
    upcoming_days: int         # how far ahead the dashboard predicts
    elo_grid: dict


NFL = SportConfig("nfl", 1999, 2002, (2016, 2017, 2018, 2019, 2020), (2021, 2022, 2023, 2024, 2025),
                  (4, 10), 14.0, 250, 14,
                  {"k": [15, 20, 25], "home_adv": [35, 50, 65], "season_regression": [0.25, 0.33, 0.5]})
NBA = SportConfig("nba", 2012, 2014, (2016, 2017, 2018, 2019, 2020), (2021, 2022, 2023, 2024, 2025),
                  (5, 15), 5.0, 200, 7,
                  {"k": [8, 12, 18], "home_adv": [40, 60, 80], "season_regression": [0.15, 0.25, 0.4]})
CONFIGS = {"nfl": NFL, "nba": NBA}

FEATURES = {
    "common": ["elo_home", "elo_away", "elo_diff", "neutral", "playoff",
               "margin_s_h", "margin_s_a", "margin_l_h", "margin_l_a",
               "pf_l_h", "pf_l_a", "pa_l_h", "pa_l_a",
               "venue_margin_h", "venue_margin_a",
               "std_winpct_h", "std_winpct_a", "std_margin_h", "std_margin_a", "season_game",
               "rest_h", "rest_a"],
    "nba": ["b2b_h", "b2b_a"],
    "nfl": ["qb_change_h", "qb_change_a"],
}


def feature_list(sport: str) -> list[str]:
    return FEATURES["common"] + FEATURES[sport]


@dataclass(frozen=True)
class EloParams:
    k: float = 20.0
    home_adv: float = 50.0
    season_regression: float = 0.33


def run_elo(fin: pd.DataFrame, p: EloParams) -> tuple[pd.DataFrame, dict[str, float], int]:
    """Margin-of-victory Elo (FiveThirtyEight style). fin: finished games sorted by kickoff."""
    ratings: dict[str, float] = {}
    season = None
    out = np.empty((len(fin), 4))
    for i, g in enumerate(fin.itertuples(index=False)):
        if g.season != season:
            if season is not None:
                for t in ratings:
                    ratings[t] = 1500 + (1 - p.season_regression) * (ratings[t] - 1500)
            season = g.season
        rh, ra = ratings.setdefault(g.home_id, 1500.0), ratings.setdefault(g.away_id, 1500.0)
        hfa = 0.0 if g.neutral else p.home_adv
        diff = rh + hfa - ra
        exp = 1 / (1 + 10 ** (-diff / 400))
        margin = g.home_score - g.away_score
        res = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        winner_gap = diff if margin > 0 else -diff
        mult = np.log(abs(margin) + 1) * 2.2 / (winner_gap * 0.001 + 2.2) if margin != 0 else 1.0
        delta = p.k * mult * (res - exp)
        ratings[g.home_id], ratings[g.away_id] = rh + delta, ra - delta
        out[i] = (rh, ra, rh + delta, ra - delta)
    hist = pd.DataFrame(out, columns=["elo_home_pre", "elo_away_pre", "elo_home_post", "elo_away_post"])
    hist.insert(0, "game_id", fin["game_id"].values)
    return hist, ratings, int(season) if season is not None else 0


def load_games(conn: sqlite3.Connection, sport: str) -> pd.DataFrame:
    g = pd.read_sql_query("SELECT * FROM us_games WHERE sport = ?", conn, params=(sport,))
    g["kickoff"] = pd.to_datetime(g["kickoff_utc"], utc=True, errors="coerce")
    return g.sort_values(["kickoff", "game_id"]).reset_index(drop=True)


def team_game_table(fin: pd.DataFrame) -> pd.DataFrame:
    base = dict(kickoff=fin["kickoff"], season=fin["season"], game_id=fin["game_id"])
    h = pd.DataFrame({**base, "team": fin["home_id"], "is_home": 1, "pf": fin["home_score"], "pa": fin["away_score"],
                      "qb": fin.get("home_qb"), "neutral": fin["neutral"]})
    a = pd.DataFrame({**base, "team": fin["away_id"], "is_home": 0, "pf": fin["away_score"], "pa": fin["home_score"],
                      "qb": fin.get("away_qb"), "neutral": fin["neutral"]})
    t = pd.concat([h, a], ignore_index=True).sort_values(["team", "kickoff"]).reset_index(drop=True)
    t["margin"] = t["pf"] - t["pa"]
    t["win"] = (t["margin"] > 0).astype(float) + 0.5 * (t["margin"] == 0)
    return t


@dataclass
class USFeatureSet:
    frame: pd.DataFrame
    elo_history: pd.DataFrame
    elo_current: dict[str, float]


def build(conn: sqlite3.Connection | None, cfg: SportConfig, elo: EloParams, now: pd.Timestamp | None = None,
          games: pd.DataFrame | None = None) -> USFeatureSet:
    now = now or pd.Timestamp.now(tz="UTC")
    g = load_games(conn, cfg.sport) if games is None else games.sort_values(["kickoff", "game_id"]).reset_index(drop=True)
    g = g[g["season"] >= cfg.first_season]
    fin = g[(g["status"] == "FINISHED") & g["home_score"].notna() & (g["kickoff"] < now)].copy()
    tgt = g[(g["season"] >= cfg.first_train_season) &
            ((g["status"] == "FINISHED") | ((g["status"] == "SCHEDULED") & g["kickoff"].notna()))].copy()
    tgt = tgt.reset_index(drop=True)
    tgt["_row"] = tgt.index

    hist, ratings, last_season = run_elo(fin, elo)
    cur_season = int(tgt["season"].max()) if len(tgt) else last_season
    current = ({t: 1500 + (1 - elo.season_regression) * (r - 1500) for t, r in ratings.items()}
               if cur_season > last_season else dict(ratings))
    pre = hist.set_index("game_id")
    tgt["elo_home"] = tgt["game_id"].map(pre["elo_home_pre"])
    tgt["elo_away"] = tgt["game_id"].map(pre["elo_away_pre"])
    up = tgt["status"] != "FINISHED"
    if up.any():
        tgt.loc[up, "elo_home"] = tgt.loc[up, "home_id"].map(lambda t: current.get(t, 1500.0)).astype(float)
        tgt.loc[up, "elo_away"] = tgt.loc[up, "away_id"].map(lambda t: current.get(t, 1500.0)).astype(float)
    tgt["elo_diff"] = tgt["elo_home"] - tgt["elo_away"]
    tgt["playoff"] = (tgt["season_type"] == "POST").astype(int)
    tgt["neutral"] = tgt["neutral"].fillna(0).astype(int)

    tm = team_game_table(fin)
    ws, wl = cfg.windows
    grp = tm.groupby("team", group_keys=False)
    st = tm[["team", "kickoff"]].copy()
    st["margin_s"] = grp["margin"].apply(lambda x: x.rolling(ws, min_periods=2).mean())
    st["margin_l"] = grp["margin"].apply(lambda x: x.rolling(wl, min_periods=3).mean())
    st["pf_l"] = grp["pf"].apply(lambda x: x.rolling(wl, min_periods=3).mean())
    st["pa_l"] = grp["pa"].apply(lambda x: x.rolling(wl, min_periods=3).mean())
    st["last"] = st["kickoff"]
    # Season to date (resets every season).
    sg = tm.groupby(["team", "season"], group_keys=False)
    st["std_winpct"] = sg["win"].apply(lambda x: x.expanding().mean())
    st["std_margin"] = sg["margin"].apply(lambda x: x.expanding().mean())
    st["std_n"] = sg["win"].cumcount() + 1
    st["season"] = tm["season"]
    if cfg.sport == "nfl":
        # Most common starting QB over the team's last 4 games (state after each game).
        usual: list[str | None] = [None] * len(tm)
        qbs = tm["qb"].to_numpy()
        for idx in tm.groupby("team").indices.values():
            for k, i in enumerate(idx):
                window = [q for q in qbs[idx[max(0, k - 3):k + 1]] if isinstance(q, str) and q]
                usual[i] = Counter(window).most_common(1)[0][0] if window else None
        st["usual_qb"] = usual

    for side, col in (("h", "home_id"), ("a", "away_id")):
        t = tgt[["_row", col, "kickoff"]].rename(columns={col: "team"})
        cols = {"margin_s": f"margin_s_{side}", "margin_l": f"margin_l_{side}", "pf_l": f"pf_l_{side}",
                "pa_l": f"pa_l_{side}", "last": "_last", "std_winpct": "_wp", "std_margin": "_sm", "std_n": "_n",
                "season": "_season"}
        if cfg.sport == "nfl":
            cols["usual_qb"] = "_qb"
        j = _asof(t, st, "team", cols)
        stale = (tgt["kickoff"] - j["_last"]).dt.days > cfg.stale_days
        for c in ("margin_s", "margin_l", "pf_l", "pa_l"):
            tgt[f"{c}_{side}"] = j[f"{c}_{side}"].where(~stale)
        same = j["_season"] == tgt["season"]
        tgt[f"std_winpct_{side}"] = j["_wp"].where(same)
        tgt[f"std_margin_{side}"] = j["_sm"].where(same)
        tgt[f"_n_{side}"] = j["_n"].where(same).fillna(0)
        rest = (tgt["kickoff"] - j["_last"]).dt.total_seconds() / 86400
        tgt[f"rest_{side}"] = rest.clip(upper=cfg.rest_cap).fillna(cfg.rest_cap)
        if cfg.sport == "nba":
            tgt[f"b2b_{side}"] = (rest < 1.6).astype(int)
        else:
            qb_col = "home_qb" if side == "h" else "away_qb"
            tgt[f"qb_change_{side}"] = ((tgt[qb_col].notna()) & (j["_qb"].notna()) & (tgt[qb_col] != j["_qb"])).astype(int)
    tgt["season_game"] = tgt[["_n_h", "_n_a"]].mean(axis=1)

    # Home team's recent home margin, away team's recent away margin.
    for side, col, is_home in (("h", "home_id", 1), ("a", "away_id", 0)):
        v = tm[(tm["is_home"] == is_home) & (tm["neutral"] == 0)]
        vs = v[["team", "kickoff"]].copy()
        vs["vm"] = v.groupby("team", group_keys=False)["margin"].apply(lambda x: x.rolling(cfg.windows[1], min_periods=3).mean())
        vs["last"] = vs["kickoff"]
        t = tgt[["_row", col, "kickoff"]].rename(columns={col: "team"})
        j = _asof(t, vs, "team", {"vm": f"venue_margin_{side}", "last": "_last"})
        stale = (tgt["kickoff"] - j["_last"]).dt.days > cfg.stale_days * 2
        tgt[f"venue_margin_{side}"] = j[f"venue_margin_{side}"].where(~stale)

    tgt["margin"] = tgt["home_score"] - tgt["away_score"]
    tgt["total"] = tgt["home_score"] + tgt["away_score"]
    tgt["y"] = np.where(tgt["status"] == "FINISHED", np.where(tgt["margin"] > 0, 1, np.where(tgt["margin"] < 0, 0, -2)), -1)
    return USFeatureSet(frame=tgt.drop(columns=["_row", "_n_h", "_n_a"]), elo_history=hist, elo_current=current)
