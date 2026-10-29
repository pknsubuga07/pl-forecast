"""Walk-forward evaluation for NBA / NFL (same protocol as the Premier League model).

Validation seasons pick Elo settings, regularisation and ensemble weights; test seasons are
scored once. Each season is predicted by models trained only on earlier seasons. Ties (NFL,
about 0.2% of games) are excluded from the win-probability metrics.

Run: python -m model.us_evaluate nfl   |   python -m model.us_evaluate nba
"""
from __future__ import annotations

import itertools
import json
import logging
import sys
from dataclasses import asdict

import numpy as np
import pandas as pd
from scipy.stats import norm

from pipeline import db
from pipeline.config import ARTIFACTS_DIR, LEDGER_DIR, ROOT

from . import us_features as U
from .us_models import (GBMParams, binary_calibration, binary_metrics, fit_margin, make_elo_lr, make_gbm,
                        make_ridge, market_home_prob)

log = logging.getLogger(__name__)
LABELS = {
    "home": "Always home team (base rate)",
    "elo": "Elo (logistic on rating gap)",
    "margin": "Margin model (ridge regression)",
    "gbm": "Gradient boosting",
    "ensemble": "Ensemble (final model)",
    "market": "Bookmaker moneyline (margin removed)",
}
GBM_GRID = [
    GBMParams(learning_rate=0.03, max_iter=200, max_depth=2, min_samples_leaf=100),
    GBMParams(learning_rate=0.05, max_iter=300, max_depth=1, min_samples_leaf=100),
    GBMParams(learning_rate=0.02, max_iter=300, max_depth=3, min_samples_leaf=200, l2_regularization=3.0),
]
# NFL was evaluated first with [1, 10, 100]; it is not re-tuned after seeing its test results.
ALPHAS = {"nfl": [1.0, 10.0, 100.0], "nba": [10.0, 100.0, 1000.0]}


def label_season(sport: str, s: int) -> str:
    return str(s) if sport == "nfl" else f"{s}-{str(s + 1)[-2:]}"


def market_table(conn, sport: str) -> pd.DataFrame:
    o = pd.read_sql_query("SELECT o.* FROM us_odds o JOIN us_games g USING (game_id) WHERE g.sport = ?", conn, params=(sport,))
    pref = {"nflverse": 0, "espn-core": 1}
    o["rank"] = o["source"].map(pref).fillna(2)
    o = o.sort_values("rank").drop_duplicates("game_id").set_index("game_id")
    o["mk_p"] = market_home_prob(o["home_ml"], o["away_ml"])
    return o


def elo_wf(frame: pd.DataFrame, seasons) -> pd.Series:
    out = []
    for s in seasons:
        tr = frame[(frame["season"] < s) & (frame["y"] >= 0)]
        te = frame[(frame["season"] == s) & (frame["y"] >= 0)]
        lr = make_elo_lr().fit(tr[["elo_diff", "neutral"]], tr["y"])
        out.append(pd.Series(lr.predict_proba(te[["elo_diff", "neutral"]])[:, 1], index=te.index))
    return pd.concat(out)


def wf(frame: pd.DataFrame, feats: list[str], seasons, kind: str, param) -> pd.DataFrame:
    """Walk-forward predictions. Returns p (home win) and, for the margin model, margin and total."""
    rows = []
    for s in seasons:
        tr = frame[(frame["season"] < s) & (frame["status"] == "FINISHED")]
        trb = tr[tr["y"] >= 0]
        te = frame[(frame["season"] == s) & (frame["status"] == "FINISHED")]
        if kind == "margin":
            m = fit_margin(tr[feats], tr["margin"], param)
            tot = make_ridge(param).fit(tr[feats], tr["total"])
            rows.append(pd.DataFrame({"p": m.prob(te[feats]), "pred_margin": m.margin(te[feats]),
                                      "pred_total": tot.predict(te[feats]), "sigma": m.sigma}, index=te.index))
        elif kind == "gbm":
            g = make_gbm(param).fit(trb[feats], trb["y"])
            rows.append(pd.DataFrame({"p": g.predict_proba(te[feats])[:, 1]}, index=te.index))
        elif kind == "home":
            rows.append(pd.DataFrame({"p": np.full(len(te), trb["y"].mean())}, index=te.index))
    return pd.concat(rows)


def evaluate(conn, sport: str) -> dict:
    cfg = U.CONFIGS[sport]
    feats = U.feature_list(sport)
    games = U.load_games(conn, sport)
    valid, test = list(cfg.validation), list(cfg.test)
    cur = int(games["season"].max())

    # 1. Elo settings on validation.
    best, best_loss = None, np.inf
    for k, hfa, reg in itertools.product(cfg.elo_grid["k"], cfg.elo_grid["home_adv"], cfg.elo_grid["season_regression"]):
        p = U.EloParams(k=k, home_adv=hfa, season_regression=reg)
        fr = U.build(None, cfg, p, games=games).frame
        pv = elo_wf(fr, valid)
        loss = binary_metrics(pv, fr.loc[pv.index, "y"])["log_loss"]
        log.info("%s elo k=%s hfa=%s reg=%s -> %.5f", sport, k, hfa, reg, loss)
        if loss < best_loss:
            best, best_loss = p, loss
    elo_p = best
    frame = U.build(None, cfg, elo_p, games=games).frame
    vy = frame.loc[frame["season"].isin(valid) & (frame["y"] >= 0), "y"]

    # 2. Ridge strength and GBM settings on validation.
    def vloss(df):
        return binary_metrics(df.loc[vy.index, "p"], vy)["log_loss"]
    alpha = min(ALPHAS[sport], key=lambda a: vloss(wf(frame, feats, valid, "margin", a)))
    gbm_p = min(GBM_GRID, key=lambda g: vloss(wf(frame, feats, valid, "gbm", g)))
    log.info("%s ridge alpha=%s gbm=%s", sport, alpha, gbm_p)

    seasons = valid + test + ([cur] if cur not in test else [])
    preds = {"home": wf(frame, feats, seasons, "home", None)["p"],
             "elo": elo_wf(frame, seasons),
             "gbm": wf(frame, feats, seasons, "gbm", gbm_p)["p"]}
    mdf = wf(frame, feats, seasons, "margin", alpha)
    preds["margin"] = mdf["p"]

    # 3. Ensemble weights on validation.
    names = ["elo", "margin", "gbm"]
    best_w, best_loss = None, np.inf
    for w in itertools.product(np.arange(0, 1.01, 0.05), repeat=2):
        if sum(w) > 1 + 1e-9:
            continue
        ws = dict(zip(names, [round(w[0], 2), round(w[1], 2), round(1 - sum(w), 2)]))
        p = sum(ws[n] * preds[n].loc[vy.index] for n in names)
        loss = binary_metrics(p, vy)["log_loss"]
        if loss < best_loss:
            best_w, best_loss = ws, loss
    idx = preds["elo"].index
    preds["ensemble"] = sum(best_w[n] * preds[n].reindex(idx) for n in names)
    mk = market_table(conn, sport)
    preds["market"] = frame.loc[idx, "game_id"].map(mk["mk_p"]).set_axis(idx)

    def block(ss):
        rows_all = frame.index[frame["season"].isin(ss) & (frame["y"] >= 0)]
        rows_mk = rows_all[preds["market"].loc[rows_all].notna()]
        # Score everything on the games with market odds when (almost) all have them, so the
        # comparison is like-for-like; NBA validation seasons have no stored odds, so use all games.
        with_market = len(rows_mk) >= 0.9 * len(rows_all) and len(rows_mk) > 0
        rows = rows_mk if with_market else rows_all
        out = {n: binary_metrics(preds[n].loc[rows], frame.loc[rows, "y"]) for n in LABELS if n != "market" or with_market}
        # Point spread / total accuracy against the market's lines.
        sp = mk.reindex(frame.loc[rows, "game_id"]).set_axis(rows)
        ok = sp["home_spread"].notna()
        actual = frame.loc[rows, "margin"]
        ens_margin = pd.Series(np.asarray(mdf.loc[rows, "sigma"]) * norm.ppf(np.clip(preds["ensemble"].loc[rows], 1e-6, 1 - 1e-6)), index=rows)
        spread = {"n": int(ok.sum()),
                  "model_mae": float((ens_margin[ok] - actual[ok]).abs().mean()) if ok.any() else None,
                  "market_mae": float((-sp.loc[ok, "home_spread"] - actual[ok]).abs().mean()) if ok.any() else None}
        okt = sp["total"].notna()
        tot = frame.loc[rows, "total"]
        totals = {"n": int(okt.sum()),
                  "model_mae": float((mdf.loc[rows[okt], "pred_total"] - tot[okt]).abs().mean()) if okt.any() else None,
                  "market_mae": float((sp.loc[okt, "total"] - tot[okt]).abs().mean()) if okt.any() else None}
        return {"seasons": [label_season(sport, s) for s in ss], "n": int(len(rows)), "metrics": out,
                "market_coverage": round(len(rows_mk) / max(len(rows_all), 1), 3),
                "spread": spread, "totals": totals}

    blocks = {"validation": block(valid), "test": block(test)}
    if cur not in test:
        blocks["current"] = block([cur])
    per_season = [{"season": label_season(sport, s), **block([s])} for s in seasons]
    test_rows = frame.index[frame["season"].isin(test) & (frame["y"] >= 0)]
    calib = {n: binary_calibration(preds[n].loc[test_rows].dropna(), frame.loc[preds[n].loc[test_rows].dropna().index, "y"])
             for n in ("ensemble", "market")}
    hyper = {"elo": asdict(elo_p), "ridge_alpha": alpha, "gbm": asdict(gbm_p), "ensemble_weights": best_w,
             "validation_seasons": valid, "test_seasons": test}
    out_dir = ARTIFACTS_DIR / sport
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hyperparams.json").write_text(json.dumps(hyper, indent=2))
    res = {"sport": sport, "generated_at": pd.Timestamp.now(tz="UTC").isoformat(), "labels": LABELS, "hyperparams": hyper,
           "blocks": blocks, "per_season": per_season, "calibration_test": calib}
    (out_dir / "evaluation.json").write_text(json.dumps(res, indent=2))

    # Retroactive backtest for the current season (labelled as such on the history page).
    curf = frame[(frame["season"] == cur) & (frame["status"] == "FINISHED")]
    pd.DataFrame({"game_id": curf["game_id"], "p_home": preds["ensemble"].reindex(curf.index).round(5),
                  "pred_margin": (mdf["sigma"].reindex(curf.index) * norm.ppf(
                      np.clip(preds["ensemble"].reindex(curf.index), 1e-6, 1 - 1e-6))).round(2),
                  "pred_total": mdf["pred_total"].reindex(curf.index).round(1)}
                 ).dropna().to_csv(LEDGER_DIR / f"{sport}_backtest_current_season.csv", index=False)
    write_report(res)
    return res


def write_report(res: dict) -> None:
    sport = res["sport"]
    order = ["home", "elo", "margin", "gbm", "ensemble", "market"]

    def table(m):
        lines = ["| Model | Log loss | Brier | Accuracy |", "|---|---:|---:|---:|"]
        lines += [f"| {LABELS[n]} | {m[n]['log_loss']:.4f} | {m[n]['brier']:.4f} | {m[n]['accuracy']:.1%} |" for n in order if n in m]
        if "market" not in m:
            lines.append("| Bookmaker moneyline | (no stored odds for these seasons) | | |")
        return "\n".join(lines)

    def lines(b):
        s, t = b["spread"], b["totals"]
        out = []
        if s["n"]:
            out.append(f"* Margin error (MAE, points): model {s['model_mae']:.2f} vs bookmaker spread {s['market_mae']:.2f} (n = {s['n']})")
        if t["n"]:
            out.append(f"* Total points error (MAE): model {t['model_mae']:.2f} vs bookmaker total {t['market_mae']:.2f} (n = {t['n']})")
        return "\n".join(out)

    b = res["blocks"]
    h = res["hyperparams"]
    txt = f"""# {sport.upper()} model evaluation

_Generated {res['generated_at'][:16].replace('T', ' ')} UTC by `python -m model.us_evaluate {sport}`._

Walk-forward by season: each season is predicted by models trained only on earlier seasons.
Settings were chosen on the validation seasons; the test seasons were scored once. All rows
are games with a bookmaker moneyline; ties are excluded.

## Test seasons ({b['test']['seasons'][0]} to {b['test']['seasons'][-1]}, n = {b['test']['n']})

{table(b['test']['metrics'])}

{lines(b['test'])}

## Validation seasons ({b['validation']['seasons'][0]} to {b['validation']['seasons'][-1]}, n = {b['validation']['n']})

{table(b['validation']['metrics'])}
"""
    if "current" in b:
        txt += f"\n## {b['current']['seasons'][0]} so far (n = {b['current']['n']})\n\n{table(b['current']['metrics'])}\n"
    txt += f"""
## Chosen settings

* Elo: K = {h['elo']['k']}, home advantage = {h['elo']['home_adv']}, off-season regression = {h['elo']['season_regression']}
* Ridge alpha = {h['ridge_alpha']}; gradient boosting {h['gbm']}
* Ensemble weights: {', '.join(f'{k} {v:.2f}' for k, v in h['ensemble_weights'].items())}

## Per season (log loss)

| Season | n | Elo | Margin | GBM | Ensemble | Market |
|---|---:|---:|---:|---:|---:|---:|
""" + "\n".join(f"| {r['season']} | {r['n']} | " + " | ".join(f"{r['metrics'][k]['log_loss']:.4f}" if k in r["metrics"] else "–" for k in ("elo", "margin", "gbm", "ensemble", "market")) + " |"
                for r in res["per_season"]) + "\n"
    (ROOT / "docs" / f"evaluation_{sport}.md").write_text(txt)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    r = evaluate(db.connect(), sys.argv[1])
    print(json.dumps({k: {"n": v["n"], **{m: round(x["log_loss"], 4) for m, x in v["metrics"].items()},
                          "spread": v["spread"], "totals": v["totals"]} for k, v in r["blocks"].items()}, indent=1))
