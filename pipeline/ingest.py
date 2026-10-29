"""Load every source into SQLite. Each step is idempotent (natural-key upserts)."""
from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import FIRST_SEASON, current_season, season_of, utcnow
from .db import transaction, upsert
from .http import SourceError
from .sources import espn, football_data, fpl
from .teams import TeamMapper

log = logging.getLogger(__name__)

STAT_FIELDS = ["fthg", "ftag", "hthg", "htag", "hs", "as", "hst", "ast", "hc", "ac", "hy", "ay", "hr", "ar"]


def match_id(div: str, season: int, home: str, away: str) -> str:
    return f"{div}-{season}-{home}-{away}"


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def _now() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def record_source(conn: sqlite3.Connection, source: str, error: str | None = None) -> None:
    now = _now()
    if error is None:
        upsert(conn, "source_status", [{"source": source, "last_ok_at": now}], key=("source",))
    else:
        upsert(conn, "source_status", [{"source": source, "last_error": error[:500], "last_error_at": now}], key=("source",))


# --------------------------------------------------------------------------- football-data
def football_data_rows(df: pd.DataFrame, season: int, mapper: TeamMapper, *, fixtures: bool = False):
    norm = football_data.normalise(df)
    matches, odds = [], []
    now = _now()
    for r in norm.to_dict("records"):
        div = r["div"]
        if div not in ("E0", "E1"):
            continue
        allow_new = div == "E1"
        home = mapper.resolve("football-data", r["home_alias"], allow_new=allow_new)
        away = mapper.resolve("football-data", r["away_alias"], allow_new=allow_new)
        s = season_of(datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))) if fixtures else season
        mid = match_id(div, s, home, away)
        finished = not fixtures and _clean(r["fthg"]) is not None and _clean(r["ftag"]) is not None
        row = {
            "match_id": mid, "div": div, "season": s, "home_id": home, "away_id": away,
            "kickoff_utc": r["kickoff_utc"],
            "status": "FINISHED" if finished else "SCHEDULED",
            "updated_at": now,
        }
        if finished:
            row.update({k: _clean(r[k]) for k in STAT_FIELDS})
            row.update({"hxg": _clean(r["hxg"]), "axg": _clean(r["axg"]), "result_source": "football-data"})
        matches.append(row)
        for book in football_data.ODDS_SETS:
            h, d, a = (_clean(r[f"{book}_{x}"]) for x in "hda")
            if h and d and a and h > 1 and d > 1 and a > 1:
                odds.append({"match_id": mid, "bookmaker": book, "odds_h": h, "odds_d": d, "odds_a": a,
                             "source": "football-data" + (" fixtures" if fixtures else ""), "fetched_at": now})
    return matches, odds


def load_football_data(conn: sqlite3.Connection, mapper: TeamMapper, *, refresh_all: bool = False) -> dict:
    cur = current_season()
    counts = {"matches": 0, "odds": 0}
    for season in range(FIRST_SEASON, cur + 1):
        for div in ("E0", "E1"):
            df = football_data.download_season(season, div, refresh=refresh_all or season == cur)
            if df is None:
                log.info("football-data %s %s not published yet", season, div)
                continue
            matches, odds = football_data_rows(df, season, mapper)
            with transaction(conn):
                # Scheduled fixtures from football-data must not downgrade a FINISHED row.
                fin = [m for m in matches if m["status"] == "FINISHED"]
                upsert(conn, "matches", fin, key=("match_id",))
                upsert(conn, "odds", odds, key=("match_id", "bookmaker"), keep_existing_when_null=False)
            counts["matches"] += len(fin)
            counts["odds"] += len(odds)
    # Upcoming-round odds (published by football-data a few days before each round).
    fx = football_data.download_fixtures(refresh=True)
    if fx is not None:
        fx = fx[fx["Div"].astype(str).str.strip() == "E0"]
        if len(fx):
            _, odds = football_data_rows(fx, cur, mapper, fixtures=True)
            existing = {r[0] for r in conn.execute("SELECT match_id FROM matches")}
            odds = [o for o in odds if o["match_id"] in existing]
            with transaction(conn):
                upsert(conn, "odds", odds, key=("match_id", "bookmaker"), keep_existing_when_null=False)
            counts["fixture_odds"] = len(odds)
    return counts


# --------------------------------------------------------------------------- FPL
def load_fpl(conn: sqlite3.Connection, mapper: TeamMapper) -> dict:
    teams, events, fixtures = fpl.fetch()
    by_fpl_id = {}
    team_rows = []
    for t in teams:
        tid = mapper.resolve("fpl", t["name"])
        by_fpl_id[t["id"]] = tid
        team_rows.append((t["code"], tid))
    # The FPL fixture list defines which season is "current". It switches to the new season in
    # June/July, possibly before football-data publishes the new season's CSV.
    kicks = [f["kickoff_time"] for f in fixtures if f.get("kickoff_time")]
    if not kicks:
        raise SourceError("FPL fixtures: no kickoff times at all (format change?)")
    season = season_of(datetime.fromisoformat(min(kicks).replace("Z", "+00:00")))
    if season < current_season() - 1:
        raise SourceError(f"FPL fixtures look stale (season {season})")
    now = _now()
    rows = []
    for f in fixtures:
        home, away = by_fpl_id[f["team_h"]], by_fpl_id[f["team_a"]]
        kickoff = f.get("kickoff_time")
        finished = bool(f.get("finished") or f.get("finished_provisional"))
        if finished:
            status = "FINISHED"
        elif f.get("started"):
            status = "IN_PLAY"
        elif not kickoff or f.get("event") is None:
            status = "POSTPONED"
        else:
            status = "SCHEDULED"
        rows.append({
            "match_id": match_id("E0", season, home, away), "div": "E0", "season": season,
            "home_id": home, "away_id": away, "kickoff_utc": kickoff, "status": status,
            "gameweek": f.get("event"), "fpl_id": f["id"],
            "fthg": f.get("team_h_score") if finished else None,
            "ftag": f.get("team_a_score") if finished else None,
            "updated_at": now,
        })
    with transaction(conn):
        conn.executemany("UPDATE teams SET fpl_code = ? WHERE team_id = ?", team_rows)
        for r in rows:
            conn.execute(
                """
                INSERT INTO matches (match_id, div, season, home_id, away_id, kickoff_utc, status, gameweek,
                                     fpl_id, fthg, ftag, result_source, updated_at)
                VALUES (:match_id, :div, :season, :home_id, :away_id, :kickoff_utc, :status, :gameweek,
                        :fpl_id, :fthg, :ftag, CASE WHEN :fthg IS NULL THEN NULL ELSE 'fpl' END, :updated_at)
                ON CONFLICT (match_id) DO UPDATE SET
                    -- FPL is the authority on the schedule: it may clear a kickoff (postponement).
                    kickoff_utc = excluded.kickoff_utc,
                    gameweek    = excluded.gameweek,
                    fpl_id      = excluded.fpl_id,
                    status      = CASE WHEN matches.result_source = 'football-data' THEN matches.status
                                       ELSE excluded.status END,
                    fthg = COALESCE(matches.fthg, excluded.fthg),
                    ftag = COALESCE(matches.ftag, excluded.ftag),
                    result_source = COALESCE(matches.result_source, excluded.result_source),
                    updated_at = excluded.updated_at
                """,
                r,
            )
    gw = {e["id"]: e for e in events}
    return {"fixtures": len(rows), "gameweeks": len(gw), "season": season}


# --------------------------------------------------------------------------- ESPN
def load_espn(conn: sqlite3.Connection, mapper: TeamMapper, *, days_ahead: int = 10) -> dict:
    season = conn.execute("SELECT MAX(season) FROM matches WHERE div = 'E0'").fetchone()[0] or current_season()
    teams = espn.league_teams()
    espn_ids = {}
    with transaction(conn):
        for t in teams:
            tid = mapper.resolve("espn", t["displayName"])
            espn_ids[t["id"]] = tid
            conn.execute("UPDATE teams SET espn_id = ? WHERE team_id = ?", (t["id"], tid))
    # Upcoming PL games: venue + DraftKings moneyline odds.
    events = espn.pl_scoreboard(utcnow().date() - timedelta(days=1), days_ahead)
    now = _now()
    n_venue = n_odds = 0
    with transaction(conn):
        for e in events:
            home = espn_ids.get(e["home_espn_id"]) or mapper.resolve("espn", e["home_name"])
            away = espn_ids.get(e["away_espn_id"]) or mapper.resolve("espn", e["away_name"])
            mid = match_id("E0", season, home, away)
            cur = conn.execute("UPDATE matches SET venue = COALESCE(?, venue), espn_id = ? WHERE match_id = ?",
                               (e["venue"], e["espn_id"], mid))
            if cur.rowcount == 0:
                log.warning("ESPN event %s %s v %s has no matching fixture", e["espn_id"], home, away)
                continue
            n_venue += 1
            if e["odds"]:
                upsert(conn, "odds", [{"match_id": mid, "bookmaker": e["odds"]["bookmaker"],
                                       "odds_h": e["odds"]["h"], "odds_d": e["odds"]["d"], "odds_a": e["odds"]["a"],
                                       "source": "espn", "fetched_at": now}],
                       key=("match_id", "bookmaker"), keep_existing_when_null=False)
                n_odds += 1
    # All-competition schedules for rest days (cups, Europe).
    other = []
    for espn_id, tid in espn_ids.items():
        for fixtures in (False, True):
            for ev in espn.team_schedule(espn_id, season, fixtures=fixtures):
                if not espn.is_competitive(ev["competition_slug"]):
                    continue
                other.append({"espn_event_id": ev["espn_event_id"], "team_id": tid,
                              "kickoff_utc": ev["kickoff_utc"], "competition": ev["competition"],
                              "opponent": ev["opponent"], "status": ev["status"]})
    with transaction(conn):
        upsert(conn, "other_matches", other, key=("espn_event_id", "team_id"), keep_existing_when_null=False)
    return {"venues": n_venue, "odds": n_odds, "other_matches": len(other)}


def backfill_espn_history(conn: sqlite3.Connection, mapper: TeamMapper, seasons: range,
                          seed_espn_id: str = "359") -> int:
    """One-off: past seasons' cup/European fixtures for every PL club (cached on disk).

    ESPN's team list ignores the season parameter, so for each season we read one club's
    schedule (Arsenal, ever-present since 1919) and collect its Premier League opponents' ids.
    """
    rows = []
    for season in seasons:
        try:
            seed = espn.team_schedule(seed_espn_id, season, fixtures=False)
        except SourceError as exc:
            log.warning("ESPN seed schedule %s failed: %s", season, exc)
            continue
        clubs = {seed_espn_id: "Arsenal"}
        clubs.update({e["opponent_id"]: e["opponent"] for e in seed if e["competition_slug"] == "eng.1" and e["opponent_id"]})
        for espn_id, name in clubs.items():
            try:
                tid = mapper.resolve("espn", name)
            except KeyError:
                log.warning("ESPN %s: unmapped club %s", season, name)
                continue
            try:
                evs = espn.team_schedule(espn_id, season, fixtures=False)
            except SourceError as exc:
                log.warning("ESPN schedule %s %s failed: %s", season, tid, exc)
                continue
            rows.extend({"espn_event_id": ev["espn_event_id"], "team_id": tid, "kickoff_utc": ev["kickoff_utc"],
                         "competition": ev["competition"], "opponent": ev["opponent"], "status": ev["status"]}
                        for ev in evs if espn.is_competitive(ev["competition_slug"]))
        log.info("ESPN backfill %s: %d clubs, %d rows so far", season, len(clubs), len(rows))
    with transaction(conn):
        upsert(conn, "other_matches", rows, key=("espn_event_id", "team_id"), keep_existing_when_null=False)
    return len(rows)


def run_ingest(conn: sqlite3.Connection, *, refresh_all: bool = False, skip_espn: bool = False) -> dict:
    """Run every source. football-data and FPL are required; ESPN is best-effort."""
    mapper = TeamMapper.from_csv()
    with transaction(conn):
        mapper.sync_to_db(conn)
    stats: dict = {}
    for name, fn, required in (
        ("football-data", lambda: load_football_data(conn, mapper, refresh_all=refresh_all), True),
        ("fpl", lambda: load_fpl(conn, mapper), True),
        ("espn", lambda: load_espn(conn, mapper), False),
    ):
        if name == "espn" and skip_espn:
            continue
        try:
            stats[name] = fn()
            with transaction(conn):
                record_source(conn, name)
        except Exception as exc:  # noqa: BLE001 - we want to record any failure
            log.error("Source %s failed: %s", name, exc)
            with transaction(conn):
                record_source(conn, name, error=f"{type(exc).__name__}: {exc}")
            if required:
                raise
            stats[name] = {"error": str(exc)}
    with transaction(conn):
        mapper.sync_to_db(conn)
    return stats
