# TASK-011 — Implement RULE-002 — Replace EndConversation Node

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-011                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | DONE                              |
| Consumes   | RULE-002, TASK-006, TASK-016, TASK-017 |

## Description

Implement RULE-002 as a Transformation Step (`ReplaceEndConversationStep`) that
rewrites the **EndConversation** node inside each customized topic's `data` YAML.
Follow the framework pattern established by `ApplyDaCompatibilityStep` (TASK-016):
a `MigrationPipelineStep` that reads its targets from the context and **stages**
its edits on the `WritebackPlan` (TASK-017) — it performs **no** Dataverse I/O and
never appends to `pending_writes` directly.

**Input.** The step iterates `context.customizations`
(`dict[str, CustomizationComponent]`, already filtered to Topic V2 topics owned by
the ESS HR/IT agent — see TASK-006). Each component's topic definition is
`component.data` (YAML); its record is `botcomponents({component_id})`.

**Staging (chaining- and no-op-safe).** For each topic:

```python
target = context.writeback.target(
    "botcomponents", component.component_id, original={"data": component.data}
)
target.set("data", replace_end_conversation(target.get("data")))
```

Reading `target.get("data")` composes with any earlier rule that edited the same
topic; the plan diffs vs the original so an unchanged topic yields no write.

## Acceptance Criteria

- [x] `ReplaceEndConversationStep` is a `MigrationPipelineStep` registered in the
  Transformation Pipeline (`build_transformation_pipeline`) after
  `ApplyDaCompatibilityStep`.
- [x] Every EndConversation node in a topic's `data` YAML is replaced with an End
  All Topics (CancelAllDialogs) node per RULE-002, preserving node connectivity
  and all other topic logic.
- [x] The transform is **idempotent** (re-running yields no further change) and a
  pure function unit-tested independently of the step.
- [x] Edits are staged via `context.writeback` — the step never appends to
  `pending_writes`; unchanged topics produce no write.
- [x] `supported_modes=("READONLY", "WRITEBACK")` (READONLY previews via
  `pending_writes`; WRITEBACK persists — the Output stage, TASK-007, applies them).
- [x] Unit Tests and Golden Tests (YAML before/after fixtures) pass.
- [x] The framework architecture is unchanged.

## Deliverables

- `src/modules/transformation/steps/replace_end_conversation_step.py`
  (`ReplaceEndConversationStep` + a pure `replace_end_conversation(data)` transform)
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
