<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 4 — Provision the ServiceNow Entra User Sign-In Path

Role: **App / Cloud Application Administrator** for the Microsoft Entra work, and
**ServiceNow Administrator** with elevated **security_admin** for the
ServiceNow-side attestations. This skill configures the delegated Microsoft Entra
OIDC application that lets employees sign in to ServiceNow with their Microsoft
identity. It owns master-checklist rows **S4.1 through S4.4**.

Depends on skill 3 (ServiceNow connection basics) having captured `authType ==
"entra_user"`, the ServiceNow instance, maker permissions, and the user-presence
attestation. It is split deliberately: Entra app registration is programmatic;
ServiceNow OIDC provider registration and user mapping are **guided attestation**
only.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names, Step IDs, checkpoint
IDs, object IDs, or hidden checklist comments in chat.

**Graph-first with portal fallback for Entra.** Each Entra configuration step is
attempted through Microsoft Graph / Azure CLI. If Graph fails because of tenant
policy or permissions, show the portal fallback and keep the row in progress until
the isolated checkpoint passes.

**Never automate ServiceNow OIDC internals.** For the ServiceNow-side rows, do not
call ServiceNow MCP tools, admin APIs, table APIs, scripts, imports, or any other
automation to create or update OIDC provider, OIDC configuration, claim mapping,
or users. The ServiceNow administrator performs those actions in ServiceNow, then
the operator explicitly attests completion.

Use ServiceNow setup paths throughout: config `.local/connect/servicenow/config.json`
and working checklist `.local/setup/servicenow/tasks.md`. Apply
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) with those paths.

**Checkpoints this skill drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|------------|------|
| S4.1 | `SN-ENTRA-SCOPE-001` — Entra app, exposed scope, connector authorization, token claims | prog |
| S4.2 | `SN-ENTRA-CONSENT-001` — Microsoft Graph permissions consented | prog; escalate to manual if blocked |
| S4.3 | `SN-CONN-OIDC-001` — ServiceNow OIDC provider registered | attest |
| S4.4 | `SN-USERMAP-001` — Microsoft identity maps to the correct ServiceNow user | attest |

Run any one with:

```
python scripts/flightcheck/cli.py --checkpoint <ID>
```

**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a —
the compact result table and, for any `MANUAL` / `Warning` / `NotConfigured` row,
the full verification steps — **before** any attestation question. Single-checkpoint
runs never open the HTML report, so this in-chat render is the only place the user
sees the manual steps. Never ask the user to attest to steps they have not been
shown.

**Resume behavior.** On every resume, always re-run **S4.0** (Entra role gate) and
**S4.0b** (idempotent Entra app lookup) first before working the first incomplete
row. These steps rehydrate `SN_ENTRA_APP_ID`, `SN_ENTRA_APP_OBJECT_ID`,
`SN_ENTRA_APP_ID_URI`, `SN_ENTRA_SCOPE_GUID`, and `SN_TENANT_ID` for S4.1–S4.2.
After re-running them, skip any S4 row whose `setupStatus` state is already `done`.

---

## S4.0 — Role gate (App / Cloud Application Administrator)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
Entra work, with:

- `REQUIRED_ROLE` = `"Application Administrator"` (or Cloud Application
  Administrator / Privileged Role Administrator / Global Administrator / app owner)
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S4.1"`
- `ROLE_QUERY` = a Microsoft Graph directory-role membership check for the
  signed-in user:

  ```
  az rest --method GET --url "https://graph.microsoft.com/v1.0/me/memberOf?%24select=displayName" --query "value[].displayName" -o json
  ```

The role is held if the returned role names include **Application Administrator**,
**Cloud Application Administrator**, **Privileged Role Administrator**, or
**Global Administrator**. Treat `Insufficient privileges`,
`Authorization_RequestDenied`, and forbidden responses as "role not held". If the
query errors for an unrelated reason (network, not signed in), follow the gate's
retry-then-attest fallback — never assume pass.

If `GATE_RESULT` is `"stop"`:

- If `GATE_REASON` is `"delegated"` (the maker can't hold the role but another
  administrator will do the Entra work), **do not halt** — go to **S4.0a** and hand
  that administrator the full sign-in-app runbook, then resume on the Application
  (client) ID they return.
- For any other `"stop"` reason, **halt**.

Otherwise carry `GATE_EVIDENCE` forward and
persist it when S4.1/S4.2 rows are updated.

---

## S4.0a — Delegated administrator runbook (Entra sign-in app)

Reached only when the S4.0 gate returned `GATE_RESULT="stop"` with
`GATE_REASON="delegated"`: the maker lacks the Entra role, so a consent-capable
administrator performs the app registration and admin consent, then hands the
maker the resulting **Application (client) ID** to continue.

Give the administrator the complete step list in one message. Substitute
`{SN_APP_DISPLAY_NAME}` (`ESS Copilot - ServiceNow OIDC ({SN_INSTANCE_NAME})`) so
they name the app the way S4.0b later rehydrates it.

**Message:**

You don't need the admin role yourself — an administrator with **Application
Administrator**, **Cloud Application Administrator**, **Privileged Role
Administrator**, or **Global Administrator** can do the ServiceNow sign-in setup
once. Send them these steps, all in the Microsoft Entra admin center
(https://entra.microsoft.com):

1. **App registrations → New registration.** Name it
   `{SN_APP_DISPLAY_NAME}`, set **Supported account types** to *Accounts in this
   organizational directory only*, and register it. Copy the **Application
   (client) ID** — you'll paste it back here.
2. **Token configuration → Add optional claim → Access** — add **email** and
   **upn**.
3. **Expose an API** — set the Application ID URI to
   `api://<Application client ID>`, then **Add a scope** named
   `user_impersonation` (admin + user consent enabled).
4. **Expose an API → Add a client application** — add the Power Platform
   ServiceNow connector client ID `c26b24aa-7874-4e06-ad55-7d06b1f79b63` and
   authorize it for `user_impersonation`.
5. **API permissions → Add a permission → Microsoft Graph → Delegated
   permissions** — add **openid**, **profile**, and **User.Read**.
6. **API permissions → Grant admin consent for your tenant** — approve the
   consent prompt.

When the app exists, paste its **Application (client) ID** here and I'll verify
the configuration and continue.

**End message.**

Ask for the identifier with the `vscode_askQuestions` tool:

```json
[
  {
    "header": "ServiceNow sign-in app",
    "question": "Paste the Application (client) ID of the ServiceNow sign-in app the administrator created.",
    "options": [],
    "allowFreeformInput": true
  }
]
```

- If the user has no ID yet (empty / "not yet"), stop here — the administrator
  hasn't finished. They can resume this step later; on resume S4.0 runs again.
- On a GUID-shaped answer, **persist** it to `.local/connect/servicenow/config.json`
  (merge): `entra.appId` and `entra.appClientId` = the pasted ID. Record the
  handoff as `GATE_EVIDENCE = { "verifiedBy": "attested", "note": "Entra sign-in
  app created by delegated admin; client ID supplied by maker for S4.1/S4.2" }`.

Then continue to **S4.0b** (which re-resolves the object ID, App ID URI, and scope
GUID from the supplied `entra.appId`) and run S4.1's verification checkpoint
`SN-ENTRA-SCOPE-001` and S4.2's `SN-ENTRA-CONSENT-001` as usual. These checkpoints
are read-only Graph queries the maker can run without the admin role. If a
checkpoint can't be read (`MANUAL` / permission error), fall back to the
checklist-updater §U.2 attestation using the delegated-admin handoff as evidence —
never silently mark the row `done`.

---

## S4.0b — Load ServiceNow config and rehydrate the Entra app

Read `.local/connect/servicenow/config.json`. This skill expects skill 3 to have
captured the ServiceNow instance and `authType == "entra_user"`.

- Set `SN_INSTANCE_NAME` from the captured instance name, or derive it from the
  instance URL host (`https://dev12345.service-now.com` → `dev12345`).
- Set `SN_TENANT_ID` from `tenantId` or `entra.tenantId` when present. If absent,
  follow `../../connect/azure/login.md` to sign in and capture the tenant ID, then
  merge it into config as both `tenantId` and `entra.tenantId`.
- Set `SN_APP_DISPLAY_NAME` to `ESS Copilot - ServiceNow OIDC ({SN_INSTANCE_NAME})`.
- Read existing app fields from `entra.appId` / `entra.appClientId`,
  `entra.objectId` / `entra.appObjectId`, `entra.appIdUri`, and `entra.scopeGuid`.

**If config already has an app ID**, re-resolve the application object and scope so
later commands never rely on stale state:

```
az ad app list --filter "appId eq '{SN_ENTRA_APP_ID}'" --query "[0].{appId:appId,id:id,identifierUris:identifierUris,scopes:api.oauth2PermissionScopes}" -o json
```

If exactly one app is found, load object ID, App ID URI, and the existing
`user_impersonation` scope GUID, then merge them back to config. If no app is
found, keep the existing config values and continue with display-name lookup.

**If no usable app is loaded**, search by display name:

```
az ad app list --display-name "{SN_APP_DISPLAY_NAME}" --query "[].{appId:appId,id:id,identifierUris:identifierUris,scopes:api.oauth2PermissionScopes}" -o json
```

- **Exactly one match** → load it, resolve scope fields, and persist.
- **More than one match** → ask the user to choose by human-readable name or create
  a new app; never show object IDs.
- **No match** → S4.1 creates a new app.

**Persist** any rehydrated values to `.local/connect/servicenow/config.json`
(merge — keep other keys): `tenantId`, `entra.tenantId`, `entra.appId`,
`entra.appClientId`, `entra.objectId`, `entra.appObjectId`, `entra.appIdUri`,
`entra.scopeGuid`, and `entra.appDisplayName`.

Do not mark any row complete from S4.0b alone. It only prepares state.

---

## S4.1 — Create the ServiceNow sign-in app

Register or update the Entra OIDC application used for delegated user sign-in, then
expose the `user_impersonation` scope for the Power Platform ServiceNow connector.
This row is **idempotent**: re-running must not create a duplicate app.

**If S4.0b loaded an existing app**, skip app creation and continue with the
configuration checks below. If no app is loaded, create one.

**Message:**

I'm going to create the Microsoft Entra app registration that employees will use
to sign in to ServiceNow through the agent. If the app already exists, I'll reuse
it instead of creating a duplicate.

**End message.**

If creation is needed, run:

```
az ad app create --display-name "{SN_APP_DISPLAY_NAME}" --sign-in-audience AzureADMyOrg --query "{appId:appId,id:id}" -o json
```

Extract `appId` and `id`, create the service principal if needed, then persist the
app identity immediately:

```
az ad sp show --id {SN_ENTRA_APP_ID} --query "appId" -o tsv 2>$null
az ad sp create --id {SN_ENTRA_APP_ID} --query "appId" -o tsv
```

If creation fails because of insufficient privileges, show the shared role-gate
failure message and halt. For other errors, retry once. If it still fails, show the
error and stop without updating the row.

**Configure the app.** Attempt each sub-step through Graph; if any PATCH fails, use
the portal fallback in that sub-step, then re-check before proceeding.

1. **Token claims.** Ensure access tokens include the employee-identifying claims
   the connector and ServiceNow mapping need. `aud` is the token audience produced
   by the exposed API; add optional access-token claims for `email` and `upn`:

   ```powershell
   $body = @{optionalClaims=@{accessToken=@(
     @{name="email";essential=$false},
     @{name="upn";essential=$false}
   )}} | ConvertTo-Json -Depth 5
   $body | Out-File ".local\setup\servicenow\sn-claims.json" -Encoding utf8
   az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{SN_ENTRA_APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@.local\setup\servicenow\sn-claims.json"
   ```

   **Portal fallback:**
   **Message:**
   I couldn't add the token claims automatically. Open https://entra.microsoft.com
   → **App registrations** → the ServiceNow sign-in app → **Token configuration** →
   **Add optional claim** → **Access** → select **email** and **upn**, then add the
   claims. Type **done** when they're added.
   **End message.**
   Wait for the user, then continue.

2. **Expose the `user_impersonation` scope.** If the app already has a
   `user_impersonation` scope, reuse its GUID. Otherwise generate a new GUID and
   set the Application ID URI to `api://{SN_ENTRA_APP_ID}`:

   ```
   python -c "import uuid; print(uuid.uuid4())"
   az ad app update --id {SN_ENTRA_APP_OBJECT_ID} --identifier-uris "api://{SN_ENTRA_APP_ID}"
   ```

   Then patch the scope:

   ```powershell
   $body = @{api=@{oauth2PermissionScopes=@(@{
     adminConsentDescription="Access ServiceNow on behalf of the user"
     adminConsentDisplayName="Access ServiceNow"
     id="{SN_ENTRA_SCOPE_GUID}"
     isEnabled=$true
     type="User"
     userConsentDescription="Access ServiceNow on your behalf"
     userConsentDisplayName="Access ServiceNow"
     value="user_impersonation"
   })}} | ConvertTo-Json -Depth 5
   $body | Out-File ".local\setup\servicenow\sn-scope.json" -Encoding utf8
   az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{SN_ENTRA_APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@.local\setup\servicenow\sn-scope.json"
   ```

   **Portal fallback:**
   **Message:**
   I couldn't expose the sign-in scope automatically. Open https://entra.microsoft.com
   → **App registrations** → the ServiceNow sign-in app → **Expose an API** → set
   the Application ID URI to `api://{app-id}` → **Add a scope** named
   `user_impersonation`. Type **done** when the scope is added.
   **End message.**
   Wait, then re-read the app and capture the scope GUID.

3. **Pre-authorize the Power Platform ServiceNow connector.** Use connector app ID
   `c26b24aa-7874-4e06-ad55-7d06b1f79b63` — this is the ServiceNow connector, not
   the Workday connector:

   ```powershell
   $body = @{api=@{preAuthorizedApplications=@(@{
     appId="c26b24aa-7874-4e06-ad55-7d06b1f79b63"
     delegatedPermissionIds=@("{SN_ENTRA_SCOPE_GUID}")
   })}} | ConvertTo-Json -Depth 5
   $body | Out-File ".local\setup\servicenow\sn-preauth.json" -Encoding utf8
   az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{SN_ENTRA_APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@.local\setup\servicenow\sn-preauth.json"
   ```

   **Portal fallback:**
   **Message:**
   I couldn't pre-authorize the Power Platform ServiceNow connector automatically.
   Open https://entra.microsoft.com → **App registrations** → the ServiceNow sign-in
   app → **Expose an API** → **Add a client application** → enter the Power Platform
   ServiceNow connector client ID and select `user_impersonation`. Type **done**
   when it's added.
   **End message.**

4. **Add Microsoft Graph delegated permissions.** Add `openid`, `profile`, and
   `User.Read`:

   ```powershell
   $body = @{requiredResourceAccess=@(@{
     resourceAppId="00000003-0000-0000-c000-000000000000"
     resourceAccess=@(
       @{ id="37f7f235-527c-4136-accd-4a02d197296e"; type="Scope" }
       @{ id="14dad69e-099b-42c9-810b-d002981feec1"; type="Scope" }
       @{ id="e1fe6dd8-ba31-4d61-89e7-88639da4683d"; type="Scope" }
     )
   })} | ConvertTo-Json -Depth 6
   $body | Out-File ".local\setup\servicenow\sn-graphperms.json" -Encoding utf8
   az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{SN_ENTRA_APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@.local\setup\servicenow\sn-graphperms.json"
   ```

   **Portal fallback:**
   **Message:**
   I couldn't add the Microsoft Graph permissions automatically. Open
   https://entra.microsoft.com → **App registrations** → the ServiceNow sign-in app
   → **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated
   permissions** → add **openid**, **profile**, and **User.Read**. Type **done**
   when they're added.
   **End message.**

**Persist** to `.local/connect/servicenow/config.json` (merge): `tenantId`,
`entra.tenantId`, `entra.appId`, `entra.appClientId`, `entra.objectId`,
`entra.appObjectId`, `entra.appIdUri`, `entra.scopeGuid`, and
`entra.appDisplayName`.

**Message:**

Now I'll verify the ServiceNow sign-in app exposes its API permission, includes
the expected token claims, and lets the Power Platform ServiceNow connector use
that scope.

**End message.**

**Verify (SN-ENTRA-SCOPE-001):**

```
python scripts/flightcheck/cli.py --checkpoint SN-ENTRA-SCOPE-001
```

Immediately render the result per checklist-updater §U.0–U.0a.

- **`PASSED`** → update **S4.1** via [`../shared/checklist-updater.md`](../shared/checklist-updater.md)
  with `STEP_ID="S4.1"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`; persist
  `GATE_EVIDENCE`. Continue to S4.2.
- **`FAILED`** → the result names the missing app, claim, scope, connector
  authorization, or permission. Fix that item by Graph or portal fallback, then
  re-run the checkpoint. Keep S4.1 `in-progress` until it passes.
- **`WARNING` / `SKIPPED` / `MANUAL`** → show the full result, resolve the named
  gap, and re-run once. Do not complete S4.1 without a passing checkpoint.

---

## S4.2 — Grant admin consent

Grant tenant-wide admin consent for the Microsoft Graph delegated permissions the
ServiceNow sign-in app needs. Attempt programmatic consent first when possible; if
blocked by policy or role, escalate to a consent-capable administrator.

Try the consent command:

```
az ad app permission admin-consent --id {SN_ENTRA_APP_ID}
```

If it succeeds, verify immediately. If it fails because admin consent is blocked,
show the manual path.

**Message:**

Now I need an administrator to grant consent for the ServiceNow sign-in app's
Microsoft Graph permissions. Open https://entra.microsoft.com → **Enterprise
applications** → the ServiceNow sign-in app → **Permissions** → **Grant admin
consent for your tenant**, then approve the prompt. This needs a consent-capable
role such as Application Administrator, Cloud Application Administrator, Privileged
Role Administrator, or Global Administrator. Type **done** when consent is granted.

**End message.**

Wait for the user, then verify.

**Message:**

Now I'll confirm that admin consent was recorded for the ServiceNow sign-in app.

**End message.**

**Verify (SN-ENTRA-CONSENT-001):**

```
python scripts/flightcheck/cli.py --checkpoint SN-ENTRA-CONSENT-001
```

Immediately render the result per checklist-updater §U.0–U.0a.

- **`PASSED`** → update **S4.2** via [`../shared/checklist-updater.md`](../shared/checklist-updater.md)
  with `STEP_ID="S4.2"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`; persist
  immediately. Continue to S4.3.
- **`FAILED`** → consent is still missing. If the current operator lacks a
  consent-capable role, ask them to have an administrator grant consent in the
  portal, then re-run the checkpoint. Keep S4.2 `in-progress` until it passes.
- **`WARNING` / `SKIPPED`** → surface the result, confirm the app from S4.0b is the
  one being consented, then re-run. Do not complete S4.2 without a pass.

---

## S4.3 — Register the ServiceNow OIDC provider

This is a **ServiceNow-internal** security operation owned by a ServiceNow
administrator. The agent guides and verifies by attestation only. **Do not call
ServiceNow MCP/admin APIs to create, update, query, or link the OIDC provider or
configuration.**

First apply the shared [`permission-gate.md`](../shared/permission-gate.md) with:

- `REQUIRED_ROLE` = `"ServiceNow Administrator with elevated security_admin"`
- `GATE_MODE` = `"attested"`
- `STEP_ID` = `"S4.3"`
- `ROLE_QUERY` = not applicable

If `GATE_RESULT` is `"stop"`, halt. Otherwise carry the ServiceNow-admin gate
evidence forward for the row update.

**Message:**

Heads up: the next part configures OIDC trust inside ServiceNow, which is a
security operation. In ServiceNow you'll need to **elevate your role** first: click
your profile menu → **Elevate role** → select **security_admin**. If you don't see
a **New** button on the OAuth/Application Registry screens, your role isn't
elevated.

**End message.**

Run the checkpoint before asking for completion attestation so its manual steps are
shown in chat:

```
python scripts/flightcheck/cli.py --checkpoint SN-CONN-OIDC-001
```

Immediately render the result and all manual verification steps per
checklist-updater §U.0–U.0a. Then show the guided manual instructions below.

**Message:**

In ServiceNow, register Microsoft Entra as the OIDC provider for employee sign-in:

1. Go to **System OAuth** → **Application Registry**.
2. Select **New** → **Configure an OIDC provider to verify ID tokens**.
3. Use a meaningful name such as **Microsoft Entra ID - ESS Copilot**.
4. Set the **Client ID** to the ServiceNow sign-in app's application ID.
5. Set **Client Secret** to any non-empty placeholder value; ID token verification
   uses the metadata keys, not this secret.
6. Set the OIDC metadata URL to your Entra tenant's well-known OpenID configuration
   URL.
7. Set cache lifespan to **120**, application to **Global**, and leave JTI
   verification disabled unless your ServiceNow policy requires otherwise.
8. Save the provider.

Type **done** when the OIDC provider is registered in ServiceNow.

**End message.**

Wait for the user. Then ask the checklist-updater attestation question (or an
equivalent explicit acknowledgement) only after the manual steps above have been
shown.

Update **S4.3** via [`../shared/checklist-updater.md`](../shared/checklist-updater.md)
with `STEP_ID="S4.3"`, `GATE="attest"`, `CHECKPOINT_RESULT` equal to the isolated
checkpoint result, and `ACK=true` only on explicit confirmation. A checkpoint pass
or manual result alone never completes this row. Persist immediately.

---

## S4.4 — Map the sign-in identity to a ServiceNow user

Confirm the Microsoft identity claim emitted by Entra resolves to the matching
ServiceNow user. This is an attestation row, not a user-provisioning step. Skill 3
already handled user presence; **do not auto-create a test user** and do not call
ServiceNow APIs to query or modify `sys_user`.

Run the checkpoint first so any manual verification guidance is visible before the
attestation question:

```
python scripts/flightcheck/cli.py --checkpoint SN-USERMAP-001
```

Immediately render the result and all manual verification steps per
checklist-updater §U.0–U.0a.

**Message:**

Now confirm the Microsoft identity used for sign-in maps to the correct ServiceNow
user. In ServiceNow, review the OIDC provider configuration and make sure the user
claim and user field match your identity data. Common mappings are:

| Microsoft claim | ServiceNow user field |
| --- | --- |
| `upn` | `user_name` |
| `email` | `email` |

If your ServiceNow usernames are not email or UPN values, use a custom claim from
Entra and map it to the matching ServiceNow user field. Do not create a new test
user here; the real signed-in person should already exist from the earlier user
record check.

Type **done** when you've confirmed the claim maps to the correct active
ServiceNow user.

**End message.**

Wait for the user. Then ask the checklist-updater attestation question (or an
equivalent explicit acknowledgement). Treat `ACK=true` only when the operator
explicitly confirms the mapping and evidence are complete.

Update **S4.4** via [`../shared/checklist-updater.md`](../shared/checklist-updater.md)
with `STEP_ID="S4.4"`, `GATE="attest"`, `CHECKPOINT_RESULT` equal to the isolated
checkpoint result, and `ACK` from the explicit confirmation. Persist immediately.

---

## Done

**Message:**

The ServiceNow user sign-in path is configured: the Microsoft Entra app is ready,
admin consent is granted, and the ServiceNow administrator has attested the OIDC
provider and user mapping. Next we'll install and connect the ServiceNow extension
pack.

**End message.**

Rows S4.1–S4.4 are now recorded in the checklist. Return control to the
orchestrator (`SKILL.md`) to resume at the next unverified row. Stop here — the
extension-pack installation is a separate skill.
