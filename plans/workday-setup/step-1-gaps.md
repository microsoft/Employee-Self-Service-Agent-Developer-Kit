# Step 1 Gaps — Infrastructure Readiness & Microsoft Entra ID Setup

Gap analysis and resolution for **Step 1 (1.1–1.5)** of the simplified Workday setup. Part of
[Workday Setup](./README.md). Each gap is closed by a **two-part fix**: a **skill** performs the
configuration action, and a **flightcheck** verifies it held.

**Source plans:** [`master-checklist`](./master-checklist.md) (canonical checkpoint registry),
[`skill-1-provision-power-platform-environment`](./skill-1-provision-power-platform-environment.md),
[`skill-2-install-ess`](./skill-2-install-ess.md),
[`skill-3-provision-workday-entra-app`](./skill-3-provision-workday-entra-app.md),
[`skill-5-install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md).

> **The fix pattern:** the **skill is the fix** (it performs the setup); the **flightcheck is the
> proof** (it verifies the fix held). A flightcheck alone can only *detect* a gap — the skill is
> what actually closes it.

---

## Step 1.1 — Verify Foundational Prerequisites

**The gap**
- *Skill side (PARTIAL):* the current flow gates on the base ESS deployment via `.local/config.json`
  and tests Workday connectivity (`connect/workday/step1.md:188-238`), but never makes "base ESS
  deployed" an owned step, and does not verify Entra SSO works for normal Workday web login.
  Open reconciliation: the Okta/Ping stance conflicts with ADK debug guidance for Okta-in-chain.
- *Flightcheck side (PARTIAL):* `prerequisites.py` covers licenses/roles/capacity and `WD-PKG-001`
  checks the extension-pack presence, but there is no ESS-solution-presence check and no live SSO probe.

**Skill (the fix)**
- **skill-1 `provision-power-platform-environment`** (net-new) — provisions environment + Dataverse +
  Copilot Studio capacity.
- **skill-2 `install-ess`** (net-new) — installs the base ESS agent from AppSource, turning the
  implicit `config.json` gate into an explicit, owned prerequisite step.

**Flightcheck (the proof)**
- **`ESS-SOLN-001`** (new, automated) — Dataverse query confirms `msdyn_copilotforemployeeselfservice*`
  is installed → *"agent verifies the ESS solution exists."*
- **`ENV-001` / `ENV-002`** (reuse) — environment + Dataverse provisioned.
- **`ENV-CAPACITY-001`** (new) — Copilot Studio capacity.
- **`PRE-001` / `PRE-002` / `PRE-003` / `PRE-008` / `PRE-009`** (reuse) — licenses + roles.

**Not closed (intentional)**
- **Live SSO web-login probe** — out of scope. SSO is covered as *setup* (`WD-CONN-010` federation
  attestation + `WD-CONN-102` cert health), not a runtime login test.
- **Okta/Ping reconciliation** — handled as an Entra-only **policy stance** (third-party IdP not
  directly supported; Entra-authenticated/federated only), not a checkpoint.

---

## Step 1.2 — Network Security & Firewall Allowlisting

**The gap (CONTESTED / NONE)**
- Setup has no coverage, and applicability is *disputed*: simplified S2S traffic may originate from a
  Microsoft backend where customer firewall control has no impact. No flightcheck coverage; the debug
  doc lists network allowlisting as a manual config step but its applicability to the simplified S2S
  path is unresolved.

**Skill (the fix)**
- **skill-5 `install-workday-extension-pack`** adds an explicit **InfoSec/IT attestation row** for
  firewall allowlisting (REST + SOAP) and **gates its own functional connection check** on it — so it
  reports **"network-unreachable" vs "config-invalid" distinctly** (a firewall miss is not
  misdiagnosed as a config error).

**Flightcheck (the proof)**
- **`WD-NET-001`** (new, **MANUAL / attest**) — defaults to an InfoSec attestation with captured
  evidence, because a local CLI probe only proves the *dev machine* (not the managed-connector
  outbound IPs) can reach Workday. Covers **both REST + SOAP** → directly addresses the "allowlists
  REST but forgets SOAP" failure mode (a single OAuth connection uses both endpoints).

**Status:** closed *as an attestation*. The contested applicability is **acknowledged** (attest, not
auto-probe; an in-environment connector probe is noted only as a later enhancement), not definitively
resolved.

---

## Step 1.3 — Configure "Expose an API" (`user_impersonation`)

**The gap (GAP / GAP)**
- *Skill:* `app-registration.md` *can* expose `user_impersonation`, but the Workday flow only invokes
  the pre-authorization sub-step, not the scope-exposure sub-step — so scope exposure is **assumed,
  not performed**.
- *Flightcheck:* no checkpoint verifies the `user_impersonation` scope is exposed.

**Skill (the fix)**
- **skill-3 `provision-workday-entra-app`** (*Core — connector configuration*) now **explicitly
  performs** exposing the `user_impersonation` scope (`api.oauth2PermissionScopes`), Graph-first with
  a portal fallback. *Extends* `app-registration.md` / `step2.md`.

**Flightcheck (the proof)**
- **`WD-ENTRA-SCOPE-001`** (new, automated — Graph) verifies the scope is exposed →
  *"Application ID URI documented and `user_impersonation` saved and visible."*

---

## Step 1.4 — Authorize the Workday Connector (`4e4707ca`)

**The gap**
- *Skill side (COVERED):* `step2.md` already verifies pre-auth and adds
  `4e4707ca-5f53-46a6-a819-f7765446e6ff` to `api.preAuthorizedApplications`.
- *Flightcheck side (GAP / debug):* no checkpoint validates the connector **stays** pre-authorized —
  a missing pre-auth silently breaks token exchange.

**Skill (the fix)**
- **Minimal — a port, not new behavior.** skill-3 carries the existing pre-auth logic forward and
  **parameterizes the connector via the shared helper** (Workday → `4e4707ca`,
  ServiceNow → `c26b24aa`) and **corrects the misleading comment**. De-dup + accuracy only; no
  behavior change for the ServiceNow path.

**Flightcheck (the proof)**
- **`WD-ENTRA-SCOPE-001`** (new) — the same composite check verifies `4e4707ca` appears in
  `preAuthorizedApplications` mapped to `user_impersonation`. This is the only genuinely new effort
  for 1.4 (the skill side was already done).

---

## Step 1.5 — Grant Microsoft Graph API Permissions + Admin Consent

**The gap (GAP / GAP)**
- *Skill:* no `openid` / `profile` / `User.Read` delegated-permission grant **or** admin-consent step
  exists in the Workday connect flow.
- *Flightcheck:* no checkpoint validates delegated Graph permissions or admin consent.

**Skill (the fix)**
- **skill-3** **adds** the three Graph delegated permissions (`requiredResourceAccess`) **and grants
  admin consent via Graph** (`oauth2PermissionGrant`). If the caller lacks a consent-capable role
  (Application Administrator / Cloud Application Administrator / Privileged Role Administrator /
  Global Administrator), it emits a **named-role error and escalates to manual consent** — directly
  handling the "customer lacks Global Admin to grant consent" failure mode.

**Flightcheck (the proof)**
- **`WD-ENTRA-SCOPE-001`** (new) verifies the three Graph permissions are present.
- **`WD-ENTRA-CONSENT-001`** (new, **prog→manual**) verifies admin consent was granted →
  *"green checkmarks under Status for all three."* Attempt programmatically; escalate to a manual
  portal row if the identity lacks consent rights.

---

## Summary

| Step | Gap type | Skill fix (action) | Skill work | Flightcheck (proof) | FC type |
|------|----------|--------------------|------------|---------------------|---------|
| 1.1 | Partial / Partial | skill-1 + skill-2 deploy env + base ESS | **net-new** | `ESS-SOLN-001`, `ENV-CAPACITY-001` (+ reuse `ENV-001/002`, `PRE-*`) | automated |
| 1.2 | Contested / None | skill-5 attestation row + unreachable-vs-misconfig | new logic | `WD-NET-001` | manual / attest |
| 1.3 | Gap / Gap | skill-3 *performs* scope exposure | **extend** | `WD-ENTRA-SCOPE-001` | automated |
| 1.4 | Covered / Gap | skill-3 ports + parameterizes pre-auth | **port only** | `WD-ENTRA-SCOPE-001` | automated |
| 1.5 | Gap / Gap | skill-3 *adds* Graph perms + consent | **new steps** | `WD-ENTRA-SCOPE-001` + `WD-ENTRA-CONSENT-001` | automated → prog→manual |

### Skills referenced

| Skill | Role | Type for Step 1 |
|-------|------|-----------------|
| skill-1 `provision-power-platform-environment` | Power Platform Administrator | net-new |
| skill-2 `install-ess` | Environment Maker | net-new |
| skill-3 `provision-workday-entra-app` | App / Cloud App Admin (consent-capable) | extend / new steps |
| skill-5 `install-workday-extension-pack` | Environment Maker (+ InfoSec/IT) | new attestation logic |

### Checkpoints referenced

| Checkpoint | New / Reuse | Verification |
|------------|-------------|--------------|
| `ESS-SOLN-001` | new | automated (Dataverse) |
| `ENV-CAPACITY-001` | new | automated (attest fallback) |
| `WD-ENTRA-SCOPE-001` | new | automated (Graph) — composite: scope + pre-auth + Graph perms |
| `WD-ENTRA-CONSENT-001` | new | automated → prog→manual (Graph) |
| `WD-NET-001` | new | manual / attest |
| `ENV-001`, `ENV-002` | reuse | automated |
| `PRE-001/002/003/008/009` | reuse | automated |
| `WD-CONN-010`, `WD-CONN-102` | reuse | federation / cert (SSO covered as setup, not live probe) |

> **Composite-check note:** `WD-ENTRA-SCOPE-001` bundles three concerns (scope exposed + `4e4707ca`
> pre-authorized + Graph perms), so it closes 1.3, 1.4, and the perms half of 1.5 in one row. This is
> convenient but is in slight tension with the flightcheck "one check, one concern" rule — if 1.3 /
> 1.4 / 1.5 should fail independently in the report, split it into three IDs.

## Out of scope (Step 1)

- **Live Workday-web-login SSO probe** (Step 1.1) — SSO is validated as setup via `WD-CONN-010` +
  `WD-CONN-102`, not a runtime login test.
- **Okta/Ping-in-chain reconciliation** (Step 1.1) — Entra-only policy stance, not a checkpoint.
