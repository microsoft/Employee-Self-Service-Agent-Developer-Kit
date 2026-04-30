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
1. Confirm the Dataverse URL in `my/config.json` is correct
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
