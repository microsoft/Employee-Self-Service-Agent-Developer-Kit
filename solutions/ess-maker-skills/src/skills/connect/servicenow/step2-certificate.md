# ServiceNow Step 2: Certificate Auth Setup

**This file is ONLY for Certificate (service-to-service) authentication.
Do not use for Entra ID User Login, OAuth2, or Basic.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "APP_A_CLIENT_ID = ..." or "OIDC_ENTITY_SYS_ID = ..." in
chat. The user should only see Message blocks and tool output tables.

Read `.local/connect/servicenow/config.json` for INSTANCE_NAME.

**Do NOT ask the user any questions or show any messages before reading
login.md in section 2.1.** Go directly to 2.1.

---

## 2.1 — Azure login

Read `src/skills/connect/azure/login.md` and follow it.

When it completes, you will have TENANT_ID.

---

## 2.2 — Create App A: Entra app registration (OIDC resource)

Certificate authentication requires **two** Entra app registrations.
App A represents ServiceNow as an OIDC resource in Entra. App B (created
in 2.4) is the service account that holds the certificate credential.

Set APP_DISPLAY_NAME to
`ESS Copilot - ServiceNow Certificate ({INSTANCE_NAME})`.

Read `src/skills/connect/azure/app-registration.md` and follow it,
passing APP_DISPLAY_NAME and TENANT_ID.

When it completes, you will have APP_A_CLIENT_ID, APP_A_OBJECT_ID,
and SCOPE_GUID.

**Immediately save APP_A_CLIENT_ID and APP_A_OBJECT_ID** to
`.local/connect/servicenow/config.json` under `certificate.appAClientId`
and `certificate.appAObjectId`.

The certificate auth docs require an additional `aud` optional claim
on App A (beyond the `email` and `upn` already added by
`app-registration.md`). Patch it now.

Run in the terminal:

```powershell
$body = @{optionalClaims=@{accessToken=@(
  @{name="aud";essential=$false},
  @{name="email";essential=$false},
  @{name="upn";essential=$false}
)}} | ConvertTo-Json -Depth 5
$body | Out-File "$env:TEMP\ess-claims.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_A_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-claims.json"
```

Replace `{APP_A_OBJECT_ID}` with the actual value.

**Verify** — run in the terminal:

```
az ad app show --id {APP_A_OBJECT_ID} --query "optionalClaims.accessToken[].name" -o json
```

Expected output: `["aud", "email", "upn"]`

**If verification fails**: retry the PATCH once. If still fails, show
manual instructions:

**Message:**

I couldn't add the audience claim automatically. You can add it
manually:

1. Open https://entra.microsoft.com
2. Go to **App registrations** → find your app → **Token configuration**
3. Click **Add optional claim** → **Access** → select **aud**
4. Click **Add**

Type **done** when you've added the claim.

**End message.**

Wait for the user, then re-verify.

---

## 2.3 — Generate or collect certificate

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Certificate",
    "question": "Do you have a .pfx certificate for the service account, or should I generate a self-signed one for testing?",
    "options": [
      { "label": "Generate self-signed certificate", "description": "Quick setup for dev/test", "recommended": true },
      { "label": "I have my own certificate" }
    ],
    "allowFreeformInput": false
  }
]
```

### If the user chose "Generate self-signed certificate":

**Message (do NOT wait for user response — continue immediately):**

Generating a self-signed certificate...

**End message.**

Run in the terminal:

```powershell
$password = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
$cert = New-SelfSignedCertificate -Subject "CN=ESS Copilot ServiceNow ({INSTANCE_NAME})" -CertStoreLocation "Cert:\CurrentUser\My" -KeyExportPolicy Exportable -KeySpec Signature -KeyLength 2048 -NotAfter (Get-Date).AddYears(2)
$pfxPath = "$env:TEMP\ess-copilot-servicenow-{INSTANCE_NAME}.pfx"
$cerPath = "$env:TEMP\ess-copilot-servicenow-{INSTANCE_NAME}.cer"
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password (ConvertTo-SecureString -String $password -Force -AsPlainText)
Export-Certificate -Cert $cert -FilePath $cerPath
Write-Output "PFX: $pfxPath"
Write-Output "CER: $cerPath"
Write-Output "Password: $password"
Write-Output "Thumbprint: $($cert.Thumbprint)"
Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)"
```

Replace `{INSTANCE_NAME}` with the actual instance name.

From the terminal output, extract:
- The PFX path → save as CERT_PFX_PATH
- The CER path → save as CERT_CER_PATH
- The password → save as CERT_PASSWORD (session memory only — do NOT write to disk)
- The thumbprint → save as CERT_THUMBPRINT

**Save CERT_PFX_PATH, CERT_CER_PATH, and CERT_THUMBPRINT** to
`.local/connect/servicenow/config.json` under `certificate.certPfxPath`,
`certificate.certCerPath`, and `certificate.certThumbprint`.

**Do NOT write CERT_PASSWORD to disk.** The PFX password is a reusable
credential — persisting it to `.local/connect/servicenow/config.json` would
leave it sitting in the workspace even after the session ends. Keep it
in session memory for the rest of this flow. If the session breaks,
resume code in step3-certificate.md will re-prompt the user.

**If the command fails**: show the error and suggest the user generate
a certificate manually using their organization's certificate process,
then come back and choose "I have my own certificate".

**Message:**

✅ Certificate generated:

| Item | Location |
|------|----------|
| **PFX file** | `{CERT_PFX_PATH}` |
| **CER file** | `{CERT_CER_PATH}` |
| **Password** | `{CERT_PASSWORD}` |

> **Save the password in your password manager now** — it is NOT
> persisted by this kit, and you'll need it when installing the
> extension pack and on any future `/connect` resume. The certificate
> expires in 2 years.

**End message.**

Proceed to 2.4.

### If the user chose "I have my own certificate":

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "PFX path",
    "question": "What's the full path to your .pfx file?"
  },
  {
    "header": "PFX password",
    "question": "What's the password for the .pfx file?"
  },
  {
    "header": "CER path",
    "question": "What's the full path to your .cer file (public certificate)? Leave blank if you only have the .pfx."
  }
]
```

Save the PFX path as CERT_PFX_PATH, the password as CERT_PASSWORD, and
the CER path as CERT_CER_PATH.

**If CERT_CER_PATH is blank**: export the .cer from the .pfx. Run in the
terminal:

```powershell
$pfx = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2("{CERT_PFX_PATH}", "{CERT_PASSWORD}")
$cerPath = "$env:TEMP\ess-copilot-servicenow-{INSTANCE_NAME}.cer"
[System.IO.File]::WriteAllBytes($cerPath, $pfx.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
Write-Output "CER: $cerPath"
```

Replace `{CERT_PFX_PATH}` and `{CERT_PASSWORD}` with the actual values.

Extract the CER path from the output → save as CERT_CER_PATH.

**If the export fails**: show the error and ask the user to provide the
.cer file path directly.

**Save CERT_PFX_PATH and CERT_CER_PATH** to
`.local/connect/servicenow/config.json` under `certificate.certPfxPath`
and `certificate.certCerPath`. Compute and save CERT_THUMBPRINT to
`certificate.certThumbprint` (use
`(Get-PfxCertificate -FilePath '{CERT_PFX_PATH}').Thumbprint` if not
already captured).

**Do NOT write CERT_PASSWORD to disk.** Keep it in session memory only.
Resume in step3-certificate.md re-prompts.

Proceed to 2.4.

---

## 2.4 — Create App B: Service account app registration

App B is the connector service account — it holds the certificate
credential and is used as the Client ID when configuring the Power
Platform connector.

Set APP_B_DISPLAY_NAME to
`ESS Copilot - ServiceNow Service Account ({INSTANCE_NAME})`.

**First, check if the app already exists** (idempotency). Run in the
terminal:

```
az ad app list --display-name "{APP_B_DISPLAY_NAME}" --query "[0].{appId:appId, id:id}" -o json
```

Replace `{APP_B_DISPLAY_NAME}` with the actual value.

**If the output contains a result** (non-null, non-empty array):
- Extract `appId` → save as APP_B_CLIENT_ID
- Extract `id` → save as APP_B_OBJECT_ID
- Skip to 2.5

**If the output is `[]` or `null`**: proceed to create it.

**Message:**

Now I'll create a second app registration for the service account. This
one holds the certificate credential and acts as the connector's identity.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Create service account app",
    "question": "OK to create the service account app registration in your Entra tenant?",
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
3. Name: `{APP_B_DISPLAY_NAME}`
4. Supported account types: **Single tenant**
5. Click **Register**

Copy the **Application (client) ID** and **Object ID** from the
overview page and paste them here.

**End message.**

Wait for the user to provide the IDs. Save as APP_B_CLIENT_ID and
APP_B_OBJECT_ID. Skip to 2.5.

**If the user chose "Yes, create it":**

**Message (do NOT wait for user response — continue immediately):**

Creating the service account app registration...

**End message.**

Run in the terminal:

```
az ad app create --display-name "{APP_B_DISPLAY_NAME}" --sign-in-audience AzureADMyOrg --query "{appId:appId, id:id}" -o json
```

Replace `{APP_B_DISPLAY_NAME}` with the actual value.

Extract from the output:
- `appId` → save as APP_B_CLIENT_ID
- `id` → save as APP_B_OBJECT_ID

**If the command fails**:

If the error mentions "Insufficient privileges" or
"Authorization_RequestDenied":

**Message:**

Your account doesn't have permission to create app registrations. You
need the **Application Administrator** or **Global Administrator** role
in your Entra tenant.

Ask your IT admin to grant this role, then come back and run `/connect`
again.

**End message.**

Stop here. Do not proceed.

For any other error, retry once. If still fails, show the error and stop.

**Immediately save APP_B_CLIENT_ID and APP_B_OBJECT_ID** to
`.local/connect/servicenow/config.json` under `certificate.appBClientId`
and `certificate.appBObjectId`.

---

## 2.5 — Upload certificate to App B

Upload the public certificate (.cer) to App B's credentials via the
Graph API. Run in the terminal:

```powershell
$cerBytes = [System.IO.File]::ReadAllBytes("{CERT_CER_PATH}")
$base64 = [System.Convert]::ToBase64String($cerBytes)
$body = @{keyCredentials=@(@{
  displayName="ESS Copilot Certificate"
  type="AsymmetricX509Cert"
  usage="Verify"
  key=$base64
})} | ConvertTo-Json -Depth 5
$body | Out-File "$env:TEMP\ess-cert-upload.json" -Encoding utf8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_B_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-cert-upload.json"
```

Replace `{CERT_CER_PATH}` and `{APP_B_OBJECT_ID}` with the actual values.

**Verify** — run in the terminal:

```
az ad app credential list --id {APP_B_OBJECT_ID} --cert --query "[0].{keyId:keyId, displayName:displayName}" -o json
```

Expected output: a JSON object with `keyId` (a GUID) and
`displayName` of `"ESS Copilot Certificate"`.

**If verification fails**: retry the upload once. If still fails:

**Message:**

I couldn't upload the certificate automatically. You can do it manually:

1. Open https://entra.microsoft.com
2. Go to **App registrations** → find **{APP_B_DISPLAY_NAME}**
3. Go to **Certificates & secrets** → **Certificates** tab
4. Click **Upload certificate** → select your `.cer` file → **Add**

Type **done** when you've uploaded the certificate.

**End message.**

Wait for the user, then re-verify.

---

## 2.6 — Create service principal for App B

The service principal's **object ID** is used as the ServiceNow system
user's User ID. This is different from the app registration's object ID.

**Step 2.6a** — Check if SP already exists. Run in the terminal:

```
az ad sp show --id {APP_B_CLIENT_ID} --query "id" -o tsv 2>$null
```

**If it returns** a GUID: save it as APP_B_SP_OBJECT_ID. Skip 2.6b.

**If it fails or returns nothing**: proceed to 2.6b.

**Step 2.6b** — Create the SP. Run in the terminal:

```
az ad sp create --id {APP_B_CLIENT_ID} --query "id" -o tsv
```

Save the output as APP_B_SP_OBJECT_ID.

**If the command fails** because the SP already exists, query it again:

```
az ad sp show --id {APP_B_CLIENT_ID} --query "id" -o tsv
```

Save the output as APP_B_SP_OBJECT_ID.

For any other error, retry once, then show the error and stop.

**Immediately save APP_B_SP_OBJECT_ID** to
`.local/connect/servicenow/config.json` under
`certificate.appBSpObjectId`.

---

## 2.7 — Register OIDC provider entity in ServiceNow

**Message:**

Next I'll configure the OIDC authentication link between Entra and
ServiceNow. This creates an OIDC provider record and updates the
claims mapping in your ServiceNow instance.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Configure OIDC",
    "question": "OK to set up OIDC authentication in ServiceNow?",
    "options": [
      { "label": "Go ahead", "recommended": true },
      { "label": "Wait" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user chose "Wait", pause and wait for them to say they're ready.
If they chose "Go ahead", proceed.

First, check if an OIDC entity already exists for this app (idempotency).

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="oauth_oidc_entity", query="nameLIKEESS Copilot", fields="sys_id,name,client_id", limit=5)
```

**If a result exists** whose `client_id` matches APP_A_CLIENT_ID: extract
its `sys_id` as OIDC_ENTITY_SYS_ID. Skip to 2.8.

**If no match**: create a new one.

Call the ServiceNow MCP `register_oidc_provider` tool.

**Pre-step:** OIDC verification with Entra ID does not actually use the
client secret (ID tokens are verified via the JWKS endpoint), but the
ServiceNow record requires the field to be non-empty. Set a sentinel
env var first so the MCP server can read it:

In the same VS Code terminal where the ServiceNow MCP server runs (or
restart the MCP after setting it):

```
$env:SERVICENOW_OIDC_CLIENT_SECRET_NOT_USED = "not-used"
```

Then call the tool:

```
register_oidc_provider(
  name="Microsoft Entra ID - ESS Copilot Certificate",
  client_id="{APP_A_CLIENT_ID}",
  client_secret_env_var="SERVICENOW_OIDC_CLIENT_SECRET_NOT_USED",
  well_known_url="https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration"
)
```

Replace `{APP_A_CLIENT_ID}` and `{TENANT_ID}` with the actual values.

Extract `sys_id` from the response → save as OIDC_ENTITY_SYS_ID.

**If the call fails**: retry once. If still fails, show the error and
suggest manual creation:

**Message:**

I couldn't register the OIDC provider automatically. You can do it
in ServiceNow:

1. Go to **System OAuth** → **Application Registry**
2. Click **New** → **Configure an OIDC provider to verify ID tokens**
3. Enter:
   - **Name**: `Microsoft Entra ID - ESS Copilot Certificate`
   - **Client ID**: `{APP_A_CLIENT_ID}`
   - **Client Secret**: `not-used`
   - **OIDC Metadata URL**: `https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration`
4. Click **Submit**

Type **done** when you've created it.

**End message.**

Wait for the user. Then query again to get OIDC_ENTITY_SYS_ID.

---

## 2.8 — Create OIDC provider configuration (claims mapping)

Certificate authentication uses its **own** OIDC provider configuration
record — separate from any existing Entra ID User Login or Graph
Connector configs. This avoids overwriting claims mappings used by other
connection types.

Certificate auth maps the token's `oid` claim (object ID) to the
ServiceNow `user_id` field. This is different from User Login which
maps `upn` to `user_name`.

First, check if a certificate-specific config already exists:

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="oidc_provider_configuration", query="nameLIKECertificate", fields="sys_id,name,user_claim,user_field,oidc_url", limit=5)
```

**If a matching record exists** with `user_claim=oid` and
`user_field=user_id`: extract its `sys_id` as OIDC_CONFIG_SYS_ID.
Skip to 2.9.

**If no match**: create a new config.

Call the ServiceNow MCP `create_record` tool:

```
create_record(table="oidc_provider_configuration", data="{\"name\": \"Microsoft Entra ID - ESS Copilot Certificate\", \"oidc_url\": \"https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration\", \"oidc_config_cache_life_span\": \"120\", \"user_claim\": \"oid\", \"user_field\": \"user_id\", \"enable_jti_verification\": \"false\"}")
```

Replace `{TENANT_ID}` with the actual value.

Extract `sys_id` from the response → save as OIDC_CONFIG_SYS_ID.

**Immediately save OIDC_CONFIG_SYS_ID** to
`.local/connect/servicenow/config.json` under
`certificate.oidcConfigSysId`.

**If create returns 403**: fall back to querying for the built-in
"Azure AD" config and updating it:

```
query_table(table="oidc_provider_configuration", query="nameLIKEAzure", fields="sys_id,name,user_claim,user_field", limit=5)
```

Find the record, save its `sys_id` as OIDC_CONFIG_SYS_ID.

**Before updating the fallback record**, check the current values.
If `user_claim` is already set to `upn` and `user_field` is set to
`user_name`, an existing Entra ID User Login configuration is active.

If the current values are `upn` / `user_name`:

**Message:**

⚠️ I couldn't create a separate OIDC config for certificate auth
(your ServiceNow instance restricts new records on this table), so
I need to update the existing Azure AD configuration.

The existing config has claims set for **Entra ID User Login**
(`upn` → `user_name`). Certificate authentication requires
**different** claims (`oid` → `user_id`). Updating this will
**break any existing Entra ID User Login connections** on this
instance.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Overwrite claims",
    "question": "Continue and overwrite the existing claims mapping?",
    "options": [
      { "label": "Yes, overwrite" },
      { "label": "No, stop here" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user chose "No, stop here": stop. Do not proceed.

If the user chose "Yes, overwrite" (or the current values were not
`upn` / `user_name`): continue.

Update the fallback record:

```
update_record(table="oidc_provider_configuration", sys_id="{OIDC_CONFIG_SYS_ID}", data="{\"oidc_url\": \"https://login.microsoftonline.com/{TENANT_ID}/.well-known/openid-configuration\", \"user_claim\": \"oid\", \"user_field\": \"user_id\"}")
```

Replace `{OIDC_CONFIG_SYS_ID}` and `{TENANT_ID}` with the actual values.

**If the update also fails**: retry once. If still fails, show the
error and suggest the user check that the Multi-Provider SSO plugin
(`com.snc.integration.sso.multi`) is active, and that their admin
account has sufficient privileges.

---

## 2.9 — Link OIDC config to entity

Call the ServiceNow MCP `update_record` tool:

```
update_record(table="oauth_oidc_entity", sys_id="{OIDC_ENTITY_SYS_ID}", data="{\"oidc_provider_configuration\": \"{OIDC_CONFIG_SYS_ID}\"}")
```

Replace `{OIDC_ENTITY_SYS_ID}` and `{OIDC_CONFIG_SYS_ID}` with the
actual values.

**If the update fails**: retry once. If still fails, show the error
and tell the user to link them manually in ServiceNow admin.

---

## 2.10 — Create ServiceNow system user for App B

Certificate authentication uses a system user in ServiceNow whose
User ID matches the service principal's object ID. This user is
marked as "Web service access only".

First, check if the user already exists (idempotency).

Call the ServiceNow MCP `query_table` tool:

```
query_table(table="sys_user", query="user_name={APP_B_SP_OBJECT_ID}", fields="sys_id,user_name,active", limit=1)
```

Replace `{APP_B_SP_OBJECT_ID}` with the actual value.

**If a matching user is found**: proceed to 2.11.

**If no matching user is found**:

Call the ServiceNow MCP `create_record` tool:

```
create_record(table="sys_user", data="{\"user_name\": \"{APP_B_SP_OBJECT_ID}\", \"first_name\": \"ESS Copilot\", \"last_name\": \"Service Account\", \"active\": \"true\", \"web_service_access_only\": \"true\"}")
```

Replace `{APP_B_SP_OBJECT_ID}` with the actual value.

Save the `sys_id` from the response as CREATED_SVC_USER_SYS_ID.

**Immediately save CREATED_SVC_USER_SYS_ID** to
`.local/connect/servicenow/config.json` under
`certificate.createdSvcUserSysId`. This ensures the created user is
tracked for cleanup if later steps fail.

**Message (do NOT wait for user response — continue immediately):**

Created a ServiceNow system user for the service account. This user is
set to "Web service access only" and is used by the certificate-based
connector.

**End message.**

**If the create_record call fails**: show the error and suggest the user
create the user manually:

**Message:**

I couldn't create the system user automatically. You can do it in
ServiceNow:

1. Go to **User Administration** → **Users** → **New**
2. Enter:
   - **User ID**: `{APP_B_SP_OBJECT_ID}`
   - **First name**: `ESS Copilot`
   - **Last name**: `Service Account`
   - Check **Web service access only**
3. Click **Submit**

Type **done** when you've created the user.

**End message.**

Wait for the user. Then proceed to 2.11.

---

## 2.11 — Save config and display results

Update `.local/connect/servicenow/config.json` — add a `certificate` object
(merge with any fields already saved in earlier steps):

```json
{
  "certificate": {
    "tenantId": "{TENANT_ID}",
    "appAClientId": "{APP_A_CLIENT_ID}",
    "appAObjectId": "{APP_A_OBJECT_ID}",
    "scopeGuid": "{SCOPE_GUID}",
    "appADisplayName": "{APP_DISPLAY_NAME}",
    "appBClientId": "{APP_B_CLIENT_ID}",
    "appBObjectId": "{APP_B_OBJECT_ID}",
    "appBSpObjectId": "{APP_B_SP_OBJECT_ID}",
    "appBDisplayName": "{APP_B_DISPLAY_NAME}",
    "certPfxPath": "{CERT_PFX_PATH}",
    "certCerPath": "{CERT_CER_PATH}",
    "certThumbprint": "{CERT_THUMBPRINT}",
    "oidcEntitySysId": "{OIDC_ENTITY_SYS_ID}",
    "oidcConfigSysId": "{OIDC_CONFIG_SYS_ID}"
  }
}
```

**Do NOT add `certPassword` to this object.** The PFX password stays in
session memory only. step3-certificate.md re-prompts on resume.

If CREATED_SVC_USER_SYS_ID was set (user was created in step 2.10),
also add:
```json
{
  "certificate": {
    "createdSvcUserSysId": "{CREATED_SVC_USER_SYS_ID}"
  }
}
```

Update `.local/connect/servicenow/tasks.md` — change step 2 from
`- [ ]` to `- [x]`.

**Message:**

✅ Certificate connection secured — both apps registered, OIDC
configured, and system user created.

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ✅ |
| 3 | Extension installed | ⬜ |
| 4 | Connection verified | ⬜ |

Here are the values you'll need for the next step:

| Field | Value |
|-------|-------|
| **Authentication Type** | Microsoft Entra ID OAuth using Certificate |
| **Instance Name** | `{INSTANCE_NAME}` |
| **Tenant ID** | `{TENANT_ID}` |
| **Client ID** | `{APP_B_CLIENT_ID}` |
| **Resource URI** | `{APP_A_CLIENT_ID}` |
| **Client Secret** | Browse to `{CERT_PFX_PATH}` |
| **Certificate password** | `{CERT_PASSWORD}` |

Ready to install the integration in Copilot Studio? Type **go** to
continue.

**End message.**

Wait for the user. Then read
`src/skills/connect/servicenow/step3-certificate.md` and follow it.

---

## 2.12 — Cleanup on failure (reference)

This section is NOT part of the normal flow. Use it only if a step
fails permanently and the user wants to start over.

If a system user was created in 2.10 (CREATED_SVC_USER_SYS_ID is set),
it can be deactivated:

```
update_record(table="sys_user", sys_id="{CREATED_SVC_USER_SYS_ID}", data="{\"active\": \"false\"}")
```

If an OIDC entity was created in 2.7 (OIDC_ENTITY_SYS_ID is set), it
can be deleted:

```
delete_record(table="oauth_oidc_entity", sys_id="{OIDC_ENTITY_SYS_ID}")
```

If App B was created in 2.4 (APP_B_OBJECT_ID is set):

```
az ad app delete --id {APP_B_OBJECT_ID}
```

If App A was created in 2.2 (APP_A_OBJECT_ID is set):

```
az ad app delete --id {APP_A_OBJECT_ID}
```

Certificate files at CERT_PFX_PATH and CERT_CER_PATH can be deleted
manually.

**Message:**

If you need to start over, you can clean up the resources I created:

```
az ad app delete --id {APP_B_OBJECT_ID}
az ad app delete --id {APP_A_OBJECT_ID}
```

Then run `/connect` again to restart the process.

**End message.**

Stop here.
