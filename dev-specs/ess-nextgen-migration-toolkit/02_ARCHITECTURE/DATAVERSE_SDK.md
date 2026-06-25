# DATAVERSE_SDK.md

# ESS NextGen Migration Toolkit — Dataverse SDK Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the Dataverse SDK layer used by the ESS NextGen Migration Toolkit.
>
> The SDK provides strongly typed wrappers around Dataverse REST APIs and is the only layer permitted to communicate directly with Dataverse.
>
> The SDK contains **no business logic**. Its responsibility is limited to authentication, request execution, serialization, deserialization, retry handling, and conversion between Dataverse payloads and the framework's canonical domain models.

---

# 1. Purpose

The Dataverse SDK abstracts all communication with Microsoft Dataverse.

Its responsibilities include:

* Authentication
* HTTP communication
* Serialization
* Deserialization
* Retry handling
* Error translation

The SDK is intentionally unaware of:

* Migration rules
* Customer ownership
* ALM
* Preview vs Migrate
* Pipeline execution

---

# 2. Design Principles

## SDK-001

The SDK is the only layer allowed to communicate with Dataverse.

---

## SDK-002

The SDK never contains migration logic.

---

## SDK-003

The SDK exposes strongly typed methods.

Raw REST payloads never leave the SDK.

---

## SDK-004

Every SDK Client owns exactly one Dataverse API family.

---

## SDK-005

Authentication is provided externally.

The SDK accepts a valid Bearer Token.

---

## SDK-006

SDK methods are deterministic and side-effect free except for explicit write operations.

---

# 3. Layer Placement

```
Pipeline Steps
        │
        ▼
Application Services
        │
        ▼
Dataverse SDK
        │
        ▼
Dataverse REST APIs
```

Pipeline Steps never call the SDK directly.

---

# 4. SDK Clients

The SDK is organized into independent API clients.

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

The SDK supports the following discovery sequence.

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

Ownership analysis occurs outside the SDK.

---

# 13. Serialization Boundary

Everything below the SDK uses Dataverse representations.

Examples:

* JSON
* XML
* HTTP Payloads

Everything above the SDK uses Canonical Domain Models.

Translation occurs only within the SDK.

---

# 14. Error Handling

The SDK translates infrastructure failures into typed exceptions.

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

The SDK owns retry behavior.

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

| SDK Client           | Owns                     |
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

Every SDK Client requires:

* Unit Tests
* Integration Tests (where applicable)
* Mockable interfaces
* Deterministic responses

Business logic tests should mock SDK Clients rather than calling Dataverse.

---

# 18. Future Evolution

The SDK is expected to evolve only when:

* New Dataverse APIs are required
* Existing APIs change
* New ESS component types are introduced

Adding a new migration rule should rarely require SDK modifications.

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

The Dataverse SDK provides the infrastructure boundary between the ESS NextGen Migration Toolkit and Microsoft Dataverse. It is responsible solely for data access and transport concerns, allowing the remainder of the framework to remain focused on business behavior and migration logic.
