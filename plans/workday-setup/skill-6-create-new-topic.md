# Plan: Skill 6 — `create-new-topic`

**Role:** Environment Maker (+ Workday SME for tenant IDs/permissions) · Part of
[Workday Setup](./README.md).
**Depends on:** [`skill-5-install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md).

## Purpose

Create a new custom Workday scenario (beyond the OOTB set, e.g. Request Time Off) by adding
its template configuration and topic definition and wiring tenant-specific reference IDs.

## Approach

- Workday-specialized refactor of the existing **`src/skills/topics/create`** skill using the
  **Template Config + Shared Flow** pattern (reuse, not reinvention).
- A new scenario may need **additional API-client functional areas** → loops back to
  [`skill-4-configure-workday-tenant`](./skill-4-configure-workday-tenant.md) (Register API
  Client) when scopes are missing.
- On completion, **auto-generate a matching eval set** for the new topic (see
  [`evals`](./evals.md)).

## Permission gating

- Not an **Environment Maker** → named error + stop. Tenant-ID/permission gaps surface the
  Workday SME / `configure-workday-tenant` loop-back.

## Verification

- Emit two per-topic checkpoint families, run individually via `--checkpoint`:
  **`TOPIC-TRIGGER-*`** — the new topic exists and its trigger phrases/recognition are wired; and
  **`TOPIC-INTEGRATION-*`** — the topic's Workday system-action wiring resolves (e.g. `dialog:`
  references to `msdyn_copilotforemployeeselfservice*.topic.WorkdaySystem…Execution` exist in the
  deployed solution namespace, and tenant reference IDs are populated). Updates master checklist
  rows.

## Acceptance criteria

- New topic + template config created and wired with tenant reference IDs.
- A matching eval set is generated automatically (no separate manual step).
- Missing API scopes produce a clear loop-back to skill 4 rather than a silent failure.
