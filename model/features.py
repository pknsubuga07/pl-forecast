"""Pre-match features for Premier League matches.

Leakage rule: every feature for a match is computed only from information dated strictly
before its kickoff. The mechanism is the same everywhere: we build "state after match" rows
from finished matches, then attach them to target matches with an as-of join that excludes
exact timestamp matches (pd.merge_asof(..., allow_exact_matches=False)). Dixon-Coles ratings
come from walk-forward fits that only see matches before the fit date.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pipeline.config import FIRST_TRAIN_SEASON, POINT_DEDUCTIONS_CSV

from . import dixon_coles as dc
from .elo import EloParams, run_elo, season_start_ratings

log = logging.getLogger(__name__)

STALE_DAYS = 400       # rolling form older than this (e.g. a promoted club's last PL stint) is dropped
REST_CAP_DAYS = 14.0   # "fully rested"; also used at the start of a season


FEATURES = [
    "elo_home", "elo_away", "elo_diff",
    "dc_lambda", "dc_mu", "dc_ph", "dc_pa",
    "form5_ppg_h", "form5_ppg_a", "gd10_h", "gd10_a", "sotd10_h", "sotd10_a", "sd10_h", "sd10_a",
    "venue_ppg_h", "venue_ppg_a", "venue_gd_h", "venue_gd_a",
    "std_ppg_h", "std_ppg_a", "std_gdpg_h", "std_gdpg_a", "pos_h", "pos_a", "season_round",
    "rest_h", "rest_a", "euro_h", "euro_a", "promoted_h", "promoted_a",
]

# Groups used for plain-English explanations (see model/explain.py).
FEATURE_GROUPS = {
    "strength": ["elo_home", "elo_away", "elo_diff"],
    "goal_model": ["dc_lambda", "dc_mu", "dc_ph", "dc_pa"],
    "recent_form": ["form5_ppg_h", "form5_ppg_a", "gd10_h", "gd10_a"],
    "shots": ["sotd10_h", "sotd10_a", "sd10_h", "sd10_a"],
    "venue_form": ["venue_ppg_h", "venue_ppg_a", "venue_gd_h", "venue_gd_a"],
    "table": ["std_ppg_h", "std_ppg_a", "std_gdpg_h", "std_gdpg_a", "pos_h", "pos_a"],
    "rest": ["rest_h", "rest_a", "euro_h", "euro_a"],
    "promoted": ["promoted_h", "promoted_a"],
}


def load_matches(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM matches", conn)
    df["kickoff"] = pd.to_datetime(df["kickoff_utc"], utc=True, errors="coerce")
    return df


def load_other(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT team_id, kickoff_utc, competition, status FROM other_matches", conn)
    df["kickoff"] = pd.to_datetime(df["kickoff_utc"], utc=True, errors="coerce")
    bad = df["status"].fillna("").str.contains("POSTPONED|CANCELED|CANCELLED", regex=True)
    return df.loc[~bad & df["kickoff"].notna()]


def outcome(fthg, ftag) -> np.ndarray:
    """0 = home win, 1 = draw, 2 = away win."""
    fthg, ftag = np.asarray(fthg), np.asarray(ftag)
    return np.where(fthg > ftag, 0, np.where(fthg == ftag, 1, 2))


# --------------------------------------------------------------------------- helpers
def _asof(targets: pd.DataFrame, states: pd.DataFrame, by: str, prefix_cols: dict[str, str]) -> pd.DataFrame:
    """Attach the latest state strictly before each target's kickoff."""
    t = targets[["_row", by, "kickoff"]].sort_values("kickoff")
    s = states.sort_values("kickoff")[[by, "kickoff", *prefix_cols]].rename(columns=prefix_cols)
    s = s.rename(columns={"kickoff": "_state_time"})
    s["kickoff"] = s["_state_time"]
    # Same key dtype on both sides (an empty source table comes back as object dtype).
    t[by] = t[by].astype(str)
    s[by] = s[by].astype(str)
    out = pd.merge_asof(t, s, on="kickoff", by=by, allow_exact_matches=False, direction="backward")
    return out.set_index("_row").sort_index()


def team_match_table(fin: pd.DataFrame) -> pd.DataFrame:
    """Two rows per finished E0 match, from each team's point of view."""
    cols = dict(kickoff=fin["kickoff"], season=fin["season"])
    home = pd.DataFrame({**cols, "team": fin["home_id"], "is_home": 1, "gf": fin["fthg"], "ga": fin["ftag"],
                         "sf": fin["hs"], "sa": fin["as"], "stf": fin["hst"], "sta": fin["ast"]})
    away = pd.DataFrame({**cols, "team": fin["away_id"], "is_home": 0, "gf": fin["ftag"], "ga": fin["fthg"],
                         "sf": fin["as"], "sa": fin["hs"], "stf": fin["ast"], "sta": fin["hst"]})
    t = pd.concat([home, away], ignore_index=True).sort_values(["team", "kickoff"]).reset_index(drop=True)
    t["pts"] = np.where(t["gf"] > t["ga"], 3, np.where(t["gf"] == t["ga"], 1, 0))
    t["gd"] = t["gf"] - t["ga"]
    t["sd"] = t["sf"] - t["sa"]
    t["sotd"] = t["stf"] - t["sta"]
    return t


def rolling_states(tm: pd.DataFrame) -> pd.DataFrame:
    g = tm.groupby("team", group_keys=False)
    s = tm[["team", "kickoff"]].copy()
    s["form5_ppg"] = g["pts"].apply(lambda x: x.rolling(5, min_periods=3).mean())
    s["gd10"] = g["gd"].apply(lambda x: x.rolling(10, min_periods=4).mean())
    s["sd10"] = g["sd"].apply(lambda x: x.rolling(10, min_periods=4).mean())
    s["sotd10"] = g["sotd"].apply(lambda x: x.rolling(10, min_periods=4).mean())
    return s


def venue_states(tm: pd.DataFrame, is_home: int) -> pd.DataFrame:
    v = tm[tm["is_home"] == is_home]
    g = v.groupby("team", group_keys=False)
    s = v[["team", "kickoff"]].copy()
    s["venue_ppg"] = g["pts"].apply(lambda x: x.rolling(10, min_periods=4).mean())
    s["venue_gd"] = g["gd"].apply(lambda x: x.rolling(10, min_periods=4).mean())
    return s


def load_deductions() -> pd.DataFrame:
    try:
        d = pd.read_csv(POINT_DEDUCTIONS_CSV)
    except FileNotFoundError:
        return pd.DataFrame(columns=["season", "div", "team_id", "points"])
    return d[d["div"] == "E0"]


def standings_states(fin: pd.DataFrame, teams_by_season: dict[int, list[str]]) -> pd.DataFrame:
    """League table after every matchday (one row per team per date)."""
    ded = load_deductions()
    rows = []
    for season, sm in fin.groupby("season"):
        teams = teams_by_season.get(season, sorted(set(sm["home_id"]) | set(sm["away_id"])))
        pts = {t: 0.0 for t in teams}
        for r in ded[ded["season"] == season].itertuples():
            if r.team_id in pts:
                pts[r.team_id] += r.points
        gd = {t: 0 for t in teams}
        gf = {t: 0 for t in teams}
        pl = {t: 0 for t in teams}
        sm = sm.sort_values("kickoff")
        for day, dm in sm.groupby(sm["kickoff"].dt.floor("D")):
            for r in dm.itertuples():
                for t, f, a in ((r.home_id, r.fthg, r.ftag), (r.away_id, r.ftag, r.fthg)):
                    pts.setdefault(t, 0.0); gd.setdefault(t, 0); gf.setdefault(t, 0); pl.setdefault(t, 0)
                    pts[t] += 3 if f > a else 1 if f == a else 0
                    gd[t] += f - a
                    gf[t] += f
                    pl[t] += 1
            order = sorted(pts, key=lambda t: (-pts[t], -gd[t], -gf[t], t))
            # Available two hours after the day's last kickoff, i.e. once those matches are over.
            stamp = dm["kickoff"].max() + pd.Timedelta(hours=2)
            for pos, t in enumerate(order, start=1):
                rows.append({"team": t, "kickoff": stamp, "season": season, "std_played": pl[t],
                             "std_ppg": pts[t] / pl[t] if pl[t] else np.nan,
                             "std_gdpg": gd[t] / pl[t] if pl[t] else np.nan, "pos": pos})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- Dixon-Coles walk-forward
def block_start(ts: pd.Series) -> pd.Series:
    """Fit dates: Monday 00:00 and Thursday 00:00 UTC of each week."""
    day = ts.dt.floor("D")
    dow = day.dt.dayofweek
    back = np.where(dow >= 3, dow - 3, dow)
    return day - pd.to_timedelta(back, unit="D")


def promoted_sets(e0: pd.DataFrame) -> dict[int, set[str]]:
    by_season = {s: set(g["home_id"]) | set(g["away_id"]) for s, g in e0.groupby("season")}
    return {s: teams - by_season.get(s - 1, set()) for s, teams in by_season.items()}


def dc_walk_forward(e0: pd.DataFrame, targets: pd.DataFrame, now: pd.Timestamp,
                    params: dc.DCParams = dc.DCParams()) -> pd.DataFrame:
    """Out-of-sample Dixon-Coles predictions for every target E0 match."""
    fin = e0[e0["status"] == "FINISHED"]
    promoted = promoted_sets(e0)
    fit_at = block_start(targets["kickoff"])
    # Upcoming matches: fit on everything finished before today (UTC). Using the day, not the
    # minute, keeps predictions stable between runs unless new data actually arrived.
    today = now.floor("D")
    fit_at = fit_at.where(targets["status"] == "FINISHED", today)
    fit_at = fit_at.where(fit_at <= today, today)
    out = []
    warm = None
    for when, grp in targets.groupby(fit_at):
        season = int(grp["season"].iloc[0])
        model = dc.fit(fin, when, params, promoted=promoted.get(season, set()), warm=warm)
        if model is None:
            continue
        warm = model
        for r in grp.itertuples():
            p = model.predict(r.home_id, r.away_id)
            out.append({"_row": r.Index, "dc_lambda": p["lambda"], "dc_mu": p["mu"],
                        "dc_ph": p["p_home"], "dc_pd": p["p_draw"], "dc_pa": p["p_away"]})
    return pd.DataFrame(out).set_index("_row")


# --------------------------------------------------------------------------- main builder
@dataclass
class FeatureSet:
    frame: pd.DataFrame            # one row per E0 match (finished + upcoming), with features
    elo_history: pd.DataFrame      # per-match ratings, E0 + E1
    elo_current: dict[str, float]  # ratings now (with off-season regression if a new season began)


def build(conn: sqlite3.Connection, now: pd.Timestamp | None = None,
          elo_params: EloParams = EloParams(), dc_params: dc.DCParams = dc.DCParams(),
          first_season: int = FIRST_TRAIN_SEASON, matches: pd.DataFrame | None = None) -> FeatureSet:
    now = now or pd.Timestamp.now(tz="UTC")
    m = load_matches(conn) if matches is None else matches
    other = load_other(conn)
    fin_all = m[(m["status"] == "FINISHED") & m["fthg"].notna() & (m["kickoff"] < now)].copy()
    e0 = m[m["div"] == "E0"].copy()
    fin = fin_all[fin_all["div"] == "E0"].copy()

    # Targets: every E0 match from first_season, finished or not yet played (not postponed / TBC).
    tgt = e0[(e0["season"] >= first_season)].copy()
    tgt = tgt[(tgt["status"] == "FINISHED") | ((tgt["status"] == "SCHEDULED") & tgt["kickoff"].notna())]
    tgt = tgt.sort_values(["kickoff", "match_id"]).reset_index(drop=True)
    tgt["_row"] = tgt.index

    # Elo: pre-match ratings for finished matches, current ratings for upcoming ones.
    hist, ratings = run_elo(fin_all, elo_params)
    last_div = fin_all.sort_values("kickoff").groupby("home_id")["div"].last().to_dict()
    last_div.update(fin_all.sort_values("kickoff").groupby("away_id")["div"].last().to_dict())
    last_season = int(fin_all["season"].max())
    cur_season = int(tgt["season"].max())
    current = season_start_ratings(ratings, last_div, elo_params) if cur_season > last_season else ratings
    pre = hist.set_index("match_id")
    tgt["elo_home"] = tgt["match_id"].map(pre["elo_home_pre"])
    tgt["elo_away"] = tgt["match_id"].map(pre["elo_away_pre"])
    upcoming = tgt["status"] != "FINISHED"
    default = elo_params.init_e1
    if upcoming.any():
        tgt.loc[upcoming, "elo_home"] = tgt.loc[upcoming, "home_id"].map(lambda t: current.get(t, default)).astype(float)
        tgt.loc[upcoming, "elo_away"] = tgt.loc[upcoming, "away_id"].map(lambda t: current.get(t, default)).astype(float)
    tgt["elo_diff"] = tgt["elo_home"] - tgt["elo_away"]

    # Rolling form (PL matches only).
    tm = team_match_table(fin)
    roll = rolling_states(tm)
    roll["last_kick"] = roll["kickoff"]
    for side, col in (("h", "home_id"), ("a", "away_id")):
        t = tgt[["_row", col, "kickoff"]].rename(columns={col: "team"})
        j = _asof(t, roll, "team", {"form5_ppg": f"form5_ppg_{side}", "gd10": f"gd10_{side}",
                                    "sd10": f"sd10_{side}", "sotd10": f"sotd10_{side}", "last_kick": "_last"})
        stale = (tgt["kickoff"] - j["_last"]).dt.days > STALE_DAYS
        for c in ("form5_ppg", "gd10", "sd10", "sotd10"):
            tgt[f"{c}_{side}"] = j[f"{c}_{side}"].where(~stale)
    # Home team's home form, away team's away form.
    for side, col, is_home in (("h", "home_id", 1), ("a", "away_id", 0)):
        vs = venue_states(tm, is_home)
        vs["last_kick"] = vs["kickoff"]
        t = tgt[["_row", col, "kickoff"]].rename(columns={col: "team"})
        j = _asof(t, vs, "team", {"venue_ppg": f"venue_ppg_{side}", "venue_gd": f"venue_gd_{side}", "last_kick": "_last"})
        stale = (tgt["kickoff"] - j["_last"]).dt.days > STALE_DAYS
        tgt[f"venue_ppg_{side}"] = j[f"venue_ppg_{side}"].where(~stale)
        tgt[f"venue_gd_{side}"] = j[f"venue_gd_{side}"].where(~stale)

    # Season-to-date table (only states from the same season count).
    teams_by_season = {s: sorted(set(g["home_id"]) | set(g["away_id"])) for s, g in e0.groupby("season")}
    st = standings_states(fin, teams_by_season)
    for side, col in (("h", "home_id"), ("a", "away_id")):
        t = tgt[["_row", col, "kickoff"]].rename(columns={col: "team"})
        j = _asof(t, st.assign(st_season=st["season"]), "team",
                  {"std_ppg": f"std_ppg_{side}", "std_gdpg": f"std_gdpg_{side}", "pos": f"pos_{side}",
                   "st_season": "_season", "std_played": f"_played_{side}"})
        same = j["_season"] == tgt["season"]
        for c in ("std_ppg", "std_gdpg", "pos"):
            tgt[f"{c}_{side}"] = j[f"{c}_{side}"].where(same)
        tgt[f"_played_{side}"] = j[f"_played_{side}"].where(same).fillna(0)
    tgt["season_round"] = tgt[["_played_h", "_played_a"]].mean(axis=1)
    tgt = tgt.drop(columns=["_played_h", "_played_a"])

    # Rest days: days since the previous competitive match in any competition.
    ev = pd.concat([
        e0.loc[e0["kickoff"].notna() & (e0["status"] != "POSTPONED"), ["home_id", "kickoff"]].rename(columns={"home_id": "team"}).assign(euro=0),
        e0.loc[e0["kickoff"].notna() & (e0["status"] != "POSTPONED"), ["away_id", "kickoff"]].rename(columns={"away_id": "team"}).assign(euro=0),
        other[["team_id", "kickoff", "competition"]].rename(columns={"team_id": "team"})
        .assign(euro=lambda d: d["competition"].str.contains("UEFA").astype(int))[["team", "kickoff", "euro"]],
    ], ignore_index=True).drop_duplicates(["team", "kickoff"])
    ev["prev_kick"] = ev["kickoff"]
    for side, col in (("h", "home_id"), ("a", "away_id")):
        t = tgt[["_row", col, "kickoff"]].rename(columns={col: "team"})
        j = _asof(t, ev, "team", {"prev_kick": "_prev", "euro": "_euro"})
        days = (tgt["kickoff"] - j["_prev"]).dt.total_seconds() / 86400
        tgt[f"rest_{side}"] = days.clip(upper=REST_CAP_DAYS).fillna(REST_CAP_DAYS)
        tgt[f"euro_{side}"] = ((j["_euro"] == 1) & (days <= 5)).astype(int)

    promoted = promoted_sets(e0)
    tgt["promoted_h"] = [int(h in promoted.get(s, set())) for h, s in zip(tgt["home_id"], tgt["season"])]
    tgt["promoted_a"] = [int(a in promoted.get(s, set())) for a, s in zip(tgt["away_id"], tgt["season"])]

    # Dixon-Coles walk-forward ratings.
    dcp = dc_walk_forward(e0, tgt.set_index("_row", drop=False), now, dc_params)
    tgt = tgt.join(dcp, on="_row")

    tgt["y"] = np.where(tgt["status"] == "FINISHED", outcome(tgt["fthg"].fillna(0), tgt["ftag"].fillna(0)), -1)
    return FeatureSet(frame=tgt.drop(columns=["_row"]), elo_history=hist, elo_current=current)
