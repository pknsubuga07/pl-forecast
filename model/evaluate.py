"""Walk-forward evaluation, hyper-parameter selection and the evaluation report.

Protocol (fixed before looking at any test results):
  * Validation seasons 2016-17 .. 2020-21: used to pick Elo / Dixon-Coles / learner
    hyper-parameters and the ensemble weights.
  * Test seasons 2021-22 .. 2025-26: scored once with the chosen settings.
  * 2026-27 so far: extra out-of-sample check (models trained on seasons before 2026).
For a season S every learner is trained only on seasons < S; Dixon-Coles is refit twice a
week on matches strictly before the fit date. No random splits anywhere.

Run: python -m model.evaluate
"""
from __future__ import annotations

import itertools
import json
import logging
from dataclasses import asdict, replace

import numpy as np
import pandas as pd

from pipeline import db
from pipeline.config import ARTIFACTS_DIR, FIRST_TRAIN_SEASON, LEDGER_DIR, ROOT, current_season, season_label

from . import dixon_coles as dc
from . import features as F
from .elo import EloParams, run_elo
from .learners import Ensemble, GBMParams, make_elo_lr, make_gbm, make_logreg, proba3
from .metrics import all_metrics, calibration, implied_probs, log_loss, normalise

log = logging.getLogger(__name__)

VALID = list(range(2016, 2021))
TEST = list(range(2021, 2026))
CURRENT = current_season()
HYPERPARAMS_PATH = ARTIFACTS_DIR / "hyperparams.json"
EVAL_PATH = ARTIFACTS_DIR / "evaluation.json"
REPORT_PATH = ROOT / "docs" / "evaluation.md"

MODEL_LABELS = {
    "home": "Always home win (base-rate probabilities)",
    "elo": "Elo (logistic on rating gap)",
    "dc": "Dixon-Coles goals model",
    "logreg": "Multinomial logistic regression",
    "gbm": "Gradient boosting (HistGradientBoosting)",
    "ensemble": "Ensemble (final model)",
    "market": "Bookmaker average, pre-match (margin removed)",
    "market_close": "Bookmaker average, closing (margin removed)",
}


def market_table(conn, book: str) -> pd.DataFrame:
    o = pd.read_sql_query("SELECT match_id, odds_h, odds_d, odds_a FROM odds WHERE bookmaker = ?", conn, params=(book,))
    p = implied_probs(o["odds_h"], o["odds_d"], o["odds_a"])
    return pd.DataFrame(p, columns=["mk_h", "mk_d", "mk_a"], index=o["match_id"])


# --------------------------------------------------------------------------- tuning helpers
def elo_frame(m: pd.DataFrame, params: EloParams) -> pd.DataFrame:
    fin = m[(m["status"] == "FINISHED") & m["fthg"].notna()]
    hist, _ = run_elo(fin, params)
    e0 = fin[(fin["div"] == "E0") & (fin["season"] >= FIRST_TRAIN_SEASON)].merge(hist, on="match_id")
    e0["elo_diff"] = e0["elo_home_pre"] - e0["elo_away_pre"]
    e0["y"] = F.outcome(e0["fthg"], e0["ftag"])
    return e0


def elo_wf_loss(e0: pd.DataFrame, seasons: list[int]) -> float:
    losses, n = 0.0, 0
    for s in seasons:
        tr, te = e0[e0["season"] < s], e0[e0["season"] == s]
        lr = make_elo_lr().fit(tr[["elo_diff"]], tr["y"])
        losses += log_loss(proba3(lr, te[["elo_diff"]]), te["y"]) * len(te)
        n += len(te)
    return losses / n


def tune_elo(m: pd.DataFrame) -> EloParams:
    best, best_loss = None, np.inf
    for k, hfa, reg in itertools.product([10, 15, 20, 25], [65, 80, 95], [0.05, 0.1, 0.2]):
        p = EloParams(k=k, home_adv=hfa, season_regression=reg)
        loss = elo_wf_loss(elo_frame(m, p), VALID)
        log.info("elo k=%s hfa=%s reg=%s -> %.5f", k, hfa, reg, loss)
        if loss < best_loss:
            best, best_loss = p, loss
    log.info("best Elo %s (%.5f)", best, best_loss)
    return best


def tune_dc(m: pd.DataFrame) -> dc.DCParams:
    e0 = m[m["div"] == "E0"].copy()
    tgt = e0[e0["season"].isin(VALID) & (e0["status"] == "FINISHED")].sort_values("kickoff").reset_index(drop=True)
    y = F.outcome(tgt["fthg"], tgt["ftag"])
    now = pd.Timestamp.now(tz="UTC")
    best, best_loss = None, np.inf
    for xi, ridge, prior, sw in itertools.product([0.0019, 0.0028, 0.004], [1.5, 3.0, 6.0], [-0.2], [0.0, 0.3, 0.6]):
        p = dc.DCParams(xi=xi, ridge=ridge, promoted_attack=prior, promoted_defence=prior, sot_weight=sw)
        pr = F.dc_walk_forward(e0, tgt, now, p)
        probs = normalise(pr.loc[tgt.index, ["dc_ph", "dc_pd", "dc_pa"]].to_numpy())
        loss = log_loss(probs, y)
        log.info("dc xi=%s ridge=%s prior=%s sot=%s -> %.5f", xi, ridge, prior, sw, loss)
        if loss < best_loss:
            best, best_loss = p, loss
    log.info("best DC %s (%.5f)", best, best_loss)
    return best


GBM_GRID = [
    GBMParams(learning_rate=0.03, max_iter=200, max_depth=2, min_samples_leaf=80),
    GBMParams(learning_rate=0.02, max_iter=200, max_depth=2, min_samples_leaf=150, l2_regularization=3.0),
    GBMParams(learning_rate=0.01, max_iter=400, max_depth=2, min_samples_leaf=150, l2_regularization=3.0),
    GBMParams(learning_rate=0.05, max_iter=300, max_depth=1, min_samples_leaf=100),
    GBMParams(learning_rate=0.02, max_iter=300, max_depth=2, min_samples_leaf=200, l2_regularization=5.0),
    GBMParams(learning_rate=0.03, max_iter=300, max_depth=3, min_samples_leaf=60),
]
LR_GRID = [0.001, 0.003, 0.01, 0.03]


def train_rows(frame: pd.DataFrame, before_season: int) -> pd.DataFrame:
    return frame[(frame["season"] < before_season) & (frame["y"] >= 0)]


def wf_predict(frame: pd.DataFrame, seasons: list[int], kind: str, param) -> pd.DataFrame:
    """Walk-forward predictions for one learner. Returns rows indexed like frame."""
    out = []
    for s in seasons:
        tr = train_rows(frame, s)
        te = frame[(frame["season"] == s) & (frame["y"] >= 0)]
        if kind == "gbm":
            mdl = make_gbm(param).fit(tr[F.FEATURES], tr["y"])
            p = proba3(mdl, te[F.FEATURES])
        elif kind == "logreg":
            mdl = make_logreg(param).fit(tr[F.FEATURES], tr["y"])
            p = proba3(mdl, te[F.FEATURES])
        elif kind == "elo":
            mdl = make_elo_lr().fit(tr[["elo_diff"]], tr["y"])
            p = proba3(mdl, te[["elo_diff"]])
        elif kind == "home":
            freq = np.bincount(tr["y"], minlength=3) / len(tr)
            p = np.tile(freq, (len(te), 1))
        elif kind == "dc":
            p = normalise(te[["dc_ph", "dc_pd", "dc_pa"]].to_numpy())
        else:
            raise ValueError(kind)
        out.append(pd.DataFrame(p, index=te.index, columns=["p_h", "p_d", "p_a"]))
    return pd.concat(out)


def choose_weights(preds: dict[str, pd.DataFrame], y: pd.Series, names: list[str], step: float = 0.05) -> dict[str, float]:
    """Grid search on the simplex for the weighted average with the lowest validation log loss."""
    grid = np.arange(0, 1 + 1e-9, step)
    best, best_loss = None, np.inf
    for w in itertools.product(grid, repeat=len(names) - 1):
        if sum(w) > 1 + 1e-9:
            continue
        ws = list(w) + [1 - sum(w)]
        p = normalise(sum(wi * preds[n].loc[y.index].to_numpy() for wi, n in zip(ws, names)))
        loss = log_loss(p, y.to_numpy())
        if loss < best_loss:
            best, best_loss = dict(zip(names, (round(float(x), 4) for x in ws))), loss
    return best


def evaluate(conn) -> dict:
    m = F.load_matches(conn)
    log.info("Tuning Elo on validation seasons %s", VALID)
    elo_p = tune_elo(m)
    log.info("Tuning Dixon-Coles on validation seasons")
    dc_p = tune_dc(m)
    fs = F.build(conn, elo_params=elo_p, dc_params=dc_p, matches=m)
    frame = fs.frame
    fin = frame[frame["y"] >= 0]
    mk = market_table(conn, "avg")
    mkc = market_table(conn, "avg_close")

    # Learner hyper-parameters on validation seasons.
    valid_y = fin.loc[fin["season"].isin(VALID), "y"]
    best_gbm, best_gbm_loss = None, np.inf
    for gp in GBM_GRID:
        loss = log_loss(wf_predict(frame, VALID, "gbm", gp).loc[valid_y.index].to_numpy(), valid_y)
        log.info("gbm %s -> %.5f", gp, loss)
        if loss < best_gbm_loss:
            best_gbm, best_gbm_loss = gp, loss
    best_c, best_c_loss = None, np.inf
    for c in LR_GRID:
        loss = log_loss(wf_predict(frame, VALID, "logreg", c).loc[valid_y.index].to_numpy(), valid_y)
        log.info("logreg C=%s -> %.5f", c, loss)
        if loss < best_c_loss:
            best_c, best_c_loss = c, loss

    seasons = VALID + TEST + [CURRENT]
    preds = {
        "home": wf_predict(frame, seasons, "home", None),
        "elo": wf_predict(frame, seasons, "elo", None),
        "dc": wf_predict(frame, seasons, "dc", None),
        "logreg": wf_predict(frame, seasons, "logreg", best_c),
        "gbm": wf_predict(frame, seasons, "gbm", best_gbm),
    }
    weights = choose_weights(preds, valid_y, ["dc", "gbm", "logreg", "elo"])
    log.info("ensemble weights (validation): %s", weights)
    preds["ensemble"] = pd.DataFrame(
        normalise(sum(w * preds[k].to_numpy() for k, w in weights.items())),
        index=preds["dc"].index, columns=["p_h", "p_d", "p_a"])
    idx = preds["dc"].index
    preds["market"] = mk.reindex(frame.loc[idx, "match_id"]).set_axis(idx).rename(columns={"mk_h": "p_h", "mk_d": "p_d", "mk_a": "p_a"})
    preds["market_close"] = mkc.reindex(frame.loc[idx, "match_id"]).set_axis(idx).rename(columns={"mk_h": "p_h", "mk_d": "p_d", "mk_a": "p_a"})

    def score(rows: pd.Index, names) -> dict:
        res = {}
        for n in names:
            p = preds[n].loc[rows]
            ok = p.notna().all(axis=1)
            if ok.sum() == 0:
                continue
            res[n] = all_metrics(p[ok].to_numpy(), frame.loc[p[ok].index, "y"].to_numpy())
        return res

    names = ["home", "elo", "dc", "logreg", "gbm", "ensemble", "market", "market_close"]
    blocks = {}
    for label, ss in (("validation", VALID), ("test", TEST), ("current", [CURRENT])):
        rows = fin.index[fin["season"].isin(ss)]
        rows = rows[preds["market"].loc[rows].notna().all(axis=1)]  # common subset with market odds
        blocks[label] = {"seasons": [season_label(s) for s in ss], "n": int(len(rows)), "metrics": score(rows, names)}
        close_rows = rows[preds["market_close"].loc[rows].notna().all(axis=1)]
        blocks[label]["closing_subset"] = {"n": int(len(close_rows)),
                                           "metrics": score(close_rows, ["ensemble", "market", "market_close"])}
    per_season = []
    for s in VALID + TEST + [CURRENT]:
        rows = fin.index[fin["season"] == s]
        rows = rows[preds["market"].loc[rows].notna().all(axis=1)]
        per_season.append({"season": season_label(s), "n": int(len(rows)),
                           "metrics": score(rows, ["home", "elo", "dc", "gbm", "ensemble", "market"])})
    test_rows = fin.index[fin["season"].isin(TEST)]
    calib = {n: calibration(preds[n].loc[test_rows].dropna().to_numpy(), frame.loc[preds[n].loc[test_rows].dropna().index, "y"].to_numpy())
             for n in ("ensemble", "market", "dc", "gbm")}

    hyper = {"elo": asdict(elo_p), "dc": asdict(dc_p), "gbm": asdict(best_gbm), "logreg_c": best_c,
             "ensemble_weights": weights, "validation_seasons": VALID, "test_seasons": TEST}
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    HYPERPARAMS_PATH.write_text(json.dumps(hyper, indent=2))
    result = {"generated_at": pd.Timestamp.now(tz="UTC").isoformat(), "labels": MODEL_LABELS,
              "hyperparams": hyper, "blocks": blocks, "per_season": per_season, "calibration_test": calib}
    EVAL_PATH.write_text(json.dumps(result, indent=2))

    # Retroactive backtest for the current season (shown on the history page, labelled as such).
    cur = fin[fin["season"] == CURRENT]
    bt = pd.DataFrame({
        "match_id": cur["match_id"], "kickoff_utc": cur["kickoff_utc"],
        "p_home": preds["ensemble"].loc[cur.index, "p_h"].round(5),
        "p_draw": preds["ensemble"].loc[cur.index, "p_d"].round(5),
        "p_away": preds["ensemble"].loc[cur.index, "p_a"].round(5),
        "xg_home": cur["dc_lambda"].round(3), "xg_away": cur["dc_mu"].round(3),
        "model": f"walk-forward ensemble trained on seasons before {season_label(CURRENT)}",
    })
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    bt.to_csv(LEDGER_DIR / "backtest_current_season.csv", index=False)
    # Walk-forward predictions + market odds, used by the parlay backtest.
    odds = pd.read_sql_query("SELECT match_id, odds_h, odds_d, odds_a FROM odds WHERE bookmaker='avg'", conn).set_index("match_id")
    wfr = fin[fin["season"].isin(VALID + TEST + [CURRENT])]
    wf_out = pd.DataFrame({"game_id": wfr["match_id"], "kickoff_utc": wfr["kickoff_utc"], "season": wfr["season"],
                           "p_h": preds["ensemble"].loc[wfr.index, "p_h"], "p_d": preds["ensemble"].loc[wfr.index, "p_d"],
                           "p_a": preds["ensemble"].loc[wfr.index, "p_a"], "y": wfr["y"],
                           "home": wfr["home_id"], "away": wfr["away_id"]}).join(odds, on="game_id")
    wf_out.round(5).to_csv(ARTIFACTS_DIR / "walkforward.csv", index=False)
    write_report(result)
    return result


def _fmt_table(metrics: dict, order: list[str]) -> str:
    lines = ["| Model | Log loss | Brier | RPS | Accuracy |", "|---|---:|---:|---:|---:|"]
    for n in order:
        if n not in metrics:
            continue
        r = metrics[n]
        lines.append(f"| {MODEL_LABELS[n]} | {r['log_loss']:.4f} | {r['brier']:.4f} | {r['rps']:.4f} | {r['accuracy']:.1%} |")
    return "\n".join(lines)


def write_report(res: dict) -> None:
    order = ["home", "elo", "dc", "logreg", "gbm", "ensemble", "market"]
    h = res["hyperparams"]
    b = res["blocks"]
    txt = f"""# Model evaluation report

_Generated {res['generated_at'][:16].replace('T', ' ')} UTC by `python -m model.evaluate`._

## Protocol

* **Walk-forward by season.** For each evaluated season every learner is trained only on
  earlier seasons (from {season_label(FIRST_TRAIN_SEASON)}). Dixon-Coles ratings are refit every Monday and
  Thursday using only matches before that date. Features use only pre-kickoff information.
* **Validation** ({b['validation']['seasons'][0]} to {b['validation']['seasons'][-1]}, {b['validation']['n']} matches) was used for all choices:
  Elo K / home advantage / off-season regression, Dixon-Coles time decay / shrinkage /
  promoted-club prior, the gradient boosting and logistic regression settings, and the
  ensemble weights.
* **Test** ({b['test']['seasons'][0]} to {b['test']['seasons'][-1]}, {b['test']['n']} matches) was scored once with those fixed choices.
* Bookmaker baseline: market-average decimal odds collected by football-data.co.uk before
  the round (not closing odds), margin removed by proportional normalisation. All models are
  scored on the same matches (those with market odds).

Lower is better for log loss, Brier (multi-class, 0-2) and RPS (0-1).

## Test seasons ({b['test']['seasons'][0]} to {b['test']['seasons'][-1]})

{_fmt_table(b['test']['metrics'], order)}

Against **closing** odds (sharper; available from 2019-20, n = {b['test']['closing_subset']['n']}):

{_fmt_table(b['test']['closing_subset']['metrics'], ['ensemble', 'market', 'market_close'])}

## Validation seasons ({b['validation']['seasons'][0]} to {b['validation']['seasons'][-1]})

{_fmt_table(b['validation']['metrics'], order)}

## {b['current']['seasons'][0]} so far (n = {b['current']['n']}, out-of-sample, models trained before the season)

{_fmt_table(b['current']['metrics'], order)}

Small sample: one unusual weekend moves these numbers a lot.

## Chosen settings

* Elo: K = {h['elo']['k']}, home advantage = {h['elo']['home_adv']}, off-season regression = {h['elo']['season_regression']}
* Dixon-Coles: time decay xi = {h['dc']['xi']} per day, ridge = {h['dc']['ridge']}, promoted-club prior = {h['dc']['promoted_attack']}
* Gradient boosting: {h['gbm']}
* Logistic regression: C = {h['logreg_c']}
* Ensemble weights: {', '.join(f'{k} {v:.2f}' for k, v in h['ensemble_weights'].items())}

## Per season

| Season | n | Elo | Dixon-Coles | GBM | Ensemble | Market |
|---|---:|---:|---:|---:|---:|---:|
""" + "\n".join(
        f"| {r['season']} | {r['n']} | " + " | ".join(f"{r['metrics'][k]['log_loss']:.4f}" for k in ('elo', 'dc', 'gbm', 'ensemble', 'market')) + " |"
        for r in res["per_season"]) + "\n\n_(log loss)_\n"
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(txt + LEARNINGS_PLACEHOLDER)


LEARNINGS_PLACEHOLDER = "\n## What we learned\n\nSee [evaluation-notes.md](evaluation-notes.md) for the discussion, honesty notes and limitations.\n"


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = evaluate(db.connect())
    print(json.dumps(res["blocks"], indent=1))
