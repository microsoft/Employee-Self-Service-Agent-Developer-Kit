# TASK-003 — Migration Orchestrator

| Field      | Value                                                              |
| ---------- | ------------------------------------------------------------------ |
| ID         | TASK-003                                                           |
| Workstream | 0 — Repository Foundation                                          |
| Status     | TODO                                                               |
| Consumes   | TASK-002 (pipeline framework), TASK-005 (diagnostics + `MigrationContext`); stage pipelines from TASK-006 (Input) and TASK-007 (Output) via the stage-builder seam below |

## Description

Implement the Migration Orchestrator (`src/service/mtk_orchestrator.py`). The
orchestrator is the **composition root** only: it assembles the three stage
pipelines into the fluent super-pipeline
(`EssMigrationToolkit().input(...).migrate(...).output(...)`), configures the
execution mode (Discover / Preview / Migrate), owns the diagnostics **session
lifecycle**, executes the super-pipeline, and surfaces the resulting session
bundle (`output/session-<timestamp>/`). It is the application entry point (run
by `scripts/mtk.sh start` → `uv run python src/service/mtk_orchestrator.py`) and
the top of the dependency graph. The orchestrator contains **no** migration
logic and **no** pipeline-step behaviour — those belong to the stages and steps
(TASK-006/007 and the migration-rule tasks).

This task was de-risked by a throwaway runtime spike that wired the TASK-002
pipeline framework to the TASK-005 diagnostics framework end-to-end and ran
successfully through `mtk.sh start`, producing a valid two-file bundle. The
**Proven blueprint** section below is that spike distilled into the contract to
build against; the spike code itself is discarded and is not the deliverable.

## Layer boundary (what belongs where)

- **Orchestrator (this task)** — owns process wiring: build `MigrationContext`,
  select `ExecutionMode`, `Logger.start_session(...)`, compose the toolkit, call
  `.run(ctx)`, guarantee `logger.close()` in a `finally`, and surface the bundle
  path. Nothing else.
- **Output pipeline terminal step (TASK-007)** — `GenerateMigrationReport()`
  runs last in the Output stage and calls `Reporter(logger.session_manager)
  .render(ctx)`. Report rendering is **not** done by the orchestrator (keeps
  DIAG-005 / PIPE-006 intact — only the Logger and Reporter write files).
- **Stage steps (TASK-006/007 + rule tasks)** — report exclusively through the
  injected `Logger` (`LogInfo`/`LogChange`/`LogAdvisory`, etc.); never
  `print()`, never touch the filesystem.

## Stage-builder seam (integration contract with TASK-006 / TASK-007)

The three stage pipelines are provided by other tasks, but their steps need the
`Logger` injected. Define the composition seam as three builder functions the
orchestrator calls, each returning a context-preserving stage pipeline and
receiving the active `Logger` for dependency injection:

```python
# provided by the modules packages (TASK-006 / TASK-007 / migration-rule tasks)
def build_input_pipeline(logger: Logger)     -> Pipeline[MigrationContext, MigrationContext]: ...
def build_migration_pipeline(logger: Logger) -> Pipeline[MigrationContext, MigrationContext]: ...
def build_output_pipeline(logger: Logger)    -> Pipeline[MigrationContext, MigrationContext]: ...
```

- Input builder → `src/service/modules/preprocessing/` (TASK-006).
- Migration builder → `src/service/modules/migration/` (migration-rule tasks).
- Output builder → `src/service/modules/postprocessing/` (TASK-007); its LAST
  `use(...)` is `GenerateMigrationReport()`.

Until those tasks land, each builder may return a minimal pipeline (a single
trivial pass-through step) so `mtk.sh start` runs the real composition root
end-to-end. Adding real stage behaviour must require only editing the builders /
adding steps — **the orchestrator must not change** when stages evolve (this is
the PIPE-008/009 open/closed guarantee at the composition level).

## Proven blueprint (from the runtime spike — exact contracts)

Framework surface actually available (do not re-derive):

- `from modules.migration.models import MigrationContext` — `@dataclass` with
  `ExecutionMode: ExecutionMode = ExecutionMode.READONLY` and mutable collectors `Logs`, `Warnings`,
  `Errors` (`list[DiagnosticEntry]`), `Changes` (`list[ChangeEntry]`). This IS
  the shared context threaded as `Pipeline[MigrationContext, MigrationContext]`.
- `from service import EssMigrationToolkit` (the ESS product super-pipeline,
  inheriting the generic `ChainedPipeline[TContext]` from `core.pipelines`) and
  `from core.pipelines import Pipeline, PipelineStep` —
  `EssMigrationToolkit` is **immutable/fluent**: `.input(p)`, `.migrate(p)`,
  `.output(p)` each return a NEW toolkit; `.run(ctx)` executes Input → Migration
  → Output threading the SAME context and raises `PipelineConfigurationError`
  if any stage is unconfigured. Build a stage with
  `Pipeline.builder("input", input_type=MigrationContext).use(step).build()`.
- `from core.logging import Logger, Reporter` — `Logger.start_session(output_root:
  Path, context: MigrationContext, *, level: LogLevel = LogLevel.INFO) -> Logger`
  creates the bundle folder AND installs the stdout/stderr tee; `logger.close()`
  restores streams and closes `session.log`; `logger.session_manager.paths
  .session_dir` is the bundle directory (contains `migration_report.md` +
  `session.log`).

Reference composition-root shape (skeleton — not the final code):

```python
from pathlib import Path
from modules.migration.models import MigrationContext
from service import EssMigrationToolkit
from core.logging import Logger

_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"  # <toolkit>/output

def main() -> None:
    mode = _select_mode()                       # default READONLY for now
    context = MigrationContext(ExecutionMode=mode)
    logger = Logger.start_session(_OUTPUT_ROOT, context)
    try:
        toolkit = (
            EssMigrationToolkit[MigrationContext]()
            .input(build_input_pipeline(logger))
            .migrate(build_migration_pipeline(logger))
            .output(build_output_pipeline(logger))   # terminal step renders report
        )
        toolkit.run(context)
    finally:
        logger.close()                          # ALWAYS restore streams / flush log
    _announce_bundle(logger.session_manager.paths.session_dir)

if __name__ == "__main__":
    main()
```

Verified in the spike: stages execute in order over one shared context;
`session.log` captures the full CLI transcript (engineer channel); the customer
channel (`LogChange`/`LogAdvisory`) lands only in `migration_report.md`; and the
report title is mode-aware ("Migration Readiness Report" for READONLY).

## Execution-mode selection

- `ExecutionMode` is a `StrEnum` on `ExecutionContext` (base class of `MigrationContext`) with values
  `READONLY` / `WRITEBACK`. The enum lives in `core.models.execution_context`. No
  additional enum or constant module is needed —
  the `StrEnum` compares equal to plain strings (`ExecutionMode.READONLY == "READONLY"`).
- `scripts/mtk.sh` presently forwards **no arguments** to the orchestrator
  (`exec uv run python src/service/mtk_orchestrator.py`). For this task, default
  the mode to `READONLY`. Wiring a real CLI surface (e.g. `--mode`, and updating
  `mtk.sh` to forward `"$@"`) is an allowed minimal extension **only if** it does
  not add migration logic; otherwise leave it to a follow-up and keep the default.

## Acceptance Criteria

- [ ] `main()` in `src/service/mtk_orchestrator.py` is the composition root and
  the module runs via `scripts/mtk.sh start` (both `--dev` and default paths).
- [ ] The orchestrator selects the execution mode (default `READONLY`) and
  constructs a single shared `MigrationContext(ExecutionMode=...)`.
- [ ] The orchestrator opens the diagnostics session with
  `Logger.start_session(output_root, context)` where `output_root` resolves to
  the toolkit's `output/` directory, and **guarantees** `logger.close()` runs in
  a `finally` even if a stage raises.
- [ ] The orchestrator composes the super-pipeline
  (`EssMigrationToolkit().input(...).migrate(...).output(...)`) exclusively from
  the three stage-builder functions (the seam above), injecting the `Logger`, and
  executes it with `.run(context)`.
- [ ] The orchestrator surfaces the produced session bundle
  (`output/session-<timestamp>/`) to the user — at minimum by logging/announcing
  the `session_dir` (the two files `migration_report.md` + `session.log` are the
  product); it does **not** render the report itself.
- [ ] Adding/altering stage behaviour requires no change to the orchestrator
  (open/closed at the composition level; PIPE-008/009).
- [ ] No migration-transformation logic, no pipeline-step behaviour, and no
  direct file I/O or `print()` from business paths exist in the orchestrator
  (DIAG-005 / PIPE-006).
- [ ] Running `mtk.sh start` end-to-end produces a bundle with exactly
  `migration_report.md` and `session.log`, and `session.log` contains the run
  transcript.
- [ ] Quality gates pass in `tools/ess-nextgen-migration-toolkit/`:
  `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src`,
  `uv run pytest -q` (add orchestrator unit tests: mode selection, `close()` in
  `finally` on stage exception, bundle-path surfacing, and "no report render in
  orchestrator").

## Deliverables

- `src/service/mtk_orchestrator.py` composition root implementing the blueprint
  (mode selection, `MigrationContext` construction, `Logger` session lifecycle
  with `finally`-guaranteed `close()`, toolkit composition via the stage seam,
  `.run()`, bundle-path surfacing).
- The stage-builder seam consumed from the modules packages (with minimal
  pass-through stage pipelines if TASK-006/007 have not yet landed, so the entry
  point runs end-to-end).
- Optional-minimal: `mtk.sh` argument forwarding + `--mode` parsing (only if it
  introduces no business logic).
- Unit tests under `tests/unit/service/` covering the criteria above.

## References

- 00_META/INVARIANTS.md — PIPE-006/007, DIAG-004 (supreme). Note: PIPE-008/009/010
  are defined in PIPELINES.md and DIAG-005 in DIAGNOSTICS.md (referenced below).
- 02_ARCHITECTURE/ARCHITECTURE.md — layering / dependency graph (orchestrator =
  composition root at the top)
- 02_ARCHITECTURE/PIPELINES.md — v2.0 super-pipeline, `EssMigrationToolkit`,
  `Pipeline[TIn,TOut]`, `PipelineStep[TIn,TOut]`, composition-root role
- 02_ARCHITECTURE/DOMAIN_MODEL.md — `MigrationContext`, `ExecutionMode`,
  `DiagnosticEntry` / `ChangeEntry`
- 03_ENGINEERING/DIAGNOSTICS.md — sections 5 (two-file bundle), 6 (Logger session
  lifecycle + tee + two channels), 9 (Reporter / terminal `GenerateMigrationReport`)
- 04_EXECUTION/tasks/TASK-002-pipeline-framework.md — framework this consumes
- 04_EXECUTION/tasks/TASK-005-diagnostics-framework.md — logging/reporter this consumes
- 04_EXECUTION/tasks/TASK-006-preprocessing-pipeline.md — Input stage builder (`preprocessing`)
- 04_EXECUTION/tasks/TASK-007-postprocessing-pipeline.md — Output stage builder (`postprocessing`, terminal report step)
