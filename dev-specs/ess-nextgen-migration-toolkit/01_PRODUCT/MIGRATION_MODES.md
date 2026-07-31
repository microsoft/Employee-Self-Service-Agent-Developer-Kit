# MIGRATION_MODES.md

# ESS NextGen Migration Toolkit — Migration Modes Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This specification defines the execution modes supported by the ESS NextGen Migration Toolkit.
>
> Execution Modes determine **whether** transformed artifacts are persisted back to the customer environment.
>
> They **do not** change the migration logic itself.
>
> The same migration rules are executed across execution modes. The only difference is whether transformed artifacts are persisted back to the customer environment.

---

# 1. Purpose

The migration toolkit executes in one of **two technical execution modes**,
defined by the ESS-domain `ExecutionMode` StrEnum
(`src/modules/transformation/models/execution_mode.py`). The generic framework
base (`ExecutionContext`, `src/core/models/execution_context.py`) stays
product-agnostic and carries only an opaque `mode: str`; the domain enum's
string values populate it:

```text
READONLY   →   WRITEBACK
```

An Execution Mode determines **whether transformed artifacts are persisted** back
to the customer environment. The same discovery, analysis, and transformation
logic runs in both modes; only persistence differs.

The customer-facing journey is described in three progressive *intents* —
**Discover**, **Preview**, **Migrate** (see `01_PRODUCT/CUSTOMER_JOURNEY.md`) —
which map onto the two technical modes:

| Customer intent | Meaning                                             | Execution Mode |
| --------------- | --------------------------------------------------- | -------------- |
| Discover        | Inventory the environment; assess readiness         | `READONLY`     |
| Preview         | Full dry-run showing exactly what Migrate would do   | `READONLY`     |
| Migrate         | Execute and persist supported changes               | `WRITEBACK`    |

Discover and Preview are the **same** `READONLY` run viewed at different depths —
`READONLY` always executes the whole pipeline (including transformations) and
computes the intended writes, but the persistence step is gated off so nothing is
written. `WRITEBACK` runs the identical pipeline and additionally persists.

Each step declares which modes it supports (`supported_modes`); the persistence
step alone is `("WRITEBACK",)`, so `MigrationPipelineStep.can_execute` skips it in
`READONLY`. This is the entire mechanism by which mode controls behaviour.

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

Reuse the same migration engine across `READONLY` and `WRITEBACK`.

---

## MODE-004

Guarantee a `READONLY` run faithfully represents what `WRITEBACK` would perform.

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

# 4. READONLY Mode

---

## Identifier

`READONLY` (serves the **Discover** and **Preview** customer intents)

---

## Purpose

Execute the complete pipeline — discovery, analysis, and transformation —
**without persisting any changes**. A single `READONLY` run serves both the
Discover intent (inventory + readiness) and the Preview intent (a faithful
dry-run of exactly what `WRITEBACK` would perform).

---

## Customer Objective

Understand:

* What customizations exist
* Which components are migration candidates
* Which constructs are unsupported
* Exactly what `WRITEBACK` would change (the proposed writes)

---

## Pipeline Execution

```text
Input        (authenticate, select agent, ALM input, agent config, discover customizations)
    │
    ▼
Transformation  (apply rules → compute pending writes)
    │
    ▼
Output       (validate + render report; persistence step skipped)
```

The Transformation stage still runs and computes `context.pending_writes`; the
Output stage's persistence step is gated off (`supported_modes=("WRITEBACK",)`),
so nothing is written to Dataverse.

---

## Responsibilities

* Authenticate
* Discover ESS Agents
* Discover migration candidates (customizations)
* Analyze component ownership and solution layers
* Detect unsupported constructs
* Execute migration rules (in-memory) and compute proposed writes
* Validate transformed artifacts
* Generate the report

---

## Allowed Side Effects

* Console logging
* Session logging
* Diagnostics + report generation

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

* Readiness + preview content in `migration_report.md` (candidates, customized /
  net-new / unsupported components, proposed changes, validation results,
  warnings)
* Diagnostics (`session.log`)

---

## Exit Criteria

Customer understands whether migration can proceed and exactly what `WRITEBACK`
would perform.

---

# 5. WRITEBACK Mode

---

## Identifier

`WRITEBACK` (serves the **Migrate** customer intent)

---

## Purpose

Execute the validated migration and **persist** supported changes back to the
customer environment.

---

## Customer Objective

Complete migration.

---

## Pipeline Execution

```text
Input
    │
    ▼
Transformation  (apply rules → pending writes)
    │
    ▼
Output       (validate → persist pending writes → render report)
```

The persistence step now runs and applies `context.pending_writes`. When the
customer has a preferred solution (ALM customers), writes target that solution;
otherwise they land in the default solution
(see `01_PRODUCT/CUSTOMER_JOURNEY.md`).

---

## Responsibilities

* Execute migration rules
* Validate transformed artifacts
* Persist migrated artifacts (`pending_writes`)
* Validate persistence
* Generate the migration report

---

## Allowed Side Effects

* Dataverse updates
* Component writeback
* Session logging
* Diagnostics + report generation

---

## Inputs

* Dataverse Environment
* ESS Agent
* Authentication Context
* (Recommended) a preceding approved `READONLY` preview

---

## Outputs

* Migration summary + writeback results in `migration_report.md`
* Persisted components
* Diagnostics (`session.log`)

---

## Exit Criteria

Supported customer customizations are successfully migrated and persisted.

---

# 7. Execution Matrix

| Capability                  | READONLY | WRITEBACK |
| --------------------------- | :------: | :-------: |
| Authentication              |     ✓    |     ✓     |
| Discover ESS Agents         |     ✓    |     ✓     |
| Discover Components         |     ✓    |     ✓     |
| Analyze Component Ownership |     ✓    |     ✓     |
| Analyze Solution Layers     |     ✓    |     ✓     |
| Execute Migration Rules     |     ✓    |     ✓     |
| Validate Transformations    |     ✓    |     ✓     |
| Generate Reports            |     ✓    |     ✓     |
| Persist Changes             |     ✗    |     ✓     |
| Generate Diagnostics        |     ✓    |     ✓     |

Migration rules execute in **both** modes (in-memory) — the sole difference is
the final **Persist Changes** step, which runs only in `WRITEBACK`.

---

# 8. Execution Guarantees

## MODE-GUARANTEE-001

`READONLY` and `WRITEBACK` execute identical migration rules.

---

## MODE-GUARANTEE-002

`READONLY` never persists customer artifacts.

---

## MODE-GUARANTEE-003

`READONLY` never modifies the customer environment (no Dataverse writes).

---

## MODE-GUARANTEE-004

`WRITEBACK` always performs validation before persistence.

---

## MODE-GUARANTEE-005

Migration reports accurately reflect the execution performed.

---

# 9. Failure Behaviour

## READONLY

Failures prevent readiness/preview generation.

No customer changes occur (READONLY never writes).

---

## WRITEBACK

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

When `WRITEBACK` fails partway through:

* Successful writebacks already persisted to the customer environment **remain
  persisted**. The toolkit does not automatically revert them.
* Recovery is achieved by resolving the root cause reported in diagnostics and
  **re-running migration**. Migration is idempotent (INVARIANT MIG-005), so a
  successful re-run reconciles the environment to the fully migrated state
  without introducing duplicate changes.
* Customers who require a restore point should rely on their existing Dataverse
  solution/ALM backup mechanisms before executing `WRITEBACK`.

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
