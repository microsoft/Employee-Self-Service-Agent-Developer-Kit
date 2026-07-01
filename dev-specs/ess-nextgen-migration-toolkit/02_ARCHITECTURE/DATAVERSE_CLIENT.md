# DATAVERSE_CLIENT.md

# ESS NextGen Migration Toolkit — Dataverse Client Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the Dataverse Client layer used by the ESS NextGen Migration Toolkit.
>
> The Dataverse client provides strongly typed wrappers around Dataverse REST APIs and is the only layer permitted to communicate directly with Dataverse.
>
> The Dataverse client contains **no business logic**. Its responsibility is limited to authentication, request execution, serialization, deserialization, retry handling, and conversion between Dataverse payloads and the framework's canonical domain models.

---

# 1. Purpose

The Dataverse client abstracts all communication with Microsoft Dataverse.

Its responsibilities include:

* Authentication
* HTTP communication
* Serialization
* Deserialization
* Retry handling
* Error translation

The Dataverse client is intentionally unaware of:

* Migration rules
* Customer ownership
* ALM
* Preview vs Migrate
* Pipeline execution

---

# 2. Design Principles

## Dataverse Client-001

The Dataverse client is the only layer allowed to communicate with Dataverse.

---

## Dataverse Client-002

The Dataverse client never contains migration logic.

---

## Dataverse Client-003

The Dataverse client exposes strongly typed methods.

Raw REST payloads never leave the Dataverse client.

---

## Dataverse Client-004

Every Dataverse API Client owns exactly one Dataverse API family.

---

## Dataverse Client-005

Authentication is provided externally.

The Dataverse client accepts a valid Bearer Token.

---

## Dataverse Client-006

Dataverse Client methods are deterministic and side-effect free except for explicit write operations.

---

# 3. Layer Placement

```
Pipeline Steps
        │
        ▼
Application Services
        │
        ▼
Dataverse Client
        │
        ▼
Dataverse REST APIs
```

Pipeline Steps never call the Dataverse client directly.

---

# 4. Dataverse API Clients

The Dataverse client is organized into independent API clients.

```
AuthenticationClient

↓

AgentClient

↓

DependencyClient

↓

ComponentLayerClient

↓

ComponentClient

↓

SolutionClient

↓

WritebackClient
```

Each client wraps a cohesive set of REST endpoints.

---

# 5. AuthenticationClient

## Purpose

Provide authenticated Dataverse communication.

---

## Responsibilities

* Accept Bearer Token
* Validate token format
* Attach Authorization headers

---

## Produces

AuthenticationContext

---

## Never

* Acquire tokens
* Refresh tokens
* Persist credentials

---

# 6. AgentClient

## Purpose

Retrieve ESS Agents available within an environment.

---

## Responsibilities

* Enumerate Agents
* Retrieve Agent Metadata
* Retrieve Agent Configuration

---

## Produces

Agent

---

## Never

Determine migration eligibility.

---

# 7. DependencyClient

## Purpose

Retrieve migration candidates using Dataverse dependency APIs.

---

## Responsibilities

Execute:

RetrieveDependenciesForUninstall

---

## Produces

ComponentReference[]

---

## Never

Determine ownership.

Never load full component payloads.

---

# 8. ComponentLayerClient

## Purpose

Retrieve Solution Component Layer information.

---

## Responsibilities

Retrieve all solution layers for a component.

---

## Produces

ComponentLayer[]

---

## Never

Classify ownership.

---

# 9. ComponentClient

## Purpose

Retrieve complete component payloads.

---

## Responsibilities

Load supported ESS artifacts including:

* Topics
* Agent Metadata
* Flows
* Knowledge Sources
* Future supported components

---

## Produces

Component

---

## Never

Transform component content.

---

# 10. SolutionClient

## Purpose

Retrieve solution metadata.

---

## Responsibilities

* Retrieve Preferred Solution
* Retrieve Default Solution
* Retrieve Solution Metadata

---

## Produces

Solution

---

## Never

Perform migration.

---

# 11. WritebackClient

## Purpose

Persist transformed components.

---

## Responsibilities

Update Dataverse artifacts.

---

## Consumes

Canonical Components

---

## Never

Transform artifacts.

---

# 12. Discovery Flow

The Dataverse client supports the following discovery sequence.

```
Retrieve ESS Agent

        │

        ▼

RetrieveDependenciesForUninstall

        │

        ▼

Component References

        │

        ▼

Retrieve Solution Component Layers

        │

        ▼

Retrieve Full Component Payloads
```

Ownership analysis occurs outside the Dataverse client.

---

# 13. Serialization Boundary

Everything below the Dataverse client uses Dataverse representations.

Examples:

* JSON
* XML
* HTTP Payloads

Everything above the Dataverse client uses Canonical Domain Models.

Translation occurs only within the Dataverse client.

---

# 14. Error Handling

The Dataverse client translates infrastructure failures into typed exceptions.

Examples include:

* Authentication Failure
* Authorization Failure
* Not Found
* Validation Failure
* Rate Limited
* Timeout
* Service Unavailable

Business logic never interprets raw HTTP status codes.

---

# 15. Retry Policy

The Dataverse client owns retry behavior.

Suggested policy:

| Failure | Action                      |
| ------- | --------------------------- |
| 429     | Exponential Backoff + Retry |
| 500     | Retry                       |
| 503     | Retry                       |
| Timeout | Retry                       |
| 401     | Fail Immediately            |
| 403     | Fail Immediately            |
| 404     | Return Not Found            |

Retry behavior is invisible to callers.

---

# 16. Ownership Matrix

| Dataverse API Client           | Owns                     |
| -------------------- | ------------------------ |
| AuthenticationClient | Authentication           |
| AgentClient          | ESS Agent APIs           |
| DependencyClient     | Dependency APIs          |
| ComponentLayerClient | Solution Layer APIs      |
| ComponentClient      | Component Retrieval APIs |
| SolutionClient       | Solution APIs            |
| WritebackClient      | Persistence APIs         |

---

# 17. Testing Strategy

Every Dataverse API Client requires:

* Unit Tests
* Integration Tests (where applicable)
* Mockable interfaces
* Deterministic responses

Business logic tests should mock Dataverse API Clients rather than calling Dataverse.

---

# 18. Future Evolution

The Dataverse client is expected to evolve only when:

* New Dataverse APIs are required
* Existing APIs change
* New ESS component types are introduced

Adding a new migration rule should rarely require Dataverse Client modifications.

---

# 19. Traceability

**Consumes**

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* INVARIANTS.md

**Referenced By**

* PIPELINES.md
* MIGRATION_RULES.md
* TASKS.md
* TESTING.md

The Dataverse client provides the infrastructure boundary between the ESS NextGen Migration Toolkit and Microsoft Dataverse. It is responsible solely for data access and transport concerns, allowing the remainder of the framework to remain focused on business behavior and migration logic.
