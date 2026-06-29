# AGENTS.md

# ESS NextGen Migration Toolkit — AI Agent Operating Manual

> **Purpose**
>
> This repository follows **Specification-Driven Development (SDD)**.
>
> Specifications are the source of truth. Code is an implementation of those specifications.
>
> AI agents are expected to behave as disciplined software engineers—not autonomous designers.
>
> When specifications are ambiguous, stop and ask for clarification rather than inventing behavior.

---

# 1. Core Philosophy

This repository is intentionally specification-first.

Development always follows the same lifecycle:

```text
Understand
    ↓
Design
    ↓
Implement
    ↓
Verify
    ↓
Document
```

Implementation is **never** the first step.

---

# 2. Repository Philosophy

The repository is divided into independent layers.

```text
Product

↓

Architecture

↓

Engineering

↓

Execution

↓

Implementation
```

Every layer depends only on layers above it.

Never implement code without understanding the specifications that define it.

---

# 3. Specification Classification

Specifications are classified into levels by how often they are needed and how
stable they are. This classification drives the dependency-based loading model
in Section 3a — agents resolve only the documents a task actually requires
rather than reading every specification on every task.

| Level | Category      | Documents |
| ----- | ------------- | --------- |
| 0     | Orchestrator  | `AGENTS.md` |
| 1     | Execution     | `04_EXECUTION/TASKS.md` |
| 2     | Business Rules| `01_PRODUCT/MIGRATION_RULES.md` |
| 3     | Constitution  | `00_META/PROJECT.md`, `00_META/INVARIANTS.md`, `00_META/VOCABULARY.md` |
| 4     | Architecture  | `02_ARCHITECTURE/ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `SERVICES.md`, `PIPELINES.md`, `DATAVERSE_CLIENT.md` |
| 5     | Engineering   | `03_ENGINEERING/REPOSITORY_STRUCTURE.md`, `CODING_STANDARDS.md`, `IMPLEMENTATION_GUIDE.md`, `DIAGNOSTICS.md`, `TESTING.md` |
| 6     | Context       | `01_PRODUCT/CUSTOMER_JOURNEY.md`, `01_PRODUCT/MIGRATION_MODES.md`, `00_META/ROADMAP.md` |

Level 6 (Context) documents are read **only when a task references them**.

---

# 3a. Dependency-Based Loading Model

Do not read every specification on every task. Resolve the dependency graph
for the specific task, like a compiler resolving only the modules it needs.

```text
Receive Prompt
        ↓
Phase 0 — Boot
    Always read AGENTS.md (this file). It is the orchestrator.
        ↓
Phase 1 — Resolve Task
    Open 04_EXECUTION/TASKS.md (the task index) and locate TASK-XXX, then
    open its task file 04_EXECUTION/tasks/TASK-XXX-<slug>.md.
        ↓
Phase 2 — Resolve Migration Rule
    If the task references RULE-XXX, open 01_PRODUCT/MIGRATION_RULES.md
    and read only that rule.
        ↓
Phase 3 — Constitution (always; these are small)
    00_META/PROJECT.md
    00_META/INVARIANTS.md
    00_META/VOCABULARY.md
        ↓
Phase 4 — Architecture (read once per work session)
    02_ARCHITECTURE/ARCHITECTURE.md
    DOMAIN_MODEL.md
    SERVICES.md
    PIPELINES.md
    DATAVERSE_CLIENT.md
        ↓
Phase 5 — Engineering (read once per work session)
    03_ENGINEERING/REPOSITORY_STRUCTURE.md
    CODING_STANDARDS.md
    IMPLEMENTATION_GUIDE.md
    DIAGNOSTICS.md
    TESTING.md
        ↓
Phase 6 — Product Context (only if referenced by the task or its rule)
    01_PRODUCT/CUSTOMER_JOURNEY.md
    01_PRODUCT/MIGRATION_MODES.md
    00_META/ROADMAP.md
        ↓
Implement → Run Tests → Update task file Status (and TASKS.md index) → Update CHANGELOG.md → Stop
```

Each task file under `04_EXECUTION/tasks/` declares a `Consumes` field (the
governing Migration Rule) and a `References` section (the exact specifications
required to implement it). Prefer resolving a task's required documents from its
`References` section over reading broadly.

---

# 4. Specification Hierarchy (Conflict Resolution)

The classification in Section 3 governs **what to read**. This section governs
**which document wins** when two specifications conflict.

* `00_META/INVARIANTS.md` is supreme. An invariant always takes precedence over
  any other specification or implementation convenience.
* For all other conflicts, a **lower Level number takes precedence over a higher
  one** (Level 0 → Level 6).
* Within the same level, the document that **owns the concern** wins
  (for example, `MIGRATION_RULES.md` owns business behavior; `DOMAIN_MODEL.md`
  owns canonical models).

Lower-precedence documents must never contradict higher-precedence
specifications. If a conflict is discovered, stop and update the specifications
before implementing.

---

# 5. Implementation Principles

AI agents should behave conservatively.

## Always

✔ Follow specifications exactly.

✔ Preserve architectural boundaries.

✔ Keep implementations deterministic.

✔ Prefer explicitness over cleverness.

✔ Implement one task at a time.

✔ Keep changes minimal and localized.

---

## Never

✘ Invent missing requirements.

✘ Add speculative abstractions.

✘ Modify unrelated code.

✘ Ignore documented invariants.

✘ Introduce architectural changes without updating specifications.

---

# 6. Task Execution Workflow

Every task follows the same lifecycle.

```
Read Task

↓

Read Referenced Specifications

↓

Understand Dependencies

↓

Implement

↓

Write Tests

↓

Verify

↓

Update Documentation

↓

Complete Task
```

Do not skip steps.

---

# 7. Architectural Boundaries

Always respect module ownership.

| Module          | Owns                     | Must Never         |
| --------------- | ------------------------ | ------------------ |
| Dataverse Client         | Dataverse communication  | Business logic     |
| Service helpers | Reusable capabilities    | Migration rules    |
| Pipelines       | Workflow orchestration   | REST communication |
| Migration Steps | Business transformations | Dataverse Client calls      |
| Diagnostics     | Logging and reporting    | Business decisions |
| Service         | Session coordination     | Business transformations |

## Repository Navigation

| Concern               | Implementation location                         |
| --------------------- | ----------------------------------------------- |
| Dataverse APIs        | `src/core/outbound/`                            |
| Domain Models         | `src/core/models/`                              |
| Migration Rules       | `src/modules/migration/steps/`          |
| Pipeline Registration | `src/modules/migration/`                |
| Orchestration entry   | `src/service/mtk_orchestrator.py`               |
| Utilities             | `src/core/utils/`                               |
| Diagnostics code      | `src/core/logging/`                             |
| Generated output      | `debug/logs/`, `debug/reports/`         |

---

# 8. One Responsibility Per Layer

A module should have exactly one responsibility.

Example

```
Discovery

↓

Find Components

Not

↓

Find Components

↓

Transform Components

↓

Write Back
```

Keep responsibilities isolated.

---

# 9. Migration Philosophy

The toolkit implements three execution modes.

```
DISCOVER

↓

PREVIEW

↓

MIGRATE
```

Execution modes differ only in **how far the pipeline progresses**.

Business transformations should remain identical between Preview and Migrate.

Preview should always represent exactly what Migrate would execute.

---

# 10. Determinism

The framework must be deterministic.

Given identical:

* Inputs
* Environment
* Configuration

The toolkit must always produce identical outputs.

Avoid:

* Hidden state
* Random ordering
* Non-deterministic iteration

---

# 11. Canonical Models

Business logic operates only on canonical domain models.

Never implement migration directly against:

* REST payloads
* Dataverse client DTOs
* Raw JSON
* YAML dictionaries

Conversion between external formats and canonical models occurs only within the Dataverse client and loader layers.

---

# 12. Dependency Rules

Always depend downward.

```
Service

↓

Core

↓

Dataverse Client

↓

Dataverse
```

Never introduce reverse dependencies.

---

# 13. Change Philosophy

Every change should answer:

1. Why is this change required?
2. Which specification requires it?
3. Which invariant does it preserve?
4. Which tests validate it?

If these questions cannot be answered, the change is incomplete.

---

# 14. Testing Requirements

Every implementation requires automated validation.

Minimum expectations:

* Unit tests
* Golden file tests (where applicable)
* Integration tests (when crossing module boundaries)

No feature is complete without tests.

---

# 15. Documentation Requirements

When behavior changes:

* Update the relevant specification.
* Update CHANGELOG.md.
* Update tests.

Specifications and implementation must remain synchronized.

---

# 16. When to Stop

Stop implementation immediately if:

* Specifications conflict.
* Requirements are incomplete.
* Architectural boundaries would be violated.
* Required behavior cannot be inferred confidently.

Prefer asking for clarification over making assumptions.

---

# 17. Code Quality Expectations

Generated code should be:

* Readable
* Deterministic
* Strongly typed
* Testable
* Modular
* Small
* Cohesive

Prefer simple implementations over clever implementations.

---

# 18. Error Philosophy

Handle expected failures explicitly.

Unexpected failures should fail fast with actionable diagnostics.

Never silently ignore errors.

---

# 19. Review Checklist

Before considering work complete, verify:

* Relevant specifications implemented.
* Architectural boundaries preserved.
* Invariants maintained.
* Tests added and passing.
* Documentation updated.
* No unrelated changes introduced.

---

# 20. Definition of Success

The objective is **not** to maximize generated code.

The objective is to produce software that:

* faithfully implements the specifications,
* remains easy to evolve,
* preserves architectural integrity,
* and minimizes future maintenance cost.

Correctness, simplicity, and maintainability are valued over implementation speed.

---

# 21. Guiding Principle

> **Specifications define the system.**
>
> **Code is merely one implementation of those specifications.**
>
> When in doubt, improve the specifications before changing the implementation.
