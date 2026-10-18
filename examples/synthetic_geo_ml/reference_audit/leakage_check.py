"""Reference script of the data-spatial-leakage front, applied to the example project.

This is the kind of script the front agent writes and runs. It reads the
project (read-only), writes only to --out, and produces both the raw output
(raw/leakage_synthetic.json) and the front artifact (data-spatial-leakage.json).

Steps:
  1. distance from every test sample to its nearest training sample;
  2. practical range of spatial autocorrelation of the residual the covariates
     do not explain (empirical semivariogram, first lag reaching 95% of the sill);
  3. fraction of test samples closer to training data than that range;
  4. the same model scored under random 5-fold CV and under spatially blocked
     5-fold CV (blocks larger than the range); the gap is the optimism of the split.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

import numpy as np


def import_project(project):
    sys.path.insert(0, str(Path(project).resolve()))
    import train  # the project's own model code, used read-only
    return train


def semivariogram(xy, z, max_lag, step, max_points, rng):
    if len(z) > max_points:
        sel = rng.choice(len(z), max_points, replace=False)
        xy, z = xy[sel], z[sel]
    i, j = np.triu_indices(len(z), k=1)
    d = np.sqrt(((xy[i] - xy[j]) ** 2).sum(1))
    g = 0.5 * (z[i] - z[j]) ** 2
    edges = np.arange(0, max_lag + step, step)
    lags, gamma = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (d >= lo) & (d < hi)
        if m.sum() >= 30:
            lags.append((lo + hi) / 2)
            gamma.append(float(g[m].mean()))
    return np.array(lags), np.array(gamma)


def practical_range(lags, gamma, sill_from):
    sill = float(gamma[lags >= sill_from].mean())
    reach = np.nonzero(gamma >= 0.95 * sill)[0]
    return (float(lags[reach[0]]) if len(reach) else float(lags[-1])), sill


def cv_r2(train, X, y, folds, k):
    pred = np.empty_like(y)
    for f in np.unique(folds):
        te, tr = np.nonzero(folds == f)[0], np.nonzero(folds != f)[0]
        pred[te] = train.fit_predict(X, y, tr, te, k)
    return train.scores(y, pred)[1]


def run(project, out, n_folds=5, seed=0):
    project, out = Path(project), Path(out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    train = import_project(project)
    cfg = json.loads((project / "config.json").read_text(encoding="utf-8"))
    ids, X, y = train.load(project / "data" / "samples.csv")
    split = json.loads((project / "results" / "split.json").read_text(encoding="utf-8"))
    declared = json.loads((project / "results" / "metrics.json").read_text(encoding="utf-8"))
    pos = {int(v): i for i, v in enumerate(ids)}
    te = np.array([pos[i] for i in split["test_ids"]])
    tr = np.array([pos[i] for i in split["train_ids"]])
    xy = X[:, :2]
    rng = np.random.default_rng(seed)

    # 1. nearest training sample for each test sample
    d = np.sqrt(((xy[te][:, None, :] - xy[tr][None, :, :]) ** 2).sum(-1)).min(1)

    # 2. residual of the covariates (no coordinates), then its semivariogram
    A = np.column_stack([np.ones(len(y)), X[:, 2:]])
    resid = y - A @ np.linalg.lstsq(A, y, rcond=None)[0]
    lags, gamma = semivariogram(xy, resid, max_lag=60.0, step=2.0, max_points=1200, rng=rng)
    rng_km, sill = practical_range(lags, gamma, sill_from=40.0)

    # 3. fraction of test samples inside the range
    frac_inside = float((d < rng_km).mean())

    # 4. random vs spatially blocked CV with the project's own model
    block_km = float(np.ceil(max(rng_km, 1.0) * 1.5))
    random_folds = rng.permutation(np.arange(len(y)) % n_folds)
    bx, by = np.floor(xy[:, 0] / block_km).astype(int), np.floor(xy[:, 1] / block_km).astype(int)
    block_id = bx * 10_000 + by
    ublocks = np.unique(block_id)
    block_fold = dict(zip(ublocks, rng.permutation(np.arange(len(ublocks)) % n_folds)))
    blocked_folds = np.array([block_fold[b] for b in block_id])
    r2_random = cv_r2(train, X, y, random_folds, cfg["k"])
    r2_blocked = cv_r2(train, X, y, blocked_folds, cfg["k"])
    optimism = r2_random - r2_blocked

    command = " ".join(shlex.quote(c) for c in [sys.executable, str(Path(__file__).resolve()),
                                                  "--project", str(project), "--out", str(out)])
    raw = {"n_test": int(len(te)), "nn_dist_km": {"median": float(np.median(d)), "p90": float(np.quantile(d, 0.9))},
           "semivariogram": {"lags_km": lags.tolist(), "gamma": gamma.tolist(), "sill": sill},
           "practical_range_km": rng_km, "fraction_test_inside_range": frac_inside,
           "block_km": block_km, "r2_declared": declared["r2"], "r2_random_cv": r2_random,
           "r2_blocked_cv": r2_blocked, "optimism_r2": optimism, "command": command}
    raw_path = out / "raw" / "leakage_synthetic.json"
    raw_path.write_text(json.dumps(raw, indent=1), encoding="utf-8")

    findings = []
    if frac_inside > 0.5 and optimism > 0.05:
        findings.append({
            "id": "LEAK-01", "severity": "block",
            "description": (f"{frac_inside:.0%} of test samples lie within the {rng_km:.0f} km autocorrelation range "
                            f"of the training data (median nearest-train distance {np.median(d):.2f} km). "
                            f"The same model scores R2 {r2_random:.3f} under random CV and {r2_blocked:.3f} under "
                            f"{block_km:.0f} km spatial blocks: the declared split overstates R2 by {optimism:.3f}."),
            "evidence": {"file": str(raw_path), "field_or_line": "fraction_test_inside_range, optimism_r2",
                         "command": command},
            "fix": f"Evaluate with spatially blocked CV (blocks >= {block_km:.0f} km) and report that R2; "
                   f"describe the random split as interpolation skill, not independent-test skill.",
            "supports_claim": True})
    artifact = {"front": "data-spatial-leakage", "target": str(project / "results" / "metrics.json"),
                "verdict": "block" if findings else "pass", "findings": findings,
                "coverage": {"verified": ["nearest-train distance of every test sample",
                                          "practical range of the covariate residual",
                                          "random vs spatially blocked 5-fold CV with the project model"],
                             "not_verified": ["buffered blocks", "error curve by distance band"],
                             "reason": "not needed to decide the verdict on this target; listed for round 2"},
                "file": str(out / "data-spatial-leakage.json")}
    (out / "data-spatial-leakage.json").write_text(json.dumps(artifact, indent=1), encoding="utf-8")
    return artifact, raw


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    art, raw = run(a.project, a.out)
    print(json.dumps({"verdict": art["verdict"], "range_km": raw["practical_range_km"],
                      "fraction_inside": round(raw["fraction_test_inside_range"], 3),
                      "r2_random_cv": round(raw["r2_random_cv"], 3), "r2_blocked_cv": round(raw["r2_blocked_cv"], 3)}))


if __name__ == "__main__":
    main()
