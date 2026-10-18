# Walkthrough: an ML campaign on a flawed synthetic project

The project in `project/` is a small geospatial regression: a
k-nearest-neighbour model predicts a target at 1,500 scattered points from
coordinates and two covariates. Its report says the model reaches a given R2
"on an independent held-out test set" and that "all runs use seed 42".

Two defects are planted:

1. **Spatial leakage.** The target contains a smooth latent field that the
   covariates do not explain (`generate_data.py`), and the test set is a
   random 25% of the points (`train.py`). Test points sit next to training
   points that share the same latent value, so the held-out R2 measures
   interpolation, not skill on independent ground.
2. **Seed declared but not effective.** `config.json` sets `seed: 42` and
   `metrics.json` reports it, but the split uses `np.random.default_rng()`
   with no argument. Every run draws a different test set.

## Running the campaign with agents

Install the framework into the folder that contains the example (see the main
README), then ask for the ML campaign, restricted to the two fronts that apply:

```
/audit-ml project=synthetic target=project/results/metrics.json
          paths=project/ output_dir=audit_out
          fronts=seed-reproducibility,spatial-leakage
```

The session opens the thread, launches the two fronts in parallel, validates
their artifacts, sends each blocking finding to three `critic-verifier`
agents, tallies the votes, asks `critic-coverage` what was left out, and hands
everything to `coord-ml`, which writes `audit_out/consolidated_ml.md` and the
thread synthesis before the thread is closed.

## Running the mechanical half without any agent

`run_walkthrough.py` does the same steps with scripts in place of agents: the
two fronts are the reference scripts in `reference_audit/` (what a front agent
would write), and each verifier vote re-executes the finding's evidence
command into its own directory and checks that the finding reappears.

```bash
python3 run_walkthrough.py --work /tmp/walkthrough
```

Output from one run (`walkthrough_summary.json`; values from the unseeded
split differ on every run, which is the point of defect 2):

| quantity | value |
|---|---|
| held-out R2 reported by the project | 0.768 |
| practical range of the residual autocorrelation | 13 km |
| test points closer to a training point than that range | 100% |
| R2, same model, random 5-fold CV | 0.782 |
| R2, same model, 5-fold CV on 20 km spatial blocks | 0.238 |
| unseeded generator found by AST | `train.py`, line 57 |
| R2 of two runs with the same config | 0.773, 0.758 |

Findings and their fate:

| id | front | severity | votes | status |
|---|---|---|---|---|
| LEAK-01 | data-spatial-leakage | block | 3 confirmed | survives |
| SEED-01 | ml-seed-reproducibility | block | 3 confirmed | survives |
| SEED-02 | ml-seed-reproducibility | block | 3 confirmed | survives |

The thread passes `thread.py check` and is closed; a second
`thread.py open` on the unchanged project is refused as already audited.
`critic-coverage.json` declares coverage `partial`, because four of the six ML
fronts were outside this example. The event log holds one event per step, and
`query_events.py by-agent` counts them from a saved query.

## What the fix looks like

Pass `cfg["seed"]` to the generator, evaluate with spatially blocked
cross-validation (blocks of at least 20 km here), report the mean and spread
over several seeds, and describe the random-split number, if kept, as
interpolation skill. Re-running the campaign on the changed project is allowed
because its content hash changed.
