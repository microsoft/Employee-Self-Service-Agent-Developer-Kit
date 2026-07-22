# IMPLEMENTATION_GUIDE.md

# ESS NextGen Migration Toolkit — Implementation Guide
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the standard implementation workflow for all contributors to the ESS NextGen Migration Toolkit.
>
> It describes how implementation work is performed from specification through completion.
>
> This guide is mandatory for both AI agents and human contributors.

---

# 1. Guiding Philosophy

The project follows **Specification-Driven Development (SDD).**

Implementation never drives architecture.

Instead:

```text
Specification

↓

Architecture

↓

Task

↓

Implementation

↓

Testing

↓

Review

↓

Merge
```

Implementation is always a consequence of approved specifications.

---

# 2. Implementation Lifecycle

Every implementation follows the same lifecycle.

```text
Read Specifications

↓

Understand Architecture

↓

Select Task

↓

Implement

↓

Run Tests

↓

Review

↓

Update Changelog

↓

Complete
```

No step may be skipped.

---

# 3. Required Reading Order

Reading is **dependency-based, not sequential**. Do not read every
specification on every task. Follow the Specification Classification and the
Dependency-Based Loading Model defined in `AGENTS.md` (Sections 3, 3a, and 4),
which resolve only the documents a given task requires:

```text
Phase 0  Boot          AGENTS.md (always)
Phase 1  Resolve Task  04_EXECUTION/TASKS.md → locate TASK-XXX
Phase 2  Resolve Rule  01_PRODUCT/MIGRATION_RULES.md → only RULE-XXX (if referenced)
Phase 3  Constitution  00_META/PROJECT.md, INVARIANTS.md, VOCABULARY.md (always)
Phase 4  Architecture  02_ARCHITECTURE/* (read once per work session)
Phase 5  Engineering   03_ENGINEERING/* (read once per work session)
Phase 6  Context       01_PRODUCT/CUSTOMER_JOURNEY.md, MIGRATION_MODES.md,
                       00_META/ROADMAP.md (only if referenced by the task)
```

Resolve a task's exact required documents from its `References` section in
`TASKS.md`. Only after reading the resolved specifications may implementation
begin.

---

# 4. Task Selection

Every implementation must originate from a task.

Tasks shall define:

* Scope
* Acceptance Criteria
* Dependencies
* Deliverables

Implementation shall never begin without a corresponding task.

---

# 5. Before Writing Code

Before creating or modifying code, verify:

* Correct architectural layer
* Correct destination folder
* Existing reusable components
* Relevant Domain Models
* Relevant Services
* Relevant Pipeline Steps

Avoid introducing duplicate functionality.

---

# 6. Implementation Rules

Implementation shall:

* Follow architectural boundaries.
* Reuse existing framework components.
* Preserve deterministic execution.
* Operate on Domain Models.
* Use Services for reusable capabilities.
* Use the Dataverse client for all Dataverse communication.

Implementation shall not:

* Invent new architecture.
* Create speculative abstractions.
* Duplicate business logic.
* Bypass existing layers.

---

# 7. Pipeline Development

Every new migration capability should normally be implemented as a new Pipeline Step.

Example:

```
OverrideAgentInstructionsStep

ReplaceEndConversationStep

HandleOnActivityTopicStep

HandleGeneratedResponseTopicStep
```

Pipeline Steps should remain:

* Small
* Independent
* Testable

Pipeline composition occurs within the Transformation Pipeline.

---

# 8. Service Development

Create a new Service only when functionality is reusable across multiple Pipeline Steps.

Services should remain:

* Stateless
* Reusable
* Independently testable

Migration rules live exclusively in `src/modules/transformation/steps/`.
Reusable service capabilities outside `modules/` shall not contain
migration rules.

---

# 9. Dataverse Client Development

Dataverse Client changes are required only when:

* A new Dataverse REST API is consumed.
* Existing API behavior changes.
* Additional serialization is required.

Business logic never belongs inside the Dataverse client.

---

# 10. Testing

Every implementation must include appropriate tests.

Minimum expectation:

* Unit Tests
* Golden Tests (where deterministic transformations exist)
* Integration Tests (for Dataverse Client functionality where applicable)

No implementation is complete without tests.

---

# 11. Diagnostics

All runtime output shall use the framework Logger.

Direct use of:

```
print()
```

is prohibited.

Execution logs and the customer-facing report are written to the per-execution
session bundle:

```
output/session-YYYY-MM-DD_HH-MM-SS/
    migration_report.md
    session.log
```

---

# 12. Code Review Checklist

Before submitting changes, verify:

* Correct repository location.
* Correct architectural layer.
* No dependency violations.
* Uses Domain Models.
* Uses Services appropriately.
* Uses Dataverse Client appropriately.
* No direct Dataverse calls outside the Dataverse client.
* No direct console output.
* Tests added.
* Changelog updated.

---

# 13. Definition of Done

A task is complete only when all of the following are true:

* Acceptance Criteria satisfied.
* Code compiles.
* Tests pass.
* Logging implemented.
* Documentation updated where applicable.
* Changelog updated.
* No architectural violations.

---

# 14. When to Stop Implementation

Implementation shall stop immediately if:

* Specifications are ambiguous.
* Repository structure requires modification.
* Architectural boundaries are insufficient.
* Acceptance Criteria cannot be satisfied.
* A specification conflict is discovered.

In these cases, update the specifications before continuing.

---

# 15. Modification Rules

Contributors should prefer:

* Extending existing Pipeline Steps.
* Adding new Pipeline Steps.
* Extending Services.
* Extending Domain Models.

Avoid modifying framework infrastructure unless explicitly required.

---

# 16. Common Development Patterns

## Adding a New Transformation

1. Read relevant Migration Rule.
2. Create a new Pipeline Step.
3. Register the step in the Transformation Pipeline.
4. Add unit tests.
5. Update TASKS.md.
6. Update CHANGELOG.md.

---

## Adding a New Dataverse API

1. Extend `dataverse_client.py`.
2. Update the corresponding Service.
3. Add integration tests.
4. Update TASKS.md if required.

---

## Adding a New Component Type

1. Extend the Domain Model.
2. Update preprocessing.
3. Add Pipeline Steps.
4. Add validation.
5. Add tests.

---

# 17. AI Agent Responsibilities

AI agents shall:

* Read specifications before implementation.
* Preserve repository structure.
* Preserve architectural boundaries.
* Minimize code churn.
* Implement only the requested scope.
* Prefer composition over modification.

AI agents shall not:

* Invent requirements.
* Perform speculative refactoring.
* Reorganize folders.
* Introduce unnecessary abstractions.

---

# 18. Specification Precedence

Conflict resolution follows the rules defined in `AGENTS.md` Section 4
(Specification Hierarchy):

* `INVARIANTS.md` is supreme and always wins.
* Otherwise a lower Level number (see `AGENTS.md` Section 3) takes precedence
  over a higher one: Orchestrator (0) → Execution (1) → Business Rules (2) →
  Constitution (3) → Architecture (4) → Engineering (5) → Context (6) →
  Implementation.
* Within the same level, the document that owns the concern wins.

Higher-precedence specifications always take precedence. If a conflict is
discovered, stop and update the specifications before implementing.

---

# 19. Deliverables

Every completed task should produce:

* Source Code
* Tests
* Updated TASKS.md
* Updated CHANGELOG.md (if user-visible or architecturally significant)

Specifications are updated only when architecture or behavior changes.

---

# 20. Future Evolution

The framework is expected to grow primarily by:

* Adding Pipeline Steps.
* Extending Services.
* Extending Domain Models.
* Extending the Dataverse client.

The framework architecture itself should remain stable for the lifetime of the project.

---

# 21. Traceability

**Consumes**

* All specifications under `00_META`, `01_PRODUCT`, `02_ARCHITECTURE`, and `03_ENGINEERING`

**Referenced By**

* TASKS.md
* CHANGELOG.md

This document defines the standard implementation workflow for the ESS NextGen Migration Toolkit. All implementation work shall conform to this process to ensure consistency, maintainability, and specification alignment.
