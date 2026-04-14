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

---

## B.3 — Add optional claims (email, upn)

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

✅ Entra app registration configured.

**End message.**

The calling file will continue with integration-specific configuration.
