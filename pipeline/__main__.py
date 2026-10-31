"""Command line entry point.

  python -m pipeline update [--retrain] [--skip-espn]   # the scheduled job
  python -m pipeline backfill-espn                      # one-off: historical cup/European dates
  python -m pipeline bootstrap                          # first run on a fresh machine

Exit code is non-zero if a required source fails or the output cannot be produced; in that
case nothing under web/public/data is touched, so the dashboard keeps the last good data.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings

import pandas as pd

from . import db, ingest
from .config import ARTIFACTS_DIR, current_season, utcnow
from .db import transaction, upsert

log = logging.getLogger("pipeline")


def _now_iso() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def mirror_tables(conn, fs, ledger_rows: dict) -> None:
    """Keep elo_history and predictions tables in sync with the computed state / ledger."""
    hist = fs.elo_history.merge(pd.read_sql_query("SELECT match_id, kickoff_utc, home_id, away_id FROM matches", conn), on="match_id")
    rows = []
    for r in hist.itertuples():
        rows.append({"match_id": r.match_id, "team_id": r.home_id, "kickoff_utc": r.kickoff_utc,
                     "rating_before": r.elo_home_pre, "rating_after": r.elo_home_post})
        rows.append({"match_id": r.match_id, "team_id": r.away_id, "kickoff_utc": r.kickoff_utc,
                     "rating_before": r.elo_away_pre, "rating_after": r.elo_away_post})
    preds = [{
        "match_id": r["match_id"], "mode": "live", "model_version": r["model_version"], "predicted_at": r["predicted_at"],
        "locked": int(r["locked"] == "1"), "p_home": float(r["p_home"]), "p_draw": float(r["p_draw"]), "p_away": float(r["p_away"]),
        "xg_home": float(r["xg_home"]) if r["xg_home"] else None, "xg_away": float(r["xg_away"]) if r["xg_away"] else None,
        "market_p_home": float(r["market_p_home"]) if r["market_p_home"] else None,
        "market_p_draw": float(r["market_p_draw"]) if r["market_p_draw"] else None,
        "market_p_away": float(r["market_p_away"]) if r["market_p_away"] else None,
    } for r in ledger_rows.values()]
    known = {r[0] for r in conn.execute("SELECT match_id FROM matches")}
    with transaction(conn):
        upsert(conn, "elo_history", rows, key=("match_id", "team_id"), keep_existing_when_null=False)
        upsert(conn, "predictions", [p for p in preds if p["match_id"] in known], key=("match_id", "mode"),
               keep_existing_when_null=False)


def update_pl(conn, args, now: pd.Timestamp) -> dict:
    from model import ledger, train
    from model.predict import predict_upcoming

    from .export import export_all

    stats = ingest.run_ingest(conn, refresh_all=args.refresh_all, skip_espn=args.skip_espn)
    if not args.skip_espn and conn.execute("SELECT COUNT(*) FROM other_matches").fetchone()[0] < 1000:
        log.info("Fresh database: backfilling historical cup/European fixtures from ESPN")
        cmd_backfill(argparse.Namespace(start=2005))
    log.info("Ingest: %s", json.dumps(stats))
    if args.retrain or not (ARTIFACTS_DIR / "LATEST").exists():
        stats["trained"] = train.train(conn)
    preds, fs, manifest = predict_upcoming(conn, now=now, gameweeks=args.gameweeks)
    state = {r["match_id"]: {"kickoff_utc": r["kickoff_utc"], "status": r["status"]}
             for r in conn.execute("SELECT match_id, kickoff_utc, status FROM matches WHERE div='E0'")}
    led = ledger.read()
    stats["ledger"] = ledger.update(led, preds, state, now.to_pydatetime())
    ledger.write(led)
    mirror_tables(conn, fs, led)
    log.info("Ledger: %s", stats["ledger"])
    evaluation = json.loads((ARTIFACTS_DIR / "evaluation.json").read_text()) if (ARTIFACTS_DIR / "evaluation.json").exists() else None
    export_all(conn, preds, fs, manifest, evaluation, {"finished_at": _now_iso(), "stats": stats})
    return stats


def update_us(conn, sport: str, args, now: pd.Timestamp) -> dict:
    from model import ledger, us_predict

    from . import us_export, us_ingest

    stats = us_ingest.run_us_ingest(conn, sport, refresh_all=args.refresh_all)
    if args.retrain or not (ARTIFACTS_DIR / sport / "LATEST").exists():
        stats["trained"] = us_predict.train(conn, sport)
    preds, fs, manifest = us_predict.predict_upcoming(conn, sport, now=now)
    state = {r["game_id"]: {"kickoff_utc": r["kickoff_utc"], "status": r["status"]}
             for r in conn.execute("SELECT game_id, kickoff_utc, status FROM us_games WHERE sport=?", (sport,))}
    path = us_export.ledger_path(sport)
    led = ledger.read(path, key="game_id")
    stats["ledger"] = ledger.update(led, preds, state, now.to_pydatetime(), columns=us_export.LEDGER_COLUMNS)
    ledger.write(led, path, us_export.LEDGER_COLUMNS)
    log.info("%s ledger: %s", sport, stats["ledger"])
    us_export.export_sport(conn, sport, preds, fs, manifest, {"finished_at": _now_iso()})
    stats["props"] = update_props(conn, sport, preds)
    return stats


def update_props(conn, sport: str, preds: list[dict]) -> dict:
    """Best effort: a props failure is recorded but never blocks the game predictions."""
    from model import props as PR

    from . import props_ingest, us_export
    from .ingest import record_source

    name = f"espn-{sport}-props"
    try:
        ids = [p["game_id"] for p in preds]
        upcoming = conn.execute(f"SELECT game_id, espn_id FROM us_games WHERE game_id IN ({','.join('?' * len(ids))})", ids).fetchall() if ids else []
        season = max((p["season"] for p in preds), default=None) or conn.execute(
            "SELECT MAX(season) FROM us_games WHERE sport=?", (sport,)).fetchone()[0]
        stats = props_ingest.update_props(conn, sport, [tuple(r) for r in upcoming], season)
        props = PR.predict_upcoming(conn, sport, ids)
        stats["ledger"] = us_export.update_props_ledger(conn, sport, props, _now_iso())
        us_export.export_props(conn, sport, props, preds)
        stats["projected"] = len(props)
        with transaction(conn):
            record_source(conn, name)
        return stats
    except Exception as exc:  # noqa: BLE001
        log.exception("%s props failed", sport)
        with transaction(conn):
            record_source(conn, name, error=f"{type(exc).__name__}: {exc}")
        return {"error": str(exc)}


SPORTS = {"pl": update_pl, "nba": lambda c, a, n: update_us(c, "nba", a, n), "nfl": lambda c, a, n: update_us(c, "nfl", a, n)}


def cmd_update(args) -> int:
    """Each sport runs independently: a failing source only stops that sport, and its last good
    dashboard data stays in place. Exit 0 = all ok, 2 = some sports failed, 1 = all failed."""
    conn = db.connect()
    with transaction(conn):
        run_id = conn.execute("INSERT INTO pipeline_runs (started_at, status) VALUES (?, 'running')", (_now_iso(),)).lastrowid
    now = pd.Timestamp.now(tz="UTC")
    results, failed = {}, []
    for sport in args.sports:
        try:
            results[sport] = SPORTS[sport](conn, args, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s update failed", sport)
            failed.append(sport)
            results[sport] = {"error": f"{type(exc).__name__}: {exc}"}
    if len(failed) < len(args.sports):
        try:
            from . import parlay_export
            results["parlays"] = parlay_export.update(conn)
        except Exception as exc:  # noqa: BLE001
            log.exception("parlays failed")
            results["parlays"] = {"error": str(exc)}
    status = "ok" if not failed else "failed" if len(failed) == len(args.sports) else "partial"
    with transaction(conn):
        conn.execute("UPDATE pipeline_runs SET finished_at=?, status=?, message=? WHERE run_id=?",
                     (_now_iso(), status, json.dumps(results, default=str)[:2000], run_id))
    print(json.dumps(results, indent=1, default=str))
    return 0 if status == "ok" else 2 if status == "partial" else 1


def cmd_backfill(args) -> int:
    from .teams import TeamMapper
    conn = db.connect()
    mapper = TeamMapper.from_csv()
    with transaction(conn):
        mapper.sync_to_db(conn)
    n = ingest.backfill_espn_history(conn, mapper, range(args.start, current_season() + 1))
    print(f"other_matches rows: {n}")
    return 0


def cmd_backfill_nba_odds(args) -> int:
    from .us_ingest import backfill_nba_odds
    print(f"NBA odds rows: {backfill_nba_odds(db.connect(), range(args.start, current_season() + 1))}")
    return 0


def cmd_bootstrap(args) -> int:
    from model import evaluate, train
    conn = db.connect()
    ingest.run_ingest(conn, refresh_all=False)
    cmd_backfill(argparse.Namespace(start=2005))
    if not (ARTIFACTS_DIR / "hyperparams.json").exists() or args.evaluate:
        evaluate.evaluate(conn)
    train.train(conn)
    for sport in ("nfl", "nba"):
        from . import us_ingest
        us_ingest.run_us_ingest(conn, sport)
        if not (ARTIFACTS_DIR / sport / "hyperparams.json").exists() or args.evaluate:
            from model import us_evaluate
            if sport == "nba":
                us_ingest.backfill_nba_odds(conn, range(2021, current_season() + 1))
            us_evaluate.evaluate(conn, sport)
        from model import props as PR
        from model import us_predict

        from . import props_ingest
        us_predict.train(conn, sport)
        if sport == "nba":
            props_ingest.backfill_nba_boxscores(conn, range(2024, current_season() + 1))
        else:
            props_ingest.load_nfl_player_stats(conn, range(2023, current_season() + 1), current_season())
        if not (ARTIFACTS_DIR / sport / "props_models.pkl").exists() or args.evaluate:
            props_ingest.backfill_props(conn, sport, range(2024, current_season() + 1))
            PR.evaluate(conn, sport)
    if not (ARTIFACTS_DIR / "parlays_backtest.json").exists() or args.evaluate:
        from . import parlay_export
        parlay_export.run_backtest()
    return cmd_update(argparse.Namespace(retrain=False, skip_espn=False, refresh_all=False, gameweeks=3, sports=list(SPORTS)))


def main(argv=None) -> int:
    warnings.filterwarnings("ignore", category=UserWarning)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="python -m pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update", help="fetch data, refresh predictions, export dashboard data")
    u.add_argument("--retrain", action="store_true", help="refit the production model first")
    u.add_argument("--skip-espn", action="store_true")
    u.add_argument("--refresh-all", action="store_true", help="re-download finished seasons too")
    u.add_argument("--gameweeks", type=int, default=3)
    u.add_argument("--sports", nargs="+", choices=list(SPORTS), default=list(SPORTS))
    u.set_defaults(fn=cmd_update)
    b = sub.add_parser("backfill-espn", help="historical cup / European fixtures for rest days")
    b.add_argument("--start", type=int, default=2005)
    b.set_defaults(fn=cmd_backfill)
    o = sub.add_parser("backfill-nba-odds", help="historical NBA odds from ESPN for the evaluation seasons")
    o.add_argument("--start", type=int, default=2021)
    o.set_defaults(fn=cmd_backfill_nba_odds)
    s = sub.add_parser("bootstrap", help="first full run: ingest, backfill, evaluate, train, update")
    s.add_argument("--evaluate", action="store_true", help="re-run the walk-forward evaluation")
    s.set_defaults(fn=cmd_bootstrap)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
