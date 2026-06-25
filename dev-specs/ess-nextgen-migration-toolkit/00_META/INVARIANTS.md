# INVARIANTS.md

# ESS NextGen Migration Toolkit — Engineering Invariants
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the non-negotiable engineering invariants of the ESS NextGen Migration Toolkit.
>
> These invariants represent architectural laws that all implementations must preserve.
>
> Every specification, implementation task, code review, and AI-generated change must comply with these invariants.
>
> If an implementation conflicts with an invariant, **the invariant always takes precedence**.

---

# 1. Purpose

Engineering invariants exist to ensure that the architecture remains consistent as the toolkit evolves.

Unlike implementation details, invariants are expected to remain stable throughout the lifetime of the project.

Every architectural decision should preserve these invariants.

---

# 2. Scope

These invariants apply to:

* Human contributors
* AI coding agents
* Generated code
* Future architectural extensions

They do **not** define migration business rules.

Business behavior is documented separately in:

* MIGRATION_RULES.md
* CUSTOMER_JOURNEY.md
* MIGRATION_MODES.md

---

# 3. Architectural Invariants

---

## ARCH-001

### Layer dependencies always point downward.

Allowed

```text
UI
↓

Application
↓

Pipeline

↓

Services

↓

SDK

↓

Dataverse
```

Forbidden

```text
SDK

↓

Pipeline
```

or

```text
Services

↓

UI
```

---

## ARCH-002

Each architectural layer owns exactly one responsibility.

Responsibilities must never overlap.

---

## ARCH-003

Business logic must remain independent of infrastructure.

Replacing the Dataverse SDK should not require changes to migration rules.

---

## ARCH-004

All external systems are accessed only through the SDK layer.

No module outside the SDK may communicate directly with Dataverse.

---

# 4. Domain Model Invariants

---

## MODEL-001

Migration logic operates only on canonical domain models.

Never perform business transformations directly against:

* REST payloads
* SDK DTOs
* JSON dictionaries
* YAML dictionaries

---

## MODEL-002

Canonical domain models are the single source of truth during execution.

All transformations operate against canonical models.

---

## MODEL-003

Translation between external representations and canonical models occurs only during:

* Loading
* Serialization
* Persistence

---

# 5. Pipeline Invariants

---

## PIPE-001

Pipeline execution is deterministic.

Given identical inputs, execution always produces identical outputs.

---

## PIPE-002

Pipeline steps are stateless.

No pipeline step may depend on hidden state.

---

## PIPE-003

Each pipeline step performs exactly one logical transformation.

---

## PIPE-004

Pipeline execution order is deterministic.

Execution order must not depend on registration order unless explicitly documented.

---

## PIPE-005

Pipeline steps never communicate directly with Dataverse.

They interact only through Services.

---

## PIPE-006

Pipeline steps never produce console output.

Diagnostics are emitted through the Diagnostics framework.

---

# 6. Service Invariants

---

## SERVICE-001

Services coordinate application behavior.

They do not implement migration rules.

---

## SERVICE-002

Services never modify business artifacts.

Transformation belongs exclusively to Migration Steps.

---

## SERVICE-003

Services may call the SDK.

Pipeline Steps may not.

---

# 7. SDK Invariants

---

## SDK-001

The SDK owns all Dataverse communication.

No other module performs HTTP requests.

---

## SDK-002

The SDK never contains migration logic.

---

## SDK-003

The SDK never performs business validation.

---

## SDK-004

SDK methods return strongly typed models.

Never expose raw REST payloads outside the SDK.

---

# 8. Migration Invariants

---

## MIG-001

The migration pipeline is identical for Preview and Migrate.

The only behavioral difference is persistence.

---

## MIG-002

Preview never modifies customer environments.

---

## MIG-003

Discover never performs transformations.

---

## MIG-004

Migration rules are independent.

Adding a new migration rule should not require modifying existing rules.

---

## MIG-005

Migration should be idempotent.

Executing migration multiple times should not introduce additional changes once migration has completed successfully.

---

# 9. Diagnostics Invariants

---

## DIAG-001

Every execution produces diagnostics.

---

## DIAG-002

Diagnostics never influence execution behavior.

---

## DIAG-003

Sensitive information must never be persisted.

Examples

* Access tokens
* OAuth tokens
* Secrets
* Connection strings

---

# 10. Testing Invariants

---

## TEST-001

Every Migration Step requires automated unit tests.

---

## TEST-002

Every transformation rule requires Golden File coverage.

---

## TEST-003

No implementation is complete without automated validation.

---

# 11. Extensibility Invariants

---

## EXT-001

Adding support for a new migration rule should require:

* New Migration Step
* New Tests
* Registration

Framework changes should not be required.

---

## EXT-002

Adding support for a new component type should require:

* Domain Model
* SDK support
* Service
* Pipeline
* Tests

---

# 12. Documentation Invariants

---

## DOC-001

Specifications remain the authoritative source of truth.

Implementation follows specifications.

---

## DOC-002

Behavioral changes require corresponding specification updates.

---

## DOC-003

Every completed task must maintain traceability back to the governing specifications.

---

# 13. AI Agent Invariants

---

## AI-001

AI agents never invent missing requirements.

---

## AI-002

When specifications are ambiguous, stop and request clarification.

---

## AI-003

AI agents implement only the requested scope.

Do not anticipate future work.

---

## AI-004

AI agents preserve architectural boundaries.

---

# 14. Repository Invariants

---

## REPO-001

No direct `print()` statements.

Use the Diagnostics framework.

---

## REPO-002

No duplicated business logic.

Shared behavior belongs in reusable components.

---

## REPO-003

One responsibility per module.

---

## REPO-004

Every pull request leaves the repository in a buildable, testable state.

---

# 15. Modifying Invariants

Engineering invariants are intentionally stable.

They should only be modified when:

* the architecture fundamentally changes,
* the product strategy changes,
* or a previous invariant is proven incorrect.

Implementation convenience is **not** a valid reason to modify an invariant.

---

# 16. Traceability

Every specification should reference the invariants it relies upon.

Every implementation task should preserve the applicable invariants.

Every code review should verify invariant compliance before approval.

The engineering invariants defined in this document represent the architectural constitution of the ESS NextGen Migration Toolkit.
