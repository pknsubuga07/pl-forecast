"""Daily parlays: build from the freshly exported predictions, freeze, settle, export.

Ledger rules (data/ledger/parlays.csv):
  * A day's parlays are rebuilt on every run until the first leg of any of that day's parlays
    kicks off; then the whole day's set is locked and never rebuilt.
  * Locked parlays are settled as their games finish (won / lost / void if a leg is postponed).
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from model import parlays as P

from .config import ARTIFACTS_DIR, LEDGER_DIR, WEB_DATA_DIR
from .export import _clean

log = logging.getLogger(__name__)
LEDGER = LEDGER_DIR / "parlays.csv"
COLUMNS = ["parlay_id", "day", "tag", "n_legs", "legs", "p_model", "p_market", "odds", "first_kickoff",
           "created_at", "locked", "status", "settled_at"]
BACKTEST_PATH = ARTIFACTS_DIR / "parlays_backtest.json"
DAYS_AHEAD = 3


def et_day(ts: str) -> str:
    return pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d")


def read_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    with open(LEDGER, newline="") as f:
        return list(csv.DictReader(f))


def write_ledger(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["day"], r["created_at"], r["parlay_id"]))
    tmp = LEDGER.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(LEDGER)


def current_legs() -> list[P.Leg]:
    legs = []
    path = WEB_DATA_DIR / "fixtures.json"
    if path.exists():
        legs += [l for l in (P.pl_leg(f) for f in json.loads(path.read_text())) if l]
    for sport in ("nba", "nfl"):
        path = WEB_DATA_DIR / sport / "games.json"
        if path.exists():
            legs += [l for l in (P.us_leg(sport, g) for g in json.loads(path.read_text())) if l]
    return legs


def results(conn: sqlite3.Connection) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for r in conn.execute("SELECT match_id, status, fthg, ftag FROM matches WHERE div='E0' AND season >= 2026"):
        if r["status"] == "FINISHED" and r["fthg"] is not None:
            out[r["match_id"]] = "H" if r["fthg"] > r["ftag"] else "A" if r["fthg"] < r["ftag"] else "D"
        elif r["status"] == "POSTPONED":
            out[r["match_id"]] = "VOID"
    for r in conn.execute("SELECT game_id, status, home_score, away_score FROM us_games WHERE season >= 2026"):
        if r["status"] == "FINISHED" and r["home_score"] is not None:
            out[r["game_id"]] = "H" if r["home_score"] > r["away_score"] else "A" if r["home_score"] < r["away_score"] else "D"
        elif r["status"] == "POSTPONED":
            out[r["game_id"]] = "VOID"
    return out


def update(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = read_ledger()
    legs = current_legs()
    by_day: dict[str, list[P.Leg]] = {}
    for l in legs:
        by_day.setdefault(et_day(l.kickoff_utc), []).append(l)
    today = pd.Timestamp(now).tz_convert("America/New_York").strftime("%Y-%m-%d")
    days = sorted(d for d in by_day if d >= today)[:DAYS_AHEAD]
    stats = {"built": 0, "locked_days": 0}
    for day in days:
        existing = [r for r in rows if r["day"] == day]
        if any(r["locked"] == "1" for r in existing):
            continue
        if existing and min(r["first_kickoff"] for r in existing) <= stamp:
            for r in existing:
                r["locked"] = "1"
            stats["locked_days"] += 1
            continue
        fresh = P.build(by_day[day])
        rows = [r for r in rows if r["day"] != day]
        for p in fresh:
            d = p.to_dict()
            rows.append({"parlay_id": d["id"], "day": day, "tag": d["tag"], "n_legs": d["n_legs"],
                         "legs": json.dumps([{k: l[k] for k in ("sport", "game_id", "pick", "label", "matchup", "kickoff_utc",
                                                                 "p_model", "p_market", "odds", "confidence", "href")} for l in d["legs"]]),
                         "p_model": d["p_model"], "p_market": "" if d["p_market"] is None else d["p_market"], "odds": d["odds"],
                         "first_kickoff": d["first_kickoff"], "created_at": stamp, "locked": "0", "status": "open", "settled_at": ""})
            stats["built"] += 1
    # Lock any day whose first leg has started (including days no longer in the window).
    for day in {r["day"] for r in rows}:
        day_rows = [r for r in rows if r["day"] == day]
        if any(r["locked"] != "1" for r in day_rows) and min(r["first_kickoff"] for r in day_rows) <= stamp:
            for r in day_rows:
                r["locked"] = "1"
    res = results(conn)
    for r in rows:
        if r["locked"] == "1" and r["status"] == "open":
            st = P.settle(json.loads(r["legs"]), res)
            if st != "open":
                r["status"], r["settled_at"] = st, stamp
    write_ledger(rows)
    export(rows, by_day, days, stamp)
    return stats


def summary(rows: list[dict]) -> dict | None:
    done = [r for r in rows if r["status"] in ("won", "lost")]
    if not done:
        return None
    won = [r for r in done if r["status"] == "won"]
    profit = sum(float(r["odds"]) - 1 for r in won) - (len(done) - len(won))
    return {"n": len(done), "won": len(won), "hit_rate": len(won) / len(done),
            "expected_hit_rate": float(np.mean([float(r["p_model"]) for r in done])), "roi": profit / len(done)}


def export(rows: list[dict], by_day: dict, days: list[str], stamp: str) -> None:
    def view(r):
        return {**{k: r[k] for k in ("parlay_id", "day", "tag", "status", "first_kickoff", "locked")},
                "n_legs": int(r["n_legs"]), "p_model": float(r["p_model"]),
                "p_market": float(r["p_market"]) if r["p_market"] not in ("", None) else None,
                "odds": float(r["odds"]), "legs": json.loads(r["legs"])}
    out_days = []
    for day in days:
        eligible = P.eligible(by_day.get(day, []))
        out_days.append({"day": day, "n_games": len(by_day.get(day, [])), "n_eligible": len(eligible),
                         "parlays": [view(r) for r in rows if r["day"] == day]})
    settled = sorted([r for r in rows if r["status"] in ("won", "lost", "void")], key=lambda r: r["day"], reverse=True)
    backtest = json.loads(BACKTEST_PATH.read_text()) if BACKTEST_PATH.exists() else None
    data = {"generated_at": stamp, "days": out_days, "record": summary(rows),
            "history": [view(r) for r in settled[:80]], "backtest": backtest}
    path = WEB_DATA_DIR / "parlays.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(data), separators=(",", ":"), allow_nan=False))
    tmp.replace(path)


def run_backtest() -> dict:
    pl_path = ARTIFACTS_DIR / "walkforward.csv"
    pl = pd.read_csv(pl_path) if pl_path.exists() else None
    us = {s: pd.read_csv(ARTIFACTS_DIR / s / "walkforward.csv") for s in ("nba", "nfl") if (ARTIFACTS_DIR / s / "walkforward.csv").exists()}
    seasons = {"pl": [2021, 2022, 2023, 2024, 2025], "nba": [2021, 2022, 2023, 2024, 2025], "nfl": [2021, 2022, 2023, 2024, 2025]}
    res = P.backtest(pl, us, seasons)
    res["seasons"] = "2021-22 to 2025-26 (Premier League, NBA) and 2021 to 2025 (NFL), walk-forward predictions"
    BACKTEST_PATH.write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_backtest(), indent=1))
