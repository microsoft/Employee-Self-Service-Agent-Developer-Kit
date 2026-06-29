# DOMAIN_MODEL.md

# ESS NextGen Migration Toolkit — Domain Model Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the canonical domain model for the ESS NextGen Migration Toolkit.
>
> Every module within the toolkit communicates exclusively through these models.
>
> External representations (Dataverse REST payloads, XML, JSON, Dataverse client DTOs, etc.) are translated into these models at the system boundary.
>
> Business logic must never operate directly on external representations.

---

# 1. Purpose

The Domain Model provides a stable, implementation-independent representation of the migration problem domain.

It serves as the common language shared between:

- Migration Orchestrator
- Services
- Pipeline Engine
- Migration Steps
- Diagnostics
- Reports

The Domain Model isolates business logic from platform implementation details.

---

# 2. Design Principles

## MODEL-001

Canonical models are the single source of truth during execution.

---

## MODEL-002

Business logic never depends on Dataverse payloads.

---

## MODEL-003

Models represent business concepts, not storage formats.

---

## MODEL-004

Every model has a single owner.

---

## MODEL-005

Models evolve independently of Dataverse APIs.

---

# 3. Domain Model Overview

```
MigrationSession
        │
        ▼
MigrationContext
        │
        ├───────────────┐
        ▼               ▼
Environment        Agent
        │
        ▼
Component[]
        │
        ▼
ComponentLayer[]
        │
        ▼
MigrationCandidate[]
        │
        ▼
Transformation[]
        │
        ▼
ValidationResult[]
        │
        ▼
MigrationReport
```

---

# 4. Core Models

---

# MigrationSession

## Purpose

Represents one execution of the migration toolkit.

---

## Owned By

Migration Orchestrator

---

## Lifecycle

Created once.

Destroyed when execution completes.

---

## Properties

- SessionId
- StartTime
- EndTime
- ExecutionMode
- Status

---

## Mutable

Yes

`SessionId`, `StartTime`, and `ExecutionMode` are set once and never change.
`EndTime` and `Status` are updated by the Migration Orchestrator as the session
progresses and completes.

---

# MigrationContext

## Purpose

Shared execution context flowing through every module.

---

## Owned By

Migration Orchestrator

---

## Consumed By

- Services
- Pipelines
- Migration Steps
- Diagnostics

---

## Properties

- Session
- Environment
- Agent
- Components
- Candidates
- Reports
- Diagnostics
- Configuration

---

## Mutable

Yes

Every pipeline enriches the context.

---

# MigrationEnvironment

## Purpose

Represents the target Dataverse environment.

---

## Properties

- EnvironmentId
- EnvironmentUrl
- TenantId
- PreferredSolution
- AuthenticationContext

---

## Mutable

No

---

# Agent

## Purpose

Represents the ESS Agent being migrated.

---

## Properties

- AgentId
- Name
- Version
- Runtime
- AgentType

---

## Mutable

Yes

Migration updates runtime metadata.

---

# Component

## Purpose

Canonical representation of a Dataverse solution component.

---

## Properties

- ComponentId
- ComponentType
- DisplayName
- LogicalName
- Source
- Layers
- Metadata

---

## Mutable

Yes

Migration transforms components.

---

# ComponentLayer

## Purpose

Represents a single solution layer applied to a component.

---

## Properties

- LayerId
- SolutionId
- SolutionName
- Managed
- CreatedTime
- Publisher

---

## Mutable

No

---

## Notes

Component Layers determine:

- Microsoft-owned artifacts
- Customer-owned customizations
- Net-new components

---

# MigrationCandidate

## Purpose

Represents a component eligible for migration.

---

## Properties

- Component
- Ownership
- MigrationStatus
- ValidationState

---

## Mutable

Yes

---

# Transformation

## Purpose

Represents a single business transformation.

---

## Properties

- RuleId
- Component
- Before
- After

---

## Mutable

No

---

# ValidationResult

## Purpose

Represents validation performed after migration.

---

## Properties

- Component
- Status
- Warnings
- Errors

---

## Mutable

No

---

# Diagnostic

## Purpose

Represents a single diagnostic message.

---

## Properties

- Severity
- Message
- Component
- Timestamp
- Category

---

## Mutable

No

---

# MigrationReport

## Purpose

Represents the overall migration outcome.

---

## Properties

- ComponentsProcessed
- ComponentsMigrated
- ComponentsSkipped
- Warnings
- Errors
- Duration

---

## Mutable

Yes

Built throughout execution.

---

# 5. Ownership Matrix

| Model | Created By | Modified By | Read By |
|----------|------------|-------------|---------|
| MigrationSession | Orchestrator | Orchestrator | All |
| MigrationContext | Orchestrator | All Pipelines | All |
| MigrationEnvironment | Dataverse Client | None | All |
| Agent | Discovery Service | Migration Steps | All |
| Component | Discovery Service | Migration Steps | All |
| ComponentLayer | Dataverse Client | None | Analysis |
| MigrationCandidate | Analysis Service | Pipeline | All |
| Transformation | Migration Step | None | Reports |
| ValidationResult | Validation Pipeline | None | Reports |
| Diagnostic | Diagnostics | Diagnostics | Reports |
| MigrationReport | Report Service | Report Service | User |

---

# 6. Object Lifecycle

Every migrated component follows the same lifecycle.

```
Discovered
      │
      ▼
Layer Analysis
      │
      ▼
Migration Candidate
      │
      ▼
Transformation
      │
      ▼
Validation
      │
      ▼
Persistence
      │
      ▼
Migration Report
```

---

# 7. Data Ownership

Business logic owns:

- Agent
- Component
- Candidate
- Transformation

Infrastructure owns:

- REST Payloads
- XML
- JSON
- HTTP Responses

Translation occurs only inside the Dataverse client layer.

---

# 8. Mutability Rules

| Model | Mutable |
|---------|----------|
| MigrationSession | Yes |
| MigrationEnvironment | No |
| ComponentLayer | No |
| Transformation | No |
| ValidationResult | No |
| Diagnostic | No |
| MigrationContext | Yes |
| Agent | Yes |
| Component | Yes |
| MigrationCandidate | Yes |
| MigrationReport | Yes |

---

# 9. Future Evolution

The Domain Model is expected to remain stable.

Supporting new migration capabilities should typically require:

- New Component Types
- Additional Metadata
- New Migration Rules

Existing models should rarely require structural changes.

---

# 10. Traceability

**Consumes**

- PROJECT.md
- VOCABULARY.md
- ARCHITECTURE.md
- INVARIANTS.md

**Referenced By**

- SERVICES.md
- PIPELINES.md
- DATAVERSE_CLIENT.md
- MIGRATION_RULES.md
- TASKS.md

The Domain Model is the canonical language of the ESS NextGen Migration Toolkit.

