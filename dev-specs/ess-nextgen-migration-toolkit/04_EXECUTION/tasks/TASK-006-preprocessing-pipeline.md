# TASK-006 — Preprocessing Pipeline

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-006                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement the **Input Pipeline** (`src/modules/preprocessing/`) — the stage
pipeline that discovers customer-owned artifacts and prepares the canonical
`MigrationContext` consumed by the migration engine. It is built fluently over
the shared `MigrationContext` and composed into the super-pipeline by the
orchestrator. No migration transformations occur here.

## Acceptance Criteria

- [ ] The Input Pipeline is built fluently: `InputPipeline().use(...)`.
- [ ] The ESS Agent is discovered from the selected environment.
- [ ] `DependenciesForUninstall` is retrieved.
- [ ] Solution Component Layers are retrieved.
- [ ] Migration candidates are determined deterministically.
- [ ] Raw payloads are converted into canonical Domain Models and loaded into the
  `MigrationContext`, including the keyed `ComponentSet` (ComponentType →
  Component[]).
- [ ] No migration transformation logic is performed in this stage.

## Deliverables

- Input Pipeline (fluent, over `MigrationContext`)
- Discover ESS Agent
- Retrieve DependenciesForUninstall
- Retrieve Solution Component Layers
- Determine migration candidates
- Load canonical components and build the keyed `ComponentSet`

## References

- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/SERVICES.md
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
