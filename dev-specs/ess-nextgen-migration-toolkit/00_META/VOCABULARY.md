# VOCABULARY.md

# ESS NextGen Migration Toolkit — Project Vocabulary
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the canonical vocabulary used throughout the ESS NextGen Migration Toolkit.
>
> Every term has exactly one meaning.
>
> Specifications, implementation, tests, diagnostics, and AI agents must use these definitions consistently.
>
> Avoid introducing synonyms or alternate terminology.

---

# 1. Purpose

The project vocabulary provides a shared language across the repository.

Every specification should use these terms consistently.

If a concept is missing, extend this document before introducing new terminology elsewhere.

---

# 2. Vocabulary Rules

## VOC-001

Each concept has exactly one preferred term.

---

## VOC-002

Avoid synonyms unless explicitly documented.

---

## VOC-003

Specifications should reference these definitions rather than redefining terms.

---

# 3. Core Platform Concepts

---

## Agent

### Definition

An Employee Self-Service (ESS) Copilot deployed within a Dataverse environment.

### Examples

* ESS HR Agent
* ESS IT Agent

### Related

* Topic
* Flow
* Knowledge
* Component

---

## Custom Engine Agent (CA)

### Definition

The legacy Copilot runtime model based on Custom Engine Agent architecture.

CA is the source migration platform.

---

## Declarative Agent (DA)

### Definition

The new Copilot runtime model based on Declarative Agent architecture.

DA is the migration target platform.

---

## Migration

### Definition

The process of transforming supported customer-owned customizations from CA-compatible artifacts into DA-compatible artifacts.

Migration never refers to package installation or package upgrades.

---

# 4. Dataverse Concepts

---

## Component

### Definition

A Dataverse solution component participating in migration.

Examples

* Topic
* Agent Metadata
* Flow
* Knowledge Source

Components are the smallest independently migrated units.

---

## Solution

### Definition

A Dataverse container used to organize components.

Solutions may be:

* Managed
* Unmanaged

---

## Preferred Solution

### Definition

The unmanaged solution designated by the maker as the destination for new customizations.

Preferred Solutions are characteristic of ALM-enabled environments.

---

## Default Solution

### Definition

The environment's default unmanaged solution.

Non-ALM customer customizations typically reside here.

---

## Solution Layer

### Definition

A single layer applied to a Dataverse component.

Layers determine ownership and precedence.

---

## Managed Layer

### Definition

A solution layer originating from a Microsoft-managed ESS package.

Managed layers are never modified during migration.

---

## Unmanaged Layer

### Definition

A solution layer created by customer customizations.

Migration operates on unmanaged layers.

---

# 5. Migration Concepts

---

## Migration Candidate

### Definition

A component eligible for migration.

Typically:

* Customized ESS components
* Net-new ESS components

---

## Supported Component

### Definition

A component type for which migration rules exist.

---

## Unsupported Construct

### Definition

A CA capability that cannot currently be transformed into a DA-compatible equivalent.

Unsupported constructs generate diagnostics but are not automatically migrated.

---

## Migration Rule

### Definition

A deterministic transformation that converts one supported CA construct into its DA equivalent.

Migration Rules are documented separately in:

```text
MIGRATION_RULES.md
```

---

## Migration Step

### Definition

The implementation of a single Migration Rule.

Migration Steps execute within the Migration Pipeline.

Each Migration Step performs exactly one logical transformation.

---

# 6. Execution Concepts

---

## Discover

### Definition

Read-only execution mode.

Responsibilities

* Inventory environment
* Discover migration candidates
* Analyze customization layers

Produces diagnostics only.

---

## Preview

### Definition

Transformation execution mode without persistence.

Responsibilities

* Execute migration pipeline
* Generate proposed changes
* Produce migration preview

Preview never writes to customer environments.

---

## Migrate

### Definition

Full migration execution mode.

Responsibilities

* Execute migration pipeline
* Persist transformed artifacts
* Validate migrated components

---

# 7. Architecture Concepts

---

## Canonical Model

### Definition

The internal representation of a business entity.

Migration logic operates exclusively on canonical models.

Canonical models are independent of Dataverse REST payloads.

---

## Pipeline

### Definition

An ordered sequence of execution stages responsible for one phase of migration.

Examples

* Discovery Pipeline
* Analysis Pipeline
* Migration Pipeline
* Validation Pipeline

---

## Migration Pipeline

### Definition

The pipeline responsible for executing Migration Steps.

---

## Migration Context

### Definition

The execution state shared across the migration workflow.

Contains:

* Environment
* Execution Mode
* Components
* Diagnostics
* Configuration

---

## Service

### Definition

The application orchestration layer (`service/mtk_orchestrator.py`), responsible
for coordinating a migration session — composing the lower layers and driving
the pipeline.

Migration rules live exclusively in `src/modules/transformation/steps/`.
The service layer never contains migration rules.

---

## Dataverse Client

### Definition

The Dataverse integration layer.

Responsibilities include:

* Authentication
* REST communication
* Serialization
* Deserialization

The Dataverse client never contains business logic.

---

# 8. Diagnostics Concepts

---

## Diagnostic

### Definition

Information generated during migration to assist troubleshooting.

Examples

* Warning
* Error
* Migration Summary
* Preview Report

---

## Session

### Definition

A single execution of the migration toolkit.

Each session generates an isolated diagnostics directory.

---

## Migration Report

### Definition

A structured summary describing the outcome of migration.

---

# 9. Engineering Concepts

---

## Specification

### Definition

A document describing expected system behavior.

Specifications are the authoritative source of truth.

---

## Invariant

### Definition

A non-negotiable engineering constraint.

Invariants must remain true regardless of implementation.

---

## Task

### Definition

The smallest independently implementable unit of work.

Tasks implement one or more specifications.

---

# 10. Naming Guidelines

Specifications, implementation, and diagnostics should consistently use the canonical vocabulary defined in this document.

Avoid introducing alternative names for existing concepts.

Examples

| Preferred       | Avoid                                            |
| --------------- | ------------------------------------------------ |
| Agent           | Bot (unless referring to Dataverse entity names) |
| Component       | Artifact, Object                                 |
| Migration Step  | Transformer                                      |
| Migration Rule  | Conversion Logic                                 |
| Preview         | Dry Run                                          |
| Canonical Model | DTO, Payload                                     |
| Service         | Manager, Helper                                  |
| Pipeline        | Workflow, Chain                                  |

---

# 11. Future Evolution

This vocabulary is expected to grow as new component types and migration capabilities are introduced.

Existing definitions should only change when platform behavior fundamentally changes.

New specifications should extend this vocabulary rather than redefining terminology.

---

# 12. Traceability

All specifications should reference the terminology defined in this document.

Implementation, diagnostics, and tests should use the canonical vocabulary consistently to minimize ambiguity and improve maintainability.

This document is the single authoritative source for project terminology.
