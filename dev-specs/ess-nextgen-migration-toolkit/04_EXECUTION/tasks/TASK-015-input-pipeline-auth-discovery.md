# TASK-015 — Input Pipeline: Authentication + Agent Discovery + Orchestrator Wiring

| Field      | Value                                                          |
| ---------- | -------------------------------------------------------------- |
| ID         | TASK-015                                                       |
| Workstream | 0 — Repository Foundation                                      |
| Status     | DONE                                                           |
| Consumes   | TASK-002 (pipeline framework), TASK-005 (diagnostics), TASK-008 (token provider) |

## Description

Implement the first **end-to-end vertical slice**: the orchestrator composes a
`ChainedPipeline[MigrationContext]` with three stages (Input → Migration →
Output), the Input Pipeline authenticates and discovers agents, and the
Migration/Output stages are empty pass-throughs until their tasks land.

This task delivers:

1. **Orchestrator wiring** (`src/service/mtk_orchestrator.py`) — the composition
   root that builds the three stage pipelines, chains them via
   `ChainedPipeline`, manages the diagnostics session lifecycle
   (`Logger.start_session` / `close()`), and surfaces the bundle path.
2. **Input Pipeline steps** (`src/modules/preprocessing/`) — real steps that
   gather the Dataverse environment URL, authenticate, discover ESS agents, and
   capture the optional preferred solution for future writeback.
3. **Migration + Output empty pass-throughs** — one no-op
   `MigrationPipelineStep` each so the chained pipeline runs end-to-end.

### Input Pipeline Flow

1. **Gather input + authenticate** — prompt for the full Dataverse environment
   URL (`https://org.crm.dynamics.com`), discover the tenant from the
   `WWW-Authenticate` challenge, then use `MsalTokenProvider` (TASK-008) to
   acquire a Dataverse bearer token. Proactive refresh is handled
   automatically.
2. **Discover ESS agents** — call Dataverse (`GET /bots`) scoped to the
   environment, display the list (name, bot ID, status), let the user select one.
   Store selected agent on `MigrationContext`.
3. **Gather preferred solution** — ask for the optional preferred solution
   unique name up front so future writeback can target it when present.

### Orchestrator Shape

```python
from core.pipelines import ChainedPipeline, Pipeline
from core.logging import Logger
from core.models import ExecutionMode
from modules.migration.models import MigrationContext

def main() -> None:
    ctx = MigrationContext(ExecutionMode=ExecutionMode.READONLY)
    logger = Logger.start_session(OUTPUT_ROOT, ctx)
    try:
        input_pipeline = build_input_pipeline(logger)
        migration_pipeline = build_migration_pipeline(logger)  # pass-through
        output_pipeline = build_output_pipeline(logger)        # pass-through

        toolkit = (
            ChainedPipeline[MigrationContext]()
            .add(input_pipeline)
            .add(migration_pipeline)
            .add(output_pipeline)
        )
        toolkit.run(ctx)
    finally:
        logger.close()
```

### Architecture notes

- All steps are `MigrationPipelineStep` subclasses.
- Input steps declare `supported_modes=("READONLY", "WRITEBACK")` (discovery
  runs in both modes).
- CLI prompting uses Python `input()` — captured by Logger's stdout tee.
- The toolkit currently asks for the full Dataverse environment URL directly.
  Future enhancement may resolve the URL from an Environment ID through the
  Power Platform BAP discovery API before Dataverse auth.
- Dataverse calls use the token provider directly with `httpx` for tenant
  discovery before the Dataverse client is initialized.
- No `EssMigrationToolkit` class — the orchestrator composes `ChainedPipeline`
  directly with `.add()`.
- After this task, `./mtk.sh start` runs the full pipeline end-to-end and
  produces a session bundle.

## Acceptance Criteria

- [ ] `mtk_orchestrator.py` composes a `ChainedPipeline[MigrationContext]` with
  three stages and runs end-to-end via `./mtk.sh start`.
- [ ] Logger session lifecycle: `start_session` before pipeline, `close()` in
  `finally`, produces `output/session-<timestamp>/` with two files.
- [ ] `MsalTokenProvider` is instantiated and used for Dataverse auth.
- [ ] User is prompted for the full Dataverse environment URL via CLI.
- [ ] Dataverse call retrieves ESS agents in the environment.
- [ ] Agent list displayed; user selects one; stored on `MigrationContext`.
- [ ] User is prompted for an optional preferred solution unique name; blank
  input leaves `preferred_solution` unset.
- [ ] `MigrationContext` extended with: `tenant_id`, `environment_url`,
  `selected_agent_id`, `selected_agent_name`, and `preferred_solution`.
- [ ] Migration and Output stages are pass-through (one no-op step each).
- [ ] All steps are `MigrationPipelineStep` subclasses with `supported_modes`.
- [ ] Quality gates pass: `uv run ruff check .`, `uv run mypy src`,
  `uv run pytest -q`.

## Deliverables

- `src/service/mtk_orchestrator.py` — composition root (ChainedPipeline wiring
  + Logger lifecycle)
- `src/modules/preprocessing/steps/gather_input_with_auth_step.py`
- `src/modules/preprocessing/steps/agent_selection_step.py`
- `src/modules/preprocessing/steps/gather_preferred_solution_step.py`
- `src/modules/migration/migration_pipeline.py` — builder returning pass-through
- `src/modules/postprocessing/output_pipeline.py` — builder returning pass-through
- `MigrationContext` extended with session input fields
- Unit tests under `tests/unit/service/` and `tests/unit/modules/preprocessing/`

## References

- 02_ARCHITECTURE/PIPELINES.md — stage responsibilities, ChainedPipeline
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — bot listing API
- 03_ENGINEERING/DIAGNOSTICS.md — session bundle, Logger lifecycle
- 01_PRODUCT/CUSTOMER_JOURNEY.md — user interaction flow
- src/core/auth/token_provider.py — MsalTokenProvider (TASK-008)
- src/core/pipelines/ — ChainedPipeline, Pipeline, PipelineStep
- src/modules/migration/migration_step.py — MigrationPipelineStep
- src/modules/migration/models/migration_context.py — MigrationContext
- src/core/models/execution_context.py — ExecutionContext, ExecutionMode
