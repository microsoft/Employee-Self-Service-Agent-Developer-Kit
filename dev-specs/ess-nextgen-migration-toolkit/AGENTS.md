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

# 3. Reading Order

Before implementing any task, read the specifications in the following order.

## Repository Constitution

```
PROJECT.md

INVARIANTS.md

GLOSSARY.md
```

---

## Product

```
CUSTOMER_JOURNEY.md

MIGRATION_MODES.md

MIGRATION_RULES.md

ROADMAP.md
```

---

## Architecture

```
ARCHITECTURE.md

DOMAIN_MODEL.md

SERVICES.md

PIPELINES.md

DATAVERSE_SDK.md
```

---

## Engineering

```
REPOSITORY_STRUCTURE.md

CODING_STANDARDS.md

DIAGNOSTICS.md

TESTING.md

IMPLEMENTATION_GUIDE.md
```

---

## Execution

```
TASKS.md
```

Only after understanding the above specifications should implementation begin.

---

# 4. Specification Hierarchy

When conflicts exist between specifications, resolve them in the following order.

```
INVARIANTS

↓

PROJECT

↓

CUSTOMER JOURNEY

↓

ARCHITECTURE

↓

DOMAIN MODEL

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

Lower-level documents must never contradict higher-level specifications.

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
| SDK             | Dataverse communication  | Business logic     |
| Services        | Data coordination        | Migration rules    |
| Pipelines       | Workflow orchestration   | REST communication |
| Migration Steps | Business transformations | SDK calls          |
| Diagnostics     | Logging and reporting    | Business decisions |
| UI              | User interaction         | Migration logic    |

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
* SDK DTOs
* Raw JSON
* YAML dictionaries

Conversion between external formats and canonical models occurs only within the SDK and loader layers.

---

# 12. Dependency Rules

Always depend downward.

```
UI

↓

Application

↓

Pipelines

↓

Services

↓

SDK
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
