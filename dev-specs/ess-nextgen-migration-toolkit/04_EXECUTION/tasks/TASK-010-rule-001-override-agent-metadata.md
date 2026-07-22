# TASK-010 — RULE-001: Override Agent Instructions

| Field      | Value                          |
| ---------- | ------------------------------ |
| ID         | TASK-010                       |
| Workstream | 1 — First Vertical Slice       |
| Status     | TODO                           |
| Consumes   | RULE-001                       |

## Description

Implement RULE-001 — the **Agent Instructions** override — as a dedicated
Transformation step. This is the piece of the agent-metadata migration that the
foundational `ApplyDaCompatibilityStep` (TASK-016) does **not** cover.

Scope (this task):

* Override **Agent Instructions** (the Overview-page system prompt) with the
  Declarative Agent instructions.

Explicitly **out of scope** (already delivered by `ApplyDaCompatibilityStep`,
TASK-016):

* Template (`default-*` → `gptagent-1.0.0`) — and the Runtime Provider switch it
  effects
* AI Model Kind (`PreviewModels` → `MicrosoftCopilotModels`)
* Configuration model block

Like every transformation step, it produces `context.pending_writes` (no direct
Dataverse I/O); persistence is TASK-007 (Output), gated to WRITEBACK mode. A new
step is expected here — it does not exist yet.

## Acceptance Criteria

- [ ] `OverrideAgentInstructionsStep` is delivered as the Pipeline Step that
  implements RULE-001, registered in `build_transformation_pipeline` after
  `ApplyDaCompatibilityStep`.
- [ ] The agent's instructions are overridden with the DA instructions
  (idempotent — re-running does not double-apply).
- [ ] The step appends to `context.pending_writes`; it performs no Dataverse I/O.
- [ ] The change is recorded to the report model (`LogChange` / `context.Changes`).
- [ ] Unit Tests and Golden Tests pass; covered by TASK-009 end-to-end validation.
- [ ] Quality gates pass.

## Deliverables

- `src/modules/transformation/steps/override_agent_instructions_step.py`
  (`OverrideAgentInstructionsStep`)
- Unit Tests + Golden Tests under `tests/`

## References

- 01_PRODUCT/MIGRATION_RULES.md — RULE-001 (Override Agent Instructions)
- 02_ARCHITECTURE/PIPELINES.md — Transformation Pipeline, step registration
- 04_EXECUTION/tasks/TASK-016-transformation-da-compatibility.md — the
  foundational DA-compat step this builds on (nomenclature already handled there)
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md

