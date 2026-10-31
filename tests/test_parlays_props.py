import numpy as np
import pandas as pd
import pytest

from model import parlays as P
from model import props as PR
from pipeline import props_ingest as PI


def leg(i, p, conf="medium", odds=None, sport="nba"):
    return P.Leg(sport, f"g{i}", f"2026-10-30T23:{i:02d}:00Z", "H", f"Team {i} to win", f"A{i} @ H{i}", p,
                 p - 0.02, odds or round(1 / (p - 0.03), 2), conf)


def test_parlays_use_only_medium_high_legs_and_respect_limits():
    legs = [leg(i, 0.62 + 0.02 * (i % 8), "high" if i % 3 == 0 else "medium") for i in range(12)]
    legs += [leg(50 + i, 0.9, "low") for i in range(3)]  # never used, however likely
    out = P.build(legs)
    assert P.MIN_PARLAYS <= len(out) <= P.MAX_PARLAYS
    use: dict[str, int] = {}
    for p in out:
        assert 2 <= len(p.legs) <= 4
        assert len({l.game_id for l in p.legs}) == len(p.legs)       # one leg per game
        assert all(l.confidence in ("high", "medium") for l in p.legs)
        assert p.p_model == pytest.approx(np.prod([l.p_model for l in p.legs]))
        assert p.odds == pytest.approx(np.prod([l.odds for l in p.legs]))
        for l in p.legs:
            use[l.key] = use.get(l.key, 0) + 1
    assert max(use.values()) <= P.MAX_LEG_USE
    assert len({p.id for p in out}) == len(out)
    assert out[0].tag == "Safest double"


def test_no_parlays_from_a_thin_slate():
    assert P.build([leg(1, 0.7)]) == []
    assert P.build([leg(1, 0.7, "low"), leg(2, 0.7, "low")]) == []


def test_settlement():
    legs = [{"game_id": "a", "pick": "H"}, {"game_id": "b", "pick": "A"}]
    assert P.settle(legs, {"a": "H", "b": "A"}) == "won"
    assert P.settle(legs, {"a": "D"}) == "lost"            # lost as soon as one leg fails
    assert P.settle(legs, {"a": "H"}) == "open"
    assert P.settle(legs, {"a": "H", "b": "VOID"}) == "void"


def test_american_conversion():
    assert P.american_to_decimal(-200) == pytest.approx(1.5)
    assert P.american_to_decimal(150) == pytest.approx(2.5)


# ------------------------------------------------------------------ props
def test_prop_market_names():
    assert PI.market_of("nba", "Total Points, Rebounds, and Assists") == "pra"
    assert PI.market_of("nba", "Total Points") == "pts"
    assert PI.market_of("nba", "Points Milestones") is None
    # Combined markets must never be filed under a single stat.
    assert PI.market_of("nba", "Total Points and Assists") is None
    assert PI.market_of("nba", "Total Assists and Rebounds") is None
    assert PI.market_of("nba", "Total Points and Rebounds") is None
    assert PI.market_of("nfl", "Total Receiving Yards (incl. overtime)") == "rec_yds"
    assert PI.market_of("nfl", "Anytime Touchdown Scorer") == "anytime_td"


def item(aid, name, line, price):
    return {"athlete": {"$ref": f"http://x/athletes/{aid}?lang=en"}, "type": {"name": name},
            "current": {"target": {"value": line}}, "odds": {"american": {"value": str(price)}}}


def test_parse_props_pairs_sides_and_keeps_one_line():
    items = [item(1, "Total Points", 21.5, -110), item(1, "Total Points", 21.5, -116),
             item(1, "Total Points", 25.5, +150), item(1, "Total Points", 25.5, -190),
             item(2, "Anytime Touchdown Scorer", None, +120)]
    rows = {(r["athlete_id"], r["market"]): r for r in PI.parse_props("nba", items, "g", "dk")}
    pts = rows[("1", "pts")]
    assert pts["line"] == 21.5 and (pts["price_a"], pts["price_b"]) == (-110, -116)   # the near-even main line
    nfl = PI.parse_props("nfl", items, "g", "dk")
    td = [r for r in nfl if r["market"] == "anytime_td"][0]
    assert td["line"] == 0.5 and td["price_b"] is None


def test_orientation_detects_which_price_is_the_over():
    rng = np.random.default_rng(0)
    n = 400
    line = np.full(n, 20.5)
    actual = rng.normal(20.5, 6, n)
    over = actual > line
    # Make the first price the favourite exactly when the over is more likely to hit (it is the over side).
    fav = np.where(rng.random(n) < 0.6, over, ~over)
    a = np.where(fav, -130, 110)
    b = np.where(fav, 110, -130)
    df = pd.DataFrame({"market": "pts", "line": line, "actual": actual, "price_a": a, "price_b": b})
    assert PR.orientation(df) is True
    assert PR.orientation(df.rename(columns={"price_a": "price_b", "price_b": "price_a"})) is False


def test_prop_confidence_levels():
    assert PR.confidence(0.65) == "high" and PR.confidence(0.58) == "medium" and PR.confidence(0.52) == "low"
