# ESS FlightCheck — Remediation Guide

Per-checkpoint fix instructions for every FlightCheck failure. Organized
by category. Each entry includes the root cause, fix steps, and
verification.

---

## Prerequisites

### PRE-001: Microsoft 365 Copilot licenses
**Root cause:** No M365 Copilot SKU assigned to users in the tenant.
**Fix:**
1. Go to [Microsoft 365 admin center](https://admin.microsoft.com) → Billing → Licenses
2. Purchase or assign Microsoft 365 Copilot licenses
3. Assign to users who will use the ESS agent
**Verify:** Re-run `/flightcheck --scope prerequisites`

### PRE-002: Copilot Studio licenses
**Root cause:** Admins/makers don't have Copilot Studio or PVA licenses.
**Fix:**
1. Go to [Microsoft 365 admin center](https://admin.microsoft.com) → Billing → Licenses
2. Assign Copilot Studio licenses to Power Platform admins and environment makers
**Verify:** Re-run `/flightcheck --scope prerequisites`

### PRE-008: Global Admin role
**Root cause:** No user has the Global Administrator role activated.
**Fix:**
1. Go to [Entra admin center](https://entra.microsoft.com) → Roles and administrators
2. Assign Global Administrator to the deployment lead
**Verify:** Re-run `/flightcheck --scope prerequisites`

### PRE-009: Power Platform Admin role
**Root cause:** No user has the Power Platform Administrator role.
**Fix:**
1. Go to [Entra admin center](https://entra.microsoft.com) → Roles and administrators
2. Search "Power Platform Administrator" → Add assignment
**Verify:** Re-run `/flightcheck --scope prerequisites`

---

## Environment

### ENV-001: Environment not found
**Root cause:** Environment ID couldn't be derived, or user lacks admin access.
**Fix:**
1. Confirm the Dataverse URL in `.local/config.json` is correct
2. Ensure you have Environment Admin or PP Admin role
3. Re-run `/setup` if the URL is wrong
**Verify:** Re-run `/flightcheck --scope environment`

### ENV-002: Dataverse not provisioned
**Root cause:** Environment exists but Dataverse database wasn't enabled.
**Fix:**
1. Go to [Power Platform admin center](https://admin.powerplatform.microsoft.com)
2. Select environment → Add database
3. Wait for provisioning to complete
**Verify:** Re-run `/flightcheck --scope environment`

### ENV-008: No DLP policies
**Root cause:** No DLP policies are applied to the environment, or required
connectors may be blocked by existing policies.
**Fix:**
1. Go to PP Admin Center → Policies → Data policies
2. Review existing policies for this environment
3. Ensure Workday/ServiceNow/SAP connectors are in the "Business" group
**Verify:** Re-run `/flightcheck --scope environment`

---

## Authentication

### AUTH-001: Entra ID not accessible
**Root cause:** Graph API couldn't retrieve organization info.
**Fix:** Usually a permissions issue. Ensure you have Organization.Read.All.
**Verify:** Re-run `/flightcheck --scope authentication`

### AUTH-002: No Conditional Access policies
**Root cause:** No CA policies configured. Not a blocker but a security gap.
**Fix:**
1. Go to [Entra admin center](https://entra.microsoft.com) → Protection → Conditional Access
2. Create policies appropriate for your organization
**Note:** This is a warning, not a failure.

---

## Workday

### WD-ENV-001: EmployeeContextRequestAccountName not set
**Root cause:** The critical environment variable wasn't manually configured
after installing the Workday extension pack.
**Fix:**
1. Go to [Power Platform admin center](https://admin.powerplatform.microsoft.com) → Environments → [your env]
2. Open the environment → Solutions → Default Solution
3. Find `EmployeeContextRequestAccountName` → set to your ISU account name
4. Or use `/connect workday` to walk through the full setup
**Verify:** Re-run `/flightcheck --scope workday`

### WD-CONN-xxx: Connection in Error state
**Root cause:** Connection authentication expired or credentials rotated.
**Fix:**
1. Go to Power Platform → Connections
2. Find the errored connection → Edit → Re-authenticate
3. For OAuthUser connections: sign in with Entra SSO
4. For ISU connections: enter the ISU username and password
5. Or run `/connect workday` for guided re-setup
**Verify:** Re-run `/flightcheck --scope workday`

### WD-CONN-102: Entra↔Workday SAML federation certificate health
**Scope:** This check validates the X.509 signing certificate on the
federated Workday SAML enterprise app in Entra. It is **not** a check on
Power Platform connector secrets, ISU credentials, network connectivity, or
the Workday OAuth API Client's `client_secret` — for those see WD-CONN-001,
WD-CONN-101, WD-CONN-012, or WD-ENV-* instead.

**Where the cert sits relative to the ESS SOAP/REST runtime path.**
ESS user-context Workday calls execute through two Power Automate flows
(verified in `workspace/agents/{slug}/workflows/`):

  * `ESS HR Workday` — the SOAP orchestrator topics call via
    `WorkdaySystemGetCommonExecution`.
  * `WorkdayRESTExecution` — the REST equivalent for newer scenarios.

Both flows declare exactly one Workday connection:

```json
"shared_workdaysoap": {
  "connection": {
    "connectionReferenceLogicalName": "new_sharedworkdaysoap_ff0df"
  },
  "runtimeSource": "invoker"
}
```

`ff0df` is configured with Power Platform's **"Microsoft Entra ID
Integrated"** authentication type (see
`src/skills/connect/workday/step3.md` lines 155–166), not Basic auth.
"Microsoft Entra ID Integrated" authenticates the signed-in employee against
a **federated Workday enterprise app** in Entra
(Application ID URI: `http://www.workday.com/{WD_TENANT}`) — the same
enterprise app the connect skill provisions in
`src/skills/connect/workday/step2.md` lines 191–264. The X.509 signing
certificate WD-CONN-102 inspects lives on that same enterprise app as a
`keyCredential`. It is the signing key Entra uses to issue SAML assertions
for browser-based Workday SSO and is the most visible expiry-driven artifact
on the federation app that ESS's user-context SOAP/REST calls depend on.

**What expiry actually breaks (and what it doesn't):**

| Impact | Path | Why |
|---|---|---|
| **Will break** | Browser-based SAML SSO into Workday's web UI (employees clicking "Sign in with Microsoft" on workday.com) | Entra cannot sign SAML assertions Workday will accept |
| **May break — verify Workday API Client config** | Power Platform OAuth exchange on the `ff0df` connection used by `ESS HR Workday` / `WorkdayRESTExecution` | Depends on whether the Workday API Client backing the OAuth token endpoint validates the inbound JWT assertion against this same X.509 public key (some tenants) or against Entra's published JWKS (other tenants). Check Workday → View API Client → Authorized Public Key. |
| **Will not break** | SOAP calls over `d6081` (Context Generic) and `0786a` (Generic User) | HTTP Basic auth with ISU username + password; no certificate in the handshake |

On a **full / legacy install** (3 connection refs), the ISU SOAP calls keep
working when this cert expires, but the OAuthUser/`ff0df` path is at risk.
On a **simplified install** (1 connection ref, OAuthUser only — see WD-PKG-001),
`ff0df` is the entire Workday surface, so cert expiry combined with a
JWT-validating Workday API Client takes user-facing Workday topics offline.

**Root cause:** The X.509 signing certificate on the federated Workday SAML
enterprise app is missing, expired, expiring within 30 days, or out of sync
with the certificate uploaded to Workday's tenant security setup. Minimum
known impact is browser-based SAML SSO failure; OAuth exposure depends on
the Workday API Client's Authorized Public Key setting (see table above).
**Fix (FAILED — no cert or all expired):**
1. In Entra, open the federated Workday enterprise app → Single sign-on →
   SAML Signing Certificate → generate a new cert and download the
   `Certificate (Base64)`
2. In Workday, search `Edit Tenant Setup - Security` → open the matching
   `Service Provider ID` row in `SAML Identity Providers` → paste the new
   `Certificate (Base64)` into `X509 Certificate`
3. Set Entra's `preferredTokenSigningKeyThumbprint` (or the "Make
   certificate active" toggle) to the new thumbprint
**Fix (WARNING — expiring within 30 days or not yet valid):** Schedule a
rotation before `NotAfter`; same steps as above, but stage the new cert in
both systems first and only flip the active selection during a low-traffic
window.
**Fix (MANUAL — active cert is healthy on the Entra side):** Compare the
thumbprint surfaced in the result against the `X509 Certificate` thumbprint
on the matching `Service Provider ID` row in Workday. They must match
byte-for-byte (colon-separated uppercase hex); if they differ, re-upload the
active Entra `Certificate (Base64)` into Workday.
**Verify:** Re-run `/flightcheck --scope workday`

### WD-FLOW-xxx: Flow disabled
**Root cause:** A Workday Power Automate flow is turned off.
**Fix:**
1. Go to Power Automate → My Flows → find the flow
2. Turn it on
**Verify:** Re-run `/flightcheck --scope workday`

### WD-WF-xxx: Permission denied on workflow test
**Root cause:** The ISU account lacks the required Workday security domain.
**Fix:**
1. Identify the workflow name from the check result
2. Refer to the Workday security domain table in `validation-matrix.md`
3. Ask your Workday Administrator to grant the corresponding
   `Self-Service: [Domain] as Self` permission
4. Or run `/troubleshoot` for guided ISU debugging
**Verify:** Re-run `/flightcheck --scope workday`

### WD-SEC-003: Personal Data domain write permission (Employee as Self)
**Scope:** This check validates whether the resolved security group for
ESS personal-contact write topics (Update Email, Update Phone) has the
permissions needed to call `Maintain_Contact_Information` /
`Edit_Worker_Additional_Data` on Workday's Personal Data domain. It is
complementary to — not a replacement for — WD-WF-016 / WD-WF-017, which
only emit a coarse "Contact Information" remediation that misses the
intersection-group resolution problem this check exposes.

**Why both the runtime probe and MANUAL fallback exist.** The original
ticket proposed reading Workday's domain security policies directly via
`Get_Security_Groups` / `Get_Domain_Security_Policies` SOAP (or the REST
equivalents). Those admin operations are **not reachable** from outside
the Workday UI on a typical tenant (see
`tests/fixtures/cassettes/workday_config.yaml` — every captured
`Get_API_Clients` / `Get_Authentication_Policies` returned the SOAP
fault `Element not found=…_Request-urn:com.workday/bsvc`), and the WQL
alternative is blocked by the chicken-and-egg OAuth API Client
registration documented in `tests/fixtures/cassettes/INDEX.md` (WQL
also does not model domain-level permissions at all). The check
therefore probes the actual runtime write path on full / legacy
installs (where an ISU exists) and delegates to the operator on
simplified installs (where the write resolves against the signed-in
employee's own Workday identity and there is no ISU to probe from
FlightCheck).

**On a full / legacy install (Mode A — runtime probe):** the check
issues `Get_Change_Work_Contact_Information_Event_Request` via the same
SOAP envelope the existing 17-workflow tests use, then classifies the
response by faultstring:

| Workday response | WD-SEC-003 verdict |
|---|---|
| 2xx success, or fault containing `Worker not found` / `Invalid_ID` / `Invalid reference` | **PASSED** — Personal Data resolution succeeded; the test employee just has no open contact-change event |
| 400 with `Processing error occurred. The task submitted is not authorized` | **FAILED** — see fix steps below |
| 401 / `Invalid username or password` | **WARNING** — auth itself is broken; resolve WD-CONN-101 first |
| Anything else | **WARNING** with MANUAL fix steps (cannot guess permission state from an unknown fault) |

**On a simplified install (Mode B — MANUAL):** the check emits one
MANUAL row stating the kit cannot probe an ISU because the OBO/OAuthUser
path runs as the signed-in employee, and that the Workday-side
permission to verify is on each employee's own `Employee as Self`
intersection group.

**Root cause (FAILED):** The resolved security group for the configured
ISU has read access to other Workday domains (which is why
WD-WF-001..015 pass) but is missing **Modify** on the **Personal Data**
domain. Common cause: a tenant with multiple intersection groups
overlapping where the write permission resolves to a group that wasn't
granted Personal Data modify rights when the others were.
**Fix (FAILED):**
1. In Workday, search for and open `View Security Group`.
2. Look up `Employee as Self` (or the equivalent intersection group
   your tenant uses for self-service permissions).
3. From the group's related actions: `Security Group` → `Maintain
   Permissions for Security Group` → `Domain Security Policy
   Permissions` tab.
4. Grant **Modify** on the `Personal Data` domain (`Modify Self` for an
   intersection group like Employee as Self; `Modify All` if your
   tenant uses a regular group instead).
5. In Workday, search for and open `Edit Business Process Security
   Policy` → `Maintain Contact Information`. Confirm `Employee as Self`
   (or your equivalent) is listed as an Initiator. Repeat for `Edit
   Worker Additional Data` if your topics call that business process.
6. Search for and run `Activate Pending Security Policy Changes` — the
   edits above are pending until you activate them.
7. Re-run `/flightcheck --scope workday` to confirm WD-SEC-003 now
   passes.

**Fix (WARNING — auth fault):** Resolve WD-CONN-101 (ISU credential
health) first — see the connection re-bind path under `WD-CONN-xxx`
above. Once WD-CONN-101 is green, WD-SEC-003 will exercise the actual
permission resolution.

**Fix (MANUAL — simplified install or no ISU creds):** Follow the
Workday UI navigation in the check's `remediation` field (Steps 1–3:
verify Personal Data domain has the group with Modify, verify
Maintain Contact Information / Edit Worker Additional Data initiators,
activate any pending security policy changes). MANUAL items do not
fail readiness.
**Verify:** Re-run `/flightcheck --scope workday`

---

## Local Files

### CONFIG-007: No agent instructions
**Root cause:** `agent.mcs.yml` doesn't contain an instructions block.
**Fix:**
1. Open Copilot Studio → your agent → Settings → Instructions
2. Write comprehensive instructions (50+ words minimum)
3. Publish and re-extract with `/setup`
**Verify:** Re-run `/flightcheck --scope local`

### CONFIG-005: Too few starter prompts
**Root cause:** Agent has fewer than 3 conversation starters configured.
**Fix:**
1. Open Copilot Studio → your agent → Overview → Starter Prompts
2. Add 6-12 relevant prompts
3. Publish and re-extract
**Verify:** Re-run `/flightcheck --scope local`

### TOPIC-xxx: Required topic missing
**Root cause:** A required system or admin topic wasn't found in the
extracted files. It may exist under a different schema name or may not
have been extracted.
**Fix:**
1. Check Copilot Studio → Topics for the missing topic
2. If it exists, re-run `/setup` to re-extract
3. If missing, install the relevant extension pack
**Verify:** Re-run `/flightcheck --scope local`

---

## Publishing

All publishing checks (QA-xxx, PUB-xxx) are manual verification items.
They appear as "Not Configured" until you've completed each step and
can confirm it manually. These don't affect the automated pass/fail
verdict.

Refer to the [deployment checklist](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/deploy-overview-alm)
for detailed guidance on each item.
