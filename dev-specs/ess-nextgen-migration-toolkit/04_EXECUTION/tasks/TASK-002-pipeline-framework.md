# TASK-002 — Pipeline Framework

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-002                  |
| Workstream | 0 — Repository Foundation |
| Status     | ACTIVE                      |
| Consumes   | —                         |

## Description

Implement the Pipeline Framework — the deterministic execution engine on which
all Migration Rules are built. The framework is **generic and typed**:
`Pipeline[TInput, TOutput]` and `PipelineStep[TInput, TOutput]`. The fluent
Builder type-threads adjacent steps (the output type of one step is the input
type of the next) and produces an immutable pipeline. The three ESS stage
pipelines instantiate the framework over the shared `MigrationContext`. All
registered Pipeline Steps may initially be no-op implementations.

## Acceptance Criteria

- [ ] A generic `Pipeline[TInput, TOutput]` and `PipelineStep[TInput, TOutput]`
  abstraction defines the typed contract every step implements.
- [ ] A fluent Pipeline Builder constructs an ordered, immutable pipeline and
  type-threads adjacent steps (incompatible composition fails at build time).
- [ ] A Pipeline Registry holds the ordered set of Pipeline Steps.
- [ ] A Pipeline Context threads through steps without hidden global state; a
  step enriches and returns the context (never replaces it with an unrelated
  type).
- [ ] A stage pipeline runs end-to-end with no-op steps and is deterministic
  (identical inputs produce identical ordering and output).
- [ ] The framework supports composing stage pipelines into the super-pipeline
  (`EssMigrationToolkit().input(...).migrate(...).output(...)`).

## Deliverables

- Generic `Pipeline[TInput, TOutput]` and `PipelineStep[TInput, TOutput]`
- Fluent, type-threading Pipeline Builder
- Pipeline Registry
- Pipeline Context contract
- Super-pipeline composition (`EssMigrationToolkit`)

## References

- 02_ARCHITECTURE/ARCHITECTURE.md
- 02_ARCHITECTURE/PIPELINES.md
