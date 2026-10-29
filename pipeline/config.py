"""Paths, season helpers and source settings shared by the pipeline and model."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EPL_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
LEDGER_DIR = DATA_DIR / "ledger"
DB_PATH = Path(os.environ.get("EPL_DB_PATH", DATA_DIR / "epl.sqlite"))
TEAM_ALIASES_CSV = DATA_DIR / "team_aliases.csv"
POINT_DEDUCTIONS_CSV = DATA_DIR / "point_deductions.csv"
ARTIFACTS_DIR = ROOT / "model" / "artifacts"
WEB_DATA_DIR = Path(os.environ.get("EPL_WEB_DATA_DIR", ROOT / "web" / "public" / "data"))

# First season we download. Seasons before FIRST_FEATURE_SEASON are only used to warm up
# Elo / rolling features and are never used as training targets.
FIRST_SEASON = 2004
FIRST_TRAIN_SEASON = 2007

USER_AGENT = os.environ.get(
    "EPL_USER_AGENT",
    "epl-predictor/1.0 (personal, educational project; low-volume requests)",
)
HTTP_TIMEOUT = 30

DIVISIONS = ("E0", "E1")  # Premier League, Championship


def season_label(start_year: int) -> str:
    """2026 -> '2026-27'."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def season_code(start_year: int) -> str:
    """2026 -> '2627' (football-data.co.uk folder name)."""
    return f"{str(start_year)[-2:]}{str(start_year + 1)[-2:]}"


def season_of(d: date | datetime) -> int:
    """Start year of the English season a date falls in (seasons roll over on 1 July)."""
    return d.year if d.month >= 7 else d.year - 1


def current_season(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return season_of(now)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
