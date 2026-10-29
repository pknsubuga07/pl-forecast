"""NBA and NFL ingest.

NFL: nflverse `games.csv` (every game since 1999: kickoff, scores, rest, stadium, starting QBs,
     closing moneyline / spread / total). One ~1.5 MB request per run.
NBA: ESPN team schedules (one request per team per season type returns the whole season with
     scores); historical odds from ESPN's core API (one request per game, backfilled once for the
     evaluation seasons).
Both: ESPN daily scoreboards for the next few days give live status, venues and DraftKings odds.

All writes are upserts keyed on game_id, so re-running never duplicates anything.
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import DATA_DIR, RAW_DIR, utcnow
from .db import transaction, upsert
from .http import SourceError, fetch_cached, get
from .sources.espn import american_to_decimal  # noqa: F401  (re-exported for callers)
from .teams import TeamMapper

log = logging.getLogger(__name__)
NFLVERSE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports"
PATHS = {"nba": "basketball/nba", "nfl": "football/nfl"}
EASTERN = ZoneInfo("America/New_York")
FIRST_NBA_SEASON = 2012   # 2012-13
STATUS = {"STATUS_FINAL": "FINISHED", "STATUS_FULL_TIME": "FINISHED", "STATUS_SCHEDULED": "SCHEDULED",
          "STATUS_POSTPONED": "POSTPONED", "STATUS_CANCELED": "POSTPONED", "STATUS_SUSPENDED": "POSTPONED"}


def _now() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def nba_season_of(d: datetime) -> int:
    """NBA seasons start in October; 2026-27 is season 2026."""
    return d.year if d.month >= 8 else d.year - 1


def nfl_season_of(d: datetime) -> int:
    """NFL seasons run September-February; the 2026 season includes February 2027."""
    return d.year if d.month >= 4 else d.year - 1


def load_teams(conn: sqlite3.Connection) -> None:
    with open(DATA_DIR / "us_teams.csv", newline="") as f:
        rows = [dict(r) for r in csv.DictReader(f)]
    with transaction(conn):
        upsert(conn, "us_teams", rows, key=("team_id",), keep_existing_when_null=False)


def _f(v: str) -> float | None:
    try:
        return float(v) if v not in ("", "NA", None) else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- NFL
def parse_nflverse(text: str, mapper: TeamMapper) -> tuple[list[dict], list[dict]]:
    if text.lstrip().startswith("<"):
        raise SourceError("nflverse games.csv: got HTML instead of CSV")
    reader = csv.DictReader(io.StringIO(text))
    need = {"game_id", "season", "game_type", "week", "gameday", "gametime", "home_team", "away_team",
            "home_score", "away_score", "location", "spread_line", "total_line", "home_moneyline", "away_moneyline"}
    missing = need - set(reader.fieldnames or [])
    if missing:
        raise SourceError(f"nflverse games.csv: missing columns {sorted(missing)}")
    now = _now()
    games, odds = [], []
    for r in reader:
        gid = f"nfl-{r['game_id']}"
        time = r["gametime"] if r["gametime"] not in ("", "NA") else "13:00"
        local = datetime.strptime(f"{r['gameday']} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=EASTERN)
        hs, as_ = _f(r["home_score"]), _f(r["away_score"])
        games.append({
            "game_id": gid, "sport": "nfl", "season": int(r["season"]),
            "season_type": "REG" if r["game_type"] == "REG" else "POST",
            "week": int(r["week"]), "kickoff_utc": local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_id": mapper.resolve("nflverse", r["home_team"]), "away_id": mapper.resolve("nflverse", r["away_team"]),
            "neutral": int(r["location"] == "Neutral"),
            "status": "FINISHED" if hs is not None and as_ is not None else "SCHEDULED",
            "home_score": None if hs is None else int(hs), "away_score": None if as_ is None else int(as_),
            "overtime": int(_f(r.get("overtime", "")) or 0) if hs is not None else None,
            "venue": r.get("stadium") or None,
            "home_qb": r.get("home_qb_name") or None, "away_qb": r.get("away_qb_name") or None,
            "espn_id": r.get("espn") or None, "updated_at": now,
        })
        hml, aml, spread, total = _f(r["home_moneyline"]), _f(r["away_moneyline"]), _f(r["spread_line"]), _f(r["total_line"])
        if hml is not None and aml is not None:
            # nflverse spread_line is positive when the home team is favoured; we store the home line.
            odds.append({"game_id": gid, "source": "nflverse", "home_ml": hml, "away_ml": aml,
                         "home_spread": None if spread is None else -spread, "total": total, "fetched_at": now})
    return games, odds


def load_nfl(conn: sqlite3.Connection, mapper: TeamMapper) -> dict:
    path = fetch_cached(NFLVERSE_URL, RAW_DIR / "nflverse" / "games.csv", refresh=True)
    if path is None:
        raise SourceError("nflverse games.csv returned 404")
    games, odds = parse_nflverse(path.read_text(), mapper)
    with transaction(conn):
        upsert(conn, "us_games", games, key=("game_id",), keep_existing_when_null=False)
        upsert(conn, "us_odds", odds, key=("game_id", "source"), keep_existing_when_null=False)
    return {"games": len(games), "odds": len(odds)}


# --------------------------------------------------------------------------- NBA
def _espn_event(e: dict, sport: str, mapper: TeamMapper) -> dict | None:
    c = e["competitions"][0]
    teams = {x["homeAway"]: x for x in c["competitors"]}
    try:
        home = mapper.resolve(f"espn-{sport}", str(teams["home"]["team"]["id"]))
        away = mapper.resolve(f"espn-{sport}", str(teams["away"]["team"]["id"]))
    except KeyError:
        return None  # e.g. an exhibition opponent
    st = (c.get("status") or e.get("status") or {}).get("type", {})
    status = STATUS.get(st.get("name"), "IN_PLAY" if st.get("state") == "in" else "SCHEDULED")
    if st.get("completed"):
        status = "FINISHED"

    def score(x):
        s = x.get("score")
        if isinstance(s, dict):
            s = s.get("value")
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return None
    ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
    stype = (e.get("seasonType") or {}).get("type") or (e.get("season") or {}).get("type")
    return {
        "game_id": f"{sport}-{e['id']}", "sport": sport,
        "season": nba_season_of(ko) if sport == "nba" else nfl_season_of(ko),
        "season_type": "POST" if stype == 3 else "REG", "week": (e.get("week") or {}).get("number"),
        "kickoff_utc": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_id": home, "away_id": away,
        "neutral": int(bool(c.get("neutralSite"))), "status": status,
        "home_score": score(teams["home"]) if status == "FINISHED" else None,
        "away_score": score(teams["away"]) if status == "FINISHED" else None,
        "venue": (c.get("venue") or {}).get("fullName"), "espn_id": e["id"], "updated_at": _now(),
    }


def nba_team_schedule(espn_team_id: str, end_year: int, season_type: int, *, refresh: bool) -> list[dict]:
    url = f"{ESPN}/basketball/nba/teams/{espn_team_id}/schedule"
    dest = RAW_DIR / "espn-nba" / f"sched_{espn_team_id}_{end_year}_{season_type}.json"
    path = fetch_cached(url, dest, refresh=refresh, params={"season": end_year, "seasontype": season_type}, min_interval=0.3)
    if path is None:
        return []
    import json
    try:
        return json.loads(path.read_text()).get("events", [])
    except json.JSONDecodeError as exc:
        raise SourceError(f"ESPN NBA schedule {espn_team_id} {end_year}: invalid JSON") from exc


def load_nba(conn: sqlite3.Connection, mapper: TeamMapper, *, refresh_all: bool = False) -> dict:
    cur = nba_season_of(utcnow())
    team_ids = [r[0] for r in conn.execute("SELECT espn_id FROM us_teams WHERE sport='nba'")]
    if len(team_ids) != 30:
        raise SourceError(f"expected 30 NBA teams in us_teams, found {len(team_ids)}")
    games: dict[str, dict] = {}
    for season in range(FIRST_NBA_SEASON, cur + 1):
        refresh = refresh_all or season == cur
        for tid in team_ids:
            for stype in (2, 3):
                if season == cur and stype == 3 and utcnow().month in (10, 11, 12, 1, 2, 3):
                    continue  # no playoffs yet
                for e in nba_team_schedule(tid, season + 1, stype, refresh=refresh):
                    g = _espn_event(e, "nba", mapper)
                    if g:
                        # The request says which season this is (dates alone misfile e.g. the 2020 bubble).
                        g["season"] = season
                        g["season_type"] = "POST" if stype == 3 else "REG"
                        games[g["game_id"]] = g
    if not any(g["season"] == cur for g in games.values()):
        raise SourceError("ESPN NBA schedules returned no games for the current season")
    with transaction(conn):
        upsert(conn, "us_games", list(games.values()), key=("game_id",), keep_existing_when_null=False)
    return {"games": len(games)}


def backfill_nba_odds(conn: sqlite3.Connection, seasons: range) -> int:
    """Historical NBA moneylines/spreads from ESPN's core API, for evaluating against the market."""
    import json
    rows = []
    q = "SELECT game_id, espn_id FROM us_games WHERE sport='nba' AND status='FINISHED' AND season BETWEEN ? AND ?"
    todo = conn.execute(q, (seasons.start, seasons.stop - 1)).fetchall()
    have = {r[0] for r in conn.execute("SELECT game_id FROM us_odds WHERE source='espn-core'")}
    for i, (gid, eid) in enumerate(todo):
        if gid in have:
            continue
        url = f"{ESPN_CORE}/basketball/leagues/nba/events/{eid}/competitions/{eid}/odds"
        try:
            path = fetch_cached(url, RAW_DIR / "espn-nba-odds" / f"{eid}.json", refresh=False, min_interval=0.25)
        except SourceError as exc:
            log.warning("odds %s: %s", eid, exc)
            continue
        if path is None:
            continue
        try:
            items = json.loads(path.read_text()).get("items", [])
        except json.JSONDecodeError:
            continue
        for it in items:
            h, a = (it.get("homeTeamOdds") or {}).get("moneyLine"), (it.get("awayTeamOdds") or {}).get("moneyLine")
            if h is None or a is None:
                continue
            rows.append({"game_id": gid, "source": "espn-core", "home_ml": float(h), "away_ml": float(a),
                         "home_spread": it.get("spread"), "total": it.get("overUnder"), "fetched_at": _now()})
            break
        if i % 500 == 0:
            log.info("NBA odds backfill: %d / %d", i, len(todo))
    with transaction(conn):
        upsert(conn, "us_odds", rows, key=("game_id", "source"), keep_existing_when_null=False)
    return len(rows)


# --------------------------------------------------------------------------- ESPN scoreboards (both)
def scoreboard_odds(c: dict) -> dict | None:
    for o in c.get("odds") or []:
        ml = o.get("moneyline") or {}

        def pick(side):
            s = ml.get(side) or {}
            return (s.get("close") or {}).get("odds") or (s.get("open") or {}).get("odds")
        h, a = pick("home"), pick("away")
        if h is None or a is None:
            h, a = (o.get("homeTeamOdds") or {}).get("moneyLine"), (o.get("awayTeamOdds") or {}).get("moneyLine")
        try:
            h, a = float(str(h).replace("+", "")), float(str(a).replace("+", ""))
        except (TypeError, ValueError):
            continue
        return {"source": (o.get("provider") or {}).get("name", "espn").lower(), "home_ml": h, "away_ml": a,
                "home_spread": o.get("spread"), "total": o.get("overUnder")}
    return None


def load_scoreboards(conn: sqlite3.Connection, sport: str, mapper: TeamMapper, days: int = 8) -> dict:
    """Next few days of ESPN scoreboards: live status, venue and DraftKings odds."""
    import json
    start = utcnow().date() - timedelta(days=1)
    n_games = n_odds = 0
    now = _now()
    for i in range(days):
        day = (start + timedelta(days=i)).strftime("%Y%m%d")
        path = fetch_cached(f"{ESPN}/{PATHS[sport]}/scoreboard", RAW_DIR / f"espn-{sport}" / f"scoreboard_{day}.json",
                            refresh=True, params={"dates": day}, min_interval=0.3)
        if path is None:
            continue
        for e in json.loads(path.read_text()).get("events", []):
            g = _espn_event(e, sport, mapper)
            if not g:
                continue
            if sport == "nfl":
                # nflverse is the source of truth for NFL ids; match on teams + kickoff day.
                row = conn.execute(
                    "SELECT game_id FROM us_games WHERE sport='nfl' AND home_id=? AND away_id=? "
                    "AND ABS(julianday(kickoff_utc) - julianday(?)) < 2", (g["home_id"], g["away_id"], g["kickoff_utc"])).fetchone()
                if not row:
                    continue
                gid = row[0]
                with transaction(conn):
                    # ESPN can report a final score before nflverse catches up.
                    conn.execute("UPDATE us_games SET venue=COALESCE(?, venue), espn_id=?, "
                                 "status=CASE WHEN status='FINISHED' THEN status ELSE ? END, "
                                 "home_score=COALESCE(home_score, ?), away_score=COALESCE(away_score, ?) WHERE game_id=?",
                                 (g["venue"], g["espn_id"], g["status"], g["home_score"], g["away_score"], gid))
            else:
                gid = g["game_id"]
                with transaction(conn):
                    upsert(conn, "us_games", [g], key=("game_id",), keep_existing_when_null=True)
            n_games += 1
            o = scoreboard_odds(e["competitions"][0])
            if o and g["status"] == "SCHEDULED":
                with transaction(conn):
                    upsert(conn, "us_odds", [{"game_id": gid, **o, "fetched_at": now}],
                           key=("game_id", "source"), keep_existing_when_null=False)
                n_odds += 1
    return {"games": n_games, "odds": n_odds}


def run_us_ingest(conn: sqlite3.Connection, sport: str, *, refresh_all: bool = False) -> dict:
    from .ingest import record_source
    mapper = TeamMapper.from_csv()
    load_teams(conn)
    stats = {}
    main = (lambda: load_nfl(conn, mapper)) if sport == "nfl" else (lambda: load_nba(conn, mapper, refresh_all=refresh_all))
    main_name = "nflverse" if sport == "nfl" else "espn-nba"
    try:
        stats[main_name] = main()
        with transaction(conn):
            record_source(conn, main_name)
    except Exception as exc:  # noqa: BLE001
        with transaction(conn):
            record_source(conn, main_name, error=f"{type(exc).__name__}: {exc}")
        raise
    name = f"espn-{sport}-scoreboard"
    try:
        stats[name] = load_scoreboards(conn, sport, mapper)
        with transaction(conn):
            record_source(conn, name)
    except Exception as exc:  # noqa: BLE001 - best effort
        log.error("%s failed: %s", name, exc)
        with transaction(conn):
            record_source(conn, name, error=f"{type(exc).__name__}: {exc}")
        stats[name] = {"error": str(exc)}
    return stats
