# TASK-013 — Implement RULE-004 — Handle OnGeneratedResponse Topic

| Field      | Value                             |
| ---------- | --------------------------------- |
| ID         | TASK-013                          |
| Workstream | 2 — Incremental Migration Rules   |
| Status     | TODO                              |
| Consumes   | RULE-004                          |

## Description

Implement RULE-004 as a Migration Step that handles the OnGeneratedResponse
topic, following the established framework pattern. The framework architecture
remains unchanged.

## Acceptance Criteria

- [ ] `HandleGeneratedResponseTopicStep` is delivered as the Pipeline Step that
  implements RULE-004 and is registered in the migration pipeline.
- [ ] Each OnGeneratedResponse topic is disabled and its title is prefixed once
  with `[DEPRECATED]` (idempotent), with all topic logic preserved, per
  RULE-004.
- [ ] Preview and Writeback modes are supported.
- [ ] Unit Tests and Golden Tests pass.
- [ ] The framework architecture is unchanged.

## Deliverables

- `HandleGeneratedResponseTopicStep` (Pipeline Step)
- Unit Tests
- Golden Tests

## References

- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
