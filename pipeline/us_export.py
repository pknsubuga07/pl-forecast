"""Dashboard JSON for NBA / NFL (web/public/data/<sport>/*.json), swapped in atomically."""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3

import numpy as np
import pandas as pd

from model import ledger
from model.us_models import binary_metrics, market_home_prob

from .config import ARTIFACTS_DIR, LEDGER_DIR, WEB_DATA_DIR
from .export import _clean

log = logging.getLogger(__name__)

LEDGER_COLUMNS = [
    "game_id", "sport", "season", "week", "kickoff_utc", "home_id", "away_id", "model_version",
    "first_predicted_at", "predicted_at", "locked", "locked_at",
    "p_home", "p_away", "pred_margin", "pred_total", "pred_home_score", "pred_away_score",
    "market_source", "market_p_home", "market_spread_home", "market_total",
]


def ledger_path(sport: str):
    return LEDGER_DIR / f"{sport}_predictions.csv"


def season_label(sport: str, s: int) -> str:
    return str(s) if sport == "nfl" else f"{s}-{str(s + 1)[-2:]}"


def teams_info(conn, sport: str) -> dict[str, dict]:
    return {r["team_id"]: {"id": r["team_id"], "name": r["name"], "short": r["short_name"], "nickname": r["nickname"],
                           "conference": r["conference"], "division": r["division"], "logo": r["logo"]}
            for r in conn.execute("SELECT * FROM us_teams WHERE sport = ?", (sport,))}


def team_games(g: pd.DataFrame, team: str) -> pd.DataFrame:
    t = g[((g["home_id"] == team) | (g["away_id"] == team)) & (g["status"] == "FINISHED")].sort_values("kickoff").copy()
    home = t["home_id"] == team
    t["is_home"] = home
    t["opp"] = np.where(home, t["away_id"], t["home_id"])
    t["pf"] = np.where(home, t["home_score"], t["away_score"])
    t["pa"] = np.where(home, t["away_score"], t["home_score"])
    t["res"] = np.where(t["pf"] > t["pa"], "W", np.where(t["pf"] < t["pa"], "L", "T"))
    return t


def record(t: pd.DataFrame) -> dict:
    w, l, tie = int((t["res"] == "W").sum()), int((t["res"] == "L").sum()), int((t["res"] == "T").sum())
    n = w + l + tie
    return {"w": w, "l": l, "t": tie, "pct": round((w + 0.5 * tie) / n, 3) if n else None,
            "pf_pg": round(float(t["pf"].mean()), 1) if n else None, "pa_pg": round(float(t["pa"].mean()), 1) if n else None}


def streak(t: pd.DataFrame) -> str | None:
    if t.empty:
        return None
    r = t["res"].tolist()
    k = 1
    while k < len(r) and r[-k - 1] == r[-1]:
        k += 1
    return f"{r[-1]}{k}"


def standings(g: pd.DataFrame, season: int, teams: dict, elo: dict) -> list[dict]:
    s = g[(g["season"] == season) & (g["season_type"] == "REG")]
    rows = []
    for tid, info in teams.items():
        t = team_games(s, tid)
        rec = record(t)
        rows.append({**info, **rec, "played": len(t), "diff": int((t["pf"] - t["pa"]).sum()) if len(t) else 0,
                     "home": record(t[t["is_home"]]), "away": record(t[~t["is_home"]]),
                     "last10": record(t.tail(10)), "streak": streak(t), "elo": round(elo.get(tid, 1500.0), 1),
                     "form": t["res"].tail(5).tolist()})
    rows.sort(key=lambda r: (-(r["pct"] or 0), -r["diff"], r["name"]))
    for conf in {r["conference"] for r in rows}:
        for i, r in enumerate([r for r in rows if r["conference"] == conf], start=1):
            r["conf_rank"] = i
    return rows


def context(g: pd.DataFrame, p: dict, teams: dict, season: int, sport: str) -> dict:
    ko = pd.Timestamp(p["kickoff_utc"])
    past = g[g["kickoff"] < ko]
    out = {}
    for side, tid in (("home", p["home_id"]), ("away", p["away_id"])):
        allg = team_games(past, tid)
        cur = allg[allg["season"] == season]
        prev = allg[allg["season"] == season - 1]
        is_home = side == "home"
        last = allg.tail(1)
        out[side] = {
            "form": [{"date": r.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "opponent": teams.get(r.opp, {}).get("short", r.opp),
                      "venue": "H" if r.is_home else "A", "pf": int(r.pf), "pa": int(r.pa), "result": r.res}
                     for r in allg.tail(5).itertuples()],
            "season": record(cur), "last10": record(cur.tail(10)), "streak": streak(cur),
            "venue_this": record(cur[cur["is_home"] == is_home]), "venue_last": record(prev[prev["is_home"] == is_home]),
            "margin_pg": round(float((cur["pf"] - cur["pa"]).mean()), 1) if len(cur) else None,
            "last_game": None if last.empty else {
                "date": last["kickoff"].iloc[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "opponent": teams.get(last["opp"].iloc[0], {}).get("name", last["opp"].iloc[0]),
                "days": round((ko - last["kickoff"].iloc[0]).total_seconds() / 86400, 1)},
        }
    h2h = past[(((past["home_id"] == p["home_id"]) & (past["away_id"] == p["away_id"])) |
                ((past["home_id"] == p["away_id"]) & (past["away_id"] == p["home_id"]))) & (past["status"] == "FINISHED")]
    h2h = h2h.sort_values("kickoff").tail(10)
    meetings, w = [], 0
    for r in h2h.itertuples():
        hs, as_ = (r.home_score, r.away_score) if r.home_id == p["home_id"] else (r.away_score, r.home_score)
        w += hs > as_
        meetings.append({"date": r.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "season": season_label(sport, r.season),
                         "home": teams[r.home_id]["short"], "away": teams[r.away_id]["short"],
                         "home_score": int(r.home_score), "away_score": int(r.away_score),
                         "result_for_home_team": "W" if hs > as_ else "L" if hs < as_ else "T",
                         "playoff": r.season_type == "POST"})
    out["h2h"] = {"meetings": meetings[::-1], "home_wins": int(w), "away_wins": len(meetings) - int(w)}
    return out


def history(conn, g: pd.DataFrame, sport: str, season: int, teams: dict) -> dict:
    live = ledger.read(ledger_path(sport), key="game_id")
    bt_path = LEDGER_DIR / f"{sport}_backtest_current_season.csv"
    bt = pd.read_csv(bt_path).set_index("game_id") if bt_path.exists() else pd.DataFrame()
    odds = pd.read_sql_query("SELECT o.* FROM us_odds o JOIN us_games g USING (game_id) WHERE g.sport=? AND g.season=?",
                             conn, params=(sport, season))
    odds["rank"] = odds["source"].map({"nflverse": 0, "draftkings": 1}).fillna(2)
    odds = odds.sort_values("rank").drop_duplicates("game_id").set_index("game_id")
    fin = g[(g["season"] == season) & (g["status"] == "FINISHED")].sort_values("kickoff")
    rows = []
    for r in fin.itertuples():
        lv = live.get(r.game_id)
        if lv and lv.get("locked") == "1":
            p, mode, margin, at = float(lv["p_home"]), "live", float(lv["pred_margin"] or 0), lv["predicted_at"]
        elif r.game_id in bt.index:
            b = bt.loc[r.game_id]
            p, mode, margin, at = float(b["p_home"]), "backtest", float(b["pred_margin"]), None
        else:
            continue
        actual = int(r.home_score - r.away_score)
        mk = None
        if r.game_id in odds.index:
            o = odds.loc[r.game_id]
            mk = round(float(market_home_prob(o["home_ml"], o["away_ml"])), 4)
        y = 1 if actual > 0 else 0 if actual < 0 else None
        rows.append({"game_id": r.game_id, "kickoff_utc": r.kickoff_utc, "week": None if pd.isna(r.week) else int(r.week),
                     "home": teams[r.home_id]["short"], "away": teams[r.away_id]["short"],
                     "home_logo": teams[r.home_id]["logo"], "away_logo": teams[r.away_id]["logo"],
                     "home_score": int(r.home_score), "away_score": int(r.away_score), "p_home": round(p, 4),
                     "pred_margin": round(margin, 1), "actual_margin": actual, "mode": mode, "predicted_at": at,
                     "correct": None if y is None else (p >= 0.5) == (y == 1), "market_p_home": mk,
                     "log_loss": None if y is None else round(float(-np.log(max(p if y else 1 - p, 1e-9))), 4)})
    summary = {}
    for label, sel in (("live", [x for x in rows if x["mode"] == "live"]), ("backtest", [x for x in rows if x["mode"] == "backtest"]), ("all", rows)):
        sel = [x for x in sel if x["correct"] is not None]
        if not sel:
            continue
        y = np.array([1 if x["actual_margin"] > 0 else 0 for x in sel])
        s = binary_metrics([x["p_home"] for x in sel], y)
        s["margin_mae"] = round(float(np.mean([abs(x["pred_margin"] - x["actual_margin"]) for x in sel])), 2)
        wm = [(x, yy) for x, yy in zip(sel, y) if x["market_p_home"] is not None]
        if wm:
            s["market"] = binary_metrics([x["market_p_home"] for x, _ in wm], [yy for _, yy in wm])
            s["model_same_games"] = binary_metrics([x["p_home"] for x, _ in wm], [yy for _, yy in wm])
        summary[label] = s
    return {"season": season_label(sport, season), "games": rows[::-1], "summary": summary}


def export_sport(conn: sqlite3.Connection, sport: str, preds: list[dict], fs, manifest: dict, run_info: dict) -> None:
    from model.us_features import load_games
    teams = teams_info(conn, sport)
    g = load_games(conn, sport)
    season = int(g.loc[g["kickoff"].notna(), "season"].max())
    table = standings(g, season, teams, fs.elo_current)
    by_team = {r["id"]: r for r in table}
    games, details = [], {}
    for p in preds:
        venue = conn.execute("SELECT venue FROM us_games WHERE game_id=?", (p["game_id"],)).fetchone()[0]
        mk = p["market"]
        summary = {
            "game_id": p["game_id"], "kickoff_utc": p["kickoff_utc"], "week": p["week"], "playoff": p["playoff"],
            "neutral": p["neutral"], "venue": venue,
            "home": {**teams[p["home_id"]], "record": by_team[p["home_id"]]}, "away": {**teams[p["away_id"]], "record": by_team[p["away_id"]]},
            "p_home": p["p_home"], "predicted": p["predicted"], "confidence": p["confidence"],
            "pred_home_score": p["pred_home_score"], "pred_away_score": p["pred_away_score"],
            "pred_margin": p["pred_margin"], "pred_total": p["pred_total"],
            "market_p_home": p["market_p_home"], "market_spread_home": p["market_spread_home"], "market_total": p["market_total"],
            "market_label": mk["label"] if mk else None, "disagreement": p["disagreement"],
        }
        for t in ("home", "away"):
            summary[t]["record"] = {k: summary[t]["record"][k] for k in ("w", "l", "t", "pct", "conf_rank", "streak")}
        games.append(summary)
        details[p["game_id"]] = {**summary, **{k: p[k] for k in ("components", "weights", "explanation", "factors",
                                                                   "market", "inputs", "model_version", "home_qb", "away_qb")},
                                 "context": context(g, p, teams, season, sport)}
    hist = fs.elo_history.merge(g[["game_id", "kickoff_utc", "home_id", "away_id", "season"]], on="game_id")
    team_pages = {}
    for tid, info in teams.items():
        h = hist[((hist["home_id"] == tid) | (hist["away_id"] == tid)) & (hist["season"] >= season - 2)].sort_values("kickoff_utc")
        elo = [{"date": r.kickoff_utc[:10], "elo": round(r.elo_home_post if r.home_id == tid else r.elo_away_post, 1)} for r in h.itertuples()]
        tg = team_games(g[g["season"] == season], tid)
        if len(tg) < 8:
            tg = team_games(g[g["season"] >= season - 1], tid).tail(30)
        roll = (tg["pf"] - tg["pa"]).rolling(5, min_periods=1).mean()
        trend = [{"date": r.kickoff.strftime("%Y-%m-%d"), "opponent": teams.get(r.opp, {}).get("short", r.opp),
                  "venue": "H" if r.is_home else "A", "pf": int(r.pf), "pa": int(r.pa), "result": r.res,
                  "margin5": round(float(m), 1)} for r, m in zip(tg.itertuples(), roll)]
        team_pages[tid] = {**info, "standing": by_team[tid], "elo_history": elo, "elo_now": round(fs.elo_current.get(tid, 1500.0), 1),
                           "trend": trend, "upcoming": [p["game_id"] for p in preds if tid in (p["home_id"], p["away_id"])]}
    evaluation_path = ARTIFACTS_DIR / sport / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.exists() else None
    hist_json = history(conn, g, sport, season, teams)
    sources = [dict(r) for r in conn.execute("SELECT * FROM source_status WHERE source LIKE ?", (f"%{'nflverse' if sport == 'nfl' else 'nba'}%",))]
    if sport == "nfl":
        sources += [dict(r) for r in conn.execute("SELECT * FROM source_status WHERE source = 'espn-nfl-scoreboard'")]
    meta = {"sport": sport, "generated_at": run_info["finished_at"], "season": season_label(sport, season),
            "model_version": manifest.get("version"), "model_trained_at": manifest.get("trained_at"),
            "n_train": manifest.get("n_train"), "sources": sources, "n_upcoming": len(games)}
    files = {"meta.json": meta, "games.json": games, "game_details.json": details, "standings.json": table,
             "teams.json": team_pages, "history.json": hist_json,
             "performance.json": {"evaluation": evaluation, "live": hist_json["summary"], "model": manifest}}
    out = WEB_DATA_DIR / sport
    tmp = WEB_DATA_DIR / f".{sport}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for name, obj in files.items():
        (tmp / name).write_text(json.dumps(_clean(obj), separators=(",", ":"), allow_nan=False))
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    log.info("Exported %d %s games", len(games), sport)
