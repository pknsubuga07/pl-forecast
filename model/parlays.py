"""Daily parlays built from medium- and high-confidence picks across the Premier League, NBA and NFL.

How a day's parlays are built:
  1. Legs: every game that day (New York date) whose model pick is medium or high confidence and
     that has a bookmaker price for that pick.
  2. Candidates: every 2-, 3- and 4-leg combination of the strongest legs (one leg per game).
     Legs are treated as independent, so the parlay probability is the product of the legs'.
  3. Selection (5 to 10 per day, fewer if the slate is small): the safest double, treble and
     four-fold, the best model-vs-market value, the best cross-sport combination, then the most
     likely remaining combinations, with no leg used in more than three parlays.

Honesty: the model is less accurate than the betting market, and every extra leg multiplies the
bookmaker's margin, so parlays are expected to lose money on average. `backtest()` measures this
on the walk-forward test seasons and the result is shown next to the picks.
"""
from __future__ import annotations

import hashlib
import itertools
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

MIN_PARLAYS, MAX_PARLAYS = 5, 10
MAX_LEG_USE = 3
POOL = 12          # strongest legs considered for combinations
MIN_JOINT_P = 0.10  # don't suggest long shots


@dataclass
class Leg:
    sport: str           # 'pl' | 'nba' | 'nfl'
    game_id: str
    kickoff_utc: str
    pick: str            # 'H' | 'D' | 'A'
    label: str           # "Arsenal to win"
    matchup: str         # "Arsenal v Chelsea" / "BOS @ NYK"
    p_model: float
    p_market: float | None
    odds: float          # decimal odds for this pick
    confidence: str
    href: str = ""

    @property
    def key(self) -> str:
        return f"{self.game_id}:{self.pick}"


@dataclass
class Parlay:
    tag: str
    legs: list[Leg]
    p_model: float = 0.0
    p_market: float | None = None
    odds: float = 0.0
    ev_model: float = 0.0     # expected profit per 1 staked if the model's probabilities were right
    ev_market: float | None = None
    sports: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.p_model = float(np.prod([l.p_model for l in self.legs]))
        mk = [l.p_market for l in self.legs]
        self.p_market = float(np.prod(mk)) if all(m is not None for m in mk) else None
        self.odds = float(np.prod([l.odds for l in self.legs]))
        self.ev_model = self.p_model * self.odds - 1
        self.ev_market = None if self.p_market is None else self.p_market * self.odds - 1
        self.sports = sorted({l.sport for l in self.legs})

    @property
    def id(self) -> str:
        return hashlib.sha1("|".join(sorted(l.key for l in self.legs)).encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        return {"id": self.id, "tag": self.tag, "n_legs": len(self.legs), "p_model": round(self.p_model, 4),
                "p_market": None if self.p_market is None else round(self.p_market, 4), "odds": round(self.odds, 2),
                "payout_per_10": round(10 * self.odds, 2), "ev_model": round(self.ev_model, 4),
                "ev_market": None if self.ev_market is None else round(self.ev_market, 4), "sports": self.sports,
                "first_kickoff": min(l.kickoff_utc for l in self.legs),
                "legs": [asdict(l) for l in self.legs]}


def eligible(legs: list[Leg]) -> list[Leg]:
    return [l for l in legs if l.confidence in ("high", "medium") and l.odds and l.odds > 1.0]


def build(legs: list[Leg], n_max: int = MAX_PARLAYS) -> list[Parlay]:
    pool = sorted(eligible(legs), key=lambda l: -l.p_model)[:POOL]
    if len(pool) < 2:
        return []
    cands: list[Parlay] = []
    for size in (2, 3, 4):
        for combo in itertools.combinations(pool, size):
            if len({l.game_id for l in combo}) < size:
                continue
            p = Parlay("", list(combo))
            if p.p_model >= MIN_JOINT_P:
                cands.append(p)
    chosen: list[Parlay] = []
    use: dict[str, int] = {}

    def take(p: Parlay | None, tag: str) -> None:
        if p is None or any(p.id == c.id for c in chosen):
            return
        if any(use.get(l.key, 0) >= MAX_LEG_USE for l in p.legs):
            return
        p.tag = tag
        chosen.append(p)
        for l in p.legs:
            use[l.key] = use.get(l.key, 0) + 1

    def best(pred, key) -> Parlay | None:
        c = [p for p in cands if pred(p) and all(use.get(l.key, 0) < MAX_LEG_USE for l in p.legs)
             and not any(p.id == x.id for x in chosen)]
        return max(c, key=key) if c else None

    take(best(lambda p: len(p.legs) == 2, lambda p: p.p_model), "Safest double")
    take(best(lambda p: len(p.legs) == 3, lambda p: p.p_model), "Safest treble")
    take(best(lambda p: len(p.legs) == 4, lambda p: p.p_model), "Safest four-fold")
    take(best(lambda p: len(p.legs) <= 3 and p.p_model >= 0.2 and p.ev_model > 0, lambda p: p.ev_model), "Best value vs market")
    take(best(lambda p: len(p.sports) >= 2, lambda p: p.p_model), "Cross-sport")
    while len(chosen) < n_max:
        p = best(lambda p: len(p.legs) <= 3, lambda p: p.p_model)
        if p is None:
            break
        take(p, f"{len(p.legs)}-leg")
    return chosen


# --------------------------------------------------------------------------- legs from predictions
def american_to_decimal(ml: float) -> float:
    return 1 + (ml / 100 if ml > 0 else 100 / -ml)


def pl_leg(f: dict) -> Leg | None:
    """From a Premier League fixture summary (web/public/data/fixtures.json)."""
    k = "HDA".index(f["predicted"])
    mk = f.get("market_p")
    odds = (f.get("market_odds") or [None, None, None])[k]
    if not odds:
        return None
    label = {"H": f"{f['home']['name']} to win", "D": "Draw", "A": f"{f['away']['name']} to win"}[f["predicted"]]
    return Leg("pl", f["match_id"], f["kickoff_utc"], f["predicted"], label, f"{f['home']['name']} v {f['away']['name']}",
               float(f["p"][k]), float(mk[k]) if mk else None, float(odds), f["confidence"], f"/match/{f['match_id']}")


def us_leg(sport: str, g: dict) -> Leg | None:
    """From an NBA/NFL game summary (web/public/data/<sport>/games.json) plus its moneyline."""
    ml = g.get("market_ml")
    if not ml:
        return None
    home = g["predicted"] == "H"
    p = g["p_home"] if home else 1 - g["p_home"]
    mk = g.get("market_p_home")
    team = g["home"] if home else g["away"]
    return Leg(sport, g["game_id"], g["kickoff_utc"], g["predicted"], f"{team['name']} to win",
               f"{g['away']['short']} @ {g['home']['short']}", float(p),
               None if mk is None else float(mk if home else 1 - mk),
               american_to_decimal(ml[0] if home else ml[1]), g["confidence"], f"/{sport}/game/{g['game_id']}")


# --------------------------------------------------------------------------- backtest
def _pl_conf(p: np.ndarray) -> str:
    from .predict import confidence
    return confidence(p)


def backtest(pl: pd.DataFrame | None, us: dict[str, pd.DataFrame], seasons: dict[str, list[int]]) -> dict:
    """Build parlays every day of the test seasons from walk-forward predictions and score them at
    the bookmaker prices that were available. Returns hit rates and return on stake."""
    from .us_predict import confidence as us_conf
    legs_by_day: dict[str, list[tuple[Leg, bool | None]]] = {}

    def day_of(ts: str) -> str:
        return pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d")

    if pl is not None:
        d = pl[pl["season"].isin(seasons["pl"]) & pl["odds_h"].notna()]
        for r in d.itertuples():
            p = np.array([r.p_h, r.p_d, r.p_a])
            k = int(np.argmax(p))
            odds = [r.odds_h, r.odds_d, r.odds_a]
            inv = np.array([1 / o for o in odds])
            leg = Leg("pl", r.game_id, r.kickoff_utc, "HDA"[k], "", "", float(p[k]), float(inv[k] / inv.sum()),
                      float(odds[k]), _pl_conf(p))
            legs_by_day.setdefault(day_of(r.kickoff_utc), []).append((leg, int(r.y) == k))
    for sport, d in us.items():
        d = d[d["season"].isin(seasons[sport]) & d["home_ml"].notna() & (d["y"] >= 0)]
        for r in d.itertuples():
            home = r.p_home >= 0.5
            p = r.p_home if home else 1 - r.p_home
            ph = 1 / american_to_decimal(r.home_ml)
            pa = 1 / american_to_decimal(r.away_ml)
            leg = Leg(sport, r.game_id, r.kickoff_utc, "H" if home else "A", "", "", float(p),
                      float((ph if home else pa) / (ph + pa)), american_to_decimal(r.home_ml if home else r.away_ml),
                      us_conf(r.p_home))
            legs_by_day.setdefault(day_of(r.kickoff_utc), []).append((leg, (r.y == 1) == home))
    rows = []
    for day, items in legs_by_day.items():
        won = {l.key: w for l, w in items}
        for p in build([l for l, _ in items]):
            hit = all(won[l.key] for l in p.legs)
            rows.append({"day": day, "tag": p.tag, "n_legs": len(p.legs), "p_model": p.p_model, "p_market": p.p_market,
                         "odds": p.odds, "hit": hit, "profit": (p.odds - 1) if hit else -1.0, "sports": "+".join(p.sports)})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n": 0}

    def summary(x: pd.DataFrame) -> dict:
        return {"n": int(len(x)), "hit_rate": float(x["hit"].mean()), "expected_hit_rate_model": float(x["p_model"].mean()),
                "expected_hit_rate_market": float(x["p_market"].mean()), "avg_odds": float(x["odds"].mean()),
                "roi": float(x["profit"].mean())}
    out = {"days": int(df["day"].nunique()), "all": summary(df),
           "by_legs": {str(k): summary(g) for k, g in df.groupby("n_legs")},
           "by_tag": {k: summary(g) for k, g in df.groupby("tag") if not k[0].isdigit()}}
    # Per-season-ish view: by calendar year of the day.
    out["by_year"] = {k: summary(g) for k, g in df.groupby(df["day"].str[:4])}
    return out


def settle(legs: list[dict], results: dict[str, str | None]) -> str:
    """results: game_id -> 'H'|'D'|'A' when final, None when not finished, 'VOID' if postponed."""
    outs = [results.get(l["game_id"]) for l in legs]
    if any(o == "VOID" for o in outs):
        return "void"
    if any(o is not None and o != l["pick"] for o, l in zip(outs, legs)):
        return "lost"
    if all(o is not None for o in outs):
        return "won"
    return "open"
