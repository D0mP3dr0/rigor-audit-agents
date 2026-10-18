# Example project under audit (synthetic)

A toy geospatial regression: predict a terrain-related target at scattered
sample points from coordinates and two covariates, with a k-nearest-neighbour
regressor.

The claim the project makes, as it would appear in a report:

> The model predicts the target on an independent held-out test set with the
> R2 reported in `results/metrics.json`. All runs use seed 42 (`config.json`).

Reproduce:

```bash
python generate_data.py --out data
python train.py
```

This project is deliberately flawed. Do not read `../WALKTHROUGH.md` before
trying the campaign on it if you want to see the agents find the flaws.
