# TASK-011 — Implement RULE-002 — Replace EndConversation Node

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-011                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | TODO                              |
| Consumes   | RULE-002                          |

## Description

Implement RULE-002 as a Migration Step that replaces the EndConversation node,
following the same framework pattern established by RULE-001. The framework
architecture remains unchanged.

## Acceptance Criteria

- [ ] `ReplaceEndConversationStep` is delivered as the Pipeline Step that
  implements RULE-002 and is registered in the migration pipeline.
- [ ] Every EndConversation node is replaced with an End All Topics
  (CancelAllDialogs) node per RULE-002, preserving node connectivity.
- [ ] Preview and Writeback modes are supported.
- [ ] Unit Tests and Golden Tests pass.
- [ ] The framework architecture is unchanged.

## Deliverables

- `ReplaceEndConversationStep` (Pipeline Step)
- Unit Tests
- Golden Tests

## References

- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
