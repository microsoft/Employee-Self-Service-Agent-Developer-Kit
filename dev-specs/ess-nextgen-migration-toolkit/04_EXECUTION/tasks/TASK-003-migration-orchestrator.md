# TASK-003 — Migration Orchestrator

| Field      | Value                                                              |
| ---------- | ------------------------------------------------------------------ |
| ID         | TASK-003                                                           |
| Workstream | 0 — Repository Foundation                                          |
| Status     | DONE                                                              |
| Consumes   | TASK-002, TASK-005, TASK-015                                       |

## Description

Evolve `src/service/mtk_orchestrator.py` from the minimal composition root
(delivered by TASK-015) into the full **Migration Orchestrator** — the
application entry point that owns execution-mode selection, CLI command surface,
and session lifecycle management.

TASK-015 delivers the initial orchestrator wiring (ChainedPipeline composition,
Logger lifecycle, default READONLY mode). This task extends it with:

1. **Execution-mode selection** — parse `--mode readonly|writeback` from the CLI
   (forwarded by `mtk.sh start`). Default remains `READONLY`.
2. **CLI command surface** — wire `mtk.sh` argument forwarding so
   `./mtk.sh start --mode writeback` propagates to the orchestrator. Future
   subcommands (e.g. `mtk discover`, `mtk migrate`) may be added here.
3. **Graceful error handling** — catch pipeline exceptions, surface user-friendly
   messages, and ensure `logger.close()` runs in all paths.
4. **Session summary** — after pipeline completes, print the bundle path and a
   one-line summary (mode, agent, changes/warnings counts).

### Architecture constraints

- The orchestrator is the **composition root only** — it composes
  `ChainedPipeline[MigrationContext]` with `.add()` and calls `.run(ctx)`.
- No migration-transformation logic, no pipeline-step behaviour, and no direct
  file I/O or `print()` from business paths (DIAG-005 / PIPE-006).
- `ExecutionMode` is a StrEnum (`READONLY` / `WRITEBACK`) from
  `modules.transformation.models`. The generic base `ExecutionContext` stores it
  as an opaque `mode: str`; set it via `MigrationContext(mode=ExecutionMode.…)`.
- Logger, Reporter, MigrationContext, ChainedPipeline are already wired by
  TASK-015 — this task extends, not rewrites.

## Acceptance Criteria

- [x] `--mode readonly|writeback` CLI argument parsed and applied to
  `MigrationContext.mode` (`_resolve_mode`; accepts `--mode X` and `--mode=X`,
  case-insensitive; invalid value → friendly `SystemExit`).
- [x] `mtk.sh start --mode writeback` forwards the argument to the orchestrator
  (and `mtk.ps1 -Mode writeback` on Windows).
- [x] Default mode is `READONLY` when no argument supplied.
- [x] Pipeline exceptions are caught, a user-friendly message is logged
  (`LogError` with the session-log path), and `logger.close()` always runs.
- [x] After a successful run, the orchestrator logs a summary line (mode, agent
  name, changes/warnings/errors counts, bundle path).
- [x] No migration logic in the orchestrator (PIPE-006).
- [x] Quality gates pass: `uv run ruff check .`, `uv run mypy .`,
  `uv run pytest -q`.

## Deliverables

- `src/service/mtk_orchestrator.py` — extended with mode parsing, error
  handling, session summary
- `scripts/mtk.sh` / `scripts/mtk.ps1` — parse and forward `--dev` and
  `--mode readonly|writeback` to the orchestrator
- Unit tests under `tests/unit/service/`

## References

- 02_ARCHITECTURE/ARCHITECTURE.md — orchestrator = composition root
- 02_ARCHITECTURE/PIPELINES.md — ChainedPipeline composition
- 03_ENGINEERING/DIAGNOSTICS.md — Logger session lifecycle
- src/modules/transformation/models/execution_mode.py — ExecutionMode StrEnum
- src/core/models/execution_context.py — ExecutionContext (generic `mode: str`)
- src/core/pipelines/ — ChainedPipeline, Pipeline
- 04_EXECUTION/tasks/TASK-015-input-pipeline-auth-discovery.md — base wiring
  this task extends
