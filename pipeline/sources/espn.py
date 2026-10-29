"""ESPN public site API (unofficial): venues, DraftKings moneyline odds for upcoming
Premier League games, and every club's all-competition schedule (cups, Europe) for rest days.

Best-effort only: if ESPN is unavailable the pipeline keeps going without venues/rest-day
extras and records the failure in source_status.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from ..config import RAW_DIR
from ..http import SourceError, fetch_cached

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def _load(url: str, dest_name: str, params: dict | None = None) -> dict:
    path = fetch_cached(url, RAW_DIR / "espn" / dest_name, refresh=True, params=params, min_interval=0.4)
    if path is None:
        raise SourceError(f"ESPN {url} returned 404")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SourceError(f"ESPN {url}: invalid JSON") from exc


def league_teams() -> list[dict]:
    data = _load(f"{BASE}/eng.1/teams", "eng1_teams.json")
    try:
        return [t["team"] for t in data["sports"][0]["leagues"][0]["teams"]]
    except (KeyError, IndexError) as exc:
        raise SourceError("ESPN teams: unexpected shape") from exc


# Competitive fixtures that count towards fatigue / rest days. Friendlies and pre-season
# tournaments are excluded.
COMPETITIVE_PREFIXES = ("eng.fa", "eng.league_cup", "eng.charity", "uefa.champions", "uefa.europa",
                        "uefa.super_cup", "fifa.cwc")


def is_competitive(slug: str | None) -> bool:
    return bool(slug) and slug.startswith(COMPETITIVE_PREFIXES)


def american_to_decimal(ml: str | int | float | None) -> float | None:
    if ml in (None, "", "OFF", "EVEN"):
        return 2.0 if ml == "EVEN" else None
    try:
        v = float(str(ml).replace("+", ""))
    except ValueError:
        return None
    if v == 0:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def _event_summary(e: dict) -> dict:
    c = e["competitions"][0]
    teams = {x["homeAway"]: x["team"] for x in c["competitors"]}
    out = {
        "espn_id": e["id"],
        "kickoff_utc": e["date"],
        "home_name": teams["home"]["displayName"],
        "away_name": teams["away"]["displayName"],
        "home_espn_id": teams["home"]["id"],
        "away_espn_id": teams["away"]["id"],
        "venue": (c.get("venue") or {}).get("fullName"),
        "status": c.get("status", e.get("status", {})).get("type", {}).get("name"),
        "odds": None,
    }
    for o in c.get("odds") or []:
        ml = o.get("moneyline") or {}
        def pick(side: str):
            s = ml.get(side) or {}
            return (s.get("close") or {}).get("odds") or (s.get("open") or {}).get("odds")
        h, d, a = (american_to_decimal(pick(s)) for s in ("home", "draw", "away"))
        if h and d and a:
            out["odds"] = {"bookmaker": (o.get("provider") or {}).get("name", "espn").lower(), "h": h, "d": d, "a": a}
            break
    return out


def pl_scoreboard(start: date, days: int) -> list[dict]:
    """Premier League events for each day in [start, start+days). One request per day."""
    events = []
    for i in range(days):
        day = (start + timedelta(days=i)).strftime("%Y%m%d")
        data = _load(f"{BASE}/eng.1/scoreboard", f"scoreboard_{day}.json", params={"dates": day})
        events.extend(_event_summary(e) for e in data.get("events", []))
    return events


def team_schedule(espn_team_id: str, season: int, *, fixtures: bool) -> list[dict]:
    """All competitions for one club in one season (results, or upcoming with fixtures=True)."""
    params = {"season": season}
    if fixtures:
        params["fixture"] = "true"
    tag = "fix" if fixtures else "res"
    data = _load(f"{BASE}/all/teams/{espn_team_id}/schedule", f"sched_{espn_team_id}_{season}_{tag}.json", params=params)
    out = []
    for e in data.get("events", []):
        league = e.get("league") or {}
        c = e["competitions"][0]
        opp = [x["team"] for x in c["competitors"] if x["team"]["id"] != str(espn_team_id)]
        out.append({
            "espn_event_id": e["id"],
            "kickoff_utc": e["date"],
            "competition": league.get("abbreviation") or league.get("name") or "Unknown",
            "competition_slug": league.get("slug"),
            "opponent": opp[0]["displayName"] if opp else None,
            "opponent_id": opp[0]["id"] if opp else None,
            "status": (c.get("status") or {}).get("type", {}).get("name"),
        })
    return out
