# PROJECT.md

# ESS NextGen Migration Toolkit
**Version:** Draft v1.0
**Owner:** Anil Kumar Adepu

**Project:** ESS Custom Engine Agent (CA) → Declarative Agent (DA) Migration Toolkit

**Repository Type:** Specification-Driven Development (SDD)

**Status:** Active Development

---

# 1. Purpose

The ESS NextGen Migration Toolkit is a pro-code migration framework that enables existing Employee Self-Service (ESS) Custom Engine Agents (CA) to transition to Declarative Agents (DA) while preserving supported customer customizations.

The toolkit serves as a temporary migration bridge during the CA → DA platform transition until feature parity is achieved.

The toolkit is designed to be:

* Deterministic
* Extensible
* Testable
* Observable
* Specification-driven

The toolkit itself is **not** the product being migrated.

It is the engineering framework responsible for migrating customer-owned ESS customizations.

---

# 2. Problem Statement

Microsoft-managed ESS packages will transition from Custom Engine Agent (CA) to Declarative Agent (DA).

While Microsoft-owned package artifacts are upgraded through package updates, customer-owned customizations require additional migration to remain compatible with the DA runtime.

Examples include:

* Customized Topics
* Customized Agent Metadata
* Customized Flows
* Customized Knowledge Sources
* Future supported ESS component types

Without a migration framework:

* Customer customizations become incompatible.
* Manual migration becomes error-prone.
* Customer adoption slows.
* Support cost increases.

---

# 3. Vision

Provide a reusable migration framework that enables safe, repeatable, and observable migration of customer-owned ESS customizations from CA to DA.

The framework should maximize confidence while minimizing customer effort.

Migration should become a predictable engineering process rather than a manual exercise.

---

# 4. Goals

## Primary Goals

* Enable migration of supported customer customizations.
* Preserve customer investments.
* Minimize migration risk.
* Support staged migration confidence.
* Produce deterministic results.
* Generate comprehensive diagnostics.

---

## Secondary Goals

* Minimize manual migration work.
* Improve customer confidence.
* Simplify engineering maintenance.
* Create reusable migration patterns for future scenarios.

---

# 5. Non-Goals

The toolkit will **not**:

* Replace Dataverse ALM.
* Replace Solution management.
* Modify Microsoft-managed package artifacts.
* Migrate unsupported platform capabilities.
* Perform generic Dataverse migrations outside ESS.

---

# 6. Product Scope

The toolkit focuses exclusively on customer-owned ESS artifacts.

Current migration scope includes:

* Agent metadata
* Topics
* Power Automate flows
* Knowledge sources
* Additional supported ESS components

Support for new component types should be extensible through migration rules.

---

# 7. Migration Strategy

Migration follows a staged confidence model. These are customer-journey
*intents* that map onto the two technical execution modes (`READONLY` /
`WRITEBACK` — see `01_PRODUCT/MIGRATION_MODES.md`):

```text
Discover   → READONLY

↓

Preview    → READONLY

↓

Migrate    → WRITEBACK
```

Each stage increases confidence before customer environments are modified.

The migration engine remains identical across `READONLY` and `WRITEBACK`.

Only persistence differs.

---

# 8. Customer Types

The toolkit supports two customer categories.

## ALM Customers

Characteristics

* Preferred Solution configured.
* Customer customizations managed through ALM.

Migration writes transformed artifacts back into the Preferred Solution.

---

## Non-ALM Customers

Characteristics

* No Preferred Solution configured.
* Customizations reside within the Default Solution.

Migration writes transformed artifacts into the Default Solution.

---

# 9. Product Principles

The toolkit is built upon the following principles.

## Customer Safety

Customer environments are never modified without explicit migration execution.

---

## Progressive Confidence

Migration progresses through:

* Discovery
* Preview
* Migration

Customers understand migration before execution.

---

## Determinism

Identical inputs always produce identical outputs.

---

## Extensibility

New migration capabilities should require adding migration rules rather than redesigning the framework.

---

## Observability

Every execution generates diagnostics sufficient for troubleshooting.

---

## Separation of Concerns

Discovery, transformation, validation, persistence, and diagnostics remain independent responsibilities.

---

# 10. Success Criteria

The project is successful when:

* Existing CA customers can migrate to DA with minimal effort.
* Supported customer customizations are preserved.
* Migration is deterministic.
* Migration diagnostics explain unsupported scenarios.
* Preview accurately represents migration execution.
* The framework remains maintainable and extensible.

---

# 11. Project Lifecycle

The toolkit is intended to be transitional.

High-level lifecycle:

```text
CA

↓

Migration Bridge

↓

DA

↓

Feature Parity

↓

Migration Tool Retired
```

As CA and DA converge toward feature parity, reliance on the migration toolkit should steadily decrease.

---

# 12. Repository Philosophy

This repository follows Specification-Driven Development (SDD).

Specifications define expected system behavior.

Implementation exists only to satisfy those specifications.

Specifications remain the authoritative source of truth.

---

# 13. Repository Organization

Specifications are organized into logical layers.

```text
Meta

↓

Product

↓

Architecture

↓

Engineering

↓

Execution
```

Each layer builds upon the previous layer.

---

# 14. Related Specifications

This document introduces the project.

Detailed behavior is defined by the following specifications.

## Meta

* AGENTS.md
* INVARIANTS.md
* VOCABULARY.md

## Product

* CUSTOMER_JOURNEY.md
* MIGRATION_MODES.md
* MIGRATION_RULES.md
* ROADMAP.md

## Architecture

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_CLIENT.md

## Engineering

* REPOSITORY_STRUCTURE.md
* CODING_STANDARDS.md
* DIAGNOSTICS.md
* TESTING.md
* IMPLEMENTATION_GUIDE.md

## Execution

* TASKS.md
* CHANGELOG.md

---

# 15. Traceability

This document establishes the overall product contract for the ESS NextGen Migration Toolkit.

All downstream specifications, implementation tasks, and generated code must remain consistent with the goals, scope, and principles defined here.

When architectural or implementation decisions conflict with this document, the conflict should be resolved by updating the specifications before changing the implementation.
