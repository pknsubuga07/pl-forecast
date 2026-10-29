"""Train, save and apply the NBA / NFL production models.

  python -m model.us_predict train nfl     # refit on every finished game, save a new version
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
import platform
import sys

import numpy as np
import pandas as pd
import sklearn

from pipeline.config import ARTIFACTS_DIR

from . import us_features as U
from .us_models import (GBMParams, USEnsemble, american_to_prob, fit_margin, make_elo_lr, make_gbm, make_ridge,
                        market_home_prob)

def poss(name: str) -> str:
    """English possessive: "Arsenal's", "Green Bay Packers'"."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


log = logging.getLogger(__name__)
DISAGREE = 0.10
MARKET_PREFERENCE = ["nflverse", "draftkings", "espn bet", "espn-core"]
MARKET_LABEL = {"nflverse": "Closing line (nflverse)", "draftkings": "DraftKings (via ESPN)", "espn bet": "ESPN BET",
                "espn-core": "ESPN odds"}


def _dir(sport):
    return ARTIFACTS_DIR / sport


def hyperparams(sport: str) -> dict:
    path = _dir(sport) / "hyperparams.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run `python -m model.us_evaluate {sport}` first")
    return json.loads(path.read_text())


def train(conn, sport: str, now: pd.Timestamp | None = None) -> str:
    now = now or pd.Timestamp.now(tz="UTC")
    cfg, h = U.CONFIGS[sport], hyperparams(sport)
    feats = U.feature_list(sport)
    fs = U.build(conn, cfg, U.EloParams(**h["elo"]), now=now)
    fin = fs.frame[fs.frame["status"] == "FINISHED"]
    binary = fin[fin["y"] >= 0]
    ens = USEnsemble(
        sport=sport, features=feats, weights=h["ensemble_weights"],
        elo_lr=make_elo_lr().fit(binary[["elo_diff", "neutral"]], binary["y"]),
        margin=fit_margin(fin[feats], fin["margin"], h["ridge_alpha"]),
        total=make_ridge(h["ridge_alpha"]).fit(fin[feats], fin["total"]),
        gbm=make_gbm(GBMParams(**h["gbm"])).fit(binary[feats], binary["y"]),
    )
    fp = hashlib.sha256("\n".join(sorted(fin["game_id"] + fin["margin"].astype(str))).encode()).hexdigest()[:6]
    version = f"v{now.strftime('%Y%m%d')}-{fp}"
    ens.meta = {"version": version, "sport": sport, "trained_at": now.isoformat(), "n_train": int(len(fin)),
                "train_from": fin["kickoff_utc"].min(), "train_to": fin["kickoff_utc"].max(), "hyperparams": h,
                "features": feats, "neutral_values": {c: float(np.nanmean(fin[c])) for c in feats},
                "python": platform.python_version(), "sklearn": sklearn.__version__}
    out = _dir(sport) / version
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "model.pkl", "wb") as f:
        pickle.dump(ens, f)
    (out / "manifest.json").write_text(json.dumps(ens.meta, indent=2))
    (_dir(sport) / "LATEST").write_text(version + "\n")
    log.info("Saved %s model %s (%d games)", sport, version, len(fin))
    return version


def load_model(sport: str) -> USEnsemble:
    version = (_dir(sport) / "LATEST").read_text().strip()
    with open(_dir(sport) / version / "model.pkl", "rb") as f:
        return pickle.load(f)


# --------------------------------------------------------------------------- explanations
GROUPS = {
    "ratings": ["elo_home", "elo_away", "elo_diff"],
    "recent_form": ["margin_s_h", "margin_s_a", "margin_l_h", "margin_l_a"],
    "scoring": ["pf_l_h", "pf_l_a", "pa_l_h", "pa_l_a"],
    "venue_form": ["venue_margin_h", "venue_margin_a"],
    "record": ["std_winpct_h", "std_winpct_a", "std_margin_h", "std_margin_a"],
    "rest": ["rest_h", "rest_a", "b2b_h", "b2b_a"],
    "qb": ["qb_change_h", "qb_change_a"],
}
GROUP_LABELS = {"ratings": "Elo strength rating", "recent_form": "Recent point differential", "scoring": "Points scored / allowed",
                "venue_form": "Home / road form", "record": "Season record", "rest": "Rest & back-to-backs",
                "qb": "Quarterback change"}


def neutralise(x: pd.DataFrame, group: str, neutral: dict) -> pd.DataFrame:
    x = x.copy()
    if group == "ratings":
        m = (x["elo_home"] + x["elo_away"]) / 2
        x["elo_home"], x["elo_away"], x["elo_diff"] = m, m, 0.0
    elif group == "venue_form":
        for c in GROUPS[group]:
            x[c] = neutral.get(c, np.nan)
    elif group in ("qb",):
        x["qb_change_h"], x["qb_change_a"] = 0, 0
    else:
        for c in GROUPS[group]:
            if c.endswith("_h") and c in x.columns:
                pair = c[:-2] + "_a"
                m = x[[c, pair]].mean(axis=1)
                x[c], x[pair] = m, m
    return x


def _fmt(v, f="{:+.1f}"):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f.format(v)


def phrase(group, fav_home, r, home, away, sport) -> str:
    team, other = (home, away) if fav_home else (away, home)
    s, o = ("h", "a") if fav_home else ("a", "h")
    if group == "ratings":
        mine, theirs = (r["elo_home"], r["elo_away"]) if fav_home else (r["elo_away"], r["elo_home"])
        if mine >= theirs:
            return f"{poss(team)} higher Elo rating ({mine:.0f} vs {theirs:.0f})"
        return f"{poss(team)} rating once home advantage is counted"
    if group == "recent_form":
        n = U.CONFIGS[sport].windows[0]
        return f"{poss(team)} recent point differential ({_fmt(r[f'margin_s_{s}'])} vs {_fmt(r[f'margin_s_{o}'])} per game over the last {n})"
    if group == "scoring":
        return (f"{poss(team)} recent scoring ({_fmt(r[f'pf_l_{s}'], '{:.1f}')}–{_fmt(r[f'pa_l_{s}'], '{:.1f}')} points per game "
                f"vs {_fmt(r[f'pf_l_{o}'], '{:.1f}')}–{_fmt(r[f'pa_l_{o}'], '{:.1f}')})")
    if group == "venue_form":
        return (f"{poss(home)} home form ({_fmt(r['venue_margin_h'])} average margin at home)" if fav_home
                else f"{poss(away)} road form ({_fmt(r['venue_margin_a'])} average margin away)")
    if group == "record":
        ws, wo = r.get(f"std_winpct_{s}"), r.get(f"std_winpct_{o}")
        if ws is not None and wo is not None and not np.isnan(ws) and not np.isnan(wo) and ws > wo:
            return f"{poss(team)} better season record ({ws:.0%} vs {wo:.0%} wins)"
        # Win % says otherwise (or is level): it is the season point margin doing the work.
        return f"{poss(team)} better point margin this season ({_fmt(r.get(f'std_margin_{s}'))} vs {_fmt(r.get(f'std_margin_{o}'))} per game)"
    if group == "rest":
        if sport == "nba" and r.get(f"b2b_{o}") == 1 and r.get(f"b2b_{s}") != 1:
            return f"{other} playing the second night of a back-to-back"
        return f"{team} having more rest ({r[f'rest_{s}']:.1f} vs {r[f'rest_{o}']:.1f} days)"
    if group == "qb":
        return f"{other} starting a different quarterback than usual"
    return group


def explain(ens: USEnsemble, row: pd.DataFrame, home: str, away: str) -> dict:
    p = float(ens.predict(row)[0])
    fav_is_home = p >= 0.5
    neutral = ens.meta["neutral_values"]
    groups = [g for g in GROUPS if all(c in row.columns for c in GROUPS[g]) or g == "rest"]
    groups = [g for g in groups if not (g == "qb" and ens.sport != "nfl")]
    r = row.iloc[0]
    items = []
    for g in groups:
        d = p - float(ens.predict(neutralise(row, g, neutral))[0])  # change in P(home win)
        items.append({"group": g, "label": GROUP_LABELS[g], "effect_home": round(d, 4), "favours": "home" if d > 0 else "away",
                      "text": phrase(g, d > 0, r, home, away, ens.sport)})
    items.sort(key=lambda x: -abs(x["effect_home"]))
    toward = [i for i in items if (i["effect_home"] > 0.01) == fav_is_home and abs(i["effect_home"]) > 0.01][:2]
    against = [i for i in items if (i["effect_home"] > 0.01) != fav_is_home and abs(i["effect_home"]) > 0.01][:1]
    fav = home if fav_is_home else away
    if toward:
        lead = " and ".join(i["text"] for i in toward)
        text = f"{lead[0].upper()}{lead[1:]} {'drive' if len(toward) > 1 else 'drives'} most of this prediction towards {fav}."
        if against:
            text += f" {against[0]['text'][0].upper()}{against[0]['text'][1:]} pulls the other way."
    elif fav_is_home and not r.get("neutral"):
        text = f"The teams are closely matched on the model's inputs, so home advantage tips it towards {home}."
    else:
        text = f"No single factor stands out; the combined inputs lean slightly towards {fav}."
    return {"text": text, "factors": items}


# --------------------------------------------------------------------------- prediction
def confidence(p_home: float) -> str:
    top = max(p_home, 1 - p_home)
    return "high" if top >= 0.75 else "medium" if top >= 0.62 else "low"


def latest_market(conn, game_ids: list[str]) -> dict[str, dict]:
    if not game_ids:
        return {}
    o = pd.read_sql_query(f"SELECT * FROM us_odds WHERE game_id IN ({','.join('?' * len(game_ids))})", conn, params=game_ids)
    o["rank"] = o["source"].map({s: i for i, s in enumerate(MARKET_PREFERENCE)}).fillna(len(MARKET_PREFERENCE))
    out = {}
    for gid, g in o.sort_values("rank").groupby("game_id"):
        r = g.iloc[0]
        ph = float(market_home_prob(r["home_ml"], r["away_ml"]))
        out[gid] = {"source": r["source"], "label": MARKET_LABEL.get(r["source"], r["source"]),
                    "home_ml": float(r["home_ml"]), "away_ml": float(r["away_ml"]), "p_home": ph,
                    "spread_home": None if pd.isna(r["home_spread"]) else float(r["home_spread"]),
                    "total": None if pd.isna(r["total"]) else float(r["total"]),
                    "overround": float(american_to_prob(r["home_ml"]) + american_to_prob(r["away_ml"]) - 1),
                    "fetched_at": r["fetched_at"]}
    return out


def predict_upcoming(conn, sport: str, now: pd.Timestamp | None = None):
    now = now or pd.Timestamp.now(tz="UTC")
    cfg = U.CONFIGS[sport]
    ens = load_model(sport)
    fs = U.build(conn, cfg, U.EloParams(**ens.meta["hyperparams"]["elo"]), now=now.floor("h"))
    fr = fs.frame
    up = fr[(fr["status"] == "SCHEDULED") & (fr["kickoff"] > now) &
            (fr["kickoff"] <= now + pd.Timedelta(days=cfg.upcoming_days))].copy()
    if up.empty:
        return [], fs, ens.meta
    names = dict(conn.execute("SELECT team_id, name FROM us_teams").fetchall())
    p = ens.predict(up)
    margin = ens.predict_margin(up)
    total = ens.predict_total(up)
    comps = ens.components(up)
    market = latest_market(conn, up["game_id"].tolist())
    out = []
    for i, (idx, r) in enumerate(up.iterrows()):
        ex = explain(ens, up.loc[[idx]], names[r["home_id"]], names[r["away_id"]])
        mk = market.get(r["game_id"])
        hs, as_ = (total[i] + margin[i]) / 2, (total[i] - margin[i]) / 2
        out.append({
            "game_id": r["game_id"], "sport": sport, "season": int(r["season"]),
            "week": None if pd.isna(r["week"]) else int(r["week"]), "playoff": bool(r["playoff"]),
            "kickoff_utc": r["kickoff_utc"], "home_id": r["home_id"], "away_id": r["away_id"],
            "neutral": bool(r["neutral"]), "model_version": ens.meta["version"],
            "p_home": round(float(p[i]), 4), "p_away": round(1 - float(p[i]), 4),
            "pred_margin": round(float(margin[i]), 1), "pred_total": round(float(total[i]), 1),
            "pred_home_score": round(float(hs), 1), "pred_away_score": round(float(as_), 1),
            "predicted": "H" if p[i] >= 0.5 else "A", "confidence": confidence(float(p[i])),
            "components": {k: round(float(v[i]), 4) for k, v in comps.items()}, "weights": ens.weights,
            "explanation": ex["text"], "factors": ex["factors"],
            "market": mk, "market_source": mk["source"] if mk else None,
            "market_p_home": round(mk["p_home"], 4) if mk else None,
            "market_spread_home": mk["spread_home"] if mk else None, "market_total": mk["total"] if mk else None,
            "disagreement": bool(mk and abs(float(p[i]) - mk["p_home"]) >= DISAGREE),
            "home_qb": r.get("home_qb"), "away_qb": r.get("away_qb"),
            "inputs": {c: (None if pd.isna(r[c]) else round(float(r[c]), 3)) for c in ens.features},
        })
    return out, fs, ens.meta


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from pipeline import db
    if sys.argv[1] == "train":
        print(train(db.connect(), sys.argv[2]))
