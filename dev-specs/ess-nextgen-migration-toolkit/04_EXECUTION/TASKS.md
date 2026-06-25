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

Every task progresses through the following lifecycle.

```text
TODO

↓

IN PROGRESS

↓

BLOCKED

↓

DONE
```

Completed tasks shall remain in this document for traceability.

---

# 2a. Task Anatomy

Every task declares the documents required to implement it, so that agents and
contributors resolve only the specifications a task actually needs (see the
Dependency-Based Loading Model in `AGENTS.md`).

Each task may declare:

* **Consumes** — the governing Migration Rule(s) the task implements
  (e.g. `RULE-003`). Foundation tasks that implement no business rule omit this.
* **References** — the exact specifications required to implement the task,
  given as paths relative to the specification root
  (e.g. `02_ARCHITECTURE/PIPELINES.md`).

Example:

```text
TASK-012
Consumes
- RULE-003
References
- 02_ARCHITECTURE/PIPELINES.md
- 02_ARCHITECTURE/DOMAIN_MODEL.md
- 03_ENGINEERING/CODING_STANDARDS.md
- 03_ENGINEERING/TESTING.md
```

Resolving a task's `References` replaces reading every specification on every
task.

---

# 3. Workstream 0 — Repository Foundation

## Goal

Produce the first runnable version of the migration toolkit.

The objective of this workstream is **not** to perform migrations.

Instead, it establishes the complete framework, wiring, and developer experience so that future migration rules can be implemented with minimal effort.

---

### TASK-001

## Repository Scaffold

**Status**

TODO

**Description**

Create the repository structure defined in `REPOSITORY_STRUCTURE.md`.

**Deliverables**

* Folder scaffold
* Source layout
* Test layout
* Logs folder
* Reports folder
* Scripts folder
* README
* pyproject.toml

**References**

* 03_ENGINEERING/REPOSITORY_STRUCTURE.md

---

### TASK-002

## Pipeline Framework

**Status**

TODO

**Description**

Implement the Pipeline Framework.

**Deliverables**

* Pipeline Builder
* Pipeline Registry
* Pipeline Context
* Pipeline Step abstraction
* Fluent API

All registered Pipeline Steps may initially be no-op implementations.

**References**

* 02_ARCHITECTURE/ARCHITECTURE.md
* 02_ARCHITECTURE/PIPELINES.md

---

### TASK-003

## Migration Orchestrator

**Status**

TODO

**Description**

Implement the Migration Orchestrator.

Responsibilities include:

* User interaction
* Pipeline initialization
* Session lifecycle
* Pipeline execution

No migration logic.

**References**

* 02_ARCHITECTURE/ARCHITECTURE.md
* 02_ARCHITECTURE/DOMAIN_MODEL.md

---

### TASK-004

## Dataverse SDK

**Status**

TODO

**Description**

Implement the Dataverse REST wrapper.

Initial implementation includes:

* Authentication
* REST helpers
* Dependency APIs
* Component APIs
* Layer APIs
* Solution APIs
* Writeback APIs

Business logic is out of scope.

**References**

* 02_ARCHITECTURE/DATAVERSE_SDK.md

---

### TASK-005

## Diagnostics Framework

**Status**

TODO

**Description**

Implement diagnostics infrastructure.

Deliverables:

* Logger
* Session Manager
* Report Writer
* Console Output
* Log Files

All output shall use the framework Logger.

**References**

* 03_ENGINEERING/DIAGNOSTICS.md

---

### TASK-006

## Preprocessing Pipeline

**Status**

TODO

**Description**

Implement discovery and preprocessing.

Responsibilities:

* Discover ESS Agent
* Retrieve DependenciesForUninstall
* Retrieve Solution Component Layers
* Determine migration candidates
* Load canonical components

No migration transformations.

**References**

* 02_ARCHITECTURE/SERVICES.md
* 02_ARCHITECTURE/DATAVERSE_SDK.md
* 02_ARCHITECTURE/DOMAIN_MODEL.md

---

### TASK-007

## Postprocessing Pipeline

**Status**

TODO

**Description**

Implement post-processing.

Responsibilities:

* Validation
* Writeback
* Report generation

Migration logic is out of scope.

**References**

* 02_ARCHITECTURE/SERVICES.md
* 03_ENGINEERING/DIAGNOSTICS.md

---

### TASK-008

## Command Line Interface

**Status**

TODO

**Description**

Implement the CLI experience.

Support:

* Environment selection
* Agent selection
* Preferred Solution selection
* Execution mode
* Progress reporting

**References**

* 01_PRODUCT/CUSTOMER_JOURNEY.md
* 01_PRODUCT/MIGRATION_MODES.md
* 03_ENGINEERING/REPOSITORY_STRUCTURE.md

---

### TASK-009

## End-to-End Framework Validation

**Status**

TODO

**Description**

Validate that the toolkit executes end-to-end.

The pipeline shall execute successfully even though all Pipeline Steps are currently no-op implementations.

Deliverables:

* Working CLI
* Discovery
* Pipeline
* Logging
* Reports
* Empty writeback implementation

**References**

* 02_ARCHITECTURE/ARCHITECTURE.md
* 03_ENGINEERING/TESTING.md

---

# Workstream 1 — First Vertical Slice

## Goal

Deliver the first fully functional migration capability.

The toolkit should now perform one real migration end-to-end.

---

### TASK-010

## Implement RULE-001 — Override Agent Metadata

**Status**

TODO

**Consumes**

RULE-001

**Description**

Implement the first production migration rule.

Scope includes:

* Override Agent Instructions
* Override Runtime Provider
* Override Template
* Override Model Kind

Support both:

* Preview mode
* Writeback mode

CLI should expose:

```text
--preview

--writeback
```

Preview shall produce reports without modifying Dataverse.

Writeback shall persist the migrated component.

Deliverables:

* OverrideAgentMetadataStep
* Unit Tests
* Golden Tests
* End-to-End validation

**References**

* 02_ARCHITECTURE/PIPELINES.md
* 02_ARCHITECTURE/DOMAIN_MODEL.md
* 03_ENGINEERING/CODING_STANDARDS.md
* 03_ENGINEERING/TESTING.md

---

# Workstream 2 — Incremental Migration Rules

Every subsequent workstream adds one or more Migration Rules.

The framework architecture should remain unchanged.

---

### TASK-011

## Implement RULE-002 — Replace EndConversation Node

**Status**

TODO

**Consumes**

RULE-002

**References**

* 02_ARCHITECTURE/PIPELINES.md
* 02_ARCHITECTURE/DOMAIN_MODEL.md
* 03_ENGINEERING/CODING_STANDARDS.md
* 03_ENGINEERING/TESTING.md

---

### TASK-012

## Implement RULE-003 — Handle OnActivity Topic

**Status**

TODO

**Consumes**

RULE-003

**References**

* 02_ARCHITECTURE/PIPELINES.md
* 02_ARCHITECTURE/DOMAIN_MODEL.md
* 03_ENGINEERING/CODING_STANDARDS.md
* 03_ENGINEERING/TESTING.md

---

### TASK-013

## Implement RULE-004 — Handle OnGeneratedResponse Topic

**Status**

TODO

**Consumes**

RULE-004

**References**

* 02_ARCHITECTURE/PIPELINES.md
* 02_ARCHITECTURE/DOMAIN_MODEL.md
* 03_ENGINEERING/CODING_STANDARDS.md
* 03_ENGINEERING/TESTING.md

---

Future Migration Rules shall be appended below as they are specified in `MIGRATION_RULES.md`.

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
