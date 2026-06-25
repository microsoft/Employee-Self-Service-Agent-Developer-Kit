# AGENTS.md

# ESS NextGen Migration Toolkit — AI Agent Operating Manual

> **Purpose**
>
> This repository follows **Specification-Driven Development (SDD)**.
>
> Specifications are the source of truth.
>
> Code is merely one implementation of those specifications.
>
> AI agents are expected to behave as disciplined software engineers implementing approved specifications—not as software architects, framework designers, or product managers.
>
> When specifications are incomplete or ambiguous, stop and request clarification instead of inventing behavior.

---

# 1. Core Philosophy

This repository is specification-first.

Development always follows the same lifecycle.

```text
Understand

↓

Specify

↓

Implement

↓

Verify

↓

Document
```

Implementation is never the first step.

---

# 2. Repository Organization

All specifications live under:

```text
specs/

├── 00_META/
├── 01_PRODUCT/
├── 02_ARCHITECTURE/
├── 03_ENGINEERING/
└── 04_EXECUTION/
```

Implementation lives under:

```text
src/
```

Tests live under:

```text
tests/
```

---

# 3. AI Execution Algorithm

Every implementation request shall follow this algorithm.

```text
Receive Task Request

↓

Open

specs/04_EXECUTION/TASKS.md

↓

Locate TASK-XXX

↓

Read task details

↓

Resolve "Consumes"

↓

Open referenced specifications

↓

Understand implementation

↓

Check repository invariants

↓

Implement

↓

Run tests

↓

Update TASK status

↓

Update CHANGELOG (if applicable)

↓

Stop
```

Never begin implementation before completing this algorithm.

---

# 4. Specification Reading Order

Unless the task specifies otherwise, specifications shall be consumed in the following order.

## Repository Constitution

```text
specs/00_META/

PROJECT.md

INVARIANTS.md

VOCABULARY.md
```

---

## Product Specifications

```text
specs/01_PRODUCT/

CUSTOMER_JOURNEY.md

MIGRATION_MODES.md

MIGRATION_RULES.md

ROADMAP.md
```

---

## Architecture Specifications

```text
specs/02_ARCHITECTURE/

ARCHITECTURE.md

DOMAIN_MODEL.md

SERVICES.md

PIPELINES.md

DATAVERSE_SDK.md
```

---

## Engineering Specifications

```text
specs/03_ENGINEERING/

REPOSITORY_STRUCTURE.md

CODING_STANDARDS.md

IMPLEMENTATION_GUIDE.md

DIAGNOSTICS.md

TESTING.md
```

---

## Execution Specifications

```text
specs/04_EXECUTION/

TASKS.md
```

Only after understanding the required specifications may implementation begin.

---

# 5. Task Resolution

Every implementation shall originate from exactly one TASK.

Locate the requested task inside:

```text
specs/04_EXECUTION/TASKS.md
```

Every task defines:

* Scope
* Deliverables
* Dependencies
* Acceptance Criteria

Never implement functionality that is not described by an approved task.

---

# 6. Migration Rule Resolution

If a task references a Migration Rule:

Open

```text
specs/01_PRODUCT/MIGRATION_RULES.md
```

Locate:

```text
RULE-XXX
```

Migration Rules are the authoritative business specification.

Every Migration Rule maps directly to one Pipeline Step.

Never invent migration behavior.

---

# 7. Repository Invariants

The following repository invariants shall never be violated.

* Repository structure is frozen.
* Architectural layers are fixed.
* One Migration Rule maps to one Pipeline Step.
* Business logic exists only within Migration Steps.
* Dataverse communication exists only within the SDK.
* Customer customizations shall never be deleted during migration.
* Preview and Migrate execute identical business transformations.
* Specifications always take precedence over implementation.

---

# 8. Repository Navigation

Use the following mapping when implementing code.

| Implementing          | Folder               |
| --------------------- | -------------------- |
| Pipeline Engine       | src/core/            |
| Migration Rules       | src/migration/steps/ |
| Pipeline Registration | src/migration/       |
| Domain Models         | src/models/          |
| Services              | src/services/        |
| Dataverse APIs        | src/sdk/             |
| CLI                   | src/ui/              |
| Utilities             | src/utils/           |
| Diagnostics           | src/core/logging/    |

Never place code outside its designated architectural boundary.

---

# 9. Specification Hierarchy

When specifications conflict, resolve them in the following order.

```text
INVARIANTS

↓

PROJECT

↓

CUSTOMER_JOURNEY

↓

MIGRATION_RULES

↓

ARCHITECTURE

↓

DOMAIN_MODEL

↓

SERVICES

↓

PIPELINES

↓

SDK

↓

ENGINEERING

↓

TASKS
```

Lower-level specifications shall never contradict higher-level specifications.

---

# 10. Implementation Principles

Always:

* Follow specifications exactly.
* Preserve architectural boundaries.
* Keep implementations deterministic.
* Prefer explicitness over cleverness.
* Implement one task at a time.
* Keep changes localized.
* Reuse existing framework components.

Never:

* Invent business rules.
* Invent migration behavior.
* Delete customer customizations.
* Add speculative abstractions.
* Introduce architectural changes.
* Modify unrelated code.

---

# 11. Migration Philosophy

The toolkit prioritizes preservation of customer intent.

Migration should prefer:

```text
Override

↓

Replace

↓

Disable

↓

Manual Review
```

Customer-authored assets should never be deleted unless explicitly required by an approved Migration Rule.

---

# 12. Determinism

The framework must be deterministic.

Given identical:

* Inputs
* Environment
* Configuration

the toolkit shall always produce identical outputs.

Avoid:

* Hidden state
* Random ordering
* Non-deterministic iteration

---

# 13. Canonical Models

Business logic shall operate exclusively on canonical Domain Models.

Never implement migration directly against:

* REST payloads
* SDK DTOs
* Raw JSON
* YAML dictionaries

Conversion into canonical models occurs only inside the SDK and preprocessing layers.

---

# 14. Dependency Rules

Dependencies always flow downward.

```text
UI

↓

Core

↓

Migration

↓

Services

↓

SDK

↓

Dataverse
```

Reverse dependencies are prohibited.

---

# 15. Testing Workflow

Every implementation shall include:

* Unit Tests
* Golden Tests (where applicable)
* Integration Tests (when required)

No implementation is complete without automated validation.

---

# 16. Living Specifications

The following specifications evolve throughout the lifetime of the project.

```text
specs/01_PRODUCT/MIGRATION_RULES.md

specs/04_EXECUTION/TASKS.md

CHANGELOG.md
```

When introducing a new migration capability:

1. Update Migration Rules.
2. Update Tasks.
3. Implement Pipeline Step.
4. Add Tests.
5. Update Changelog.

All other specifications should remain relatively stable.

---

# 17. Stop Conditions

Stop implementation immediately if:

* TASK does not exist.
* Migration Rule does not exist.
* Specifications conflict.
* Repository invariants would be violated.
* Architecture requires modification.
* Required behavior cannot be inferred confidently.

Prefer requesting clarification over making assumptions.

---

# 18. Completion Checklist

Before marking a task complete, verify:

* Correct specifications implemented.
* Repository structure unchanged.
* Architectural boundaries preserved.
* Migration Rule implemented.
* Tests added and passing.
* TASK status updated.
* CHANGELOG updated (if applicable).
* No unrelated modifications introduced.

---

# 19. Definition of Success

The objective is not to maximize generated code.

The objective is to produce software that:

* faithfully implements the specifications,
* preserves customer intent,
* maintains architectural integrity,
* remains deterministic,
* is easy to extend through new Migration Rules,
* and minimizes long-term maintenance.

Correctness is valued above implementation speed.

---

# 20. Guiding Principle

> **Specifications define the system.**
>
> **Migration Rules define business behavior.**
>
> **Tasks define implementation work.**
>
> **Code is merely the current implementation.**
>
> When in doubt, improve the specifications before changing the implementation.
