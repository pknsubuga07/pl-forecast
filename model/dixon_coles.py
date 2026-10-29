"""Time-weighted Dixon-Coles goals model.

log(lambda_home) = c + h + attack[home] - defence[away]
log(lambda_away) = c     + attack[away] - defence[home]

Fitted in two steps: a ridge-penalised weighted Poisson regression (Newton's method) for
c, h, attack and defence, then the Dixon-Coles low-score correlation rho by 1-D likelihood
maximisation. With sot_weight > 0 the Poisson target is a blend of actual goals and
"shots on target x league conversion rate", a free stand-in for xG that is less noisy than
goals. Ratings are shrunk towards a prior: 0 for established clubs and a negative
"promoted club" prior for clubs with no recent Premier League matches.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10


@dataclass(frozen=True)
class DCParams:
    xi: float = 0.0019             # time decay per day (half-life ~ 1 year)
    window_days: int = 3 * 365     # ignore matches older than this
    ridge: float = 6.0             # L2 strength pulling ratings towards their prior
    promoted_attack: float = -0.20  # prior (log scale) for clubs without recent PL data
    promoted_defence: float = -0.20
    sot_weight: float = 0.0        # blend of goals and shots-on-target-implied goals in the target


@dataclass
class DCModel:
    teams: list[str]
    c: float
    home: float
    attack: dict[str, float]
    defence: dict[str, float]
    rho: float
    params: DCParams = field(default_factory=DCParams)

    def rates(self, home: str, away: str) -> tuple[float, float]:
        p = self.params
        ah = self.attack.get(home, p.promoted_attack)
        dh = self.defence.get(home, p.promoted_defence)
        aa = self.attack.get(away, p.promoted_attack)
        da = self.defence.get(away, p.promoted_defence)
        return float(np.exp(self.c + self.home + ah - da)), float(np.exp(self.c + aa - dh))

    def score_matrix(self, home: str, away: str) -> np.ndarray:
        lam, mu = self.rates(home, away)
        return score_matrix(lam, mu, self.rho)

    def predict(self, home: str, away: str) -> dict:
        lam, mu = self.rates(home, away)
        m = score_matrix(lam, mu, self.rho)
        return {"lambda": lam, "mu": mu, **outcome_probs(m)}

    def to_dict(self) -> dict:
        return {"c": self.c, "home": self.home, "rho": self.rho, "attack": self.attack, "defence": self.defence}


def tau(x, y, lam, mu, rho):
    out = np.ones_like(lam, dtype=float)
    out = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, out)
    out = np.where((x == 0) & (y == 1), 1 + lam * rho, out)
    out = np.where((x == 1) & (y == 0), 1 + mu * rho, out)
    out = np.where((x == 1) & (y == 1), 1 - rho, out)
    return out


def score_matrix(lam: float, mu: float, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    m[0, 0] *= 1 - lam * mu * rho
    m[0, 1] *= 1 + lam * rho
    m[1, 0] *= 1 + mu * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def outcome_probs(m: np.ndarray) -> dict:
    return {"p_home": float(np.tril(m, -1).sum()), "p_draw": float(np.trace(m)), "p_away": float(np.triu(m, 1).sum())}


def fit(matches: pd.DataFrame, as_of: pd.Timestamp, params: DCParams = DCParams(),
        promoted: set[str] | None = None, warm: DCModel | None = None) -> DCModel | None:
    """Fit on finished matches strictly before as_of. matches needs kickoff (Timestamp),
    home_id, away_id, fthg, ftag."""
    age = (as_of - matches["kickoff"]).dt.total_seconds() / 86400.0
    sel = (age > 0) & (age <= params.window_days)
    m = matches.loc[sel]
    if len(m) < 100:
        return None
    w = np.exp(-params.xi * age[sel].to_numpy())
    teams = sorted(set(m["home_id"]) | set(m["away_id"]))
    idx = {t: i for i, t in enumerate(teams)}
    n, k = len(m), len(teams)
    hi = m["home_id"].map(idx).to_numpy()
    ai = m["away_id"].map(idx).to_numpy()
    # Design: [c, h, attack_0..k-1, defence_0..k-1]; two rows per match.
    p = 2 + 2 * k
    X = np.zeros((2 * n, p))
    r = np.arange(n)
    X[:, 0] = 1
    X[r, 1] = 1
    X[r, 2 + hi] = 1
    X[r, 2 + k + ai] = -1
    X[n + r, 2 + ai] = 1
    X[n + r, 2 + k + hi] = -1
    goals = np.concatenate([m["fthg"].to_numpy(float), m["ftag"].to_numpy(float)])
    y = goals
    if params.sot_weight > 0 and "hst" in m.columns:
        sot = np.concatenate([m["hst"].to_numpy(float), m["ast"].to_numpy(float)])
        ok = ~np.isnan(sot)
        if ok.sum() > 0:
            conv = goals[ok].sum() / max(sot[ok].sum(), 1.0)
            y = goals.copy()
            y[ok] = (1 - params.sot_weight) * goals[ok] + params.sot_weight * conv * sot[ok]
    ww = np.concatenate([w, w])

    promoted = promoted or set()
    prior = np.zeros(p)
    for t in promoted:
        if t in idx:
            prior[2 + idx[t]] = params.promoted_attack
            prior[2 + k + idx[t]] = params.promoted_defence
    pen = np.full(p, params.ridge)
    pen[:2] = 1e-6

    beta = prior.copy()
    beta[0] = np.log(max(y.mean(), 0.1))
    beta[1] = 0.25
    if warm is not None:
        beta[0], beta[1] = warm.c, warm.home
        for t, i in idx.items():
            if t in warm.attack:
                beta[2 + i], beta[2 + k + i] = warm.attack[t], warm.defence[t]
    for _ in range(50):
        eta = X @ beta
        mu = np.exp(eta)
        grad = X.T @ (ww * (mu - y)) + pen * (beta - prior)
        H = (X * (ww * mu)[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(H, grad)
        beta -= step
        if np.max(np.abs(step)) < 1e-7:
            break

    eta = X @ beta
    lam, muu = np.exp(eta[:n]), np.exp(eta[n:])
    x_, y_ = m["fthg"].to_numpy(), m["ftag"].to_numpy()

    def nll(rho):
        t = tau(x_, y_, lam, muu, rho)
        if np.any(t <= 0):
            return 1e12
        return -np.sum(w * np.log(t))

    rho = float(minimize_scalar(nll, bounds=(-0.25, 0.25), method="bounded").x)
    return DCModel(
        teams=teams, c=float(beta[0]), home=float(beta[1]),
        attack={t: float(beta[2 + i]) for t, i in idx.items()},
        defence={t: float(beta[2 + k + i]) for t, i in idx.items()},
        rho=rho, params=params,
    )
