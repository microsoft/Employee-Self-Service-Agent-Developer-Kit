# TASK-007 — Postprocessing Pipeline (Validation + Writeback + Report)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-007                  |
| Workstream | 0 — Repository Foundation |
| Status     | BLOCKED                      |
| Consumes   | TASK-015, TASK-004, TASK-005 |

## Description

Implement the **Output Pipeline** (`src/modules/postprocessing/`) — the stage
pipeline that runs after migration transformations to validate, persist, and
render the session bundle.

TASK-015 delivers an empty pass-through output stage. This task replaces it with
the real steps:

1. **ValidateMigration** — verify migrated components meet post-conditions
   (runs in both modes).
2. **Writeback** — persist transformed components back to Dataverse via the
   DataverseClient (TASK-004). **WRITEBACK mode only** —
   `supported_modes=("WRITEBACK",)`, auto-skipped in READONLY.
3. **GenerateMigrationReport** — terminal step that renders the customer-facing
   `migration_report.md` from `MigrationContext` collectors via the Reporter
   service (runs in both modes).

### Architecture constraints

- All steps are `MigrationPipelineStep` subclasses.
- `Writeback` declares `supported_modes=("WRITEBACK",)` — this is the
  READONLY/WRITEBACK gate in action.
- `ValidateMigration` and `GenerateMigrationReport` declare
  `supported_modes=("READONLY", "WRITEBACK")`.
- Report rendering calls `Reporter(logger.session_manager).render(ctx)` — the
  step does not write files directly (DIAG-005).
- Output lands in `output/session-<timestamp>/` (two-file bundle).
- No migration transformation logic in this stage.

## Acceptance Criteria

- [ ] `ValidateMigration` step verifies post-conditions on migrated components.
- [ ] `Writeback` step persists results via DataverseClient — **WRITEBACK only**.
- [ ] `Writeback` is auto-skipped in READONLY mode (mode-gating via
  `MigrationPipelineStep.can_execute`).
- [ ] `GenerateMigrationReport` renders `migration_report.md` via Reporter.
- [ ] Output bundle contains exactly `migration_report.md` + `session.log`.
- [ ] All steps are `MigrationPipelineStep` subclasses with `supported_modes`.
- [ ] No migration transformation logic in this stage.
- [ ] Quality gates pass.

## Deliverables

- `src/modules/postprocessing/steps/validate_migration_step.py`
- `src/modules/postprocessing/steps/writeback_step.py`
- `src/modules/postprocessing/steps/generate_report_step.py`
- Unit tests under `tests/unit/modules/postprocessing/`

## References

- 02_ARCHITECTURE/PIPELINES.md — Output Pipeline responsibilities
- 03_ENGINEERING/DIAGNOSTICS.md — Reporter, session bundle
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — writeback API
- src/core/logging/reporter.py — Reporter.render()
- src/modules/migration/migration_step.py — MigrationPipelineStep (mode-gating)
- src/core/models/execution_context.py — ExecutionMode (READONLY/WRITEBACK)
