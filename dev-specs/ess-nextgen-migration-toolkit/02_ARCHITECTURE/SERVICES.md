# SERVICES.md

# ESS NextGen Migration Toolkit — Application Services Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the application service layer of the ESS NextGen Migration Toolkit.
>
> Services encapsulate reusable application capabilities used throughout the migration framework.
>
> Services coordinate interactions between the Pipeline Engine and the Dataverse SDK while remaining independent of migration rules.
>
> Services never contain business transformation logic.

---

# 1. Purpose

The Service Layer provides reusable capabilities shared across multiple pipeline steps.

Examples include:

- Discovering components
- Loading component metadata
- Analyzing ownership
- Persisting changes
- Validating migrated artifacts
- Producing reports

Services expose **what** can be done.

Pipeline Steps decide **when** those capabilities are used.

---

# 2. Design Principles

## SERVICE-001

Services are stateless.

---

## SERVICE-002

Services expose reusable application capabilities.

---

## SERVICE-003

Services never contain migration rules.

---

## SERVICE-004

Services communicate only through Domain Models.

---

## SERVICE-005

Services never communicate directly with other Services.

Communication occurs through:

- MigrationContext
- Pipeline
- Orchestrator

---

## SERVICE-006

Services may depend on SDK Clients.

SDK Clients never depend on Services.

---

# 3. Service Layer

```
Pipeline Engine
        │
        ▼
Application Services
        │
        ▼
Dataverse SDK
```

Services isolate business workflows from infrastructure.

---

# 4. Service Catalogue

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

SDK Clients

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

Call Dataverse SDK.

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

- CLI arguments
- UI selections
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
- Build SDK context

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
SDK Client
      │
      ▼
Dataverse
```

Services never bypass the SDK.

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
- DATAVERSE_SDK.md
- MIGRATION_RULES.md
- TASKS.md

The Service Layer provides the reusable application capabilities upon which the migration framework is built. Business transformations remain the responsibility of Migration Steps, while Services provide reusable operations that support those transformations.