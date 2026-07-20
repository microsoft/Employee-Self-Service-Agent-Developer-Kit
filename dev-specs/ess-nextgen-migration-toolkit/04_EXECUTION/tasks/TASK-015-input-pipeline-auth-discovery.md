# TASK-015 — Input Pipeline: Authentication + Agent Discovery

| Field      | Value                                                          |
| ---------- | -------------------------------------------------------------- |
| ID         | TASK-015                                                       |
| Workstream | 1 — First Vertical Slice                                       |
| Status     | TODO                                                           |
| Consumes   | TASK-002 (pipeline framework), TASK-005 (diagnostics), TASK-008 (token provider), TASK-014 (InputPipeline) |

## Description

Implement the first real steps in the **Input Pipeline**
(`src/modules/preprocessing/`). This is the entry point of every migration
session — it authenticates the user, gathers session inputs from the CLI, calls
Dataverse to discover ESS agents in the target environment, and lets the user
select which agent to operate on.

The Input Pipeline supports both `READONLY` and `WRITEBACK` modes (the
discovery flow is identical in both — mode-gating only matters for downstream
writeback steps).

### Flow

1. **Authenticate** — use the existing `MsalTokenProvider` (TASK-008) to acquire
   a Dataverse bearer token. Token refresh is handled automatically by the
   provider (proactive silent refresh before expiry).
2. **Gather session inputs via CLI** — prompt the user for:
   - Tenant ID
   - Environment ID
   - (optional: Environment URL — can be derived from env ID)
   
   Populate these on the `MigrationContext` so downstream steps have them.
3. **Discover ESS agents** — call Dataverse (`GET /bots`) scoped to the
   environment to retrieve the list of ESS agents (Copilot Studio bots).
4. **Present agent list** — display the discovered agents to the user in a
   numbered list (name, bot ID, status).
5. **User selects agent** — the user picks one agent by number. Store the
   selected agent's bot ID and metadata on the `MigrationContext`.

After this pipeline stage completes, `MigrationContext` is hydrated with:
- `tenant_id`, `environment_id`
- `selected_agent` (bot ID, name, metadata)
- A valid bearer token (via the injected token provider)

### Architecture notes

- Steps in this pipeline are `MigrationPipelineStep` subclasses (inherit
  mode-gating). All steps here declare
  `supported_modes=("READONLY", "WRITEBACK")` since discovery runs in both modes.
- CLI prompting is the responsibility of a dedicated step (e.g.
  `GatherSessionInputsStep`). The step uses Python's `input()` — this is the
  one sanctioned place for direct user interaction. The Logger's stdout tee
  captures the interaction in `session.log`.
- Dataverse calls go through the `DataverseClient` (TASK-004) if available, or
  a minimal HTTP helper if TASK-004 hasn't landed yet (note: TASK-004 is TODO,
  so this task may need a thin adapter or a direct `httpx`/`requests` call with
  the token provider — keep it behind an interface so TASK-004 can replace it).

## Acceptance Criteria

- [ ] `MsalTokenProvider` is instantiated and used for Dataverse auth (reuse
  TASK-008's implementation).
- [ ] The user is prompted for Tenant ID and Environment ID via CLI input.
- [ ] A Dataverse call retrieves the list of ESS agents (bots) in the given
  environment.
- [ ] The agent list is displayed to the user with name, bot ID, and status.
- [ ] The user selects one agent; the selection is stored on `MigrationContext`.
- [ ] `MigrationContext` is extended with fields: `tenant_id`, `environment_id`,
  `selected_agent` (or equivalent structured data).
- [ ] All steps are `MigrationPipelineStep` subclasses with
  `supported_modes=("READONLY", "WRITEBACK")`.
- [ ] The input pipeline runs end-to-end via `InputPipeline` (TASK-014) with
  these steps wired in.
- [ ] Quality gates pass: `uv run ruff check .`, `uv run mypy src`,
  `uv run pytest -q`.

## Deliverables

- `src/modules/preprocessing/steps/authenticate_step.py` — acquire token
- `src/modules/preprocessing/steps/gather_inputs_step.py` — CLI prompts for
  tenant/env
- `src/modules/preprocessing/steps/discover_agents_step.py` — Dataverse call +
  display + user selection
- `MigrationContext` extended with session input fields (`tenant_id`,
  `environment_id`, `selected_agent`)
- Unit tests under `tests/unit/modules/preprocessing/`
- Integration test (optional, if Dataverse fixture available)

## References

- 02_ARCHITECTURE/PIPELINES.md — Input Pipeline responsibilities
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — bot listing API
- 01_PRODUCT/CUSTOMER_JOURNEY.md — user interaction flow
- src/core/auth/token_provider.py — TASK-008 MsalTokenProvider
- src/modules/migration/migration_step.py — MigrationPipelineStep base
- src/modules/migration/models/migration_context.py — MigrationContext to extend
