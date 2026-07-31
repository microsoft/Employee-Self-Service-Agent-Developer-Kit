# ROADMAP.md

# ESS NextGen Migration Toolkit — Product & Engineering Roadmap
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the planned evolution of the ESS NextGen Migration Toolkit.
>
> It serves as the authoritative roadmap for:
>
> * Product rollout
> * Engineering implementation
> * Repository maturity
> * Long-term transition strategy
>
> This roadmap intentionally focuses on **capabilities and milestones**, not sprint planning.

---

# 1. Purpose

The ESS NextGen Migration Toolkit is a temporary engineering bridge that enables existing Employee Self-Service (ESS) Custom Engine Agent (CA) customers to transition safely to Declarative Agents (DA).

The roadmap describes how the toolkit evolves from initial validation through production rollout and eventually becomes unnecessary once CA and DA achieve feature parity.

---

# 2. Guiding Principles

The roadmap follows several principles.

## ROAD-001

Build confidence before writeback.

---

## ROAD-002

Validate internally before customer rollout.

---

## ROAD-003

Separate technical feasibility from customer adoption.

---

## ROAD-004

Progressively reduce migration risk.

---

## ROAD-005

Treat the migration toolkit as temporary infrastructure rather than a permanent product.

---

# 3. Product Evolution

```text
Stage 0
Upgrade Readiness Validation
        │
        ▼
Stage 1
Discovery
(Read Only)
        │
        ▼
Stage 2
Preview
(Dry Run)
        │
        ▼
Stage 3
Migration Execution
        │
        ▼
Stage 4
DA-First Engineering
        │
        ▼
Stage 5
Broad Customer Rollout
        │
        ▼
Stage 6
Feature Parity
        │
        ▼
Stage 7
DA-Only End State
```

---

# 4. Stage 0 — Upgrade Readiness Validation

## Status

Completed

---

## Objective

Validate the technical feasibility of upgrading existing CA package lineage to DA package lineage.

---

## Deliverables

* Upgrade mechanism validated.
* Package identity preserved.
* Configuration preserved.
* In-place package replacement validated.

---

## Customer Experience

None.

Internal engineering validation only.

---

## Exit Criteria

* Upgrade path validated.
* Technical feasibility established.

---

# 5. Stage 1 — Discovery

## Target

Initial Internal Dogfood

---

## Execution Mode

`READONLY` (Discover intent)

---

## Objective

Inventory customer-owned customizations without modifying customer environments.

---

## Capabilities

* Authenticate
* Discover ESS agents
* Discover migration candidates
* Analyze component ownership
* Analyze customization layers
* Detect unsupported constructs
* Produce migration readiness report

---

## Customer Experience

Read-only assessment.

No transformations.

No persistence.

---

## Deliverables

* Migration Readiness Report
* Environment Inventory
* Diagnostics

---

## Exit Criteria

* Discovery validated internally.
* Customer-owned artifacts correctly identified.
* Readiness reports accurate.

---

# 6. Stage 2 — Preview

## Target

Internal Dogfood + Design Partners

---

## Execution Mode

`READONLY` (Preview intent)

---

## Objective

Execute the complete migration pipeline without modifying customer environments.

---

## Capabilities

* Execute transformation pipeline
* Generate migration preview
* Produce change summary
* Validate transformed artifacts
* Report unsupported constructs

---

## Customer Experience

Preview proposed migration.

No writeback.

---

## Deliverables

* Migration Preview Report
* Proposed Changes
* Validation Summary

---

## Exit Criteria

* Preview accurately reflects migration execution.
* Transformation coverage validated.
* Design partner confidence established.

---

# 7. Stage 3 — Migration Execution

## Target

Internal Dogfood

---

## Execution Mode

`WRITEBACK` (Migrate intent)

---

## Objective

Execute validated migration.

---

## Capabilities

* Persist transformed artifacts
* Validate migrated components
* Produce migration summary
* Produce diagnostics

---

## Customer Experience

End-to-end migration.

Discovery

↓

Preview

↓

Approve

↓

Migrate

---

## Deliverables

* Migrated Components
* Migration Summary
* Validation Report

---

## Exit Criteria

* Successful internal migrations.
* Successful design partner migrations.
* Writeback safety validated.
* Rollback strategy documented.

---

# 8. Stage 4 — DA-First Engineering

## Objective

Transition ESS engineering investment from CA to DA.

---

## Activities

* Freeze CA feature development.
* Move active engineering to DA.
* Retain CA for servicing only.
* Maintain migration bridge.

---

## Exit Criteria

Leadership approval.

Migration confidence established.

---

# 9. Stage 5 — Broad Customer Rollout

## Objective

Operationalize migration at production scale.

---

## Activities

* Publish major package updates.
* Enable production migration.
* Support customer rollout.
* Monitor adoption.

---

## Customer Experience

Existing CA customers migrate using the toolkit.

New customers install DA packages directly.

---

## Exit Criteria

Migration available for production customers.

---

# 10. Stage 6 — Feature Parity

## Target

December 2026

---

## Objective

Eliminate remaining CA ↔ DA platform gaps.

---

## Activities

* Complete migration rule coverage.
* Remove temporary workarounds.
* Simplify migration.

---

## Exit Criteria

Migration complexity minimized.

Toolkit usage significantly reduced.

---

# 11. Stage 7 — DA-Only End State

## Target

January 2027+

---

## Objective

Complete transition to Declarative Agents.

---

## Activities

* Retire migration bridge.
* Remove CA-specific pathways.
* Operate entirely on DA.

---

## End State

```text
Customer

↓

DA Packages

↓

Copilot Studio

↓

No Dedicated Migration Tool
```

Migration becomes unnecessary for normal customer operations.

---

# 12. Repository Evolution

The repository itself evolves incrementally.

```text
Repository Scaffolding
        │
        ▼
Canonical Domain Models
        │
        ▼
Dataverse Client
        │
        ▼
Discovery Services
        │
        ▼
Pipeline Framework
        │
        ▼
Migration Rules
        │
        ▼
Preview Engine
        │
        ▼
Persistence Engine
        │
        ▼
Diagnostics
        │
        ▼
User Experience
        │
        ▼
Production Hardening
```

---

# 13. Capability Matrix

| Capability          | Discover | Preview | Migrate |
| ------------------- | :------: | :-----: | :-----: |
| Authentication      |     ✓    |    ✓    |    ✓    |
| Agent Discovery     |     ✓    |    ✓    |    ✓    |
| Component Discovery |     ✓    |    ✓    |    ✓    |
| Layer Analysis      |     ✓    |    ✓    |    ✓    |
| Migration Rules     |     ✗    |    ✓    |    ✓    |
| Validation          |     ✗    |    ✓    |    ✓    |
| Report Generation   |     ✓    |    ✓    |    ✓    |
| Writeback           |     ✗    |    ✗    |    ✓    |

---

# 14. Long-Term Vision

The migration toolkit is intentionally temporary.

As Custom Engine Agent and Declarative Agent converge toward complete feature parity:

* Migration rules reduce.
* Platform handles compatibility natively.
* Dedicated migration tooling is retired.

Future migration experiences may be integrated directly into Microsoft Copilot Studio using the architectural patterns validated by this toolkit.

---

# 15. Specification Roadmap

Repository specifications are authored in the following order.

## Meta

* ✓ AGENTS.md
* ✓ PROJECT.md
* ✓ INVARIANTS.md
* ✓ VOCABULARY.md
* ✓ ROADMAP.md

---

## Product

* CUSTOMER_JOURNEY.md
* MIGRATION_MODES.md
* MIGRATION_RULES.md

---

## Architecture

* ARCHITECTURE.md
* DOMAIN_MODEL.md
* SERVICES.md
* PIPELINES.md
* DATAVERSE_CLIENT.md

---

## Engineering

* REPOSITORY_STRUCTURE.md
* CODING_STANDARDS.md
* DIAGNOSTICS.md
* TESTING.md
* IMPLEMENTATION_GUIDE.md

---

## Execution

* TASKS.md
* CHANGELOG.md

---

# 16. Traceability

**Consumes**

* PROJECT.md
* INVARIANTS.md

**Referenced By**

* TASKS.md
* IMPLEMENTATION_GUIDE.md

This roadmap defines the planned evolution of both the migration toolkit and the engineering repository. It intentionally separates long-term capability planning from day-to-day implementation tasks, ensuring that engineering decisions remain aligned with the overall migration strategy while allowing implementation details to evolve independently.
