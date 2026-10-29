"""football-data.co.uk: historical results, match stats and bookmaker odds (CSV).

Terms: free to download for personal / research use; the site asks users not to hammer it.
We download each finished season once and only refresh the current season and fixtures.csv.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..config import RAW_DIR, season_code
from ..http import SourceError, fetch_cached

log = logging.getLogger(__name__)
BASE = "https://www.football-data.co.uk"
LONDON = ZoneInfo("Europe/London")

REQUIRED = ["Div", "Date", "HomeTeam", "AwayTeam"]

# Column -> our name. Not every season has every column.
STAT_COLS = {
    "FTHG": "fthg", "FTAG": "ftag", "HTHG": "hthg", "HTAG": "htag",
    "HS": "hs", "AS": "as", "HST": "hst", "AST": "ast",
    "HC": "hc", "AC": "ac", "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
    "HxG": "hxg", "AxG": "axg",
}

# (bookmaker key, candidate column prefixes in priority order). Opening/pre-match odds are
# collected by football-data on Fridays (weekend) / Tuesdays (midweek); "C" columns are closing.
ODDS_SETS = {
    "avg": ["Avg", "BbAv"],
    "max": ["Max", "BbMx"],
    "b365": ["B365"],
    "pinnacle": ["PS", "PSC_unused"],
    "avg_close": ["AvgC"],
    "pinnacle_close": ["PSC"],
    "b365_close": ["B365C"],
}


def season_csv_url(start_year: int, div: str) -> str:
    return f"{BASE}/mmz4281/{season_code(start_year)}/{div}.csv"


def download_season(start_year: int, div: str, *, refresh: bool) -> pd.DataFrame | None:
    dest = RAW_DIR / "football-data" / f"{season_code(start_year)}_{div}.csv"
    path = fetch_cached(season_csv_url(start_year, div), dest, refresh=refresh)
    if path is None:
        return None
    return read_csv_bytes(path.read_bytes(), source=str(path))


def download_fixtures(*, refresh: bool = True) -> pd.DataFrame | None:
    dest = RAW_DIR / "football-data" / "fixtures.csv"
    path = fetch_cached(f"{BASE}/fixtures.csv", dest, refresh=refresh)
    if path is None:
        return None
    return read_csv_bytes(path.read_bytes(), source=str(path))


def read_csv_bytes(raw: bytes, *, source: str) -> pd.DataFrame:
    text = raw.decode("utf-8-sig", errors="replace")
    if text.lstrip().startswith("<"):
        raise SourceError(f"{source}: expected CSV, got HTML (format change or error page)")
    df = pd.read_csv(io.StringIO(text), on_bad_lines="skip", low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise SourceError(f"{source}: missing expected columns {missing}")
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "Date"])
    return df


def parse_kickoff(date_str: str, time_str: str | float | None) -> tuple[str, bool]:
    """football-data dates are dd/mm/yy or dd/mm/yyyy, times are UK local time.

    Returns (UTC ISO timestamp, has_time). Without a time we assume 15:00 UK.
    """
    date_str = str(date_str).strip()
    fmt = "%d/%m/%Y" if len(date_str.split("/")[-1]) == 4 else "%d/%m/%y"
    d = datetime.strptime(date_str, fmt)
    has_time = isinstance(time_str, str) and ":" in time_str
    hh, mm = (int(x) for x in time_str.split(":")[:2]) if has_time else (15, 0)
    local = d.replace(hour=hh, minute=mm, tzinfo=LONDON)
    return local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"), has_time


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Turn a raw football-data frame into one row per match with tidy columns.

    Team names are left as raw football-data aliases; mapping happens in teams.py.
    """
    out = pd.DataFrame({
        "div": df["Div"].astype(str).str.strip(),
        "home_alias": df["HomeTeam"].astype(str).str.strip(),
        "away_alias": df["AwayTeam"].astype(str).str.strip(),
    })
    times = df["Time"] if "Time" in df.columns else pd.Series([None] * len(df), index=df.index)
    parsed = [parse_kickoff(d, t if isinstance(t, str) else None) for d, t in zip(df["Date"], times)]
    out["kickoff_utc"] = [p[0] for p in parsed]
    out["has_time"] = [p[1] for p in parsed]
    for src, dst in STAT_COLS.items():
        out[dst] = _num(df[src]) if src in df.columns else np.nan
    for key, prefixes in ODDS_SETS.items():
        for prefix in prefixes:
            cols = [f"{prefix}H", f"{prefix}D", f"{prefix}A"]
            if all(c in df.columns for c in cols):
                vals = df[cols].apply(_num)
                out[f"{key}_h"], out[f"{key}_d"], out[f"{key}_a"] = (vals[c].values for c in cols)
                break
        else:
            out[f"{key}_h"] = out[f"{key}_d"] = out[f"{key}_a"] = np.nan
    return out.reset_index(drop=True)
