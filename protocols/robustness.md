# Protocol: robustness

Multi-agent systems fail in recognizable ways: an agent stops without
producing anything, an agent "finishes" without noticing the task is not
done, a loop never ends, a verifier quietly drops what it could not check.
Each rule here closes one of those holes.

## R1. Complete frontmatter per agent
`tools`, `model`, `effort` and `maxTurns` are explicit. Fronts and critics do
not have the `Agent` tool: only the orchestrating session convenes agents.
Mechanism: the agent test suite.

## R2. Artifact first, checked when the agent stops
Every audit agent writes its artifact before answering. The `SubagentStop`
hook in `tools/event_log.py` warns when an audit agent finishes without
writing any file, and `query_events.py no-artifact` lists those cases.

## R3. Failure is counted, never retried forever
A front that returns nothing is a process failure recorded in the
consolidated report. Retry a failed front at most a fixed number of times;
after that it is reported as missing, not silently re-launched.

## R4. Explicit resume after interruption
Usage limits and interruptions are not assumed to resume by themselves. The
campaign's state lives on disk (thread, artifacts, votes), so a new session
resumes from the files rather than from memory.

## R5. Hard ceiling for anything that forces continuation
A hook or loop that forces an agent to continue has a counter and a hard
ceiling; at the ceiling it gives up and reports, rather than looping.

## R6. Termination checkable by script
Every task has an end condition a script can check: the artifact exists and
passes `campaign.py validate`, the thread passes `thread.py check`. "When the
agent thinks it is done" is not an end condition.

## R7. Success stamp with effect for scheduled jobs
An exit code of 0 proves nothing. Scheduled jobs write a stamp with their
effect (files written, counts, hashes), and an independent check reads it.

## R8. Dry run, hard budget and atomic checkpoints for long training
Long training runs one batch first, runs under a hard time or epoch budget
with automatic termination, and writes checkpoints atomically (temporary file,
then rename). Audit fronts never launch long training at all.

## R9. Secrets never in plain files
Credentials come from the environment or a keyring. A secret scanner runs over
the repository before every release, and its report gives locations, never
values.

## R10. Refutation requires execution
A verifier that could not run the evidence command answers "not verifiable";
it never refutes. Without a quorum of valid votes, a finding is kept as not
verified. Mechanism: `campaign.py tally`.

## R11. Blameless postmortem
Every real incident becomes a dated, blameless postmortem: what happened,
timeline, contributing causes, preventive action. A postmortem that proposes a
process change links to the change record (see `change.md`).

## R12. A cold copy of citable artifacts
A synchronized replica is one copy. Citable artifacts need a cold copy as well,
tested by periodic restore with file counts and hashes compared.
