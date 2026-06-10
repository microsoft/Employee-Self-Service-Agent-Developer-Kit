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

## Cloud Policies / Telemetry & Feedback

End-user feedback (thumbs up / thumbs down, optional verbatim, optional
screenshots/attachments) on Copilot responses is gated by two Microsoft 365
Cloud Policies in the **Microsoft 365 Apps admin center → Policy Management**.
When the "Allow feedback" policy is Disabled / Not Configured for the ESS
deployment group, end users simply see no feedback control — there is no error,
no failed request, no log entry — and the FlightCheck Trend Miner loses its
primary customer-signal source.

These two checkpoints are **manual** (`Status.Manual`): the Office Cloud Policy
Service exposes no supported API for reading effective per-group policy state,
so FlightCheck explains *why* each policy matters and *how* to confirm it in the
portal, then you verify it. They don't fail readiness.

### POL-FB-001: confirm "Allow feedback" is Enabled for the deployment group

- **Why verify** — Thumbs up / down feedback is the primary closed-loop quality
  signal (it feeds the Trend Miner, IcM correlation, and product-quality work).
  The control only appears when **"Allow users to send feedback to Microsoft
  about Microsoft 365 apps"** is Enabled for the deployment group; if it's
  Disabled / Not Configured the control disappears silently, so the tenant can
  opt out of the signal unnoticed.
- **How to verify** — Open the [Microsoft 365 Apps admin center](https://config.office.com/)
  → Policy Management → the policy configuration assigned to the security group
  that owns the ESS deployment → search its settings for "feedback" → confirm
  **"Allow users to send feedback to Microsoft about Microsoft 365 apps"** is
  set to **Enabled**. If no configuration targets that group, create or assign
  one with this policy Enabled.
- **Scope + confidence** — IT admin scope (Cloud Policy is admin-controlled).
  This is a manual confirmation — FlightCheck can't read OCPS state directly.
- **Still stuck?** — If the setting looks right but users still don't see the
  control, confirm the configuration is assigned to the correct group and isn't
  overridden by a higher-priority configuration.

### POL-FB-002: confirm "Allow attachments" is Enabled (fidelity)

- **Why verify** — Screenshots and attachments give the feedback signal its
  diagnostic fidelity. If **"Allow users to include screenshots and attachments
  when they submit feedback to Microsoft"** is Disabled while feedback is
  Enabled, feedback still flows but without diagnostic context — a lower-fidelity
  Trend Miner signal. This is a fidelity consideration, not a feedback blocker.
- **How to verify** — In the same policy configuration (where you enabled the
  feedback policy), confirm **"Allow users to include screenshots and
  attachments when they submit feedback to Microsoft"** is set to **Enabled**.

### Data-sharing notice (emitted verbatim)

Whenever feedback is (or should be) enabled, FlightCheck emits the following
notice. It is reproduced here **verbatim** so you can lift it directly into
your organization's privacy documentation and end-user training:

> End-user feedback collected from Copilot responses in this deployment —
> including any verbatim text, screenshots, and attachments the end user
> chooses to include — will be shared with Microsoft for product-quality and
> support improvement purposes. Confirm that your organization's privacy
> notice and end-user training cover this data flow before launch.
