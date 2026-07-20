# TASK-007 — Postprocessing Pipeline

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-007                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement the **Output Pipeline** (`src/modules/postprocessing/`) — the stage
pipeline that runs after migration transformations to validate, persist, and
render the session bundle. It is built fluently over the shared
`MigrationContext` and composed into the chained pipeline by the orchestrator.
Migration logic is out of scope.

## Acceptance Criteria

- [ ] The Output Pipeline is built fluently: `OutputPipeline().use(...)`.
- [ ] Migrated components are validated against the required rules
  (`ValidateMigration`).
- [ ] Writeback persists results through the Dataverse client only, in Migrate
  mode (`Writeback`).
- [ ] A terminal `GenerateMigrationReport` step renders the customer-facing
  `migration_report.md` from the `MigrationContext` collectors, via the Reporter
  service (no direct file I/O in steps).
- [ ] Output lands in the single session bundle `output/session-<timestamp>/`
  (`migration_report.md` + `session.log`).
- [ ] No migration transformation logic exists in this stage.

## Deliverables

- Output Pipeline (fluent, over `MigrationContext`)
- `ValidateMigration` step
- `Writeback` step (Migrate mode only)
- `GenerateMigrationReport` step

## References

- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/SERVICES.md
- 03_ENGINEERING/DIAGNOSTICS.md
