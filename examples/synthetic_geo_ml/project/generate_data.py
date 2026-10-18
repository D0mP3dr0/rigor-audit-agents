"""Generate the synthetic geospatial dataset of the example project.

Samples are scattered over a 100 km x 100 km square. The target depends on two
observed covariates (an elevation-like field and a wetness-like field) and on a
latent residual field that is spatially smooth and NOT observed. That latent
field is what makes neighbouring samples similar beyond what the covariates
explain, i.e. it creates spatial autocorrelation in the residual.

The data generator itself is seeded: the dataset is reproducible and hashed in
data/MANIFEST.json.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

DOMAIN_KM = 100.0


def smooth_field(rng, xy, n_bumps, scale_km):
    """Sum of Gaussian bumps with random centres and amplitudes, standardized."""
    centres = rng.uniform(0, DOMAIN_KM, size=(n_bumps, 2))
    amps = rng.normal(size=n_bumps)
    d2 = ((xy[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
    f = (amps[None, :] * np.exp(-d2 / (2 * scale_km ** 2))).sum(1)
    return (f - f.mean()) / f.std()


def generate(n, seed):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, DOMAIN_KM, size=(n, 2))
    elev = smooth_field(rng, xy, 25, 20.0)
    wetness = -0.6 * elev + 0.5 * smooth_field(rng, xy, 40, 12.0)
    noise_cov = rng.normal(size=n)                 # an uninformative covariate
    latent = smooth_field(rng, xy, 120, 6.0)       # unobserved, spatially autocorrelated
    target = 2.0 * elev + 1.0 * wetness + 1.5 * latent + 0.2 * rng.normal(size=n)
    return xy, elev, wetness, noise_cov, target


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data")
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    xy, elev, wet, noise, y = generate(a.n, a.seed)
    csv_path = out / "samples.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "x_km", "y_km", "elev", "wetness", "noise", "target"])
        for i in range(a.n):
            w.writerow([i, f"{xy[i, 0]:.4f}", f"{xy[i, 1]:.4f}", f"{elev[i]:.6f}", f"{wet[i]:.6f}",
                        f"{noise[i]:.6f}", f"{y[i]:.6f}"])
    manifest = {"files": [{"path": "samples.csv", "sha256": sha256(csv_path), "rows": a.n}],
                "regenerated_by": f"generate_data.py --out <dir> --n {a.n} --seed {a.seed}",
                "crs": "local planar, kilometres"}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(csv_path)


if __name__ == "__main__":
    main()
