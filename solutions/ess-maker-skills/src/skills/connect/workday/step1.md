# Workday Step 1: Environment Setup & Entra SSO

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "BASE_URL = ..." or "TENANT = ..." in chat.

**CRITICAL RULES (from retro — read these before proceeding):**
- Entra SSO is MANDATORY for the Workday extension pack. Do NOT offer
  to skip it. The OAuthUser connection uses `runtimeSource: invoker`
  which requires employee identity via Entra SSO.
- NEVER say "check with your teammates" or "ask your admin." Use Azure
  CLI, Workday MCP, and Dataverse MCP to discover state yourself.
- NEVER accept "done" from the user without programmatic verification.
- Prefer MCP tools over PowerShell scripts. MCP calls are invisible to
  the user — PowerShell fills the terminal with noise they don't understand.

---

## 1.1 — Get the Workday URL

Use the `vscode_askQuestions` tool with ONE question:

```json
[
  {
    "header": "Workday URL",
    "question": "Paste the URL from your browser when you're logged into Workday (e.g. https://impl.workday.com/yourcompany/d/home.htmld)"
  }
]
```

**Parse the URL to extract tenant and SOAP base URL:**

The Workday web URL follows one of these patterns:
- `https://impl.workday.com/{tenant}/d/...` (implementation)
- `https://wd5.myworkday.com/{tenant}/d/...` (production)
- `https://{host}.workday.com/{tenant}/d/...` (other data centers)

Extract WD_TENANT from the first path segment after the domain.
Example: `https://impl.workday.com/contoso_impl/d/home.htmld`
→ WD_TENANT = `contoso_impl`

Derive the SOAP base URL and OAuth token host from the web host:
- `impl.workday.com` → SOAP: `https://wd2-impl-services1.workday.com/ccx/service` / Token host: `wd2-impl-services1.workday.com`
- `wd5.myworkday.com` → SOAP: `https://wd5-services1.myworkday.com/ccx/service` / Token host: `wd5-services1.myworkday.com`
- `{dcN}.myworkday.com` → SOAP: `https://{dcN}-services1.myworkday.com/ccx/service` / Token host: `{dcN}-services1.myworkday.com`

If the URL doesn't match any known pattern, fall back to asking:

```json
[
  {
    "header": "SOAP URL",
    "question": "I couldn't determine your Workday services URL from that link. What's the SOAP endpoint? (e.g. https://wd2-impl-services1.workday.com/ccx/service)"
  }
]
```

Save WD_TENANT, WD_BASE_URL, and WD_TOKEN_HOST.

---

## 1.2 — Install MCP server dependencies

Run in the terminal (do not show this to the user):

```
pip install -r src/mcp/workday/requirements.txt
```

If pip fails, try `python -m pip install -r src/mcp/workday/requirements.txt`.

---

## 1.3 — Save initial config

Write `my/connect/workday/config.json`:

```json
{
  "baseUrl": "{WD_BASE_URL}",
  "tenant": "{WD_TENANT}",
  "tokenHost": "{WD_TOKEN_HOST}",
  "status": "in-progress"
}
```

---

## 1.4 — Set up the Workday MCP server

Read `.vscode/mcp.json`. If it exists, parse it. If it doesn't exist,
start with an empty `{ "servers": {} }` object.

Add a `Workday` entry to the `servers` object. **Keep all existing
entries (like Dataverse, ServiceNow) intact.**

Also ensure the top-level `inputs` array contains the Workday input
definitions. If `inputs` doesn't exist yet, create it. If it exists,
append the Workday inputs (don't overwrite existing inputs).

Write the merged result back to `.vscode/mcp.json`. The Workday section
should look like this (merge with whatever is already there):

```json
{
  "inputs": [
    {
      "id": "workdayUser",
      "type": "promptString",
      "description": "Workday username (the one you use to sign in)",
      "password": false
    },
    {
      "id": "workdayPass",
      "type": "promptString",
      "description": "Workday password",
      "password": true
    }
  ],
  "servers": {
    "Workday": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "${workspaceFolder}/src/mcp/workday",
      "env": {
        "WORKDAY_BASE_URL": "{WD_BASE_URL}",
        "WORKDAY_TENANT": "{WD_TENANT}",
        "WORKDAY_USERNAME": "${input:workdayUser}@{WD_TENANT}",
        "WORKDAY_PASSWORD": "${input:workdayPass}"
      }
    }
  }
}
```

Replace `{WD_BASE_URL}` and `{WD_TENANT}` with the actual values from
step 1.1. These are not secrets so they go directly in the file.

The `WORKDAY_USERNAME` env var appends `@{WD_TENANT}` automatically so
the user only enters their normal username. The client derives the RaaS
username (without @tenant) and reuses the same password internally.

---

## 1.5 — Start the MCP server

**Message:**

Got it — your Workday tenant is **{WD_TENANT}**.

Now let's start the Workday connector:

1. Press **Ctrl+Shift+P** → type **MCP: List Servers** → select it
2. Find **Workday** in the list → click the **Start** button
3. VS Code will prompt for your **Workday username** and **password**
   at the top of the screen — just enter the same credentials you use
   to sign into Workday

Your credentials are only held in memory and never saved to disk. We'll
create dedicated service accounts later so you won't need yours long-term.

Type **done** when the server shows as Running.

**End message.**

Wait for the user.

---

## 1.6 — Verify connectivity

Use the Workday MCP `test_connection` tool.

**If the call succeeds** (returns worker data, not an error):
Proceed to 1.7.

**If "invalid username or password":**

**Message:**

Authentication failed. A few things to check:

- **Is your account a Workday admin?** The setup needs an account with
  administrative permissions. A regular employee account won't work.
- **Is the password correct?** Try signing into Workday in your browser
  to confirm.
- **Special characters in password?** Characters like `&`, `%`, `#` can
  cause issues. If your password contains these, try resetting it to one
  with only letters and numbers temporarily.

To retry: press **Ctrl+Shift+P** → **MCP: List Servers** → stop and
restart the **Workday** server.

Type **retry** when ready, or **back** to re-enter your info.

**End message.**

Wait for the user. If retry, re-run `test_connection`. If back, go to 1.1.

**If "not authorized":**

Connectivity works — the account just lacks some permissions. That's fine
for now. Proceed to 1.7.

**If any other error (connection refused, timeout, etc.):**

**Message:**

I couldn't reach Workday. A few things to check:

- **Are you connected to your corporate network/VPN?** Workday may
  require it.
- **Is the Workday URL correct?** You gave me `{WD_BASE_URL}` — if
  that doesn't look right, type **back** to start over.

Type **retry** to test again, or **back** to re-enter your Workday URL.

**End message.**

Wait for the user. If retry, re-run `test_connection`. If back, go to 1.1.

---

## 1.7 — Detect existing state

**Do all of the following silently — do NOT show the user what you're
checking. Just collect the results.**

### 1.7a — Check if Workday extension pack is already installed

Use the Dataverse MCP `read_query` tool:

```sql
SELECT TOP 5 connectionreferencelogicalname, connectionreferencedisplayname,
  statuscode FROM connectionreference
  WHERE connectorid LIKE '%workday%'
```

Save the results. If 3 Workday connection references exist (`d6081`,
`0786a`, `ff0df`), the extension pack is already installed. Set
EXTENSION_INSTALLED = true.

### 1.7b — Check for existing Entra SSO app

Read `src/skills/connect/azure/login.md` and follow it to ensure Azure
CLI is installed and the user is logged into the correct tenant. Save
the TENANT_ID.

Then run in the terminal (do not show to user):

```
az ad app list --query "[?identifierUris[?contains(@, 'workday.com/{WD_TENANT}')]].{displayName:displayName, appId:appId, id:id, identifierUris:identifierUris}" -o json --all
```

**If results found** with an identifierUri containing `workday.com/{WD_TENANT}`:
- Save appId as WD_ENTRA_APP_ID
- Save id as WD_ENTRA_APP_OBJECT_ID
- Save the matching identifierUri as WD_ENTRA_APP_ID_URI
  (typically `http://www.workday.com/{WD_TENANT}`)
- Set ENTRA_SSO_EXISTS = true

Also get the domain name:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/domains" --query "value[?isDefault==``true``].id | [0]" -o tsv
```

If that fails, fall back to:

```
az account show --query "tenantDefaultDomain" -o tsv
```

Save as DOMAIN_NAME.

**If no results found**: Set ENTRA_SSO_EXISTS = false. Still get
DOMAIN_NAME and TENANT_ID.

### 1.7c — Check for existing RaaS report owner

Try known ISU account patterns for the WD_User_Context report. Run
each silently via the Workday MCP `run_report` tool until one succeeds:

1. `ISU_WQL_COPILOT@{DOMAIN_NAME}` / `WD_User_Context`
2. `ISU_WQL_COPILOT@{WD_TENANT}` / `WD_User_Context`
3. `ISU_WQL_Copilot@{DOMAIN_NAME}` / `WD_User_Context`

Use a known test username like `lmcneil` in the params.

If any succeeds, save the working report owner as REPORT_OWNER and
set RAAS_REPORT_EXISTS = true.

### 1.7d — Derive the OAuth token URL

Build: `https://{WD_TOKEN_HOST}/ccx/oauth2/{WD_TENANT}/token`
Save as WD_OAUTH_TOKEN_URL.

### 1.7e — Update config with discovered state

Update `my/connect/workday/config.json` — merge all discovered values:

```json
{
  "baseUrl": "{WD_BASE_URL}",
  "tenant": "{WD_TENANT}",
  "tokenHost": "{WD_TOKEN_HOST}",
  "oauthTokenUrl": "{WD_OAUTH_TOKEN_URL}",
  "domainName": "{DOMAIN_NAME}",
  "tenantId": "{TENANT_ID}",
  "status": "in-progress",
  "extensionInstalled": true/false,
  "entraAppId": "{WD_ENTRA_APP_ID or null}",
  "entraAppIdUri": "{WD_ENTRA_APP_ID_URI or null}",
  "entraAppObjectId": "{WD_ENTRA_APP_OBJECT_ID or null}",
  "entraSSO": true/false,
  "reportOwner": "{REPORT_OWNER or null}",
  "raasReportExists": true/false
}
```

---

## 1.8 — Show status and proceed

Update `my/connect/workday/tasks.md` — change step 1 from
`- [ ]` to `- [x]`.

Build a status summary from the detected state.

**Message:**

✅ Connected to Workday tenant **{WD_TENANT}**.

Here's what I found in your environment:

| Check | Status |
|-------|--------|
| Workday connectivity | ✅ |
| Entra SSO app | {✅ if ENTRA_SSO_EXISTS else "⬜ needs setup"} |
| Extension pack installed | {✅ if EXTENSION_INSTALLED else "⬜ not yet"} |
| WD_User_Context report | {✅ if RAAS_REPORT_EXISTS else "⬜ needs setup"} |

{If ENTRA_SSO_EXISTS is false, add this line:}
The Workday extension requires Entra SSO — I'll set that up in the next step.

**End message.**

Now read `src/skills/connect/workday/step2.md` and follow it.
