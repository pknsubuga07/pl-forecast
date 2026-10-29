"""Predictions for upcoming fixtures with scorelines, confidence, explanation and market view."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import dixon_coles as dc
from . import features as F
from .explain import explain
from .metrics import implied_probs
from .train import load_hyperparams, load_model, param_objects

log = logging.getLogger(__name__)

MARKET_PREFERENCE = ["avg", "b365", "draftkings"]
MARKET_LABELS = {"avg": "Market average (football-data.co.uk)", "b365": "Bet365 (football-data.co.uk)",
                 "draftkings": "DraftKings (via ESPN)"}
DISAGREE_THRESHOLD = 0.10


def confidence(p: np.ndarray) -> str:
    """high / medium / low from the top probability and its gap to the runner-up."""
    s = np.sort(p)[::-1]
    top, gap = s[0], s[0] - s[1]
    if top >= 0.60 or gap >= 0.30:
        return "high"
    if top >= 0.45 or gap >= 0.15:
        return "medium"
    return "low"


def adjust_matrix(m: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rescale a Dixon-Coles score matrix so its home/draw/away totals equal the ensemble's."""
    out = m.copy()
    regions = [np.tril(np.ones_like(m), -1) > 0, np.eye(len(m)) > 0, np.triu(np.ones_like(m), 1) > 0]
    for region, t in zip(regions, target):
        s = out[region].sum()
        if s > 0:
            out[region] *= t / s
    return out / out.sum()


def latest_market(conn, match_ids: list[str]) -> dict[str, dict]:
    if not match_ids:
        return {}
    q = f"SELECT * FROM odds WHERE match_id IN ({','.join('?' * len(match_ids))})"
    o = pd.read_sql_query(q, conn, params=match_ids)
    out = {}
    for mid, g in o.groupby("match_id"):
        g = g.set_index("bookmaker")
        for book in MARKET_PREFERENCE:
            if book in g.index:
                r = g.loc[book]
                p = implied_probs([r["odds_h"]], [r["odds_d"]], [r["odds_a"]])[0]
                out[mid] = {"source": book, "label": MARKET_LABELS[book], "fetched_at": r["fetched_at"],
                            "odds": [float(r["odds_h"]), float(r["odds_d"]), float(r["odds_a"])],
                            "p": [float(x) for x in p],
                            "overround": float(1 / r["odds_h"] + 1 / r["odds_d"] + 1 / r["odds_a"] - 1)}
                break
    return out


def predict_upcoming(conn, now: pd.Timestamp | None = None, gameweeks: int = 3) -> tuple[list[dict], F.FeatureSet, dict]:
    now = now or pd.Timestamp.now(tz="UTC")
    h = load_hyperparams()
    elo_p, dc_p = param_objects(h)
    ens = load_model()
    manifest = ens.meta
    fs = F.build(conn, now=now, elo_params=elo_p, dc_params=dc_p)
    fr = fs.frame
    up = fr[(fr["status"] == "SCHEDULED") & (fr["kickoff"] > now) & fr["gameweek"].notna()]
    gws = sorted(up["gameweek"].unique())[:gameweeks]
    up = up[up["gameweek"].isin(gws)].copy()
    if up.empty:
        log.warning("No upcoming fixtures to predict")
        return [], fs, manifest

    # Live Dixon-Coles fit for full score matrices.
    m_all = F.load_matches(conn)
    e0 = m_all[m_all["div"] == "E0"]
    fin = e0[(e0["status"] == "FINISHED") & e0["fthg"].notna()]
    season = int(up["season"].max())
    dcm = dc.fit(fin, now.floor("D"), dc_p, promoted=F.promoted_sets(e0).get(season, set()))

    names = dict(conn.execute("SELECT team_id, name FROM teams").fetchall())
    market = latest_market(conn, up["match_id"].tolist())
    probs = ens.predict(up)
    comps = ens.components(up)
    out = []
    for i, (idx, r) in enumerate(up.iterrows()):
        p = probs[i]
        row = up.loc[[idx]]
        mat = adjust_matrix(dcm.score_matrix(r["home_id"], r["away_id"]), p)
        g = np.arange(mat.shape[0])
        xg_h, xg_a = float((mat.sum(axis=1) * g).sum()), float((mat.sum(axis=0) * g).sum())
        flat = [(mat[a, b], f"{a}-{b}") for a in range(6) for b in range(6)]
        flat.sort(reverse=True)
        ex = explain(ens, row, manifest["neutral_values"], names[r["home_id"]], names[r["away_id"]])
        mk = market.get(r["match_id"])
        diff = [float(p[j] - mk["p"][j]) for j in range(3)] if mk else None
        out.append({
            "match_id": r["match_id"], "season": int(r["season"]), "gameweek": int(r["gameweek"]),
            "kickoff_utc": r["kickoff_utc"], "home_id": r["home_id"], "away_id": r["away_id"],
            "model_version": manifest["version"],
            "p_home": round(float(p[0]), 4), "p_draw": round(float(p[1]), 4), "p_away": round(float(p[2]), 4),
            "xg_home": round(xg_h, 2), "xg_away": round(xg_a, 2),
            "predicted": ["H", "D", "A"][int(np.argmax(p))],
            "confidence": confidence(p),
            "top_scores": [{"score": s, "p": round(float(v), 4)} for v, s in flat[:5]],
            "score_grid": [[round(float(mat[a, b]), 4) for b in range(6)] for a in range(6)],
            "components": {k: [round(float(x), 4) for x in v[i]] for k, v in comps.items()},
            "weights": ens.weights,
            "explanation": ex["text"],
            "factors": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()} for f in ex["factors"]],
            "market": mk,
            "market_source": mk["source"] if mk else None,
            "market_p_home": round(mk["p"][0], 4) if mk else None,
            "market_p_draw": round(mk["p"][1], 4) if mk else None,
            "market_p_away": round(mk["p"][2], 4) if mk else None,
            "market_diff": [round(d, 4) for d in diff] if diff else None,
            "disagreement": bool(diff and max(abs(d) for d in diff) >= DISAGREE_THRESHOLD),
            "inputs": {c: (None if pd.isna(r[c]) else round(float(r[c]), 3)) for c in F.FEATURES},
        })
    return out, fs, manifest
