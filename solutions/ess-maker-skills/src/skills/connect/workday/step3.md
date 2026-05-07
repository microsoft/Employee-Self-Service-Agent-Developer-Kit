# Workday Step 3: Extension Pack Install & Verification

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "ENV_URL = ..." or "BOT_ID = ..." in chat.

Read `my/connect/workday/config.json` for ALL values.
Read `my/config.json` for agent details (dataverseEndpoint, agent.botId,
agent.name, agent.schemaName, agent.isManaged).

**CRITICAL RULES (from retro):**
- The 3 Workday connections need DIFFERENT configurations:
  - `d6081` (Context Generic) = Basic auth with ISU_WQL
  - `0786a` (Generic User) = Basic auth with ISU_GENERIC
  - `ff0df` (OAuthUser) = **Microsoft Entra ID Integrated** (SSO)
  This is because `ff0df` uses `runtimeSource: invoker` in the flow —
  it authenticates AS the employee, not as a service account.
- Power Platform AUTO-FILLS connections 2 and 3 when you create #1.
  The user MUST create each connection separately. Warn explicitly.
- Name each connection distinctively (append the reference ID suffix)
  so they're distinguishable in dropdowns.
- The topic redirect MUST be pushed automatically via push.py — do NOT
  leave it as a manual portal step.
- After install, verify EVERYTHING programmatically: connection refs,
  flows, env vars, topic redirect. Do NOT accept "done" without checking.
- Environment variables are in the Default Solution, NOT a "Workday" solution.

---

## 3.1 — Check if extension pack is already installed

Read `my/connect/workday/config.json` for `extensionInstalled`.

If step 1 already detected connection references exist, the extension
pack is installed. Skip to section 3.5 (diagnose/fix existing install).

If not installed, proceed to 3.2.

---

## 3.2 — Re-extract the agent (pre-install baseline)

**Message (do NOT wait for user response — continue immediately):**

Preparing your agent for the Workday extension...

**End message.**

Read `my/config.json` to get agent details. Run:

```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}" {--managed if IS_MANAGED}
```

Wait for completion.

---

## 3.3 — Pre-check: Entra app role assignment

Before the user installs the extension, silently ensure their account
is assigned to the Workday Entra app (required for SSO connections).

Read WD_ENTRA_APP_ID from config. Get the service principal ID:

```
az ad sp list --filter "appId eq '{WD_ENTRA_APP_ID}'" --query "[0].id" -o tsv
```

Save as WD_ENTRA_SP_ID. Check `appRoleAssignmentRequired`:

```
az ad sp show --id {WD_ENTRA_SP_ID} --query "appRoleAssignmentRequired" -o tsv
```

If `true`, check if the current user is assigned:

```
az ad signed-in-user show --query id -o tsv
```

Save as MAKER_USER_ID. Check assignment:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}/appRoleAssignedTo" --query "value[?principalId=='{MAKER_USER_ID}']" -o json
```

If not assigned, get the default role and assign:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}/appRoles" --query "value[0].id" -o tsv
```

```powershell
$body = @{principalId="{MAKER_USER_ID}"; resourceId="{WD_ENTRA_SP_ID}"; appRoleId="{ROLE_ID}"} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-assign.json" -Encoding utf8
az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}/appRoleAssignments" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-assign.json"
```

Do this silently — do not tell the user about app role assignments.

---

## 3.4 — Guide extension pack installation

Read the ISU passwords from config (`isuWqlPassword`, `isuGenericPassword`).
Read `entraAppIdUri`, `oauthTokenUrl`, `oauthClientId`, `baseUrl`, `tenant`
from config.

**Message:**

Now let's install the Workday extension pack.

1. Open your agent in [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Go to **Settings** → **Customize**
3. Select **Workday** and choose **Install**

You'll be asked to set up 4 connections. **This is the most important
step — each connection needs different credentials.**

**⚠️ IMPORTANT: Power Platform will try to auto-fill connections 2–4
after you create the first one. Do NOT accept the auto-fill. Create
each connection separately using the exact values below.**

---

**Connection 1 — Context Generic User (`d6081`)**
Name it: `Workday SOAP - Context Generic (d6081)`

| Field | Value |
|-------|-------|
| **Authentication type** | Basic |
| **SOAP base URI** | `{baseUrl}` |
| **Tenant name** | `{tenant}` |
| **Username** | `ISU_WQL_COPILOT@{DOMAIN_NAME}@{tenant}` |
| **Password** | `{isuWqlPassword}` |

---

**Connection 2 — Generic User (`0786a`)**
Name it: `Workday SOAP - Generic User (0786a)`

| Field | Value |
|-------|-------|
| **Authentication type** | Basic |
| **SOAP base URI** | `{baseUrl}` |
| **Tenant name** | `{tenant}` |
| **Username** | `ISU_GENERIC_COPILOT@{DOMAIN_NAME}@{tenant}` |
| **Password** | `{isuGenericPassword}` |

---

**Connection 3 — OAuthUser SSO (`ff0df`)**
Name it: `Workday SOAP - OAuthUser SSO (ff0df)`

| Field | Value |
|-------|-------|
| **Authentication type** | **Microsoft Entra ID Integrated** |
| **Microsoft Entra resource URL (Application ID URI)** | `{entraAppIdUri}` |
| **Workday OAuth token URL** | `{oauthTokenUrl}` |
| **Workday OAuth client ID** | `{oauthClientId}` |
| **SOAP base URL** | `{baseUrl}` |
| **Tenant name** | `{tenant}` |

→ Sign in with your Microsoft account when prompted.

---

**Connection 4 — Dataverse**
Should auto-connect with your account. Just click to confirm.

---

Once all 4 show green checkmarks, click **Next** to complete the install.

Type **done** when the installation finishes.

**End message.**

Wait for the user.

---

## 3.5 — Post-install verification and fixes

**Run ALL of the following checks silently. Do NOT show the user what
you're checking — just collect results and fix what you can.**

### 3.5a — Verify connection references

Use the Dataverse MCP:

```sql
SELECT TOP 5 connectionreferencelogicalname,
  connectionreferencedisplayname, statuscode
  FROM connectionreference
  WHERE connectorid LIKE '%workday%'
```

Check that all 3 Workday connection references exist and have
`statuscode = 1` (Connected).

If any show `statuscode != 1`, note which ones are broken.

### 3.5b — Verify flows are enabled

Use the PowerApps Admin API (run in terminal, do not show to user).
Resolve the PowerShell binary off `PATH` so this works for every
contributor and on macOS / Linux. Try `pwsh` first; if it is not
installed, fall back to `powershell` (Windows-only); if neither is on
`PATH`, fall through to the Dataverse MCP block below.

```
pwsh -ExecutionPolicy Bypass -NoProfile -Command "Import-Module Microsoft.PowerApps.Administration.PowerShell -Force -WarningAction SilentlyContinue; Add-PowerAppsAccount; Get-AdminFlow -EnvironmentName '{ENV_ID}' | Where-Object { `$_.DisplayName -match 'workday|WD_|Workday' } | Select-Object DisplayName, @{n='State';e={`$_.Internal.properties.state}} | Format-Table"
```

If pwsh is not available, use the Dataverse MCP to check the `workflow`
table instead:

```sql
SELECT TOP 5 name, statecode FROM workflow
  WHERE name LIKE '%Workday%'
```

Both Workday flows must be in state "Started" / statecode 1 (Activated).

If any flow is disabled, tell the user:

**Message:**

The Workday flows need to be turned on:

1. In Copilot Studio → **Flows** (left nav)
2. Find the disabled Workday flow → open it → click **Turn on**

Type **done** when both flows are on.

**End message.**

### 3.5c — Verify environment variables

The environment variable `EmployeeContextRequestAccountName` must be
set to the ISU_WQL account. This is the one that's usually missed.

Try querying via Dataverse MCP:

```sql
SELECT TOP 5 schemaname, displayname, defaultvalue
  FROM environmentvariabledefinition
  WHERE displayname LIKE '%EmployeeContext%'
```

If this fails (table not available for reports), tell the user:

**Message:**

Verify the environment variable is set:

1. Go to **make.powerapps.com** → your environment
2. **Solutions** → **Default Solution** → search for **Environment variables**
3. Find **EmployeeContextRequestAccountName**
4. Set the value to: `ISU_WQL_COPILOT@{DOMAIN_NAME}`

The other two variables (`EmployeeContextRequestReportName` = `WD_User_Context`,
`EmployeeContextRequestReportInstanceName` = `Report2`) should be auto-filled.

Type **done** when set.

**End message.**

Wait for the user.

### 3.5d — Wire topic redirect (AUTOMATIC — do not ask user)

Read the agent's `user-context-setup.mcs.yml` file:

```
my/agents/{slug}/topics/user-context-setup.mcs.yml
```

Check if it already contains a `BeginDialog` action pointing to
`WorkdaySystemGetUserContext`.

**If the redirect already exists:** Good, skip this step.

**If the file is empty (just `OnRedirect` with no actions):**

Before making any change to the agent, surface the consent to the
user. This step writes to their live agent and is hard to undo without
the checkpoint.

**Message:**

Wiring the **User Context** topic to call the Workday flow on every
conversation. Without this, Workday topics fail with "This feature
isn't available yet."

I'll save a checkpoint named `Add User Context redirect to Workday`
first so you can roll back if anything looks off.

**End message.**

Create a checkpoint:
```
python scripts/checkpoint.py "Add User Context redirect to Workday"
```

Replace the file content with:

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  priority: 0
  actions:
    - kind: BeginDialog
      id: bfT9Kx
      displayName: Redirect to Workday System Get User Context
      dialog: msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetUserContext
```

Push the change:
```
python scripts/push.py --yes
```

This wires the user context topic to call the Workday flow on every
conversation. Without this, every Workday topic fails with "This
feature isn't available yet."

### 3.5e — Re-extract agent (post-install)

Run the fetch_and_setup script again to capture the new extension pack
components:

```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}" {--managed if IS_MANAGED}
```

### 3.5f — Show verification results

Build a results table from all checks.

**Message:**

Post-install verification:

| Check | Status |
|-------|--------|
| Connection: Context Generic (`d6081`) | {✅ or ❌} |
| Connection: Generic User (`0786a`) | {✅ or ❌} |
| Connection: OAuthUser SSO (`ff0df`) | {✅ or ❌} |
| Flow: ESS HR Workday Get User Context | {✅ Enabled or ❌ Disabled} |
| Flow: ESS HR Workday | {✅ Enabled or ❌ Disabled} |
| Environment variable: AccountName | {✅ Set or ⚠️ Verify manually} |
| Topic redirect: User Context → Workday | {✅ Pushed or ❌ Missing} |

{If any ❌ items, show specific fix instructions for each.}

**End message.**

If all checks pass, proceed to 3.6.

If any connection references failed, the user needs to update them.
Show the specific connection creation instructions from section 3.4
for the failed connection(s) only.

---

## 3.6 — End-to-end test

**Message:**

Let's test the full integration. In Copilot Studio:

1. Click **Test** (top right) → **New test session**
2. Type: **What is my employee ID?**

This tests the User Context flow — if it returns your employee ID,
the Workday integration is working.

Tell me what the agent responds with.

**End message.**

Wait for the user.

**If employee ID returned successfully:**

**Message:**

✅ Workday integration is working!

Now try: **What is my base salary?**

When the agent asks to "Connect to continue" → select the **Workday
SOAP** connection with the **ff0df** suffix and click **Allow**. This
is the SSO connection that authenticates as you.

**End message.**

Wait for the user.

**If "This feature isn't available yet":**

The topic redirect wasn't wired. Check section 3.5d — was the push
successful? Re-read the topic file and verify the BeginDialog action
exists. If not, retry the push.

**If "Error code: 400" or "invalid username or password":**

A connection reference has wrong credentials. Use the Dataverse MCP
to check connection statuses:

```sql
SELECT connectionreferencelogicalname, connectionreferencedisplayname,
  statuscode FROM connectionreference
  WHERE connectorid LIKE '%workday%'
```

Guide the user to fix the specific broken connection using the values
from section 3.4.

**If "not authorized":**

The ISU account lacks domain permissions. Go back to step2.md Task 5
and verify the full permission list.

---

## 3.7 — Complete

Update `my/connect/workday/tasks.md` — change step 3 to `- [x]`.

Update `my/connect/workday/config.json` — set `"status": "connected"`.

Update `my/config.json` — add or merge:

```json
{
  "connections": {
    "Workday": {
      "tenant": "{WD_TENANT}",
      "baseUrl": "{WD_BASE_URL}",
      "connectedAt": "{current ISO date}"
    }
  }
}
```

**Message:**

✅ Workday is fully connected!

Here's what you can do next:

| Command | What it does |
|---------|-------------|
| `/flightcheck` | Verify Workday connections, flows, and permissions are healthy |
| `/create` | Create a new topic that uses Workday data |
| `/scan` | Check your agent for any errors |
| `/connect` | Connect another system (e.g., ServiceNow) |

**End message.**

Stop here. Do not continue.
