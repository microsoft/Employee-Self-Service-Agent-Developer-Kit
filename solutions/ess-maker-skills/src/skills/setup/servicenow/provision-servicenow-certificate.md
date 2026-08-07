<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 5 — Provision ServiceNow Certificate Sign-in

Role: **App / Cloud Application Administrator** for the Microsoft Entra work, then
**ServiceNow admin** for the guided ServiceNow work. This skill configures the
ServiceNow certificate / service-account sign-in path (`authType ==
"entra_certificate"`) and owns master-checklist rows **S5.1 through S5.3**.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names, Step IDs, or
checkpoint IDs in chat.

## Certificate-key safety — path only

The certificate private key (`.pfx`) and every secret related to it are sensitive.
Never ask the operator to paste a private key, PFX contents, PFX password, client
secret, or any other secret into chat. Never write a secret to
`.local/connect/servicenow/config.json`.

Allowed durable fields are **file paths and public metadata only**:

- `certificate.certPfxPath` — path to the `.pfx` file on disk.
- `certificate.certCerPath` — path to the public `.cer` file.
- `certificate.certThumbprint` — certificate thumbprint.
- App/client IDs, object IDs, display names, tenant ID, scope GUID, and SNI
  subject.

Do **not** add `certificate.certPassword`, private-key bytes, PEM/PFX content, or
any secret field. If a password is needed while generating/exporting a PFX, keep
it in process/session memory only. If the session is interrupted, resume by
reconfirming the certificate file paths; do not recover a password from config.

---

## Checkpoints this skill drives

Canonical row text from `src/skills/setup/servicenow/tasks.md`:

- **Create the certificate sign-in apps** — Register the Entra applications for the certificate / service-account sign-in path (the OIDC resource app and the service-account app).
- **Upload the signing certificate and trust it** — Upload the signing certificate to the app and record the certificate trust (SNI subject) so ServiceNow accepts the tokens.
- **Register the ServiceNow OIDC provider and system user** — In ServiceNow, register Entra as the OIDC provider and create the integration system user. Both are ServiceNow-admin actions the kit never performs for you.

Run each checkpoint in isolation:

```
python scripts/flightcheck/cli.py --checkpoint <ID>
```

| Internal row | Checkpoint | Gate |
|--------------|------------|------|
| S5.1 | `SN-ENTRA-CERT-001` — certificate apps exist and identifiers are recorded | prog |
| S5.2 | `SN-ENTRA-CERT-001` — certificate uploaded and SNI trust recorded | prog; else attest |
| S5.3 | `SN-CONN-OIDC-001` — OIDC provider registered in ServiceNow | attest |
| S5.3 | `SN-SYSUSER-001` — ServiceNow integration system user exists | attest |

**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` (or `Warning` / `NotConfigured`) row,
its full verification steps — **before** you show any later **Message** or ask any
attestation question. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees the manual steps; never ask a user
to attest to steps they have not been shown.

## Build and resume order

On every run or resume:

1. Read `.local/connect/servicenow/config.json` and confirm `authType` is
   `"entra_certificate"`. If not, stop and return to the router; this skill is not
   applicable to the selected sign-in path.
2. Re-run **P5.0** (role gate) and **P5.0b** (config rehydrate / app lookup) first.
   Both are idempotent. Later rows need the in-memory App A / App B identifiers
   populated even when the row itself was completed in a previous session.
3. Skip any owned row whose `setupStatus` state is already `done`, except that the
   idempotent lookup in P5.0b still runs to rehydrate identifiers.
4. Persist each row immediately through
   [`shared/checklist-updater.md`](../shared/checklist-updater.md), updating
   `.local/setup/servicenow/tasks.md` and `.local/connect/servicenow/config.json`.
   Do not batch row updates at the end.

---

## P5.0 — Role gate (App / Cloud Application Administrator)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
Entra app work, with:

- `REQUIRED_ROLE` = `"Application Administrator"` (or Cloud Application
  Administrator / Privileged Role Administrator / Global Administrator / app owner)
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S5.1"`
- `ROLE_QUERY` = a Microsoft Graph directory-role membership check for the
  signed-in user:

  ```
  az rest --method GET --url "https://graph.microsoft.com/v1.0/me/memberOf?%24select=displayName" --query "value[].displayName" -o json
  ```

  The role is held if the returned role names include **Application
  Administrator**, **Cloud Application Administrator**, **Privileged Role
  Administrator**, or **Global Administrator**. Treat an `Insufficient privileges`,
  `Authorization_RequestDenied`, or forbidden response as "role not held". If the
  query errors for an unrelated reason (network, not signed in), follow the gate's
  retry-then-attest fallback — never assume pass.

If `GATE_RESULT` is `"stop"`:

- If `GATE_REASON` is `"delegated"` (the maker can't hold the role but another
  administrator will do the Entra work), **do not halt** — go to **P5.0a** and hand
  that administrator the full certificate-app runbook, then resume on the
  Application (client) IDs they return.
- For any other `"stop"` reason, **halt**.

Otherwise carry `GATE_EVIDENCE` forward;
it is recorded when S5.1 and S5.2 are updated.

---

## P5.0a — Delegated administrator runbook (certificate apps)

Reached only when the P5.0 gate returned `GATE_RESULT="stop"` with
`GATE_REASON="delegated"`: the maker lacks the Entra role, so a consent-capable
administrator registers the two certificate apps and uploads the signing
certificate, then hands the maker back the resulting **Application (client) IDs**.

The signing certificate's **private key** never leaves the maker's machine. Before
handing off, make sure the public `.cer` exists to give the administrator — run
**P5.2a** now if needed to generate/locate it (the maker keeps the `.pfx`; only the
public `.cer` goes to the admin). Substitute the deterministic display names so
P5.0b later rehydrates the same apps:

- App A: `ESS Copilot - ServiceNow Certificate ({INSTANCE_NAME})`
- App B: `ESS Copilot - ServiceNow Service Account ({INSTANCE_NAME})`

**Message:**

You don't need the admin role yourself — an administrator with **Application
Administrator**, **Cloud Application Administrator**, **Privileged Role
Administrator**, or **Global Administrator** can register the certificate apps
once. Send them these steps (all in https://entra.microsoft.com), plus the public
`.cer` signing-certificate file I prepared:

**App A — the ServiceNow resource app**
1. **App registrations → New registration.** Name it
   `ESS Copilot - ServiceNow Certificate ({INSTANCE_NAME})`, **Accounts in this
   organizational directory only**, register. Copy its **Application (client) ID**.
2. **Expose an API** — set the Application ID URI to
   `api://<App A Application client ID>`, then **Add a scope** named
   `user_impersonation`.
3. **Expose an API → Add a client application** — add the Power Platform
   ServiceNow connector client ID `c26b24aa-7874-4e06-ad55-7d06b1f79b63` and
   authorize it for `user_impersonation`.
4. **Token configuration → Add optional claim → Access** — add **aud**, **email**,
   and **upn**.

**App B — the service-account app**
5. **App registrations → New registration.** Name it
   `ESS Copilot - ServiceNow Service Account ({INSTANCE_NAME})`, same account type,
   register. Copy its **Application (client) ID**.
6. **Certificates & secrets → Certificates → Upload certificate** — upload the
   public `.cer` file I provided (no private key, no password).
7. If any added permission needs it, **API permissions → Grant admin consent for
   your tenant**.

When both apps exist and the certificate is uploaded, paste the two **Application
(client) IDs** here and I'll verify and continue.

**End message.**

Collect the two identifiers with the `vscode_askQuestions` tool:

```json
[
  {
    "header": "ServiceNow resource app (App A)",
    "question": "Paste App A's Application (client) ID (the 'ESS Copilot - ServiceNow Certificate' app).",
    "allowFreeformInput": true
  },
  {
    "header": "Service-account app (App B)",
    "question": "Paste App B's Application (client) ID (the 'ESS Copilot - ServiceNow Service Account' app).",
    "allowFreeformInput": true
  }
]
```

- If either ID is missing (empty / "not yet"), stop here — the administrator hasn't
  finished. The maker can resume later; on resume P5.0 runs again.
- On GUID-shaped answers, **persist** to `.local/connect/servicenow/config.json`
  (merge): `certificate.appAClientId` = App A's ID and `certificate.appBClientId` =
  App B's ID. Record `GATE_EVIDENCE = { "verifiedBy": "attested", "note":
  "certificate apps created by delegated admin; App A/App B client IDs supplied by
  maker for S5.1/S5.2" }`.

Then continue to **P5.0b**, which re-resolves each app's object ID, scope GUID, and
App B's service-principal object ID (`certificate.appBSpObjectId`) from those client
IDs and the display names, and run P5.1c's `SN-ENTRA-CERT-001` verification as
usual. `SN-ENTRA-CERT-001` is a read-only Graph query the maker can run without the
admin role; if it can't be read (`MANUAL` / permission error), fall back to the
checklist-updater §U.2 attestation using this delegated-admin handoff as evidence —
never silently mark the row `done`.

---

## P5.0b — Rehydrate config and app identifiers

Read `.local/connect/servicenow/config.json` (merge on every write; never drop
existing fields). Use these values:

- `instanceName` or parse it from `instanceUrl` / `baseUrl` for display-name
  suffixes.
- `tenantId`, if present; otherwise run:

  ```
  az account show --query tenantId -o tsv
  ```

  Save it to `certificate.tenantId`.
- Existing `certificate.*` fields, if present.

Set the deterministic display names:

- App A: `ESS Copilot - ServiceNow Certificate ({INSTANCE_NAME})`
- App B: `ESS Copilot - ServiceNow Service Account ({INSTANCE_NAME})`

Idempotently rehydrate App A and App B:

```
az ad app list --display-name "ESS Copilot - ServiceNow Certificate ({INSTANCE_NAME})" --query "[0].{appId:appId,id:id,displayName:displayName}" -o json
az ad app list --display-name "ESS Copilot - ServiceNow Service Account ({INSTANCE_NAME})" --query "[0].{appId:appId,id:id,displayName:displayName}" -o json
```

Persist `certificate.appBSpObjectId` with the returned service-principal object
ID. This ID is later shown to the ServiceNow admin as the User ID for the system
user.

Also persist App B's application identifiers from the rehydrate query above so a
re-run resolves the same app without recreating it:

- `certificate.appBObjectId` — App B's application object ID (the `id` field).
- `certificate.appBClientId` — App B's application (client) ID (the `appId`
  field).

---

## P5.1 — Create the certificate sign-in apps

Row title in the checklist: **Create the certificate sign-in apps**. Register App
A and App B, then persist their identifiers under the top-level `certificate`
object in `.local/connect/servicenow/config.json`.

### P5.1a — Ensure App A (OIDC resource app)

If P5.0b found App A, use it. Otherwise create it:

**Message:**

I'll create the Microsoft Entra app that represents ServiceNow for the certificate
sign-in path. This app exposes the permission that the Power Platform ServiceNow
connector uses.

**End message.**

```
az ad app create --display-name "ESS Copilot - ServiceNow Certificate ({INSTANCE_NAME})" --sign-in-audience AzureADMyOrg --query "{appId:appId,id:id}" -o json
```

Configure App A like the ServiceNow OIDC resource app from
`connect/azure/app-registration.md`:

1. Set the Application ID URI to `api://{APP_A_CLIENT_ID}`.
2. Expose a `user_impersonation` delegated scope and save its GUID to
   `certificate.scopeGuid`.
3. Pre-authorize the Power Platform **ServiceNow** connector application ID
   `c26b24aa-7874-4e06-ad55-7d06b1f79b63` for that scope.
4. Add access-token optional claims `aud`, `email`, and `upn`.


**Message:**

I couldn't finish configuring the ServiceNow certificate resource app
automatically. Open https://entra.microsoft.com → **App registrations** → the
ServiceNow certificate app, then make these updates:

1. **Expose an API**: set the Application ID URI to `api://<Application client ID>`.
2. Add the delegated scope **user_impersonation**.
3. Under **Authorized client applications**, add the Power Platform ServiceNow
   connector and authorize it for that scope.
4. Under **Token configuration**, add access-token optional claims **aud**,
   **email**, and **upn**.

Tell me when that's done and I'll verify it.

**End message.**


### P5.1b — Ensure App B (service-account app)

If P5.0b found App B, use it. Otherwise create it:

**Message:**

I'll create the second Microsoft Entra app for the ServiceNow service account.
This app holds the certificate credential and is the client identity used by the
connector.

**End message.**

```
az ad app create --display-name "ESS Copilot - ServiceNow Service Account ({INSTANCE_NAME})" --sign-in-audience AzureADMyOrg --query "{appId:appId,id:id}" -o json
```

Persist App B's identifiers so later checks and steps can resolve it:

- `certificate.appBObjectId` — App B's **application object ID** (the `id`
  field). `SN-ENTRA-CERT-001` reads this to fetch App B's `keyCredentials` and
  verify the certificate is uploaded.
- `certificate.appBClientId` — App B's **application (client) ID** (the `appId`
  field), used as a fallback resolver and for the connector binding.

Do not confuse these with `certificate.appBSpObjectId` (the service-principal
object ID persisted in P5.0b) — that is a different identifier.

### P5.1c — Verify and record S5.1

**Message:**

Now I'll verify the certificate sign-in apps are registered and discoverable.

**End message.**

Run:

```
python scripts/flightcheck/cli.py --checkpoint SN-ENTRA-CERT-001
```

Immediately show the checkpoint result per the checklist-updater §U.0–U.0a.
Then update **S5.1** via [`shared/checklist-updater.md`](../shared/checklist-updater.md)
with:

- `STEP_ID="S5.1"`
- `GATE="prog"`
- `CHECKPOINT_RESULT` = the checkpoint status
- `ACK=false`
- Persist `GATE_EVIDENCE` from P5.0

If the result is not `PASSED` only because the certificate is not uploaded or SNI
trust is not recorded yet, continue to P5.2. The same checkpoint is run again
after P5.2; when it passes, update S5.1 again if it is still not `done`.

---

## P5.2 — Upload the signing certificate and trust it

Row title in the checklist: **Upload the signing certificate and trust it**.
Generate or reference the signing certificate, upload the public `.cer` to App B,
and patch App B's SNI trust. The private key stays on disk and is referenced only
by file path.

### P5.2a — Locate or generate certificate files

If `certificate.certPfxPath`, `certificate.certCerPath`, and
`certificate.certThumbprint` already exist in config and the files still exist on
disk, reuse them. Otherwise ask for the non-secret path choice:

```json
[
  {
    "header": "Certificate",
    "question": "Do you already have certificate files for the ServiceNow service account, or should I generate a self-signed certificate for a dev/test setup?",
    "options": [
      { "label": "Generate self-signed certificate", "description": "Creates local .pfx and .cer files for dev/test", "recommended": true },
      { "label": "I already have certificate files", "description": "Use existing .pfx and .cer files by path" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chooses generation**, create files under `.local/connect/servicenow/`
(not a temp directory). Use a subject that identifies the instance, export both
`.pfx` and `.cer`, compute the thumbprint, and remove the certificate from the
current-user store after export. Keep any PFX password in session memory only;
never print it in chat and never write it to config.

Use PowerShell to create `.local\connect\servicenow`, create a self-signed
certificate in `Cert:\CurrentUser\My`, export `.pfx` and `.cer` files under that
folder, compute `$cert.Thumbprint`, and remove the certificate from the store.
Hold any PFX password as a `SecureString` in memory only; do not print it.

**Message:**

The certificate files are ready. I saved only the file paths and public
thumbprint. The private key stays in the `.pfx` file on disk and is not stored in
the setup config.

**End message.**

**If the user has existing files**, ask only for paths, not passwords or file
contents:

```json
[
  {
    "header": "PFX path",
    "question": "What's the full path to the .pfx file on this machine?",
    "allowFreeformInput": true
  },
  {
    "header": "CER path",
    "question": "What's the full path to the public .cer file? Leave blank if I should export it from the .pfx during this session without saving any secret to config.",
    "allowFreeformInput": true
  }
]
```

If the `.cer` path is blank, export the public certificate from the `.pfx` during
this session. Do not ask for or echo the PFX password in chat; use only a secure
local mechanism available to the host environment. If no secure mechanism is
available, stop and ask the operator to export the `.cer` with their certificate
tooling, then resume with the `.cer` file path.

Persist only:

- `certificate.certPfxPath`
- `certificate.certCerPath`
- `certificate.certThumbprint`

### P5.2b — Upload the public certificate to App B

Upload the `.cer` to App B's `keyCredentials`. The upload uses only the public
certificate:

```powershell
$cerBytes = [System.IO.File]::ReadAllBytes("{CERT_CER_PATH}")
$base64 = [System.Convert]::ToBase64String($cerBytes)
$body = @{keyCredentials=@(@{
  displayName="ESS Copilot Certificate"
  type="AsymmetricX509Cert"
  usage="Verify"
  key=$base64
})} | ConvertTo-Json -Depth 6
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_B_OBJECT_ID}" --headers "Content-Type=application/json" --body $body
```

Verify:

```
az ad app credential list --id {APP_B_OBJECT_ID} --cert --query "[?displayName=='ESS Copilot Certificate'].{keyId:keyId,displayName:displayName}" -o json
```

If upload or verification fails, retry once. If it still fails, show the portal
fallback:

**Message:**

I couldn't upload the public certificate automatically. Open
https://entra.microsoft.com → **App registrations** → the ServiceNow service
account app → **Certificates & secrets** → **Certificates** → **Upload
certificate**, then select the `.cer` file and add it. Tell me when it's uploaded
and I'll verify it.

**End message.**

After the user confirms, re-run the credential-list verification.

### P5.2c — Patch App B SNI trust

Certificate SNI authentication also requires App B's manifest to trust the
certificate subject. Compute the certificate subject from the public `.cer`, patch
`trustedCertificateSubjects`, and persist the subject for later checks:

```powershell
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2("{CERT_CER_PATH}")
$subject = $cert.Subject
$authorityId = [System.Guid]::Empty.ToString()
$body = @{ trustedCertificateSubjects = @(@{ authorityId = $authorityId; subjectName = $subject; revokedCertificateIdentifiers = @() }) } | ConvertTo-Json -Depth 8
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{APP_B_OBJECT_ID}" --headers "Content-Type=application/json" --body $body
```

Verify:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/applications/{APP_B_OBJECT_ID}?%24select=trustedCertificateSubjects" -o json
```

Expected: a non-empty `trustedCertificateSubjects` array whose `subjectName`
matches the certificate subject. Save the subject to
`certificate.trustedCertificateSubject`.

If the manifest PATCH fails, use the portal fallback and then verify again:

**Message:**

I couldn't update the service account app manifest automatically. Open
https://entra.microsoft.com → **App registrations** → the ServiceNow service
account app → **Manifest**, then add a `trustedCertificateSubjects` entry for the
certificate subject shown in the Entra certificate details. Tell me when it's
saved and I'll verify the trust.

**End message.**

### P5.2d — Verify and record S5.2

**Message:**

Now I'll verify the certificate upload and trust settings for the ServiceNow
service account app.

**End message.**

Run:

```
python scripts/flightcheck/cli.py --checkpoint SN-ENTRA-CERT-001
```

Immediately show the checkpoint result per the checklist-updater §U.0–U.0a.
Then:

- If `PASSED`, update **S5.1** if it is not already `done`, then update **S5.2**
  with `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`, `ACK=false`, and the P5.0
  `GATE_EVIDENCE`.
- If `FAILED`, redo the missing upload/trust action named by the result and re-run
  the checkpoint. Keep S5.2 `in-progress` or `blocked` per the updater.
- If the check cannot programmatically prove SNI trust but the Entra portal shows
  the certificate and trusted subject are correct, show the checkpoint output first,
  require explicit acknowledgement, and update **S5.2** with `GATE="attest"`,
  `ACK=true`, and evidence noting that the operator confirmed the certificate
  upload and trusted subject in Entra. Never mark S5.2 `done` without either a
  passing checkpoint or that explicit attestation.

---

## P5.3 — Register the ServiceNow OIDC provider and system user

Row title in the checklist: **Register the ServiceNow OIDC provider and system
user**. This is a ServiceNow-admin section. The spec requires **guided manual +
attestation only**: the agent must **never** automate ServiceNow OIDC provider
registration, OIDC provider configuration, claim mapping, linking, or system-user
creation. Do not call ServiceNow table APIs, MCP tools, scripts, or browser
automation to perform these actions.

### P5.3a — ServiceNow admin attested role gate

Apply [`permission-gate.md`](../shared/permission-gate.md) with:

- `REQUIRED_ROLE` = `"ServiceNow admin with security_admin elevation"`
- `GATE_MODE` = `"attested"`
- `STEP_ID` = `"S5.3"`

If `GATE_RESULT` is `"stop"`, halt. This gate only confirms the role claim; it
does not complete the row.

### P5.3b — Guide OIDC provider registration

Before asking the operator to attest, show the current checkpoint state:

```
python scripts/flightcheck/cli.py --checkpoint SN-CONN-OIDC-001
```

Immediately render §U.0–U.0a output. Then guide the admin:

**Message:**

Now a ServiceNow admin needs to register Microsoft Entra as the OIDC provider in
ServiceNow. I won't make ServiceNow changes for you.

In ServiceNow, elevate your role to **security_admin**, then open **System OAuth**
→ **Application Registry** → **New** → **Configure an OIDC provider to verify ID
tokens**.

Use these values:

- **Name**: `Microsoft Entra ID - ESS Copilot Certificate`
- **Client ID**: the ServiceNow certificate resource app's Application (client) ID
- **Client Secret**: `not-used` if the form requires a non-empty value
- **OIDC Metadata URL**: `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`

Create or select a certificate-specific OIDC provider configuration that maps
**User claim** `oid` to **User field** `User ID`. Do not overwrite an existing
user sign-in configuration that maps `upn` to `user_name` unless your ServiceNow
admin intentionally accepts that impact.

Tell me when the OIDC provider and claim mapping are complete.

**End message.**

Do not proceed on implied completion. Wait for an explicit user response, then use
the checklist-updater attestation question flow if needed. Completion of this
sub-part is evidence for `SN-CONN-OIDC-001` only; S5.3 is not done until the
system-user evidence is also captured.

### P5.3c — Guide ServiceNow system-user creation

First, show the current system-user checkpoint state:

```
python scripts/flightcheck/cli.py --checkpoint SN-SYSUSER-001
```

Immediately render §U.0–U.0a output. Then guide the admin:

**Message:**

Now create or verify the ServiceNow integration system user for the certificate
service account. I won't create the user automatically.

In ServiceNow, open **User Administration** → **Users** → **New User** and use:

- **User ID**: the service account app's service-principal object ID
- **First name**: `ESS Copilot`
- **Last name**: `Service Account`
- **Active**: checked
- **Web service access only**: checked

Tell me when the user exists with those values.

**End message.**

The **User ID** must be App B's **service-principal object ID**
(`certificate.appBSpObjectId`), not App B's application/client ID and not the app
registration object ID.

### P5.3d — Record S5.3 attestation evidence

After the operator explicitly confirms both ServiceNow tasks are complete, record
the row through [`shared/checklist-updater.md`](../shared/checklist-updater.md):

- `STEP_ID="S5.3"`
- `GATE="attest"`
- `CHECKPOINT_RESULT` = the latest result from `SN-SYSUSER-001` if that was the
  last isolated checkpoint shown; otherwise use `MANUAL` / `null` per updater
  inputs and preserve the displayed checkpoint evidence in the note.
- `ACK=true` only after explicit confirmation.
- `verifiedBy="attested"`
- Evidence note must state that the ServiceNow admin attested:
  - OIDC provider registered for the Entra tenant and App A client ID.
  - Certificate claim mapping is `oid` → `User ID`.
  - ServiceNow system user exists with User ID equal to App B service-principal
    object ID and **Web service access only** checked.

If the operator says the ServiceNow work is not complete, update S5.3 as
`in-progress` with `ACK=false` and stop. The router will resume here later.

---

## Done

When S5.1, S5.2, and S5.3 are `done`, return to the ServiceNow setup router. Do
not display internal identifiers. It is safe to summarize only the non-secret
connection values that later setup needs: authentication type, instance name,
tenant ID, App B client ID, App A client ID/resource URI, and the `.pfx` file
path. Never display the private key, PFX contents, or any password.
