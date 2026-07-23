# TASK-018 — Implement RULE-006 — Disable Unsupported-Trigger Topics

| Field      | Value                                  |
| ---------- | -------------------------------------- |
| ID         | TASK-018                               |
| Workstream | 2 — Incremental Migration Rules        |
| Status     | DONE                                   |
| Consumes   | RULE-006, TASK-012, TASK-020           |

## Description

Implement RULE-006 — disable + deprecate topics whose trigger is one of the
additional unsupported kinds (`OnUnknownIntent`, `OnPlanComplete`,
`OnSystemRedirect`, `OnSelectIntent`, `OnEscalate`), beyond OnActivity (RULE-003)
and OnGeneratedResponse (RULE-004). Source of truth: the CA→DA component support
analysis.

Delivered as one thin step per trigger, each subclassing the shared
`UnsupportedTopicTriggerStep` base (which handles a single trigger + a tailored
mitigation message), registered in `build_transformation_pipeline`. Uses the
shared `deprecate_topic` action (disable `statecode`/`statuscode`, `[DEPRECATED]`
`name`, preserve logic, warn, and record a per-topic change — TASK-020).

## Acceptance Criteria

- [x] One step per trigger (`HandleOnUnknownIntentTopicStep`,
  `HandleOnPlanCompleteTopicStep`, `HandleOnSystemRedirectTopicStep`,
  `HandleOnSelectIntentTopicStep`, `HandleOnEscalateTopicStep`) registered in the
  Transformation Pipeline.
- [x] Topics with any listed unsupported trigger are disabled + `[DEPRECATED]`-prefixed
  (idempotent, MIG-005), all logic preserved; supported triggers untouched.
- [x] Edits staged via `context.writeback`; per-topic change recorded (RULE-006).
- [x] `supported_modes=("READONLY", "WRITEBACK")`.
- [x] Unit tests pass; quality gates pass.

## Deliverables

- `src/modules/transformation/steps/unsupported_construct_base.py` —
  `UnsupportedTopicTriggerStep` base + shared `deprecate_topic` action
- `src/modules/transformation/steps/handle_on_unknown_intent_topic_step.py`,
  `handle_on_plan_complete_topic_step.py`, `handle_on_system_redirect_topic_step.py`,
  `handle_on_select_intent_topic_step.py`, `handle_on_escalate_topic_step.py`
- Registration in `build_transformation_pipeline`; unit tests

## References

- 01_PRODUCT/MIGRATION_RULES.md — RULE-006
- 04_EXECUTION/tasks/TASK-012-rule-003-handle-onactivity-topic.md — the base pattern
- 04_EXECUTION/tasks/TASK-020-per-topic-migration-report.md — per-topic report
- 02_ARCHITECTURE/PIPELINES.md — Transformation stage
