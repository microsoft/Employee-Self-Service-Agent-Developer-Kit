# TASK-013 — Implement RULE-004 — Handle OnGeneratedResponse Topic

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-013                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | DONE                              |
| Consumes   | RULE-004, TASK-006, TASK-016, TASK-017 |

## Description

Implement RULE-004 as a Transformation Step (`HandleGeneratedResponseTopicStep`)
that deprecates each **OnGeneratedResponse** topic. Follow the framework pattern
established by `ApplyDaCompatibilityStep` (TASK-016): a `MigrationPipelineStep`
that reads its targets from `context.customizations` and **stages** its edits on
the `WritebackPlan` (TASK-017) — no Dataverse I/O, never appends to
`pending_writes`.

**Input.** Iterate `context.customizations`
(`dict[str, CustomizationComponent]`, Topic V2 topics). The OnGeneratedResponse
trigger is identified from the topic's `data` YAML
(`beginDialog.kind == "OnGeneratedResponse"`), but the **title and disabled state
are record fields, NOT in the `data` YAML** (see bring-up findings below). Its
record is `botcomponents({component_id})`.

**Staging (chaining- and no-op-safe).** Detect the trigger from `component.data`,
then stage the record-field edits (title + disabled state) — NOT `data`:

```python
if not is_generated_response_topic(component.data):
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

Identical mechanism to RULE-003 (TASK-012) — see its "Bring-up findings" section:
the topic title/enabled state are the botcomponent `name` + `statecode`/`statuscode`
record fields (not the `data` YAML); the trigger type is `beginDialog.kind` in
`data`; the Inactive `statecode`/`statuscode` values are **UNCONFIRMED** and must
be isolated as constants + confirmed live under TASK-009; idempotency (MIG-005)
skips a topic already Inactive with a `[DEPRECATED]`-prefixed `name`. Consider a
shared `_deprecate_topic` helper so RULE-003 and RULE-004 share the disable +
title-prefix logic and differ only in the trigger they match.

## Acceptance Criteria

- [x] `HandleGeneratedResponseTopicStep` is a `MigrationPipelineStep` registered in
  the Transformation Pipeline after `ApplyDaCompatibilityStep`.
- [x] Each OnGeneratedResponse topic is disabled (`statecode`/`statuscode` → Inactive
  pair) and its `name` prefixed once with `[DEPRECATED]`, all topic `data` logic
  preserved (never rewritten), and a manual-review warning emitted, per RULE-004.
- [x] Idempotent (MIG-005): a topic already Inactive AND `[DEPRECATED]`-prefixed is
  skipped; shares the `DeprecateTriggerTopicStep` base + `topic_trigger_kind` with RULE-003.
- [x] Edits are staged via `context.writeback` (record fields `name`/`statecode`/
  `statuscode`); unchanged/other-trigger topics produce no write.
- [x] `supported_modes=("READONLY", "WRITEBACK")`.
- [x] Unit Tests and a Golden Test pass.
- [x] The framework architecture is unchanged.

## Deliverables

- `src/modules/transformation/steps/handle_generated_response_topic_step.py`
  (`HandleGeneratedResponseTopicStep` — a thin subclass of the shared
  `DeprecateTriggerTopicStep`, differing only in the trigger it matches)
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
