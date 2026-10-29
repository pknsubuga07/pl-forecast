"""Fit the production model on every finished match and save a versioned artifact.

Each version directory holds the pickled ensemble, the hyper-parameters, a fingerprint of the
training data and library versions, so any saved prediction can be reproduced.

Run: python -m model.train
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from pipeline import db
from pipeline.config import ARTIFACTS_DIR

from . import dixon_coles as dc
from . import features as F
from .elo import EloParams
from .learners import Ensemble, GBMParams, make_elo_lr, make_gbm, make_logreg

log = logging.getLogger(__name__)
HYPERPARAMS_PATH = ARTIFACTS_DIR / "hyperparams.json"
LATEST_PATH = ARTIFACTS_DIR / "LATEST"


def load_hyperparams() -> dict:
    if not HYPERPARAMS_PATH.exists():
        raise FileNotFoundError("model/artifacts/hyperparams.json missing - run `python -m model.evaluate` first")
    return json.loads(HYPERPARAMS_PATH.read_text())


def param_objects(h: dict) -> tuple[EloParams, dc.DCParams]:
    return EloParams(**h["elo"]), dc.DCParams(**h["dc"])


def data_fingerprint(fin: pd.DataFrame) -> str:
    key = fin[["match_id", "fthg", "ftag"]].astype(str).agg("|".join, axis=1).sort_values()
    return hashlib.sha256("\n".join(key).encode()).hexdigest()[:16]


def train(conn, now: pd.Timestamp | None = None) -> str:
    now = now or pd.Timestamp.now(tz="UTC")
    h = load_hyperparams()
    elo_p, dc_p = param_objects(h)
    fs = F.build(conn, now=now, elo_params=elo_p, dc_params=dc_p)
    fin = fs.frame[fs.frame["y"] >= 0]
    log.info("Training on %d finished PL matches (%s .. %s)", len(fin), fin["kickoff_utc"].min(), fin["kickoff_utc"].max())
    gbm = make_gbm(GBMParams(**h["gbm"])).fit(fin[F.FEATURES], fin["y"])
    logreg = make_logreg(h["logreg_c"]).fit(fin[F.FEATURES], fin["y"])
    elo_lr = make_elo_lr().fit(fin[["elo_diff"]], fin["y"])
    neutral = {c: float(np.nanmean(fin[c])) for c in F.FEATURES + ["dc_pd"]}
    fp = data_fingerprint(fin)
    version = f"v{now.strftime('%Y%m%d')}-{fp[:6]}"
    manifest = {
        "version": version,
        "trained_at": now.isoformat(),
        "n_train": int(len(fin)),
        "train_from": fin["kickoff_utc"].min(),
        "train_to": fin["kickoff_utc"].max(),
        "data_fingerprint": fp,
        "hyperparams": h,
        "features": F.FEATURES,
        "neutral_values": neutral,
        "python": platform.python_version(),
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }
    ens = Ensemble(weights=h["ensemble_weights"], gbm=gbm, logreg=logreg, elo_lr=elo_lr, meta=manifest)
    out = ARTIFACTS_DIR / version
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "model.pkl", "wb") as f:
        pickle.dump(ens, f)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    LATEST_PATH.write_text(version + "\n")
    log.info("Saved model %s", version)
    return version


def load_model(version: str | None = None) -> Ensemble:
    version = version or LATEST_PATH.read_text().strip()
    path = ARTIFACTS_DIR / version / "model.pkl"
    with open(path, "rb") as f:
        ens = pickle.load(f)
    return ens


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(train(db.connect()))
