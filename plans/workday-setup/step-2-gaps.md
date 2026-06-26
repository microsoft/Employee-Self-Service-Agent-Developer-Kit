# Step 2 Gaps — Workday Tenant Configuration (X.509, SAML, API Client, Endpoints)

Gap analysis and resolution for **Step 2 (2.1–2.4)** of the simplified Workday setup. Part of
[Workday Setup](./README.md). Each gap is closed by a **two-part fix**: a **skill** performs the
configuration action, and a **flightcheck** verifies it held.

**Source plans:** [`master-checklist`](./master-checklist.md) (canonical checkpoint registry),
[`skill-3-provision-workday-entra-app`](./skill-3-provision-workday-entra-app.md),
[`skill-4-configure-workday-tenant`](./skill-4-configure-workday-tenant.md),
[`skill-5-install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md).

> **Ownership note (reconciliation):** the gap source attributes Steps 2.1–2.2 to
> `provision-workday-entra-app` because the legacy monolith (`connect/workday/step2.md`) bundled
> them. In the new decomposition these **Workday-tenant tasks move to the net-new
> [`skill-4 configure-workday-tenant`](./skill-4-configure-workday-tenant.md)** (Workday Administrator
> role). skill-5 owns the connection-side REST trim; skill-3 owns the Entra-side signing cert.

> **Step 2 is attestation-heavy.** Unlike Step 1 (Entra/Graph, mostly automated), Step 2 is
> Workday-tenant-side and has **no queryable admin API** — so most checks are `MANUAL` / attestation
> (report what's observable, never auto-complete the row, never fail readiness).

---

## Step 2.1 — Create an X.509 Public Key

**The gap**
- *Skill side (COVERED):* `step2.md` guides the Workday **Create X509 Public Key** task — names the
  key, supplies the exact base64 to paste, and handles public-vs-private / PEM guidance.
- *Flightcheck side (PARTIAL):* `WD-CONN-102` checks the **Entra-side** signing-cert health and emits
  a manual "compare against the Workday UI" action; **no Workday API validates the X.509 directly**.

**Skill (the fix)**
- **skill-4 `configure-workday-tenant`, Task 1** — *"Create X.509 public key from the Entra signing
  certificate. Verify its thumbprint matches the one skill-3 activated
  (`preferredTokenSigningKeyThumbprint`)."* The cert itself is added + activated on the Entra side by
  **skill-3 (S3.4)**; skill-4 uploads the matching public key into Workday.

**Flightcheck (the proof)**
- **`WD-CONN-102`** (reuse, **MANUAL**) — asserts the Workday-uploaded cert thumbprint matches the one
  skill-3 activated. The Workday-side X.509 field is not API-reachable, so the operator performs the
  thumbprint comparison (`MANUAL`). No new cert checkpoint is minted.

**Status:** skill already covered; flightcheck gap closed **as a MANUAL thumbprint-parity check**. The
"alternative" (uploads `.pfx` / pastes private key) is handled by skill guidance: Workday requires the
public key in PEM/Base64 (`-----BEGIN CERTIFICATE-----`); export the public cert from the Entra app.

---

## Step 2.2 — Configure SAML Authentication Policy

**The gap**
- *Skill side (GAP, simplified):* **Activate All Pending Authentication Policy Changes** exists only in
  the legacy path (ISU username/password), not for the SAML / Entra-IdP-to-employee-group binding.
  Simplified skipped this and relied on the prerequisite web SSO.
- *Flightcheck side (GAP):* cannot detect **unactivated pending authentication policy changes**; no
  Workday API coverage.

**Skill (the fix)**
- **skill-4 Task 4** — *"Manage authentication policies: scope to the OAuth client from Task 3, allow
  SAML as an allowed authentication type, then **Activate All Pending Authentication Policy
  Changes**."* This explicitly adds the activate-pending step to the SAML/OAuth path (closing the
  "simplified skips this" gap).
- **skill-4 Task 2** — *Edit Tenant Setup – Security:* enable SAML, verify SAML IdP fields, and ensure
  the **Service Provider ID matches the Entra Identifier / Entity ID**.
- **skill-4 single-tenant SAML pre-gate** — identify and record the current active SAML IdP (issuer,
  SP-ID, cert thumbprint) **first**; halt and escalate if an unrelated IdP is already active (Workday
  supports only one active Entra-tenant federation).

**Flightcheck (the proof)**
- **`WD-TENANT-001`** (new, **attest**) — confirms the observable config (redirect URL, SP-ID ↔ Entra
  Identifier match, auth policy scoped to the OAuth client). It **cannot** auto-detect "pending changes
  not activated" (no Workday API), so the activation itself is an **operator attestation**.
- **`WD-CONN-010`** (reuse) — Entra↔Workday federation alignment / active-IdP single-tenant check
  (backs the pre-gate).

**Status:** skill gap closed (Task 4 adds activate-pending). Flightcheck gap closed **only as
attestation** — automated detection of unactivated pending policy changes is not possible without a
Workday API. The "policy edited but users still get auth errors" alternative is exactly the
forgot-to-activate case the attestation prompt guards.

---

## Step 2.3 — Register the API Client for Integrations

**The gap**
- *Skill side (GAP debug + RECONCILE):* `step2.md` covers registration, but the golden set specifies
  **JWT Bearer Grant** while the ADK uses **SAML Bearer Grant**, and the ADK functional areas are a
  **superset** of the golden set.
- *Flightcheck side (GAP, simplified):* missing functional areas were caught by the **legacy live SOAP
  probes `WD-WF-001…017`** — but those are **legacy-only and skipped on simplified**, so the simplified
  path can **silently miss** required functional areas.

**Skill (the fix)**
- **skill-4 Task 3** — *"Register API Client: functional areas **Core Payroll, Organizations and
  Roles, Staffing, Time Off and Leave** + **Include Workday Owned Scope = Yes** (required for REST
  `/workers/me`). Capture Client ID, Token Endpoint, and REST base URL from the View API Client
  page."* Ordering is enforced: **register the API client before** scoping auth policies (the policy
  must reference the OAuth client identity).

**Flightcheck (the proof)**
- **`WD-API-CLIENT-001`** (new, **attest**) — confirms what is observable (API client registered, scope
  captured). Detecting a **missing functional area** on simplified has **no API** (the legacy SOAP
  probes are gone), so completeness of functional areas is an **operator attestation**.

**Status:** skill gap closed (Task 3 enumerates the superset functional areas + Workday Owned Scope).
Flightcheck = attestation; **automated functional-area detection is not available on simplified** (a
deliberate coverage reduction vs. legacy). The "Access Denied / blank cards" alternative traces to a
missing functional area — exactly what the attestation prompt enumerates. **Open reconciliation
remains** (see below) on JWT vs SAML Bearer Grant.

---

## Step 2.4 — Capture and Trim API Endpoints

**The gap**
- *Skill side (COVERED):* the ADK auto-derives `restBaseUrl` as `https://{WD_TOKEN_HOST}/ccx/api` and
  injects it into the `OAuthUser` connection, eliminating the `/v1/tenant` trimming error.
- *Flightcheck side (PARTIAL):* `WD-CONN-012/101` verify binding/health, **not URL-format
  correctness**; no simplified runtime probe catches a malformed REST URL.

**Skill (the fix)**
- **skill-4 Task 3** captures the **REST base URL** (from View API Client) and the **SOAP base URL**
  (derived from the Workday web host per `step1.md`, with a user-prompt fallback) and **persists both**
  for skill-5.
- **skill-5 Configuration** sets the connection's **REST base URL trimmed to `/api`** via the shared
  connection-field helper, consuming skill-4's captured config (does not re-derive).

**Flightcheck (the proof)**
- **`WD-REST-001`** (new, **automated**, skill-5) — verifies the REST base URL is present and **ends at
  `/api`** (guards the documented silent failure). **This is the precise piece the gap said was
  missing.**
- **`WD-TENANT-001`** (new, attest) — Workday-side capture of Client ID / Token Endpoint / REST + SOAP
  base URLs.
- **`WD-CONN-012` / `WD-CONN-101`** (reuse) — connection binding completeness / health.

**Status:** skill covered (auto-derive + capture); flightcheck **PARTIAL → closed** by the new
automated `WD-REST-001` `/api`-trim check. The "leaves `/v1` or the tenant name" alternative is exactly
what `WD-REST-001` catches.

---

## Summary

| Step | Gap type | Skill fix (action) | Skill | Flightcheck (proof) | FC type |
|------|----------|--------------------|-------|---------------------|---------|
| 2.1 | Covered / Partial | skill-4 creates Workday X.509 from Entra cert; thumbprint parity | skill-4 (Task 1) | `WD-CONN-102` (reuse) | **manual** (parity) |
| 2.2 | Gap / Gap | skill-4 scopes SAML policy + **activates pending changes**; SP-ID match; single-tenant pre-gate | skill-4 (Tasks 2, 4) | `WD-TENANT-001` (+ reuse `WD-CONN-010`) | **attest** |
| 2.3 | Gap / Gap | skill-4 registers API client with superset functional areas + Workday Owned Scope | skill-4 (Task 3) | `WD-API-CLIENT-001` | **attest** |
| 2.4 | Covered / Partial | skill-4 captures REST+SOAP URLs; skill-5 trims REST to `/api` | skill-4 (Task 3) + skill-5 | `WD-REST-001` (+ reuse `WD-CONN-012/101`, `WD-TENANT-001`) | **automated** (+ attest capture) |

### Skills referenced

| Skill | Role | Type for Step 2 |
|-------|------|-----------------|
| skill-4 `configure-workday-tenant` | Workday Administrator | **net-new** — owns all 4 Workday-tenant tasks |
| skill-5 `install-workday-extension-pack` | Environment Maker | REST `/api` trim at connection time (2.4) |
| skill-3 `provision-workday-entra-app` | App / Cloud App Admin | Entra-side signing cert add + activate (2.1 counterpart) |

### Checkpoints referenced

| Checkpoint | New / Reuse | Verification |
|------------|-------------|--------------|
| `WD-CONN-102` | reuse | **MANUAL** — Workday cert thumbprint matches Entra-activated cert |
| `WD-TENANT-001` | new | **attest** — config values captured, redirect / SP-ID match, auth policy scoped |
| `WD-API-CLIENT-001` | new | **attest** — API client registered + functional areas (no automated completeness on simplified) |
| `WD-REST-001` | new | **automated** — REST base URL present and trimmed to `/api` |
| `WD-CONN-010` | reuse | automated — Entra↔Workday federation alignment (single-tenant SAML pre-gate) |
| `WD-CONN-012`, `WD-CONN-101` | reuse | automated — connection binding completeness / health |

> **Automated vs manual for Step 2:** only `WD-REST-001` (+ reused `WD-CONN-010/012/101`) is automated.
> `WD-CONN-102`, `WD-TENANT-001`, and `WD-API-CLIENT-001` are MANUAL / attestation because the
> Workday tenant exposes no admin API the kit can query. Every attest/MANUAL row needs explicit
> operator acknowledgement + captured evidence and is **never** auto-completed.

## Open items & reduced coverage (Step 2)

1. **API client grant type — UNRESOLVED reconciliation (2.3).** The gap source specifies **JWT Bearer
   Grant** (golden set) while the ADK uses **SAML Bearer Grant**. The plan does **not** settle this;
   it must be decided before skill-4 Task 3 hardcodes a grant type. *(Action: confirm the correct
   grant type for the simplified V2 path.)*
2. **Functional-area completeness is not auto-detectable on simplified (2.3).** The legacy live SOAP
   probes (`WD-WF-001…017`) that caught a missing functional area are **skipped on simplified**;
   `WD-API-CLIENT-001` replaces them with **attestation**. A missing functional area will not fail a
   flightcheck — it surfaces only as runtime "Access Denied / blank cards." This is a deliberate
   coverage reduction vs. legacy.
3. **X.509 has no Workday API (2.1).** Workday-side validation is limited to the **MANUAL thumbprint
   parity** in `WD-CONN-102`; there is no direct Workday API to validate the uploaded public key.
4. **Pending-policy activation is not auto-detectable (2.2).** No Workday API exposes "pending vs
   activated" auth-policy state, so `WD-TENANT-001` relies on the operator attesting they ran
   **Activate All Pending Authentication Policy Changes**.
