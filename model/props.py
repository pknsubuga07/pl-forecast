"""Player prop projections (NBA points / rebounds / assists / 3s / PRA; NFL passing, rushing and
receiving yards, receptions, anytime touchdown).

For every player and market:
  1. Projection: ridge regression of the stat on the player's recent form (last 5 / last 10 /
     season-to-date means, spread of results, minutes or usage trend), using only games strictly
     before kickoff.
  2. P(over the line): normal distribution around the projection with a spread that grows with
     the projection, then a logistic calibration fitted on the training season's real lines.
     Anytime TD uses a Poisson rate: P(at least one) = 1 - exp(-rate), also calibrated.
Train on one season's lines, test on the next: the test season is never used for fitting.

Run: python -m model.props evaluate nba | nfl
"""
from __future__ import annotations

import json
import logging
import pickle
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LogisticRegression, Ridge

from pipeline.config import ARTIFACTS_DIR

log = logging.getLogger(__name__)
MARKETS = {"nba": ["pts", "reb", "ast", "fg3m", "pra"], "nfl": ["pass_yds", "rush_yds", "rec_yds", "rec", "anytime_td"]}
LABELS = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "3-pointers made", "pra": "Points + rebounds + assists",
          "pass_yds": "Passing yards", "rush_yds": "Rushing yards", "rec_yds": "Receiving yards", "rec": "Receptions",
          "anytime_td": "Anytime touchdown"}
USAGE = {"nba": "minutes", "nfl": None}
NFL_USAGE = {"pass_yds": "pass_att", "rush_yds": "carries", "rec_yds": "targets", "rec": "targets", "anytime_td": "touches"}
TRAIN_SEASON, TEST_SEASONS = 2024, (2025, 2026)
OUT = {"Out", "Injured Reserve", "Doubtful", "Suspension"}


def american_prob(x) -> np.ndarray:
    x = np.asarray(x, float)
    return np.where(x < 0, -x / (-x + 100), 100 / (x + 100))


def american_decimal(x) -> np.ndarray:
    x = np.asarray(x, float)
    return np.where(x < 0, 1 + 100 / -x, 1 + x / 100)


def stat_value(df: pd.DataFrame, market: str) -> pd.Series:
    if market == "pra":
        return df["pts"] + df["reb"] + df["ast"]
    if market == "anytime_td":
        return df["tds"]
    return df[market]


def player_games(conn, sport: str) -> pd.DataFrame:
    pg = pd.read_sql_query(
        "SELECT p.*, g.season, g.home_id, g.away_id FROM us_player_games p JOIN us_games g USING (game_id) WHERE p.sport = ?",
        conn, params=(sport,))
    pg["kickoff"] = pd.to_datetime(pg["kickoff_utc"], utc=True)
    if sport == "nfl":
        pg["touches"] = pg["carries"] + pg["targets"]
    return pg.sort_values(["athlete_id", "kickoff"]).reset_index(drop=True)


def market_states(pg: pd.DataFrame, sport: str, market: str) -> pd.DataFrame:
    """Per player, rolling form *after* each game (joined strictly before later kickoffs)."""
    v = stat_value(pg, market).astype(float)
    use_col = USAGE[sport] or NFL_USAGE[market]
    use = pg[use_col].astype(float)
    g = pd.DataFrame({"athlete_id": pg["athlete_id"], "kickoff": pg["kickoff"], "season": pg["season"], "v": v, "u": use})
    grp = g.groupby("athlete_id", group_keys=False)
    s = g[["athlete_id", "kickoff"]].copy()
    s["l5"] = grp["v"].apply(lambda x: x.rolling(5, min_periods=1).mean())
    s["l10"] = grp["v"].apply(lambda x: x.rolling(10, min_periods=1).mean())
    s["l20"] = grp["v"].apply(lambda x: x.rolling(20, min_periods=1).mean())
    s["sd20"] = grp["v"].apply(lambda x: x.rolling(20, min_periods=3).std())
    s["u5"] = grp["u"].apply(lambda x: x.rolling(5, min_periods=1).mean())
    s["u20"] = grp["u"].apply(lambda x: x.rolling(20, min_periods=1).mean())
    s["n"] = grp.cumcount() + 1
    s["season"] = g["season"]
    s["season_mean"] = g.groupby(["athlete_id", "season"], group_keys=False)["v"].apply(lambda x: x.expanding().mean())
    s["last_kick"] = s["kickoff"]
    return s


FEATS = ["l5", "l10", "l20", "season_mean_f", "u5", "u20", "u_ratio"]


def attach(targets: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    t = targets.sort_values("kickoff").copy()
    t["_i"] = np.arange(len(t))
    s = states.sort_values("kickoff").rename(columns={"kickoff": "_sk", "season": "_ss"})
    s["kickoff"] = s["_sk"]
    t["athlete_id"] = t["athlete_id"].astype(str)
    s["athlete_id"] = s["athlete_id"].astype(str)
    j = pd.merge_asof(t, s, on="kickoff", by="athlete_id", allow_exact_matches=False, direction="backward")
    j["season_mean_f"] = j["season_mean"].where(j["_ss"] == j["season"], j["l10"])  # new season: fall back to recent form
    j["u_ratio"] = (j["u5"] / j["u20"].replace(0, np.nan)).clip(0, 2).fillna(1.0)
    j["days_since"] = (j["kickoff"] - j["last_kick"]).dt.days
    return j


@dataclass
class MarketModel:
    market: str
    ridge: Ridge
    sd_coef: tuple[float, float]       # sd = a + b * projection
    calib: LogisticRegression
    metrics: dict = field(default_factory=dict)

    def project(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(self.ridge.predict(X[FEATS].fillna(0)), 0, None)

    def z(self, X: pd.DataFrame, line: np.ndarray) -> np.ndarray:
        mu = self.project(X)
        if self.market == "anytime_td":
            return np.log(np.clip(1 - np.exp(-mu), 1e-4, 1 - 1e-4) / np.clip(np.exp(-mu), 1e-4, 1))
        sd = np.maximum(self.sd_coef[0] + self.sd_coef[1] * mu, 0.5)
        return (mu - line) / sd

    def p_over(self, X: pd.DataFrame, line: np.ndarray) -> np.ndarray:
        return self.calib.predict_proba(self.z(X, line).reshape(-1, 1))[:, 1]


def fit_market(train: pd.DataFrame, market: str) -> MarketModel:
    tr = train.dropna(subset=["actual", "l5"])
    ridge = Ridge(alpha=1.0).fit(tr[FEATS].fillna(0), tr["actual"])
    mu = np.clip(ridge.predict(tr[FEATS].fillna(0)), 0, None)
    resid = np.abs(tr["actual"] - mu)
    # Mean absolute residual ~ 0.8 sd for a normal; regress it on the projection.
    b, a = np.polyfit(mu, resid / 0.8, 1) if len(tr) > 30 else (0.0, float(np.std(tr["actual"])))
    model = MarketModel(market, ridge, (float(a), float(b)), LogisticRegression())
    y = (tr["actual"] > tr["line"]).astype(int)
    model.calib.fit(model.z(tr, tr["line"].to_numpy()).reshape(-1, 1), y)
    return model


OVER_RATE_BOUNDS = (0.40, 0.60)  # a real two-sided market lands near 50%; far outside means bad lines


def orientation(df: pd.DataFrame) -> bool:
    """True if the first listed price is the OVER. ESPN does not label the side, so this is decided
    from the training data: the favoured side should win more often than the other."""
    two = df.dropna(subset=["price_b", "actual"])
    two = two[two["market"] != "anytime_td"]
    if two.empty:
        # No prices kept (settled NFL props): use the convention measured on NBA lines, same API.
        nba = ARTIFACTS_DIR / "nba" / "props_evaluation.json"
        return json.loads(nba.read_text()).get("first_price_is_over", True) if nba.exists() else True
    fav_a = american_prob(two["price_a"]) > american_prob(two["price_b"])
    over = two["actual"] > two["line"]
    agree = (fav_a == over).mean()
    return bool(agree >= 0.5)


def prop_frame(conn, sport: str) -> pd.DataFrame:
    p = pd.read_sql_query("SELECT p.*, g.season, g.kickoff_utc, g.home_id, g.away_id, g.status FROM us_props p "
                          "JOIN us_games g USING (game_id) WHERE g.sport = ?", conn, params=(sport,))
    p["kickoff"] = pd.to_datetime(p["kickoff_utc"], utc=True)
    return p


def build_rows(conn, sport: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    pg = player_games(conn, sport)
    props = prop_frame(conn, sport)
    rows = []
    for m in MARKETS[sport]:
        t = props[props["market"] == m].copy()
        if t.empty:
            continue
        j = attach(t, market_states(pg, sport, m))
        act = pg.assign(actual=stat_value(pg, m))[["game_id", "athlete_id", "actual"]]
        act["athlete_id"] = act["athlete_id"].astype(str)
        j = j.merge(act, on=["game_id", "athlete_id"], how="left")
        rows.append(j)
    return (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()), pg


def evaluate(conn, sport: str) -> dict:
    df, _ = build_rows(conn, sport)
    df = df[df["l5"].notna()]
    a_is_over = orientation(df[df["season"] == TRAIN_SEASON])
    res = {"sport": sport, "train_season": TRAIN_SEASON, "test_seasons": list(TEST_SEASONS), "first_price_is_over": a_is_over,
           "markets": {}}
    models = {}
    for m in MARKETS[sport]:
        d = df[df["market"] == m]
        tr = d[(d["season"] == TRAIN_SEASON) & d["actual"].notna()]
        te = d[d["season"].isin(TEST_SEASONS) & d["actual"].notna() & (d["status"] == "FINISHED")]
        if len(tr) < 50 or len(te) < 20:
            res["markets"][m] = {"n_train": int(len(tr)), "n_test": int(len(te)), "note": "not enough historical lines"}
            continue
        rate = float((tr["actual"] > tr["line"]).mean())
        if m != "anytime_td" and not (OVER_RATE_BOUNDS[0] <= rate <= OVER_RATE_BOUNDS[1]):
            # Guard against mis-parsed lines (e.g. a combined market filed under a single stat).
            res["markets"][m] = {"n_train": int(len(tr)), "n_test": int(len(te)),
                                 "note": f"lines look wrong (overs hit {rate:.0%} in training); market excluded"}
            log.warning("%s %s: training over-rate %.2f outside %s, excluded", sport, m, rate, OVER_RATE_BOUNDS)
            continue
        model = fit_market(tr, m)
        models[m] = model
        p = model.p_over(te, te["line"].to_numpy())
        over = (te["actual"] > te["line"]).to_numpy()
        if m == "anytime_td" and te["price_a"].isna().all():
            base = float(tr["actual"].gt(0.5).mean())
            ll_model = float(-np.mean(np.where(over, np.log(p), np.log(1 - p))))
            ll_base = float(-np.mean(np.where(over, np.log(base), np.log(1 - base))))
            res["markets"][m] = {"label": LABELS[m], "n_train": int(len(tr)), "n_test": int(len(te)), "log_loss_model": ll_model,
                                 "log_loss_base_rate": ll_base, "note": "past prices not kept by ESPN; scored against the base rate only"}
            continue
        if m == "anytime_td":
            mk = american_prob(te["price_a"])  # one-sided price, margin included
            pick_over = p > mk
            ll_model = float(-np.mean(np.where(over, np.log(p), np.log(1 - p))))
            ll_mk = float(-np.mean(np.where(over, np.log(mk), np.log(1 - np.clip(mk, 0, 0.999)))))
            ret = np.where(pick_over, np.where(over, american_decimal(te["price_a"]) - 1, -1.0), 0.0)
            n_bets = int(pick_over.sum())
            res["markets"][m] = {"label": LABELS[m], "n_train": int(len(tr)), "n_test": int(len(te)), "log_loss_model": ll_model,
                                 "log_loss_market_with_margin": ll_mk, "bets": n_bets,
                                 "hit_rate": float(over[pick_over].mean()) if n_bets else None,
                                 "roi": float(ret[pick_over].mean()) if n_bets else None,
                                 "mae_projection": None}
            continue
        assumed = bool(te["price_b"].isna().all())
        if assumed:  # settled NFL props keep the line but not the prices: assume the standard -110 / -110
            te = te.assign(price_a=te["price_a"].fillna(-110.0), price_b=te["price_b"].fillna(-110.0))
        two = te["price_b"].notna().to_numpy()
        p_over_price = np.where(a_is_over, te["price_a"], te["price_b"])
        p_under_price = np.where(a_is_over, te["price_b"], te["price_a"])
        po, pu = american_prob(p_over_price), american_prob(p_under_price)
        mk_over = np.where(two, po / (po + pu), np.nan)
        pick_over = p >= 0.5
        hit = np.where(pick_over, over, ~over) & (te["actual"] != te["line"]).to_numpy()
        price = np.where(pick_over, p_over_price, p_under_price)
        profit = np.where(hit, american_decimal(price) - 1, -1.0)
        conf = np.abs(p - 0.5)
        strong = conf >= 0.06
        ok = two & ~np.isnan(mk_over)
        res["markets"][m] = {
            "label": LABELS[m], "n_train": int(len(tr)), "n_test": int(len(te)),
            "mae_projection": float(np.mean(np.abs(model.project(te) - te["actual"]))),
            "mae_line": float(np.mean(np.abs(te["line"] - te["actual"]))),
            "log_loss_model": float(-np.mean(np.where(over[ok], np.log(p[ok]), np.log(1 - p[ok])))),
            "log_loss_market": float(-np.mean(np.where(over[ok], np.log(mk_over[ok]), np.log(1 - mk_over[ok])))),
            "hit_rate_all": float(hit[ok].mean()), "roi_all": float(profit[ok].mean()),
            "bets_confident": int((strong & ok).sum()),
            "hit_rate_confident": float(hit[strong & ok].mean()) if (strong & ok).any() else None,
            "roi_confident": float(profit[strong & ok].mean()) if (strong & ok).any() else None,
            "over_rate_train": rate, "assumed_prices": assumed,
        }
    out = ARTIFACTS_DIR / sport
    out.mkdir(parents=True, exist_ok=True)
    (out / "props_evaluation.json").write_text(json.dumps(res, indent=2))
    # Production models: refit on everything finished (train + test seasons).
    full = {}
    for m in models:
        d = df[(df["market"] == m) & df["actual"].notna()]
        full[m] = fit_market(d, m)
    with open(out / "props_models.pkl", "wb") as f:
        pickle.dump({"models": full, "first_price_is_over": a_is_over}, f)
    return res


def confidence(p_side: float) -> str:
    return "high" if p_side >= 0.62 else "medium" if p_side >= 0.56 else "low"


def predict_upcoming(conn, sport: str, game_ids: list[str]) -> list[dict]:
    path = ARTIFACTS_DIR / sport / "props_models.pkl"
    if not path.exists() or not game_ids:
        return []
    with open(path, "rb") as f:
        bundle = pickle.load(f)
    models, a_is_over = bundle["models"], bundle["first_price_is_over"]
    pg = player_games(conn, sport)
    props = prop_frame(conn, sport)
    props = props[props["game_id"].isin(game_ids)]
    players = pd.read_sql_query("SELECT athlete_id, name, team_id, position, injury FROM us_players WHERE sport = ?",
                                conn, params=(sport,)).drop_duplicates("athlete_id").set_index("athlete_id")
    out = []
    for m, model in models.items():
        t = props[props["market"] == m]
        if t.empty:
            continue
        j = attach(t, market_states(pg, sport, m))
        j = j[j["l5"].notna() & (j["days_since"] < 120)]
        if j.empty:
            continue
        p = model.p_over(j, j["line"].to_numpy())
        mu = model.project(j)
        for (_, r), pi, mui in zip(j.iterrows(), p, mu):
            pl = players.loc[r["athlete_id"]] if r["athlete_id"] in players.index else None
            injury = None if pl is None or pd.isna(pl["injury"]) else pl["injury"]
            if injury in OUT:
                continue
            if m == "anytime_td":
                mk = float(american_prob(r["price_a"]))
                side, p_side, mk_side, price = "Yes", float(pi), mk, r["price_a"]
            else:
                op, up = (r["price_a"], r["price_b"]) if a_is_over else (r["price_b"], r["price_a"])
                mk_over = None
                if not pd.isna(op) and not pd.isna(up):
                    po, pu = american_prob(op), american_prob(up)
                    mk_over = float(po / (po + pu))
                over = pi >= 0.5
                side = "Over" if over else "Under"
                p_side = float(pi if over else 1 - pi)
                mk_side = None if mk_over is None else (mk_over if over else 1 - mk_over)
                price = op if over else up
            out.append({"game_id": r["game_id"], "athlete_id": r["athlete_id"],
                        "player": None if pl is None else pl["name"], "team_id": None if pl is None else pl["team_id"],
                        "position": None if pl is None else pl["position"], "injury": injury, "market": m, "label": LABELS[m],
                        "line": float(r["line"]), "projection": round(float(mui), 2), "side": side,
                        "p_side": round(p_side, 4), "p_market": None if mk_side is None else round(mk_side, 4),
                        "price": None if pd.isna(price) else float(price), "confidence": confidence(p_side) if m != "anytime_td" else
                        ("high" if p_side >= 0.5 else "medium" if p_side >= 0.35 else "low"),
                        "l5": round(float(r["l5"]), 1), "l10": round(float(r["l10"]), 1),
                        "season_mean": None if pd.isna(r["season_mean_f"]) else round(float(r["season_mean_f"]), 1),
                        "provider": r["provider"]})
    return out


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.INFO)
    from pipeline import db
    if sys.argv[1] == "evaluate":
        # Call through the package so pickled models reference model.props, not __main__.
        from model import props as _props
        print(json.dumps(_props.evaluate(db.connect(), sys.argv[2]), indent=1))
