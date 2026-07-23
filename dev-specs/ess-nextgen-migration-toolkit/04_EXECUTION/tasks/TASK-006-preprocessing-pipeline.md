# TASK-006 — Preprocessing Pipeline (Agent Config + Customization Discovery)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-006                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
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
   base solution for the agent's vertical (and its `solutionid` GUID), call
   `RetrieveDependenciesForUninstallWithMetadata(SolutionId=<guid>)`, fetch
   `msdyn_componentlayers` **one component at a time** (the virtual table needs
   `msdyn_solutioncomponentname` and won't OR ids), then **classify + filter +
   hydrate**: keep customer changes (multi-layer, or a lone non-OOB-solution
   layer) that are a migrated sub-type (Topic V2) owned by an ESS HR/IT agent,
   hydrated into `CustomizationComponent`s. See
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
- [x] ESS base solution resolved from the agent schemaname vertical, and its
  `solutionid` GUID resolved via a `solutions` query.
- [x] `RetrieveDependenciesForUninstallWithMetadata(SolutionId=<guid>)` retrieved
  onto `context.raw_dependencies` (GUID inlined unquoted by `call_function`).
- [x] `msdyn_componentlayers` fetched **per component** (paired with
  `msdyn_solutioncomponentname`, fully paginated) onto `context.component_layers`
  (`{componentId -> [layer, …]}`).
- [x] Customizations classified onto `context.customizations`
  (`{componentId -> CustomizationComponent}`): kept when customized (multi-layer,
  or a lone non-OOB-solution layer) AND migratable (componenttype in
  `ALLOWED_BOT_COMPONENT_TYPES`, schemaname matches `ESS_AGENT_SCHEMANAMES`),
  hydrated with `schemaname`/`name`/`component_type`/`component_type_label`/`data`.
  `context.customized_dependencies` holds the matching raw dependency infos.
- [x] All steps are `MigrationPipelineStep` subclasses.
- [x] No transformation logic in this stage.
- [x] Discovery field names confirmed against live records
  (`msdyn_componentid`, `msdyn_solutionname`, `msdyn_solutioncomponentname`,
  `msdyn_componentjson` → `componenttype`/`schemaname`/`name`/`data`,
  `dependentcomponentobjectid`, `dependentcomponententitylogicalname`, gpt
  `schemaname`/`botcomponentid`) — verified from live API samples during the
  discovery bring-up. (The transform-target fields
  `template`/`configuration`/`data` writeback is TASK-016's concern.)
- [x] Quality gates pass (`ruff`, `mypy`, `pytest`; enforced in CI).

## Deliverables

- `src/modules/preprocessing/steps/retrieve_agent_configuration_step.py`
- `src/modules/preprocessing/steps/retrieve_customizations_step.py`
- `src/modules/transformation/models/customization_component.py` —
  `CustomizationComponent` hydrated model
- `src/service/utils.py` — `resolve_ess_solution(agent_schemaname)`
- `src/service/constants.py` — `ESS_SOLUTION_BY_VERTICAL`, `OOB_ESS_SOLUTIONS`,
  `BOT_COMPONENT_TYPE_LABELS`, `ALLOWED_BOT_COMPONENT_TYPES`,
  `ESS_AGENT_SCHEMANAMES`
- `MigrationContext` extended with `agent_bot_record`, `agent_gpt_component`,
  `ess_solution_unique_name`, `raw_dependencies`, `component_layers`,
  `customizations`, `customized_dependencies`
- Unit tests under `tests/unit/modules/preprocessing/`

## References

- 02_ARCHITECTURE/PIPELINES.md — Input Pipeline responsibilities
- 02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md — solution resolution, dependencies,
  component-layer classification, filtering & hydration
- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — dependency, layer, function/query APIs
- src/modules/transformation/migration_step.py — MigrationPipelineStep
- src/modules/transformation/models/migration_context.py — MigrationContext
