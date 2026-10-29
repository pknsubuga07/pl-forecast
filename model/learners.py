"""The trainable 1X2 learners and the ensemble that combines them."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES
from .metrics import normalise


@dataclass(frozen=True)
class GBMParams:
    learning_rate: float = 0.03
    max_iter: int = 300
    max_depth: int = 3
    min_samples_leaf: int = 60
    l2_regularization: float = 1.0


def make_gbm(p: GBMParams, seed: int = 0) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=p.learning_rate, max_iter=p.max_iter, max_depth=p.max_depth,
        min_samples_leaf=p.min_samples_leaf, l2_regularization=p.l2_regularization,
        early_stopping=False, random_state=seed,
    )


def make_logreg(c: float):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=c, max_iter=2000))


def make_elo_lr():
    return LogisticRegression(C=1.0, max_iter=1000)


def proba3(model, X) -> np.ndarray:
    """predict_proba re-ordered to columns [home, draw, away] even if a class was absent."""
    raw = model.predict_proba(X)
    out = np.full((len(X), 3), 1e-6)
    for j, cls in enumerate(model.classes_):
        out[:, int(cls)] = raw[:, j]
    return normalise(out)


@dataclass
class Ensemble:
    """Weighted average of component probabilities. Weights are chosen on validation seasons."""
    weights: dict[str, float]
    gbm: object | None = None
    logreg: object | None = None
    elo_lr: object | None = None
    meta: dict = field(default_factory=dict)

    def components(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        out = {"dc": normalise(X[["dc_ph", "dc_pd", "dc_pa"]].to_numpy(float))}
        if self.gbm is not None:
            out["gbm"] = proba3(self.gbm, X[FEATURES])
        if self.logreg is not None:
            out["logreg"] = proba3(self.logreg, X[FEATURES])
        if self.elo_lr is not None:
            out["elo"] = proba3(self.elo_lr, X[["elo_diff"]])
        return out

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        comps = self.components(X)
        p = sum(w * comps[k] for k, w in self.weights.items() if w > 0)
        return normalise(p)
