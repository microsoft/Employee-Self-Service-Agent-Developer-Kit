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

> **Pre-gate (single-tenant SAML coupling — do this first):** Workday supports exactly **one**
> active Entra-tenant SAML federation at a time; pointing a second Entra tenant at the same
> Workday tenant silently breaks the first (see `scripts/flightcheck/checks/workday.py`, the
> active-IdP warning). Before changing anything, **identify and record the current active SAML
> IdP row**: issuer/tenant ID, **Service Provider ID**, and the **signing-cert thumbprint**
> currently in use. If an unrelated IdP is already active, **stop and escalate** rather than
> overwrite it.

1. **Create X.509 public key** from the Entra signing certificate. **Verify its thumbprint
   matches the one skill-3 activated** (`preferredTokenSigningKeyThumbprint`, reused via
   `WD-CONN-102`) — a mismatch means the wrong cert was uploaded and SSO will fail.
2. **Edit Tenant Setup – Security:** set the redirection URL; enable **OAuth 2.0 Clients**
   and **SAML**; verify SAML IdP fields. The **Service Provider ID must match the Entra
   Identifier / Entity ID**.
3. **Register API Client:** functional areas **Core Payroll, Organizations and Roles,
   Staffing, Time Off and Leave** + **Include Workday Owned Scope = Yes** (required for REST
   `/workers/me`). Capture **Client ID**, **Token Endpoint**, and the **REST base URL** from
   the registered client's **"View API Client"** page.
   - **SOAP / web-services base URL comes from a *different* place** — it is derived from the
     tenant's **Workday web host**, not the Register API Client page. (Repo precedent:
     `connect/workday/step1.md` pattern-maps the logged-in Workday web host to the SOAP base URL
     — e.g. `impl.workday.com` → `https://wd2-impl-services1.workday.com/ccx/service` — and
     **prompts the user for it** when no pattern matches; `step3.md` then expects both base URLs
     at connection time.) Reuse that derivation (host → `…-services1….workday.com/ccx/service`)
     with a user-prompt fallback, and capture it separately. Persist **both** base URLs —
     skill-5 needs each.
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
- New flightcheck `WD-TENANT-001` / `WD-API-CLIENT-001` checkpoints, run individually, confirm
  what is observable (e.g. config values captured, redirect/SP-ID match). **Reuse `WD-CONN-102`**
  to assert the Workday-uploaded cert thumbprint matches the one skill-3 activated — don't mint
  a new cert checkpoint. The **functional** proof comes downstream, when skill 5's Copilot
  Studio connection authenticates successfully — not from any standalone Workday call here.
- Role gating for **Workday Administrator** is by **attestation** (no queryable directory) —
  a named-role prompt the user confirms, recorded as such.
- Updates master checklist rows.

## Acceptance criteria

- The single-tenant SAML pre-gate ran first: active IdP issuer/tenant ID, SP-ID, and cert
  thumbprint are recorded, and an unrelated active IdP halts with an escalation (never a silent
  overwrite).
- Each of the 4 tasks is independently verifiable (single checkpoint) or clearly `MANUAL`.
- API client registered **before** auth policies are scoped/activated.
- Client ID / Token Endpoint / **REST base URL** (from "View API Client") and **SOAP base URL**
  (derived from the Workday web host, per `step1.md`, with a user-prompt fallback) are both
  persisted for skill 5.
- The X.509 cert thumbprint matches skill-3's activated `preferredTokenSigningKeyThumbprint`.
- The skill never marks a Workday-admin task "done" without an explicit manual
  acknowledgement (no standalone Workday connection is used as a setup shortcut).
