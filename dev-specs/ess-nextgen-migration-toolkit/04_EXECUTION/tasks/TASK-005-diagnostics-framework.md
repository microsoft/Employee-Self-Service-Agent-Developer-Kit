# TASK-005 — Diagnostics Framework

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-005                  |
| Workstream | 0 — Repository Foundation |
| Status     | ACTIVE                      |
| Consumes   | —                         |

## Description

Implement the diagnostics infrastructure. All toolkit output shall flow through
the framework Logger; direct `print()` is prohibited. Logging code lives in
`src/core/logging/`. Each execution produces one timestamped **session bundle**
under `output/session-<timestamp>/` containing exactly two files:
`migration_report.md` (customer-facing) and `session.log` (ESS-engineer
diagnostics). Steps accumulate into the `MigrationContext` collectors; the
Reporter renders the report — steps never write files.

The Logger has two responsibilities that define this framework:

1. **Transcript capture** — when the Logger initializes at the application entry
   point (before the pipeline runs), it installs a **stdout/stderr tee** so that
   from that point on **every byte written to the CLI** is mirrored into
   `session.log`. `session.log` is therefore a complete, replayable transcript of
   the run, not just selected log lines. Capture begins at the **Python app
   entry** (migration run only); shell provisioning output is out of scope.
2. **Two channels** — the Logger exposes an **engineer channel**
   (`LogDebug`/`LogInfo`/`LogWarning`/`LogError`) that prints to the CLI as usual
   (and is mirrored to `session.log` by the tee), and a **customer channel**
   (`LogChange`/`LogAdvisory`) that does **not** touch the CLI or `session.log`
   but instead appends structured entries to the report model (the
   `MigrationContext` collectors) that the Reporter later renders into the fancy
   `migration_report.md`. `LogChange` records a successful transformation
   (`ChangeEntry` → `context.Changes` → `## Changes`); `LogAdvisory` records a
   manual-review advisory (`DiagnosticEntry` → `context.Warnings`/`Errors`/`Logs`
   by `severity` → `## Warnings — Manual Review Required`).

## Acceptance Criteria

- [ ] A Logger is implemented and is the single output channel for the toolkit.
- [ ] On initialization at the application entry, the Logger installs a
  stdout/stderr tee so `session.log` captures the **entire CLI transcript** of the
  run (Logger output, incidental library output, and tracebacks alike).
- [ ] The Logger exposes an **engineer channel** (`LogDebug`/`LogInfo`/… →
  console + `session.log`, honoring log levels) and a **customer channel**
  (`LogChange`/`LogAdvisory` → report model only, never console/`session.log`).
- [ ] A Session Manager tracks per-session diagnostics and owns the
  `output/session-<timestamp>/` bundle folder.
- [ ] A Reporter renders `migration_report.md` (summary, changes, warnings
  sections) from the `MigrationContext` collectors (the report model).
- [ ] `MigrationContext` exposes the diagnostic collectors (`Logs`, `Warnings`,
  `Errors`, `Changes`) that steps append to.
- [ ] No component bypasses the framework Logger/Reporter with direct prints or
  file writes.

## Deliverables

- Logger — dual-channel (engineer + customer) with stdout/stderr transcript tee
- Session Manager (owns the session bundle)
- Reporter (renders `migration_report.md` from the report model)
- MigrationContext diagnostic collectors

## References

- 03_ENGINEERING/DIAGNOSTICS.md
