# TASK-016 — Transformation: DA-Compatibility Rewrite

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-016                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
| Consumes   | TASK-006, TASK-002        |

## Description

Implement the **first Transformation step**
(`src/modules/transformation/steps/apply_da_compatibility_step.py`) that makes a
CA agent DA-compatible. A CA agent becomes a DA agent only when its GPT-model
nomenclature and template are DA-compatible. A customer overlay (e.g. renaming
the agent, editing instructions/starters) keeps overriding the managed base even
after a major-version update, so the effective record can still point at the
CA values (`PreviewModels` / `default-*`) and **block** the CA→DA transition.
This step rewrites them.

It consumes the agent artifacts hydrated by TASK-006
(`context.agent_bot_record`, `context.agent_gpt_component`) and produces
`context.pending_writes` for the Output stage (TASK-007) to persist. It performs
**no** Dataverse I/O itself (transformation steps never call Dataverse directly).

**Boundary.** This task is the *producer* of `pending_writes`; TASK-007 (Output)
is the *consumer* that validates and persists them. Confirming the DA-compat
field names (`template` / `configuration` / `data` / `botcomponentid`) against a
**live** record is an end-to-end concern owned by TASK-009 (run under
`./mtk.sh start --dev` in WRITEBACK mode) — it is not a per-step blocker here.

### Transforms (all idempotent)

1. **gpt.default `data` (YAML)** — `kind: PreviewModels` (+ the now-orphaned
   `modelNameHint:` line) → `kind: MicrosoftCopilotModels`. Line-anchored regex
   preserves indentation.
2. **bot `template`** — `default-*` → `gptagent-1.0.0`.
3. **bot `configuration` (JSON)** — add
   `aISettings.model = {"$kind": "MicrosoftCopilotModels"}` when `aISettings` is
   present and not already DA.

Model *names* are intentionally retained; only the model kind / template /
config nomenclature changes. Records already at DA values produce no pending
write. See `02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md` section 6.

### Architecture constraints

- The step is a `MigrationPipelineStep` subclass with
  `supported_modes=("READONLY", "WRITEBACK")` — it always runs (writeback is
  gated separately in the Output stage); READONLY still computes and reports the
  intended writes.
- Registered as the **first** step of the Transformation Pipeline
  (`build_transformation_pipeline`), ahead of the Migration Rules (RULE-001..004).
- Pure transform functions (`transform_bot_template`,
  `transform_bot_configuration`, `transform_gpt_data`) are unit-testable in
  isolation and return `(value, changed)`.

## Acceptance Criteria

- [x] `transform_gpt_data` rewrites `PreviewModels` → `MicrosoftCopilotModels`
  and strips `modelNameHint`, preserving indentation; idempotent.
- [x] `transform_bot_template` rewrites `default-*` → `gptagent-1.0.0`; idempotent.
- [x] `transform_bot_configuration` injects the DA model into `aISettings`;
  idempotent; tolerant of non-JSON / unexpected shapes.
- [x] Only changed records append to `context.pending_writes`
  (`{"entity_set", "record_id", "changes"}`).
- [x] Step is a `MigrationPipelineStep` and performs no Dataverse I/O.
- [x] Unit tests cover each transform + the step's pending-write assembly.
- [x] Registered as the first step of `build_transformation_pipeline`.
- [x] Quality gates pass (`ruff`, `mypy`, `pytest`; enforced in CI).

> Live confirmation of the transform-target field names against a real record
> moved to TASK-009 (E2E validation) — see the Boundary note above.

## Deliverables

- `src/modules/transformation/steps/apply_da_compatibility_step.py`
- `context.pending_writes` contract on `MigrationContext`
- Unit tests under `tests/unit/modules/transformation/`

## References

- 02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md — DA-compatibility transforms
- 02_ARCHITECTURE/PIPELINES.md — Transformation Pipeline responsibilities
- src/modules/transformation/migration_step.py — MigrationPipelineStep
- src/modules/transformation/models/migration_context.py — `pending_writes`,
  `agent_bot_record`, `agent_gpt_component`
