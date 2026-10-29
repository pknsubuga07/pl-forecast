"""Fantasy Premier League public API: current-season fixtures, gameweeks, kickoff times
(UTC), live/finished scores and club codes (used for crest images).

Unofficial and undocumented, no key needed. We make 2 requests per pipeline run.
"""
from __future__ import annotations

import json

from ..config import RAW_DIR
from ..http import SourceError, fetch_cached

BASE = "https://fantasy.premierleague.com/api"


def _load(name: str, url: str) -> dict | list:
    path = fetch_cached(url, RAW_DIR / "fpl" / f"{name}.json", refresh=True, min_interval=1.0)
    if path is None:
        raise SourceError(f"FPL {url} returned 404")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SourceError(f"FPL {url}: invalid JSON ({exc})") from exc


def fetch() -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (teams, events, fixtures) exactly as the API shapes them, after validation."""
    boot = _load("bootstrap-static", f"{BASE}/bootstrap-static/")
    fixtures = _load("fixtures", f"{BASE}/fixtures/")
    if not isinstance(boot, dict) or "teams" not in boot or "events" not in boot:
        raise SourceError("FPL bootstrap-static: unexpected shape (no teams/events)")
    if not isinstance(fixtures, list) or (fixtures and "team_h" not in fixtures[0]):
        raise SourceError("FPL fixtures: unexpected shape")
    return boot["teams"], boot["events"], fixtures
