# Workday Step 2: Admin Setup

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "DOMAIN_NAME = ..." or "TENANT_NAME = ..." in chat.

Read `my/connect/workday/config.json` for WD_BASE_URL (baseUrl) and
WD_TENANT (tenant).

**MCP reconnect:** If any Workday MCP tool call fails with a connection
error (timeout, server not running, etc.), check if the MCP server is
still running. If not, restart it by re-running the MCP setup from
step1.md (pip install + server start). Then retry the failed call.
Do NOT ask the user about MCP internals — handle reconnection silently.

---

## 2.0 — Pre-flight: Verify what's already configured

**CRITICAL PRINCIPLE: Verify before acting.** Many Workday tenants are
shared or partially configured. Before asking the user to create or
configure anything, run API checks to see what already works. Only
fall back to portal instructions when verification fails.

### 2.0a — Run verification sweep

Run all of these checks silently (do NOT show them to the user). Track
pass/fail for each. Do NOT stop on failure — run all checks.

| Check | Tool | Pass condition |
|-------|------|---------------|
| SOAP auth | `test_connection` | Returns worker data |
| Worker data | `get_worker` with `employee_id="21001"` | Returns worker details |
| Time off | `get_time_off_balance` with `employee_id="21001"` | Returns data (even if empty) |
| Organizations | `get_organization` | Returns org data |
| RaaS report | `run_report` with `report_owner="ISU_WQL_COPILOT@{DOMAIN_NAME}"` `report_name="WD_User_Context"` `params={"User_Name":"lmcneil"}` | Returns Report_Entry |

If the RaaS report fails with the first owner, try these alternative
owners before giving up:
- `ISU_WQL_COPILOT@{DOMAIN_NAME}`
- `ISU_WQL_COPILOT@esseval.onmicrosoft.com`
- `ISU_WQL_Copilot@{DOMAIN_NAME}` (case variation)

Save the results. They determine which tasks can be skipped.

### 2.0b — Ask authentication method

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Entra SSO",
    "question": "Do your employees sign into Workday with their Microsoft work account (Entra ID / Azure AD)?",
    "options": [
      { "label": "Yes", "description": "Employees use their Microsoft account to sign in" },
      { "label": "No", "description": "Employees sign in with a Workday username and password" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

Save the Entra answer as USES_ENTRA (true if "Yes", false otherwise).
If "I'm not sure", default to true — the Entra flow will detect if
it's not configured and offer to skip.

Update `my/connect/workday/config.json` — add:
```json
{
  "usesEntra": true/false
}
```

### 2.0c — Show task table with pre-verified results

Build the task table showing which tasks are already done based on
the verification sweep:

- **SOAP auth passed** → Tasks 2, 3 are likely done (ISU + auth policy)
- **Worker data + time off passed** → Task 5 is likely done (permissions)
- **RaaS report passed** → Task 6 is done (report exists)

**Message:**

There are 6 admin tasks to set up. I'll verify what's already
configured and skip anything that's working.

| # | Admin Task | Status |
|---|-----------|--------|
| 1 | Tenant security config | {✅ if SOAP passed, else ⬜} *(Entra only)* |
| 2 | ISU accounts | {✅ if SOAP passed, else ⬜} |
| 3 | Authentication policies | {✅ if SOAP passed, else ⬜} |
| 4 | API client registration | ⬜ *(always needed for new environment)* |
| 5 | Domain permissions | {✅ if worker+timeoff passed, else ⬜} |
| 6 | WD_User_Context report | {✅ if RaaS passed, else ⬜} |

Let's go.

**End message.**

If USES_ENTRA is true, go to Task 1.
If USES_ENTRA is false, skip Task 1 and go directly to Task 2.

---

## Task 1: Entra + Workday Tenant Security (Entra only)

**Skip this entire task if USES_ENTRA is false.**

### 2.1-pre — Check if SAML is already configured in Workday

**Before creating anything in Entra**, ask the user to check the
Workday side first.

**Message:**

Before I set up anything in Entra, I need to check if your Workday
tenant already has SAML configured.

In Workday, search for **`Edit Tenant Setup - Security`** and scroll
down to the **SAML Identity Providers** section.

Do you see any identity providers listed that use your Entra tenant?
Look for an Issuer that starts with `https://sts.windows.net/`.

1. **Yes, I see one** — tell me its name and Issuer URL
2. **No, none exist** — we'll create one

**End message.**

Wait for the user.

**If the user sees an existing SAML IdP with their Entra tenant:**

Extract the tenant ID from the Issuer URL (the GUID between
`sts.windows.net/` and `/`). Save as TENANT_ID.

Now find the matching Entra app by searching for apps with the
Workday identifier URI:

```
az ad app list --query "[?identifierUris[?contains(@, 'workday.com/{WD_TENANT}')]].{displayName:displayName, appId:appId, id:id, identifierUris:identifierUris}" -o json --all
```

If found, save the app details:
- `appId` → WD_ENTRA_APP_ID
- `id` → WD_ENTRA_APP_OBJECT_ID
- `identifierUris[0]` → WD_ENTRA_APP_ID_URI

Verify the Power Platform Workday connector (`4e4707ca-5f53-46a6-a819-f7765446e6ff`)
is pre-authorized:

```
az ad app show --id {WD_ENTRA_APP_OBJECT_ID} --query "api.preAuthorizedApplications" -o json
```

If the connector is already pre-authorized, **skip the rest of Task 1**.
Update config and go directly to Task 2.

If the connector is NOT pre-authorized, run section 2.1e to add it,
then skip to Task 2.

**If the user says no SAML IdP exists:** proceed to 2.1a below.

### 2.1a — Log into Azure CLI

Read `src/skills/connect/azure/login.md` and follow it to log the user
into Azure CLI and get TENANT_ID.

After login, retrieve the domain name. First try:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/domains" --query "value[?isDefault==``true``].id | [0]" -o tsv
```

If that fails, fall back to:

```
az account show --query "tenantDefaultDomain" -o tsv
```

Save the output as DOMAIN_NAME (e.g., `contoso.onmicrosoft.com`).

Update `my/connect/workday/config.json` — add `"domainName": "{DOMAIN_NAME}"`.

### 2.1b — Create the Workday enterprise app

**Message (do NOT wait for user response — continue immediately):**

Setting up Workday SSO in your Entra tenant...

**End message.**

First, check if a Workday app already exists:

```
az ad sp list --display-name "Workday" --query "[].{name:displayName, appId:appId, id:id}" -o json
```

**If results are found:** Show the user the list and ask which one is
their Workday SSO app. Save the `appId` as WD_ENTRA_APP_ID and the
`id` as WD_ENTRA_SP_ID. Skip to 2.1d.

**If no results:** Create the app from the Workday gallery template.

Find the Workday template ID:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/applicationTemplates?\$filter=displayName%20eq%20'Workday'" --query "value[0].id" -o tsv
```

Save the output as TEMPLATE_ID.

Instantiate the template:

```powershell
$body = @{displayName="Workday (ESS Copilot)"} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-wd-template.json" -Encoding utf8
az rest --method POST --url "https://graph.microsoft.com/v1.0/applicationTemplates/{TEMPLATE_ID}/instantiate" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-template.json"
```

From the response, extract:
- `application.appId` → save as WD_ENTRA_APP_ID
- `application.id` → save as WD_ENTRA_APP_OBJECT_ID
- `servicePrincipal.id` → save as WD_ENTRA_SP_ID

**If the command fails with permission errors:**

**Message:**

I don't have permission to create enterprise applications in your Entra
tenant. This requires the **Application Administrator** or **Cloud
Application Administrator** role.

Ask your IT admin to grant this role, or have them create a Workday
enterprise app in Entra for you. Then run `/connect workday` again.

**End message.**

Stop here.

### 2.1c — Configure SAML SSO

Set preferred SSO mode to SAML:

```powershell
$body = @{preferredSingleSignOnMode="saml"} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-wd-sso.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-sso.json"
```

Configure the SAML identifiers and reply URLs:

```powershell
$body = @{
  identifierUris=@("http://www.workday.com/{WD_TENANT}")
  web=@{
    redirectUris=@(
      "https://impl.workday.com/{WD_TENANT}/login-saml.htmld"
    )
  }
} | ConvertTo-Json -Depth 3
$body | Out-File "$env:TEMP\ess-wd-saml.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{WD_ENTRA_APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-saml.json"
```

Replace `{WD_TENANT}` with the actual tenant name from config. If the
base URL host is not `impl.workday.com`, adjust the redirect URI to
match (e.g., `wd5.myworkday.com`).

### 2.1d — Create signing certificate

```powershell
$body = @{
  displayName="CN=ESS Copilot Signing Cert"
  endDateTime="2028-01-01T00:00:00Z"
} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-wd-cert.json" -Encoding utf8
az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}/addTokenSigningCertificate" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-cert.json"
```

From the response, extract the `customKeyIdentifier` (thumbprint).

Then download the Base64 certificate:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}" --query "keyCredentials[0].key" -o tsv
```

Save the output as ENTRA_CERTIFICATE_BASE64.

If the certificate already exists (e.g., from a previous run), skip
creation and just download the existing one.

### 2.1e — Pre-authorize the Power Platform connector

The Power Platform Workday connector app ID is:
`4e4707ca-5f53-46a6-a819-f7765446e6ff`

Follow the same pattern as `src/skills/connect/azure/app-registration.md`
section B.5 — use `az rest` to PATCH the application's
`api.preAuthorizedApplications` array, adding the Power Platform connector.

If it fails with permission errors, fall back to manual instructions
(same pattern as the ServiceNow flow).

### 2.1f — Build the values for Workday portal

Compute the values the user needs:

- ENTRA_IDENTIFIER = `https://sts.windows.net/{TENANT_ID}/`
- ENTRA_LOGIN_URL = `https://login.microsoftonline.com/{TENANT_ID}/saml2`
- SERVICE_PROVIDER_ID = `http://www.workday.com/{WD_TENANT}`

### 2.1g — Guide Workday portal configuration

**Message:**

✅ Entra setup is done. Now I need you to configure the Workday side —
this is the one part that has no API.

In Workday, search for **`Edit Tenant Setup - Security`** and make
these changes:

**1. Enable OAuth 2.0:**
- Find **OAuth 2.0 Clients Enabled** → set to **Yes**

**2. Enable SAML Authentication:**
- Find **Enable SAML Authentication** → set to **Yes**

**3. Configure the SAML Identity Provider** — paste these exact values:

| Field | Value |
|---|---|
| **Identity provider name** | `Microsoft Entra ID` |
| **Issuer** | `{ENTRA_IDENTIFIER}` |
| **X509 Certificate** | *(see below)* |
| **SP initiated** | **Yes** |
| **Service Provider ID** | `{SERVICE_PROVIDER_ID}` |
| **Sign SP-initiated Request** | **No** |
| **Do Not Deflate SP-initiated Request** | **Yes** |
| **Always require IdP Authentication** | **No** |
| **IdP SSO Service URL** | `{ENTRA_LOGIN_URL}` |

**For the X.509 certificate:**
1. Search for **`Create x509 Public Key`** in Workday
2. Name it `Microsoft_Entra_Signing_Cert`
3. Paste this certificate:

```
{ENTRA_CERTIFICATE_BASE64}
```

4. Click **OK**, then select it in the SAML Identity Provider config

Click **OK** to save the tenant security settings.

Type **done** when complete.

**End message.**

Wait for the user.

Update `my/connect/workday/config.json` — add:
```json
{
  "usesEntra": true,
  "entraAppId": "{WD_ENTRA_APP_ID}",
  "entraAppIdUri": "http://www.workday.com/{WD_TENANT}",
  "tenantId": "{TENANT_ID}"
}
```

**Also save the entraAppIdUri when an existing app is found in 2.1-pre.**
The identifier URI is typically `http://www.workday.com/{WD_TENANT}` or
whatever was found in `identifierUris[0]` from the Entra app lookup.

---

## Task 2: ISU Accounts and Security Groups

**If the pre-flight SOAP auth check passed**, the ISU accounts and
security groups are already working. Show:

**Message:**

✅ ISU accounts and security groups are already configured and
authenticated successfully. Skipping Task 2.

**End message.**

Skip to Task 3.

**If the SOAP auth check failed**, proceed with creation below.

### 2.2 — Get domain name (if not already set)

Check `my/connect/workday/config.json` for `domainName`. If it was set
during Task 1 (Entra login), DOMAIN_NAME is already available.

If DOMAIN_NAME is not set (user skipped Entra or chose "No"), ask:

```json
[
  {
    "header": "Domain",
    "question": "What's your organization's email domain? (e.g. contoso.com or contoso.onmicrosoft.com)"
  }
]
```

Save as DOMAIN_NAME. Update `my/connect/workday/config.json` — add
`"domainName": "{DOMAIN_NAME}"`.

### 2.2a — Create Integration System (automated)

**Message (do NOT wait for user response — continue immediately):**

**Task 2 of 6: ISU Accounts**

Creating the integration system and ISU accounts automatically...

**End message.**

Generate two random passwords for the ISU accounts. Run in the terminal
(do not show this command or its output to the user):

```
python -c "import secrets; print(secrets.token_urlsafe(16)); print(secrets.token_urlsafe(16))"
```

Save the first line as ISU_WQL_PASSWORD and the second as ISU_GENERIC_PASSWORD.

Use the Workday MCP `call_soap_api` tool to create the Integration System:

```
service_name: "Integrations"
version: "v42.0"
body_xml: |
  <bsvc:Put_Integration_System_Request bsvc:Add_Only="true" bsvc:version="v42.0"
    xmlns:bsvc="urn:com.workday/bsvc">
    <bsvc:Integration_System_Data>
      <bsvc:Integration_System_ID>ESS_COPILOT_{WD_TENANT}</bsvc:Integration_System_ID>
      <bsvc:Integration_System_Name>ESS Copilot Integration</bsvc:Integration_System_Name>
    </bsvc:Integration_System_Data>
  </bsvc:Put_Integration_System_Request>
```

**If the call succeeds**, continue to 2.2b.

**If it fails with "already exists" or similar**, that's fine — continue
to 2.2b (the integration system was created in a previous run).

**If it fails with "not authorized"**, the current account can't create
integration systems. Show:

**Message:**

I don't have permission to create integration systems automatically.
You'll need to create them manually:

1. In Workday, search for **`Create Integration System`**
2. Set **Integration System ID** to `ESS_COPILOT_{WD_TENANT}`
3. Set **Integration System Name** to `ESS Copilot Integration`
4. Click **OK**

Type **done** when complete.

**End message.**

Wait for the user, then continue to 2.2b.

### 2.2b — Create ISU_WQL_COPILOT (automated)

Use the Workday MCP `call_soap_api` tool:

```
service_name: "Integrations"
version: "v42.0"
body_xml: |
  <bsvc:Put_Integration_System_User_Request bsvc:version="v42.0"
    xmlns:bsvc="urn:com.workday/bsvc">
    <bsvc:Integration_System_Reference>
      <bsvc:ID bsvc:type="Integration_System_ID">ESS_COPILOT_{WD_TENANT}</bsvc:ID>
    </bsvc:Integration_System_Reference>
    <bsvc:Integration_System_User_Data>
      <bsvc:Integration_System_Reference>
        <bsvc:ID bsvc:type="Integration_System_ID">ESS_COPILOT_{WD_TENANT}</bsvc:ID>
      </bsvc:Integration_System_Reference>
      <bsvc:User_Name>ISU_WQL_COPILOT@{DOMAIN_NAME}</bsvc:User_Name>
      <bsvc:Password>{ISU_WQL_PASSWORD}</bsvc:Password>
      <bsvc:Do_Not_Allow_UI_Sessions>true</bsvc:Do_Not_Allow_UI_Sessions>
      <bsvc:Session_Timeout_Minutes>0</bsvc:Session_Timeout_Minutes>
      <bsvc:Require_New_Password_At_Next_Sign_In>false</bsvc:Require_New_Password_At_Next_Sign_In>
    </bsvc:Integration_System_User_Data>
  </bsvc:Put_Integration_System_User_Request>
```

Handle errors the same as 2.2a — if "not authorized", guide the user
to create manually in the portal.

### 2.2c — Create ISU_GENERIC_COPILOT (automated)

Same pattern as 2.2b but with:
- User_Name: `ISU_GENERIC_COPILOT@{DOMAIN_NAME}`
- Password: `{ISU_GENERIC_PASSWORD}`

### 2.2d — Show results

If automated creation succeeded for at least the ISU accounts:

**Message:**

✅ Created integration system and ISU accounts:

| Account | Username |
|---------|----------|
| WQL (reports) | `ISU_WQL_COPILOT@{DOMAIN_NAME}` |
| Generic (API) | `ISU_GENERIC_COPILOT@{DOMAIN_NAME}` |

Save these passwords — you'll need them for the connection references
in Copilot Studio:

| Account | Password |
|---------|----------|
| ISU_WQL_COPILOT | `{ISU_WQL_PASSWORD}` |
| ISU_GENERIC_COPILOT | `{ISU_GENERIC_PASSWORD}` |

**End message.**

### 2.2e — Create Security Groups (portal)

**Before asking the user to create security groups, check if they
already exist.** Security groups cannot be queried via SOAP API, so
ask the user to check.

**Message:**

Before creating security groups, let's check if they already exist.

In Workday, search for **`View Security Group`**, then look up
`ISSG_WQL_COPILOT`. If it exists, check that
`ISU_WQL_COPILOT@{DOMAIN_NAME}` is listed as a member.

Do the same for `ISSG_GENERIC_COPILOT` and
`ISU_GENERIC_COPILOT@{DOMAIN_NAME}`.

1. **Both exist with correct members** — skip to next task
2. **They exist but members are wrong** — I'll guide you to update them
3. **They don't exist** — I'll walk you through creating them

**End message.**

Wait for the user.

**If both exist with correct members:** skip to Task 3.

**If they don't exist:** show the creation instructions:

**Message:**

**Workday search:** `Create Security Group`

**First group:**
1. Type of Tenanted Security Group: **Integration System Security Group
   (Unconstrained)**
2. Name: `ISSG_WQL_COPILOT`
3. Click **OK**
4. On the next page, add Integration System Users:
   `ISU_WQL_COPILOT@{DOMAIN_NAME}`
5. Click **OK**

**Second group:**
1. Type: **Integration System Security Group (Unconstrained)**
2. Name: `ISSG_GENERIC_COPILOT`
3. Add Integration System Users:
   `ISU_GENERIC_COPILOT@{DOMAIN_NAME}`
4. Click **OK**

Type **done** when both groups are created.

**End message.**

Wait for the user.

---

## Task 3: Authentication Policies

**Verify first.** If the pre-flight SOAP auth check passed, authentication
policies are already configured correctly. Show:

**Message:**

✅ Authentication policies are already configured and working.
Skipping Task 3.

**End message.**

Skip to Task 4.

**If the SOAP auth check failed**, proceed with manual configuration:

**Message:**

**Task 3 of 6: Authentication Policies**

**Workday search:** `Manage Authentication Policies`

If there are multiple policies, select the one for the **Implementation**
environment (matching your tenant URL).

1. Click **Edit** on the authentication policy
2. Check if the ISU accounts are already listed:
   - `ISU_WQL_COPILOT@{DOMAIN_NAME}`
   - `ISU_GENERIC_COPILOT@{DOMAIN_NAME}`
3. If not listed, add them
4. For **Allowed Authentication Type**: select **User Name Password**
5. **Move these two entries to the TOP of the list** (drag them above
   all other entries)
6. Click **OK**

**Then activate the changes:**

**Workday search:** `Activate All Pending Authentication Policy Changes`
→ Click **OK**

Type **done** when complete.

**End message.**

Wait for the user.

### 2.3a — Verify auth policy

**Message (do NOT wait for user response — continue immediately):**

Verifying ISU authentication...

**End message.**

Use the Workday MCP `test_connection` tool.

**If it returns worker data (success):**

**Message:**

✅ Authentication policy is working.

**End message.**

**If it returns "invalid username or password":**

**Message:**

Authentication is still failing. Common causes:

- The ISU accounts weren't moved to the **top** of the auth policy list
- The auth type wasn't set to **User Name Password** for the ISU entries
- You forgot to activate pending changes (search for
  `Activate All Pending Authentication Policy Changes`)
- The ISU password may have expired — try resetting it

Fix and type **retry**.

**End message.**

Wait for the user. When they say retry, re-run `test_connection`.

---

## Task 4: Register API Client

**This task is always needed** for a new environment, even if other
tasks were pre-configured. However, an existing client may already be
suitable. Ask the user to check first.

**Message:**

**Task 4 of 6: API Client Registration**

Before creating a new client, let's check if a suitable one exists.

In Workday, search for **`View API Clients`** and look at the
**API Clients** tab (the first tab, NOT "API Clients for Integrations").

Do you see any client with **Assertion Verification** set to
**Use Configured IdPs**? Common names are `copilot_workday_sso`,
`Workday Copilot for SSO`, or similar.

1. **Yes, I see one** — tell me its Client Name and Client ID
2. **No** — I'll walk you through creating one

**End message.**

Wait for the user.

**If the user found an existing client:** save the Client ID as
OAUTH_CLIENT_ID. The Token Endpoint is always:
`https://{WD_BASE_URL host}/ccx/oauth2/{WD_TENANT}/token`
Skip client creation and go to the save step below.

**If the user says no:** proceed with creation.

### 2.4a — Create API Client (Entra ID Integrated path)

**If USES_ENTRA is true:**

**Message:**

**Workday search:** `Register API Client`
(NOT "Register API Client for Integrations" — that's a different form)

Fill in these fields in order:

| # | Field | Value |
|---|-------|-------|
| 1 | **Client Name** | `ESS_Copilot_{WD_TENANT}` |
| 2 | **Client Grant Type** | **SAML Bearer Grant** |
| 3 | **Support Proof Key for Code Exchange** | *(unchecked)* |
| 4 | **Allow User Delegation** | *(unchecked)* |
| 5 | **Enforce Customized Access Token Expiry** | *(unchecked)* |
| 6 | **Assertion Verification** | **Use Configured IdPs** |
| 7 | **x509 Certificate** | *(empty)* |
| 8 | **Integration System User** | *(empty)* |
| 9 | **Access Token Type** | Bearer |
| 10 | **Allow Access to All System Users** | **Yes** *(checked)* |
| 11 | **Redirection URI** | *(empty)* |
| 12 | **Allow Integration Messages** | **Yes** *(checked)* |
| 13 | **Refresh Token Timeout (in days)** | `0` |
| 14 | **Non-Expiring Refresh Tokens** | *(unchecked)* |
| 15 | **Grant Administrative Consent** | **Yes** *(checked)* |

Scroll down for scopes:

| # | Field | Value |
|---|-------|-------|
| 16 | **Scope (Functional Areas)** | *(see list below)* |
| 17 | **Include Workday Owned Scope** | **Yes** *(checked)* |

**Scopes to add** (alphabetical):
- Cloud Connect for Learning
- Core Payroll
- Organizations and Roles
- Peakon Employee Voice
- Staffing
- Tenant Non-Configurable
- Time Off and Leave
- Worker Profile and Skills
- Worktags

Click **OK**, then **immediately copy the Client ID** — it cannot
be retrieved later.

**End message.**

### 2.4b — Create API Client (Basic auth path)

**If USES_ENTRA is false:**

**Message:**

**Workday search:** `Register API Client for Integrations`

Fill in these fields in order:

| # | Field | Value |
|---|-------|-------|
| 1 | **Client Name** | `ESS_Copilot_{WD_TENANT}` |
| 2 | **Non-Expiring Refresh Tokens** | **Yes** *(checked)* |
| 3 | **Scope (Functional Areas)** | *(see list below)* |
| 4 | **Include Workday Owned Scope** | **Yes** *(checked)* |

**Scopes to add** (alphabetical):
- Advanced Compensation
- Benefits
- Contact Information
- Core Compensation
- Organizations and Roles
- Personal Data
- Staffing
- Time Off and Leave

Click **OK**, then **immediately copy the Client ID and Client
Secret** — they cannot be retrieved later.

**End message.**

### 2.4c — Save client details

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Client ID",
    "question": "Paste the Client ID from Workday:"
  }
]
```

Save as OAUTH_CLIENT_ID. The Token Endpoint is:
`https://{WD_BASE_URL host}/ccx/oauth2/{WD_TENANT}/token`

Update `my/connect/workday/config.json` — add:
```json
{
  "oauthClientId": "{OAUTH_CLIENT_ID}",
  "oauthTokenUrl": "https://{WD_BASE_URL host}/ccx/oauth2/{WD_TENANT}/token"
}
```

**Note on API client types:** Workday API clients **cannot be deleted**,
only disabled. If the user made a mistake, they should disable the
incorrect client and create a new one.

**Message:**

✅ API client registered.

**End message.**

---

## Task 5: Security Group Domain Permissions

**Verify first.** If the pre-flight worker data AND time off balance
checks passed, domain permissions are already configured. Show:

**Message:**

✅ Domain permissions are already configured — worker data and time
off balances are accessible. Skipping Task 5.

**End message.**

Skip to Task 6.

**If either check failed**, proceed with manual permission setup:

### 2.5a — ISSG_WQL_COPILOT permissions

**Message:**

**Task 5 of 6: Domain Permissions** (most complex step — 4 sub-steps)

**Step 5a — Permissions for ISSG_WQL_COPILOT:**

In Workday, search for **`View Security Group`**, then look up
`ISSG_WQL_COPILOT`. Click on it, then use **Related Actions**
(ellipsis) → **Security Group** → **Maintain Domain Permissions
for Security Group**.

Add these permissions:

**Report/Task Permissions tab:**

| Domain Security Policy | Modify | View |
|---|---|---|
| Workday Accounts | No | **Yes** |
| Custom Report Creation | **Yes** | No |
| Person Data: Work Email | No | **Yes** |
| Worker Data: Current Staffing Information | No | **Yes** |
| Setup: Tenant Setup - Reporting and Analytics | No | **Yes** |
| Worker Data: Worker ID | No | **Yes** |

**Integration Permissions tab:**

| Domain Security Policy | Put | Get |
|---|---|---|
| Person Data: Work Email | No | **Yes** |
| Worker Data: Current Staffing Information | No | **Yes** |
| Setup: Tenant Setup - Reporting and Analytics | No | **Yes** |
| Worker Data: Worker ID | No | **Yes** |

4. Click **OK**

Type **done** when complete.

**End message.**

Wait for the user.

### 2.5b — ISSG_GENERIC_COPILOT permissions

**Message:**

**Step 5b — Permissions for ISSG_GENERIC_COPILOT:**

In Workday, search for **`View Security Group`**, then look up
`ISSG_GENERIC_COPILOT`. Click on it, then use **Related Actions**
(ellipsis) → **Security Group** → **Maintain Domain Permissions
for Security Group**.
2. Add these permissions:

**Integration Permissions tab:**

| Domain Security Policy | Put | Get |
|---|---|---|
| Job Information | No | **Yes** |
| Setup: Compensation Packages | No | **Yes** |
| Integration Build | No | **Yes** |

3. Click **OK**

Type **done** when complete.

**End message.**

Wait for the user.

### 2.5c — Employee/manager self-service permissions

**Message:**

**Step 5c — Self-service permissions:**

**Workday search:** `Maintain Domain Permissions`

For each domain below, add the listed security groups:

| Domain Security Policy | Security Groups to Add | Put | Get |
|---|---|---|---|
| Worker data: Public worker reports | Employee as self, Manager | No | **Yes** |
| Person data: Home contact information | Employee as self | No | **Yes** |
| Person data: Work contact information | Employee as self, Manager | No | **Yes** |
| BP: Home contact change | Employee as self | No | **Yes** |

Click **OK** after each domain.

Type **done** when all four domains are updated.

**End message.**

Wait for the user.

### 2.5d — Activate permissions

**Message:**

**Step 5d — Activate changes:**

**Workday search:** `Activate Pending Security Policy Changes`
→ Click **OK**

Type **done**.

**End message.**

Wait for the user.

### 2.5e — Verify permissions

**Message (do NOT wait for user response — continue immediately):**

Verifying permissions...

**End message.**

Use the Workday MCP `get_worker` tool with a known employee ID
(e.g., `employee_id="21001"`).

**If it returns worker data:**

**Message:**

✅ Domain permissions verified — worker data is accessible.

**End message.**

**If it returns "not authorized":**

**Message:**

Permission check failed. The domain permission **Worker data: Public
worker reports** may be missing. In Workday:

1. Search for `ISSG_WQL_COPILOT`
2. Open **Related Actions** → **Security Group** →
   **Maintain Domain Permissions**
3. Verify all domains listed in steps 5a–5c are present
4. Search for `Activate Pending Security Policy Changes` → click **OK**

Type **retry** to test again.

**End message.**

Wait for the user. On retry, re-run the `get_worker` check.

---

## Task 6: WD_User_Context RaaS Report

**Verify first.** If the pre-flight RaaS report check passed, the
report already exists and is working. Show:

**Message:**

✅ The WD_User_Context report already exists and is returning data.
Skipping Task 6.

**End message.**

Skip to section 2.7.

**If the RaaS check failed**, the report needs to be created. Proceed
below.

### 2.6a — Create calculated fields

**Message:**

**Task 6 of 6: WD_User_Context Report** (10 sub-steps)

This report maps Workday usernames to employee context data. The ESS
agent calls it on every conversation to identify the user.

**Step 6a — Create 4 calculated fields:**

**Workday search:** `Create Calculated Field`

**Field 1: CF - ISO 2 Country Code LRV**
- Business Object: `Worker`
- Lookup Field: `Location Address - Country/Region`
- Related Business Object: `Country/Region`
- Return Value: `Alpha-2 Code`

**Field 2: CF - EE Level LRV**
- Business Object: `Worker`
- Lookup Field: `Supervisory Organization - Primary Position`
- Related Business Object: `Supervisory Organization`
- Return Value: `Organization on Level from Top`

**Field 3: CF LRV Sup Org Ref ID**
- Business Object: `Worker`
- Lookup Field: `Manager's Default Supervisory Organization`
- Related Business Object: `Supervisory Organization`
- Return Value: `Reference ID`

**Field 4: CF LRV Worker Type**
- Business Object: `Workday Account`
- Lookup Field: `Worker`
- Related Business Object: `Worker`
- Return Value: `Worker Type`

Type **done** when all 4 fields are created.

**End message.**

Wait for the user.

### 2.6b — Create the report

**Message:**

**Step 6b — Create the report:**

**Workday search:** `Create Custom Report`

| Field | Value |
|---|---|
| **Report Name** | `WD_User_Context` |
| **Report Type** | Advanced |
| **Data Source** | All Workday Accounts |

Click **OK**, then configure each tab below.

**End message.**

### 2.6c — Columns tab

**Message:**

**Step 6c — Columns tab:**

Add these columns in this exact order:

| # | Business Object | Field | Column Heading Override (XML Alias) |
|---|---|---|---|
| 1 | Worker | Preferred Name - First Name | `First_Name` |
| 2 | Worker | Preferred Name - Last Name | `Last_Name` |
| 3 | Worker | Email - Primary Work | `Work_Email` |
| 4 | Workday Account | User Name | `User_Name` |
| 5 | Worker | Employee ID | `Employee_ID` |
| 6 | Worker | CF - ISO 2 Country Code LRV | `Country_Code` |
| 7 | Worker | Company - ID | `Company_Code` |
| 8 | Worker | Is Manager | `Is_Manager` |
| 9 | Worker | Is People Manager (with prompts) | `Is_People_Manager` |
| 10 | Worker | CF - EE Level LRV | `Level` |
| 11 | Workday Account | Display Language | `Display_Language` |
| 12 | Workday Account | Locale | `Locale` |
| 13 | Worker | CF LRV Sup Org Ref ID | `Mgr_Sup_Org_Id` |

Set **Group Column Heading** XML alias to `Worker_group`.

Type **done** when all columns are added.

**End message.**

Wait for the user.

### 2.6d — Filter tab

**Message:**

**Step 6d — Filter tab:**

Add these filter conditions:

| And/Or | Field | Operator | Comparison Type | Value |
|---|---|---|---|---|
| And | User Name | equal to | Prompt the user for the value | *(default prompt)* |
| And | CF LRV Worker Type | in the selection list | value specified in filter | `Employee` |

Type **done**.

**End message.**

Wait for the user.

### 2.6e — Prompts tab

**Message:**

**Step 6e — Prompts tab:**

| Prompt Field | XML Alias | Required | Don't Prompt at Runtime |
|---|---|---|---|
| User Name | `User_Name` | **Yes** | No |
| Employee Type | `Employee_Type` | No | **Yes** |
| Non-Employee Type | `Employee_Type` | No | **Yes** |
| Include managers of employees | `Include_managers_of_employees` | No | **Yes** (default: Yes) |
| Include managers of nonemployees | `Include_managers_of_non_employees` | No | **Yes** |
| Include managers of unfilled positions only | `Include_managers_of_unfilled_positions_only` | No | **Yes** |

**Critical:** The User Name XML alias must be exactly `User_Name`
(not `Username`, not `UPN`, not `user_name`).

Type **done**.

**End message.**

Wait for the user.

### 2.6f — Sort, Output, Share, Advanced tabs

**Message:**

**Step 6f — Remaining tabs:**

**Sort tab:** Sort by first accessible column (no changes needed).

**Output tab:** Set Output type to **Table**.

**Share tab:**
- Share with specific authorized groups and users: **Yes**
- Report owned by: `ISU_WQL_COPILOT@{DOMAIN_NAME}`

**Advanced tab:**
- **Enable as a web service:** **Yes**
- Web service API version: `v43.0`
- Namespace: `urn:com.workday.report/WD_User_Context`

Click **Save** (or **OK**) to save the report.

Type **done**.

**End message.**

Wait for the user.

### 2.6g — Transfer report ownership

**Message:**

**Step 6g — Transfer ownership:**

**Workday search:** `Transfer Report Ownership`

1. Find the `WD_User_Context` report
2. Transfer ownership to `ISU_WQL_COPILOT@{DOMAIN_NAME}`

Type **done**.

**End message.**

Wait for the user.

### 2.6h — Verify the report

**Message (do NOT wait for user response — continue immediately):**

Verifying the WD_User_Context report...

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Test username",
    "question": "Enter a Workday username to test the report (e.g., a known employee's Workday login name):"
  }
]
```

Use the Workday MCP `get_user_context` tool with the provided username.

**If it returns a Report_Entry with employee data:**

**Message:**

✅ WD_User_Context report is working.

**End message.**

**If it returns "Report parameter User Name is required":**

**Message:**

The report is accessible but the parameter name doesn't match. Check
the **Prompts tab** — the User Name field's **XML Alias** must be
exactly `User_Name` (case-sensitive).

Fix and type **retry**.

**End message.**

**If it returns "not authorized":**

**Message:**

The ISU account can't access the report. Check:
1. Report ownership was transferred to `ISU_WQL_COPILOT@{DOMAIN_NAME}`
2. ISSG_WQL_COPILOT has **Custom Report Creation** under Modify in
   Report/Task Permissions
3. Pending security policy changes are activated

Fix and type **retry**.

**End message.**

**If it returns 404 or "resource not found":**

**Message:**

The report wasn't found. Check:
1. **Advanced tab** → **Enable as a web service** is **Yes**
2. The report name is exactly `WD_User_Context`
3. The report owner matches your RaaS username

Fix and type **retry**.

**End message.**

Wait for the user on retry. Re-run `get_user_context`.

---

## 2.7 — Complete step 2

Update `my/connect/workday/tasks.md` — change step 2 from
`- [ ]` to `- [x]`.

**Message:**

✅ Admin setup complete!

| # | Task | Status |
|---|------|--------|
| 1 | Environment configured | ✅ |
| 2 | Admin setup complete | ✅ |
| 3 | Connection verified | ⬜ |

One more step — let's run the final verification.

**End message.**

Now read `src/skills/connect/workday/step3.md` and follow it.
