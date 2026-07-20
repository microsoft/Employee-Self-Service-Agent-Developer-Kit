# TASK-006 — Preprocessing Pipeline (Component Discovery + Hydration)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-006                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | TASK-015, TASK-004        |

## Description

Extend the **Input Pipeline** (`src/modules/preprocessing/`) — building on the
auth + agent discovery delivered by TASK-015 — with the deeper preprocessing
steps that hydrate the `MigrationContext` with the full component graph needed
by migration rules.

TASK-015 delivers: authentication, CLI input gathering, agent discovery +
selection. This task adds the steps that run **after** agent selection:

1. **Retrieve DependenciesForUninstall** — call Dataverse for the selected
   agent's dependency graph.
2. **Retrieve Solution Component Layers** — load solution layering metadata.
3. **Determine migration candidates** — filter components based on ownership and
   layer analysis (deterministic).
4. **Load canonical components** — convert raw Dataverse payloads into the
   canonical Domain Models and build the keyed `ComponentSet` (ComponentType →
   Component[]) on `MigrationContext`.

### Architecture constraints

- All steps are `MigrationPipelineStep` subclasses with
  `supported_modes=("READONLY", "WRITEBACK")` (read-only — no writes here).
- Dataverse calls go through the `DataverseClient` (TASK-004).
- Steps enrich `MigrationContext` — they never replace it.
- No migration transformation logic in this stage.

## Acceptance Criteria

- [ ] `DependenciesForUninstall` retrieved for the selected agent.
- [ ] Solution Component Layers retrieved.
- [ ] Migration candidates determined deterministically.
- [ ] Raw payloads converted into canonical Domain Models.
- [ ] `MigrationContext.ComponentSet` (ComponentType → Component[]) populated.
- [ ] All steps are `MigrationPipelineStep` subclasses.
- [ ] No migration transformation logic in this stage.
- [ ] Quality gates pass.

## Deliverables

- `src/modules/preprocessing/steps/retrieve_dependencies_step.py`
- `src/modules/preprocessing/steps/retrieve_layers_step.py`
- `src/modules/preprocessing/steps/determine_candidates_step.py`
- `src/modules/preprocessing/steps/load_components_step.py`
- `MigrationContext` extended with `ComponentSet` and dependency fields
- Unit tests under `tests/unit/modules/preprocessing/`

## References

- 02_ARCHITECTURE/PIPELINES.md — Input Pipeline responsibilities
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — dependency, layer, component APIs
- 02_ARCHITECTURE/DOMAIN_MODEL.md — ComponentSet, Component, ComponentType
- src/modules/migration/migration_step.py — MigrationPipelineStep
- src/modules/migration/models/migration_context.py — MigrationContext
