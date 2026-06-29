# TASK-003 — Migration Orchestrator

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-003                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement the Migration Orchestrator (`src/service/mtk_orchestrator.py`), which
coordinates a migration session from user interaction through pipeline
execution. It is the application entry point and top of the dependency graph.
The orchestrator contains no migration logic.

## Acceptance Criteria

- [ ] The orchestrator handles user interaction and gathers the session inputs.
- [ ] The orchestrator initializes the pipeline from the registry.
- [ ] The orchestrator manages the session lifecycle (start, run, finish).
- [ ] The orchestrator executes the pipeline and surfaces results.
- [ ] No migration transformation logic exists in the orchestrator.

## Deliverables

- User interaction handling
- Pipeline initialization
- Session lifecycle management
- Pipeline execution

## References

- 02_ARCHITECTURE/ARCHITECTURE.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
