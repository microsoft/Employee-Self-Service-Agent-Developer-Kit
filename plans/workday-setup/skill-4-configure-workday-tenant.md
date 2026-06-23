# Plan: Skill 4 — `configure-workday-tenant` *(NEW)*

**Role:** Workday Administrator · Part of [Workday Setup](./README.md).
**Depends on:** [`skill-3-provision-workday-entra-app`](./skill-3-provision-workday-entra-app.md).

## Purpose

Perform the Workday-tenant-side configuration that the simplified setup requires. These
tasks are **not automatable** (Workday UI) — the skill guides, gates on role, and records
each task as a verified manual step. **No standalone Workday connection (e.g. the Workday
MCP) is used to verify setup:** standing one up requires substantially the *same* Entra-app +
tenant + connector configuration as the ESS agent's own connection, so it would be
**circular/redundant** as an atomic verifier — independent of which credentials it uses — not
a check of any single upstream step.

## Tasks (from the official simplified-setup doc)

> **Ordering note:** Register the API client **before** managing authentication policies — the
> auth policy must be scoped to the OAuth client identity, which only exists once the API
> client is registered.

1. **Create X.509 public key** from the Entra signing certificate.
2. **Edit Tenant Setup – Security:** set the redirection URL; enable **OAuth 2.0 Clients**
   and **SAML**; verify SAML IdP fields. The **Service Provider ID must match the Entra
   Identifier / Entity ID**.
3. **Register API Client:** functional areas **Core Payroll, Organizations and Roles,
   Staffing, Time Off and Leave** + **Include Workday Owned Scope = Yes** (required for REST
   `/workers/me`). Capture **Client ID**, **Token Endpoint**, **REST base URL**, and the
   **SOAP / web-services base URL** into config (skill-5 needs both base URLs).
4. **Manage authentication policies:** scope to the **OAuth client from task 3**, allow SAML
   as an allowed authentication type, then **Activate All Pending Authentication Policy
   Changes**.

## Permission gating

- Not a **Workday Administrator** → named error (shared helper) + stop.

## Verification

- These are manual Workday-admin tasks → flightcheck reports them as `MANUAL` (captures the
  observable artifacts it can, does **not** fail readiness). A `MANUAL` pass is **not**
  completion: each row also needs an explicit user acknowledgement (+ captured artifact)
  before it is marked done (see [`master-checklist.md`](./master-checklist.md)).
- New flightcheck `WD-TENANT-*` / `WD-API-CLIENT-*` checkpoints, run individually, confirm
  what is observable (e.g. config values captured, redirect/SP-ID match). The **functional**
  proof comes downstream, when skill 5's Copilot Studio connection authenticates
  successfully — not from any standalone Workday call here.
- Role gating for **Workday Administrator** is by **attestation** (no queryable directory) —
  a named-role prompt the user confirms, recorded as such.
- Updates master checklist rows.

## Acceptance criteria

- Each of the 4 tasks is independently verifiable (single checkpoint) or clearly `MANUAL`.
- API client registered **before** auth policies are scoped/activated.
- Client ID / Token Endpoint / **REST base URL** / **SOAP base URL** persisted for skill 5.
- The skill never marks a Workday-admin task "done" without an explicit manual
  acknowledgement (no standalone Workday connection is used as a setup shortcut).
