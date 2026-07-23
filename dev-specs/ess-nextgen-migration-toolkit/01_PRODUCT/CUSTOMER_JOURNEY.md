# CUSTOMER_JOURNEY.md

# ESS NextGen Migration Toolkit — Customer Journey Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This specification defines the end-to-end customer experience for migrating Employee Self-Service (ESS) Custom Engine Agents (CA) to Declarative Agents (DA).
>
> It describes **what the customer experiences**, independent of implementation details.
>
> Architecture, pipelines, APIs, and migration rules derive from this document.

---

# 1. Purpose

The migration toolkit enables existing ESS customers to safely transition customer-owned customizations from Custom Engine Agents (CA) to Declarative Agents (DA).

The customer experience follows a progressive confidence model:

```text
Discover
    ↓
Preview
    ↓
Migrate
```

Each stage builds confidence before customer environments are modified. These
are customer-journey *intents*; technically they run in one of two execution
modes — Discover and Preview in `READONLY`, Migrate in `WRITEBACK`
(see `01_PRODUCT/MIGRATION_MODES.md`).

---

# 2. Scope

This specification defines:

* Customer personas
* Customer workflow
* Customer-visible outputs
* Customer decisions
* Success criteria

This specification intentionally excludes:

* Dataverse APIs
* Internal architecture
* Migration implementation
* Pipeline design

---

# 3. Customer Personas

## PERSONA-001 — ALM Customer

Characteristics

* Preferred Solution configured
* Solution lifecycle managed through ALM
* Existing deployment process

Migration target:

Preferred Solution

---

## PERSONA-002 — Non-ALM Customer

Characteristics

* No Preferred Solution
* Customizations exist in Default Solution
* No established ALM process

Migration target:

Default Solution

---

# 4. Customer Journey

All customers follow the same logical journey.

```text
Authenticate
      │
      ▼
Select Environment
      │
      ▼
Select ESS Agent
      │
      ▼
Discover
      │
      ▼
Review Readiness Report
      │
      ▼
Preview
      │
      ▼
Review Preview Report
      │
      ▼
Approve Migration
      │
      ▼
Migrate
      │
      ▼
Review Migration Summary
```

Only the writeback destination differs between ALM and non-ALM customers.

---

# 5. Discovery Experience

## Objective

Understand the customer's environment without making changes.

### Customer Actions

* Authenticate
* Select environment
* Select ESS agent
* Run discovery

### Customer Outputs

* Migration Readiness Report
* Customized component inventory
* Net-new component inventory
* Unsupported construct report
* Warnings

### Side Effects

None.

No customer artifacts are modified.

---

# 6. Preview Experience

## Objective

Show exactly what migration will perform.

### Customer Actions

* Execute Preview

### Customer Outputs

* Migration Preview Report
* Proposed component changes
* Validation results
* Warnings
* Unsupported constructs

### Side Effects

None.

No customer artifacts are modified.

---

# 7. Migration Experience

## Objective

Execute the validated migration.

### Customer Actions

* Approve migration
* Execute migration

### Customer Outputs

* Migration Summary
* Validation Report
* Diagnostics

### Side Effects

Supported customer artifacts are updated.

---

# 8. Customer Decision Points

## DECISION-001

Select target environment.

---

## DECISION-002

Select ESS agent.

---

## DECISION-003

Review Migration Readiness Report.

Continue or stop.

---

## DECISION-004

Review Migration Preview.

Approve or cancel migration.

---

# 9. Customer Expectations

The toolkit should ensure:

## CUST-001

Migration is predictable.

---

## CUST-002

Preview accurately represents migration execution.

---

## CUST-003

Customers understand why components are skipped.

---

## CUST-004

Customers can safely stop after Discover or Preview without affecting their environment.

---

## CUST-005

Migration minimizes manual effort.

---

# 10. Failure Experience

Failures should always communicate:

* What failed
* Why it failed
* Which components are affected
* Suggested remediation
* Whether migration may continue

Customers should never receive unexplained failures.

---

# 11. Success Experience

Successful migration concludes with:

```text
✓ Discovery Complete

✓ Preview Complete

✓ Migration Complete

✓ Validation Complete
```

The toolkit produces:

* Migration Summary
* Diagnostics
* Session Logs
* Reports

---

# 12. Future Evolution

As Custom Engine Agent and Declarative Agent achieve feature parity:

* Migration complexity decreases.
* Fewer transformation rules are required.
* Dedicated migration tooling becomes unnecessary.

Future migration experiences may be integrated directly into Microsoft Copilot Studio using the patterns established by this toolkit.

---

# 13. Traceability

**Consumes**

* PROJECT.md
* MIGRATION_MODES.md
* VOCABULARY.md

**Referenced By**

* ARCHITECTURE.md
* TASKS.md
* IMPLEMENTATION_GUIDE.md

This specification defines the required customer experience. All architectural and implementation decisions must preserve this experience.
