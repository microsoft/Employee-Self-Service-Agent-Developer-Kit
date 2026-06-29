# TASK-006 — Preprocessing Pipeline

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-006                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement discovery and preprocessing — the stages that gather and prepare data
before any migration transformation. Implemented under
`src/modules/preprocessing/`. No migration transformations occur here.

## Acceptance Criteria

- [ ] The ESS Agent is discovered from the selected environment.
- [ ] `DependenciesForUninstall` is retrieved.
- [ ] Solution Component Layers are retrieved.
- [ ] Migration candidates are determined deterministically.
- [ ] Raw payloads are converted into canonical Domain Models.
- [ ] No migration transformation logic is performed in this stage.

## Deliverables

- Discover ESS Agent
- Retrieve DependenciesForUninstall
- Retrieve Solution Component Layers
- Determine migration candidates
- Load canonical components

## References

- 02_ARCHITECTURE/SERVICES.md
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
