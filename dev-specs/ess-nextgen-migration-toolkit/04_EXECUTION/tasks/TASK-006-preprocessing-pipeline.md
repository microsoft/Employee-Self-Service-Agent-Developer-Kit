# TASK-006 — Preprocessing Pipeline (Agent Config + Customization Discovery)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-006                  |
| Workstream | 0 — Repository Foundation |
| Status     | ACTIVE                    |
| Consumes   | TASK-015, TASK-004        |

## Description

Extend the **Input Pipeline** (`src/modules/preprocessing/`) — building on the
auth + agent discovery delivered by TASK-015 — with the two preprocessing steps
that hydrate the `MigrationContext` with the agent's core configuration and its
discovered **customizations**, which the Transformation stage (TASK-016) then
rewrites for DA compatibility.

TASK-015 delivers the first three fixed-order steps: authentication + input
gathering (`GatherInputWithAuthStep`), agent discovery/selection
(`AgentSelectionStep`), and the ALM preferred-solution capture + cross-check
(`GatherALMCustomerInputStep`). This task adds the steps that run **after**
those three:

1. **Retrieve agent configuration + metadata**
   (`RetrieveAgentConfigurationStep`) — fetch the selected agent's
   `bots({botid})` record (carries `template` + `configuration`) and its
   `{schemaname}.gpt.default` botcomponent (carries the model-kind YAML). Stored
   raw on the context for the Transformation stage.
2. **Retrieve customizations** (`RetrieveCustomizationsStep`) — resolve the ESS
   base solution for the agent's vertical, call
   `RetrieveDependenciesForUninstallWithMetadata`, bulk-fetch
   `msdyn_componentlayers` for the dependent components (chunked + paginated),
   and classify each component's layers via the **~1900 sentinel** rule to keep
   only genuine customizations. See
   `02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md` for the full algorithm.

### Architecture constraints

- All steps are `MigrationPipelineStep` subclasses with
  `supported_modes=("READONLY", "WRITEBACK")` (read-only — no writes here).
- Dataverse access goes through the `DataverseClient` (TASK-004), including
  `call_function` (bound functions) and `query_all` (paginated collection reads).
- Steps enrich `MigrationContext` — they never replace it.
- No transformation logic in this stage (that is TASK-016).

## Acceptance Criteria

- [x] Agent `bots({botid})` record fetched onto `context.agent_bot_record`.
- [x] `{schemaname}.gpt.default` botcomponent fetched onto
  `context.agent_gpt_component` (missing component warns, does not fail).
- [x] ESS base solution resolved from the agent schemaname vertical.
- [x] `RetrieveDependenciesForUninstallWithMetadata` retrieved onto
  `context.raw_dependencies`.
- [x] `msdyn_componentlayers` bulk-fetched (chunked + fully paginated) onto
  `context.component_layers`.
- [x] Customizations classified by the ~1900 sentinel rule onto
  `context.customizations` (latest non-sentinel layer per component).
- [x] All steps are `MigrationPipelineStep` subclasses.
- [x] No transformation logic in this stage.
- [ ] Field names against live records confirmed (`template`, `configuration`,
  `data`, `botcomponentid`) via `./mtk.sh start --dev`.
- [ ] Quality gates pass.

## Deliverables

- `src/modules/preprocessing/steps/retrieve_agent_configuration_step.py`
- `src/modules/preprocessing/steps/retrieve_customizations_step.py`
- `src/service/utils.py` — `resolve_ess_solution(agent_schemaname)`
- `src/service/constants.py` — `ESS_SOLUTION_BY_VERTICAL`
- `MigrationContext` extended with `agent_bot_record`, `agent_gpt_component`,
  `ess_solution_unique_name`, `raw_dependencies`, `component_layers`,
  `customizations`
- Unit tests under `tests/unit/modules/preprocessing/`

## References

- 02_ARCHITECTURE/PIPELINES.md — Input Pipeline responsibilities
- 02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md — solution resolution, dependencies,
  component-layer classification (~1900 sentinel rule)
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — dependency, layer, function/query APIs
- src/modules/transformation/migration_step.py — MigrationPipelineStep
- src/modules/transformation/models/migration_context.py — MigrationContext
