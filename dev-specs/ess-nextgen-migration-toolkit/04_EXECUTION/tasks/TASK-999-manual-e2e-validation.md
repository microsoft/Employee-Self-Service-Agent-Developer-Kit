# TASK-999 — Manual End-to-End Validation

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-999                  |
| Workstream | 3 — Final Validation      |
| Status     | BLOCKED                      |
| Consumes   | —                         |

## Description

Perform the final manual end-to-end validation and sanity check of a real
migration. A human operator runs the toolkit against a real ESS Agent in a
target environment, exercises both preview and writeback modes, and confirms the
migrated Declarative Agent behaves as expected. This is the last manual sign-off
gate and is performed after the Migration Rules land; it complements the
automated `TASK-009 — End-to-End Framework Validation` (which exercises the
framework with no-op steps). No new toolkit code is produced.

## Acceptance Criteria

- [ ] A human operator runs a full migration end-to-end against a real ESS Agent.
- [ ] Preview mode is validated manually with no writeback side effects observed.
- [ ] Writeback mode is validated manually and the migrated agent is inspected in
  the target environment.
- [ ] Migration outcomes are sanity-checked against the expected transformations
  defined in `01_PRODUCT/MIGRATION_RULES.md`.
- [ ] Diagnostics and reports are reviewed for the run.
- [ ] Findings are recorded as a manual validation sign-off.

## Deliverables

- Manual end-to-end migration run
- Preview mode sanity check
- Writeback mode sanity check
- Manual validation sign-off notes

## References

- 01_PRODUCT/CUSTOMER_JOURNEY.md
- 01_PRODUCT/MIGRATION_MODES.md
- 03_ENGINEERING/TESTING.md
