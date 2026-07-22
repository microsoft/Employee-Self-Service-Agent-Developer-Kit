# SERVICES.md

# ESS NextGen Migration Toolkit — Application Services Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the **Service (Orchestration) layer** of the ESS NextGen
> Migration Toolkit — the application's entry point and the top of the
> dependency graph, implemented as `service/mtk_orchestrator.py`.
>
> The Service layer coordinates a migration session: it composes the lower
> layers, drives the Pipeline Engine over the pipeline-stage `modules/`, and
> performs Dataverse I/O through the Dataverse client — while remaining
> independent of migration rules.
>
> The Service layer never contains business transformation logic; transformation
> belongs exclusively to Migration Steps.

---

# 1. Purpose

The Service layer provides application **orchestration** — it decides **when**
capabilities run and in what order, and it owns the session lifecycle.

The reusable capabilities it coordinates are realized in the lower layers:

- Discovery and component loading → `modules/preprocessing/`
- Validation, writeback, and reporting → `modules/postprocessing/`
- Authentication, configuration, diagnostics, and generic helpers →
  cross-cutting `core/` primitives (`core/outbound`, `constants`,
  `core/logging`, `core/utils`)

The Service layer exposes **what** a migration session does end to end.
Pipeline Steps decide the individual transformations.

---

# 2. Design Principles

## SERVICE-001

Orchestration owns the session and execution lifecycle.

---

## SERVICE-002

The Service layer never performs business transformations.

Transformation belongs exclusively to Migration Steps.

---

## SERVICE-003

Migration rules live exclusively in `src/modules/transformation/steps/`.
The Service layer never contains migration rules.

---

## SERVICE-004

Layers communicate only through Domain Models and the MigrationContext.

---

## SERVICE-005

The Service layer may call the Dataverse client.

Migration Steps may not.

---

## SERVICE-006

The Service layer depends only on the layers beneath it.

Lower layers never depend on the Service layer.

---

# 3. Layer Position

```
Orchestration (service/mtk_orchestrator.py)
        │
        ▼
Pipeline Engine  ──►  Modules  ──►  Dataverse client
```

Orchestration isolates session coordination from business transformation and
infrastructure.

---

# 4. Coordinated Capabilities

> The catalogue below enumerates the capability **responsibilities** an
> end-to-end migration session coordinates. These are realized within the
> pipeline-stage `modules/` (preprocessing and postprocessing) and cross-cutting
> `core/` primitives — not as a separate physical `services/` folder — and are
> driven by the orchestrator.

```
DiscoveryService

↓

LayerAnalysisService

↓

ComponentLoaderService

↓

ValidationService

↓

WritebackService

↓

ReportService

↓

DiagnosticsService

↓

ConfigurationService

↓

AuthenticationService
```

Each service owns one responsibility.

---

# 5. DiscoveryService

## Purpose

Discover ESS migration candidates.

---

## Responsibilities

- Enumerate ESS Agents
- Retrieve uninstall dependency graph
- Discover candidate components
- Build initial Component models

---

## Consumes

- MigrationEnvironment

---

## Produces

- Agent
- Component[]

---

## Depends On

- AgentClient
- DependencyClient

---

## Never

- Analyze ownership
- Transform components
- Persist data

---

# 6. LayerAnalysisService

## Purpose

Determine customer ownership of discovered components.

---

## Responsibilities

- Retrieve Solution Component Layers
- Determine ownership
- Classify components

---

## Ownership Rules

Customized OOB Component

```
Managed Layer
↓

Customer Layer
```

Customer customization exists.

---

Net New Component

```
Customer Layer
```

CreatedTime != 1900

Customer owned.

---

Microsoft Component

```
Managed Layer
```

No migration required.

---

## Produces

MigrationCandidate[]

---

## Depends On

- ComponentLayerClient

---

## Never

- Modify components
- Persist data

---

# 7. ComponentLoaderService

## Purpose

Load complete component payloads.

---

## Responsibilities

Retrieve canonical representations of:

- Topics
- Agent Metadata
- Knowledge
- Flows
- Future Components

---

## Produces

Component[]

---

## Depends On

Dataverse API Clients

---

## Never

Transform components.

---

# 8. ValidationService

## Purpose

Validate migrated artifacts.

---

## Responsibilities

- Structural validation
- Required property validation
- Migration rule validation
- Consistency validation

---

## Produces

ValidationResult[]

---

## Never

Modify artifacts.

---

# 9. WritebackService

## Purpose

Persist migrated artifacts.

---

## Responsibilities

Serialize canonical models.

Call Dataverse client.

Verify persistence.

---

## Consumes

Component[]

---

## Produces

MigrationReport

---

## Never

Perform migration logic.

---

# 10. ReportService

## Purpose

Generate customer-facing reports.

---

## Responsibilities

Generate:

- Readiness Report
- Preview Report
- Migration Summary

---

## Produces

MigrationReport

---

# 11. DiagnosticsService

## Purpose

Central diagnostics provider.

---

## Responsibilities

- Session logging
- Console logging
- Error logging
- Timing
- Metrics
- File generation

---

## Produces

Diagnostic[]

---

## Never

Influence migration execution.

---

# 12. ConfigurationService

## Purpose

Load runtime configuration.

---

## Responsibilities

Read:

- Invocation arguments
- User selections
- Configuration files
- Environment settings

---

## Produces

MigrationConfiguration

---

# 13. AuthenticationService

## Purpose

Provide authenticated Dataverse access.

---

## Responsibilities

- Accept bearer token
- Validate authentication
- Build Dataverse Client context

---

## Produces

AuthenticationContext

---

## Never

Store credentials.

---

# 14. Service Dependency Graph

```
Pipeline Step
      │
      ▼
Application Service
      │
      ▼
Dataverse API Client
      │
      ▼
Dataverse
```

Services never bypass the Dataverse client.

---

# 15. Service Ownership

| Service | Owns | Produces |
|----------|------|----------|
| DiscoveryService | Discovery | Component[] |
| LayerAnalysisService | Ownership Analysis | MigrationCandidate[] |
| ComponentLoaderService | Payload Retrieval | Component[] |
| ValidationService | Validation | ValidationResult[] |
| WritebackService | Persistence | MigrationReport |
| ReportService | Customer Reports | Reports |
| DiagnosticsService | Diagnostics | Diagnostic[] |
| ConfigurationService | Runtime Configuration | MigrationConfiguration |
| AuthenticationService | Authentication | AuthenticationContext |

---

# 16. Execution Responsibility

| Service | Discover | Preview | Migrate |
|----------|:--------:|:-------:|:--------:|
| AuthenticationService | ✓ | ✓ | ✓ |
| DiscoveryService | ✓ | ✓ | ✓ |
| LayerAnalysisService | ✓ | ✓ | ✓ |
| ComponentLoaderService | ✓ | ✓ | ✓ |
| ValidationService | ✗ | ✓ | ✓ |
| WritebackService | ✗ | ✗ | ✓ |
| ReportService | ✓ | ✓ | ✓ |
| DiagnosticsService | ✓ | ✓ | ✓ |
| ConfigurationService | ✓ | ✓ | ✓ |

---

# 17. Future Evolution

Adding a new application capability should typically require introducing a new Service rather than modifying existing ones.

Services should remain:

- Small
- Cohesive
- Stateless
- Independently testable

Framework orchestration should not change when new services are introduced.

---

# 18. Traceability

**Consumes**

- ARCHITECTURE.md
- DOMAIN_MODEL.md
- MIGRATION_MODES.md
- INVARIANTS.md

**Referenced By**

- PIPELINES.md
- DATAVERSE_CLIENT.md
- MIGRATION_RULES.md
- TASKS.md

The Service (Orchestration) layer coordinates the end-to-end migration session upon which the framework is built. Business transformations remain the responsibility of Migration Steps, while the capability responsibilities above are realized within the pipeline-stage `modules/` and cross-cutting `core/` primitives.