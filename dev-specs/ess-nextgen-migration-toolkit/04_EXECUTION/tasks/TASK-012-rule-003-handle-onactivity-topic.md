# TASK-012 — Implement RULE-003 — Handle OnActivity Topic

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-012                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | TODO                              |
| Consumes   | RULE-003                          |

## Description

Implement RULE-003 as a Migration Step that handles the OnActivity topic,
following the established framework pattern. The framework architecture remains
unchanged.

## Acceptance Criteria

- [ ] `HandleOnActivityTopicStep` is delivered as the Pipeline Step that
  implements RULE-003 and is registered in the migration pipeline.
- [ ] Each OnActivity topic is disabled and its title is prefixed once with
  `[DEPRECATED]` (idempotent), with all original logic preserved and customer
  guidance to move it under OnConversationStart or discard, per RULE-003.
- [ ] Preview and Writeback modes are supported.
- [ ] Unit Tests and Golden Tests pass.
- [ ] The framework architecture is unchanged.

## Deliverables

- `HandleOnActivityTopicStep` (Pipeline Step)
- Unit Tests
- Golden Tests

## References

- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
