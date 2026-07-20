# TASK-009 — End-to-End Framework Validation

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-009                  |
| Workstream | 0 — Repository Foundation |
| Status     | BLOCKED                      |
| Consumes   | TASK-003, TASK-006, TASK-007 |

## Description

Validate that the entire framework executes end-to-end with real pipeline wiring
but no-op Migration Steps (the migration stage has pass-through steps only).
This proves the foundation is sound before any Migration Rule is implemented in
Workstream 1.

### What this validates

- `./mtk.sh start` runs the full ChainedPipeline (Input → Migration → Output).
- READONLY mode: all stages run, Writeback is auto-skipped (mode-gating works).
- WRITEBACK mode: Writeback step executes (persists via DataverseClient).
- Diagnostics: session bundle produced with `migration_report.md` + `session.log`.
- Determinism: identical inputs produce identical ordering and output.
- Logger session lifecycle: `start_session` → pipeline → `close()` in all paths.

### Architecture constraints

- This is a **validation task**, not an implementation task. No new production
  code — only integration/e2e tests that exercise the assembled framework.
- Tests run against real pipeline composition (not mocked pipelines).
- May use a Dataverse fixture/cassette for the writeback assertion.

## Acceptance Criteria

- [ ] The framework runs end-to-end with no-op Migration Steps via
  `./mtk.sh start`.
- [ ] READONLY mode executes without writeback (Writeback step skipped).
- [ ] WRITEBACK mode persists results through the DataverseClient.
- [ ] Session bundle produced: `output/session-<timestamp>/` with exactly two
  files.
- [ ] `migration_report.md` contains Summary, Changes, Warnings, Errors sections.
- [ ] `session.log` contains the full CLI transcript.
- [ ] Execution is deterministic across identical inputs.
- [ ] Quality gates pass.

## Deliverables

- Integration tests under `tests/integration/` exercising the full pipeline
- E2E test under `tests/e2e/` running `mtk.sh start` as a subprocess
- Dataverse fixture/cassette for writeback mode

## References

- 02_ARCHITECTURE/PIPELINES.md — ChainedPipeline, stage ordering
- 03_ENGINEERING/DIAGNOSTICS.md — session bundle contract
- 03_ENGINEERING/TESTING.md — integration/e2e test strategy
- src/core/models/execution_context.py — ExecutionMode (READONLY/WRITEBACK)
