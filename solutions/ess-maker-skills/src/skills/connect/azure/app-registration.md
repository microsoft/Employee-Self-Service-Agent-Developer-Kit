# Entra App Registration (Shared)

This file is integration-agnostic. It creates an Entra ID app registration
configured for Power Platform connector SSO. It is called by
integration-specific step files (e.g., `servicenow/step2-entra.md`).

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "APP_CLIENT_ID = ..." or "APP_OBJECT_ID = ..." in chat.

**Inputs from the calling file:**
- TENANT_ID — from `azure/login.md`
- APP_DISPLAY_NAME — set by the calling file (e.g.,
  `"ESS Copilot - ServiceNow OIDC (dev352928)"`)

**Outputs to the calling file:**
- APP_CLIENT_ID — the app (client) ID
- APP_OBJECT_ID — the app object ID (for Graph API calls)
- SCOPE_GUID — the GUID of the `user_impersonation` scope

---

## B.1 — Check for existing app (idempotency)

Run in the terminal:

```
az ad app list --display-name "{APP_DISPLAY_NAME}" --query "[0].{appId:appId, id:id}" -o json
```

**If the output contains a result** (non-null, non-empty array):
- Extract `appId` → save as APP_CLIENT_ID
- Extract `id` → save as APP_OBJECT_ID
- Skip to B.4 (scope may already exist, but B.4 is idempotent)

**If the output is `[]` or `null`**: proceed to B.2.

**If the command fails**: retry once. If still fails, show the error
to the user and stop.

---

## B.2 — Create app registration

**Message:**

I'm going to create an app registration called **{APP_DISPLAY_NAME}** in
your Entra tenant. This lets the Power Platform connector authenticate
employees through Microsoft when they use the agent.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Create app registration",
    "question": "OK to create this app registration in your Entra tenant?",
    "options": [
      { "label": "Yes, create it", "recommended": true },
      { "label": "No, I'll do it manually" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chose "No, I'll do it manually":**

**Message:**

No problem. Create the app registration manually:

1. Open https://entra.microsoft.com
2. Go to **App registrations** → **New registration**
3. Name: `{APP_DISPLAY_NAME}`
4. Supported account types: **Single tenant**
5. Click **Register**

Copy the **Application (client) ID** and **Object ID** from the
overview page and paste them here.

**End message.**

Wait for the user to provide the IDs. Save as APP_CLIENT_ID and
APP_OBJECT_ID. Skip to B.3.

**If the user chose "Yes, create it":**

**Message (do NOT wait for user response — continue immediately):**

Creating the app registration...

**End message.**

Run in the terminal:

```
az ad app create --display-name "{APP_DISPLAY_NAME}" --sign-in-audience AzureADMyOrg --query "{appId:appId, id:id}" -o json
```

Extract from the output:
- `appId` → save as APP_CLIENT_ID
- `id` → save as APP_OBJECT_ID

**If the command fails**:

If the error mentions "Insufficient privileges" or "Authorization_RequestDenied":

**Message:**

Your account doesn't have permission to create app registrations. You need
the **Application Administrator** or **Global Administrator** role in
your Entra tenant.

Ask your IT admin to grant this role, then come back and run `/connect`
again.

**End message.**

Stop here. Do not proceed.

For any other error, retry once. If still fails, show the error and stop.

**Immediately save APP_CLIENT_ID and APP_OBJECT_ID** to
`my/connect/servicenow/config.json` under the relevant auth section
(e.g., `entra.appClientId`, `entra.appObjectId`). This preserves state
if the session breaks before the calling file's final config save.

---

## B.3 — Add optional claims (email, upn)

Before running any commands in B.3–B.6, show this message and get
confirmation:

**Message:**

App created. Now I'll configure it — adding token claims, exposing
an API scope, and pre-authorizing the Power Platform connector. This
involves a few commands and takes about 15 seconds.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Configure app",
    "question": "OK to configure the app registration?",
    "options": [
      { "label": "Go ahead", "recommended": true },
      { "label": "Wait, let me check something first" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user chose "Wait", pause and wait for them to say they're ready.
If they chose "Go ahead", proceed.

Build a JSON temp file and use `az rest` to patch the application. This
is more reliable than inline JSON on Windows/PowerShell.

Run in the terminal:

```powershell
$body = @{optionalClaims=@{accessToken=@(
  @{name="email";essential=$false},
  @{name="upn";essential=$false}
)}} | ConvertTo-Json -Depth 5
$body | Out-File "$env:TEMP\ess-claims.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-claims.json"
```

Replace `{APP_OBJECT_ID}` with the actual value.

**Verify** — run in the terminal:

```
az ad app show --id {APP_OBJECT_ID} --query "optionalClaims.accessToken[].name" -o json
```

Expected output: `["email", "upn"]`

**If verification fails**: retry the PATCH once. If still fails:

**Message:**

I couldn't configure the token claims automatically. You can add them
manually:

1. Open https://entra.microsoft.com
2. Go to **App registrations** → find your app → **Token configuration**
3. Click **Add optional claim** → **Access** → select **email** and **upn**
4. Click **Add**

Type **done** when you've added the claims.

**End message.**

Wait for the user, then re-verify.

---

## B.4 — Set identifier URI and expose API scope

**Step B.4a** — Set the identifier URI. Run in the terminal:

```
az ad app update --id {APP_OBJECT_ID} --identifier-uris "api://{APP_CLIENT_ID}"
```

**Step B.4b** — Generate a GUID for the scope. Run in the terminal:

```
python -c "import uuid; print(uuid.uuid4())"
```

Save the output as SCOPE_GUID.

**Step B.4c** — Expose the `user_impersonation` scope. Run in the terminal:

```powershell
$body = @{api=@{oauth2PermissionScopes=@(@{
  adminConsentDescription="Access ServiceNow on behalf of the user"
  adminConsentDisplayName="Access ServiceNow"
  id="{SCOPE_GUID}"
  isEnabled=$true
  type="User"
  userConsentDescription="Access ServiceNow on your behalf"
  userConsentDisplayName="Access ServiceNow"
  value="user_impersonation"
})}} | ConvertTo-Json -Depth 5
$body | Out-File "$env:TEMP\ess-scope.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-scope.json"
```

Replace `{APP_OBJECT_ID}` and `{SCOPE_GUID}` with the actual values.

**Verify** — run in the terminal:

```
az ad app show --id {APP_OBJECT_ID} --query "api.oauth2PermissionScopes[0].value" -o tsv
```

Expected output: `user_impersonation`

**If verification fails**: retry the PATCH once. If still fails:

**Message:**

I couldn't expose the API scope automatically. You can do it manually:

1. Open https://entra.microsoft.com
2. Go to **App registrations** → find your app → **Expose an API**
3. Set **Application ID URI** to `api://{APP_CLIENT_ID}`
4. Click **Add a scope** → value: `user_impersonation` → Who can consent:
   **Admins and users** → fill in the display names → **Add scope**

Type **done** when you've added the scope.

**End message.**

Wait for the user, then re-verify.

---

## B.5 — Pre-authorize the Power Platform connector

The Power Platform ServiceNow (and Workday) connector uses the first-party
app `c26b24aa-7874-4e06-ad55-7d06b1f79b63`. Pre-authorizing it allows
token requests without additional consent prompts.

Run in the terminal:

```powershell
$body = @{api=@{preAuthorizedApplications=@(@{
  appId="c26b24aa-7874-4e06-ad55-7d06b1f79b63"
  delegatedPermissionIds=@("{SCOPE_GUID}")
})}} | ConvertTo-Json -Depth 5
$body | Out-File "$env:TEMP\ess-preauth.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-preauth.json"
```

Replace `{APP_OBJECT_ID}` and `{SCOPE_GUID}` with the actual values.

**Verify** — run in the terminal:

```
az ad app show --id {APP_OBJECT_ID} --query "api.preAuthorizedApplications[0].appId" -o tsv
```

Expected output: `c26b24aa-7874-4e06-ad55-7d06b1f79b63`

**If verification fails**: retry the PATCH once. If still fails:

**Message:**

I couldn't pre-authorize the connector automatically. You can do it
manually:

1. Open https://entra.microsoft.com
2. Go to **App registrations** → find your app → **Expose an API**
3. Click **Add a client application**
4. Enter Client ID: `c26b24aa-7874-4e06-ad55-7d06b1f79b63`
5. Check the `user_impersonation` scope → **Add application**

Type **done** when you're finished.

**End message.**

Wait for the user, then re-verify.

---

## B.6 — Create service principal

**Step B.6a** — Check if SP already exists. Run in the terminal:

```
az ad sp show --id {APP_CLIENT_ID} --query "appId" -o tsv 2>$null
```

**If it returns** APP_CLIENT_ID (or any output): SP exists. Skip B.6b.

**If it fails or returns nothing**: proceed to B.6b.

**Step B.6b** — Create the SP. Run in the terminal:

```
az ad sp create --id {APP_CLIENT_ID} --query "appId" -o tsv
```

**If the command fails** because the SP already exists, that's fine —
proceed.

For any other error, retry once, then show the error and stop.

---

## B.7 — Done

The Entra app registration is complete. Return these values to the
calling file:
- APP_CLIENT_ID
- APP_OBJECT_ID
- SCOPE_GUID

**Message:**

✅ Entra app registration configured:

- **App**: {APP_DISPLAY_NAME}
- **Scope**: `user_impersonation` exposed
- **Power Platform connector**: pre-authorized
- **Service principal**: created

**End message.**

The calling file will continue with integration-specific configuration.

---

## B.8 — Cleanup on failure (reference)

This section is NOT part of the normal flow. Use it only if a step
after B.2 fails permanently and the user wants to start over.

If the app was created in B.2 but a later step (B.3–B.6) cannot be
completed:

**Message:**

If you need to start over, you can delete the app registration I
created:

```
az ad app delete --id {APP_OBJECT_ID}
```

Then run `/connect` again to restart the process.

**End message.**

Stop here.
