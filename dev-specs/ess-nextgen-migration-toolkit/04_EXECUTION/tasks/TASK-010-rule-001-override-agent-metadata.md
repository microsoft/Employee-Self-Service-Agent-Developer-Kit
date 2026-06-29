# TASK-010 — Implement RULE-001 — Override Agent Metadata

| Field      | Value                          |
| ---------- | ------------------------------ |
| ID         | TASK-010                       |
| Workstream | 1 — First Vertical Slice       |
| Status     | TODO                           |
| Consumes   | RULE-001                       |

## Description

Implement the first production migration rule, delivering the first fully
functional migration capability end-to-end.

Scope includes:

* Override Agent Instructions
* Override Runtime Provider
* Override Template
* Override Model Kind

Both execution modes are supported:

* Preview mode
* Writeback mode

The orchestration entry point exposes:

```text
--preview

--writeback
```

Preview shall produce reports without modifying Dataverse. Writeback shall
persist the migrated component.

## Acceptance Criteria

- [ ] `OverrideAgentMetadataStep` is delivered as the Pipeline Step that
  implements RULE-001 and is registered in the migration pipeline.
- [ ] Agent Instructions, Runtime Provider, Template, and Model Kind are
  overridden per RULE-001.
- [ ] Preview mode produces reports without modifying Dataverse.
- [ ] Writeback mode persists the migrated component through the Dataverse
  client.
- [ ] The orchestration entry point exposes `--preview` and `--writeback`.
- [ ] Unit Tests, Golden Tests, and End-to-End validation pass.

## Deliverables

- `OverrideAgentMetadataStep`
- Unit Tests
- Golden Tests
- End-to-End validation

## References

- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
