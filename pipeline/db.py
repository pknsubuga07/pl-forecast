"""SQLite schema and upsert helpers. Every write is an upsert keyed on a natural key,
so re-running the pipeline never creates duplicate rows."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,          -- canonical slug, e.g. 'man-united'
    name        TEXT NOT NULL,             -- display name
    short_name  TEXT NOT NULL,             -- 3-letter code
    stadium     TEXT,
    fpl_code    INTEGER,                   -- used for crest URLs
    espn_id     TEXT
);

-- The single place where source-specific spellings map to a canonical team.
CREATE TABLE IF NOT EXISTS team_aliases (
    source   TEXT NOT NULL,                -- 'football-data' | 'fpl' | 'espn'
    alias    TEXT NOT NULL,
    team_id  TEXT NOT NULL REFERENCES teams(team_id),
    PRIMARY KEY (source, alias)
);

CREATE TABLE IF NOT EXISTS matches (
    match_id     TEXT PRIMARY KEY,         -- '{div}-{season}-{home}-{away}'
    div          TEXT NOT NULL,            -- 'E0' Premier League, 'E1' Championship
    season       INTEGER NOT NULL,         -- start year, 2026 = 2026-27
    kickoff_utc  TEXT,                     -- ISO-8601 UTC; NULL when postponed / TBC
    home_id      TEXT NOT NULL REFERENCES teams(team_id),
    away_id      TEXT NOT NULL REFERENCES teams(team_id),
    status       TEXT NOT NULL,            -- SCHEDULED | IN_PLAY | FINISHED | POSTPONED
    gameweek     INTEGER,
    venue        TEXT,
    fthg INTEGER, ftag INTEGER, hthg INTEGER, htag INTEGER,
    hs INTEGER, "as" INTEGER, hst INTEGER, ast INTEGER,
    hc INTEGER, ac INTEGER, hy INTEGER, ay INTEGER, hr INTEGER, ar INTEGER,
    hxg REAL, axg REAL,
    fpl_id       INTEGER,
    espn_id      TEXT,
    result_source TEXT,                    -- which source supplied the score
    updated_at   TEXT NOT NULL,
    UNIQUE (div, season, home_id, away_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_kickoff ON matches(kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(div, season);

CREATE TABLE IF NOT EXISTS odds (
    match_id   TEXT NOT NULL REFERENCES matches(match_id),
    bookmaker  TEXT NOT NULL,              -- avg | max | b365 | pinnacle | *_close | draftkings
    odds_h REAL, odds_d REAL, odds_a REAL, -- decimal odds
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (match_id, bookmaker)
);

-- Non-league fixtures (cups, Europe) used only for rest-day calculations.
CREATE TABLE IF NOT EXISTS other_matches (
    espn_event_id TEXT NOT NULL,
    team_id       TEXT NOT NULL REFERENCES teams(team_id),
    kickoff_utc   TEXT NOT NULL,
    competition   TEXT NOT NULL,
    opponent      TEXT,
    status        TEXT,
    PRIMARY KEY (espn_event_id, team_id)
);

CREATE TABLE IF NOT EXISTS elo_history (
    match_id     TEXT NOT NULL REFERENCES matches(match_id),
    team_id      TEXT NOT NULL REFERENCES teams(team_id),
    kickoff_utc  TEXT NOT NULL,
    rating_before REAL NOT NULL,
    rating_after  REAL NOT NULL,
    PRIMARY KEY (match_id, team_id)
);

-- Live predictions are mirrored from data/ledger/predictions.csv (the durable copy).
CREATE TABLE IF NOT EXISTS predictions (
    match_id      TEXT NOT NULL REFERENCES matches(match_id),
    mode          TEXT NOT NULL,           -- 'live' (made before kickoff) | 'backtest'
    model_version TEXT NOT NULL,
    predicted_at  TEXT NOT NULL,
    locked        INTEGER NOT NULL DEFAULT 0,
    p_home REAL NOT NULL, p_draw REAL NOT NULL, p_away REAL NOT NULL,
    xg_home REAL, xg_away REAL,
    market_p_home REAL, market_p_draw REAL, market_p_away REAL,
    PRIMARY KEY (match_id, mode)
);

-- NBA and NFL. team_aliases above maps nflverse / ESPN spellings to these ids too.
CREATE TABLE IF NOT EXISTS us_teams (
    team_id    TEXT PRIMARY KEY,            -- 'nba-bos', 'nfl-kc'
    sport      TEXT NOT NULL,               -- 'nba' | 'nfl'
    name       TEXT NOT NULL,
    short_name TEXT NOT NULL,
    nickname   TEXT,
    conference TEXT,
    division   TEXT,
    espn_id    TEXT,
    logo       TEXT
);

CREATE TABLE IF NOT EXISTS us_games (
    game_id      TEXT PRIMARY KEY,          -- 'nfl-2026_08_KC_DEN', 'nba-401909277'
    sport        TEXT NOT NULL,
    season       INTEGER NOT NULL,          -- start year: 2026 = NFL 2026 / NBA 2026-27
    season_type  TEXT NOT NULL,             -- REG | POST
    week         INTEGER,                   -- NFL week
    kickoff_utc  TEXT,
    home_id      TEXT NOT NULL REFERENCES us_teams(team_id),
    away_id      TEXT NOT NULL REFERENCES us_teams(team_id),
    neutral      INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,             -- SCHEDULED | IN_PLAY | FINISHED | POSTPONED
    home_score INTEGER, away_score INTEGER,
    overtime     INTEGER,
    venue        TEXT,
    home_qb TEXT, away_qb TEXT,             -- NFL starting quarterbacks (nflverse)
    espn_id      TEXT,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_us_games ON us_games(sport, kickoff_utc);

CREATE TABLE IF NOT EXISTS us_odds (
    game_id     TEXT NOT NULL REFERENCES us_games(game_id),
    source      TEXT NOT NULL,              -- 'nflverse' | 'espn' | provider name
    home_ml REAL, away_ml REAL,             -- American moneylines
    home_spread REAL,                       -- points, negative = home favoured
    total REAL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (game_id, source)
);

-- Player props (NBA / NFL). Athlete ids are ESPN ids.
CREATE TABLE IF NOT EXISTS us_players (
    athlete_id TEXT NOT NULL,
    sport      TEXT NOT NULL,
    name       TEXT NOT NULL,
    team_id    TEXT,
    position   TEXT,
    injury     TEXT,                        -- latest injury status from ESPN rosters ('Out', 'Day-To-Day', ...)
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sport, athlete_id)
);

CREATE TABLE IF NOT EXISTS us_player_games (
    sport      TEXT NOT NULL,
    game_id    TEXT NOT NULL,
    athlete_id TEXT NOT NULL,
    team_id    TEXT,
    kickoff_utc TEXT,
    minutes REAL,
    pts REAL, reb REAL, ast REAL, fg3m REAL,                      -- NBA
    pass_yds REAL, pass_att REAL, rush_yds REAL, carries REAL,    -- NFL
    rec REAL, targets REAL, rec_yds REAL, tds REAL,
    PRIMARY KEY (game_id, athlete_id)
);
CREATE INDEX IF NOT EXISTS idx_player_games ON us_player_games(sport, athlete_id, kickoff_utc);

CREATE TABLE IF NOT EXISTS us_props (
    game_id    TEXT NOT NULL,
    athlete_id TEXT NOT NULL,
    market     TEXT NOT NULL,               -- pts | reb | ast | fg3m | pra | pass_yds | rush_yds | rec_yds | rec | anytime_td
    line       REAL NOT NULL,
    price_a    REAL,                        -- American odds of the first listed side
    price_b    REAL,                        -- second listed side (NULL for one-sided markets)
    provider   TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (game_id, athlete_id, market)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,             -- running | ok | failed
    message     TEXT
);

CREATE TABLE IF NOT EXISTS source_status (
    source       TEXT PRIMARY KEY,
    last_ok_at   TEXT,
    last_error   TEXT,
    last_error_at TEXT
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=60)  # autocommit; transaction() opens explicit ones
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def upsert(conn: sqlite3.Connection, table: str, rows: Iterable[dict], key: tuple[str, ...],
           keep_existing_when_null: bool = True) -> int:
    """INSERT ... ON CONFLICT DO UPDATE. With keep_existing_when_null, a NULL in the new row
    never overwrites a known value (e.g. a later source that lacks shot data)."""
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    quoted = [f'"{c}"' for c in cols]
    updates = []
    for c in cols:
        if c in key:
            continue
        if keep_existing_when_null:
            updates.append(f'"{c}" = COALESCE(excluded."{c}", {table}."{c}")')
        else:
            updates.append(f'"{c}" = excluded."{c}"')
    sql = (
        f"INSERT INTO {table} ({', '.join(quoted)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT ({', '.join(key)}) DO "
        + (f"UPDATE SET {', '.join(updates)}" if updates else "NOTHING")
    )
    conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)
