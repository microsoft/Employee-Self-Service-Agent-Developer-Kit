# TASK-009 — End-to-End Framework Validation

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-009                  |
| Workstream | 0 — Repository Foundation |
| Status     | BLOCKED                      |
| Consumes   | TASK-003, TASK-006, TASK-007, TASK-016 |

## Description

Validate that the entire framework executes end-to-end with real pipeline wiring.
The Input and Transformation stages now carry real steps (auth + discovery, and
`ApplyDaCompatibilityStep`); the remaining Migration Rules (RULE-001..004) may
still be pending. This proves the assembled framework — composition, mode-gating,
diagnostics, and writeback — is sound end-to-end.

### What this validates

- `./mtk.sh run` runs the full ChainedPipeline (Input → Transformation → Output).
- READONLY mode: all stages run, Writeback is auto-skipped (mode-gating works).
- WRITEBACK mode: Writeback step executes (persists via DataverseClient).
- Diagnostics: session bundle produced with `migration_report.md` + `session.log`.
- Determinism: identical inputs produce identical ordering and output.
- Logger session lifecycle: `start_session` → pipeline → `close()` in all paths.
- **Live Dataverse field names**: confirm the DA-compat read/write fields
  (`template`, `configuration`, `data`, `botcomponentid`) match a real record when
  run under `./mtk.sh run --dev` in WRITEBACK mode — verifying the fields that
  TASK-016 reads and TASK-007 persists. (Moved here from TASK-016 so the live
  check lives once, at the end-to-end boundary.)

### Architecture constraints

- This is a **validation task**, not an implementation task. No new production
  code — only integration/e2e tests that exercise the assembled framework.
- Tests run against real pipeline composition (not mocked pipelines).
- May use a Dataverse fixture/cassette for the writeback assertion.

## Acceptance Criteria

- [ ] The framework runs end-to-end (Input → Transformation → Output) via
  `./mtk.sh run`.
- [ ] READONLY mode executes without writeback (Writeback step skipped).
- [ ] WRITEBACK mode persists results through the DataverseClient.
- [ ] Under `./mtk.sh run --dev` (WRITEBACK), the DA-compat field names
  (`template`, `configuration`, `data`, `botcomponentid`) are confirmed against a
  live record — the transform produces a non-empty `pending_writes` and the PATCH
  succeeds.
- [ ] Session bundle produced: `output/session-<timestamp>/` with exactly two
  files.
- [ ] `migration_report.md` contains Summary, Changes, Warnings, Errors sections.
- [ ] `session.log` contains the full CLI transcript.
- [ ] Execution is deterministic across identical inputs.
- [ ] Quality gates pass.

## Deliverables

- Integration tests under `tests/integration/` exercising the full pipeline
- E2E test under `tests/e2e/` running `mtk.sh run` as a subprocess
- Dataverse fixture/cassette for writeback mode

## References

- 02_ARCHITECTURE/PIPELINES.md — ChainedPipeline, stage ordering
- 03_ENGINEERING/DIAGNOSTICS.md — session bundle contract
- 03_ENGINEERING/TESTING.md — integration/e2e test strategy
- src/modules/transformation/models/execution_mode.py — ExecutionMode (READONLY/WRITEBACK)
