# TASK-012 — Implement RULE-003 — Handle OnActivity Topic

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-012                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | DONE                              |
| Consumes   | RULE-003, TASK-006, TASK-016, TASK-017 |

## Description

Implement RULE-003 as a Transformation Step (`HandleOnActivityTopicStep`) that
deprecates each **OnActivity** topic. Follow the framework pattern established by
`ApplyDaCompatibilityStep` (TASK-016): a `MigrationPipelineStep` that reads its
targets from `context.customizations` and **stages** its edits on the
`WritebackPlan` (TASK-017) — no Dataverse I/O, never appends to `pending_writes`.

**Input.** Iterate `context.customizations`
(`dict[str, CustomizationComponent]`, Topic V2 topics). The OnActivity trigger is
identified from the topic's `data` YAML (`beginDialog.kind == "OnActivity"`), but
the **title and disabled state are record fields, NOT in the `data` YAML** (see
bring-up findings below). Its record is `botcomponents({component_id})`.

**Staging (chaining- and no-op-safe).** Detect the trigger from `component.data`,
then stage the record-field edits (title + disabled state) — NOT `data`:

```python
if not is_on_activity_topic(component.data):
    continue
target = context.writeback.target(
    "botcomponents",
    component.component_id,
    original={"name": component.name, "statecode": ..., "statuscode": ...},
)
target.set("name", deprecate_title(target.get("name")))   # "[DEPRECATED] " once
target.set("statecode", _INACTIVE_STATECODE)              # disable
target.set("statuscode", _INACTIVE_STATUSCODE)
```

### Bring-up findings (from RULE-002, TASK-011)

- A topic's `data` YAML root is `kind: AdaptiveDialog` + `inputs` /
  `modelDescription` / `beginDialog` / `inputType` / `outputType` **only** — it
  does **not** contain the topic title or an enabled/disabled flag (verified
  against the `ess-samples` topic YAMLs).
- **Trigger type** = `beginDialog.kind` in `data` (e.g. `OnActivity`,
  `OnGeneratedResponse`, `OnRecognizedIntent`). Detect from `data`; do not modify
  `data` for this rule.
- **Title** = the botcomponent `name` field (hydrated as
  `CustomizationComponent.name`). Prefix `"[DEPRECATED] "` once (idempotent).
- **Disable** = the botcomponent `statecode`/`statuscode` (standard Dataverse
  Inactive is `statecode=1`, `statuscode=2`). **UNCONFIRMED** for Copilot topics —
  isolate the values as module constants and confirm live under TASK-009
  (`./mtk.sh run --dev` WRITEBACK), per the existing UNCONFIRMED-field pattern.
  `CustomizationComponent` does not yet hydrate statecode/statuscode; either read
  them from the layer's `msdyn_componentjson` attributes or extend hydration.
- **Idempotency (MIG-005)**: skip when the topic is already Inactive AND `name`
  already starts with `[DEPRECATED]`.
- **Migration warning**: emit via the diagnostics warning collector the Reporter
  renders (confirm the exact API used by existing steps, e.g. `logger.LogWarning`
  vs a context collector).

## Acceptance Criteria

- [x] `HandleOnActivityTopicStep` is a `MigrationPipelineStep` registered in the
  Transformation Pipeline after `ApplyDaCompatibilityStep`.
- [x] Each OnActivity topic is disabled (`statecode`/`statuscode` → Inactive pair)
  and its `name` prefixed once with `[DEPRECATED]`, all topic `data` logic preserved
  (never rewritten), and a manual-review warning emitted, per RULE-003.
- [x] Idempotent (MIG-005): a topic already Inactive AND `[DEPRECATED]`-prefixed is
  skipped; `topic_trigger_kind` + title-prefix are pure and unit-tested.
- [x] Edits are staged via `context.writeback` (record fields `name`/`statecode`/
  `statuscode`); unchanged/other-trigger topics produce no write.
- [x] `supported_modes=("READONLY", "WRITEBACK")`.
- [x] Unit Tests and a Golden Test pass.
- [x] The framework architecture is unchanged.

## Deliverables

- `src/modules/transformation/steps/handle_on_activity_topic_step.py`
  (`HandleOnActivityTopicStep`)
- `src/modules/transformation/steps/deprecate_trigger_topic_step.py`
  (shared `DeprecateTriggerTopicStep` base + `topic_trigger_kind` — also used by RULE-004)
- `CustomizationComponent` extended with `statecode`/`statuscode` (hydrated in
  `RetrieveCustomizationsStep`)
- Registration in `build_transformation_pipeline`
- Unit Tests + Golden Test

## References

- 02_ARCHITECTURE/PIPELINES.md — Transformation stage + writeback-plan contract
- 02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md — customizations input, §7 writeback
- 04_EXECUTION/tasks/TASK-016-transformation-da-compatibility.md — step pattern
- 04_EXECUTION/tasks/TASK-017-writeback-plan.md — staging API
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
