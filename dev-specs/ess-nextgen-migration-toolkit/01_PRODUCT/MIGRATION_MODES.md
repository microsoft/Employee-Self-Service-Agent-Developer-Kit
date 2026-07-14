# MIGRATION_MODES.md

# ESS NextGen Migration Toolkit — Migration Modes Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This specification defines the execution modes supported by the ESS NextGen Migration Toolkit.
>
> Execution Modes determine **how far** the migration pipeline executes.
>
> They **do not** change the migration logic itself.
>
> The same migration rules are executed across execution modes wherever applicable. The primary difference is whether transformed artifacts are persisted back to the customer environment.

---

# 1. Purpose

The migration framework supports progressive execution through multiple confidence levels.

Rather than immediately modifying customer environments, migrations proceed through increasingly trusted stages:

```text
DISCOVER
    ↓
PREVIEW
    ↓
MIGRATE
```

Each stage builds confidence before advancing to the next.

---

# 2. Design Goals

Execution Modes are designed to achieve the following goals.

## MODE-001

Separate environment discovery from migration execution.

---

## MODE-002

Allow customers to understand migration impact before writeback.

---

## MODE-003

Reuse the same migration engine across Preview and Migrate.

---

## MODE-004

Guarantee Preview faithfully represents Migrate.

---

## MODE-005

Minimize duplicated implementation.

---

# 3. Execution Model

Every toolkit execution begins with an Execution Mode.

```text
MigrationContext
        │
        ▼
Execution Mode
        │
        ▼
Pipeline Orchestrator
        │
        ▼
Execute Supported Pipelines
```

Execution Mode controls:

* Which pipelines execute
* Which outputs are generated
* Whether persistence is allowed

Execution Mode **does not** change migration rules.

---

# 4. DISCOVER Mode

---

## Identifier

DISCOVER

---

## Purpose

Inventory the customer environment and determine migration readiness.

---

## Customer Objective

Understand:

* What customizations exist
* Which components are migration candidates
* Which constructs are unsupported

---

## Pipeline Execution

```text
Initialize
    │
    ▼
Discover
    │
    ▼
Analyze
    │
    ▼
Diagnostics
```

---

## Responsibilities

* Authenticate
* Discover ESS Agents
* Discover migration candidates
* Analyze component ownership
* Analyze solution layers
* Detect unsupported constructs
* Generate readiness report

---

## Allowed Pipelines

* Discovery Pipeline
* Analysis Pipeline
* Diagnostics Pipeline

---

## Forbidden Pipelines

* Migration Pipeline
* Persistence Pipeline

---

## Allowed Side Effects

* Console logging
* Session logging
* Diagnostics generation

---

## Forbidden Side Effects

* Dataverse updates
* Artifact modification
* Component writeback

---

## Inputs

* Dataverse Environment
* ESS Agent
* Authentication Context

---

## Outputs

* Migration Readiness Report
* Candidate Inventory
* Diagnostics

---

## Exit Criteria

Customer understands whether migration can proceed.

---

# 5. PREVIEW Mode

---

## Identifier

PREVIEW

---

## Purpose

Execute the complete migration pipeline without persisting changes.

---

## Customer Objective

Understand exactly what migration will do.

---

## Pipeline Execution

```text
Initialize
    │
    ▼
Discover
    │
    ▼
Analyze
    │
    ▼
Transform
    │
    ▼
Validate
    │
    ▼
Preview Report
```

---

## Responsibilities

* Execute migration rules
* Validate transformed artifacts
* Generate migration preview
* Produce diagnostics

---

## Allowed Pipelines

* Discovery Pipeline
* Analysis Pipeline
* Migration Pipeline
* Validation Pipeline
* Diagnostics Pipeline

---

## Forbidden Pipelines

* Persistence Pipeline

---

## Allowed Side Effects

* Console logging
* Diagnostics generation
* Preview generation

---

## Forbidden Side Effects

* Dataverse updates
* Component writeback
* Artifact persistence

---

## Inputs

* Dataverse Environment
* ESS Agent
* Authentication Context

---

## Outputs

* Migration Preview Report
* Proposed Changes
* Validation Results
* Diagnostics

---

## Exit Criteria

Customer understands exactly what Migrate will perform.

---

# 6. MIGRATE Mode

---

## Identifier

MIGRATE

---

## Purpose

Execute validated migration and persist supported changes.

---

## Customer Objective

Complete migration.

---

## Pipeline Execution

```text
Initialize
    │
    ▼
Discover
    │
    ▼
Analyze
    │
    ▼
Transform
    │
    ▼
Validate
    │
    ▼
Persist
    │
    ▼
Migration Report
```

---

## Responsibilities

* Execute migration rules
* Validate transformed artifacts
* Persist migrated artifacts
* Validate persistence
* Generate migration summary

---

## Allowed Pipelines

* Discovery Pipeline
* Analysis Pipeline
* Migration Pipeline
* Validation Pipeline
* Persistence Pipeline
* Diagnostics Pipeline

---

## Allowed Side Effects

* Dataverse updates
* Component writeback
* Session logging
* Diagnostics generation

---

## Inputs

* Approved Migration Preview
* Dataverse Environment
* ESS Agent
* Authentication Context

---

## Outputs

* Migration Summary
* Validation Report
* Persisted Components
* Diagnostics

---

## Exit Criteria

Supported customer customizations are successfully migrated.

---

# 7. Execution Matrix

| Capability                  | DISCOVER | PREVIEW | MIGRATE |
| --------------------------- | :------: | :-----: | :-----: |
| Authentication              |     ✓    |    ✓    |    ✓    |
| Discover ESS Agents         |     ✓    |    ✓    |    ✓    |
| Discover Components         |     ✓    |    ✓    |    ✓    |
| Analyze Component Ownership |     ✓    |    ✓    |    ✓    |
| Analyze Solution Layers     |     ✓    |    ✓    |    ✓    |
| Execute Migration Rules     |     ✗    |    ✓    |    ✓    |
| Validate Transformations    |     ✗    |    ✓    |    ✓    |
| Generate Reports            |     ✓    |    ✓    |    ✓    |
| Persist Changes             |     ✗    |    ✗    |    ✓    |
| Generate Diagnostics        |     ✓    |    ✓    |    ✓    |

---

# 8. Execution Guarantees

## MODE-GUARANTEE-001

Preview and Migrate execute identical migration rules.

---

## MODE-GUARANTEE-002

Preview never persists customer artifacts.

---

## MODE-GUARANTEE-003

Discover never transforms customer artifacts.

---

## MODE-GUARANTEE-004

Migrate always performs validation before persistence.

---

## MODE-GUARANTEE-005

Migration reports accurately reflect the execution performed.

---

# 9. Failure Behaviour

## DISCOVER

Failures prevent readiness assessment.

No customer changes occur.

---

## PREVIEW

Failures prevent preview generation.

No customer changes occur.

---

## MIGRATE

Failures terminate migration.

Successful writebacks remain persisted unless explicit rollback is supported.

Diagnostics must clearly identify:

* Failed stage
* Failed component
* Root cause
* Recommended remediation

---

# 9a. Rollback Strategy

Automated rollback is **out of scope** for the current toolkit version.

When MIGRATE fails partway through:

* Successful writebacks already persisted to the customer environment **remain
  persisted**. The toolkit does not automatically revert them.
* Recovery is achieved by resolving the root cause reported in diagnostics and
  **re-running migration**. Migration is idempotent (INVARIANT MIG-005), so a
  successful re-run reconciles the environment to the fully migrated state
  without introducing duplicate changes.
* Customers who require a restore point should rely on their existing Dataverse
  solution/ALM backup mechanisms before executing MIGRATE.

Automated rollback may be introduced in a future version. Until then, the
idempotent re-run path above is the documented rollback strategy referenced by
the roadmap.

---

# 10. Future Evolution

Execution Modes are expected to remain stable.

Future capabilities should extend existing modes rather than introducing new execution models unless fundamentally required.

Potential future enhancements include:

* Selective Migration
* Resume Migration
* Batch Migration
* Incremental Migration

These should build upon the existing execution model.

---

# 11. Traceability

**Consumes**

* PROJECT.md
* VOCABULARY.md
* INVARIANTS.md

**Referenced By**

* CUSTOMER_JOURNEY.md
* ARCHITECTURE.md
* PIPELINES.md
* TASKS.md

This specification defines the execution contract for the ESS NextGen Migration Toolkit. Every architectural component, service, pipeline, and implementation task must conform to the execution semantics described in this document.
