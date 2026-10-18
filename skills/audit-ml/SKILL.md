---
name: audit-ml
description: Rigor-audit campaign of the machine-learning team on ONE target - fan-out of 6 fronts as subagents, adversarial verification by three votes per blocking finding, coverage critic, and a coordinator that judges only artifacts. Use before a number from this target is quoted as a claim.
disable-model-invocation: true
---

# Campaign: machine-learning team

You are running a rigor-audit campaign. The main session ORCHESTRATES: it
convenes agents, runs the mechanical tools and passes file paths. It does not
audit raw material itself and does not summarize findings from memory.

## Arguments
`project`, `target`, `paths` (read-only), `output_dir`, `python` (default
`python3`), `tools_dir` (default `.claude/audit-tools`), `fronts` (optional
subset), `rerun_budget_min` (default 20), `budget_tokens` (optional),
`force` (optional reason to re-audit an unchanged target).

## Front matrix
| front | agent | done when |
|---|---|---|
| seed-reproducibility | `ml-seed-reproducibility` | seed fixed in the EFFECTIVE config and used by every generator; same-seed rerun compared by script when within budget |
| baseline-fairness | `ml-baseline-fairness` | every baseline has the same tuning budget and training time as the proposed model; parameter counts reported |
| ablation | `ml-ablation` | component x run x metric matrix built from existing results; structural ablation present or flagged missing |
| experiment-card | `ml-experiment-card` | complete card (dataset+version+hash, split, seed, hyperparameters, hardware, time) extracted from primary sources |
| silent-bug | `ml-silent-bug` | one-batch overfit, gradient flow, single normalization, right split for the metric, label leakage, loss shapes |
| spatial-leakage | `data-spatial-leakage` | shared with the data team: test-train distance against autocorrelation range |

If `fronts` restricts the matrix, say so at the top of the consolidated
report: a partial campaign is declared, never implied.

## Phases
0. **Open the thread.** Run
   `<python> <tools_dir>/thread.py open --key ml-<target-slug> --mission "<question of the campaign>" --coordinator coord-ml --target <target> [--budget-tokens N] [--force "<reason>"]`.
   If it prints `REFUSED`, stop: the target was already audited without
   change, or a thread is open. Do not work around it.
1. **Fronts (fan-out).** In ONE message, launch one subagent per front with
   the Agent tool, in parallel. Every prompt starts with the same stable
   header (thread path first, then these rules, then project, target, paths,
   output_dir, python, tools_dir, rerun_budget_min) and ends with the front
   name and its done criterion. Each front writes `<output_dir>/<agent>.json`
   and posts to the thread.
2. **Validate.** Run `<python> <tools_dir>/campaign.py validate <output_dir>/*.json`.
   A front whose artifact is missing or invalid is a process failure: record
   it; do not rewrite the artifact for the agent.
3. **Verify (3 votes).** Run `<python> <tools_dir>/campaign.py to-vote --out-dir <output_dir>`.
   For each listed finding (every `block` and every `supports_claim`),
   launch three `critic-verifier` subagents in parallel (vote 1, 2, 3) with
   the finding JSON. Then run
   `<python> <tools_dir>/campaign.py tally --out-dir <output_dir>`.
   The tally, not an agent, decides what survives: refutation needs an
   executed command; quorum is 2 of 3; a finding without quorum survives as
   NOT VERIFIED.
4. **Coverage.** Launch `critic-coverage` with the front matrix above and
   `output_dir`.
5. **Coordinate.** Launch `coord-ml` with `output_dir`, `thread`, `tools_dir`.
   It reads only artifacts, writes `<output_dir>/consolidated_ml.md`
   and the thread synthesis, and runs `thread.py check` until clean.
6. **Close the thread.** Run `thread.py check`; if clean, `thread.py close`.
   If not, do not close: report the problems as printed.

## Rules
- Every subagent call declares its model and effort explicitly (they are in
  each agent's frontmatter; do not override them mid-campaign).
- Artifacts on disk, not text in the conversation: pass paths between
  phases, never pasted content.
- Numbers about the campaign itself (fronts failed, tokens per agent) come
  from `query_events.py`, with the saved query file named next to the number.
- The campaign audits. It does not replace human review of the work, and its
  report is not evidence that the work is correct; it is evidence of what was
  checked and how.
