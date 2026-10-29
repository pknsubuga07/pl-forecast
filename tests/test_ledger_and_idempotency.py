from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from model import ledger
from pipeline import db, ingest
from pipeline.teams import TeamMapper

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def pred(mid, ko, p=(0.5, 0.3, 0.2)):
    return {"match_id": mid, "kickoff_utc": ko, "p_home": p[0], "p_draw": p[1], "p_away": p[2], "model_version": "v1"}


def test_prediction_is_frozen_once_kickoff_passes(tmp_path):
    path = tmp_path / "ledger.csv"
    rows = {}
    ko = (NOW + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.update(rows, [pred("m1", ko)], {"m1": {"kickoff_utc": ko, "status": "SCHEDULED"}}, NOW)
    first = dict(rows["m1"])
    # A later run before kickoff may refresh the prediction...
    ledger.update(rows, [pred("m1", ko, (0.4, 0.3, 0.3))], {"m1": {"kickoff_utc": ko, "status": "SCHEDULED"}}, NOW + timedelta(hours=1))
    assert rows["m1"]["p_home"] == "0.4"
    assert rows["m1"]["first_predicted_at"] == first["first_predicted_at"]
    # ...but after kickoff the row locks and new predictions are ignored.
    later = NOW + timedelta(hours=3)
    stats = ledger.update(rows, [pred("m1", ko, (0.9, 0.05, 0.05))], {"m1": {"kickoff_utc": ko, "status": "IN_PLAY"}}, later)
    assert stats["locked"] == 1 and stats["skipped_locked"] == 1
    assert rows["m1"]["locked"] == "1" and rows["m1"]["p_home"] == "0.4"
    ledger.write(rows, path)
    again = ledger.read(path)
    assert again["m1"]["p_home"] == "0.4" and again["m1"]["locked"] == "1"


def test_never_writes_a_prediction_after_kickoff():
    rows = {}
    ko = (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = ledger.update(rows, [pred("m2", ko)], {"m2": {"kickoff_utc": ko, "status": "SCHEDULED"}}, NOW)
    assert stats["skipped_started"] == 1 and "m2" not in rows


def test_postponed_unlocked_prediction_stays_editable():
    rows = {}
    ko = (NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.update(rows, [pred("m3", ko)], {}, NOW)
    # Postponed: FPL clears the kickoff. Row must not lock.
    ledger.update(rows, [], {"m3": {"kickoff_utc": None, "status": "POSTPONED"}}, NOW + timedelta(days=2))
    assert rows["m3"]["locked"] == "0"
    new_ko = (NOW + timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.update(rows, [pred("m3", new_ko, (0.3, 0.3, 0.4))], {"m3": {"kickoff_utc": new_ko, "status": "SCHEDULED"}}, NOW + timedelta(days=3))
    assert rows["m3"]["kickoff_utc"] == new_ko and rows["m3"]["p_away"] == "0.4"


# ------------------------------------------------------------------ idempotent loading
FD_CSV = b"""Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HS,AS,HST,AST,AvgH,AvgD,AvgA
E0,16/08/2025,15:00,Man United,Arsenal,0,1,10,12,3,5,3.1,3.4,2.3
E0,17/08/2025,14:00,Nott'm Forest,Brentford,3,1,14,8,6,2,2.0,3.5,3.8
"""


def test_loading_twice_creates_no_duplicates(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    mapper = TeamMapper.from_csv()
    mapper.sync_to_db(conn)
    df = ingest.football_data.read_csv_bytes(FD_CSV, source="t")
    for _ in range(3):
        matches, odds = ingest.football_data_rows(df, 2025, mapper)
        db.upsert(conn, "matches", matches, key=("match_id",))
        db.upsert(conn, "odds", odds, key=("match_id", "bookmaker"), keep_existing_when_null=False)
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM odds").fetchone()[0] == 2
    row = conn.execute("SELECT * FROM matches WHERE match_id='E0-2025-man-united-arsenal'").fetchone()
    assert row["kickoff_utc"] == "2025-08-16T14:00:00Z" and row["ftag"] == 1 and row["status"] == "FINISHED"


def test_null_from_a_later_source_does_not_erase_known_values(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    TeamMapper.from_csv().sync_to_db(conn)
    base = {"match_id": "x", "div": "E0", "season": 2025, "home_id": "arsenal", "away_id": "chelsea",
            "status": "FINISHED", "updated_at": "now", "hst": 7}
    db.upsert(conn, "matches", [base], key=("match_id",))
    db.upsert(conn, "matches", [{**base, "hst": None}], key=("match_id",))
    assert conn.execute("SELECT hst FROM matches").fetchone()[0] == 7


def test_fpl_postponement_clears_kickoff_and_is_idempotent(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite")
    mapper = TeamMapper.from_csv()
    mapper.sync_to_db(conn)
    teams = [{"id": 1, "name": "Arsenal", "code": 3}, {"id": 2, "name": "Chelsea", "code": 8}]
    fixtures = [{"id": 10, "event": 9, "kickoff_time": "2026-10-31T15:00:00Z", "team_h": 1, "team_a": 2,
                 "finished": False, "finished_provisional": False, "started": False,
                 "team_h_score": None, "team_a_score": None}]
    monkeypatch.setattr(ingest.fpl, "fetch", lambda: (teams, [{"id": 9}], fixtures))
    ingest.load_fpl(conn, mapper)
    ingest.load_fpl(conn, mapper)
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
    fixtures[0].update({"kickoff_time": None, "event": None})
    fixtures.append({**fixtures[0], "id": 11, "event": 1, "kickoff_time": "2026-08-20T19:00:00Z", "team_h": 2, "team_a": 1})
    ingest.load_fpl(conn, mapper)
    row = conn.execute("SELECT * FROM matches WHERE match_id='E0-2026-arsenal-chelsea'").fetchone()
    assert row["kickoff_utc"] is None and row["status"] == "POSTPONED"
    assert conn.execute("SELECT fpl_code FROM teams WHERE team_id='arsenal'").fetchone()[0] == 3
