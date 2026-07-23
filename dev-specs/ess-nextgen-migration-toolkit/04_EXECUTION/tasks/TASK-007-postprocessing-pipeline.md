# TASK-007 — Postprocessing Pipeline (Validation + Writeback + Report)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-007                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
| Consumes   | TASK-015, TASK-004, TASK-005, TASK-016, TASK-017 |

## Description

Implement the **Output Pipeline** (`src/modules/postprocessing/`) — the stage
pipeline that runs after transformations to validate, persist, and render the
session bundle.

TASK-015 delivers an empty pass-through output stage. This task replaces it with
the real steps:

1. **ValidateMigration** — verify migrated components meet post-conditions
   (runs in both modes).
2. **Writeback** — apply `context.pending_writes` back to Dataverse via the
   DataverseClient (TASK-004). The list is already **coalesced** (one entry per
   record) and **no-op-guarded** (only genuinely-changed fields) by the
   `WritebackPlan` (TASK-017), so each entry
   `{"entity_set", "record_id", "changes"}` maps to a single
   `client.update(entity_set, record_id, changes)` — no de-duplication needed here.
   When `context.preferred_solution` is set (ALM customers, verified in
   `GatherALMCustomerInputStep`), the writes target that solution via the
   `MSCRM.SolutionUniqueName` request header. **WRITEBACK mode only** —
   `supported_modes=("WRITEBACK",)`, auto-skipped in READONLY.
3. **GenerateMigrationReport** — terminal step that renders the customer-facing
   `migration_report.md` from `MigrationContext` collectors via the Reporter
   service (runs in both modes).

**Boundary.** This task is the *consumer* of the `pending_writes` produced by
TASK-016 (Transformation) — it validates and persists them; it never computes
transformations itself. The live confirmation that the persisted field names are
correct is owned by TASK-009 (E2E, `--dev` WRITEBACK).

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

- [x] `ValidateMigration` step verifies post-conditions on migrated components.
- [x] `Writeback` step applies `context.pending_writes` via DataverseClient —
  **WRITEBACK only**.
- [x] Writeback targets `context.preferred_solution` (when set) via the
  `MSCRM.SolutionUniqueName` header.
- [x] `Writeback` is auto-skipped in READONLY mode (mode-gating via
  `MigrationPipelineStep.can_execute`).
- [x] `GenerateMigrationReport` renders `migration_report.md` via Reporter.
- [x] Output bundle contains exactly `migration_report.md` + `session.log`.
- [x] All steps are `MigrationPipelineStep` subclasses with `supported_modes`.
- [x] No transformation logic in this stage.
- [x] Quality gates pass.

## Deliverables

- `src/modules/postprocessing/steps/validate_migration_step.py`
- `src/modules/postprocessing/steps/writeback_step.py`
- `src/modules/postprocessing/steps/generate_report_step.py`
- Unit tests under `tests/unit/modules/postprocessing/`

## References

- 02_ARCHITECTURE/PIPELINES.md — Output Pipeline responsibilities
- 03_ENGINEERING/DIAGNOSTICS.md — Reporter, session bundle
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — writeback API
- src/service/reporter.py — Reporter.render()
- src/modules/transformation/migration_step.py — MigrationPipelineStep (mode-gating)
- src/modules/transformation/models/execution_mode.py — ExecutionMode (READONLY/WRITEBACK)
- src/modules/transformation/models/migration_context.py — `pending_writes` contract
