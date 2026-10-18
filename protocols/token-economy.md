# Protocol: token economy

A campaign convenes many agents. Economy is not a matter of asking agents to
be brief; it holds only where a mechanism enforces it. Each rule below names
its mechanism.

## E1. Model and effort explicit per agent
Every agent declares `model` and `effort` in its frontmatter; nothing inherits
the session default. Mechanical roles (opening a thread, voting with a short
rubric) use a small model; coordinators that judge many artifacts use a large
one. Mechanism: `tests/test_example_and_agents.py` fails if an agent lacks
these keys.

## E2. Do not switch model or effort in the middle of a campaign
Switching invalidates the prompt cache and makes votes incomparable.

## E3. Stable prompt prefix
Every prompt of a campaign starts with the same header (thread path, rules,
project, target, paths) and ends with what varies (front name, finding). The
stable prefix is what the prompt cache can reuse across parallel agents.

## E4. Artifact on disk instead of text in the conversation
Agents write JSON artifacts and hand over paths. The orchestrating session
passes paths between phases and never pastes artifact content.

## E5. Schema for every structured output
Fronts, votes and coverage share the schemas enforced by `tools/campaign.py
validate`; free-form output that has to be re-parsed costs a second call.

## E6. Memory before judgment
Before starting a front, read what earlier audits of the same target already
concluded (the synthesis of previous threads). Repeating a recorded mistake is
a process failure, not bad luck.

## E7. An already audited target does not run again
`thread.py open` refuses a target whose content hash was already closed in a
thread; `--force "reason"` is the only way around it, and the reason is kept.

## E8. The coordinator reads the synthesis, never raw material
Coordinators judge artifacts. If a judgment needs raw material, that is a
round-2 item for a front.

## E9. Budget per thread
A thread may carry a token budget; `thread.py total` reports the fraction
used, and at 80% the coordinator closes the round or asks for more.

## E10. Declared campaign size
A partial campaign (a subset of fronts) is declared at the top of the
consolidated report, so that a cheap campaign is never mistaken for a full one.

## E11. Filter verbose tool output before it reaches the context
Scripts write raw output to `<output_dir>/raw/` and print a short summary; the
agent reads the summary and opens the raw file only for the field it needs.

## E12. Side-effect skills are not auto-invoked
Campaign skills set `disable-model-invocation: true`: a campaign starts when a
person asks for it, never because a model decided to.

## How to measure
`tools/query_events.py by-agent` (tokens and events per agent) and `by-day`,
with the saved query file cited next to every number.
