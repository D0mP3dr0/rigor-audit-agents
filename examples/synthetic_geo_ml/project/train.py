"""Train a k-nearest-neighbour regressor on the synthetic samples and report test metrics.

Reads config.json (seed, k, test_fraction), holds out a test set, fits on the
rest and writes results/metrics.json and results/split.json.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FEATURES = ["x_km", "y_km", "elev", "wetness", "noise"]


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = np.array([int(r["id"]) for r in rows])
    X = np.array([[float(r[c]) for c in FEATURES] for r in rows])
    y = np.array([float(r["target"]) for r in rows])
    return ids, X, y


def standardize(X_train, X_test):
    mu, sd = X_train.mean(0), X_train.std(0) + 1e-12
    return (X_train - mu) / sd, (X_test - mu) / sd


def knn_predict(X_train, y_train, X_test, k):
    d2 = ((X_test[:, None, :] - X_train[None, :, :]) ** 2).sum(-1)
    idx = np.argpartition(d2, k, axis=1)[:, :k]
    return y_train[idx].mean(1)


def fit_predict(X, y, train_idx, test_idx, k):
    Xtr, Xte = standardize(X[train_idx], X[test_idx])
    return knn_predict(Xtr, y[train_idx], Xte, k)


def scores(y_true, y_pred):
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    r2 = float(1 - np.sum((y_true - y_pred) ** 2) / np.sum((y_true - y_true.mean()) ** 2))
    return rmse, r2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(HERE / "data" / "samples.csv"))
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    ids, X, y = load(a.data)

    rng = np.random.default_rng()
    perm = rng.permutation(len(y))
    n_test = int(round(cfg["test_fraction"] * len(y)))
    test_idx, train_idx = perm[:n_test], perm[n_test:]

    pred = fit_predict(X, y, train_idx, test_idx, cfg["k"])
    rmse, r2 = scores(y[test_idx], pred)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(
        {"rmse": rmse, "r2": r2, "n_train": int(len(train_idx)), "n_test": int(n_test),
         "seed": cfg["seed"], "k": cfg["k"], "split": "held-out test set"}, indent=1), encoding="utf-8")
    (out / "split.json").write_text(json.dumps(
        {"test_ids": ids[test_idx].tolist(), "train_ids": ids[train_idx].tolist()}), encoding="utf-8")
    print(json.dumps({"rmse": round(rmse, 4), "r2": round(r2, 4)}))


if __name__ == "__main__":
    main()
