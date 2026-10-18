---
name: audit-data
description: Rigor-audit campaign of the data team on ONE target - fan-out of 4 fronts as subagents, adversarial verification by three votes per blocking finding, coverage critic, and a coordinator that judges only artifacts. Use before a number from this target is quoted as a claim.
disable-model-invocation: true
---

# Campaign: data team

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
| provenance | `data-provenance` | every link raw -> used data has a hash checked on disk and a regeneration command |
| contract | `data-contract` | contract script ran over the dataset (or a declared sample) and every violation has a severity |
| spatial-leakage | `data-spatial-leakage` | test-train distance compared with the autocorrelation range by script, with a number |
| etl-reproducibility | `data-etl-reproducibility` | ETL mapped (inputs+hash, command, versions, outputs+hash); cheap stage re-run and compared |

If `fronts` restricts the matrix, say so at the top of the consolidated
report: a partial campaign is declared, never implied.

## Phases
0. **Open the thread.** Run
   `<python> <tools_dir>/thread.py open --key data-<target-slug> --mission "<question of the campaign>" --coordinator coord-data --target <target> [--budget-tokens N] [--force "<reason>"]`.
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
5. **Coordinate.** Launch `coord-data` with `output_dir`, `thread`, `tools_dir`.
   It reads only artifacts, writes `<output_dir>/consolidated_data.md`
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
