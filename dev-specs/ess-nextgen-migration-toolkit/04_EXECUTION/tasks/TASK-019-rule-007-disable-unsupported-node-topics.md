# TASK-019 — Implement RULE-007 — Disable Topics With Unsupported Nodes

| Field      | Value                                  |
| ---------- | -------------------------------------- |
| ID         | TASK-019                               |
| Workstream | 2 — Incremental Migration Rules        |
| Status     | DONE                                   |
| Consumes   | RULE-007, TASK-012, TASK-020           |

## Description

Implement RULE-007 — detect topics whose `data` uses an unsupported conversational
node (`IncludeSelectedTopics`, `InvokeAIBuilderModelAction`, `ConversationHistory`,
`RecognizeIntent`, `TransferConversationV2`, `SearchAndSummarizeContent`,
`AnswerQuestionWithAI`) and disable + deprecate the whole topic. Source of truth:
the CA→DA component support analysis. These nodes have no DA equivalent and no
automatic in-place mitigation today (tracked for later MCS waves), so — consistent
with unsupported triggers — the topic is disabled and flagged rather than partially
transformed.

Delivered as one thin step per node, each subclassing the shared
`UnsupportedNodeStep` base (which carries the node `kind:` token + a tailored
mitigation message), registered in `build_transformation_pipeline`. Each step
detects its node kind via a line-anchored regex over `data` (read-only; `data` is
never rewritten), then applies the shared `deprecate_topic` action, naming the
specific unsupported node in the per-topic report message (TASK-020).

## Acceptance Criteria

- [x] One step per unsupported node (`HandleAnswerQuestionWithAINodeStep`,
  `HandleRecognizeIntentNodeStep`, `HandleSearchAndSummarizeContentNodeStep`,
  `HandleTransferConversationV2NodeStep`, `HandleConversationHistoryNodeStep`,
  `HandleInvokeAIBuilderModelActionNodeStep`, `HandleIncludeSelectedTopicsNodeStep`)
  registered in the Transformation Pipeline.
- [x] Topics using any unsupported node are disabled + `[DEPRECATED]`-prefixed
  (idempotent, MIG-005), all logic preserved; clean topics untouched.
- [x] The specific unsupported node(s) are named in the per-topic report change (RULE-007).
- [x] Edits staged via `context.writeback`; `data` is not rewritten.
- [x] `supported_modes=("READONLY", "WRITEBACK")`.
- [x] Unit tests pass; quality gates pass.

## Notes / Follow-up

- The exact YAML `kind:` tokens for the unsupported nodes are analysis-sourced;
  confirm them against live topic `data` under TASK-009. If a token differs,
  update the `node_kind` on the corresponding `Handle*NodeStep` (each step owns
  its own token — no shared constant).

## Deliverables

- `src/modules/transformation/steps/unsupported_construct_base.py` —
  `UnsupportedNodeStep` base + shared `deprecate_topic` action
- `src/modules/transformation/steps/handle_answer_question_with_ai_node_step.py`,
  `handle_recognize_intent_node_step.py`, `handle_search_and_summarize_content_node_step.py`,
  `handle_transfer_conversation_v2_node_step.py`, `handle_conversation_history_node_step.py`,
  `handle_invoke_ai_builder_model_action_node_step.py`, `handle_include_selected_topics_node_step.py`
- Registration in `build_transformation_pipeline`; unit tests

## References

- 01_PRODUCT/MIGRATION_RULES.md — RULE-007
- 04_EXECUTION/tasks/TASK-020-per-topic-migration-report.md — per-topic report
- 04_EXECUTION/tasks/TASK-009-end-to-end-framework-validation.md — live node-token confirmation
- 02_ARCHITECTURE/PIPELINES.md — Transformation stage
