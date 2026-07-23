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

| Layer           | Responsibility                    |
| --------------- | --------------------------------- |
| Service         | Application orchestration and entry point |
| Core            | Framework execution               |
| Core Models     | Canonical domain models           |
| Modules         | Pipeline-stage business logic     |
| Dataverse Client         | Dataverse communication           |

Responsibilities shall not overlap.

---

# 5. Pipeline Step Rules

Every migration transformation shall be implemented as a dedicated Pipeline Step.

Example:

```
OverrideAgentInstructionsStep

ReplaceEndConversationStep

HandleOnActivityTopicStep

HandleGeneratedResponseTopicStep
```

Each Pipeline Step shall perform exactly one logical transformation.

Pipeline Steps shall never:

* Call Dataverse
* Read configuration files
* Print directly
* Perform unrelated transformations

---

# 6. Service Rules

The service layer provides application orchestration.

The service layer shall:

* Own the migration session and execution lifecycle
* Operate on Domain Models and the MigrationContext
* Drive the Pipeline Engine over the pipeline-stage modules
* Call the Dataverse client when required

The service layer shall never:

* Contain migration rules
* Perform business transformations

---

# 7. Dataverse Client Rules

Dataverse communication exists only within the Dataverse client (`src/core/outbound/`).

Dataverse Client responsibilities include:

* Authentication
* HTTP requests
* Serialization
* Deserialization
* Retry policies

The Dataverse client shall never:

* Implement business rules
* Determine ownership
* Perform transformations

---

# 8. Domain Model Rules

Business logic shall operate exclusively on canonical Domain Models.

Raw Dataverse payloads shall never leave the Dataverse client layer.

Examples of prohibited behavior:

* Passing JSON between Services
* Manipulating REST payloads inside Pipeline Steps
* Exposing HTTP response objects outside the Dataverse client

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
Service

↓

Core

↓

Migration

↓

Dataverse Client

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

# 15a. Dependency Management

Dependencies shall be **pinned and reproducible**. `uv.lock` is the source of
truth and is committed; `pyproject.toml` declares dependencies and the supported
Python floor. The environment is **pip-free**: `uv` provisions both the pinned
Python and the locked dependencies (`uv sync`). Any dependency change shall
update `pyproject.toml` and `uv.lock` together. See
`dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
section 11a.

Operational commands are exposed through the single `mtk` dispatcher
(`./mtk.sh <subcommand>`, e.g. `mtk run`, `mtk run --dev`); new commands
are added as subcommands, never as new top-level scripts. See
`dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`
section 11b.

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
* Integration Tests for Dataverse Client interactions.

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
* No Dataverse calls outside the Dataverse client.
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
* Extending the Dataverse client.
* Adding or extending Domain Models.

Framework architecture should remain stable throughout the project lifecycle.

---

# 23. Traceability

**Consumes**

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_CLIENT.md
* REPOSITORY_STRUCTURE.md
* INVARIANTS.md

**Referenced By**

* IMPLEMENTATION_GUIDE.md
* TASKS.md
* TESTING.md

These standards are mandatory for all implementation work and are considered project invariants unless superseded by an updated specification.
