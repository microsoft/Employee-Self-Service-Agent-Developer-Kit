# Workday Step 3: Final Verification

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "ENV_URL = ..." or "BOT_ID = ..." in chat.

Read `my/connect/workday/config.json` for WD_TENANT (tenant),
WD_BASE_URL (baseUrl), etc.
Read `my/config.json` for the agent details (dataverseEndpoint, agent.botId,
agent.name, agent.schemaName, agent.isManaged).

---

## 3.1 — Run comprehensive checks

**Message (do NOT wait for user response — continue immediately):**

Running final verification — testing all Workday API endpoints...

**End message.**

Run these 5 checks using the Workday MCP tools. Track pass/fail for each.

**Check 1: SOAP authentication**
Use `test_connection`.
Pass = returns worker data. Fail = error.

**Check 2: Get worker data**
Use `get_worker` with `employee_id="21001"` (or any known ID).
Pass = returns worker details. Fail = "not authorized" or error.

**Check 3: Time off balances**
Use `get_time_off_balance` with `employee_id="21001"`.
Pass = returns balance data (even if empty). Fail = "not authorized" or error.

**Check 4: Organizations**
Use `get_organization` with no arguments (lists orgs, count=5).
Pass = returns org data. Fail = "not authorized" or error.

**Check 5: RaaS WD_User_Context**
Use the `vscode_askQuestions` tool to ask for a test username (if not
already collected in step 2.6h):
```json
[
  {
    "header": "Test username",
    "question": "Enter a Workday username to verify the user context report:"
  }
]
```
Use `get_user_context` with the provided username.
Pass = returns Report_Entry with employee data. Fail = error.

---

## 3.2 — Report results

Build a results table from the 5 checks.

**If all 5 pass:**

Update `my/connect/workday/tasks.md` — change step 3 from
`- [ ]` to `- [x]`.

Update `my/connect/workday/config.json` — set `"status": "connected"`.

Update `my/config.json` — add or update a `connections` object:

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

If `connections` already exists (e.g., ServiceNow is there), merge — don't
overwrite existing entries.

**Message:**

✅ All checks passed!

| Check | Result |
|-------|--------|
| SOAP authentication | ✅ |
| Worker data (Get_Workers) | ✅ |
| Time off balances | ✅ |
| Organizations | ✅ |
| User context (RaaS) | ✅ |

| # | Task | Status |
|---|------|--------|
| 1 | Environment configured | ✅ |
| 2 | Admin setup complete | ✅ |
| 3 | Connection verified | ✅ |

**End message.**

Now go to section 3.3 (re-extract agent).

**If some checks fail:**

**Message:**

Verification results:

| Check | Result |
|-------|--------|
| SOAP authentication | {✅ or ❌} |
| Worker data (Get_Workers) | {✅ or ❌} |
| Time off balances | {✅ or ❌} |
| Organizations | {✅ or ❌} |
| User context (RaaS) | {✅ or ❌} |

{For each failed check, add a specific troubleshooting note:}

{If SOAP auth failed:}
- **SOAP auth:** Check ISU credentials and auth policy. The username
  must be in `user@domain@tenant` format.

{If Get_Workers failed:}
- **Worker data:** The ISU account needs **Worker data: Public worker
  reports** domain permission (Get access) on ISSG_WQL_COPILOT.

{If Time off failed:}
- **Time off:** The ISU account needs **Worker data: Time Off** domain
  permission. This may not have been configured — it's an optional
  permission for absence management scenarios.

{If Organizations failed:}
- **Organizations:** The ISU account needs organization domain
  permissions. This is optional — only needed if your agent uses
  org-based scenarios.

{If RaaS failed:}
- **User context:** Check report ownership, XML aliases, and that the
  report is enabled as a web service.

Fix the failed items and type **retry** to re-run verification.

**End message.**

Wait for the user. On retry, go back to section 3.1 and re-run all checks.

---

## 3.3 — Re-extract the agent

**Message (do NOT wait for user response — continue immediately):**

Re-extracting your agent to check for Workday extension pack components...

**End message.**

Read `my/config.json` to get the agent details. Set:
- ENV_URL = `dataverseEndpoint`
- BOT_ID = `agent.botId`
- BOT_NAME = `agent.name`
- SCHEMA_NAME = `agent.schemaName`
- IS_MANAGED = `agent.isManaged`

Run this command in the terminal:

If IS_MANAGED is true:
```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}" --managed
```

If IS_MANAGED is false:
```
python scripts/fetch_and_setup.py --url "{ENV_URL}" --bot-id "{BOT_ID}" --name "{BOT_NAME}" --schema "{SCHEMA_NAME}"
```

Wait for the script to complete.

---

## 3.4 — Install Workday Extension Pack

**Message:**

Now let's install the Workday extension pack in Copilot Studio.

1. Open your agent in [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Go to **Settings** → **Customize**
3. Select **Workday** and choose **Install**

You'll be prompted to set up connections. Show me what you see.

**End message.**

Wait for the user.

### 3.4a — Pre-check: Entra app role assignment

**Before the user creates connections**, verify the maker account is
assigned to the Workday Entra app (required when
`appRoleAssignmentRequired=true`).

If USES_ENTRA is true:

```
az ad sp show --id "{WD_ENTRA_APP_ID}" -o json | check appRoleAssignmentRequired
```

If `appRoleAssignmentRequired` is true:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/{SP_ID}/appRoleAssignedTo" --query "value[?contains(principalDisplayName,'{maker_name}')]"
```

If the maker is NOT assigned, get the maker's user ID:

```
az ad signed-in-user show --query id -o tsv
```

Save the output as MAKER_USER_ID.

Find the correct role ID:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/{SP_ID}/appRoles" --query "value[0].id" -o tsv
```

Then assign them:

```powershell
$body = @{principalId="{MAKER_USER_ID}"; resourceId="{SP_ID}"; appRoleId="{ROLE_ID}"} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-assign.json" -Encoding utf8
az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/{SP_ID}/appRoleAssignments" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-assign.json"
```

Do this silently — do not tell the user about app role assignments.

### 3.4b — Set up connections (Entra ID Integrated)

**If USES_ENTRA is true:**

Read `my/connect/workday/config.json` for the saved values.

The extension pack has 3 Workday SOAP connections + 1 Dataverse
connection:

| Connection Reference ID | Purpose | Account |
|------------------------|---------|---------|
| `new_sharedworkdaysoap_d6081` | Context Generic User (RaaS) | Maker SSO |
| `new_sharedworkdaysoap_0786a` | Generic User (API) | Maker SSO |
| `new_sharedworkdaysoap_ff0df` | OAuthUser (employee SSO) | Maker SSO |
| `msviess_sharedcommondataserviceforapps_92b66` | Dataverse | Maker SSO |

**IMPORTANT:** All 3 Workday connections use the SAME values and the
SAME sign-in account (the maker). Create each one separately even if
they all appear green after the first.

**Message:**

For each Workday SOAP connection, click the **...** and fill in
(fields in exact UI order):

| # | Field | Value |
|---|-------|-------|
| 1 | **Authentication type** | Microsoft Entra ID Integrated |
| 2 | **Microsoft Entra resource URL (Application ID URI)** | `{entraAppIdUri from config}` |
| 3 | **Workday OAuth token URL** | `{oauthTokenUrl from config}` |
| 4 | **Workday OAuth client ID** | `{oauthClientId from config}` |
| 5 | **SOAP base URL** | `{baseUrl from config}` |
| 6 | **Tenant name** | `{tenant from config}` |

Sign in with your Microsoft account when prompted. Do this for all 3
Workday connections separately.

The Dataverse connection should auto-connect with your account.

Once all 4 show green checkmarks, click **Next**.

**End message.**

### 3.4c — Set up connections (Basic auth)

**If USES_ENTRA is false:**

Check if the ISU passwords are still available from the step 2 session.
If not (e.g., session was interrupted), ask the user:

```json
[
  {
    "header": "ISU_WQL password",
    "question": "Paste the password for ISU_WQL_COPILOT (from step 2):"
  },
  {
    "header": "ISU_GENERIC password",
    "question": "Paste the password for ISU_GENERIC_COPILOT (from step 2):"
  }
]
```

**Message:**

For the Workday SOAP connections, click the **...** on each one.
Use **Basic** auth with these values (fields in exact UI order):

**Connection 1 (`d6081` — Context Generic User):**

| # | Field | Value |
|---|-------|-------|
| 1 | **Authentication type** | Basic |
| 2 | **SOAP base URI** | `{baseUrl from config}` |
| 3 | **Tenant name** | `{tenant from config}` |
| 4 | **Username** | `ISU_WQL_COPILOT@{tenant from config}` |
| 5 | **Password** | `{ISU_WQL_PASSWORD}` |

**Connection 2 (`0786a` — Generic User):**

| # | Field | Value |
|---|-------|-------|
| 1 | **Authentication type** | Basic |
| 2 | **SOAP base URI** | `{baseUrl from config}` |
| 3 | **Tenant name** | `{tenant from config}` |
| 4 | **Username** | `ISU_GENERIC_COPILOT@{tenant from config}` |
| 5 | **Password** | `{ISU_GENERIC_PASSWORD}` |

**Connection 3 (`ff0df` — OAuthUser):** same as Connection 1.

The Dataverse connection should auto-connect.

Once all 4 show green checkmarks, click **Next**.

**End message.**

### 3.4d — Environment variables

**Message:**

After installation, go to **Solutions** → find the **Workday**
solution. Update these environment variables:

| Variable | Value |
|----------|-------|
| **EmployeeContextRequestAccountName** | `ISU_WQL_COPILOT@{DOMAIN_NAME}` |
| **EmployeeContextRequestReportName** | `WD_User_Context` *(should be auto-filled)* |
| **EmployeeContextRequestReportInstanceName** | `Report2` *(should be auto-filled)* |

**End message.**

Wait for the user.

### 3.4e — Turn on cloud flows

**Message:**

Open the **Workday** solution → **Cloud flows** and verify both
workflows are **turned on**. If not, open each one and click
**Turn on**.

Type **done** when both flows are on.

**End message.**

Wait for the user.

### 3.4f — Add topic redirect

**Message:**

Last step — add the User Context redirect:

1. Open the topic **[Admin] - User Context - Setup** in your agent
2. Add a **Topic redirect** to **Workday System Get User Context**

Type **done** when complete.

**End message.**

Wait for the user.

---

## 3.5 — Final message

**Message:**

✅ Workday is fully connected and the extension pack is installed!

Here's what you can do next:

| Command | What it does |
|---------|-------------|
| `/create` | Create a new topic that uses Workday data |
| `/scan` | Check your agent for any errors |
| `/connect` | Connect another system (e.g., ServiceNow) |

**End message.**

Stop here. Do not continue.
