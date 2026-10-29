"""Plain-English explanations by group ablation.

For each group of related features we make the two teams equal on that group (home and away
values replaced by their mean; ratings set to an evenly matched fixture, which keeps normal
home advantage) and measure how much the probability of the predicted outcome changes. Groups that raise it the most "drive" the prediction; groups that lower it
"pull the other way". This works on the whole ensemble, not just one component.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .learners import Ensemble

def poss(name: str) -> str:
    """English possessive: "Arsenal's", "Green Bay Packers'"."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


GROUPS = {
    "ratings": ["elo_home", "elo_away", "elo_diff", "dc_lambda", "dc_mu", "dc_ph", "dc_pd", "dc_pa"],
    "recent_form": ["form5_ppg_h", "form5_ppg_a", "gd10_h", "gd10_a"],
    "shots": ["sotd10_h", "sotd10_a", "sd10_h", "sd10_a"],
    "venue_form": ["venue_ppg_h", "venue_ppg_a", "venue_gd_h", "venue_gd_a"],
    "table": ["std_ppg_h", "std_ppg_a", "std_gdpg_h", "std_gdpg_a", "pos_h", "pos_a"],
    "rest": ["rest_h", "rest_a", "euro_h", "euro_a"],
    "promoted": ["promoted_h", "promoted_a"],
}
OUTCOME = {0: "home", 1: "draw", 2: "away"}


# Columns that are not home/away pairs and are reset to the training average instead.
AVERAGE_COLS = {"dc_lambda", "dc_mu", "dc_ph", "dc_pd", "dc_pa", "venue_ppg_h", "venue_ppg_a", "venue_gd_h", "venue_gd_a"}


def neutralise(x: pd.DataFrame, group: str, neutral: dict[str, float]) -> pd.DataFrame:
    x = x.copy()
    cols = GROUPS[group]
    for c in cols:
        if c in AVERAGE_COLS:
            x[c] = neutral.get(c, np.nan)
    if group == "ratings":
        mean = (x["elo_home"] + x["elo_away"]) / 2
        x["elo_home"], x["elo_away"], x["elo_diff"] = mean, mean, 0.0
    elif group == "promoted":
        x["promoted_h"], x["promoted_a"] = 0, 0
    else:
        for c in cols:
            if c.endswith("_h") and c not in AVERAGE_COLS:
                pair = c[:-2] + "_a"
                mean = x[[c, pair]].mean(axis=1)
                x[c], x[pair] = mean, mean
    return x


def group_effects(ens: Ensemble, row: pd.DataFrame, neutral: dict[str, float]) -> dict[str, np.ndarray]:
    """Change in [p_home, p_draw, p_away] attributable to each group (actual - equalised)."""
    base = ens.predict(row)[0]
    return {g: base - ens.predict(neutralise(row, g, neutral))[0] for g in GROUPS}


def _ordinal(n) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _win(team: str) -> str:
    return f"{'an' if team[0] in 'AEIOU' else 'a'} {team} win"


def _f(v, fmt="{:.1f}") -> str:
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else fmt.format(v)


def phrase(group: str, favours_home: bool, r: pd.Series, home: str, away: str) -> str:
    team, other = (home, away) if favours_home else (away, home)
    s = "h" if favours_home else "a"
    o = "a" if favours_home else "h"
    if group == "ratings":
        mine, theirs = (r["elo_home"], r["elo_away"]) if favours_home else (r["elo_away"], r["elo_home"])
        if mine > theirs:
            return f"{poss(team)} higher strength rating (Elo {mine:.0f} vs {theirs:.0f})"
        g_mine, g_theirs = (r["dc_lambda"], r["dc_mu"]) if favours_home else (r["dc_mu"], r["dc_lambda"])
        return f"{poss(team)} attack and defence ratings in the goals model ({g_mine:.2f} vs {g_theirs:.2f} expected goals)"
    if group == "recent_form":
        return f"{poss(team)} better recent form ({_f(r[f'form5_ppg_{s}'])} vs {_f(r[f'form5_ppg_{o}'])} points per game over the last 5)"
    if group == "shots":
        return (f"{poss(team)} stronger shot numbers (shots-on-target difference {_f(r[f'sotd10_{s}'], '{:+.1f}')} "
                f"vs {_f(r[f'sotd10_{o}'], '{:+.1f}')} per game over the last 10)")
    if group == "venue_form":
        lead = f"{poss(home)} home record" if favours_home else f"{poss(away)} away record"
        return (f"{lead} ({home} {_f(r['venue_ppg_h'])} points per game in recent home matches, "
                f"{away} {_f(r['venue_ppg_a'])} in recent away matches)")
    if group == "table":
        ph, pa = r.get(f"pos_{s}"), r.get(f"pos_{o}")
        if ph is not None and not np.isnan(ph) and pa is not None and not np.isnan(pa):
            return f"{poss(team)} league position ({_ordinal(ph)} vs {_ordinal(pa)})"
        return f"{poss(team)} points per game this season"
    if group == "rest":
        if r[f"euro_{o}"] == 1 and r[f"euro_{s}"] == 0:
            return f"{other} playing in Europe a few days earlier"
        return f"{team} having more rest ({r[f'rest_{s}']:.0f} vs {r[f'rest_{o}']:.0f} days)"
    if group == "promoted":
        return f"{other} being newly promoted"
    return group


def explain(ens: Ensemble, row: pd.DataFrame, neutral: dict[str, float], home: str, away: str,
            threshold: float = 0.01) -> dict:
    p = ens.predict(row)[0]
    k = int(np.argmax(p))
    effects = group_effects(ens, row, neutral)
    r = row.iloc[0]
    items = []
    for g, d in effects.items():
        favours_home = (d[0] - d[2]) > 0
        items.append({"group": g, "effect": float(d[k]), "home_minus_away": float(d[0] - d[2]),
                      "favours": "home" if favours_home else "away",
                      "text": phrase(g, favours_home, r, home, away)})
    items.sort(key=lambda x: -abs(x["effect"]))
    pros = [i for i in items if i["effect"] > threshold][:2]
    cons = [i for i in items if i["effect"] < -threshold][:1]
    outcome_txt = {0: _win(home), 1: "a draw", 2: _win(away)}[k]
    if k == 1:
        # For a draw, the story is how evenly the factors cancel out.
        top = sorted(items, key=lambda x: -abs(x["home_minus_away"]))[:2]
        parts = " and ".join(i["text"] for i in top)
        text = (f"The model sees this as close: no single factor dominates, so a draw is its most likely single outcome. "
                f"The biggest influences are {parts}." if top else "The model sees this as evenly matched.")
    elif pros:
        lead = " and ".join(i["text"] for i in pros)
        verb = "drive" if len(pros) > 1 else "drives"
        text = f"{lead[0].upper()}{lead[1:]} {verb} most of this prediction towards {outcome_txt}."
        if cons:
            text += f" {cons[0]['text'][0].upper()}{cons[0]['text'][1:]} pulls the other way."
    else:
        text = (f"The teams are closely matched on the model's inputs, so home advantage is what tips it towards {outcome_txt}."
                if k == 0 else f"No single factor stands out; the combined inputs lean slightly towards {outcome_txt}.")
    return {"text": text, "factors": items}
