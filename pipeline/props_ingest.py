"""Player data for props: box scores, rosters/injuries and DraftKings prop lines.

NBA box scores: ESPN game summaries (parsed on the fly, raw JSON not kept: ~0.5 MB each).
NFL player stats: nflverse weekly player stats (one CSV per season) + players.csv for ESPN ids.
Prop lines: ESPN core API `propBets` (DraftKings now, ESPN BET in older seasons), kept for past
games too, which is what makes an honest backtest possible.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3

from .config import RAW_DIR, utcnow
from .db import transaction, upsert
from .http import SourceError, fetch_cached, get

log = logging.getLogger(__name__)
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"
PATH = {"nba": "basketball/nba", "nfl": "football/nfl"}
CORE_PATH = {"nba": "basketball/leagues/nba", "nfl": "football/leagues/nfl"}
NFLVERSE_STATS = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
NFLVERSE_PLAYERS = "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"

# Prop market names (matched on the start of ESPN's type name) -> our market id.
MARKETS = {
    "nba": {"total points, rebounds, and assists": "pra", "total points": "pts", "total rebounds": "reb",
            "total assists": "ast", "total 3-point field goals": "fg3m"},
    "nfl": {"total passing yards": "pass_yds", "total rushing yards": "rush_yds", "total receiving yards": "rec_yds",
            "total receptions": "rec", "anytime touchdown scorer": "anytime_td"},
}
ONE_SIDED = {"anytime_td"}


def _now() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def market_of(sport: str, type_name: str) -> str | None:
    """Exact market names only: "Total Points and Assists" must not count as "Total Points".
    NFL names carry an "(incl. overtime)" suffix, which is ignored."""
    t = re.sub(r"\s*\(incl\. overtime\)\s*$", "", type_name.strip().lower())
    return MARKETS[sport].get(t)


# --------------------------------------------------------------------------- NBA box scores
def parse_nba_boxscore(summary: dict, game_id: str, kickoff: str, team_of: dict[str, str]) -> list[dict]:
    rows = []
    for team in (summary.get("boxscore") or {}).get("players", []):
        tid = team_of.get(str((team.get("team") or {}).get("id")))
        for block in team.get("statistics", []):
            keys = block.get("keys") or []
            for a in block.get("athletes", []):
                if a.get("didNotPlay") or not a.get("stats") or not (a.get("athlete") or {}).get("id"):
                    continue
                st = dict(zip(keys, a["stats"]))
                three = str(st.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted", "")).split("-")[0]
                rows.append({"sport": "nba", "game_id": game_id, "athlete_id": str(a["athlete"]["id"]), "team_id": tid,
                             "kickoff_utc": kickoff, "minutes": _num(st.get("minutes")), "pts": _num(st.get("points")),
                             "reb": _num(st.get("rebounds")), "ast": _num(st.get("assists")), "fg3m": _num(three)})
    return rows


def backfill_nba_boxscores(conn: sqlite3.Connection, seasons: range) -> int:
    team_of = dict(conn.execute("SELECT espn_id, team_id FROM us_teams WHERE sport='nba'").fetchall())
    done = {r[0] for r in conn.execute("SELECT DISTINCT game_id FROM us_player_games WHERE sport='nba'")}
    games = conn.execute("SELECT game_id, espn_id, kickoff_utc FROM us_games WHERE sport='nba' AND status='FINISHED' "
                         "AND season BETWEEN ? AND ? ORDER BY kickoff_utc", (seasons.start, seasons.stop - 1)).fetchall()
    todo = [g for g in games if g[0] not in done]
    n = 0
    for i, (gid, eid, ko) in enumerate(todo):
        try:
            resp = get(f"{ESPN}/basketball/nba/summary", params={"event": eid}, min_interval=0.2)
            rows = parse_nba_boxscore(resp.json(), gid, ko, team_of)
        except (SourceError, ValueError, KeyError) as exc:
            log.warning("box score %s: %s", gid, exc)
            continue
        with transaction(conn):
            upsert(conn, "us_player_games", rows, key=("game_id", "athlete_id"), keep_existing_when_null=False)
        n += len(rows)
        if i % 250 == 0:
            log.info("NBA box scores: %d / %d games", i, len(todo))
    return n


# --------------------------------------------------------------------------- NFL player stats
def nfl_espn_ids(refresh: bool) -> dict[str, str]:
    path = fetch_cached(NFLVERSE_PLAYERS, RAW_DIR / "nflverse" / "players.csv", refresh=refresh)
    if path is None:
        raise SourceError("nflverse players.csv 404")
    out = {}
    for r in csv.DictReader(io.StringIO(path.read_text())):
        if r.get("gsis_id") and r.get("espn_id") not in (None, "", "NA"):
            out[r["gsis_id"]] = str(int(float(r["espn_id"])))
    return out


def load_nfl_player_stats(conn: sqlite3.Connection, seasons: range, current: int) -> int:
    ids = nfl_espn_ids(refresh=False)
    n = 0
    for season in seasons:
        path = fetch_cached(NFLVERSE_STATS.format(season=season), RAW_DIR / "nflverse" / f"stats_player_week_{season}.csv",
                            refresh=season == current)
        if path is None:
            continue
        kick = dict(conn.execute("SELECT game_id, kickoff_utc FROM us_games WHERE sport='nfl' AND season=?", (season,)).fetchall())
        rows = []
        for r in csv.DictReader(io.StringIO(path.read_text())):
            gid = f"nfl-{r['game_id']}"
            if gid not in kick:
                continue
            f = lambda k: _num(r.get(k)) or 0.0  # noqa: E731
            rows.append({"sport": "nfl", "game_id": gid, "athlete_id": ids.get(r["player_id"], f"gsis:{r['player_id']}"),
                         "team_id": None, "kickoff_utc": kick[gid], "pass_yds": f("passing_yards"), "pass_att": f("attempts"),
                         "rush_yds": f("rushing_yards"), "carries": f("carries"), "rec": f("receptions"),
                         "targets": f("targets"), "rec_yds": f("receiving_yards"), "tds": f("rushing_tds") + f("receiving_tds")})
            rows[-1]["_name"] = r.get("player_display_name") or r.get("player_name")
            rows[-1]["_pos"] = r.get("position")
            rows[-1]["_team"] = r.get("team")
        players = {(x["athlete_id"]): x for x in rows}
        with transaction(conn):
            upsert(conn, "us_player_games", [{k: v for k, v in x.items() if not k.startswith("_")} for x in rows],
                   key=("game_id", "athlete_id"), keep_existing_when_null=False)
            upsert(conn, "us_players", [{"athlete_id": a, "sport": "nfl", "name": x["_name"], "position": x["_pos"],
                                         "updated_at": _now()} for a, x in players.items()],
                   key=("sport", "athlete_id"), keep_existing_when_null=True)
        n += len(rows)
    return n


# --------------------------------------------------------------------------- rosters & injuries
def load_rosters(conn: sqlite3.Connection, sport: str) -> int:
    teams = conn.execute("SELECT espn_id, team_id FROM us_teams WHERE sport=?", (sport,)).fetchall()
    rows = []
    for eid, tid in teams:
        data = get(f"{ESPN}/{PATH[sport]}/teams/{eid}/roster", min_interval=0.2).json()
        groups = data.get("athletes", [])
        athletes = [a for g in groups for a in g.get("items", [])] if groups and "items" in groups[0] else groups
        for a in athletes:
            inj = (a.get("injuries") or [{}])[0].get("status")
            rows.append({"athlete_id": str(a["id"]), "sport": sport, "name": a.get("displayName") or a.get("fullName"),
                         "team_id": tid, "position": (a.get("position") or {}).get("abbreviation"), "injury": inj,
                         "updated_at": _now()})
    with transaction(conn):
        # Injury must be overwritten with NULL once a player is healthy again.
        upsert(conn, "us_players", rows, key=("sport", "athlete_id"), keep_existing_when_null=False)
    return len(rows)


# --------------------------------------------------------------------------- prop lines
def parse_props(sport: str, items: list[dict], game_id: str, provider: str) -> list[dict]:
    pairs: dict[tuple, list] = {}
    for it in items:
        m = market_of(sport, (it.get("type") or {}).get("name", ""))
        ref = (it.get("athlete") or {}).get("$ref", "")
        aid = re.search(r"/athletes/(\d+)", ref)
        if not m or not aid:
            continue
        line = (it.get("current") or {}).get("target", {}).get("value")
        if m in ONE_SIDED:
            line = 0.5
        # Settled games keep the line but (for the NFL) not the prices; keep the line anyway.
        price = _num(((it.get("odds") or {}).get("american") or {}).get("value"))
        if line is None:
            continue
        pairs.setdefault((aid.group(1), m, float(line)), []).append(price)
    now = _now()
    out = {}
    for (aid, m, line), prices in pairs.items():
        row = {"game_id": game_id, "athlete_id": aid, "market": m, "line": line, "price_a": prices[0],
               "price_b": prices[1] if len(prices) > 1 and m not in ONE_SIDED else None, "provider": provider, "fetched_at": now}
        # One line per player and market: the two-sided main line closest to even money
        # (or, without prices, the line listed with both sides).
        key = (aid, m)
        closeness = abs(abs(row["price_a"]) - 110) if row["price_a"] is not None else (0 if len(prices) > 1 else 999)
        if key not in out or closeness < out[key]["_c"]:
            out[key] = {**row, "_c": closeness}
    for r in out.values():
        r.pop("_c")
    return list(out.values())


def fetch_props(conn: sqlite3.Connection, sport: str, game_id: str, espn_id: str) -> int:
    base = f"{CORE}/{CORE_PATH[sport]}/events/{espn_id}/competitions/{espn_id}/odds"
    rows = []
    for provider in ("100", "58"):  # DraftKings, ESPN BET
        resp = get(f"{base}/{provider}/propBets", params={"limit": 1000}, min_interval=0.2)
        if resp.status_code == 404:
            continue
        try:
            items = resp.json().get("items", [])
        except ValueError:
            continue
        rows = parse_props(sport, items, game_id, {"100": "draftkings", "58": "espn bet"}[provider])
        if rows:
            break
    if rows:
        with transaction(conn):
            upsert(conn, "us_props", rows, key=("game_id", "athlete_id", "market"), keep_existing_when_null=False)
    return len(rows)


def backfill_props(conn: sqlite3.Connection, sport: str, seasons: range) -> int:
    have = {r[0] for r in conn.execute("SELECT DISTINCT game_id FROM us_props p JOIN us_games g USING (game_id) WHERE g.sport=?", (sport,))}
    games = conn.execute("SELECT game_id, espn_id FROM us_games WHERE sport=? AND status='FINISHED' AND espn_id IS NOT NULL "
                         "AND season BETWEEN ? AND ? ORDER BY kickoff_utc", (sport, seasons.start, seasons.stop - 1)).fetchall()
    n = 0
    todo = [g for g in games if g[0] not in have]
    for i, (gid, eid) in enumerate(todo):
        try:
            n += fetch_props(conn, sport, gid, eid)
        except SourceError as exc:
            log.warning("props %s: %s", gid, exc)
        if i % 250 == 0:
            log.info("%s props backfill: %d / %d games", sport, i, len(todo))
    return n


def update_props(conn: sqlite3.Connection, sport: str, upcoming: list[tuple[str, str]], season: int) -> dict:
    """Daily job: rosters/injuries, new box scores / player stats, and lines for upcoming games."""
    stats = {"roster_players": load_rosters(conn, sport)}
    if sport == "nba":
        stats["box_rows"] = backfill_nba_boxscores(conn, range(season, season + 1))
    else:
        stats["stat_rows"] = load_nfl_player_stats(conn, range(season, season + 1), season)
    stats["prop_rows"] = sum(fetch_props(conn, sport, gid, eid) for gid, eid in upcoming if eid)
    return stats
