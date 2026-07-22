# TASKS.md

# ESS NextGen Migration Toolkit — Implementation Tasks

> **Purpose**
>
> This document defines the implementation backlog for the ESS NextGen Migration Toolkit.
>
> Unlike the architectural specifications, this is a **living document**.
>
> Every implementation task shall originate from an approved specification and, where applicable, from a corresponding Migration Rule.
>
> As new migration rules are introduced, this document shall be updated with the corresponding implementation tasks.
>
> Upon completion, tasks shall be marked accordingly while preserving implementation history.

---

# 1. Execution Philosophy

Development follows **Specification-Driven Development (SDD).**

Implementation always follows the sequence:

```text
Specification

↓

Migration Rule

↓

Implementation Task

↓

Implementation

↓

Testing

↓

Completion
```

Implementation must never precede specification.

---

# 2. Task Lifecycle

Every task uses **exactly one** of these four canonical statuses (no other
values are permitted in a task header or the index table below):

| Status    | Meaning                                                            |
| --------- | ----------------------------------------------------------------- |
| `TODO`    | Not started; ready to be picked up once its `Consumes` are met.    |
| `ACTIVE`  | Being implemented right now (a worktree/branch is in flight).      |
| `BLOCKED` | Cannot proceed until a dependency or decision is resolved.         |
| `DONE`    | Merged and meets the Definition of Done (section 5).               |

```text
TODO  →  ACTIVE  →  DONE
             ↕
          BLOCKED
```

Completed tasks shall remain in this document for traceability.

---

# 2a. Task Anatomy

Every task is defined in its own file under `04_EXECUTION/tasks/`, named
`TASK-XXX-<slug>.md`. This document is the **index**; the per-task files are the
authoritative task definitions. Each task declares the documents required to
implement it, so that agents and contributors resolve only the specifications a
task actually needs (see the Dependency-Based Loading Model in `AGENTS.md`).

Each task file follows a fixed structure:

* **Header table** — `ID`, `Workstream`, `Status`, and `Consumes`.
* **Description** — what the task delivers and its scope.
* **Acceptance Criteria** — the checkbox conditions that must all hold for the
  task to be considered DONE (derived from the Deliverables and the global
  Definition of Done in section 5).
* **Deliverables** — the concrete artifacts the task produces.
* **References** — the exact specifications required to implement the task,
  given as paths relative to the specification root
  (e.g. `02_ARCHITECTURE/PIPELINES.md`).

The header table also declares:

* **Consumes** — the governing Migration Rule(s) the task implements
  (e.g. `RULE-003`). Foundation tasks that implement no business rule use `—`.

Example header:

```text
| Field    | Value    |
| ID       | TASK-012 |
| Status   | TODO     |
| Consumes | RULE-003 |
```

Resolving a task's `References` replaces reading every specification on every
task.

---

# 3. Workstream 0 — Repository Foundation

## Goal

Produce the first runnable version of the migration toolkit.

The objective of this workstream is **not** to perform migrations.

Instead, it establishes the complete framework, wiring, and developer experience so that future migration rules can be implemented with minimal effort.

| Task                                                     | Title                          | Status | Consumes |
| -------------------------------------------------------- | ------------------------------ | ------ | -------- |
| [TASK-001](tasks/TASK-001-repository-scaffold.md)        | Repository Scaffold            | DONE   | —        |
| [TASK-002](tasks/TASK-002-pipeline-framework.md)         | Pipeline Framework             | DONE   | —        |
| [TASK-003](tasks/TASK-003-migration-orchestrator.md)     | Migration Orchestrator         | TODO   | TASK-002, TASK-005, TASK-015 |
| [TASK-004](tasks/TASK-004-dataverse-client.md)           | Dataverse Client               | DONE   | —        |
| [TASK-005](tasks/TASK-005-diagnostics-framework.md)      | Diagnostics Framework          | DONE   | —        |
| [TASK-006](tasks/TASK-006-preprocessing-pipeline.md)     | Preprocessing: Agent Config + Customization Discovery | DONE | TASK-015, TASK-004 |
| [TASK-007](tasks/TASK-007-postprocessing-pipeline.md)    | Postprocessing Pipeline        | TODO   | TASK-015, TASK-004, TASK-005, TASK-016 |
| [TASK-008](tasks/TASK-008-authentication-token-provider.md) | Authentication Token Provider | DONE   | —        |
| [TASK-009](tasks/TASK-009-end-to-end-framework-validation.md) | End-to-End Framework Validation | BLOCKED | TASK-003, TASK-006, TASK-007 |
| [TASK-015](tasks/TASK-015-input-pipeline-auth-discovery.md) | Input Pipeline: Auth + Agent Discovery + Orchestrator Wiring | DONE | TASK-002, TASK-005, TASK-008 |
| [TASK-016](tasks/TASK-016-transformation-da-compatibility.md) | Transformation: DA-Compatibility Rewrite | ACTIVE | TASK-006, TASK-002 |

---

# Workstream 1 — First Vertical Slice

## Goal

Deliver the first fully functional migration capability.

The toolkit should now perform one real migration end-to-end.

| Task                                                              | Title                                  | Status | Consumes |
| ----------------------------------------------------------------- | -------------------------------------- | ------ | -------- |
| [TASK-010](tasks/TASK-010-rule-001-override-agent-metadata.md)    | Implement RULE-001 — Override Agent Metadata | TODO | RULE-001 |

---

# Workstream 2 — Incremental Migration Rules

Every subsequent workstream adds one or more Migration Rules.

The framework architecture should remain unchanged.

| Task                                                                   | Title                                       | Status | Consumes |
| ---------------------------------------------------------------------- | ------------------------------------------- | ------ | -------- |
| [TASK-011](tasks/TASK-011-rule-002-replace-endconversation-node.md)    | Implement RULE-002 — Replace EndConversation Node | TODO | RULE-002 |
| [TASK-012](tasks/TASK-012-rule-003-handle-onactivity-topic.md)         | Implement RULE-003 — Handle OnActivity Topic | TODO  | RULE-003 |
| [TASK-013](tasks/TASK-013-rule-004-handle-ongeneratedresponse-topic.md) | Implement RULE-004 — Handle OnGeneratedResponse Topic | TODO | RULE-004 |

---

Future Migration Rules shall be appended as new task files under
`04_EXECUTION/tasks/` and listed above as they are specified in
`MIGRATION_RULES.md`.

---

# Workstream 3 — Final Validation

## Goal

Sign off the toolkit against a real migration. This workstream runs **last**,
after all Migration Rules are implemented. `TASK-999` is a sentinel ID: it
always sorts to the end of the backlog and is the final manual gate before a
release.

| Task                                                     | Title                          | Status | Consumes |
| -------------------------------------------------------- | ------------------------------ | ------ | -------- |
| [TASK-999](tasks/TASK-999-manual-e2e-validation.md)      | Manual End-to-End Validation   | BLOCKED | TASK-009 |

---

# 4. Living Backlog

This section intentionally remains open-ended.

Whenever:

* A new unsupported CA construct is identified,
* A new migration strategy is approved, or
* MCS introduces new platform capabilities,

the following updates shall occur:

1. Add or update the corresponding rule in `MIGRATION_RULES.md`.
2. Add the implementation task to this document, declaring its `Consumes`
   (governing Rule) and `References` (required specifications) sections.
3. Implement the Pipeline Step.
4. Add tests.
5. Mark the task as complete.

This keeps the implementation backlog synchronized with the business specification.

---

# 5. Definition of Done

A task is considered complete only when:

* Implementation is complete.
* Tests pass.
* Logging is implemented.
* Reports are updated.
* Documentation is updated wherever applicable — README, any affected
  dev-specs, the top-level Copilot instructions mirror
  (`.github/instructions/ess-nextgen-toolkit.instructions.md`), and
  CHANGELOG.md — so specifications and implementation stay synchronized. In
  particular, any change to the layer/dependency model, repository structure,
  invariants, dependency-management workflow, or naming conventions must be
  reflected in that instructions file, which only summarizes the canonical
  specs.
* No specification violations exist.
* Corresponding Migration Rule is implemented.
* Task status is updated to **DONE**.

---

# 6. Traceability

Every implementation task should map directly to:

| Artifact       | Convention              |
| -------------- | ----------------------- |
| Migration Rule | RULE-XXX                |
| Pipeline Step  | `<RuleName>Step`        |
| Unit Test      | `test_<rule>.py`        |
| Golden Test    | `test_<rule>_golden.py` |
| Task           | TASK-XXX                |
| Changelog      | Rule reference          |

This ensures complete traceability from business requirement through implementation and validation.

---

# 7. Specification Dependencies

**Consumes**

* MIGRATION_RULES.md
* IMPLEMENTATION_GUIDE.md
* CODING_STANDARDS.md
* TESTING.md

**Referenced By**

* CHANGELOG.md

This document is the authoritative implementation backlog for the ESS NextGen Migration Toolkit and shall evolve throughout the lifetime of the project.
