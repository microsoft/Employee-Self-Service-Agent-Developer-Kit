# TASK-012 — Implement RULE-003 — Handle OnActivity Topic

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-012                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | TODO                              |
| Consumes   | RULE-003, TASK-006, TASK-016, TASK-017 |

## Description

Implement RULE-003 as a Transformation Step (`HandleOnActivityTopicStep`) that
deprecates each **OnActivity** topic. Follow the framework pattern established by
`ApplyDaCompatibilityStep` (TASK-016): a `MigrationPipelineStep` that reads its
targets from `context.customizations` and **stages** its edits on the
`WritebackPlan` (TASK-017) — no Dataverse I/O, never appends to `pending_writes`.

**Input.** Iterate `context.customizations`
(`dict[str, CustomizationComponent]`, Topic V2 topics). A topic's definition is
`component.data` (YAML); an OnActivity topic is identified from that YAML. Its
record is `botcomponents({component_id})`.

**Staging (chaining- and no-op-safe).**

```python
target = context.writeback.target(
    "botcomponents", component.component_id, original={"data": component.data}
)
target.set("data", deprecate_on_activity_topic(target.get("data")))
```

## Acceptance Criteria

- [ ] `HandleOnActivityTopicStep` is a `MigrationPipelineStep` registered in the
  Transformation Pipeline after `ApplyDaCompatibilityStep`.
- [ ] Each OnActivity topic is disabled and its title is prefixed once with
  `[DEPRECATED]` (idempotent), with all original logic preserved and customer
  guidance to move it under OnConversationStart or discard, per RULE-003.
- [ ] The transform is **idempotent** and a pure function unit-tested independently.
- [ ] Edits are staged via `context.writeback`; unchanged topics produce no write.
- [ ] `supported_modes=("READONLY", "WRITEBACK")`.
- [ ] Unit Tests and Golden Tests (YAML before/after fixtures) pass.
- [ ] The framework architecture is unchanged.

## Deliverables

- `src/modules/transformation/steps/handle_on_activity_topic_step.py`
  (`HandleOnActivityTopicStep` + a pure `deprecate_on_activity_topic(data)` transform)
- Registration in `build_transformation_pipeline`
- Unit Tests + Golden Tests

## References

- 02_ARCHITECTURE/PIPELINES.md — Transformation stage + writeback-plan contract
- 02_ARCHITECTURE/CUSTOMIZATION_DISCOVERY.md — customizations input, §7 writeback
- 04_EXECUTION/tasks/TASK-016-transformation-da-compatibility.md — step pattern
- 04_EXECUTION/tasks/TASK-017-writeback-plan.md — staging API
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
