# TASK-020 — Migration Report (component mitigations + run context)

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-020                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
| Consumes   | TASK-016, TASK-005        |

## Description

Give the customer-facing `migration_report.md` a **well-structured, polished
shape**: run context (environment/agents), the customizations extracted, a
per-component **mitigations table** (which rules acted on each topic and the
mitigation applied), warnings/errors, and a customer **Next Steps** checklist.
Every transformation rule that touches a topic records a structured change; the
Reporter tabulates them per component. This is valuable in **READONLY** (a preview
of exactly what the tool would do to each topic) as well as WRITEBACK.

Implementation:

- A shared `record_topic_change(logger, component, *, rule_id, rule_name, message)`
  helper (`src/modules/transformation/steps/topic_change_log.py`) that formats a
  stable topic label (`name [schemaname]`) and a component-type label
  (`botcomponent / Topic (V2)`), and appends a `ChangeEntry` via the Logger's
  `LogChange` → `context.Changes` collector (`ChangeEntry` gained a
  `component_type` field).
- Every topic rule records on action: RULE-002 (replace), RULE-003/004/006
  (disable trigger), RULE-007 (disable node).
- `AgentSelectionStep` retains the discovered ESS agents on
  `MigrationContext.discovered_agents` for the report.
- The Reporter (`src/service/reporter.py`, typed to `MigrationContext`) renders,
  in order: **Summary**, **Environment** (URL/tenant/user/target solution),
  **Agents** (discovered agents table + selected marker), **Customizations
  Extracted** (count + type/name/schema/state table), **Migration Mitigations by
  Component** (Component Type | Component | Mitigations Applied (Rules), one row per
  topic with all rules' mitigations merged via `<br>`), **Warnings** / **Errors**
  (numbered `# | Component | Reason/Error | Recommendation` tables), **Next Steps —
  Action Required** (checkbox checklist: validate + run your own end-to-end evals before
  promoting), a run status banner + emoji section headers, and a closing "Thanks for
  using the ESS Migration Toolkit (MTK)."

## Acceptance Criteria

- [x] `record_topic_change` helper appends a per-topic `ChangeEntry` (rule_id,
  title, component label, component_type, message).
- [x] RULE-002/003/004/006/007 each record a per-topic change when they act.
- [x] The Reporter renders the mitigations as a Markdown table (Component Type |
  Component | Mitigations Applied), one row per component, in READONLY + WRITEBACK.
- [x] The report includes Environment, Agents, Customizations Extracted, Next
  Steps, and the closing line; empty sections degrade gracefully.
- [x] Unit tests (reporter sections/table + per-rule recording + empty-state) pass;
  quality gates pass.

## Deliverables

- `src/modules/transformation/steps/topic_change_log.py`
- `src/service/reporter.py` — full report structure + mitigations table
- `src/core/models/execution_context.py` — `ChangeEntry.component_type`
- `src/modules/transformation/models/migration_context.py` — `discovered_agents`
- `src/modules/preprocessing/steps/agent_selection_step.py` — retain discovered agents
- Wiring in the RULE-002/003/004/006/007 steps
- Unit tests

## References

- 03_ENGINEERING/DIAGNOSTICS.md — report model + collectors
- 01_PRODUCT/MIGRATION_RULES.md — the rules that record per-component changes
- src/core/models/execution_context.py — `ChangeEntry` / `Changes` collector
