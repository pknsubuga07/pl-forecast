"""The prediction ledger: data/ledger/predictions.csv, committed to git.

Rules that keep the history honest:
  * A prediction can be written or refreshed only while its match has not kicked off.
  * Once kickoff passes (or the match is reported started/finished) the row is locked and is
    never modified again, even if the model is retrained or the match is later postponed.
  * Git history of this file is the audit trail.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config import LEDGER_DIR

LEDGER_PATH = LEDGER_DIR / "predictions.csv"
COLUMNS = [
    "match_id", "season", "gameweek", "kickoff_utc", "home_id", "away_id", "model_version",
    "first_predicted_at", "predicted_at", "locked", "locked_at",
    "p_home", "p_draw", "p_away", "xg_home", "xg_away",
    "market_source", "market_p_home", "market_p_draw", "market_p_away",
]


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(path: Path = LEDGER_PATH, key: str = "match_id") -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r[key]: r for r in csv.DictReader(f)}


def write(rows: dict[str, dict], path: Path = LEDGER_PATH, columns: list[str] = COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    key = columns[0]
    ordered = sorted(rows.values(), key=lambda r: (r.get("kickoff_utc") or "9999", r[key]))
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(ordered)
    tmp.replace(path)


def update(ledger: dict[str, dict], predictions: list[dict], match_state: dict[str, dict], now: datetime,
           columns: list[str] = COLUMNS) -> dict:
    """Lock rows whose match has started, then upsert fresh pre-kickoff predictions.

    match_state: match_id -> {"kickoff_utc": str | None, "status": str}
    Returns counts of what changed.
    """
    stats = {"locked": 0, "inserted": 0, "refreshed": 0, "skipped_locked": 0, "skipped_started": 0}
    for mid, row in ledger.items():
        if row.get("locked") == "1":
            continue
        st = match_state.get(mid, {})
        ko = _parse(st.get("kickoff_utc") or row.get("kickoff_utc"))
        started = st.get("status") in ("IN_PLAY", "FINISHED") or (ko is not None and ko <= now)
        if started and st.get("status") != "POSTPONED":
            row["locked"] = "1"
            row["locked_at"] = _iso(now)
            stats["locked"] += 1
    key = columns[0]
    for p in predictions:
        mid = p[key]
        existing = ledger.get(mid)
        if existing and existing.get("locked") == "1":
            stats["skipped_locked"] += 1
            continue
        ko = _parse(p["kickoff_utc"])
        if ko is None or ko <= now:
            stats["skipped_started"] += 1
            continue
        row = {c: "" for c in columns}
        row.update({k: ("" if v is None else str(v)) for k, v in p.items() if k in columns})
        row["predicted_at"] = _iso(now)
        row["first_predicted_at"] = existing["first_predicted_at"] if existing else _iso(now)
        row["locked"] = "0"
        row["locked_at"] = ""
        ledger[mid] = row
        stats["refreshed" if existing else "inserted"] += 1
    return stats
