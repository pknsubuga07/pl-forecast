"""Probabilistic scoring rules for 1X2 forecasts. Outcome index: 0 home, 1 draw, 2 away."""
from __future__ import annotations

import numpy as np

EPS = 1e-12


def _check(p: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=int)
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError("probabilities must have shape (n, 3)")
    if not np.allclose(p.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("each row of probabilities must sum to 1")
    return p, y


def log_loss(p, y) -> float:
    p, y = _check(p, y)
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], EPS, 1))))


def brier(p, y) -> float:
    """Multi-class Brier score: mean over matches of the summed squared error (range 0-2)."""
    p, y = _check(p, y)
    onehot = np.eye(3)[y]
    return float(np.mean(np.sum((p - onehot) ** 2, axis=1)))


def rps(p, y) -> float:
    """Ranked probability score for the ordered outcomes home < draw < away (range 0-1)."""
    p, y = _check(p, y)
    onehot = np.eye(3)[y]
    cp, co = np.cumsum(p, axis=1)[:, :2], np.cumsum(onehot, axis=1)[:, :2]
    return float(np.mean(np.sum((cp - co) ** 2, axis=1) / 2))


def accuracy(p, y) -> float:
    p, y = _check(p, y)
    return float(np.mean(np.argmax(p, axis=1) == y))


def all_metrics(p, y) -> dict:
    return {"n": int(len(y)), "log_loss": log_loss(p, y), "brier": brier(p, y), "rps": rps(p, y), "accuracy": accuracy(p, y)}


def calibration(p, y, bins: int = 10) -> list[dict]:
    """Reliability table for all three outcomes pooled (each match contributes 3 forecasts)."""
    p, y = _check(p, y)
    probs = p.ravel()
    hits = np.eye(3)[y].ravel()
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(probs, edges) - 1, 0, bins - 1)
    out = []
    for b in range(bins):
        sel = idx == b
        if sel.sum() == 0:
            continue
        out.append({"bin_lo": float(edges[b]), "bin_hi": float(edges[b + 1]), "n": int(sel.sum()),
                    "mean_pred": float(probs[sel].mean()), "observed": float(hits[sel].mean())})
    return out


def implied_probs(odds_h, odds_d, odds_a) -> np.ndarray:
    """Bookmaker probabilities with the margin removed (proportional normalisation)."""
    inv = 1.0 / np.column_stack([odds_h, odds_d, odds_a]).astype(float)
    return inv / inv.sum(axis=1, keepdims=True)


def normalise(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, None)
    return p / p.sum(axis=1, keepdims=True)
