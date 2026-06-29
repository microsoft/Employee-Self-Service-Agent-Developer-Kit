# TASK-007 — Postprocessing Pipeline

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-007                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement post-processing — the stages that run after migration transformations
to validate, persist, and report results. Implemented under
`src/modules/postprocessing/`. Migration logic is out of scope.

## Acceptance Criteria

- [ ] Migrated components are validated against the required rules.
- [ ] Writeback persists results through the Dataverse client only.
- [ ] Reports are generated through the Report Writer to `debug/reports/`.
- [ ] No migration transformation logic exists in this stage.

## Deliverables

- Validation
- Writeback
- Report generation

## References

- 02_ARCHITECTURE/SERVICES.md
- 03_ENGINEERING/DIAGNOSTICS.md
