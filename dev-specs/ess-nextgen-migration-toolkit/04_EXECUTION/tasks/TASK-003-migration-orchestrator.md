# TASK-003 — Migration Orchestrator

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-003                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement the Migration Orchestrator (`src/service/mtk_orchestrator.py`). The
orchestrator is the **composition root** only: it assembles the three stage
pipelines into the fluent super-pipeline
(`EssMigrationToolkit().input(...).migrate(...).output(...)`), configures the
execution mode (Discover / Preview / Migrate), executes it, and returns the
session bundle (reports and diagnostics). It is the application entry point and
top of the dependency graph. The orchestrator contains no migration logic and no
pipeline behaviour — those belong to the stages and steps.

## Acceptance Criteria

- [ ] The orchestrator gathers session inputs and selects the execution mode.
- [ ] The orchestrator composes the super-pipeline from the Input, Migration,
  and Output stage pipelines.
- [ ] The orchestrator manages the session lifecycle (start, run, finish).
- [ ] The orchestrator executes the super-pipeline and returns the session
  bundle (`output/session-<timestamp>/`).
- [ ] No migration transformation logic or pipeline-step behaviour exists in the
  orchestrator.

## Deliverables

- Session input handling and mode selection
- Super-pipeline composition (composition root)
- Session lifecycle management
- Super-pipeline execution and result surfacing

## References

- 02_ARCHITECTURE/ARCHITECTURE.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 02_ARCHITECTURE/PIPELINES.md
