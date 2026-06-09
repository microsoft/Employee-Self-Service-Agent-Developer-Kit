# Workday Step 2: Admin Setup

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "DOMAIN_NAME = ..." or "TENANT_NAME = ..." in chat.

Read `.local/connect/workday/config.json` for ALL values — WD_BASE_URL (baseUrl),
WD_TENANT (tenant), WD_TOKEN_HOST (tokenHost), DOMAIN_NAME (domainName),
TENANT_ID (tenantId), WD_ENTRA_APP_ID (entraAppId),
WD_ENTRA_APP_ID_URI (entraAppIdUri), WD_OAUTH_TOKEN_URL (oauthTokenUrl),
WD_OAUTH_CLIENT_ID (oauthClientId),
ENTRA_SSO_EXISTS (entraSSO), REPORT_OWNER (reportOwner),
RAAS_REPORT_EXISTS (raasReportExists).

**MCP reconnect:** If any Workday MCP tool call fails with a connection
error (timeout, server not running, etc.), check if the MCP server is
still running. If not, restart it by re-running the MCP setup from
step1.md (pip install + server start). Then retry the failed call.
Do NOT ask the user about MCP internals — handle reconnection silently.

**CRITICAL RULES (from retro):**
- There are TWO install paths (set as `installPath` in config by step 1):
  - **simplified** — Task 1 (Entra SSO) and Task 4 (Register API
    Client) apply. ISU accounts, security groups, auth policies, domain
    permissions, and the RaaS report are NOT needed (the `ff0df`
    connection + REST `/workers/me` replace them). The `ff0df` OAuthUser
    connection still signs in with a Workday API client whose Client ID
    (`oauthClientId`) is entered at install time, so Task 4 is required.
    After Task 1, do Task 4, then skip to 2.7.
  - **legacy** — all 6 tasks apply, as documented below.
  Read `installPath` from `my/connect/workday/config.json` and follow
  the matching path. When in doubt for a fresh install, the path is
  `simplified`.
- Entra SSO is MANDATORY on BOTH paths. Do not ask if the user wants it.
  Do not skip Task 1. The OAuthUser connection reference uses
  `runtimeSource: invoker` which requires Entra SSO for employee-scoped
  API calls.
- NEVER skip tasks based on pre-flight tests run with MCP admin credentials.
  The MCP uses the user's admin account. The Power Platform flows use ISU
  accounts. These have DIFFERENT permissions. A passing pre-flight does NOT
  mean ISU accounts work.
- Use idempotent creation patterns: try to create with Add_Only=true, catch
  "already exists" errors gracefully. This tells you the object exists
  without needing to search the Workday UI.
- When generating ISU passwords, include uppercase, lowercase, digits, AND
  special characters (`!@#$`). Workday rejects passwords without special chars.
- NEVER tell the user to "check with your teammates." Use the tools available
  (Azure CLI, Workday MCP, Dataverse MCP) to discover state.
- Every step that has a verifiable outcome MUST be verified programmatically.
  Do NOT accept "done" without checking.

---

## 2.0 — Show task overview

Read `installPath` from `my/connect/workday/config.json`.

**If INSTALL_PATH is `simplified`:**

**Message:**

There are two admin tasks for the streamlined Workday setup: enabling
Microsoft Entra single sign-on so employees authenticate as themselves,
and registering the Workday API client the connection signs in with.
I'll handle as much as possible automatically and verify each before
moving on.

**End message.**

Do Task 1 (Entra SSO Setup) and Task 4 (Register API Client) below, then
skip directly to section 2.7. Do NOT do Tasks 2, 3, 5, or 6.

**If INSTALL_PATH is `legacy`:**

**Message:**

There are 6 admin tasks to set up. I'll handle as much as possible
automatically and verify each step before moving on.

| # | Admin Task | What it does |
|---|-----------|-------------|
| 1 | Entra SSO | Lets employees sign in to Workday via their Microsoft account |
| 2 | ISU accounts | Service accounts for the Copilot agent's API calls |
| 3 | Authentication policies | Allows ISU accounts to authenticate |
| 4 | API client | OAuth client for Workday token exchange |
| 5 | Domain permissions | Controls which data the agent can access |
| 6 | User context report | Maps employee usernames to their HR data |

Let's go.

**End message.**

---

## Task 1: Entra SSO Setup

**This task is MANDATORY.** Do not skip it regardless of any pre-flight
results. The Workday extension pack requires Entra SSO for employee-scoped
scenarios (compensation, time off requests, contact updates).

### 2.1a — Check if Entra app already exists

Read `.local/connect/workday/config.json`. If `entraSSO` is `true` and
`entraAppId` is set, an Entra app was already found in step 1.

**If ENTRA_SSO_EXISTS is true:**

Verify the Power Platform Workday connector is pre-authorized on the app:

```
az ad app show --id {WD_ENTRA_APP_OBJECT_ID} --query "api.preAuthorizedApplications" -o json
```

The Power Platform Workday connector app ID is:
`4e4707ca-5f53-46a6-a819-f7765446e6ff`

**If the connector is already pre-authorized:**

**Message:**

✅ Entra SSO is already configured — found app **{app displayName}**
with Application ID URI `{WD_ENTRA_APP_ID_URI}`.

**End message.**

If `installPath` is `simplified`, skip to Task 4. Otherwise continue to
Task 2.

**If the connector is NOT pre-authorized:** add it using `az rest`
to PATCH `api.preAuthorizedApplications` (follow the pattern in
`src/skills/connect/azure/app-registration.md` section B.5). Then, if
`installPath` is `simplified`, skip to Task 4; otherwise continue to
Task 2.

**If ENTRA_SSO_EXISTS is false:** proceed to 2.1b.

### 2.1b — Create or find the Workday Entra app

**Message (do NOT wait for user response — continue immediately):**

Setting up Entra SSO for Workday...

**End message.**

First, check if any Workday service principals exist:

```
az ad sp list --display-name "Workday" --query "[].{name:displayName, appId:appId, id:id, sso:preferredSingleSignOnMode}" -o json
```

**If results contain an app with `sso: "saml"` and a matching identifier
URI for `{WD_TENANT}`:** That's the existing SSO app. Save its details
and skip to 2.1d (pre-authorize connector).

**If no SAML app exists for this tenant:** Create from the Workday gallery
template.

Find the Workday template ID:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/applicationTemplates?\$filter=displayName%20eq%20'Workday'" --query "value[0].id" -o tsv
```

Save as TEMPLATE_ID. Instantiate the template:

```powershell
$body = @{displayName="Workday (ESS Copilot)"} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-wd-template.json" -Encoding utf8
az rest --method POST --url "https://graph.microsoft.com/v1.0/applicationTemplates/{TEMPLATE_ID}/instantiate" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-template.json"
```

From the response, extract:
- `application.appId` → WD_ENTRA_APP_ID
- `application.id` → WD_ENTRA_APP_OBJECT_ID
- `servicePrincipal.id` → WD_ENTRA_SP_ID

**If permission error:** Show:

**Message:**

I need permission to create enterprise applications in your Entra
tenant. This requires the **Application Administrator** or **Cloud
Application Administrator** role.

This is a one-time setup. Ask your IT admin to either:
- Grant you that role temporarily, or
- Create a Workday enterprise app in Entra and tell you its Application ID

Then run `/connect workday` again.

**End message.**

Stop here.

### 2.1c — Configure SAML SSO

Set preferred SSO mode to SAML:

```powershell
$body = @{preferredSingleSignOnMode="saml"} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-wd-sso.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-sso.json"
```

Set identifier URIs and reply URLs:

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

Adjust the redirect URI host if the tenant is not on `impl.workday.com`.

Save WD_ENTRA_APP_ID_URI = `http://www.workday.com/{WD_TENANT}`.

### 2.1d — Create signing certificate and pre-authorize connector

Create signing certificate:

```powershell
$body = @{
  displayName="CN=ESS Copilot Signing Cert"
  endDateTime="2028-01-01T00:00:00Z"
} | ConvertTo-Json
$body | Out-File "$env:TEMP\ess-wd-cert.json" -Encoding utf8
az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}/addTokenSigningCertificate" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-cert.json"
```

If certificate already exists (from a previous run), skip creation.

Download the Base64 certificate:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/{WD_ENTRA_SP_ID}" --query "keyCredentials[0].key" -o tsv
```

Save as ENTRA_CERTIFICATE_BASE64.

Pre-authorize the Power Platform Workday connector
(`4e4707ca-5f53-46a6-a819-f7765446e6ff`) — follow the pattern in
`src/skills/connect/azure/app-registration.md` section B.5.

### 2.1e — Configure Workday tenant security

Compute the values:
- ENTRA_IDENTIFIER = `https://sts.windows.net/{TENANT_ID}/`
- ENTRA_LOGIN_URL = `https://login.microsoftonline.com/{TENANT_ID}/saml2`
- SERVICE_PROVIDER_ID = `http://www.workday.com/{WD_TENANT}`

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

Update `.local/connect/workday/config.json`:
```json
{
  "entraSSO": true,
  "entraAppId": "{WD_ENTRA_APP_ID}",
  "entraAppIdUri": "{WD_ENTRA_APP_ID_URI}",
  "tenantId": "{TENANT_ID}"
}
```

**Task 1 done.** If `installPath` is `simplified`, skip Tasks 2 and 3 and
go to **Task 4 (Register API Client)** now. If `legacy`, continue to
Task 2.

---

## Task 2: ISU Accounts and Security Groups

**LEGACY PATH ONLY.** If `installPath` is `simplified`, skip Tasks 2 and
3 and go to **Task 4 (Register API Client)** now; after Task 4, skip
Tasks 5 and 6 and go to section 2.7. The simplified install still needs
the API client but no ISU accounts, security groups, auth policies,
domain permissions, or RaaS report.

**Do NOT skip this task based on pre-flight.** The pre-flight uses
the MCP admin credentials, not ISU credentials. Always verify ISU
accounts exist using idempotent creation.

### 2.2a — Create Integration System (idempotent)

**Message (do NOT wait for user response — continue immediately):**

Setting up service accounts...

**End message.**

Use the Workday MCP `call_soap_api` tool:

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

- If succeeds → integration system created.
- If "already exists" → fine, it was created previously.
- If "not authorized" → fall back to asking user to create manually.

### 2.2b — Create ISU accounts (idempotent)

Generate passwords with special characters. Run in the terminal
(do not show this command or its output to the user):

```
python -c "import secrets,string; chars=string.ascii_letters+string.digits+'!@#$'; pw=''.join(secrets.choice(chars) for _ in range(16)); pw=pw[:4]+'!'+pw[4:8]+'#'+pw[8:12]+'@'+pw[12:]; print(pw); pw2=''.join(secrets.choice(chars) for _ in range(16)); pw2=pw2[:4]+'!'+pw2[4:8]+'#'+pw2[8:12]+'@'+pw2[12:]; print(pw2)"
```

Save the first line as ISU_WQL_PASSWORD and the second as ISU_GENERIC_PASSWORD.

**Create ISU_WQL_COPILOT:**

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

**If succeeds** → ISU created with known password.
**If "already exists"** or the account was updated → the password is now
reset to {ISU_WQL_PASSWORD}. This is intentional — we need to know
the password for the Power Platform connections.

**If password rejected** ("does not meet password requirements") →
regenerate with more special characters and retry.

**If "not authorized"** → fall back to portal instructions.

**Create ISU_GENERIC_COPILOT:** Same pattern with:
- User_Name: `ISU_GENERIC_COPILOT@{DOMAIN_NAME}`
- Password: `{ISU_GENERIC_PASSWORD}`

### 2.2c — Verify or create security groups

Security groups cannot be created via SOAP API. Use the idempotent
"try to create, catch exists" approach in the portal.

**Message:**

Now I need you to set up two security groups in Workday. For each one,
I'll tell you exactly what to search for and what to enter.

**Group 1:**
1. In Workday, search for **`Create Security Group`**
2. Type: **Integration System Security Group (Unconstrained)**
3. Name: `ISSG_WQL_COPILOT`
4. Click **OK**
5. On the next page, add: `ISU_WQL_COPILOT@{DOMAIN_NAME}`
6. Click **OK**

If you see "name already in use" — that means it already exists.
Search for **`View Security Group`** → `ISSG_WQL_COPILOT` and verify
`ISU_WQL_COPILOT@{DOMAIN_NAME}` is listed as a member. If not, use
**Related Actions → Edit** to add it.

**Group 2:** Same steps but:
- Name: `ISSG_GENERIC_COPILOT`
- Member: `ISU_GENERIC_COPILOT@{DOMAIN_NAME}`

Type **done** when both groups are ready.

**End message.**

Wait for the user. Do NOT accept "done" blindly — proceed to Task 3
which will verify authentication actually works.

**Message:**

✅ Service accounts configured.

| Account | Username |
|---------|----------|
| WQL (reports) | `ISU_WQL_COPILOT@{DOMAIN_NAME}` |
| Generic (API) | `ISU_GENERIC_COPILOT@{DOMAIN_NAME}` |

**End message.**

**Hold ISU_WQL_PASSWORD and ISU_GENERIC_PASSWORD in session memory only**
for use in step 3 connection setup. Do NOT write them to
`.local/connect/workday/config.json` - ISU credentials are full reusable
Workday user accounts (worse risk profile than the cert PFX passphrase
in `step2-certificate.md`, which we also keep off disk), and `.local/` is a
working directory contributors share, debug from, and occasionally
commit by accident. The Power Platform connection ref encrypts and
stores them server-side once step 3 wires the connections, so the
on-disk copy in `.local/` would be a duplicate worth eliminating.

If the user comes back to step 3 in a new session and the passwords
are gone from session memory, re-prompt for them at that point.

---

## Task 3: Authentication Policies

Authentication policies control which accounts can authenticate via
SOAP API. If the policies are **disabled** (common in implementation
tenants), ISU accounts work automatically. If **enabled**, ISU accounts
must be listed.

**Message:**

In Workday, search for **`Manage Authentication Policies`**.

Do any policies show **Authentication Policy Enabled: Yes**?

1. **No, all are disabled** — we can skip this step
2. **Yes, one or more are enabled** — I'll guide you through adding
   the ISU accounts

**End message.**

Wait for the user.

**If all disabled:** Skip to Task 4.

**If enabled:**

**Message:**

Click **Edit** on the enabled policy (choose the one matching your
environment — Implementation or Production).

1. Add these two accounts:
   - `ISU_WQL_COPILOT@{DOMAIN_NAME}`
   - `ISU_GENERIC_COPILOT@{DOMAIN_NAME}`
2. Set **Allowed Authentication Type** to **User Name Password**
3. **Move both entries to the TOP of the list**
4. Click **OK**

Then search for **`Activate All Pending Authentication Policy Changes`**
→ Click **OK**

Type **done** when complete.

**End message.**

Wait for the user. Proceed to Task 4.

---

## Task 4: Register API Client

Check `.local/connect/workday/config.json` for `oauthClientId`. If it's
already set (discovered or saved previously), skip to the save step.

**Message:**

In Workday, search for **`View API Clients`** and check the first tab
(**API Clients**, NOT "API Clients for Integrations").

Do you see any client with **Assertion Verification** set to
**Use Configured IdPs**?

1. **Yes** — tell me its Client ID
2. **No** — I'll walk you through creating one

**End message.**

Wait for the user.

**If user found one:** Save Client ID as OAUTH_CLIENT_ID.

**If no:**

**Message:**

**Workday search:** `Register API Client`
(NOT "Register API Client for Integrations" — that's a different form)

| # | Field | Value |
|---|-------|-------|
| 1 | **Client Name** | `ESS_Copilot_{WD_TENANT}` |
| 2 | **Client Grant Type** | **SAML Bearer Grant** |
| 3 | **Assertion Verification** | **Use Configured IdPs** |
| 4 | **Access Token Type** | Bearer |
| 5 | **Allow Access to All System Users** | **Yes** |
| 6 | **Allow Integration Messages** | **Yes** |
| 7 | **Grant Administrative Consent** | **Yes** |
| 8 | **Include Workday Owned Scope** | **Yes** |

**Scopes to add:**
- Core Payroll
- Organizations and Roles
- Staffing
- Tenant Non-Configurable
- Time Off and Leave
- Worker Profile and Skills

Leave all other fields at defaults.

Click **OK**, then **immediately copy the Client ID** — it cannot
be retrieved later.

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

Save as OAUTH_CLIENT_ID.

Update `.local/connect/workday/config.json`:
```json
{
  "oauthClientId": "{OAUTH_CLIENT_ID}",
  "oauthTokenUrl": "https://{WD_TOKEN_HOST}/ccx/oauth2/{WD_TENANT}/token"
}
```

**Message:**

✅ API client registered.

**End message.**

**If `installPath` is `simplified`, admin setup is done - skip Tasks 5
and 6 and go to section 2.7 now.** For legacy, continue to Task 5.

---

## Task 5: Security Group Domain Permissions

**NEVER skip this task.** The pre-flight tests use MCP admin credentials
which have broader permissions than ISU accounts. Always walk through
the full permission checklist.

### 2.5a — ISSG_WQL_COPILOT permissions

**Message:**

In Workday, search for **`Maintain Permissions for Security Group`**.
Select **Maintain** and search for `ISSG_WQL_COPILOT`.

Verify these permissions exist (add any that are missing):

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
| Setup: Contact Info, IDs, and Personal Data | **Yes** | **Yes** |
| Person Data: Work Email | No | **Yes** |
| Worker Data: Current Staffing Information | No | **Yes** |
| Setup: Tenant Setup - Reporting and Analytics | No | **Yes** |
| Worker Data: Worker ID | No | **Yes** |

Click **OK**. Type **done**.

**End message.**

Wait for the user.

### 2.5b — ISSG_GENERIC_COPILOT permissions

**Message:**

Same task — search for **`Maintain Permissions for Security Group`**,
select `ISSG_GENERIC_COPILOT`.

**Integration Permissions tab:**

| Domain Security Policy | Put | Get |
|---|---|---|
| Setup: Contact Info, IDs, and Personal Data | **Yes** | **Yes** |
| Job Information | No | **Yes** |
| Setup: Compensation Packages | No | **Yes** |
| Setup: Compensation Management | No | **Yes** |
| Integration Build | No | **Yes** |
| Worker Data: Compensation | No | **Yes** |
| Worker Data: Time Off | No | **Yes** |
| Worker Data: Personal Data | No | **Yes** |
| Worker Data: Public Worker Reports | No | **Yes** |

Click **OK**. Type **done**.

**End message.**

Wait for the user.

### 2.5c — Employee/manager self-service permissions

**Message:**

**Workday search:** `Maintain Domain Permissions`

For each domain below, verify the listed security groups have access
(add any that are missing):

| Domain Security Policy | Security Groups | Put | Get |
|---|---|---|---|
| Worker data: Public worker reports | Employee as self, Manager | No | **Yes** |
| Person data: Home contact information | Employee as self | No | **Yes** |
| Person data: Work contact information | Employee as self, Manager | No | **Yes** |
| BP: Home contact change | Employee as self | No | **Yes** |

Click **OK** after each domain. Type **done** when all are set.

**End message.**

Wait for the user.

### 2.5d — Activate and verify

**Message:**

**Workday search:** `Activate Pending Security Policy Changes` → **OK**

**End message.**

Wait 5 seconds, then verify via Workday MCP:

Use `get_worker` with `employee_id="21001"`.

**If returns worker data:**

**Message:**

✅ Domain permissions verified.

**End message.**

**If returns error:** Show the specific error and guide the user to
check the relevant domain in their security group permissions. Then
retry.

---

## Task 6: WD_User_Context RaaS Report

Check `.local/connect/workday/config.json`. If `raasReportExists` is `true`,
the report was already detected in step 1.

**If report exists:**

**Message:**

✅ The WD_User_Context report already exists and is working.

**End message.**

Skip to section 2.7.

**If report does not exist**, guide creation. The report creation steps
are portal-only and cannot be automated.

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

Update `.local/connect/workday/tasks.md` — change step 2 from
`- [ ]` to `- [x]`.

**If INSTALL_PATH is `simplified`:**

**Message:**

✅ Admin setup complete!

| # | Task | Status |
|---|------|--------|
| 1 | Environment configured | ✅ |
| 2 | Entra SSO enabled | ✅ |
| 3 | Connection verified | ⬜ |

One more step — let's install the Workday extension and run the final
verification.

**End message.**

**If INSTALL_PATH is `legacy`:**

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
