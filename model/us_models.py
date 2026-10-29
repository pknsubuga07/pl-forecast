"""Two-outcome (home win / away win) models for NBA and NFL, plus margin and total models for
projected scores and spreads."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

EPS = 1e-6


# --------------------------------------------------------------------------- metrics
def binary_metrics(p, y) -> dict:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return {
        "n": int(len(y)),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "brier": float(np.mean((p - y) ** 2)),
        "accuracy": float(np.mean((p >= 0.5) == (y == 1))),
    }


def binary_calibration(p, y, bins: int = 10) -> list[dict]:
    """Reliability bins for P(home win)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return [{"bin_lo": float(edges[b]), "bin_hi": float(edges[b + 1]), "n": int((idx == b).sum()),
             "mean_pred": float(p[idx == b].mean()), "observed": float(y[idx == b].mean())}
            for b in range(bins) if (idx == b).sum()]


def american_to_prob(ml) -> np.ndarray:
    ml = np.asarray(ml, float)
    return np.where(ml < 0, -ml / (-ml + 100), 100 / (ml + 100))


def market_home_prob(home_ml, away_ml) -> np.ndarray:
    """Moneyline implied probability of a home win, bookmaker margin removed."""
    ph, pa = american_to_prob(home_ml), american_to_prob(away_ml)
    return ph / (ph + pa)


# --------------------------------------------------------------------------- learners
@dataclass(frozen=True)
class GBMParams:
    learning_rate: float = 0.03
    max_iter: int = 300
    max_depth: int = 2
    min_samples_leaf: int = 100
    l2_regularization: float = 1.0


def make_gbm(p: GBMParams) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(learning_rate=p.learning_rate, max_iter=p.max_iter, max_depth=p.max_depth,
                                          min_samples_leaf=p.min_samples_leaf, l2_regularization=p.l2_regularization,
                                          early_stopping=False, random_state=0)


def make_ridge(alpha: float):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=alpha))


def make_elo_lr():
    return LogisticRegression(C=1.0, max_iter=1000)


@dataclass
class MarginModel:
    """Ridge regression for the home margin; win probability = P(N(margin, sigma) > 0)."""
    reg: object
    sigma: float

    def margin(self, X) -> np.ndarray:
        return np.asarray(self.reg.predict(X), float)

    def prob(self, X) -> np.ndarray:
        return norm.cdf(self.margin(X) / self.sigma)


def fit_margin(X, margin, alpha: float) -> MarginModel:
    reg = make_ridge(alpha).fit(X, margin)
    resid = np.asarray(margin, float) - reg.predict(X)
    return MarginModel(reg, float(np.std(resid)))


@dataclass
class USEnsemble:
    sport: str
    features: list[str]
    weights: dict[str, float]
    elo_lr: object
    margin: MarginModel
    total: object
    gbm: object | None
    meta: dict = field(default_factory=dict)

    def components(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        out = {"elo": self.elo_lr.predict_proba(X[["elo_diff", "neutral"]])[:, 1],
               "margin": self.margin.prob(X[self.features])}
        if self.gbm is not None:
            out["gbm"] = self.gbm.predict_proba(X[self.features])[:, 1]
        return out

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        c = self.components(X)
        p = sum(w * c[k] for k, w in self.weights.items() if w > 0)
        return np.clip(p, EPS, 1 - EPS)

    def predict_margin(self, X: pd.DataFrame) -> np.ndarray:
        """Margin consistent with the ensemble probability (inverse of the margin model's link)."""
        return norm.ppf(self.predict(X)) * self.margin.sigma

    def predict_total(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.total.predict(X[self.features]), float)
