# Protocol: change

The audit process itself changes: a front gets a new check, a threshold moves,
a hook starts blocking instead of warning. Changing the auditor silently is
the fastest way to make old and new audits incomparable.

## C1. Decision record before touching the real file
Every relevant change to agents, skills, protocols or hooks starts as a short
decision record (title, status, context, decision, consequences), one file per
decision, before the change is applied.

## C2. Canary before full rollout
Apply the change first to one low-risk, frequently used agent for a short
cycle; record "in canary on agent X since <date>, full rollout planned for
<date>"; then propagate.

## C3. Backups named with date and reason, and a tested rollback
Before editing an agent or hook, keep `<file>.bak-<YYYY-MM-DD>-<reason>`, and
keep a rollback command that restores it without having to remember paths.
Test the rollback once on purpose.

## C4. No structural change inside a critical window
Do not change the audit process right before a deadline that depends on its
output. Smoke-test the change before its first real use.

## C5. Switches by configuration for critical hooks
Critical hooks can be switched on and off by configuration, without editing
code, and a start-of-session check reports any switch that is off. Gates whose
whole purpose is to stop the session should not have a switch that an agent
could flip.

## C6. Smoke test before "done"
No change is done without a recorded smoke test: the test suite of this
repository, plus the scenarios of the gate that changed (for example, "delete
the artifact on purpose and check that the hook warns").

## C7. Every change is a viability test
The change enters `tools/experiment_registry.py` with an exit question. It
becomes permanent only with a verdict backed by the event log.
