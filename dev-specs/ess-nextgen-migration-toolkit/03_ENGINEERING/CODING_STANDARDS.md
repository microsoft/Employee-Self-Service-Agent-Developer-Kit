# CODING_STANDARDS.md

# ESS NextGen Migration Toolkit — Coding Standards
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the implementation standards for the ESS NextGen Migration Toolkit.
>
> These standards are mandatory for both human contributors and AI agents.
>
> The goal is to maintain a deterministic, extensible, and specification-driven codebase throughout the lifetime of the project.

---

# 1. Guiding Principles

All implementation must follow these principles:

* Specification-Driven Development (SDD)
* Single Responsibility Principle
* Separation of Concerns
* Open/Closed Principle
* Deterministic Execution
* Explicit over Implicit
* Composition over Inheritance

Implementation shall conform to the repository architecture rather than redefining it.

---

# 2. Source of Truth

Implementation shall always follow the following precedence:

```
Specification

↓

Architecture

↓

Tasks

↓

Implementation

↓

Tests
```

Implementation must never contradict the specifications.

---

# 3. Repository Invariants

The repository structure is frozen.

Implementation shall not:

* Create new architectural layers.
* Introduce new top-level folders.
* Move responsibilities across folders.
* Bypass dependency rules.

If architectural changes are required, update the specifications before implementation.

---

# 4. Separation of Concerns

Each layer owns one responsibility.

| Layer     | Responsibility                    |
| --------- | --------------------------------- |
| UI        | Customer interaction              |
| Core      | Framework execution               |
| Migration | Business transformations          |
| Services  | Reusable application capabilities |
| SDK       | Dataverse communication           |
| Models    | Canonical domain models           |

Responsibilities shall not overlap.

---

# 5. Pipeline Step Rules

Every migration transformation shall be implemented as a dedicated Pipeline Step.

Example:

```
UpdateRuntimeProviderStep

UpdateTemplateStep

UpdateModelKindStep

ReplaceEndConversationStep
```

Each Pipeline Step shall perform exactly one logical transformation.

Pipeline Steps shall never:

* Call Dataverse
* Read configuration files
* Print directly
* Perform unrelated transformations

---

# 6. Service Rules

Services expose reusable application capabilities.

Services shall:

* Be stateless
* Operate on Domain Models
* Call the SDK when required

Services shall never:

* Contain migration rules
* Coordinate pipeline execution
* Call UI components

---

# 7. SDK Rules

The SDK owns all Dataverse communication.

SDK responsibilities include:

* Authentication
* HTTP requests
* Serialization
* Deserialization
* Retry policies

The SDK shall never:

* Implement business rules
* Determine ownership
* Perform transformations

---

# 8. Domain Model Rules

Business logic shall operate exclusively on canonical Domain Models.

Raw Dataverse payloads shall never leave the SDK layer.

Examples of prohibited behavior:

* Passing JSON between Services
* Manipulating REST payloads inside Pipeline Steps
* Exposing HTTP response objects outside the SDK

---

# 9. Logging Rules

Direct output is prohibited.

The following shall not be used:

```
print()

pprint()

logging.basicConfig()
```

All diagnostics shall use the framework Logger.

Logger responsibilities include:

* Console output
* Session log file
* Timestamps
* Severity levels

---

# 10. Exception Handling

Never raise generic exceptions.

Prefer typed exceptions.

Examples:

```
AuthenticationException

ValidationException

PipelineExecutionException

MigrationException

WritebackException
```

Exceptions shall propagate upward.

Lower layers shall not suppress failures.

---

# 11. Dependency Rules

Dependencies shall follow this direction only.

```
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

No layer may bypass another.

---

# 12. Class Design

Each public class shall:

* Have one responsibility
* Be independently testable
* Expose a minimal public API

Avoid "God Objects".

---

# 13. Function Design

Functions should:

* Be deterministic
* Have descriptive names
* Avoid hidden side effects
* Return explicit results

Avoid large procedural functions.

---

# 14. State Management

Global mutable state is prohibited.

Execution state shall be carried exclusively through:

```
MigrationContext
```

---

# 15. Configuration

Configuration shall be injected.

Hardcoded values are prohibited except for true constants.

---

# 16. Type Safety

All public functions shall include type hints.

Avoid untyped collections where a domain model exists.

---

# 17. Testing Requirements

Every implementation task shall include corresponding tests.

Minimum expectation:

* Unit Tests for business logic.
* Golden Tests for deterministic transformations.
* Integration Tests for SDK interactions.

No production code shall be introduced without tests.

---

# 18. Documentation Requirements

Every public class shall include:

* Purpose
* Responsibilities
* Inputs
* Outputs

Complex business logic should include explanatory comments describing **why**, not **what**.

---

# 19. AI Agent Requirements

AI agents shall:

* Read relevant specifications before implementation.
* Implement only the assigned task.
* Preserve architectural boundaries.
* Avoid speculative abstractions.
* Reuse existing framework components whenever possible.

AI agents shall not:

* Invent new architecture.
* Rename folders.
* Introduce new frameworks.
* Refactor unrelated code.

---

# 20. Completion Checklist

Before marking a task complete, verify:

* Repository structure unchanged.
* Architecture preserved.
* Domain Models used.
* No Dataverse calls outside the SDK.
* No business logic outside Migration Steps.
* Logger used instead of `print()`.
* Tests added.
* Task status updated.
* Changelog updated where applicable.

---

# 21. Code Review Checklist

Every review should verify:

* Correct folder placement.
* Correct architectural layer.
* Single responsibility.
* Dependency direction.
* Test coverage.
* Logging compliance.
* No specification violations.

---

# 22. Future Evolution

New functionality should primarily be introduced by:

* Adding a new Pipeline Step.
* Extending an existing Service.
* Extending the Dataverse SDK.
* Adding or extending Domain Models.

Framework architecture should remain stable throughout the project lifecycle.

---

# 23. Traceability

**Consumes**

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_SDK.md
* REPOSITORY_STRUCTURE.md
* INVARIANTS.md

**Referenced By**

* IMPLEMENTATION_GUIDE.md
* TASKS.md
* TESTING.md

These standards are mandatory for all implementation work and are considered project invariants unless superseded by an updated specification.
