# REPOSITORY_STRUCTURE.md

# ESS NextGen Migration Toolkit — Repository Structure Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the canonical repository structure of the ESS NextGen Migration Toolkit.
>
> The repository layout is intentionally **fixed** for the lifetime of this project.
>
> AI agents and human contributors shall implement new functionality within this structure rather than introducing new architectural layers or reorganizing the repository.

---

# 1. Design Goals

The repository structure is designed to provide:

* Predictable implementation locations
* Strong separation of concerns
* AI-friendly navigation
* Minimal architectural churn
* Clear ownership boundaries
* Specification-driven development

The physical repository mirrors the logical architecture defined in `ARCHITECTURE.md`.

---

# 2. Repository Layout

Specifications and the buildable toolkit live in two separate trees at the repository root.

Specifications (the source of truth) live under `dev-specs/`:

```text
dev-specs/

└── ess-nextgen-migration-toolkit/

    AGENTS.md

    00_META/
    01_PRODUCT/
    02_ARCHITECTURE/
    03_ENGINEERING/
    04_EXECUTION/
```

The buildable toolkit lives under `tools/`:

```text
tools/

└── ess-nextgen-migration-toolkit/

    AGENTS.md

    src/

        core/
            pipeline/
            orchestrator/
            logging/

        models/

        constants/

        services/

        sdk/
            dataverse_api.py

        migration/
            migration_pipeline.py
            steps/

        preprocessing/

        postprocessing/

        ui/

        utils/

    tests/

        unit/
        integration/
        golden/
        e2e/

    logs/

    reports/

    scripts/

    .pre-commit-config.yaml

    pyproject.toml

    README.md
```

---

# 3. Repository Ownership

Every folder owns exactly one architectural concern.

---

## core/

Owns framework infrastructure.

Contains:

* Pipeline Engine
* Pipeline Builder
* Pipeline Registry
* Execution Context
* Migration Orchestrator
* Logging Framework

Never contains:

* Dataverse REST calls
* Migration rules
* ESS-specific business logic

---

## models/

Owns canonical domain models.

Contains only business entities shared across the framework.

Examples:

* MigrationContext
* MigrationSession
* Component
* ComponentLayer
* MigrationCandidate
* ValidationResult
* MigrationReport

Never contains:

* REST payloads
* Business logic

---

## constants/

Owns shared constants.

Examples:

* Execution Modes
* Component Types
* Solution Component Types
* Configuration Keys

Contains no executable logic.

---

## services/

Owns reusable application capabilities.

Examples:

* Discovery
* Ownership Analysis
* Component Loading
* Validation
* Reporting
* Writeback Coordination

Services expose reusable operations.

They never implement migration rules.

---

## sdk/

Owns Dataverse communication.

Contains:

* Authentication
* REST API wrappers
* Serialization
* Deserialization
* Retry handling

Initially implemented as:

```text
dataverse_api.py
```

Business logic never belongs here.

---

## migration/

Owns business transformations.

Contains:

* Migration Pipeline
* Pipeline Step implementations

Every Pipeline Step performs one logical transformation.

Examples:

* Runtime Provider transformation
* Template transformation
* Model Kind transformation
* Conversation Node transformation

Migration Steps never call Dataverse directly.

---

## preprocessing/

Owns discovery and preparation.

Responsibilities include:

* Discover ESS Agents
* Retrieve Dependencies For Uninstall
* Retrieve Solution Component Layers
* Determine migration candidates
* Load canonical components

No transformations occur here.

---

## postprocessing/

Owns execution after transformation.

Responsibilities include:

* Validation
* Writeback
* Report generation

No migration rules belong here.

---

## ui/

Owns customer interaction.

Responsibilities include:

* CLI
* Browser UI
* User prompts
* Progress reporting

UI never performs migration logic.

---

## utils/

Owns framework-independent helpers.

Examples:

* Utility methods
* Generic exceptions
* Shared helper functions

Utilities remain generic and reusable.

---

# 4. Dependency Rules

Dependencies shall flow only in the following direction.

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

Models and Constants may be referenced by every layer.

No layer may bypass another layer.

---

# 5. Folder Ownership Matrix

| Folder         | Responsibility                |
| -------------- | ----------------------------- |
| core           | Framework execution           |
| models         | Canonical domain models       |
| constants      | Shared constants              |
| services       | Reusable application services |
| sdk            | Dataverse communication       |
| migration      | Business transformations      |
| preprocessing  | Discovery pipeline            |
| postprocessing | Validation and persistence    |
| ui             | Customer interaction          |
| utils          | Generic helper functionality  |

---

# 6. Specification Mapping

| Specification           | Primary Implementation Folder |
| ----------------------- | ----------------------------- |
| ARCHITECTURE.md         | core                          |
| DOMAIN_MODEL.md         | models                        |
| SERVICES.md             | services                      |
| DATAVERSE_SDK.md        | sdk                           |
| PIPELINES.md            | core + migration              |
| MIGRATION_RULES.md      | migration                     |
| DIAGNOSTICS.md          | core/logging                  |
| IMPLEMENTATION_GUIDE.md | Entire repository             |

---

# 7. Repository Invariants

The repository structure is considered **frozen**.

Implementation tasks shall not:

* Introduce new top-level folders.
* Move existing folders.
* Bypass architectural boundaries.
* Duplicate responsibilities across folders.
* Create alternative implementations outside the prescribed layout.

If implementation requires a structural change, the corresponding specification must be updated before implementation proceeds.

---

# 8. File Organization Rules

Each source file should:

* Have one primary responsibility.
* Contain one primary public class.
* Follow the dependency rules defined in this specification.

Avoid unrelated public classes within the same file.

---

# 9. Testing Layout

```text
tests/

    unit/

    integration/

    golden/

    e2e/
```

Unit tests mirror the `src/` directory.

Golden tests validate deterministic migration outputs.

Integration tests validate Dataverse interactions.

End-to-end tests validate complete migration workflows through the Orchestrator.

---

# 10. Logging and Reports

Execution artifacts are written to:

```text
logs/
```

Session logs are timestamped and written using the framework logging abstraction.

Customer-facing reports are written to:

```text
reports/
```

Business logic must never write files directly.

---

# 11. Pre-Commit Requirements

The repository shall enforce quality gates through pre-commit hooks.

Examples include:

* Formatting
* Linting
* Type checking
* Unit test execution
* Prevention of direct `print()` statements
* Prevention of accidental debug artifacts

Logging must always use the framework logging abstraction.

---

# 12. Future Evolution

New functionality should primarily be implemented by:

* Adding new Domain Models.
* Adding new Services.
* Adding new Pipeline Steps.
* Extending `dataverse_api.py`.
* Adding corresponding tests.

Framework infrastructure should remain stable throughout the lifetime of the migration toolkit.

---

# 13. Traceability

**Consumes**

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_SDK.md

**Referenced By**

* CODING_STANDARDS.md
* IMPLEMENTATION_GUIDE.md
* TASKS.md

This repository structure is a project invariant. AI agents and contributors shall treat it as fixed architecture and implement new capabilities within its prescribed boundaries rather than reorganizing the repository.
