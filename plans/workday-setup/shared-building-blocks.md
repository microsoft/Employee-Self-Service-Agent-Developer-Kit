# Plan: Workday shared building blocks (refactor for reuse)

Cross-cutting foundation extracted so the 6 Workday skills don't duplicate logic. Part of
the [Workday Setup](./README.md) initiative. The Entra-app helper item also **de-duplicates
connector authorization across Workday and ServiceNow** (today each path carries its own
connector ID inline), so it has value independent of the Workday work.

## Building blocks

### 1. Parameterized Entra-app helper — *(parameterize + de-duplicate)*
- **Gap (not a bug):** `src/skills/connect/azure/app-registration.md` hardcodes the
  connector `c26b24aa-7874-4e06-ad55-7d06b1f79b63` — which is **correct for ServiceNow**.
  Workday's `connect/workday/step2.md` already authorizes the **Workday** connector
  `4e4707ca-5f53-46a6-a819-f7765446e6ff` inline, so the two paths **duplicate** connector
  logic instead of sharing it. (The only real defect is a misleading comment in
  `app-registration.md` implying `c26b24aa` "also" serves Workday — correct that comment.)
- **Fix:** generalize the helper so the **connector app ID**, **scope**, and **target app
  (new vs existing SSO gallery app)** are parameters. ServiceNow passes `c26b24aa`;
  Workday passes `4e4707ca` — one helper, no duplication, no regression.
- Preserve the existing **permission-failure → stop** pattern already in the helper
  (section B.2 "Insufficient privileges").

### 2. Permission-gate helper
- A standard, reusable "**role check → specific named error → stop**" routine used by all
  6 skills. Each caller supplies the required role; on failure the message names the exact
  role (e.g. "This step requires the **Workday Administrator** role…") and halts.
- **Gating mechanism differs by role:** Entra roles (Graph role query), Power Platform
  (admin API), and Dataverse maker/system roles are checked **programmatically**. **Workday
  Administrator** and **InfoSec/IT** have no queryable directory here → gate by **explicit
  attestation + captured evidence** (a named-role prompt the user confirms), never a silent
  pass. The helper records which mode (programmatic vs attested) verified each gate.

### 3. Connection-field capture/validation helper
- Centralizes capture + validation of: **App ID URI** (Entra resource URL), **Workday
  OAuth token URL**, **Client ID**, **SOAP base URL**, and **REST base URL trimmed to
  `/api`** (the documented silent-failure gotcha — copy as displayed, then trim trailing
  path/`/v1`/tenant suffix).

### 4. Config persistence schema
- `.local/connect/workday/config.json` canonical shape:
  `installPath` (=`simplified`), `entraApp*`, `appIdUri`, `oauthClientId`,
  `tokenEndpoint`, `restBaseUrl`, `soapBaseUrl`, plus per-skill status fields.

### 5. Master-checklist updater
- Shared routine each skill calls to update **its own rows** in the single master checklist
  (see [`master-checklist.md`](./master-checklist.md)), keyed by step ID, recording status
  + the flightcheck checkpoint used to verify.
- A row backed by a `MANUAL`/attestation checkpoint is **never auto-completed** by a
  flightcheck pass; it requires an explicit user acknowledgement (+ captured artifact) to
  reach *done*. A `MANUAL` result means "needs manual confirmation," **not** "done."

## Acceptance criteria

- The Entra-app helper produces a Workday-authorized app (`4e4707ca`, `user_impersonation`,
  Graph `openid`/`profile`/`User.Read`, admin consent) **and** still produces the correct
  ServiceNow result with `c26b24aa` — no regression.
- All 6 skills consume the permission-gate + checklist-updater helpers (no duplicated
  inline role checks or checklist writes).
- Config written by any skill round-trips through the documented schema.

## Out of scope

- The skills themselves (see the `skill-*` plans) and the master checklist file
  (see [`master-checklist.md`](./master-checklist.md)).
- Flightcheck CLI changes (see [`flightcheck-single-checkpoint.md`](./flightcheck-single-checkpoint.md)).
