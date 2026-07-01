# TASK-005 — Diagnostics Framework

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-005                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement the diagnostics infrastructure. All toolkit output shall flow through
the framework Logger; direct `print()` is prohibited. Logging code lives in
`src/core/logging/`. Each execution produces one timestamped **session bundle**
under `output/session-<timestamp>/` containing exactly two files:
`migration_report.md` (customer-facing) and `session.log` (ESS-engineer
diagnostics). Steps accumulate into the `MigrationContext` collectors; the
Reporter renders the report — steps never write files.

## Acceptance Criteria

- [ ] A Logger is implemented and is the single output channel for the toolkit;
  it streams `session.log` live across all stages.
- [ ] A Session Manager tracks per-session diagnostics and owns the
  `output/session-<timestamp>/` bundle folder.
- [ ] A Reporter renders `migration_report.md` (summary, changes, warnings
  sections) from the `MigrationContext` collectors.
- [ ] `MigrationContext` exposes the diagnostic collectors (`Logs`, `Warnings`,
  `Errors`, `Changes`) that steps append to.
- [ ] No component bypasses the framework Logger/Reporter with direct prints or
  file writes.

## Deliverables

- Logger (streams `session.log`)
- Session Manager (owns the session bundle)
- Reporter (renders `migration_report.md`)
- MigrationContext diagnostic collectors

## References

- 03_ENGINEERING/DIAGNOSTICS.md
