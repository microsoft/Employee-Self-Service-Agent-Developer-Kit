# TASK-014 — ESS Product Pipeline (EssMigrationToolkit + Stage Pipelines)

| Field      | Value                                             |
| ---------- | ------------------------------------------------- |
| ID         | TASK-014                                          |
| Workstream | 0 — Repository Foundation                         |
| Status     | ACTIVE                                            |
| Consumes   | TASK-002 (`ChainedPipeline[TContext]` core base)  |

## Description

Implement the **ESS product chained pipeline** — the thin composition layer
that sits on top of the generic `core.pipelines` framework. This task owns two
things:

1. The **ESS product chained pipeline** `EssMigrationToolkit` (`src/service/`),
   which inherits the generic, product-agnostic `ChainedPipeline[TContext]` base
   from `core.pipelines` and adds named, immutable
   `.input()/.migrate()/.output()` stage setters.
2. The **three stage-pipeline class definitions** (`InputPipeline`,
   `MigrationPipeline`, `OutputPipeline`) in `src/modules/`. These are thin,
   fluent `Pipeline[MigrationContext, MigrationContext]` builders — they define
   the stage structure and accept steps via `.use()`. They contain **no**
   discovery, Dataverse, transformation, validation, or reporting steps. Those
   are added by later tasks (TASK-006, TASK-007, and migration-rule tasks).

## Key design constraints

- `EssMigrationToolkit` inherits `ChainedPipeline[MigrationContext]` and its
  `.run(ctx)` executes Input → Migration → Output in order. It raises
  `PipelineConfigurationError` if any stage is unconfigured.
- `MigrationContext` lives in `modules.migration.models` (extends
  `ExecutionContext` from `core.models`). Import it from there.
- `ExecutionMode` is a `StrEnum` with values `READONLY` / `WRITEBACK` (defined
  in `core.models.execution_context`).
- `MigrationPipelineStep` (in `modules.migration.migration_step`) is the
  mandatory base for ESS steps — it implements mode-gating via
  `supported_modes` in `can_execute`. Steps declaring
  `supported_modes=("WRITEBACK",)` auto-skip in READONLY mode.
- Depend only on the `core.pipelines` framework (`Pipeline`, `PipelineBuilder`,
  `PipelineStep`, and the `ChainedPipeline[TContext]` base).

## Deliverables

- `src/service/toolkit.py` → `EssMigrationToolkit` (subclass of
  `ChainedPipeline[MigrationContext]`, adds `.input()/.migrate()/.output()`),
  exported from `src/service/__init__.py`.
- `src/modules/preprocessing/input_pipeline.py` → `InputPipeline` (a
  `Pipeline[MigrationContext, MigrationContext]` builder/factory function).
- `src/modules/migration/migration_pipeline.py` → `MigrationPipeline` (same).
- `src/modules/postprocessing/output_pipeline.py` → `OutputPipeline` (same).
- Unit tests under `tests/unit/service/` and `tests/unit/modules/` covering:
  toolkit composition, stage validation, and end-to-end run with pass-through
  steps.

## Acceptance Criteria

- [ ] `EssMigrationToolkit` exists in `src/service/toolkit.py`,
  inherits `ChainedPipeline[MigrationContext]` from `core.pipelines`, is exported
  from `src/service/__init__.py`.
- [ ] `EssMigrationToolkit` exposes immutable, fluent
  `.input()/.migrate()/.output()` stage setters plus `.run(ctx)` executing the
  ordered stages. It raises `PipelineConfigurationError` if any stage is
  unconfigured at run time.
- [ ] `InputPipeline`, `MigrationPipeline`, and `OutputPipeline` are defined as
  builder functions or classes returning `Pipeline[MigrationContext, MigrationContext]`.
- [ ] Each stage pipeline initially contains one no-op pass-through step (so
  `EssMigrationToolkit().input(...).migrate(...).output(...).run(ctx)` works
  end-to-end without TASK-006/007 content).
- [ ] Mode-gating is tested: a step with `supported_modes=("WRITEBACK",)` is
  skipped when context has `ExecutionMode=READONLY`.
- [ ] Quality gates pass: `uv run ruff check .`, `uv run mypy src`,
  `uv run pytest -q`.

## References

- 02_ARCHITECTURE/PIPELINES.md — v2.0 chained pipeline, `EssMigrationToolkit`
- 02_ARCHITECTURE/ARCHITECTURE.md — layering (service → modules → core)
- 04_EXECUTION/tasks/TASK-002-pipeline-framework.md — generic framework consumed
- src/core/pipelines/ — `ChainedPipeline`, `Pipeline`, `PipelineStep`
- src/modules/migration/migration_step.py — `MigrationPipelineStep` (mode-gating base)
- src/modules/migration/models/migration_context.py — `MigrationContext`
- src/core/models/execution_context.py — `ExecutionContext`, `ExecutionMode` (StrEnum)
