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
`src/core/logging/`; generated output is written to `debug/logs/` and
`debug/reports/`.

## Acceptance Criteria

- [ ] A Logger is implemented and is the single output channel for the toolkit.
- [ ] A Session Manager tracks per-session diagnostics.
- [ ] A Report Writer emits reports to `debug/reports/`.
- [ ] Console output and log files are produced; log files are written to
  `debug/logs/`.
- [ ] No component bypasses the framework Logger with direct prints.

## Deliverables

- Logger
- Session Manager
- Report Writer
- Console output
- Log files

## References

- 03_ENGINEERING/DIAGNOSTICS.md
