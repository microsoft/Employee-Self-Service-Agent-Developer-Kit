# TASK-020 — Per-Topic Migration Report

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-020                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
| Consumes   | TASK-016, TASK-005        |

## Description

Give the migration report a **per-topic view**: for a given topic, which rules
acted on it and what mitigation / workaround / transformation was applied. Every
transformation rule that touches a topic records a structured change; the Reporter
tabulates them per topic. This is valuable in **READONLY** (a preview of exactly
what the tool would do to each topic) as well as WRITEBACK.

Implementation:

- A shared `record_topic_change(logger, component, *, rule_id, rule_name, message)`
  helper (`src/modules/transformation/steps/topic_change_log.py`) that formats a
  stable topic label (`name [schemaname]`) and appends a `ChangeEntry` via the
  Logger's `LogChange` → `context.Changes` collector.
- Every topic rule records on action: RULE-002 (replace), RULE-003/004/006
  (disable trigger), RULE-007 (disable node).
- The Reporter adds a **"Per-Topic Migration Summary"** section grouping
  `context.Changes` by component (topic) → the rules + mitigations applied.

## Acceptance Criteria

- [x] `record_topic_change` helper appends a per-topic `ChangeEntry` (rule_id,
  title, component label, message).
- [x] RULE-002/003/004/006/007 each record a per-topic change when they act.
- [x] The Reporter renders a "Per-Topic Migration Summary" grouped by topic, in
  both READONLY and WRITEBACK.
- [x] Unit tests (reporter grouping + per-rule recording) pass; quality gates pass.

## Deliverables

- `src/modules/transformation/steps/topic_change_log.py`
- `src/service/reporter.py` — per-topic summary section
- Wiring in the RULE-002/003/004/006/007 steps
- Unit tests

## References

- 03_ENGINEERING/DIAGNOSTICS.md — report model + collectors
- 01_PRODUCT/MIGRATION_RULES.md — the rules that record per-topic changes
- src/core/models/execution_context.py — `ChangeEntry` / `Changes` collector
