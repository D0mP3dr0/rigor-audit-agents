# Changelog

## 0.1.0

First public release.

- 35 subagent definitions: 27 fronts across data, ML, physics, geoprocessing,
  mathematics and software architecture; adversarial verifier; coverage critic;
  traceability auditor; five coordinators.
- Six campaign skills (`/audit-data`, `/audit-ml`, `/audit-physics`,
  `/audit-geo`, `/audit-math`, `/audit-architecture`).
- Tools: `thread.py` (file-based audit thread with synthesis, check, close and
  refusal of unchanged targets), `campaign.py` (artifact validation, findings
  to vote, vote tally), `experiment_registry.py` (viability tests with exit
  questions), `event_log.py` (event log and `SubagentStop` hook),
  `query_events.py` (saved queries, DuckDB optional).
- Protocols: thread, traceability, token economy, robustness, change.
- Synthetic geospatial example with a planted spatial leakage and a planted
  unseeded split, a scripted walkthrough, and tests.
