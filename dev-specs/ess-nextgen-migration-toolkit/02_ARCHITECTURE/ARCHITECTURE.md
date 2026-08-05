# ARCHITECTURE.md

# ESS NextGen Migration Toolkit — Architecture Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the logical architecture of the ESS NextGen Migration Toolkit.
>
> The architecture is intentionally independent of ESS-specific migration rules.
>
> It establishes the reusable framework upon which migration capabilities are implemented.
>
> Migration rules, Dataverse APIs, and orchestration behavior are documented separately.

---

# 1. Purpose

The toolkit is designed as a layered, extensible migration framework.

Rather than embedding migration logic directly into procedural scripts, the framework decomposes migration into independent responsibilities connected through a deterministic execution pipeline.

This architecture enables:

* Extensibility
* Testability
* Deterministic execution
* Independent evolution of migration rules
* Clear separation of concerns

---

# 2. Architectural Principles

## ARCH-001

Framework before migration rules.

The framework owns execution.

Migration rules plug into the framework.

---

## ARCH-002

One responsibility per module.

Each module owns one concern.

---

## ARCH-003

Dependencies flow downward only.

No circular dependencies.

---

## ARCH-004

Business logic never communicates directly with Dataverse.

---

## ARCH-005

Migration rules never perform persistence.

---

## ARCH-006

Infrastructure remains replaceable.

The Dataverse client, orchestrator, and persistence mechanisms can evolve independently without affecting migration rules.

---

# 3. High-Level Architecture

```text
                    User
                      │
                      ▼
          Migration Orchestrator
                      │
                      ▼
             Pipeline Engine
                      │
      ┌───────────────┼────────────────┐
      ▼               ▼                ▼
Preprocessing    Transformation    Postprocessing
                      │
                      ▼
                Diagnostics
                      │
                      ▼
               Dataverse client
                      │
                      ▼
                  Dataverse
```

---

# 4. Architectural Layers

```text
Orchestration

↓

Pipeline

↓

Modules

↓

Dataverse Client

↓

Platform
```

Each layer depends only on the layer directly beneath it. Orchestration is the
application entry point (`service/mtk_orchestrator.py`). Logging, canonical
models, and generic utilities are cross-cutting `core` primitives available to
every layer.

---

# 5. Core Modules

---

## 5.1 Migration Orchestrator

Implemented as `service/mtk_orchestrator.py` — the application entry point and
top of the dependency graph.

### Purpose

Coordinates an entire migration session.

### Responsibilities

* Initialize execution
* Build MigrationContext
* Select Execution Mode
* Invoke Pipeline Engine
* Coordinate progress
* Handle failures
* Produce final results

### Owns

* Session lifecycle
* Execution lifecycle

### Consumes

* Pipeline Engine
* Modules
* Dataverse client
* Diagnostics

### Produces

* MigrationReport

### Never

* Transform artifacts
* Call Dataverse directly

---

## 5.2 Pipeline Engine

### Purpose

Execute an ordered collection of Migration Steps.

### Responsibilities

* Register pipeline steps
* Execute steps sequentially
* Manage execution context
* Stop on failure
* Report execution status

### Owns

Pipeline execution.

### Consumes

MigrationContext

### Produces

Updated MigrationContext

### Never

* Read Dataverse
* Write Dataverse
* Make migration decisions

---

## 5.3 Preprocessing Module

### Purpose

Load migration inputs.

### Responsibilities

* Discover agents
* Discover components
* Load component metadata
* Analyze solution layers
* Build canonical models

### Produces

Canonical Models

### Never

* Transform components
* Persist changes

---

## 5.4 Transformation Pipeline

### Purpose

Apply migration rules.

### Responsibilities

* Execute Migration Steps
* Modify canonical models
* Produce transformed models

### Owns

Business transformations.

### Never

* Call Dataverse
* Persist artifacts

---

## 5.5 Postprocessing Module

### Purpose

Persist transformed artifacts.

### Responsibilities

* Serialize canonical models
* Call Dataverse client
* Validate persistence
* Produce writeback summary

### Never

* Perform transformations

---

## 5.6 Diagnostics Module

### Purpose

Capture execution diagnostics.

### Responsibilities

* Console logging
* File logging
* Session reports
* Error reporting
* Migration summaries

### Never

Influence migration behavior.

---

## 5.7 Dataverse client

### Purpose

Abstract all Dataverse communication.

### Responsibilities

* Authentication
* REST requests
* Serialization
* Deserialization
* Retry policies

### Never

Contain migration logic.

---

# 6. Execution Flow

Every execution follows the same lifecycle.

```text
Initialize Session
        │
        ▼
Build Migration Context
        │
        ▼
Preprocessing
        │
        ▼
Pipeline Execution
        │
        ▼
Validation
        │
        ▼
Postprocessing
        │
        ▼
Diagnostics
        │
        ▼
Migration Summary
```

Execution Modes determine how far the lifecycle progresses.

---

# 7. Dependency Rules

Allowed dependency graph:

```text
Orchestration (service/mtk_orchestrator.py)

↓

Pipeline Engine

↓

Modules

↓

Dataverse Client

↓

Dataverse
```

Forbidden examples:

* Dataverse Client → Pipeline
* Dataverse Client → Modules
* Modules → Orchestration
* Migration Step → Dataverse Client
* Migration Step → Dataverse

---

# 8. Extension Points

The framework exposes the following extension points.

---

## Migration Steps

Add new business transformations.

---

## Services

Add reusable application services.

---

## Dataverse API Clients

Add new Dataverse APIs.

---

## Canonical Models

Add support for new component types.

Framework changes should rarely be required.

---

# 9. Execution Context

Every migration session owns a single MigrationContext.

MigrationContext flows through the entire framework.

It contains:

* Execution Mode
* Environment
* Agent
* Components
* Diagnostics
* Configuration
* Session Metadata

The MigrationContext is the shared contract between all modules.

---

# 10. Error Handling

Errors propagate upward.

```text
Dataverse Client

↓

Service

↓

Pipeline

↓

Orchestrator

↓

User
```

Lower layers never suppress failures.

Diagnostics capture all failures.

---

# 11. Logging

All modules emit diagnostics through the Diagnostics framework.

Direct console output is prohibited.

Every execution generates:

* Console output
* Session log
* Migration report
* Diagnostics summary

---

# 12. Testing Strategy

Each architectural layer is tested independently.

| Layer           | Test Type         |
| --------------- | ----------------- |
| Migration Steps | Unit Tests        |
| Services        | Unit Tests        |
| Dataverse Client             | Integration Tests |
| Pipeline        | Golden Tests      |
| Orchestrator    | End-to-End Tests  |

---

# 13. Future Evolution

The framework is intentionally generic.

Future migration scenarios should require only:

* New Canonical Models
* New Migration Steps
* New Dataverse API Clients

Existing framework components should remain unchanged.

---

# 14. Traceability

Consumes:

* PROJECT.md
* MIGRATION_MODES.md
* CUSTOMER_JOURNEY.md
* INVARIANTS.md

Referenced By:

* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_CLIENT.md
* MIGRATION_RULES.md

This specification defines the architectural foundation of the ESS NextGen Migration Toolkit. All implementations, services, pipelines, and migration rules must conform to the architecture described herein.
