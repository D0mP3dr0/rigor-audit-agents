# Rigor audit agents for ML and geoscience pipelines

A framework of Claude Code subagents, campaign skills, protocols and small
tools for **auditing the rigor of machine-learning and geoscience pipelines**
before their numbers are quoted as claims.

It is an audit framework. It does not write or review papers, and it does not
replace human review.

## The problem

Many ML results do not survive an audit. The test set sits a few hundred
metres from the training set in a spatially autocorrelated field. The seed in
the config never reaches the random generator. The proposed model got a
hyperparameter search and the baselines got defaults. The equation in the text
and the loss in the code differ by a sign. None of these is visible in the
headline metric, and each of them can be found by a script that someone
actually runs.

This framework turns that audit into a repeatable procedure: many narrow
agents, each asking one question of one target and answering with a JSON
artifact backed by a command, plus mechanical rules that do not depend on any
agent's judgment.

## How it works: the pyramid

```
            coordinator          judges only artifacts, writes the consolidated report
                 |
        coverage critic          "what was not covered?"
                 |
   adversarial verification      3 independent votes per blocking finding
                 |
   front  front  front  front    one question, one target, one JSON artifact each
```

1. **Fronts** (`agents/data-*`, `ml-*`, `physics-*`, `geo-*`, `math-*`,
   `arch-*`). Each front has a single question (for example "does the split
   isolate the test set from spatial autocorrelation, and by how much does it
   overestimate if not?"), works script first, and writes one artifact:
   `{front, target, verdict, findings[{id, severity, description, evidence{file,
   field_or_line, command}, fix, supports_claim}], coverage{verified,
   not_verified, reason}}`.
2. **Adversarial verification** (`agents/critic-verifier.md`). Every blocking
   finding, and every finding that supports the claim, goes to three
   independent verifiers who try to refute it by re-execution. The rule is
   applied by `tools/campaign.py tally`, not by an agent: a refutation counts
   only with an executed command; quorum is two valid votes; a finding without
   quorum survives as "not verified", never as refuted.
3. **Coverage critic** (`agents/critic-coverage.md`). Reads the front matrix
   and the artifacts, and says only what was not covered.
4. **Coordinator** (`agents/coord-*.md`). Reads artifacts, votes, the tally
   and the thread, never raw material; decides final severities; writes the
   consolidated report and the thread synthesis.

Everything goes through an **audit thread** (`tools/thread.py`): posts are
files, the coordinator writes a short synthesis, and the thread cannot be
closed while a blocking post is not cited in it. A target that was already
audited and has not changed (content hash) is refused unless a reason is given.

## Teams and campaigns

| skill | fronts |
|---|---|
| `/audit-data` | provenance, data contract, spatial leakage, ETL reproducibility |
| `/audit-ml` | seeds, baseline fairness, ablation, experiment card, silent bugs, spatial leakage |
| `/audit-physics` | spatial reference (geodesy), hydrology, sensor physics, order of magnitude |
| `/audit-geo` | spatial reference, sensor alignment, clipping and sampling, reference products |
| `/audit-math` | equations, statistics of the claim, graphs and spectra, invariance |
| `/audit-architecture` | dependency map, single point of failure, file review, test coverage, technical debt, security, operations |

Fronts shared between teams (spatial leakage, spatial reference) exist once
and serve both. A separate `traceability-auditor` walks the chain from raw data
to a quoted number by `sha256sum` and script.

## Repository layout

```
agents/      subagent definitions (frontmatter: name, description, tools, model, effort, maxTurns)
skills/      one campaign per team (fan-out, 3-vote verification, coverage, coordinator)
tools/       thread.py, campaign.py, experiment_registry.py, event_log.py, query_events.py
protocols/   thread, traceability, token economy, robustness, change
examples/    synthetic geospatial ML project with two planted defects, and a walkthrough
tests/       tests for the tools, the agent definitions and the example
```

The tools use only the Python standard library. The example needs NumPy.
DuckDB is optional for `query_events.py`; without it the named queries run in
pure Python.

## Installation

Into a project that you open with Claude Code:

```bash
./install.sh /path/to/your/project
```

This copies `agents/` to `.claude/agents/`, `skills/` to `.claude/skills/`
and `tools/` to `.claude/audit-tools/`. To log every finished subagent and be
warned when an audit agent finishes without an artifact, add to
`.claude/settings.json`:

```json
{
  "hooks": {
    "SubagentStop": [
      {"hooks": [{"type": "command", "command": "python3 .claude/audit-tools/event_log.py --root .audit hook"}]}
    ]
  }
}
```

Then, in a session, run a campaign on one target, for example:

```
/audit-ml project=myproj target=results/v3/metrics.json paths=src/,data/,results/v3/ output_dir=audit/v3-ml
```

## Try it without any agent

```bash
python3 examples/synthetic_geo_ml/run_walkthrough.py --work /tmp/walkthrough
python3 -m pytest tests
```

The walkthrough runs the mechanical half of a campaign on the synthetic
project (reference front scripts, scripted re-execution votes, tally, thread)
and finds both planted defects. See
[`examples/synthetic_geo_ml/WALKTHROUGH.md`](examples/synthetic_geo_ml/WALKTHROUGH.md).

## Limits

- The agents audit; they do not replace human review. A clean campaign is
  evidence of what was checked and how, not proof that the work is correct.
- Agents can be wrong in both directions. The design reduces that risk
  (script-backed evidence, execution-only refutation, three votes, a coverage
  critic) but does not remove it. Read the artifacts, not only the verdict.
- Fronts are generic. Domain thresholds (what counts as an acceptable
  autocorrelation range, a plausible error) must come from the project and its
  literature, passed as inputs.
- Fronts never launch long training. Anything that needs a full retrain is
  reported with the command that would run it.
- Coverage is declared, not implied: an incomplete campaign says so.

## License and citation

MIT, see [LICENSE](LICENSE). If you use this framework, please cite it using
[CITATION.cff](CITATION.cff).
