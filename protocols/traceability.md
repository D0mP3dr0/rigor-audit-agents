# Protocol: traceability

This protocol joins two things that are usually separate: "the machine records
what it did" (the event log) and "the number quoted in a report can be traced
back to its source" (manifests and hashes). A number is citable only when
both chains hold.

## T1. A citable number comes from a script, never from a log read by eye

The number is recomputed from a result file by a script, and the script's
output is what gets quoted. An audit script counts as evidence only after
someone who did not write it has re-run it and read it; until then the number
is provisional. In this framework, the three adversarial votes of
`critic-verifier` are that re-execution for findings, and `traceability-auditor`
is that re-execution for numbers.

## T2. Manifests with hashes are the spine

Every file between raw data and the quoted number appears in a manifest with
its sha256 and the command that regenerates it. The chain is:

raw data -> processed data -> run (effective config, seed, commit) ->
evaluation index (hash of the sample ids) -> result file -> quoted number.

A broken link close to the number (result file, evaluation index) blocks the
number; a broken link further upstream is a warning to fix before release.
Releasable packages also carry a `CITATION.cff` and, ideally, an archived,
versioned DOI.

## T3. Every report carries the id of the event that produced it

A consolidated report or a quoted number names the artifact it was copied
from and the `event_id` and sha256 recorded by `tools/event_log.py`. Months
later this answers which agent, on which input, produced each number.

## T4. Numbers about the process come from saved queries

How many fronts failed, which agents finished without an artifact, how many
tokens a campaign used: these come from `tools/query_events.py`, which saves
every query and its result to a file. The number in the report points to that
file.

## T5. Every process change is a test with an exit question

A new gate, front or rule enters `tools/experiment_registry.py` as an open
test with an entry date and an exit question (what must be true for it to
become permanent, or be withdrawn). The periodic review gives each open test a
verdict backed by the event log; `experiment_registry.py stale` reports tests
left open too long.

## T6. Periodic review checklist

Each periodic review of the audit process answers six items, each with the
saved query that supports it: what changed, what it cost, what failed, what is
still under test, what was withdrawn, and which query supports each number.
