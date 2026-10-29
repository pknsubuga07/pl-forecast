"""Write the JSON files the dashboard is built from (web/public/data/*.json).

Files are written to a temporary directory first and swapped in only when every file was
produced, so a failure never leaves the site with half-updated data.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from model import features as F
from model import ledger
from model.metrics import all_metrics

from .config import LEDGER_DIR, WEB_DATA_DIR, season_label

log = logging.getLogger(__name__)
CREST_URL = "https://resources.premierleague.com/premierleague25/badges/{code}.svg"


def _team_info(conn: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for r in conn.execute("SELECT team_id, name, short_name, stadium, fpl_code FROM teams"):
        out[r["team_id"]] = {"id": r["team_id"], "name": r["name"], "short": r["short_name"],
                             "stadium": r["stadium"],
                             "crest": CREST_URL.format(code=r["fpl_code"]) if r["fpl_code"] else None}
    return out


def _clean(o):
    """Make numpy / pandas values JSON-safe (NaN -> null)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%dT%H:%M:%SZ")
    return o


def _result(gf, ga) -> str:
    return "W" if gf > ga else "D" if gf == ga else "L"


def team_matches(m: pd.DataFrame, team: str, div: str | None = "E0") -> pd.DataFrame:
    sel = (m["home_id"] == team) | (m["away_id"] == team)
    if div:
        sel &= m["div"] == div
    t = m[sel & (m["status"] == "FINISHED")].sort_values("kickoff").copy()
    home = t["home_id"] == team
    t["is_home"] = home
    t["opp"] = np.where(home, t["away_id"], t["home_id"])
    t["gf"] = np.where(home, t["fthg"], t["ftag"])
    t["ga"] = np.where(home, t["ftag"], t["fthg"])
    t["sf"] = np.where(home, t["hs"], t["as"])
    t["sa"] = np.where(home, t["as"], t["hs"])
    t["stf"] = np.where(home, t["hst"], t["ast"])
    t["sta"] = np.where(home, t["ast"], t["hst"])
    t["xgf"] = np.where(home, t["hxg"], t["axg"])
    t["xga"] = np.where(home, t["axg"], t["hxg"])
    t["pts"] = np.where(t["gf"] > t["ga"], 3, np.where(t["gf"] == t["ga"], 1, 0))
    return t


def record(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "ppg": None}
    w = int((t["gf"] > t["ga"]).sum()); d = int((t["gf"] == t["ga"]).sum()); l = len(t) - w - d
    return {"p": len(t), "w": w, "d": d, "l": l, "gf": int(t["gf"].sum()), "ga": int(t["ga"].sum()),
            "ppg": round((3 * w + d) / len(t), 2)}


def standings(m: pd.DataFrame, season: int, teams: dict) -> list[dict]:
    s = m[(m["div"] == "E0") & (m["season"] == season)]
    ids = sorted(set(s["home_id"]) | set(s["away_id"]))
    ded = F.load_deductions()
    ded = ded[ded["season"] == season].groupby("team_id")["points"].sum().to_dict()
    rows = []
    for t in ids:
        tm = team_matches(s, t)
        r = record(tm)
        pts = 3 * r["w"] + r["d"] + ded.get(t, 0)
        xg_ok = tm["xgf"].notna()
        rows.append({
            "team_id": t, "name": teams[t]["name"], "short": teams[t]["short"], "crest": teams[t]["crest"],
            "played": r["p"], "won": r["w"], "drawn": r["d"], "lost": r["l"], "gf": r["gf"], "ga": r["ga"],
            "gd": r["gf"] - r["ga"], "points": pts, "deduction": ded.get(t, 0),
            "ppg": round(pts / r["p"], 2) if r["p"] else None,
            "form": [_result(a, b) for a, b in zip(tm["gf"].tail(5), tm["ga"].tail(5))],
            "xg_for": round(float(tm.loc[xg_ok, "xgf"].sum()), 1) if xg_ok.any() else None,
            "xg_against": round(float(tm.loc[xg_ok, "xga"].sum()), 1) if xg_ok.any() else None,
        })
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))
    for i, r in enumerate(rows, start=1):
        r["position"] = i
    return rows


def underlying(t: pd.DataFrame) -> dict:
    if t.empty:
        return {}
    n = len(t)
    xg = t["xgf"].notna()
    return {
        "matches": n,
        "xg_for_pg": round(float(t.loc[xg, "xgf"].mean()), 2) if xg.any() else None,
        "xg_against_pg": round(float(t.loc[xg, "xga"].mean()), 2) if xg.any() else None,
        "xg_matches": int(xg.sum()),
        "shots_for_pg": round(float(t["sf"].mean()), 1) if t["sf"].notna().any() else None,
        "shots_against_pg": round(float(t["sa"].mean()), 1) if t["sa"].notna().any() else None,
        "sot_for_pg": round(float(t["stf"].mean()), 1) if t["stf"].notna().any() else None,
        "sot_against_pg": round(float(t["sta"].mean()), 1) if t["sta"].notna().any() else None,
        "clean_sheets": int((t["ga"] == 0).sum()),
        "goals_for_pg": round(float(t["gf"].mean()), 2),
        "goals_against_pg": round(float(t["ga"].mean()), 2),
    }


def last_match_any(conn, m: pd.DataFrame, team: str, before: pd.Timestamp, teams: dict) -> dict | None:
    pl = m[((m["home_id"] == team) | (m["away_id"] == team)) & m["kickoff"].notna() & (m["kickoff"] < before)
           & (m["status"] != "POSTPONED") & (m["div"] == "E0")].sort_values("kickoff").tail(1)
    cands = []
    if len(pl):
        r = pl.iloc[0]
        opp = r["away_id"] if r["home_id"] == team else r["home_id"]
        cands.append((r["kickoff"], "Premier League", teams.get(opp, {}).get("name", opp)))
    row = conn.execute(
        "SELECT kickoff_utc, competition, opponent FROM other_matches WHERE team_id = ? AND kickoff_utc < ? "
        "AND (status IS NULL OR status NOT LIKE '%POSTPONED%') ORDER BY kickoff_utc DESC LIMIT 1",
        (team, before.strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone()
    if row:
        cands.append((pd.Timestamp(row["kickoff_utc"]), row["competition"], row["opponent"]))
    if not cands:
        return None
    ko, comp, opp = max(cands, key=lambda c: c[0])
    return {"kickoff_utc": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "competition": comp, "opponent": opp,
            "days": round((before - ko).total_seconds() / 86400, 1)}


def fixture_context(conn, m: pd.DataFrame, p: dict, teams: dict, season: int) -> dict:
    home, away = p["home_id"], p["away_id"]
    ko = pd.Timestamp(p["kickoff_utc"])
    past = m[m["kickoff"] < ko]
    ctx = {}
    for side, team in (("home", home), ("away", away)):
        cur = team_matches(past[past["season"] == season], team)
        last5 = cur.tail(5) if len(cur) >= 5 else team_matches(past, team).tail(5)
        form = [{"date": r.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "opponent": teams.get(r.opp, {}).get("name", r.opp),
                 "opponent_short": teams.get(r.opp, {}).get("short", ""), "venue": "H" if r.is_home else "A",
                 "gf": int(r.gf), "ga": int(r.ga), "result": _result(r.gf, r.ga)} for r in last5.itertuples()]
        prev = past[past["season"] == season - 1]
        prev_div = "E0" if ((prev["div"] == "E0") & ((prev["home_id"] == team) | (prev["away_id"] == team))).any() else "E1"
        prev_t = team_matches(prev, team, div=prev_div)
        is_home = side == "home"
        ctx[side] = {
            "form": form,
            "form_goals_for": int(sum(f["gf"] for f in form)), "form_goals_against": int(sum(f["ga"] for f in form)),
            "venue_record": {
                "this_season": record(cur[cur["is_home"] == is_home]),
                "last_season": {**record(prev_t[prev_t["is_home"] == is_home]),
                                "division": "Premier League" if prev_div == "E0" else "Championship"},
            },
            "underlying": underlying(cur),
            "underlying_last5": underlying(cur.tail(5)),
            "last_match": last_match_any(conn, m, team, ko, teams),
        }
    h2h = past[(((past["home_id"] == home) & (past["away_id"] == away)) | ((past["home_id"] == away) & (past["away_id"] == home)))
               & (past["status"] == "FINISHED")].sort_values("kickoff").tail(10)
    meetings = []
    w = d = l = 0
    for r in h2h.itertuples():
        gf, ga = (r.fthg, r.ftag) if r.home_id == home else (r.ftag, r.fthg)
        res = _result(gf, ga)
        w += res == "W"; d += res == "D"; l += res == "L"
        meetings.append({"date": r.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "season": season_label(r.season),
                         "division": "Premier League" if r.div == "E0" else "Championship",
                         "home": teams[r.home_id]["name"], "away": teams[r.away_id]["name"],
                         "home_goals": int(r.fthg), "away_goals": int(r.ftag), "result_for_home_team": res})
    ctx["h2h"] = {"meetings": meetings[::-1], "home_wins": w, "draws": d, "away_wins": l}
    return ctx


def history(conn, m: pd.DataFrame, season: int, teams: dict) -> dict:
    """Finished current-season matches with the prediction that was on record before kickoff."""
    live = ledger.read()
    bt_path = LEDGER_DIR / "backtest_current_season.csv"
    bt = pd.read_csv(bt_path).set_index("match_id") if bt_path.exists() else pd.DataFrame()
    mk = pd.read_sql_query("SELECT match_id, odds_h, odds_d, odds_a, bookmaker FROM odds WHERE bookmaker IN ('avg','draftkings')", conn)
    mk = mk.sort_values("bookmaker").drop_duplicates("match_id").set_index("match_id")
    fin = m[(m["div"] == "E0") & (m["season"] == season) & (m["status"] == "FINISHED")].sort_values("kickoff")
    rows = []
    for r in fin.itertuples():
        lv = live.get(r.match_id)
        if lv and lv.get("locked") == "1":
            p = [float(lv["p_home"]), float(lv["p_draw"]), float(lv["p_away"])]
            mode, version, at = "live", lv["model_version"], lv["predicted_at"]
        elif r.match_id in bt.index:
            b = bt.loc[r.match_id]
            p = [float(b["p_home"]), float(b["p_draw"]), float(b["p_away"])]
            mode, version, at = "backtest", "walk-forward", None
        else:
            continue
        y = int(F.outcome([r.fthg], [r.ftag])[0])
        mkp = None
        if r.match_id in mk.index:
            o = mk.loc[r.match_id]
            inv = np.array([1 / o["odds_h"], 1 / o["odds_d"], 1 / o["odds_a"]])
            mkp = [round(float(x), 4) for x in inv / inv.sum()]
        rows.append({
            "match_id": r.match_id, "gameweek": None if pd.isna(r.gameweek) else int(r.gameweek),
            "kickoff_utc": r.kickoff_utc, "home": teams[r.home_id]["name"], "away": teams[r.away_id]["name"],
            "home_short": teams[r.home_id]["short"], "away_short": teams[r.away_id]["short"],
            "home_crest": teams[r.home_id]["crest"], "away_crest": teams[r.away_id]["crest"],
            "home_goals": int(r.fthg), "away_goals": int(r.ftag), "result": "HDA"[y],
            "p": [round(x, 4) for x in p], "predicted": "HDA"[int(np.argmax(p))], "correct": int(np.argmax(p)) == y,
            "log_loss": round(float(-np.log(max(p[y], 1e-12))), 4), "mode": mode, "model_version": version,
            "predicted_at": at, "market_p": mkp,
        })
    summary = {}
    for label, sel in (("live", [x for x in rows if x["mode"] == "live"]),
                       ("backtest", [x for x in rows if x["mode"] == "backtest"]), ("all", rows)):
        if sel:
            P = np.array([x["p"] for x in sel]); P = P / P.sum(axis=1, keepdims=True)
            Y = np.array(["HDA".index(x["result"]) for x in sel])
            s = all_metrics(P, Y)
            withm = [x for x in sel if x["market_p"]]
            if withm:
                PM = np.array([x["market_p"] for x in withm]); PM = PM / PM.sum(axis=1, keepdims=True); YM = np.array(["HDA".index(x["result"]) for x in withm])
                PP = np.array([x["p"] for x in withm]); PP = PP / PP.sum(axis=1, keepdims=True)
                s["market"] = all_metrics(PM, YM)
                s["model_same_matches"] = all_metrics(PP, YM)
            summary[label] = s
    return {"season": season_label(season), "matches": rows[::-1], "summary": summary}


def team_pages(m: pd.DataFrame, fs: F.FeatureSet, preds: list[dict], teams: dict, season: int, table: list[dict]) -> dict:
    hist = fs.elo_history.merge(m[["match_id", "kickoff_utc", "home_id", "away_id", "div"]], on="match_id")
    current = {r["team_id"] for r in table}
    out = {}
    by_pos = {r["team_id"]: r for r in table}
    for t in current:
        h = hist[((hist["home_id"] == t) | (hist["away_id"] == t)) & (hist["kickoff_utc"] >= f"{season - 3}-07-01")]
        elo = [{"date": r.kickoff_utc[:10], "elo": round(r.elo_home_post if r.home_id == t else r.elo_away_post, 1),
                "div": r.div} for r in h.sort_values("kickoff_utc").itertuples()]
        tm = team_matches(m[m["season"] >= season - 1], t, div=None)
        tm = tm[tm["div"] == "E0"] if (tm["div"] == "E0").sum() >= 10 else tm
        tm = tm.tail(38)
        roll = tm["pts"].rolling(5, min_periods=1).mean()
        form = [{"date": r.kickoff.strftime("%Y-%m-%d"), "opponent": teams.get(r.opp, {}).get("short", r.opp),
                 "venue": "H" if r.is_home else "A", "gf": int(r.gf), "ga": int(r.ga), "result": _result(r.gf, r.ga),
                 "ppg5": round(float(pp), 2), "xgf": None if pd.isna(r.xgf) else float(r.xgf),
                 "xga": None if pd.isna(r.xga) else float(r.xga), "div": r.div}
                for r, pp in zip(tm.itertuples(), roll)]
        up = [p["match_id"] for p in preds if t in (p["home_id"], p["away_id"])]
        cur = team_matches(m[(m["season"] == season)], t)
        out[t] = {**teams[t], "table": by_pos.get(t), "elo_history": elo,
                  "elo_now": round(float(fs.elo_current.get(t, np.nan)), 1), "form_trend": form,
                  "upcoming": up, "home_record": record(cur[cur["is_home"]]), "away_record": record(cur[~cur["is_home"]]),
                  "underlying": underlying(cur)}
    return out


def export_all(conn: sqlite3.Connection, preds: list[dict], fs: F.FeatureSet, manifest: dict,
               evaluation: dict | None, run_info: dict, out_dir: Path = WEB_DATA_DIR) -> None:
    teams = _team_info(conn)
    m = F.load_matches(conn)
    season = int(m.loc[m["div"] == "E0", "season"].max())
    table = standings(m, season, teams)
    fixtures, details = [], {}
    for p in preds:
        venue = conn.execute("SELECT venue FROM matches WHERE match_id = ?", (p["match_id"],)).fetchone()[0]
        venue = venue or teams[p["home_id"]]["stadium"]
        summary = {
            "match_id": p["match_id"], "gameweek": p["gameweek"], "kickoff_utc": p["kickoff_utc"], "venue": venue,
            "home": teams[p["home_id"]], "away": teams[p["away_id"]],
            "p": [p["p_home"], p["p_draw"], p["p_away"]], "predicted": p["predicted"], "confidence": p["confidence"],
            "xg": [p["xg_home"], p["xg_away"]], "top_score": p["top_scores"][0],
            "market_p": p["market"]["p"] if p["market"] else None,
            "market_source": p["market"]["label"] if p["market"] else None,
            "disagreement": p["disagreement"], "market_diff": p["market_diff"],
        }
        fixtures.append(summary)
        details[p["match_id"]] = {**summary, **{k: p[k] for k in ("top_scores", "score_grid", "components", "weights",
                                                                   "explanation", "factors", "market", "inputs", "model_version")},
                                  "home_table": next((r for r in table if r["team_id"] == p["home_id"]), None),
                                  "away_table": next((r for r in table if r["team_id"] == p["away_id"]), None),
                                  "context": fixture_context(conn, m, p, teams, season)}
    sources = [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY source")]
    meta = {
        "generated_at": run_info["finished_at"], "season": season_label(season),
        "next_gameweek": min((f["gameweek"] for f in fixtures), default=None),
        "model_version": manifest.get("version"), "model_trained_at": manifest.get("trained_at"),
        "n_train": manifest.get("n_train"), "sources": sources, "timezone": "America/New_York",
        "last_result_utc": m.loc[(m["div"] == "E0") & (m["status"] == "FINISHED"), "kickoff_utc"].max(),
    }
    hist = history(conn, m, season, teams)
    files = {
        "meta.json": meta,
        "fixtures.json": fixtures,
        "fixture_details.json": details,
        "table.json": table,
        "teams.json": team_pages(m, fs, preds, teams, season, table),
        "history.json": hist,
        "performance.json": {"evaluation": evaluation, "live": hist["summary"], "model": manifest},
    }
    tmp = out_dir.parent / (out_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for name, obj in files.items():
        (tmp / name).write_text(json.dumps(_clean(obj), separators=(",", ":"), allow_nan=False))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp.rename(out_dir)
    log.info("Exported %d fixtures to %s", len(fixtures), out_dir)
